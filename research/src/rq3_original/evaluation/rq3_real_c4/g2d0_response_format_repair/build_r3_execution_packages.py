#!/usr/bin/env python3
"""Build three dormant, allowlisted C4 REAL regeneration R3 packages offline."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Iterable, Mapping
import zipfile

try:
    from .generation_package_validator_v3 import ALLOWED_FILES, validate, validate_zip
except ImportError:
    from generation_package_validator_v3 import ALLOWED_FILES, validate, validate_zip


REPO_ROOT = Path(__file__).resolve().parents[3]
REPAIR_DIR = Path(__file__).resolve().parent
I1_DIR = REPO_ROOT / "evaluation/rq3_real_c4/i1_route_integration"
DOWNLOADS = Path("/Users/liuming/Downloads")
BRANCH = "research/rq3-real-c4-i1-route-integration"
INTEGRATED_G2_HEAD = "2c1094d6486d5db8d01d8a4ef02e11f15d1813e9"
MODEL = "gpt-4o-mini-2024-07-18"
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)
EXPECTED_PYTHON = Path("/opt/anaconda3/bin/python3")

UNIQUE_MANIFEST_PATH = I1_DIR / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl"
SHARD_SUMMARY_PATH = I1_DIR / "c4_real_generation_shard_summary_v3.json"
CONFIGURATION_PATH = I1_DIR / "c4_real_generation_configuration_frozen_v3.json"
SCHEMA_PATH = I1_DIR / "c4_real_generation_schema_v2_provider_compatible.json"
PROMPT_PATH = REPAIR_DIR / "c4_real_generation_prompt_frozen_v3.txt"
FORMAT_CONTRACT_PATH = REPAIR_DIR / "c4_real_student_facing_response_format_contract_v1.json"
RUNNER_PATH = REPAIR_DIR / "generation_execution_runner_v3.py"
SEMANTIC_VALIDATOR_PATH = REPAIR_DIR / "c4_real_student_facing_response_validator_v1.py"
PACKAGE_VALIDATOR_PATH = REPAIR_DIR / "generation_package_validator_v3.py"
PACKAGE_TESTS_PATH = REPAIR_DIR / "generation_package_offline_tests_v3.py"
PACKAGE_MANIFEST_PATH = I1_DIR / "c4_real_generation_package_manifest_v3.json"

PACKAGE_PATHS = {
    shard: DOWNLOADS / f"C4_REAL_GENERATION_SHARD_{shard}_EXECUTION_PACKAGE_R3_2026-09-01.zip"
    for shard in "ABC"
}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        for row in rows
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def runtime_identity() -> Mapping[str, Any]:
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
        cwd=REPO_ROOT,
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
        raise RuntimeError(f"future R3 runtime identity mismatch: {identity}")
    return identity


def verify_inputs() -> Mapping[str, Any]:
    if Path.cwd().resolve() != REPO_ROOT:
        raise RuntimeError("R3 package builder must run from repository root")
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("R3 package builder branch mismatch")
    if git("rev-parse", "HEAD") != INTEGRATED_G2_HEAD:
        raise RuntimeError("R3 package builder integrated G2 HEAD mismatch")
    if PACKAGE_MANIFEST_PATH.exists() or any(path.exists() for path in PACKAGE_PATHS.values()):
        raise FileExistsError("refusing to overwrite an R3 package or package manifest")
    subprocess.run(
        [
            str(EXPECTED_PYTHON),
            str(REPAIR_DIR / "build_v3_regeneration_artifacts.py"),
            "--verify-only",
        ],
        cwd=REPO_ROOT,
        check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
    )
    schema_hash = sha256_file(SCHEMA_PATH)
    if schema_hash != "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873":
        raise RuntimeError("outer schema bytes changed")
    shard_summary = json.loads(SHARD_SUMMARY_PATH.read_text(encoding="utf-8"))
    if (
        shard_summary["unique_request_count"] != 147
        or shard_summary["maximum_physical_attempt_count"] != 294
        or shard_summary["scenario_atomic"] is not True
    ):
        raise RuntimeError("V3 shard freeze changed")
    return shard_summary


def package_id(shard: str) -> str:
    return f"C4_REAL_GENERATION_SHARD_{shard}_R3_20260901"


def package_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "c4-real-blinded-generation-request-v3",
            "logical_generation_request_id": row["logical_generation_request_id"],
            "response_blind_id": row["response_blind_id"],
            "provider_payload_sha256": row["provider_payload_sha256"],
            "estimated_input_tokens": row["estimated_input_tokens"],
            "provider_payload": row["provider_payload"],
        }
        for row in sorted(rows, key=lambda value: str(value["logical_generation_request_id"]))
    ]


def readme(shard: str, count: int, tokens: int) -> bytes:
    return (
        "# C4 REAL blinded response-regeneration package R3\n\n"
        f"Package ID: `{package_id(shard)}`. Shard: `{shard}`. Blinded logical requests: `{count}`. Estimated input tokens: `{tokens}`.\n\n"
        "This package was prepared and tested offline. It contains no G2 answer, generated R3 response, restricted mapping, HMAC key, Judge material, score, or execution authority.\n\n"
        "Offline checks:\n\n"
        "```text\n/opt/anaconda3/bin/python3 validate_package.py\n/opt/anaconda3/bin/python3 test_package.py\n```\n\n"
        "A future authorized execution must provide a package-specific authorization record, the exact package ZIP, a new output directory, `--execute`, and the exact R3 environment gate. Runner V3 uses SDK retries 0; permits one byte-identical retry only after invalid JSON, strict outer-schema failure, or non-student-facing answer format; records the first invalid raw response durably; and stops the shard after a second invalid or any non-retryable failure. No Judge or scoring operation is included.\n"
    ).encode("utf-8")


def execution_contract(shard: str, count: int, tokens: int) -> Mapping[str, Any]:
    return {
        "schema_version": "c4-real-generation-execution-contract-v3",
        "package_id": package_id(shard),
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
        "manual_retry_categories": [
            "INVALID_JSON",
            "STRICT_SCHEMA_VALIDATION_FAILED",
            "NON_STUDENT_FACING_FORMAT",
        ],
        "maximum_manual_retries_per_request": 1,
        "identical_retry_payload": True,
        "correction_message_on_retry": False,
        "first_invalid_raw_response_retained": True,
        "semantic_validation_after_strict_outer_schema": True,
        "stop_entire_shard_after_second_invalid_response": True,
        "stop_entire_shard_on_first_non_retryable_failure": True,
        "initial_request_gap_seconds_minimum": 2,
        "serial_execution": True,
        "streaming": False,
        "tools": "NONE",
        "authorization_record_required": True,
        "authorization_record_status_required": "AUTHORIZED",
        "authorization_environment_variable": "C4_REAL_RESPONSE_GENERATION_AUTHORIZATION",
        "authorization_environment_value": "AUTHORIZED_C4_REAL_RESPONSE_REGENERATION_R3",
        "authorization_binds_package_zip_sha256": True,
        "authorization_binds_blinded_manifest_sha256": True,
        "output_directory_must_not_exist": True,
        "automatic_resume": False,
        "continuation_requires_new_direct_authorization": True,
        "durability": "APPEND_FLUSH_FSYNC_EVERY_JOURNAL_RECORD",
        "preflight_receipt_before_runtime_or_client_construction": True,
        "returned_model_identity_required": True,
        "provider_errors_sanitized": True,
        "provider_calls_during_package_preparation": 0,
        "response_generation_during_package_preparation": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }


def write_package_directory(root: Path, shard: str, rows: list[dict[str, Any]]) -> None:
    tokens = sum(int(row["estimated_input_tokens"]) for row in rows)
    manifest_bytes = jsonl_bytes(rows)
    source_members = {
        "README.md": readme(shard, len(rows), tokens),
        "BLINDED_REQUESTS.jsonl": manifest_bytes,
        "GENERATION_PROMPT.txt": PROMPT_PATH.read_bytes(),
        "GENERATION_SCHEMA.json": SCHEMA_PATH.read_bytes(),
        "GENERATION_CONFIGURATION.json": CONFIGURATION_PATH.read_bytes(),
        "STUDENT_FACING_FORMAT_CONTRACT.json": FORMAT_CONTRACT_PATH.read_bytes(),
        "EXECUTION_CONTRACT.json": json_bytes(execution_contract(shard, len(rows), tokens)),
        "generation_execution_runner_v3.py": RUNNER_PATH.read_bytes(),
        "c4_real_student_facing_response_validator_v1.py": SEMANTIC_VALIDATOR_PATH.read_bytes(),
        "validate_package.py": PACKAGE_VALIDATOR_PATH.read_bytes(),
        "test_package.py": PACKAGE_TESTS_PATH.read_bytes(),
    }
    if set(source_members) != ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"}:
        raise RuntimeError("R3 package source-member allowlist mismatch")
    root.mkdir(mode=0o700)
    for name, content in source_members.items():
        (root / name).write_bytes(content)
        os.chmod(root / name, 0o600 if name == "BLINDED_REQUESTS.jsonl" else 0o644)
    member_hashes = {
        name: hashlib.sha256(content).hexdigest() for name, content in sorted(source_members.items())
    }
    source_hashes = {
        "schema_version": "c4-real-generation-package-source-hashes-v3",
        "package_id": package_id(shard),
        "shard": shard,
        "request_count": len(rows),
        "estimated_input_tokens": tokens,
        "blinded_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_artifact_sha256": {
            "full_unique_request_manifest_v3": sha256_file(UNIQUE_MANIFEST_PATH),
            "frozen_generation_prompt_v3": sha256_file(PROMPT_PATH),
            "plain_text_request_renderer_v3": sha256_file(
                REPAIR_DIR / "c4_real_generation_request_renderer_v3.py"
            ),
            "provider_compatible_outer_schema": sha256_file(SCHEMA_PATH),
            "generation_configuration_v3": sha256_file(CONFIGURATION_PATH),
            "student_facing_format_contract_v1": sha256_file(FORMAT_CONTRACT_PATH),
            "student_facing_validator_v1": sha256_file(SEMANTIC_VALIDATOR_PATH),
            "generation_runner_v3": sha256_file(RUNNER_PATH),
        },
        "member_sha256_excluding_self": member_hashes,
        "restricted_mapping_included": False,
        "hmac_key_included": False,
        "scenario_mode_route_or_gold_identity_included": False,
        "g2_answers_included": False,
        "existing_execution_results_included": False,
        "course_corpus_included": False,
        "memory_database_included": False,
        "api_key_included": False,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }
    (root / "PACKAGE_SOURCE_HASHES.json").write_bytes(json_bytes(source_hashes))
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
        raise RuntimeError("R3 offline package tests failed:\n" + output)
    match = re.search(r"Ran (\d+) tests?", output)
    if match is None or int(match.group(1)) != 9:
        raise RuntimeError("unexpected R3 package offline-test count:\n" + output)
    return int(match.group(1))


def publish_all_exclusive(staged: Mapping[str, Path]) -> list[Path]:
    created: list[Path] = []
    try:
        for shard in "ABC":
            target = PACKAGE_PATHS[shard]
            os.link(staged[shard], target)
            os.chmod(target, 0o644)
            created.append(target)
        return created
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main() -> int:
    shard_summary = verify_inputs()
    runtime = runtime_identity()
    unique_rows = load_jsonl(UNIQUE_MANIFEST_PATH)
    if len(unique_rows) != 147:
        raise RuntimeError("V3 unique request count changed")
    expected_by_shard = {row["shard_id"]: row for row in shard_summary["shards"]}
    reports: list[dict[str, Any]] = []
    created: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix=".c4-real-generation-r3-", dir=DOWNLOADS) as temporary:
            temporary_root = Path(temporary)
            staged: dict[str, Path] = {}
            for shard in "ABC":
                rows = package_rows(row for row in unique_rows if row["shard_id"] == shard)
                expected = expected_by_shard[shard]
                if len(rows) != expected["unique_request_count"] or sum(
                    row["estimated_input_tokens"] for row in rows
                ) != expected["estimated_input_tokens"]:
                    raise RuntimeError(f"shard {shard} frozen identity changed")
                package_root = temporary_root / f"shard-{shard}"
                write_package_directory(package_root, shard, rows)
                directory_validation = dict(validate(package_root))
                offline_test_count = run_package_tests(package_root)
                staged_zip = temporary_root / PACKAGE_PATHS[shard].name
                write_zip(package_root, staged_zip)
                zip_validation = dict(validate_zip(staged_zip))
                if directory_validation != {
                    key: value for key, value in zip_validation.items() if key != "package_zip_sha256"
                }:
                    raise RuntimeError("directory/ZIP validation mismatch")
                staged[shard] = staged_zip
                reports.append(
                    {
                        "package_id": package_id(shard),
                        "shard": shard,
                        "path": str(PACKAGE_PATHS[shard]),
                        "sha256": sha256_file(staged_zip),
                        "byte_count": staged_zip.stat().st_size,
                        "request_count": zip_validation["request_count"],
                        "estimated_input_tokens": zip_validation["estimated_input_tokens"],
                        "maximum_physical_attempts": zip_validation[
                            "maximum_physical_attempts"
                        ],
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
                raise RuntimeError("V3 requests omitted from or duplicated across packages")
            created = publish_all_exclusive(staged)

        package_manifest = {
            "schema_version": "c4-real-generation-package-manifest-v3",
            "status": "PASS_THREE_DORMANT_R3_REGENERATION_PACKAGES_PREPARED_NOT_AUTHORIZED",
            "runtime_preflight": runtime,
            "seed": 20260901,
            "scenario_atomic": True,
            "package_count": 3,
            "unique_request_count": len(unique_rows),
            "logical_call_count": len(unique_rows),
            "maximum_physical_attempts": len(unique_rows) * 2,
            "packages": reports,
            "hmac_key_included": False,
            "restricted_mapping_included": False,
            "scenario_mode_route_or_gold_identity_included": False,
            "g2_answers_included": False,
            "response_regeneration_authorised": False,
            "response_regeneration_executed": False,
            "provider_calls": 0,
            "generation_calls": 0,
            "judge_calls": 0,
            "scoring_calls": 0,
            "streamlit_launches": 0,
        }
        descriptor = os.open(PACKAGE_MANIFEST_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json_bytes(package_manifest))
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps(package_manifest, sort_keys=True))
        return 0
    except Exception:
        PACKAGE_MANIFEST_PATH.unlink(missing_ok=True)
        for path in created:
            path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
