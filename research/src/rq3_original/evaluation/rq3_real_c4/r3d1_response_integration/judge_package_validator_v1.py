#!/usr/bin/env python3
"""Offline validator for one frozen C4 REAL Judge execution Package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


ALLOWED_FILES = {
    "README.md",
    "BLINDED_JUDGE_REQUESTS.jsonl",
    "JUDGE_PROMPT.txt",
    "JUDGE_SCHEMA.json",
    "JUDGE_CONFIGURATION.json",
    "PRIMARY_RUBRIC.json",
    "APPLICABILITY_CONTRACT.json",
    "EXECUTION_CONTRACT.json",
    "judge_execution_runner_v1.py",
    "judge_result_parser_v1.py",
    "validate_package.py",
    "test_package.py",
    "PACKAGE_SOURCE_HASHES.json",
}

EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_MAX_OUTPUT_TOKENS = 2048
EXPECTED_PROMPT_SHA256 = "5b99b52bef760daa4e2fc8ae6ab13cead7e031b9d41b52d41e88617d906c35f3"
EXPECTED_SCHEMA_SHA256 = "caf69ff4e8c27b71805414b29caf3b87fa5da92bf0df0dec23c6945b2019be30"
EXPECTED_RUBRIC_SHA256 = "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350"
EXPECTED_APPLICABILITY_SHA256 = "bee7bf9d681004f4ab5be549053b7dbeb2f7726361217251495a167257460b0e"
LOGICAL_ID_RE = re.compile(r"^C4J1-[A-F0-9]{24}$")
RESULT_ID_RE = re.compile(r"^R3B-[A-F0-9]{20}$")
FORBIDDEN_KEYS = {
    "scenario_id",
    "scenario_family_id",
    "family_id",
    "mode",
    "mode_id",
    "condition",
    "condition_id",
    "condition_name",
    "route",
    "route_id",
    "route_signature",
    "p3",
    "gold",
    "expected_winner",
    "dataset_group",
    "generation_shard",
    "generation_attempt_number",
}
FORBIDDEN_VALUE_TOKENS = (
    "C0_ORIGINAL",
    "C1_EVIDENCE",
    "C2_EVIDENCE_RAG",
    "C3_EVIDENCE_MEMORY",
    "C4_EVIDENCE_PLANNING",
    "C5_FULL_C4",
    "C5_MINUS_RAG",
    "C5_MINUS_MEMORY",
    "C5_MINUS_PLANNING",
    "BASE_NEVER_ON",
    "ALWAYS_ON",
    "ORACLE_ROUTE",
    "PREDICTED_ROUTE",
)


class PackageValidationError(ValueError):
    """Raised when a Package differs from the frozen execution contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _walk_blind_payload(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PackageValidationError(f"non-string key at {path}")
            if key.casefold() in FORBIDDEN_KEYS:
                raise PackageValidationError(f"condition identity key at {path}.{key}")
            _walk_blind_payload(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_blind_payload(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for token in FORBIDDEN_VALUE_TOKENS:
            if token.casefold() in value.casefold():
                raise PackageValidationError(f"condition identity token at {path}")
        if re.search(r"(?<![A-Za-z0-9])P3(?![A-Za-z0-9])", value, re.IGNORECASE):
            raise PackageValidationError(f"P3 token at {path}")


def _extract_blind_request(provider_payload: Mapping[str, Any]) -> dict[str, Any]:
    messages = provider_payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        raise PackageValidationError("Judge payload must contain exactly one system message")
    message = messages[0]
    if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
        raise PackageValidationError("Judge message shape mismatch")
    if message["role"] != "system" or not isinstance(message["content"], str):
        raise PackageValidationError("Judge message role/content mismatch")
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    content = message["content"]
    if content.count(begin) != 1 or content.count(end) != 1:
        raise PackageValidationError("blind request insertion boundary mismatch")
    request = json.loads(content.split(begin, 1)[1].rsplit(end, 1)[0])
    if not isinstance(request, dict):
        raise PackageValidationError("blind request is not an object")
    return request


def validate_package_dir(package_dir: Path) -> dict[str, Any]:
    package_dir = package_dir.resolve()
    files = {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    if files != ALLOWED_FILES:
        raise PackageValidationError(
            f"Package file allowlist mismatch; missing={sorted(ALLOWED_FILES-files)}, "
            f"extra={sorted(files-ALLOWED_FILES)}"
        )
    if any(path.is_symlink() for path in package_dir.rglob("*")):
        raise PackageValidationError("Package must not contain symlinks")

    hashes = json.loads((package_dir / "PACKAGE_SOURCE_HASHES.json").read_text("utf-8"))
    if hashes.get("schema_version") != "c4-real-judge-package-source-hashes-v1":
        raise PackageValidationError("source-hash manifest version mismatch")
    declared = hashes.get("member_sha256")
    if not isinstance(declared, dict) or set(declared) != ALLOWED_FILES - {
        "PACKAGE_SOURCE_HASHES.json"
    }:
        raise PackageValidationError("source-hash member set mismatch")
    for name, expected in declared.items():
        if sha256_file(package_dir / name) != expected:
            raise PackageValidationError(f"member hash mismatch: {name}")

    if sha256_file(package_dir / "JUDGE_PROMPT.txt") != EXPECTED_PROMPT_SHA256:
        raise PackageValidationError("Judge Prompt hash mismatch")
    if sha256_file(package_dir / "JUDGE_SCHEMA.json") != EXPECTED_SCHEMA_SHA256:
        raise PackageValidationError("Judge schema hash mismatch")
    if sha256_file(package_dir / "PRIMARY_RUBRIC.json") != EXPECTED_RUBRIC_SHA256:
        raise PackageValidationError("primary rubric hash mismatch")
    if sha256_file(package_dir / "APPLICABILITY_CONTRACT.json") != EXPECTED_APPLICABILITY_SHA256:
        raise PackageValidationError("applicability contract hash mismatch")

    configuration = json.loads((package_dir / "JUDGE_CONFIGURATION.json").read_text("utf-8"))
    required_config = {
        "model": EXPECTED_MODEL,
        "temperature": 0,
        "max_output_tokens": EXPECTED_MAX_OUTPUT_TOKENS,
        "automatic_sdk_retries": 0,
        "streaming": False,
        "tools": "NONE",
    }
    for field, expected in required_config.items():
        if configuration.get(field) != expected:
            raise PackageValidationError(f"Judge configuration mismatch: {field}")
    contract = json.loads((package_dir / "EXECUTION_CONTRACT.json").read_text("utf-8"))
    if contract.get("python_executable") != "/opt/anaconda3/bin/python3":
        raise PackageValidationError("Python executable mismatch")
    if contract.get("python_version") != "3.13.5":
        raise PackageValidationError("Python version mismatch")
    if contract.get("openai_sdk_version") != "1.109.1":
        raise PackageValidationError("OpenAI SDK version mismatch")
    if contract.get("serial_execution") is not True:
        raise PackageValidationError("serial execution is not frozen")
    if contract.get("automatic_resume") is not False:
        raise PackageValidationError("automatic resume is not prohibited")
    if contract.get("minimum_seconds_between_initial_request_starts") != 2:
        raise PackageValidationError("initial-start spacing mismatch")

    schema = json.loads((package_dir / "JUDGE_SCHEMA.json").read_text("utf-8"))
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        (package_dir / "BLINDED_JUDGE_REQUESTS.jsonl").read_text("utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        expected_fields = {
            "schema_version",
            "logical_judge_request_id",
            "judge_result_blind_id",
            "provider_payload_sha256",
            "estimated_input_tokens",
            "shard_id",
            "provider_payload",
        }
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise PackageValidationError(f"request row {line_number} field mismatch")
        if not LOGICAL_ID_RE.fullmatch(str(row["logical_judge_request_id"])):
            raise PackageValidationError("invalid opaque logical Judge ID")
        if not RESULT_ID_RE.fullmatch(str(row["judge_result_blind_id"])):
            raise PackageValidationError("invalid opaque Judge result ID")
        payload = row["provider_payload"]
        if not isinstance(payload, dict) or set(payload) != {
            "model", "messages", "temperature", "max_tokens", "stream", "response_format"
        }:
            raise PackageValidationError("provider payload field mismatch")
        if payload["model"] != EXPECTED_MODEL or payload["temperature"] != 0:
            raise PackageValidationError("provider model/temperature mismatch")
        if payload["max_tokens"] != EXPECTED_MAX_OUTPUT_TOKENS or payload["stream"] is not False:
            raise PackageValidationError("provider output-token/stream mismatch")
        response_format = payload["response_format"]
        if response_format.get("type") != "json_schema":
            raise PackageValidationError("strict response format missing")
        wrapped = response_format.get("json_schema")
        if not isinstance(wrapped, dict) or wrapped.get("strict") is not True:
            raise PackageValidationError("strict JSON schema wrapper mismatch")
        if wrapped.get("schema") != schema:
            raise PackageValidationError("embedded Judge schema mismatch")
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if digest != row["provider_payload_sha256"]:
            raise PackageValidationError("provider payload hash mismatch")
        request = _extract_blind_request(payload)
        if request.get("response_blind_id") != row["judge_result_blind_id"]:
            raise PackageValidationError("embedded Judge result ID mismatch")
        if set(request) != {
            "schema_version",
            "response_blind_id",
            "student_query",
            "current_lad_page",
            "visible_conversation_history",
            "frozen_dashboard_evidence",
            "course_evidence_available_in_condition",
            "long_term_memory_available_in_condition",
            "planning_support_available_in_condition",
            "candidate_response",
            "frozen_applicability_map",
        }:
            raise PackageValidationError("blind Judge request field mismatch")
        _walk_blind_payload(request)
        rows.append(row)
    if not rows:
        raise PackageValidationError("empty Judge request manifest")
    if len({row["logical_judge_request_id"] for row in rows}) != len(rows):
        raise PackageValidationError("duplicate logical Judge IDs")
    if len({row["judge_result_blind_id"] for row in rows}) != len(rows):
        raise PackageValidationError("duplicate Judge result IDs")
    if len({row["provider_payload_sha256"] for row in rows}) != len(rows):
        raise PackageValidationError("duplicate Provider payload identities inside Shard")
    shard_ids = {row["shard_id"] for row in rows}
    if len(shard_ids) != 1 or next(iter(shard_ids)) not in {"A", "B", "C"}:
        raise PackageValidationError("Shard identity mismatch")

    forbidden_blob_tokens = (
        "OPENAI_API_KEY=",
        "c4_real_i1_blinding_hmac_key.bin",
        "restricted_internal/",
    )
    for name in (
        "README.md",
        "BLINDED_JUDGE_REQUESTS.jsonl",
        "JUDGE_CONFIGURATION.json",
        "EXECUTION_CONTRACT.json",
        "PACKAGE_SOURCE_HASHES.json",
    ):
        path = package_dir / name
        data = path.read_bytes()
        for token in forbidden_blob_tokens:
            if token.encode("utf-8") in data:
                raise PackageValidationError(f"prohibited package material in {path.name}")

    return {
        "status": "PASS",
        "shard_id": next(iter(shard_ids)),
        "request_count": len(rows),
        "regular_file_count": len(files),
        "checks_failed": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(validate_package_dir(args.package_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
