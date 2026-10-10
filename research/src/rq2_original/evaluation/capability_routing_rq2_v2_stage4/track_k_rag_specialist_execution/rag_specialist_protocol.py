"""Fail-closed protocol and manifest handling for Stage 4K.

This module performs no provider calls. It verifies the immutable Stage 4K-0
materials, creates the narrowly authorized V2 execution manifest, and exposes
small helpers shared by the synchronous execution and finalization modules.
"""

from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


TRACK_DIR = Path(__file__).resolve().parent
STAGE4_ROOT = TRACK_DIR.parent
K0_DIR = STAGE4_ROOT / "track_k0_specialists"
DEV_PROTOCOL_DIR = STAGE4_ROOT / "dev_protocol"
REPO_ROOT = TRACK_DIR.parents[2]

EXPECTED_WORKING_DIRECTORY = Path(
    "external_inputs/stage4-k-rag-specialist"
)
EXPECTED_BRANCH = "research/rq2-v2-stage4-k-rag-specialist-execution"
EXPECTED_STARTING_HEAD = "4dc4cd7d4e5cc0065f0acc194f3dce4beac27e32"
AUTHORIZED_MODEL_SNAPSHOT = "gpt-4o-mini-2024-07-18"
AUTHORIZED_STATUS = "AUTHORIZED_RAG_SPECIALIST_DEV_ONLY"
RUN_VERSION = "RQ2-V2-STAGE4K-RAG-SPECIALIST-DEV-EXECUTION-V1"
LOGICAL_CALL_CEILING = 64
PHYSICAL_ATTEMPT_CEILING = 128
CLIENT_MAX_RETRIES = 0
MAX_OUTPUT_TOKENS = 32
MIN_INITIAL_REQUEST_INTERVAL_SECONDS = 2.0
PRICING_REFERENCE_DATE = "2026-08-31"
INPUT_PRICE_USD_PER_MILLION = "0.15"
OUTPUT_PRICE_USD_PER_MILLION = "0.60"

EXPECTED_K0_MANIFEST_SHA256 = (
    "d743af72ac2b7a93c8daa099f4f389a7d36c4cac104325eb87f763601820e432"
)
EXPECTED_PROMPT_SHA256 = (
    "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c"
)
EXPECTED_SCHEMA_SHA256 = (
    "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866"
)
EXPECTED_V1_MANIFEST_SHA256 = (
    "e29efcb74aa16a608c0dfe16291c3d29be8556092f8b42014c6cb608500caec0"
)
EXPECTED_FOLD_PACKAGE_FILE_SHA256 = {
    "DEV-CV-FOLD-1": "956ce3754996cb6784ce7298848d68ba9cb3b126223d72b9d62bceb8c58f3d0c",
    "DEV-CV-FOLD-2": "d99564c46aa3c0926ffbcc583e10b795b70caf169680818d895eb905b2e38482",
    "DEV-CV-FOLD-3": "865eb528bc5808e89acbc1a97ccd2cc8753840f3b65122f6025b17fbf07b5b3b",
    "DEV-CV-FOLD-4": "4ffb5a32be91103dd84daeed3701a3ca308302e9de3e64124d17975fbc0ac63f",
}
EXPECTED_FINAL_PACKAGE_FILE_SHA256 = (
    "60c5d9de78bf60c2b186c46ab3c935511c2a994bc8974a2bc965e5aa2ffc6f55"
)
EXPECTED_FOLD_EXAMPLES_FILE_SHA256 = (
    "1b83e608e56dbabfe6d9a0509359fe994bd7d04028e0cb793c559559225ebddb"
)
EXPECTED_FINAL_EXAMPLES_FILE_SHA256 = (
    "ed6a66364d952041b3a2ce45c11c836646e9fe17e8d5173d8f6b6f4040261221"
)
EXPECTED_P2_CONTRACT_SHA256 = (
    "532bd513cc9b5f11003036ecbbc492f0305e359ae48f6cb133a05fe43d26f6ad"
)
EXPECTED_EVALUATION_PROTOCOL_SHA256 = (
    "92d9e675b5871e3c5af8865404893030ae9e7bbf611130d62463a42ab3b360bc"
)
EXPECTED_FOLD_HASH_REGISTRY_SHA256 = (
    "c6dc3c15b87160c4e802ef213d1197e794169896acae2bd9d82975d0621af6d2"
)
EXPECTED_SOURCE_VERIFICATION_SHA256 = (
    "8d090d5e1a4399cf3cdf81fb0fcb5c63f7693ff58e5007e82e5abb2d03348c1d"
)

