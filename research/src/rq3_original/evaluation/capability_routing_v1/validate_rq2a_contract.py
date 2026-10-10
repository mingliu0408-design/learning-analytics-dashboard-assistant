"""Build and validate the complete RQ2-A research-only freeze."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from . import (
    HERE,
    LOCAL_BANK_RELATIVE,
    LOCAL_LINEAGE_RELATIVE,
    LOCAL_PROPOSAL_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    LOCAL_SYNTHETIC_SOURCE_RELATIVE,
    ROOT,
    RQ1_C1_HEAD,
    RQ1_C1_PARENT,
    canonical_json_bytes,
    require_frozen_rq1_router,
    sha256_file,
)
from .build_capability_development_bank import write_safe_bank_summaries
from .build_capability_review_packets import HUMAN_FIELDS, build_review_packets
from .capability_case_schema import capability_case_schema_document
from .capability_schema import capability_schema_document
from .context_envelope import context_envelope_schema_document
from .legacy_hard_route_adapter import build_legacy_baseline


RQ1_SAFE_OUTPUT_HASHES = {
    "evaluation/learned_intent_ranking/rq1c_final/rq1c1_final_metrics_v1.json": (
        "77397fdc3a611eda583904051956769c85a4ec6883fd6b7ada55eaf143167904"
    ),
    "evaluation/learned_intent_ranking/rq1c_final/rq1c1_router_selection_manifest_v1.json": (
        "337dd3d78d8c3d47926759a4670606f6a9e1912bf2f98c265ba8467005a04c9a"
    ),
    "evaluation/learned_intent_ranking/rq1c_final/rq1c1_execution_manifest_v1.json": (
        "8285d1ee17a29bf9aa0ecea35e45813ae33bb88cab7ce32c3fa6e656aa315dfb"
    ),
    "evaluation/learned_intent_ranking/rq1c_final/rq1c1_final_contamination_report_v1.json": (
        "90c16352254e0bdd485ad3a281d48a3bdf36de6bacc2b5a139f65e8150da127a"
    ),
}
PROTECTED_PATHS = (
    "Home.py",
    "pages",
    "utils",
    "tests",
    "semantic_runtime",
    "evaluation/learned_intent_ranking",
    "evaluation/functional_qa",
    "evaluation/unified_benchmark_scenarios.jsonl",
    "evaluation/multiturn_scenarios.jsonl",
    "evaluation/rag_scenarios.jsonl",
    "evaluation/scenarios.jsonl",
    "docs/thesis_mainline/rq1",
)
PROTECTED_TREE_SHA256 = (
    "d2335db2ff623ce36b0795dcde3bc98625a24b42aea3c0ea769680ffba9728c4"
)
PYTHON_FILES = (
    "__init__.py",
    "capability_schema.py",
    "context_envelope.py",
    "capability_case_schema.py",
    "legacy_hard_route_adapter.py",
    "source_inventory.py",
    "duplicate_lineage.py",
    "build_capability_development_bank.py",
    "build_capability_review_packets.py",
    "validate_rq2a_contract.py",
    "test_rq2a_contract_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2A_RESEARCH_QUESTION_AND_ARCHITECTURE.md",
    "RQ2A_CONTEXT_ENVELOPE_CONTRACT.md",
    "RQ2A_CAPABILITY_SCHEMA_AND_ANNOTATION_GUIDE.md",
    "RQ2A_DEVELOPMENT_BENCHMARK_PROTOCOL.md",
    "RQ2A_LEGACY_HARD_GATING_BASELINE.md",
)
SAFE_JSON_FILES = (
    "capability_schema_v1.json",
    "context_envelope_schema_v1.json",
    "legacy_capability_projection_v1.json",
    "capability_source_inventory_v1.json",
    "capability_development_bank_summary_v1.json",
    "capability_duplicate_lineage_summary_v1.json",
    "capability_review_packet_manifest_v1.json",
    "rq2a_preflight_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_v1/rq2a_output_checksums_v1.sha256"
)
EXPECTED_TEST_COVERAGE = (
    "rq1_selection_manifest_hash",
    "frozen_router_c0",
    "m64_rejected",
    "track_a_rejected",
    "track_b_rejected",
    "context_envelope_schema",
    "maximum_recent_turns_four",
    "correction_precedence",
    "replaced_goal_suppression",
    "no_cross_student_context",
    "multi_label_capability_plan",
    "empty_plan_rejected",
    "clarification_exclusive",
    "working_context_not_capability",
    "deterministic_guards_not_predicted",
    "legacy_adapter_calls_production",
    "legacy_c0_identity",
    "retrieval_projection_actual_request",
    "planning_projection_actual_planner",
    "working_context_episodic_separation",
    "duplicate_canonicalisation",
    "context_variant_preserved",
    "source_lineage_preserved",
    "proposal_not_gold",
    "review_human_fields_blank",
    "review_case_sets_equal",
    "review_orders_different",
    "review_packets_ignored",
    "tracked_outputs_query_free",
    "provider_and_network_free",
    "production_files_unchanged",
    "double_build_byte_identical",
    "output_checksums_pass",
)


class RQ2AValidationError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RQ2AValidationError(
            f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace')}"
        )
    return result


def protected_tree_digest(root: Path = ROOT) -> str:
    result = _git(root, "ls-tree", "-r", RQ1_C1_HEAD, "--", *PROTECTED_PATHS)
    return hashlib.sha256(result.stdout).hexdigest()


def assert_protected_sources_unchanged(root: Path = ROOT) -> None:
    if protected_tree_digest(root) != PROTECTED_TREE_SHA256:
        raise RQ2AValidationError("protected baseline tree identity mismatch")
    if _git(root, "diff", "--quiet", RQ1_C1_HEAD, "--", *PROTECTED_PATHS, check=False).returncode:
        raise RQ2AValidationError("BLOCKED_RQ2_A_PRODUCTION_SOURCE_MUTATED")
    if _git(root, "diff", "--cached", "--quiet", RQ1_C1_HEAD, "--", *PROTECTED_PATHS, check=False).returncode:
        raise RQ2AValidationError("BLOCKED_RQ2_A_PRODUCTION_SOURCE_MUTATED")
    untracked = _git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *PROTECTED_PATHS,
    ).stdout
    if untracked.strip():
        raise RQ2AValidationError("untracked protected-source content is present")


def _allowed_changed_path(relative: str) -> bool:
    return bool(
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_v1/")
        or relative.startswith("docs/thesis_mainline/rq2/")
    )


def assert_change_scope(root: Path = ROOT) -> None:
    output = _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.decode(
        "utf-8"
    )
    for line in output.splitlines():
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not _allowed_changed_path(relative):
            raise RQ2AValidationError(f"change outside RQ2-A scope: {relative}")


def assert_rq1_authority(root: Path = ROOT) -> dict[str, Any]:
    authority = require_frozen_rq1_router(root)
    for relative, expected in RQ1_SAFE_OUTPUT_HASHES.items():
        if sha256_file(root / relative) != expected:
            raise RQ2AValidationError(f"RQ1 safe output hash mismatch: {relative}")
    head_parent = _git(root, "rev-parse", f"{RQ1_C1_HEAD}^").stdout.decode().strip()
    if head_parent != RQ1_C1_PARENT:
        raise RQ2AValidationError("RQ1-C1 parent mismatch")
    return authority


def _tracked_output_paths(root: Path) -> list[Path]:
    return [
        root / ".gitignore",
        *(HERE / name for name in PYTHON_FILES),
        *(root / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
        *(HERE / name for name in SAFE_JSON_FILES),
    ]


def assert_all_python_ast() -> None:
    for name in PYTHON_FILES:
        path = HERE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _read_governed_strings(root: Path) -> list[str]:
    source = root / LOCAL_SYNTHETIC_SOURCE_RELATIVE
    values: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        values.append(str(row.get("current_query") or ""))
        for turn in row.get("conversation_history") or []:
            values.append(str(turn.get("content") or ""))
    return sorted({value for value in values if len(value.strip()) >= 8})


def governed_text_leak_scan(root: Path = ROOT) -> dict[str, Any]:
    governed = _read_governed_strings(root)
    scanned = _tracked_output_paths(root)
    leaks: list[str] = []
    user_home_marker = "/" + "Users" + "/"
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if user_home_marker in text or str(root) in text:
            leaks.append(f"absolute_path:{path.relative_to(root)}")
        for value in governed:
            if value and value in text:
                leaks.append(f"governed_text:{path.relative_to(root)}")
                break
    if leaks:
        raise RQ2AValidationError("governed-text leak: " + ", ".join(leaks))
    return {
        "status": "PASS",
        "governed_strings_checked": len(governed),
        "tracked_files_scanned": len(scanned),
        "leak_count": 0,
    }


def assert_safe_json() -> None:
    user_home_marker = "/" + "Users" + "/"
    for name in SAFE_JSON_FILES:
        path = HERE / name
        value = json.loads(path.read_text(encoding="utf-8"))
        serialised = json.dumps(value, ensure_ascii=False)
        if user_home_marker in serialised:
            raise RQ2AValidationError(f"absolute path in safe JSON: {name}")


def _review_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_review_packets(root: Path = ROOT) -> None:
    a_path = root / LOCAL_REVIEW_A_RELATIVE
    b_path = root / LOCAL_REVIEW_B_RELATIVE
    a_rows, b_rows = _review_rows(a_path), _review_rows(b_path)
    if len(a_rows) < 20 or len(a_rows) != len(b_rows):
        raise RQ2AValidationError("invalid review packet row counts")
    a_ids = [row["case_id"] for row in a_rows]
    b_ids = [row["case_id"] for row in b_rows]
    if set(a_ids) != set(b_ids) or a_ids == b_ids:
        raise RQ2AValidationError("invalid reviewer packet set/order")
    if any(row[field] for row in [*a_rows, *b_rows] for field in HUMAN_FIELDS):
        raise RQ2AValidationError("human review field is not blank")
    for relative in (LOCAL_REVIEW_A_RELATIVE, LOCAL_REVIEW_B_RELATIVE):
        if _git(root, "check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2AValidationError("review packet is not ignored")


def _snapshot_local_build(root: Path) -> dict[str, bytes]:
    relatives = (
        LOCAL_BANK_RELATIVE,
        LOCAL_LINEAGE_RELATIVE,
        LOCAL_PROPOSAL_RELATIVE,
        LOCAL_REVIEW_A_RELATIVE,
        LOCAL_REVIEW_B_RELATIVE,
        Path("evaluation/capability_routing_v1/capability_source_inventory_v1.json"),
        Path("evaluation/capability_routing_v1/capability_development_bank_summary_v1.json"),
        Path("evaluation/capability_routing_v1/capability_duplicate_lineage_summary_v1.json"),
        Path("evaluation/capability_routing_v1/capability_review_packet_manifest_v1.json"),
    )
    return {relative.as_posix(): (root / relative).read_bytes() for relative in relatives}


def assert_double_build(root: Path = ROOT) -> None:
    write_safe_bank_summaries(root)
    build_review_packets(root)
    first = _snapshot_local_build(root)
    write_safe_bank_summaries(root)
    build_review_packets(root)
    second = _snapshot_local_build(root)
    if first != second:
        raise RQ2AValidationError("development bank/review double build differs")


def _preflight_report(
    *,
    authority: dict[str, Any],
    bank: dict[str, Any],
    lineage: dict[str, Any],
    review: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rq2a-preflight-report-v1",
        "stage": "RQ2-A",
        "status": "PASS",
        "approved_starting_branch": "research/rq1-c1-final-evaluation-results",
        "approved_starting_head": RQ1_C1_HEAD,
        "approved_starting_parent": RQ1_C1_PARENT,
        "rq2a_branch": "research/rq2-a-capability-contract",
        "rq1_router_identity": "C0_COSINE",
        "rq1_selection": "C0_REMAINS_SELECTED",
        "rq1_decision_immutable": True,
        "rq1_post_final_tuning_authorised": False,
        "rq1_safe_output_hashes": RQ1_SAFE_OUTPUT_HASHES,
        "rq1_router_manifest_hash_verified": True,
        "rq1_execution_completed_once": True,
        "rq1_retry_permitted": False,
        "m64_used": False,
        "canonical_case_count": bank["canonical_case_count"],
        "minimum_case_gate_passed": bank["minimum_count_gate_passed"],
        "exact_duplicate_extra_count": lineage["exact_duplicate_extra_count"],
        "context_variants_merged": lineage["context_variants_merged"],
        "page_variants_merged": lineage["page_variants_merged"],
        "all_canonical_cases_enter_review": bank["all_canonical_cases_enter_review"],
        "reviewer_packets_blank": review["all_human_fields_blank"],
        "reviewer_packet_case_sets_equal": review["same_case_set"],
        "reviewer_packet_orders_different": review["different_row_order"],
        "legacy_baseline_status": baseline["status"],
        "legacy_baseline_identity": baseline["baseline_identity"],
        "provider_calls": baseline["provider_calls"],
        "firebase_calls": baseline["firebase_calls"],
        "network_access": baseline["network_access"],
        "training_performed": baseline["training_performed"],
        "protected_tree_sha256": PROTECTED_TREE_SHA256,
        "production_source_change_count": 0,
        "track_a_accessed": False,
        "track_a_lock_accessed": False,
        "track_b_accessed": False,
        "track_b_role": "FUTURE_CONTEXTUAL_HELD_OUT_SOURCE",
        "new_production_capability_router_implemented": False,
        "rq2_b_implemented": False,
        "rq2_c_implemented": False,
        "rq3_implemented": False,
        "test_coverage_count": len(EXPECTED_TEST_COVERAGE),
        "test_coverage": list(EXPECTED_TEST_COVERAGE),
        "double_build_byte_identical": True,
        "governed_text_leak_count": 0,
        "expected_relative_commit_count_after_commit": 1,
        "output_checksum_manifest_generated": True,
    }


def _write_schema_outputs() -> None:
    capability = capability_schema_document()
    capability["capability_case_contract"] = capability_case_schema_document()
    capability["future_conditions_frozen_not_implemented"] = {
        "B0": "ORIGINAL_QUERY_PLUS_FROZEN_GUARDS_PLUS_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION",
        "B1": "CURRENT_PRODUCTION_CONTEXT_RESOLUTION_PLUS_FROZEN_GUARDS_PLUS_C0_TOP1_HARD_ROUTE",
        "P1": "CONTEXT_ENVELOPE_PLUS_FROZEN_C0_VECTOR_PLUS_NEED_SIGNALS_PLUS_MULTILABEL_PLAN",
        "P2": "P1_PLUS_DUAL_GATED_RAG_PLUS_SELECTIVE_EPISODIC_MEMORY",
    }
    capability["future_capability_threshold_tuning_authorised"] = False
    capability["future_metrics_required"] = {
        "intent": ["MRR", "TOP1", "RECALL_AT_3"],
        "capability_set": [
            "EXACT_SET_ACCURACY",
            "MICRO_PRECISION",
            "MICRO_RECALL",
            "MICRO_F1",
            "MACRO_F1",
            "REQUIRED_CAPABILITY_RECALL",
            "UNNECESSARY_CAPABILITY_RATE",
            "FORBIDDEN_CAPABILITY_VIOLATION_RATE",
        ],
        "tool_activation": [
            "RAG_TRIGGER_PRECISION_RECALL",
            "PLANNER_ACTIVATION_PRECISION_RECALL",
            "EPISODIC_MEMORY_ACTIVATION_PRECISION_RECALL",
        ],
        "context": [
            "CONTEXT_RESOLUTION_ACCURACY",
            "FALSE_CONTEXT_USE_RATE",
            "STALE_MEMORY_USE_RATE",
            "UNNECESSARY_QUERY_ALTERATION_RATE",
        ],
        "safety_usability": [
            "CLARIFICATION_PRECISION",
            "UNNECESSARY_CLARIFICATION_RATE",
            "MISLEADING_ROUTE_RATE",
            "SAFE_DIRECT_RESPONSE_ACCURACY",
        ],
    }
    (HERE / "capability_schema_v1.json").write_bytes(canonical_json_bytes(capability))
    (HERE / "context_envelope_schema_v1.json").write_bytes(
        canonical_json_bytes(context_envelope_schema_document())
    )


def output_checksum_targets(root: Path = ROOT) -> list[Path]:
    return sorted(_tracked_output_paths(root), key=lambda path: path.relative_to(root).as_posix())


def write_output_checksums(root: Path = ROOT) -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(root).as_posix()}"
        for path in output_checksum_targets(root)
    ]
    (root / CHECKSUM_RELATIVE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_output_checksums(root: Path = ROOT) -> None:
    manifest = root / CHECKSUM_RELATIVE
    expected_paths = {
        path.relative_to(root).as_posix() for path in output_checksum_targets(root)
    }
    observed_paths: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        observed_paths.add(relative)
        if sha256_file(root / relative) != expected:
            raise RQ2AValidationError(f"output checksum mismatch: {relative}")
    if observed_paths != expected_paths:
        raise RQ2AValidationError("output checksum member set mismatch")


def assert_staged_content_safe(root: Path = ROOT) -> None:
    names = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode(
        "utf-8"
    ).splitlines()
    for relative in names:
        if not _allowed_changed_path(relative):
            raise RQ2AValidationError(f"staged path outside allowlist: {relative}")
        if any(
            marker in relative
            for marker in ("local_review/", "local_artifacts/", "raw_case_bank/", "tmp/")
        ):
            raise RQ2AValidationError(f"local-only content staged: {relative}")


def build_all(root: Path = ROOT) -> None:
    authority = assert_rq1_authority(root)
    assert_change_scope(root)
    assert_protected_sources_unchanged(root)
    assert_all_python_ast()
    assert_double_build(root)
    bank = json.loads((HERE / "capability_development_bank_summary_v1.json").read_text())
    lineage = json.loads(
        (HERE / "capability_duplicate_lineage_summary_v1.json").read_text()
    )
    review = json.loads((HERE / "capability_review_packet_manifest_v1.json").read_text())
    baseline = build_legacy_baseline(root)
    _write_schema_outputs()
    report = _preflight_report(
        authority=authority,
        bank=bank,
        lineage=lineage,
        review=review,
        baseline=baseline,
    )
    (HERE / "rq2a_preflight_report_v1.json").write_bytes(canonical_json_bytes(report))
    write_output_checksums(root)
    validate_all(root)


def validate_all(root: Path = ROOT) -> None:
    assert_rq1_authority(root)
    assert_change_scope(root)
    assert_protected_sources_unchanged(root)
    assert_all_python_ast()
    assert_safe_json()
    assert_review_packets(root)
    assert_staged_content_safe(root)
    governed_text_leak_scan(root)
    validate_output_checksums(root)
    if _git(root, "remote").stdout.strip():
        raise RQ2AValidationError("Git remote count is not zero")
    if _git(root, "tag", "--list").stdout.strip():
        raise RQ2AValidationError("Git tag count is not zero")
    branch = _git(root, "branch", "--show-current").stdout.decode().strip()
    if branch != "research/rq2-a-capability-contract":
        raise RQ2AValidationError("RQ2-A branch mismatch")


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
                "protected_tree_sha256": PROTECTED_TREE_SHA256,
                "track_a_accessed": False,
                "track_b_accessed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
