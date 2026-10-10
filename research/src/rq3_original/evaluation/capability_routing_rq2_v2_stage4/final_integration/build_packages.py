"""Build five deterministic, strict-allowlist Stage 4N ZIP packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
import zipfile

from .build_final_integration import METHOD_SOURCES, sha256_file, write_json
from .constants import (
    INTEGRATION_DIR,
    PACKAGE_PATHS,
    PROVIDER_STREAMS,
    REPOSITORY_ROOT,
    TEST_INPUT_DIR,
)
from .validate_execution_package import validate as validate_zip


class PackageBuildError(RuntimeError):
    """Raised before publishing when a package allowlist or byte check fails."""


FIXED_ZIP_TIME = (2026, 8, 31, 0, 0, 0)
_SECRET_PATTERN = re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")


def _integration(name: str) -> Path:
    return INTEGRATION_DIR / name


def _source(relative: str) -> Path:
    return REPOSITORY_ROOT / relative


def _source_items(method_ids: list[str]) -> dict[str, Path]:
    paths = sorted({path for method_id in method_ids for path in METHOD_SOURCES[method_id]})
    return {f"frozen_sources/{path}": _source(path) for path in paths}


def package_specs() -> dict[str, dict[str, Path]]:
    deterministic_methods = [
        "R2V2-D0_ALWAYS_ON", "R2V2-D1_NEVER_ON",
        "R2V2-CG1_CLARIFICATION_RULE", "R2V2-B0_RULE",
        "R2V2-B1_LEGACY_INTENT", "R2V2-B2_PROTOTYPE", "R2V2-B3_OVR",
    ]
    common_inputs = {
        "test_inputs/test_inputs_frozen_v1.csv": TEST_INPUT_DIR / "test_inputs_frozen_v1.csv",
        "test_inputs/test_inputs_frozen_v1.jsonl": TEST_INPUT_DIR / "test_inputs_frozen_v1.jsonl",
    }
    deterministic = {
        **common_inputs,
        "manifests/deterministic_test_execution_manifest_v1.jsonl": _integration("deterministic_test_execution_manifest_v1.jsonl"),
        "configuration/deterministic_test_execution_config_v1.json": _integration("deterministic_test_execution_config_v1.json"),
        "configuration/deterministic_source_hash_registry_v1.json": _integration("deterministic_source_hash_registry_v1.json"),
        "schemas/deterministic_prediction_output_schema_v1.json": _integration("deterministic_prediction_output_schema_v1.json"),
        "runner/execute_deterministic_test.py": _integration("execute_deterministic_test.py"),
        "validation/validate_execution_package.py": _integration("validate_execution_package.py"),
        "STATUS.md": _integration("STATUS.md"),
        **_source_items(deterministic_methods),
    }

    b4 = {
        **common_inputs,
        "manifests/b4_test_execution_manifest_v1.jsonl": _integration("b4_test_execution_manifest_v1.jsonl"),
        "schemas/provider_prediction_output_schema_v1.json": _integration("provider_prediction_output_schema_v1.json"),
        "runner/execute_provider_test.py": _integration("execute_provider_test.py"),
        "validation/validate_execution_package.py": _integration("validate_execution_package.py"),
        "STATUS.md": _integration("STATUS.md"),
        **_source_items(["R2V2-B4_JOINT_LLM"]),
    }
    rag = {
        **common_inputs,
        "manifests/rag_specialist_test_execution_manifest_v1.jsonl": _integration("rag_specialist_test_execution_manifest_v1.jsonl"),
        "schemas/provider_prediction_output_schema_v1.json": _integration("provider_prediction_output_schema_v1.json"),
        "runner/execute_provider_test.py": _integration("execute_provider_test.py"),
        "validation/validate_execution_package.py": _integration("validate_execution_package.py"),
        "STATUS.md": _integration("STATUS.md"),
        **_source_items(["R2V2-RAG_SPECIALIST"]),
    }
    memory = {
        **common_inputs,
        "manifests/memory_specialist_test_execution_manifest_v1.jsonl": _integration("memory_specialist_test_execution_manifest_v1.jsonl"),
        "schemas/provider_prediction_output_schema_v1.json": _integration("provider_prediction_output_schema_v1.json"),
        "runner/execute_provider_test.py": _integration("execute_provider_test.py"),
        "validation/validate_execution_package.py": _integration("validate_execution_package.py"),
        "STATUS.md": _integration("STATUS.md"),
        **_source_items(["R2V2-MEMORY_SPECIALIST"]),
    }

    review_names = [
        "final_method_registry_v1.json", "frozen_source_hash_registry_v1.json",
        "deterministic_source_hash_registry_v1.json",
        "test_input_verification_v1.json",
        "deterministic_test_execution_manifest_v1.jsonl",
        "b4_test_execution_manifest_v1.jsonl",
        "rag_specialist_test_execution_manifest_v1.jsonl",
        "memory_specialist_test_execution_manifest_v1.jsonl",
        "deterministic_test_execution_config_v1.json",
        "test_execution_population_v1.json",
        "FINAL_TEST_SCORING_PROTOCOL.md", "final_test_scoring_protocol_v1.json",
        "comparison_hierarchy_v1.json", "uncertainty_reporting_plan_v1.json",
        "deterministic_prediction_output_schema_v1.json",
        "provider_prediction_output_schema_v1.json",
        "STAGE4N_GENERATED_SHA256_MANIFEST.json", "README.md", "STATUS.md",
        "constants.py", "build_final_integration.py", "build_packages.py",
        "validate_final_integration.py", "validate_execution_package.py",
        "execute_provider_test.py", "execute_deterministic_test.py",
        "tests/test_final_integration.py",
    ]
    review = {
        "test_inputs/test_inputs_frozen_v1.csv": TEST_INPUT_DIR / "test_inputs_frozen_v1.csv",
        "test_inputs/test_inputs_frozen_v1.jsonl": TEST_INPUT_DIR / "test_inputs_frozen_v1.jsonl",
        **{f"integration/{name}": _integration(name) for name in review_names},
    }
    return {
        "DETERMINISTIC": deterministic,
        "B4": b4,
        "RAG_SPECIALIST": rag,
        "MEMORY_SPECIALIST": memory,
        "INTERNAL_REVIEW": review,
    }


def _manifest_bytes(role: str, items: Mapping[str, Path]) -> bytes:
    names = sorted(items)
    allowlist = [*names, "PACKAGE_MANIFEST.json"]
    payload = {
        "schema_version": "rq2-v2-stage4n-package-manifest-v1",
        "package_role": role,
        "package_status": "FROZEN_UNEXECUTED",
        "archive_allowlist": allowlist,
        "members": [
            {
                "path": name,
                "sha256": sha256_file(items[name]),
                "size_bytes": items[name].stat().st_size,
            }
            for name in names
        ],
        "TEST_Gold_included": False,
        "predictions_included": False,
        "scores_included": False,
        "API_keys_included": False,
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_member(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    mode = 0o755 if name.endswith(".py") else 0o644
    info.external_attr = (mode & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_one(path: Path, role: str, items: Mapping[str, Path]) -> None:
    missing = [str(source) for source in items.values() if not source.is_file()]
    if missing:
        raise PackageBuildError("package source files are missing: " + ", ".join(missing))
    if len(items) != len(set(items)) or any("gold" in Path(name).name.casefold() for name in items):
        raise PackageBuildError("package allowlist contains duplicate or Gold-like member")
    manifest_data = _manifest_bytes(role, items)
    with zipfile.ZipFile(path, "x") as archive:
        for name in sorted(items):
            data = items[name].read_bytes()
            if _SECRET_PATTERN.search(data):
                raise PackageBuildError(f"possible API key in package source: {name}")
            _write_member(archive, name, data)
        _write_member(archive, "PACKAGE_MANIFEST.json", manifest_data)


def build_all_packages(*, replace_existing: bool = False) -> dict[str, dict[str, Any]]:
    specs = package_specs()
    existing = [str(PACKAGE_PATHS[role]) for role in specs if PACKAGE_PATHS[role].exists()]
    if existing and not replace_existing:
        raise PackageBuildError("refusing to overwrite existing package(s): " + ", ".join(existing))
    if existing:
        for role in specs:
            if PACKAGE_PATHS[role].exists():
                validate_zip(PACKAGE_PATHS[role])
    with tempfile.TemporaryDirectory(prefix="rq2-v2-stage4n-packages-") as temporary:
        temp_root = Path(temporary)
        temp_paths: dict[str, Path] = {}
        for role, items in specs.items():
            path = temp_root / PACKAGE_PATHS[role].name
            build_one(path, role, items)
            validate_zip(path)
            temp_paths[role] = path
        for role, temporary_path in temp_paths.items():
            os.replace(temporary_path, PACKAGE_PATHS[role])

    results: dict[str, dict[str, Any]] = {}
    for role, path in PACKAGE_PATHS.items():
        audit = validate_zip(path)
        results[role] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "member_count": audit["member_count"],
            "allowlist_status": "PASS",
            "CRC_status": "PASS",
            "TEST_Gold_member_count": 0,
        }
    write_json(
        INTEGRATION_DIR / "package_hashes_v1.json",
        {
            "schema_version": "rq2-v2-stage4n-package-hashes-v1",
            "status": "PASS_ALL_PACKAGE_AUDITS",
            "packages": results,
        },
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="atomically replace only previously valid Stage 4N package paths",
    )
    args = parser.parse_args()
    results = build_all_packages(replace_existing=args.replace_existing)
    for role, item in results.items():
        print(f"PASS {role} {item['sha256']} {item['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
