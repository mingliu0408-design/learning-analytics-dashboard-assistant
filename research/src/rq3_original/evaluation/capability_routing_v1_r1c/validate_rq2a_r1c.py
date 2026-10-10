"""Build and validate RQ2-A-R1C safe artifacts and local review material."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from evaluation.capability_routing_v1_r1b import SYNTHETIC_SOURCE_RELATIVE
from evaluation.capability_routing_v1_r1b.authentic_source_authority import (
    load_authentic_rows,
)

from . import (
    AUTHENTIC_ASSISTANT_COUNT,
    AUTHENTIC_RECORD_COUNT,
    AUTHENTIC_SOURCE_SHA256,
    AUTHENTIC_USER_COUNT,
    HERE,
    LOCAL_ARTIFACT_DIRECTORY,
    LOCAL_AUTHENTIC_BANK_RELATIVE,
    LOCAL_CASE_BANK_DIRECTORY,
    LOCAL_COMBINED_BANK_RELATIVE,
    LOCAL_MAPPING_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    LOCAL_REVIEW_DIRECTORY,
    LOCAL_SYNTHETIC_BANK_RELATIVE,
    OLD_PACKET_IDENTITIES,
    PREVIOUS_CONTEXT_CASE_IDS,
    R1B_AUTHENTIC_BANK_RELATIVE,
    R1B_COMBINED_BANK_RELATIVE,
    R1B_MAPPING_RELATIVE,
    R1B_SYNTHETIC_BANK_RELATIVE,
    R1B_SYNTHETIC_BANK_SHA256,
    ROOT,
    RQ2A_R1B_HEAD,
    RQ2A_R1B_PARENT,
    RQ2A_R1B_REVIEW_ZIP_NAME,
    RQ2A_R1B_REVIEW_ZIP_SHA256,
    RQ2A_R1B_TREE_SHA256,
    TARGET_BRANCH,
    canonical_json_bytes,
    sha256_file,
)
from .adjudication_contract_v1_3 import human_adjudication_contract_document
from .agreement_contract_v1_3 import human_agreement_contract_document
from .build_reviewer_packets_v1_3 import build_reviewer_packets_v1_3
from .human_review_schema_v1_3 import (
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    human_review_schema_document,
    validate_blank_packet,
)
from .provenance_attestation import (
    build_provenance_attestation,
    write_provenance_contracts,
)


PYTHON_FILES = (
    "__init__.py",
    "provenance_attestation.py",
    "authentic_context_link_correction.py",
    "combined_bank_v1_3.py",
    "human_review_schema_v1_3.py",
    "agreement_contract_v1_3.py",
    "adjudication_contract_v1_3.py",
    "build_reviewer_packets_v1_3.py",
    "validate_rq2a_r1c.py",
    "test_rq2a_r1c_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2A_R1C_AUTHENTIC_PROVENANCE_CLOSURE.md",
    "RQ2A_R1C_CONTEXT_LINK_REMOVAL.md",
    "RQ2A_R1C_HUMAN_REVIEW_PROTOCOL_V1_3.md",
)
SAFE_JSON_FILES = (
    "authentic_provenance_attestation_v1.json",
    "authentic_context_link_correction_v1.json",
    "authentic_bank_role_v1_1.json",
    "combined_calibration_bank_manifest_v1_3.json",
    "human_review_schema_v1_3.json",
    "human_agreement_contract_v1_3.json",
    "human_adjudication_contract_v1_3.json",
    "reviewer_packet_manifest_v1_3.json",
    "rq2a_r1c_preflight_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1c/rq2a_r1c_output_checksums_v1.sha256"
)
IGNORE_ADDITIONS = (
    "evaluation/capability_routing_v1_r1c/local_artifacts/",
    "evaluation/capability_routing_v1_r1c/local_review/",
    "evaluation/capability_routing_v1_r1c/local_case_bank/",
)
EXPECTED_TEST_COVERAGE = (
    "starting_head",
    "authentic_csv_hash",
    "twenty_five_user_turns",
    "twenty_five_assistant_outputs",
    "authentic_student_origin_true",
    "assistant_original_gpt4_true",
    "researcher_rewriting_false",
    "few_shot_reconstruction_false",
    "adjacency_linkage_false",
    "previous_five_links_removed",
    "authentic_assistant_context_zero",
    "authentic_query_text_unchanged",
    "synthetic_35_unchanged",
    "combined_60_unchanged",
    "v13_same_case_set",
    "v13_different_order",
    "source_hidden",
    "authentic_histories_blank",
    "synthetic_contexts_retained",
    "all_human_fields_blank",
    "context_link_agreement_excludes_authentic",
    "missing_context_adjudication_rule",
    "old_packets_unchanged",
    "new_packets_ignored",
    "track_a_rejected",
    "track_b_rejected",
    "no_production_change",
    "no_provider_network",
    "double_build_byte_identical",
    "output_checksums",
    "governed_text_leak_scan",
    "protected_sources_unchanged",
)


class RQ2AR1CValidationError(RuntimeError):
    pass


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if check and result.returncode:
        raise RQ2AR1CValidationError(f"git command failed: {' '.join(args)}")
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _read_packet(relative: Path) -> list[dict[str, str]]:
    with (ROOT / relative).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def starting_tree_digest() -> str:
    return hashlib.sha256(_git("ls-tree", "-r", RQ2A_R1B_HEAD).stdout).hexdigest()


def assert_starting_lineage() -> None:
    parent = _git("rev-parse", f"{RQ2A_R1B_HEAD}^").stdout.decode().strip()
    if parent != RQ2A_R1B_PARENT or starting_tree_digest() != RQ2A_R1B_TREE_SHA256:
        raise RQ2AR1CValidationError("BLOCKED_RQ2_A_R1C_STARTING_STATE_MISMATCH")
    if _git("merge-base", "--is-ancestor", RQ2A_R1B_HEAD, "HEAD", check=False).returncode:
        raise RQ2AR1CValidationError("RQ2-A-R1B HEAD is not an ancestor")
    branch = _git("branch", "--show-current").stdout.decode().strip()
    if branch != TARGET_BRANCH:
        raise RQ2AR1CValidationError("RQ2-A-R1C branch mismatch")
    relative = int(
        _git("rev-list", "--count", f"{RQ2A_R1B_HEAD}..HEAD").stdout.decode().strip()
    )
    if relative not in {0, 1}:
        raise RQ2AR1CValidationError("unexpected relative commit count")
    if _git("remote").stdout.strip() or _git("tag", "--list").stdout.strip():
        raise RQ2AR1CValidationError("remote/tag count is not zero")


def assert_starting_artifacts() -> None:
    review_zip = Path.home() / "Downloads" / RQ2A_R1B_REVIEW_ZIP_NAME
    if not review_zip.is_file() or review_zip.is_symlink():
        raise RQ2AR1CValidationError("RQ2-A-R1B review ZIP unavailable")
    if sha256_file(review_zip) != RQ2A_R1B_REVIEW_ZIP_SHA256:
        raise RQ2AR1CValidationError("RQ2-A-R1B review ZIP mismatch")
    checksum = (
        ROOT
        / "evaluation/capability_routing_v1_r1b/rq2a_r1b_output_checksums_v1.sha256"
    )
    entries = 0
    for line in checksum.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2AR1CValidationError("RQ2-A-R1B output checksum mismatch")
        entries += 1
    if entries != 26:
        raise RQ2AR1CValidationError("RQ2-A-R1B checksum count mismatch")
    rows, identity = load_authentic_rows(ROOT)
    roles = Counter(row["role"] for row in rows)
    if identity["sha256"] != AUTHENTIC_SOURCE_SHA256 or len(rows) != AUTHENTIC_RECORD_COUNT:
        raise RQ2AR1CValidationError("authentic CSV identity mismatch")
    if (roles["user"], roles["assistant"]) != (
        AUTHENTIC_USER_COUNT,
        AUTHENTIC_ASSISTANT_COUNT,
    ):
        raise RQ2AR1CValidationError("authentic CSV role counts mismatch")


def _allowed_path(relative: str) -> bool:
    return bool(
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_v1_r1c/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2A_R1C_")
    )


def assert_change_scope() -> None:
    status = _git("status", "--porcelain=v1", "--untracked-files=all").stdout.decode()
    for line in status.splitlines():
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not _allowed_path(relative):
            raise RQ2AR1CValidationError(f"change outside R1C scope: {relative}")
    for args in (
        ("diff", "--name-only", RQ2A_R1B_HEAD),
        ("diff", "--cached", "--name-only", RQ2A_R1B_HEAD),
    ):
        names = _git(*args).stdout.decode().splitlines()
        if any(not _allowed_path(name) for name in names):
            raise RQ2AR1CValidationError("BLOCKED_RQ2_A_R1C_PROTECTED_SOURCE_MUTATED")


def assert_gitignore_contract() -> None:
    base = _git("show", f"{RQ2A_R1B_HEAD}:.gitignore").stdout.decode("utf-8")
    expected = base.rstrip("\n") + "\n" + "\n".join(IGNORE_ADDITIONS) + "\n"
    if (ROOT / ".gitignore").read_text(encoding="utf-8") != expected:
        raise RQ2AR1CValidationError(".gitignore differs from exact R1C additions")


def assert_old_packets_unchanged() -> None:
    for relative, expected in OLD_PACKET_IDENTITIES.items():
        path = ROOT / relative
        with path.open("r", encoding="utf-8", newline="") as handle:
            count = sum(1 for _ in csv.DictReader(handle))
        observed = (sha256_file(path), path.stat().st_size, count)
        if observed != expected:
            raise RQ2AR1CValidationError(f"old packet changed: {relative}")


def assert_all_python_ast() -> None:
    for name in PYTHON_FILES:
        path = HERE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def assert_no_provider_network_surface() -> None:
    prohibited = {
        "openai",
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "socket",
        "firebase_admin",
    }
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
            raise RQ2AR1CValidationError(f"provider/network import in {name}")


def _write_static_contracts() -> dict[str, Any]:
    attestation = write_provenance_contracts(ROOT)
    (HERE / "human_review_schema_v1_3.json").write_bytes(
        canonical_json_bytes(human_review_schema_document())
    )
    (HERE / "human_agreement_contract_v1_3.json").write_bytes(
        canonical_json_bytes(human_agreement_contract_document())
    )
    (HERE / "human_adjudication_contract_v1_3.json").write_bytes(
        canonical_json_bytes(human_adjudication_contract_document())
    )
    return attestation


def _generate() -> dict[str, Any]:
    attestation = _write_static_contracts()
    packets = build_reviewer_packets_v1_3(ROOT)
    return {"attestation": attestation, "packets": packets}


def _snapshot_generated() -> dict[str, bytes]:
    safe = [name for name in SAFE_JSON_FILES if name != "rq2a_r1c_preflight_report_v1.json"]
    local = (
        LOCAL_AUTHENTIC_BANK_RELATIVE,
        LOCAL_SYNTHETIC_BANK_RELATIVE,
        LOCAL_COMBINED_BANK_RELATIVE,
        LOCAL_MAPPING_RELATIVE,
        LOCAL_REVIEW_A_RELATIVE,
        LOCAL_REVIEW_B_RELATIVE,
    )
    return {
        **{f"safe:{name}": (HERE / name).read_bytes() for name in safe},
        **{f"local:{relative.as_posix()}": (ROOT / relative).read_bytes() for relative in local},
    }


def assert_double_build() -> dict[str, Any]:
    first_result = _generate()
    first = _snapshot_generated()
    second_result = _generate()
    second = _snapshot_generated()
    if first != second or first_result != second_result:
        raise RQ2AR1CValidationError("RQ2-A-R1C double build is not byte-identical")
    return second_result


def assert_local_outputs() -> None:
    old_authentic = _read_jsonl(ROOT / R1B_AUTHENTIC_BANK_RELATIVE)
    authentic = _read_jsonl(ROOT / LOCAL_AUTHENTIC_BANK_RELATIVE)
    old_synthetic = _read_jsonl(ROOT / R1B_SYNTHETIC_BANK_RELATIVE)
    synthetic = _read_jsonl(ROOT / LOCAL_SYNTHETIC_BANK_RELATIVE)
    old_combined = _read_jsonl(ROOT / R1B_COMBINED_BANK_RELATIVE)
    combined = _read_jsonl(ROOT / LOCAL_COMBINED_BANK_RELATIVE)
    old_mapping = _read_jsonl(ROOT / R1B_MAPPING_RELATIVE)
    mapping = _read_jsonl(ROOT / LOCAL_MAPPING_RELATIVE)
    if (len(authentic), len(synthetic), len(combined), len(mapping)) != (25, 35, 60, 60):
        raise RQ2AR1CValidationError("local output count mismatch")
    if [row["current_query"] for row in authentic] != [
        row["current_query"] for row in old_authentic
    ]:
        raise RQ2AR1CValidationError("authentic query text changed")
    if any(
        row["candidate_conversation_history"]
        or row["assistant_context_attached"]
        or row["context_link_status"] != "NOT_AVAILABLE"
        for row in authentic
    ):
        raise RQ2AR1CValidationError("authentic context removal incomplete")
    if synthetic != old_synthetic or sha256_file(ROOT / LOCAL_SYNTHETIC_BANK_RELATIVE) != R1B_SYNTHETIC_BANK_SHA256:
        raise RQ2AR1CValidationError("synthetic35 changed")
    if mapping != old_mapping:
        raise RQ2AR1CValidationError("source-blinded mapping changed")
    if Counter(row["source_bank"] for row in combined) != Counter(
        {"authentic": 25, "synthetic": 35}
    ):
        raise RQ2AR1CValidationError("combined60 source counts changed")
    combined_authentic = [row for row in combined if row["source_bank"] == "authentic"]
    if any(row["necessary_conversation_history"] for row in combined_authentic):
        raise RQ2AR1CValidationError("authentic combined history is not blank")
    if [row for row in combined if row["source_bank"] == "synthetic"] != [
        row for row in old_combined if row["source_bank"] == "synthetic"
    ]:
        raise RQ2AR1CValidationError("synthetic combined rows changed")
    for relative in (
        LOCAL_CASE_BANK_DIRECTORY,
        LOCAL_ARTIFACT_DIRECTORY,
        LOCAL_REVIEW_DIRECTORY,
    ):
        if _git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2AR1CValidationError("local output directory is not ignored")


def assert_new_packets() -> None:
    rows_a = _read_packet(LOCAL_REVIEW_A_RELATIVE)
    rows_b = _read_packet(LOCAL_REVIEW_B_RELATIVE)
    if len(rows_a) != 60 or len(rows_b) != 60:
        raise RQ2AR1CValidationError("v1.3 packet count mismatch")
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    ids_a = [row["review_case_id"] for row in rows_a]
    ids_b = [row["review_case_id"] for row in rows_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise RQ2AR1CValidationError("v1.3 packet set/order mismatch")
    mapping = _read_jsonl(ROOT / LOCAL_MAPPING_RELATIVE)
    source_by_id = {
        str(row["review_case_id"]): str(row["source_bank"]) for row in mapping
    }
    authentic = [
        row for row in rows_a if source_by_id[row["review_case_id"]] == "authentic"
    ]
    synthetic = [
        row for row in rows_a if source_by_id[row["review_case_id"]] == "synthetic"
    ]
    if any(row["necessary_conversation_history"] for row in authentic):
        raise RQ2AR1CValidationError("assistant context entered authentic packet")
    combined = _read_jsonl(ROOT / LOCAL_COMBINED_BANK_RELATIVE)
    expected_synthetic_histories = sum(
        bool(row["necessary_conversation_history"])
        for row in combined
        if row["source_bank"] == "synthetic"
    )
    if sum(bool(row["necessary_conversation_history"]) for row in synthetic) != expected_synthetic_histories:
        raise RQ2AR1CValidationError("synthetic context was not retained")
    if tuple(rows_a[0]) != (*VISIBLE_FIELDS, *HUMAN_FIELDS):
        raise RQ2AR1CValidationError("v1.3 packet columns mismatch")


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
    if (ROOT / CHECKSUM_RELATIVE).is_file():
        scanned.append(ROOT / CHECKSUM_RELATIVE)
    leaks: list[str] = []
    absolute_marker = "/" + "Users" + "/"
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if absolute_marker in text or any(value in text for value in strings):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RQ2AR1CValidationError("governed-text leak: " + ", ".join(leaks))
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
        text = json.dumps(value, ensure_ascii=False)
        if absolute_marker in text:
            raise RQ2AR1CValidationError(f"absolute path in safe JSON: {name}")
    correction = json.loads(
        (HERE / "authentic_context_link_correction_v1.json").read_text(encoding="utf-8")
    )
    if set(correction) != {
        "authentic_case_count",
        "previous_candidate_link_count",
        "links_removed",
        "remaining_link_count",
        "assistant_context_in_packets",
        "query_text_modified",
    }:
        raise RQ2AR1CValidationError("context-link correction is not aggregate-only")
    packet_manifest = json.loads(
        (HERE / "reviewer_packet_manifest_v1_3.json").read_text(encoding="utf-8")
    )
    if set(packet_manifest) != {
        "row_count",
        "case_set_sha256",
        "reviewer_a_packet_sha256",
        "reviewer_b_packet_sha256",
        "reviewer_a_order_sha256",
        "reviewer_b_order_sha256",
        "human_field_blank_count",
        "authentic_history_count",
        "source_blinding_status",
    }:
        raise RQ2AR1CValidationError("packet manifest exceeds safe field allowlist")


def output_checksum_targets() -> list[Path]:
    return sorted(
        _tracked_output_paths(), key=lambda path: path.relative_to(ROOT).as_posix()
    )


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
            raise RQ2AR1CValidationError(f"output checksum mismatch: {relative}")
    if observed != expected:
        raise RQ2AR1CValidationError("output checksum member mismatch")


def assert_staged_content_safe() -> None:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode().splitlines()
    for relative in names:
        if not _allowed_path(relative):
            raise RQ2AR1CValidationError(f"staged path outside allowlist: {relative}")
        if any(marker in relative for marker in ("local_artifacts/", "local_review/", "local_case_bank/")):
            raise RQ2AR1CValidationError(f"local-only content staged: {relative}")


def _preflight(generated: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2a-r1c-preflight-report-v1",
        "stage": "RQ2-A-R1C",
        "status": "PASS",
        "approved_starting_branch": "research/rq2-a-r1b-authentic-calibration-integration",
        "approved_starting_head": RQ2A_R1B_HEAD,
        "approved_starting_parent": RQ2A_R1B_PARENT,
        "target_branch": TARGET_BRANCH,
        "starting_tree_sha256": RQ2A_R1B_TREE_SHA256,
        "rq2a_r1b_review_zip_sha256": RQ2A_R1B_REVIEW_ZIP_SHA256,
        "rq2a_r1b_checksum_count": 26,
        "authentic_source_sha256": AUTHENTIC_SOURCE_SHA256,
        "provenance_confirmation_basis": "USER_EXPLICIT_ATTESTATION",
        "authentic_student_origin_confirmed": True,
        "assistant_outputs_original": True,
        "adjacent_pair_linkage_confirmed": False,
        "previous_context_link_count": len(PREVIOUS_CONTEXT_CASE_IDS),
        "remaining_authentic_context_link_count": 0,
        "authentic_case_count": 25,
        "synthetic_case_count": 35,
        "combined_case_count": 60,
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
        "packet_row_count": generated["packets"]["row_count"],
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
    generated = assert_double_build()
    (HERE / "rq2a_r1c_preflight_report_v1.json").write_bytes(
        canonical_json_bytes(_preflight(generated))
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
    attestation = build_provenance_attestation(ROOT)
    if not attestation["role_user_origin"].startswith("VERBATIM_OR_DEIDENTIFIED"):
        raise RQ2AR1CValidationError("provenance attestation mismatch")
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
                "authentic_assistant_context_count": 0,
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
