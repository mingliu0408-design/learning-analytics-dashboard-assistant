"""Run the RQ2-V2 B4 DEV R1 request-compatibility execution.

This adapter preserves the historical failed run, uses the frozen prompt and
examples, writes every new physical-attempt reservation durably before HTTP,
and permits a second attempt only after invalid structured output.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from build_b4_preparation import LABEL_FIELDS, canonical_json, parse_strict_response


TRACK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRACK_DIR.parents[2]
V2_MANIFEST_PATH = TRACK_DIR / "b4_dev_execution_manifest_v2.jsonl"
V3_MANIFEST_PATH = TRACK_DIR / "b4_dev_execution_manifest_v3.jsonl"
MANIFEST_DIFF_PATH = TRACK_DIR / "b4_manifest_v2_v3_diff_v1.json"
SCHEMA_V1_PATH = TRACK_DIR / "b4_response_schema_v1.json"
SCHEMA_V2_PATH = TRACK_DIR / "b4_response_schema_v2.json"
HISTORICAL_PRESERVATION_PATH = (
    TRACK_DIR / "b4_historical_failed_run_preservation_v1.json"
)
SCHEMA_REPAIR_REPORT_PATH = TRACK_DIR / "B4_SCHEMA_COMPATIBILITY_REPAIR.md"
ATTEMPT_RECORDS_PATH = TRACK_DIR / "b4_dev_attempt_records_v2.jsonl"
CALL_JOURNAL_PATH = TRACK_DIR / "b4_dev_call_journal_v2.jsonl"
TERMINAL_RESULTS_PATH = TRACK_DIR / "b4_dev_terminal_results_v2.jsonl"

EXPECTED_BRANCH = "research/rq2-v2-stage4-i-b4-preparation"
EXPECTED_STARTING_HEAD = "fa3ba58fbd7abaecb0f7332312aade99bb2fc870"
EXPECTED_PROMPT_SHA256 = (
    "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541"
)
EXPECTED_SCHEMA_V1_SHA256 = (
    "9f364e920cfcca07a90580000196c85a6f801ef2e75c9c907bf820eea6a9aba2"
)
EXPECTED_V2_MANIFEST_SHA256 = (
    "e3fe5585ccd78d51cf9c154d64a56f919c3fc47b0e2460678a4cb7b058a67c22"
)
AUTHORIZED_MODEL_SNAPSHOT = "gpt-4o-mini-2024-07-18"
AUTHORIZED_STATUS = "AUTHORIZED_DEV_ONLY"
LOGICAL_CALL_CEILING = 64
NEW_PHYSICAL_ATTEMPT_CEILING = 128
HISTORICAL_PHYSICAL_ATTEMPTS = 1
CUMULATIVE_PHYSICAL_ATTEMPT_CEILING = 129
CLIENT_MAX_RETRIES = 0
MAX_OUTPUT_TOKENS = 64

HISTORICAL_STAGE4IX_SHA256 = {
    "B4_DEV_EXECUTION_BLOCKER.md": "437551767952ed3ecc959fadb9f4424966c51056303a840716678b4cf9477578",
    "B4_DEV_EXECUTION_RESULTS.md": "e4afaf52340178d4dac3062704452c472836cd54134f6103765c3c5e2745a9f8",
    "B4_DEV_EXECUTION_STATUS.md": "ab337358d6df829419c2ea82ea2294fd99f6b6c0d934c33c3f38cb9d197bffbe",
    "B4_DEV_EXECUTION_VERIFICATION_REPORT.md": "a686356bd3a09d13aa070a7549692b1738264efe461d20db5fe0d534b31f8291",
    "b4_dev_attempt_records_v1.jsonl": "0be2829472fd15e5339c09618fd2902ea17700c2645504923b40ee5563c45755",
    "b4_dev_call_journal_v1.jsonl": "7722518f6c25c1196adfcc923aaee0ecbee5929f0883caa805e5bc8e3c34cff0",
    "b4_dev_error_registry_v1.csv": "735fd45fbc4299bd60605e1df42feb3bf0b73a6ed2a57ea2394ca14a0b1a2f3a",
    "b4_dev_execution_manifest_v2.jsonl": EXPECTED_V2_MANIFEST_SHA256,
    "b4_dev_metrics_v1.json": "4217c8e3b8278dd54078f8390c7ff3a3eeafa919179dd94f9363c435ce77e833",
    "b4_dev_predictions_v1.csv": "ed2ab9860a93d60bba043023e4eeb42f5eb9008e933b03267cea77b6601659f0",
    "b4_dev_terminal_results_v1.jsonl": "81e74e9446b5da17cbd299ac543b6ce68ba572b0a5485ff2b216b113b30b2b49",
    "b4_dev_usage_and_cost_v1.json": "5cf6fcd0f52730c1af5a735e63387fbc5b3e8bda47c0fd94af252a841d693cc0",
    "b4_execution_runtime_v1.json": "bce30fa44ecdd331718fd8e8c83760beac02dc14c3e3898cde1c46c0c429c817",
    "b4_final_frozen_configuration_v1.json": "b47ce09f19a8ec55b2e156057afc82c8c29f97f0f9cf1d7b86d74b930bd8c012",
    "b4_manifest_v1_v2_diff_v1.json": "fafd7087b9b7b3746c43ab69f14535e82d3abb331a18256aef3055b358012bc4",
    "execute_b4_dev.py": "ac40ba119c8057fc4bd8a2e9122aee4ce2696ce90bfedbfb7286fc8c0f274c60",
    "finalize_b4_dev.py": "771caf32a41b66ca1ef4f379604fc7b7386338c4c50db9ce0b78eaf6d90b6d0f",
    "tests/test_b4_execution_preflight.py": "9f2346ce954aaabd654a6d26269d05bf43e8ee33dc2042ac66e6425ea2fd19e3",
    "tests/test_b4_execution_results.py": "ecd7da97a1314e00015fa33e96a7fa5d509deee652cab927f14000b79c2fc609",
}

SCHEMA_METADATA_REMOVED = ("$schema", "title", "minProperties", "maxProperties")
ALLOWED_V2_V3_DIFF_PATHS = {
    "schema_version",
    "strict_response_schema_sha256",
    *{
        "provider_request_payload.response_format.json_schema.schema." + key
        for key in SCHEMA_METADATA_REMOVED
    },
}
FIRST_CALL_FATAL_CATEGORIES = {
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "REQUEST_CONFIGURATION_ERROR",
    "MODEL_OR_ENDPOINT_NOT_FOUND",
}
NEW_DERIVED_OUTPUT_PATHS = (
    TRACK_DIR / "b4_dev_predictions_v2.csv",
    TRACK_DIR / "b4_dev_error_registry_v2.csv",
    TRACK_DIR / "b4_dev_usage_and_cost_v2.json",
    TRACK_DIR / "b4_dev_metrics_v2.json",
    TRACK_DIR / "b4_final_frozen_configuration_v2.json",
    TRACK_DIR / "B4_DEV_EXECUTION_RESULTS_R1.md",
    TRACK_DIR / "B4_DEV_EXECUTION_STATUS_R1.md",
    TRACK_DIR / "B4_DEV_EXECUTION_VERIFICATION_R1.md",
)


class ExecutionBoundaryError(RuntimeError):
    """Raised before an unauthorized or unsafe provider action."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def append_jsonl_fsync(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _diff_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        differences: set[str] = set()
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                differences.add(path)
            else:
                differences.update(_diff_paths(left[key], right[key], path))
        return differences
    if left != right:
        return {prefix}
    return set()


