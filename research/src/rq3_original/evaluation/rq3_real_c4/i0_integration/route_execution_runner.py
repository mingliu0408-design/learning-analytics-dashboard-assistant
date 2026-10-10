#!/usr/bin/env python3
"""Future route-package runner with a hard post-I0 authorization gate.

This file is frozen and packaged in I0 but is not executed in I0. It performs
no work unless a later operator supplies --execute, a package-specific signed-
off authorization record, and an API key. SDK retries are disabled. Exactly
one identical retry is allowed only after invalid strict structured output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.name}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{number} is not an object")
        rows.append(value)
    return rows


def append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    encoded = canonical_bytes(dict(value)) + b"\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(encoded)
        os.fsync(handle.fileno())


def validate_authorization(
    *, authorization: Mapping[str, Any], package_id: str
) -> None:
    required = {
        "authorization_id",
        "authorization_scope",
        "authorized_by",
        "authorized_at",
        "package_id",
        "status",
    }
    if set(authorization) != required:
        raise PermissionError("Authorization record has incorrect strict fields")
    if authorization["status"] != "AUTHORIZED":
        raise PermissionError("Route execution is not authorized")
    if authorization["authorization_scope"] != "RQ3_REAL_C4_P3_ROUTE_EXECUTION":
        raise PermissionError("Authorization scope mismatch")
    if authorization["package_id"] != package_id:
        raise PermissionError("Authorization package mismatch")
    for field in ("authorization_id", "authorized_by", "authorized_at"):
        if not str(authorization[field]).strip():
            raise PermissionError(f"Authorization field is empty: {field}")


def strict_parse(raw_text: str, schema: Mapping[str, Any]) -> dict[str, bool] | None:
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    required = list(schema.get("required") or [])
    if set(value) != set(required):
        return None
    if any(type(value[field]) is not bool for field in required):
        return None
    return {field: value[field] for field in required}


def build_payload(
    *, plan: Mapping[str, Any], prompt: str, schema: Mapping[str, Any],
    examples: Iterable[Mapping[str, Any]], request: Mapping[str, Any]
) -> dict[str, Any]:
    messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
    for example in examples:
        messages.append(
            {"role": "user", "content": canonical_bytes(example["input"]).decode("utf-8")}
        )
        messages.append(
            {"role": "assistant", "content": canonical_bytes(example["output"]).decode("utf-8")}
        )
    messages.append(
        {"role": "user", "content": canonical_bytes(request["semantic_input"]).decode("utf-8")}
    )
    return {
        "model": plan["model"],
        "messages": messages,
        "temperature": 0,
        "max_tokens": plan["max_output_tokens"],
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": plan["response_schema_name"],
                "strict": True,
                "schema": dict(schema),
            },
        },
    }


def execute(package_dir: Path, authorization_path: Path) -> dict[str, int]:
    plan = load_json(package_dir / "EXECUTION_PLAN.json")
    validate_authorization(
        authorization=load_json(authorization_path),
        package_id=str(plan["package_id"]),
    )
    if os.environ.get("RQ3_REAL_P3_EXECUTION_AUTHORIZED") != "YES":
        raise PermissionError("Explicit execution environment gate is not YES")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise PermissionError("OPENAI_API_KEY is absent")

    # The dependency and client are constructed only after all authorization
    # gates pass. max_retries=0 prevents hidden SDK retries.
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=api_key, max_retries=0)
    prompt = (package_dir / "prompt.txt").read_text(encoding="utf-8")
    schema = load_json(package_dir / "schema.json")
    examples_value = load_json(package_dir / "few_shot_examples.json")
    examples = examples_value["few_shot_examples"]
    requests = load_jsonl(package_dir / "requests.jsonl")
    attempts_path = package_dir / "ATTEMPT_JOURNAL.jsonl"
    terminals_path = package_dir / "TERMINAL_JOURNAL.jsonl"
    attempts_path.touch(exist_ok=True)
    terminals_path.touch(exist_ok=True)
    attempt_events = load_jsonl(attempts_path)
    terminal_events = load_jsonl(terminals_path)
    started = {}
    for event in attempt_events:
        if event.get("event") == "PROVIDER_CALL_STARTED":
            started[event["scenario_id"]] = started.get(event["scenario_id"], 0) + 1
    terminal_by_id = {event["scenario_id"]: event for event in terminal_events}

    completed = failed = physical_attempts = 0
    for request in requests:
        scenario_id = str(request["scenario_id"])
        if scenario_id in terminal_by_id:
            continue
        payload = build_payload(
            plan=plan,
            prompt=prompt,
            schema=schema,
            examples=examples,
            request=request,
        )
        payload_hash = sha256(canonical_bytes(payload))
        prior = int(started.get(scenario_id, 0))
        if prior >= 2:
            append_fsync(
                terminals_path,
                {
                    "event": "TERMINAL_FAILED_ATTEMPT_CEILING",
                    "scenario_id": scenario_id,
                    "semantic_input_sha256": request["semantic_input_sha256"],
                    "request_payload_sha256": payload_hash,
                },
            )
            failed += 1
            continue
        for attempt_number in range(prior + 1, 3):
            append_fsync(
                attempts_path,
                {
                    "attempt_number": attempt_number,
                    "event": "PROVIDER_CALL_STARTED",
                    "request_payload_sha256": payload_hash,
                    "scenario_id": scenario_id,
                    "semantic_input_sha256": request["semantic_input_sha256"],
                },
            )
            physical_attempts += 1
            try:
                response = client.chat.completions.create(**payload)
                raw_text = response.choices[0].message.content or ""
            except Exception as error:
                append_fsync(
                    terminals_path,
                    {
                        "error_type": type(error).__name__,
                        "event": "TERMINAL_PROVIDER_ERROR_NO_RETRY",
                        "request_payload_sha256": payload_hash,
                        "scenario_id": scenario_id,
                        "semantic_input_sha256": request["semantic_input_sha256"],
                    },
                )
                failed += 1
                break
            parsed = strict_parse(raw_text, schema)
            if parsed is not None:
                append_fsync(
                    terminals_path,
                    {
                        "attempt_number": attempt_number,
                        "event": "TERMINAL_SUCCESS",
                        "output": parsed,
                        "raw_response_sha256": sha256(raw_text.encode("utf-8")),
                        "request_payload_sha256": payload_hash,
                        "scenario_id": scenario_id,
                        "semantic_input_sha256": request["semantic_input_sha256"],
                    },
                )
                completed += 1
                break
            if attempt_number == 2:
                append_fsync(
                    terminals_path,
                    {
                        "attempt_number": attempt_number,
                        "event": "TERMINAL_INVALID_STRICT_OUTPUT",
                        "raw_response_sha256": sha256(raw_text.encode("utf-8")),
                        "request_payload_sha256": payload_hash,
                        "scenario_id": scenario_id,
                        "semantic_input_sha256": request["semantic_input_sha256"],
                    },
                )
                failed += 1
    return {"completed": completed, "failed": failed, "physical_attempts": physical_attempts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorization-record", type=Path)
    parser.add_argument("--package-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("NO_EXECUTION: --execute was not supplied")
    if args.authorization_record is None:
        raise SystemExit("NO_EXECUTION: --authorization-record is required")
    result = execute(args.package_dir.resolve(), args.authorization_record.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
