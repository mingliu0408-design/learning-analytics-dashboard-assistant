#!/usr/bin/env python3
"""Offline validator for a C4 REAL Judge R2 execution Package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from zipfile import BadZipFile, ZipFile


ALLOWED_FILES = {
    "README.md",
    "BLINDED_JUDGE_REQUESTS.jsonl",
    "JUDGE_PROMPT.txt",
    "JUDGE_SCHEMA.json",
    "JUDGE_CONFIGURATION.json",
    "PRIMARY_RUBRIC.json",
    "APPLICABILITY_CONTRACT.json",
    "EXECUTION_CONTRACT.json",
    "judge_execution_runner_v2.py",
    "judge_result_parser_v2.py",
    "validate_package.py",
    "test_package.py",
    "PACKAGE_SOURCE_HASHES.json",
}
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
EXPECTED_MAX_OUTPUT_TOKENS = 2048
EXPECTED_TEMPERATURE = 0
EXPECTED_RUBRIC_SHA256 = (
    "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350"
)
EXPECTED_APPLICABILITY_SHA256 = (
    "bee7bf9d681004f4ab5be549053b7dbeb2f7726361217251495a167257460b0e"
)
EXPECTED_TRANSPORT_SCHEMA_VERSION = "rq3-judge-response-r3d1-r2-transport"
EXPECTED_SEMANTIC_SCHEMA_VERSION = "rq3-judge-response-v1"
LOGICAL_ID_RE = re.compile(r"^C4J1-[A-F0-9]{24}$")
RESULT_ID_RE = re.compile(r"^R3B-[A-F0-9]{20}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
PRIMARY_FIELDS = {
    "clarity",
    "personalisation",
    "actionability",
    "context_awareness",
    "motivation_and_engagement",
    "reliability",
    "multi_page_cohesiveness",
    "error_handling",
}
PROVIDER_FIELDS = {
    *PRIMARY_FIELDS,
    "evidence_faithfulness",
    "unsupported_claim_count",
    "criterion_rationales",
    "schema_version",
}
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
    """Raised when a Package differs from the frozen R2 contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _duplicate_key_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise PackageValidationError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def strict_json(data: bytes, label: str) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_duplicate_key_guard)
    except PackageValidationError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PackageValidationError(f"invalid JSON: {label}") from exc


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
        raise PackageValidationError("exactly one system message is required")
    message = messages[0]
    if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
        raise PackageValidationError("Judge message field set mismatch")
    if message["role"] != "system" or not isinstance(message["content"], str):
        raise PackageValidationError("Judge message role/content mismatch")
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    content = message["content"]
    if content.count(begin) != 1 or content.count(end) != 1:
        raise PackageValidationError("blind request insertion boundary mismatch")
    raw = content.split(begin, 1)[1].rsplit(end, 1)[0].encode("utf-8")
    request = strict_json(raw, "embedded blind request")
    if not isinstance(request, dict):
        raise PackageValidationError("blind request is not an object")
    return request


def _estimated_input_tokens(provider_payload: Mapping[str, Any]) -> int:
    message_bytes = sum(
        len(canonical_json_bytes(message)) for message in provider_payload["messages"]
    )
    response_format_bytes = len(canonical_json_bytes(provider_payload["response_format"]))
    return (message_bytes + response_format_bytes + 16 + 3) // 4


def _validate_schema(schema: Any) -> None:
    if not isinstance(schema, dict):
        raise PackageValidationError("Judge schema is not an object")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise PackageValidationError("Judge schema root is not strict")
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or set(properties) != PROVIDER_FIELDS:
        raise PackageValidationError("Provider schema field set mismatch")
    if not isinstance(required, list) or len(required) != len(set(required)):
        raise PackageValidationError("Provider schema required list invalid")
    if set(required) != PROVIDER_FIELDS:
        raise PackageValidationError("Provider schema required fields mismatch")
    if "response_blind_id" in properties or "overall_applicable_mean" in properties:
        raise PackageValidationError("locally attached/calculated field exposed to Provider")
    score_enum = ["1", "2", "3", "4", "5", "NA"]
    for field in PRIMARY_FIELDS:
        if properties[field] != {"type": "string", "enum": score_enum}:
            raise PackageValidationError(f"score schema mismatch: {field}")
    if properties["evidence_faithfulness"] != {
        "type": "string",
        "enum": ["1", "2", "3", "4", "5"],
    }:
        raise PackageValidationError("evidence-faithfulness schema mismatch")
    unsupported = properties["unsupported_claim_count"]
    if unsupported != {"type": "string"}:
        raise PackageValidationError("unsupported-claim-count schema mismatch")
    if properties["schema_version"] != {
        "type": "string",
        "enum": [EXPECTED_TRANSPORT_SCHEMA_VERSION],
    }:
        raise PackageValidationError("transport schema-version field mismatch")
    rationales = properties["criterion_rationales"]
    if not isinstance(rationales, dict):
        raise PackageValidationError("rationale schema missing")
    if rationales.get("type") != "object" or rationales.get("additionalProperties") is not False:
        raise PackageValidationError("rationale schema is not strict")
    if set(rationales.get("properties", {})) != PRIMARY_FIELDS:
        raise PackageValidationError("rationale field set mismatch")
    if set(rationales.get("required", [])) != PRIMARY_FIELDS:
        raise PackageValidationError("rationale required fields mismatch")


