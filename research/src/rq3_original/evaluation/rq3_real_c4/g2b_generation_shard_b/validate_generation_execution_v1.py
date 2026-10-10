#!/usr/bin/env python3
"""Offline mechanical validator for frozen C4 REAL generation shard B.

This validator uses only Python's standard library. It never constructs a
provider client and never reads an API key.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import zipfile


EXPECTED_PACKAGE_ID = "C4_REAL_GENERATION_SHARD_B_R2_20260901"
EXPECTED_SHARD = "B"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-G2B-RESPONSE-GENERATION-20260901"
EXPECTED_AUTHORIZATION_SHA256 = (
    "c052463d2223f5277842bd2df0ce98d321e87e539bfd24301127b354bdfc4822"
)
EXPECTED_PACKAGE_SHA256 = (
    "a6deea49c3c90b1c28a2e0afffe50b61b11ae6513415f8da0ba4f9c3681a0b8d"
)
EXPECTED_MANIFEST_SHA256 = (
    "3e6fabcf523919c93e64aae735f56708210743d2604ed5d4be01a95717b0d690"
)
EXPECTED_PROMPT_SHA256 = (
    "41748d1f3a69ce6623e607551a8473228c0724871e16e392ecd7872b4e550b21"
)
EXPECTED_SCHEMA_SHA256 = (
    "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
)
EXPECTED_CONFIGURATION_SHA256 = (
    "3a589b593c964288ab5976718dd4fcb1e2d45186d978ee201b235a7aaf25059c"
)
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_REQUEST_COUNT = 62
EXPECTED_MAXIMUM_ATTEMPTS = 124

PACKAGE_FILES = frozenset(
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
OUTPUT_FILES = frozenset(
    {
        "GENERATION_ATTEMPT_JOURNAL.jsonl",
        "GENERATION_ERROR_REGISTRY.jsonl",
        "GENERATION_EXECUTION_REPORT.md",
        "GENERATION_EXECUTION_STATUS.json",
        "GENERATION_PREFLIGHT_RECEIPT.json",
        "GENERATION_TERMINAL_JOURNAL.jsonl",
        "GENERATION_USAGE_AND_COST.json",
    }
)
AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "authorized_by",
        "authorized_at_utc",
        "package_id",
        "shard",
        "request_count",
        "maximum_physical_attempts",
        "package_sha256",
        "blinded_manifest_sha256",
        "status",
    }
)
REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "logical_generation_request_id",
        "response_blind_id",
        "provider_payload_sha256",
        "estimated_input_tokens",
        "provider_payload",
    }
)
ATTEMPT_FIELDS = frozenset(
    {
        "schema_version",
        "logical_order",
        "logical_generation_request_id",
        "response_blind_id",
        "attempt_number",
        "provider_payload_sha256",
        "requested_model",
        "returned_model",
        "provider_response_id",
        "system_fingerprint",
        "finish_reason",
        "raw_response_content",
        "parsed_output",
        "strict_validation_status",
        "prompt_tokens",
        "cached_input_tokens",
        "completion_tokens",
        "total_tokens",
        "started_at_utc",
        "completed_at_utc",
        "latency_ms",
        "error",
    }
)
VALID_TERMINAL_FIELDS = frozenset(
    {
        "schema_version",
        "logical_order",
        "logical_generation_request_id",
        "response_blind_id",
        "terminal_status",
        "physical_attempts",
        "provider_payload_sha256",
        "requested_model",
        "returned_model",
        "provider_response_id",
        "system_fingerprint",
        "finish_reason",
        "raw_response_content",
        "parsed_output",
        "prompt_tokens",
        "cached_input_tokens",
        "completion_tokens",
        "total_tokens",
        "recorded_at_utc",
    }
)
PROHIBITED_RESPONSE_KEYS = frozenset(
    {
        "gold",
        "gold_label",
        "final_gold",
        "condition",
        "condition_id",
        "condition_name",
        "mode",
        "mode_id",
        "mode_name",
        "route",
        "route_id",
        "route_label",
        "judge",
        "judge_result",
        "rating",
        "score",
        "score_value",
        "mechanism_score",
        "response_quality_score",
    }
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
    re.compile(r"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+", re.IGNORECASE),
)

CHECK_NAMES = (
    "package_zip_identity",
    "package_member_allowlist",
    "extracted_package_identity",
    "source_member_hashes",
    "blinded_manifest_identity",
    "frozen_prompt_schema_configuration_identity",
    "authorization_shape_and_binding",
    "execution_output_exclusivity",
    "preflight_receipt",
    "runtime_identity",
    "request_population",
    "attempt_journal_order",
    "terminal_uniqueness",
    "logical_request_id_uniqueness",
    "response_blind_id_uniqueness",
    "provider_payload_hash_binding",
    "strict_result_shape",
    "non_empty_answer_text",
    "raw_json_parse_and_schema",
    "returned_model_identity",
    "retry_compliance",
    "physical_attempt_ceiling",
    "complete_fail_closed_status",
    "usage_arithmetic",
    "answer_hashes",
    "secret_absence",
    "prohibited_response_fields_absence",
    "zero_error_and_evaluation_calls",
    "future_response_integration_compatibility",
    "bytecode_hygiene",
)


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} is not a JSON object")
        rows.append(value)
    return rows


def recursive_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from recursive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from recursive_keys(nested)


def utc_now_seconds() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    content = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def collect_audit(
    artifact_dir: Path,
    package_zip: Path,
    extracted_package: Path,
    *,
    audited_at_utc: str | None = None,
) -> dict[str, Any]:
    artifact_dir = artifact_dir.resolve()
    package_zip = package_zip.resolve()
    extracted_package = extracted_package.resolve()
    output_dir = artifact_dir / "execution_output_v1"
    authorization_path = artifact_dir / "generation_execution_authorization_v1.json"
    source_manifest_path = artifact_dir / "generation_execution_source_manifest_v1.json"

    source_manifest = load_json(source_manifest_path)
    authorization = load_json(authorization_path)
    status = load_json(output_dir / "GENERATION_EXECUTION_STATUS.json")
    preflight = load_json(output_dir / "GENERATION_PREFLIGHT_RECEIPT.json")
    usage_file = load_json(output_dir / "GENERATION_USAGE_AND_COST.json")
    manifest_rows = load_jsonl(extracted_package / "BLINDED_REQUESTS.jsonl")
    attempt_rows = load_jsonl(output_dir / "GENERATION_ATTEMPT_JOURNAL.jsonl")
    terminal_rows = load_jsonl(output_dir / "GENERATION_TERMINAL_JOURNAL.jsonl")
    error_rows = load_jsonl(output_dir / "GENERATION_ERROR_REGISTRY.jsonl")

    checks: dict[str, bool] = {}

    def record(name: str, condition: Any) -> None:
        if name not in CHECK_NAMES:
            raise KeyError(f"unknown audit check: {name}")
        checks[name] = bool(condition)

    package_digest = sha256_file(package_zip)
    record("package_zip_identity", package_digest == EXPECTED_PACKAGE_SHA256)

    with zipfile.ZipFile(package_zip) as archive:
        zip_names = archive.namelist()
        zip_members = {name: archive.read(name) for name in zip_names if not name.endswith("/")}
    package_allowlist_ok = (
        len(zip_names) == len(set(zip_names))
        and set(zip_names) == PACKAGE_FILES
        and all(Path(name).name == name and not name.endswith("/") for name in zip_names)
    )
    record("package_member_allowlist", package_allowlist_ok)

    extracted_entries = list(extracted_package.iterdir())
    extracted_identity_ok = (
        {path.name for path in extracted_entries} == PACKAGE_FILES
        and all(path.is_file() for path in extracted_entries)
        and all(
            zip_members.get(name) == (extracted_package / name).read_bytes()
            for name in PACKAGE_FILES
        )
    )
    record("extracted_package_identity", extracted_identity_ok)

    declared_member_hashes = source_manifest.get("package_member_sha256", {})
    actual_member_hashes = {
        name: sha256_file(extracted_package / name) for name in sorted(PACKAGE_FILES)
    }
    embedded_source_hashes = load_json(extracted_package / "PACKAGE_SOURCE_HASHES.json")
    embedded_member_hashes = embedded_source_hashes.get("member_sha256_excluding_self", {})
    source_hashes_ok = (
        declared_member_hashes == actual_member_hashes
        and all(actual_member_hashes.get(name) == digest for name, digest in embedded_member_hashes.items())
        and set(embedded_member_hashes) == PACKAGE_FILES - {"PACKAGE_SOURCE_HASHES.json"}
        and source_manifest.get("package_zip_sha256") == EXPECTED_PACKAGE_SHA256
        and source_manifest.get("package_member_count") == 10
    )
    record("source_member_hashes", source_hashes_ok)

    manifest_digest = sha256_file(extracted_package / "BLINDED_REQUESTS.jsonl")
    record(
        "blinded_manifest_identity",
        manifest_digest == EXPECTED_MANIFEST_SHA256
        and source_manifest.get("blinded_manifest_sha256") == EXPECTED_MANIFEST_SHA256,
    )
    record(
        "frozen_prompt_schema_configuration_identity",
        sha256_file(extracted_package / "GENERATION_PROMPT.txt") == EXPECTED_PROMPT_SHA256
        and sha256_file(extracted_package / "GENERATION_SCHEMA.json") == EXPECTED_SCHEMA_SHA256
        and sha256_file(extracted_package / "GENERATION_CONFIGURATION.json")
        == EXPECTED_CONFIGURATION_SHA256,
    )

    authorization_ok = (
        set(authorization) == AUTHORIZATION_FIELDS
        and authorization.get("schema_version")
        == "c4-real-response-generation-authorization-r2"
        and authorization.get("authorization_id") == EXPECTED_AUTHORIZATION_ID
        and authorization.get("authorized_by") == "Ming Liu"
        and authorization.get("package_id") == EXPECTED_PACKAGE_ID
        and authorization.get("shard") == EXPECTED_SHARD
        and authorization.get("request_count") == EXPECTED_REQUEST_COUNT
        and authorization.get("maximum_physical_attempts") == EXPECTED_MAXIMUM_ATTEMPTS
        and authorization.get("package_sha256") == EXPECTED_PACKAGE_SHA256
        and authorization.get("blinded_manifest_sha256") == EXPECTED_MANIFEST_SHA256
        and authorization.get("status") == "AUTHORIZED"
        and isinstance(authorization.get("authorized_at_utc"), str)
        and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", authorization["authorized_at_utc"]))
        and sha256_file(authorization_path) == EXPECTED_AUTHORIZATION_SHA256
    )
    record("authorization_shape_and_binding", authorization_ok)

    output_entries = list(output_dir.iterdir())
    record(
        "execution_output_exclusivity",
        {path.name for path in output_entries} == OUTPUT_FILES
        and all(path.is_file() for path in output_entries),
    )

    preflight_ok = (
        preflight.get("schema_version")
        == "c4-real-generation-preflight-start-receipt-v2"
        and preflight.get("status") == "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION"
        and preflight.get("package_id") == EXPECTED_PACKAGE_ID
        and preflight.get("shard") == EXPECTED_SHARD
        and preflight.get("request_count") == EXPECTED_REQUEST_COUNT
        and preflight.get("maximum_physical_attempts") == EXPECTED_MAXIMUM_ATTEMPTS
        and preflight.get("package_sha256") == EXPECTED_PACKAGE_SHA256
        and preflight.get("blinded_manifest_sha256") == EXPECTED_MANIFEST_SHA256
        and preflight.get("authorization_id") == EXPECTED_AUTHORIZATION_ID
        and preflight.get("authorization_record_sha256") == EXPECTED_AUTHORIZATION_SHA256
        and preflight.get("runtime_constructed") is False
        and preflight.get("client_constructed") is False
        and preflight.get("automatic_resume") is False
        and preflight.get("judge_calls") == 0
    )
    record("preflight_receipt", preflight_ok)

    runtime = status.get("runtime_identity")
    runtime_ok = isinstance(runtime, Mapping) and runtime == {
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
        "automatic_sdk_retries": 0,
        "openai_sdk_version": "1.109.1",
        "python_path": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
    }
    record("runtime_identity", runtime_ok)

    manifest_field_ok = all(set(row) == REQUEST_FIELDS for row in manifest_rows)
    payload_hash_ok = True
    payload_configuration_ok = True
    for row in manifest_rows:
        payload = row.get("provider_payload")
        if not isinstance(payload, Mapping):
            payload_hash_ok = False
            payload_configuration_ok = False
            continue
        payload_hash_ok &= sha256_bytes(canonical_bytes(payload)) == row.get(
            "provider_payload_sha256"
        )
        payload_configuration_ok &= (
            payload.get("model") == EXPECTED_MODEL
            and payload.get("temperature") == 0
            and payload.get("max_tokens") == 512
            and payload.get("stream") is False
            and "tools" not in payload
        )
    record(
        "request_population",
        len(manifest_rows) == EXPECTED_REQUEST_COUNT
        and manifest_field_ok
        and payload_configuration_ok,
    )

    expected_by_order = {index: row for index, row in enumerate(manifest_rows, 1)}
    attempts_by_order: dict[int, list[dict[str, Any]]] = {}
    attempt_fields_ok = True
    attempt_order_ok = True
    last_pair = (0, 0)
    for attempt in attempt_rows:
        attempt_fields_ok &= set(attempt) == ATTEMPT_FIELDS
        order = attempt.get("logical_order")
        number = attempt.get("attempt_number")
        if not isinstance(order, int) or not isinstance(number, int):
            attempt_order_ok = False
            continue
        pair = (order, number)
        attempt_order_ok &= pair > last_pair
        last_pair = pair
        attempts_by_order.setdefault(order, []).append(attempt)
    record(
        "attempt_journal_order",
        attempt_fields_ok
        and attempt_order_ok
        and set(attempts_by_order) == set(range(1, EXPECTED_REQUEST_COUNT + 1)),
    )

    terminal_orders = [row.get("logical_order") for row in terminal_rows]
    record(
        "terminal_uniqueness",
        len(terminal_rows) == EXPECTED_REQUEST_COUNT
        and terminal_orders == list(range(1, EXPECTED_REQUEST_COUNT + 1))
        and all(set(row) == VALID_TERMINAL_FIELDS for row in terminal_rows)
        and all(row.get("terminal_status") == "VALID_RESPONSE" for row in terminal_rows),
    )

    manifest_logical_ids = [row.get("logical_generation_request_id") for row in manifest_rows]
    terminal_logical_ids = [row.get("logical_generation_request_id") for row in terminal_rows]
    manifest_blind_ids = [row.get("response_blind_id") for row in manifest_rows]
    terminal_blind_ids = [row.get("response_blind_id") for row in terminal_rows]
    record(
        "logical_request_id_uniqueness",
        len(set(manifest_logical_ids)) == EXPECTED_REQUEST_COUNT
        and terminal_logical_ids == manifest_logical_ids
        and len(set(terminal_logical_ids)) == EXPECTED_REQUEST_COUNT,
    )
    record(
        "response_blind_id_uniqueness",
        len(set(manifest_blind_ids)) == EXPECTED_REQUEST_COUNT
        and terminal_blind_ids == manifest_blind_ids
        and len(set(terminal_blind_ids)) == EXPECTED_REQUEST_COUNT,
    )

    journal_binding_ok = payload_hash_ok
    for order in range(1, EXPECTED_REQUEST_COUNT + 1):
        expected = expected_by_order[order]
        for observed in attempts_by_order.get(order, []):
            journal_binding_ok &= (
                observed.get("logical_generation_request_id")
                == expected.get("logical_generation_request_id")
                and observed.get("response_blind_id") == expected.get("response_blind_id")
                and observed.get("provider_payload_sha256")
                == expected.get("provider_payload_sha256")
            )
        terminal = terminal_rows[order - 1] if len(terminal_rows) >= order else {}
        journal_binding_ok &= terminal.get("provider_payload_sha256") == expected.get(
            "provider_payload_sha256"
        )
    record("provider_payload_hash_binding", journal_binding_ok)

    strict_shape_ok = True
    non_empty_ok = True
    raw_json_ok = True
    answer_hashes: list[dict[str, Any]] = []
    answer_set_projection: list[dict[str, Any]] = []
    json_error_count = 0
    schema_error_count = 0
    prohibited_key_count = 0
    model_error_count = 0
    for terminal in terminal_rows:
        parsed = terminal.get("parsed_output")
        strict_shape_ok &= isinstance(parsed, dict) and set(parsed) == {"answer_text"}
        answer = parsed.get("answer_text") if isinstance(parsed, dict) else None
        non_empty_ok &= isinstance(answer, str) and bool(answer.strip())
        raw = terminal.get("raw_response_content")
        try:
            raw_parsed = json.loads(raw) if isinstance(raw, str) else None
        except json.JSONDecodeError:
            raw_parsed = None
            json_error_count += 1
        if not isinstance(raw_parsed, dict) or set(raw_parsed) != {"answer_text"}:
            schema_error_count += 1
        raw_json_ok &= raw_parsed == parsed
        prohibited_key_count += sum(
            1 for key in recursive_keys(parsed) if key.casefold() in PROHIBITED_RESPONSE_KEYS
        )
        model_error_count += int(terminal.get("returned_model") != EXPECTED_MODEL)
        if isinstance(answer, str):
            answer_hash = sha256_bytes(answer.encode("utf-8"))
            answer_hashes.append(
                {
                    "logical_order": terminal.get("logical_order"),
                    "logical_generation_request_id": terminal.get(
                        "logical_generation_request_id"
                    ),
                    "response_blind_id": terminal.get("response_blind_id"),
                    "answer_text_sha256": answer_hash,
                }
            )
            answer_set_projection.append(
                {
                    "logical_order": terminal.get("logical_order"),
                    "logical_generation_request_id": terminal.get(
                        "logical_generation_request_id"
                    ),
                    "response_blind_id": terminal.get("response_blind_id"),
                    "answer_text": answer,
                }
            )
    record("strict_result_shape", strict_shape_ok)
    record("non_empty_answer_text", non_empty_ok)
    record(
        "raw_json_parse_and_schema",
        raw_json_ok and json_error_count == 0 and schema_error_count == 0,
    )

    all_model_ok = all(
        row.get("requested_model") == EXPECTED_MODEL
        and row.get("returned_model") == EXPECTED_MODEL
        for row in attempt_rows
    ) and all(
        row.get("requested_model") == EXPECTED_MODEL
        and row.get("returned_model") == EXPECTED_MODEL
        for row in terminal_rows
    )
    record("returned_model_identity", all_model_ok and model_error_count == 0)

    retry_ok = True
    retry_count = 0
    for order in range(1, EXPECTED_REQUEST_COUNT + 1):
        observed = attempts_by_order.get(order, [])
        numbers = [row.get("attempt_number") for row in observed]
        retry_ok &= numbers in ([1], [1, 2])
        if numbers == [1, 2]:
            retry_count += 1
            retry_ok &= (
                observed[0].get("strict_validation_status")
                == "INVALID_JSON_OR_STRICT_SCHEMA"
                and observed[0].get("provider_payload_sha256")
                == observed[1].get("provider_payload_sha256")
            )
        if observed:
            terminal = terminal_rows[order - 1]
            retry_ok &= terminal.get("physical_attempts") == len(observed)
    record("retry_compliance", retry_ok)
    record(
        "physical_attempt_ceiling",
        EXPECTED_REQUEST_COUNT <= len(attempt_rows) <= EXPECTED_MAXIMUM_ATTEMPTS
        and status.get("physical_attempt_count") == len(attempt_rows)
        and status.get("maximum_physical_attempts") == EXPECTED_MAXIMUM_ATTEMPTS,
    )

    complete_ok = (
        status.get("schema_version") == "c4-real-generation-execution-status-v2"
        and status.get("status") == "COMPLETE"
        and status.get("stop_reason") is None
        and status.get("request_count") == EXPECTED_REQUEST_COUNT
        and status.get("valid_response_count") == EXPECTED_REQUEST_COUNT
        and status.get("incomplete_logical_request_count") == 0
        and status.get("unattempted_logical_request_count") == 0
        and status.get("automatic_resume") is False
        and status.get("continuation_requires_new_direct_authorization") is True
    )
    record("complete_fail_closed_status", complete_ok)

    prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in attempt_rows)
    completion_tokens = sum(int(row.get("completion_tokens") or 0) for row in attempt_rows)
    total_tokens = sum(int(row.get("total_tokens") or 0) for row in attempt_rows)
    cached_values = [row.get("cached_input_tokens") for row in attempt_rows]
    cached_detail_complete = all(isinstance(value, int) for value in cached_values)
    cached_tokens = sum(int(value) for value in cached_values if isinstance(value, int))
    responses_without_cached_detail = sum(value is None for value in cached_values)
    per_attempt_arithmetic_ok = all(
        isinstance(row.get("prompt_tokens"), int)
        and isinstance(row.get("completion_tokens"), int)
        and isinstance(row.get("total_tokens"), int)
        and row["total_tokens"] == row["prompt_tokens"] + row["completion_tokens"]
        and (
            row.get("cached_input_tokens") is None
            or (
                isinstance(row.get("cached_input_tokens"), int)
                and 0 <= row["cached_input_tokens"] <= row["prompt_tokens"]
            )
        )
        for row in attempt_rows
    )
    usage_ok = (
        per_attempt_arithmetic_ok
        and total_tokens == prompt_tokens + completion_tokens
        and usage_file.get("prompt_tokens") == prompt_tokens
        and usage_file.get("cached_input_tokens") == cached_tokens
        and usage_file.get("completion_tokens") == completion_tokens
        and usage_file.get("total_tokens") == total_tokens
        and usage_file.get("responses_without_cached_token_detail")
        == responses_without_cached_detail
        and usage_file.get("usage_arithmetic_valid") is True
        and usage_file.get("provider_calls_observed") == len(attempt_rows)
    )
    record("usage_arithmetic", usage_ok)

    answer_set_sha256 = sha256_bytes(canonical_bytes(answer_set_projection))
    record(
        "answer_hashes",
        len(answer_hashes) == EXPECTED_REQUEST_COUNT
        and all(re.fullmatch(r"[0-9a-f]{64}", row["answer_text_sha256"]) for row in answer_hashes),
    )

    secret_match_count = 0
    for path in artifact_dir.rglob("*"):
        if not path.is_file() or path.name.endswith(".pyc"):
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        secret_match_count += sum(len(pattern.findall(text)) for pattern in SECRET_PATTERNS)
    record("secret_absence", secret_match_count == 0)

    request_prohibited_keys = sum(
        1
        for row in manifest_rows
        for key in recursive_keys(row.get("provider_payload"))
        if key.casefold() in PROHIBITED_RESPONSE_KEYS
    )
    record(
        "prohibited_response_fields_absence",
        prohibited_key_count == 0 and request_prohibited_keys == 0,
    )

    provider_error_count = sum(row.get("error") is not None for row in attempt_rows)
    zero_calls_ok = (
        not error_rows
        and provider_error_count == 0
        and status.get("judge_calls") == 0
        and status.get("scoring_calls") == 0
        and preflight.get("judge_calls") == 0
        and usage_file.get("judge_calls") == 0
    )
    record("zero_error_and_evaluation_calls", zero_calls_ok)

    integration_ok = (
        strict_shape_ok
        and non_empty_ok
        and terminal_orders == list(range(1, EXPECTED_REQUEST_COUNT + 1))
        and terminal_logical_ids == manifest_logical_ids
        and terminal_blind_ids == manifest_blind_ids
        and all(
            isinstance(row.get("provider_payload_sha256"), str)
            and isinstance(row.get("parsed_output", {}).get("answer_text"), str)
            for row in terminal_rows
        )
    )
    record("future_response_integration_compatibility", integration_ok)

    bytecode_paths = [
        path
        for root in (artifact_dir, extracted_package)
        for path in root.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc"
    ]
    record("bytecode_hygiene", not bytecode_paths)

    if set(checks) != set(CHECK_NAMES):
        raise AssertionError("audit check population mismatch")

    standard_cost = (
        Decimal(prompt_tokens) * Decimal("0.15")
        + Decimal(completion_tokens) * Decimal("0.60")
    ) / Decimal(1_000_000)
    cached_aware_cost = None
    if cached_detail_complete:
        cached_aware_cost = (
            Decimal(prompt_tokens - cached_tokens) * Decimal("0.15")
            + Decimal(cached_tokens) * Decimal("0.075")
            + Decimal(completion_tokens) * Decimal("0.60")
        ) / Decimal(1_000_000)

    output_hashes = {
        path.name: sha256_file(path) for path in sorted(output_dir.iterdir()) if path.is_file()
    }
    all_passed = all(checks.values())
    return {
        "schema_version": "c4-real-generation-execution-audit-v1",
        "status": "PASS" if all_passed else "FAIL",
        "audited_at_utc": audited_at_utc or utc_now_seconds(),
        "package_id": EXPECTED_PACKAGE_ID,
        "shard": EXPECTED_SHARD,
        "authorization_id": EXPECTED_AUTHORIZATION_ID,
        "checks": {name: "PASS" if checks[name] else "FAIL" for name in CHECK_NAMES},
        "check_summary": {
            "passed": sum(checks.values()),
            "failed": len(checks) - sum(checks.values()),
            "total": len(checks),
        },
        "runtime_identity": dict(runtime) if isinstance(runtime, Mapping) else runtime,
        "execution_counts": {
            "logical_requests": EXPECTED_REQUEST_COUNT,
            "physical_attempts": len(attempt_rows),
            "retries": retry_count,
            "valid_responses": len(terminal_rows),
            "incomplete_logical_requests": status.get("incomplete_logical_request_count"),
            "unattempted_logical_requests": status.get("unattempted_logical_request_count"),
        },
        "error_counts": {
            "provider_or_runtime_errors": provider_error_count,
            "invalid_json": json_error_count,
            "strict_schema": schema_error_count,
            "returned_model_mismatch": model_error_count,
            "unresolved_error_registry_entries": len(error_rows),
        },
        "returned_model": EXPECTED_MODEL,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "cached_input_tokens": cached_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "responses_without_cached_token_detail": responses_without_cached_detail,
        },
        "descriptive_cost_estimates": {
            "rates_as_of": "2026-09-01",
            "currency": "USD",
            "non_cached_input_per_1m": "0.15",
            "cached_input_per_1m": "0.075",
            "output_per_1m": "0.60",
            "standard_non_cached_input_estimate": format(standard_cost, ".9f"),
            "cached_input_aware_estimate": (
                format(cached_aware_cost, ".9f") if cached_aware_cost is not None else None
            ),
            "exact_billed_amount_claimed": False,
        },
        "hashes": {
            "package_zip_sha256": package_digest,
            "blinded_manifest_sha256": manifest_digest,
            "authorization_record_sha256": sha256_file(authorization_path),
            "terminal_journal_sha256": output_hashes["GENERATION_TERMINAL_JOURNAL.jsonl"],
            "answer_set_sha256": answer_set_sha256,
            "answer_set_hash_definition": (
                "SHA-256 of canonical UTF-8 JSON array in terminal order with fields "
                "logical_order, logical_generation_request_id, response_blind_id, answer_text; "
                "sort_keys=true, separators=comma-colon, ensure_ascii=false"
            ),
            "output_file_sha256": output_hashes,
        },
        "answer_text_sha256": answer_hashes,
        "prohibited_content": {
            "secret_scan_matches": secret_match_count,
            "prohibited_request_field_keys": request_prohibited_keys,
            "prohibited_response_field_keys": prohibited_key_count,
            "judge_calls": status.get("judge_calls"),
            "scoring_calls": status.get("scoring_calls"),
        },
        "execution_boundary": {
            "generation_only": True,
            "automatic_resume": status.get("automatic_resume"),
            "continuation_requires_new_direct_authorization": status.get(
                "continuation_requires_new_direct_authorization"
            ),
            "response_integration_performed": False,
            "unblinding_performed": False,
            "human_rating_performed": False,
            "statistical_analysis_performed": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--package-zip", type=Path, required=True)
    parser.add_argument("--extracted-package", type=Path, required=True)
    parser.add_argument("--write-audit", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = collect_audit(args.artifact_dir, args.package_zip, args.extracted_package)
    if args.write_audit is not None:
        write_exclusive_json(args.write_audit.resolve(), audit)
    print(
        json.dumps(
            {
                "answer_set_sha256": audit["hashes"]["answer_set_sha256"],
                "checks": audit["check_summary"],
                "status": audit["status"],
                "terminal_journal_sha256": audit["hashes"]["terminal_journal_sha256"],
                "usage": audit["usage"],
            },
            sort_keys=True,
        )
    )
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
