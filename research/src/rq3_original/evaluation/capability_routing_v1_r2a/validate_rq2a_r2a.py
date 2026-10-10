"""Build and validate RQ2-A-R2A safe artifacts and local-only packets."""

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

from evaluation.capability_routing_v1_r1c.human_review_schema_v1_3 import (
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    validate_independent_reviewer_ids,
)

from . import (
    ADJUDICATION_PACKET_RELATIVE,
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    COMPLETED_B_SHA256,
    CORRECTED_A_SHA256,
    EXPECTED_ADJUDICATION_CASES,
    HERE,
    ORIGINAL_A_SHA256,
    R1C_COMPLETED_B_RELATIVE,
    R1C_CORRECTED_A_RELATIVE,
    R1C_MAPPING_RELATIVE,
    R1C_ORIGINAL_A_RELATIVE,
    ROOT,
    RQ2A_R1C_CHECKSUM_COUNT,
    RQ2A_R1C_CHECKSUM_RELATIVE,
    RQ2A_R1C_HEAD,
    RQ2A_R1C_PARENT,
    RQ2A_R1C_REVIEW_ZIP_NAME,
    RQ2A_R1C_REVIEW_ZIP_SHA256,
    RQ2A_R1C_TREE_SHA256,
    SOURCE_MAPPING_SHA256,
    TARGET_BRANCH,
    canonical_json_bytes,
    reject_prohibited_track_path,
    sha256_file,
)
from .adjudication_packet_builder import (
    BLANK_DECISION_FIELDS,
    FORBIDDEN_COLUMNS,
    PACKET_FIELDS,
    build_adjudication_packet_bytes,
    write_adjudication_packet,
)
from .adjudication_set_builder import build_adjudication_case_summary
from .agreement_runner import run_agreement, validate_expected_agreement
from .date_canonicalisation import (
    ISO_DATE,
    OLD_DATE,
    canonicalise_date_bytes,
    write_canonical_packets,
)
from .independence_attestation import independence_attestation_document
from .limited_correction_validator import validate_limited_correction
from .packet_identity import (
    PacketPaths,
    read_mapping,
    read_packet,
    resolve_packet_paths,
    validate_packet_identities,
)


PYTHON_FILES = (
    "__init__.py",
    "packet_identity.py",
    "limited_correction_validator.py",
    "date_canonicalisation.py",
    "independence_attestation.py",
    "agreement_runner.py",
    "adjudication_set_builder.py",
    "adjudication_packet_builder.py",
    "validate_rq2a_r2a.py",
    "test_rq2a_r2a_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2A_R2A_HUMAN_PACKET_FREEZE.md",
    "RQ2A_R2A_SOURCE_STRATIFIED_AGREEMENT_REPORT.md",
    "RQ2A_R2A_ADJUDICATION_PROTOCOL.md",
)
SAFE_JSON_FILES = (
    "human_review_independence_attestation_v1.json",
    "human_packet_freeze_manifest_v1.json",
    "human_agreement_results_v1.json",
    "adjudication_case_summary_v1.json",
    "adjudication_packet_manifest_v1.json",
    "rq2a_r2a_preflight_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r2a/rq2a_r2a_output_checksums_v1.sha256"
)
IGNORE_ADDITIONS = (
    "evaluation/capability_routing_v1_r2a/local_review/",
    "evaluation/capability_routing_v1_r2a/local_adjudication/",
    "evaluation/capability_routing_v1_r2a/local_artifacts/",
)
EXPECTED_TEST_COVERAGE = (
    "starting_head",
    "r1c_review_zip_hash",
    "original_a_hash",
    "corrected_a_hash",
    "completed_b_hash",
    "a_correction_exactly_seven_cells",
    "a_changed_column_only_context_sufficient",
    "a_exact_seven_ids",
    "reviewer_id_unchanged",
    "dates_unchanged_before_canonicalisation",
    "a_canonical_hash",
    "b_canonical_hash",
    "canonical_date_only_diff",
    "two_different_reviewer_ids",
    "independence_attestation",
    "canonical_schema_validation",
    "source_mapping_hash",
    "source_split_25_35",
    "overall_agreement",
    "source_stratified_agreement",
    "capability_exact_set_one",
    "naturalness_metrics",
    "context_resolution_agreement",
    "authentic_missing_context_counts",
    "expected_five_adjudication_cases",
    "exact_adjudication_reasons",
    "adjudication_final_fields_blank",
    "no_hidden_proposal",
    "no_model_outputs",
    "local_packets_ignored",
    "old_packets_unchanged",
    "track_a_rejected",
    "track_b_rejected",
    "no_production_change",
    "no_provider_network",
    "double_build_byte_identical",
    "output_checksums",
    "governed_text_leak_scan",
    "protected_sources_unchanged",
)


