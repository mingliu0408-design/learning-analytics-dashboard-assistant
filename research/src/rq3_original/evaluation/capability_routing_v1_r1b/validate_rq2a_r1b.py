"""Build and fail-closed validation for RQ2-A-R1B."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import subprocess
from typing import Any, Iterable

from . import (
    AUTHENTIC_SOURCE_SHA256,
    AUTHORITY_ZIP_SHA256,
    HERE,
    LOCAL_ARTIFACT_DIRECTORY,
    LOCAL_AUTHENTIC_BANK_RELATIVE,
    LOCAL_CASE_BANK_DIRECTORY,
    LOCAL_COMBINED_BANK_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    LOCAL_REVIEW_DIRECTORY,
    LOCAL_REVIEW_ID_MAPPING_RELATIVE,
    LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE,
    OLD_PACKET_IDENTITIES,
    ROOT,
    RQ2A_R1_HEAD,
    RQ2A_R1_PARENT,
    RQ2A_R1_REVIEW_ZIP_NAME,
    RQ2A_R1_REVIEW_ZIP_SHA256,
    RQ2A_R1_TREE_SHA256,
    SYNTHETIC_SOURCE_RELATIVE,
    SYNTHETIC_SOURCE_SHA256,
    TARGET_BRANCH,
    canonical_json_bytes,
    sha256_file,
)
from .adjudication_contract_v1_2 import human_adjudication_contract_document
from .agreement_contract_v1_2 import human_agreement_contract_document
from .authentic_case_builder import build_authentic_cases
from .authentic_overlap_audit import build_overlap_audit
from .authentic_source_authority import (
    build_authentic_source_authority,
    load_authentic_rows,
    validate_authority_package,
    write_authentic_source_authority,
)
from .build_reviewer_packets_v1_2 import build_reviewer_packets_v1_2
from .combined_bank_builder import build_combined_bank
from .human_review_schema_v1_2 import (
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    human_review_schema_document,
    validate_blank_packet,
)


PYTHON_FILES = (
    "__init__.py",
    "authentic_source_authority.py",
    "authentic_case_builder.py",
    "authentic_overlap_audit.py",
    "combined_bank_builder.py",
    "source_blinded_review_ids.py",
    "human_review_schema_v1_2.py",
    "agreement_contract_v1_2.py",
    "adjudication_contract_v1_2.py",
    "build_reviewer_packets_v1_2.py",
    "validate_rq2a_r1b.py",
    "test_rq2a_r1b_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2A_R1B_AUTHENTIC_DIALOGUE_DATA_AUTHORITY.md",
    "RQ2A_R1B_AUTHENTIC_AND_SYNTHETIC_DATA_ROLES.md",
    "RQ2A_R1B_OVERLAP_AND_INDEPENDENCE_LIMITATIONS.md",
    "RQ2A_R1B_HUMAN_REVIEW_PROTOCOL_V1_2.md",
)
SAFE_JSON_FILES = (
    "authentic_dialogue_source_authority_v1.json",
    "authentic_overlap_audit_v1.json",
    "authentic_case_summary_v1.json",
    "synthetic_stress_bank_role_v1.json",
    "combined_calibration_bank_manifest_v1_2.json",
    "human_review_schema_v1_2.json",
    "human_agreement_contract_v1_2.json",
    "human_adjudication_contract_v1_2.json",
    "reviewer_packet_manifest_v1_2.json",
    "rq2a_r1b_preflight_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1b/rq2a_r1b_output_checksums_v1.sha256"
)
IGNORE_ADDITIONS = (
    "evaluation/capability_routing_v1_r1b/local_artifacts/",
    "evaluation/capability_routing_v1_r1b/local_review/",
    "evaluation/capability_routing_v1_r1b/local_case_bank/",
)
EXPECTED_TEST_COVERAGE = (
    "starting_head",
    "authority_zip_hash",
    "raw_csv_hash",
    "fifty_total_records",
    "twenty_five_user_turns",
    "twenty_five_assistant_turns",
    "five_page_distribution",
    "assistant_never_current_query",
    "authentic_ids_unique",
    "five_context_link_candidates",
    "no_automatic_session_inference",
    "exact_overlap_counts",
    "normalised_overlap_counts",
    "rq1_dev_overlap_zero",
    "track_b_rejection",
    "authentic_threshold_ineligible",
    "synthetic_stress_role",
    "synthetic_membership_unchanged",
    "combined_case_count_sixty",
    "source_blinded_review_ids",
    "source_identity_hidden",
    "same_packet_case_set",
    "different_packet_order",
    "all_human_fields_blank",
    "context_link_valid_enum",
    "agreement_separated_by_source",
    "context_link_adjudication_trigger",
    "old_packets_unchanged",
    "new_packets_ignored",
    "tracked_outputs_query_free",
    "no_production_change",
    "no_provider_or_network",
    "double_build_byte_identical",
    "output_checksums",
    "protected_sources_unchanged",
)


class RQ2AR1BValidationError(RuntimeError):
    pass


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if check and result.returncode:
        raise RQ2AR1BValidationError(f"git command failed: {' '.join(args)}")
    return result


def starting_tree_digest() -> str:
    tree = _git("ls-tree", "-r", RQ2A_R1_HEAD).stdout
    return hashlib.sha256(tree).hexdigest()


def assert_starting_lineage() -> None:
    parent = _git("rev-parse", f"{RQ2A_R1_HEAD}^").stdout.decode().strip()
    if parent != RQ2A_R1_PARENT or starting_tree_digest() != RQ2A_R1_TREE_SHA256:
        raise RQ2AR1BValidationError("BLOCKED_RQ2_A_R1B_STARTING_STATE_MISMATCH")
    if _git("merge-base", "--is-ancestor", RQ2A_R1_HEAD, "HEAD", check=False).returncode:
        raise RQ2AR1BValidationError("RQ2-A-R1 HEAD is not an ancestor")
    branch = _git("branch", "--show-current").stdout.decode().strip()
    if branch != TARGET_BRANCH:
        raise RQ2AR1BValidationError("RQ2-A-R1B branch mismatch")
    relative = int(
        _git("rev-list", "--count", f"{RQ2A_R1_HEAD}..HEAD").stdout.decode().strip()
    )
    if relative not in {0, 1}:
        raise RQ2AR1BValidationError("unexpected relative commit count")
    if _git("remote").stdout.strip() or _git("tag", "--list").stdout.strip():
        raise RQ2AR1BValidationError("remote/tag count is not zero")


def assert_starting_artifacts() -> None:
    review_zip = Path.home() / "Downloads" / RQ2A_R1_REVIEW_ZIP_NAME
    if not review_zip.is_file() or review_zip.is_symlink():
        raise RQ2AR1BValidationError("RQ2-A-R1 review ZIP unavailable")
    if sha256_file(review_zip) != RQ2A_R1_REVIEW_ZIP_SHA256:
        raise RQ2AR1BValidationError("RQ2-A-R1 review ZIP mismatch")
    checksum = ROOT / "evaluation/capability_routing_v1_r1/rq2a_r1_output_checksums_v1.sha256"
    entries = 0
    for line in checksum.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2AR1BValidationError("RQ2-A-R1 output checksum mismatch")
        entries += 1
    if entries != 19:
        raise RQ2AR1BValidationError("RQ2-A-R1 checksum count mismatch")
    synthetic = ROOT / SYNTHETIC_SOURCE_RELATIVE
    if sha256_file(synthetic) != SYNTHETIC_SOURCE_SHA256:
        raise RQ2AR1BValidationError("synthetic source identity mismatch")
    router = json.loads(
        (
            ROOT
            / "evaluation/learned_intent_ranking/rq1c_final/"
            "rq1c1_router_selection_manifest_v1.json"
        ).read_text(encoding="utf-8")
    )
    if router.get("selected_router") != "C0_COSINE":
        raise RQ2AR1BValidationError("RQ1 Router mismatch")


def _allowed_path(relative: str) -> bool:
    return bool(
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_v1_r1b/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2A_R1B_")
    )


def assert_change_scope() -> None:
    status = _git("status", "--porcelain=v1", "--untracked-files=all").stdout.decode()
    for line in status.splitlines():
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not _allowed_path(relative):
            raise RQ2AR1BValidationError(f"change outside R1B scope: {relative}")
    for args in (
        ("diff", "--name-only", RQ2A_R1_HEAD),
        ("diff", "--cached", "--name-only", RQ2A_R1_HEAD),
    ):
        names = _git(*args).stdout.decode().splitlines()
        if any(not _allowed_path(name) for name in names):
            raise RQ2AR1BValidationError("BLOCKED_RQ2_A_R1B_PROTECTED_SOURCE_MUTATED")


def assert_gitignore_contract() -> None:
    base = _git("show", f"{RQ2A_R1_HEAD}:.gitignore").stdout.decode("utf-8")
    expected = base.rstrip("\n") + "\n" + "\n".join(IGNORE_ADDITIONS) + "\n"
    if (ROOT / ".gitignore").read_text(encoding="utf-8") != expected:
        raise RQ2AR1BValidationError(".gitignore differs from exact R1B additions")


def assert_old_packets_unchanged() -> None:
    for relative, expected in OLD_PACKET_IDENTITIES.items():
        path = ROOT / relative
        with path.open("r", encoding="utf-8", newline="") as handle:
            count = sum(1 for _ in csv.DictReader(handle))
        observed = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "record_count": count,
        }
        if observed != expected:
            raise RQ2AR1BValidationError(f"old packet changed: {relative}")


def assert_all_python_ast() -> None:
    for name in PYTHON_FILES:
        path = HERE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def assert_no_provider_network_surface() -> None:
    prohibited = {"openai", "requests", "httpx", "urllib3", "firebase_admin"}
    for name in PYTHON_FILES:
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            str(node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        if imports & prohibited:
            raise RQ2AR1BValidationError(f"provider/network import in {name}")


def _write_static_contracts() -> None:
    (HERE / "human_review_schema_v1_2.json").write_bytes(
        canonical_json_bytes(human_review_schema_document())
    )
    (HERE / "human_agreement_contract_v1_2.json").write_bytes(
        canonical_json_bytes(human_agreement_contract_document())
    )
    (HERE / "human_adjudication_contract_v1_2.json").write_bytes(
        canonical_json_bytes(human_adjudication_contract_document())
    )


def _generate() -> dict[str, Any]:
    authority = write_authentic_source_authority(ROOT)
    _write_static_contracts()
    overlap = build_overlap_audit(ROOT)
    (HERE / "authentic_overlap_audit_v1.json").write_bytes(
        canonical_json_bytes(overlap)
    )
    packets = build_reviewer_packets_v1_2(ROOT)
    return {"authority": authority, "overlap": overlap, "packets": packets}


def _snapshot_generated() -> dict[str, bytes]:
    safe_without_preflight = [name for name in SAFE_JSON_FILES if name != "rq2a_r1b_preflight_report_v1.json"]
    local = (
        LOCAL_AUTHENTIC_BANK_RELATIVE,
        LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE,
        LOCAL_COMBINED_BANK_RELATIVE,
        LOCAL_REVIEW_ID_MAPPING_RELATIVE,
        LOCAL_REVIEW_A_RELATIVE,
        LOCAL_REVIEW_B_RELATIVE,
    )
    return {
        **{f"safe:{name}": (HERE / name).read_bytes() for name in safe_without_preflight},
        **{f"local:{relative.as_posix()}": (ROOT / relative).read_bytes() for relative in local},
    }


def assert_double_build() -> dict[str, Any]:
    first_result = _generate()
    first = _snapshot_generated()
    second_result = _generate()
    second = _snapshot_generated()
    if first != second:
        raise RQ2AR1BValidationError("RQ2-A-R1B double build is not byte-identical")
    if first_result != second_result:
        raise RQ2AR1BValidationError("RQ2-A-R1B build result changed")
    return second_result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def assert_local_outputs() -> None:
    authentic = _read_jsonl(ROOT / LOCAL_AUTHENTIC_BANK_RELATIVE)
    synthetic = _read_jsonl(ROOT / LOCAL_SYNTHETIC_STRESS_BANK_RELATIVE)
    combined = _read_jsonl(ROOT / LOCAL_COMBINED_BANK_RELATIVE)
    mapping = _read_jsonl(ROOT / LOCAL_REVIEW_ID_MAPPING_RELATIVE)
    if (len(authentic), len(synthetic), len(combined), len(mapping)) != (25, 35, 60, 60):
        raise RQ2AR1BValidationError("local bank count mismatch")
    if Counter(row["source_bank"] for row in combined) != Counter(
        {"authentic": 25, "synthetic": 35}
    ):
        raise RQ2AR1BValidationError("combined source distribution mismatch")
    if Counter(row["source_bank"] for row in mapping) != Counter(
        {"authentic": 25, "synthetic": 35}
    ):
        raise RQ2AR1BValidationError("mapping source distribution mismatch")
    if any(row["source_role"] != "user" for row in authentic):
        raise RQ2AR1BValidationError("assistant became an authentic current query")
    context_ids = {
        row["case_id"] for row in authentic if row["candidate_conversation_history"]
    }
    if len(context_ids) != 5 or any(row["session_inference_performed"] for row in authentic):
        raise RQ2AR1BValidationError("authentic context-link contract mismatch")
    for relative in (
        LOCAL_CASE_BANK_DIRECTORY,
        LOCAL_ARTIFACT_DIRECTORY,
        LOCAL_REVIEW_DIRECTORY,
    ):
        if _git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2AR1BValidationError("local output directory is not ignored")


def _read_packet(relative: Path) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_new_packets() -> None:
    rows_a = _read_packet(LOCAL_REVIEW_A_RELATIVE)
    rows_b = _read_packet(LOCAL_REVIEW_B_RELATIVE)
    if len(rows_a) != 60 or len(rows_b) != 60:
        raise RQ2AR1BValidationError("v1.2 packet count mismatch")
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    ids_a = [row["review_case_id"] for row in rows_a]
    ids_b = [row["review_case_id"] for row in rows_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise RQ2AR1BValidationError("v1.2 packet set/order mismatch")
    forbidden = {
        "source_dataset",
        "source_bank",
        "canonical_case_id",
        "authentic_student_language",
        "overlap_status",
        "legacy_prediction",
        "c0_score",
    }
    if forbidden & set(rows_a[0]) or forbidden & set(rows_b[0]):
        raise RQ2AR1BValidationError("v1.2 packet leaks source/model fields")
    if tuple(rows_a[0]) != (*VISIBLE_FIELDS, *HUMAN_FIELDS):
        raise RQ2AR1BValidationError("v1.2 packet columns mismatch")


def _tracked_output_paths() -> list[Path]:
    return [
        *(HERE / name for name in PYTHON_FILES),
        *(ROOT / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
        *(HERE / name for name in SAFE_JSON_FILES),
    ]


def _governed_text_values() -> list[str]:
    authentic_rows, _ = load_authentic_rows(ROOT)
    strings = [row["message"] for row in authentic_rows]
    source = ROOT / SYNTHETIC_SOURCE_RELATIVE
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        strings.append(str(row.get("current_query") or ""))
        strings.extend(
            str(item.get("content") or "")
            for item in row.get("conversation_history") or []
        )
    return sorted({value for value in strings if len(value.strip()) >= 8})


def governed_text_leak_scan() -> dict[str, Any]:
    strings = _governed_text_values()
    scanned = _tracked_output_paths()
    checksum = ROOT / CHECKSUM_RELATIVE
    if checksum.is_file():
        scanned.append(checksum)
    leaks: list[str] = []
    absolute_marker = "/" + "Users" + "/"
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if absolute_marker in text or any(value in text for value in strings):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RQ2AR1BValidationError("governed text leak: " + ", ".join(leaks))
    return {
        "status": "PASS",
        "governed_text_value_count": len(strings),
        "scanned_file_count": len(scanned),
        "leak_count": 0,
    }


def assert_safe_json() -> None:
    absolute_marker = "/" + "Users" + "/"
    for name in SAFE_JSON_FILES:
        value = json.loads((HERE / name).read_text(encoding="utf-8"))
        if absolute_marker in json.dumps(value, ensure_ascii=False):
            raise RQ2AR1BValidationError(f"absolute path in safe JSON: {name}")


def output_checksum_targets() -> list[Path]:
    return sorted(_tracked_output_paths(), key=lambda path: path.relative_to(ROOT).as_posix())


def write_output_checksums() -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in output_checksum_targets()
    ]
    (ROOT / CHECKSUM_RELATIVE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_output_checksums() -> None:
    expected = {path.relative_to(ROOT).as_posix() for path in output_checksum_targets()}
    observed: set[str] = set()
    for line in (ROOT / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        observed.add(relative)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2AR1BValidationError(f"output checksum mismatch: {relative}")
    if observed != expected:
        raise RQ2AR1BValidationError("output checksum member mismatch")


def assert_staged_content_safe() -> None:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode().splitlines()
    for relative in names:
        if not _allowed_path(relative):
            raise RQ2AR1BValidationError(f"staged path outside allowlist: {relative}")
        if any(
            marker in relative
            for marker in ("local_artifacts/", "local_review/", "local_case_bank/")
        ):
            raise RQ2AR1BValidationError(f"local-only content staged: {relative}")


def _preflight(generated: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2a-r1b-preflight-report-v1",
        "stage": "RQ2-A-R1B",
        "status": "PASS",
        "approved_starting_branch": "research/rq2-a-r1-review-protocol-repair",
        "approved_starting_head": RQ2A_R1_HEAD,
        "approved_starting_parent": RQ2A_R1_PARENT,
        "target_branch": TARGET_BRANCH,
        "starting_tree_sha256": RQ2A_R1_TREE_SHA256,
        "rq2a_r1_review_zip_sha256": RQ2A_R1_REVIEW_ZIP_SHA256,
        "rq2a_r1_checksum_count": 19,
        "authority_zip_sha256": AUTHORITY_ZIP_SHA256,
        "authority_package_verified": True,
        "authentic_source_sha256": AUTHENTIC_SOURCE_SHA256,
        "authentic_case_count": 25,
        "synthetic_case_count": 35,
        "combined_case_count": 60,
        "context_link_candidate_count": 5,
        "overlap_audit_status": generated["overlap"]["status"],
        "all_recomputable_overlap_counts_match": True,
        "rq1_router": "C0_COSINE",
        "human_fields_filled": False,
        "human_review_completed": False,
        "source_blinding_enabled": True,
        "track_a_accessed": False,
        "track_b_accessed": False,
        "model_training_performed": False,
        "provider_calls": 0,
        "network_access": False,
        "production_source_change_count": 0,
        "threshold_tuning_performed": False,
        "p1_implemented": False,
        "p2_implemented": False,
        "rq2_b_implemented": False,
        "double_build_byte_identical": True,
        "expected_test_coverage_count": len(EXPECTED_TEST_COVERAGE),
        "expected_test_coverage": list(EXPECTED_TEST_COVERAGE),
        "expected_relative_commit_count_after_commit": 1,
    }


def build_all() -> None:
    assert_starting_lineage()
    assert_starting_artifacts()
    assert_change_scope()
    assert_gitignore_contract()
    assert_old_packets_unchanged()
    assert_all_python_ast()
    assert_no_provider_network_surface()
    validate_authority_package()
    generated = assert_double_build()
    preflight = _preflight(generated)
    (HERE / "rq2a_r1b_preflight_report_v1.json").write_bytes(
        canonical_json_bytes(preflight)
    )
    write_output_checksums()
    validate_all()


def validate_all() -> None:
    assert_starting_lineage()
    assert_starting_artifacts()
    assert_change_scope()
    assert_gitignore_contract()
    assert_old_packets_unchanged()
    assert_all_python_ast()
    assert_no_provider_network_surface()
    validate_authority_package()
    authority = build_authentic_source_authority(ROOT)
    if authority["source_identity"]["sha256"] != AUTHENTIC_SOURCE_SHA256:
        raise RQ2AR1BValidationError("authentic authority mismatch")
    build_overlap_audit(ROOT)
    assert_local_outputs()
    assert_new_packets()
    assert_safe_json()
    assert_staged_content_safe()
    governed_text_leak_scan()
    validate_output_checksums()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.build:
        build_all()
    else:
        validate_all()
    print(
        json.dumps(
            {
                "status": "PASS",
                "build": args.build,
                "authentic_case_count": 25,
                "synthetic_case_count": 35,
                "combined_case_count": 60,
                "human_fields_filled": False,
                "track_a_accessed": False,
                "track_b_accessed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
