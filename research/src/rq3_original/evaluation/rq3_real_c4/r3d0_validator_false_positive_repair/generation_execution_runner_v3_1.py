#!/usr/bin/env python3
"""Fail-closed serial runner for the explicitly authorized C4 REAL Shard-C R3C1 continuation.

This source is frozen into a dormant regeneration package. Package possession,
an API key, or this script is not execution authority.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping, Sequence
import zipfile

try:
    from .c4_real_student_facing_response_validator_v2 import (
        VALID_STUDENT_FACING_RESPONSE,
        validate_answer_text,
    )
except ImportError:
    from c4_real_student_facing_response_validator_v2 import (
        VALID_STUDENT_FACING_RESPONSE,
        validate_answer_text,
    )


EXPECTED_PYTHON = (3, 13, 5)
EXPECTED_PYTHON_PATH = "/opt/anaconda3/bin/python3"
EXPECTED_OPENAI = "1.109.1"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_PROMPT_SHA256 = "c72c9982899902221d1da6d67724c2058547b0641a285a7c28d9bafd12ec63cb"
EXPECTED_SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
EXPECTED_CONFIGURATION_SHA256 = "b859f0feb71bc12fa483337d65f583a871e40aeb40d1689b9855da7d3d034708"
EXPECTED_FORMAT_CONTRACT_SHA256 = "60284fda9ad9a8990fde593966cb218ab75061d9ba3f6bfe81e0bc457ac51f53"
EXPECTED_VALIDATOR_SHA256 = "dbfe05b5a659518546bfdda660c9c64927fa929adb57655a49d0ef5814f06cba"
AUTHORIZATION_ENVIRONMENT_VARIABLE = "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION"
AUTHORIZATION_ENVIRONMENT_VALUE = "AUTHORIZED_C4_REAL_SHARD_C_CONTINUATION_R3C1"
MAX_ATTEMPTS_PER_REQUEST = 2
INITIAL_REQUEST_GAP_SECONDS = 2.0

PACKAGE_FILES = frozenset(
    {
        "README.md",
        "BLINDED_REQUESTS.jsonl",
        "GENERATION_PROMPT.txt",
        "GENERATION_SCHEMA.json",
        "GENERATION_CONFIGURATION.json",
        "STUDENT_FACING_FORMAT_CONTRACT_V2.json",
        "EXECUTION_CONTRACT.json",
        "generation_execution_runner_v3_1.py",
        "c4_real_student_facing_response_validator_v2.py",
        "validate_package.py",
        "test_package.py",
        "PACKAGE_SOURCE_HASHES.json",
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
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_LOGICAL_ID = re.compile(r"^C4G3-[A-F0-9]{24}$")
_RESPONSE_ID = re.compile(r"^R3B3-[A-F0-9]{20}$")
_SECRET = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|"
    r"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)
_LOCAL_PATH = re.compile(r"/(?:Users|private|var|opt)/[^\s,;:'\"]+")


class RunnerFailure(RuntimeError):
    """A categorized non-retryable failure."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def categorize_error(error: BaseException) -> str:
    if isinstance(error, RunnerFailure):
        return error.category
    name = type(error).__name__.casefold()
    message = str(error).casefold()
    if "authentication" in name or "unauthorized" in message or "invalid api key" in message:
        return "AUTHENTICATION_ERROR"
    if "permission" in name or "forbidden" in message:
        return "PERMISSION_ERROR"
    if "ratelimit" in name or "rate limit" in message:
        return "RATE_LIMIT_ERROR"
    if "timeout" in name or "timed out" in message:
        return "TIMEOUT_ERROR"
    if any(token in name for token in ("badrequest", "invalidrequest", "notfound")):
        return "CONFIGURATION_ERROR"
    if any(token in name for token in ("connection", "transport", "network")):
        return "TRANSPORT_ERROR"
    if isinstance(error, ConnectionError):
        return "TRANSPORT_ERROR"
    if isinstance(error, TimeoutError):
        return "TIMEOUT_ERROR"
    return "UNEXPECTED_PROVIDER_OR_RUNTIME_ERROR"


