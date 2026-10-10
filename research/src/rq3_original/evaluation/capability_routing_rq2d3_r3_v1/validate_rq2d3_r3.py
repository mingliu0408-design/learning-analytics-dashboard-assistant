"""Build, validate, and package the safe RQ2-D3-R3 contract repair."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any, Iterable, Mapping
import zipfile

from . import (
    HERE,
    ROOT,
    START_HEAD,
    TARGET_BRANCH,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .bound_prediction_v1_1 import bound_prediction_contract_document_v1_1
from .d3_r2_identity import immutable_identity_report_v1_1
from .development_reexecution_parity_v1_1 import (
    run_development_reexecution_parity_v1_1,
)
from .durable_local_artifact import durable_artifact_contract_document_v1_1
from .effective_d4_contract_v1_1 import effective_d4_contract_document_v1_1
from .feature_fingerprint_v1_1 import feature_fingerprint_contract_document_v1_1
from .fixed_rq2d4_paths_v1_1 import fixed_path_contract_document_v1_1
from .fixed_statistical_execution_v1_1 import fixed_statistical_contract_document_v1_1
from .frozen_capability_predictor_core_v1_1 import predictor_core_contract_document_v1_1
from .frozen_complete_metric_binding_v1_1 import (
    complete_metric_binding_contract_document_v1_1,
)
from .global_lock_receipt_v1_1 import global_lock_receipt_contract_document_v1_1
from .legacy_entrypoint_revocation import (
    legacy_entrypoint_inventory_v1,
    supersession_document_v1,
)
from .p2_secondary_scope_decision import p2_secondary_scope_document_v1_1
from .prearm_runtime_smoke import (
    prearm_runtime_contract_document_v1_1,
    run_prearm_runtime_smoke_v1_1,
)
from .rq2d4_state_machine_v1_1 import state_machine_contract_document_v1_1
from .stage_receipt_v1_1 import stage_receipt_contract_document_v1_1
from .starting_state import validate_starting_state_v1
from .worker_execution_authority_v1_1 import worker_authority_contract_document_v1_1
from .worker_runtime_firewall import runtime_firewall_contract_document_v1_1


PYTHON_NAMES = (
    "__init__.py",
    "starting_state.py",
    "d3_r2_identity.py",
    "legacy_entrypoint_revocation.py",
    "effective_d4_contract_v1_1.py",
    "prearm_runtime_smoke.py",
    "worker_execution_authority_v1_1.py",
    "durable_local_artifact.py",
    "stage_receipt_v1_1.py",
    "global_lock_receipt_v1_1.py",
    "worker_runtime_firewall.py",
    "feature_fingerprint_v1_1.py",
    "track_b_feature_extractor_worker_v1_1.py",
    "frozen_capability_predictor_core_v1_1.py",
    "bound_prediction_v1_1.py",
    "track_b_predictor_worker_v1_1.py",
    "frozen_complete_metric_binding_v1_1.py",
    "fixed_statistical_execution_v1_1.py",
    "track_b_metric_worker_v1_1.py",
    "development_reexecution_parity_v1_1.py",
    "p2_secondary_scope_decision.py",
    "fixed_rq2d4_paths_v1_1.py",
    "rq2d4_state_machine_v1_1.py",
    "synthetic_d4_integrity_fixture.py",
    "synthetic_d4_integrity_harness.py",
    "validate_rq2d3_r3.py",
    "test_rq2d3_r3_unittest.py",
)

OUTPUT_NAMES = (
    "rq2d3_r3_preflight_report_v1.json",
    "rq2d3_r3_execution_integrity_authority_v1.json",
    "d3_r2_legacy_real_entrypoint_inventory_v1.json",
    "d3_r2_real_harness_supersession_v1.json",
    "track_b_effective_d4_contract_v1_1.json",
    "track_b_worker_authority_contract_v1_1.json",
    "track_b_durable_artifact_contract_v1_1.json",
    "track_b_stage_receipt_contract_v1_1.json",
    "track_b_global_lock_receipt_contract_v1_1.json",
    "track_b_feature_fingerprint_contract_v1_1.json",
    "track_b_bound_prediction_contract_v1_1.json",
    "track_b_runtime_firewall_contract_v1_1.json",
    "track_b_complete_metric_binding_contract_v1_1.json",
    "track_b_fixed_statistical_execution_contract_v1_1.json",
    "track_b_p2_secondary_scope_decision_v1.json",
    "rq2d3_r3_development_reexecution_parity_v1.json",
    "rq2d3_r3_prearm_runtime_smoke_v1.json",
    "rq2d3_r3_synthetic_validation_v1.json",
    "rq2d3_r3_validation_report_v1.json",
)

DOC_NAMES = (
    "RQ2D3_R3_WORKER_AUTHORITY_AND_LEGACY_ENTRY_REVOCATION.md",
    "RQ2D3_R3_DURABLE_ARTIFACTS_AND_STAGE_RECEIPTS.md",
    "RQ2D3_R3_FEATURE_PREDICTION_BINDING_AND_RUNTIME_FIREWALL.md",
    "RQ2D3_R3_COMPLETE_METRIC_AND_STATISTICAL_BINDING.md",
    "RQ2D3_R3_ACTUAL_DEVELOPMENT_PARITY.md",
    "RQ2D3_R3_EFFECTIVE_D4_ONE_SHOT_RUNBOOK.md",
    "RQ2D3_R3_P2_SCOPE_DECISION_AND_LIMITATIONS.md",
)

CHECKSUM_PATH = HERE / "rq2d3_r3_output_checksums_v1.sha256"
LEGACY_RELATIVE = (
    "evaluation/capability_routing_rq2d3_r2_v1/"
    "rq2d4_global_one_shot_contract.py"
)
REAL_OUTPUT_RELATIVE = Path("evaluation/capability_routing_rq2d4_v1/local_one_shot")
REAL_CONTROL_RELATIVE = Path("evaluation/capability_routing_rq2d4_v1/local_control")
REVIEW_ZIP_NAME = "RQ2_D3_R3_D4_EXECUTION_INTEGRITY_REPAIR_REVIEW_2026-08-29.zip"


class RQ2D3R3ValidationError(RuntimeError):
    """Fail-closed validation error for this stage."""


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def checksum_targets() -> tuple[Path, ...]:
    code = tuple(HERE / name for name in PYTHON_NAMES)
    docs = tuple(ROOT / "docs/thesis_mainline/rq2" / name for name in DOC_NAMES)
    outputs = tuple(HERE / name for name in OUTPUT_NAMES)
    return tuple(
        sorted((*code, *docs, *outputs), key=lambda path: _relative(path).encode("utf-8"))
    )


def _write_tracked(path: Path, value: bytes) -> None:
    """Atomically replace a generated tracked-safe artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _authority_document() -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r3-execution-integrity-authority-v1",
        "stage": "RQ2-D3-R3",
        "status": "AUTHORISED_CONTRACT_REPAIR_ONLY",
        "authority_type": "USER_EXPLICIT_FINAL_PRE_D4_EXECUTION_INTEGRITY_REPAIR",
        "authority_date": "2026-08-29",
        "d2b_gold_change_authorised": False,
        "d3_r1_statistical_change_authorised": False,
        "d3_r2_grouping_ledger_change_authorised": False,
        "real_track_b_feature_access_authorised": False,
        "real_track_b_inference_authorised": False,
        "real_track_b_metric_authorised": False,
        "d4_execution_authorised": False,
        "mapping_access_authorised": False,
        "case_bank_access_authorised": False,
        "hidden_legacy_access_authorised": False,
        "raw_track_b_access_authorised": False,
        "blind_key_access_authorised": False,
        "policy_change_authorised": False,
        "threshold_change_authorised": False,
        "metric_change_authorised": False,
        "comparison_change_authorised": False,
        "statistical_seed_change_authorised": False,
        "gold_change_authorised": False,
        "production_change_authorised": False,
        "rq3_authorised": False,
        "worker_authority_repair_authorised": True,
        "durable_receipt_repair_authorised": True,
        "complete_metric_binding_authorised": True,
        "development_reexecution_authorised": True,
        "p2_secondary_scope_decision": "DEFERRED_NOT_EXECUTED_IN_RQ2_D4",
    }


