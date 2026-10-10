#!/usr/bin/env python3
"""Build replacement I0-R1 route packages without regenerating scientific inputs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

try:
    from .route_package_validator_v1 import (
        AUTHORIZATION_ENVIRONMENT_VALUE,
        AUTHORIZATION_ENVIRONMENT_VARIABLE,
        AUTHORIZATION_FIELDS,
        AUTHORIZATION_SCOPE,
        REQUESTS_SHA256,
        SCIENTIFIC_MEMBERS,
        canonical_bytes,
        parse_requests,
        validate_package_dir,
    )
except ImportError:  # pragma: no cover - standalone package-builder entrypoint
    from route_package_validator_v1 import (  # type: ignore
        AUTHORIZATION_ENVIRONMENT_VALUE,
        AUTHORIZATION_ENVIRONMENT_VARIABLE,
        AUTHORIZATION_FIELDS,
        AUTHORIZATION_SCOPE,
        REQUESTS_SHA256,
        SCIENTIFIC_MEMBERS,
        canonical_bytes,
        parse_requests,
        validate_package_dir,
    )


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RQ2 = ROOT / "evaluation/capability_routing_rq2_v2_stage4"
DOWNLOADS = ROOT / "external_inputs/historical_archives"
STARTING_HEAD = "23c1a016b0d797b9e975baa65994321eb3d2fd67"
MODEL = "gpt-4o-mini-2024-07-18"
FIXED_ZIP_TIME = (2026, 9, 1, 0, 0, 0)
FIXED_DATE = "2026-09-01"

ORIGINAL_PACKAGE_STATUS = "SUPERSEDED_UNEXECUTED_BY_I0_R1"
R1_PACKAGE_STATUS = "FROZEN_UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION"

ERROR_CLASSES = [
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "REQUEST_CONFIGURATION_ERROR",
    "MODEL_OR_ENDPOINT_NOT_FOUND",
    "RATE_LIMIT_ERROR",
    "TRANSPORT_ERROR",
    "TIMEOUT",
    "PROVIDER_REFUSAL",
    "INVALID_JSON",
    "STRICT_SCHEMA_VALIDATION_FAILED",
    "RETURNED_MODEL_MISMATCH",
    "UNEXPECTED_PROVIDER_RESPONSE",
]

I0_SCIENTIFIC_TRACKED_PATHS = [
    "evaluation/rq3_real_c4/i0_integration/c4_real_clarification_decisions_frozen_v1.csv",
    "evaluation/rq3_real_c4/i0_integration/c4_real_final_analysis_cohorts_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_generation_configuration_frozen_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_generation_prompt_frozen_v1.txt",
    "evaluation/rq3_real_c4/i0_integration/c4_real_generation_schema_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_judge_configuration_frozen_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_judge_schema_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_memory_preconditioning_manifest_v1.jsonl",
    "evaluation/rq3_real_c4/i0_integration/c4_real_memory_preconditioning_validation_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_p3_route_input_manifest_v1.jsonl",
    "evaluation/rq3_real_c4/i0_integration/c4_real_route_execution_plan_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_system_dry_run_v1.json",
]

PACKAGE_SPECS: dict[str, dict[str, Any]] = {
    "RAG": {
        "method_id": "R2V2-RAG_SPECIALIST",
        "original_filename": "C4_REAL_P3_RAG_ROUTE_EXECUTION_PACKAGE_2026-09-01.zip",
        "original_package_id": "C4_REAL_P3_RAG_ROUTE_EXECUTION_V1",
        "original_sha256": "9cdd4caf404a2ba8c6743ed08b47a4bb3427d73851c0f7e1ba74c9f9a98c2f2a",
        "r1_filename": "C4_REAL_P3_RAG_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip",
        "r1_package_id": "C4_REAL_P3_RAG_ROUTE_EXECUTION_R1",
        "max_output_tokens": 32,
        "frozen_configuration": RQ2 / "track_k_rag_specialist_execution/rag_specialist_frozen_configuration_v1.json",
        "frozen_configuration_sha256": "19fc104b55ed92ec6c9a988fe6664d5f062f92e473a5ff4d77f8c88aa871c7cc",
        "frozen_token_field": "maximum_output_tokens",
        "prompt": RQ2 / "track_k0_specialists/rag_specialist_prompt_frozen_v1.txt",
        "prompt_sha256": "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
        "schema": RQ2 / "track_k0_specialists/rag_specialist_schema_v1.json",
        "schema_sha256": "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
        "prompt_package": RQ2 / "track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json",
        "prompt_package_sha256": "60c5d9de78bf60c2b186c46ab3c935511c2a994bc8974a2bc965e5aa2ffc6f55",
        "example_sha256": "a932596e126ab66c054173bd1b9c454cbba9988e9d0b418da2d80c3e1df1e6eb",
        "response_schema_name": "c4_real_p3_rag_specialist_v1",
        "p3_consumption": "RAG_BIT",
        "scientific_member_sha256": {
            "requests.jsonl": REQUESTS_SHA256,
            "prompt.txt": "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
            "schema.json": "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
            "few_shot_examples.json": "39c5bfcfba2f4b91e61bdc05af358798ba72cb32741f699801fd6f4985250fb5",
        },
    },
    "MEMORY": {
        "method_id": "R2V2-MEMORY_SPECIALIST",
        "original_filename": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_PACKAGE_2026-09-01.zip",
        "original_package_id": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_V1",
        "original_sha256": "4ba5f4fe34d32fb4000af66209a0d6bb6d8bb9e6c7959d2a3ddbadaedec1d115",
        "r1_filename": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip",
        "r1_package_id": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_R1",
        "max_output_tokens": 32,
        "frozen_configuration": RQ2 / "track_l_memory_specialist_execution/memory_specialist_frozen_configuration_v1.json",
        "frozen_configuration_sha256": "8813854b4a73e4c07416e26db0b72f28ab1923f415053f8d48ad31b0eca0a3c3",
        "frozen_token_field": "maximum_output_tokens",
        "prompt": RQ2 / "track_k0_specialists/memory_specialist_prompt_frozen_v1.txt",
        "prompt_sha256": "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
        "schema": RQ2 / "track_k0_specialists/memory_specialist_schema_v1.json",
        "schema_sha256": "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
        "prompt_package": RQ2 / "track_k0_specialists/memory_specialist_final_full_dev_prompt_package_v1.json",
        "prompt_package_sha256": "ba27b9ee29960d0dfe67389f685e3338ff90b4ed71b57756a0e3abe890eb6875",
        "example_sha256": "57a7aecd53710a1587388711177d7564f4560f1a8729939d445268d2514d3eb4",
        "response_schema_name": "c4_real_p3_memory_specialist_v1",
        "p3_consumption": "MEMORY_BIT",
        "scientific_member_sha256": {
            "requests.jsonl": REQUESTS_SHA256,
            "prompt.txt": "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
            "schema.json": "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
            "few_shot_examples.json": "837057a389de21abd1f7426b43809bcf46e6a0d3a2880f5ddc56790471975b6c",
        },
    },
    "B4_PLANNING": {
        "method_id": "R2V2-B4_JOINT_LLM",
        "original_filename": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_PACKAGE_2026-09-01.zip",
        "original_package_id": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_V1",
        "original_sha256": "a7baa7fce67420df4e99fbc2cad51c0df258f5278150cec46181bae6bdbaed82",
        "r1_filename": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_PACKAGE_R1_2026-09-01.zip",
        "r1_package_id": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_R1",
        "max_output_tokens": 64,
        "frozen_configuration": RQ2 / "track_i_b4/b4_final_frozen_configuration_v2.json",
        "frozen_configuration_sha256": "12a75dd33298f6e1078b326e7c922eb92f2675ee87c7f7858fdf19494072d470",
        "frozen_token_field": "max_output_tokens",
        "prompt": RQ2 / "track_i_b4/b4_prompt_template_frozen_v1.txt",
        "prompt_sha256": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
        "schema": RQ2 / "track_i_b4/b4_response_schema_v2.json",
        "schema_sha256": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
        "prompt_package": RQ2 / "track_i_b4/b4_final_full_dev_prompt_package_v1.json",
        "prompt_package_sha256": "76af7a5c6c63630ded53fb2bdaf2b24cfcc10e087ac44d99717427e13db2297c",
        "example_sha256": "020ec80b8b592a62c9975b47bf5bc63c9dd86c029da05a6a4afd43440291aff2",
        "response_schema_name": "c4_real_p3_b4_route_v1",
        "p3_consumption": "PLANNING_BIT_ONLY_ALL_THREE_BITS_RETAINED",
        "scientific_member_sha256": {
            "requests.jsonl": REQUESTS_SHA256,
            "prompt.txt": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
            "schema.json": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
            "few_shot_examples.json": "76c1bd755a9ea6d794932c203d639c03594c38a5c99dafd4357104b7bdd6ebb7",
        },
    },
}

AUDIT_FILENAMES = {
    "configuration": "c4_real_frozen_component_configuration_verification_v1.json",
    "supersession": "c4_real_original_route_packages_supersession_v1.json",
    "identity": "c4_real_r1_old_new_identity_audit_v1.json",
    "contracts": "c4_real_r1_execution_contract_v1.json",
    "summaries": "c4_real_r1_route_package_summaries_v1.json",
    "build": "c4_real_i0_r1_build_report_v1.json",
}


class R1BuildError(RuntimeError):
    """Raised before publishing if any frozen identity differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise R1BuildError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    require(path.is_file(), f"Missing required file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        require(isinstance(current, Mapping) and key in current, f"Missing frozen field: {'.'.join(keys)}")
        current = current[key]
    return current


def verify_frozen_component(component: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    config_path = Path(spec["frozen_configuration"])
    require(
        sha_file(config_path) == spec["frozen_configuration_sha256"],
        f"{component} frozen configuration SHA-256 mismatch",
    )
    config = load_json(config_path)
    require(config.get("model_snapshot") == MODEL, f"{component} frozen model mismatch")
    require(config.get("temperature") == 0, f"{component} frozen temperature mismatch")
    require(
        config.get(spec["frozen_token_field"]) == spec["max_output_tokens"],
        f"{component} frozen output-token limit mismatch",
    )
    require(sha_file(Path(spec["prompt"])) == spec["prompt_sha256"], f"{component} prompt mismatch")
    require(sha_file(Path(spec["schema"])) == spec["schema_sha256"], f"{component} schema mismatch")
    require(
        sha_file(Path(spec["prompt_package"])) == spec["prompt_package_sha256"],
        f"{component} prompt-package mismatch",
    )
    prompt_package = load_json(Path(spec["prompt_package"]))
    examples = prompt_package.get("few_shot_examples")
    require(isinstance(examples, list), f"{component} few-shot examples missing")
    require(
        sha256(canonical_bytes(examples)) == spec["example_sha256"],
        f"{component} final example-set SHA-256 mismatch",
    )

    if component == "RAG":
        declared_example = _nested(
            config, "final_full_dev_examples_and_order", "specialist_example_set_sha256"
        )
        declared_schema = config.get("schema_sha256")
    elif component == "MEMORY":
        declared_example = _nested(
            config, "final_full_dev_examples_and_order", "specialist_example_set_sha256"
        )
        declared_schema = config.get("schema_sha256")
    else:
        declared_example = _nested(config, "full_dev_examples", "example_set_sha256")
        declared_schema = config.get("response_schema_v2_sha256")
    require(config.get("prompt_sha256") == spec["prompt_sha256"], f"{component} declared prompt hash mismatch")
    require(declared_schema == spec["schema_sha256"], f"{component} declared schema hash mismatch")
    require(declared_example == spec["example_sha256"], f"{component} declared examples hash mismatch")

    return {
        "method_id": spec["method_id"],
        "configuration_path": str(config_path.relative_to(ROOT)),
        "configuration_sha256": spec["frozen_configuration_sha256"],
        "model": MODEL,
        "temperature": 0,
        "max_output_tokens": spec["max_output_tokens"],
        "prompt_sha256": spec["prompt_sha256"],
        "schema_sha256": spec["schema_sha256"],
        "final_example_set_sha256": spec["example_sha256"],
        "verification_status": "PASS_ACTUAL_COMMITTED_FROZEN_CONFIGURATION",
    }


def _validate_request_population(data: bytes) -> None:
    require(sha256(data) == REQUESTS_SHA256, "Frozen requests SHA-256 mismatch")
    rows = parse_requests(data)
    require(len(rows) == 62, "Frozen request population is not 62")
    require(
        [row.get("scenario_id") for row in rows]
        == [f"U{number:03d}" for number in range(1, 63)],
        "Frozen scenario identity/order mismatch",
    )


def read_original_package(
    component: str, spec: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any]]:
    path = DOWNLOADS / spec["original_filename"]
    require(sha_file(path) == spec["original_sha256"], f"{component} original package hash mismatch")
    with ZipFile(path) as archive:
        names = sorted(archive.namelist())
        require(len(names) == len(set(names)), f"{component} original ZIP has duplicate members")
        require(all(not name.startswith(("/", "../")) and "/../" not in name for name in names), f"{component} unsafe ZIP member")
        require(all(not info.flag_bits & 0x1 for info in archive.infolist()), f"{component} encrypted ZIP member")
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        require(names == manifest.get("strict_allowlist"), f"{component} original allowlist mismatch")
        declared = manifest.get("member_sha256_excluding_self")
        require(isinstance(declared, dict), f"{component} original member hashes missing")
        for name, expected in declared.items():
            require(sha256(archive.read(name)) == expected, f"{component} original member mismatch: {name}")
        plan = json.loads(archive.read("EXECUTION_PLAN.json"))
        require(plan.get("package_id") == spec["original_package_id"], f"{component} original package ID mismatch")
        require(plan.get("max_output_tokens") == 64, f"{component} original defect is not the audited global 64")
        require(archive.read("ATTEMPT_JOURNAL.jsonl") == b"", f"{component} original attempt journal is not empty")
        require(archive.read("TERMINAL_JOURNAL.jsonl") == b"", f"{component} original terminal journal is not empty")
        scientific = {name: archive.read(name) for name in SCIENTIFIC_MEMBERS}
    observed_scientific = {name: sha256(data) for name, data in scientific.items()}
    require(
        observed_scientific == spec["scientific_member_sha256"],
        f"{component} original scientific-member identity mismatch",
    )
    _validate_request_population(scientific["requests.jsonl"])
    return scientific, {
        "component": component,
        "path": str(path),
        "package_id": spec["original_package_id"],
        "sha256": spec["original_sha256"],
        "status": ORIGINAL_PACKAGE_STATUS,
        "executed": False,
        "provider_calls": 0,
        "attempt_journal_bytes": 0,
        "terminal_journal_bytes": 0,
        "scientific_member_sha256": observed_scientific,
    }


def execution_contract(component: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-p3-route-execution-contract-r1-v1",
        "status": R1_PACKAGE_STATUS,
        "package_id": spec["r1_package_id"],
        "component": component,
        "authorization_scope": AUTHORIZATION_SCOPE,
        "authorization_environment_variable": AUTHORIZATION_ENVIRONMENT_VARIABLE,
        "authorization_environment_value": AUTHORIZATION_ENVIRONMENT_VALUE,
        "strict_authorization_record_fields": AUTHORIZATION_FIELDS,
        "output_directory_must_not_exist": True,
        "output_directory_created_atomically_before_first_provider_call": True,
        "package_members_are_read_only": True,
        "execution_outputs_are_external": True,
        "automatic_resume_permitted": False,
        "continuation_requires_new_direct_user_authorization": True,
        "serial_execution": True,
        "minimum_initial_request_start_interval_seconds": 2.0,
        "manual_retry_maximum": 1,
        "manual_retry_only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
        "retry_payload_must_be_identical": True,
        "correction_message_on_retry": False,
        "recognized_error_classes": ERROR_CLASSES,
        "durable_output_files": [
            "route_execution_preflight_receipt_v1.json",
            "route_attempt_records_v1.jsonl",
            "route_terminal_results_v1.jsonl",
            "route_error_registry_v1.jsonl",
            "route_execution_status_v1.json",
            "route_usage_and_cost_v1.json",
            "ROUTE_EXECUTION_REPORT.md",
        ],
        "accuracy_or_expected_label_comparison_permitted": False,
        "pricing_snapshot": {
            "status": "APPROXIMATE_ONLY_CURRENT_AT_FREEZE_DATE",
            "observed_at": FIXED_DATE,
            "source": "https://developers.openai.com/api/docs/models/gpt-4o-mini",
            "usd_per_1m_input_tokens": 0.15,
            "usd_per_1m_cached_input_tokens": 0.075,
            "usd_per_1m_output_tokens": 0.60,
        },
    }


def execution_plan(component: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-p3-route-execution-plan-r1-v2",
        "status": R1_PACKAGE_STATUS,
        "package_id": spec["r1_package_id"],
        "supersedes_package_id": spec["original_package_id"],
        "supersedes_package_sha256": spec["original_sha256"],
        "supersession_status": ORIGINAL_PACKAGE_STATUS,
        "route_component": component,
        "frozen_component_method_id": spec["method_id"],
        "frozen_configuration_path": str(Path(spec["frozen_configuration"]).relative_to(ROOT)),
        "frozen_configuration_sha256": spec["frozen_configuration_sha256"],
        "p3_consumption": spec["p3_consumption"],
        "model": MODEL,
        "endpoint": "OpenAI Chat Completions",
        "temperature": 0,
        "max_output_tokens": spec["max_output_tokens"],
        "max_output_tokens_source": "COMPONENT_SPEC_VERIFIED_AGAINST_FROZEN_RQ2_CONFIGURATION",
        "automatic_sdk_retries": 0,
        "manual_retry_maximum": 1,
        "manual_retry_only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
        "retry_payload_must_be_identical": True,
        "correction_message_on_retry": False,
        "streaming": False,
        "tools": "NONE",
        "serial_execution": True,
        "minimum_initial_request_start_interval_seconds": 2.0,
        "logical_call_count": 62,
        "maximum_physical_attempt_count": 124,
        "response_schema_name": spec["response_schema_name"],
        "semantic_input_fields": [
            "current_query",
            "current_page",
            "dashboard_context",
            "visible_conversation_history",
        ],
        "prompt_sha256": spec["prompt_sha256"],
        "schema_sha256": spec["schema_sha256"],
        "final_example_set_sha256": spec["example_sha256"],
        "requests_sha256": REQUESTS_SHA256,
        "execution_output_location": "EXTERNAL_NEW_OUTPUT_DIRECTORY",
        "automatic_resume_permitted": False,
        "route_accuracy_or_expected_label_comparison": False,
    }


def _readme(component: str, spec: Mapping[str, Any]) -> bytes:
    return (
        f"# {spec['r1_package_id']}\n\n"
        f"Status: `{R1_PACKAGE_STATUS}`. This package has not been executed.\n\n"
        f"It replaces the unexecuted `{spec['original_package_id']}` only to align the "
        f"{component} output-token limit with the committed frozen RQ2 component configuration. "
        "The requests, prompt, schema, few-shot examples, model, and temperature are unchanged.\n\n"
        "Execution requires a new external strict authorization record, the exact R1 environment "
        "gate, `--execute`, and a new output directory. The runner never writes into this package "
        "and does not resume automatically. I0-R1 itself authorizes zero provider calls.\n"
    ).encode("utf-8")


def deterministic_zip(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((stat.S_IFREG | 0o644) & 0xFFFF) << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def build_package_bytes(
    component: str,
    spec: Mapping[str, Any],
    scientific: Mapping[str, bytes],
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    plan = execution_plan(component, spec)
    contract = execution_contract(component, spec)
    files: dict[str, bytes] = {
        **scientific,
        "EXECUTION_PLAN.json": json_bytes(plan),
        "EXECUTION_CONTRACT.json": json_bytes(contract),
        "README.md": _readme(component, spec),
        "execute_route_package_v2.py": (HERE / "route_execution_runner_v2.py").read_bytes(),
        "validate_route_package_v1.py": (HERE / "route_package_validator_v1.py").read_bytes(),
    }
    scientific_hashes = {name: sha256(scientific[name]) for name in SCIENTIFIC_MEMBERS}
    require(scientific_hashes == spec["scientific_member_sha256"], f"{component} scientific bytes changed before R1 build")
    manifest = {
        "schema_version": "c4-real-route-package-manifest-r1-v1",
        "status": R1_PACKAGE_STATUS,
        "package_id": spec["r1_package_id"],
        "route_component": component,
        "strict_allowlist": sorted([*files, "PACKAGE_MANIFEST.json"]),
        "member_sha256_excluding_self": {
            name: sha256(data) for name, data in sorted(files.items())
        },
        "scientific_member_sha256": scientific_hashes,
        "scientific_members_byte_identical_to_original": True,
        "superseded_original": {
            "package_id": spec["original_package_id"],
            "path": str(DOWNLOADS / spec["original_filename"]),
            "sha256": spec["original_sha256"],
            "status": ORIGINAL_PACKAGE_STATUS,
            "executed": False,
        },
        "contains_mutable_execution_journals": False,
        "contains_credentials": False,
        "contains_gold": False,
        "contains_generated_routes": False,
        "contains_generated_answers": False,
        "contains_judge_outputs": False,
        "provider_calls_in_i0_r1": 0,
    }
    files["PACKAGE_MANIFEST.json"] = json_bytes(manifest)
    archive_bytes = deterministic_zip(files)
    _validate_archive_bytes(archive_bytes, component)
    return archive_bytes, plan, contract


def _validate_archive_bytes(data: bytes, component: str) -> dict[str, Any]:
    with ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), f"{component} R1 ZIP duplicate member")
        require(all(not info.flag_bits & 0x1 for info in archive.infolist()), f"{component} R1 ZIP encryption forbidden")
        with tempfile.TemporaryDirectory(prefix="c4-r1-validate-") as temporary:
            root = Path(temporary)
            for name in names:
                require(Path(name).name == name, f"{component} nested/unsafe package member")
                (root / name).write_bytes(archive.read(name))
            return validate_package_dir(root, expected_component=component)


def _publish_exclusive(path: Path, data: bytes) -> None:
    require(path.parent.is_dir(), f"Output parent does not exist: {path.parent}")
    require(not path.exists(), f"Refusing to overwrite existing output: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            handle.write(data)
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _git_bytes(relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{STARTING_HEAD}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def verify_i0_scientific_tree() -> list[dict[str, Any]]:
    rows = []
    for relative in I0_SCIENTIFIC_TRACKED_PATHS:
        current = (ROOT / relative).read_bytes()
        starting = _git_bytes(relative)
        require(current == starting, f"Committed I0 scientific artifact changed: {relative}")
        rows.append(
            {
                "path": relative,
                "starting_head_sha256": sha256(starting),
                "current_sha256": sha256(current),
                "byte_identical": True,
            }
        )
    return rows


def build_all(output_dir: Path, audit_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    audit_dir = audit_dir.resolve()
    targets = [output_dir / spec["r1_filename"] for spec in PACKAGE_SPECS.values()]
    audit_targets = [audit_dir / name for name in AUDIT_FILENAMES.values()]
    for target in [*targets, *audit_targets]:
        require(not target.exists(), f"Refusing to overwrite existing R1 artifact: {target}")

    scientific_tree = verify_i0_scientific_tree()
    configurations: dict[str, Any] = {}
    originals: dict[str, Any] = {}
    built: dict[str, tuple[bytes, dict[str, Any], dict[str, Any]]] = {}
    old_scientific: dict[str, dict[str, bytes]] = {}
    for component, spec in PACKAGE_SPECS.items():
        configurations[component] = verify_frozen_component(component, spec)
        scientific, original = read_original_package(component, spec)
        originals[component] = original
        old_scientific[component] = scientific
        built[component] = build_package_bytes(component, spec, scientific)

    summaries = []
    identities = []
    contracts = []
    for component, spec in PACKAGE_SPECS.items():
        archive_bytes, plan, contract = built[component]
        target = output_dir / spec["r1_filename"]
        _publish_exclusive(target, archive_bytes)
        require(sha_file(DOWNLOADS / spec["original_filename"]) == spec["original_sha256"], f"{component} original package changed during build")
        with ZipFile(target) as archive:
            r1_scientific = {name: archive.read(name) for name in SCIENTIFIC_MEMBERS}
        identity_members = {}
        for name in SCIENTIFIC_MEMBERS:
            old_bytes = old_scientific[component][name]
            new_bytes = r1_scientific[name]
            require(old_bytes == new_bytes, f"{component} old/R1 bytes differ: {name}")
            identity_members[name] = {
                "original_sha256": sha256(old_bytes),
                "r1_sha256": sha256(new_bytes),
                "byte_identical": True,
            }
        identities.append(
            {
                "component": component,
                "original_package_sha256": spec["original_sha256"],
                "r1_package_sha256": sha256(archive_bytes),
                "members": identity_members,
                "all_scientific_members_byte_identical": True,
            }
        )
        summaries.append(
            {
                "component": component,
                "package_id": spec["r1_package_id"],
                "path": str(target),
                "sha256": sha256(archive_bytes),
                "status": R1_PACKAGE_STATUS,
                "logical_call_count": plan["logical_call_count"],
                "maximum_physical_attempt_count": plan["maximum_physical_attempt_count"],
                "max_output_tokens": plan["max_output_tokens"],
                "provider_calls_in_i0_r1": 0,
            }
        )
        contracts.append(contract)

    audit_payloads = {
        "configuration": {
            "schema_version": "c4-real-frozen-component-configuration-verification-v1",
            "status": "PASS_ALL_COMPONENTS_MATCH_COMMITTED_RQ2_FREEZES",
            "components": configurations,
            "provider_calls": 0,
        },
        "supersession": {
            "schema_version": "c4-real-original-route-packages-supersession-v1",
            "status": ORIGINAL_PACKAGE_STATUS,
            "packages": [originals[name] for name in PACKAGE_SPECS],
            "packages_deleted": 0,
            "packages_overwritten": 0,
            "packages_executed": 0,
        },
        "identity": {
            "schema_version": "c4-real-r1-old-new-identity-audit-v1",
            "status": "PASS_SCIENTIFIC_MEMBERS_BYTE_IDENTICAL",
            "required_requests_sha256": REQUESTS_SHA256,
            "i0_scientific_tracked_artifacts": scientific_tree,
            "packages": identities,
            "all_i0_scientific_artifacts_unchanged": True,
            "all_old_r1_scientific_members_byte_identical": True,
        },
        "contracts": {
            "schema_version": "c4-real-r1-execution-contract-registry-v1",
            "status": R1_PACKAGE_STATUS,
            "contracts": contracts,
            "provider_calls_in_i0_r1": 0,
        },
        "summaries": {
            "schema_version": "c4-real-r1-route-package-summaries-v1",
            "status": R1_PACKAGE_STATUS,
            "packages": summaries,
            "package_count": 3,
            "logical_calls_per_package": 62,
            "maximum_physical_attempts_per_package": 124,
            "provider_calls_in_i0_r1": 0,
        },
        "build": {
            "schema_version": "c4-real-i0-r1-build-report-v1",
            "status": "READY_FOR_PARALLEL_C4_P3_ROUTE_EXECUTION_R1",
            "starting_head": STARTING_HEAD,
            "repair_type": "TRANSPORT_CONFIGURATION_ALIGNMENT_NOT_MODEL_TUNING",
            "components": {
                name: {"max_output_tokens": spec["max_output_tokens"]}
                for name, spec in PACKAGE_SPECS.items()
            },
            "scientific_inputs_regenerated": False,
            "provider_calls": 0,
            "route_calls": 0,
            "generation_calls": 0,
            "judge_calls": 0,
            "streamlit_launches": 0,
        },
    }
    for key, payload in audit_payloads.items():
        _publish_exclusive(audit_dir / AUDIT_FILENAMES[key], json_bytes(payload))

    return {
        "status": "READY_FOR_PARALLEL_C4_P3_ROUTE_EXECUTION_R1",
        "packages": summaries,
        "audit_artifacts": {
            key: str(audit_dir / filename) for key, filename in AUDIT_FILENAMES.items()
        },
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DOWNLOADS)
    parser.add_argument("--audit-dir", type=Path, default=HERE)
    args = parser.parse_args()
    result = build_all(args.output_dir, args.audit_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
