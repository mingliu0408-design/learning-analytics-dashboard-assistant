"""Execute the frozen RQ2-V2 B4 DEV manifest with a bounded OpenAI client.

The adapter is deliberately synchronous and minimal.  It uses the existing
Chat Completions SDK surface, disables SDK retries, reserves every physical
attempt in a durable journal before HTTP, and never repairs model output.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

from build_b4_preparation import (
    LABEL_FIELDS,
    canonical_json,
    parse_strict_response,
)


TRACK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRACK_DIR.parents[2]
V1_MANIFEST_PATH = TRACK_DIR / "b4_dev_execution_manifest_v1.jsonl"
V2_MANIFEST_PATH = TRACK_DIR / "b4_dev_execution_manifest_v2.jsonl"
MANIFEST_DIFF_PATH = TRACK_DIR / "b4_manifest_v1_v2_diff_v1.json"
ATTEMPT_RECORDS_PATH = TRACK_DIR / "b4_dev_attempt_records_v1.jsonl"
TERMINAL_RESULTS_PATH = TRACK_DIR / "b4_dev_terminal_results_v1.jsonl"
CALL_JOURNAL_PATH = TRACK_DIR / "b4_dev_call_journal_v1.jsonl"

EXPECTED_BRANCH = "research/rq2-v2-stage4-i-b4-preparation"
EXPECTED_STARTING_HEAD = "119f5595f69362410858ff69ce32b879119d12b6"
EXPECTED_PROMPT_SHA256 = (
    "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541"
)
EXPECTED_SCHEMA_SHA256 = (
    "9f364e920cfcca07a90580000196c85a6f801ef2e75c9c907bf820eea6a9aba2"
)
PREPARED_MODEL_ALIAS = "gpt-4o-mini"
AUTHORIZED_MODEL_SNAPSHOT = "gpt-4o-mini-2024-07-18"
AUTHORIZED_STATUS = "AUTHORIZED_DEV_ONLY"
LOGICAL_CALL_CEILING = 64
PHYSICAL_ATTEMPT_CEILING = 128
CLIENT_MAX_RETRIES = 0
MAX_OUTPUT_TOKENS = 64
ALLOWED_V1_V2_DIFF_PATHS = {
    "model_execution_authorization_status",
    "provider_request_payload.max_tokens",
    "provider_request_payload.model",
}
FINAL_OUTPUT_PATHS = (
    TRACK_DIR / "b4_dev_predictions_v1.csv",
    TRACK_DIR / "b4_dev_error_registry_v1.csv",
    TRACK_DIR / "b4_dev_usage_and_cost_v1.json",
    TRACK_DIR / "b4_dev_metrics_v1.json",
    TRACK_DIR / "b4_final_frozen_configuration_v1.json",
    TRACK_DIR / "B4_DEV_EXECUTION_RESULTS.md",
    TRACK_DIR / "B4_DEV_EXECUTION_STATUS.md",
)


class ExecutionBoundaryError(RuntimeError):
    """Raised before HTTP when a frozen execution boundary is not satisfied."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def append_jsonl_fsync(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _diff_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        differences: set[str] = set()
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                differences.add(path)
            else:
                differences.update(_diff_paths(left[key], right[key], path))
        return differences
    if left != right:
        return {prefix}
    return set()