def verify_historical_artifacts() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative_path, expected in HISTORICAL_STAGE4IX_SHA256.items():
        path = TRACK_DIR / relative_path
        if not path.is_file():
            raise ExecutionBoundaryError(f"Historical artifact missing: {relative_path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ExecutionBoundaryError(
                f"Historical artifact hash mismatch: {relative_path}"
            )
        observed[relative_path] = actual
    historical_attempts = load_jsonl(TRACK_DIR / "b4_dev_attempt_records_v1.jsonl")
    historical_terminals = load_jsonl(TRACK_DIR / "b4_dev_terminal_results_v1.jsonl")
    if len(historical_attempts) != 1 or len(historical_terminals) != 1:
        raise ExecutionBoundaryError("Historical failed-run call count changed")
    attempt = historical_attempts[0]
    if (
        attempt.get("provider_error", {}).get("error_type") != "BadRequestError"
        or attempt.get("provider_error", {}).get("status_code") != 400
        or attempt.get("response_id") is not None
        or attempt.get("returned_model") is not None
        or attempt.get("total_tokens") is not None
    ):
        raise ExecutionBoundaryError("Historical failure facts changed")
    return observed


def schema_v1_v2_equivalence() -> dict[str, Any]:
    if sha256_file(SCHEMA_V1_PATH) != EXPECTED_SCHEMA_V1_SHA256:
        raise ExecutionBoundaryError("Frozen schema V1 hash mismatch")
    schema_v1 = json.loads(SCHEMA_V1_PATH.read_text(encoding="utf-8"))
    schema_v2 = json.loads(SCHEMA_V2_PATH.read_text(encoding="utf-8"))
    normalized = copy.deepcopy(schema_v1)
    for key in SCHEMA_METADATA_REMOVED:
        normalized.pop(key, None)
    if normalized != schema_v2:
        raise ExecutionBoundaryError("Schema V2 changes the semantic output contract")
    if set(schema_v2) != {
        "type",
        "properties",
        "required",
        "additionalProperties",
    }:
        raise ExecutionBoundaryError("Schema V2 is not the authorized minimal schema")
    if schema_v2["type"] != "object" or schema_v2["additionalProperties"] is not False:
        raise ExecutionBoundaryError("Schema V2 object boundary differs")
    if list(schema_v2["required"]) != list(LABEL_FIELDS):
        raise ExecutionBoundaryError("Schema V2 required-field order differs")
    if list(schema_v2["properties"]) != list(LABEL_FIELDS):
        raise ExecutionBoundaryError("Schema V2 property order differs")
    if any(schema_v2["properties"][field] != {"type": "boolean"} for field in LABEL_FIELDS):
        raise ExecutionBoundaryError("Schema V2 field type differs")
    return {
        "semantic_output_space_unchanged": True,
        "schema_v1_sha256": sha256_file(SCHEMA_V1_PATH),
        "schema_v2_sha256": sha256_file(SCHEMA_V2_PATH),
        "removed_keywords": list(SCHEMA_METADATA_REMOVED),
        "required_boolean_fields": list(LABEL_FIELDS),
    }


