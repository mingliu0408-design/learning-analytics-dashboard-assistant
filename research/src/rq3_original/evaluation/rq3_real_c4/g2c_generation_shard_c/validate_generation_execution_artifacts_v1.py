#!/usr/bin/env python3
"""Offline mechanical validator for frozen C4 REAL generation shard C.

This validator performs no network operation and makes no quality judgment.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
import zipfile


SHARD_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SHARD_DIR / "execution_output_v1"
AUTHORIZATION_PATH = SHARD_DIR / "generation_execution_authorization_v1.json"
SOURCE_MANIFEST_PATH = SHARD_DIR / "generation_execution_source_manifest_v1.json"
AUDIT_PATH = SHARD_DIR / "generation_execution_audit_v1.json"
REPORT_PATH = SHARD_DIR / "C4_REAL_GENERATION_SHARD_REPORT.md"
STATUS_PATH = SHARD_DIR / "STATUS.md"
REVIEW_MANIFEST_PATH = SHARD_DIR / "generation_review_manifest_v1.json"
PACKAGE_ZIP = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_GENERATION_SHARD_C_EXECUTION_PACKAGE_R2_2026-09-01.zip"
)

EXPECTED_PACKAGE_SHA256 = (
    "1181d3dbed46d60f8989883907088907d570e6c7a532ee3f469082b66eabe353"
)
EXPECTED_MANIFEST_SHA256 = (
    "91fc2c4d90bee4d67924bb06ad69437f0ad76beb9ac60b586bb390ea35eb0136"
)
EXPECTED_AUTHORIZATION_SHA256 = (
    "44727cee5cfd0ff4f290bd970805000fea2a5c71a559479d40a2e02a29babd2e"
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
EXPECTED_TERMINAL_JOURNAL_SHA256 = (
    "d91c60aebdcde9103b9bfec62ae0b8d387b79e7d1a275dc22c8ee034168786ef"
)
EXPECTED_ANSWER_SET_SHA256 = (
    "e2c2c7da53ea8cf90639f06e35b5abf27140ab8ae21b88df126dd2c1b778925f"
)
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_PACKAGE_ID = "C4_REAL_GENERATION_SHARD_C_R2_20260901"
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-G2C-RESPONSE-GENERATION-20260901"
EXPECTED_REQUEST_COUNT = 62
EXPECTED_MAXIMUM_ATTEMPTS = 124

PACKAGE_FILES = {
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
OUTPUT_FILES = {
    "GENERATION_ATTEMPT_JOURNAL.jsonl",
    "GENERATION_ERROR_REGISTRY.jsonl",
    "GENERATION_EXECUTION_REPORT.md",
    "GENERATION_EXECUTION_STATUS.json",
    "GENERATION_PREFLIGHT_RECEIPT.json",
    "GENERATION_TERMINAL_JOURNAL.jsonl",
    "GENERATION_USAGE_AND_COST.json",
}
AUTHORIZATION_FIELDS = {
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
REQUEST_FIELDS = {
    "schema_version",
    "logical_generation_request_id",
    "response_blind_id",
    "provider_payload_sha256",
    "estimated_input_tokens",
    "provider_payload",
}
ATTEMPT_FIELDS = {
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
VALID_TERMINAL_FIELDS = {
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
REVIEW_MEMBERS = {
    "generation_execution_authorization_v1.json",
    "generation_execution_source_manifest_v1.json",
    "generation_execution_audit_v1.json",
    "C4_REAL_GENERATION_SHARD_REPORT.md",
    "STATUS.md",
    "validate_generation_execution_artifacts_v1.py",
    "test_generation_execution_artifacts_v1.py",
    "generation_review_manifest_v1.json",
    *(f"execution_output_v1/{name}" for name in OUTPUT_FILES),
}

UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|"
    r"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)
PROHIBITED_FIELD_TOKENS = {"gold", "condition", "mode", "route", "judge", "rating", "score", "scoring"}
ALLOWED_ZERO_COUNTER_FIELDS = {"judge_calls", "scoring_calls"}


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


def load_jsonl_bytes(value: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in value.decode("utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("JSONL record must be an object")
            records.append(record)
    return records


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return load_jsonl_bytes(path.read_bytes())


def _field_violations(value: Any, prefix: str = "") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            field_path = f"{prefix}.{key}" if prefix else key
            tokens = set(re.findall(r"[a-z0-9]+", key.casefold()))
            if tokens & PROHIBITED_FIELD_TOKENS:
                if key not in ALLOWED_ZERO_COUNTER_FIELDS or nested != 0:
                    violations.append(field_path)
            violations.extend(_field_violations(nested, field_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(_field_violations(nested, f"{prefix}[{index}]"))
    return violations


def _all_artifact_files() -> Iterable[Path]:
    return (path for path in SHARD_DIR.rglob("*") if path.is_file())


def validate() -> dict[str, Any]:
    checks: dict[str, bool] = {}

    def check(name: str, condition: bool) -> None:
        if name in checks:
            raise AssertionError(f"duplicate check name: {name}")
        checks[name] = bool(condition)

    source = load_json(SOURCE_MANIFEST_PATH)
    authorization = load_json(AUTHORIZATION_PATH)
    status = load_json(OUTPUT_DIR / "GENERATION_EXECUTION_STATUS.json")
    preflight = load_json(OUTPUT_DIR / "GENERATION_PREFLIGHT_RECEIPT.json")
    usage = load_json(OUTPUT_DIR / "GENERATION_USAGE_AND_COST.json")
    attempts = load_jsonl(OUTPUT_DIR / "GENERATION_ATTEMPT_JOURNAL.jsonl")
    terminals = load_jsonl(OUTPUT_DIR / "GENERATION_TERMINAL_JOURNAL.jsonl")
    errors = load_jsonl(OUTPUT_DIR / "GENERATION_ERROR_REGISTRY.jsonl")

    with zipfile.ZipFile(PACKAGE_ZIP) as archive:
        zip_names = archive.namelist()
        package_bytes = {name: archive.read(name) for name in zip_names}

    request_rows = load_jsonl_bytes(package_bytes["BLINDED_REQUESTS.jsonl"])
    prompt = package_bytes["GENERATION_PROMPT.txt"].decode("utf-8")
    schema = json.loads(package_bytes["GENERATION_SCHEMA.json"])
    configuration = json.loads(package_bytes["GENERATION_CONFIGURATION.json"])
    contract = json.loads(package_bytes["EXECUTION_CONTRACT.json"])
    package_sources = json.loads(package_bytes["PACKAGE_SOURCE_HASHES.json"])

    package_member_hashes = {
        name: sha256_bytes(content) for name, content in sorted(package_bytes.items())
    }
    output_file_hashes = {
        path.name: sha256_file(path)
        for path in sorted(OUTPUT_DIR.iterdir())
        if path.is_file()
    }

    check(
        "source_manifest_schema",
        source.get("schema_version") == "c4-real-generation-source-manifest-v1"
        and source.get("shard") == "C",
    )
    check("package_zip_identity", sha256_file(PACKAGE_ZIP) == EXPECTED_PACKAGE_SHA256)
    check(
        "package_zip_allowlist",
        len(zip_names) == len(set(zip_names))
        and set(zip_names) == PACKAGE_FILES
        and all(Path(name).name == name and not name.endswith("/") for name in zip_names),
    )
    check(
        "package_member_hashes",
        package_member_hashes == source["package"]["member_sha256"]
        and package_sources["member_sha256_excluding_self"]
        == {
            name: digest
            for name, digest in package_member_hashes.items()
            if name != "PACKAGE_SOURCE_HASHES.json"
        },
    )
    check(
        "blinded_manifest_identity",
        sha256_bytes(package_bytes["BLINDED_REQUESTS.jsonl"])
        == EXPECTED_MANIFEST_SHA256
        == source["blinded_request_manifest"]["sha256"],
    )
    check(
        "frozen_scientific_identity",
        sha256_bytes(package_bytes["GENERATION_PROMPT.txt"]) == EXPECTED_PROMPT_SHA256
        and sha256_bytes(package_bytes["GENERATION_SCHEMA.json"]) == EXPECTED_SCHEMA_SHA256
        and sha256_bytes(package_bytes["GENERATION_CONFIGURATION.json"])
        == EXPECTED_CONFIGURATION_SHA256
        and configuration["model"] == EXPECTED_MODEL
        and configuration["temperature"] == 0
        and configuration["max_output_tokens"] == 512
        and configuration["streaming"] is False
        and configuration["tools"] == "NONE"
        and contract["endpoint"] == "OpenAI Chat Completions"
        and contract["automatic_sdk_retries"] == 0,
    )
    check(
        "package_request_population",
        len(request_rows) == EXPECTED_REQUEST_COUNT
        == source["blinded_request_manifest"]["logical_request_count"],
    )
    check(
        "strict_authorization_shape",
        set(authorization) == AUTHORIZATION_FIELDS
        and authorization["schema_version"]
        == "c4-real-response-generation-authorization-r2"
        and authorization["status"] == "AUTHORIZED"
        and isinstance(authorization["authorized_at_utc"], str)
        and UTC_PATTERN.fullmatch(authorization["authorized_at_utc"]) is not None,
    )
    check(
        "authorization_binding",
        authorization["authorization_id"] == EXPECTED_AUTHORIZATION_ID
        and authorization["authorized_by"] == "Ming Liu"
        and authorization["package_id"] == EXPECTED_PACKAGE_ID
        and authorization["shard"] == "C"
        and authorization["request_count"] == EXPECTED_REQUEST_COUNT
        and authorization["maximum_physical_attempts"] == EXPECTED_MAXIMUM_ATTEMPTS
        and authorization["package_sha256"] == EXPECTED_PACKAGE_SHA256
        and authorization["blinded_manifest_sha256"] == EXPECTED_MANIFEST_SHA256,
    )
    check(
        "authorization_hash",
        sha256_file(AUTHORIZATION_PATH) == EXPECTED_AUTHORIZATION_SHA256
        == source["authorization_record"]["sha256"],
    )
    check(
        "output_directory_exclusivity",
        OUTPUT_DIR.is_dir()
        and {path.name for path in OUTPUT_DIR.iterdir()} == OUTPUT_FILES
        and all(path.is_file() and not path.is_symlink() for path in OUTPUT_DIR.iterdir()),
    )
    check(
        "preflight_receipt",
        preflight
        == {
            "authorization_id": EXPECTED_AUTHORIZATION_ID,
            "authorization_record_sha256": EXPECTED_AUTHORIZATION_SHA256,
            "automatic_resume": False,
            "blinded_manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "client_constructed": False,
            "judge_calls": 0,
            "maximum_physical_attempts": EXPECTED_MAXIMUM_ATTEMPTS,
            "package_id": EXPECTED_PACKAGE_ID,
            "package_sha256": EXPECTED_PACKAGE_SHA256,
            "request_count": EXPECTED_REQUEST_COUNT,
            "runtime_constructed": False,
            "schema_version": "c4-real-generation-preflight-start-receipt-v2",
            "shard": "C",
            "started_at_utc": preflight.get("started_at_utc"),
            "status": "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
        }
        and isinstance(preflight.get("started_at_utc"), str)
        and UTC_PATTERN.fullmatch(preflight["started_at_utc"]) is not None,
    )
    check(
        "status_complete",
        status.get("status") == "COMPLETE"
        and status.get("stop_reason") is None
        and status.get("request_count") == EXPECTED_REQUEST_COUNT
        and status.get("valid_response_count") == EXPECTED_REQUEST_COUNT
        and status.get("incomplete_logical_request_count") == 0
        and status.get("unattempted_logical_request_count") == 0
        and status.get("physical_attempt_count") == len(attempts),
    )
    check(
        "fail_closed_contract",
        status.get("automatic_resume") is False
        and status.get("continuation_requires_new_direct_authorization") is True
        and contract.get("automatic_resume") is False
        and contract.get("continuation_requires_new_direct_authorization") is True
        and contract.get("stop_entire_shard_on_first_non_retryable_failure") is True,
    )
    check(
        "runtime_identity",
        status.get("runtime_identity")
        == {
            "api_key_presence_checked_only": True,
            "api_key_value_recorded": False,
            "automatic_sdk_retries": 0,
            "openai_sdk_version": "1.109.1",
            "python_path": "/opt/anaconda3/bin/python3",
            "python_version": "3.13.5",
        }
        and contract["runtime"]["python_version"] == "3.13.5"
        and contract["runtime"]["openai_sdk_version"] == "1.109.1",
    )
    check(
        "request_population",
        len(request_rows) == EXPECTED_REQUEST_COUNT
        and all(set(row) == REQUEST_FIELDS for row in request_rows),
    )
    check(
        "logical_request_id_uniqueness",
        len({row["logical_generation_request_id"] for row in request_rows})
        == EXPECTED_REQUEST_COUNT,
    )
    check(
        "response_blind_id_uniqueness",
        len({row["response_blind_id"] for row in request_rows})
        == EXPECTED_REQUEST_COUNT,
    )
    check(
        "provider_payload_hashes",
        all(
            sha256_bytes(canonical_bytes(row["provider_payload"]))
            == row["provider_payload_sha256"]
            for row in request_rows
        ),
    )
    expected_response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "c4_real_generation_response_v2_provider_compatible",
            "strict": True,
            "schema": schema,
        },
    }
    check(
        "frozen_provider_payloads",
        all(
            set(row["provider_payload"])
            == {"model", "messages", "temperature", "max_tokens", "stream", "response_format"}
            and row["provider_payload"]["model"] == EXPECTED_MODEL
            and row["provider_payload"]["temperature"] == 0
            and row["provider_payload"]["max_tokens"] == 512
            and row["provider_payload"]["stream"] is False
            and row["provider_payload"]["response_format"] == expected_response_format
            and row["provider_payload"]["messages"][0]
            == {"role": "system", "content": prompt}
            for row in request_rows
        ),
    )

    expected_by_order = {index: row for index, row in enumerate(request_rows, 1)}
    attempts_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_order[attempt["logical_order"]].append(attempt)

    check("attempt_count", len(attempts) == status["physical_attempt_count"] == 62)
    check("attempt_field_shape", all(set(row) == ATTEMPT_FIELDS for row in attempts))
    expected_attempt_sequence = [
        (order, attempt_number)
        for order in range(1, EXPECTED_REQUEST_COUNT + 1)
        for attempt_number in range(1, len(attempts_by_order[order]) + 1)
    ]
    check(
        "attempt_journal_order",
        [(row["logical_order"], row["attempt_number"]) for row in attempts]
        == expected_attempt_sequence,
    )
    check(
        "attempt_identity_binding",
        all(
            row["logical_generation_request_id"]
            == expected_by_order[row["logical_order"]]["logical_generation_request_id"]
            and row["response_blind_id"]
            == expected_by_order[row["logical_order"]]["response_blind_id"]
            and row["provider_payload_sha256"]
            == expected_by_order[row["logical_order"]]["provider_payload_sha256"]
            and row["requested_model"] == EXPECTED_MODEL
            for row in attempts
        ),
    )
    check(
        "attempt_numbering",
        set(attempts_by_order) == set(range(1, EXPECTED_REQUEST_COUNT + 1))
        and all(
            [row["attempt_number"] for row in group] == list(range(1, len(group) + 1))
            and 1 <= len(group) <= 2
            for group in attempts_by_order.values()
        ),
    )
    check(
        "retry_compliance",
        all(
            len(group) == 1
            or (
                group[0]["strict_validation_status"]
                == "INVALID_JSON_OR_STRICT_SCHEMA"
                and group[1]["provider_payload_sha256"]
                == group[0]["provider_payload_sha256"]
            )
            for group in attempts_by_order.values()
        ),
    )
    retry_count = len(attempts) - len(attempts_by_order)
    check("retry_count", retry_count == 0)
    check(
        "strict_validation_statuses",
        all(
            row["strict_validation_status"]
            in {"VALID", "INVALID_JSON_OR_STRICT_SCHEMA"}
            for row in attempts
        )
        and all(group[-1]["strict_validation_status"] == "VALID" for group in attempts_by_order.values()),
    )
    check(
        "strict_parsed_output_shape",
        all(
            isinstance(row["parsed_output"], dict)
            and set(row["parsed_output"]) == {"answer_text"}
            for row in attempts
            if row["strict_validation_status"] == "VALID"
        ),
    )
    check(
        "nonempty_answer_text",
        all(
            isinstance(row["parsed_output"]["answer_text"], str)
            and bool(row["parsed_output"]["answer_text"].strip())
            for row in attempts
            if row["strict_validation_status"] == "VALID"
        ),
    )
    check(
        "raw_parsed_output_consistency",
        all(
            json.loads(row["raw_response_content"]) == row["parsed_output"]
            for row in attempts
            if row["strict_validation_status"] == "VALID"
        ),
    )
    check(
        "returned_model_identity",
        all(row["returned_model"] == EXPECTED_MODEL for row in attempts)
        and all(row["returned_model"] == EXPECTED_MODEL for row in terminals),
    )
    check("terminal_count", len(terminals) == EXPECTED_REQUEST_COUNT)
    check("terminal_field_shape", all(set(row) == VALID_TERMINAL_FIELDS for row in terminals))
    check("terminal_order", [row["logical_order"] for row in terminals] == list(range(1, 63)))
    check(
        "terminal_logical_id_uniqueness",
        len({row["logical_generation_request_id"] for row in terminals}) == 62,
    )
    check(
        "terminal_response_blind_id_uniqueness",
        len({row["response_blind_id"] for row in terminals}) == 62,
    )
    check(
        "terminal_identity_binding",
        all(
            row["logical_generation_request_id"]
            == expected_by_order[row["logical_order"]]["logical_generation_request_id"]
            and row["response_blind_id"]
            == expected_by_order[row["logical_order"]]["response_blind_id"]
            and row["provider_payload_sha256"]
            == expected_by_order[row["logical_order"]]["provider_payload_sha256"]
            for row in terminals
        ),
    )
    check("terminal_statuses", all(row["terminal_status"] == "VALID_RESPONSE" for row in terminals))
    check(
        "terminal_attempt_consistency",
        all(
            row["physical_attempts"] == len(attempts_by_order[row["logical_order"]])
            for row in terminals
        ),
    )
    terminal_attempt_fields = {
        "logical_generation_request_id",
        "response_blind_id",
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
    }
    check(
        "terminal_output_consistency",
        all(
            all(
                row[field] == attempts_by_order[row["logical_order"]][-1][field]
                for field in terminal_attempt_fields
            )
            for row in terminals
        ),
    )
    check(
        "physical_attempt_ceiling",
        EXPECTED_REQUEST_COUNT <= len(attempts) <= EXPECTED_MAXIMUM_ATTEMPTS
        and status["maximum_physical_attempts"] == EXPECTED_MAXIMUM_ATTEMPTS,
    )
    check("error_registry_empty", len(errors) == 0)
    provider_error_count = len(errors)
    invalid_json_or_schema_count = sum(
        row["strict_validation_status"] == "INVALID_JSON_OR_STRICT_SCHEMA" for row in attempts
    )
    model_error_count = sum(row["returned_model"] != EXPECTED_MODEL for row in attempts)
    check("provider_error_count", provider_error_count == 0)
    check("invalid_json_or_schema_count", invalid_json_or_schema_count == 0)
    check("model_error_count", model_error_count == 0)
    check(
        "usage_per_attempt",
        all(
            isinstance(row["prompt_tokens"], int)
            and isinstance(row["completion_tokens"], int)
            and isinstance(row["total_tokens"], int)
            and row["prompt_tokens"] >= 0
            and row["completion_tokens"] >= 0
            and row["total_tokens"] == row["prompt_tokens"] + row["completion_tokens"]
            and (
                row["cached_input_tokens"] is None
                or (
                    isinstance(row["cached_input_tokens"], int)
                    and 0 <= row["cached_input_tokens"] <= row["prompt_tokens"]
                )
            )
            for row in attempts
        ),
    )
    aggregate_prompt = sum(row["prompt_tokens"] for row in attempts)
    aggregate_cached = sum((row["cached_input_tokens"] or 0) for row in attempts)
    aggregate_completion = sum(row["completion_tokens"] for row in attempts)
    aggregate_total = sum(row["total_tokens"] for row in attempts)
    check(
        "usage_aggregate",
        usage["prompt_tokens"] == aggregate_prompt == 39957
        and usage["cached_input_tokens"] == aggregate_cached == 2048
        and usage["completion_tokens"] == aggregate_completion == 7075
        and usage["total_tokens"] == aggregate_total == 47032
        and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        and usage["usage_arithmetic_valid"] is True
        and usage["provider_calls_observed"] == len(attempts),
    )
    responses_without_cached_detail = sum(row["cached_input_tokens"] is None for row in attempts)
    check(
        "cached_usage_detail",
        usage["responses_without_cached_token_detail"] == responses_without_cached_detail == 0,
    )

    secret_hits = []
    for artifact in _all_artifact_files():
        if SECRET_PATTERN.search(artifact.read_text(encoding="utf-8", errors="replace")):
            secret_hits.append(artifact.relative_to(SHARD_DIR).as_posix())
    check("secret_absence", secret_hits == [])

    output_structures: list[Any] = [preflight, status, usage, *attempts, *terminals, *errors]
    prohibited_fields = []
    for index, structure in enumerate(output_structures):
        prohibited_fields.extend(_field_violations(structure, f"output[{index}]"))
    check("prohibited_output_fields", prohibited_fields == [])

    terminal_journal_hash = sha256_file(OUTPUT_DIR / "GENERATION_TERMINAL_JOURNAL.jsonl")
    check("terminal_journal_hash", terminal_journal_hash == EXPECTED_TERMINAL_JOURNAL_SHA256)
    answer_entries = []
    for row in terminals:
        answer_entries.append(
            {
                "logical_order": row["logical_order"],
                "logical_generation_request_id": row["logical_generation_request_id"],
                "response_blind_id": row["response_blind_id"],
                "answer_text_sha256": sha256_bytes(
                    row["parsed_output"]["answer_text"].encode("utf-8")
                ),
            }
        )
    answer_set_hash = sha256_bytes(canonical_bytes(answer_entries))
    audit = load_json(AUDIT_PATH)
    check("answer_text_hashes", audit.get("answer_text_sha256") == answer_entries)
    check("answer_set_hash", answer_set_hash == EXPECTED_ANSWER_SET_SHA256)
    check(
        "output_file_hashes",
        output_file_hashes == source["execution_output"]["file_sha256"],
    )
    check(
        "future_integration_compatibility",
        len(answer_entries) == EXPECTED_REQUEST_COUNT
        and [row["logical_order"] for row in answer_entries] == list(range(1, 63))
        and all(row["response_blind_id"] for row in answer_entries)
        and all(row["answer_text_sha256"] for row in answer_entries),
    )
    check(
        "zero_judge_scoring",
        preflight["judge_calls"] == 0
        and status["judge_calls"] == 0
        and status["scoring_calls"] == 0
        and usage["judge_calls"] == 0
        and source["scope_boundaries"]["judge_calls"] == 0
        and source["scope_boundaries"]["scoring_calls"] == 0,
    )
    check(
        "scope_boundaries",
        source["scope_boundaries"]
        == {
            "hmac_material_accessed": False,
            "judge_calls": 0,
            "other_shard_packages_accessed": False,
            "restricted_mapping_accessed": False,
            "rq2_calls": 0,
            "scoring_calls": 0,
            "streamlit_launches": 0,
        },
    )
    check(
        "no_bytecode_residue",
        source["package"]["post_validation_bytecode_entry_count"] == 0
        and not any(
            path.name == "__pycache__" or path.suffix == ".pyc"
            for path in SHARD_DIR.rglob("*")
        )
        and not any(name.endswith(".pyc") or "__pycache__" in name for name in zip_names),
    )

    standard_cost = (
        Decimal(aggregate_prompt) * Decimal("0.15")
        + Decimal(aggregate_completion) * Decimal("0.60")
    ) / Decimal(1_000_000)
    cached_aware_cost = (
        Decimal(aggregate_prompt - aggregate_cached) * Decimal("0.15")
        + Decimal(aggregate_cached) * Decimal("0.075")
        + Decimal(aggregate_completion) * Decimal("0.60")
    ) / Decimal(1_000_000)

    check(
        "audit_summary_consistency",
        audit.get("status") == "PASS"
        and audit.get("shard") == "C"
        and audit.get("execution", {}).get("logical_request_count") == 62
        and audit.get("execution", {}).get("physical_attempt_count") == 62
        and audit.get("execution", {}).get("retry_count") == 0
        and audit.get("hashes", {}).get("terminal_journal_sha256")
        == terminal_journal_hash
        and audit.get("hashes", {}).get("answer_set_sha256") == answer_set_hash
        and audit.get("cost_estimates_usd", {}).get("standard_non_cached_input")
        == f"{standard_cost:.8f}"
        and audit.get("cost_estimates_usd", {}).get("cached_input_aware")
        == f"{cached_aware_cost:.8f}",
    )
    report_text = REPORT_PATH.read_text(encoding="utf-8")
    check(
        "report_summary_consistency",
        "Status: `COMPLETE`" in report_text
        and "62/62" in report_text
        and EXPECTED_TERMINAL_JOURNAL_SHA256 in report_text
        and EXPECTED_ANSWER_SET_SHA256 in report_text
        and "No response-quality assessment was performed" in report_text,
    )
    status_text = STATUS_PATH.read_text(encoding="utf-8")
    check(
        "status_summary_consistency",
        "COMPLETE" in status_text
        and "Response integration is not authorized" in status_text,
    )
    review_manifest = load_json(REVIEW_MANIFEST_PATH)
    review_hashes = review_manifest.get("members_sha256_excluding_manifest", {})
    check(
        "review_manifest_allowlist",
        review_manifest.get("schema_version") == "c4-real-generation-review-manifest-v1"
        and set(review_hashes) == REVIEW_MEMBERS - {"generation_review_manifest_v1.json"}
        and review_manifest.get("review_member_count") == len(REVIEW_MEMBERS),
    )
    check(
        "review_manifest_hashes",
        all(sha256_file(SHARD_DIR / name) == digest for name, digest in review_hashes.items()),
    )

    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "c4-real-generation-offline-validation-result-v1",
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_failed": len(failed),
        "failed_checks": failed,
        "metrics": {
            "logical_request_count": EXPECTED_REQUEST_COUNT,
            "physical_attempt_count": len(attempts),
            "retry_count": retry_count,
            "valid_response_count": len(terminals),
            "provider_error_count": provider_error_count,
            "invalid_json_or_schema_count": invalid_json_or_schema_count,
            "model_error_count": model_error_count,
            "prompt_tokens": aggregate_prompt,
            "cached_input_tokens": aggregate_cached,
            "completion_tokens": aggregate_completion,
            "total_tokens": aggregate_total,
            "standard_non_cached_input_cost_usd": f"{standard_cost:.8f}",
            "cached_input_aware_cost_usd": f"{cached_aware_cost:.8f}",
            "terminal_journal_sha256": terminal_journal_hash,
            "answer_set_sha256": answer_set_hash,
        },
    }


def main() -> int:
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
