#!/usr/bin/env python3
"""Offline structural/byte validation of a corrected Judge R4 package.

During Phase B, callers must supply in-memory members obtained through the
Phase-B access guard. Filesystem entry points are for separately authorized
delivery-package inspection and execution, not for bypassing that guard.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import stat
from pathlib import Path
from zipfile import BadZipFile, ZipFile

ALLOWED_FILES = frozenset({"README.md", "BLINDED_JUDGE_REQUESTS.jsonl", "JUDGE_PROMPT.txt", "JUDGE_SCHEMA.json",
                          "JUDGE_CONFIGURATION.json", "PRIMARY_RUBRIC.json", "APPLICABILITY_CONTRACT_V2.json",
                          "EXECUTION_CONTRACT.json", "judge_execution_runner_v3.py", "judge_result_parser_v3.py",
                          "validate_package.py", "test_package.py", "PACKAGE_SOURCE_HASHES.json"})
PROMPT_SHA256 = "0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e"
SCHEMA_SHA256 = "5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a"
RUBRIC_SHA256 = "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350"
PARSER_SHA256 = "7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb"
AUTHORITY_STATUS = "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT"
ENTRY_SHA256 = "abf6fd158e68a406008bee838a74adc9d0cc3e87feef0ad649ea790c0feb44e4"
V2_MAP_SHA256 = "12d8618beb629235a42261266338a02fb419573ce1f37deffc1b7f28feafa553"
EXPECTED_MODEL = "gpt-4.1-2025-04-14"
SCHEMA_NAME = "c4_real_judge_response_r3d1_r2_provider_compatible"
BEGIN = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
END = "\nEND_BLIND_JUDGE_REQUEST_JSON"
RETRYABLE = ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED", "APPLICABILITY_CONTRACT_VIOLATION"]
PRIMARY = ("CLARITY", "PERSONALISATION", "ACTIONABILITY", "CONTEXT_AWARENESS", "MOTIVATION_AND_ENGAGEMENT",
           "RELIABILITY", "MULTI_PAGE_COHESIVENESS", "ERROR_HANDLING")
REQUEST_FIELDS = {"schema_version", "logical_order", "logical_judge_request_id", "judge_result_blind_id",
                  "provider_payload_sha256", "estimated_input_tokens", "provider_payload"}
BLIND_FIELDS = {"candidate_response", "course_evidence_available_in_condition", "current_lad_page",
                "frozen_applicability_map", "frozen_dashboard_evidence", "long_term_memory_available_in_condition",
                "planning_support_available_in_condition", "response_blind_id", "schema_version",
                "student_query", "visible_conversation_history"}
FORBIDDEN_KEYS = {"scenario_id", "family_id", "scenario_family_id", "mode", "mode_id", "condition_id", "condition_name",
                  "route", "route_signature", "gold", "expected_winner", "human_rating", "judge_score",
                  "prior_rating", "prior_rationale", "raw_response_content", "parsed_semantic_result"}


class PackageValidationError(ValueError):
    pass


def require(condition, message):
    if not condition: raise PackageValidationError(message)


def canonical_json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def strict_json(raw, label="JSON"):
    try:
        return json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(PackageValidationError("non-finite JSON constant")))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, PackageValidationError): raise
        raise PackageValidationError(label + " is invalid JSON") from exc


def read_package_bytes(raw):
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)) == 13 and set(names) == ALLOWED_FILES, "exact 13-member allowlist required")
            for info in infos:
                require(not info.is_dir() and "/" not in info.filename and "\\" not in info.filename, "flat regular files required")
                require(not stat.S_ISLNK(info.external_attr >> 16), "symlink prohibited")
                require(not info.flag_bits & 1, "encrypted member prohibited")
            require(archive.testzip() is None, "CRC failure")
            return {name: archive.read(name) for name in names}
    except BadZipFile as exc:
        raise PackageValidationError("invalid ZIP") from exc


def read_package_zip(path):
    return read_package_bytes(Path(path).read_bytes())


def _validate_map(value):
    require(set(value) == {"schema_version", "freeze_status", "criteria", "applicable_primary_count", "applicability_sha256"}, "applicability field set")
    require(value["schema_version"] == "rq3-dimension-applicability-map-v1", "map wire schema must remain unchanged")
    require(value["freeze_status"] == "FROZEN_BEFORE_CANDIDATE_SCORING", "map freeze status")
    criteria = value["criteria"]
    require(set(criteria) == set(PRIMARY) and all(type(v) is bool for v in criteria.values()), "boolean primary flags required")
    require(all(criteria[c] for c in ("CLARITY", "CONTEXT_AWARENESS", "RELIABILITY")), "always-applicable flags changed")
    require(type(value["applicable_primary_count"]) is int and value["applicable_primary_count"] == sum(criteria.values()), "applicability count mismatch")
    require(value["applicability_sha256"] == sha256_bytes(canonical_json_bytes(criteria)), "applicability commitment mismatch")


def _forbid_hidden_identity(value):
    if isinstance(value, dict):
        require(not set(value) & FORBIDDEN_KEYS, "hidden evaluation identity or prior result found")
        for item in value.values(): _forbid_hidden_identity(item)
    elif isinstance(value, list):
        for item in value: _forbid_hidden_identity(item)
    elif isinstance(value, str):
        require(not re.search(r"\bC[0-9]+_[A-Z][A-Z_]+\b|\bU[0-9]{3}\b|\bsk-[A-Za-z0-9_-]{16,}", value), "evaluation identity or credential-like token found")


def validate_members(members, *, package_zip_sha256=None):
    require(set(members) == ALLOWED_FILES, "package allowlist mismatch")
    source_hashes = strict_json(members["PACKAGE_SOURCE_HASHES.json"])
    require(set(source_hashes) == {"schema_version", "files"} and source_hashes["schema_version"] == "c4-real-corrected-judge-package-hashes-r4-v1", "hash manifest schema")
    require(set(source_hashes["files"]) == ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"}, "hash manifest file set")
    require(all(sha256_bytes(members[name]) == expected for name, expected in source_hashes["files"].items()), "package member hash mismatch")
    for name, expected in {"JUDGE_PROMPT.txt": PROMPT_SHA256, "JUDGE_SCHEMA.json": SCHEMA_SHA256,
                           "PRIMARY_RUBRIC.json": RUBRIC_SHA256, "judge_result_parser_v3.py": PARSER_SHA256}.items():
        require(sha256_bytes(members[name]) == expected, "frozen protocol source changed: " + name)
    prompt = members["JUDGE_PROMPT.txt"].decode()
    require(prompt.count("{{BLIND_JUDGE_REQUEST_JSON}}") == 1, "frozen prompt placeholder")
    schema = strict_json(members["JUDGE_SCHEMA.json"])
    config = strict_json(members["JUDGE_CONFIGURATION.json"])
    contract = strict_json(members["EXECUTION_CONTRACT.json"])
    applicability = strict_json(members["APPLICABILITY_CONTRACT_V2.json"])
    require(config["schema_version"] == "c4-real-corrected-judge-configuration-r4-v1", "configuration version")
    require(config["shard_id"] in ("A", "B", "C"), "corrected shard identity")
    require(config["package_id"] == "C4_REAL_CORRECTED_JUDGE_SHARD_" + config["shard_id"] + "_R4_20260902", "corrected package identity")
    expected_runtime = {"python_executable": "/opt/anaconda3/bin/python3", "python_version": "3.13.5", "openai_sdk_version": "1.109.1"}
    require(config["runtime"] == expected_runtime, "runtime gate differs")
    require(config["model"] == EXPECTED_MODEL and type(config["temperature"]) is int and config["temperature"] == 0,
            "frozen model/temperature differs")
    require(type(config["maximum_output_tokens"]) is int and config["maximum_output_tokens"] == 2048, "frozen output limit differs")
    require(config["sdk_retries"] == 0 and config["request_timeout_seconds"] == 120.0 and config["minimum_initial_start_interval_seconds"] == 15.0, "transport gate differs")
    require(config["stream"] is False and config["tools"] == "NONE" and config["execution_authorized"] is False, "package must remain dormant")
    require(applicability["schema_version"] == "c4-real-applicability-contract-v2", "Applicability Contract V2 required")
    require(applicability["authority_status"] == AUTHORITY_STATUS and applicability["condition_map_v2_sha256"] == V2_MAP_SHA256, "V2 authority binding differs")
    require(applicability["decision_recomputation_permitted"] is False and applicability["incident_disclosure_preserved"] is True, "V2 boundary weakened")
    require(contract["schema_version"] == "c4-real-corrected-judge-execution-contract-r4-v1", "execution contract version")
    require(contract["external_authorization_record_required"] is True and contract["authorization_environment_variable"] == "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION", "external gate missing")
    require(contract["authorization_environment_value"] == "AUTHORIZED_C4_REAL_CORRECTED_JUDGE_EXECUTION_R4", "wrong external gate")
    require(contract["authorization_record_schema_version"] == "c4-real-corrected-judge-execution-authorization-r4-v1", "authorization record version")
    require(contract["retryable_failure_codes"] == RETRYABLE and contract["maximum_byte_identical_invalid_output_retries"] == 1, "retry contract differs")
    require(contract["all_other_failures_non_retryable"] is True and contract["automatic_resume_permitted"] is False,
            "fail-closed contract differs")
    require(contract["phase_b_entry_receipt_sha256"] == ENTRY_SHA256 and contract["execution_authorized"] is False, "entry/dormancy binding differs")
    for field in ("package_id", "shard_id", "request_count", "maximum_physical_attempts", "blinded_judge_manifest_sha256"):
        require(contract[field] == config[field], "contract/config binding mismatch")
    rows = [strict_json(line, "blinded request") for line in members["BLINDED_JUDGE_REQUESTS.jsonl"].splitlines() if line.strip()]
    require(bool(rows) and len(rows) == config["request_count"] and config["maximum_physical_attempts"] == len(rows) * 2, "request/attempt counts differ")
    require(sha256_bytes(members["BLINDED_JUDGE_REQUESTS.jsonl"]) == config["blinded_judge_manifest_sha256"], "request manifest commitment differs")
    logical_ids, result_ids, payload_bytes = set(), set(), set()
    total_estimated_tokens = 0
    for position, row in enumerate(rows, 1):
        require(set(row) == REQUEST_FIELDS, "request metadata field set differs")
        require(row["schema_version"] == "c4-real-corrected-judge-execution-request-r4-v1", "request version")
        require(type(row["logical_order"]) is int and row["logical_order"] == position, "request order must be consecutive")
        require(bool(re.fullmatch(r"C4J4-[A-F0-9]{24}", row["logical_judge_request_id"])), "fresh R4 logical ID required")
        require(bool(re.fullmatch(r"R3B-[A-F0-9]{20}", row["judge_result_blind_id"])), "opaque result ID shape")
        payload = row["provider_payload"]
        raw = canonical_json_bytes(payload)
        require(sha256_bytes(raw) == row["provider_payload_sha256"], "complete provider payload hash differs")
        require(raw not in payload_bytes and row["logical_judge_request_id"] not in logical_ids and row["judge_result_blind_id"] not in result_ids, "duplicate payload or identity")
        logical_ids.add(row["logical_judge_request_id"]); result_ids.add(row["judge_result_blind_id"]); payload_bytes.add(raw)
        require(set(payload) == {"model", "messages", "temperature", "max_tokens", "stream", "response_format"}, "provider field set changed")
        require(payload["model"] == EXPECTED_MODEL and payload["temperature"] == 0 and payload["max_tokens"] == 2048 and payload["stream"] is False, "provider configuration differs")
        require(payload["response_format"] == {"type": "json_schema", "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": schema}}, "provider schema differs")
        require(len(payload["messages"]) == 1 and set(payload["messages"][0]) == {"role", "content"} and payload["messages"][0]["role"] == "system", "message structure differs")
        content = payload["messages"][0]["content"]
        require(content.count(BEGIN) == content.count(END) == 1, "embedded request boundaries")
        body = content.split(BEGIN, 1)[1].rsplit(END, 1)[0]
        blind = strict_json(body)
        require(set(blind) == BLIND_FIELDS and canonical_json_bytes(blind).decode() == body, "embedded field/byte contract")
        require(blind["schema_version"] == "rq3-blind-judge-request-v1" and blind["response_blind_id"] == row["judge_result_blind_id"], "embedded result identity differs")
        require(content == prompt.replace("{{BLIND_JUDGE_REQUEST_JSON}}", body), "prompt template changed")
        _validate_map(blind["frozen_applicability_map"])
        _forbid_hidden_identity(blind)
        estimate = math.ceil((sum(len(canonical_json_bytes(m)) for m in payload["messages"]) + len(canonical_json_bytes(payload["response_format"])) + 16) / 4)
        require(type(row["estimated_input_tokens"]) is int and row["estimated_input_tokens"] == estimate, "token estimate mismatch")
        total_estimated_tokens += estimate
    require(total_estimated_tokens == config["estimated_input_tokens"], "shard token estimate differs")
    return {"status": "PASS", "package_id": config["package_id"], "shard_id": config["shard_id"],
            "request_count": len(rows), "maximum_physical_attempts": 2 * len(rows),
            "estimated_input_tokens": total_estimated_tokens, "regular_file_count": 13,
            "request_timeout_seconds": 120.0, "blinded_judge_manifest_sha256": config["blinded_judge_manifest_sha256"],
            "package_zip_sha256": package_zip_sha256, "provider_calls": 0, "judge_execution": False}


def validate_package_zip(path):
    raw = Path(path).read_bytes()
    return validate_members(read_package_bytes(raw), package_zip_sha256=sha256_bytes(raw))


def validate_package_directory(path):
    directory = Path(path)
    require({p.name for p in directory.iterdir()} == ALLOWED_FILES, "directory allowlist differs")
    require(all(p.is_file() and not p.is_symlink() for p in directory.iterdir()), "directory contains nonregular source")
    return validate_members({name: (directory / name).read_bytes() for name in ALLOWED_FILES})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline validation only; this command performs no Judge execution.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package-zip", type=Path)
    group.add_argument("--package-dir", type=Path)
    args = parser.parse_args()
    result = validate_package_zip(args.package_zip) if args.package_zip else validate_package_directory(args.package_dir)
    print(json.dumps(result, sort_keys=True))
