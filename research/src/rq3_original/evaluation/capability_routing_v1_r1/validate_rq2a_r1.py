"""Build and validate the complete RQ2-A-R1 protocol repair."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from . import (
    HERE,
    NEW_REVIEW_A_RELATIVE,
    NEW_REVIEW_B_RELATIVE,
    OLD_REVIEW_PACKET_IDENTITIES,
    RAW_SYNTHETIC_SOURCE_RELATIVE,
    ROOT,
    RQ2A_HEAD,
    RQ2A_PARENT,
    RQ2A_STARTING_TREE_SHA256,
    canonical_json_bytes,
    require_exact_synthetic_source,
    sha256_file,
)
from .adjudication_contract import human_adjudication_contract_document
from .agreement_metrics import human_agreement_contract_document
from .baseline_identity_correction import (
    B0_MEASURED,
    CURRENT_MEASURED_BASELINE,
    FUTURE_UNMEASURED_B0,
    assert_aggregate_identity,
    baseline_identity_contract,
    write_corrected_projection,
)
from .build_reviewer_packets_v1_1 import build_reviewer_packets_v1_1
from .calibration_bank_authority import build_synthetic_authority, write_synthetic_authority
from .human_review_schema import HUMAN_FIELDS, human_review_schema_document, validate_blank_packet


PYTHON_FILES = (
    "__init__.py",
    "calibration_bank_authority.py",
    "baseline_identity_correction.py",
    "human_review_schema.py",
    "agreement_metrics.py",
    "adjudication_contract.py",
    "build_reviewer_packets_v1_1.py",
    "validate_rq2a_r1.py",
    "test_rq2a_r1_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2A_R1_SYNTHETIC_CALIBRATION_BANK_LIMITATIONS.md",
    "RQ2A_R1_LEGACY_BASELINE_IDENTITY_CORRECTION.md",
    "RQ2A_R1_HUMAN_REVIEW_AND_ADJUDICATION_PROTOCOL.md",
)
SAFE_JSON_FILES = (
    "synthetic_calibration_bank_authority_v1.json",
    "legacy_capability_projection_v1_1.json",
    "human_review_schema_v1_1.json",
    "human_agreement_contract_v1.json",
    "human_adjudication_contract_v1.json",
    "reviewer_packet_manifest_v1_1.json",
    "rq2a_r1_preflight_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1/rq2a_r1_output_checksums_v1.sha256"
)
EXPECTED_TEST_COVERAGE = (
    "rq2a_starting_head",
    "raw_synthetic_source_hash",
    "raw_source_36_synthetic_records",
    "authentic_student_voice_false",
    "final_evaluation_eligibility_false",
    "old_b0_label_superseded",
    "current_measured_baseline_b1",
    "future_b0_not_measured",
    "original_aggregate_counts_unchanged",
    "old_reviewer_packets_unchanged",
    "new_packet_case_sets_identical",
    "new_packet_orders_differ",
    "new_human_fields_blank",
    "accept_as_presented_removed",
    "reviewer_ids_must_differ",
    "naturalness_validation",
    "agreement_metrics_synthetic_fixtures",
    "zero_prevalence_kappa_safe",
    "exact_set_agreement",
    "jaccard",
    "adjudication_trigger_rules",
    "no_query_rewrite_in_adjudication",
    "coverage_gates",
    "packets_ignored",
    "track_a_rejected",
    "track_b_rejected",
    "no_provider_or_network",
    "production_sources_unchanged",
    "double_build_byte_identical",
    "output_checksums_pass",
)


class RQ2AR1ValidationError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RQ2AR1ValidationError(
            f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace')}"
        )
    return result


def starting_tree_digest(root: Path = ROOT) -> str:
    tree = _git(root, "ls-tree", "-r", RQ2A_HEAD).stdout
    return hashlib.sha256(tree).hexdigest()


def assert_starting_lineage(root: Path = ROOT) -> None:
    if _git(root, "rev-parse", f"{RQ2A_HEAD}^").stdout.decode().strip() != RQ2A_PARENT:
        raise RQ2AR1ValidationError("RQ2-A parent mismatch")
    if starting_tree_digest(root) != RQ2A_STARTING_TREE_SHA256:
        raise RQ2AR1ValidationError("RQ2-A starting tree identity mismatch")
    if _git(root, "merge-base", "--is-ancestor", RQ2A_HEAD, "HEAD", check=False).returncode:
        raise RQ2AR1ValidationError("RQ2-A HEAD is not an ancestor")
    branch = _git(root, "branch", "--show-current").stdout.decode().strip()
    if branch != "research/rq2-a-r1-review-protocol-repair":
        raise RQ2AR1ValidationError("RQ2-A-R1 branch mismatch")
    if _git(root, "remote").stdout.strip() or _git(root, "tag", "--list").stdout.strip():
        raise RQ2AR1ValidationError("remote/tag count is not zero")


def _allowed_path(relative: str) -> bool:
    return bool(
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_v1_r1/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2A_R1_")
    )


def assert_change_scope(root: Path = ROOT) -> None:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.decode(
        "utf-8"
    )
    for line in status.splitlines():
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not _allowed_path(relative):
            raise RQ2AR1ValidationError(f"change outside RQ2-A-R1 scope: {relative}")
    for args in (
        ("diff", "--name-only", RQ2A_HEAD),
        ("diff", "--cached", "--name-only", RQ2A_HEAD),
    ):
        names = _git(root, *args).stdout.decode("utf-8").splitlines()
        if any(not _allowed_path(relative) for relative in names):
            raise RQ2AR1ValidationError("existing protected source was modified")


def assert_original_rq2a_files_unchanged(root: Path = ROOT) -> None:
    protected = (
        "Home.py",
        "pages",
        "utils",
        "tests",
        "semantic_runtime",
        "evaluation/learned_intent_ranking",
        "evaluation/capability_routing_v1",
        "docs/thesis_mainline/rq1",
        "docs/thesis_mainline/rq2/RQ2A_CAPABILITY_SCHEMA_AND_ANNOTATION_GUIDE.md",
        "docs/thesis_mainline/rq2/RQ2A_CONTEXT_ENVELOPE_CONTRACT.md",
        "docs/thesis_mainline/rq2/RQ2A_DEVELOPMENT_BENCHMARK_PROTOCOL.md",
        "docs/thesis_mainline/rq2/RQ2A_LEGACY_HARD_GATING_BASELINE.md",
        "docs/thesis_mainline/rq2/RQ2A_RESEARCH_QUESTION_AND_ARCHITECTURE.md",
    )
    if _git(root, "diff", "--quiet", RQ2A_HEAD, "--", *protected, check=False).returncode:
        raise RQ2AR1ValidationError("BLOCKED_RQ2_A_R1_PROTECTED_SOURCE_MUTATED")
    if _git(
        root, "diff", "--cached", "--quiet", RQ2A_HEAD, "--", *protected, check=False
    ).returncode:
        raise RQ2AR1ValidationError("BLOCKED_RQ2_A_R1_PROTECTED_SOURCE_MUTATED")


def assert_gitignore_unchanged(root: Path = ROOT) -> None:
    original = _git(root, "show", f"{RQ2A_HEAD}:.gitignore").stdout
    if (root / ".gitignore").read_bytes() != original:
        raise RQ2AR1ValidationError("unexpected .gitignore change")


def assert_old_packets_unchanged(root: Path = ROOT) -> None:
    for relative, identity in OLD_REVIEW_PACKET_IDENTITIES.items():
        packet = root / relative
        with packet.open("r", encoding="utf-8", newline="") as handle:
            record_count = sum(1 for _ in csv.DictReader(handle))
        observed = {
            "sha256": sha256_file(packet),
            "size_bytes": packet.stat().st_size,
            "record_count": record_count,
        }
        if observed != identity:
            raise RQ2AR1ValidationError(f"old reviewer packet changed: {relative}")


def assert_all_python_ast() -> None:
    for name in PYTHON_FILES:
        file_path = HERE / name
        ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))


def _tracked_output_paths(root: Path) -> list[Path]:
    return [
        *(HERE / name for name in PYTHON_FILES),
        *(root / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
        *(HERE / name for name in SAFE_JSON_FILES),
    ]


def _governed_strings(root: Path) -> list[str]:
    source = require_exact_synthetic_source(RAW_SYNTHETIC_SOURCE_RELATIVE)
    strings: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        strings.append(str(record.get("current_query") or ""))
        strings.extend(
            str(turn.get("content") or "")
            for turn in record.get("conversation_history") or []
        )
    return sorted({value for value in strings if len(value.strip()) >= 8})


def governed_text_leak_scan(root: Path = ROOT) -> dict[str, Any]:
    marker = "/" + "Users" + "/"
    strings = _governed_strings(root)
    leaks: list[str] = []
    scanned = _tracked_output_paths(root)
    checksum = root / CHECKSUM_RELATIVE
    if checksum.is_file():
        scanned.append(checksum)
    for file_path in scanned:
        text = file_path.read_text(encoding="utf-8")
        if marker in text or str(root) in text:
            leaks.append(f"absolute-path:{file_path.relative_to(root)}")
        if any(value in text for value in strings):
            leaks.append(f"synthetic-text:{file_path.relative_to(root)}")
    if leaks:
        raise RQ2AR1ValidationError("governed-text leak: " + ", ".join(leaks))
    return {
        "status": "PASS",
        "governed_string_count": len(strings),
        "scanned_file_count": len(scanned),
        "leak_count": 0,
    }


def assert_safe_json() -> None:
    marker = "/" + "Users" + "/"
    for name in SAFE_JSON_FILES:
        value = json.loads((HERE / name).read_text(encoding="utf-8"))
        if marker in json.dumps(value, ensure_ascii=False):
            raise RQ2AR1ValidationError(f"absolute path in safe JSON: {name}")


def _read_packet(relative: Path, root: Path = ROOT) -> list[dict[str, str]]:
    with (root / relative).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_new_packets(root: Path = ROOT) -> None:
    rows_a = _read_packet(NEW_REVIEW_A_RELATIVE, root)
    rows_b = _read_packet(NEW_REVIEW_B_RELATIVE, root)
    if len(rows_a) != 35 or len(rows_b) != 35:
        raise RQ2AR1ValidationError("new reviewer packet count mismatch")
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    ids_a = [row["case_id"] for row in rows_a]
    ids_b = [row["case_id"] for row in rows_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise RQ2AR1ValidationError("new reviewer packet set/order mismatch")
    for relative in (NEW_REVIEW_A_RELATIVE, NEW_REVIEW_B_RELATIVE):
        if _git(root, "check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2AR1ValidationError("new reviewer packet is not ignored")


def assert_no_provider_network_surface() -> None:
    prohibited_imports = {"openai", "firebase_admin", "requests", "httpx", "urllib3"}
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
        if imports & prohibited_imports:
            raise RQ2AR1ValidationError(f"provider/network import in {name}")


def _write_static_contracts() -> None:
    (HERE / "human_review_schema_v1_1.json").write_bytes(
        canonical_json_bytes(human_review_schema_document())
    )
    (HERE / "human_agreement_contract_v1.json").write_bytes(
        canonical_json_bytes(human_agreement_contract_document())
    )
    (HERE / "human_adjudication_contract_v1.json").write_bytes(
        canonical_json_bytes(human_adjudication_contract_document())
    )


def _snapshot_build(root: Path) -> dict[str, bytes]:
    relatives = (
        NEW_REVIEW_A_RELATIVE,
        NEW_REVIEW_B_RELATIVE,
        Path("evaluation/capability_routing_v1_r1/synthetic_calibration_bank_authority_v1.json"),
        Path("evaluation/capability_routing_v1_r1/legacy_capability_projection_v1_1.json"),
        Path("evaluation/capability_routing_v1_r1/human_review_schema_v1_1.json"),
        Path("evaluation/capability_routing_v1_r1/human_agreement_contract_v1.json"),
        Path("evaluation/capability_routing_v1_r1/human_adjudication_contract_v1.json"),
        Path("evaluation/capability_routing_v1_r1/reviewer_packet_manifest_v1_1.json"),
    )
    return {relative.as_posix(): (root / relative).read_bytes() for relative in relatives}


def assert_double_build(root: Path = ROOT) -> None:
    write_synthetic_authority(root)
    write_corrected_projection(root)
    _write_static_contracts()
    build_reviewer_packets_v1_1(root)
    first = _snapshot_build(root)
    write_synthetic_authority(root)
    write_corrected_projection(root)
    _write_static_contracts()
    build_reviewer_packets_v1_1(root)
    second = _snapshot_build(root)
    if first != second:
        raise RQ2AR1ValidationError("RQ2-A-R1 double build is not byte-identical")


def _preflight_report(
    authority: dict[str, Any], baseline: dict[str, Any], packets: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "rq2a-r1-preflight-report-v1",
        "stage": "RQ2-A-R1",
        "status": "PASS",
        "approved_starting_branch": "research/rq2-a-capability-contract",
        "approved_starting_head": RQ2A_HEAD,
        "approved_starting_parent": RQ2A_PARENT,
        "repair_branch": "research/rq2-a-r1-review-protocol-repair",
        "starting_tree_sha256": RQ2A_STARTING_TREE_SHA256,
        "synthetic_authority_status": authority["status"],
        "synthetic_bank_alias": authority["alias"],
        "raw_source_sha256": authority["raw_source_sha256"],
        "raw_record_count": authority["raw_record_count"],
        "canonical_case_count": authority["canonical_case_count"],
        "authentic_student_voice": False,
        "final_evaluation_eligible": False,
        "current_measured_baseline": baseline["baseline_identity"],
        "current_baseline_context_resolution_enabled": True,
        "future_b0_identity": FUTURE_UNMEASURED_B0,
        "future_b0_measured": B0_MEASURED,
        "future_b0_measurement_stage": "RQ2-B",
        "old_packets_unchanged": packets["old_packets_unchanged"],
        "new_packet_case_count": packets["canonical_case_count"],
        "new_packets_all_human_fields_blank": packets["all_human_fields_blank"],
        "required_human_reviewer_count": 2,
        "reviewer_ids_must_differ": True,
        "agreement_contract_frozen": True,
        "adjudication_contract_frozen": True,
        "human_review_completed": False,
        "human_labels_filled": False,
        "adjudication_completed": False,
        "synthetic_calibration_gold_frozen": False,
        "track_a_accessed": False,
        "track_b_accessed": False,
        "provider_calls": 0,
        "network_access": False,
        "model_training_performed": False,
        "production_source_change_count": 0,
        "production_router_implemented": False,
        "p1_implemented": False,
        "p2_implemented": False,
        "rq2_b_implemented": False,
        "test_coverage_count": len(EXPECTED_TEST_COVERAGE),
        "test_coverage": list(EXPECTED_TEST_COVERAGE),
        "double_build_byte_identical": True,
        "governed_text_leak_count": 0,
        "expected_relative_commit_count_after_commit": 1,
    }


def output_checksum_targets(root: Path = ROOT) -> list[Path]:
    return sorted(
        _tracked_output_paths(root), key=lambda file_path: file_path.relative_to(root).as_posix()
    )


def write_output_checksums(root: Path = ROOT) -> None:
    lines = [
        f"{sha256_file(file_path)}  {file_path.relative_to(root).as_posix()}"
        for file_path in output_checksum_targets(root)
    ]
    (root / CHECKSUM_RELATIVE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_output_checksums(root: Path = ROOT) -> None:
    expected_paths = {
        file_path.relative_to(root).as_posix() for file_path in output_checksum_targets(root)
    }
    observed: set[str] = set()
    for line in (root / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        observed.add(relative)
        if sha256_file(root / relative) != digest:
            raise RQ2AR1ValidationError(f"checksum mismatch: {relative}")
    if observed != expected_paths:
        raise RQ2AR1ValidationError("checksum member set mismatch")


def assert_staged_content_safe(root: Path = ROOT) -> None:
    names = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode(
        "utf-8"
    ).splitlines()
    for relative in names:
        if not _allowed_path(relative):
            raise RQ2AR1ValidationError(f"staged path outside allowlist: {relative}")
        if any(
            marker in relative
            for marker in (
                "local_review/",
                "raw_case_bank/",
                "local_artifacts/",
                "final_results_local/",
            )
        ):
            raise RQ2AR1ValidationError(f"local-only content staged: {relative}")


def build_all(root: Path = ROOT) -> None:
    assert_starting_lineage(root)
    assert_change_scope(root)
    assert_original_rq2a_files_unchanged(root)
    assert_gitignore_unchanged(root)
    assert_old_packets_unchanged(root)
    assert_all_python_ast()
    assert_no_provider_network_surface()
    assert_double_build(root)
    authority = build_synthetic_authority(root)
    baseline = write_corrected_projection(root)
    assert_aggregate_identity(root)
    packets = build_reviewer_packets_v1_1(root)
    report = _preflight_report(authority, baseline, packets)
    (HERE / "rq2a_r1_preflight_report_v1.json").write_bytes(
        canonical_json_bytes(report)
    )
    write_output_checksums(root)
    validate_all(root)


def validate_all(root: Path = ROOT) -> None:
    assert_starting_lineage(root)
    assert_change_scope(root)
    assert_original_rq2a_files_unchanged(root)
    assert_gitignore_unchanged(root)
    assert_old_packets_unchanged(root)
    assert_all_python_ast()
    assert_no_provider_network_surface()
    build_synthetic_authority(root)
    assert_aggregate_identity(root)
    assert_new_packets(root)
    assert_safe_json()
    assert_staged_content_safe(root)
    governed_text_leak_scan(root)
    validate_output_checksums(root)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.build:
        build_all(ROOT)
    else:
        validate_all(ROOT)
    print(
        json.dumps(
            {
                "status": "PASS",
                "build": args.build,
                "current_measured_baseline": CURRENT_MEASURED_BASELINE,
                "future_b0_measured": False,
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
