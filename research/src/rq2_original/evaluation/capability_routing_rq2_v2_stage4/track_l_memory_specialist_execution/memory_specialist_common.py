"""Shared fail-closed contracts for the Stage 4L Memory Specialist run."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence


TRACK_DIR = Path(__file__).resolve().parent
STAGE4_DIR = TRACK_DIR.parent
REPO_ROOT = TRACK_DIR.parents[2]
K0_DIR = STAGE4_DIR / "track_k0_specialists"
DEV_PROTOCOL_DIR = STAGE4_DIR / "dev_protocol"

V1_MANIFEST_PATH = K0_DIR / "memory_specialist_dev_execution_manifest_v1.jsonl"
V2_MANIFEST_PATH = TRACK_DIR / "memory_specialist_dev_execution_manifest_v2.jsonl"
MANIFEST_DIFF_PATH = TRACK_DIR / "memory_specialist_manifest_v1_v2_diff.json"
SOURCE_VERIFICATION_PATH = (
    TRACK_DIR / "memory_specialist_frozen_source_verification_v1.json"
)
PROMPT_PATH = K0_DIR / "memory_specialist_prompt_frozen_v1.txt"
SCHEMA_PATH = K0_DIR / "memory_specialist_schema_v1.json"
K0_SHA256_MANIFEST_PATH = K0_DIR / "STAGE4_K0_SHA256_MANIFEST.json"
FOLD_HASHES_PATH = K0_DIR / "specialist_fold_prompt_hashes_v1.json"
EVALUATION_PROTOCOL_PATH = K0_DIR / "specialist_evaluation_protocol_v1.json"
P3_CONTRACT_PATH = K0_DIR / "p3_capability_specialists_composition_contract_v1.json"

ATTEMPT_RECORDS_PATH = TRACK_DIR / "memory_specialist_attempt_records_v1.jsonl"
CALL_JOURNAL_PATH = TRACK_DIR / "memory_specialist_call_journal_v1.jsonl"
TERMINAL_RESULTS_PATH = TRACK_DIR / "memory_specialist_terminal_results_v1.jsonl"
PREDICTIONS_PATH = TRACK_DIR / "memory_specialist_predictions_v1.csv"
ERROR_REGISTRY_PATH = TRACK_DIR / "memory_specialist_error_registry_v1.csv"
USAGE_PATH = TRACK_DIR / "memory_specialist_usage_and_cost_v1.json"
METRICS_PATH = TRACK_DIR / "memory_specialist_metrics_v1.json"
FROZEN_CONFIGURATION_PATH = TRACK_DIR / "memory_specialist_frozen_configuration_v1.json"
RESULTS_REPORT_PATH = TRACK_DIR / "MEMORY_SPECIALIST_DEV_EXECUTION_RESULTS.md"
VERIFICATION_REPORT_PATH = (
    TRACK_DIR / "MEMORY_SPECIALIST_DEV_EXECUTION_VERIFICATION.md"
)
STATUS_PATH = TRACK_DIR / "STATUS.md"
TEST_REPORT_PATH = TRACK_DIR / "memory_specialist_test_report_v1.json"
OUTPUT_SHA256_MANIFEST_PATH = TRACK_DIR / "OUTPUT_SHA256_MANIFEST.json"

EXPECTED_WORKING_DIRECTORY = Path(
    "external_inputs/stage4-l-memory-specialist"
)
EXPECTED_BRANCH = "research/rq2-v2-stage4-l-memory-specialist-execution"
EXPECTED_STARTING_HEAD = "4dc4cd7d4e5cc0065f0acc194f3dce4beac27e32"
AUTHORIZED_MODEL_SNAPSHOT = "gpt-4o-mini-2024-07-18"
AUTHORIZED_STATUS = "AUTHORIZED_MEMORY_SPECIALIST_DEV_ONLY"
RUN_VERSION = "RQ2_V2_STAGE_4L_MEMORY_SPECIALIST_DEV_EXECUTION_V1"
EXPECTED_PROMPT_SHA256 = (
    "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04"
)
EXPECTED_SCHEMA_SHA256 = (
    "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7"
)
EXPECTED_V1_MANIFEST_SHA256 = (
    "403e738b95fd2e8a2a9930eacdf6c073b755544bd2ebd32ed5a0f2e279d1ac0d"
)
EXPECTED_K0_SHA256_MANIFEST_SHA256 = (
    "d743af72ac2b7a93c8daa099f4f389a7d36c4cac104325eb87f763601820e432"
)
EXPECTED_P3_CONTRACT_SHA256 = (
    "36e4c0589979f762568d29680a6d76b8c6116680072c051d00b2c5739e030288"
)
EXPECTED_EVALUATION_PROTOCOL_SHA256 = (
    "92d9e675b5871e3c5af8865404893030ae9e7bbf611130d62463a42ab3b360bc"
)

LOGICAL_CALL_CEILING = 64
PHYSICAL_ATTEMPT_CEILING = 128
CLIENT_MAX_RETRIES = 0
MAX_OUTPUT_TOKENS = 32
MIN_INITIAL_REQUEST_DELAY_SECONDS = 2.0
TARGET_FIELD = "memory_required"

TRACK_RELATIVE_PREFIX = (
    "evaluation/capability_routing_rq2_v2_stage4/"
    "track_l_memory_specialist_execution/"
)

DYNAMIC_OUTPUT_PATHS = (
    ATTEMPT_RECORDS_PATH,
    CALL_JOURNAL_PATH,
    TERMINAL_RESULTS_PATH,
    PREDICTIONS_PATH,
    ERROR_REGISTRY_PATH,
    USAGE_PATH,
    METRICS_PATH,
    FROZEN_CONFIGURATION_PATH,
    RESULTS_REPORT_PATH,
    VERIFICATION_REPORT_PATH,
    STATUS_PATH,
    TEST_REPORT_PATH,
    OUTPUT_SHA256_MANIFEST_PATH,
)

ALLOWED_V1_V2_DIFF_PATHS = {
    "schema_version",
    "model_execution_authorization_status",
    "execution_authorization_status",
    "run_version",
    "source_manifest_references",
    "provider_facing_request.stream",
    "provider_facing_request_sha256",
}

EXPECTED_SCHEMA = {
    "type": "object",
    "properties": {TARGET_FIELD: {"type": "boolean"}},
    "required": [TARGET_FIELD],
    "additionalProperties": False,
}

_API_KEY_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{8,}", re.IGNORECASE)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)


class ExecutionBoundaryError(RuntimeError):
    """Raised before an unauthorized or integrity-unsafe action."""


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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


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


def atomic_write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    atomic_write_text(
        path,
        "".join(canonical_json(record) + "\n" for record in records),
    )


def append_jsonl_fsync(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def verify_git_boundary(*, require_clean: bool) -> dict[str, Any]:
    observed_pwd = Path.cwd().resolve()
    if observed_pwd != EXPECTED_WORKING_DIRECTORY.resolve():
        raise ExecutionBoundaryError(f"Unexpected working directory: {observed_pwd}")
    branch = _git_output("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise ExecutionBoundaryError(f"Unexpected branch: {branch}")
    head = _git_output("rev-parse", "HEAD")
    if head != EXPECTED_STARTING_HEAD:
        raise ExecutionBoundaryError(f"Unexpected starting HEAD: {head}")
    status_lines = _git_output("status", "--short", "--untracked-files=all").splitlines()
    if require_clean and status_lines:
        raise ExecutionBoundaryError("Starting worktree is not clean")
    for line in status_lines:
        if not line:
            continue
        relative = line[3:]
        if not relative.startswith(TRACK_RELATIVE_PREFIX):
            raise ExecutionBoundaryError(f"Unrelated worktree change: {line}")
    return {
        "working_directory": str(observed_pwd),
        "branch": branch,
        "head": head,
        "require_clean": require_clean,
        "status_lines": status_lines,
    }


def _verify_package_hashes() -> dict[str, Any]:
    fold_hashes = load_json(FOLD_HASHES_PATH)["specialists"]["memory"]
    observed_folds: dict[str, Any] = {}
    for fold_id, expected in sorted(fold_hashes["folds"].items()):
        package_path = K0_DIR / expected["prompt_package_filename"]
        package = load_json(package_path)
        if package["outer_fold"] != fold_id:
            raise ExecutionBoundaryError(f"Fold package identity differs: {fold_id}")
        if canonical_sha256(package["few_shot_examples"]) != expected[
            "specialist_example_set_sha256"
        ]:
            raise ExecutionBoundaryError(f"Fold example-set hash differs: {fold_id}")
        example_ids = package["source_b4_reuse"]["example_ids_in_order"]
        if example_ids != expected["example_ids"]:
            raise ExecutionBoundaryError(f"Fold example order differs: {fold_id}")
        if canonical_sha256(example_ids) != expected["example_id_order_sha256"]:
            raise ExecutionBoundaryError(f"Fold example-order hash differs: {fold_id}")
        if canonical_sha256(package["complete_rendered_fold_package"]) != expected[
            "complete_rendered_fold_package_sha256"
        ]:
            raise ExecutionBoundaryError(f"Rendered fold hash differs: {fold_id}")
        observed_folds[fold_id] = copy.deepcopy(expected)

    expected_full = fold_hashes["full_dev"]
    full_path = K0_DIR / expected_full["prompt_package_filename"]
    full_package = load_json(full_path)
    full_ids = full_package["source_b4_reuse"]["example_ids_in_order"]
    if full_ids != expected_full["example_ids"]:
        raise ExecutionBoundaryError("Final full-DEV example order differs")
    if canonical_sha256(full_ids) != expected_full["example_id_order_sha256"]:
        raise ExecutionBoundaryError("Final full-DEV example-order hash differs")
    if canonical_sha256(full_package["few_shot_examples"]) != expected_full[
        "specialist_example_set_sha256"
    ]:
        raise ExecutionBoundaryError("Final full-DEV example-set hash differs")
    if canonical_sha256(full_package["complete_rendered_full_dev_package"]) != (
        expected_full["complete_rendered_full_dev_package_sha256"]
    ):
        raise ExecutionBoundaryError("Rendered final full-DEV package hash differs")
    return {"folds": observed_folds, "full_dev": copy.deepcopy(expected_full)}


def verify_frozen_sources() -> dict[str, Any]:
    if sha256_file(K0_SHA256_MANIFEST_PATH) != EXPECTED_K0_SHA256_MANIFEST_SHA256:
        raise ExecutionBoundaryError("Stage 4K-0 SHA-256 manifest hash differs")
    manifest = load_json(K0_SHA256_MANIFEST_PATH)
    if manifest.get("file_count") != 36 or len(manifest.get("files", [])) != 36:
        raise ExecutionBoundaryError("Stage 4K-0 file count differs")
    k0_hashes: list[dict[str, str]] = []
    for entry in manifest["files"]:
        relative = str(entry["path"])
        path = K0_DIR / relative
        if not path.is_file():
            raise ExecutionBoundaryError(f"Frozen Stage 4K-0 file missing: {relative}")
        observed = sha256_file(path)
        if observed != entry["sha256"]:
            raise ExecutionBoundaryError(f"Frozen Stage 4K-0 hash differs: {relative}")
        k0_hashes.append({"path": relative, "sha256": observed})

    required = {
        PROMPT_PATH: EXPECTED_PROMPT_SHA256,
        SCHEMA_PATH: EXPECTED_SCHEMA_SHA256,
        V1_MANIFEST_PATH: EXPECTED_V1_MANIFEST_SHA256,
        P3_CONTRACT_PATH: EXPECTED_P3_CONTRACT_SHA256,
        EVALUATION_PROTOCOL_PATH: EXPECTED_EVALUATION_PROTOCOL_SHA256,
    }
    for path, expected in required.items():
        if sha256_file(path) != expected:
            raise ExecutionBoundaryError(f"Required frozen identity differs: {path.name}")
    if load_json(SCHEMA_PATH) != EXPECTED_SCHEMA:
        raise ExecutionBoundaryError("Frozen Memory schema semantic value differs")

    upstream_index = load_json(K0_DIR / "specialist_source_verification_v1.json")
    if upstream_index.get("status") != "PASS":
        raise ExecutionBoundaryError("Frozen upstream source verification is not PASS")
    upstream_hashes: list[dict[str, str]] = []
    for entry in upstream_index["verified_files"]:
        relative = str(entry["name"])
        path = STAGE4_DIR / relative
        observed = sha256_file(path)
        if observed != entry["sha256"]:
            raise ExecutionBoundaryError(f"Frozen upstream hash differs: {relative}")
        upstream_hashes.append({"path": relative, "sha256": observed})

    package_hashes = _verify_package_hashes()
    return {
        "status": "PASS",
        "k0_manifest_sha256": sha256_file(K0_SHA256_MANIFEST_PATH),
        "k0_file_count": len(k0_hashes),
        "k0_files": k0_hashes,
        "upstream_file_count": len(upstream_hashes),
        "upstream_files": upstream_hashes,
        "required_identities": {
            "prompt_sha256": sha256_file(PROMPT_PATH),
            "schema_sha256": sha256_file(SCHEMA_PATH),
            "manifest_v1_sha256": sha256_file(V1_MANIFEST_PATH),
            "p3_composition_contract_sha256": sha256_file(P3_CONTRACT_PATH),
            "evaluation_protocol_sha256": sha256_file(EVALUATION_PROTOCOL_PATH),
        },
        "memory_prompt_packages": package_hashes,
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


def _normalize_v2_to_v1(
    v2_record: Mapping[str, Any], v1_record: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = copy.deepcopy(v2_record)
    normalized["schema_version"] = v1_record["schema_version"]
    normalized["model_execution_authorization_status"] = v1_record[
        "model_execution_authorization_status"
    ]
    normalized.pop("execution_authorization_status", None)
    normalized.pop("run_version", None)
    normalized.pop("source_manifest_references", None)
    normalized["provider_facing_request"].pop("stream", None)
    normalized["provider_facing_request_sha256"] = v1_record[
        "provider_facing_request_sha256"
    ]
    return normalized


def validate_manifest_pair(
    v1_records: Sequence[Mapping[str, Any]],
    v2_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(v1_records) != LOGICAL_CALL_CEILING or len(v2_records) != LOGICAL_CALL_CEILING:
        raise ExecutionBoundaryError("V1 and V2 manifests must each contain 64 records")
    expected_ids = [
        f"R2V2-MEMORY-SPECIALIST-DEV-{index:04d}" for index in range(1, 65)
    ]
    if [record["logical_call_id"] for record in v1_records] != expected_ids:
        raise ExecutionBoundaryError("Frozen V1 logical order differs")
    if [record["logical_call_id"] for record in v2_records] != expected_ids:
        raise ExecutionBoundaryError("Authorized V2 logical order differs")

    observed_paths: set[str] = set()
    per_record: list[dict[str, Any]] = []
    annotation_ids: set[str] = set()
    fold_counts: dict[str, int] = {}
    for old, new in zip(v1_records, v2_records, strict=True):
        differences = _diff_paths(old, new)
        if differences != ALLOWED_V1_V2_DIFF_PATHS:
            raise ExecutionBoundaryError(
                f"Unauthorized V1/V2 differences for {old['logical_call_id']}: "
                f"{sorted(differences)}"
            )
        if _normalize_v2_to_v1(new, old) != old:
            raise ExecutionBoundaryError("Normalized V2 does not equal frozen V1")
        if new["execution_authorization_status"] != AUTHORIZED_STATUS:
            raise ExecutionBoundaryError("V2 authorization status differs")
        if new["model_execution_authorization_status"] != AUTHORIZED_STATUS:
            raise ExecutionBoundaryError("V2 model authorization status differs")
        if new["run_version"] != RUN_VERSION:
            raise ExecutionBoundaryError("V2 run version differs")
        references = new["source_manifest_references"]
        if references != {
            "memory_specialist_dev_execution_manifest_v1": {
                "filename": V1_MANIFEST_PATH.name,
                "sha256": EXPECTED_V1_MANIFEST_SHA256,
            },
            "stage4_k0_sha256_manifest": {
                "filename": K0_SHA256_MANIFEST_PATH.name,
                "sha256": EXPECTED_K0_SHA256_MANIFEST_SHA256,
            },
        }:
            raise ExecutionBoundaryError("V2 source-manifest references differ")
        payload = new["provider_facing_request"]
        if set(payload) != {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "response_format",
            "stream",
        }:
            raise ExecutionBoundaryError("V2 provider payload fields differ")
        if (
            payload["model"] != AUTHORIZED_MODEL_SNAPSHOT
            or payload["temperature"] != 0
            or payload["max_tokens"] != MAX_OUTPUT_TOKENS
            or payload["stream"] is not False
        ):
            raise ExecutionBoundaryError("V2 model configuration differs")
        response_format = payload["response_format"]
        if response_format != {
            "type": "json_schema",
            "json_schema": {
                "name": "rq2_v2_memory_specialist_v1",
                "strict": True,
                "schema": EXPECTED_SCHEMA,
            },
        }:
            raise ExecutionBoundaryError("V2 strict response format differs")
        if canonical_sha256(payload) != new["provider_facing_request_sha256"]:
            raise ExecutionBoundaryError("V2 provider request hash differs")
        if new["execution_status"] != "NOT_EXECUTED":
            raise ExecutionBoundaryError("V2 pre-run execution status differs")
        if new["validation_gold_in_provider_request"] is not False:
            raise ExecutionBoundaryError("Validation Gold entered provider request")
        annotation_id = str(new["annotation_case_id"])
        if annotation_id in annotation_ids:
            raise ExecutionBoundaryError("Duplicate annotation case ID")
        annotation_ids.add(annotation_id)
        if "TEST" in annotation_id.upper():
            raise ExecutionBoundaryError("Prohibited partition identifier in V2")
        fold = str(new["outer_fold"])
        fold_counts[fold] = fold_counts.get(fold, 0) + 1
        serialized_payload = json.dumps(payload, ensure_ascii=False)
        for prohibited in (
            "annotation_case_id",
            "scenario_family_id",
            "dev_atomic_component_id",
            "outer_fold",
            "validation_gold",
            "partition",
            "R2V2-TEST",
            "TEST_ESCROW",
        ):
            if prohibited in serialized_payload:
                raise ExecutionBoundaryError(
                    f"Prohibited provider-payload field or identifier: {prohibited}"
                )
        observed_paths.update(differences)
        per_record.append(
            {
                "logical_call_id": old["logical_call_id"],
                "difference_paths": sorted(differences),
            }
        )
    if fold_counts != {f"DEV-CV-FOLD-{value}": 16 for value in range(1, 5)}:
        raise ExecutionBoundaryError("V2 fold counts differ")
    return {
        "record_count": len(v2_records),
        "unique_annotation_case_count": len(annotation_ids),
        "fold_counts": dict(sorted(fold_counts.items())),
        "allowed_difference_paths": sorted(ALLOWED_V1_V2_DIFF_PATHS),
        "observed_difference_paths": sorted(observed_paths),
        "normalized_v2_equals_v1": True,
        "all_semantic_request_elements_identical": True,
        "per_record_differences": per_record,
    }


def build_manifest_v2() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if sha256_file(V1_MANIFEST_PATH) != EXPECTED_V1_MANIFEST_SHA256:
        raise ExecutionBoundaryError("Frozen Memory manifest V1 hash differs")
    v1_records = load_jsonl(V1_MANIFEST_PATH)
    v2_records: list[dict[str, Any]] = []
    references = {
        "memory_specialist_dev_execution_manifest_v1": {
            "filename": V1_MANIFEST_PATH.name,
            "sha256": EXPECTED_V1_MANIFEST_SHA256,
        },
        "stage4_k0_sha256_manifest": {
            "filename": K0_SHA256_MANIFEST_PATH.name,
            "sha256": EXPECTED_K0_SHA256_MANIFEST_SHA256,
        },
    }
    for record in v1_records:
        updated = copy.deepcopy(record)
        updated["schema_version"] = (
            "rq2-v2-stage4-l-memory-specialist-dev-execution-record-v2"
        )
        updated["model_execution_authorization_status"] = AUTHORIZED_STATUS
        updated["execution_authorization_status"] = AUTHORIZED_STATUS
        updated["run_version"] = RUN_VERSION
        updated["source_manifest_references"] = copy.deepcopy(references)
        updated["provider_facing_request"]["stream"] = False
        updated["provider_facing_request_sha256"] = canonical_sha256(
            updated["provider_facing_request"]
        )
        v2_records.append(updated)
    validation = validate_manifest_pair(v1_records, v2_records)
    atomic_write_jsonl(V2_MANIFEST_PATH, v2_records)
    diff_report = {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-manifest-v1-v2-diff-v1",
        "status": "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY",
        "v1_manifest_filename": V1_MANIFEST_PATH.name,
        "v1_manifest_sha256": sha256_file(V1_MANIFEST_PATH),
        "v2_manifest_filename": V2_MANIFEST_PATH.name,
        "v2_manifest_sha256": sha256_file(V2_MANIFEST_PATH),
        "execution_authorization_status": AUTHORIZED_STATUS,
        "run_version": RUN_VERSION,
        **validation,
    }
    atomic_write_json(MANIFEST_DIFF_PATH, diff_report)
    return v2_records, diff_report


def verify_manifest_v2() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not V2_MANIFEST_PATH.is_file() or not MANIFEST_DIFF_PATH.is_file():
        raise ExecutionBoundaryError("Authorized manifest V2 preparation is missing")
    v1_records = load_jsonl(V1_MANIFEST_PATH)
    v2_records = load_jsonl(V2_MANIFEST_PATH)
    validation = validate_manifest_pair(v1_records, v2_records)
    diff_report = load_json(MANIFEST_DIFF_PATH)
    if diff_report.get("status") != "PASS_EXACT_ALLOWED_DIFFERENCES_ONLY":
        raise ExecutionBoundaryError("Manifest diff status differs")
    if diff_report.get("v1_manifest_sha256") != sha256_file(V1_MANIFEST_PATH):
        raise ExecutionBoundaryError("Recorded V1 manifest hash differs")
    if diff_report.get("v2_manifest_sha256") != sha256_file(V2_MANIFEST_PATH):
        raise ExecutionBoundaryError("Recorded V2 manifest hash differs")
    for field in (
        "record_count",
        "unique_annotation_case_count",
        "fold_counts",
        "allowed_difference_paths",
        "observed_difference_paths",
        "normalized_v2_equals_v1",
        "all_semantic_request_elements_identical",
    ):
        if diff_report.get(field) != validation[field]:
            raise ExecutionBoundaryError(f"Manifest diff field differs: {field}")
    return v2_records, diff_report


def write_pre_execution_source_verification(observed: Mapping[str, Any]) -> None:
    report = {
        "schema_version": "rq2-v2-stage4-l-memory-specialist-source-verification-v1",
        "status": "PASS_PRE_EXECUTION_POST_EXECUTION_PENDING",
        "pre_execution": copy.deepcopy(observed),
        "post_execution": None,
        "bytes_unchanged": None,
    }
    atomic_write_json(SOURCE_VERIFICATION_PATH, report)


def write_post_execution_source_verification(observed: Mapping[str, Any]) -> None:
    if not SOURCE_VERIFICATION_PATH.is_file():
        raise ExecutionBoundaryError("Pre-execution source verification is missing")
    report = load_json(SOURCE_VERIFICATION_PATH)
    before = report.get("pre_execution")
    if before != observed:
        raise ExecutionBoundaryError("Frozen source identities changed after execution")
    report["status"] = "PASS_PRE_AND_POST_EXECUTION_BYTES_UNCHANGED"
    report["post_execution"] = copy.deepcopy(observed)
    report["bytes_unchanged"] = True
    atomic_write_json(SOURCE_VERIFICATION_PATH, report)


def parse_strict_memory_response(content: str) -> dict[str, bool]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("INVALID_JSON") from error
    if type(parsed) is not dict:
        raise ValueError("STRICT_SCHEMA_VALIDATION_FAILED")
    if set(parsed) != {TARGET_FIELD}:
        raise ValueError("STRICT_SCHEMA_VALIDATION_FAILED")
    if type(parsed[TARGET_FIELD]) is not bool:
        raise ValueError("STRICT_SCHEMA_VALIDATION_FAILED")
    return {TARGET_FIELD: parsed[TARGET_FIELD]}


def validate_response_content(
    content: str,
) -> tuple[Any, bool, str | None]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None, False, "INVALID_JSON"
    try:
        strict = parse_strict_memory_response(content)
    except ValueError:
        return parsed, False, "STRICT_SCHEMA_VALIDATION_FAILED"
    return strict, True, None


def sanitize_provider_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = _API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT_PATTERN.sub("[REDACTED_SECRET_ASSIGNMENT]", text)
    return text[:2000]


def credential_or_partition_scan(paths: Sequence[Path]) -> dict[str, Any]:
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if _API_KEY_PATTERN.search(text) or _BEARER_PATTERN.search(text):
            raise ExecutionBoundaryError(f"Credential-shaped text found: {path.name}")
        upper = text.upper()
        if "R2V2-TEST" in upper or "TEST_ESCROW" in upper:
            raise ExecutionBoundaryError(
                f"Prohibited partition identifier found: {path.name}"
            )
    return {
        "status": "PASS",
        "files_scanned": len(paths),
        "credential_patterns_found": 0,
        "prohibited_partition_identifiers_found": 0,
    }


def write_output_sha256_manifest() -> dict[str, Any]:
    files: list[dict[str, str]] = []
    for path in sorted(TRACK_DIR.rglob("*")):
        if not path.is_file() or path == OUTPUT_SHA256_MANIFEST_PATH:
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".tmp"}:
            continue
        files.append(
            {
                "path": path.relative_to(TRACK_DIR).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema_version": "rq2-v2-stage4-l-output-sha256-manifest-v1",
        "hash_algorithm": "SHA-256",
        "manifest_self_hash_included": False,
        "file_count": len(files),
        "files": files,
    }
    atomic_write_json(OUTPUT_SHA256_MANIFEST_PATH, manifest)
    return manifest