def _validate_members(members: Mapping[str, bytes]) -> dict[str, Any]:
    if set(members) != ALLOWED_FILES:
        raise PackageValidationError(
            "Package allowlist mismatch; "
            f"missing={sorted(ALLOWED_FILES-set(members))}, "
            f"extra={sorted(set(members)-ALLOWED_FILES)}"
        )

    source_hashes = strict_json(members["PACKAGE_SOURCE_HASHES.json"], "source hashes")
    if not isinstance(source_hashes, dict) or set(source_hashes) != {
        "schema_version",
        "package_id",
        "shard_id",
        "member_sha256",
    }:
        raise PackageValidationError("source-hash manifest field set mismatch")
    if source_hashes["schema_version"] != "c4-real-judge-package-source-hashes-r2-v1":
        raise PackageValidationError("source-hash manifest version mismatch")
    declared = source_hashes["member_sha256"]
    if not isinstance(declared, dict) or set(declared) != ALLOWED_FILES - {
        "PACKAGE_SOURCE_HASHES.json"
    }:
        raise PackageValidationError("source-hash member set mismatch")
    for name, expected in declared.items():
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            raise PackageValidationError(f"invalid declared hash: {name}")
        if sha256_bytes(members[name]) != expected:
            raise PackageValidationError(f"member hash mismatch: {name}")

    if sha256_bytes(members["PRIMARY_RUBRIC.json"]) != EXPECTED_RUBRIC_SHA256:
        raise PackageValidationError("primary rubric hash mismatch")
    if sha256_bytes(members["APPLICABILITY_CONTRACT.json"]) != EXPECTED_APPLICABILITY_SHA256:
        raise PackageValidationError("applicability contract hash mismatch")

    schema = strict_json(members["JUDGE_SCHEMA.json"], "Judge schema")
    _validate_schema(schema)
    prompt = members["JUDGE_PROMPT.txt"].decode("utf-8")
    if prompt.count("{{BLIND_JUDGE_REQUEST_JSON}}") != 1:
        raise PackageValidationError("Judge Prompt placeholder count mismatch")
    output_section = prompt.split("OUTPUT PROCEDURE\n\n", 1)[1].split(
        "\n\nThe runtime inserts", 1
    )[0]
    required_output_phrases = (
        "Do not return or echo the opaque result ID",
        "Do not calculate or return overall_applicable_mean",
        "attached by the local parser",
        "computed exclusively by the local parser",
    )
    if any(phrase not in output_section for phrase in required_output_phrases):
        raise PackageValidationError("R2 local-field output procedure mismatch")

    requests_blob = members["BLINDED_JUDGE_REQUESTS.jsonl"]
    configuration = strict_json(members["JUDGE_CONFIGURATION.json"], "configuration")
    contract = strict_json(members["EXECUTION_CONTRACT.json"], "execution contract")
    if not isinstance(configuration, dict) or configuration.get("schema_version") != (
        "c4-real-judge-configuration-r3d1-r2-v1"
    ):
        raise PackageValidationError("Judge configuration version mismatch")
    required_config = {
        "model": EXPECTED_MODEL,
        "temperature": EXPECTED_TEMPERATURE,
        "max_output_tokens": EXPECTED_MAX_OUTPUT_TOKENS,
        "automatic_sdk_retries": 0,
        "streaming": False,
        "tools": "NONE",
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 15.0,
        "semantic_schema_version": EXPECTED_SEMANTIC_SCHEMA_VERSION,
        "transport_schema_version": EXPECTED_TRANSPORT_SCHEMA_VERSION,
        "provider_outputs_result_blind_id": False,
        "provider_outputs_overall_applicable_mean": False,
        "overall_applicable_mean_computed_locally": True,
        "judge_calls": 0,
    }
    for field, expected in required_config.items():
        if configuration.get(field) != expected:
            raise PackageValidationError(f"Judge configuration mismatch: {field}")
    shard = configuration.get("shard_id")
    if shard not in {"A", "B", "C"} or source_hashes["shard_id"] != shard:
        raise PackageValidationError("Package Shard mismatch")
    package_id = configuration.get("package_id")
    if not isinstance(package_id, str) or source_hashes["package_id"] != package_id:
        raise PackageValidationError("Package ID mismatch")
    if configuration.get("request_count") != 49:
        raise PackageValidationError("configuration request count mismatch")
    if configuration.get("maximum_physical_attempts") != 98:
        raise PackageValidationError("configuration attempt cap mismatch")
    if configuration.get("blinded_judge_manifest_sha256") != sha256_bytes(requests_blob):
        raise PackageValidationError("configuration manifest binding mismatch")
    for name, field in (
        ("JUDGE_PROMPT.txt", "judge_prompt_sha256"),
        ("JUDGE_SCHEMA.json", "provider_schema_sha256"),
        ("PRIMARY_RUBRIC.json", "primary_rubric_sha256"),
        ("APPLICABILITY_CONTRACT.json", "applicability_contract_sha256"),
    ):
        if configuration.get(field) != sha256_bytes(members[name]):
            raise PackageValidationError(f"configuration hash mismatch: {field}")

    if not isinstance(contract, dict) or contract.get("schema_version") != (
        "c4-real-judge-execution-contract-r2-v1"
    ):
        raise PackageValidationError("execution contract version mismatch")
    required_contract = {
        "python_executable": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
        "openai_sdk_version": "1.109.1",
        "automatic_sdk_retries": 0,
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 15.0,
        "existing_output_directory_permitted": False,
        "automatic_resume": False,
        "raw_invalid_output_preserved": True,
        "returned_model_identity_verified": EXPECTED_MODEL,
        "non_retryable_error_policy": "STOP_ENTIRE_SHARD",
        "authorization_environment_variable": "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION",
        "authorization_environment_value": "AUTHORIZED_C4_REAL_JUDGE_EXECUTION_R2",
        "execution_authorized_in_package": False,
        "condition_comparisons_inside_worker": False,
    }
    for field, expected in required_contract.items():
        if contract.get(field) != expected:
            raise PackageValidationError(f"execution contract mismatch: {field}")
    if contract.get("configuration_sha256") != sha256_bytes(
        members["JUDGE_CONFIGURATION.json"]
    ):
        raise PackageValidationError("execution/configuration binding mismatch")
    retry = contract.get("manual_retry")
    if retry != {
        "maximum_retries": 1,
        "byte_identical": True,
        "correction_message": False,
        "permitted_only_after": [
            "INVALID_JSON",
            "STRICT_SCHEMA_VALIDATION_FAILED",
            "APPLICABILITY_CONTRACT_VIOLATION",
        ],
    }:
        raise PackageValidationError("manual retry contract mismatch")

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(requests_blob.splitlines(), 1):
        if not line.strip():
            continue
        row = strict_json(line, f"request row {line_number}")
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
        if row["schema_version"] != "c4-real-unique-judge-request-frozen-r2":
            raise PackageValidationError("request record version mismatch")
        if not LOGICAL_ID_RE.fullmatch(str(row["logical_judge_request_id"])):
            raise PackageValidationError("invalid opaque logical Judge ID")
        if not RESULT_ID_RE.fullmatch(str(row["judge_result_blind_id"])):
            raise PackageValidationError("invalid opaque Judge result ID")
        if row["shard_id"] != shard:
            raise PackageValidationError("request/configuration Shard mismatch")
        payload = row["provider_payload"]
        if not isinstance(payload, dict) or set(payload) != {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "stream",
            "response_format",
        }:
            raise PackageValidationError("Provider payload field mismatch")
        if payload["model"] != EXPECTED_MODEL or payload["temperature"] != 0:
            raise PackageValidationError("Provider model/temperature mismatch")
        if payload["max_tokens"] != 2048 or payload["stream"] is not False:
            raise PackageValidationError("Provider output-token/stream mismatch")
        wrapped = payload["response_format"]
        if not isinstance(wrapped, dict) or set(wrapped) != {"type", "json_schema"}:
            raise PackageValidationError("strict response-format wrapper mismatch")
        if wrapped["type"] != "json_schema":
            raise PackageValidationError("strict JSON response format missing")
        json_schema = wrapped["json_schema"]
        if not isinstance(json_schema, dict) or set(json_schema) != {
            "name",
            "strict",
            "schema",
        }:
            raise PackageValidationError("strict JSON schema wrapper mismatch")
        if json_schema["strict"] is not True or json_schema["schema"] != schema:
            raise PackageValidationError("embedded Judge schema mismatch")
        digest = sha256_bytes(canonical_json_bytes(payload))
        if digest != row["provider_payload_sha256"]:
            raise PackageValidationError("Provider payload hash mismatch")
        if row["estimated_input_tokens"] != _estimated_input_tokens(payload):
            raise PackageValidationError("estimated-input-token count mismatch")
        request = _extract_blind_request(payload)
        if request.get("response_blind_id") != row["judge_result_blind_id"]:
            raise PackageValidationError("embedded local result ID mismatch")
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
        template = prompt.replace(
            "{{BLIND_JUDGE_REQUEST_JSON}}",
            canonical_json_bytes(request).decode("utf-8"),
        )
        if payload["messages"][0]["content"] != template:
            raise PackageValidationError("rendered Prompt/request mismatch")
        _walk_blind_payload(request)
        rows.append(row)

    if len(rows) != 49:
        raise PackageValidationError("Judge request count must be exactly 49")
    for field in (
        "logical_judge_request_id",
        "judge_result_blind_id",
        "provider_payload_sha256",
    ):
        if len({row[field] for row in rows}) != 49:
            raise PackageValidationError(f"duplicate request identity: {field}")

    forbidden_blob_tokens = (
        b"OPENAI_API_KEY=",
        b"c4_real_i1_blinding_hmac_key.bin",
        b"restricted_internal/",
    )
    for name in (
        "README.md",
        "BLINDED_JUDGE_REQUESTS.jsonl",
        "JUDGE_CONFIGURATION.json",
        "EXECUTION_CONTRACT.json",
        "PACKAGE_SOURCE_HASHES.json",
    ):
        data = members[name]
        for token in forbidden_blob_tokens:
            if token in data:
                raise PackageValidationError(f"prohibited material in {name}")
    for token in (b"JUDGE_ATTEMPT_JOURNAL", b"JUDGE_TERMINAL_JOURNAL"):
        if token in requests_blob:
            raise PackageValidationError("existing Judge output leaked into requests")

    return {
        "status": "PASS",
        "package_id": package_id,
        "shard_id": shard,
        "request_count": len(rows),
        "maximum_physical_attempts": len(rows) * 2,
        "blinded_judge_manifest_sha256": sha256_bytes(requests_blob),
        "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in rows),
        "regular_file_count": len(members),
        "checks_failed": 0,
    }


