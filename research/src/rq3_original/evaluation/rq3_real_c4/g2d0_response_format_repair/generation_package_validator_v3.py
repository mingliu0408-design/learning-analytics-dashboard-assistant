#!/usr/bin/env python3
"""Strict offline validator for one unpacked C4 REAL regeneration R3 package."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping
import zipfile

try:
    from .c4_real_student_facing_response_validator_v1 import (
        VALID_STUDENT_FACING_RESPONSE,
        validate_answer_text,
    )
except ImportError:
    from c4_real_student_facing_response_validator_v1 import (
        VALID_STUDENT_FACING_RESPONSE,
        validate_answer_text,
    )


ALLOWED_FILES = frozenset(
    {
        "README.md",
        "BLINDED_REQUESTS.jsonl",
        "GENERATION_PROMPT.txt",
        "GENERATION_SCHEMA.json",
        "GENERATION_CONFIGURATION.json",
        "STUDENT_FACING_FORMAT_CONTRACT.json",
        "EXECUTION_CONTRACT.json",
        "generation_execution_runner_v3.py",
        "c4_real_student_facing_response_validator_v1.py",
        "validate_package.py",
        "test_package.py",
        "PACKAGE_SOURCE_HASHES.json",
    }
)
PROMPT_SHA256 = "c72c9982899902221d1da6d67724c2058547b0641a285a7c28d9bafd12ec63cb"
SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
CONFIG_SHA256 = "8a4a4a07137336d058645820bdd9d32091afb4df3513ec6324d380015454b138"
FORMAT_CONTRACT_SHA256 = "e68165bc78294beb490ea37ae45752ce2a41ee4232ae5127cd9d2e7ee6336319"
VALIDATOR_SHA256 = "5b098ff2e8368a7830938ae83ea4ea5cbdcdf71fcf61b674c579118c4742fbcc"
MODEL = "gpt-4o-mini-2024-07-18"
AUTHORIZATION_GATE = "AUTHORIZED_C4_REAL_RESPONSE_REGENERATION_R3"
_LOGICAL_ID = re.compile(r"^C4G3-[A-F0-9]{24}$")
_RESPONSE_ID = re.compile(r"^R3B3-[A-F0-9]{20}$")
_PACKAGE_ID = re.compile(r"^C4_REAL_GENERATION_SHARD_([ABC])_R3_20260901$")
_SCENARIO = re.compile(r"\bU\d{3}\b")
_MODE = re.compile(
    r"\bC(?:0_ORIGINAL|1_EVIDENCE|2_EVIDENCE_RAG|3_EVIDENCE_MEMORY|"
    r"4_EVIDENCE_PLANNING|5_FULL_C4|5_MINUS_RAG|5_MINUS_MEMORY|5_MINUS_PLANNING)\b"
)
_ROUTE_OR_P3 = re.compile(r"\b(?:R2V2|C4-P3-|P3_GATE|P3)\b", re.IGNORECASE)
_LOCAL = re.compile(r"(?:/Users/|/private/|/var/folders/|file://|\.sqlite(?:3)?\b)", re.IGNORECASE)
_HASH = re.compile(r"\b[0-9a-fA-F]{64}\b")
_RAW_INTERNAL_KEY = re.compile(
    r"(?m)(?:\"|')?(?:action_steps|recommended_action|student_state|main_issue|"
    r"next_steps|next_step|evidence|availability_notes|supporting_evidence|"
    r"reflection_summary|activity_summary|data_summary|gaps_identified|planning_support)"
    r"(?:\"|')?\s*:"
)
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_plain_text_user_message(message: str) -> None:
    if not message.startswith("CURRENT LAD PAGE\n") or "\n\nSTUDENT REQUEST\n" not in message:
        raise ValueError("V3 plain-text request sections are missing")
    try:
        parsed = json.loads(message)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, (dict, list)):
        raise ValueError("V3 user message is a raw JSON object or array")
    for pattern, label in (
        (_SCENARIO, "scenario identity"),
        (_MODE, "mode identity"),
        (_ROUTE_OR_P3, "route or P3 identity"),
        (_LOCAL, "path or database"),
        (_HASH, "hash"),
        (_RAW_INTERNAL_KEY, "raw internal serialized key"),
    ):
        if pattern.search(message):
            raise ValueError(f"provider user message exposes {label}")


def _validate_payload(row: Mapping[str, Any], prompt: str, schema: Mapping[str, Any]) -> None:
    if set(row) != {
        "schema_version",
        "logical_generation_request_id",
        "response_blind_id",
        "provider_payload_sha256",
        "estimated_input_tokens",
        "provider_payload",
    } or row.get("schema_version") != "c4-real-blinded-generation-request-v3":
        raise ValueError("blinded request V3 fields or schema mismatch")
    if not _LOGICAL_ID.fullmatch(str(row.get("logical_generation_request_id", ""))):
        raise ValueError("logical generation request ID is not opaque V3")
    if not _RESPONSE_ID.fullmatch(str(row.get("response_blind_id", ""))):
        raise ValueError("response blind ID is not opaque V3")
    if not isinstance(row.get("estimated_input_tokens"), int) or row["estimated_input_tokens"] <= 0:
        raise ValueError("estimated input tokens must be positive")
    payload = row.get("provider_payload")
    if not isinstance(payload, Mapping) or set(payload) != {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "stream",
        "response_format",
    }:
        raise ValueError("provider payload transport fields mismatch")
    if hashlib.sha256(canonical_bytes(payload)).hexdigest() != row.get("provider_payload_sha256"):
        raise ValueError("provider payload canonical hash mismatch")
    if (
        payload.get("model") != MODEL
        or payload.get("temperature") != 0
        or payload.get("max_tokens") != 512
        or payload.get("stream") is not False
        or "tools" in payload
    ):
        raise ValueError("provider payload frozen configuration mismatch")
    messages = payload.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or messages[0] != {"role": "system", "content": prompt}
        or not isinstance(messages[1], Mapping)
        or set(messages[1]) != {"role", "content"}
        or messages[1].get("role") != "user"
        or not isinstance(messages[1].get("content"), str)
    ):
        raise ValueError("provider message construction mismatch")
    _validate_plain_text_user_message(messages[1]["content"])
    expected_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "c4_real_generation_response_v2_provider_compatible",
            "strict": True,
            "schema": dict(schema),
        },
    }
    if payload.get("response_format") != expected_format:
        raise ValueError("outer provider response schema changed")


def _validate_semantic_validator() -> None:
    rejected = (
        "{",
        "[",
        "{}",
        "[]",
        '{"answer":"raw object"}',
        '["raw array"]',
        "{'action_steps': ['Do this'], 'recommended_action': 'Do it'}",
        '{"evidence":{"content":"raw"}}',
    )
    accepted = (
        "Review the Week 4 lecture.",
        "Yes.",
        "- Review the lecture\n- Write one note",
        "1. Review the lecture\n2. Write one note",
    )
    if any(validate_answer_text(value) == VALID_STUDENT_FACING_RESPONSE for value in rejected):
        raise ValueError("semantic validator accepted a required rejection case")
    if any(validate_answer_text(value) != VALID_STUDENT_FACING_RESPONSE for value in accepted):
        raise ValueError("semantic validator rejected an allowed natural-language form")


def _validate_runner_source(source: str) -> None:
    required = (
        "--authorization-record",
        "--package-zip",
        "--execute",
        AUTHORIZATION_GATE,
        "OpenAI(max_retries=0)",
        "MAX_ATTEMPTS_PER_REQUEST = 2",
        "INVALID_JSON",
        "STRICT_SCHEMA_VALIDATION_FAILED",
        "NON_STUDENT_FACING_FORMAT",
        "validate_response_content",
        "validate_answer_text",
        "RETRY_PAYLOAD_BYTES_CHANGED",
        "client.chat.completions.create(**json.loads(payload_bytes))",
        "append_fsync(attempts_path, record)",
        "INCOMPLETE_AFTER_SECOND_INVALID_RESPONSE",
        "return stop_before_or_during_requests",
        "GENERATION_ERROR_REGISTRY.jsonl",
        "Refusing overwrite or automatic resume",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise ValueError(f"Runner V3 fail-closed markers missing: {missing}")
    outer_parse = source.find("parsed = json.loads(raw_content)")
    semantic_call = source.find("semantic_status = validate_answer_text(answer_text)")
    if min(outer_parse, semantic_call) < 0 or outer_parse >= semantic_call:
        raise ValueError("semantic validator does not run after outer JSON parsing")
    retry_call = source.find("client.chat.completions.create(**json.loads(payload_bytes))")
    if retry_call < 0 or "correction message" in source.casefold():
        raise ValueError("Runner V3 retry payload contract is invalid")
    receipt_write = source.find('write_exclusive_json(\n        output_dir / "GENERATION_PREFLIGHT_RECEIPT.json"')
    runtime_call = source.find("runtime_checker()", receipt_write)
    client_call = source.find("client_factory()", receipt_write)
    if min(receipt_write, runtime_call, client_call) < 0 or not receipt_write < runtime_call < client_call:
        raise ValueError("preflight receipt is not durable before runtime/client construction")


def validate(root: Path) -> Mapping[str, Any]:
    root = root.resolve()
    entries = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("package must contain regular files only")
    files = {path.name for path in entries}
    if files != ALLOWED_FILES:
        raise ValueError(f"package allowlist mismatch: {sorted(files ^ ALLOWED_FILES)}")
    source_hashes = json.loads((root / "PACKAGE_SOURCE_HASHES.json").read_text(encoding="utf-8"))
    expected_hashes = source_hashes.get("member_sha256_excluding_self")
    if not isinstance(expected_hashes, dict) or set(expected_hashes) != ALLOWED_FILES - {
        "PACKAGE_SOURCE_HASHES.json"
    }:
        raise ValueError("package source-hash member set mismatch")
    for name, digest in expected_hashes.items():
        if not isinstance(digest, str) or sha256(root / name) != digest:
            raise ValueError(f"package member hash mismatch: {name}")
    if _SECRET.search(b"\n".join((root / name).read_bytes() for name in sorted(files))):
        raise ValueError("package contains a credential-like value")
    frozen_hashes = {
        "GENERATION_PROMPT.txt": PROMPT_SHA256,
        "GENERATION_SCHEMA.json": SCHEMA_SHA256,
        "GENERATION_CONFIGURATION.json": CONFIG_SHA256,
        "STUDENT_FACING_FORMAT_CONTRACT.json": FORMAT_CONTRACT_SHA256,
        "c4_real_student_facing_response_validator_v1.py": VALIDATOR_SHA256,
    }
    for name, expected in frozen_hashes.items():
        if sha256(root / name) != expected:
            raise ValueError(f"frozen package source hash mismatch: {name}")

    prompt = (root / "GENERATION_PROMPT.txt").read_text(encoding="utf-8")
    required_prompt_phrases = (
        "complete natural-language reply addressed to the student",
        "Do not begin answer_text with \"{\" or \"[\"",
        "ordinary prose or concise Markdown bullets",
        "short complete sentence",
        "Do not output any raw internal structure",
    )
    if any(phrase not in prompt for phrase in required_prompt_phrases):
        raise ValueError("V3 prompt natural-language contract is incomplete")
    schema = json.loads((root / "GENERATION_SCHEMA.json").read_text(encoding="utf-8"))
    if schema != {
        "type": "object",
        "properties": {"answer_text": {"type": "string"}},
        "required": ["answer_text"],
        "additionalProperties": False,
    }:
        raise ValueError("provider-compatible outer schema changed")
    config = json.loads((root / "GENERATION_CONFIGURATION.json").read_text(encoding="utf-8"))
    if (
        config.get("model") != MODEL
        or config.get("temperature") != 0
        or config.get("max_output_tokens") != 512
        or config.get("automatic_sdk_retries") != 0
        or config.get("streaming") is not False
        or config.get("tools") != "NONE"
        or config.get("generation_execution_authorised") is not False
        or config.get("response_generation_executed") is not False
        or config.get("semantic_validation_after_strict_outer_schema") is not True
    ):
        raise ValueError("frozen V3 generation configuration content mismatch")

    rows = [
        json.loads(line)
        for line in (root / "BLINDED_REQUESTS.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("blinded request manifest is empty")
    for row in rows:
        _validate_payload(row, prompt, schema)
    logical_ids = [row["logical_generation_request_id"] for row in rows]
    response_ids = [row["response_blind_id"] for row in rows]
    if len(set(logical_ids)) != len(rows) or len(set(response_ids)) != len(rows):
        raise ValueError("opaque request or response IDs are not unique")
    if logical_ids != sorted(logical_ids):
        raise ValueError("blinded requests are not deterministically ordered")

    contract = json.loads((root / "EXECUTION_CONTRACT.json").read_text(encoding="utf-8"))
    package_match = _PACKAGE_ID.fullmatch(str(contract.get("package_id", "")))
    if package_match is None or package_match.group(1) != contract.get("shard"):
        raise ValueError("execution contract package ID or shard mismatch")
    if (
        contract.get("schema_version") != "c4-real-generation-execution-contract-v3"
        or contract.get("status") != "PREPARED_NOT_AUTHORIZED"
        or contract.get("request_count") != len(rows)
        or contract.get("maximum_physical_attempts") != len(rows) * 2
        or contract.get("authorization_record_required") is not True
        or contract.get("authorization_environment_value") != AUTHORIZATION_GATE
        or contract.get("semantic_validation_after_strict_outer_schema") is not True
        or contract.get("identical_retry_payload") is not True
        or contract.get("correction_message_on_retry") is not False
        or contract.get("provider_calls_during_package_preparation") != 0
        or contract.get("response_generation_during_package_preparation") != 0
        or contract.get("judge_calls") != 0
        or contract.get("scoring_calls") != 0
    ):
        raise ValueError("execution contract fail-closed fields mismatch")
    if (
        source_hashes.get("schema_version") != "c4-real-generation-package-source-hashes-v3"
        or source_hashes.get("package_id") != contract.get("package_id")
        or source_hashes.get("shard") != contract.get("shard")
        or source_hashes.get("request_count") != len(rows)
        or source_hashes.get("blinded_manifest_sha256") != sha256(root / "BLINDED_REQUESTS.jsonl")
        or source_hashes.get("restricted_mapping_included") is not False
        or source_hashes.get("hmac_key_included") is not False
        or source_hashes.get("g2_answers_included") is not False
        or source_hashes.get("existing_execution_results_included") is not False
        or source_hashes.get("provider_calls") != 0
        or source_hashes.get("generation_calls") != 0
        or source_hashes.get("judge_calls") != 0
        or source_hashes.get("scoring_calls") != 0
    ):
        raise ValueError("package source/manifest binding mismatch")
    _validate_semantic_validator()
    _validate_runner_source((root / "generation_execution_runner_v3.py").read_text(encoding="utf-8"))
    return {
        "status": "PASS",
        "package_id": contract["package_id"],
        "shard": contract["shard"],
        "request_count": len(rows),
        "estimated_input_tokens": sum(int(row["estimated_input_tokens"]) for row in rows),
        "maximum_physical_attempts": len(rows) * 2,
        "allowlisted_file_count": len(files),
        "plain_text_user_message_count": len(rows),
        "raw_json_user_message_count": 0,
        "semantic_validator_status": "PASS",
    }


def validate_zip(path: Path) -> Mapping[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != ALLOWED_FILES:
            raise ValueError("ZIP member allowlist mismatch")
        if any(name.endswith("/") or Path(name).name != name for name in names):
            raise ValueError("ZIP contains a nested or directory member")
        with tempfile.TemporaryDirectory(prefix="c4-real-r3-validate-") as temporary:
            root = Path(temporary)
            archive.extractall(root)
            report = dict(validate(root))
    report["package_zip_sha256"] = sha256(path)
    return report


def main() -> int:
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    report = validate_zip(target) if target.suffix.casefold() == ".zip" else validate(target)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