def _normalize_v3_to_v2(
    record: Mapping[str, Any],
    v2_record: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(record)
    normalized["schema_version"] = v2_record["schema_version"]
    normalized["strict_response_schema_sha256"] = v2_record[
        "strict_response_schema_sha256"
    ]
    normalized["provider_request_payload"]["response_format"]["json_schema"][
        "schema"
    ] = copy.deepcopy(
        v2_record["provider_request_payload"]["response_format"]["json_schema"][
            "schema"
        ]
    )
    return normalized


def validate_manifest_pair(
    v2_records: Sequence[Mapping[str, Any]],
    v3_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(v2_records) != LOGICAL_CALL_CEILING or len(v3_records) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("V2 and V3 manifests must each contain 64 records")
    expected_ids = [f"R2V2-B4-DEV-{index:04d}" for index in range(1, 65)]
    if [record["logical_call_id"] for record in v2_records] != expected_ids:
        raise ExecutionBoundaryError("V2 logical order changed")
    if [record["logical_call_id"] for record in v3_records] != expected_ids:
        raise ExecutionBoundaryError("V3 logical order changed")
    schema_v2 = json.loads(SCHEMA_V2_PATH.read_text(encoding="utf-8"))
    schema_v2_hash = sha256_file(SCHEMA_V2_PATH)
    observed_paths: set[str] = set()
    per_record: list[dict[str, Any]] = []
    for old, new in zip(v2_records, v3_records, strict=True):
        differences = _diff_paths(old, new)
        if differences != ALLOWED_V2_V3_DIFF_PATHS:
            raise ExecutionBoundaryError(
                f"Disallowed V2/V3 differences for {old['logical_call_id']}: "
                f"{sorted(differences)}"
            )
        if _normalize_v3_to_v2(new, old) != old:
            raise ExecutionBoundaryError("V3 normalization is not exact V2 identity")
        payload = new["provider_request_payload"]
        if set(payload) != {
            "model",
            "messages",
            "temperature",
            "response_format",
            "max_tokens",
        }:
            raise ExecutionBoundaryError("V3 provider payload has an unauthorized field")
        if (
            payload["model"] != AUTHORIZED_MODEL_SNAPSHOT
            or payload["temperature"] != 0
            or payload["max_tokens"] != MAX_OUTPUT_TOKENS
        ):
            raise ExecutionBoundaryError("V3 model configuration differs")
        response_format = payload["response_format"]
        if response_format.get("type") != "json_schema":
            raise ExecutionBoundaryError("Structured Output type differs")
        json_schema = response_format.get("json_schema") or {}
        old_json_schema = old["provider_request_payload"]["response_format"][
            "json_schema"
        ]
        if json_schema.get("name") != old_json_schema.get("name"):
            raise ExecutionBoundaryError("Existing schema name changed")
        if json_schema.get("strict") is not True:
            raise ExecutionBoundaryError("Strict Structured Output is not enabled")
        if json_schema.get("schema") != schema_v2:
            raise ExecutionBoundaryError("Provider schema differs from schema V2 file")
        if new["strict_response_schema_sha256"] != schema_v2_hash:
            raise ExecutionBoundaryError("V3 response-schema hash differs")
        if new["model_execution_authorization_status"] != AUTHORIZED_STATUS:
            raise ExecutionBoundaryError("V3 authorization status differs")
        if new["execution_status"] != "NOT_EXECUTED":
            raise ExecutionBoundaryError("V3 manifest is not a pre-run snapshot")
        controls = new["execution_controls"]
        if controls != {
            "invalid_structured_output_retries_max": 1,
            "sdk_transport_retries": 0,
            "silent_repair_allowed": False,
        }:
            raise ExecutionBoundaryError("V3 execution controls differ")
        observed_paths.update(differences)
        per_record.append(
            {
                "logical_call_id": old["logical_call_id"],
                "difference_paths": sorted(differences),
            }
        )
    return {
        "allowed_difference_paths": sorted(ALLOWED_V2_V3_DIFF_PATHS),
        "observed_difference_paths": sorted(observed_paths),
        "normalized_v3_equals_v2": True,
        "per_record_differences": per_record,
    }


def prepare_r1() -> dict[str, Any]:
    historical_hashes = verify_historical_artifacts()
    schema_validation = schema_v1_v2_equivalence()
    v2_records = load_jsonl(V2_MANIFEST_PATH)
    v3_records: list[dict[str, Any]] = []
    schema_v2 = json.loads(SCHEMA_V2_PATH.read_text(encoding="utf-8"))
    schema_v2_hash = schema_validation["schema_v2_sha256"]
    for record in v2_records:
        updated = copy.deepcopy(record)
        updated["schema_version"] = (
            "rq2-v2-stage4-i-x-r1-b4-dev-execution-record-v3"
        )
        updated["strict_response_schema_sha256"] = schema_v2_hash
        updated["provider_request_payload"]["response_format"]["json_schema"][
            "schema"
        ] = copy.deepcopy(schema_v2)
        v3_records.append(updated)
    validation = validate_manifest_pair(v2_records, v3_records)
    atomic_write_text(
        V3_MANIFEST_PATH,
        "".join(canonical_json(record) + "\n" for record in v3_records),
    )
    diff_report = {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-manifest-diff-v1",
        "status": "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY",
        "record_count": len(v3_records),
        "v2_manifest_path": V2_MANIFEST_PATH.name,
        "v2_manifest_sha256": sha256_file(V2_MANIFEST_PATH),
        "v3_manifest_path": V3_MANIFEST_PATH.name,
        "v3_manifest_sha256": sha256_file(V3_MANIFEST_PATH),
        "schema_v1_sha256": schema_validation["schema_v1_sha256"],
        "schema_v2_sha256": schema_v2_hash,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "model_snapshot": AUTHORIZED_MODEL_SNAPSHOT,
        "temperature": 0,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        **validation,
    }
    atomic_write_json(MANIFEST_DIFF_PATH, diff_report)
    preservation = {
        "schema_version": "rq2-v2-stage4-i-x-r1-historical-preservation-v1",
        "status": "PASS_HISTORICAL_STAGE4IX_BYTES_UNCHANGED",
        "historical_classification": "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE",
        "historical_physical_attempts": HISTORICAL_PHYSICAL_ATTEMPTS,
        "historical_model_response_present": False,
        "historical_parsed_prediction_present": False,
        "historical_provider_usage_present": False,
        "included_in_r1_performance_metrics": False,
        "historical_artifact_sha256": historical_hashes,
    }
    atomic_write_json(HISTORICAL_PRESERVATION_PATH, preservation)
    atomic_write_text(
        SCHEMA_REPAIR_REPORT_PATH,
        f"""# B4 Schema Compatibility Repair

Status: `REQUEST_COMPATIBILITY_REPAIR_PREPARED`

- Schema V1 SHA-256: `{schema_validation['schema_v1_sha256']}`
- Schema V2 SHA-256: `{schema_v2_hash}`
- Semantic output space: unchanged.
- Required fields: `rag_required`, `memory_required`, and `planning_required`; each remains a JSON boolean.
- Removed provider-facing keywords only: `$schema`, `title`, `minProperties`, and `maxProperties`.
- `additionalProperties: false`, strict JSON Schema mode, and the existing schema name are retained.
- Schema V1 produced no model output or prediction.
- This is a request-compatibility correction, not prompt tuning or model tuning.

The frozen prompt, messages, examples, example order, validation inputs, folds,
logical order, model snapshot, temperature, and token limit are unchanged.
""",
    )
    return {
        "status": "PASS_R1_PREPARATION",
        "historical_artifacts_verified": len(historical_hashes),
        "schema_v2_sha256": schema_v2_hash,
        "v3_manifest_sha256": diff_report["v3_manifest_sha256"],
        "logical_call_count": len(v3_records),
        "provider_calls": 0,
    }


def verify_v3_files() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if sha256_file(V2_MANIFEST_PATH) != EXPECTED_V2_MANIFEST_SHA256:
        raise ExecutionBoundaryError("Historical manifest V2 hash mismatch")
    schema_v1_v2_equivalence()
    v2_records = load_jsonl(V2_MANIFEST_PATH)
    v3_records = load_jsonl(V3_MANIFEST_PATH)
    validation = validate_manifest_pair(v2_records, v3_records)
    report = json.loads(MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
    if report.get("v2_manifest_sha256") != sha256_file(V2_MANIFEST_PATH):
        raise ExecutionBoundaryError("Recorded manifest V2 hash differs")
    if report.get("v3_manifest_sha256") != sha256_file(V3_MANIFEST_PATH):
        raise ExecutionBoundaryError("Recorded manifest V3 hash differs")
    for key in (
        "allowed_difference_paths",
        "observed_difference_paths",
        "normalized_v3_equals_v2",
    ):
        if report.get(key) != validation.get(key):
            raise ExecutionBoundaryError(f"Manifest-diff report field differs: {key}")
    return v3_records, report


def _git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_pre_http_boundaries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if Path.cwd().resolve() != REPO_ROOT.resolve():
        raise ExecutionBoundaryError(f"Unexpected working directory: {Path.cwd()}")
    if _git_output("branch", "--show-current") != EXPECTED_BRANCH:
        raise ExecutionBoundaryError("Unexpected branch")
    if _git_output("rev-parse", "HEAD") != EXPECTED_STARTING_HEAD:
        raise ExecutionBoundaryError("Unexpected starting HEAD")
    for line in _git_output("status", "--short").splitlines():
        if not line:
            continue
        path = line[3:]
        if not path.startswith(
            "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/"
        ):
            raise ExecutionBoundaryError(f"Unrelated worktree change: {line}")
    verify_historical_artifacts()
    if sha256_file(TRACK_DIR / "b4_prompt_template_frozen_v1.txt") != EXPECTED_PROMPT_SHA256:
        raise ExecutionBoundaryError("Frozen prompt hash mismatch")
    records, report = verify_v3_files()
    if not os.environ.get("OPENAI_API_KEY"):
        raise ExecutionBoundaryError("OPENAI_API_KEY is missing or empty")
    for path in (ATTEMPT_RECORDS_PATH, CALL_JOURNAL_PATH, TERMINAL_RESULTS_PATH):
        if path.exists():
            raise ExecutionBoundaryError(f"New execution output already exists: {path.name}")
    for path in NEW_DERIVED_OUTPUT_PATHS:
        if path.exists():
            raise ExecutionBoundaryError(f"New derived output already exists: {path.name}")
    for record in records:
        payload_text = json.dumps(record["provider_request_payload"], ensure_ascii=False)
        if "R2V2-TEST" in payload_text.upper() or "TEST_ESCROW" in payload_text.upper():
            raise ExecutionBoundaryError("Prohibited TEST identifier in provider payload")
    return records, report


def create_client() -> Any:
    from openai import OpenAI

    client = OpenAI(max_retries=CLIENT_MAX_RETRIES)
    if getattr(client, "max_retries", None) != CLIENT_MAX_RETRIES:
        raise ExecutionBoundaryError("OpenAI client max_retries is not zero")
    return client


_API_KEY_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.IGNORECASE)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)


def sanitize_provider_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = _API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT_PATTERN.sub("[REDACTED_SECRET_ASSIGNMENT]", text)
    return text[:2000]


def _provider_body(error: BaseException) -> Mapping[str, Any]:
    body = getattr(error, "body", None)
    if not isinstance(body, Mapping):
        return {}
    nested = body.get("error")
    return nested if isinstance(nested, Mapping) else body


def _request_id(error: BaseException) -> str | None:
    direct = getattr(error, "request_id", None)
    if direct:
        return sanitize_provider_text(direct)
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            value = headers.get("x-request-id") or headers.get("X-Request-ID")
        except Exception:
            value = None
        if value:
            return sanitize_provider_text(value)
    return None


def classify_provider_error(error: BaseException) -> str:
    error_type = type(error).__name__
    status = getattr(error, "status_code", None)
    if error_type == "AuthenticationError" or status == 401:
        return "AUTHENTICATION_ERROR"
    if error_type == "PermissionDeniedError" or status == 403:
        return "PERMISSION_ERROR"
    if error_type == "BadRequestError" or status == 400:
        return "REQUEST_CONFIGURATION_ERROR"
    if error_type == "NotFoundError" or status == 404:
        return "MODEL_OR_ENDPOINT_NOT_FOUND"
    if error_type == "RateLimitError" or status == 429:
        return "RATE_LIMIT_ERROR"
    if error_type in {"APIConnectionError", "APITimeoutError", "TimeoutError"}:
        return "TRANSPORT_ERROR"
    return "PROVIDER_ERROR"


def safe_provider_error(error: BaseException) -> dict[str, Any]:
    body = _provider_body(error)
    message = body.get("message")
    if message is None:
        message = getattr(error, "message", None)
    if message is None:
        message = str(error)
    return {
        "exception_type": type(error).__name__,
        "http_status": getattr(error, "status_code", None),
        "provider_error_code": sanitize_provider_text(body.get("code")),
        "provider_error_param": sanitize_provider_text(body.get("param")),
        "provider_request_id": _request_id(error),
        "sanitized_error_message": sanitize_provider_text(message),
        "category": classify_provider_error(error),
        "request_headers_recorded": False,
        "authorization_headers_recorded": False,
    }


def _usage_values(response: Any) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
    )