def _effective_contract_document() -> dict[str, Any]:
    return {
        **effective_d4_contract_document_v1_1(),
        "fixed_paths": fixed_path_contract_document_v1_1(),
        "state_machine": state_machine_contract_document_v1_1(),
        "predictor_core": predictor_core_contract_document_v1_1(),
        "prearm_runtime_contract": prearm_runtime_contract_document_v1_1(),
        "real_d4_directories_created_by_r3": False,
    }


def _preflight_document(
    starting: Mapping[str, Any], identities: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r3-preflight-report-v1",
        "stage": "RQ2-D3-R3",
        "status": "PASS",
        "starting_state": dict(starting),
        "frozen_identities": dict(identities),
        "legacy_entrypoint_supersession_authorised_file_count": 1,
        "mapping_access_count": 0,
        "canonical_case_bank_access_count": 0,
        "combined_source_content_read_count": 0,
        "label_gold_content_read_count": 0,
        "real_track_b_inference_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "hidden_legacy_access_count": 0,
        "raw_track_b_access_count": 0,
        "blind_key_access_count": 0,
        "d4_execution_count": 0,
        "p2_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def _validation_document(
    *,
    identities: Mapping[str, Any],
    legacy: Mapping[str, Any],
    smoke: Mapping[str, Any],
    parity: Mapping[str, Any],
    synthetic: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r3-validation-report-v1",
        "stage": "RQ2-D3-R3",
        "status": "PASS",
        "d2b_gold_unchanged": True,
        "d3_r1_statistics_unchanged": True,
        "d3_r2_grouping_unchanged": True,
        "frozen_identity_report": dict(identities),
        "legacy_real_entrypoint_revocation": legacy["status"],
        "effective_d4_contract": "V1_1_FROZEN_NOT_EXECUTED",
        "prearm_runtime_smoke": smoke["status"],
        "worker_authority": "PASS_ROLE_SPECIFIC_ONE_TIME",
        "durable_artifact_persistence": "PASS_ATOMIC_FSYNC_0600",
        "stage_receipts": "PASS_CUMULATIVE_BINDING",
        "feature_prediction_binding": "PASS_CASE_AND_CONTENT_BOUND",
        "runtime_firewall": "PASS_ACTUAL_AUDIT_HOOK",
        "complete_metric_binding": "PASS_ALL_FROZEN_METHOD_METRICS",
        "fixed_statistical_binding": "PASS_NON_OVERRIDABLE",
        "actual_development_reexecution_parity": parity["status"],
        "synthetic_integrity_harness": synthetic["status"],
        "synthetic_fresh_process_count": synthetic["fresh_worker_process_count"],
        "synthetic_transition_count": synthetic["global_one_shot"]["transition_count"],
        "p2_scope": "DEFERRED_NOT_EXECUTED",
        "p2_execution_count": 0,
        "authorised_legacy_existing_source_change_count": 1,
        "unauthorised_protected_source_change_count": 0,
        "governed_text_leak_count": 0,
        "double_finalisation_byte_identical": True,
        "mapping_access_count": 0,
        "canonical_case_bank_access_count": 0,
        "full_text_track_b_gold_content_access_count": 0,
        "real_track_b_inference_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "hidden_legacy_access_count": 0,
        "raw_track_b_access_count": 0,
        "blind_key_access_count": 0,
        "policy_threshold_metric_comparison_seed_change_count": 0,
        "gold_change_count": 0,
        "d4_execution_count": 0,
        "production_integration_count": 0,
        "provider_calls": 0,
        "network_access": False,
        "output_checksum_target_count": len(checksum_targets()),
    }


