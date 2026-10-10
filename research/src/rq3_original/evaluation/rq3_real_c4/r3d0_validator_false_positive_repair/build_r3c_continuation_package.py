#!/usr/bin/env python3
"""Build the dormant, exact 43-request Shard-C R3C1 continuation package."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping
import zipfile


sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
RQ3 = HERE.parent
G2D0 = RQ3 / "g2d0_response_format_repair"
SOURCE_PACKAGE = Path(
    "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_EXECUTION_PACKAGE_R3_2026-09-01.zip"
)
OUTPUT_PACKAGE = Path(
    "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_CONTINUATION_EXECUTION_PACKAGE_R3C1_2026-09-02.zip"
)
SOURCE_PACKAGE_SHA256 = "16215b04bb875ec8b9b9627df7fb018eff14edf46f5a294049f0dd8442952699"
SOURCE_MANIFEST_SHA256 = "2bc12fbdf114cda1f52f3438820e2ec706bf60e1c8f0965c4ce610d9853f7ea1"
CONTINUATION_MANIFEST_SHA256 = (
    "1b14542082db9b19a20cadbb1469a19de7b194181fc0f7ad949b39c95755c2d2"
)
PROMPT_SHA256 = "c72c9982899902221d1da6d67724c2058547b0641a285a7c28d9bafd12ec63cb"
SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"
SOURCE_CONFIGURATION_SHA256 = (
    "8a4a4a07137336d058645820bdd9d32091afb4df3513ec6324d380015454b138"
)
SOURCE_RUNNER_SHA256 = "679e1412ca2ed31daa02aa2bec8be81a7bc498447636820bd658eab963707a13"
PACKAGE_ID = "C4_REAL_GENERATION_SHARD_C_CONTINUATION_R3C1_20260902"
SHARD = "C_CONTINUATION"
AUTHORIZATION_VALUE = "AUTHORIZED_C4_REAL_SHARD_C_CONTINUATION_R3C1"
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pretty_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _load_validator_module() -> Any:
    path = HERE / "continuation_package_validator_v1.py"
    spec = importlib.util.spec_from_file_location("r3c1_package_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import continuation package validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_members() -> dict[str, bytes]:
    if sha256_file(SOURCE_PACKAGE) != SOURCE_PACKAGE_SHA256:
        raise ValueError("original Shard-C R3 package identity mismatch")
    with zipfile.ZipFile(SOURCE_PACKAGE) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    if sha256_bytes(members["BLINDED_REQUESTS.jsonl"]) != SOURCE_MANIFEST_SHA256:
        raise ValueError("original Shard-C blinded manifest identity mismatch")
    if sha256_bytes(members["GENERATION_PROMPT.txt"]) != PROMPT_SHA256:
        raise ValueError("original generation Prompt identity mismatch")
    if sha256_bytes(members["GENERATION_SCHEMA.json"]) != SCHEMA_SHA256:
        raise ValueError("original generation schema identity mismatch")
    if sha256_bytes(members["GENERATION_CONFIGURATION.json"]) != SOURCE_CONFIGURATION_SHA256:
        raise ValueError("original generation configuration identity mismatch")
    if sha256_bytes(members["generation_execution_runner_v3.py"]) != SOURCE_RUNNER_SHA256:
        raise ValueError("original Runner V3 identity mismatch")
    return members


def _continuation_manifest(source_bytes: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    lines = source_bytes.splitlines(keepends=True)
    if len(lines) != 47 or any(not line.strip() for line in lines):
        raise ValueError("original manifest must contain exactly 47 nonblank rows")
    continuation = b"".join(lines[4:])
    if sha256_bytes(continuation) != CONTINUATION_MANIFEST_SHA256:
        raise ValueError("continuation manifest differs from frozen orders 5 through 47")
    tracked = (HERE / "c4_real_r3c_remaining_request_manifest_v1.jsonl").read_bytes()
    if continuation != tracked:
        raise ValueError("tracked continuation manifest is not byte-identical to source subset")
    rows = [json.loads(line) for line in lines[4:]]
    if len(rows) != 43:
        raise ValueError("continuation request population mismatch")
    for row in rows:
        if sha256_bytes(canonical_bytes(row["provider_payload"])) != row["provider_payload_sha256"]:
            raise ValueError("Provider payload canonical byte identity mismatch")
    return continuation, rows


def _configuration(source: bytes, contract_hash: str, validator_hash: str) -> tuple[bytes, Mapping[str, Any]]:
    original = json.loads(source)
    if pretty_json(original) != source:
        raise ValueError("source generation configuration serialization is unexpected")
    continuation = dict(original)
    continuation["student_facing_format_contract_sha256"] = contract_hash
    continuation["student_facing_validator_sha256"] = validator_hash
    differences = {
        key: {"source": original.get(key), "continuation": continuation.get(key)}
        for key in sorted(set(original) | set(continuation))
        if original.get(key) != continuation.get(key)
    }
    if set(differences) != {
        "student_facing_format_contract_sha256",
        "student_facing_validator_sha256",
    }:
        raise ValueError("generation configuration changed beyond V2 binding")
    return pretty_json(continuation), differences


def _execution_contract(source: bytes, rows: list[dict[str, Any]]) -> bytes:
    contract = json.loads(source)
    contract.update(
        {
            "schema_version": "c4-real-generation-execution-contract-v3-1",
            "package_id": PACKAGE_ID,
            "shard": SHARD,
            "source_shard": "C",
            "source_original_logical_order_range": [5, 47],
            "request_count": 43,
            "maximum_physical_attempts": 86,
            "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in rows),
            "authorization_environment_value": AUTHORIZATION_VALUE,
            "runner_version": "V3.1",
            "student_facing_validator_version": "V2",
            "student_facing_format_contract_version": "V2",
            "fresh_execution_over_previously_unattempted_requests": True,
            "original_execution_output_resume": False,
            "original_shard_c_logical_orders_1_through_4_excluded": True,
            "provider_calls_during_package_preparation": 0,
            "response_generation_during_package_preparation": 0,
            "judge_calls": 0,
            "scoring_calls": 0,
            "status": "PREPARED_NOT_AUTHORIZED",
        }
    )
    return pretty_json(contract)


def _runner_v3_1(
    source: bytes,
    configuration_hash: str,
    contract_hash: str,
    validator_hash: str,
) -> bytes:
    text = source.decode("utf-8")
    replacements = {
        "c4_real_student_facing_response_validator_v1": "c4_real_student_facing_response_validator_v2",
        "STUDENT_FACING_FORMAT_CONTRACT.json": "STUDENT_FACING_FORMAT_CONTRACT_V2.json",
        "generation_execution_runner_v3.py": "generation_execution_runner_v3_1.py",
        'EXPECTED_CONFIGURATION_SHA256 = "8a4a4a07137336d058645820bdd9d32091afb4df3513ec6324d380015454b138"': f'EXPECTED_CONFIGURATION_SHA256 = "{configuration_hash}"',
        'EXPECTED_FORMAT_CONTRACT_SHA256 = "e68165bc78294beb490ea37ae45752ce2a41ee4232ae5127cd9d2e7ee6336319"': f'EXPECTED_FORMAT_CONTRACT_SHA256 = "{contract_hash}"',
        'EXPECTED_VALIDATOR_SHA256 = "5b098ff2e8368a7830938ae83ea4ea5cbdcdf71fcf61b674c579118c4742fbcc"': f'EXPECTED_VALIDATOR_SHA256 = "{validator_hash}"',
        "AUTHORIZED_C4_REAL_RESPONSE_REGENERATION_R3": AUTHORIZATION_VALUE,
        "one explicitly authorized C4 REAL R3 shard": "the explicitly authorized C4 REAL Shard-C R3C1 continuation",
        "exact R3 response-regeneration environment authorization": "exact R3C1 continuation environment authorization",
        "exact R3 environment value": "exact R3C1 continuation environment value",
    }
    for old, new in replacements.items():
        if old not in text:
            raise ValueError(f"Runner V3 transformation marker missing: {old}")
        text = text.replace(old, new)
    if "validator_v1" in text or "STUDENT_FACING_FORMAT_CONTRACT.json" in text:
        raise ValueError("Runner V3.1 retains a V1 validator/contract binding")
    transformed = text.encode("utf-8")
    (HERE / "generation_execution_runner_v3_1.py").write_bytes(transformed)
    return transformed


def _readme(estimated_input_tokens: int) -> bytes:
    hard_break = "  "
    return f"""# C4 REAL Shard-C continuation execution package R3C1