def sanitize_error(error: BaseException, category: str | None = None) -> Mapping[str, str]:
    message = _SECRET.sub("[REDACTED_SECRET]", str(error))
    message = _LOCAL_PATH.sub("[REDACTED_LOCAL_PATH]", message)
    return {
        "category": category or categorize_error(error),
        "error_type": type(error).__name__,
        "sanitized_message": message[:500],
    }


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
            raise ValueError(f"request manifest line {line_number} is not an object")
        rows.append(value)
    if not rows:
        raise ValueError("request manifest is empty")
    return rows


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive_bytes(path: Path, content: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_parent(path)


def write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    write_exclusive_bytes(
        path,
        (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def create_exclusive_empty(path: Path) -> None:
    write_exclusive_bytes(path, b"")


def append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    content = (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_parent(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def runtime_preflight() -> Mapping[str, Any]:
    if tuple(sys.version_info[:3]) != EXPECTED_PYTHON:
        raise RunnerFailure("RUNTIME_PREFLIGHT_ERROR", "EXACT_PYTHON_3_13_5_REQUIRED")
    if os.path.realpath(sys.executable) != os.path.realpath(EXPECTED_PYTHON_PATH):
        raise RunnerFailure("RUNTIME_PREFLIGHT_ERROR", "EXACT_OPT_ANACONDA_PYTHON_REQUIRED")
    import openai

    if openai.__version__ != EXPECTED_OPENAI:
        raise RunnerFailure("RUNTIME_PREFLIGHT_ERROR", "EXACT_OPENAI_SDK_1_109_1_REQUIRED")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RunnerFailure("CONFIGURATION_ERROR", "OPENAI_API_KEY_NOT_PRESENT")
    return {
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "python_path": EXPECTED_PYTHON_PATH,
        "openai_sdk_version": openai.__version__,
        "automatic_sdk_retries": 0,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }


def default_client_factory() -> Any:
    from openai import OpenAI

    return OpenAI(max_retries=0)


def validate_response_content(
    raw_content: str,
) -> tuple[Mapping[str, str] | None, str | None, str | None]:
    """Validate strict outer JSON first, then the local student-facing contract."""

    try:
        parsed = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        return None, "INVALID_JSON", None
    if not isinstance(parsed, dict) or set(parsed) != {"answer_text"}:
        return None, "STRICT_SCHEMA_VALIDATION_FAILED", None
    answer_text = parsed.get("answer_text")
    if not isinstance(answer_text, str):
        return None, "STRICT_SCHEMA_VALIDATION_FAILED", None
    semantic_status = validate_answer_text(answer_text)
    if semantic_status != VALID_STUDENT_FACING_RESPONSE:
        return None, "NON_STUDENT_FACING_FORMAT", semantic_status
    return {"answer_text": answer_text}, None, semantic_status


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _extract_usage(response: Any) -> Mapping[str, int | None]:
    usage = _attribute(response, "usage")
    if usage is None:
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "PROVIDER_USAGE_MISSING")
    prompt = _attribute(usage, "prompt_tokens")
    completion = _attribute(usage, "completion_tokens")
    total = _attribute(usage, "total_tokens")
    if not all(isinstance(value, int) and value >= 0 for value in (prompt, completion, total)):
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "PROVIDER_USAGE_INVALID")
    if total != prompt + completion:
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "PROVIDER_USAGE_ARITHMETIC_MISMATCH")
    details = _attribute(usage, "prompt_tokens_details")
    cached = _attribute(details, "cached_tokens") if details is not None else None
    if cached is not None and (not isinstance(cached, int) or cached < 0 or cached > prompt):
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "CACHED_TOKEN_USAGE_INVALID")
    return {
        "prompt_tokens": prompt,
        "cached_input_tokens": cached,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _extract_response(response: Any) -> Mapping[str, Any]:
    choices = _attribute(response, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or len(choices) != 1:
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "PROVIDER_RESPONSE_CHOICE_COUNT_INVALID")
    choice = choices[0]
    message = _attribute(choice, "message")
    refusal = _attribute(message, "refusal")
    finish_reason = _attribute(choice, "finish_reason")
    if refusal:
        raise RunnerFailure("PROVIDER_REFUSAL", "PROVIDER_RETURNED_REFUSAL")
    if finish_reason == "content_filter":
        raise RunnerFailure("PROVIDER_REFUSAL", "PROVIDER_CONTENT_FILTER_REFUSAL")
    if finish_reason != "stop":
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "PROVIDER_FINISH_REASON_NOT_STOP")
    returned_model = _attribute(response, "model")
    if returned_model != EXPECTED_MODEL:
        raise RunnerFailure("MODEL_MISMATCH", "RETURNED_MODEL_IDENTITY_MISMATCH")
    raw_content = _attribute(message, "content")
    if not isinstance(raw_content, str):
        raise RunnerFailure("UNEXPECTED_PROVIDER_RESPONSE", "PROVIDER_RESPONSE_CONTENT_NOT_TEXT")
    return {
        "provider_response_id": _attribute(response, "id"),
        "returned_model": returned_model,
        "system_fingerprint": _attribute(response, "system_fingerprint"),
        "finish_reason": finish_reason,
        "raw_response_content": raw_content,
        "usage": _extract_usage(response),
    }


def _best_effort_response_fields(response: Any) -> Mapping[str, Any]:
    output: dict[str, Any] = {
        "returned_model": _attribute(response, "model"),
        "provider_response_id": _attribute(response, "id"),
        "system_fingerprint": _attribute(response, "system_fingerprint"),
    }
    choices = _attribute(response, "choices")
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)) and choices:
        choice = choices[0]
        output["finish_reason"] = _attribute(choice, "finish_reason")
        content = _attribute(_attribute(choice, "message"), "content")
        if isinstance(content, str):
            output["raw_response_content"] = content
    try:
        output["usage"] = _extract_usage(response)
    except Exception:
        output["usage"] = None
    return output


