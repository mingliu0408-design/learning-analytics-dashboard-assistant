"""Execute the frozen Stage 4K RAG Specialist DEV manifest serially."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from .rag_specialist_protocol import (
    ATTEMPT_RECORDS_PATH,
    AUTHORIZED_MODEL_SNAPSHOT,
    CALL_JOURNAL_PATH,
    CLIENT_MAX_RETRIES,
    ExecutionBoundaryError,
    LOGICAL_CALL_CEILING,
    MIN_INITIAL_REQUEST_INTERVAL_SECONDS,
    PHYSICAL_ATTEMPT_CEILING,
    TERMINAL_RESULTS_PATH,
    append_jsonl_fsync,
    canonical_sha256,
    prepare_authorized_manifest,
    runtime_summary,
    sanitize_provider_text,
    should_retry,
    utc_now,
    validate_response_content,
    verify_pre_http_boundaries,
)


FIRST_CALL_FATAL_CATEGORIES = {
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "REQUEST_CONFIGURATION_ERROR",
    "MODEL_OR_ENDPOINT_ERROR",
}
INTEGRITY_FAILURE_CATEGORIES = FIRST_CALL_FATAL_CATEGORIES


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
    if headers is not None:
        try:
            value = headers.get("x-request-id") or headers.get("X-Request-ID")
        except Exception:
            value = None
        if value:
            return sanitize_provider_text(value)
    return None


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
        return "MODEL_OR_ENDPOINT_ERROR"
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
        "raw_exception_recorded": False,
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


def _one_physical_attempt(
    client: Any,
    manifest_record: Mapping[str, Any],
    attempt_number: int,
    physical_attempt_number: int,
    initial_request_interval_seconds: float | None,
) -> tuple[dict[str, Any], str, float]:
    if physical_attempt_number > PHYSICAL_ATTEMPT_CEILING:
        raise ExecutionBoundaryError("Physical-attempt ceiling would be exceeded")
    payload = manifest_record["provider_facing_request"]
    request_hash = canonical_sha256(payload)
    if request_hash != manifest_record["provider_facing_request_sha256"]:
        raise ExecutionBoundaryError("Provider payload changed before HTTP")
    physical_attempt_id = (
        f"R2V2-RAG-SPECIALIST-PHYS-{physical_attempt_number:04d}"
    )
    reservation = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-call-journal-v1",
        "event": "ATTEMPT_RESERVED",
        "physical_attempt_id": physical_attempt_id,
        "physical_attempt_number": physical_attempt_number,
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold"],
        "attempt_number": attempt_number,
        "initial_request": attempt_number == 1,
        "request_sha256": request_hash,
        "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
        "reserved_at": utc_now(),
    }
    append_jsonl_fsync(CALL_JOURNAL_PATH, reservation)

    started_at = utc_now()
    started_monotonic = time.perf_counter()
    try:
        response = client.chat.completions.create(**payload)
    except Exception as error:
        latency = time.perf_counter() - started_monotonic
        provider_error = safe_provider_error(error)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-k-rag-specialist-attempt-record-v1",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold"],
            "attempt_number": attempt_number,
            "initial_request": attempt_number == 1,
            "initial_request_interval_seconds": (
                round(initial_request_interval_seconds, 6)
                if initial_request_interval_seconds is not None
                else None
            ),
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
            "provider_error": provider_error,
            "started_at": started_at,
            "completed_at": utc_now(),
        }
        outcome = "PROVIDER_ERROR"
    else:
        latency = time.perf_counter() - started_monotonic
        choices = list(getattr(response, "choices", []) or [])
        if choices:
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            message = getattr(choice, "message", None)
            raw_content = getattr(message, "content", None)
            content = raw_content if isinstance(raw_content, str) else ""
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
                "category": "MODEL_OR_ENDPOINT_ERROR",
                "request_headers_recorded": False,
                "authorization_headers_recorded": False,
                "raw_exception_recorded": False,
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
                "raw_exception_recorded": False,
            }
        elif schema_valid:
            outcome = "VALID_PREDICTION"
        else:
            outcome = "INVALID_STRUCTURED_OUTPUT"
        input_tokens, output_tokens, total_tokens = _usage_values(response)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-k-rag-specialist-attempt-record-v1",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold"],
            "attempt_number": attempt_number,
            "initial_request": attempt_number == 1,
            "initial_request_interval_seconds": (
                round(initial_request_interval_seconds, 6)
                if initial_request_interval_seconds is not None
                else None
            ),
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
            "provider_error": provider_error,
            "started_at": started_at,
            "completed_at": utc_now(),
        }

    append_jsonl_fsync(ATTEMPT_RECORDS_PATH, attempt_record)
    completion = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-call-journal-v1",
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
    return attempt_record, outcome, started_monotonic


def _terminal_result(
    manifest_record: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    terminal_status: str,
) -> dict[str, Any]:
    final = attempts[-1]
    prediction = (
        {"rag_required": final["parsed_json"]["rag_required"]}
        if terminal_status == "VALID_PREDICTION"
        else None
    )
    return {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-terminal-result-v1",
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


def _pacing_interval(last_initial_start: float | None) -> float | None:
    if last_initial_start is None:
        return None
    while True:
        elapsed = time.perf_counter() - last_initial_start
        remaining = MIN_INITIAL_REQUEST_INTERVAL_SECONDS - elapsed
        if remaining <= 0:
            return time.perf_counter() - last_initial_start
        time.sleep(remaining)


def _stop_reason(logical_results: int, terminal: Mapping[str, Any]) -> str | None:
    if terminal["terminal_status"] == "RETURNED_MODEL_MISMATCH":
        return "RETURNED_MODEL_MISMATCH_EXECUTION_INTEGRITY_FAILURE"
    category = (terminal.get("provider_error") or {}).get("category")
    if logical_results == 1 and category in FIRST_CALL_FATAL_CATEGORIES:
        return f"FIRST_LOGICAL_CALL_{category}"
    if logical_results > 1 and category in INTEGRITY_FAILURE_CATEGORIES:
        return f"MID_RUN_{category}_EXECUTION_INTEGRITY_FAILURE"
    return None


def execute() -> dict[str, Any]:
    manifest_records, verification = verify_pre_http_boundaries()
    client = create_client()
    physical_attempts = 0
    logical_results = 0
    retries = 0
    stop_reason: str | None = None
    last_initial_start: float | None = None

    for manifest_record in manifest_records:
        logical_attempts: list[dict[str, Any]] = []
        terminal_status = "PROVIDER_ERROR"
        for attempt_number in (1, 2):
            interval = None
            if attempt_number == 1:
                interval = _pacing_interval(last_initial_start)
            physical_attempts += 1
            attempt, outcome, started_monotonic = _one_physical_attempt(
                client,
                manifest_record,
                attempt_number,
                physical_attempts,
                interval,
            )
            if attempt_number == 1:
                last_initial_start = started_monotonic
            logical_attempts.append(attempt)
            if outcome == "VALID_PREDICTION":
                terminal_status = outcome
                break
            if should_retry(outcome, attempt_number):
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
        stop_reason = _stop_reason(logical_results, terminal)
        if stop_reason:
            break
        if logical_results % 8 == 0:
            print(
                f"RAG Specialist progress: {logical_results}/64 logical, "
                f"{physical_attempts}/128 physical, {retries} retries",
                flush=True,
            )

    from .finalize_rag_specialist_dev import finalize

    summary = finalize(
        stop_reason=stop_reason,
        pre_http_verification=verification,
    )
    if stop_reason:
        raise ExecutionBoundaryError(stop_reason)
    if logical_results != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError(
            f"Execution ended with {logical_results} logical results instead of 64"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("prepare", "preflight", "execute", "finalize", "runtime"),
    )
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_authorized_manifest()
    elif args.command == "preflight":
        records, _ = verify_pre_http_boundaries()
        client = create_client()
        del client
        result = {
            "status": "PASS_PRE_HTTP_BOUNDARIES",
            "logical_calls": len(records),
            "runtime": runtime_summary(),
            "provider_calls": 0,
        }
    elif args.command == "execute":
        result = execute()
    elif args.command == "finalize":
        from .finalize_rag_specialist_dev import finalize

        result = finalize()
    else:
        result = runtime_summary()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