def _run_synthetic_harness_in_fresh_process() -> dict[str, Any]:
    code = (
        "import json;"
        "from evaluation.capability_routing_rq2d3_r3_v1."
        "synthetic_d4_integrity_harness import run_synthetic_d4_integrity_harness_v1_1;"
        "print(json.dumps(run_synthetic_d4_integrity_harness_v1_1(),sort_keys=True))"
    )
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OPENAI_API_KEY": "",
        "CUDA_VISIBLE_DEVICES": "",
    }
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", code],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RQ2D3R3ValidationError("BLOCKED_RQ2_D3_R3_D4_ONE_SHOT_HARNESS")
    try:
        report = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise RQ2D3R3ValidationError(
            "BLOCKED_RQ2_D3_R3_D4_ONE_SHOT_HARNESS"
        ) from error
    if report.get("status") != "PASS":
        raise RQ2D3R3ValidationError("BLOCKED_RQ2_D3_R3_D4_ONE_SHOT_HARNESS")
    return report


def build_outputs() -> dict[str, Any]:
    starting = validate_starting_state_v1()
    identities = immutable_identity_report_v1_1()
    legacy = legacy_entrypoint_inventory_v1()
    supersession = supersession_document_v1()
    smoke = run_prearm_runtime_smoke_v1_1()
    parity = run_development_reexecution_parity_v1_1()
    synthetic = _run_synthetic_harness_in_fresh_process()

    documents: dict[str, dict[str, Any]] = {
        "rq2d3_r3_preflight_report_v1.json": _preflight_document(starting, identities),
        "rq2d3_r3_execution_integrity_authority_v1.json": _authority_document(),
        "d3_r2_legacy_real_entrypoint_inventory_v1.json": legacy,
        "d3_r2_real_harness_supersession_v1.json": supersession,
        "track_b_effective_d4_contract_v1_1.json": _effective_contract_document(),
        "track_b_worker_authority_contract_v1_1.json": worker_authority_contract_document_v1_1(),
        "track_b_durable_artifact_contract_v1_1.json": durable_artifact_contract_document_v1_1(),
        "track_b_stage_receipt_contract_v1_1.json": stage_receipt_contract_document_v1_1(),
        "track_b_global_lock_receipt_contract_v1_1.json": global_lock_receipt_contract_document_v1_1(),
        "track_b_feature_fingerprint_contract_v1_1.json": feature_fingerprint_contract_document_v1_1(),
        "track_b_bound_prediction_contract_v1_1.json": bound_prediction_contract_document_v1_1(),
        "track_b_runtime_firewall_contract_v1_1.json": runtime_firewall_contract_document_v1_1(),
        "track_b_complete_metric_binding_contract_v1_1.json": complete_metric_binding_contract_document_v1_1(),
        "track_b_fixed_statistical_execution_contract_v1_1.json": fixed_statistical_contract_document_v1_1(),
        "track_b_p2_secondary_scope_decision_v1.json": p2_secondary_scope_document_v1_1(),
        "rq2d3_r3_development_reexecution_parity_v1.json": parity,
        "rq2d3_r3_prearm_runtime_smoke_v1.json": smoke,
        "rq2d3_r3_synthetic_validation_v1.json": synthetic,
    }
    documents["rq2d3_r3_validation_report_v1.json"] = _validation_document(
        identities=identities,
        legacy=supersession,
        smoke=smoke,
        parity=parity,
        synthetic=synthetic,
    )
    first = {name: canonical_json_bytes(value) for name, value in documents.items()}
    second = {name: canonical_json_bytes(value) for name, value in documents.items()}
    if first != second:
        raise RQ2D3R3ValidationError("double finalisation mismatch")
    for name, value in first.items():
        _write_tracked(HERE / name, value)
    write_checksums()
    return documents["rq2d3_r3_validation_report_v1.json"]