V1_MANIFEST_PATH = K0_DIR / "rag_specialist_dev_execution_manifest_v1.jsonl"
V2_MANIFEST_PATH = TRACK_DIR / "rag_specialist_dev_execution_manifest_v2.jsonl"
MANIFEST_DIFF_PATH = TRACK_DIR / "rag_specialist_manifest_v1_v2_diff.json"
PRE_EXECUTION_VERIFICATION_PATH = (
    TRACK_DIR / "rag_specialist_pre_execution_verification_v1.json"
)
ATTEMPT_RECORDS_PATH = TRACK_DIR / "rag_specialist_attempt_records_v1.jsonl"
CALL_JOURNAL_PATH = TRACK_DIR / "rag_specialist_call_journal_v1.jsonl"
TERMINAL_RESULTS_PATH = TRACK_DIR / "rag_specialist_terminal_results_v1.jsonl"
PREDICTIONS_PATH = TRACK_DIR / "rag_specialist_predictions_v1.csv"
ERROR_REGISTRY_PATH = TRACK_DIR / "rag_specialist_error_registry_v1.csv"
USAGE_AND_COST_PATH = TRACK_DIR / "rag_specialist_usage_and_cost_v1.json"
METRICS_PATH = TRACK_DIR / "rag_specialist_metrics_v1.json"
FROZEN_CONFIGURATION_PATH = (
    TRACK_DIR / "rag_specialist_frozen_configuration_v1.json"
)
RESULTS_REPORT_PATH = TRACK_DIR / "RAG_SPECIALIST_DEV_EXECUTION_RESULTS.md"
VERIFICATION_REPORT_PATH = (
    TRACK_DIR / "RAG_SPECIALIST_DEV_EXECUTION_VERIFICATION.md"
)
STATUS_PATH = TRACK_DIR / "STATUS.md"
TEST_RESULTS_PATH = TRACK_DIR / "rag_specialist_test_results_v1.json"

EXECUTION_OUTPUT_PATHS = (
    ATTEMPT_RECORDS_PATH,
    CALL_JOURNAL_PATH,
    TERMINAL_RESULTS_PATH,
    PREDICTIONS_PATH,
    ERROR_REGISTRY_PATH,
    USAGE_AND_COST_PATH,
    METRICS_PATH,
    FROZEN_CONFIGURATION_PATH,
    RESULTS_REPORT_PATH,
    VERIFICATION_REPORT_PATH,
    STATUS_PATH,
    TEST_RESULTS_PATH,
)

ALLOWED_V1_V2_DIFF_PATHS = {
    "execution_authorization_status",
    "model_execution_authorization_status",
    "provider_facing_request.stream",
    "provider_facing_request_sha256",
    "run_version",
    "schema_version",
    "source_manifest_sha256",
    "source_stage4_k0_sha256_manifest_sha256",
}

SEMANTIC_TOP_LEVEL_FIELDS = (
    "logical_call_id",
    "annotation_case_id",
    "outer_fold",
    "fold_example_id_order_sha256",
    "fold_example_ids_in_order",
    "fold_example_set_sha256",
    "fold_prompt_package_sha256",
    "model_snapshot",
    "prompt_sha256",
    "semantic_validation_inputs",
    "specialist_schema_sha256",
    "validation_gold_in_provider_request",
)
SEMANTIC_INPUT_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)


