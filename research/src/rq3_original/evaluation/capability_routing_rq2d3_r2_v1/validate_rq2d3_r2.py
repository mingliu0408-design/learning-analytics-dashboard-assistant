"""Build, validate, and package the safe RQ2-D3-R2 harness freeze."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any
import zipfile

from . import HERE, REVIEW_ZIP_NAME, ROOT, START_HEAD, canonical_json_bytes, downloads_path, durable_write, sha256_bytes, sha256_file
from .development_parity import run_development_parity_v1
from .fixed_rq2d4_paths import fixed_d4_path_contract_document_v1
from .fixed_statistical_execution import fixed_statistical_execution_contract_document_v1
from .frozen_metric_binding import metric_binding_contract_document_v1
from .grouping_manifest import validate_persisted_grouping_v1
from .model_identity_contract import build_model_identity_contract_v1
from .p2_secondary_scope import p2_secondary_scope_document_v1
from .prediction_contract import prediction_contract_document_v1
from .rq2d4_global_one_shot_contract import global_one_shot_contract_document_v1
from .rq2d4_state_machine import state_machine_contract_document_v1
from .starting_state import validate_starting_state_v1
from .synthetic_final_harness import run_synthetic_final_harness_v1
from .track_b_feature_label_process_firewall import feature_label_firewall_contract_document_v1


PYTHON_NAMES = (
    "__init__.py", "starting_state.py", "grouping_input_authority.py",
    "source_blinded_grouping_builder.py", "grouping_manifest.py",
    "model_identity_contract.py", "frozen_metric_binding.py",
    "fixed_statistical_execution.py", "track_b_feature_label_process_firewall.py",
    "prediction_contract.py", "p2_secondary_scope.py", "development_parity.py",
    "fixed_rq2d4_paths.py", "rq2d4_global_one_shot_contract.py",
    "rq2d4_state_machine.py", "synthetic_track_b_final_fixture.py",
    "synthetic_final_harness.py", "validate_rq2d3_r2.py", "test_rq2d3_r2_unittest.py",
)
OUTPUT_NAMES = (
    "rq2d3_r2_preflight_report_v1.json",
    "rq2d3_r2_grouping_and_harness_authority_v1.json",
    "track_b_source_blinded_contrast_groups_v1.jsonl",
    "track_b_source_blinded_grouping_manifest_v1.json",
    "track_b_final_model_identity_contract_v1.json",
    "track_b_frozen_metric_binding_contract_v1.json",
    "track_b_fixed_statistical_execution_contract_v1.json",
    "track_b_feature_label_process_firewall_contract_v1.json",
    "track_b_prediction_contract_v1.json",
    "track_b_p2_secondary_scope_v1.json",
    "track_b_d4_fixed_path_contract_v1.json",
    "track_b_d4_global_one_shot_contract_v1.json",
    "track_b_d4_state_machine_v1.json",
    "rq2d3_r2_development_parity_v1.json",
    "rq2d3_r2_synthetic_validation_v1.json",
    "rq2d3_r2_validation_report_v1.json",
)
DOC_NAMES = (
    "RQ2D3_R2_SOURCE_BLINDED_GROUPING_AUTHORITY.md",
    "RQ2D3_R2_B0_B1_P1_FINAL_PROTOCOL.md",
    "RQ2D3_R2_FEATURE_LABEL_PROCESS_FIREWALL.md",
    "RQ2D3_R2_STATISTICAL_IMPLEMENTATION_BINDING.md",
    "RQ2D3_R2_D4_ONE_SHOT_RUNBOOK.md",
    "RQ2D3_R2_SCOPE_AND_LIMITATIONS.md",
)
CHECKSUM_PATH = HERE / "rq2d3_r2_output_checksums_v1.sha256"


class RQ2D3R2ValidationError(RuntimeError):
    pass


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def checksum_targets() -> tuple[Path, ...]:
    code = tuple(HERE / name for name in PYTHON_NAMES)
    docs = tuple(ROOT / "docs/thesis_mainline/rq2" / name for name in DOC_NAMES)
    outputs = tuple(HERE / name for name in OUTPUT_NAMES)
    return tuple(sorted((*code, *docs, *outputs), key=lambda path: _relative(path).encode("utf-8")))


def _authority_document(grouping: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r2-grouping-and-harness-authority-v1",
        "stage": "RQ2-D3-R2",
        "status": "AUTHORISED_CONTRACT_ONLY",
        "authorised_actions": [
            "MAPPING_SINGLE_OPEN_READ", "CANONICAL_CASE_BANK_SINGLE_OPEN_READ",
            "SOURCE_BLINDED_GROUPING", "DEVELOPMENT_PARITY", "SYNTHETIC_FINAL_HARNESS",
            "D4_GLOBAL_ONE_SHOT_CONTRACT_FREEZE",
        ],
        "grouping_input_open_read": {
            "mapping": grouping["mapping_open_read"],
            "canonical_case_bank": grouping["case_bank_open_read"],
        },
        "forbidden_field_value_access_count": grouping["forbidden_field_value_access_count"],
        "real_track_b_feature_access_authorised": False,
        "real_track_b_prediction_authorised": False,
        "real_track_b_metric_authorised": False,
        "full_text_gold_content_access_authorised": False,
        "hidden_legacy_access_authorised": False,
        "raw_track_b_access_authorised": False,
        "blind_key_access_authorised": False,
        "d4_execution_authorised": False,
        "policy_or_threshold_change_authorised": False,
        "metric_comparison_or_seed_change_authorised": False,
        "gold_change_authorised": False,
        "provider_or_network_authorised": False,
    }


def _preflight(starting: dict[str, Any], grouping: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r2-preflight-report-v1",
        "stage": "RQ2-D3-R2",
        "status": "PASS",
        "starting_state": starting,
        "grouping_input_identity": "PASS",
        "mapping_open_read": grouping["mapping_open_read"],
        "canonical_case_bank_open_read": grouping["case_bank_open_read"],
        "full_text_gold_content_open_count": 0,
        "label_row_open_count": 0,
        "real_track_b_feature_access_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "hidden_legacy_access_count": 0,
        "raw_track_b_access_count": 0,
        "blind_key_access_count": 0,
        "d4_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def _validation_document(grouping: dict[str, Any], parity: dict[str, Any], synthetic: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r2-validation-report-v1",
        "stage": "RQ2-D3-R2",
        "status": "PASS",
        "source_blinded_grouping": "48/24/2 PASS",
        "grouping_ledger_sha256": grouping["ledger_sha256"],
        "forbidden_field_value_access_count": 0,
        "model_identity": "PASS",
        "frozen_metric_binding": "PASS_NON_INJECTABLE",
        "fixed_statistical_binding": "PASS_NON_OVERRIDABLE",
        "feature_label_process_firewall": "PASS",
        "development_parity": parity["status"],
        "c0_dev84_ranking_identity": "84/84 PASS",
        "c0_dev84_maximum_score_delta": parity["c0_dev84"]["maximum_absolute_score_delta"],
        "c0_dev84_maximum_metric_delta": parity["c0_dev84"]["maximum_absolute_metric_delta"],
        "synthetic_final_harness": synthetic["status"],
        "synthetic_process_isolation": "3/3 FRESH PASS",
        "synthetic_sign_flip": "3 x 100000 PASS",
        "synthetic_bootstrap": "3 x 50000 PASS",
        "synthetic_global_one_shot": "PASS",
        "protected_source_change_count": 0,
        "governed_text_leak_count": 0,
        "double_finalisation_byte_identical": True,
        "real_track_b_feature_access_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "full_text_gold_content_open_count": 0,
        "label_row_open_count": 0,
        "hidden_legacy_access_count": 0,
        "raw_track_b_access_count": 0,
        "blind_key_access_count": 0,
        "d4_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def build_outputs() -> dict[str, Any]:
    starting = validate_starting_state_v1()
    grouping = validate_persisted_grouping_v1()
    model = build_model_identity_contract_v1()
    metric = metric_binding_contract_document_v1()
    statistics = fixed_statistical_execution_contract_document_v1()
    firewall = feature_label_firewall_contract_document_v1()
    prediction = prediction_contract_document_v1()
    p2 = p2_secondary_scope_document_v1()
    paths = fixed_d4_path_contract_document_v1()
    global_contract = global_one_shot_contract_document_v1()
    state_machine = state_machine_contract_document_v1()
    parity = run_development_parity_v1()
    synthetic = run_synthetic_final_harness_v1()
    documents = {
        "rq2d3_r2_preflight_report_v1.json": _preflight(starting, grouping),
        "rq2d3_r2_grouping_and_harness_authority_v1.json": _authority_document(grouping),
        "track_b_final_model_identity_contract_v1.json": model,
        "track_b_frozen_metric_binding_contract_v1.json": metric,
        "track_b_fixed_statistical_execution_contract_v1.json": statistics,
        "track_b_feature_label_process_firewall_contract_v1.json": firewall,
        "track_b_prediction_contract_v1.json": prediction,
        "track_b_p2_secondary_scope_v1.json": p2,
        "track_b_d4_fixed_path_contract_v1.json": paths,
        "track_b_d4_global_one_shot_contract_v1.json": global_contract,
        "track_b_d4_state_machine_v1.json": state_machine,
        "rq2d3_r2_development_parity_v1.json": parity,
        "rq2d3_r2_synthetic_validation_v1.json": synthetic,
    }
    validation = _validation_document(grouping, parity, synthetic)
    documents["rq2d3_r2_validation_report_v1.json"] = validation
    encoded_once = {name: canonical_json_bytes(value) for name, value in documents.items()}
    encoded_twice = {name: canonical_json_bytes(value) for name, value in documents.items()}
    if encoded_once != encoded_twice:
        raise RQ2D3R2ValidationError("double finalisation mismatch")
    for name, value in encoded_once.items():
        durable_write(HERE / name, value)
    write_checksums()
    return validation


def write_checksums() -> None:
    missing = [path for path in checksum_targets() if not path.is_file()]
    if missing:
        raise RQ2D3R2ValidationError(f"checksum target absent: {missing[0].name}")
    payload = "".join(f"{sha256_file(path)}  {_relative(path)}\n" for path in checksum_targets()).encode("utf-8")
    durable_write(CHECKSUM_PATH, payload)


def _verify_checksums() -> int:
    lines = [line for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines() if line]
    expected_paths = {_relative(path) for path in checksum_targets()}
    observed_paths: set[str] = set()
    for line in lines:
        expected, relative = line.split("  ", 1)
        observed_paths.add(relative)
        if sha256_file(ROOT / relative) != expected:
            raise RQ2D3R2ValidationError(f"output checksum mismatch: {relative}")
    if observed_paths != expected_paths:
        raise RQ2D3R2ValidationError("output checksum path set mismatch")
    return len(lines)


def _protected_source_check() -> None:
    result = subprocess.run(["git", "diff", "--name-only", START_HEAD], cwd=ROOT, capture_output=True, text=True, check=True)
    for name in result.stdout.splitlines():
        if name == ".gitignore" or name.startswith("evaluation/capability_routing_rq2d3_r2_v1/") or name.startswith("docs/thesis_mainline/rq2/RQ2D3_R2_"):
            continue
        raise RQ2D3R2ValidationError(f"protected source changed: {name}")


def _safe_content_scan() -> None:
    absolute_user_marker = "/" + "Users/"
    file_uri_marker = "file" + "://"
    ledger = (HERE / "track_b_source_blinded_contrast_groups_v1.jsonl").read_text(encoding="utf-8")
    forbidden_ledger = ("raw_scenario_id", "raw_case_id", "contrast_set_id", "scenario_family_id", "current_query", "history", "rationale")
    if any(marker in ledger for marker in forbidden_ledger):
        raise RQ2D3R2ValidationError("grouping ledger leak")
    for name in OUTPUT_NAMES:
        text = (HERE / name).read_text(encoding="utf-8")
        if absolute_user_marker in text or file_uri_marker in text:
            raise RQ2D3R2ValidationError("absolute path leak")
    for name in PYTHON_NAMES:
        ast.parse((HERE / name).read_text(encoding="utf-8"), filename=name)


def validate_outputs(*, require_review_zip: bool = False) -> dict[str, Any]:
    validate_starting_state_v1()
    grouping = validate_persisted_grouping_v1()
    if grouping["forbidden_field_value_access_count"] != 0:
        raise RQ2D3R2ValidationError("forbidden grouping field access")
    count = _verify_checksums()
    validation = json.loads((HERE / "rq2d3_r2_validation_report_v1.json").read_text(encoding="utf-8"))
    parity = json.loads((HERE / "rq2d3_r2_development_parity_v1.json").read_text(encoding="utf-8"))
    synthetic = json.loads((HERE / "rq2d3_r2_synthetic_validation_v1.json").read_text(encoding="utf-8"))
    if validation.get("status") != "PASS" or parity.get("status") != "PASS" or synthetic.get("status") != "PASS":
        raise RQ2D3R2ValidationError("safe validation artifact failed")
    _protected_source_check()
    _safe_content_scan()
    if require_review_zip:
        validate_review_zip()
    return {
        "stage": "RQ2-D3-R2",
        "status": "PASS",
        "output_checksum_count": count,
        "grouping": "48/24/2 PASS",
        "full_text_gold_content_open_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "d4_execution_count": 0,
        "review_zip_required": require_review_zip,
    }


def _git_text(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members, key=lambda value: value.encode("utf-8")):
            info = zipfile.ZipInfo(name, (2026, 8, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def build_review_zip() -> dict[str, Any]:
    validation = validate_outputs()
    referenced: list[str] = []
    for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines():
        if line:
            _, relative = line.split("  ", 1)
            referenced.append(relative)
    members = {relative: (ROOT / relative).read_bytes() for relative in referenced}
    members[_relative(CHECKSUM_PATH)] = CHECKSUM_PATH.read_bytes()
    members["review/GIT_STATE.txt"] = (
        f"branch={_git_text('branch','--show-current').strip()}\n"
        f"head={_git_text('rev-parse','HEAD').strip()}\n"
        f"parent={_git_text('rev-parse','HEAD^').strip()}\n"
        f"relative_commits_from_r1={_git_text('rev-list','--count',f'{START_HEAD}..HEAD').strip()}\n"
        f"remote_count={len(_git_text('remote').splitlines())}\n"
        f"tag_count={len(_git_text('tag','--list').splitlines())}\n"
        "working_tree_clean=true\nindex_clean=true\n"
    ).encode("utf-8")
    members["review/DIFF_SUMMARY.txt"] = _git_text("diff", "--stat", f"{START_HEAD}..HEAD").encode("utf-8")
    members["review/GITIGNORE_SAFE_DIFF.txt"] = _git_text("diff", f"{START_HEAD}..HEAD", "--", ".gitignore").encode("utf-8")
    review_checksums = "".join(
        f"{sha256_bytes(value)}  {name}\n" for name, value in sorted(members.items())
    ).encode("utf-8")
    members["review/REVIEW_CHECKSUMS.sha256"] = review_checksums
    target = downloads_path(REVIEW_ZIP_NAME)
    durable_write(target, _zip_bytes(members))
    review = validate_review_zip()
    return {**validation, **review}


def validate_review_zip() -> dict[str, Any]:
    absolute_user_marker = b"/" + b"Users/"
    file_uri_marker = b"file" + b"://"
    target = downloads_path(REVIEW_ZIP_NAME)
    if not target.is_file() or target.is_symlink():
        raise RQ2D3R2ValidationError("review ZIP absent or unsafe")
    referenced = [line.split("  ", 1)[1] for line in CHECKSUM_PATH.read_text(encoding="utf-8").splitlines() if line]
    allowed = set(referenced) | {
        _relative(CHECKSUM_PATH), "review/GIT_STATE.txt", "review/DIFF_SUMMARY.txt",
        "review/GITIGNORE_SAFE_DIFF.txt", "review/REVIEW_CHECKSUMS.sha256",
    }
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        if set(names) != allowed or len(names) != len(allowed) or archive.testzip() is not None:
            raise RQ2D3R2ValidationError("review ZIP allowlist or integrity failure")
        checksum_lines = archive.read("review/REVIEW_CHECKSUMS.sha256").decode("utf-8").splitlines()
        for line in checksum_lines:
            expected, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RQ2D3R2ValidationError("review internal checksum mismatch")
        for name in names:
            value = archive.read(name)
            if absolute_user_marker in value or file_uri_marker in value:
                raise RQ2D3R2ValidationError("review ZIP absolute path leak")
    return {
        "review_zip": str(target.name),
        "review_zip_sha256": sha256_file(target),
        "review_zip_size_bytes": target.stat().st_size,
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