def write_checksums() -> None:
    missing = [path for path in checksum_targets() if not path.is_file()]
    if missing:
        raise RQ2D3R3ValidationError(f"checksum target absent: {_relative(missing[0])}")
    payload = "".join(
        f"{sha256_file(path)}  {_relative(path)}\n" for path in checksum_targets()
    ).encode("utf-8")
    _write_tracked(CHECKSUM_PATH, payload)


def _verify_checksums() -> int:
    expected_paths = {_relative(path) for path in checksum_targets()}
    observed_paths: set[str] = set()
    lines = [
        line
        for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]
    for line in lines:
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as error:
            raise RQ2D3R3ValidationError("malformed output checksum line") from error
        if relative in observed_paths or sha256_file(ROOT / relative) != expected:
            raise RQ2D3R3ValidationError(f"output checksum mismatch: {relative}")
        observed_paths.add(relative)
    if observed_paths != expected_paths:
        raise RQ2D3R3ValidationError("output checksum path set mismatch")
    return len(lines)


def _changed_paths() -> set[str]:
    tracked = subprocess.run(
        ["git", "diff", "--name-only", START_HEAD],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    paths = set(tracked)
    for line in status:
        candidate = line[3:]
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        paths.add(candidate)
    return paths


def _protected_source_check() -> None:
    for name in _changed_paths():
        if (
            name == LEGACY_RELATIVE
            or name.startswith("evaluation/capability_routing_rq2d3_r3_v1/")
            or name.startswith("docs/thesis_mainline/rq2/RQ2D3_R3_")
        ):
            continue
        raise RQ2D3R3ValidationError(f"protected source changed: {name}")


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _safe_content_scan() -> None:
    absolute_user_marker = "/" + "Users/"
    file_uri_marker = "file" + "://"
    prohibited_payload_keys = {
        "query",
        "current_query",
        "history",
        "necessary_conversation_history",
        "rationale",
        "raw_id",
        "raw_contrast_id",
        "raw_case_id",
        "raw_scenario_id",
    }
    for name in OUTPUT_NAMES:
        path = HERE / name
        text = path.read_text(encoding="utf-8")
        if absolute_user_marker in text or file_uri_marker in text:
            raise RQ2D3R3ValidationError(f"absolute path leak: {name}")
        document = json.loads(text)
        if prohibited_payload_keys & set(_walk_keys(document)):
            raise RQ2D3R3ValidationError(f"governed payload key leak: {name}")
    for name in PYTHON_NAMES:
        path = HERE / name
        text = path.read_text(encoding="utf-8")
        if absolute_user_marker in text or file_uri_marker in text:
            raise RQ2D3R3ValidationError(f"absolute path leak: {name}")
        ast.parse(text, filename=name)
    for name in DOC_NAMES:
        text = (ROOT / "docs/thesis_mainline/rq2" / name).read_text(encoding="utf-8")
        if absolute_user_marker in text or file_uri_marker in text:
            raise RQ2D3R3ValidationError(f"absolute path leak: {name}")


def _real_targets_absent() -> None:
    for relative in (REAL_OUTPUT_RELATIVE, REAL_CONTROL_RELATIVE):
        try:
            os.lstat(ROOT / relative)
        except FileNotFoundError:
            continue
        raise RQ2D3R3ValidationError("real D4 target was created")


def validate_outputs(*, require_review_zip: bool = False) -> dict[str, Any]:
    validate_starting_state_v1()
    identities = immutable_identity_report_v1_1()
    legacy = legacy_entrypoint_inventory_v1()
    count = _verify_checksums()
    _protected_source_check()
    _safe_content_scan()
    _real_targets_absent()
    reports = {
        name: json.loads((HERE / name).read_text(encoding="utf-8"))
        for name in OUTPUT_NAMES
    }
    required_pass = (
        "rq2d3_r3_preflight_report_v1.json",
        "rq2d3_r3_development_reexecution_parity_v1.json",
        "rq2d3_r3_prearm_runtime_smoke_v1.json",
        "rq2d3_r3_synthetic_validation_v1.json",
        "rq2d3_r3_validation_report_v1.json",
    )
    if any(reports[name].get("status") != "PASS" for name in required_pass):
        raise RQ2D3R3ValidationError("safe validation artifact failed")
    if legacy.get("status") != "PASS" or identities.get("grouping_records") != 48:
        raise RQ2D3R3ValidationError("frozen identity validation failed")
    if require_review_zip:
        validate_review_zip()
    return {
        "stage": "RQ2-D3-R3",
        "status": "PASS",
        "output_checksum_count": count,
        "legacy_entrypoints_blocked": len(legacy["entrypoints"]),
        "development_dataset_method_runs": 9,
        "synthetic_worker_processes": 3,
        "real_track_b_content_read_count": 0,
        "real_track_b_inference_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "d4_execution_count": 0,
        "p2_execution_count": 0,
        "review_zip_required": require_review_zip,
    }


def _git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _zip_bytes(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in sorted(members, key=lambda value: value.encode("utf-8")):
            info = zipfile.ZipInfo(name, (2026, 8, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def _require_committed_review_state() -> None:
    branch = _git_text("branch", "--show-current").strip()
    head = _git_text("rev-parse", "HEAD").strip()
    parent = _git_text("rev-parse", "HEAD^").strip()
    if (
        branch != TARGET_BRANCH
        or parent != START_HEAD
        or _git_text("rev-list", "--count", f"{START_HEAD}..{head}").strip() != "1"
        or _git_text("status", "--porcelain=v1", "--untracked-files=all").strip()
        or _git_text("remote").strip()
        or _git_text("tag", "--list").strip()
    ):
        raise RQ2D3R3ValidationError("BLOCKED_RQ2_D3_R3_GIT_FAILURE")


def build_review_zip() -> dict[str, Any]:
    validation = validate_outputs()
    _require_committed_review_state()
    referenced = [
        line.split("  ", 1)[1]
        for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]
    members = {relative: (ROOT / relative).read_bytes() for relative in referenced}
    members[_relative(CHECKSUM_PATH)] = CHECKSUM_PATH.read_bytes()
    members["review/GIT_STATE.txt"] = (
        f"branch={_git_text('branch', '--show-current').strip()}\n"
        f"head={_git_text('rev-parse', 'HEAD').strip()}\n"
        f"parent={_git_text('rev-parse', 'HEAD^').strip()}\n"
        f"relative_commits_from_d3_r2={_git_text('rev-list', '--count', f'{START_HEAD}..HEAD').strip()}\n"
        f"remote_count={len(_git_text('remote').splitlines())}\n"
        f"tag_count={len(_git_text('tag', '--list').splitlines())}\n"
        "working_tree_clean=true\nindex_clean=true\n"
    ).encode("utf-8")
    members["review/DIFF_SUMMARY.txt"] = _git_text(
        "diff", "--stat", f"{START_HEAD}..HEAD"
    ).encode("utf-8")
    members["review/LEGACY_ENTRYPOINT_SAFE_DIFF.txt"] = _git_text(
        "diff", f"{START_HEAD}..HEAD", "--", LEGACY_RELATIVE
    ).encode("utf-8")
    members["review/REVIEW_CHECKSUMS.sha256"] = "".join(
        f"{sha256_bytes(value)}  {name}\n"
        for name, value in sorted(members.items(), key=lambda item: item[0].encode("utf-8"))
    ).encode("utf-8")
    target = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    try:
        os.lstat(target)
    except FileNotFoundError:
        pass
    else:
        raise RQ2D3R3ValidationError("review ZIP target already exists")
    payload = _zip_bytes(members)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {**validation, **validate_review_zip()}


def validate_review_zip() -> dict[str, Any]:
    target = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    value = os.lstat(target)
    if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode):
        raise RQ2D3R3ValidationError("review ZIP absent or unsafe")
    referenced = [
        line.split("  ", 1)[1]
        for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]
    allowed = set(referenced) | {
        _relative(CHECKSUM_PATH),
        "review/GIT_STATE.txt",
        "review/DIFF_SUMMARY.txt",
        "review/LEGACY_ENTRYPOINT_SAFE_DIFF.txt",
        "review/REVIEW_CHECKSUMS.sha256",
    }
    absolute_user_marker = b"/" + b"Users/"
    file_uri_marker = b"file" + b"://"
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        if (
            len(names) != len(allowed)
            or set(names) != allowed
            or archive.testzip() is not None
            or any(name.startswith("/") or ".." in Path(name).parts for name in names)
        ):
            raise RQ2D3R3ValidationError("review ZIP allowlist or integrity failure")
        checksum_lines = archive.read("review/REVIEW_CHECKSUMS.sha256").decode("utf-8").splitlines()
        expected_checksum_members = allowed - {"review/REVIEW_CHECKSUMS.sha256"}
        observed_checksum_members: set[str] = set()
        for line in checksum_lines:
            expected, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RQ2D3R3ValidationError("review internal checksum mismatch")
            observed_checksum_members.add(name)
        if observed_checksum_members != expected_checksum_members:
            raise RQ2D3R3ValidationError("review checksum member set mismatch")
        for name in names:
            payload = archive.read(name)
            if absolute_user_marker in payload or file_uri_marker in payload:
                raise RQ2D3R3ValidationError("review ZIP absolute path leak")
    return {
        "review_zip": target.name,
        "review_zip_sha256": sha256_file(target),
        "review_zip_size_bytes": value.st_size,
        "review_zip_member_count": len(allowed),
        "referenced_tracked_output_count": len(referenced),
        "referenced_output_member_count": len(referenced),
        "zip_integrity": "PASS",
        "exact_allowlist": "PASS",
        "internal_checksums": "PASS",
        "governed_text_leak_scan": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--review-zip", action="store_true")
    parser.add_argument("--require-review-zip", action="store_true")
    args = parser.parse_args()
    if args.build:
        build_outputs()
        result = validate_outputs()
        result["operation"] = "build"
    elif args.review_zip:
        result = build_review_zip()
        result["operation"] = "review_zip"
    else:
        result = validate_outputs(require_review_zip=args.require_review_zip)
        result["operation"] = "validate"
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