class ExecutionBoundaryError(RuntimeError):
    """Raised before a provider call when a frozen boundary is not satisfied."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_worktree_boundary() -> dict[str, Any]:
    actual_cwd = Path.cwd().resolve()
    if actual_cwd != EXPECTED_WORKING_DIRECTORY.resolve():
        raise ExecutionBoundaryError(f"Unexpected working directory: {actual_cwd}")
    if REPO_ROOT.resolve() != EXPECTED_WORKING_DIRECTORY.resolve():
        raise ExecutionBoundaryError("Adapter repository root differs from authorized cwd")
    branch = _git_output("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise ExecutionBoundaryError(f"Unexpected branch: {branch}")
    head = _git_output("rev-parse", "HEAD")
    if head != EXPECTED_STARTING_HEAD:
        raise ExecutionBoundaryError(f"Unexpected starting HEAD: {head}")
    status_lines = [line for line in _git_output("status", "--short").splitlines() if line]
    allowed_prefix = (
        "evaluation/capability_routing_rq2_v2_stage4/"
        "track_k_rag_specialist_execution/"
    )
    for line in status_lines:
        path = line[3:]
        if not path.startswith(allowed_prefix):
            raise ExecutionBoundaryError(f"Out-of-scope worktree change: {line}")
    return {
        "working_directory": str(actual_cwd),
        "branch": branch,
        "head": head,
        "status_lines": status_lines,
        "out_of_scope_changes": 0,
    }


def verify_k0_source_hashes() -> dict[str, str]:
    manifest_path = K0_DIR / "STAGE4_K0_SHA256_MANIFEST.json"
    if sha256_file(manifest_path) != EXPECTED_K0_MANIFEST_SHA256:
        raise ExecutionBoundaryError("Stage 4K-0 SHA-256 manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if manifest.get("file_count") != 36 or not isinstance(entries, list):
        raise ExecutionBoundaryError("Stage 4K-0 hash manifest shape changed")
    observed: dict[str, str] = {}
    for entry in entries:
        relative = str(entry["path"])
        expected = str(entry["sha256"])
        path = K0_DIR / relative
        if not path.is_file():
            raise ExecutionBoundaryError(f"Frozen Stage 4K-0 file missing: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise ExecutionBoundaryError(f"Frozen Stage 4K-0 hash mismatch: {relative}")
        observed[relative] = actual
    if len(observed) != 36:
        raise ExecutionBoundaryError("Stage 4K-0 source hash count changed")
    return observed


def verify_external_dev_source_hashes() -> dict[str, str]:
    registry_path = K0_DIR / "specialist_source_verification_v1.json"
    if sha256_file(registry_path) != EXPECTED_SOURCE_VERIFICATION_SHA256:
        raise ExecutionBoundaryError("Specialist source-verification registry changed")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("status") != "PASS":
        raise ExecutionBoundaryError("Specialist source-verification status is not PASS")
    observed: dict[str, str] = {}
    for entry in registry.get("verified_files", []):
        relative = str(entry["name"])
        path = STAGE4_ROOT / relative
        if not path.is_file():
            raise ExecutionBoundaryError(f"Frozen DEV source missing: {relative}")
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise ExecutionBoundaryError(f"Frozen DEV source hash mismatch: {relative}")
        observed[relative] = actual
    if len(observed) != 8:
        raise ExecutionBoundaryError("Frozen DEV source count changed")
    governance = registry.get("governance", {})
    prohibited_true = [key for key, value in governance.items() if key != "dev_only" and value]
    if governance.get("dev_only") is not True or prohibited_true:
        raise ExecutionBoundaryError("Frozen source governance boundary changed")
    return observed


def _verify_package_settings(package: Mapping[str, Any], rendered_key: str) -> None:
    prompt_text = (K0_DIR / "rag_specialist_prompt_frozen_v1.txt").read_text(
        encoding="utf-8"
    )
    schema = json.loads((K0_DIR / "rag_specialist_schema_v1.json").read_text())
    if package["prompt_template"] != prompt_text:
        raise ExecutionBoundaryError("Fold package prompt text differs from frozen prompt")
    if package["specialist_schema"] != schema:
        raise ExecutionBoundaryError("Fold package schema differs from frozen schema")
    rendered = package[rendered_key]
    if set(rendered) != {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "response_format",
    }:
        raise ExecutionBoundaryError("Rendered package has unauthorized provider fields")
    if (
        rendered["model"] != AUTHORIZED_MODEL_SNAPSHOT
        or rendered["temperature"] != 0
        or rendered["max_tokens"] != MAX_OUTPUT_TOKENS
    ):
        raise ExecutionBoundaryError("Rendered package model settings changed")
    response_format = rendered["response_format"]
    if response_format != {
        "type": "json_schema",
        "json_schema": {
            "name": "rq2_v2_rag_specialist_v1",
            "strict": True,
            "schema": schema,
        },
    }:
        raise ExecutionBoundaryError("Rendered package strict schema changed")


def verify_required_protocol() -> dict[str, Any]:
    k0_hashes = verify_k0_source_hashes()
    external_hashes = verify_external_dev_source_hashes()
    required = {
        "rag_specialist_prompt_frozen_v1.txt": EXPECTED_PROMPT_SHA256,
        "rag_specialist_schema_v1.json": EXPECTED_SCHEMA_SHA256,
        "rag_specialist_dev_execution_manifest_v1.jsonl": EXPECTED_V1_MANIFEST_SHA256,
        "rag_specialist_fold_examples_v1.csv": EXPECTED_FOLD_EXAMPLES_FILE_SHA256,
        "rag_specialist_final_examples_v1.csv": EXPECTED_FINAL_EXAMPLES_FILE_SHA256,
        "rag_specialist_final_full_dev_prompt_package_v1.json": EXPECTED_FINAL_PACKAGE_FILE_SHA256,
        "p2_rag_specialist_composition_contract_v1.json": EXPECTED_P2_CONTRACT_SHA256,
        "specialist_evaluation_protocol_v1.json": EXPECTED_EVALUATION_PROTOCOL_SHA256,
        "specialist_fold_prompt_hashes_v1.json": EXPECTED_FOLD_HASH_REGISTRY_SHA256,
    }
    for relative, expected in required.items():
        if k0_hashes.get(relative) != expected:
            raise ExecutionBoundaryError(f"Required frozen identity mismatch: {relative}")

    fold_registry = json.loads(
        (K0_DIR / "specialist_fold_prompt_hashes_v1.json").read_text(
            encoding="utf-8"
        )
    )
    rag_registry = fold_registry["specialists"]["rag"]
    if (
        rag_registry["prompt_template_sha256"] != EXPECTED_PROMPT_SHA256
        or rag_registry["specialist_schema_sha256"] != EXPECTED_SCHEMA_SHA256
    ):
        raise ExecutionBoundaryError("RAG fold registry prompt/schema hash changed")

    fold_summary: dict[str, Any] = {}
    packages: dict[str, Mapping[str, Any]] = {}
    for fold_id, metadata in sorted(rag_registry["folds"].items()):
        if fold_id not in EXPECTED_FOLD_PACKAGE_FILE_SHA256:
            raise ExecutionBoundaryError(f"Unexpected RAG fold: {fold_id}")
        filename = metadata["prompt_package_filename"]
        if k0_hashes.get(filename) != EXPECTED_FOLD_PACKAGE_FILE_SHA256[fold_id]:
            raise ExecutionBoundaryError(f"Fold package file hash changed: {fold_id}")
        package = json.loads((K0_DIR / filename).read_text(encoding="utf-8"))
        _verify_package_settings(package, "complete_rendered_fold_package")
        complete_hash = canonical_sha256(package["complete_rendered_fold_package"])
        if complete_hash != metadata["complete_rendered_fold_package_sha256"]:
            raise ExecutionBoundaryError(f"Complete rendered package hash changed: {fold_id}")
        ids = package["source_b4_reuse"]["example_ids_in_order"]
        if (
            ids != metadata["example_ids"]
            or ids != package["source_b4_reuse"]["source_b4_example_id_order"]
            or package["source_b4_reuse"]["identity_and_order_exact"] is not True
        ):
            raise ExecutionBoundaryError(f"Fold example identity/order changed: {fold_id}")
        if len(package["few_shot_examples"]) != 8 or len(ids) != 8:
            raise ExecutionBoundaryError(f"Fold example count changed: {fold_id}")
        packages[fold_id] = package
        fold_summary[fold_id] = {
            "package_filename": filename,
            "package_file_sha256": k0_hashes[filename],
            "complete_rendered_package_sha256": complete_hash,
            "example_ids_in_order": ids,
            "example_id_order_sha256": metadata["example_id_order_sha256"],
            "specialist_example_set_sha256": metadata["specialist_example_set_sha256"],
        }

    if set(packages) != set(EXPECTED_FOLD_PACKAGE_FILE_SHA256):
        raise ExecutionBoundaryError("RAG fold package set changed")

    final_metadata = rag_registry["full_dev"]
    final_package = json.loads(
        (K0_DIR / final_metadata["prompt_package_filename"]).read_text(
            encoding="utf-8"
        )
    )
    _verify_package_settings(final_package, "complete_rendered_full_dev_package")
    final_complete_hash = canonical_sha256(
        final_package["complete_rendered_full_dev_package"]
    )
    final_ids = final_package["source_b4_reuse"]["example_ids_in_order"]
    if (
        final_complete_hash != final_metadata["complete_rendered_full_dev_package_sha256"]
        or final_ids != final_metadata["example_ids"]
        or final_ids != final_package["source_b4_reuse"]["source_b4_example_id_order"]
        or final_package["source_b4_reuse"]["identity_and_order_exact"] is not True
        or len(final_ids) != 8
    ):
        raise ExecutionBoundaryError("Final full-DEV example identity/order changed")

    records = load_jsonl(V1_MANIFEST_PATH)
    expected_logical_ids = [
        f"R2V2-RAG-SPECIALIST-DEV-{index:04d}"
        for index in range(1, LOGICAL_CALL_CEILING + 1)
    ]
    if len(records) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("RAG V1 manifest does not contain 64 records")
    if [record["logical_call_id"] for record in records] != expected_logical_ids:
        raise ExecutionBoundaryError("RAG V1 manifest logical order changed")
    case_ids = [record["annotation_case_id"] for record in records]
    if len(set(case_ids)) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("RAG V1 manifest annotation IDs are not unique")
    schema = json.loads((K0_DIR / "rag_specialist_schema_v1.json").read_text())
    for record in records:
        fold_id = record["outer_fold"]
        if fold_id not in packages:
            raise ExecutionBoundaryError("Manifest references an unexpected fold")
        package = packages[fold_id]
        metadata = rag_registry["folds"][fold_id]
        payload = record["provider_facing_request"]
        if set(payload) != {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "response_format",
        }:
            raise ExecutionBoundaryError("V1 provider request fields changed")
        if (
            payload["model"] != AUTHORIZED_MODEL_SNAPSHOT
            or payload["temperature"] != 0
            or payload["max_tokens"] != MAX_OUTPUT_TOKENS
            or payload["response_format"]["json_schema"]["schema"] != schema
            or payload["response_format"]["json_schema"]["strict"] is not True
        ):
            raise ExecutionBoundaryError("V1 provider request settings changed")
        frozen_messages = package["complete_rendered_fold_package"]["messages"]
        if payload["messages"][:-1] != frozen_messages:
            raise ExecutionBoundaryError("V1 prompt or few-shot messages changed")
        validation = record["semantic_validation_inputs"]
        if set(validation) != set(SEMANTIC_INPUT_FIELDS) or len(validation) != len(
            SEMANTIC_INPUT_FIELDS
        ):
            raise ExecutionBoundaryError("V1 semantic input field set changed")
        last_message = payload["messages"][-1]
        try:
            rendered_validation = json.loads(last_message["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ExecutionBoundaryError("V1 validation input rendering is not JSON") from error
        if last_message.get("role") != "user" or rendered_validation != validation:
            raise ExecutionBoundaryError("V1 validation input rendering changed")
        if canonical_sha256(payload) != record["provider_facing_request_sha256"]:
            raise ExecutionBoundaryError("V1 provider request hash changed")
        if (
            record["model_snapshot"] != AUTHORIZED_MODEL_SNAPSHOT
            or record["prompt_sha256"] != EXPECTED_PROMPT_SHA256
            or record["specialist_schema_sha256"] != EXPECTED_SCHEMA_SHA256
            or record["fold_example_ids_in_order"] != metadata["example_ids"]
            or record["fold_example_id_order_sha256"]
            != metadata["example_id_order_sha256"]
            or record["fold_example_set_sha256"]
            != metadata["specialist_example_set_sha256"]
            or record["fold_prompt_package_sha256"]
            != metadata["complete_rendered_fold_package_sha256"]
            or record["validation_gold_in_provider_request"] is not False
        ):
            raise ExecutionBoundaryError("V1 semantic request identity changed")
        serialized = canonical_json(record).upper()
        if "R2V2-TEST" in serialized or "TEST_ESCROW" in serialized:
            raise ExecutionBoundaryError("Prohibited TEST identifier in RAG manifest")

    gold_rows = {
        row["annotation_case_id"]: row
        for row in read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
        if row["annotation_case_id"] in set(case_ids)
    }
    if set(gold_rows) != set(case_ids):
        raise ExecutionBoundaryError("Frozen DEV Gold does not match RAG case IDs")
    if any(
        row["partition"] != "DEV"
        or row["final_dialogue_action"] != "ANSWER"
        or row["final_rag_required"] not in {"YES", "NO"}
        for row in gold_rows.values()
    ):
        raise ExecutionBoundaryError("Authorized RAG population is not DEV ANSWER only")
    if sum(row["final_rag_required"] == "YES" for row in gold_rows.values()) != 32:
        raise ExecutionBoundaryError("Frozen RAG Gold positive count changed")

    validation_folds = {
        row["annotation_case_id"]: row["fold_id"]
        for row in read_csv(DEV_PROTOCOL_DIR / "dev_cv_folds_v1.csv")
        if row["annotation_case_id"] in set(case_ids)
        and row["fold_role"] == "VALIDATION"
    }
    if len(validation_folds) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("Frozen validation-fold mapping changed")
    if any(
        validation_folds[record["annotation_case_id"]] != record["outer_fold"]
        for record in records
    ):
        raise ExecutionBoundaryError("Manifest outer-fold assignment changed")

    return {
        "status": "PASS_FROZEN_PROTOCOL_VERIFIED",
        "k0_source_hashes": k0_hashes,
        "external_dev_source_hashes": external_hashes,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "schema_sha256": EXPECTED_SCHEMA_SHA256,
        "v1_manifest_sha256": EXPECTED_V1_MANIFEST_SHA256,
        "p2_composition_contract_sha256": EXPECTED_P2_CONTRACT_SHA256,
        "evaluation_protocol_sha256": EXPECTED_EVALUATION_PROTOCOL_SHA256,
        "folds": fold_summary,
        "final_full_dev": {
            "package_filename": final_metadata["prompt_package_filename"],
            "package_file_sha256": EXPECTED_FINAL_PACKAGE_FILE_SHA256,
            "complete_rendered_package_sha256": final_complete_hash,
            "example_ids_in_order": final_ids,
            "example_id_order_sha256": final_metadata["example_id_order_sha256"],
            "specialist_example_set_sha256": final_metadata[
                "specialist_example_set_sha256"
            ],
        },
        "logical_call_count": len(records),
        "annotation_case_count": len(set(case_ids)),
        "rag_gold_yes_count": 32,
        "rag_gold_no_count": 32,
        "test_access_count": 0,
        "successful_case_level_b4_prediction_access_count": 0,
        "b4_error_file_access_count": 0,
    }


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


def _v2_record(v1: Mapping[str, Any]) -> dict[str, Any]:
    v2 = copy.deepcopy(v1)
    v2["schema_version"] = "rq2-v2-stage4-k-rag-specialist-dev-execution-record-v2"
    v2["model_execution_authorization_status"] = AUTHORIZED_STATUS
    v2["execution_authorization_status"] = AUTHORIZED_STATUS
    v2["run_version"] = RUN_VERSION
    v2["source_manifest_sha256"] = EXPECTED_V1_MANIFEST_SHA256
    v2["source_stage4_k0_sha256_manifest_sha256"] = EXPECTED_K0_MANIFEST_SHA256
    v2["provider_facing_request"]["stream"] = False
    v2["provider_facing_request_sha256"] = canonical_sha256(
        v2["provider_facing_request"]
    )
    return v2


def _normalize_v2_to_v1(v2: Mapping[str, Any], v1: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(v2)
    normalized["schema_version"] = v1["schema_version"]
    normalized["model_execution_authorization_status"] = v1[
        "model_execution_authorization_status"
    ]
    for key in (
        "execution_authorization_status",
        "run_version",
        "source_manifest_sha256",
        "source_stage4_k0_sha256_manifest_sha256",
    ):
        normalized.pop(key, None)
    normalized["provider_facing_request"].pop("stream", None)
    normalized["provider_facing_request_sha256"] = v1[
        "provider_facing_request_sha256"
    ]
    return normalized


def validate_manifest_pair(
    v1_records: Sequence[Mapping[str, Any]],
    v2_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(v1_records) != LOGICAL_CALL_CEILING or len(v2_records) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("V1 and V2 manifests must each contain 64 records")
    observed: set[str] = set()
    per_record: list[dict[str, Any]] = []
    for v1, v2 in zip(v1_records, v2_records, strict=True):
        if v1["logical_call_id"] != v2["logical_call_id"]:
            raise ExecutionBoundaryError("V1/V2 logical record alignment changed")
        differences = _diff_paths(v1, v2)
        if differences != ALLOWED_V1_V2_DIFF_PATHS:
            raise ExecutionBoundaryError(
                f"Unauthorized V1/V2 difference for {v1['logical_call_id']}: "
                f"{sorted(differences)}"
            )
        if _normalize_v2_to_v1(v2, v1) != v1:
            raise ExecutionBoundaryError("V2 does not normalize exactly to V1")
        for field in SEMANTIC_TOP_LEVEL_FIELDS:
            if v2[field] != v1[field]:
                raise ExecutionBoundaryError(f"Semantic field changed in V2: {field}")
        payload = v2["provider_facing_request"]
        if set(payload) != {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "response_format",
            "stream",
        }:
            raise ExecutionBoundaryError("V2 provider request has unauthorized fields")
        if (
            payload["model"] != AUTHORIZED_MODEL_SNAPSHOT
            or payload["temperature"] != 0
            or payload["max_tokens"] != MAX_OUTPUT_TOKENS
            or payload["stream"] is not False
            or v2["execution_authorization_status"] != AUTHORIZED_STATUS
            or v2["model_execution_authorization_status"] != AUTHORIZED_STATUS
            or v2["execution_status"] != "NOT_EXECUTED"
            or canonical_sha256(payload) != v2["provider_facing_request_sha256"]
        ):
            raise ExecutionBoundaryError("V2 execution configuration changed")
        observed.update(differences)
        per_record.append(
            {
                "logical_call_id": v1["logical_call_id"],
                "difference_paths": sorted(differences),
                "semantic_request_identity_preserved": True,
            }
        )
    return {
        "allowed_difference_paths": sorted(ALLOWED_V1_V2_DIFF_PATHS),
        "observed_difference_paths": sorted(observed),
        "normalized_v2_equals_v1": True,
        "semantic_request_identity_preserved": True,
        "record_count": len(v2_records),
        "per_record_differences": per_record,
    }


def prepare_authorized_manifest() -> dict[str, Any]:
    worktree = verify_worktree_boundary()
    protocol = verify_required_protocol()
    if any(path.exists() for path in (ATTEMPT_RECORDS_PATH, CALL_JOURNAL_PATH, TERMINAL_RESULTS_PATH)):
        raise ExecutionBoundaryError("Provider execution artifacts already exist")
    v1_records = load_jsonl(V1_MANIFEST_PATH)
    v2_records = [_v2_record(record) for record in v1_records]
    validation = validate_manifest_pair(v1_records, v2_records)
    v2_text = "".join(canonical_json(record) + "\n" for record in v2_records)
    if V2_MANIFEST_PATH.exists() and V2_MANIFEST_PATH.read_text(encoding="utf-8") != v2_text:
        raise ExecutionBoundaryError("Existing V2 manifest differs from deterministic V2")
    atomic_write_text(V2_MANIFEST_PATH, v2_text)
    diff_report = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-manifest-v1-v2-diff-v1",
        "status": "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY",
        "v1_manifest_path": str(V1_MANIFEST_PATH.relative_to(REPO_ROOT)),
        "v1_manifest_sha256": EXPECTED_V1_MANIFEST_SHA256,
        "v2_manifest_path": str(V2_MANIFEST_PATH.relative_to(REPO_ROOT)),
        "v2_manifest_sha256": sha256_file(V2_MANIFEST_PATH),
        "execution_authorization_status": AUTHORIZED_STATUS,
        "run_version": RUN_VERSION,
        "provider_configuration": {
            "model": AUTHORIZED_MODEL_SNAPSHOT,
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
            "sdk_transport_retries": CLIENT_MAX_RETRIES,
        },
        **validation,
    }
    atomic_write_json(MANIFEST_DIFF_PATH, diff_report)
    pre_verification = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-pre-execution-verification-v1",
        "status": "PASS_PRE_EXECUTION_FROZEN_IDENTITIES",
        "verified_at": utc_now(),
        "worktree": worktree,
        "protocol": protocol,
        "v2_manifest_sha256": diff_report["v2_manifest_sha256"],
        "v1_v2_diff_status": diff_report["status"],
        "execution_authorization_status": AUTHORIZED_STATUS,
        "logical_call_ceiling": LOGICAL_CALL_CEILING,
        "physical_attempt_ceiling": PHYSICAL_ATTEMPT_CEILING,
        "provider_calls_made_at_verification": 0,
        "test_access_count": 0,
        "memory_specialist_calls": 0,
        "composition_calls": 0,
        "p1_calls": 0,
        "rq3_calls": 0,
    }
    if PRE_EXECUTION_VERIFICATION_PATH.exists():
        existing = json.loads(PRE_EXECUTION_VERIFICATION_PATH.read_text(encoding="utf-8"))
        if (
            existing.get("status") != pre_verification["status"]
            or existing.get("protocol", {}).get("k0_source_hashes")
            != protocol["k0_source_hashes"]
            or existing.get("v2_manifest_sha256") != diff_report["v2_manifest_sha256"]
        ):
            raise ExecutionBoundaryError("Existing pre-execution verification differs")
        pre_verification = existing
    else:
        atomic_write_json(PRE_EXECUTION_VERIFICATION_PATH, pre_verification)
    return {
        "status": "PASS_AUTHORIZED_MANIFEST_PREPARED",
        "logical_calls": len(v2_records),
        "v2_manifest_sha256": diff_report["v2_manifest_sha256"],
        "diff_status": diff_report["status"],
        "provider_calls": 0,
    }


def verify_pre_http_boundaries() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verify_worktree_boundary()
    protocol = verify_required_protocol()
    if not V2_MANIFEST_PATH.is_file() or not MANIFEST_DIFF_PATH.is_file():
        raise ExecutionBoundaryError("Authorized V2 manifest preparation is missing")
    v1_records = load_jsonl(V1_MANIFEST_PATH)
    v2_records = load_jsonl(V2_MANIFEST_PATH)
    validation = validate_manifest_pair(v1_records, v2_records)
    diff_report = json.loads(MANIFEST_DIFF_PATH.read_text(encoding="utf-8"))
    if (
        diff_report.get("status") != "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY"
        or diff_report.get("v2_manifest_sha256") != sha256_file(V2_MANIFEST_PATH)
        or diff_report.get("v1_manifest_sha256") != EXPECTED_V1_MANIFEST_SHA256
        or diff_report.get("observed_difference_paths")
        != validation["observed_difference_paths"]
    ):
        raise ExecutionBoundaryError("V1/V2 diff report does not verify")
    if not PRE_EXECUTION_VERIFICATION_PATH.is_file():
        raise ExecutionBoundaryError("Pre-execution source-hash record is missing")
    pre = json.loads(PRE_EXECUTION_VERIFICATION_PATH.read_text(encoding="utf-8"))
    if (
        pre.get("status") != "PASS_PRE_EXECUTION_FROZEN_IDENTITIES"
        or pre.get("protocol", {}).get("k0_source_hashes")
        != protocol["k0_source_hashes"]
        or pre.get("protocol", {}).get("external_dev_source_hashes")
        != protocol["external_dev_source_hashes"]
    ):
        raise ExecutionBoundaryError("Pre-execution source hashes do not match current sources")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ExecutionBoundaryError("OPENAI_API_KEY is missing or empty")
    for path in EXECUTION_OUTPUT_PATHS:
        if path.exists():
            raise ExecutionBoundaryError(f"Execution output already exists: {path.name}")
    return v2_records, {
        "manifest_diff": diff_report,
        "protocol": protocol,
        "pre_execution_verification": pre,
    }


def runtime_summary() -> dict[str, Any]:
    try:
        sdk_version = importlib.metadata.version("openai")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = None
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "openai_sdk_version": sdk_version,
        "client_max_retries": CLIENT_MAX_RETRIES,
        "stream": False,
        "provider_calls": 0,
    }


def parse_strict_rag_response(content: str) -> dict[str, bool]:
    duplicate = False

    def no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicate = True
            result[key] = value
        return result

    try:
        parsed = json.loads(content, object_pairs_hook=no_duplicate_pairs)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("INVALID_JSON") from error
    if duplicate:
        raise ValueError("DUPLICATE_OBJECT_KEY")
    if not isinstance(parsed, dict) or set(parsed) != {"rag_required"}:
        raise ValueError("STRICT_SCHEMA_VALIDATION_FAILED")
    if type(parsed["rag_required"]) is not bool:
        raise ValueError("STRICT_SCHEMA_VALIDATION_FAILED")
    return {"rag_required": parsed["rag_required"]}


def validate_response_content(content: str) -> tuple[Any, bool, str | None]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None, False, "INVALID_JSON"
    try:
        strict = parse_strict_rag_response(content)
    except ValueError as error:
        return parsed, False, str(error)
    return strict, True, None


def should_retry(outcome: str, attempt_number: int) -> bool:
    return outcome == "INVALID_STRUCTURED_OUTPUT" and attempt_number == 1


_API_KEY_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")
_BEARER_PATTERN = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.IGNORECASE
)
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
