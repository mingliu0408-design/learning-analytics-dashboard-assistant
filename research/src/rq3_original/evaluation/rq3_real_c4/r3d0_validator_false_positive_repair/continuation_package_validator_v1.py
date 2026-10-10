#!/usr/bin/env python3
"""Strict offline validator for the dormant Shard-C R3C1 continuation package."""

from __future__ import annotations

import hashlib
import importlib.util
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
        "STUDENT_FACING_FORMAT_CONTRACT_V2.json",
        "EXECUTION_CONTRACT.json",
        "generation_execution_runner_v3_1.py",
        "c4_real_student_facing_response_validator_v2.py",
        "validate_package.py",
        "test_package.py",
        "PACKAGE_SOURCE_HASHES.json",
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
PROMPT_SHA256 = "c72c9982899902221d1da6d67724c2058547b0641a285a7c28d9bafd12ec63cb"
SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
CONTINUATION_MANIFEST_SHA256 = (
    "1b14542082db9b19a20cadbb1469a19de7b194181fc0f7ad949b39c95755c2d2"
)
ORIGINAL_C_PACKAGE_SHA256 = (
    "16215b04bb875ec8b9b9627df7fb018eff14edf46f5a294049f0dd8442952699"
)
ORIGINAL_C_MANIFEST_SHA256 = (
    "2bc12fbdf114cda1f52f3438820e2ec706bf60e1c8f0965c4ce610d9853f7ea1"
)
PACKAGE_ID = "C4_REAL_GENERATION_SHARD_C_CONTINUATION_R3C1_20260902"
SHARD = "C_CONTINUATION"
MODEL = "gpt-4o-mini-2024-07-18"
AUTHORIZATION_GATE = "AUTHORIZED_C4_REAL_SHARD_C_CONTINUATION_R3C1"
_LOGICAL_ID = re.compile(r"^C4G3-[A-F0-9]{24}$")
_RESPONSE_ID = re.compile(r"^R3B3-[A-F0-9]{20}$")
_SECRET = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
    rb"OPENAI_API_KEY\s*[=:]\s*[^\s,;]+)",
    re.IGNORECASE,
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_validator(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("r3c1_embedded_validator_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import embedded Validator V2")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_payload(row: Mapping[str, Any], prompt: str, schema: Mapping[str, Any]) -> None:
    if set(row) != REQUEST_FIELDS or row.get("schema_version") != "c4-real-blinded-generation-request-v3":
        raise ValueError("blinded request V3 field set or schema mismatch")
    if not _LOGICAL_ID.fullmatch(str(row.get("logical_generation_request_id", ""))):
        raise ValueError("logical request ID is not opaque V3")
    if not _RESPONSE_ID.fullmatch(str(row.get("response_blind_id", ""))):
        raise ValueError("response blind ID is not opaque V3")
    if not isinstance(row.get("estimated_input_tokens"), int) or row["estimated_input_tokens"] <= 0:
        raise ValueError("estimated input tokens must be positive")
    payload = row.get("provider_payload")
    if not isinstance(payload, Mapping) or set(payload) != {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "stream",
        "response_format",
    }:
        raise ValueError("Provider payload transport fields changed")
    if hashlib.sha256(canonical_bytes(payload)).hexdigest() != row.get("provider_payload_sha256"):
        raise ValueError("Provider payload canonical byte hash mismatch")
    if (
        payload.get("model") != MODEL
        or payload.get("temperature") != 0
        or payload.get("max_tokens") != 512
        or payload.get("stream") is not False
        or "tools" in payload
    ):
        raise ValueError("Provider transport configuration changed")
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
        raise ValueError("Provider message construction changed")
    user_message = messages[1]["content"]
    if not user_message.startswith("CURRENT LAD PAGE\n") or "\n\nSTUDENT REQUEST\n" not in user_message:
        raise ValueError("plain-text V3 request sections are absent")
    try:
        raw_user = json.loads(user_message)
    except json.JSONDecodeError:
        raw_user = None
    if isinstance(raw_user, (dict, list)):
        raise ValueError("Provider user message is a raw container")
    expected_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "c4_real_generation_response_v2_provider_compatible",
            "strict": True,
            "schema": dict(schema),
        },
    }
    if payload.get("response_format") != expected_format:
        raise ValueError("outer Provider response schema changed")


