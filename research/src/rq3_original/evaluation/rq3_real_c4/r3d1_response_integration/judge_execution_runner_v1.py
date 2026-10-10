#!/usr/bin/env python3
"""Durable serial runner for one frozen C4 REAL Judge Shard.

The R3D1-R1 freeze does not execute this runner. A later, separate execution
authorization is required. The implementation has no resume mode and refuses
an existing output directory.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Callable, Mapping

try:
    from judge_result_parser_v1 import (
        JudgeResultError,
        parse_judge_result,
        retryable_failure_code,
    )
except ImportError:  # pragma: no cover - repository package import
    from .judge_result_parser_v1 import (
        JudgeResultError,
        parse_judge_result,
        retryable_failure_code,
    )


EXPECTED_PYTHON = "3.13.5"
EXPECTED_OPENAI_SDK = "1.109.1"
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_MAX_OUTPUT_TOKENS = 2048
EXPECTED_TEMPERATURE = 0
MINIMUM_INITIAL_START_INTERVAL_SECONDS = 2.0


class RunnerError(RuntimeError):
    """Raised for a fail-closed runner or execution-contract violation."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RunnerError(f"JSONL row {line_number} is not an object")
        rows.append(value)
    return rows


def durable_write_json(path: Path, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def durable_append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    data = canonical_json_bytes(dict(value)).decode("utf-8") + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _require_runtime() -> dict[str, Any]:
    if platform.python_version() != EXPECTED_PYTHON:
        raise RunnerError(
            f"Python identity mismatch: expected {EXPECTED_PYTHON}, got {platform.python_version()}"
        )
    try:
        sdk_version = importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RunnerError("OpenAI SDK is not installed") from exc
    if sdk_version != EXPECTED_OPENAI_SDK:
        raise RunnerError(
            f"OpenAI SDK identity mismatch: expected {EXPECTED_OPENAI_SDK}, got {sdk_version}"
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise RunnerError("OPENAI_API_KEY is absent")
    return {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "openai_sdk_version": sdk_version,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }


def validate_request_record(record: Mapping[str, Any], configuration: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "logical_judge_request_id",
        "judge_result_blind_id",
        "provider_payload_sha256",
        "estimated_input_tokens",
        "shard_id",
        "provider_payload",
    }
    if not isinstance(record, Mapping) or set(record) != expected:
        raise RunnerError("Judge request record field set mismatch")
    logical_id = record["logical_judge_request_id"]
    result_id = record["judge_result_blind_id"]
    if not isinstance(logical_id, str) or not logical_id.startswith("C4J1-"):
        raise RunnerError("invalid opaque logical Judge request ID")
    if not isinstance(result_id, str) or not result_id.startswith("R3B-"):
        raise RunnerError("invalid opaque Judge result ID")
    payload = record["provider_payload"]
    if not isinstance(payload, Mapping):
        raise RunnerError("provider payload is not an object")
    if payload.get("model") != EXPECTED_MODEL:
        raise RunnerError("Judge model mismatch")
    if payload.get("temperature") != EXPECTED_TEMPERATURE:
        raise RunnerError("Judge temperature mismatch")
    if payload.get("max_tokens") != EXPECTED_MAX_OUTPUT_TOKENS:
        raise RunnerError("Judge maximum-output-token mismatch")
    if payload.get("stream") is not False or "tools" in payload:
        raise RunnerError("streaming/tools boundary mismatch")
    if configuration.get("max_output_tokens") != EXPECTED_MAX_OUTPUT_TOKENS:
        raise RunnerError("configuration maximum-output-token mismatch")
    import hashlib

    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if digest != record["provider_payload_sha256"]:
        raise RunnerError("provider payload hash mismatch")


def _extract_transport_response(response: Any) -> tuple[str, dict[str, Any]]:
    try:
        choice = response.choices[0]
        content = choice.message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise RunnerError("non-retryable malformed SDK response") from exc
    if not isinstance(content, str):
        raise RunnerError("non-retryable missing response content")
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    cached_tokens = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
    metadata = {
        "provider_response_id": getattr(response, "id", None),
        "returned_model": getattr(response, "model", None),
        "system_fingerprint": getattr(response, "system_fingerprint", None),
        "finish_reason": getattr(choice, "finish_reason", None),
        "prompt_tokens": prompt_tokens,
        "cached_input_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    return content, metadata


def execute_shard(
    package_dir: Path,
    output_dir: Path,
    *,
    client_factory: Callable[[], Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    enforce_runtime: bool = True,
) -> dict[str, Any]:
    """Execute one frozen Shard after later authorization; never resume."""

    package_dir = package_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise RunnerError("output directory already exists; resume and overwrite are prohibited")
    configuration = load_json(package_dir / "JUDGE_CONFIGURATION.json")
    contract = load_json(package_dir / "EXECUTION_CONTRACT.json")
    records = load_jsonl(package_dir / "BLINDED_JUDGE_REQUESTS.jsonl")
    if not records:
        raise RunnerError("empty Judge Shard")
    if contract.get("automatic_resume") is not False:
        raise RunnerError("execution contract must prohibit automatic resume")
    if contract.get("serial_execution") is not True:
        raise RunnerError("execution contract must require serial execution")
    if contract.get("automatic_sdk_retries") != 0:
        raise RunnerError("automatic SDK retries must be zero")
    for record in records:
        validate_request_record(record, configuration)

    runtime = _require_runtime() if enforce_runtime else {
        "runtime_check_bypassed_for_mock_test": True,
        "api_key_value_recorded": False,
    }
    output_dir.mkdir(parents=False, exist_ok=False)
    attempt_path = output_dir / "JUDGE_ATTEMPT_JOURNAL.jsonl"
    terminal_path = output_dir / "JUDGE_TERMINAL_JOURNAL.jsonl"
    error_path = output_dir / "JUDGE_ERROR_REGISTRY.jsonl"
    attempt_path.touch(exist_ok=False)
    terminal_path.touch(exist_ok=False)
    error_path.touch(exist_ok=False)
    preflight = {
        "schema_version": "c4-real-judge-preflight-receipt-v1",
        "status": "PASS_BEFORE_ANY_JUDGE_CALL",
        "request_count": len(records),
        "shard_id": records[0]["shard_id"],
        "model": EXPECTED_MODEL,
        "temperature": EXPECTED_TEMPERATURE,
        "max_output_tokens": EXPECTED_MAX_OUTPUT_TOKENS,
        "automatic_sdk_retries": 0,
        "automatic_resume": False,
        "runtime": runtime,
        "judge_calls_at_receipt_write": 0,
    }
    durable_write_json(output_dir / "JUDGE_PREFLIGHT_RECEIPT.json", preflight)

    if client_factory is None:
        from openai import OpenAI

        client_factory = lambda: OpenAI(max_retries=0)
    client = client_factory()
    judge_calls = 0
    initial_starts: list[float] = []
    try:
        for logical_order, record in enumerate(records, 1):
            if initial_starts:
                remaining = MINIMUM_INITIAL_START_INTERVAL_SECONDS - (
                    monotonic() - initial_starts[-1]
                )
                if remaining > 0:
                    sleeper(remaining)
            initial_starts.append(monotonic())
            payload = record["provider_payload"]
            frozen_request_bytes = canonical_json_bytes(payload)
            terminal: dict[str, Any] | None = None
            for attempt_number in (1, 2):
                started = monotonic()
                try:
                    # A retry receives the identical payload object bytes and no
                    # correction message or mutation.
                    if canonical_json_bytes(payload) != frozen_request_bytes:
                        raise RunnerError("request bytes changed before an attempt")
                    response = client.chat.completions.create(**payload)
                    judge_calls += 1
                    raw, metadata = _extract_transport_response(response)
                    if metadata["returned_model"] != EXPECTED_MODEL:
                        raise RunnerError("non-retryable returned-model mismatch")
                    failure_code: str | None = None
                    parsed: dict[str, Any] | None = None
                    try:
                        parsed = parse_judge_result(
                            raw,
                            _extract_applicability_from_payload(payload),
                            expected_judge_result_blind_id=record["judge_result_blind_id"],
                        )
                    except JudgeResultError as exc:
                        failure_code = retryable_failure_code(exc)
                        if failure_code is None:
                            raise RunnerError("non-retryable local parser failure") from exc
                    attempt = {
                        "schema_version": "c4-real-judge-attempt-v1",
                        "logical_order": logical_order,
                        "logical_judge_request_id": record["logical_judge_request_id"],
                        "judge_result_blind_id": record["judge_result_blind_id"],
                        "attempt_number": attempt_number,
                        "provider_payload_sha256": record["provider_payload_sha256"],
                        "raw_response_content": raw,
                        "parsed_semantic_result": parsed,
                        "failure_code": failure_code,
                        "latency_ms": round((monotonic() - started) * 1000, 3),
                        **metadata,
                    }
                    durable_append_jsonl(attempt_path, attempt)
                    if failure_code is None:
                        terminal = {
                            **attempt,
                            "schema_version": "c4-real-judge-terminal-v1",
                            "terminal_status": "VALID_JUDGE_RESULT",
                            "physical_attempts": attempt_number,
                        }
                        durable_append_jsonl(terminal_path, terminal)
                        break
                    if attempt_number == 2:
                        error = {
                            "schema_version": "c4-real-judge-error-v1",
                            "logical_judge_request_id": record["logical_judge_request_id"],
                            "judge_result_blind_id": record["judge_result_blind_id"],
                            "terminal_error": failure_code,
                            "physical_attempts": 2,
                        }
                        durable_append_jsonl(error_path, error)
                        raise RunnerError("retryable invalid output repeated; Shard stopped")
                except RunnerError:
                    raise
                except Exception as exc:
                    error = {
                        "schema_version": "c4-real-judge-error-v1",
                        "logical_judge_request_id": record["logical_judge_request_id"],
                        "judge_result_blind_id": record["judge_result_blind_id"],
                        "attempt_number": attempt_number,
                        "error_type": type(exc).__name__,
                        "terminal_status": "NON_RETRYABLE_ERROR_SHARD_STOPPED",
                    }
                    durable_append_jsonl(error_path, error)
                    raise RunnerError("non-retryable provider error; Shard stopped") from exc
            if terminal is None:
                raise RunnerError("request ended without a terminal result")
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    status = {
        "schema_version": "c4-real-judge-execution-status-v1",
        "status": "COMPLETE",
        "request_count": len(records),
        "valid_terminal_count": len(records),
        "judge_calls": judge_calls,
        "automatic_resume": False,
    }
    durable_write_json(output_dir / "JUDGE_EXECUTION_STATUS.json", status)
    return status


def _extract_applicability_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        raise RunnerError("provider payload message shape mismatch")
    content = messages[0].get("content") if isinstance(messages[0], Mapping) else None
    if not isinstance(content, str):
        raise RunnerError("provider payload content missing")
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    if begin not in content or end not in content:
        raise RunnerError("rendered blind Judge request boundary missing")
    request_text = content.split(begin, 1)[1].rsplit(end, 1)[0]
    request = json.loads(request_text)
    return request["frozen_applicability_map"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    execute_shard(args.package_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

