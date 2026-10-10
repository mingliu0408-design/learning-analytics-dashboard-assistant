"""RQ2-D0 contract, safety, Git, and review-package validators."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable
import zipfile

from . import (
    CHECKSUM_NAME,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    RESULT_BRANCH,
    ROOT,
    SAFE_AUTHORITY_COPY_ROOT,
    SAFE_JSON_FILENAMES,
    SCHEMA_AUTHORITY_MEMBER_SHA256,
    STARTING_HEAD,
    TRACK_B_FILE_NAME,
    sha256_file,
)
from .finalise_rq2d0 import expected_review_members, parse_output_checksums
from .starting_state import assert_d0_partition_allowed
from .track_b_safe_authority import verify_safe_schema_package
from .track_b_schema_contract import load_schema_authority


class ValidationError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"status": "PASS", "python_file_count": len(paths)}


def validate_authority_copies() -> dict[str, Any]:
    report, payloads = verify_safe_schema_package()
    failed: list[str] = []
    for name, expected in SCHEMA_AUTHORITY_MEMBER_SHA256.items():
        path = SAFE_AUTHORITY_COPY_ROOT / name
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected
            or path.read_bytes() != payloads[name]
        ):
            failed.append(name)
    if failed:
        raise ValidationError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    authority, profile, template = load_schema_authority()
    return {
        "status": "PASS",
        "package_status": report["status"],
        "copy_count": len(payloads),
        "byte_identical_count": len(payloads),
        "column_count": len(authority["header_contract"]["exact_column_order"]),
        "field_profile_count": len(profile["fields"]),
        "blank_template_data_row_count": template.count(b"\r\n") - 1,
    }


def validate_safe_outputs() -> dict[str, Any]:
    missing = [name for name in SAFE_JSON_FILENAMES if not (HERE / name).is_file()]
    missing.extend(name for name in DOC_FILENAMES if not (DOC_ROOT / name).is_file())
    if missing:
        raise ValidationError("BLOCKED_RQ2_D0_TEST_FAILURE")
    synthetic = json.loads(
        (HERE / "rq2d0_synthetic_validation_v1.json").read_text(encoding="utf-8")
    )
    scope = json.loads((HERE / "rq2_final_scope_contract_v1.json").read_text())
    statistics = json.loads((HERE / "rq2_final_statistical_contract_v1.json").read_text())
    if (
        synthetic.get("status") != "PASS"
        or synthetic.get("real_track_b_access_count") != 0
        or synthetic.get("real_lock_created") is not False
        or synthetic.get("real_packets_generated") is not False
        or scope.get("track_b_persistent_retrieval_evaluable") is not False
        or scope.get("track_b_rag_sufficiency_accuracy_evaluable") is not False
        or statistics.get("paired_bootstrap", {}).get("resampling_unit")
        != "contrast_set_id"
        or statistics.get("paired_sign_flip", {}).get("unit")
        != "contrast_set_id_cluster"
    ):
        raise ValidationError("BLOCKED_RQ2_D0_TEST_FAILURE")
    prohibited_collection_keys = {
        "records",
        "rows",
        "queries",
        "conversation_histories",
        "model_predictions",
        "capability_gold_rows",
    }
    for name in SAFE_JSON_FILENAMES:
        value = json.loads((HERE / name).read_text(encoding="utf-8"))
        stack: list[Any] = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if prohibited_collection_keys & set(item):
                    raise ValidationError("BLOCKED_RQ2_D0_TEST_FAILURE")
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return {
        "status": "PASS",
        "safe_json_count": len(SAFE_JSON_FILENAMES),
        "document_count": len(DOC_FILENAMES),
        "prohibited_record_collection_count": 0,
    }


def validate_output_checksums() -> dict[str, Any]:
    values = parse_output_checksums()
    failed = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if failed:
        raise ValidationError("BLOCKED_RQ2_D0_TEST_FAILURE")
    return {"status": "PASS", "checksum_count": len(values), "failure_count": 0}


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    values = list(paths) if paths is not None else [ROOT / p for p in parse_output_checksums()]
    prohibited_fragments = (
        str(Path.home()) + "/",
        "local_final_gold/" + "primary_v3_hybrid_context",
    )
    leaks: list[str] = []
    for path in values:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(fragment in text for fragment in prohibited_fragments):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise ValidationError("BLOCKED_RQ2_D0_TEST_FAILURE")
    return {
        "status": "PASS",
        "prohibited_fragment_count": len(prohibited_fragments),
        "leak_count": 0,
        "raw_track_b_compared": False,
        "safe_authority_declaration_used": True,
    }


def protected_source_comparison() -> dict[str, Any]:
    changed = _git("diff", "--name-only", STARTING_HEAD, "--").splitlines()
    invalid = [
        path
        for path in changed
        if not path.startswith("evaluation/capability_routing_rq2d0_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_")
    ]
    if invalid:
        raise ValidationError("BLOCKED_RQ2_D0_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "changed_file_count": len(changed),
        "invalid_changed_file_count": 0,
    }


def validate_no_raw_access() -> dict[str, Any]:
    rejected = False
    try:
        assert_d0_partition_allowed(TRACK_B_FILE_NAME)
    except PermissionError:
        rejected = True
    synthetic = json.loads(
        (HERE / "rq2d0_synthetic_validation_v1.json").read_text(encoding="utf-8")
    )
    if not rejected or synthetic.get("real_track_b_access_count") != 0:
        raise ValidationError("BLOCKED_RQ2_D0_TRACK_B_AUTHORITY")
    return {
        "status": "PASS",
        "raw_path_rejected_before_filesystem_access": True,
        "codex_raw_access_count": 0,
        "repository_d0_raw_access_count": 0,
        "real_lock_created": False,
        "real_packets_generated": False,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = _git("diff", "--cached", "--name-only").splitlines()
    invalid = [
        path
        for path in staged
        if not path.startswith("evaluation/capability_routing_rq2d0_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_")
    ]
    if invalid or any("local_" in Path(path).name and "safe_schema" not in path for path in staged):
        raise ValidationError("BLOCKED_RQ2_D0_GIT_FAILURE")
    return {"status": "PASS", "staged_count": len(staged), "invalid_count": 0}


def validate_git_state(*, require_commit: bool = False) -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    count = int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD"))
    if (
        branch != RESULT_BRANCH
        or count not in ({1} if require_commit else {0, 1})
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise ValidationError("BLOCKED_RQ2_D0_GIT_FAILURE")
    return {
        "status": "PASS",
        "branch": branch,
        "relative_commit_count": count,
        "remote_count": 0,
        "tag_count": 0,
    }


def validate_review_zip(path: Path) -> dict[str, Any]:
    expected = set(expected_review_members())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if archive.testzip() is not None or len(names) != len(set(names)) or set(names) != expected:
            raise ValidationError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
        if TRACK_B_FILE_NAME in names or any("reviewer_a_track_b" in n for n in names):
            raise ValidationError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
        if not set(parse_output_checksums()) <= set(names):
            raise ValidationError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
        review_lines = archive.read("REVIEW/REVIEW_CHECKSUMS.sha256").decode("ascii").splitlines()
        for line in review_lines:
            digest, name = line.split(None, 1)
            name = name.strip().lstrip("*")
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValidationError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
        authority_members = {
            f"evaluation/capability_routing_rq2d0_v1/safe_schema_authority/{name}"
            for name in SCHEMA_AUTHORITY_MEMBER_SHA256
        }
        if not authority_members <= set(names):
            raise ValidationError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "status": "PASS",
        "member_count": len(expected),
        "referenced_output_count": len(parse_output_checksums()),
        "internal_review_checksum_count": len(review_lines),
        "safe_authority_member_count": len(authority_members),
    }


def validate_all() -> dict[str, Any]:
    return {
        "python_ast": validate_python_ast(),
        "safe_authority": validate_authority_copies(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "no_raw_access": validate_no_raw_access(),
        "staged_allowlist": staged_allowlist(),
        "git": validate_git_state(),
        "status": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(validate_all(), indent=2, sort_keys=True))