def _validate_v2(root: Path) -> None:
    validator = _load_validator(root / "c4_real_student_facing_response_validator_v2.py")
    valid = validator.VALID_STUDENT_FACING_RESPONSE
    accepted = (
        "Use your dashboard evidence:",
        "Review your activity evidence:",
        "Use the course evidence:",
        "The evidence:",
        "## Suggested focus:\n\n**Debate Activity:** Review one post.",
        "**Lecture Video Activity:** Rewatch Week 2.",
    )
    rejected = (
        "",
        "{}",
        "[]",
        '{"answer_text":"raw"}',
        "{'action_steps': ['Review']}",
        "action_steps:\n- Review Week 2",
        "recommended_action: Review Week 2",
        "```json\n{\"answer_text\":\"raw\"}\n```",
        "<response>raw</response>",
    )
    if any(validator.validate_answer_text(value) != valid for value in accepted):
        raise ValueError("Validator V2 rejected an authorized prose/Markdown colon case")
    if any(validator.validate_answer_text(value) == valid for value in rejected):
        raise ValueError("Validator V2 accepted a required rejection case")


def _validate_runner(root: Path, configuration_sha256: str) -> None:
    source = (root / "generation_execution_runner_v3_1.py").read_text(encoding="utf-8")
    required = (
        "EXPECTED_PYTHON = (3, 13, 5)",
        'EXPECTED_PYTHON_PATH = "/opt/anaconda3/bin/python3"',
        'EXPECTED_OPENAI = "1.109.1"',
        'EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"',
        f'EXPECTED_CONFIGURATION_SHA256 = "{configuration_sha256}"',
        AUTHORIZATION_GATE,
        "OpenAI(max_retries=0)",
        "MAX_ATTEMPTS_PER_REQUEST = 2",
        "INVALID_JSON",
        "STRICT_SCHEMA_VALIDATION_FAILED",
        "NON_STUDENT_FACING_FORMAT",
        "client.chat.completions.create(**json.loads(payload_bytes))",
        "append_fsync(attempts_path, record)",
        "terminal_path,",
        "INCOMPLETE_AFTER_SECOND_INVALID_RESPONSE",
        "Refusing overwrite or automatic resume",
        "c4_real_student_facing_response_validator_v2",
        "STUDENT_FACING_FORMAT_CONTRACT_V2.json",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise ValueError(f"Runner V3.1 fail-closed markers missing: {missing}")
    outer_parse = source.find("parsed = json.loads(raw_content)")
    semantic_call = source.find("semantic_status = validate_answer_text(answer_text)")
    if min(outer_parse, semantic_call) < 0 or outer_parse >= semantic_call:
        raise ValueError("Validator V2 is not applied after strict outer parsing")
    receipt = source.find(
        'write_exclusive_json(\n        output_dir / "GENERATION_PREFLIGHT_RECEIPT.json"'
    )
    runtime = source.find("runtime_checker()", receipt)
    client = source.find("client_factory()", receipt)
    if min(receipt, runtime, client) < 0 or not receipt < runtime < client:
        raise ValueError("durable preflight is not written before runtime/client construction")


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
        raise ValueError("original generation Prompt changed")
    if sha256(root / "GENERATION_SCHEMA.json") != SCHEMA_SHA256:
        raise ValueError("original outer response schema changed")
    if sha256(root / "BLINDED_REQUESTS.jsonl") != CONTINUATION_MANIFEST_SHA256:
        raise ValueError("continuation request manifest is not the frozen 43-row subset")

    prompt = (root / "GENERATION_PROMPT.txt").read_text(encoding="utf-8")
    schema = json.loads((root / "GENERATION_SCHEMA.json").read_text(encoding="utf-8"))
    expected_schema = {
        "type": "object",
        "properties": {"answer_text": {"type": "string"}},
        "required": ["answer_text"],
        "additionalProperties": False,
    }
    if schema != expected_schema:
        raise ValueError("outer response schema content changed")
    configuration_path = root / "GENERATION_CONFIGURATION.json"
    config = json.loads(configuration_path.read_text(encoding="utf-8"))
    if (
        config.get("model") != MODEL
        or config.get("temperature") != 0
        or config.get("max_output_tokens") != 512
        or config.get("automatic_sdk_retries") != 0
        or config.get("streaming") is not False
        or config.get("tools") != "NONE"
        or config.get("generation_execution_authorised") is not False
        or config.get("response_generation_executed") is not False
        or config.get("semantic_validation_after_strict_outer_schema") is not True
        or config.get("provider_calls") != 0
        or config.get("judge_calls") != 0
        or config.get("scoring_calls") != 0
    ):
        raise ValueError("frozen generation configuration transport fields changed")
    if config.get("prompt_sha256") != PROMPT_SHA256 or config.get(
        "provider_transport_schema_sha256"
    ) != SCHEMA_SHA256:
        raise ValueError("generation Prompt/schema configuration binding changed")
    if config.get("student_facing_format_contract_sha256") != sha256(
        root / "STUDENT_FACING_FORMAT_CONTRACT_V2.json"
    ) or config.get("student_facing_validator_sha256") != sha256(
        root / "c4_real_student_facing_response_validator_v2.py"
    ):
        raise ValueError("configuration does not bind Format Contract/Validator V2")

    lines = (root / "BLINDED_REQUESTS.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    if len(rows) != 43 or len(lines) != 43:
        raise ValueError("continuation manifest must contain exactly 43 rows")
    for row in rows:
        _validate_payload(row, prompt, schema)
    logical_ids = [row["logical_generation_request_id"] for row in rows]
    response_ids = [row["response_blind_id"] for row in rows]
    if len(set(logical_ids)) != 43 or len(set(response_ids)) != 43:
        raise ValueError("continuation opaque IDs are not unique")
    if logical_ids != sorted(logical_ids):
        raise ValueError("continuation requests do not preserve deterministic source order")

    contract = json.loads((root / "EXECUTION_CONTRACT.json").read_text(encoding="utf-8"))
    if (
        contract.get("package_id") != PACKAGE_ID
        or contract.get("shard") != SHARD
        or contract.get("source_shard") != "C"
        or contract.get("source_original_logical_order_range") != [5, 47]
        or contract.get("request_count") != 43
        or contract.get("maximum_physical_attempts") != 86
        or contract.get("authorization_environment_variable")
        != "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION"
        or contract.get("authorization_environment_value") != AUTHORIZATION_GATE
        or contract.get("automatic_sdk_retries") != 0
        or contract.get("maximum_manual_retries_per_request") != 1
        or contract.get("identical_retry_payload") is not True
        or contract.get("automatic_resume") is not False
        or contract.get("stop_entire_shard_after_second_invalid_response") is not True
        or contract.get("stop_entire_shard_on_first_non_retryable_failure") is not True
        or contract.get("provider_calls_during_package_preparation") != 0
        or contract.get("response_generation_during_package_preparation") != 0
        or contract.get("judge_calls") != 0
        or contract.get("scoring_calls") != 0
        or contract.get("status") != "PREPARED_NOT_AUTHORIZED"
    ):
        raise ValueError("continuation execution contract mismatch")

    if (
        source_hashes.get("package_id") != PACKAGE_ID
        or source_hashes.get("shard") != SHARD
        or source_hashes.get("request_count") != 43
        or source_hashes.get("maximum_physical_attempts") != 86
        or source_hashes.get("blinded_manifest_sha256") != CONTINUATION_MANIFEST_SHA256
        or source_hashes.get("source_original_shard_c_package_sha256")
        != ORIGINAL_C_PACKAGE_SHA256
        or source_hashes.get("source_original_shard_c_manifest_sha256")
        != ORIGINAL_C_MANIFEST_SHA256
        or source_hashes.get("restricted_mapping_included") is not False
        or source_hashes.get("hmac_key_included") is not False
        or source_hashes.get("existing_execution_results_included") is not False
        or source_hashes.get("scenario_mode_route_or_gold_identity_included") is not False
        or source_hashes.get("provider_calls") != 0
        or source_hashes.get("generation_calls") != 0
        or source_hashes.get("judge_calls") != 0
        or source_hashes.get("scoring_calls") != 0
    ):
        raise ValueError("continuation package source binding mismatch")
    _validate_v2(root)
    _validate_runner(root, sha256(configuration_path))
    return {
        "status": "PASS",
        "package_id": PACKAGE_ID,
        "shard": SHARD,
        "request_count": 43,
        "maximum_physical_attempts": 86,
        "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in rows),
        "allowlisted_file_count": len(files),
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }


def validate_zip(path: Path) -> Mapping[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != ALLOWED_FILES:
            raise ValueError("ZIP member allowlist mismatch")
        if any(name.endswith("/") or Path(name).name != name for name in names):
            raise ValueError("ZIP contains a nested or directory member")
        with tempfile.TemporaryDirectory(prefix="c4-real-r3c1-validate-") as temporary:
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
