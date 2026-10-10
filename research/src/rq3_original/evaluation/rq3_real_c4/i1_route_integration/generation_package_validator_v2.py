#!/usr/bin/env python3
"""Strict offline validator for one unpacked C4 REAL generation R2 package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping
import zipfile


ALLOWED_FILES = frozenset(
    {
        "README.md",
        "BLINDED_REQUESTS.jsonl",
        "GENERATION_PROMPT.txt",
        "GENERATION_SCHEMA.json",
        "GENERATION_CONFIGURATION.json",
        "EXECUTION_CONTRACT.json",
        "generation_execution_runner_v2.py",
        "validate_package.py",
        "test_package.py",
        "PACKAGE_SOURCE_HASHES.json",
    }
)
PROMPT_SHA256 = "41748d1f3a69ce6623e607551a8473228c0724871e16e392ecd7872b4e550b21"
SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
CONFIG_SHA256 = "3a589b593c964288ab5976718dd4fcb1e2d45186d978ee201b235a7aaf25059c"
MODEL = "gpt-4o-mini-2024-07-18"
AUTHORIZATION_GATE = "AUTHORIZED_C4_REAL_RESPONSE_GENERATION_R2"
_LOGICAL_ID = re.compile(r"^C4G-[A-F0-9]{24}$")
_RESPONSE_ID = re.compile(r"^R3B-[A-F0-9]{20}$")
_PACKAGE_ID = re.compile(r"^C4_REAL_GENERATION_SHARD_([ABC])_R2_20260901$")
_SCENARIO = re.compile(r"\bU\d{3}\b")
_MODE = re.compile(
    r"\bC(?:0_ORIGINAL|1_EVIDENCE|2_EVIDENCE_RAG|3_EVIDENCE_MEMORY|"
    r"4_EVIDENCE_PLANNING|5_FULL_C4|5_MINUS_RAG|5_MINUS_MEMORY|5_MINUS_PLANNING)\b"
)
_LOCAL = re.compile(
    r"(?:/Users/|/private/|/var/folders/|file://|\.sqlite(?:3)?\b)", re.IGNORECASE
)
_INTERNAL_ROUTE = re.compile(r"\b(?:R2V2|C4-P3-|P3_GATE)\b", re.IGNORECASE)
_PROHIBITED_TEXT = re.compile(
    r"(?:TRACK_M_RESEARCH_ONLY_NOT_C4_INTEGRATED|"
    r"P3_GATE_NOT_EXECUTED_IN_TRACK_M|NO_ELIGIBLE_ACTIVE_MEMORY|"
    r"FROZEN_(?:OUTPUT_LEVEL_EVIDENCE_PACK|STRUCTURED_OUTPUT|TYPED_EMPTY_OUTPUT_LEVEL_PACK)|"
    r"Reviewed output-level Dashboard evidence|raw DataFrames were not available in I0|"
    r"Frozen legacy lexical scoring|no dense representation|"
    r"c4-real-provider-evidence-projection-v[12]|"
    r"research only|not integrated|internal cache status|implementation-stage)",
    re.IGNORECASE,
)
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)
_FORBIDDEN_PROVIDER_KEYS = frozenset(
    {
        "path",
        "file_path",
        "filename",
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
)
_PROHIBITED_EVIDENCE_KEYS = frozenset(
    {"schema_version", "evidence_type", "source_kind", "source_type", "typed_absence", "limitations"}
)
_NEUTRAL_NOTES = frozenset(
    {
        "No sufficiently relevant course material was found for this request.",
        "No relevant earlier-session learner information was available for this request.",
        "No student activity evidence was available for this page.",
    }
)
_SOURCE_CATEGORY = {
    "dashboard_activity": "DASHBOARD",
    "current_page_context": "DASHBOARD",
    "course_material": "COURSE_RAG",
    "learner_memory": "LEARNER_MEMORY",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_provider(value: Any) -> None:
    if isinstance(value, Mapping):
        forbidden = _FORBIDDEN_PROVIDER_KEYS & set(value)
        if forbidden:
            raise ValueError(f"forbidden provider keys: {sorted(forbidden)}")
        for nested in value.values():
            _walk_provider(nested)
    elif isinstance(value, list):
        for nested in value:
            _walk_provider(nested)
    elif isinstance(value, str):
        if (
            _SCENARIO.search(value)
            or _MODE.search(value)
            or _LOCAL.search(value)
            or _INTERNAL_ROUTE.search(value)
            or _PROHIBITED_TEXT.search(value)
        ):
            raise ValueError("provider payload exposes prohibited internal identity or text")


def _walk_evidence(value: Any) -> None:
    if isinstance(value, Mapping):
        forbidden = _PROHIBITED_EVIDENCE_KEYS & set(value)
        if forbidden:
            raise ValueError(f"provider evidence contains internal keys: {sorted(forbidden)}")
        for nested in value.values():
            _walk_evidence(nested)
    elif isinstance(value, list):
        for nested in value:
            _walk_evidence(nested)
    elif isinstance(value, str) and _PROHIBITED_TEXT.search(value):
        raise ValueError("provider evidence contains internal implementation text")


def _validate_evidence(envelope: Any) -> tuple[int, Mapping[str, int]]:
    if not isinstance(envelope, Mapping) or set(envelope) != {"evidence", "availability_notes"}:
        raise ValueError("provider evidence V2 envelope mismatch")
    evidence = envelope["evidence"]
    notes = envelope["availability_notes"]
    if not isinstance(evidence, list) or not isinstance(notes, list):
        raise ValueError("provider evidence V2 lists are malformed")
    if any(not isinstance(note, str) or note not in _NEUTRAL_NOTES for note in notes):
        raise ValueError("provider availability note is not neutral and allowlisted")
    if len(notes) != len(set(notes)):
        raise ValueError("duplicate provider availability note")
    category_seen: dict[str, set[bytes]] = {
        "DASHBOARD": set(),
        "COURSE_RAG": set(),
        "LEARNER_MEMORY": set(),
    }
    counts = {key: 0 for key in category_seen}
    for item in evidence:
        if not isinstance(item, Mapping):
            raise ValueError("provider evidence item field mismatch")
        source = str(item.get("source"))
        category = _SOURCE_CATEGORY.get(source)
        if category is None:
            raise ValueError("unknown provider evidence source")
        expected_fields = {
            "dashboard_activity": {"source", "content"},
            "current_page_context": {"source", "content"},
            "course_material": {
                "source",
                "content",
                "document_title",
                "week",
                "section",
                "evidence_strength",
            },
            "learner_memory": {"source", "content", "memory_type"},
        }[source]
        if set(item) != expected_fields:
            raise ValueError("provider evidence item field mismatch")
        encoded = canonical_bytes(item)
        if encoded in category_seen[category]:
            raise ValueError(f"exact duplicate provider evidence item: {category}")
        category_seen[category].add(encoded)
        counts[category] += 1
        _walk_evidence(item)
    return len(evidence), counts


def _validate_payload(row: Mapping[str, Any], prompt: str, schema: Mapping[str, Any]) -> tuple[int, Mapping[str, int]]:
    expected_fields = {
        "schema_version",
        "logical_generation_request_id",
        "response_blind_id",
        "provider_payload_sha256",
        "estimated_input_tokens",
        "provider_payload",
    }
    if set(row) != expected_fields or row.get("schema_version") != "c4-real-blinded-generation-request-v2":
        raise ValueError("blinded request V2 fields or schema mismatch")
    if not _LOGICAL_ID.fullmatch(str(row.get("logical_generation_request_id", ""))):
        raise ValueError("logical generation request ID is not opaque")
    if not _RESPONSE_ID.fullmatch(str(row.get("response_blind_id", ""))):
        raise ValueError("response blind ID is not opaque")
    if not isinstance(row.get("estimated_input_tokens"), int) or row["estimated_input_tokens"] <= 0:
        raise ValueError("estimated input tokens must be a positive integer")
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
    ):
        raise ValueError("provider payload frozen transport configuration mismatch")
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
    expected_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "c4_real_generation_response_v2_provider_compatible",
            "strict": True,
            "schema": dict(schema),
        },
    }
    if payload.get("response_format") != expected_format:
        raise ValueError("provider response-format schema mismatch")
    user = json.loads(messages[1]["content"])
    if not isinstance(user, Mapping) or set(user) != {
        "current_query",
        "current_page",
        "visible_conversation_history",
        "evidence",
        "planning_support",
    }:
        raise ValueError("provider user-message field set mismatch")
    if not isinstance(user["current_query"], str) or not isinstance(user["current_page"], str):
        raise ValueError("provider query or page is malformed")
    if not isinstance(user["visible_conversation_history"], list):
        raise ValueError("provider visible history is malformed")
    _walk_provider(user)
    return _validate_evidence(user["evidence"])


def _validate_runner_source(source: str) -> None:
    required = (
        "--authorization-record",
        "--package-zip",
        "--execute",
        "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION",
        AUTHORIZATION_GATE,
        "max_retries=0",
        "Refusing overwrite or automatic resume",
        "SECOND_INVALID_JSON_OR_SCHEMA",
        "return stop_before_or_during_requests",
        "GENERATION_ERROR_REGISTRY.jsonl",
        "GENERATION_USAGE_AND_COST.json",
        "GENERATION_EXECUTION_REPORT.md",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise ValueError(f"runner fail-closed source markers missing: {missing}")
    if "C4_REAL_GENERATION_EXECUTION_AUTHORIZED" in source:
        raise ValueError("runner retains the obsolete generic authorization gate")
    receipt_write = source.find('write_exclusive_json(output_dir / "GENERATION_PREFLIGHT_RECEIPT.json"')
    runtime_call = source.find("runtime_checker()", receipt_write)
    client_call = source.find("client_factory()", receipt_write)
    if min(receipt_write, runtime_call, client_call) < 0 or not receipt_write < runtime_call < client_call:
        raise ValueError("runner does not durably receipt before runtime/client construction")


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
    if sha256(root / "GENERATION_PROMPT.txt") != PROMPT_SHA256:
        raise ValueError("generation prompt SHA-256 mismatch")
    if sha256(root / "GENERATION_SCHEMA.json") != SCHEMA_SHA256:
        raise ValueError("generation schema SHA-256 mismatch")
    if sha256(root / "GENERATION_CONFIGURATION.json") != CONFIG_SHA256:
        raise ValueError("generation configuration SHA-256 mismatch")
    prompt = (root / "GENERATION_PROMPT.txt").read_text(encoding="utf-8")
    schema = json.loads((root / "GENERATION_SCHEMA.json").read_text(encoding="utf-8"))
    if schema != {
        "type": "object",
        "properties": {"answer_text": {"type": "string"}},
        "required": ["answer_text"],
        "additionalProperties": False,
    }:
        raise ValueError("provider-compatible semantic response schema mismatch")
    config = json.loads((root / "GENERATION_CONFIGURATION.json").read_text(encoding="utf-8"))
    if (
        config.get("model") != MODEL
        or config.get("temperature") != 0
        or config.get("max_output_tokens") != 512
        or config.get("automatic_sdk_retries") != 0
        or config.get("streaming") is not False
        or config.get("tools") != "NONE"
        or config.get("generation_execution_authorised") is not False
    ):
        raise ValueError("frozen generation configuration content mismatch")
    manifest_path = root / "BLINDED_REQUESTS.jsonl"
    rows = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("blinded request manifest is empty")
    logical_ids: list[str] = []
    response_ids: list[str] = []
    evidence_item_count = 0
    evidence_counts = {"DASHBOARD": 0, "COURSE_RAG": 0, "LEARNER_MEMORY": 0}
    for row in rows:
        item_count, counts = _validate_payload(row, prompt, schema)
        evidence_item_count += item_count
        for name, count in counts.items():
            evidence_counts[name] += count
        logical_ids.append(str(row["logical_generation_request_id"]))
        response_ids.append(str(row["response_blind_id"]))
    if len(set(logical_ids)) != len(rows) or len(set(response_ids)) != len(rows):
        raise ValueError("opaque request or response IDs are not unique")
    if logical_ids != sorted(logical_ids):
        raise ValueError("blinded requests are not deterministically ordered")
    contract = json.loads((root / "EXECUTION_CONTRACT.json").read_text(encoding="utf-8"))
    package_match = _PACKAGE_ID.fullmatch(str(contract.get("package_id", "")))
    if package_match is None or package_match.group(1) != contract.get("shard"):
        raise ValueError("execution contract package ID or shard mismatch")
    if (
        contract.get("schema_version") != "c4-real-generation-execution-contract-v2"
        or contract.get("status") != "PREPARED_NOT_AUTHORIZED"
        or contract.get("request_count") != len(rows)
        or contract.get("maximum_physical_attempts") != len(rows) * 2
        or contract.get("authorization_record_required") is not True
        or contract.get("authorization_environment_value") != AUTHORIZATION_GATE
        or contract.get("provider_calls_during_package_preparation") != 0
        or contract.get("response_generation_during_package_preparation") != 0
        or contract.get("judge_calls") != 0
        or contract.get("scoring_calls") != 0
    ):
        raise ValueError("execution contract fail-closed fields mismatch")
    if (
        source_hashes.get("schema_version") != "c4-real-generation-package-source-hashes-v2"
        or source_hashes.get("package_id") != contract.get("package_id")
        or source_hashes.get("shard") != contract.get("shard")
        or source_hashes.get("request_count") != len(rows)
        or source_hashes.get("blinded_manifest_sha256") != sha256(manifest_path)
        or source_hashes.get("restricted_mapping_included") is not False
        or source_hashes.get("hmac_key_included") is not False
        or source_hashes.get("existing_execution_results_included") is not False
        or source_hashes.get("provider_calls") != 0
        or source_hashes.get("generation_calls") != 0
        or source_hashes.get("judge_calls") != 0
    ):
        raise ValueError("package source/manifest binding mismatch")
    _validate_runner_source(
        (root / "generation_execution_runner_v2.py").read_text(encoding="utf-8")
    )
    return {
        "status": "PASS",
        "package_id": contract["package_id"],
        "shard": contract["shard"],
        "request_count": len(rows),
        "estimated_input_tokens": sum(int(row["estimated_input_tokens"]) for row in rows),
        "maximum_physical_attempts": len(rows) * 2,
        "allowlisted_file_count": len(files),
        "provider_evidence_item_count": evidence_item_count,
        "provider_evidence_item_counts_by_category": evidence_counts,
        "prohibited_provider_string_occurrences": 0,
        "exact_duplicate_provider_evidence_items": 0,
    }


def validate_zip(path: Path) -> Mapping[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != ALLOWED_FILES:
            raise ValueError("ZIP member allowlist mismatch")
        if any(name.endswith("/") or Path(name).name != name for name in names):
            raise ValueError("ZIP contains a nested or directory member")
        with tempfile.TemporaryDirectory(prefix="c4-real-r2-validate-") as temporary:
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
