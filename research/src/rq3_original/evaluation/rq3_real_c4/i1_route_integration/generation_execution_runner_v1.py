#!/usr/bin/env python3
"""Durable serial runner for an authorised blinded C4 generation shard.

The runner is packaged in I1 but is not executed by I1. It contains only the
future blinded generation transport and its durable local journals.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable, Mapping


EXPECTED_PYTHON = (3, 13, 5)
EXPECTED_PYTHON_PATH = "/opt/anaconda3/bin/python3"
EXPECTED_OPENAI = "1.109.1"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
INITIAL_REQUEST_GAP_SECONDS = 2.0
MAX_ATTEMPTS_PER_REQUEST = 2
_SECRET = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    r"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)
_LOCAL_PATH = re.compile(r"/(?:Users|private|var|opt)/[^\s,;]+")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_error(error: BaseException) -> Mapping[str, str]:
    message = _SECRET.sub("[REDACTED_SECRET]", str(error))
    message = _LOCAL_PATH.sub("[REDACTED_LOCAL_PATH]", message)
    return {
        "error_type": type(error).__name__,
        "sanitized_message": message[:500],
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"request manifest line {line_number} is not an object")
        rows.append(value)
    if not rows:
        raise ValueError("request manifest is empty")
    return rows


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        raise
    _fsync_parent(path)


def create_exclusive_empty(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_parent(path)


def append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def validate_answer(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"answer_text"}:
        return None
    answer = parsed["answer_text"]
    if not isinstance(answer, str) or not answer.strip():
        return None
    return answer


def runtime_preflight() -> Mapping[str, Any]:
    if tuple(sys.version_info[:3]) != EXPECTED_PYTHON:
        raise RuntimeError("EXACT_PYTHON_3_13_5_REQUIRED")
    if os.path.realpath(sys.executable) != os.path.realpath(EXPECTED_PYTHON_PATH):
        raise RuntimeError("EXACT_OPT_ANACONDA_PYTHON_REQUIRED")
    import openai

    if openai.__version__ != EXPECTED_OPENAI:
        raise RuntimeError("EXACT_OPENAI_SDK_1_109_1_REQUIRED")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY_NOT_PRESENT")
    return {
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "python_path": EXPECTED_PYTHON_PATH,
        "openai_sdk_version": openai.__version__,
        "automatic_sdk_retries": 0,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }


def _response_content(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise ValueError("PROVIDER_RESPONSE_HAS_NO_CHOICES")
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if not isinstance(content, str):
        raise ValueError("PROVIDER_RESPONSE_CONTENT_NOT_TEXT")
    return content


def _usage(response: Any) -> Mapping[str, Any]:
    usage = getattr(response, "usage", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "prompt_tokens_details": (
            getattr(getattr(usage, "prompt_tokens_details", None), "to_dict", lambda: None)()
            if usage is not None
            else None
        ),
    }


def run(requests: Iterable[Mapping[str, Any]], output_dir: Path) -> int:
    from openai import OpenAI

    rows = list(requests)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    preflight_path = output_dir / "GENERATION_PREFLIGHT_RECEIPT.json"
    attempts_path = output_dir / "GENERATION_ATTEMPT_JOURNAL.jsonl"
    terminal_path = output_dir / "GENERATION_TERMINAL_JOURNAL.jsonl"
    summary_path = output_dir / "GENERATION_EXECUTION_SUMMARY.json"
    runtime = runtime_preflight()
    receipt = {
        "schema_version": "c4-real-generation-preflight-receipt-v1",
        "created_at_utc": utc_now(),
        "request_count": len(rows),
        "request_manifest_sha256": sha256_bytes(
            b"".join(canonical_bytes(row) + b"\n" for row in rows)
        ),
        "runtime": runtime,
        "model": EXPECTED_MODEL,
        "temperature": 0,
        "max_output_tokens": 512,
        "streaming": False,
        "tools": "NONE",
        "maximum_physical_attempts": len(rows) * MAX_ATTEMPTS_PER_REQUEST,
        "automatic_resume": False,
        "judge_calls": 0,
    }
    write_exclusive_json(preflight_path, receipt)
    create_exclusive_empty(attempts_path)
    create_exclusive_empty(terminal_path)

    client = OpenAI(max_retries=0)
    success_count = 0
    physical_attempts = 0
    previous_initial_started: float | None = None
    for logical_order, row in enumerate(rows, 1):
        payload = row.get("provider_payload")
        if not isinstance(payload, Mapping):
            raise ValueError("provider_payload is missing")
        payload = dict(payload)
        if payload.get("model") != EXPECTED_MODEL:
            raise ValueError("frozen model mismatch")
        if sha256_bytes(canonical_bytes(payload)) != row.get("provider_payload_sha256"):
            raise ValueError("provider payload hash mismatch")

        if previous_initial_started is not None:
            remaining = INITIAL_REQUEST_GAP_SECONDS - (time.monotonic() - previous_initial_started)
            if remaining > 0:
                time.sleep(remaining)
        previous_initial_started = time.monotonic()

        terminal_written = False
        for attempt_number in range(1, MAX_ATTEMPTS_PER_REQUEST + 1):
            started = time.perf_counter()
            physical_attempts += 1
            try:
                response = client.chat.completions.create(**payload)
                latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                returned_model = str(getattr(response, "model", ""))
                if returned_model != EXPECTED_MODEL:
                    raise ValueError("RETURNED_MODEL_IDENTITY_MISMATCH")
                raw_content = _response_content(response)
                answer = validate_answer(raw_content)
                choice = response.choices[0]
                attempt_record = {
                    "schema_version": "c4-real-generation-attempt-v1",
                    "logical_order": logical_order,
                    "logical_generation_request_id": row["logical_generation_request_id"],
                    "response_blind_id": row["response_blind_id"],
                    "attempt_number": attempt_number,
                    "provider_payload_sha256": row["provider_payload_sha256"],
                    "provider_response_id": getattr(response, "id", None),
                    "returned_model": returned_model,
                    "system_fingerprint": getattr(response, "system_fingerprint", None),
                    "finish_reason": getattr(choice, "finish_reason", None),
                    "usage": _usage(response),
                    "latency_ms": latency_ms,
                    "validation_status": "VALID" if answer is not None else "INVALID_JSON_OR_SCHEMA",
                    "recorded_at_utc": utc_now(),
                }
                append_fsync(attempts_path, attempt_record)
                if answer is None and attempt_number == 1:
                    continue
                if answer is None:
                    append_fsync(
                        terminal_path,
                        {
                            "schema_version": "c4-real-generation-terminal-v1",
                            "logical_order": logical_order,
                            "logical_generation_request_id": row["logical_generation_request_id"],
                            "response_blind_id": row["response_blind_id"],
                            "terminal_status": "INVALID_JSON_OR_SCHEMA_AFTER_ONE_IDENTICAL_RETRY",
                            "physical_attempts": attempt_number,
                            "provider_payload_sha256": row["provider_payload_sha256"],
                            "recorded_at_utc": utc_now(),
                        },
                    )
                    terminal_written = True
                    break
                append_fsync(
                    terminal_path,
                    {
                        "schema_version": "c4-real-generation-terminal-v1",
                        "logical_order": logical_order,
                        "logical_generation_request_id": row["logical_generation_request_id"],
                        "response_blind_id": row["response_blind_id"],
                        "terminal_status": "VALID_RESPONSE",
                        "physical_attempts": attempt_number,
                        "provider_payload_sha256": row["provider_payload_sha256"],
                        "provider_response_id": getattr(response, "id", None),
                        "returned_model": returned_model,
                        "system_fingerprint": getattr(response, "system_fingerprint", None),
                        "finish_reason": getattr(choice, "finish_reason", None),
                        "usage": _usage(response),
                        "latency_ms": latency_ms,
                        "raw_response_content": raw_content,
                        "answer_text": answer,
                        "recorded_at_utc": utc_now(),
                    },
                )
                success_count += 1
                terminal_written = True
                break
            except Exception as error:
                latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                sanitized = sanitize_error(error)
                append_fsync(
                    attempts_path,
                    {
                        "schema_version": "c4-real-generation-attempt-v1",
                        "logical_order": logical_order,
                        "logical_generation_request_id": row["logical_generation_request_id"],
                        "response_blind_id": row["response_blind_id"],
                        "attempt_number": attempt_number,
                        "provider_payload_sha256": row["provider_payload_sha256"],
                        "validation_status": "NON_RETRYABLE_PROVIDER_OR_RUNTIME_ERROR",
                        "latency_ms": latency_ms,
                        "error": sanitized,
                        "recorded_at_utc": utc_now(),
                    },
                )
                append_fsync(
                    terminal_path,
                    {
                        "schema_version": "c4-real-generation-terminal-v1",
                        "logical_order": logical_order,
                        "logical_generation_request_id": row["logical_generation_request_id"],
                        "response_blind_id": row["response_blind_id"],
                        "terminal_status": "NON_RETRYABLE_ERROR",
                        "physical_attempts": attempt_number,
                        "provider_payload_sha256": row["provider_payload_sha256"],
                        "error": sanitized,
                        "recorded_at_utc": utc_now(),
                    },
                )
                terminal_written = True
                break
        if not terminal_written:
            raise RuntimeError("logical request ended without a terminal record")

    summary = {
        "schema_version": "c4-real-generation-execution-summary-v1",
        "request_count": len(rows),
        "valid_response_count": success_count,
        "terminal_failure_count": len(rows) - success_count,
        "physical_attempt_count": physical_attempts,
        "maximum_physical_attempt_count": len(rows) * MAX_ATTEMPTS_PER_REQUEST,
        "judge_calls": 0,
        "automatic_resume": False,
        "completed_at_utc": utc_now(),
    }
    write_exclusive_json(summary_path, summary)
    return 0 if success_count == len(rows) else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-manifest", type=Path, default=Path("BLINDED_REQUESTS.jsonl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute or os.environ.get("C4_REAL_GENERATION_EXECUTION_AUTHORIZED") != "YES":
        raise SystemExit(
            "Generation is not authorised: require --execute and "
            "C4_REAL_GENERATION_EXECUTION_AUTHORIZED=YES"
        )
    if args.output_dir.exists():
        raise SystemExit("Refusing overwrite or automatic resume: output directory already exists")
    return run(load_jsonl(args.request_manifest), args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
