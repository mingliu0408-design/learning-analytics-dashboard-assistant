#!/usr/bin/env python3
"""Build and freeze three dormant, validated C4 REAL generation R2 packages.

This builder performs no provider, response-generation, Judge, or scoring call.
It refuses to overwrite any R2 deliverable.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Iterable, Mapping
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.generation_package_validator_v2 import (
    ALLOWED_FILES,
    validate,
    validate_zip,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_common import SOURCE_PATHS
from evaluation.rq3_real_c4.i1_route_integration.i1_r1_common import (
    BRANCH,
    GENERATION_CONFIGURATION_V2_SHA256,
    GENERATION_PROMPT_SHA256,
    GENERATION_SCHEMA_V2_SHA256,
    HERE,
    MODEL,
    NEW_PACKAGE_PATHS,
    OLD_PACKAGE_PATHS,
    OLD_PACKAGE_SHA256,
    ROOT,
    SCIENTIFIC_SHA256,
    STARTING_HEAD,
    V1_RESTRICTED_SHA256,
    V1_REQUEST_ARTIFACT_SHA256,
    assert_sha256,
    git,
    load_jsonl,
    sha256_file,
    write_json,
)


EXPECTED_PYTHON = Path("/opt/anaconda3/bin/python3")
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)
UNIQUE_MANIFEST = HERE / "c4_real_unique_generation_request_manifest_frozen_v2.jsonl"
PACKAGE_MANIFEST = HERE / "c4_real_generation_package_manifest_v2.json"
SHARD_EXPECTATIONS = {
    "A": {"request_count": 73, "estimated_input_tokens": 51821},
    "B": {"request_count": 62, "estimated_input_tokens": 51822},
    "C": {"request_count": 62, "estimated_input_tokens": 51752},
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        for row in rows
    )


def _runtime_identity() -> Mapping[str, Any]:
    program = (
        "import json, openai, sys; "
        "print(json.dumps({'python_version': '.'.join(map(str, sys.version_info[:3])), "
        "'openai_sdk_version': openai.__version__, 'executable': sys.executable}, sort_keys=True))"
    )
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [str(EXPECTED_PYTHON), "-c", program],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    identity = json.loads(completed.stdout)
    expected = {
        "executable": str(EXPECTED_PYTHON),
        "openai_sdk_version": "1.109.1",
        "python_version": "3.13.5",
    }
    if identity != expected:
        raise ValueError(f"future generation runtime identity mismatch: {identity}")
    return identity


def verify_frozen_state() -> None:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("R2 package builder must run from the repository root")
    if git("branch", "--show-current") != BRANCH:
        raise ValueError("R2 package builder branch mismatch")
    if git("rev-parse", "HEAD") != STARTING_HEAD:
        raise ValueError("R2 package builder starting HEAD mismatch")
    for name, expected in SCIENTIFIC_SHA256.items():
        assert_sha256(HERE / name, expected, name)
    for name, expected in V1_REQUEST_ARTIFACT_SHA256.items():
        assert_sha256(HERE / name, expected, name)
    for name, expected in V1_RESTRICTED_SHA256.items():
        assert_sha256(HERE / "restricted_internal" / name, expected, name)
    for shard, expected in OLD_PACKAGE_SHA256.items():
        assert_sha256(OLD_PACKAGE_PATHS[shard], expected, f"old R1 package {shard}")
    assert_sha256(SOURCE_PATHS["generation_prompt"], GENERATION_PROMPT_SHA256, "prompt")
    assert_sha256(
        HERE / "c4_real_generation_schema_v2_provider_compatible.json",
        GENERATION_SCHEMA_V2_SHA256,
        "generation schema",
    )
    assert_sha256(
        HERE / "c4_real_generation_configuration_frozen_v2.json",
        GENERATION_CONFIGURATION_V2_SHA256,
        "generation configuration",
    )
    existing = [str(path) for path in NEW_PACKAGE_PATHS.values() if path.exists()]
    if existing:
        raise FileExistsError("refusing to overwrite R2 package(s): " + ", ".join(existing))


def _read_unique_rows() -> list[dict[str, Any]]:
    rows = load_jsonl(UNIQUE_MANIFEST)
    if len(rows) != 197:
        raise ValueError("V2 unique request population changed")
    if Counter(str(row.get("shard_id")) for row in rows) != Counter(
        {shard: expected["request_count"] for shard, expected in SHARD_EXPECTATIONS.items()}
    ):
        raise ValueError("V2 shard distribution changed")
    if len({row["logical_generation_request_id"] for row in rows}) != len(rows):
        raise ValueError("V2 logical request IDs are not unique")
    if len({row["response_blind_id"] for row in rows}) != len(rows):
        raise ValueError("V2 response blind IDs are not unique")
    for row in rows:
        payload_bytes = json.dumps(
            row["provider_payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(payload_bytes).hexdigest() != row["provider_payload_sha256"]:
            raise ValueError("V2 unique-request payload hash mismatch")
    return rows


def _package_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "c4-real-blinded-generation-request-v2",
            "logical_generation_request_id": row["logical_generation_request_id"],
            "response_blind_id": row["response_blind_id"],
            "provider_payload_sha256": row["provider_payload_sha256"],
            "estimated_input_tokens": row["estimated_input_tokens"],
            "provider_payload": row["provider_payload"],
        }
        for row in sorted(rows, key=lambda value: str(value["logical_generation_request_id"]))
    ]


def _package_id(shard: str) -> str:
    return f"C4_REAL_GENERATION_SHARD_{shard}_R2_20260901"


def _readme(shard: str, count: int, tokens: int) -> bytes:
    return (
        "# C4 REAL blinded generation execution package R2\n\n"
        f"Package ID: `{_package_id(shard)}`. Shard: `{shard}`. "
        f"Blinded logical requests: `{count}`. Estimated input tokens: `{tokens}`.\n\n"
        "This package was prepared and tested offline. It contains no generated response and grants no "
        "execution authority. A new, package-specific response-generation authorization record is required.\n\n"
        "Offline checks:\n\n"
        "```text\n"
        "/opt/anaconda3/bin/python3 validate_package.py\n"
        "/opt/anaconda3/bin/python3 test_package.py\n"
        "```\n\n"
        "A future authorized command must provide `--authorization-record`, `--package-zip`, `--output-dir`, "
        "and `--execute`, together with the exact R2 environment gate. The runner refuses overwrite or resume, "
        "uses SDK retries 0, retries only once for invalid JSON/strict schema, and stops the whole shard on the "
        "first non-retryable failure. No Judge or scoring operation is included.\n"
    ).encode("utf-8")


def _execution_contract(shard: str, count: int, tokens: int) -> Mapping[str, Any]:
    return {
        "schema_version": "c4-real-generation-execution-contract-v2",
        "package_id": _package_id(shard),
        "status": "PREPARED_NOT_AUTHORIZED",
        "shard": shard,
        "request_count": count,
        "estimated_input_tokens": tokens,
        "maximum_physical_attempts": count * 2,
        "runtime": {
            "python_path": str(EXPECTED_PYTHON),
            "python_version": "3.13.5",
            "openai_sdk_version": "1.109.1",
        },
        "model": MODEL,
        "endpoint": "OpenAI Chat Completions",
        "temperature": 0,
        "max_output_tokens": 512,
        "automatic_sdk_retries": 0,
        "manual_retry": "ONE_IDENTICAL_RETRY_ONLY_INVALID_JSON_OR_STRICT_SCHEMA",
        "initial_request_gap_seconds_minimum": 2,
        "serial_execution": True,
        "streaming": False,
        "tools": "NONE",
        "authorization_record_required": True,
        "authorization_record_status_required": "AUTHORIZED",
        "authorization_environment_variable": "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION",
        "authorization_environment_value": "AUTHORIZED_C4_REAL_RESPONSE_GENERATION_R2",
        "authorization_binds_package_zip_sha256": True,
        "authorization_binds_blinded_manifest_sha256": True,
        "output_directory_must_not_exist": True,
        "automatic_resume": False,
        "continuation_requires_new_direct_authorization": True,
        "durability": "APPEND_FLUSH_FSYNC_EVERY_JOURNAL_RECORD",
        "preflight_receipt_before_runtime_or_client_construction": True,
        "stop_entire_shard_on_first_non_retryable_failure": True,
        "stop_entire_shard_after_second_invalid_json_or_schema": True,
        "returned_model_identity_required": True,
        "provider_errors_sanitized": True,
        "provider_calls_during_package_preparation": 0,
        "response_generation_during_package_preparation": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }


def write_package_directory(root: Path, shard: str, rows: list[dict[str, Any]]) -> None:
    tokens = sum(int(row["estimated_input_tokens"]) for row in rows)
    if {"request_count": len(rows), "estimated_input_tokens": tokens} != SHARD_EXPECTATIONS[shard]:
        raise ValueError(f"shard {shard} count/token identity changed")
    manifest_bytes = _jsonl_bytes(rows)
    source_members = {
        "README.md": _readme(shard, len(rows), tokens),
        "BLINDED_REQUESTS.jsonl": manifest_bytes,
        "GENERATION_PROMPT.txt": SOURCE_PATHS["generation_prompt"].read_bytes(),
        "GENERATION_SCHEMA.json": (
            HERE / "c4_real_generation_schema_v2_provider_compatible.json"
        ).read_bytes(),
        "GENERATION_CONFIGURATION.json": (
            HERE / "c4_real_generation_configuration_frozen_v2.json"
        ).read_bytes(),
        "EXECUTION_CONTRACT.json": _json_bytes(_execution_contract(shard, len(rows), tokens)),
        "generation_execution_runner_v2.py": (
            HERE / "generation_execution_runner_v2.py"
        ).read_bytes(),
        "validate_package.py": (HERE / "generation_package_validator_v2.py").read_bytes(),
        "test_package.py": (HERE / "generation_package_offline_tests_v2.py").read_bytes(),
    }
    if set(source_members) != ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"}:
        raise ValueError("R2 package source-member allowlist mismatch")
    root.mkdir(mode=0o700)
    for name, content in source_members.items():
        (root / name).write_bytes(content)
        os.chmod(root / name, 0o600 if name == "BLINDED_REQUESTS.jsonl" else 0o644)
    member_hashes = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(source_members.items())
    }
    source_hashes = {
        "schema_version": "c4-real-generation-package-source-hashes-v2",
        "package_id": _package_id(shard),
        "shard": shard,
        "request_count": len(rows),
        "estimated_input_tokens": tokens,
        "blinded_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_artifact_sha256": {
            "full_unique_request_manifest_v2": sha256_file(UNIQUE_MANIFEST),
            "frozen_generation_prompt": GENERATION_PROMPT_SHA256,
            "provider_compatible_generation_schema_v2": GENERATION_SCHEMA_V2_SHA256,
            "generation_configuration_v2": GENERATION_CONFIGURATION_V2_SHA256,
        },
        "member_sha256_excluding_self": member_hashes,
        "restricted_mapping_included": False,
        "hmac_key_included": False,
        "scenario_or_mode_identity_included": False,
        "existing_execution_results_included": False,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }
    (root / "PACKAGE_SOURCE_HASHES.json").write_bytes(_json_bytes(source_hashes))
    os.chmod(root / "PACKAGE_SOURCE_HASHES.json", 0o644)


def write_zip(source: Path, target: Path) -> None:
    with zipfile.ZipFile(
        target,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(ALLOWED_FILES):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = (0o600 if name == "BLINDED_REQUESTS.jsonl" else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (source / name).read_bytes(), compresslevel=9)


def run_package_tests(root: Path) -> int:
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["C4_REAL_RESPONSE_GENERATION_AUTHORIZATION"] = "NOT_AUTHORIZED"
    completed = subprocess.run(
        [str(EXPECTED_PYTHON), "test_package.py"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError("R2 offline package tests failed:\n" + output)
    match = re.search(r"Ran (\d+) tests?", output)
    if match is None or int(match.group(1)) != 6:
        raise ValueError("unexpected R2 package offline-test count")
    return int(match.group(1))


def _publish_all_exclusive(staged: Mapping[str, Path]) -> None:
    created: list[Path] = []
    try:
        for shard in "ABC":
            target = NEW_PACKAGE_PATHS[shard]
            os.link(staged[shard], target)
            os.chmod(target, 0o644)
            created.append(target)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _update_status(package_manifest: Mapping[str, Any]) -> None:
    status_path = HERE / "c4_real_i1_r1_status_v1.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(
        {
            "RQ3_REAL_I1_R1_STATUS": "READY_FOR_PARALLEL_C4_REAL_RESPONSE_GENERATION_AUTHORIZATION_R2",
            "replacement_generation_packages_complete": True,
            "replacement_generation_package_count": 3,
            "replacement_generation_package_manifest_sha256": sha256_file(PACKAGE_MANIFEST),
            "response_generation_authorised": False,
            "response_generation_executed": False,
            "provider_calls": 0,
            "judge_calls": 0,
            "scoring_calls": 0,
            "streamlit_launches": 0,
        }
    )
    write_json(status_path, status)
    (HERE / "STATUS.md").write_text(
        "# RQ3-REAL-C4 I1-R1 status\n\n"
        "`RQ3_REAL_I1_R1_STATUS = READY_FOR_PARALLEL_C4_REAL_RESPONSE_GENERATION_AUTHORIZATION_R2`\n\n"
        "Provider projection V2, exact evidence deduplication, 558 repaired condition payloads, preserved HMAC "
        "blinding, fail-closed runner V2, deterministic scenario-atomic shard assignment, and all three dormant "
        "R2 generation-package freezes passed. The original R1 packages remain preserved and unexecuted.\n\n"
        "No route or local mechanism was rerun; no provider request, response generation, Judge, scoring, or "
        "Streamlit execution occurred. READY status and package possession are not response-generation authority.\n",
        encoding="utf-8",
    )


def main() -> int:
    verify_frozen_state()
    runtime = _runtime_identity()
    unique_rows = _read_unique_rows()
    reports: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix=".c4-real-generation-r2-", dir=Path("/Users/liuming/Downloads")
    ) as temporary:
        temporary_root = Path(temporary)
        staged: dict[str, Path] = {}
        for shard in "ABC":
            rows = _package_rows(row for row in unique_rows if row["shard_id"] == shard)
            package_root = temporary_root / f"shard-{shard}"
            write_package_directory(package_root, shard, rows)
            directory_validation = dict(validate(package_root))
            offline_test_count = run_package_tests(package_root)
            staged_zip = temporary_root / NEW_PACKAGE_PATHS[shard].name
            write_zip(package_root, staged_zip)
            zip_validation = dict(validate_zip(staged_zip))
            if directory_validation["request_count"] != zip_validation["request_count"]:
                raise ValueError("directory/ZIP validation mismatch")
            staged[shard] = staged_zip
            reports.append(
                {
                    "package_id": _package_id(shard),
                    "shard": shard,
                    "path": str(NEW_PACKAGE_PATHS[shard]),
                    "sha256": sha256_file(staged_zip),
                    "byte_count": staged_zip.stat().st_size,
                    "request_count": zip_validation["request_count"],
                    "estimated_input_tokens": zip_validation["estimated_input_tokens"],
                    "maximum_physical_attempts": zip_validation["maximum_physical_attempts"],
                    "allowlisted_file_count": zip_validation["allowlisted_file_count"],
                    "validator_status": zip_validation["status"],
                    "offline_test_count": offline_test_count,
                    "provider_calls": 0,
                    "generation_calls": 0,
                    "judge_calls": 0,
                    "scoring_calls": 0,
                }
            )
        if sum(report["request_count"] for report in reports) != len(unique_rows):
            raise ValueError("V2 requests were omitted from or duplicated across packages")
        _publish_all_exclusive(staged)
    package_manifest = {
        "schema_version": "c4-real-generation-package-manifest-v2",
        "status": "PASS_THREE_DORMANT_R2_PACKAGES_PREPARED_NOT_AUTHORIZED",
        "runtime_preflight": runtime,
        "seed": 20260901,
        "scenario_atomic": True,
        "package_count": 3,
        "unique_request_count": len(unique_rows),
        "logical_call_count": len(unique_rows),
        "maximum_physical_attempts": len(unique_rows) * 2,
        "packages": reports,
        "old_r1_packages_status": "SUPERSEDED_UNEXECUTED_BY_I1_R1",
        "hmac_key_included": False,
        "restricted_mapping_included": False,
        "scenario_or_mode_identity_included": False,
        "response_generation_authorised": False,
        "response_generation_executed": False,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "streamlit_launches": 0,
    }
    write_json(PACKAGE_MANIFEST, package_manifest)
    _update_status(package_manifest)
    print(json.dumps(package_manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