def validate_response_content(content: str) -> tuple[Any, bool, str | None]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, False, "INVALID_JSON"
    try:
        strict = parse_strict_response(content)
    except ValueError:
        return parsed, False, "STRICT_SCHEMA_VALIDATION_FAILED"
    return strict, True, None


def _one_physical_attempt(
    client: Any,
    manifest_record: Mapping[str, Any],
    attempt_number: int,
    physical_attempt_number: int,
) -> tuple[dict[str, Any], str]:
    if physical_attempt_number > NEW_PHYSICAL_ATTEMPT_CEILING:
        raise ExecutionBoundaryError("New physical-attempt ceiling would be exceeded")
    payload = manifest_record["provider_request_payload"]
    request_hash = canonical_sha256(payload)
    physical_attempt_id = f"R2V2-B4-R1-PHYS-{physical_attempt_number:04d}"
    reservation = {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-call-journal-v2",
        "event": "ATTEMPT_RESERVED",
        "physical_attempt_id": physical_attempt_id,
        "physical_attempt_number": physical_attempt_number,
        "cumulative_physical_attempt_number": (
            HISTORICAL_PHYSICAL_ATTEMPTS + physical_attempt_number
        ),
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold_id"],
        "attempt_number": attempt_number,
        "request_sha256": request_hash,
        "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
        "reserved_at": utc_now(),
    }
    append_jsonl_fsync(CALL_JOURNAL_PATH, reservation)

    started_at = utc_now()
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**payload)
    except Exception as error:
        latency = time.perf_counter() - started
        provider_error = safe_provider_error(error)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-i-x-r1-b4-attempt-record-v2",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "cumulative_physical_attempt_number": (
                HISTORICAL_PHYSICAL_ATTEMPTS + physical_attempt_number
            ),
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold_id"],
            "attempt_number": attempt_number,
            "request_sha256": request_hash,
            "response_id": None,
            "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": None,
            "system_fingerprint": None,
            "finish_reason": None,
            "response_content": None,
            "parsed_json": None,
            "schema_validation": {"valid": False, "error": "PROVIDER_ERROR"},
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "latency_seconds": round(latency, 6),
            "provider_error": provider_error,
            "started_at": started_at,
            "completed_at": utc_now(),
        }
        outcome = "PROVIDER_ERROR"
    else:
        latency = time.perf_counter() - started
        choices = list(getattr(response, "choices", []) or [])
        if choices:
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            message = getattr(choice, "message", None)
            content = str(getattr(message, "content", "") or "")
            refusal = getattr(message, "refusal", None)
        else:
            finish_reason = None
            content = ""
            refusal = None
        returned_model = str(getattr(response, "model", "") or "") or None
        parsed, schema_valid, schema_error = validate_response_content(content)
        provider_error: dict[str, Any] | None = None
        if returned_model != AUTHORIZED_MODEL_SNAPSHOT:
            outcome = "RETURNED_MODEL_MISMATCH"
            schema_valid = False
            schema_error = "RETURNED_MODEL_MISMATCH"
            provider_error = {
                "exception_type": "ReturnedModelMismatch",
                "http_status": None,
                "provider_error_code": None,
                "provider_error_param": None,
                "provider_request_id": None,
                "sanitized_error_message": "Returned model identity did not equal the authorized snapshot.",
                "category": "MODEL_OR_ENDPOINT_NOT_FOUND",
                "request_headers_recorded": False,
                "authorization_headers_recorded": False,
            }
        elif refusal:
            outcome = "PROVIDER_REFUSAL"
            schema_valid = False
            schema_error = "PROVIDER_REFUSAL"
            provider_error = {
                "exception_type": "ProviderRefusal",
                "http_status": None,
                "provider_error_code": None,
                "provider_error_param": None,
                "provider_request_id": None,
                "sanitized_error_message": sanitize_provider_text(refusal),
                "category": "PROVIDER_ERROR",
                "request_headers_recorded": False,
                "authorization_headers_recorded": False,
            }
        elif schema_valid:
            outcome = "VALID_PREDICTION"
        else:
            outcome = "INVALID_STRUCTURED_OUTPUT"
        input_tokens, output_tokens, total_tokens = _usage_values(response)
        attempt_record = {
            "schema_version": "rq2-v2-stage4-i-x-r1-b4-attempt-record-v2",
            "physical_attempt_id": physical_attempt_id,
            "physical_attempt_number": physical_attempt_number,
            "cumulative_physical_attempt_number": (
                HISTORICAL_PHYSICAL_ATTEMPTS + physical_attempt_number
            ),
            "logical_call_id": manifest_record["logical_call_id"],
            "annotation_case_id": manifest_record["annotation_case_id"],
            "fold_id": manifest_record["outer_fold_id"],
            "attempt_number": attempt_number,
            "request_sha256": request_hash,
            "response_id": str(getattr(response, "id", "") or "") or None,
            "requested_model": AUTHORIZED_MODEL_SNAPSHOT,
            "returned_model": returned_model,
            "system_fingerprint": getattr(response, "system_fingerprint", None),
            "finish_reason": finish_reason,
            "response_content": content,
            "parsed_json": parsed,
            "schema_validation": {"valid": schema_valid, "error": schema_error},
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_seconds": round(latency, 6),
            "provider_error": provider_error,
            "started_at": started_at,
            "completed_at": utc_now(),
        }

    append_jsonl_fsync(ATTEMPT_RECORDS_PATH, attempt_record)
    completion = {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-call-journal-v2",
        "event": "ATTEMPT_COMPLETED",
        "physical_attempt_id": physical_attempt_id,
        "physical_attempt_number": physical_attempt_number,
        "cumulative_physical_attempt_number": (
            HISTORICAL_PHYSICAL_ATTEMPTS + physical_attempt_number
        ),
        "logical_call_id": manifest_record["logical_call_id"],
        "attempt_number": attempt_number,
        "request_sha256": request_hash,
        "outcome": outcome,
        "attempt_record_sha256": canonical_sha256(attempt_record),
        "completed_at": utc_now(),
    }
    append_jsonl_fsync(CALL_JOURNAL_PATH, completion)
    return attempt_record, outcome