class RQ2AR2AValidationError(RuntimeError):
    pass


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    if check and result.returncode:
        raise RQ2AR2AValidationError(f"git command failed: {' '.join(args)}")
    return result


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def starting_tree_digest() -> str:
    return hashlib.sha256(_git("ls-tree", "-r", RQ2A_R1C_HEAD).stdout).hexdigest()


def assert_starting_lineage() -> None:
    parent = _git("rev-parse", f"{RQ2A_R1C_HEAD}^").stdout.decode().strip()
    if parent != RQ2A_R1C_PARENT or starting_tree_digest() != RQ2A_R1C_TREE_SHA256:
        raise RQ2AR2AValidationError("BLOCKED_RQ2_A_R2A_STARTING_STATE_MISMATCH")
    branch = _git("branch", "--show-current").stdout.decode().strip()
    if branch != TARGET_BRANCH:
        raise RQ2AR2AValidationError("RQ2-A-R2A target branch mismatch")
    if _git("merge-base", "--is-ancestor", RQ2A_R1C_HEAD, "HEAD", check=False).returncode:
        raise RQ2AR2AValidationError("approved R1C HEAD is not an ancestor")
    relative = int(
        _git("rev-list", "--count", f"{RQ2A_R1C_HEAD}..HEAD").stdout.decode().strip()
    )
    if relative not in {0, 1}:
        raise RQ2AR2AValidationError("unexpected relative commit count")
    if relative == 1:
        head_parent = _git("rev-parse", "HEAD^").stdout.decode().strip()
        if head_parent != RQ2A_R1C_HEAD:
            raise RQ2AR2AValidationError("R2A commit does not directly follow R1C")
    if _git("remote").stdout.strip() or _git("tag", "--list").stdout.strip():
        raise RQ2AR2AValidationError("remote/tag count is not zero")


def assert_r1c_artifacts() -> None:
    review_zip = Path.home() / "Downloads" / RQ2A_R1C_REVIEW_ZIP_NAME
    if (
        not review_zip.is_file()
        or review_zip.is_symlink()
        or sha256_file(review_zip) != RQ2A_R1C_REVIEW_ZIP_SHA256
    ):
        raise RQ2AR2AValidationError("RQ2-A-R1C review ZIP mismatch")
    count = 0
    for line in (ROOT / RQ2A_R1C_CHECKSUM_RELATIVE).read_text(
        encoding="utf-8"
    ).splitlines():
        digest, relative = line.split("  ", 1)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2AR2AValidationError(f"R1C checksum mismatch: {relative}")
        count += 1
    if count != RQ2A_R1C_CHECKSUM_COUNT:
        raise RQ2AR2AValidationError("R1C checksum count mismatch")
    manifest = _json(
        ROOT
        / "evaluation/capability_routing_v1_r1c/reviewer_packet_manifest_v1_3.json"
    )
    if manifest["reviewer_a_packet_sha256"] != (
        "94aebdb33758e3ea5729e2234f864215bccb6c4e574fb4f84465db663253f3cf"
    ) or manifest["reviewer_b_packet_sha256"] != (
        "30cab031c5c6697b976b16d862cb19c4c7fb37c7f3a38b7b31a7767243381532"
    ):
        raise RQ2AR2AValidationError("R1C blank packet identity mismatch")


