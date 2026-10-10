#!/usr/bin/env python3
"""Durable, authorization-bound runner for one C4 REAL Judge R2 Package.

This file does not itself authorize execution.  The command line, exact
environment gate, and strict external authorization record are all mandatory.
There is no resume mode and an existing output directory is always refused.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from typing import Any, Callable, Mapping

try:
    from judge_package_validator_v2 import (
        PackageValidationError,
        canonical_json_bytes,
        read_package_zip,
        sha256_bytes,
        sha256_file,
        strict_json,
        validate_package_zip,
    )
except ImportError:  # package copy uses the public Package filename
    try:
        from validate_package import (  # type: ignore[no-redef]
            PackageValidationError,
            canonical_json_bytes,
            read_package_zip,
            sha256_bytes,
            sha256_file,
            strict_json,
            validate_package_zip,
        )
    except ImportError:  # pragma: no cover - repository package import
        from .judge_package_validator_v2 import (  # type: ignore[no-redef]
            PackageValidationError,
            canonical_json_bytes,
            read_package_zip,
            sha256_bytes,
            sha256_file,
            strict_json,
            validate_package_zip,
        )

try:
    from judge_result_parser_v2 import (
        JudgeResultError,
        parse_judge_result,
        retryable_failure_code,
    )
except ImportError:  # pragma: no cover - repository package import
    from .judge_result_parser_v2 import (
        JudgeResultError,
        parse_judge_result,
        retryable_failure_code,
    )


EXPECTED_PYTHON_EXECUTABLE = "/opt/anaconda3/bin/python3"
EXPECTED_PYTHON_VERSION = "3.13.5"
EXPECTED_OPENAI_SDK_VERSION = "1.109.1"
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_MAX_OUTPUT_TOKENS = 2048
EXPECTED_TEMPERATURE = 0
MINIMUM_INITIAL_START_INTERVAL_SECONDS = 15.0
AUTHORIZATION_ENVIRONMENT_VARIABLE = "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION"
AUTHORIZATION_ENVIRONMENT_VALUE = "AUTHORIZED_C4_REAL_JUDGE_EXECUTION_R2"
AUTHORIZATION_SCHEMA_VERSION = "c4-real-judge-execution-authorization-r2-v1"
AUTHORIZATION_FIELDS = {
    "schema_version",
    "authorization_id",
    "authorized_by",
    "authorized_at_utc",
    "package_id",
    "shard_id",
    "request_count",
    "maximum_physical_attempts",
    "package_zip_sha256",
    "blinded_judge_manifest_sha256",
    "status",
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class RunnerError(RuntimeError):
    """Raised for a fail-closed runner or execution-contract violation."""


class _RecordedShardStop(RunnerError):
    """Internal stop marker for a failure already written to the error journal."""


def load_jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        value = strict_json(line, f"request row {line_number}")
        if not isinstance(value, dict):
            raise RunnerError(f"request row {line_number} is not an object")
        rows.append(value)
    return rows


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_create_empty(path: Path) -> None:
    with path.open("xb") as handle:
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def durable_write_json(path: Path, value: Mapping[str, Any]) -> None:
    data = (
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def durable_append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(dict(value)) + b"\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(data)
        os.fsync(handle.fileno())


def _utc_now() -> str:
    return datetime.now().astimezone().astimezone(tz=None).astimezone().isoformat()


def _system_utc_now() -> str:
    from datetime import timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_authorization_record(
    value: Any,
    *,
    package_validation: Mapping[str, Any],
    package_zip_sha256: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != AUTHORIZATION_FIELDS:
        raise RunnerError("authorization record field set mismatch")
    if value["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        raise RunnerError("authorization record schema version mismatch")
    if value["status"] != "AUTHORIZED":
        raise RunnerError("authorization record status is not AUTHORIZED")
    for field in ("authorization_id", "authorized_by"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise RunnerError(f"authorization record {field} is invalid")
        if len(value[field]) > 200 or any(char in value[field] for char in "\r\n"):
            raise RunnerError(f"authorization record {field} is invalid")
    timestamp = value["authorized_at_utc"]
    if not isinstance(timestamp, str) or not UTC_RE.fullmatch(timestamp):
        raise RunnerError("authorization UTC timestamp is invalid")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunnerError("authorization UTC timestamp is invalid") from exc
    bindings = {
        "package_id": package_validation["package_id"],
        "shard_id": package_validation["shard_id"],
        "request_count": package_validation["request_count"],
        "maximum_physical_attempts": package_validation["maximum_physical_attempts"],
        "package_zip_sha256": package_zip_sha256,
        "blinded_judge_manifest_sha256": package_validation[
            "blinded_judge_manifest_sha256"
        ],
    }
    for field, expected in bindings.items():
        if value[field] != expected:
            raise RunnerError(f"authorization binding mismatch: {field}")
    return dict(value)


def _default_runtime_probe() -> dict[str, Any]:
    if sys.executable != EXPECTED_PYTHON_EXECUTABLE:
        raise RunnerError(
            "Python executable mismatch; exact /opt/anaconda3/bin/python3 is required"
        )
    if platform.python_version() != EXPECTED_PYTHON_VERSION:
        raise RunnerError("Python version mismatch")
    try:
        sdk_version = importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RunnerError("OpenAI SDK is absent") from exc
    if sdk_version != EXPECTED_OPENAI_SDK_VERSION:
        raise RunnerError("OpenAI SDK version mismatch")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RunnerError("OPENAI_API_KEY is absent")
    return {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "openai_sdk_version": sdk_version,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }


def _default_client_factory() -> Any:
    from openai import OpenAI

    return OpenAI(max_retries=0)


def _safe_scalar(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).replace("\r", " ").replace("\n", " ")[:200]
    lowered = text.casefold()
    for marker in ("bearer ", "api_key", "authorization"):
        if marker in lowered:
            return "[REDACTED]"
    return text


def sanitized_error(exc: BaseException, phase: str) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    request_id = getattr(exc, "request_id", None)
    if request_id is None and response is not None:
        request_id = getattr(response, "request_id", None)
    return {
        "error_category": type(exc).__name__,
        "error_code": _safe_scalar(getattr(exc, "code", None)),
        "error_parameter": _safe_scalar(getattr(exc, "param", None)),
        "provider_request_id": _safe_scalar(request_id),
        "phase": phase,
        "secret_or_authorization_header_recorded": False,
    }


def _nonnegative_token(value: Any, label: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise RunnerError(f"malformed Provider usage: {label}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RunnerError(f"malformed Provider usage: {label}") from exc
    if result < 0:
        raise RunnerError(f"malformed Provider usage: {label}")
    return result


def _extract_transport_response(response: Any) -> tuple[str, dict[str, Any]]:
    try:
        choice = response.choices[0]
        content = choice.message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise RunnerError("malformed Provider response") from exc
    if not isinstance(content, str):
        raise RunnerError("missing Provider response content")
    usage = getattr(response, "usage", None)
    prompt_tokens = _nonnegative_token(getattr(usage, "prompt_tokens", 0), "prompt")
    completion_tokens = _nonnegative_token(
        getattr(usage, "completion_tokens", 0), "completion"
    )
    total_value = getattr(usage, "total_tokens", None)
    total_tokens = (
        prompt_tokens + completion_tokens
        if total_value is None
        else _nonnegative_token(total_value, "total")
    )
    if total_tokens != prompt_tokens + completion_tokens:
        raise RunnerError("Provider usage arithmetic mismatch")
    cached_tokens = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached_tokens = _nonnegative_token(
            getattr(details, "cached_tokens", 0), "cached input"
        )
    if cached_tokens > prompt_tokens:
        raise RunnerError("Provider cached-input tokens exceed prompt tokens")
    return content, {
        "provider_response_id": _safe_scalar(getattr(response, "id", None)),
        "returned_model": _safe_scalar(getattr(response, "model", None)),
        "system_fingerprint": _safe_scalar(
            getattr(response, "system_fingerprint", None)
        ),
        "finish_reason": _safe_scalar(getattr(choice, "finish_reason", None)),
        "prompt_tokens": prompt_tokens,
        "cached_input_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _extract_applicability(provider_payload: Mapping[str, Any]) -> dict[str, Any]:
    messages = provider_payload["messages"]
    content = messages[0]["content"]
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    request = strict_json(
        content.split(begin, 1)[1].rsplit(end, 1)[0].encode("utf-8"),
        "embedded blind request",
    )
    return request["frozen_applicability_map"]


def _initialize_output(output_dir: Path) -> dict[str, Path]:
    if output_dir.exists():
        raise RunnerError("output directory already exists; resume is prohibited")
    if not output_dir.parent.is_dir():
        raise RunnerError("output parent directory is absent")
    os.mkdir(output_dir, 0o700)
    _fsync_directory(output_dir.parent)
    paths = {
        "attempt": output_dir / "JUDGE_ATTEMPT_JOURNAL.jsonl",
        "terminal": output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl",
        "error": output_dir / "JUDGE_ERROR_REGISTRY.jsonl",
        "status_journal": output_dir / "JUDGE_STATUS_JOURNAL.jsonl",
        "preflight": output_dir / "JUDGE_PREFLIGHT_START_RECEIPT.json",
        "final_status": output_dir / "JUDGE_EXECUTION_STATUS.json",
    }
    for name in ("attempt", "terminal", "error", "status_journal"):
        durable_create_empty(paths[name])
    return paths


def execute_package(
    package_zip: Path,
    authorization_record: Path,
    output_dir: Path,
    *,
    runtime_probe: Callable[[], Mapping[str, Any]] = _default_runtime_probe,
    client_factory: Callable[[], Any] = _default_client_factory,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    utc_now: Callable[[], str] = _system_utc_now,
) -> dict[str, Any]:
    """Execute one complete Shard after all external authorization bindings pass."""

    package_zip = package_zip.resolve()
    authorization_record = authorization_record.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise RunnerError("output directory already exists; resume is prohibited")
    if os.environ.get(AUTHORIZATION_ENVIRONMENT_VARIABLE) != AUTHORIZATION_ENVIRONMENT_VALUE:
        raise RunnerError("exact Judge execution environment gate is absent")

    try:
        package_validation = validate_package_zip(package_zip)
        members = read_package_zip(package_zip)
    except PackageValidationError as exc:
        raise RunnerError("Package validation failed") from exc
    if not authorization_record.is_file():
        raise RunnerError("authorization record is absent")
    try:
        authorization_value = strict_json(
            authorization_record.read_bytes(), "authorization record"
        )
    except PackageValidationError as exc:
        raise RunnerError("authorization record is invalid") from exc
    authorization = _validate_authorization_record(
        authorization_value,
        package_validation=package_validation,
        package_zip_sha256=sha256_file(package_zip),
    )
    rows = load_jsonl_bytes(members["BLINDED_JUDGE_REQUESTS.jsonl"])

    # All Package and external-authorization bindings have passed.  Only now is
    # the output directory atomically created.  Runtime and client construction
    # occur after the durable preflight-start receipt below.
    paths = _initialize_output(output_dir)
    preflight = {
        "schema_version": "c4-real-judge-preflight-start-receipt-r2-v1",
        "status": "BINDINGS_VERIFIED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
        "timestamp_utc": utc_now(),
        "authorization_id": authorization["authorization_id"],
        "authorized_by": authorization["authorized_by"],
        "authorized_at_utc": authorization["authorized_at_utc"],
        "package_id": package_validation["package_id"],
        "shard_id": package_validation["shard_id"],
        "request_count": len(rows),
        "maximum_physical_attempts": len(rows) * 2,
        "package_zip_sha256": package_validation["package_zip_sha256"],
        "blinded_judge_manifest_sha256": package_validation[
            "blinded_judge_manifest_sha256"
        ],
        "judge_calls_at_receipt_write": 0,
        "runtime_constructed_at_receipt_write": False,
        "client_constructed_at_receipt_write": False,
        "automatic_resume": False,
    }
    durable_write_json(paths["preflight"], preflight)
    durable_append_jsonl(
        paths["status_journal"],
        {
            "schema_version": "c4-real-judge-status-event-r2-v1",
            "status": "PREFLIGHT_STARTED",
            "timestamp_utc": utc_now(),
            "judge_calls": 0,
        },
    )

    judge_calls = 0
    physical_attempts = 0
    valid_terminals = 0
    client: Any = None
    phase = "RUNTIME_VALIDATION"
    failure_recorded = False
    try:
        runtime = dict(runtime_probe())
        durable_append_jsonl(
            paths["status_journal"],
            {
                "schema_version": "c4-real-judge-status-event-r2-v1",
                "status": "RUNTIME_VALIDATED",
                "timestamp_utc": utc_now(),
                "runtime": runtime,
                "judge_calls": judge_calls,
            },
        )
        phase = "CLIENT_CONSTRUCTION"
        client = client_factory()
        durable_append_jsonl(
            paths["status_journal"],
            {
                "schema_version": "c4-real-judge-status-event-r2-v1",
                "status": "CLIENT_CONSTRUCTED_MAX_RETRIES_ZERO",
                "timestamp_utc": utc_now(),
                "judge_calls": judge_calls,
            },
        )

        previous_initial_start: float | None = None
        for logical_order, record in enumerate(rows, 1):
            phase = "INITIAL_REQUEST_PACING"
            if previous_initial_start is not None:
                remaining = MINIMUM_INITIAL_START_INTERVAL_SECONDS - (
                    monotonic() - previous_initial_start
                )
                if remaining > 0:
                    sleeper(remaining)
            initial_start = monotonic()
            previous_initial_start = initial_start
            frozen_payload_bytes = canonical_json_bytes(record["provider_payload"])
            applicability = _extract_applicability(record["provider_payload"])
            terminal_written = False
            for attempt_number in (1, 2):
                phase = "PROVIDER_CALL"
                if canonical_json_bytes(record["provider_payload"]) != frozen_payload_bytes:
                    raise RunnerError("frozen Provider request bytes changed")
                attempt_payload = json.loads(frozen_payload_bytes)
                if canonical_json_bytes(attempt_payload) != frozen_payload_bytes:
                    raise RunnerError("Provider request round-trip changed bytes")
                started_monotonic = monotonic()
                started_utc = utc_now()
                physical_attempts += 1
                judge_calls += 1
                durable_append_jsonl(
                    paths["attempt"],
                    {
                        "schema_version": "c4-real-judge-attempt-event-r2-v1",
                        "event": "ATTEMPT_STARTED",
                        "logical_order": logical_order,
                        "logical_judge_request_id": record["logical_judge_request_id"],
                        "judge_result_blind_id": record["judge_result_blind_id"],
                        "attempt_number": attempt_number,
                        "provider_payload_sha256": record["provider_payload_sha256"],
                        "request_started_at_utc": started_utc,
                        "judge_calls_started": judge_calls,
                    },
                )
                response = client.chat.completions.create(**attempt_payload)
                raw, metadata = _extract_transport_response(response)
                finished_utc = utc_now()
                latency_ms = round((monotonic() - started_monotonic) * 1000, 3)
                attempt_returned = {
                    "schema_version": "c4-real-judge-attempt-event-r2-v1",
                    "event": "ATTEMPT_RETURNED",
                    "logical_order": logical_order,
                    "logical_judge_request_id": record["logical_judge_request_id"],
                    "judge_result_blind_id": record["judge_result_blind_id"],
                    "attempt_number": attempt_number,
                    "provider_payload_sha256": record["provider_payload_sha256"],
                    "request_started_at_utc": started_utc,
                    "response_finished_at_utc": finished_utc,
                    "latency_ms": latency_ms,
                    "raw_response_content": raw,
                    **metadata,
                }
                if metadata["returned_model"] != EXPECTED_MODEL:
                    durable_append_jsonl(paths["attempt"], attempt_returned)
                    durable_append_jsonl(
                        paths["error"],
                        {
                            "schema_version": "c4-real-judge-error-r2-v1",
                            "timestamp_utc": finished_utc,
                            "logical_judge_request_id": record[
                                "logical_judge_request_id"
                            ],
                            "judge_result_blind_id": record["judge_result_blind_id"],
                            "attempt_number": attempt_number,
                            "error_category": "RETURNED_MODEL_MISMATCH",
                            "returned_model": metadata["returned_model"],
                            "terminal_policy": "STOP_ENTIRE_SHARD",
                        },
                    )
                    failure_recorded = True
                    raise _RecordedShardStop("returned-model mismatch")
                parsed: dict[str, Any] | None = None
                failure_code: str | None = None
                try:
                    parsed = parse_judge_result(
                        raw,
                        applicability,
                        expected_judge_result_blind_id=record[
                            "judge_result_blind_id"
                        ],
                    )
                except JudgeResultError as exc:
                    failure_code = retryable_failure_code(exc)
                    if failure_code is None:
                        raise RunnerError("non-retryable local parser failure") from exc
                durable_append_jsonl(
                    paths["attempt"],
                    {
                        **attempt_returned,
                        "failure_code": failure_code,
                        "parsed_semantic_result": parsed,
                    },
                )
                if failure_code is None:
                    durable_append_jsonl(
                        paths["terminal"],
                        {
                            "schema_version": "c4-real-judge-terminal-r2-v1",
                            "terminal_status": "VALID_JUDGE_RESULT",
                            "logical_order": logical_order,
                            "logical_judge_request_id": record[
                                "logical_judge_request_id"
                            ],
                            "judge_result_blind_id": record["judge_result_blind_id"],
                            "provider_payload_sha256": record[
                                "provider_payload_sha256"
                            ],
                            "physical_attempts": attempt_number,
                            "parsed_semantic_result": parsed,
                            "terminal_at_utc": finished_utc,
                            **metadata,
                        },
                    )
                    valid_terminals += 1
                    terminal_written = True
                    break
                if attempt_number == 2:
                    durable_append_jsonl(
                        paths["error"],
                        {
                            "schema_version": "c4-real-judge-error-r2-v1",
                            "timestamp_utc": finished_utc,
                            "logical_judge_request_id": record[
                                "logical_judge_request_id"
                            ],
                            "judge_result_blind_id": record["judge_result_blind_id"],
                            "attempt_number": 2,
                            "error_category": failure_code,
                            "terminal_policy": "STOP_ENTIRE_SHARD",
                            "continuation_requires_new_direct_authorization": True,
                        },
                    )
                    failure_recorded = True
                    raise _RecordedShardStop("second invalid output")
            if not terminal_written:
                raise RunnerError("logical request ended without a terminal result")

        phase = "CLIENT_CLOSE"
        close = getattr(client, "close", None)
        if callable(close):
            close()
        client = None
        phase = "FINAL_STATUS"
        status = {
            "schema_version": "c4-real-judge-execution-status-r2-v1",
            "status": "COMPLETE",
            "timestamp_utc": utc_now(),
            "package_id": package_validation["package_id"],
            "shard_id": package_validation["shard_id"],
            "request_count": len(rows),
            "valid_terminal_count": valid_terminals,
            "physical_attempts": physical_attempts,
            "judge_calls": judge_calls,
            "automatic_resume": False,
            "continuation_requires_new_direct_authorization": False,
        }
        durable_append_jsonl(
            paths["status_journal"],
            {
                "schema_version": "c4-real-judge-status-event-r2-v1",
                "status": "COMPLETE",
                "timestamp_utc": status["timestamp_utc"],
                "judge_calls": judge_calls,
                "valid_terminal_count": valid_terminals,
            },
        )
        durable_write_json(paths["final_status"], status)
        return status
    except BaseException as exc:
        if client is not None:
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except BaseException as close_exc:
                durable_append_jsonl(
                    paths["error"],
                    {
                        "schema_version": "c4-real-judge-error-r2-v1",
                        "timestamp_utc": utc_now(),
                        **sanitized_error(close_exc, "CLIENT_CLOSE_AFTER_FAILURE"),
                        "terminal_policy": "STOP_ENTIRE_SHARD",
                    },
                )
        if not failure_recorded:
            durable_append_jsonl(
                paths["error"],
                {
                    "schema_version": "c4-real-judge-error-r2-v1",
                    "timestamp_utc": utc_now(),
                    **sanitized_error(exc, phase),
                    "terminal_policy": "STOP_ENTIRE_SHARD",
                    "continuation_requires_new_direct_authorization": True,
                },
            )
        status = {
            "schema_version": "c4-real-judge-execution-status-r2-v1",
            "status": "INCOMPLETE",
            "timestamp_utc": utc_now(),
            "package_id": package_validation["package_id"],
            "shard_id": package_validation["shard_id"],
            "request_count": len(rows),
            "valid_terminal_count": valid_terminals,
            "physical_attempts": physical_attempts,
            "judge_calls": judge_calls,
            "automatic_resume": False,
            "continuation_requires_new_direct_authorization": True,
        }
        durable_append_jsonl(
            paths["status_journal"],
            {
                "schema_version": "c4-real-judge-status-event-r2-v1",
                "status": "INCOMPLETE",
                "timestamp_utc": status["timestamp_utc"],
                "judge_calls": judge_calls,
                "valid_terminal_count": valid_terminals,
                "failure_phase": phase,
            },
        )
        durable_write_json(paths["final_status"], status)
        raise RunnerError(
            "Judge Shard stopped INCOMPLETE; inspect durable sanitized journals"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-zip", type=Path, required=True)
    parser.add_argument("--authorization-record", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    if not args.execute:  # defensive; argparse requires the explicit flag
        raise RunnerError("--execute is required")
    execute_package(args.package_zip, args.authorization_record, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORIZATION_ENVIRONMENT_VALUE",
    "AUTHORIZATION_ENVIRONMENT_VARIABLE",
    "AUTHORIZATION_SCHEMA_VERSION",
    "EXPECTED_MODEL",
    "MINIMUM_INITIAL_START_INTERVAL_SECONDS",
    "RunnerError",
    "execute_package",
    "sanitized_error",
]
