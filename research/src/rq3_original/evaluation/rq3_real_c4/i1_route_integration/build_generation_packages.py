#!/usr/bin/env python3
"""Build and validate the three dormant, blinded C4 generation packages.

This builder performs no provider operation.  It refuses to overwrite an
existing deliverable and publishes packages only after all three temporary
packages pass their strict validator and offline tests.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.generation_package_validator_v1 import (
    ALLOWED_FILES,
    validate,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_common import (
    HERE,
    ROOT,
    SOURCE_PATHS,
    canonical_bytes,
    load_jsonl,
    sha256_file,
    write_json,
)


OUTPUT_ROOT = Path("/Users/liuming/Downloads")
EXPECTED_PYTHON = Path("/opt/anaconda3/bin/python3")
PACKAGE_NAMES = {
    shard: f"C4_REAL_GENERATION_SHARD_{shard}_EXECUTION_PACKAGE_R1_2026-09-01.zip"
    for shard in "ABC"
}
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)
UNIQUE_MANIFEST = HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl"
PACKAGE_MANIFEST = HERE / "c4_real_generation_package_manifest_v1.json"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


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
    completed = subprocess.run(
        [str(EXPECTED_PYTHON), "-c", program],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    identity = json.loads(completed.stdout)
    if identity != {
        "executable": str(EXPECTED_PYTHON),
        "openai_sdk_version": "1.109.1",
        "python_version": "3.13.5",
    }:
        raise ValueError(f"future generation runtime identity mismatch: {identity}")
    return identity


def _read_unique_rows() -> list[dict[str, Any]]:
    rows = load_jsonl(UNIQUE_MANIFEST)
    if len(rows) != 197:
        raise ValueError("frozen unique-request population changed")
    if Counter(str(row.get("shard_id")) for row in rows) != Counter(
        {"A": 68, "B": 62, "C": 67}
    ):
        raise ValueError("frozen shard request distribution changed")
    logical_ids = {str(row["logical_generation_request_id"]) for row in rows}
    response_ids = {str(row["response_blind_id"]) for row in rows}
    if len(logical_ids) != len(rows) or len(response_ids) != len(rows):
        raise ValueError("opaque request identities are not unique")
    for row in rows:
        payload_hash = hashlib.sha256(canonical_bytes(row["provider_payload"])).hexdigest()
        if payload_hash != row["provider_payload_sha256"]:
            raise ValueError("unique-request provider payload hash mismatch")
    return rows


def _package_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in sorted(rows, key=lambda value: str(value["logical_generation_request_id"])):
        output.append(
            {
                "schema_version": "c4-real-blinded-generation-request-v1",
                "logical_generation_request_id": row["logical_generation_request_id"],
                "response_blind_id": row["response_blind_id"],
                "provider_payload_sha256": row["provider_payload_sha256"],
                "estimated_input_tokens": row["estimated_input_tokens"],
                "provider_payload": row["provider_payload"],
            }
        )
    return output


def _readme(shard: str, count: int, tokens: int) -> bytes:
    return (
        "# C4 REAL blinded generation execution package\n\n"
        f"Shard: `{shard}`. Blinded logical requests: `{count}`. "
        f"Estimated input tokens: `{tokens}`.\n\n"
        "This package was prepared offline. It contains no generated response and grants no execution authority. "
        "A later, explicit response-generation authorization is required.\n\n"
        "Before any later execution, run:\n\n"
        "```text\n"
        "/opt/anaconda3/bin/python3 validate_package.py\n"
        "/opt/anaconda3/bin/python3 test_package.py\n"
        "```\n\n"
        "The future runner additionally requires both `--execute` and the separate authorization environment gate. "
        "It refuses overwrite and automatic resume. It is serial, durable, and generation-only; it makes no Judge call.\n"
    ).encode("utf-8")


def _execution_contract(shard: str, count: int, tokens: int) -> Mapping[str, Any]:
    return {
        "schema_version": "c4-real-generation-execution-contract-v1",
        "status": "PREPARED_NOT_AUTHORISED",
        "shard": shard,
        "request_count": count,
        "estimated_input_tokens": tokens,
        "maximum_physical_attempt_count": count * 2,
        "runtime": {
            "python_path": str(EXPECTED_PYTHON),
            "python_version": "3.13.5",
            "openai_sdk_version": "1.109.1",
        },
        "model": "gpt-4o-mini-2024-07-18",
        "endpoint": "OpenAI Chat Completions",
        "temperature": 0,
        "max_output_tokens": 512,
        "automatic_sdk_retries": 0,
        "manual_retry": "ONE_IDENTICAL_RETRY_ONLY_INVALID_JSON_OR_SCHEMA",
        "initial_request_gap_seconds_minimum": 2,
        "serial_execution": True,
        "streaming": False,
        "tools": "NONE",
        "output_directory_must_not_exist": True,
        "automatic_resume": False,
        "durability": "APPEND_FLUSH_FSYNC_EVERY_ATTEMPT_AND_TERMINAL_RESULT",
        "returned_model_identity_required": True,
        "provider_errors_sanitized": True,
        "explicit_later_authority_required": True,
        "provider_calls_during_package_preparation": 0,
        "response_generation_during_package_preparation": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }


def _write_package_directory(root: Path, shard: str, rows: list[dict[str, Any]]) -> None:
    tokens = sum(int(row["estimated_input_tokens"]) for row in rows)
    source_members = {
        "README.md": _readme(shard, len(rows), tokens),
        "BLINDED_REQUESTS.jsonl": _jsonl_bytes(rows),
        "GENERATION_PROMPT.txt": SOURCE_PATHS["generation_prompt"].read_bytes(),
        "GENERATION_SCHEMA.json": (
            HERE / "c4_real_generation_schema_v2_provider_compatible.json"
        ).read_bytes(),
        "GENERATION_CONFIGURATION.json": (
            HERE / "c4_real_generation_configuration_frozen_v2.json"
        ).read_bytes(),
        "generation_runner.py": (HERE / "generation_execution_runner_v1.py").read_bytes(),
        "validate_package.py": (HERE / "generation_package_validator_v1.py").read_bytes(),
        "test_package.py": (HERE / "generation_package_offline_tests_v1.py").read_bytes(),
        "EXECUTION_CONTRACT.json": _json_bytes(_execution_contract(shard, len(rows), tokens)),
    }
    if set(source_members) != ALLOWED_FILES - {"PACKAGE_SOURCE_HASHES.json"}:
        raise ValueError("package source member allowlist mismatch")
    root.mkdir(mode=0o700)
    for name, content in source_members.items():
        (root / name).write_bytes(content)
        os.chmod(root / name, 0o600 if name == "BLINDED_REQUESTS.jsonl" else 0o644)
    member_hashes = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in sorted(source_members.items())
    }
    source_hashes = {
        "schema_version": "c4-real-generation-package-source-hashes-v1",
        "shard": shard,
        "request_count": len(rows),
        "estimated_input_tokens": tokens,
        "source_artifact_sha256": {
            "full_unique_request_manifest": sha256_file(UNIQUE_MANIFEST),
            "frozen_generation_prompt": sha256_file(SOURCE_PATHS["generation_prompt"]),
            "provider_compatible_generation_schema_v2": sha256_file(
                HERE / "c4_real_generation_schema_v2_provider_compatible.json"
            ),
            "generation_configuration_v2": sha256_file(
                HERE / "c4_real_generation_configuration_frozen_v2.json"
            ),
        },
        "member_sha256_excluding_self": member_hashes,
        "restricted_mapping_included": False,
        "hmac_key_included": False,
        "existing_execution_results_included": False,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
    }
    (root / "PACKAGE_SOURCE_HASHES.json").write_bytes(_json_bytes(source_hashes))
    os.chmod(root / "PACKAGE_SOURCE_HASHES.json", 0o644)


def _write_zip(source: Path, target: Path) -> None:
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
            mode = 0o600 if name == "BLINDED_REQUESTS.jsonl" else 0o644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (source / name).read_bytes(), compresslevel=9)


def _validate_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != ALLOWED_FILES:
            raise ValueError("ZIP member allowlist mismatch")
        if any(name.endswith("/") or Path(name).name != name for name in names):
            raise ValueError("ZIP contains a directory or nested member")
        with tempfile.TemporaryDirectory(prefix="c4-real-package-validate-") as temporary:
            root = Path(temporary)
            archive.extractall(root)
            validate(root)


def _run_package_tests(root: Path) -> int:
    completed = subprocess.run(
        [str(EXPECTED_PYTHON), "test_package.py"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "C4_REAL_GENERATION_EXECUTION_AUTHORIZED": "NO",
        },
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "offline package tests failed:\n" + completed.stdout + completed.stderr
        )
    return completed.stderr.count(" ... ok") + completed.stdout.count(" ... ok")


def _publish_exclusive(source: Path, target: Path) -> None:
    os.link(source, target)
    os.chmod(target, 0o644)


def _update_status(package_manifest: Mapping[str, Any]) -> None:
    status_path = HERE / "c4_real_i1_status_v1.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["generation_packages_preparation_complete"] = True
    status["generation_package_count"] = 3
    status["generation_package_manifest_sha256"] = sha256_file(PACKAGE_MANIFEST)
    status["response_generation_authorised"] = False
    status["response_generation_executed"] = False
    status["judge_executed"] = False
    status["scoring_executed"] = False
    status["streamlit_launched"] = False
    status["external_provider_calls"] = 0
    write_json(status_path, status)

    source_path = HERE / "c4_real_i1_source_manifest_v1.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["generation_packages"] = {
        "status": package_manifest["status"],
        "package_count": 3,
        "manifest_sha256": sha256_file(PACKAGE_MANIFEST),
        "logical_call_count": package_manifest["logical_call_count"],
        "maximum_physical_attempt_count": package_manifest[
            "maximum_physical_attempt_count"
        ],
    }
    write_json(source_path, source)

    (HERE / "STATUS.md").write_text(
        "# RQ3-REAL-C4 I1 status\n\n"
        "`RQ3_REAL_I1_STATUS = READY_FOR_PARALLEL_C4_REAL_RESPONSE_GENERATION_AUTHORIZATION`\n\n"
        "Frozen P3 route integration, isolated local mechanism replay, provider-safe request preparation, "
        "exact-byte deduplication, blinding, deterministic three-shard assignment, and all three dormant "
        "generation-package builds passed.\n\n"
        "No provider request was sent; no student response was generated; no Judge or scoring call was made; "
        "Streamlit was not launched. READY status is not response-generation authority.\n",
        encoding="utf-8",
    )


def main() -> int:
    final_paths = {shard: OUTPUT_ROOT / name for shard, name in PACKAGE_NAMES.items()}
    existing = [str(path) for path in final_paths.values() if path.exists()]
    if existing:
        raise FileExistsError("refusing to overwrite generation package(s): " + ", ".join(existing))
    runtime = _runtime_identity()
    unique_rows = _read_unique_rows()
    package_reports = []
    with tempfile.TemporaryDirectory(
        prefix=".c4-real-generation-packages-", dir=OUTPUT_ROOT
    ) as temporary:
        temporary_root = Path(temporary)
        staged_zips: dict[str, Path] = {}
        for shard in "ABC":
            rows = _package_rows(row for row in unique_rows if row["shard_id"] == shard)
            package_root = temporary_root / f"shard-{shard}"
            _write_package_directory(package_root, shard, rows)
            validation = dict(validate(package_root))
            offline_test_count = _run_package_tests(package_root)
            if offline_test_count != 4:
                raise ValueError(f"unexpected package offline-test count for shard {shard}")
            staged_zip = temporary_root / PACKAGE_NAMES[shard]
            _write_zip(package_root, staged_zip)
            _validate_zip(staged_zip)
            staged_zips[shard] = staged_zip
            package_reports.append(
                {
                    "shard": shard,
                    "path": str(final_paths[shard]),
                    "sha256": sha256_file(staged_zip),
                    "byte_count": staged_zip.stat().st_size,
                    "request_count": validation["request_count"],
                    "estimated_input_tokens": validation["estimated_input_tokens"],
                    "maximum_physical_attempt_count": validation["request_count"] * 2,
                    "allowlisted_file_count": validation["allowlisted_file_count"],
                    "validator_status": validation["status"],
                    "offline_test_count": offline_test_count,
                    "provider_calls": 0,
                    "generation_calls": 0,
                    "judge_calls": 0,
                }
            )
        if sum(row["request_count"] for row in package_reports) != len(unique_rows):
            raise ValueError("unique requests were omitted from or duplicated across packages")
        for shard in "ABC":
            _publish_exclusive(staged_zips[shard], final_paths[shard])

    package_manifest = {
        "schema_version": "c4-real-generation-package-manifest-v1",
        "status": "PASS_THREE_DORMANT_PACKAGES_PREPARED_NOT_AUTHORISED",
        "runtime_preflight": runtime,
        "package_count": 3,
        "unique_request_count": len(unique_rows),
        "logical_call_count": len(unique_rows),
        "maximum_physical_attempt_count": len(unique_rows) * 2,
        "packages": package_reports,
        "hmac_key_included": False,
        "restricted_mapping_included": False,
        "scenario_or_mode_identity_included": False,
        "response_generation_authorised": False,
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