def read_package_dir(package_dir: Path) -> dict[str, bytes]:
    package_dir = package_dir.resolve()
    files = {
        path.relative_to(package_dir).as_posix(): path
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    if any(path.is_symlink() for path in package_dir.rglob("*")):
        raise PackageValidationError("Package must not contain symlinks")
    return {name: path.read_bytes() for name, path in files.items()}


def validate_package_dir(package_dir: Path) -> dict[str, Any]:
    return _validate_members(read_package_dir(package_dir))


def read_package_zip(package_zip: Path) -> dict[str, bytes]:
    package_zip = package_zip.resolve()
    if not package_zip.is_file():
        raise PackageValidationError("Package ZIP is absent")
    try:
        with ZipFile(package_zip) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise PackageValidationError("duplicate ZIP member name")
            if any(info.is_dir() for info in infos):
                raise PackageValidationError("ZIP directories are not permitted")
            for info in infos:
                path = Path(info.filename)
                if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
                    raise PackageValidationError("unsafe or nested ZIP member")
                mode = (info.external_attr >> 16) & 0o170000
                if mode not in {0, stat.S_IFREG}:
                    raise PackageValidationError("non-regular ZIP member")
            return {info.filename: archive.read(info) for info in infos}
    except BadZipFile as exc:
        raise PackageValidationError("invalid Package ZIP") from exc


def validate_package_zip(package_zip: Path) -> dict[str, Any]:
    result = _validate_members(read_package_zip(package_zip))
    result["package_zip_sha256"] = sha256_file(package_zip)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--package-zip", type=Path)
    group.add_argument("--package-dir", type=Path)
    args = parser.parse_args()
    if args.package_zip:
        result = validate_package_zip(args.package_zip)
    else:
        result = validate_package_dir(args.package_dir or Path(__file__).resolve().parent)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_FILES",
    "PackageValidationError",
    "canonical_json_bytes",
    "read_package_dir",
    "read_package_zip",
    "sha256_bytes",
    "sha256_file",
    "strict_json",
    "validate_package_dir",
    "validate_package_zip",
]