def _allowed_path(relative: str) -> bool:
    return bool(
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_v1_r2a/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2A_R2A_")
    )


def assert_change_scope() -> None:
    status = _git("status", "--porcelain=v1", "--untracked-files=all").stdout.decode()
    for line in status.splitlines():
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not _allowed_path(relative):
            raise RQ2AR2AValidationError(f"change outside R2A scope: {relative}")
    for args in (
        ("diff", "--name-only", RQ2A_R1C_HEAD),
        ("diff", "--cached", "--name-only", RQ2A_R1C_HEAD),
    ):
        names = _git(*args).stdout.decode().splitlines()
        if any(not _allowed_path(name) for name in names):
            raise RQ2AR2AValidationError(
                "BLOCKED_RQ2_A_R2A_PROTECTED_SOURCE_MUTATED"
            )


def assert_gitignore_contract() -> None:
    base = _git("show", f"{RQ2A_R1C_HEAD}:.gitignore").stdout.decode("utf-8")
    expected = base.rstrip("\n") + "\n" + "\n".join(IGNORE_ADDITIONS) + "\n"
    if (ROOT / ".gitignore").read_text(encoding="utf-8") != expected:
        raise RQ2AR2AValidationError(".gitignore differs from exact R2A additions")


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
            raise RQ2AR2AValidationError(f"provider/network import in {name}")


def _packet_freeze_manifest(
    identity: dict[str, Any],
    correction: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "human-packet-freeze-manifest-v1",
        "stage": "RQ2-A-R2A",
        "status": "FROZEN_FOR_AGREEMENT_AND_ADJUDICATION",
        "original_input_identities": {
            key: identity[key] for key in ("original_a", "corrected_a", "completed_b")
        },
        "r1c_blank_template_sha256": identity["r1c_blank_template_sha256"],
        "row_count_per_packet": identity["row_count_per_packet"],
        "column_count_per_packet": identity["column_count_per_packet"],
        "case_set_sha256": identity["case_set_sha256"],
        "reviewer_a_order_sha256": identity["reviewer_a_order_sha256"],
        "reviewer_b_order_sha256": identity["reviewer_b_order_sha256"],
        "fixed_case_fields_match_r1c_templates": True,
        "limited_reviewer_a_correction": correction,
        "date_canonicalisation": {
            "from": "2026/8/26",
            "to": "2026-08-26",
            "method": "EXACT_BYTE_REPLACEMENT",
            "canonical_packets": canonical,
        },
        "reviewer_ids": ["REVIEWER_A", "REVIEWER_B"],
        "reviewer_ids_are_different": True,
        "original_inputs_preserved": True,
        "canonical_packets_local_only": True,
        "reviewer_answer_modified_beyond_authorised_changes": False,
    }


def _generate() -> dict[str, Any]:
    paths, identity = validate_packet_identities(ROOT)
    correction = validate_limited_correction(paths, ROOT)
    canonical = write_canonical_packets(paths, ROOT)
    agreement = run_agreement(ROOT)
    case_summary = build_adjudication_case_summary(ROOT)
    packet_manifest = write_adjudication_packet(ROOT)
    attestation = independence_attestation_document()
    freeze = _packet_freeze_manifest(identity, correction, canonical)
    values = {
        "human_review_independence_attestation_v1.json": attestation,
        "human_packet_freeze_manifest_v1.json": freeze,
        "human_agreement_results_v1.json": agreement,
        "adjudication_case_summary_v1.json": case_summary,
        "adjudication_packet_manifest_v1.json": packet_manifest,
    }
    for name, value in values.items():
        (HERE / name).write_bytes(canonical_json_bytes(value))
    return {
        "paths": paths,
        "identity": identity,
        "correction": correction,
        "canonical": canonical,
        "agreement": agreement,
        "case_summary": case_summary,
        "packet_manifest": packet_manifest,
        "attestation": attestation,
        "freeze": freeze,
    }