def _terminal_result(
    manifest_record: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    terminal_status: str,
) -> dict[str, Any]:
    final = attempts[-1]
    prediction = (
        {field: final["parsed_json"][field] for field in LABEL_FIELDS}
        if terminal_status == "VALID_PREDICTION"
        else None
    )
    return {
        "schema_version": "rq2-v2-stage4-i-x-r1-b4-terminal-result-v2",
        "logical_call_id": manifest_record["logical_call_id"],
        "annotation_case_id": manifest_record["annotation_case_id"],
        "fold_id": manifest_record["outer_fold_id"],
        "terminal_status": terminal_status,
        "prediction": prediction,
        "attempts_used": len(attempts),
        "request_sha256": final["request_sha256"],
        "response_id": final["response_id"],
        "requested_model": final["requested_model"],
        "returned_model": final["returned_model"],
        "schema_valid": final["schema_validation"]["valid"],
        "provider_error": final["provider_error"],
        "completed_at": utc_now(),
    }


def first_call_stop_reason(
    logical_results: int,
    terminal: Mapping[str, Any],
) -> str | None:
    if logical_results != 1:
        return None
    category = (terminal.get("provider_error") or {}).get("category")
    if category in FIRST_CALL_FATAL_CATEGORIES:
        return f"FIRST_LOGICAL_CALL_{category}"
    return None


