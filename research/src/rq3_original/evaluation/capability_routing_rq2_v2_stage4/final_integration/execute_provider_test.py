"""Future-only provider executor for one frozen Stage 4N TEST manifest.

Stage 4N does not run this file.  A later execution task must pass the exact
authorization token and an unmodified 36-record manifest.  The SDK has zero
transport retries; one same-payload manual retry is allowed only after invalid
JSON or strict-schema failure.  No scoring or Gold access exists here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping


AUTHORIZATION_TOKEN = "RQ2_V2_FINAL_TEST_PREDICTION_EXECUTION_AUTHORIZED"
MODEL = "gpt-4o-mini-2024-07-18"
MAX_LOGICAL_CALLS = 36
MAX_PHYSICAL_ATTEMPTS = 72
PRIMARY_FIELDS = {
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
}
FORBIDDEN_TEST_KEYS = {
    "gold", "scenario_family_id", "writer_id", "writer_identity",
    "contrast_id", "contrast_group_id", "partition", "split",
    "rag_context_state", "memory_context_state", "dialogue_action",
}


class ExecutionBoundaryError(RuntimeError):
    """Raised before or during a future run when a frozen boundary differs."""


def sha256_value(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExecutionBoundaryError(f"manifest line {number} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ExecutionBoundaryError(f"manifest line {number} is not an object")
        rows.append(value)
    if len(rows) != MAX_LOGICAL_CALLS:
        raise ExecutionBoundaryError("manifest must contain exactly 36 logical records")
    return rows


def _forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_TEST_KEYS or normalized.startswith("gold_"):
                found.add(str(key))
            found.update(_forbidden_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_forbidden_keys(nested))
    return found


def validate_manifest(rows: list[dict[str, Any]]) -> tuple[str, set[str]]:
    annotation_ids: set[str] = set()
    method_ids: set[str] = set()
    logical_ids: set[str] = set()
    for row in rows:
        if row.get("execution_status") != "NOT_EXECUTED":
            raise ExecutionBoundaryError("manifest includes an executed logical record")
        if row.get("model_snapshot") != MODEL:
            raise ExecutionBoundaryError("model snapshot differs")
        annotation_id = str(row.get("annotation_case_id") or "")
        logical_id = str(row.get("logical_call_id") or "")
        method_id = str(row.get("method_id") or "")
        if not annotation_id or annotation_id in annotation_ids:
            raise ExecutionBoundaryError("annotation IDs must be non-empty and unique")
        if not logical_id or logical_id in logical_ids:
            raise ExecutionBoundaryError("logical call IDs must be non-empty and unique")
        annotation_ids.add(annotation_id)
        logical_ids.add(logical_id)
        method_ids.add(method_id)
        semantic = {key: row.get(key) for key in PRIMARY_FIELDS}
        if _forbidden_keys(semantic):
            raise ExecutionBoundaryError("TEST semantic input contains prohibited metadata")
        payload = row.get("provider_request_payload")
        if not isinstance(payload, dict) or _forbidden_keys(payload):
            raise ExecutionBoundaryError("provider payload contains prohibited TEST metadata")
        if sha256_value(payload) != row.get("provider_request_payload_sha256"):
            raise ExecutionBoundaryError("provider request payload hash differs")
        controls = row.get("execution_controls") or {}
        expected_controls = {
            "temperature": 0,
            "sdk_transport_retries": 0,
            "manual_retry_max": 1,
            "prompt_change_on_retry": False,
        }
        for key, expected in expected_controls.items():
            if controls.get(key) != expected:
                raise ExecutionBoundaryError(f"execution control differs: {key}")
        if controls.get("manual_retry_only_after") != [
            "INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"
        ]:
            raise ExecutionBoundaryError("manual retry reasons differ")
        if payload.get("model") != MODEL or payload.get("temperature") != 0:
            raise ExecutionBoundaryError("provider payload model or temperature differs")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ExecutionBoundaryError("provider messages are missing")
        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "user":
            raise ExecutionBoundaryError("final provider message is not the TEST input")
        try:
            test_input = json.loads(str(last.get("content") or ""))
        except json.JSONDecodeError as exc:
            raise ExecutionBoundaryError("final provider TEST message is invalid JSON") from exc
        if not isinstance(test_input, dict) or set(test_input) != PRIMARY_FIELDS:
            raise ExecutionBoundaryError("final provider TEST message fields differ")
        if test_input != semantic:
            raise ExecutionBoundaryError("provider TEST message differs from manifest input")
    if len(method_ids) != 1 or "" in method_ids:
        raise ExecutionBoundaryError("one manifest must contain exactly one method")
    return next(iter(method_ids)), annotation_ids


def validate_prediction(content: str, schema: Mapping[str, Any]) -> tuple[dict[str, bool] | None, str | None]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, "INVALID_JSON"
    required = list(schema.get("required") or [])
    properties = schema.get("properties") or {}
    if (
        not isinstance(parsed, dict)
        or set(parsed) != set(required)
        or set(parsed) != set(properties)
        or any(not isinstance(parsed.get(key), bool) for key in required)
        or schema.get("additionalProperties") is not False
    ):
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    return {key: parsed[key] for key in required}, None


_SECRET = re.compile(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._~-]{8,})", re.I)


def safe_error(error: BaseException) -> str:
    return _SECRET.sub("[REDACTED_SECRET]", str(error))[:2000]


def physical_attempt(client: Any, record: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**record["provider_request_payload"])
    except Exception as exc:
        return {
            "outcome": "PROVIDER_ERROR",
            "returned_model": None,
            "response_id": None,
            "content": None,
            "prediction": None,
            "validation_error": "PROVIDER_ERROR",
            "provider_error": safe_error(exc),
            "latency_seconds": round(time.perf_counter() - started, 6),
            "usage": None,
        }
    returned_model = str(getattr(response, "model", "") or "")
    choices = list(getattr(response, "choices", []) or [])
    message = getattr(choices[0], "message", None) if choices else None
    content = str(getattr(message, "content", "") or "")
    refusal = getattr(message, "refusal", None)
    schema = record["provider_request_payload"]["response_format"]["json_schema"]["schema"]
    prediction, validation_error = validate_prediction(content, schema)
    if returned_model != MODEL:
        validation_error = "RETURNED_MODEL_MISMATCH"
        prediction = None
    if refusal:
        validation_error = "PROVIDER_REFUSAL"
        prediction = None
    usage = getattr(response, "usage", None)
    return {
        "outcome": "VALID" if validation_error is None else validation_error,
        "returned_model": returned_model or None,
        "response_id": str(getattr(response, "id", "") or "") or None,
        "content": content,
        "prediction": prediction,
        "validation_error": validation_error,
        "provider_error": None,
        "latency_seconds": round(time.perf_counter() - started, 6),
        "usage": None if usage is None else {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
    }


def append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def execute(rows: list[dict[str, Any]], output_path: Path) -> None:
    if output_path.exists() or output_path.with_suffix(output_path.suffix + ".partial").exists():
        raise ExecutionBoundaryError("output or partial output already exists")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ExecutionBoundaryError("OPENAI_API_KEY is missing")
    from openai import OpenAI

    client = OpenAI(max_retries=0)
    if getattr(client, "max_retries", None) != 0:
        raise ExecutionBoundaryError("OpenAI SDK retries are not zero")
    partial = output_path.with_suffix(output_path.suffix + ".partial")
    physical_count = 0
    for row in rows:
        attempts: list[dict[str, Any]] = []
        first = physical_attempt(client, row)
        physical_count += 1
        attempts.append(first)
        retryable = first["validation_error"] in {
            "INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"
        }
        if retryable:
            if physical_count >= MAX_PHYSICAL_ATTEMPTS + 1:
                raise ExecutionBoundaryError("physical-attempt ceiling would be exceeded")
            second = physical_attempt(client, row)
            physical_count += 1
            attempts.append(second)
        terminal = attempts[-1]
        if terminal["outcome"] == "VALID":
            status = "VALID_PREDICTION"
        elif terminal["outcome"] == "PROVIDER_ERROR":
            status = "PROVIDER_ERROR"
        else:
            status = "INVALID_TERMINAL_RESULT"
        result = {
            "schema_version": "rq2-v2-stage4n-provider-test-terminal-result-v1",
            "logical_case_id": row["logical_case_id"],
            "logical_call_id": row["logical_call_id"],
            "annotation_case_id": row["annotation_case_id"],
            "method_id": row["method_id"],
            "execution_status": status,
            "physical_attempts": len(attempts),
            "attempt_records": attempts,
            "prediction": terminal["prediction"],
            "scoring_performed": False,
        }
        append_fsync(partial, result)
    if physical_count > MAX_PHYSICAL_ATTEMPTS:
        raise ExecutionBoundaryError("physical-attempt ceiling exceeded")
    os.replace(partial, output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorization-token", required=True)
    args = parser.parse_args()
    if args.authorization_token != AUTHORIZATION_TOKEN:
        raise ExecutionBoundaryError("separate final-TEST prediction authority is absent")
    rows = load_manifest(args.manifest.resolve())
    method_id, _ids = validate_manifest(rows)
    execute(rows, args.output.resolve())
    print(f"PASS executed 36 future logical calls for {method_id}; no scoring performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
