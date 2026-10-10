#!/usr/bin/env python3
"""Offline, artifact-only validation for RQ3-REAL-R1B Memory routing.

This validator never calls a provider, retrieves or writes learner Memory,
opens Gold, scores routes, or assembles the later three-component P3 cache.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable, Mapping
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = HERE / "execution_output_v1"
PACKAGE = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip"
)
I1_INPUT = (
    ROOT
    / "evaluation/rq3_real_c4/i0_integration/"
    "c4_real_p3_route_input_manifest_v1.jsonl"
)
I1_ASSEMBLER = (
    ROOT / "evaluation/rq3_real_c4/i0_integration/assemble_frozen_routes.py"
)

STARTING_HEAD = "246e6ff64003caa4787716e00f050a2451dfca01"
EXPECTED_BRANCH = "research/rq3-real-r1-memory-route"
PACKAGE_ID = "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_R1"
PACKAGE_SHA256 = "fbda3819302a3c950b7febfa2c3c1cf44162943389ea6155c4bc12298c535640"
REQUESTS_SHA256 = "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326"
MODEL = "gpt-4o-mini-2024-07-18"
AUTHORIZATION_SHA256 = "0cd7b1173d9c7ae4ad7f1daf9978c62565a4ac27f5395b18f55f5350d8773b73"
TERMINAL_RESULTS_SHA256 = "0fd794e671a4f7d17247f5637ce358a634cb391ae2f79330471c69a8f1e44ef2"
RETRYABLE_ERRORS = {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}

PACKAGE_ALLOWLIST = (
    "EXECUTION_CONTRACT.json",
    "EXECUTION_PLAN.json",
    "PACKAGE_MANIFEST.json",
    "README.md",
    "execute_route_package_v2.py",
    "few_shot_examples.json",
    "prompt.txt",
    "requests.jsonl",
    "schema.json",
    "validate_route_package_v1.py",
)
PACKAGE_MEMBER_SHA256 = {
    "EXECUTION_CONTRACT.json": "74e65d784490b947e11e3cd70ad18ca324ac1797a974dd704ed2cd53835eb762",
    "EXECUTION_PLAN.json": "f6dc582104f577c2c9cf0afacd350a75d60c42ab62e07e67ff3e12100007fd61",
    "PACKAGE_MANIFEST.json": "5a7a5846396034a7feb65e5f6a48630b9e19c8f0f6bf77f9bc3e6a7df99e693d",
    "README.md": "92f6cbb91a0f9085165408690df218d4cfcb7fd5de7c74735b80aeebe8f13c70",
    "execute_route_package_v2.py": "3c09ee70b92609f5ea6b21490b198170e198a8af1db721ef1d9b1c7720a85ae2",
    "few_shot_examples.json": "837057a389de21abd1f7426b43809bcf46e6a0d3a2880f5ddc56790471975b6c",
    "prompt.txt": "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
    "requests.jsonl": REQUESTS_SHA256,
    "schema.json": "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
    "validate_route_package_v1.py": "0ffb88d64f778de61fedd9db269e7c5aa0ae7db40cbc9e2016eb1f308c42f7d2",
}
OUTPUT_HASHES = {
    "ROUTE_EXECUTION_REPORT.md": "5b916abbc89cc4ce1e7f1475546ff18b4c125344fbb5132c351677c7e27513d2",
    "route_attempt_records_v1.jsonl": "7dbd91c7e2c0bb84eae6ec8d980823ab8a3ecbff4ddb007297d4691c44412f3e",
    "route_error_registry_v1.jsonl": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "route_execution_preflight_receipt_v1.json": "ce2891c4c1ddd16b88867aa4752b83fa676f58218865c93f8be47c84d29709ca",
    "route_execution_status_v1.json": "4a5c407668b0d2fba29d4371b73c10223b3be683b51ad25547fa1ad0e200ae0f",
    "route_terminal_results_v1.jsonl": TERMINAL_RESULTS_SHA256,
    "route_usage_and_cost_v1.json": "32388e47b6230c2aac8f1d9ac19c0c8d9bc62cec3749de347749147c110cba98",
}
AUTHORIZATION_FIELDS = (
    "authorization_id",
    "authorization_scope",
    "authorized_by",
    "authorized_at",
    "package_id",
    "component",
    "logical_call_count",
    "maximum_physical_attempt_count",
    "status",
)
EXPECTED_AUTHORIZATION = {
    "authorization_id": "RQ3-REAL-R1-MEMORY-ROUTE-20260901",
    "authorization_scope": "RQ3_REAL_C4_P3_ROUTE_EXECUTION_R1",
    "authorized_by": "Ming Liu",
    "authorized_at": "2026-09-01T17:25:06Z",
    "package_id": PACKAGE_ID,
    "component": "MEMORY",
    "logical_call_count": 62,
    "maximum_physical_attempt_count": 124,
    "status": "AUTHORIZED",
}
SECRET_VALUE = re.compile(
    rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})",
    re.IGNORECASE,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def json_object(data: bytes, label: str) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8"))
    require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def jsonl_bytes(data: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        require(isinstance(value, dict), f"{label}:{line_number} is not an object")
        rows.append(value)
    return rows


def jsonl_path(path: Path) -> list[dict[str, Any]]:
    return jsonl_bytes(path.read_bytes(), str(path))


def package_members() -> dict[str, bytes]:
    require(PACKAGE.is_file() and not PACKAGE.is_symlink(), "Authoritative package is missing")
    require(sha256(PACKAGE.read_bytes()) == PACKAGE_SHA256, "Package SHA-256 mismatch")
    with ZipFile(PACKAGE) as archive:
        names = archive.namelist()
        require(tuple(sorted(names)) == PACKAGE_ALLOWLIST, "Package ten-member allowlist mismatch")
        require(len(names) == len(set(names)) == 10, "Package member duplication/count mismatch")
        for info in archive.infolist():
            mode = info.external_attr >> 16
            require(not info.is_dir(), f"Package contains a directory: {info.filename}")
            require(not stat.S_ISLNK(mode), f"Package contains a symlink: {info.filename}")
            require(Path(info.filename).name == info.filename, "Package path is not top-level")
        bad_crc = archive.testzip()
        require(bad_crc is None, f"Package CRC failure: {bad_crc}")
        return {name: archive.read(name) for name in names}


def requests_from_package() -> list[dict[str, Any]]:
    return jsonl_bytes(package_members()["requests.jsonl"], "requests.jsonl")


def validate_package_identity_and_allowlist() -> dict[str, Any]:
    members = package_members()
    require(set(members) == set(PACKAGE_MEMBER_SHA256), "Package member hash map mismatch")
    for name, expected in PACKAGE_MEMBER_SHA256.items():
        require(sha256(members[name]) == expected, f"Package member SHA-256 mismatch: {name}")
    manifest = json_object(members["PACKAGE_MANIFEST.json"], "PACKAGE_MANIFEST.json")
    plan = json_object(members["EXECUTION_PLAN.json"], "EXECUTION_PLAN.json")
    contract = json_object(members["EXECUTION_CONTRACT.json"], "EXECUTION_CONTRACT.json")
    require(manifest["package_id"] == plan["package_id"] == contract["package_id"] == PACKAGE_ID, "Package identity mismatch")
    require(manifest["route_component"] == plan["route_component"] == contract["component"] == "MEMORY", "Component mismatch")
    require(plan["frozen_component_method_id"] == "R2V2-MEMORY_SPECIALIST", "Method mismatch")
    require(plan["model"] == MODEL and plan["temperature"] == 0, "Model configuration mismatch")
    require(plan["max_output_tokens"] == 32, "Output-token limit mismatch")
    require(plan["logical_call_count"] == 62 and plan["maximum_physical_attempt_count"] == 124, "Call ceiling mismatch")
    require(contract["manual_retry_only_after"] == sorted(RETRYABLE_ERRORS), "Retry classes mismatch")
    require(contract["manual_retry_maximum"] == 1, "Manual retry maximum mismatch")
    require(contract["retry_payload_must_be_identical"] is True, "Retry identity gate mismatch")
    require(contract["automatic_resume_permitted"] is False, "Automatic resume must be false")
    return {"package_id": PACKAGE_ID, "member_count": len(members), "status": "PASS"}


def validate_no_bytecode_residue() -> dict[str, Any]:
    residue = [
        str(path.relative_to(HERE))
        for path in HERE.rglob("*")
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
    ]
    require(not residue, f"Bytecode residue exists: {residue}")
    names = package_members()
    require(not [name for name in names if "__pycache__" in name or name.endswith((".pyc", ".pyo"))], "Package contains bytecode residue")
    return {"residue_count": 0, "status": "PASS"}


def validate_authorization_record() -> dict[str, Any]:
    path = HERE / "route_execution_authorization_v1.json"
    require(sha256(path.read_bytes()) == AUTHORIZATION_SHA256, "Authorization SHA-256 mismatch")
    authorization = json_object(path.read_bytes(), path.name)
    require(tuple(authorization) == AUTHORIZATION_FIELDS, "Authorization field order/shape mismatch")
    require(authorization == EXPECTED_AUTHORIZATION, "Authorization values mismatch")
    return {"authorization_sha256": AUTHORIZATION_SHA256, "status": "PASS"}


def validate_request_population_and_order() -> dict[str, Any]:
    members = package_members()
    request_bytes = members["requests.jsonl"]
    require(sha256(request_bytes) == REQUESTS_SHA256, "Requests SHA-256 mismatch")
    require(I1_INPUT.read_bytes() == request_bytes, "Package requests differ from frozen I1 input manifest")
    requests = jsonl_bytes(request_bytes, "requests.jsonl")
    require(len(requests) == 62, "Logical request count is not 62")
    scenario_ids = [row.get("scenario_id") for row in requests]
    require(len(set(scenario_ids)) == 62, "Request scenario IDs are not unique")
    semantic_fields = {
        "current_query",
        "current_page",
        "dashboard_context",
        "visible_conversation_history",
    }
    groups: dict[str, list[str]] = defaultdict(list)
    for row in requests:
        require(set(row) == {"schema_version", "scenario_id", "semantic_input", "semantic_input_sha256", "status"}, "Request fields mismatch")
        require(row["status"] == "READY_FOR_P3_ROUTE_EXECUTION", "Request readiness mismatch")
        require(isinstance(row["semantic_input"], dict) and set(row["semantic_input"]) == semantic_fields, "Semantic input fields mismatch")
        require(sha256(canonical_bytes(row["semantic_input"])) == row["semantic_input_sha256"], "Semantic input SHA-256 mismatch")
        groups[row["semantic_input_sha256"]].append(row["scenario_id"])
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    require(len(groups) == 60, "Unique semantic-input count is not 60")
    require(duplicates == [["U022", "U026", "U031"]], "Identical-input group mismatch")
    return {"logical_requests": 62, "unique_scenario_ids": 62, "unique_semantic_inputs": 60, "status": "PASS"}


def load_execution() -> dict[str, Any]:
    require(OUTPUT.is_dir() and not OUTPUT.is_symlink(), "Execution output directory is missing")
    actual_names = {path.name for path in OUTPUT.iterdir() if path.is_file()}
    require(actual_names == set(OUTPUT_HASHES), "Execution output allowlist mismatch")
    require(not [path for path in OUTPUT.iterdir() if not path.is_file() or path.is_symlink()], "Execution output contains a non-regular member")
    for name, expected in OUTPUT_HASHES.items():
        require(sha256((OUTPUT / name).read_bytes()) == expected, f"Execution output SHA-256 mismatch: {name}")
    attempts = jsonl_path(OUTPUT / "route_attempt_records_v1.jsonl")
    terminals = jsonl_path(OUTPUT / "route_terminal_results_v1.jsonl")
    errors = jsonl_path(OUTPUT / "route_error_registry_v1.jsonl")
    status_value = json_object((OUTPUT / "route_execution_status_v1.json").read_bytes(), "status")
    usage = json_object((OUTPUT / "route_usage_and_cost_v1.json").read_bytes(), "usage")
    preflight = json_object((OUTPUT / "route_execution_preflight_receipt_v1.json").read_bytes(), "preflight")
    return {"attempts": attempts, "terminals": terminals, "errors": errors, "status": status_value, "usage": usage, "preflight": preflight}


def validate_completion_and_output_hashes() -> dict[str, Any]:
    data = load_execution()
    status_value = data["status"]
    require(status_value["state"] == "COMPLETED", "Execution state is not COMPLETED")
    require(status_value["logical_requests"] == status_value["logical_completed"] == 62, "Completion coverage mismatch")
    require(status_value["logical_failed"] == 0 and status_value["stop_reason"] is None, "Execution has a failure/stop reason")
    require(status_value["physical_attempts"] == status_value["provider_calls"] == 62, "Provider/attempt count mismatch")
    require(status_value["retry_count"] == 0, "Unexpected retry count")
    require(status_value["automatic_resume_permitted"] is False, "Automatic resume flag mismatch")
    require(status_value["continuation_requires_new_direct_user_authorization"] is True, "Continuation gate mismatch")
    for name, expected in status_value["output_sha256_excluding_status"].items():
        require(sha256((OUTPUT / name).read_bytes()) == expected, f"Final status output hash mismatch: {name}")
    preflight = data["preflight"]
    require(preflight["status"] == "PASS_CREATED_BEFORE_FIRST_PROVIDER_CALL", "Preflight receipt status mismatch")
    require(preflight["provider_calls_before_receipt"] == 0, "Provider call occurred before receipt")
    require(preflight["authorization_record_sha256"] == AUTHORIZATION_SHA256, "Preflight authorization hash mismatch")
    require(preflight["package_validation"]["status"] == "PASS_FROZEN_R1_ROUTE_PACKAGE", "Recorded package validation mismatch")
    return {"state": "COMPLETED", "valid_coverage": "62/62", "status": "PASS"}


def _completed_attempts() -> list[dict[str, Any]]:
    return [row for row in load_execution()["attempts"] if row.get("event") == "ATTEMPT_COMPLETED"]


def validate_retry_policy_and_physical_ceiling() -> dict[str, Any]:
    data = load_execution()
    attempts = data["attempts"]
    reserved = [row for row in attempts if row.get("event") == "ATTEMPT_RESERVED"]
    completed = [row for row in attempts if row.get("event") == "ATTEMPT_COMPLETED"]
    require(len(attempts) == 124 and len(reserved) == len(completed) == 62, "Attempt journal pairing/count mismatch")
    require(len(completed) <= 124, "Physical-attempt ceiling exceeded")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index in range(0, len(attempts), 2):
        reservation, completion = attempts[index : index + 2]
        require(reservation["event"] == "ATTEMPT_RESERVED" and completion["event"] == "ATTEMPT_COMPLETED", "Attempt reservation/completion ordering mismatch")
        for field in ("scenario_id", "semantic_input_sha256", "logical_order", "attempt_number", "provider_payload_sha256", "reserved_at"):
            require(reservation[field] == completion[field], f"Attempt pair mismatch: {field}")
        grouped[completion["scenario_id"]].append(completion)
    requests = requests_from_package()
    require(list(grouped) == [row["scenario_id"] for row in requests], "Attempt scenario ordering mismatch")
    for logical_order, request in enumerate(requests, 1):
        rows = grouped[request["scenario_id"]]
        require(rows[0]["attempt_number"] == 1, "Initial attempt missing")
        require(len(rows) <= 2, "More than one manual retry exists")
        if len(rows) == 2:
            require(rows[0]["outcome"] in RETRYABLE_ERRORS, "Retry followed a non-retryable outcome")
            require(rows[1]["attempt_number"] == 2, "Retry attempt number mismatch")
            require(rows[0]["provider_payload_sha256"] == rows[1]["provider_payload_sha256"], "Retry payload differs")
        require(rows[-1]["outcome"] == "VALID", "Logical request did not end validly")
        require(rows[-1]["logical_order"] == logical_order, "Logical attempt order mismatch")
    require(all(len(rows) == 1 for rows in grouped.values()), "This execution unexpectedly contains a retry")
    initial = [row for row in completed if row["attempt_number"] == 1]
    require(initial[0]["initial_start_interval_seconds"] is None, "First initial interval must be null")
    require(all(float(row["initial_start_interval_seconds"]) >= 2.0 for row in initial[1:]), "Initial calls were paced below 2 seconds")
    return {"physical_attempts": 62, "retries": 0, "maximum_physical_attempts": 124, "status": "PASS"}


def validate_strict_terminal_outputs_and_uniqueness() -> dict[str, Any]:
    data = load_execution()
    requests = requests_from_package()
    terminals = data["terminals"]
    completed = _completed_attempts()
    require(sha256((OUTPUT / "route_terminal_results_v1.jsonl").read_bytes()) == TERMINAL_RESULTS_SHA256, "Terminal-results SHA-256 mismatch")
    require(len(terminals) == 62, "Terminal result count is not 62")
    require(len({row["scenario_id"] for row in terminals}) == 62, "Terminal scenario IDs are not unique")
    require([row["scenario_id"] for row in terminals] == [row["scenario_id"] for row in requests], "Terminal order/population mismatch")
    completed_by_id = {row["scenario_id"]: row for row in completed}
    for logical_order, (request, terminal) in enumerate(zip(requests, terminals), 1):
        require(terminal["event"] == "TERMINAL_SUCCESS" and terminal["terminal_status"] == "VALID_OUTPUT", "Terminal is not a valid success")
        require(terminal["logical_order"] == logical_order, "Terminal logical order mismatch")
        require(terminal["semantic_input_sha256"] == request["semantic_input_sha256"], "Terminal semantic identity mismatch")
        require(type(terminal["output"]) is dict and set(terminal["output"]) == {"memory_required"}, "Terminal output fields mismatch")
        require(type(terminal["output"]["memory_required"]) is bool, "memory_required is not boolean")
        require(json.loads(terminal["raw_response_content"]) == terminal["output"], "Raw content differs from strict output")
        attempt = completed_by_id[terminal["scenario_id"]]
        require(attempt["outcome"] == "VALID" and attempt["strict_schema_status"] == "PASS", "Completed attempt is not strict-valid")
        require(attempt["parsed_strict_output"] == terminal["output"], "Attempt/terminal output mismatch")
        require(attempt["provider_payload_sha256"] == terminal["provider_payload_sha256"], "Attempt/terminal payload mismatch")
    return {"valid_terminal_results": 62, "unique_scenario_ids": 62, "strict_boolean_fields": 62, "status": "PASS"}


def validate_returned_model_and_errors() -> dict[str, Any]:
    data = load_execution()
    completed = [row for row in data["attempts"] if row.get("event") == "ATTEMPT_COMPLETED"]
    require(all(row["returned_model"] == MODEL for row in completed), "Completed-attempt model mismatch")
    require(all(row["returned_model"] == MODEL for row in data["terminals"]), "Terminal model mismatch")
    require(not data["errors"], "Error registry is not empty")
    return {
        "returned_model": MODEL,
        "provider_errors": 0,
        "json_errors": 0,
        "schema_errors": 0,
        "model_errors": 0,
        "status": "PASS",
    }


def validate_duplicate_input_consistency() -> dict[str, Any]:
    requests = requests_from_package()
    terminals = load_execution()["terminals"]
    output_by_id = {row["scenario_id"]: row["output"]["memory_required"] for row in terminals}
    groups: dict[str, list[str]] = defaultdict(list)
    for request in requests:
        groups[request["semantic_input_sha256"]].append(request["scenario_id"])
    duplicate_groups = [ids for ids in groups.values() if len(ids) > 1]
    require(duplicate_groups == [["U022", "U026", "U031"]], "Duplicate-input group mismatch")
    require(all(len({output_by_id[scenario_id] for scenario_id in group}) == 1 for group in duplicate_groups), "Identical inputs produced inconsistent outputs")
    return {"group_count": 1, "scenario_count": 3, "consistent": True, "status": "PASS"}


def validate_usage_arithmetic() -> dict[str, Any]:
    data = load_execution()
    completed = [row for row in data["attempts"] if row.get("event") == "ATTEMPT_COMPLETED"]
    require(all(type(row[field]) is int for row in completed for field in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")), "Attempt usage is incomplete")
    require(all(row["input_tokens"] + row["output_tokens"] == row["total_tokens"] for row in completed), "Per-attempt token arithmetic mismatch")
    input_tokens = sum(row["input_tokens"] for row in completed)
    cached_tokens = sum(row["cached_input_tokens"] for row in completed)
    output_tokens = sum(row["output_tokens"] for row in completed)
    total_tokens = sum(row["total_tokens"] for row in completed)
    require((input_tokens, cached_tokens, output_tokens, total_tokens) == (95771, 69248, 372, 96143), "Token totals mismatch")
    usage = data["usage"]
    require((usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (input_tokens, cached_tokens, output_tokens, total_tokens), "Usage report totals mismatch")
    regular_input = input_tokens - cached_tokens
    cost = (
        Decimal(regular_input) * Decimal("0.15")
        + Decimal(cached_tokens) * Decimal("0.075")
        + Decimal(output_tokens) * Decimal("0.60")
    ) / Decimal(1_000_000)
    approximate_cost = format(cost.quantize(Decimal("0.00000001")), "f")
    require(usage["approximate_cost_usd"] == approximate_cost == "0.00939525", "Approximate cost arithmetic mismatch")
    require(usage["cost_assumption"] == "REPORTED_CACHED_INPUT_USED", "Cost assumption mismatch")
    return {"input_tokens": input_tokens, "cached_input_tokens": cached_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens, "approximate_cost_usd": approximate_cost, "status": "PASS"}


def _walk_json(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def validate_no_secrets() -> dict[str, Any]:
    files = [path for path in HERE.rglob("*") if path.is_file()]
    for path in files:
        require(not SECRET_VALUE.search(path.read_bytes()), f"Potential credential value in {path}")
    for name, data in package_members().items():
        require(not SECRET_VALUE.search(data), f"Potential credential value in package member {name}")
    return {"credential_values_found": 0, "status": "PASS"}


def validate_zero_gold_and_scoring() -> dict[str, Any]:
    data = load_execution()
    documents: list[Any] = [data["preflight"], data["status"], data["usage"], *data["attempts"], *data["terminals"], *data["errors"]]
    forbidden_keys: list[str] = []
    for document in documents:
        for key, _ in _walk_json(document):
            lowered = key.lower()
            if "gold" in lowered or "score" in lowered:
                forbidden_keys.append(key)
    require(not forbidden_keys, f"Gold/scoring fields found: {sorted(set(forbidden_keys))}")
    require(data["status"]["routing_accuracy_calculated"] is False, "Status claims route accuracy")
    require(data["status"]["expected_labels_accessed"] is False, "Status claims expected-label access")
    require(data["usage"]["routing_accuracy_calculated"] is False, "Usage claims route accuracy")
    require(data["usage"]["expected_labels_accessed"] is False, "Usage claims expected-label access")
    return {"gold_fields": 0, "scoring_fields": 0, "accuracy_calculated": False, "expected_labels_accessed": False, "status": "PASS"}


def validate_zero_memory_io_and_scope() -> dict[str, Any]:
    runner = package_members()["execute_route_package_v2.py"].decode("utf-8")
    tree = ast.parse(runner)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    forbidden_imports = {"sqlite3", "firebase_admin", "pymongo", "redis", "chromadb"}
    require(not (imported_roots & forbidden_imports), "Runner imports a Memory/database interface")
    lowered = runner.lower()
    forbidden_fragments = ("c4_memory_provider", "memory_writer", "learner_memory", "firestore", "firebase", "sqlite")
    require(not [fragment for fragment in forbidden_fragments if fragment in lowered], "Runner contains a Memory/database access path")
    outputs = load_execution()["terminals"]
    require(all(set(row["output"]) == {"memory_required"} for row in outputs), "Execution emitted a non-Memory-route field")
    return {
        "learner_memory_retrievals": 0,
        "learner_memory_writes": 0,
        "generated_answers": 0,
        "judge_calls": 0,
        "rag_route_calls": 0,
        "b4_planning_route_calls": 0,
        "streamlit_launches": 0,
        "status": "PASS",
    }


def validate_i1_compatibility() -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from evaluation.rq3_real_c4.i0_integration.assemble_frozen_routes import (
        successful_by_scenario,
    )

    require(sha256(I1_INPUT.read_bytes()) == REQUESTS_SHA256, "Frozen I1 input hash mismatch")
    require(sha256(I1_ASSEMBLER.read_bytes()) == "e2c17d4ed93668368bb66aca39c5ad48d3e06dcd8d042d72de6fda590c1f3dd8", "I1 assembler hash mismatch")
    expected = {row["scenario_id"]: row for row in jsonl_path(I1_INPUT) if row["status"] == "READY_FOR_P3_ROUTE_EXECUTION"}
    accepted = successful_by_scenario(OUTPUT / "route_terminal_results_v1.jsonl", "memory_required")
    require(set(accepted) == set(expected), "I1 Memory terminal population mismatch")
    for scenario_id, terminal in accepted.items():
        require(terminal["semantic_input_sha256"] == expected[scenario_id]["semantic_input_sha256"], "I1 semantic-input identity mismatch")
    return {"consumer": "assemble_frozen_routes.successful_by_scenario", "accepted_memory_terminals": 62, "assembly_executed": False, "status": "PASS_I1_COMPATIBLE"}


def validate_derived_audit_artifacts() -> dict[str, Any]:
    source = json_object((HERE / "memory_route_execution_source_manifest_v1.json").read_bytes(), "source manifest")
    audit = json_object((HERE / "memory_route_execution_audit_v1.json").read_bytes(), "audit")
    require(source["status"] == "PASS_FROZEN_R1_MEMORY_ROUTE_SOURCES", "Source manifest status mismatch")
    require(source["authoritative_package"]["sha256"] == PACKAGE_SHA256, "Source manifest package hash mismatch")
    require(source["authorization_record"]["sha256"] == AUTHORIZATION_SHA256, "Source manifest authorization hash mismatch")
    require(source["execution_outputs"]["member_sha256"] == OUTPUT_HASHES, "Source manifest output hashes mismatch")
    require(audit["status"] == "PASS_RQ3_REAL_R1B_MEMORY_ROUTE_EXECUTION", "Audit status mismatch")
    require(audit["memory_route_counts"] == {"memory_no_count": 43, "memory_yes_count": 19}, "Audit route counts mismatch")
    require(audit["duplicate_input_consistency"]["consistent"] is True, "Audit duplicate consistency mismatch")
    require(audit["route_accuracy_calculated"] is False, "Audit contains route accuracy")
    return {"source_manifest": "PASS", "execution_audit": "PASS", "status": "PASS"}


VALIDATIONS = (
    validate_package_identity_and_allowlist,
    validate_no_bytecode_residue,
    validate_authorization_record,
    validate_request_population_and_order,
    validate_completion_and_output_hashes,
    validate_retry_policy_and_physical_ceiling,
    validate_strict_terminal_outputs_and_uniqueness,
    validate_returned_model_and_errors,
    validate_duplicate_input_consistency,
    validate_usage_arithmetic,
    validate_no_secrets,
    validate_zero_gold_and_scoring,
    validate_zero_memory_io_and_scope,
    validate_i1_compatibility,
    validate_derived_audit_artifacts,
)


def validate_all() -> dict[str, Any]:
    checks = {function.__name__: function() for function in VALIDATIONS}
    return {
        "schema_version": "rq3-real-r1b-memory-route-offline-validation-v1",
        "status": "PASS_RQ3_REAL_R1B_MEMORY_ROUTE_EXECUTION",
        "check_count": len(checks),
        "checks": checks,
        "provider_calls_by_validator": 0,
        "gold_accessed_by_validator": False,
        "route_accuracy_calculated_by_validator": False,
    }


def main() -> int:
    print(json.dumps(validate_all(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