def _validate_request_row(
    row: Mapping[str, Any], prompt: str, schema: Mapping[str, Any]
) -> tuple[dict[str, Any], bytes]:
    if set(row) != REQUEST_FIELDS or row.get("schema_version") != "c4-real-blinded-generation-request-v3":
        raise RunnerFailure("CONFIGURATION_ERROR", "BLINDED_REQUEST_V3_SCHEMA_MISMATCH")
    if not _LOGICAL_ID.fullmatch(str(row.get("logical_generation_request_id", ""))):
        raise RunnerFailure("CONFIGURATION_ERROR", "LOGICAL_REQUEST_ID_MALFORMED")
    if not _RESPONSE_ID.fullmatch(str(row.get("response_blind_id", ""))):
        raise RunnerFailure("CONFIGURATION_ERROR", "RESPONSE_BLIND_ID_MALFORMED")
    payload = row.get("provider_payload")
    if not isinstance(payload, Mapping):
        raise RunnerFailure("CONFIGURATION_ERROR", "PROVIDER_PAYLOAD_MISSING")
    payload_bytes = canonical_bytes(payload)
    if sha256_bytes(payload_bytes) != row.get("provider_payload_sha256"):
        raise RunnerFailure("CONFIGURATION_ERROR", "PROVIDER_PAYLOAD_HASH_MISMATCH")
    if set(payload) != {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "stream",
        "response_format",
    }:
        raise RunnerFailure("CONFIGURATION_ERROR", "PROVIDER_PAYLOAD_FIELD_SET_MISMATCH")
    if payload.get("model") != EXPECTED_MODEL:
        raise RunnerFailure("CONFIGURATION_ERROR", "REQUESTED_MODEL_IDENTITY_MISMATCH")
    if (
        payload.get("temperature") != 0
        or payload.get("max_tokens") != 512
        or payload.get("stream") is not False
        or "tools" in payload
    ):
        raise RunnerFailure("CONFIGURATION_ERROR", "PROVIDER_TRANSPORT_CONFIGURATION_MISMATCH")
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
        raise RunnerFailure("CONFIGURATION_ERROR", "PROVIDER_MESSAGE_CONSTRUCTION_MISMATCH")
    user_message = messages[1]["content"]
    if "CURRENT LAD PAGE\n" not in user_message or "STUDENT REQUEST\n" not in user_message:
        raise RunnerFailure("CONFIGURATION_ERROR", "PLAIN_TEXT_REQUEST_SECTIONS_MISSING")
    try:
        raw_user = json.loads(user_message)
    except json.JSONDecodeError:
        raw_user = None
    if isinstance(raw_user, (dict, list)):
        raise RunnerFailure("CONFIGURATION_ERROR", "RAW_JSON_USER_MESSAGE_PROHIBITED")
    if payload.get("response_format") != {
        "type": "json_schema",
        "json_schema": {
            "name": "c4_real_generation_response_v2_provider_compatible",
            "strict": True,
            "schema": dict(schema),
        },
    }:
        raise RunnerFailure("CONFIGURATION_ERROR", "PROVIDER_RESPONSE_SCHEMA_MISMATCH")
    return json.loads(payload_bytes), payload_bytes