def _normalize_v2_to_v1(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(record)
    normalized["model_execution_authorization_status"] = (
        "REQUIRES_DIRECT_USER_AUTHORIZATION_FOR_B4_EXECUTION"
    )
    payload = normalized["provider_request_payload"]
    payload["model"] = PREPARED_MODEL_ALIAS
    payload.pop("max_tokens", None)
    return normalized


def validate_manifest_pair(
    v1_records: Sequence[Mapping[str, Any]],
    v2_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(v1_records) != LOGICAL_CALL_CEILING or len(v2_records) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("Both manifests must contain exactly 64 records")
    expected_ids = [f"R2V2-B4-DEV-{index:04d}" for index in range(1, 65)]
    if [record["logical_call_id"] for record in v1_records] != expected_ids:
        raise ExecutionBoundaryError("V1 logical_call_id order is not frozen deterministic order")
    if [record["logical_call_id"] for record in v2_records] != expected_ids:
        raise ExecutionBoundaryError("V2 logical_call_id order is not frozen deterministic order")

    observed_paths: set[str] = set()
    per_record_differences: list[dict[str, Any]] = []
    for v1, v2 in zip(v1_records, v2_records, strict=True):
        if v1["logical_call_id"] != v2["logical_call_id"]:
            raise ExecutionBoundaryError("V1/V2 record alignment differs")
        differences = _diff_paths(v1, v2)
        if differences != ALLOWED_V1_V2_DIFF_PATHS:
            raise ExecutionBoundaryError(
                f"Disallowed V1/V2 differences for {v1['logical_call_id']}: "
                f"{sorted(differences)}"
            )
        observed_paths.update(differences)
        payload = v2["provider_request_payload"]
        if payload.get("model") != AUTHORIZED_MODEL_SNAPSHOT:
            raise ExecutionBoundaryError("V2 requested model is not the authorized snapshot")
        if payload.get("temperature") != 0:
            raise ExecutionBoundaryError("V2 temperature differs from zero")
        if payload.get("max_tokens") != MAX_OUTPUT_TOKENS:
            raise ExecutionBoundaryError("V2 max_tokens differs from 64")
        if set(payload) != {
            "model",
            "messages",
            "temperature",
            "response_format",
            "max_tokens",
        }:
            raise ExecutionBoundaryError("V2 provider payload contains an unauthorized field")
        if v2.get("model_execution_authorization_status") != AUTHORIZED_STATUS:
            raise ExecutionBoundaryError("V2 execution authorization status differs")
        if v2.get("execution_status") != "NOT_EXECUTED":
            raise ExecutionBoundaryError("V2 snapshot must remain NOT_EXECUTED")
        controls = v2.get("execution_controls") or {}
        if controls.get("sdk_transport_retries") != CLIENT_MAX_RETRIES:
            raise ExecutionBoundaryError("V2 SDK retry control differs from zero")
        if controls.get("invalid_structured_output_retries_max") != 1:
            raise ExecutionBoundaryError("V2 invalid-output retry control differs")
        if controls.get("silent_repair_allowed") is not False:
            raise ExecutionBoundaryError("V2 unexpectedly allows silent repair")
        if _normalize_v2_to_v1(v2) != v1:
            raise ExecutionBoundaryError("V2 normalization is not byte-semantic V1 identity")
        per_record_differences.append(
            {
                "logical_call_id": v1["logical_call_id"],
                "difference_paths": sorted(differences),
            }
        )

    if observed_paths != ALLOWED_V1_V2_DIFF_PATHS:
        raise ExecutionBoundaryError("Observed aggregate V1/V2 difference set differs")
    return {
        "allowed_difference_paths": sorted(ALLOWED_V1_V2_DIFF_PATHS),
        "observed_difference_paths": sorted(observed_paths),
        "per_record_differences": per_record_differences,
        "normalized_v2_equals_v1": True,
        "normalized_v2_manifest_sha256": canonical_sha256(
            [_normalize_v2_to_v1(record) for record in v2_records]
        ),
        "v1_manifest_semantic_sha256": canonical_sha256(list(v1_records)),
    }


def prepare_v2_manifest() -> dict[str, Any]:
    v1_records = load_jsonl(V1_MANIFEST_PATH)
    v2_records: list[dict[str, Any]] = []
    for record in v1_records:
        updated = copy.deepcopy(record)
        if updated["provider_request_payload"].get("model") != PREPARED_MODEL_ALIAS:
            raise ExecutionBoundaryError("V1 model alias differs from prepared freeze")
        updated["provider_request_payload"]["model"] = AUTHORIZED_MODEL_SNAPSHOT
        updated["provider_request_payload"]["max_tokens"] = MAX_OUTPUT_TOKENS
        updated["model_execution_authorization_status"] = AUTHORIZED_STATUS
        updated["execution_controls"]["sdk_transport_retries"] = CLIENT_MAX_RETRIES
        v2_records.append(updated)

    validation = validate_manifest_pair(v1_records, v2_records)
    v2_text = "".join(canonical_json(record) + "\n" for record in v2_records)
    atomic_write_text(V2_MANIFEST_PATH, v2_text)
    v1_file_hash = sha256_file(V1_MANIFEST_PATH)
    v2_file_hash = sha256_file(V2_MANIFEST_PATH)
    diff_report = {
        "schema_version": "rq2-v2-stage4-i-x-b4-manifest-diff-v1",
        "status": "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY",
        "record_count": len(v2_records),
        "v1_manifest_path": V1_MANIFEST_PATH.name,
        "v1_manifest_sha256": v1_file_hash,
        "v2_manifest_path": V2_MANIFEST_PATH.name,
        "v2_manifest_sha256": v2_file_hash,
        "requested_model_before": PREPARED_MODEL_ALIAS,
        "requested_model_after": AUTHORIZED_MODEL_SNAPSHOT,
        "authorization_status_after": AUTHORIZED_STATUS,
        "sdk_transport_retries": CLIENT_MAX_RETRIES,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        **validation,
    }
    atomic_write_json(MANIFEST_DIFF_PATH, diff_report)
    return diff_report


def verify_v2_manifest_files() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    v1_records = load_jsonl(V1_MANIFEST_PATH)
    v2_records = load_jsonl(V2_MANIFEST_PATH)
    validation = validate_manifest_pair(v1_records, v2_records)
    diff_report = json.loads(MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
    if diff_report.get("v1_manifest_sha256") != sha256_file(V1_MANIFEST_PATH):
        raise ExecutionBoundaryError("Recorded V1 manifest file hash differs")
    if diff_report.get("v2_manifest_sha256") != sha256_file(V2_MANIFEST_PATH):
        raise ExecutionBoundaryError("Recorded V2 manifest file hash differs")
    for key in (
        "allowed_difference_paths",
        "observed_difference_paths",
        "normalized_v2_manifest_sha256",
        "v1_manifest_semantic_sha256",
    ):
        if diff_report.get(key) != validation.get(key):
            raise ExecutionBoundaryError(f"Recorded manifest-diff field differs: {key}")
    return v2_records, diff_report


def _git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def verify_pre_http_boundaries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if Path.cwd().resolve() != REPO_ROOT.resolve():
        raise ExecutionBoundaryError(f"Unexpected working directory: {Path.cwd()}")
    if _git_output("branch", "--show-current") != EXPECTED_BRANCH:
        raise ExecutionBoundaryError("Unexpected branch")
    if _git_output("rev-parse", "HEAD") != EXPECTED_STARTING_HEAD:
        raise ExecutionBoundaryError("Unexpected starting HEAD")
    status_lines = [line for line in _git_output("status", "--short").splitlines() if line]
    for line in status_lines:
        path = line[3:]
        if not path.startswith(
            "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/"
        ):
            raise ExecutionBoundaryError(f"Unrelated worktree change before HTTP: {line}")
    if sha256_file(TRACK_DIR / "b4_prompt_template_frozen_v1.txt") != EXPECTED_PROMPT_SHA256:
        raise ExecutionBoundaryError("Frozen prompt hash mismatch")
    if sha256_file(TRACK_DIR / "b4_response_schema_v1.json") != EXPECTED_SCHEMA_SHA256:
        raise ExecutionBoundaryError("Frozen response-schema hash mismatch")
    records, diff_report = verify_v2_manifest_files()
    if not os.environ.get("OPENAI_API_KEY"):
        raise ExecutionBoundaryError("OPENAI_API_KEY is missing or empty")
    for path in (ATTEMPT_RECORDS_PATH, TERMINAL_RESULTS_PATH, CALL_JOURNAL_PATH, *FINAL_OUTPUT_PATHS):
        if path.exists():
            raise ExecutionBoundaryError(f"Execution output already exists: {path.name}")
    return records, diff_report


def create_client() -> Any:
    from openai import OpenAI

    return OpenAI(max_retries=CLIENT_MAX_RETRIES)


def _safe_provider_error(error: BaseException) -> dict[str, Any]:
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    if code is None:
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            code = body.get("code") or (
                body.get("error", {}).get("code")
                if isinstance(body.get("error"), dict)
                else None
            )
    error_type = type(error).__name__
    configuration_types = {
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
    }
    return {
        "error_type": error_type,
        "status_code": status_code,
        "code": str(code) if code is not None else None,
        "category": (
            "AUTHENTICATION_OR_CONFIGURATION"
            if error_type in configuration_types
            else "PROVIDER_ERROR"
        ),
        "raw_message_recorded": False,
    }


def _usage_values(response: Any) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None
    input_tokens = getattr(usage, "prompt_tokens", None)
    output_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    return input_tokens, output_tokens, total_tokens


def _validate_response_content(content: str) -> tuple[Any, bool, str | None]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, False, "INVALID_JSON"
    try:
        strict = parse_strict_response(content)
    except ValueError:
        return parsed, False, "STRICT_SCHEMA_VALIDATION_FAILED"
    return strict, True, None


def _one_physical_attempt(
    client: Any,
    manifest_record: Mapping[str, Any],
    attempt_number: int,
    physical_attempt_number: int,
) -> tuple[dict[str, Any], str]:
    payload = manifest_record["provider_request_payload"]
    request_hash = canonical_sha256(payload)
    physical_attempt_id = f"R2V2-B4-PHYS-{physical_attempt_number:04d}"
    reservation = {
        "schema_version": "rq2-v2-stage4-i-x-b4-call-journal-v1",
        "event": "ATTEMPT_RESERVED",
        "physical_attempt_id": physical_attempt_id,
        "physical_attempt_number": physical_attempt_number,
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold_id"],
        "attempt_number": attempt_number,
        "request_sha256": request_hash,
        "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
        "reserved_at": utc_now(),
    }
    append_jsonl_fsync(CALL_JOURNAL_PATH, reservation)

    started_at = utc_now()
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**payload)
    except Exception as error:  # Provider taxonomy is captured without raw error text.
        latency = time.perf_counter() - started
        provider_error = _safe_provider_error(error)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-i-x-b4-attempt-record-v1",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold_id"],
            "attempt_number": attempt_number,
            "request_sha256": request_hash,
            "response_id": None,
            "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": None,
            "system_fingerprint": None,
            "finish_reason": None,
            "response_content": None,
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
        latency = time.perf_counter() - started
        response_id = str(getattr(response, "id", "") or "") or None
        returned_model = str(getattr(response, "model", "") or "") or None
        system_fingerprint = getattr(response, "system_fingerprint", None)
        choices = list(getattr(response, "choices", []) or [])
        if choices:
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            message = getattr(choice, "message", None)
            content = str(getattr(message, "content", "") or "")
            refusal_present = bool(getattr(message, "refusal", None))
        else:
            finish_reason = None
            content = ""
            refusal_present = False
        input_tokens, output_tokens, total_tokens = _usage_values(response)
        parsed, schema_valid, schema_error = _validate_response_content(content)
        provider_error: dict[str, Any] | None = None
        if returned_model != AUTHORIZED_MODEL_SNAPSHOT:
            outcome = "RETURNED_MODEL_MISMATCH"
            schema_valid = False
            schema_error = "RETURNED_MODEL_MISMATCH"
            provider_error = {
                "error_type": "ReturnedModelMismatch",
                "status_code": None,
                "code": None,
                "category": "AUTHENTICATION_OR_CONFIGURATION",
                "raw_message_recorded": False,
            }
        elif refusal_present:
            outcome = "PROVIDER_REFUSAL"
            schema_valid = False
            schema_error = "PROVIDER_REFUSAL"
            provider_error = {
                "error_type": "ProviderRefusal",
                "status_code": None,
                "code": None,
                "category": "PROVIDER_REFUSAL",
                "raw_message_recorded": False,
            }
        elif schema_valid:
            outcome = "VALID_PREDICTION"
        else:
            outcome = "INVALID_STRUCTURED_OUTPUT"
        attempt_record = {
            "schema_version": "rq2-v2-stage4-i-x-b4-attempt-record-v1",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold_id"],
            "attempt_number": attempt_number,
            "request_sha256": request_hash,
            "response_id": response_id,
            "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": returned_model,
            "system_fingerprint": system_fingerprint,
            "finish_reason": finish_reason,
            "response_content": content,
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
        "schema_version": "rq2-v2-stage4-i-x-b4-call-journal-v1",
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
        {field: final["parsed_json"][field] for field in LABEL_FIELDS}
        if terminal_status == "VALID_PREDICTION"
        else None
    )
    return {
        "schema_version": "rq2-v2-stage4-i-x-b4-terminal-result-v1",
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold_id"],
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


def execute() -> dict[str, Any]:
    manifest_records, diff_report = verify_pre_http_boundaries()
    client = create_client()
    physical_attempts = 0
    logical_results = 0
    retries = 0
    stop_reason: str | None = None

    for manifest_record in manifest_records:
        logical_attempt_records: list[dict[str, Any]] = []
        terminal_status = "PROVIDER_ERROR"
        for attempt_number in (1, 2):
            physical_attempts += 1
            if physical_attempts > PHYSICAL_ATTEMPT_CEILING:
                raise ExecutionBoundaryError("Physical-attempt ceiling would be exceeded")
            attempt_record, outcome = _one_physical_attempt(
                client,
                manifest_record,
                attempt_number,
                physical_attempts,
            )
            logical_attempt_records.append(attempt_record)
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
            logical_attempt_records,
            terminal_status,
        )
        append_jsonl_fsync(TERMINAL_RESULTS_PATH, terminal)
        logical_results += 1

        error = terminal.get("provider_error") or {}
        configuration_failure = error.get("category") == "AUTHENTICATION_OR_CONFIGURATION"
        if terminal_status == "RETURNED_MODEL_MISMATCH":
            stop_reason = "RETURNED_MODEL_MISMATCH"
        elif logical_results == 1 and configuration_failure:
            stop_reason = "FIRST_LOGICAL_CALL_AUTHENTICATION_OR_CONFIGURATION_ERROR"
        if stop_reason:
            break
        if logical_results % 8 == 0:
            print(
                f"B4 progress: {logical_results}/64 logical, "
                f"{physical_attempts}/128 physical, {retries} retries",
                flush=True,
            )

    from finalize_b4_dev import finalize

    summary = finalize(
        stop_reason=stop_reason,
        manifest_diff_report=diff_report,
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
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="Create and verify the frozen V2 manifest")
    subparsers.add_parser("preflight", help="Verify every boundary without a provider call")
    subparsers.add_parser("execute", help="Execute the authorized bounded DEV run")
    subparsers.add_parser("finalize", help="Rebuild derived outputs without provider calls")
    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare_v2_manifest()
    elif args.command == "preflight":
        records, diff_report = verify_pre_http_boundaries()
        result = {
            "status": "PASS_PRE_HTTP_BOUNDARIES",
            "logical_call_count": len(records),
            "v2_manifest_sha256": diff_report["v2_manifest_sha256"],
            "provider_calls": 0,
        }
    elif args.command == "execute":
        result = execute()
    else:
        from finalize_b4_dev import finalize

        result = finalize(stop_reason=None, manifest_diff_report=None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