def _snapshot_generated() -> dict[str, bytes]:
    safe = [name for name in SAFE_JSON_FILES if name != "rq2a_r2a_preflight_report_v1.json"]
    local = (CANONICAL_A_RELATIVE, CANONICAL_B_RELATIVE, ADJUDICATION_PACKET_RELATIVE)
    return {
        **{f"safe:{name}": (HERE / name).read_bytes() for name in safe},
        **{f"local:{relative.as_posix()}": (ROOT / relative).read_bytes() for relative in local},
    }


def assert_double_build() -> dict[str, Any]:
    first_result = _generate()
    first = _snapshot_generated()
    second_result = _generate()
    second = _snapshot_generated()
    comparable = ("identity", "correction", "canonical", "agreement", "case_summary", "packet_manifest", "attestation", "freeze")
    if first != second or any(first_result[key] != second_result[key] for key in comparable):
        raise RQ2AR2AValidationError("R2A double build is not byte-identical")
    return second_result


def assert_canonical_packets() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    path_a, path_b = ROOT / CANONICAL_A_RELATIVE, ROOT / CANONICAL_B_RELATIVE
    if sha256_file(path_a) != CANONICAL_A_SHA256 or sha256_file(path_b) != CANONICAL_B_SHA256:
        raise RQ2AR2AValidationError("canonical packet identity mismatch")
    rows_a, rows_b = _read_csv(path_a), _read_csv(path_b)
    if tuple(rows_a[0]) != (*VISIBLE_FIELDS, *HUMAN_FIELDS) or tuple(rows_b[0]) != (
        *VISIBLE_FIELDS,
        *HUMAN_FIELDS,
    ):
        raise RQ2AR2AValidationError("canonical packet columns mismatch")
    reviewers = validate_independent_reviewer_ids(rows_a, rows_b)
    if reviewers != ("REVIEWER_A", "REVIEWER_B"):
        raise RQ2AR2AValidationError("canonical reviewer identity mismatch")
    if {row["review_date"] for row in rows_a + rows_b} != {"2026-08-26"}:
        raise RQ2AR2AValidationError("canonical review date mismatch")
    if {row["review_case_id"] for row in rows_a} != {
        row["review_case_id"] for row in rows_b
    }:
        raise RQ2AR2AValidationError("canonical packet case set mismatch")
    for relative in (CANONICAL_A_RELATIVE, CANONICAL_B_RELATIVE):
        if _git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2AR2AValidationError("canonical packet is not ignored")
        if not _git("ls-files", "--error-unmatch", relative.as_posix(), check=False).returncode:
            raise RQ2AR2AValidationError("canonical packet is tracked")
    return rows_a, rows_b


def assert_agreement_reproducibility() -> dict[str, Any]:
    observed = _json(HERE / "human_agreement_results_v1.json")
    regenerated = run_agreement(ROOT)
    if observed != regenerated:
        raise RQ2AR2AValidationError("agreement result is not reproducible")
    validate_expected_agreement(observed)
    return observed


def assert_adjudication_outputs() -> None:
    expected = build_adjudication_case_summary(ROOT)
    if _json(HERE / "adjudication_case_summary_v1.json") != expected:
        raise RQ2AR2AValidationError("adjudication summary mismatch")
    packet_path = ROOT / ADJUDICATION_PACKET_RELATIVE
    if packet_path.read_bytes() != build_adjudication_packet_bytes(ROOT):
        raise RQ2AR2AValidationError("adjudication packet is not reproducible")
    rows = _read_csv(packet_path)
    if len(rows) != 5 or tuple(rows[0]) != PACKET_FIELDS:
        raise RQ2AR2AValidationError("adjudication packet shape mismatch")
    if any(row[field] for row in rows for field in BLANK_DECISION_FIELDS):
        raise RQ2AR2AValidationError("adjudication decision was prefilled")
    if any(
        row["query_rewrite_performed"] != "false"
        or row["assistant_context_attached"] != "false"
        for row in rows
    ):
        raise RQ2AR2AValidationError("adjudication immutable flags mismatch")
    if set(PACKET_FIELDS) & FORBIDDEN_COLUMNS:
        raise RQ2AR2AValidationError("forbidden adjudication packet column")
    if _git(
        "check-ignore", "-q", "--", ADJUDICATION_PACKET_RELATIVE.as_posix(), check=False
    ).returncode:
        raise RQ2AR2AValidationError("adjudication packet is not ignored")
    if not _git(
        "ls-files", "--error-unmatch", ADJUDICATION_PACKET_RELATIVE.as_posix(), check=False
    ).returncode:
        raise RQ2AR2AValidationError("adjudication packet is tracked")


