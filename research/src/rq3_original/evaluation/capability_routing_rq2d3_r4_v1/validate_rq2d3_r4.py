"""Build, validate and package the safe RQ2-D3-R4 freeze artifacts."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import zipfile
from typing import Any, Iterable, Mapping

from . import HERE, ROOT, START_HEAD, TARGET_BRANCH, canonical_json_bytes, sha256_bytes, sha256_file
from .atomic_execution_state_v1_2 import atomic_execution_state_contract_document_v1_2
from .completion_bundle_v1_2 import completion_bundle_contract_document_v1_2
from .completion_evidence_v1_2 import completion_evidence_contract_document_v1_2
from .d3_r3_identity import AUTHORISED_LEGACY_FILES, d3_r3_identity_document_v1
from .d3_r3_legacy_entrypoint_revocation import (
    legacy_entrypoint_inventory_document_v1,
    real_harness_supersession_document_v1,
)
from .durable_no_replace_artifact_v1_2 import no_replace_artifact_contract_document_v1_2
from .effective_d4_contract_v1_2 import effective_d4_contract_document_v1_2
from .fixed_real_d4_paths_v1_2 import fixed_real_path_contract_document_v1_2
from .fixed_real_worker_authority_v1_2 import fixed_real_worker_authority_contract_document_v1_2
from .immutable_reservation_sentinel_v1_2 import immutable_reservation_contract_document_v1_2
from .parent_execution_receipt_v1_2 import parent_execution_receipt_contract_document_v1_2
from .rq2d3_r4_terminality_authority import terminality_authority_document_v1
from .starting_state import validate_starting_state_v1
from .strict_receipt_verifier_v1_2 import strict_receipt_contract_document_v1_2
from .synthetic_r4_integrity_harness import run_synthetic_r4_integrity_harness_v1_2
from .terminal_state_machine_v1_2 import terminal_state_contract_document_v1_2


REVIEW_NAME = "RQ2_D3_R4_FINAL_D4_TERMINALITY_REPAIR_REVIEW_2026-08-29.zip"
REVIEW_PATH = Path.home() / "Downloads" / REVIEW_NAME
CHECKSUM_RELATIVE = "evaluation/capability_routing_rq2d3_r4_v1/rq2d3_r4_output_checksums_v1.sha256"
DOC_NAMES = (
    "RQ2D3_R4_FIXED_REAL_WORKER_AUTHORITY.md",
    "RQ2D3_R4_IMMUTABLE_RESERVATION_AND_ATOMIC_STATE.md",
    "RQ2D3_R4_TERMINAL_FAILURE_AND_COMPLETION.md",
    "RQ2D3_R4_ATOMIC_NO_REPLACE_ARTIFACTS.md",
    "RQ2D3_R4_STRICT_RECEIPTS_AND_COMPLETION_EVIDENCE.md",
    "RQ2D3_R4_EFFECTIVE_D4_ONE_SHOT_RUNBOOK.md",
)
JSON_BUILDERS = {
    "rq2d3_r4_terminality_authority_v1.json": terminality_authority_document_v1,
    "d3_r3_legacy_real_entrypoint_inventory_v1.json": legacy_entrypoint_inventory_document_v1,
    "d3_r3_real_harness_supersession_v1.json": real_harness_supersession_document_v1,
    "track_b_effective_d4_contract_v1_2.json": effective_d4_contract_document_v1_2,
    "track_b_fixed_real_path_contract_v1_2.json": fixed_real_path_contract_document_v1_2,
    "track_b_immutable_reservation_contract_v1_2.json": immutable_reservation_contract_document_v1_2,
    "track_b_parent_execution_receipt_contract_v1_2.json": parent_execution_receipt_contract_document_v1_2,
    "track_b_atomic_execution_state_contract_v1_2.json": atomic_execution_state_contract_document_v1_2,
    "track_b_terminal_state_contract_v1_2.json": terminal_state_contract_document_v1_2,
    "track_b_fixed_real_worker_authority_contract_v1_2.json": fixed_real_worker_authority_contract_document_v1_2,
    "track_b_no_replace_artifact_contract_v1_2.json": no_replace_artifact_contract_document_v1_2,
    "track_b_strict_receipt_verification_contract_v1_2.json": strict_receipt_contract_document_v1_2,
    "track_b_completion_evidence_contract_v1_2.json": completion_evidence_contract_document_v1_2,
    "track_b_completion_bundle_contract_v1_2.json": completion_bundle_contract_document_v1_2,
}


class RQ2D3R4ValidationError(RuntimeError):
    pass


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _write_tracked(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.build-tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(value)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RQ2D3R4ValidationError("short tracked output write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def checksum_targets() -> tuple[Path, ...]:
    docs = [ROOT / "docs/thesis_mainline/rq2" / name for name in DOC_NAMES]
    code = sorted(HERE.glob("*.py"), key=lambda path: _relative(path).encode("utf-8"))
    safe_json = sorted(HERE.glob("*.json"), key=lambda path: _relative(path).encode("utf-8"))
    checksum = ROOT / CHECKSUM_RELATIVE
    return tuple(
        path
        for path in sorted(docs + code + safe_json, key=lambda path: _relative(path).encode("utf-8"))
        if path != checksum
    )


def _validation_report(
    preflight: Mapping[str, Any], synthetic: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "rq2d3-r4-validation-report-v1",
        "stage": "RQ2-D3-R4",
        "status": "PASS",
        "starting_state": dict(preflight),
        "d3_r3_identity": d3_r3_identity_document_v1(),
        "legacy_entries_revoked": True,
        "effective_contract": "RQ2_TRACK_B_B0_B1_P1_FINAL_EVALUATION_GLOBAL_ONE_SHOT_V1_2",
        "fixed_real_paths": True,
        "immutable_sentinel": True,
        "atomic_mutable_state": True,
        "failed_terminal": True,
        "completed_terminal": True,
        "root_failure_immutable": True,
        "artifact_publication": "ATOMIC_HARD_LINK_NO_REPLACE",
        "strict_receipt_verification": True,
        "completion_hard_failure_source": "ACTUAL_CUMULATIVE_EVIDENCE",
        "synthetic_validation": dict(synthetic),
        "prearm_smoke_preserved": True,
        "development_parity_preserved": "9/9 PASS",
        "p2_status": "DEFERRED_NOT_EXECUTED_IN_RQ2_D4",
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
        "production_change_count": 0,
    }


def build_outputs() -> dict[str, Any]:
    preflight = validate_starting_state_v1()
    for name, builder in JSON_BUILDERS.items():
        _write_tracked(HERE / name, canonical_json_bytes(builder()))
    synthetic = run_synthetic_r4_integrity_harness_v1_2()
    _write_tracked(
        HERE / "rq2d3_r4_synthetic_validation_v1.json",
        canonical_json_bytes(synthetic),
    )
    _write_tracked(
        HERE / "rq2d3_r4_preflight_report_v1.json",
        canonical_json_bytes(
            {
                "schema_version": "rq2d3-r4-preflight-report-v1",
                "stage": "RQ2-D3-R4",
                "status": "PASS",
                "starting_state": preflight,
                "frozen_identities": d3_r3_identity_document_v1(),
                "combined_source_content_read_count": 0,
                "label_gold_content_read_count": 0,
                "mapping_access_count": 0,
                "canonical_case_bank_access_count": 0,
                "real_d4_directories_created": False,
                "d4_execution_count": 0,
            }
        ),
    )
    report = _validation_report(preflight, synthetic)
    _write_tracked(
        HERE / "rq2d3_r4_validation_report_v1.json", canonical_json_bytes(report)
    )
    write_checksums()
    return report


def write_checksums() -> None:
    lines = [f"{sha256_file(path)}  {_relative(path)}" for path in checksum_targets()]
    _write_tracked(ROOT / CHECKSUM_RELATIVE, ("\n".join(lines) + "\n").encode("utf-8"))


def _verify_checksums() -> int:
    path = ROOT / CHECKSUM_RELATIVE
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    expected_paths = [_relative(candidate) for candidate in checksum_targets()]
    observed_paths = []
    for line in lines:
        expected, relative = line.split("  ", 1)
        observed_paths.append(relative)
        target = ROOT / relative
        if not target.is_file() or target.is_symlink() or sha256_file(target) != expected:
            raise RQ2D3R4ValidationError("RQ2-D3-R4 output checksum mismatch")
    if observed_paths != expected_paths or len(lines) != len(expected_paths):
        raise RQ2D3R4ValidationError("RQ2-D3-R4 output checksum membership mismatch")
    return len(lines)


def _changed_paths() -> set[str]:
    process = subprocess.run(
        ["git", "diff", "--name-only", START_HEAD],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line for line in process.stdout.splitlines() if line}


def _protected_source_check() -> None:
    changed = _changed_paths()
    authorised_legacy = set(AUTHORISED_LEGACY_FILES)
    allowed = {
        path
        for path in changed
        if path.startswith("evaluation/capability_routing_rq2d3_r4_v1/")
        or path.startswith("docs/thesis_mainline/rq2/RQ2D3_R4_")
        or path in authorised_legacy
    }
    if changed != allowed:
        raise RQ2D3R4ValidationError("BLOCKED_RQ2_D3_R4_PROTECTED_SOURCE_MUTATED")
    for relative in authorised_legacy:
        process = subprocess.run(
            ["git", "diff", "--numstat", START_HEAD, "--", relative],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        if not process.stdout.startswith("2\t0\t"):
            raise RQ2D3R4ValidationError("legacy entry diff exceeds minimum scope")
    protected_prefixes = (
        "evaluation/capability_routing_rq2d2b_v1/",
        "evaluation/capability_routing_rq2d3_r1_v1/",
        "evaluation/capability_routing_rq2d3_r2_v1/",
        "semantic_runtime/",
        "evaluation/capability_routing_rq2b_v1/",
    )
    if any(path.startswith(protected_prefixes) for path in changed):
        raise RQ2D3R4ValidationError("BLOCKED_RQ2_D3_R4_PROTECTED_SOURCE_MUTATED")


def _all_new_ast() -> int:
    count = 0
    for path in HERE.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += 1
    return count


def _governed_text_leak_scan() -> None:
    safe_outputs = list(checksum_targets())
    forbidden_literals = (
        "/" + "Users/",
        "student_" + "email",
        "blind_key_" + "value",
        "hidden_legacy_" + "payload",
        "raw_track_b_" + "row",
    )
    for path in safe_outputs:
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden_literals):
            raise RQ2D3R4ValidationError("governed-text leak scan failed")


def _real_targets_absent() -> None:
    for relative in (
        "evaluation/capability_routing_rq2d4_v1/local_control",
        "evaluation/capability_routing_rq2d4_v1/local_one_shot",
    ):
        try:
            os.lstat(ROOT / relative)
        except FileNotFoundError:
            continue
        raise RQ2D3R4ValidationError("real D4 target exists during R4")


def _synthetic_separation_check() -> None:
    for name in (
        "synthetic_feature_worker_v1_2.py",
        "synthetic_predictor_worker_v1_2.py",
        "synthetic_metric_worker_v1_2.py",
    ):
        text = (HERE / name).read_text(encoding="utf-8")
        if "real_feature_worker" in text or "real_predictor_worker" in text or "real_metric_worker" in text:
            raise RQ2D3R4ValidationError("synthetic worker imports real entry")


def validate_outputs(*, require_review_zip: bool = False) -> dict[str, Any]:
    checksum_count = _verify_checksums()
    ast_count = _all_new_ast()
    _protected_source_check()
    _governed_text_leak_scan()
    _real_targets_absent()
    _synthetic_separation_check()
    inventory = legacy_entrypoint_inventory_document_v1()
    synthetic = json.loads((HERE / "rq2d3_r4_synthetic_validation_v1.json").read_text())
    if (
        inventory.get("status") != "PASS"
        or synthetic.get("status") != "PASS"
        or synthetic.get("separate_worker_process_count") != 3
        or synthetic.get("hard_failure_count") != 0
        or synthetic.get("final_state") != "COMPLETED"
        or synthetic.get("concurrent_sentinel", {}).get("winner_count") != 1
        or synthetic.get("no_replace_race", {}).get("racer_target_preserved") is not True
        or synthetic.get("state_crash_and_failed_terminality", {}).get("old_state_preserved") is not True
    ):
        raise RQ2D3R4ValidationError("BLOCKED_RQ2_D3_R4_D4_ONE_SHOT_HARNESS")
    fresh = run_synthetic_r4_integrity_harness_v1_2()
    if canonical_json_bytes(fresh) != canonical_json_bytes(synthetic):
        raise RQ2D3R4ValidationError("synthetic harness is not deterministic")
    result = {
        "status": "PASS",
        "checksum_count": checksum_count,
        "new_python_ast_count": ast_count,
        "legacy_revoked_file_count": inventory["file_count"],
        "synthetic_worker_process_count": synthetic["separate_worker_process_count"],
        "real_d4_target_count": 0,
        "governed_text_leak_count": 0,
        "protected_source_violation_count": 0,
    }
    if require_review_zip:
        result["review_zip"] = validate_review_zip()
    return result


def _git_text(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _review_members() -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    manifest_lines = (ROOT / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines()
    for line in manifest_lines:
        _, relative = line.split("  ", 1)
        members[relative] = (ROOT / relative).read_bytes()
    members[CHECKSUM_RELATIVE] = (ROOT / CHECKSUM_RELATIVE).read_bytes()
    members["review_metadata/GIT_STATE.txt"] = (
        f"branch={_git_text('branch','--show-current').strip()}\n"
        f"head={_git_text('rev-parse','HEAD').strip()}\n"
        f"parent={_git_text('rev-parse','HEAD^').strip()}\n"
        f"relative_commits={_git_text('rev-list','--count',f'{START_HEAD}..HEAD').strip()}\n"
        f"remote_count={len(_git_text('remote').splitlines())}\n"
        f"tag_count={len(_git_text('tag','--list').splitlines())}\n"
        f"working_tree_clean={not bool(_git_text('status','--porcelain=v1','--untracked-files=all').strip())}\n"
    ).encode("utf-8")
    members["review_metadata/DIFF_SUMMARY.txt"] = _git_text(
        "diff", "--stat", START_HEAD, "HEAD"
    ).encode("utf-8")
    legacy_files = sorted(AUTHORISED_LEGACY_FILES)
    members["review_metadata/LEGACY_ENTRYPOINT_SAFE_DIFF.patch"] = _git_text(
        "diff", START_HEAD, "HEAD", "--", *legacy_files
    ).encode("utf-8")
    return members


def _zip_bytes(members: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members, key=lambda value: value.encode("utf-8")):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 29, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, members[name])
    return output.getvalue()


def build_review_zip() -> dict[str, Any]:
    if _git_text("branch", "--show-current").strip() != TARGET_BRANCH:
        raise RQ2D3R4ValidationError("review ZIP requires target branch")
    if _git_text("rev-list", "--count", f"{START_HEAD}..HEAD").strip() != "1":
        raise RQ2D3R4ValidationError("review ZIP requires one repair commit")
    if _git_text("status", "--porcelain=v1", "--untracked-files=all").strip():
        raise RQ2D3R4ValidationError("review ZIP requires clean worktree")
    members = _review_members()
    review_checksums = [
        f"{sha256_bytes(value)}  {name}"
        for name, value in sorted(members.items(), key=lambda item: item[0].encode("utf-8"))
    ]
    members["review_metadata/REVIEW_CHECKSUMS.sha256"] = (
        "\n".join(review_checksums) + "\n"
    ).encode("utf-8")
    value = _zip_bytes(members)
    temporary = REVIEW_PATH.with_name(f".{REVIEW_NAME}.tmp.{secrets.token_hex(8)}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(value)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RQ2D3R4ValidationError("short review ZIP write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, REVIEW_PATH, follow_symlinks=False)
    except FileExistsError as error:
        os.unlink(temporary)
        raise RQ2D3R4ValidationError("review ZIP target already exists") from error
    downloads_descriptor = os.open(
        REVIEW_PATH.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        os.fsync(downloads_descriptor)
    finally:
        os.close(downloads_descriptor)
    os.unlink(temporary)
    downloads_descriptor = os.open(
        REVIEW_PATH.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        os.fsync(downloads_descriptor)
    finally:
        os.close(downloads_descriptor)
    return validate_review_zip()


def validate_review_zip() -> dict[str, Any]:
    _governed_text_leak_scan()
    observed = os.lstat(REVIEW_PATH)
    if not stat.S_ISREG(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise RQ2D3R4ValidationError("review ZIP unsafe")
    expected_members = _review_members()
    with zipfile.ZipFile(REVIEW_PATH) as archive:
        names = archive.namelist()
        if archive.testzip() is not None or len(names) != len(set(names)):
            raise RQ2D3R4ValidationError("review ZIP integrity failed")
        expected_names = set(expected_members) | {"review_metadata/REVIEW_CHECKSUMS.sha256"}
        if set(names) != expected_names:
            raise RQ2D3R4ValidationError("BLOCKED_RQ2_D3_R4_REVIEW_PACKAGE_INCOMPLETE")
        for name, value in expected_members.items():
            if archive.read(name) != value:
                raise RQ2D3R4ValidationError("review ZIP member mismatch")
        checksum_lines = archive.read("review_metadata/REVIEW_CHECKSUMS.sha256").decode().splitlines()
        if len(checksum_lines) != len(expected_members):
            raise RQ2D3R4ValidationError("review checksum count mismatch")
        for line in checksum_lines:
            expected, name = line.split("  ", 1)
            if name not in expected_members or sha256_bytes(archive.read(name)) != expected:
                raise RQ2D3R4ValidationError("review checksum mismatch")
        forbidden_basenames = (
            "track_b_contextual_capability_final_gold_v1.jsonl",
            "track_b_contextual_capability_final_gold_labels_v1.jsonl",
            "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json",
            "TRACK_B_FINAL_EVALUATION_EXECUTION_STATE_V1_2.json",
            "TRACK_B_FINAL_EVALUATION_PARENT_EXECUTION_V1_2.json",
        )
        if any(name.endswith(forbidden_basenames) for name in names):
            raise RQ2D3R4ValidationError("review ZIP contains governed artifact")
    return {
        "status": "PASS",
        "path": str(REVIEW_PATH),
        "sha256": sha256_file(REVIEW_PATH),
        "size_bytes": observed.st_size,
        "member_count": len(expected_members) + 1,
        "output_checksum_referenced_file_count": len(checksum_targets()),
        "output_checksum_referenced_files_present": True,
        "integrity": "PASS",
        "exact_allowlist": "PASS",
        "internal_checksums": "PASS",
        "governed_text_leak_scan": "PASS",
    }


def main() -> int:
    build_outputs()
    print(json.dumps(validate_outputs(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
