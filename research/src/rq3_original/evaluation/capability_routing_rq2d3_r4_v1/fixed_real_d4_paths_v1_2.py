"""Non-overridable real D4 v1.2 paths resolved from Git's repository root."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import subprocess

from . import RQ2D3R4Error
from .strict_project_relative_path import validate_project_relative_path


OUTPUT_ROOT_RELATIVE = "evaluation/capability_routing_rq2d4_v1/local_one_shot"
CONTROL_ROOT_RELATIVE = "evaluation/capability_routing_rq2d4_v1/local_control"
SENTINEL_RELATIVE = CONTROL_ROOT_RELATIVE + "/TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json"
STATE_RELATIVE = CONTROL_ROOT_RELATIVE + "/TRACK_B_FINAL_EVALUATION_EXECUTION_STATE_V1_2.json"
PARENT_RECEIPT_RELATIVE = CONTROL_ROOT_RELATIVE + "/TRACK_B_FINAL_EVALUATION_PARENT_EXECUTION_V1_2.json"
COMBINED_RELATIVE = "evaluation/capability_routing_rq2d2b_v1/local_gold/track_b_contextual_capability_final_gold_v1.jsonl"
LABEL_RELATIVE = "evaluation/capability_routing_rq2d2b_v1/track_b_contextual_capability_final_gold_labels_v1.jsonl"
GROUPING_RELATIVE = "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl"


@dataclass(frozen=True)
class FixedRealD4PathsV1_2:
    repository_root: Path
    output_root: Path
    control_root: Path
    sentinel: Path
    state: Path
    parent_receipt: Path
    combined_source: Path
    label_gold: Path
    grouping: Path
    feature_view: Path
    extractor_report: Path
    b0_predictions: Path
    b1_predictions: Path
    p1_predictions: Path
    predictor_report: Path
    prediction_firewall_report: Path
    p2_scope_metadata: Path
    per_case_metric_ledger: Path
    method_metrics: Path
    statistical_state: Path
    metric_report: Path
    final_result: Path
    result_manifest: Path
    completion_bundle: Path
    receipts_root: Path


def discover_git_repository_root_v1_2() -> Path:
    code_checkout = Path(__file__).resolve().parents[2]
    process = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=code_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode or not process.stdout.strip():
        raise RQ2D3R4Error("BLOCKED_RQ2_D4_FIXED_REPOSITORY_ROOT")
    root = Path(process.stdout.strip())
    observed = os.lstat(root)
    if not root.is_absolute() or not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
        raise RQ2D3R4Error("BLOCKED_RQ2_D4_FIXED_REPOSITORY_ROOT")
    return root


def _join(root: Path, relative: str) -> Path:
    parsed = validate_project_relative_path(relative)
    return root.joinpath(*parsed.parts)


def _paths_for_root(root: Path) -> FixedRealD4PathsV1_2:
    output = _join(root, OUTPUT_ROOT_RELATIVE)
    control = _join(root, CONTROL_ROOT_RELATIVE)
    return FixedRealD4PathsV1_2(
        repository_root=root,
        output_root=output,
        control_root=control,
        sentinel=_join(root, SENTINEL_RELATIVE),
        state=_join(root, STATE_RELATIVE),
        parent_receipt=_join(root, PARENT_RECEIPT_RELATIVE),
        combined_source=_join(root, COMBINED_RELATIVE),
        label_gold=_join(root, LABEL_RELATIVE),
        grouping=_join(root, GROUPING_RELATIVE),
        feature_view=output / "feature_only_view_v1_2.jsonl",
        extractor_report=output / "feature_extractor_report_v1_2.json",
        b0_predictions=output / "b0_predictions_v1_2.jsonl",
        b1_predictions=output / "b1_predictions_v1_2.jsonl",
        p1_predictions=output / "p1_predictions_v1_2.jsonl",
        predictor_report=output / "predictor_process_report_v1_2.json",
        prediction_firewall_report=output / "prediction_firewall_report_v1_2.json",
        p2_scope_metadata=output / "p2_secondary_scope_v1_2.json",
        per_case_metric_ledger=output / "per_case_metric_ledger_v1_2.jsonl",
        method_metrics=output / "method_level_metrics_v1_2.json",
        statistical_state=output / "fixed_statistical_state_v1_2.json",
        metric_report=output / "metric_process_report_v1_2.json",
        final_result=output / "track_b_final_result_v1_2.json",
        result_manifest=output / "track_b_final_result_manifest_v1_2.json",
        completion_bundle=output / "track_b_completion_bundle_v1_2.json",
        receipts_root=output / "stage_receipts",
    )


def resolve_fixed_real_d4_paths_v1_2() -> FixedRealD4PathsV1_2:
    """Resolve fixed real paths; there is intentionally no caller path argument."""

    return _paths_for_root(discover_git_repository_root_v1_2())


def fixed_real_path_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-fixed-real-path-contract-v1-2",
        "status": "FROZEN",
        "repository_root_source": "git rev-parse --show-toplevel",
        "output_root_relative": OUTPUT_ROOT_RELATIVE,
        "control_root_relative": CONTROL_ROOT_RELATIVE,
        "sentinel_relative": SENTINEL_RELATIVE,
        "state_relative": STATE_RELATIVE,
        "parent_receipt_relative": PARENT_RECEIPT_RELATIVE,
        "combined_source_relative": COMBINED_RELATIVE,
        "label_gold_relative": LABEL_RELATIVE,
        "grouping_relative": GROUPING_RELATIVE,
        "caller_override_allowed": False,
        "cli_override_allowed": False,
        "environment_override_allowed": False,
        "absolute_or_traversal_allowed": False,
        "d3_r4_created_real_directories": False,
    }