Package ID: `{PACKAGE_ID}`{hard_break}
Shard: `{SHARD}`{hard_break}
Frozen requests: `43` (original Shard-C logical orders `5` through `47`){hard_break}
Maximum physical attempts: `86`{hard_break}
Estimated input tokens: `{estimated_input_tokens}`

This package is prepared but **not authorized for execution**. Package possession, an API key, or the runner is not authority. A later direct authorization record must bind this exact ZIP and blinded-manifest SHA-256, and the exact environment value must be:

`C4_REAL_RESPONSE_GENERATION_AUTHORIZATION={AUTHORIZATION_VALUE}`

Use `/opt/anaconda3/bin/python3` version `3.13.5` with OpenAI SDK `1.109.1`. Runner V3.1 performs strict outer-schema validation followed by blind mechanical Validator V2. It permits at most one byte-identical retry after `INVALID_JSON`, `STRICT_SCHEMA_VALIDATION_FAILED`, or genuine `NON_STUDENT_FACING_FORMAT`; it stops after a second invalid response or any non-retryable error. Output-directory reuse and automatic resume are prohibited.

Package preparation and embedded tests make zero real Provider, generation, Judge, scoring, or human-rating calls. The embedded tests use mocked transport only. This package contains no existing responses, prior journals, restricted mappings, HMAC key, credentials, scenario/mode/route/Gold identity, course corpus, or Memory database.
""".encode("utf-8")


def _package_source_hashes(package_root: Path, estimated_input_tokens: int) -> bytes:
    member_hashes = {
        name: sha256_file(package_root / name)
        for name in sorted(ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"})
    }
    value = {
        "schema_version": "c4-real-generation-package-source-hashes-r3c1-v1",
        "package_id": PACKAGE_ID,
        "shard": SHARD,
        "request_count": 43,
        "maximum_physical_attempts": 86,
        "source_original_shard_c_logical_order_range": [5, 47],
        "source_original_shard_c_package_sha256": SOURCE_PACKAGE_SHA256,
        "source_original_shard_c_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "blinded_manifest_sha256": CONTINUATION_MANIFEST_SHA256,
        "generation_prompt_sha256": PROMPT_SHA256,
        "generation_schema_sha256": SCHEMA_SHA256,
        "estimated_input_tokens": estimated_input_tokens,
        "member_sha256_excluding_self": member_hashes,
        "api_key_included": False,
        "existing_execution_results_included": False,
        "prior_attempt_or_terminal_journals_included": False,
        "restricted_mapping_included": False,
        "hmac_key_included": False,
        "scenario_mode_route_or_gold_identity_included": False,
        "course_corpus_included": False,
        "memory_database_included": False,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "human_rating_actions": 0,
    }
    return pretty_json(value)


def _write_zip(package_root: Path, output: Path) -> None:
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True
    ) as archive:
        for name in sorted(ALLOWED_FILES):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, (package_root / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _run_embedded_tests(package_root: Path) -> Mapping[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "test_package.py"],
        cwd=package_root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    match = re.search(r"Ran (\d+) tests?", completed.stdout)
    tests_run = int(match.group(1)) if match else 0
    if completed.returncode != 0 or tests_run != 11 or "OK" not in completed.stdout:
        raise RuntimeError(f"embedded mocked tests failed:\n{completed.stdout}")
    return {
        "status": "PASS",
        "tests_run": tests_run,
        "tests_passed": tests_run,
        "tests_failed": 0,
        "tests_errored": 0,
        "real_provider_network_calls": 0,
        "mock_transport_only": True,
    }


def build(output: Path, *, replace: bool) -> Mapping[str, Any]:
    if output.exists() and not replace:
        raise FileExistsError(f"refusing to overwrite existing continuation package: {output}")
    source = _source_members()
    manifest, rows = _continuation_manifest(source["BLINDED_REQUESTS.jsonl"])
    validator_bytes = (HERE / "c4_real_student_facing_response_validator_v2.py").read_bytes()
    contract_v2_bytes = (HERE / "c4_real_student_facing_response_format_contract_v2.json").read_bytes()
    validator_hash = sha256_bytes(validator_bytes)
    contract_v2_hash = sha256_bytes(contract_v2_bytes)
    configuration_bytes, configuration_differences = _configuration(
        source["GENERATION_CONFIGURATION.json"], contract_v2_hash, validator_hash
    )
    configuration_hash = sha256_bytes(configuration_bytes)
    runner_bytes = _runner_v3_1(
        source["generation_execution_runner_v3.py"],
        configuration_hash,
        contract_v2_hash,
        validator_hash,
    )
    execution_contract_bytes = _execution_contract(source["EXECUTION_CONTRACT.json"], rows)
    estimated_input_tokens = sum(row["estimated_input_tokens"] for row in rows)

    with tempfile.TemporaryDirectory(prefix="c4-real-r3c1-build-") as temporary_name:
        package_root = Path(temporary_name)
        members = {
            "README.md": _readme(estimated_input_tokens),
            "BLINDED_REQUESTS.jsonl": manifest,
            "GENERATION_PROMPT.txt": source["GENERATION_PROMPT.txt"],
            "GENERATION_SCHEMA.json": source["GENERATION_SCHEMA.json"],
            "GENERATION_CONFIGURATION.json": configuration_bytes,
            "STUDENT_FACING_FORMAT_CONTRACT_V2.json": contract_v2_bytes,
            "EXECUTION_CONTRACT.json": execution_contract_bytes,
            "generation_execution_runner_v3_1.py": runner_bytes,
            "c4_real_student_facing_response_validator_v2.py": validator_bytes,
            "validate_package.py": (HERE / "continuation_package_validator_v1.py").read_bytes(),
            "test_package.py": (HERE / "continuation_package_offline_tests_v1.py").read_bytes(),
        }
        for name, content in members.items():
            (package_root / name).write_bytes(content)
        (package_root / "PACKAGE_SOURCE_HASHES.json").write_bytes(
            _package_source_hashes(package_root, estimated_input_tokens)
        )
        if {path.name for path in package_root.iterdir()} != ALLOWED_FILES:
            raise ValueError("continuation package allowlist construction mismatch")
        validator_module = _load_validator_module()
        validation = dict(validator_module.validate(package_root))
        embedded_tests = _run_embedded_tests(package_root)
        temporary_output = output.with_name(f".{output.name}.building-{os.getpid()}")
        if temporary_output.exists():
            temporary_output.unlink()
        _write_zip(package_root, temporary_output)
        zip_validation = dict(validator_module.validate_zip(temporary_output))
        if output.exists():
            output.unlink()
        os.replace(temporary_output, output)
        member_hashes = {
            name: sha256_file(package_root / name) for name in sorted(ALLOWED_FILES)
        }
    audit = {
        "schema_version": "c4-real-r3c1-continuation-package-freeze-audit-v1",
        "status": "PASS_PREPARED_NOT_EXECUTED",
        "package_id": PACKAGE_ID,
        "shard": SHARD,
        "package_path": str(output),
        "package_sha256": sha256_file(output),
        "package_member_count": len(ALLOWED_FILES),
        "package_member_allowlist": sorted(ALLOWED_FILES),
        "package_member_sha256": member_hashes,
        "request_count": 43,
        "maximum_physical_attempts": 86,
        "source_original_logical_order_range": [5, 47],
        "source_original_package_sha256": SOURCE_PACKAGE_SHA256,
        "source_original_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "continuation_manifest_sha256": CONTINUATION_MANIFEST_SHA256,
        "opaque_ids_regenerated": False,
        "provider_payload_byte_identity": "PASS_ALL_43",
        "generation_prompt_identity": "PASS_BYTE_IDENTICAL",
        "generation_schema_identity": "PASS_BYTE_IDENTICAL",
        "source_generation_configuration_sha256": SOURCE_CONFIGURATION_SHA256,
        "continuation_generation_configuration_sha256": configuration_hash,
        "generation_configuration_differences": configuration_differences,
        "format_contract_v2_sha256": contract_v2_hash,
        "validator_v2_sha256": validator_hash,
        "runner_v3_1_sha256": sha256_bytes(runner_bytes),
        "authorization_environment_variable": "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION",
        "authorization_environment_value": AUTHORIZATION_VALUE,
        "validation": validation,
        "zip_validation": zip_validation,
        "embedded_mocked_tests": embedded_tests,
        "continuation_executed": False,
        "real_provider_network_calls": 0,
        "response_generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "human_rating_actions": 0,
        "condition_unblinding_actions": 0,
    }
    (HERE / "c4_real_r3c_continuation_package_freeze_audit_v1.json").write_bytes(
        pretty_json(audit)
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PACKAGE)
    parser.add_argument("--replace-owned-output", action="store_true")
    args = parser.parse_args()
    audit = build(args.output.resolve(), replace=args.replace_owned_output)
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