def execute() -> dict[str, Any]:
    manifest_records, diff_report = verify_pre_http_boundaries()
    client = create_client()
    physical_attempts = 0
    logical_results = 0
    retries = 0
    stop_reason: str | None = None

    for manifest_record in manifest_records:
        logical_attempt_records: list[dict[str, Any]] = []
        terminal_status = "PROVIDER_ERROR"
        for attempt_number in (1, 2):
            physical_attempts += 1
            if physical_attempts > NEW_PHYSICAL_ATTEMPT_CEILING:
                raise ExecutionBoundaryError("New physical-attempt ceiling exceeded")
            attempt_record, outcome = _one_physical_attempt(
                client,
                manifest_record,
                attempt_number,
                physical_attempts,
            )
            logical_attempt_records.append(attempt_record)
            if outcome == "VALID_PREDICTION":
                terminal_status = outcome
                break
            if outcome == "INVALID_STRUCTURED_OUTPUT" and attempt_number == 1:
                retries += 1
                continue
            terminal_status = outcome
            break

        terminal = _terminal_result(
            manifest_record,
            logical_attempt_records,
            terminal_status,
        )
        append_jsonl_fsync(TERMINAL_RESULTS_PATH, terminal)
        logical_results += 1
        stop_reason = first_call_stop_reason(logical_results, terminal)
        if stop_reason:
            break
        if logical_results % 8 == 0:
            print(
                f"B4 R1 progress: {logical_results}/64 logical, "
                f"{physical_attempts}/128 new physical, {retries} retries",
                flush=True,
            )

    from finalize_b4_dev_r1 import finalize

    summary = finalize(stop_reason=stop_reason, manifest_diff_report=diff_report)
    if stop_reason:
        raise ExecutionBoundaryError(stop_reason)
    if logical_results != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError(
            f"R1 ended with {logical_results} logical results instead of 64"
        )
    return summary


def runtime_summary() -> dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "openai_sdk_version": importlib.metadata.version("openai"),
        "client_max_retries": CLIENT_MAX_RETRIES,
        "streaming": False,
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "preflight", "execute", "finalize")
    )
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_r1()
    elif args.command == "preflight":
        records, report = verify_pre_http_boundaries()
        client = create_client()
        del client
        result = {
            "status": "PASS_R1_PRE_HTTP_BOUNDARIES",
            "logical_call_count": len(records),
            "v3_manifest_sha256": report["v3_manifest_sha256"],
            **runtime_summary(),
        }
    elif args.command == "execute":
        result = execute()
    else:
        from finalize_b4_dev_r1 import finalize

        result = finalize(stop_reason=None, manifest_diff_report=None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
