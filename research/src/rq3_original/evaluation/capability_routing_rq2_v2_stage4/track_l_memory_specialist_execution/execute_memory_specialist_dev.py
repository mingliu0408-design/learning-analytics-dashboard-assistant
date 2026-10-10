"""Prepare and execute the frozen RQ2-V2 Stage 4L Memory DEV run."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Sequence

from .memory_specialist_common import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    CLIENT_MAX_RETRIES,
    DYNAMIC_OUTPUT_PATHS,
    ExecutionBoundaryError,
    LOGICAL_CALL_CEILING,
    MAX_OUTPUT_TOKENS,
    MIN_INITIAL_REQUEST_DELAY_SECONDS,
    PHYSICAL_ATTEMPT_CEILING,
    SOURCE_VERIFICATION_PATH,
    TARGET_FIELD,
    TERMINAL_RESULTS_PATH,
    append_jsonl_fsync,
    build_manifest_v2,
    canonical_sha256,
    load_json,
    sanitize_provider_text,
    utc_now,
    validate_response_content,
    verify_frozen_sources,
    verify_git_boundary,
    verify_manifest_v2,
    write_pre_execution_source_verification,
)


FIRST_CALL_FATAL_CATEGORIES = {
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "REQUEST_CONFIGURATION_ERROR",
    "MODEL_OR_ENDPOINT_NOT_FOUND",
}
GLOBAL_INTEGRITY_ERROR_CATEGORIES = {
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "MODEL_OR_ENDPOINT_NOT_FOUND",
}


class InitialRequestPacer:
    """Enforce the minimum gap between attempt-one provider dispatches."""

    def __init__(
        self,
        *,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._last_initial_start: float | None = None

    def before_initial_request(self) -> tuple[float, float | None]:
        slept = 0.0
        if self._last_initial_start is not None:
            while True:
                elapsed = self._time_fn() - self._last_initial_start
                remaining = MIN_INITIAL_REQUEST_DELAY_SECONDS - elapsed
                if remaining <= 0:
                    break
                self._sleep_fn(remaining)
                slept += remaining
        started = self._time_fn()
        interval = (
            None
            if self._last_initial_start is None
            else started - self._last_initial_start
        )
        if interval is not None and interval < MIN_INITIAL_REQUEST_DELAY_SECONDS:
            raise ExecutionBoundaryError("Initial-request pacing boundary was not met")
        self._last_initial_start = started
        return slept, interval


def create_client() -> Any:
    from openai import OpenAI

    client = OpenAI(max_retries=CLIENT_MAX_RETRIES)
    if getattr(client, "max_retries", None) != CLIENT_MAX_RETRIES:
        raise ExecutionBoundaryError("OpenAI client max_retries is not zero")
    return client


def _provider_body(error: BaseException) -> Mapping[str, Any]:
    body = getattr(error, "body", None)
    if not isinstance(body, Mapping):
        return {}
    nested = body.get("error")
    return nested if isinstance(nested, Mapping) else body


def _request_id(error: BaseException) -> str | None:
    direct = getattr(error, "request_id", None)
    if direct:
        return sanitize_provider_text(direct)
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("x-request-id") or headers.get("X-Request-ID")
    except Exception:
        value = None
    return sanitize_provider_text(value) if value else None


def classify_provider_error(error: BaseException) -> str:
    error_type = type(error).__name__
    status = getattr(error, "status_code", None)
    if error_type == "AuthenticationError" or status == 401:
        return "AUTHENTICATION_ERROR"
    if error_type == "PermissionDeniedError" or status == 403:
        return "PERMISSION_ERROR"
    if error_type == "BadRequestError" or status == 400:
        return "REQUEST_CONFIGURATION_ERROR"
    if error_type == "NotFoundError" or status == 404:
        return "MODEL_OR_ENDPOINT_NOT_FOUND"
    if error_type == "RateLimitError" or status == 429:
        return "RATE_LIMIT_ERROR"
    if error_type in {"APIConnectionError", "APITimeoutError", "TimeoutError"}:
        return "TRANSPORT_ERROR"
    return "PROVIDER_ERROR"


def safe_provider_error(error: BaseException) -> dict[str, Any]:
    body = _provider_body(error)
    message = body.get("message")
    if message is None:
        message = getattr(error, "message", None)
    if message is None:
        message = str(error)
    return {
        "exception_type": type(error).__name__,
        "http_status": getattr(error, "status_code", None),
        "provider_error_code": sanitize_provider_text(body.get("code")),
        "provider_error_param": sanitize_provider_text(body.get("param")),
        "provider_request_id": _request_id(error),
        "sanitized_error_message": sanitize_provider_text(message),
        "category": classify_provider_error(error),
        "request_headers_recorded": False,
        "authorization_headers_recorded": False,
    }


def _usage_values(response: Any) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
    )


def prepare() -> dict[str, Any]:
    verify_git_boundary(require_clean=False)
    if any(path.exists() for path in DYNAMIC_OUTPUT_PATHS):
        existing = [path.name for path in DYNAMIC_OUTPUT_PATHS if path.exists()]
        raise ExecutionBoundaryError(
            f"Execution or derived output already exists: {', '.join(existing)}"
        )
    frozen = verify_frozen_sources()
    records, diff = build_manifest_v2()
    write_pre_execution_source_verification(frozen)
    return {
        "status": "PASS_AUTHORIZED_MANIFEST_V2_PREPARED",
        "provider_calls": 0,
        "logical_call_count": len(records),
        "v2_manifest_sha256": diff["v2_manifest_sha256"],
        "frozen_k0_file_count": frozen["k0_file_count"],
        "source_verification_path": SOURCE_VERIFICATION_PATH.name,
    }


def verify_pre_http_boundaries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verify_git_boundary(require_clean=False)
    current_sources = verify_frozen_sources()
    if not SOURCE_VERIFICATION_PATH.is_file():
        raise ExecutionBoundaryError("Pre-execution frozen-source record is missing")
    source_report = load_json(SOURCE_VERIFICATION_PATH)
    if source_report.get("pre_execution") != current_sources:
        raise ExecutionBoundaryError("Pre-execution source identities no longer match")
    records, diff_report = verify_manifest_v2()
    if not os.environ.get("OPENAI_API_KEY"):
        raise ExecutionBoundaryError("OPENAI_API_KEY is missing or empty")
    for path in DYNAMIC_OUTPUT_PATHS:
        if path.exists():
            raise ExecutionBoundaryError(f"Execution output already exists: {path.name}")
    client = create_client()
    del client
    return records, diff_report


def _one_physical_attempt(
    client: Any,
    manifest_record: Mapping[str, Any],
    attempt_number: int,
    physical_attempt_number: int,
    pacer: InitialRequestPacer,
) -> tuple[dict[str, Any], str]:
    if physical_attempt_number > PHYSICAL_ATTEMPT_CEILING:
        raise ExecutionBoundaryError("Physical-attempt ceiling would be exceeded")
    payload = manifest_record["provider_facing_request"]
    request_hash = canonical_sha256(payload)
    if request_hash != manifest_record["provider_facing_request_sha256"]:
        raise ExecutionBoundaryError("Provider request differs from authorized V2 hash")
    physical_attempt_id = f"R2V2-MEMORY-STAGE4L-PHYS-{physical_attempt_number:04d}"
    reservation = {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-call-journal-v1",
        "event": "ATTEMPT_RESERVED",
        "physical_attempt_id": physical_attempt_id,
        "physical_attempt_number": physical_attempt_number,
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold"],
        "attempt_number": attempt_number,
        "request_sha256": request_hash,
        "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
        "reserved_at": utc_now(),
    }
    append_jsonl_fsync(CALL_JOURNAL_PATH, reservation)

    pacing_sleep = 0.0
    seconds_since_prior_initial: float | None = None
    if attempt_number == 1:
        pacing_sleep, seconds_since_prior_initial = pacer.before_initial_request()
    started_at = utc_now()
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**payload)
    except Exception as error:
        latency = time.perf_counter() - started
        provider_error = safe_provider_error(error)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-l-memory-specialist-attempt-record-v1",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold"],
            "attempt_number": attempt_number,
            "request_sha256": request_hash,
            "response_id": None,
            "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": None,
            "system_fingerprint": None,
            "finish_reason": None,
            "raw_structured_content": None,
            "parsed_json": None,
            "schema_validation": {"valid": False, "error": "PROVIDER_ERROR"},
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "latency_seconds": round(latency, 6),
            "initial_request_pacing_sleep_seconds": round(pacing_sleep, 9),
            "seconds_since_prior_initial_request_start": (
                None
                if seconds_since_prior_initial is None
                else round(seconds_since_prior_initial, 9)
            ),
            "provider_error": provider_error,
            "started_at": started_at,
            "completed_at": utc_now(),
        }
        outcome = "PROVIDER_ERROR"
    else:
        latency = time.perf_counter() - started
        choices = list(getattr(response, "choices", []) or [])
        if choices:
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            message = getattr(choice, "message", None)
            content = str(getattr(message, "content", "") or "")
            refusal = getattr(message, "refusal", None)
        else:
            finish_reason = None
            content = ""
            refusal = None
        returned_model = str(getattr(response, "model", "") or "") or None
        parsed, schema_valid, schema_error = validate_response_content(content)
        provider_error: dict[str, Any] | None = None
        if returned_model != AUTHORIZED_MODEL_SNAPSHOT:
            outcome = "RETURNED_MODEL_MISMATCH"
            schema_valid = False
            schema_error = "RETURNED_MODEL_MISMATCH"
            provider_error = {
                "exception_type": "ReturnedModelMismatch",
                "http_status": None,
                "provider_error_code": None,
                "provider_error_param": None,
                "provider_request_id": None,
                "sanitized_error_message": (
                    "Returned model identity did not equal the authorized snapshot."
                ),
                "category": "MODEL_OR_ENDPOINT_NOT_FOUND",
                "request_headers_recorded": False,
                "authorization_headers_recorded": False,
            }
        elif refusal:
            outcome = "PROVIDER_REFUSAL"
            schema_valid = False
            schema_error = "PROVIDER_REFUSAL"
            provider_error = {
                "exception_type": "ProviderRefusal",
                "http_status": None,
                "provider_error_code": None,
                "provider_error_param": None,
                "provider_request_id": None,
                "sanitized_error_message": sanitize_provider_text(refusal),
                "category": "PROVIDER_ERROR",
                "request_headers_recorded": False,
                "authorization_headers_recorded": False,
            }
        elif schema_valid:
            outcome = "VALID_PREDICTION"
        else:
            outcome = "INVALID_STRUCTURED_OUTPUT"
        input_tokens, output_tokens, total_tokens = _usage_values(response)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-l-memory-specialist-attempt-record-v1",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold"],
            "attempt_number": attempt_number,
            "request_sha256": request_hash,
            "response_id": str(getattr(response, "id", "") or "") or None,
            "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": returned_model,
            "system_fingerprint": getattr(response, "system_fingerprint", None),
            "finish_reason": finish_reason,
            "raw_structured_content": content,
            "parsed_json": parsed,
            "schema_validation": {"valid": schema_valid, "error": schema_error},
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_seconds": round(latency, 6),
            "initial_request_pacing_sleep_seconds": round(pacing_sleep, 9),
            "seconds_since_prior_initial_request_start": (
                None
                if seconds_since_prior_initial is None
                else round(seconds_since_prior_initial, 9)
            ),
            "provider_error": provider_error,
            "started_at": started_at,
            "completed_at": utc_now(),
        }

    append_jsonl_fsync(ATTEMPT_RECORDS_PATH, attempt_record)
    completion = {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-call-journal-v1",
        "event": "ATTEMPT_COMPLETED",
        "physical_attempt_id": physical_attempt_id,
        "physical_attempt_number": physical_attempt_number,
        "logical_call_id": manifest_record["logical_call_id"],
        "attempt_number": attempt_number,
        "request_sha256": request_hash,
        "outcome": outcome,
        "attempt_record_sha256": canonical_sha256(attempt_record),
        "completed_at": utc_now(),
    }
    append_jsonl_fsync(CALL_JOURNAL_PATH, completion)
    return attempt_record, outcome


def _terminal_result(
    manifest_record: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    terminal_status: str,
) -> dict[str, Any]:
    final = attempts[-1]
    prediction = (
        {TARGET_FIELD: final["parsed_json"][TARGET_FIELD]}
        if terminal_status == "VALID_PREDICTION"
        else None
    )
    return {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-terminal-result-v1",
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold"],
        "terminal_status": terminal_status,
        "prediction": prediction,
        "attempts_used": len(attempts),
        "request_sha256": final["request_sha256"],
        "response_id": final["response_id"],
        "requested_model": final["requested_model"],
        "returned_model": final["returned_model"],
        "schema_valid": final["schema_validation"]["valid"],
        "provider_error": final["provider_error"],
        "completed_at": utc_now(),
    }


def stop_reason_for_terminal(
    logical_result_count: int, terminal: Mapping[str, Any]
) -> str | None:
    category = (terminal.get("provider_error") or {}).get("category")
    if logical_result_count == 1 and category in FIRST_CALL_FATAL_CATEGORIES:
        return f"FIRST_LOGICAL_CALL_{category}"
    if category in GLOBAL_INTEGRITY_ERROR_CATEGORIES:
        return f"EXECUTION_INTEGRITY_{category}"
    if terminal.get("terminal_status") == "RETURNED_MODEL_MISMATCH":
        return "EXECUTION_INTEGRITY_RETURNED_MODEL_MISMATCH"
    return None


def execute() -> dict[str, Any]:
    manifest_records, diff_report = verify_pre_http_boundaries()
    client = create_client()
    pacer = InitialRequestPacer()
    physical_attempts = 0
    logical_results = 0
    retries = 0
    stop_reason: str | None = None

    for manifest_record in manifest_records:
        logical_attempts: list[dict[str, Any]] = []
        terminal_status = "PROVIDER_ERROR"
        for attempt_number in (1, 2):
            physical_attempts += 1
            if physical_attempts > PHYSICAL_ATTEMPT_CEILING:
                raise ExecutionBoundaryError("Physical-attempt ceiling exceeded")
            attempt_record, outcome = _one_physical_attempt(
                client,
                manifest_record,
                attempt_number,
                physical_attempts,
                pacer,
            )
            logical_attempts.append(attempt_record)
            if outcome == "VALID_PREDICTION":
                terminal_status = outcome
                break
            if outcome == "INVALID_STRUCTURED_OUTPUT" and attempt_number == 1:
                retries += 1
                continue
            terminal_status = outcome
            break

        terminal = _terminal_result(
            manifest_record,
            logical_attempts,
            terminal_status,
        )
        append_jsonl_fsync(TERMINAL_RESULTS_PATH, terminal)
        logical_results += 1
        stop_reason = stop_reason_for_terminal(logical_results, terminal)
        if stop_reason:
            break
        if logical_results % 8 == 0:
            print(
                f"Memory Specialist progress: {logical_results}/64 logical, "
                f"{physical_attempts}/128 physical, {retries} retries",
                flush=True,
            )

    from .finalize_memory_specialist_dev import finalize

    summary = finalize(
        stop_reason=stop_reason,
        manifest_diff_report=diff_report,
        track_l_test_count=None,
        k0_test_count=None,
    )
    if stop_reason:
        raise ExecutionBoundaryError(stop_reason)
    if logical_results != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError(
            f"Execution ended with {logical_results} logical results instead of 64"
        )
    return summary


def runtime_summary() -> dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "openai_sdk_version": importlib.metadata.version("openai"),
        "client_max_retries": CLIENT_MAX_RETRIES,
        "streaming": False,
        "model_snapshot": AUTHORIZED_MODEL_SNAPSHOT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "minimum_initial_request_delay_seconds": MIN_INITIAL_REQUEST_DELAY_SECONDS,
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "preflight", "execute", "finalize")
    )
    parser.add_argument("--track-l-test-count", type=int)
    parser.add_argument("--k0-test-count", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "preflight":
        records, diff = verify_pre_http_boundaries()
        result = {
            "status": "PASS_PRE_HTTP_BOUNDARIES",
            "logical_call_count": len(records),
            "v2_manifest_sha256": diff["v2_manifest_sha256"],
            **runtime_summary(),
        }
    elif args.command == "execute":
        if args.track_l_test_count is not None or args.k0_test_count is not None:
            raise ExecutionBoundaryError("Test counts are not accepted by execute")
        result = execute()
    else:
        from .finalize_memory_specialist_dev import finalize

        result = finalize(
            stop_reason=None,
            manifest_diff_report=None,
            track_l_test_count=args.track_l_test_count,
            k0_test_count=args.k0_test_count,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
