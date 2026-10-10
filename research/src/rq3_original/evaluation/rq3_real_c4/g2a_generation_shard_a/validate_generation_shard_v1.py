#!/opt/anaconda3/bin/python3
"""Offline mechanical validator for frozen C4 REAL generation shard A."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "execution_output_v1"
PACKAGE_ZIP = Path(
    "/Users/liuming/Downloads/"
    "C4_REAL_GENERATION_SHARD_A_EXECUTION_PACKAGE_R2_2026-09-01.zip"
)

EXPECTED_WORKING_DIRECTORY = (
    "/Users/liuming/Downloads/rq2_v2_parallel/"
    "rq3-real-g2a-generation-shard-a"
)
EXPECTED_BRANCH = "research/rq3-real-c4-g2a-generation-shard-a"
EXPECTED_STARTING_HEAD = "2fd113d7c2d64442bb939cbd7aee80cab0ab4178"
EXPECTED_PACKAGE_ID = "C4_REAL_GENERATION_SHARD_A_R2_20260901"
EXPECTED_PACKAGE_SHA256 = (
    "e64aedae3499e8d4bd2d7c632d44b9757d8754854531d2ae96c611492402a148"
)
EXPECTED_MANIFEST_SHA256 = (
    "36cfcffadec9cf7bde0aed3b10a8b111df94c7b1d83a30c9387c28c7285e3cad"
)
EXPECTED_AUTHORIZATION_ID = "RQ3-REAL-C4-G2A-RESPONSE-GENERATION-20260901"
EXPECTED_AUTHORIZATION_SHA256 = (
    "e0a3778f8d7c4634c3d22cdf9e37c8a7464a210fb11639da0554c8666a3ae153"
)
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_PROMPT_SHA256 = (
    "41748d1f3a69ce6623e607551a8473228c0724871e16e392ecd7872b4e550b21"
)
EXPECTED_SCHEMA_SHA256 = (
    "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
)
EXPECTED_CONFIGURATION_SHA256 = (
    "3a589b593c964288ab5976718dd4fcb1e2d45186d978ee201b235a7aaf25059c"
)
EXPECTED_REQUEST_COUNT = 73
EXPECTED_MAXIMUM_ATTEMPTS = 146
EXPECTED_TERMINAL_JOURNAL_SHA256 = (
    "a106e593a6cbb1b886634c4b349af50d072afa5d30801e469158fd38449979eb"
)
EXPECTED_ANSWER_SET_SHA256 = (
    "89e73290a395023464e02ed954a2747c74be2bcf45bba1c0f94d83a55f701a23"
)

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

PARENT_ENTRIES = {
    "C4_REAL_GENERATION_SHARD_REPORT.md",
    "REVIEW_MANIFEST.json",
    "STATUS.md",
    "execution_output_v1",
    "generation_execution_audit_v1.json",
    "generation_execution_authorization_v1.json",
    "generation_execution_source_manifest_v1.json",
    "test_generation_shard_v1.py",
    "validate_generation_shard_v1.py",
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

TERMINAL_FIELDS = {
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

EXPECTED_PACKAGE_MEMBER_HASHES = {
    "BLINDED_REQUESTS.jsonl": EXPECTED_MANIFEST_SHA256,
    "EXECUTION_CONTRACT.json": (
        "ff7618b14822aaa00bee7ad6d305e4830fdc4c93b3f2e109da4066f03db9f277"
    ),
    "GENERATION_CONFIGURATION.json": EXPECTED_CONFIGURATION_SHA256,
    "GENERATION_PROMPT.txt": EXPECTED_PROMPT_SHA256,
    "GENERATION_SCHEMA.json": EXPECTED_SCHEMA_SHA256,
    "PACKAGE_SOURCE_HASHES.json": (
        "48a7be318a1cb20fec9da637067723341e9b486969bdcca9b12377eefac85324"
    ),
    "README.md": (
        "7cfe8474f1543d1f78731e294b3493f302d202b17b6e0d9ec6e2cfe0ba3b165d"
    ),
    "generation_execution_runner_v2.py": (
        "3d45aff869f4855ec4d2846ed0afa69d34c506c9d55bb7b913c5c72807486eee"
    ),
    "test_package.py": (
        "beff41a37193876a900835981452b21dd38ac6aacd356392afbce13c6c6e4830"
    ),
    "validate_package.py": (
        "9fdbd5544aaaad825ce268e206daadff3b7e0d1cca7b837fc553cebe84bec445"
    ),
}

EXPECTED_OUTPUT_HASHES = {
    "GENERATION_ATTEMPT_JOURNAL.jsonl": (
        "9c4a59c7a36132eb95f981309a9ef8aea1392945b8a83e34092ead9562e68c2c"
    ),
    "GENERATION_ERROR_REGISTRY.jsonl": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    ),
    "GENERATION_EXECUTION_REPORT.md": (
        "a724440b0f81b81a5ed65b01ec426b7ffa3bcf8053d9a45c0200ef3fb8624c0a"
    ),
    "GENERATION_EXECUTION_STATUS.json": (
        "9e0d753494010a906c2a6ebfb9d07ad38511eb3bfc60765d6540843c43ca4193"
    ),
    "GENERATION_PREFLIGHT_RECEIPT.json": (
        "2cf62f8f2352b6b05da1624618cb803ef2d49e2e1de5ec9ae239f07058ef9524"
    ),
    "GENERATION_TERMINAL_JOURNAL.jsonl": EXPECTED_TERMINAL_JOURNAL_SHA256,
    "GENERATION_USAGE_AND_COST.json": (
        "9d681076a16b478aac2c6520c91c04e9b340a88dd114c67a9f18ba41f28d08b6"
    ),
}

FORBIDDEN_OUTPUT_FIELD_TOKENS = {
    "gold",
    "mode",
    "condition",
    "route",
    "judge",
    "rating",
    "score",
    "scoring",
}
SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"OPENAI_API_KEY\s*="),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"HMAC[_ -]?KEY\s*[:=]", re.IGNORECASE),
)
UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NETWORK_IMPORT_ROOTS = {"aiohttp", "httpx", "openai", "requests", "socket", "urllib"}


class AuditFailure(AssertionError):
    """A named mechanical invariant failed."""


class Checks:
    def __init__(self) -> None:
        self.count = 0
        self.groups: Counter[str] = Counter()

    def require(self, condition: bool, message: str, group: str) -> None:
        self.count += 1
        self.groups[group] += 1
        if not condition:
            raise AuditFailure(f"{group}: {message}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditFailure(f"{path.name} must contain one JSON object")
    return value


def read_jsonl_bytes(data: bytes, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    text = data.decode("utf-8")
    if not text:
        return [] if allow_empty else _raise("required JSONL is empty")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            raise AuditFailure(f"blank JSONL line {line_number}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AuditFailure(f"JSONL line {line_number} is not an object")
        rows.append(value)
    return rows


def read_jsonl(path: Path, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    return read_jsonl_bytes(path.read_bytes(), allow_empty=allow_empty)


def _raise(message: str) -> Any:
    raise AuditFailure(message)


def field_tokens(key: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", key.casefold()) if token}


def walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_keys(nested)


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def validate(
    root: Path = ROOT,
    package_zip: Path = PACKAGE_ZIP,
) -> dict[str, Any]:
    checks = Checks()
    root = root.resolve()
    package_zip = package_zip.resolve()
    output_dir = root / "execution_output_v1"

    checks.require(str(root.parent.parent.parent) == EXPECTED_WORKING_DIRECTORY,
                   "working-directory binding mismatch", "support_artifacts")
    checks.require(package_zip == PACKAGE_ZIP,
                   "authoritative package path mismatch", "package_zip_identity")
    checks.require(package_zip.is_file() and not package_zip.is_symlink(),
                   "authoritative package is not a regular file", "package_zip_identity")
    checks.require(sha256_file(package_zip) == EXPECTED_PACKAGE_SHA256,
                   "authoritative ZIP hash mismatch", "package_zip_identity")

    with zipfile.ZipFile(package_zip) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        checks.require(len(names) == len(set(names)), "duplicate ZIP member", "package_member_allowlist")
        checks.require(set(names) == PACKAGE_FILES, "ZIP member allowlist mismatch", "package_member_allowlist")
        for info in infos:
            checks.require(Path(info.filename).name == info.filename and not info.is_dir(),
                           f"nested or directory ZIP member: {info.filename}", "package_member_allowlist")
        package_bytes = {name: archive.read(name) for name in names}

    for name, expected in EXPECTED_PACKAGE_MEMBER_HASHES.items():
        checks.require(sha256_bytes(package_bytes[name]) == expected,
                       f"package member hash mismatch: {name}", "package_member_hashes")

    checks.require(sha256_bytes(package_bytes["GENERATION_PROMPT.txt"]) == EXPECTED_PROMPT_SHA256,
                   "prompt hash mismatch", "frozen_scientific_identity")
    checks.require(sha256_bytes(package_bytes["GENERATION_SCHEMA.json"]) == EXPECTED_SCHEMA_SHA256,
                   "schema hash mismatch", "frozen_scientific_identity")
    checks.require(sha256_bytes(package_bytes["GENERATION_CONFIGURATION.json"]) == EXPECTED_CONFIGURATION_SHA256,
                   "configuration hash mismatch", "frozen_scientific_identity")
    prompt = package_bytes["GENERATION_PROMPT.txt"].decode("utf-8")
    schema = json.loads(package_bytes["GENERATION_SCHEMA.json"])
    configuration = json.loads(package_bytes["GENERATION_CONFIGURATION.json"])
    contract = json.loads(package_bytes["EXECUTION_CONTRACT.json"])
    internal_hashes = json.loads(package_bytes["PACKAGE_SOURCE_HASHES.json"])
    checks.require(schema == {
        "type": "object",
        "properties": {"answer_text": {"type": "string"}},
        "required": ["answer_text"],
        "additionalProperties": False,
    }, "response schema mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("model") == EXPECTED_MODEL, "configured model mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("endpoint") == "OpenAI Chat Completions", "endpoint mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("temperature") == 0, "temperature mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("max_output_tokens") == 512, "output-token limit mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("streaming") is False, "streaming mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("tools") == "NONE", "tools mismatch", "frozen_scientific_identity")
    checks.require(configuration.get("automatic_sdk_retries") == 0, "SDK retry mismatch", "frozen_scientific_identity")
    checks.require(contract.get("manual_retry") == "ONE_IDENTICAL_RETRY_ONLY_INVALID_JSON_OR_STRICT_SCHEMA",
                   "manual retry contract mismatch", "frozen_scientific_identity")
    checks.require(contract.get("request_count") == EXPECTED_REQUEST_COUNT,
                   "contract request count mismatch", "frozen_scientific_identity")
    checks.require(contract.get("maximum_physical_attempts") == EXPECTED_MAXIMUM_ATTEMPTS,
                   "contract attempt ceiling mismatch", "frozen_scientific_identity")
    checks.require(internal_hashes.get("member_sha256_excluding_self") == {
        key: value for key, value in EXPECTED_PACKAGE_MEMBER_HASHES.items()
        if key != "PACKAGE_SOURCE_HASHES.json"
    }, "internal package member hashes mismatch", "package_member_hashes")

    manifest_rows = read_jsonl_bytes(package_bytes["BLINDED_REQUESTS.jsonl"])
    checks.require(len(manifest_rows) == EXPECTED_REQUEST_COUNT,
                   "manifest population mismatch", "request_population_and_order")
    logical_ids: list[str] = []
    blind_ids: list[str] = []
    for order, row in enumerate(manifest_rows, 1):
        checks.require(set(row) == REQUEST_FIELDS,
                       f"request field set mismatch at {order}", "request_population_and_order")
        checks.require(row.get("schema_version") == "c4-real-blinded-generation-request-v2",
                       f"request schema mismatch at {order}", "request_population_and_order")
        logical_id = row.get("logical_generation_request_id")
        blind_id = row.get("response_blind_id")
        checks.require(isinstance(logical_id, str) and bool(logical_id),
                       f"logical ID invalid at {order}", "request_population_and_order")
        checks.require(isinstance(blind_id, str) and bool(blind_id),
                       f"blind ID invalid at {order}", "request_population_and_order")
        logical_ids.append(logical_id)
        blind_ids.append(blind_id)
        payload = row.get("provider_payload")
        checks.require(isinstance(payload, dict), f"payload missing at {order}", "payload_hashes")
        checks.require(sha256_bytes(canonical_bytes(payload)) == row.get("provider_payload_sha256"),
                       f"payload hash mismatch at {order}", "payload_hashes")
        checks.require(set(payload) == {"model", "messages", "temperature", "max_tokens", "stream", "response_format"},
                       f"payload fields mismatch at {order}", "payload_hashes")
        checks.require(payload.get("model") == EXPECTED_MODEL and payload.get("temperature") == 0,
                       f"payload model or temperature mismatch at {order}", "payload_hashes")
        checks.require(payload.get("max_tokens") == 512 and payload.get("stream") is False,
                       f"payload output limit or stream mismatch at {order}", "payload_hashes")
        messages = payload.get("messages")
        checks.require(isinstance(messages, list) and len(messages) == 2,
                       f"message count mismatch at {order}", "payload_hashes")
        checks.require(messages[0] == {"role": "system", "content": prompt},
                       f"system prompt mismatch at {order}", "payload_hashes")
        checks.require(isinstance(messages[1], dict) and set(messages[1]) == {"role", "content"}
                       and messages[1].get("role") == "user"
                       and isinstance(messages[1].get("content"), str),
                       f"user message shape mismatch at {order}", "payload_hashes")
        checks.require(payload.get("response_format") == {
            "type": "json_schema",
            "json_schema": {
                "name": "c4_real_generation_response_v2_provider_compatible",
                "strict": True,
                "schema": schema,
            },
        }, f"response format mismatch at {order}", "payload_hashes")
    checks.require(len(set(logical_ids)) == EXPECTED_REQUEST_COUNT,
                   "logical IDs are not unique", "request_population_and_order")
    checks.require(len(set(blind_ids)) == EXPECTED_REQUEST_COUNT,
                   "response blind IDs are not unique", "request_population_and_order")

    checks.require(set(path.name for path in root.iterdir()) == PARENT_ENTRIES,
                   "authorized parent contains an unexpected entry", "output_exclusivity")
    checks.require(output_dir.is_dir() and not output_dir.is_symlink(),
                   "execution-output leaf missing or not a directory", "output_exclusivity")
    checks.require(set(path.name for path in output_dir.iterdir()) == OUTPUT_FILES,
                   "execution-output file allowlist mismatch", "output_exclusivity")
    checks.require(not any(path.is_symlink() or not path.is_file() for path in output_dir.iterdir()),
                   "execution output contains non-regular member", "output_exclusivity")
    for name, expected in EXPECTED_OUTPUT_HASHES.items():
        checks.require(sha256_file(output_dir / name) == expected,
                       f"durable output hash mismatch: {name}", "output_exclusivity")

    authorization_path = root / "generation_execution_authorization_v1.json"
    authorization = read_json(authorization_path)
    checks.require(set(authorization) == AUTHORIZATION_FIELDS,
                   "authorization field set mismatch", "authorization_shape")
    checks.require(len(authorization) == 11, "authorization must have eleven fields", "authorization_shape")
    checks.require(authorization.get("schema_version") == "c4-real-response-generation-authorization-r2",
                   "authorization schema mismatch", "authorization_shape")
    checks.require(authorization.get("authorized_by") == "Ming Liu",
                   "authorizer mismatch", "authorization_shape")
    checks.require(isinstance(authorization.get("authorized_at_utc"), str)
                   and UTC_PATTERN.fullmatch(authorization["authorized_at_utc"]) is not None,
                   "authorization UTC timestamp mismatch", "authorization_shape")
    expected_authorization = {
        "authorization_id": EXPECTED_AUTHORIZATION_ID,
        "package_id": EXPECTED_PACKAGE_ID,
        "shard": "A",
        "request_count": EXPECTED_REQUEST_COUNT,
        "maximum_physical_attempts": EXPECTED_MAXIMUM_ATTEMPTS,
        "package_sha256": EXPECTED_PACKAGE_SHA256,
        "blinded_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "status": "AUTHORIZED",
    }
    for key, value in expected_authorization.items():
        checks.require(authorization.get(key) == value,
                       f"authorization binding mismatch: {key}", "authorization_binding")
    checks.require(sha256_file(authorization_path) == EXPECTED_AUTHORIZATION_SHA256,
                   "authorization record hash mismatch", "authorization_binding")

    receipt = read_json(output_dir / "GENERATION_PREFLIGHT_RECEIPT.json")
    checks.require(receipt.get("status") == "STARTED_BEFORE_RUNTIME_AND_CLIENT_CONSTRUCTION",
                   "preflight receipt status mismatch", "preflight_receipt")
    checks.require(receipt.get("runtime_constructed") is False
                   and receipt.get("client_constructed") is False,
                   "preflight receipt timing flags mismatch", "preflight_receipt")
    for key, value in {
        "authorization_id": EXPECTED_AUTHORIZATION_ID,
        "authorization_record_sha256": EXPECTED_AUTHORIZATION_SHA256,
        "package_id": EXPECTED_PACKAGE_ID,
        "package_sha256": EXPECTED_PACKAGE_SHA256,
        "blinded_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "request_count": EXPECTED_REQUEST_COUNT,
        "maximum_physical_attempts": EXPECTED_MAXIMUM_ATTEMPTS,
        "shard": "A",
        "judge_calls": 0,
        "automatic_resume": False,
    }.items():
        checks.require(receipt.get(key) == value,
                       f"preflight receipt mismatch: {key}", "preflight_receipt")

    status = read_json(output_dir / "GENERATION_EXECUTION_STATUS.json")
    checks.require(status.get("status") == "COMPLETE" and status.get("stop_reason") is None,
                   "execution status is not complete", "execution_complete")
    for key, value in {
        "request_count": EXPECTED_REQUEST_COUNT,
        "valid_response_count": EXPECTED_REQUEST_COUNT,
        "incomplete_logical_request_count": 0,
        "unattempted_logical_request_count": 0,
        "physical_attempt_count": EXPECTED_REQUEST_COUNT,
        "maximum_physical_attempts": EXPECTED_MAXIMUM_ATTEMPTS,
        "automatic_resume": False,
        "continuation_requires_new_direct_authorization": True,
        "judge_calls": 0,
        "scoring_calls": 0,
    }.items():
        checks.require(status.get(key) == value,
                       f"execution status mismatch: {key}", "execution_complete")
    runtime = status.get("runtime_identity")
    checks.require(isinstance(runtime, dict), "runtime identity missing", "runtime_identity")
    for key, value in {
        "python_version": "3.13.5",
        "python_path": "/opt/anaconda3/bin/python3",
        "openai_sdk_version": "1.109.1",
        "automatic_sdk_retries": 0,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }.items():
        checks.require(runtime.get(key) == value,
                       f"runtime identity mismatch: {key}", "runtime_identity")
    checks.require(status.get("started_at_utc") == receipt.get("started_at_utc"),
                   "preflight and status start times differ", "preflight_receipt")

    attempts = read_jsonl(output_dir / "GENERATION_ATTEMPT_JOURNAL.jsonl")
    terminals = read_jsonl(output_dir / "GENERATION_TERMINAL_JOURNAL.jsonl")
    errors = read_jsonl(output_dir / "GENERATION_ERROR_REGISTRY.jsonl", allow_empty=True)
    checks.require(len(attempts) == EXPECTED_REQUEST_COUNT,
                   "physical attempt count mismatch", "attempt_order")
    checks.require(len(terminals) == EXPECTED_REQUEST_COUNT,
                   "terminal count mismatch", "terminal_uniqueness")
    checks.require(errors == [], "error registry is not empty", "execution_complete")

    attempts_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record_index, attempt in enumerate(attempts, 1):
        checks.require(set(attempt) == ATTEMPT_FIELDS,
                       f"attempt field set mismatch at record {record_index}", "attempt_order")
        order = attempt.get("logical_order")
        checks.require(isinstance(order, int) and 1 <= order <= EXPECTED_REQUEST_COUNT,
                       f"attempt logical order invalid at record {record_index}", "attempt_order")
        attempts_by_order[order].append(attempt)
    checks.require(sorted(attempts_by_order) == list(range(1, EXPECTED_REQUEST_COUNT + 1)),
                   "attempt logical order population mismatch", "attempt_order")

    answer_hashes: list[dict[str, Any]] = []
    direct_answer_set: list[dict[str, Any]] = []
    terminal_logical_ids: list[str] = []
    terminal_blind_ids: list[str] = []
    usage_sums = {
        "prompt_tokens": 0,
        "cached_input_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    retry_count = 0
    invalid_json_or_schema_count = 0

    for order in range(1, EXPECTED_REQUEST_COUNT + 1):
        manifest = manifest_rows[order - 1]
        group = attempts_by_order[order]
        checks.require(len(group) in {1, 2}, f"attempt count invalid at {order}", "retry_compliance")
        retry_count += len(group) - 1
        for attempt_number, attempt in enumerate(group, 1):
            checks.require(attempt.get("attempt_number") == attempt_number,
                           f"attempt number mismatch at {order}", "attempt_order")
            for key in ("logical_generation_request_id", "response_blind_id", "provider_payload_sha256"):
                checks.require(attempt.get(key) == manifest.get(key),
                               f"attempt binding mismatch at {order}: {key}", "payload_hashes")
            checks.require(attempt.get("requested_model") == EXPECTED_MODEL,
                           f"requested model mismatch at {order}", "returned_model")
            checks.require(attempt.get("returned_model") == EXPECTED_MODEL,
                           f"returned model mismatch at {order}", "returned_model")
            checks.require(attempt.get("finish_reason") == "stop",
                           f"finish reason mismatch at {order}", "strict_output_shape")
            checks.require(attempt.get("error") is None,
                           f"attempt error present at {order}", "execution_complete")
            checks.require(isinstance(attempt.get("provider_response_id"), str)
                           and bool(attempt["provider_response_id"]),
                           f"provider response ID missing at {order}", "strict_output_shape")
            checks.require(isinstance(attempt.get("latency_ms"), (int, float))
                           and attempt["latency_ms"] >= 0,
                           f"latency invalid at {order}", "attempt_order")
            raw = attempt.get("raw_response_content")
            parsed = attempt.get("parsed_output")
            validation = attempt.get("strict_validation_status")
            checks.require(validation in {"VALID", "INVALID_JSON_OR_STRICT_SCHEMA"},
                           f"strict status invalid at {order}", "retry_compliance")
            if validation == "INVALID_JSON_OR_STRICT_SCHEMA":
                invalid_json_or_schema_count += 1
                checks.require(attempt_number == 1 and len(group) == 2,
                               f"invalid response retry rule violated at {order}", "retry_compliance")
                checks.require(parsed is None, f"invalid response has parsed output at {order}", "retry_compliance")
            else:
                checks.require(isinstance(raw, str), f"raw content missing at {order}", "strict_output_shape")
                checks.require(isinstance(parsed, dict) and set(parsed) == {"answer_text"},
                               f"parsed output shape mismatch at {order}", "strict_output_shape")
                answer = parsed.get("answer_text")
                checks.require(isinstance(answer, str) and bool(answer.strip()),
                               f"answer text empty at {order}", "strict_output_shape")
                checks.require(json.loads(raw) == parsed,
                               f"raw and parsed output differ at {order}", "strict_output_shape")
            for key in usage_sums:
                value = attempt.get(key)
                checks.require(isinstance(value, int) and value >= 0,
                               f"usage value invalid at {order}: {key}", "usage_arithmetic")
                usage_sums[key] += value
            checks.require(attempt["total_tokens"] == attempt["prompt_tokens"] + attempt["completion_tokens"],
                           f"attempt usage arithmetic invalid at {order}", "usage_arithmetic")
            checks.require(attempt["cached_input_tokens"] <= attempt["prompt_tokens"],
                           f"cached tokens exceed prompt tokens at {order}", "usage_arithmetic")
        if len(group) == 2:
            checks.require(group[0]["provider_payload_sha256"] == group[1]["provider_payload_sha256"],
                           f"retry payload is not byte-identical at {order}", "retry_compliance")
            checks.require(group[0]["strict_validation_status"] == "INVALID_JSON_OR_STRICT_SCHEMA"
                           and group[1]["strict_validation_status"] == "VALID",
                           f"retry sequence invalid at {order}", "retry_compliance")

        terminal = terminals[order - 1]
        checks.require(set(terminal) == TERMINAL_FIELDS,
                       f"terminal field set mismatch at {order}", "terminal_uniqueness")
        checks.require(terminal.get("logical_order") == order,
                       f"terminal order mismatch at {order}", "terminal_uniqueness")
        for key in ("logical_generation_request_id", "response_blind_id", "provider_payload_sha256"):
            checks.require(terminal.get(key) == manifest.get(key),
                           f"terminal binding mismatch at {order}: {key}", "terminal_uniqueness")
        checks.require(terminal.get("terminal_status") == "VALID_RESPONSE",
                       f"terminal status mismatch at {order}", "execution_complete")
        checks.require(terminal.get("physical_attempts") == len(group),
                       f"terminal physical-attempt count mismatch at {order}", "retry_compliance")
        checks.require(terminal.get("requested_model") == EXPECTED_MODEL
                       and terminal.get("returned_model") == EXPECTED_MODEL,
                       f"terminal model mismatch at {order}", "returned_model")
        checks.require(terminal.get("finish_reason") == "stop",
                       f"terminal finish reason mismatch at {order}", "strict_output_shape")
        parsed = terminal.get("parsed_output")
        raw = terminal.get("raw_response_content")
        checks.require(isinstance(parsed, dict) and set(parsed) == {"answer_text"},
                       f"terminal parsed output shape mismatch at {order}", "strict_output_shape")
        answer = parsed.get("answer_text")
        checks.require(isinstance(answer, str) and bool(answer.strip()),
                       f"terminal answer empty at {order}", "strict_output_shape")
        checks.require(isinstance(raw, str) and json.loads(raw) == parsed,
                       f"terminal raw/parsed mismatch at {order}", "strict_output_shape")
        for key in ("provider_response_id", "returned_model", "raw_response_content", "parsed_output",
                    "prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens"):
            checks.require(terminal.get(key) == group[-1].get(key),
                           f"terminal differs from final attempt at {order}: {key}", "terminal_uniqueness")
        terminal_logical_ids.append(terminal["logical_generation_request_id"])
        terminal_blind_ids.append(terminal["response_blind_id"])
        answer_hash = sha256_bytes(answer.encode("utf-8"))
        answer_hashes.append({
            "logical_order": order,
            "logical_generation_request_id": terminal["logical_generation_request_id"],
            "response_blind_id": terminal["response_blind_id"],
            "answer_text_sha256": answer_hash,
        })
        direct_answer_set.append({
            "logical_order": order,
            "logical_generation_request_id": terminal["logical_generation_request_id"],
            "response_blind_id": terminal["response_blind_id"],
            "answer_text": answer,
        })

    checks.require(len(set(terminal_logical_ids)) == EXPECTED_REQUEST_COUNT,
                   "terminal logical IDs are not unique", "terminal_uniqueness")
    checks.require(len(set(terminal_blind_ids)) == EXPECTED_REQUEST_COUNT,
                   "terminal blind IDs are not unique", "terminal_uniqueness")
    checks.require(terminal_logical_ids == logical_ids,
                   "terminal logical-ID order differs from manifest", "terminal_uniqueness")
    checks.require(terminal_blind_ids == blind_ids,
                   "terminal blind-ID order differs from manifest", "terminal_uniqueness")
    checks.require(len(attempts) <= EXPECTED_MAXIMUM_ATTEMPTS,
                   "physical-attempt ceiling exceeded", "retry_compliance")
    checks.require(retry_count == 0 and invalid_json_or_schema_count == 0,
                   "unexpected retry or invalid output observed", "retry_compliance")

    terminal_journal_sha256 = sha256_file(output_dir / "GENERATION_TERMINAL_JOURNAL.jsonl")
    answer_set_sha256 = sha256_bytes(canonical_bytes(direct_answer_set))
    checks.require(terminal_journal_sha256 == EXPECTED_TERMINAL_JOURNAL_SHA256,
                   "terminal journal hash mismatch", "answer_hashes")
    checks.require(answer_set_sha256 == EXPECTED_ANSWER_SET_SHA256,
                   "answer-set hash mismatch", "answer_hashes")
    checks.require(len(answer_hashes) == EXPECTED_REQUEST_COUNT
                   and all(re.fullmatch(r"[0-9a-f]{64}", row["answer_text_sha256"])
                           for row in answer_hashes),
                   "answer hash population invalid", "answer_hashes")

    usage = read_json(output_dir / "GENERATION_USAGE_AND_COST.json")
    for key, value in usage_sums.items():
        checks.require(usage.get(key) == value,
                       f"aggregate usage mismatch: {key}", "usage_arithmetic")
    checks.require(usage_sums == {
        "prompt_tokens": 40547,
        "cached_input_tokens": 0,
        "completion_tokens": 11302,
        "total_tokens": 51849,
    }, "frozen usage totals mismatch", "usage_arithmetic")
    checks.require(usage.get("usage_arithmetic_valid") is True,
                   "usage arithmetic receipt is false", "usage_arithmetic")
    checks.require(usage.get("responses_without_cached_token_detail") == 0,
                   "cached-token detail is incomplete", "usage_arithmetic")
    checks.require(usage.get("provider_calls_observed") == len(attempts),
                   "provider-call count mismatch", "usage_arithmetic")
    checks.require(usage.get("judge_calls") == 0 and usage.get("cost_amount") is None,
                   "runner usage contains Judge calls or asserted billing", "usage_arithmetic")

    million = Decimal(1_000_000)
    standard_cost = (
        Decimal(usage_sums["prompt_tokens"]) * Decimal("0.15")
        + Decimal(usage_sums["completion_tokens"]) * Decimal("0.60")
    ) / million
    cached_aware_cost = (
        Decimal(usage_sums["prompt_tokens"] - usage_sums["cached_input_tokens"])
        * Decimal("0.15")
        + Decimal(usage_sums["cached_input_tokens"]) * Decimal("0.075")
        + Decimal(usage_sums["completion_tokens"]) * Decimal("0.60")
    ) / million
    checks.require(standard_cost == Decimal("0.01286325"),
                   "standard estimate mismatch", "cost_estimates")
    checks.require(cached_aware_cost == Decimal("0.01286325"),
                   "cached-aware estimate mismatch", "cost_estimates")

    for record_index, record in enumerate([*attempts, *terminals], 1):
        for key in walk_keys(record):
            checks.require(field_tokens(key).isdisjoint(FORBIDDEN_OUTPUT_FIELD_TOKENS),
                           f"prohibited output field at record {record_index}: {key}",
                           "forbidden_fields_and_secrets")
    scan_paths = [authorization_path, *sorted(output_dir.iterdir()),
                  root / "generation_execution_source_manifest_v1.json",
                  root / "generation_execution_audit_v1.json",
                  root / "C4_REAL_GENERATION_SHARD_REPORT.md",
                  root / "STATUS.md",
                  root / "validate_generation_shard_v1.py",
                  root / "test_generation_shard_v1.py",
                  root / "REVIEW_MANIFEST.json"]
    for path in scan_paths:
        data = path.read_bytes()
        for pattern in SECRET_PATTERNS:
            checks.require(pattern.search(data) is None,
                           f"secret-like material detected in {path.name}",
                           "forbidden_fields_and_secrets")
    checks.require(not any(path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}
                           for path in root.rglob("*")),
                   "bytecode residue present", "forbidden_fields_and_secrets")

    source_manifest_path = root / "generation_execution_source_manifest_v1.json"
    source_manifest = read_json(source_manifest_path)
    checks.require(source_manifest.get("schema_version") == "c4-real-generation-source-manifest-v1",
                   "source manifest schema mismatch", "support_artifacts")
    checks.require(source_manifest.get("shard") == "A"
                   and source_manifest.get("authorization_id") == EXPECTED_AUTHORIZATION_ID,
                   "source manifest identity mismatch", "support_artifacts")
    checks.require(source_manifest.get("starting_git") == {
        "working_directory": EXPECTED_WORKING_DIRECTORY,
        "branch": EXPECTED_BRANCH,
        "head": EXPECTED_STARTING_HEAD,
    }, "source manifest Git binding mismatch", "support_artifacts")
    package_source = source_manifest.get("authoritative_package")
    checks.require(isinstance(package_source, dict)
                   and package_source.get("path") == str(PACKAGE_ZIP)
                   and package_source.get("sha256") == EXPECTED_PACKAGE_SHA256
                   and package_source.get("package_id") == EXPECTED_PACKAGE_ID
                   and package_source.get("member_sha256") == EXPECTED_PACKAGE_MEMBER_HASHES,
                   "source manifest package binding mismatch", "support_artifacts")
    auth_source = source_manifest.get("authorization_record")
    checks.require(auth_source == {
        "path": "generation_execution_authorization_v1.json",
        "sha256": EXPECTED_AUTHORIZATION_SHA256,
    }, "source manifest authorization binding mismatch", "support_artifacts")
    output_source = source_manifest.get("execution_output")
    checks.require(output_source == {
        "path": "execution_output_v1",
        "file_sha256": EXPECTED_OUTPUT_HASHES,
    }, "source manifest output hashes mismatch", "support_artifacts")

    audit_path = root / "generation_execution_audit_v1.json"
    audit = read_json(audit_path)
    checks.require(audit.get("schema_version") == "c4-real-generation-mechanical-audit-v1"
                   and audit.get("status") == "PASS_COMPLETE",
                   "mechanical audit status mismatch", "support_artifacts")
    checks.require(audit.get("source_manifest_sha256") == sha256_file(source_manifest_path),
                   "mechanical audit source-manifest hash mismatch", "support_artifacts")
    checks.require(audit.get("authorization_record_sha256") == EXPECTED_AUTHORIZATION_SHA256,
                   "mechanical audit authorization hash mismatch", "support_artifacts")
    execution_audit = audit.get("execution")
    checks.require(isinstance(execution_audit, dict), "execution audit missing", "support_artifacts")
    for key, value in {
        "logical_request_count": EXPECTED_REQUEST_COUNT,
        "physical_attempt_count": EXPECTED_REQUEST_COUNT,
        "retry_count": 0,
        "valid_response_count": EXPECTED_REQUEST_COUNT,
        "incomplete_logical_request_count": 0,
        "unattempted_logical_request_count": 0,
        "maximum_physical_attempts": EXPECTED_MAXIMUM_ATTEMPTS,
        "terminal_status": "VALID_RESPONSE_ONLY",
        "returned_model": EXPECTED_MODEL,
    }.items():
        checks.require(execution_audit.get(key) == value,
                       f"mechanical audit execution mismatch: {key}", "support_artifacts")
    checks.require(audit.get("answer_text_sha256_values") == answer_hashes,
                   "mechanical audit answer hashes mismatch", "answer_hashes")
    hashes_audit = audit.get("hashes")
    checks.require(isinstance(hashes_audit, dict)
                   and hashes_audit.get("terminal_journal_sha256") == terminal_journal_sha256
                   and hashes_audit.get("answer_set_sha256") == answer_set_sha256,
                   "mechanical audit aggregate hashes mismatch", "answer_hashes")
    usage_audit = audit.get("usage_and_cost")
    checks.require(isinstance(usage_audit, dict)
                   and usage_audit.get("prompt_tokens") == usage_sums["prompt_tokens"]
                   and usage_audit.get("cached_input_tokens") == usage_sums["cached_input_tokens"]
                   and usage_audit.get("completion_tokens") == usage_sums["completion_tokens"]
                   and usage_audit.get("total_tokens") == usage_sums["total_tokens"]
                   and usage_audit.get("standard_non_cached_input_estimate_usd") == str(standard_cost)
                   and usage_audit.get("cached_input_aware_estimate_usd") == str(cached_aware_cost)
                   and usage_audit.get("exact_billed_amount_claimed") is False,
                   "mechanical audit usage or cost mismatch", "cost_estimates")
    error_counts = audit.get("error_counts")
    checks.require(error_counts == {
        "invalid_json": 0,
        "model_mismatch": 0,
        "provider_or_runtime": 0,
        "strict_schema_validation": 0,
        "unresolved": 0,
    }, "mechanical audit error counts mismatch", "execution_complete")
    prohibited = audit.get("prohibited_operations")
    checks.require(prohibited == {
        "human_rating_calls": 0,
        "judge_calls": 0,
        "memory_writes": 0,
        "planner_recomputations": 0,
        "rag_recomputations": 0,
        "response_quality_scoring_calls": 0,
        "route_scoring_calls": 0,
        "rq2_calls": 0,
        "streamlit_launches": 0,
    }, "prohibited-operation counts mismatch", "forbidden_fields_and_secrets")

    review_manifest = read_json(root / "REVIEW_MANIFEST.json")
    checks.require(review_manifest.get("schema_version") == "c4-real-generation-review-manifest-v1"
                   and review_manifest.get("shard") == "A"
                   and review_manifest.get("status") == "COMPLETE",
                   "review manifest identity mismatch", "support_artifacts")
    review_hashes = review_manifest.get("member_sha256_excluding_self")
    checks.require(isinstance(review_hashes, dict), "review member hashes missing", "support_artifacts")
    expected_review_members = {
        "C4_REAL_GENERATION_SHARD_REPORT.md",
        "STATUS.md",
        "generation_execution_audit_v1.json",
        "generation_execution_authorization_v1.json",
        "generation_execution_source_manifest_v1.json",
        "test_generation_shard_v1.py",
        "validate_generation_shard_v1.py",
        *(f"execution_output_v1/{name}" for name in OUTPUT_FILES),
    }
    checks.require(set(review_hashes) == expected_review_members,
                   "review member allowlist mismatch", "support_artifacts")
    for relative, expected in review_hashes.items():
        checks.require(sha256_file(root / relative) == expected,
                       f"review member hash mismatch: {relative}", "support_artifacts")

    for script_name in ("validate_generation_shard_v1.py", "test_generation_shard_v1.py"):
        imports = imported_roots(root / script_name)
        checks.require(imports.isdisjoint(NETWORK_IMPORT_ROOTS),
                       f"network-capable import in {script_name}", "integration_compatibility_and_no_network")
    checks.require(all(set(row) == TERMINAL_FIELDS for row in terminals),
                   "terminal schema is not integration stable", "integration_compatibility_and_no_network")
    checks.require(all(row["logical_order"] == index for index, row in enumerate(terminals, 1)),
                   "terminal sequence is not integration stable", "integration_compatibility_and_no_network")
    checks.require(all(set(row["parsed_output"]) == {"answer_text"} for row in terminals),
                   "answer projection is not integration stable", "integration_compatibility_and_no_network")

    return {
        "answer_set_sha256": answer_set_sha256,
        "attempt_count": len(attempts),
        "cached_input_aware_estimate_usd": str(cached_aware_cost),
        "check_count": checks.count,
        "error_count": len(errors),
        "groups": dict(sorted(checks.groups.items())),
        "logical_request_count": len(manifest_rows),
        "network_calls": 0,
        "retry_count": retry_count,
        "shard": "A",
        "standard_non_cached_input_estimate_usd": str(standard_cost),
        "status": "PASS",
        "terminal_journal_sha256": terminal_journal_sha256,
        "valid_response_count": len(terminals),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--package-zip", type=Path, default=PACKAGE_ZIP)
    args = parser.parse_args()
    try:
        result = validate(args.root, args.package_zip)
    except Exception as error:
        print(json.dumps({
            "error_type": type(error).__name__,
            "message": str(error),
            "network_calls": 0,
            "status": "FAIL",
        }, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