def _tracked_output_paths() -> list[Path]:
    return [
        *(HERE / name for name in PYTHON_FILES),
        *(ROOT / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
        *(HERE / name for name in SAFE_JSON_FILES),
    ]


def _governed_text_values() -> list[str]:
    values: set[str] = set()
    for relative in (CANONICAL_A_RELATIVE, CANONICAL_B_RELATIVE):
        for row in _read_csv(ROOT / relative):
            for field in (
                "current_query",
                "necessary_conversation_history",
                "reviewer_rationale",
            ):
                text = str(row.get(field) or "").strip()
                if len(text) >= 12:
                    values.add(text)
    return sorted(values)


def governed_text_leak_scan() -> dict[str, Any]:
    values = _governed_text_values()
    scanned = [path for path in _tracked_output_paths() if path.is_file()]
    if (ROOT / CHECKSUM_RELATIVE).is_file():
        scanned.append(ROOT / CHECKSUM_RELATIVE)
    leaks: list[str] = []
    absolute_marker = "/" + "Users" + "/"
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if absolute_marker in text or any(value in text for value in values):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RQ2AR2AValidationError("governed-text leak: " + ", ".join(leaks))
    return {
        "status": "PASS",
        "governed_text_value_count": len(values),
        "scanned_file_count": len(scanned),
        "leak_count": 0,
    }


def assert_safe_json() -> None:
    prohibited_keys = {
        "current_query",
        "necessary_conversation_history",
        "reviewer_rationale",
        "query",
        "history",
        "rationale",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) & prohibited_keys:
                raise RQ2AR2AValidationError("governed field in safe JSON")
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for name in SAFE_JSON_FILES:
        value = _json(HERE / name)
        absolute_marker = "/" + "Users" + "/"
        if absolute_marker in json.dumps(value, ensure_ascii=False):
            raise RQ2AR2AValidationError(f"absolute path in safe JSON: {name}")
        walk(value)


def assert_staged_content_safe() -> None:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode().splitlines()
    for relative in names:
        if not _allowed_path(relative):
            raise RQ2AR2AValidationError(f"staged path outside allowlist: {relative}")
        if any(marker in relative for marker in ("local_review/", "local_adjudication/", "local_artifacts/")):
            raise RQ2AR2AValidationError(f"local-only content staged: {relative}")


def assert_protected_sources_unchanged() -> None:
    paths, _ = validate_packet_identities(ROOT)
    identities = (
        (paths.original_a, ORIGINAL_A_SHA256),
        (paths.corrected_a, CORRECTED_A_SHA256),
        (paths.completed_b, COMPLETED_B_SHA256),
        (ROOT / R1C_MAPPING_RELATIVE, SOURCE_MAPPING_SHA256),
    )
    if any(sha256_file(path) != expected for path, expected in identities):
        raise RQ2AR2AValidationError("protected local source changed")
    changed = _git("diff", "--name-only", RQ2A_R1C_HEAD).stdout.decode().splitlines()
    protected_prefixes = (
        "app/",
        "main.py",
        "evaluation/capability_routing_v1_r1c/",
        "evaluation/capability_routing_v1_r1b/",
        "evaluation/capability_routing_v1/",
    )
    if any(name.startswith(protected_prefixes) for name in changed):
        raise RQ2AR2AValidationError(
            "BLOCKED_RQ2_A_R2A_PROTECTED_SOURCE_MUTATED"
        )


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
            raise RQ2AR2AValidationError(f"output checksum mismatch: {relative}")
    if observed != expected:
        raise RQ2AR2AValidationError("output checksum member mismatch")


def _preflight(generated: dict[str, Any]) -> dict[str, Any]:
    leak = governed_text_leak_scan()
    agreement = generated["agreement"]
    return {
        "schema_version": "rq2a-r2a-preflight-report-v1",
        "stage": "RQ2-A-R2A",
        "status": "PASS",
        "approved_starting_branch": "research/rq2-a-r1c-authentic-provenance-closure",
        "approved_starting_head": RQ2A_R1C_HEAD,
        "approved_starting_parent": RQ2A_R1C_PARENT,
        "target_branch": TARGET_BRANCH,
        "starting_tree_sha256": RQ2A_R1C_TREE_SHA256,
        "rq2a_r1c_review_zip_sha256": RQ2A_R1C_REVIEW_ZIP_SHA256,
        "rq2a_r1c_checksum_count": RQ2A_R1C_CHECKSUM_COUNT,
        "input_packet_sha256": {
            "original_a": ORIGINAL_A_SHA256,
            "corrected_a": CORRECTED_A_SHA256,
            "completed_b": COMPLETED_B_SHA256,
        },
        "canonical_packet_sha256": {
            "reviewer_a": CANONICAL_A_SHA256,
            "reviewer_b": CANONICAL_B_SHA256,
        },
        "source_mapping_sha256": SOURCE_MAPPING_SHA256,
        "source_counts": {"authentic": 25, "synthetic": 35, "overall": 60},
        "limited_reviewer_a_changed_cell_count": 7,
        "reviewer_answer_modified_beyond_authorised_changes": False,
        "independence_authority_basis": "USER_EXPLICIT_ATTESTATION",
        "agreement_calculated": True,
        "overall_capability_exact_set_agreement": agreement["overall_60"][
            "capability_set"
        ]["exact_set_agreement"],
        "adjudication_case_count": 5,
        "adjudication_decisions_filled": False,
        "capability_gold_frozen": False,
        "hidden_proposal_accessed": False,
        "track_a_accessed": False,
        "track_b_accessed": False,
        "model_training_performed": False,
        "provider_calls": 0,
        "network_access": False,
        "production_source_change_count": 0,
        "threshold_tuning_performed": False,
        "p1_implemented": False,
        "p2_implemented": False,
        "rq2a_r2b_started": False,
        "double_build_byte_identical": True,
        "governed_text_leak_scan": leak,
        "expected_test_coverage_count": len(EXPECTED_TEST_COVERAGE),
        "expected_test_coverage": list(EXPECTED_TEST_COVERAGE),
        "expected_relative_commit_count_after_commit": 1,
    }


def build_all() -> None:
    assert_starting_lineage()
    assert_r1c_artifacts()
    assert_change_scope()
    assert_gitignore_contract()
    assert_all_python_ast()
    assert_no_provider_network_surface()
    assert_protected_sources_unchanged()
    generated = assert_double_build()
    assert_canonical_packets()
    assert_agreement_reproducibility()
    assert_adjudication_outputs()
    (HERE / "rq2a_r2a_preflight_report_v1.json").write_bytes(
        canonical_json_bytes(_preflight(generated))
    )
    write_output_checksums()
    validate_all()


def validate_all() -> None:
    assert_starting_lineage()
    assert_r1c_artifacts()
    assert_change_scope()
    assert_gitignore_contract()
    assert_all_python_ast()
    assert_no_provider_network_surface()
    validate_packet_identities(ROOT)
    validate_limited_correction(resolve_packet_paths(ROOT), ROOT)
    assert_canonical_packets()
    assert_agreement_reproducibility()
    assert_adjudication_outputs()
    assert_safe_json()
    assert_staged_content_safe()
    governed_text_leak_scan()
    validate_output_checksums()
    assert_protected_sources_unchanged()


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
                "reviewer_packet_count": 2,
                "source_counts": {"authentic": 25, "synthetic": 35},
                "adjudication_case_count": 5,
                "adjudication_decisions_filled": False,
                "capability_gold_frozen": False,
                "track_a_accessed": False,
                "track_b_accessed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
