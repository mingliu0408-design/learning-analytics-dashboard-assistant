#!/usr/bin/env python3
"""Strict offline validator for one unpacked C4 generation shard package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ALLOWED_FILES = frozenset(
    {
        "README.md",
        "BLINDED_REQUESTS.jsonl",
        "GENERATION_PROMPT.txt",
        "GENERATION_SCHEMA.json",
        "GENERATION_CONFIGURATION.json",
        "generation_runner.py",
        "validate_package.py",
        "test_package.py",
        "EXECUTION_CONTRACT.json",
        "PACKAGE_SOURCE_HASHES.json",
    }
)
_SCENARIO = re.compile(r"\bU\d{3}\b")
_MODE = re.compile(
    r"\bC(?:0_ORIGINAL|1_EVIDENCE|2_EVIDENCE_RAG|3_EVIDENCE_MEMORY|"
    r"4_EVIDENCE_PLANNING|5_FULL_C4|5_MINUS_RAG|5_MINUS_MEMORY|5_MINUS_PLANNING)\b"
)
_LOCAL = re.compile(
    r"(?:/Users/|/private/|/var/folders/|file://|"
    r"(?:^|\s)(?:evaluation|utils|input|course_materials_v2|System Data)/|"
    r"\.sqlite(?:3)?\b)",
    re.IGNORECASE,
)
_INTERNAL_ROUTE = re.compile(r"\b(?:R2V2|C4-P3-|P3)\b")
_SECRET = re.compile(rb"(?:sk-[A-Za-z0-9_-]{12,}|OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)")
_LOGICAL_ID = re.compile(r"^C4G-[A-F0-9]{24}$")
_RESPONSE_ID = re.compile(r"^R3B-[A-F0-9]{20}$")
_FORBIDDEN_KEYS = {
    "path",
    "file_path",
    "file",
    "filename",
    "files",
    "source_file",
    "source_files",
    "source_notes",
    "source_path",
    "source_sha256",
    "sha256",
    "evidence_id",
    "chunk_id",
    "document_id",
    "memory_id",
    "database_path",
    "source_session_id",
    "source_turn_id",
    "student_id",
    "scenario_id",
    "mode",
    "mode_id",
    "condition",
    "condition_id",
    "condition_name",
    "route",
    "route_id",
    "method_id",
    "decision_id",
    "lexical_score",
    "dense_score",
    "semantic_score",
    "fusion_score",
    "embedding",
    "embeddings",
    "cache_key",
    "internal_cache_key",
    "gold",
    "gold_label",
    "expected_label",
    "expected_labels",
    "expected_capabilities",
    "reference_answer",
    "historical_judge_score",
    "compiled_evidence_sha256",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk(value: Any) -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_KEYS & set(value)
        if forbidden:
            raise ValueError(f"forbidden provider/request keys: {sorted(forbidden)}")
        for nested in value.values():
            walk(nested)
    elif isinstance(value, list):
        for nested in value:
            walk(nested)
    elif isinstance(value, str):
        if (
            _SCENARIO.search(value)
            or _MODE.search(value)
            or _LOCAL.search(value)
            or _INTERNAL_ROUTE.search(value)
        ):
            raise ValueError(
                "request package exposes a scenario, mode, route, or local path"
            )


def validate(root: Path) -> Mapping[str, Any]:
    entries = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("package must contain regular files only")
    files = {path.name for path in entries}
    if files != ALLOWED_FILES:
        raise ValueError(f"package allowlist mismatch: {sorted(files ^ ALLOWED_FILES)}")
    hashes = json.loads((root / "PACKAGE_SOURCE_HASHES.json").read_text(encoding="utf-8"))
    expected = hashes.get("member_sha256_excluding_self")
    if not isinstance(expected, dict) or set(expected) != ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"}:
        raise ValueError("source-hash manifest member set mismatch")
    for name, digest in expected.items():
        if sha256(root / name) != digest:
            raise ValueError(f"source hash mismatch: {name}")
    if _SECRET.search(b"\n".join((root / name).read_bytes() for name in sorted(files))):
        raise ValueError("package contains a credential-like value")
    rows = [json.loads(line) for line in (root / "BLINDED_REQUESTS.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        raise ValueError("blinded request manifest is empty")
    logical_ids: set[str] = set()
    response_ids: set[str] = set()
    for row in rows:
        if set(row) != {
            "schema_version",
            "logical_generation_request_id",
            "response_blind_id",
            "provider_payload_sha256",
            "estimated_input_tokens",
            "provider_payload",
        }:
            raise ValueError("blinded request fields mismatch")
        logical_ids.add(str(row["logical_generation_request_id"]))
        response_ids.add(str(row["response_blind_id"]))
        if not _LOGICAL_ID.fullmatch(str(row["logical_generation_request_id"])):
            raise ValueError("logical request ID is not opaque or version-compatible")
        if not _RESPONSE_ID.fullmatch(str(row["response_blind_id"])):
            raise ValueError("response ID is not opaque or version-compatible")
        payload = row["provider_payload"]
        if hashlib.sha256(canonical_bytes(payload)).hexdigest() != row["provider_payload_sha256"]:
            raise ValueError("provider payload hash mismatch")
        walk(row)
    if len(logical_ids) != len(rows) or len(response_ids) != len(rows):
        raise ValueError("opaque request or response IDs are not unique")
    config = json.loads((root / "GENERATION_CONFIGURATION.json").read_text(encoding="utf-8"))
    if (
        config.get("model") != "gpt-4o-mini-2024-07-18"
        or config.get("temperature") != 0
        or config.get("max_output_tokens") != 512
        or config.get("automatic_sdk_retries") != 0
        or config.get("streaming") is not False
        or config.get("tools") != "NONE"
        or config.get("generation_execution_authorised") is not False
    ):
        raise ValueError("frozen generation configuration mismatch")
    schema = json.loads((root / "GENERATION_SCHEMA.json").read_text(encoding="utf-8"))
    if schema != {
        "type": "object",
        "properties": {"answer_text": {"type": "string"}},
        "required": ["answer_text"],
        "additionalProperties": False,
    }:
        raise ValueError("provider-compatible generation schema mismatch")
    contract = json.loads((root / "EXECUTION_CONTRACT.json").read_text(encoding="utf-8"))
    if (
        contract.get("status") != "PREPARED_NOT_AUTHORISED"
        or contract.get("request_count") != len(rows)
        or contract.get("maximum_physical_attempt_count") != len(rows) * 2
        or contract.get("provider_calls_during_package_preparation") != 0
        or contract.get("judge_calls") != 0
    ):
        raise ValueError("execution contract mismatch")
    return {
        "status": "PASS",
        "request_count": len(rows),
        "estimated_input_tokens": sum(int(row["estimated_input_tokens"]) for row in rows),
        "allowlisted_file_count": len(files),
    }


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(json.dumps(validate(root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
