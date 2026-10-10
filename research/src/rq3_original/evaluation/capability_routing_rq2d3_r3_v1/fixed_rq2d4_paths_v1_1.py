"""Non-overridable repository-relative paths for the future D4 execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import ROOT


OUTPUT_RELATIVE = Path("evaluation/capability_routing_rq2d4_v1/local_one_shot")
CONTROL_RELATIVE = Path("evaluation/capability_routing_rq2d4_v1/local_control")
LOCK_RELATIVE = CONTROL_RELATIVE / "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json"
COMBINED_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/local_gold/"
    "track_b_contextual_capability_final_gold_v1.jsonl"
)
LABEL_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/"
    "track_b_contextual_capability_final_gold_labels_v1.jsonl"
)
GROUPING_RELATIVE = Path(
    "evaluation/capability_routing_rq2d3_r2_v1/"
    "track_b_source_blinded_contrast_groups_v1.jsonl"
)


@dataclass(frozen=True)
class D4PathsV1_1:
    output_root: Path
    control_root: Path
    global_lock: Path
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
    receipts_root: Path


def paths_for_roots_v1_1(
    *, output_root: Path, control_root: Path, combined: Path, labels: Path, grouping: Path
) -> D4PathsV1_1:
    return D4PathsV1_1(
        output_root=output_root,
        control_root=control_root,
        global_lock=control_root / "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json",
        combined_source=combined,
        label_gold=labels,
        grouping=grouping,
        feature_view=output_root / "feature_only_view_v1_1.jsonl",
        extractor_report=output_root / "feature_extractor_report_v1_1.json",
        b0_predictions=output_root / "b0_predictions_v1_1.jsonl",
        b1_predictions=output_root / "b1_predictions_v1_1.jsonl",
        p1_predictions=output_root / "p1_predictions_v1_1.jsonl",
        predictor_report=output_root / "predictor_process_report_v1_1.json",
        prediction_firewall_report=output_root / "prediction_firewall_report_v1_1.json",
        p2_scope_metadata=output_root / "p2_secondary_scope_v1_1.json",
        per_case_metric_ledger=output_root / "per_case_metric_ledger_v1_1.jsonl",
        method_metrics=output_root / "method_level_metrics_v1_1.json",
        statistical_state=output_root / "fixed_statistical_state_v1_1.json",
        metric_report=output_root / "metric_process_report_v1_1.json",
        final_result=output_root / "track_b_final_result_v1_1.json",
        result_manifest=output_root / "track_b_final_result_manifest_v1_1.json",
        receipts_root=output_root / "stage_receipts",
    )


def resolve_fixed_rq2d4_paths_v1_1() -> D4PathsV1_1:
    paths = paths_for_roots_v1_1(
        output_root=ROOT / OUTPUT_RELATIVE,
        control_root=ROOT / CONTROL_RELATIVE,
        combined=ROOT / COMBINED_RELATIVE,
        labels=ROOT / LABEL_RELATIVE,
        grouping=ROOT / GROUPING_RELATIVE,
    )
    for value in vars(paths).values():
        value.relative_to(ROOT)
    return paths


def fixed_path_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-d4-fixed-path-contract-v1-1",
        "status": "FROZEN",
        "output_root_relative": str(OUTPUT_RELATIVE),
        "control_root_relative": str(CONTROL_RELATIVE),
        "global_lock_relative": str(LOCK_RELATIVE),
        "combined_source_relative": str(COMBINED_RELATIVE),
        "label_gold_relative": str(LABEL_RELATIVE),
        "grouping_relative": str(GROUPING_RELATIVE),
        "caller_override_allowed": False,
        "environment_override_allowed": False,
        "d3_r3_created_real_directories": False,
    }