def _validate_authorization_and_package(
    request_manifest: Path,
    authorization_record: Path,
    package_zip: Path,
    package_root: Path,
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    contract = load_json(package_root / "EXECUTION_CONTRACT.json")
    source_hashes = load_json(package_root / "PACKAGE_SOURCE_HASHES.json")
    authorization = load_json(authorization_record)
    entries = list(package_root.iterdir())
    if {path.name for path in entries} != PACKAGE_FILES or any(
        path.is_symlink() or not path.is_file() for path in entries
    ):
        raise ValueError("extracted package member allowlist mismatch")
    member_hashes = source_hashes.get("member_sha256_excluding_self")
    if not isinstance(member_hashes, Mapping) or set(member_hashes) != PACKAGE_FILES - {
        "PACKAGE_SOURCE_HASHES.json"
    }:
        raise ValueError("package member-hash manifest mismatch")
    for name, expected in member_hashes.items():
        if not isinstance(expected, str) or sha256_file(package_root / name) != expected:
            raise ValueError(f"extracted package member hash mismatch: {name}")
    expected_source_hashes = {
        "GENERATION_PROMPT.txt": EXPECTED_PROMPT_SHA256,
        "GENERATION_SCHEMA.json": EXPECTED_SCHEMA_SHA256,
        "GENERATION_CONFIGURATION.json": EXPECTED_CONFIGURATION_SHA256,
        "STUDENT_FACING_FORMAT_CONTRACT_V2.json": EXPECTED_FORMAT_CONTRACT_SHA256,
        "c4_real_student_facing_response_validator_v2.py": EXPECTED_VALIDATOR_SHA256,
    }
    for name, expected in expected_source_hashes.items():
        if sha256_file(package_root / name) != expected:
            raise ValueError(f"frozen package source hash mismatch: {name}")
    if set(authorization) != AUTHORIZATION_FIELDS:
        raise ValueError("authorization record field set mismatch")
    if authorization.get("schema_version") != "c4-real-response-regeneration-authorization-r3":
        raise ValueError("authorization record schema mismatch")
    if authorization.get("status") != "AUTHORIZED":
        raise ValueError("authorization status is not AUTHORIZED")
    if not isinstance(authorization.get("authorization_id"), str) or not authorization[
        "authorization_id"
    ].strip():
        raise ValueError("authorization_id is required")
    if not isinstance(authorization.get("authorized_by"), str) or not authorization[
        "authorized_by"
    ].strip():
        raise ValueError("authorized_by is required")
    if not isinstance(authorization.get("authorized_at_utc"), str) or not _UTC.fullmatch(
        authorization["authorized_at_utc"]
    ):
        raise ValueError("authorized_at_utc must be an explicit UTC timestamp")
    package_digest = sha256_file(package_zip)
    manifest_digest = sha256_file(request_manifest)
    expected = {
        "package_id": contract.get("package_id"),
        "shard": contract.get("shard"),
        "request_count": len(rows),
        "maximum_physical_attempts": len(rows) * MAX_ATTEMPTS_PER_REQUEST,
        "package_sha256": package_digest,
        "blinded_manifest_sha256": manifest_digest,
    }
    for field, value in expected.items():
        if authorization.get(field) != value:
            raise ValueError(f"authorization binding mismatch: {field}")
    if not _HEX64.fullmatch(str(authorization.get("package_sha256", ""))):
        raise ValueError("authorization package hash is malformed")
    if not _HEX64.fullmatch(str(authorization.get("blinded_manifest_sha256", ""))):
        raise ValueError("authorization manifest hash is malformed")
    if (
        contract.get("status") != "PREPARED_NOT_AUTHORIZED"
        or contract.get("request_count") != len(rows)
        or contract.get("maximum_physical_attempts") != len(rows) * 2
        or source_hashes.get("package_id") != contract.get("package_id")
        or source_hashes.get("shard") != contract.get("shard")
        or source_hashes.get("blinded_manifest_sha256") != manifest_digest
    ):
        raise ValueError("execution contract or package-source binding mismatch")
    with zipfile.ZipFile(package_zip) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != PACKAGE_FILES:
            raise ValueError("package ZIP member allowlist mismatch")
        if any(Path(name).name != name or name.endswith("/") for name in names):
            raise ValueError("package ZIP contains a nested or directory member")
        for name in PACKAGE_FILES:
            if archive.read(name) != (package_root / name).read_bytes():
                raise ValueError(f"extracted package differs from authorized ZIP: {name}")
    return {
        "authorization": authorization,
        "authorization_record_sha256": sha256_file(authorization_record),
        "contract": contract,
        "package_sha256": package_digest,
        "blinded_manifest_sha256": manifest_digest,
        "prompt": (package_root / "GENERATION_PROMPT.txt").read_text(encoding="utf-8"),
        "schema": load_json(package_root / "GENERATION_SCHEMA.json"),
    }


def _base_attempt_record(
    logical_order: int,
    row: Mapping[str, Any],
    attempt_number: int,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-generation-attempt-v3",
        "logical_order": logical_order,
        "logical_generation_request_id": row.get("logical_generation_request_id"),
        "response_blind_id": row.get("response_blind_id"),
        "attempt_number": attempt_number,
        "provider_payload_sha256": row.get("provider_payload_sha256"),
        "requested_model": EXPECTED_MODEL,
        "returned_model": None,
        "provider_response_id": None,
        "system_fingerprint": None,
        "finish_reason": None,
        "raw_response_content": None,
        "parsed_output": None,
        "outer_schema_validation_status": None,
        "student_facing_validation_status": None,
        "retryable_failure": None,
        "prompt_tokens": None,
        "cached_input_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "started_at_utc": started_at,
        "completed_at_utc": None,
        "latency_ms": None,
        "error": None,
    }


def _finalize(
    output_dir: Path,
    *,
    status: str,
    reason: str | None,
    request_count: int,
    valid_count: int,
    incomplete_count: int,
    physical_attempts: int,
    usage: Mapping[str, int],
    runtime_identity: Mapping[str, Any] | None,
    started_at: str,
    now: Callable[[], str],
) -> None:
    maximum = request_count * MAX_ATTEMPTS_PER_REQUEST
    write_atomic_json(
        output_dir / "GENERATION_EXECUTION_STATUS.json",
        {
            "schema_version": "c4-real-generation-execution-status-v3",
            "status": status,
            "stop_reason": reason,
            "request_count": request_count,
            "valid_response_count": valid_count,
            "incomplete_logical_request_count": incomplete_count,
            "unattempted_logical_request_count": request_count - valid_count - incomplete_count,
            "physical_attempt_count": physical_attempts,
            "maximum_physical_attempts": maximum,
            "automatic_resume": False,
            "continuation_requires_new_direct_authorization": True,
            "runtime_identity": dict(runtime_identity) if runtime_identity is not None else None,
            "started_at_utc": started_at,
            "completed_at_utc": now(),
            "judge_calls": 0,
            "scoring_calls": 0,
        },
    )
    write_atomic_json(
        output_dir / "GENERATION_USAGE_AND_COST.json",
        {
            "schema_version": "c4-real-generation-usage-and-cost-v3",
            **dict(usage),
            "usage_arithmetic_valid": usage["total_tokens"]
            == usage["prompt_tokens"] + usage["completion_tokens"],
            "cost_status": "NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY",
            "cost_amount": None,
            "cost_currency": None,
            "provider_calls_observed": physical_attempts,
            "judge_calls": 0,
        },
    )
    report = (
        "# C4 REAL regeneration execution report R3\n\n"
        f"Status: `{status}`.\n\n"
        f"Stop reason: `{reason or 'NONE'}`.\n\n"
        f"Logical requests: `{request_count}`; valid: `{valid_count}`; incomplete: `{incomplete_count}`; "
        f"physical attempts: `{physical_attempts}` of maximum `{maximum}`.\n\n"
        "Automatic resume is disabled. Any continuation requires new direct authorization. No Judge or scoring operation is part of this runner.\n"
    ).encode("utf-8")
    write_exclusive_bytes(output_dir / "GENERATION_EXECUTION_REPORT.md", report)


def execute_package(
    request_manifest: Path,
    authorization_record: Path,
    package_zip: Path,
    output_dir: Path,
    *,
    package_root: Path | None = None,
    runtime_checker: Callable[[], Mapping[str, Any]] = runtime_preflight,
    client_factory: Callable[[], Any] = default_client_factory,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = utc_now,
) -> int:
    """Execute one authorized shard; injected callables are for offline tests only."""

    if os.environ.get(AUTHORIZATION_ENVIRONMENT_VARIABLE) != AUTHORIZATION_ENVIRONMENT_VALUE:
        raise ValueError("exact R3C1 continuation environment authorization is required")
    request_manifest = request_manifest.resolve()
    authorization_record = authorization_record.resolve()
    package_zip = package_zip.resolve()
    output_dir = output_dir.resolve()
    package_root = (package_root or request_manifest.parent).resolve()
    if output_dir.exists():
        raise FileExistsError("Refusing overwrite or automatic resume: output directory exists")
    if not output_dir.parent.is_dir():
        raise FileNotFoundError("output parent directory does not exist")
    rows = load_jsonl(request_manifest)
    binding = _validate_authorization_and_package(
        request_manifest, authorization_record, package_zip, package_root, rows
    )
    os.mkdir(output_dir, mode=0o700)
    started_at = now()
    write_exclusive_json(
        output_dir / "GENERATION_PREFLIGHT_RECEIPT.json",
        {
            "schema_version": "c4-real-generation-preflight-start-receipt-v3",
            "status": "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
            "started_at_utc": started_at,
            "package_id": binding["contract"]["package_id"],
            "shard": binding["contract"]["shard"],
            "request_count": len(rows),
            "maximum_physical_attempts": len(rows) * 2,
            "package_sha256": binding["package_sha256"],
            "blinded_manifest_sha256": binding["blinded_manifest_sha256"],
            "authorization_id": binding["authorization"]["authorization_id"],
            "authorization_record_sha256": binding["authorization_record_sha256"],
            "runtime_constructed": False,
            "client_constructed": False,
            "automatic_resume": False,
            "judge_calls": 0,
        },
    )
    attempts_path = output_dir / "GENERATION_ATTEMPT_JOURNAL.jsonl"
    terminal_path = output_dir / "GENERATION_TERMINAL_JOURNAL.jsonl"
    errors_path = output_dir / "GENERATION_ERROR_REGISTRY.jsonl"
    create_exclusive_empty(attempts_path)
    create_exclusive_empty(terminal_path)
    create_exclusive_empty(errors_path)
    write_atomic_json(
        output_dir / "GENERATION_EXECUTION_STATUS.json",
        {
            "schema_version": "c4-real-generation-execution-status-v3",
            "status": "RUNNING_PREFLIGHT",
            "started_at_utc": started_at,
            "automatic_resume": False,
        },
    )
    aggregate_usage = {
        "prompt_tokens": 0,
        "cached_input_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "responses_without_cached_token_detail": 0,
    }
    physical_attempts = 0
    valid_count = 0
    incomplete_count = 0
    runtime_identity: Mapping[str, Any] | None = None

    def stop_before_or_during_requests(
        error: BaseException,
        stage: str,
        logical_order: int | None = None,
        row: Mapping[str, Any] | None = None,
        attempt_number: int | None = None,
    ) -> int:
        nonlocal incomplete_count
        category = categorize_error(error)
        sanitized = sanitize_error(error, category)
        append_fsync(
            errors_path,
            {
                "schema_version": "c4-real-generation-error-v3",
                "stage": stage,
                "logical_order": logical_order,
                "logical_generation_request_id": row.get("logical_generation_request_id") if row else None,
                "response_blind_id": row.get("response_blind_id") if row else None,
                "attempt_number": attempt_number,
                "error": sanitized,
                "recorded_at_utc": now(),
                "shard_stop": True,
            },
        )
        if row is not None:
            incomplete_count += 1
            append_fsync(
                terminal_path,
                {
                    "schema_version": "c4-real-generation-terminal-v3",
                    "logical_order": logical_order,
                    "logical_generation_request_id": row.get("logical_generation_request_id"),
                    "response_blind_id": row.get("response_blind_id"),
                    "terminal_status": "INCOMPLETE_NON_RETRYABLE_ERROR",
                    "physical_attempts": attempt_number or 0,
                    "provider_payload_sha256": row.get("provider_payload_sha256"),
                    "error": sanitized,
                    "recorded_at_utc": now(),
                },
            )
        _finalize(
            output_dir,
            status="INCOMPLETE_FAIL_CLOSED",
            reason=category,
            request_count=len(rows),
            valid_count=valid_count,
            incomplete_count=incomplete_count,
            physical_attempts=physical_attempts,
            usage=aggregate_usage,
            runtime_identity=runtime_identity,
            started_at=started_at,
            now=now,
        )
        return 2

    try:
        runtime_identity = dict(runtime_checker())
        if (
            runtime_identity.get("python_version") != "3.13.5"
            or runtime_identity.get("openai_sdk_version") != EXPECTED_OPENAI
            or os.path.realpath(str(runtime_identity.get("python_path")))
            != os.path.realpath(EXPECTED_PYTHON_PATH)
            or runtime_identity.get("automatic_sdk_retries") != 0
        ):
            raise RunnerFailure("RUNTIME_PREFLIGHT_ERROR", "RUNTIME_IDENTITY_MISMATCH")
    except Exception as error:
        return stop_before_or_during_requests(error, "RUNTIME_PREFLIGHT")
    try:
        client = client_factory()
    except Exception as error:
        return stop_before_or_during_requests(error, "CLIENT_CONSTRUCTION")

    write_atomic_json(
        output_dir / "GENERATION_EXECUTION_STATUS.json",
        {
            "schema_version": "c4-real-generation-execution-status-v3",
            "status": "RUNNING_REGENERATION",
            "started_at_utc": started_at,
            "runtime_identity": dict(runtime_identity),
            "client_constructed": True,
            "automatic_resume": False,
        },
    )

    previous_initial_started: float | None = None
    for logical_order, row in enumerate(rows, 1):
        try:
            payload, payload_bytes = _validate_request_row(
                row, str(binding["prompt"]), binding["schema"]
            )
        except Exception as error:
            return stop_before_or_during_requests(error, "REQUEST_VALIDATION", logical_order, row, 0)
        if previous_initial_started is not None:
            remaining = INITIAL_REQUEST_GAP_SECONDS - (monotonic() - previous_initial_started)
            if remaining > 0:
                sleeper(remaining)
        previous_initial_started = monotonic()

        for attempt_number in range(1, MAX_ATTEMPTS_PER_REQUEST + 1):
            if canonical_bytes(payload) != payload_bytes:
                return stop_before_or_during_requests(
                    RunnerFailure("CONFIGURATION_ERROR", "RETRY_PAYLOAD_BYTES_CHANGED"),
                    "PRE_ATTEMPT_VALIDATION",
                    logical_order,
                    row,
                    attempt_number,
                )
            attempt_started_at = now()
            started_clock = monotonic()
            physical_attempts += 1
            record = _base_attempt_record(logical_order, row, attempt_number, attempt_started_at)
            response: Any = None
            try:
                response = client.chat.completions.create(**json.loads(payload_bytes))
                extracted = _extract_response(response)
                parsed_output, retryable_failure, semantic_status = validate_response_content(
                    extracted["raw_response_content"]
                )
                usage = extracted["usage"]
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    aggregate_usage[field] += int(usage[field])
                if usage["cached_input_tokens"] is None:
                    aggregate_usage["responses_without_cached_token_detail"] += 1
                else:
                    aggregate_usage["cached_input_tokens"] += int(usage["cached_input_tokens"])
                outer_status = (
                    "VALID"
                    if retryable_failure in (None, "NON_STUDENT_FACING_FORMAT")
                    else retryable_failure
                )
                record.update(
                    {
                        "returned_model": extracted["returned_model"],
                        "provider_response_id": extracted["provider_response_id"],
                        "system_fingerprint": extracted["system_fingerprint"],
                        "finish_reason": extracted["finish_reason"],
                        "raw_response_content": extracted["raw_response_content"],
                        "parsed_output": parsed_output,
                        "outer_schema_validation_status": outer_status,
                        "student_facing_validation_status": semantic_status,
                        "retryable_failure": retryable_failure,
                        **usage,
                        "completed_at_utc": now(),
                        "latency_ms": round((monotonic() - started_clock) * 1000.0, 3),
                    }
                )
                append_fsync(attempts_path, record)
                if retryable_failure is not None and attempt_number == 1:
                    continue
                if retryable_failure is not None:
                    incomplete_count += 1
                    append_fsync(
                        terminal_path,
                        {
                            "schema_version": "c4-real-generation-terminal-v3",
                            "logical_order": logical_order,
                            "logical_generation_request_id": row["logical_generation_request_id"],
                            "response_blind_id": row["response_blind_id"],
                            "terminal_status": "INCOMPLETE_AFTER_SECOND_INVALID_RESPONSE",
                            "terminal_invalid_category": retryable_failure,
                            "physical_attempts": attempt_number,
                            "provider_payload_sha256": row["provider_payload_sha256"],
                            "last_raw_response_content": extracted["raw_response_content"],
                            "recorded_at_utc": now(),
                        },
                    )
                    _finalize(
                        output_dir,
                        status="INCOMPLETE_FAIL_CLOSED",
                        reason="SECOND_INVALID_RESPONSE",
                        request_count=len(rows),
                        valid_count=valid_count,
                        incomplete_count=incomplete_count,
                        physical_attempts=physical_attempts,
                        usage=aggregate_usage,
                        runtime_identity=runtime_identity,
                        started_at=started_at,
                        now=now,
                    )
                    return 2
                append_fsync(
                    terminal_path,
                    {
                        "schema_version": "c4-real-generation-terminal-v3",
                        "logical_order": logical_order,
                        "logical_generation_request_id": row["logical_generation_request_id"],
                        "response_blind_id": row["response_blind_id"],
                        "terminal_status": "VALID_STUDENT_FACING_RESPONSE",
                        "physical_attempts": attempt_number,
                        "provider_payload_sha256": row["provider_payload_sha256"],
                        "requested_model": EXPECTED_MODEL,
                        "returned_model": extracted["returned_model"],
                        "provider_response_id": extracted["provider_response_id"],
                        "system_fingerprint": extracted["system_fingerprint"],
                        "finish_reason": extracted["finish_reason"],
                        "raw_response_content": extracted["raw_response_content"],
                        "parsed_output": parsed_output,
                        "student_facing_validation_status": semantic_status,
                        **usage,
                        "recorded_at_utc": now(),
                    },
                )
                valid_count += 1
                break
            except Exception as error:
                category = categorize_error(error)
                sanitized = sanitize_error(error, category)
                if response is not None:
                    observed = _best_effort_response_fields(response)
                    for field in (
                        "returned_model",
                        "provider_response_id",
                        "system_fingerprint",
                        "finish_reason",
                        "raw_response_content",
                    ):
                        if field in observed:
                            record[field] = observed[field]
                    observed_usage = observed.get("usage")
                    if isinstance(observed_usage, Mapping):
                        record.update(observed_usage)
                        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                            aggregate_usage[field] += int(observed_usage[field])
                        if observed_usage["cached_input_tokens"] is None:
                            aggregate_usage["responses_without_cached_token_detail"] += 1
                        else:
                            aggregate_usage["cached_input_tokens"] += int(
                                observed_usage["cached_input_tokens"]
                            )
                record.update(
                    {
                        "outer_schema_validation_status": "NON_RETRYABLE_ERROR",
                        "completed_at_utc": now(),
                        "latency_ms": round((monotonic() - started_clock) * 1000.0, 3),
                        "error": sanitized,
                    }
                )
                append_fsync(attempts_path, record)
                return stop_before_or_during_requests(
                    error, "PROVIDER_ATTEMPT", logical_order, row, attempt_number
                )

    _finalize(
        output_dir,
        status="COMPLETE_VALID_STUDENT_FACING_RESPONSES",
        reason=None,
        request_count=len(rows),
        valid_count=valid_count,
        incomplete_count=incomplete_count,
        physical_attempts=physical_attempts,
        usage=aggregate_usage,
        runtime_identity=runtime_identity,
        started_at=started_at,
        now=now,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization-record", type=Path, required=True)
    parser.add_argument("--package-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print("Generation is not authorized: --execute is required.", file=sys.stderr)
        return 2
    if os.environ.get(AUTHORIZATION_ENVIRONMENT_VARIABLE) != AUTHORIZATION_ENVIRONMENT_VALUE:
        print("Generation is not authorized: exact R3C1 continuation environment value is required.", file=sys.stderr)
        return 2
    package_root = Path(__file__).resolve().parent
    try:
        return execute_package(
            package_root / "BLINDED_REQUESTS.jsonl",
            args.authorization_record,
            args.package_zip,
            args.output_dir,
            package_root=package_root,
        )
    except Exception as error:
        print(f"Generation failed closed: {sanitize_error(error)['sanitized_message']}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
