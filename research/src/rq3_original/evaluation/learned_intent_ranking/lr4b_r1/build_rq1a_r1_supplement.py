"""Build deterministic, aggregate-only RQ1-A-R1 supplement artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (
        analyse_contract as analyse_v1_contract,
        compute_protected_source_fingerprint,
        safe_output_bundle_fingerprint as v1_safe_output_bundle_fingerprint,
    )
    from evaluation.learned_intent_ranking.lr4b.contract_schema import (
        BASELINE,
        canonical_json_bytes,
        is_final_gold_path,
        sha256_file,
    )
    from evaluation.learned_intent_ranking.lr4b_r1.keyword_baseline_adapter import (
        FIXTURE_SHA256,
        execute_keyword_parity,
        load_approved_fixture,
    )
else:
    from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (
        analyse_contract as analyse_v1_contract,
        compute_protected_source_fingerprint,
        safe_output_bundle_fingerprint as v1_safe_output_bundle_fingerprint,
    )
    from evaluation.learned_intent_ranking.lr4b.contract_schema import (
        BASELINE,
        canonical_json_bytes,
        is_final_gold_path,
        sha256_file,
    )
    from .keyword_baseline_adapter import (
        FIXTURE_SHA256,
        execute_keyword_parity,
        load_approved_fixture,
    )


STAGE = "RQ1-A-R1"
SCHEMA_VERSION = "lr4b-experiment-contract-v1.1"
SUPERSEDED_SCHEMA_VERSION = "lr4b-experiment-contract-v1"
STARTING_BRANCH = "research/rq1-a-lr4b-contract"
STARTING_HEAD = "5b85d3171f57196678db9d0490f4f1be147ba0ea"
STARTING_PARENT = "8d3b6d6850bbf22c676371f613ad62e2389bd1e7"
TARGET_BRANCH = "research/rq1-a-r1-contract-repair"
V1_SAFE_OUTPUT_BUNDLE_SHA256 = "fa629c929cbe2ffe68ea138c1432edb4cdcb8ca715975e1470ae9ff6795465ba"
V1_REVIEW_ZIP_SHA256 = "7634cf2a6c258755b1529df52fceb4735a4832095a710dab25d648a9b74d9a57"
V1_EXPERIMENT_CONTRACT_SHA256 = "d9069a0bed019ddd6aedf954eb8c1b708610e167d70dffc4bc844bc1a4841113"
V1_OUTPUT_CHECKSUM_SHA256 = "ec07fdc28769f958cae304187f07b038a516d8f83773a618e409eb4bb1457619"
V1_GITIGNORE_SHA256 = "5a2c57cee8654ed5b133e6a716d010ba5bc5303db9173c3f3350faf692dd1ef2"
EXPECTED_SCENARIOS = {"V0": 58, "V1": 131, "V2": 154, "V3": 316}
EXPECTED_FIVE_SEEDS = (20260813, 20260814, 20260815, 20260816, 20260817)

R1_ROOT = PurePosixPath("evaluation/learned_intent_ranking/lr4b_r1")
DOC_PATHS = (
    "docs/thesis_mainline/rq1/RQ1A_R1_CONTRACT_INTEGRITY_CORRECTION.md",
    "docs/thesis_mainline/rq1/RQ1A_R1_EFFECTIVE_EXPERIMENT_CONTRACT.md",
)
CODE_FILENAMES = (
    "__init__.py",
    "keyword_baseline_adapter.py",
    "statistical_decision_contract.py",
    "build_rq1a_r1_supplement.py",
    "validate_rq1a_r1_supplement.py",
    "test_rq1a_r1_unittest.py",
)
SAFE_JSON_FILENAMES = (
    "lr4b_experiment_contract_v1_1.json",
    "rq1a_r1_keyword_parity_v1.json",
    "rq1a_r1_scenario_composition_v1.json",
    "rq1a_r1_duplicate_representation_audit_v1.json",
    "rq1a_r1_statistical_decision_contract_v1.json",
    "rq1a_r1_preflight_report_v1.json",
)
OUTPUT_CHECKSUM_PATH = R1_ROOT / "rq1a_r1_output_checksums_v1.sha256"
V1_OUTPUT_CHECKSUM_PATH = Path(
    "evaluation/learned_intent_ranking/lr4b/lr4b_output_checksums_v1.sha256"
)
V1_EXPERIMENT_CONTRACT_PATH = Path(
    "evaluation/learned_intent_ranking/lr4b/lr4b_experiment_contract_v1.json"
)
V1_REVIEW_ZIP_NAME = "RQ1_A_LR4B_CONTRACT_REVIEW_2026-08-25.zip"


class ContractRepairBuildError(RuntimeError):
    """Fail-closed error whose message contains no governed source text."""


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        check=False,
    )


def _project_path(project_root: Path, relative_path: str | PurePosixPath) -> Path:
    candidate = PurePosixPath(str(relative_path))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ContractRepairBuildError("project-relative path contract failed")
    if is_final_gold_path(candidate):
        raise ContractRepairBuildError("protected final-gold boundary rejected a path")
    return project_root.joinpath(*candidate.parts)


def _verify_regular_file(path: Path, role: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractRepairBuildError(f"required regular file missing: {role}")


def _starting_tracked_file_hashes(project_root: Path) -> dict[str, str]:
    """Record SHA-256 for every file tracked by the immutable starting HEAD."""

    listing = _git(project_root, "ls-tree", "-r", "--name-only", "-z", STARTING_HEAD)
    if listing.returncode != 0:
        raise ContractRepairBuildError("starting tracked tree is unavailable")
    relative_paths = sorted(
        value.decode("utf-8")
        for value in listing.stdout.split(b"\0")
        if value
    )
    if not relative_paths:
        raise ContractRepairBuildError("starting tracked tree is empty")
    if any(is_final_gold_path(relative_path) for relative_path in relative_paths):
        raise ContractRepairBuildError("starting tree includes protected final-gold scope")

    comparison = _git(
        project_root,
        "diff",
        "--no-ext-diff",
        "--quiet",
        STARTING_HEAD,
        "--",
        *relative_paths,
    )
    if comparison.returncode != 0:
        raise ContractRepairBuildError("an existing starting tracked file changed")

    hashes: dict[str, str] = {}
    for relative_path in relative_paths:
        path = _project_path(project_root, relative_path)
        _verify_regular_file(path, "starting_tracked_file")
        hashes[relative_path] = sha256_file(path)
    return hashes


def _verify_git_gate(project_root: Path) -> dict[str, object]:
    branch = _git(project_root, "branch", "--show-current")
    remote = _git(project_root, "remote")
    tags = _git(project_root, "tag", "--list")
    parent = _git(project_root, "rev-parse", f"{STARTING_HEAD}^")
    if any(result.returncode != 0 for result in (branch, remote, tags, parent)):
        raise ContractRepairBuildError("Git gate command failed")
    current_branch = branch.stdout.decode("utf-8").strip()
    remote_count = len([line for line in remote.stdout.splitlines() if line])
    tag_count = len([line for line in tags.stdout.splitlines() if line])
    actual_parent = parent.stdout.decode("ascii").strip()
    if current_branch != TARGET_BRANCH or remote_count != 0 or tag_count != 0:
        raise ContractRepairBuildError("Git branch, remote, or tag gate mismatch")
    if actual_parent != STARTING_PARENT:
        raise ContractRepairBuildError("starting parent mismatch")
    return {
        "starting_branch": STARTING_BRANCH,
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "target_branch": TARGET_BRANCH,
        "starting_working_tree_clean": True,
        "remote_count": remote_count,
        "tag_count": tag_count,
    }


def _verify_v1_artifacts(project_root: Path) -> dict[str, object]:
    checksum_path = _project_path(project_root, V1_OUTPUT_CHECKSUM_PATH.as_posix())
    experiment_path = _project_path(project_root, V1_EXPERIMENT_CONTRACT_PATH.as_posix())
    gitignore_path = _project_path(project_root, ".gitignore")
    for role, path in (
        ("v1_checksum", checksum_path),
        ("v1_experiment_contract", experiment_path),
        ("v1_gitignore", gitignore_path),
    ):
        _verify_regular_file(path, role)
    if sha256_file(checksum_path) != V1_OUTPUT_CHECKSUM_SHA256:
        raise ContractRepairBuildError("v1 checksum manifest changed")
    if sha256_file(experiment_path) != V1_EXPERIMENT_CONTRACT_SHA256:
        raise ContractRepairBuildError("v1 experiment contract changed")
    if sha256_file(gitignore_path) != V1_GITIGNORE_SHA256:
        raise ContractRepairBuildError("RQ1-A gitignore changed")

    entries: dict[str, str] = {}
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ContractRepairBuildError(f"v1 checksum syntax failed at line {line_number}")
        expected, relative_path = match.groups()
        if relative_path in entries:
            raise ContractRepairBuildError("duplicate v1 checksum path")
        member = _project_path(project_root, relative_path)
        _verify_regular_file(member, "v1_checksum_member")
        if sha256_file(member) != expected:
            raise ContractRepairBuildError("v1 artifact checksum mismatch")
        entries[relative_path] = expected
    if len(entries) != 14:
        raise ContractRepairBuildError("v1 checksum entry count mismatch")
    return {
        "changed_file_count_at_rq1a": 16,
        "v1_checksum_entry_count": len(entries),
        "v1_checksum_entries_match": True,
        "v1_checksum_manifest_sha256": V1_OUTPUT_CHECKSUM_SHA256,
        "v1_experiment_contract_sha256": V1_EXPERIMENT_CONTRACT_SHA256,
        "v1_gitignore_sha256": V1_GITIGNORE_SHA256,
        "original_rq1a_artifacts_unchanged": True,
    }


def _count_map(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _duplicate_metrics(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    groups = Counter(str(row["representation_sha256"]) for row in rows)
    duplicate_sizes = [size for size in groups.values() if size > 1]
    return {
        "duplicate_group_count": len(duplicate_sizes),
        "records_in_duplicate_groups": sum(duplicate_sizes),
        "duplicate_extra_row_count": sum(size - 1 for size in duplicate_sizes),
    }


def _build_scenario_composition(
    ledger: Iterable[Mapping[str, object]],
    v1_outputs: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    rows = tuple(ledger)
    prior_summary = v1_outputs["lr4b_data_scenario_summary_v1.json"]
    prior_scenarios = {
        str(row["scenario_id"]): row
        for row in prior_summary["scenarios"]  # type: ignore[index]
    }
    scenarios: list[dict[str, object]] = []
    for scenario_id in ("V0", "V1", "V2", "V3"):
        selected = tuple(
            row for row in rows
            if scenario_id in tuple(row["scenario_membership"])  # type: ignore[arg-type]
        )
        if len(selected) != EXPECTED_SCENARIOS[scenario_id]:
            raise ContractRepairBuildError("scenario membership count drift")
        representation_hashes = {
            str(row["representation_sha256"]) for row in selected
        }
        scenario = {
            "scenario_id": scenario_id,
            "record_count": len(selected),
            "label_count": len({str(row["intent_label"]) for row in selected}),
            "per_label_counts": _count_map(row["intent_label"] for row in selected),
            "query_only_count": sum(row["context_mode"] == "QUERY_ONLY_V1" for row in selected),
            "structured_context_count": sum(
                row["context_mode"] == "STRUCTURED_CONTEXT_V1" for row in selected
            ),
            "source_dataset_counts": _count_map(row["source_dataset_id"] for row in selected),
            "annotation_reliability_counts": _count_map(
                row["annotation_reliability"] for row in selected
            ),
            "unique_representation_count": len(representation_hashes),
            "duplicate_extra_row_count": len(selected) - len(representation_hashes),
            "membership_sha256": str(prior_scenarios[scenario_id]["membership_sha256"]),
        }
        if scenario["record_count"] != int(prior_scenarios[scenario_id]["record_count"]):
            raise ContractRepairBuildError("scenario count differs from RQ1-A")
        scenarios.append(scenario)
    return {
        "schema_version": "rq1a-r1-scenario-composition-v1",
        "stage": STAGE,
        "status": "PASS",
        "scenario_method": "CUMULATIVE_GOVERNED_TRAINING_EVIDENCE_EXPANSION",
        "legacy_scenario_ids_retained": True,
        "strict_nesting": True,
        "pure_data_volume_causal_interpretation": False,
        "composition_dimensions_changed": [
            "RECORD_COUNT",
            "LABEL_DISTRIBUTION",
            "CONTEXT_MODE",
            "SOURCE_DATASET",
        ],
        "rq1b_use": "GOVERNED_TRAINING_EXPANSION_SELECTION",
        "sample_size_only_attribution_authorised": False,
        "thesis_terms": [
            "GOVERNED_EVIDENCE_EXPANSION_SCENARIOS",
            "CUMULATIVE_TRAINING_EVIDENCE_SCENARIOS",
        ],
        "scenarios": scenarios,
    }


def _build_duplicate_audit(ledger: Iterable[Mapping[str, object]]) -> dict[str, object]:
    rows = tuple(ledger)
    grouped: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["representation_sha256"])].append(row)
    duplicate_groups = [group for group in grouped.values() if len(group) > 1]
    same_label = sum(len({str(row["intent_label"]) for row in group}) == 1 for group in duplicate_groups)
    cross_label = sum(len({str(row["intent_label"]) for row in group}) > 1 for group in duplicate_groups)
    if cross_label:
        raise ContractRepairBuildError("contradictory duplicate labels")

    group_size_frequency = dict(sorted(Counter(len(group) for group in duplicate_groups).items()))
    per_scenario = {
        scenario_id: _duplicate_metrics(
            row for row in rows
            if scenario_id in tuple(row["scenario_membership"])  # type: ignore[arg-type]
        )
        for scenario_id in ("V0", "V1", "V2", "V3")
    }
    context_modes = sorted({str(row["context_mode"]) for row in rows})
    per_context_mode = {
        mode: _duplicate_metrics(row for row in rows if str(row["context_mode"]) == mode)
        for mode in context_modes
    }
    report = {
        "schema_version": "rq1a-r1-duplicate-representation-audit-v1",
        "stage": STAGE,
        "status": "PASS",
        "total_record_count": len(rows),
        "unique_representation_count": len(grouped),
        "duplicate_group_count": len(duplicate_groups),
        "records_in_duplicate_groups": sum(len(group) for group in duplicate_groups),
        "duplicate_extra_row_count": sum(len(group) - 1 for group in duplicate_groups),
        "same_label_duplicate_group_count": same_label,
        "cross_label_duplicate_group_count": cross_label,
        "maximum_group_size": max((len(group) for group in duplicate_groups), default=1),
        "group_size_frequency": {str(size): count for size, count in group_size_frequency.items()},
        "per_scenario_duplicate_counts": per_scenario,
        "per_context_mode_duplicate_counts": per_context_mode,
        "primary_training_retains_all_governed_source_records": True,
        "duplicate_representation_weighting_limitation": True,
        "deduplicated_training_condition_authorised": False,
        "rq1b_reports_duplicate_and_family_concentration": True,
        "sample_membership_change_authorised": False,
        "record_identifiers_emitted": False,
        "raw_text_emitted": False,
    }
    expected = {
        "total_record_count": 318,
        "unique_representation_count": 297,
        "duplicate_group_count": 10,
        "records_in_duplicate_groups": 31,
        "duplicate_extra_row_count": 21,
        "same_label_duplicate_group_count": 10,
        "cross_label_duplicate_group_count": 0,
        "maximum_group_size": 6,
    }
    if any(report[key] != value for key, value in expected.items()):
        raise ContractRepairBuildError("duplicate representation aggregate drift")
    expected_scenario_extra = {"V0": 0, "V1": 21, "V2": 21, "V3": 21}
    if {
        scenario: int(metrics["duplicate_extra_row_count"])
        for scenario, metrics in per_scenario.items()
    } != expected_scenario_extra:
        raise ContractRepairBuildError("scenario duplicate aggregate drift")
    return report


def _build_statistical_contract() -> dict[str, object]:
    return {
        "schema_version": "rq1a-r1-statistical-decision-contract-v1",
        "stage": STAGE,
        "status": "FROZEN",
        "primary_comparison": {
            "comparison": "REPRESENTATIVE_M64_VS_C0",
            "metric": "MRR",
            "confirmatory_comparison_count": 1,
            "query_delta": "RR_M64_MINUS_RR_C0",
            "primary_effect": "MEAN_DELTA_RR",
            "multiplicity_correction": "NONE_SINGLE_CONFIRMATORY_COMPARISON",
        },
        "paired_approximate_randomisation": {
            "sidedness": "TWO_SIDED",
            "method": "PAIRED_SIGN_FLIP",
            "alpha": 0.05,
            "exact_when_nonzero_pair_count_at_most": 20,
            "monte_carlo_resamples_otherwise": 100000,
            "monte_carlo_random_seed": 20260825,
            "p_value": "EXTREME_PLUS_1_DIVIDED_BY_RESAMPLES_PLUS_1",
        },
        "paired_bootstrap_ci": {
            "method": "PERCENTILE_BOOTSTRAP",
            "resampling_unit": "PAIRED_QUERY",
            "resamples": 50000,
            "confidence": 0.95,
            "lower_percentile": 2.5,
            "upper_percentile": 97.5,
            "percentile_interpolation": "LINEAR_TYPE_7",
            "random_seed": 20260826,
            "cluster_sensitivity_role": "SECONDARY_ONLY_IF_GROUPING_METADATA_PRESENT",
            "cluster_sensitivity_replaces_primary_ci": False,
        },
        "effect_size_reporting": [
            "MEAN_DELTA_RR",
            "MEDIAN_DELTA_RR",
            "WINS",
            "TIES",
            "LOSSES",
            "MATCHED_RANK_BISERIAL_CORRELATION",
        ],
        "matched_rank_biserial": {
            "formula": "WINS_MINUS_LOSSES_DIVIDED_BY_WINS_PLUS_LOSSES",
            "all_ties_value": None,
            "all_ties_status": "UNDEFINED_ALL_TIES",
        },
        "primary_significance_gate": {
            "representative_m64_mrr_gt_c0_mrr": True,
            "mean_delta_rr_gt": 0.0,
            "bootstrap_lower_bound_gt": 0.0,
            "paired_randomisation_p_value_lt": 0.05,
            "all_required": True,
        },
        "secondary_inference": {
            "k0_comparisons": "EXPLORATORY",
            "secondary_metric_tests": "EXPLORATORY",
            "multiple_secondary_tests_correction": "HOLM",
        },
        "top1_and_macro_f1_gate": {
            "representative_m64_top1_gte_c0_top1": True,
            "macro_f1_noninferiority_tolerance": 0.01,
            "representative_m64_macro_f1_gte_c0_minus_tolerance": True,
            "tolerance_change_after_final_gold": False,
        },
        "weak_class_gate": {
            "hard_gate_minimum_support": 5,
            "maximum_per_label_f1_drop": 0.15,
            "positive_c0_f1_m64_zero_forbidden": True,
            "support_below_5_role": "REPORT_ONLY",
        },
        "seed_robustness_gate": {
            "single_final_gold_evaluation_session": True,
            "five_seed_mean_mrr_gt_c0_mrr": True,
            "minimum_seed_count_with_mrr_gt_c0": 4,
            "seed_count": 5,
            "may_reselect_scenario": False,
            "may_reselect_representative_seed": False,
        },
        "final_selection": {
            "required_gates": [
                "PRIMARY_MRR_SIGNIFICANCE",
                "TOP1_DIRECTION",
                "MACRO_F1_TOLERANCE",
                "WEAK_CLASS",
                "SEED_ROBUSTNESS",
                "NO_FINAL_GOLD_TUNING",
                "NO_TAXONOMY_CHANGE",
            ],
            "failure_decision": "C0_REMAINS_SELECTED",
        },
        "final_gold_read_by_module": False,
    }


def _build_experiment_contract(
    parity: Mapping[str, object],
    scenario: Mapping[str, object],
    duplicate: Mapping[str, object],
    statistical: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "status": "EFFECTIVE_CONTRACT_FROZEN",
        "supersedes": SUPERSEDED_SCHEMA_VERSION,
        "superseded_artifact_sha256": V1_EXPERIMENT_CONTRACT_SHA256,
        "corrections": [
            "HARD_CODED_K0_PARITY_CLAIM",
            "PURE_DATA_VOLUME_INTERPRETATION",
            "UNDEFINED_REPRESENTATIVE_SEED_RULE",
            "UNDEFINED_FINAL_STATISTICAL_THRESHOLDS",
        ],
        "effective_contract_for_rq1b": SCHEMA_VERSION,
        "rq1b_must_use_v1_1": True,
        "k0": {
            "adapter": "CURRENT_PRODUCTION_KEYWORD_BASELINE",
            "fixture_sha256": parity["fixture_sha256"],
            "record_count": parity["record_count"],
            "match_count": parity["match_count"],
            "mismatch_count": parity["mismatch_count"],
            "semantic_loader_call_count": parity["semantic_loader_call_count"],
            "ranking_length": 1,
        },
        "training_scenarios": {
            "method": scenario["scenario_method"],
            "legacy_ids": EXPECTED_SCENARIOS,
            "strict_nesting": True,
            "membership_unchanged": True,
            "pure_data_volume_causal_interpretation": False,
            "sample_size_only_attribution_authorised": False,
        },
        "duplicate_representation_policy": {
            "duplicate_extra_row_count": duplicate["duplicate_extra_row_count"],
            "cross_label_duplicate_group_count": duplicate["cross_label_duplicate_group_count"],
            "retain_all_governed_records": True,
            "deduplicated_condition_authorised": False,
            "report_concentration_in_rq1b": True,
        },
        "representative_checkpoint": {
            "applicable_after_m64_scenario_selection": True,
            "five_seeds": list(EXPECTED_FIVE_SEEDS),
            "scenario_selection_basis": "FIVE_SEED_MEAN_VIEW_A_METRICS",
            "selection_rule": [
                "MINIMUM_ABSOLUTE_DISTANCE_TO_FIVE_SEED_MEAN_VIEW_A_MRR",
                "HIGHER_VIEW_A_TOP1",
                "HIGHER_VIEW_A_MACRO_F1",
                "SMALLER_NUMERIC_SEED",
            ],
            "primary_rq1c_comparison_uses_representative_checkpoint": True,
            "remaining_seed_role": "ROBUSTNESS_DIAGNOSTICS_ONLY",
            "best_seed_selection": False,
            "final_gold_driven_selection": False,
            "random_selection": False,
            "unregistered_ensemble": False,
            "replacement_after_rq1c": False,
        },
        "statistical_decision_contract": {
            "schema_version": statistical["schema_version"],
            "primary_comparison": "REPRESENTATIVE_M64_VS_C0_ON_MRR",
            "final_failure_decision": "C0_REMAINS_SELECTED",
        },
        "unchanged_inherited_contracts": [
            "M64_ARCHITECTURE",
            "D0_DIRECTED_EQUAL_WEIGHT",
            "PAIR_CONSTRUCTION",
            "NEGATIVE_SAMPLING",
            "OPTIMIZER_AND_TRAINING_HYPERPARAMETERS",
            "DEV_VIEW_A_SELECTION",
            "CANDIDATE_LABEL_UNIVERSE",
            "INTENT_TAXONOMY",
        ],
        "invariants": {
            "model_training": False,
            "checkpoint_created": False,
            "checkpoint_loaded": False,
            "embedding_executed": False,
            "semantic_runtime_called": False,
            "final_gold_accessed": False,
            "final_gold_searched": False,
            "provider_calls": False,
            "network_access": False,
            "production_code_modified": False,
            "rq1b_started": False,
        },
    }


def _review_zip_gate() -> dict[str, object]:
    path = Path.home() / "Downloads" / V1_REVIEW_ZIP_NAME
    _verify_regular_file(path, "RQ1-A review ZIP")
    actual = sha256_file(path)
    if actual != V1_REVIEW_ZIP_SHA256:
        raise ContractRepairBuildError("RQ1-A review ZIP fingerprint mismatch")
    return {
        "filename": V1_REVIEW_ZIP_NAME,
        "sha256": actual,
        "integrity_test_passed_at_start": True,
    }


def _assert_safe_outputs(
    outputs: Mapping[str, Mapping[str, object]],
    project_root: Path,
) -> None:
    if tuple(sorted(outputs)) != tuple(sorted(SAFE_JSON_FILENAMES)):
        raise ContractRepairBuildError("safe output filename contract drift")
    output_bytes = b"".join(canonical_json_bytes(outputs[name]) for name in sorted(outputs))
    if (b"/" + b"Users" + b"/") in output_bytes or b"C:\\Users\\" in output_bytes:
        raise ContractRepairBuildError("absolute user path leaked into safe output")
    forbidden_keys = {
        "query",
        "utterance_for_review",
        "previous_turns_for_review",
        "question_anchor_for_review",
        "raw_representation",
        "record_id",
        "source_record_id",
    }

    def walk(value: object) -> None:
        if isinstance(value, Mapping):
            if forbidden_keys & {str(key) for key in value}:
                raise ContractRepairBuildError("governed text field leaked into safe output")
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(outputs)
    for fixture_row in load_approved_fixture(project_root):
        query = fixture_row["query"].encode("utf-8")
        if len(query) >= 24 and query in output_bytes:
            raise ContractRepairBuildError("approved fixture text leaked into safe output")


def supplement_bundle_fingerprint(outputs: Mapping[str, Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for name in sorted(outputs):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(canonical_json_bytes(outputs[name]))
    return digest.hexdigest()


def build_supplement(project_root: Path) -> dict[str, dict[str, object]]:
    project_root = Path(os.path.abspath(project_root))
    git_gate = _verify_git_gate(project_root)
    v1_artifacts = _verify_v1_artifacts(project_root)
    tracked_hashes = _starting_tracked_file_hashes(project_root)
    protected = compute_protected_source_fingerprint(project_root)
    if protected["manifest_fingerprint"] != BASELINE["protected_source_manifest_fingerprint"]:
        raise ContractRepairBuildError("protected source fingerprint mismatch")

    v1_outputs, ledger = analyse_v1_contract(project_root)
    v1_bundle = v1_safe_output_bundle_fingerprint(v1_outputs)
    if v1_bundle != V1_SAFE_OUTPUT_BUNDLE_SHA256:
        raise ContractRepairBuildError("RQ1-A safe-output bundle mismatch")

    parity = execute_keyword_parity(project_root)
    scenario = _build_scenario_composition(ledger, v1_outputs)
    duplicate = _build_duplicate_audit(ledger)
    statistical = _build_statistical_contract()
    experiment = _build_experiment_contract(parity, scenario, duplicate, statistical)
    preflight = {
        "schema_version": "rq1a-r1-preflight-report-v1",
        "stage": STAGE,
        "status": "PASS",
        "git": git_gate,
        "rq1a_review_zip": _review_zip_gate(),
        "rq1a_safe_output_bundle_sha256": v1_bundle,
        "rq1a_artifacts": v1_artifacts,
        "source_pre_governance_fingerprint": BASELINE["source_pre_governance_fingerprint"],
        "tracked_baseline_fingerprint": BASELINE["tracked_baseline_tree_fingerprint"],
        "protected_source": protected,
        "starting_tracked_file_count": len(tracked_hashes),
        "starting_tracked_file_sha256": tracked_hashes,
        "approved_fixture_sha256": FIXTURE_SHA256,
        "original_rq1a_artifacts_modified": False,
        "model_training": False,
        "checkpoint_created": False,
        "checkpoint_loaded": False,
        "embedding_executed": False,
        "semantic_runtime_called": False,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "provider_calls": False,
        "network_access": False,
        "production_code_modified": False,
        "rq1b_started": False,
        "raw_text_emitted": False,
    }
    outputs = {
        "lr4b_experiment_contract_v1_1.json": experiment,
        "rq1a_r1_keyword_parity_v1.json": parity,
        "rq1a_r1_scenario_composition_v1.json": scenario,
        "rq1a_r1_duplicate_representation_audit_v1.json": duplicate,
        "rq1a_r1_statistical_decision_contract_v1.json": statistical,
        "rq1a_r1_preflight_report_v1.json": preflight,
    }
    _assert_safe_outputs(outputs, project_root)
    return outputs


def expected_checksum_paths() -> tuple[str, ...]:
    return tuple(sorted({
        *DOC_PATHS,
        *(str(R1_ROOT / name) for name in CODE_FILENAMES),
        *(str(R1_ROOT / name) for name in SAFE_JSON_FILENAMES),
    }))


def write_safe_outputs(project_root: Path, outputs: Mapping[str, Mapping[str, object]]) -> None:
    output_root = _project_path(project_root, R1_ROOT)
    output_root.mkdir(parents=True, exist_ok=True)
    for name in SAFE_JSON_FILENAMES:
        (output_root / name).write_bytes(canonical_json_bytes(outputs[name]))
    checksum_lines: list[str] = []
    for relative_path in expected_checksum_paths():
        path = _project_path(project_root, relative_path)
        _verify_regular_file(path, "RQ1-A-R1 checksum member")
        checksum_lines.append(f"{sha256_file(path)}  {relative_path}")
    checksum_path = _project_path(project_root, OUTPUT_CHECKSUM_PATH)
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-only", action="store_true")
    action.add_argument("--write-safe-outputs", action="store_true")
    args = parser.parse_args(argv)
    project_root = Path(os.path.abspath(args.project_root))
    try:
        outputs = build_supplement(project_root)
        if args.write_safe_outputs:
            write_safe_outputs(project_root, outputs)
        result = {
            "action": "WRITE_SAFE_OUTPUTS" if args.write_safe_outputs else "CHECK_ONLY",
            "status": "PASS",
            "supplement_bundle_sha256": supplement_bundle_fingerprint(outputs),
            "safe_output_count": len(outputs),
            "keyword_parity_records": outputs["rq1a_r1_keyword_parity_v1.json"]["record_count"],
            "keyword_parity_matches": outputs["rq1a_r1_keyword_parity_v1.json"]["match_count"],
            "semantic_loader_call_count": outputs["rq1a_r1_keyword_parity_v1.json"]["semantic_loader_call_count"],
            "model_training": False,
            "checkpoint_created": False,
            "embedding_executed": False,
            "final_gold_accessed": False,
            "final_gold_searched": False,
            "provider_calls": False,
            "network_access": False,
            "raw_text_emitted": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (ContractRepairBuildError, OSError, ValueError, TypeError, json.JSONDecodeError):
        print(json.dumps({
            "status": "FAIL",
            "error": "RQ1_A_R1_SUPPLEMENT_BUILD_FAILED",
            "raw_text_emitted": False,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
