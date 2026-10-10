"""Generate only the authorized Stage 4H-R1 diagnostic amendment files."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .diagnostic_audit import (
    BASELINE_DEFINITIONS,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EXPECTED_PRIOR_MANIFEST_SHA256,
    PACKAGE_ROOT,
    STARTING_HEAD,
    complete_diagnostic_computation,
    prior_artifact_manifest,
)
from .track_h import CAPABILITIES


STATUS = "READY_FOR_STAGE_4H_DEV_REVIEW_WITH_SANITY_AUDIT"


def _json_ready(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            _json_ready(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_new_bytes(
    path: Path,
    data: bytes,
    prior_relative_paths: set[str],
) -> None:
    relative = path.relative_to(PACKAGE_ROOT.parents[2]).as_posix()
    if relative in prior_relative_paths:
        raise RuntimeError(f"refusing to alter immutable prior artifact: {relative}")
    path.write_bytes(data)


def write_json(
    path: Path,
    payload: Mapping[str, Any],
    prior_relative_paths: set[str],
) -> None:
    _write_new_bytes(path, _json_bytes(payload), prior_relative_paths)


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        return format(float(value), ".17g")
    if isinstance(value, (int, np.integer)):
        return int(value)
    return value


def csv_bytes(
    fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]
) -> bytes:
    import io

    handle = io.StringIO(newline="")
    writer = csv.DictWriter(
        handle,
        fieldnames=list(fieldnames),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _cell(row.get(field)) for field in fieldnames})
    return handle.getvalue().encode("utf-8")


def _signature(values: Sequence[int]) -> str:
    return "".join(str(int(value)) for value in values)


def _baseline_prediction_rows(
    dataset: Any, prediction: np.ndarray
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(dataset.rows):
        row: dict[str, Any] = {
            "annotation_case_id": source["annotation_case_id"],
            "scenario_family_id": source["scenario_family_id"],
            "outer_fold": source["fold_id"],
            "current_page": source["current_page"],
            "gold_capability_signature": _signature(dataset.y[index]),
            "predicted_capability_signature": _signature(prediction[index]),
        }
        for column, capability in enumerate(CAPABILITIES):
            token = capability.lower()
            row[f"gold_{token}"] = int(dataset.y[index, column])
            row[f"predicted_{token}"] = int(prediction[index, column])
        rows.append(row)
    return rows


def _compact_core(metrics: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: float(metrics[key])
        for key in (
            "macro_f1",
            "micro_f1",
            "exact_capability_set_match",
            "example_based_f1",
            "jaccard",
            "hamming_loss",
            "under_routing_rate",
            "over_routing_rate",
            "family_both_utterances_correct_rate",
        )
    }


def _addendum_markdown(diagnostic: Mapping[str, Any]) -> str:
    baseline_metrics = diagnostic["sanity_baselines"]["metrics"]
    always = baseline_metrics["R2V2-D0_ALWAYS_ON"]
    never = baseline_metrics["R2V2-D1_NEVER_ON"]
    prior_metrics = diagnostic["existing_nested_oof_point_metrics"]
    b2 = prior_metrics["R2V2-B2_PROTOTYPE"]
    b3 = prior_metrics["R2V2-B3_OVR"]
    differences = diagnostic["family_cluster_bootstrap"]["difference_intervals"]
    prevalence = diagnostic["prediction_prevalence"]
    separability = diagnostic["raw_score_separability"]

    def interval(name: str) -> str:
        item = differences[name]
        return f"[{item['percentile_2_5']:.4f}, {item['percentile_97_5']:.4f}]"

    lines = [
        "# RQ2-V2 Stage 4H-R1 Diagnostic Addendum",
        "",
        f"Status: `{STATUS}`",
        "",
        "This amendment is a descriptive DEV-only conditional-core audit added before any "
        "held-out access. It does not retrain, recalibrate, repair, or replace B2 or B3, and "
        "it is not final generalization evidence.",
        "",
        "## Why ALWAYS_ON reaches approximately 0.6667 Macro-F1",
        "",
        "Each capability is balanced at 32 Gold YES and 32 Gold NO cases. ALWAYS_ON therefore "
        "has TP=32, FP=32, FN=0 for every capability: precision=0.5, recall=1.0, and "
        "F1=2×0.5×1/(0.5+1)=2/3. Averaging the three identical label F1 values yields "
        "Macro-F1=0.6667.",
        "",
        "Macro-F1 does not reward true negatives directly. On balanced labels, predicting YES "
        "aggressively can preserve perfect or near-perfect recall and receive a high F1 despite "
        "substantial false positives. Exact Capability Set Match, under-routing, and "
        "over-routing are therefore necessary to interpret routing behavior.",
        "",
        "## Sanity-baseline and frozen-router comparison",
        "",
        "| Router | Macro-F1 | Exact set | Jaccard | Under-routing | Over-routing |",
        "|---|---:|---:|---:|---:|---:|",
        f"| ALWAYS_ON | {always['macro_f1']:.4f} | {always['exact_capability_set_match']:.4f} | {always['jaccard']:.4f} | {always['under_routing_rate']:.4f} | {always['over_routing_rate']:.4f} |",
        f"| NEVER_ON | {never['macro_f1']:.4f} | {never['exact_capability_set_match']:.4f} | {never['jaccard']:.4f} | {never['under_routing_rate']:.4f} | {never['over_routing_rate']:.4f} |",
        f"| B2 frozen nested OOF | {b2['macro_f1']:.4f} | {b2['exact_capability_set_match']:.4f} | {b2['jaccard']:.4f} | {b2['under_routing_rate']:.4f} | {b2['over_routing_rate']:.4f} |",
        f"| B3 frozen nested OOF | {b3['macro_f1']:.4f} | {b3['exact_capability_set_match']:.4f} | {b3['jaccard']:.4f} | {b3['under_routing_rate']:.4f} | {b3['over_routing_rate']:.4f} |",
        "",
        f"B2 is {b2['macro_f1'] - always['macro_f1']:+.4f} above ALWAYS_ON in point Macro-F1; "
        f"the paired family-bootstrap interval for that difference is {interval('B2_MACRO_F1_MINUS_ALWAYS_ON_MACRO_F1')}. "
        f"B3 is {b3['macro_f1'] - always['macro_f1']:+.4f} relative to ALWAYS_ON, with interval "
        f"{interval('B3_MACRO_F1_MINUS_ALWAYS_ON_MACRO_F1')}. These intervals are descriptive; "
        "a positive point estimate alone is not treated as statistically established.",
        "",
        "ALWAYS_ON has zero under-routing but over-routes 87.5% of cases. B2 lowers "
        "over-routing to 81.25% but introduces 9.375% under-routing; its Exact Set Match remains "
        "12.5%. B3 also over-routes 81.25%, under-routes 18.75%, and has lower Exact Set Match "
        "at 4.6875%. These set-level and directional metrics materially qualify the Macro-F1 "
        "comparison.",
        "",
        "## Prediction prevalence",
        "",
        "| Router | Capability | Predicted YES | Predicted NO | TP | FP | TN | FN | Positive rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model_id, label in (
        ("R2V2-B2_PROTOTYPE", "B2"),
        ("R2V2-B3_OVR", "B3"),
    ):
        for capability in CAPABILITIES:
            item = prevalence[model_id]["per_capability"][capability]
            lines.append(
                f"| {label} | {capability} | {item['predicted_yes_count']} | "
                f"{item['predicted_no_count']} | {item['true_positives']} | "
                f"{item['false_positives']} | {item['true_negatives']} | "
                f"{item['false_negatives']} | {item['positive_prediction_rate']:.4f} |"
            )
    lines.extend(
        [
            "",
            "| Router | 000 | 001 | 010 | 011 | 100 | 101 | 110 | 111 | Mean capability count |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model_id, label in (
        ("R2V2-B2_PROTOTYPE", "B2"),
        ("R2V2-B3_OVR", "B3"),
    ):
        audit = prevalence[model_id]
        distribution = audit["predicted_capability_signature_distribution"]
        lines.append(
            f"| {label} | "
            + " | ".join(str(distribution[f"{value:03b}"]) for value in range(8))
            + f" | {audit['mean_predicted_capability_count_per_case']:.4f} |"
        )
    lines.extend(
        [
            "",
            "B2 and B3 both have zero true negatives for RAG and Memory. This is flagged "
            "explicitly and no prediction or threshold was changed in response.",
            "",
            "## Existing raw-score separability",
            "",
            "| Router | Capability | ROC-AUC | Average Precision | Mean Gold YES | Mean Gold NO | Score range |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for model_id, label in (
        ("R2V2-B2_PROTOTYPE", "B2"),
        ("R2V2-B3_OVR", "B3"),
    ):
        for capability in CAPABILITIES:
            item = separability[model_id][capability]
            lines.append(
                f"| {label} | {capability} | {item['roc_auc']:.4f} | "
                f"{item['average_precision']:.4f} | {item['mean_score_gold_yes']:.4f} | "
                f"{item['mean_score_gold_no']:.4f} | "
                f"[{item['score_minimum']:.4f}, {item['score_maximum']:.4f}] |"
            )
    lines.extend(
        [
            "",
            "RAG and Memory ROC-AUC are below 0.5 for both B2 and B3. The audit reports the "
            "existing score orientation transparently; it does not flip scores, reverse labels, "
            "choose new thresholds, or create a repaired model.",
            "",
            "## Family-clustered uncertainty",
            "",
            f"The bootstrap uses `scenario_family_id`, seed `{BOOTSTRAP_SEED}`, and "
            f"`{BOOTSTRAP_REPLICATES:,}` paired replicates. Each sampled family contributes both "
            "utterances. The machine-readable files contain all requested model intervals, "
            "difference intervals, and replicate values.",
            "",
            "| Router | Metric | Point | 95% percentile interval |",
            "|---|---|---:|---:|",
        ]
    )
    bootstrap_intervals = diagnostic["family_cluster_bootstrap"]["model_intervals"]
    for model_id, label in (
        ("R2V2-D0_ALWAYS_ON", "ALWAYS_ON"),
        ("R2V2-D1_NEVER_ON", "NEVER_ON"),
        ("R2V2-B2_PROTOTYPE", "B2"),
        ("R2V2-B3_OVR", "B3"),
    ):
        for metric in (
            "macro_f1",
            "exact_capability_set_match",
            "jaccard",
            "under_routing_rate",
            "over_routing_rate",
        ):
            item = bootstrap_intervals[model_id][metric]
            lines.append(
                f"| {label} | {metric} | {item['point_estimate']:.4f} | "
                f"[{item['percentile_2_5']:.4f}, {item['percentile_97_5']:.4f}] |"
            )
    lines.extend(
        [
            "",
            "| Paired Macro-F1 difference | Point | 95% percentile interval |",
            "|---|---:|---:|",
        ]
    )
    for difference_id in (
        "B2_MACRO_F1_MINUS_B3_MACRO_F1",
        "B2_MACRO_F1_MINUS_ALWAYS_ON_MACRO_F1",
        "B3_MACRO_F1_MINUS_ALWAYS_ON_MACRO_F1",
    ):
        item = differences[difference_id]
        lines.append(
            f"| {difference_id} | {item['point_estimate']:.4f} | "
            f"[{item['percentile_2_5']:.4f}, {item['percentile_97_5']:.4f}] |"
        )
    lines.extend(
        [
            "",
            "## Freeze and governance boundary",
            "",
            f"All 25 prior Track H files remain byte-identical to `{STARTING_HEAD}`. Their "
            f"canonical SHA-256 identity is `{EXPECTED_PRIOR_MANIFEST_SHA256}`. The existing B2/B3 "
            "models, configurations, thresholds, predictions, metrics, learning curves, reports, "
            "and code remain unchanged.",
            "",
            "This diagnostic was frozen before held-out access. No provider was called, no model "
            "was trained, no threshold was selected, and no P1 or RQ3 work was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def _status_markdown() -> str:
    return "\n".join(
        [
            "# RQ2-V2 Stage 4H-R1 Status",
            "",
            f"Status: `{STATUS}`",
            "",
            f"Starting HEAD: `{STARTING_HEAD}`",
            "Scope: post-calibration sanity baselines, prediction prevalence, raw-score "
            "separability, and deterministic family-cluster bootstrap only.",
            "",
            f"Prior Track H identity: `{EXPECTED_PRIOR_MANIFEST_SHA256}` across 25 immutable files.",
            "",
            "Final verification: `PENDING_EXACT_R1_TEST_COUNT_AND_COMMIT`",
            "",
            "No B2/B3 retraining, recalibration, threshold selection, prediction change, metric "
            "change, prior-file modification, held-out access, provider call, P1, or RQ3 occurred.",
            "",
            "This status is DEV-only technical review readiness and does not authorize held-out "
            "evaluation or another stage.",
            "",
        ]
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    prior_before = prior_artifact_manifest()
    prior_relative_paths = {item["path"] for item in prior_before["files"]}
    computation = complete_diagnostic_computation()
    frozen = computation["frozen_inputs"]
    bootstrap = computation["bootstrap"]

    baseline_metrics = computation["baseline_metrics"]
    existing_point_metrics = {
        model_id: {
            **{
                metric: bootstrap["model_intervals"][model_id][metric][
                    "point_estimate"
                ]
                for metric in (
                    "macro_f1",
                    "exact_capability_set_match",
                    "jaccard",
                    "under_routing_rate",
                    "over_routing_rate",
                )
            }
        }
        for model_id in ("R2V2-B2_PROTOTYPE", "R2V2-B3_OVR")
    }
    bootstrap_summary = {
        key: value
        for key, value in bootstrap.items()
        if key not in {"samples", "difference_samples"}
    }
    diagnostic = {
        "schema_version": "rq2-v2-stage4h-r1-diagnostic-v1",
        "status": STATUS,
        "starting_head": STARTING_HEAD,
        "scope": "DEV ANSWER conditional-core descriptive diagnostic only",
        "sanity_baselines": {
            "definitions": BASELINE_DEFINITIONS,
            "metrics": baseline_metrics,
        },
        "existing_nested_oof_point_metrics": existing_point_metrics,
        "prediction_prevalence": computation["prevalence"],
        "raw_score_separability": computation["separability"],
        "family_cluster_bootstrap": bootstrap_summary,
        "prior_artifact_identity": {
            "file_count": prior_before["file_count"],
            "canonical_identity_sha256": prior_before[
                "canonical_identity_sha256"
            ],
            "verified_before_generation": True,
            "verification_after_generation": "RECORDED_IN_PRIOR_TRACK_H_SHA256_V1_JSON",
        },
        "governance_audit": {
            "b2_b3_retrained": False,
            "b2_b3_recalibrated": False,
            "alternative_thresholds_selected": False,
            "scores_flipped": False,
            "labels_reversed": False,
            "prior_results_changed": False,
            "held_out_access_count": 0,
            "held_out_identifier_count": 0,
            "provider_call_count": 0,
            "new_learned_model_count": 0,
            "p1_or_rq3_work_performed": False,
        },
        "machine_readable_replicates": "family_cluster_bootstrap_replicates_v1.csv",
    }

    write_json(
        PACKAGE_ROOT / "sanity_baseline_definitions_v1.json",
        {
            "schema_version": "rq2-v2-stage4h-r1-sanity-baselines-v1",
            "freeze_status": "FROZEN_PRE_FUTURE_HELD_OUT_EXECUTION",
            "population": "64 DEV ANSWER conditional-core utterances",
            "future_end_to_end_note": (
                "The separately evaluated shared clarification gate applies before core "
                "routing in any separately authorized future end-to-end execution."
            ),
            "definitions": BASELINE_DEFINITIONS,
        },
        prior_relative_paths,
    )
    prediction_fields = [
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
        "gold_capability_signature",
        "predicted_capability_signature",
    ] + [
        f"{prefix}_{capability.lower()}"
        for capability in CAPABILITIES
        for prefix in ("gold", "predicted")
    ]
    for model_id, filename in (
        ("R2V2-D0_ALWAYS_ON", "d0_always_on_predictions_v1.csv"),
        ("R2V2-D1_NEVER_ON", "d1_never_on_predictions_v1.csv"),
    ):
        _write_new_bytes(
            PACKAGE_ROOT / filename,
            csv_bytes(
                prediction_fields,
                _baseline_prediction_rows(
                    frozen.dataset, computation["baseline_predictions"][model_id]
                ),
            ),
            prior_relative_paths,
        )
    write_json(
        PACKAGE_ROOT / "sanity_baseline_metrics_v1.json",
        {
            "schema_version": "rq2-v2-stage4h-r1-sanity-baseline-metrics-v1",
            "interpretation_boundary": "DEV ANSWER diagnostic baselines; not learned models",
            "metrics": baseline_metrics,
        },
        prior_relative_paths,
    )

    prevalence_fields = [
        "model_id",
        "capability",
        "gold_positive_count",
        "gold_negative_count",
        "predicted_yes_count",
        "predicted_no_count",
        "true_positives",
        "false_positives",
        "true_negatives",
        "false_negatives",
        "positive_prediction_rate",
        "zero_true_negatives",
    ]
    prevalence_rows: list[dict[str, Any]] = []
    signature_rows: list[dict[str, Any]] = []
    for model_id, audit in computation["prevalence"].items():
        for capability in CAPABILITIES:
            prevalence_rows.append(
                {
                    "model_id": model_id,
                    "capability": capability,
                    **audit["per_capability"][capability],
                }
            )
        for signature, count in audit[
            "predicted_capability_signature_distribution"
        ].items():
            signature_rows.append(
                {
                    "model_id": model_id,
                    "predicted_capability_signature": signature,
                    "count": count,
                    "is_000": signature == "000",
                    "is_111": signature == "111",
                    "mean_predicted_capability_count_per_case": audit[
                        "mean_predicted_capability_count_per_case"
                    ],
                }
            )
    _write_new_bytes(
        PACKAGE_ROOT / "prediction_prevalence_audit_v1.csv",
        csv_bytes(prevalence_fields, prevalence_rows),
        prior_relative_paths,
    )
    _write_new_bytes(
        PACKAGE_ROOT / "prediction_signature_distribution_v1.csv",
        csv_bytes(
            [
                "model_id",
                "predicted_capability_signature",
                "count",
                "is_000",
                "is_111",
                "mean_predicted_capability_count_per_case",
            ],
            signature_rows,
        ),
        prior_relative_paths,
    )

    separability_fields = [
        "model_id",
        "capability",
        "roc_auc",
        "average_precision",
        "mean_score_gold_yes",
        "mean_score_gold_no",
        "score_minimum",
        "score_maximum",
        "score_range_width",
        "roc_auc_below_0_5",
        "scores_flipped_or_labels_reversed",
    ]
    separability_rows = [
        {"model_id": model_id, "capability": capability, **values}
        for model_id, per_capability in computation["separability"].items()
        for capability, values in per_capability.items()
    ]
    _write_new_bytes(
        PACKAGE_ROOT / "raw_score_separability_audit_v1.csv",
        csv_bytes(separability_fields, separability_rows),
        prior_relative_paths,
    )

    interval_fields = [
        "model_id",
        "metric",
        "point_estimate",
        "bootstrap_mean",
        "bootstrap_standard_deviation",
        "percentile_2_5",
        "percentile_50",
        "percentile_97_5",
        "replicates_below_zero",
        "replicates_equal_zero",
        "replicates_above_zero",
        "difference_statistically_established",
        "seed",
        "replicates",
        "resampling_unit",
    ]
    interval_rows = [
        {
            "model_id": model_id,
            "metric": metric,
            **summary,
            "seed": bootstrap["seed"],
            "replicates": bootstrap["replicates"],
            "resampling_unit": bootstrap["resampling_unit"],
        }
        for model_id, metrics in bootstrap["model_intervals"].items()
        for metric, summary in metrics.items()
    ]
    _write_new_bytes(
        PACKAGE_ROOT / "family_cluster_bootstrap_intervals_v1.csv",
        csv_bytes(interval_fields, interval_rows),
        prior_relative_paths,
    )
    difference_fields = [
        "difference_id",
        "left_model",
        "right_model",
        "point_estimate",
        "bootstrap_mean",
        "bootstrap_standard_deviation",
        "percentile_2_5",
        "percentile_50",
        "percentile_97_5",
        "replicates_below_zero",
        "replicates_equal_zero",
        "replicates_above_zero",
        "difference_statistically_established",
        "seed",
        "replicates",
    ]
    difference_rows = [
        {
            "difference_id": difference_id,
            **summary,
            "seed": bootstrap["seed"],
            "replicates": bootstrap["replicates"],
        }
        for difference_id, summary in bootstrap["difference_intervals"].items()
    ]
    _write_new_bytes(
        PACKAGE_ROOT / "family_cluster_bootstrap_differences_v1.csv",
        csv_bytes(difference_fields, difference_rows),
        prior_relative_paths,
    )

    metric_tokens = (
        "macro_f1",
        "exact_capability_set_match",
        "jaccard",
        "under_routing_rate",
        "over_routing_rate",
    )
    model_tokens = (
        "R2V2-D0_ALWAYS_ON",
        "R2V2-D1_NEVER_ON",
        "R2V2-B2_PROTOTYPE",
        "R2V2-B3_OVR",
    )
    difference_tokens = tuple(bootstrap["difference_samples"])
    replicate_fields = ["replicate_id"] + [
        f"{model_id}__{metric}"
        for model_id in model_tokens
        for metric in metric_tokens
    ] + list(difference_tokens)
    replicate_rows: list[dict[str, Any]] = []
    for replicate_index in range(bootstrap["replicates"]):
        row: dict[str, Any] = {"replicate_id": replicate_index + 1}
        for model_id in model_tokens:
            for metric in metric_tokens:
                row[f"{model_id}__{metric}"] = bootstrap["samples"][model_id][
                    metric
                ][replicate_index]
        for difference_id in difference_tokens:
            row[difference_id] = bootstrap["difference_samples"][difference_id][
                replicate_index
            ]
        replicate_rows.append(row)
    _write_new_bytes(
        PACKAGE_ROOT / "family_cluster_bootstrap_replicates_v1.csv",
        csv_bytes(replicate_fields, replicate_rows),
        prior_relative_paths,
    )

    write_json(
        PACKAGE_ROOT / "track_h_r1_diagnostic_v1.json",
        diagnostic,
        prior_relative_paths,
    )
    _write_new_bytes(
        PACKAGE_ROOT / "TRACK_H_DIAGNOSTIC_ADDENDUM.md",
        _addendum_markdown(diagnostic).encode("utf-8"),
        prior_relative_paths,
    )
    _write_new_bytes(
        PACKAGE_ROOT / "STATUS_R1.md",
        _status_markdown().encode("utf-8"),
        prior_relative_paths,
    )

    prior_after_outputs = prior_artifact_manifest()
    if prior_after_outputs != prior_before:
        raise RuntimeError("prior-artifact manifest changed during R1 generation")
    prior_record = {
        **prior_before,
        "verification": {
            "before_r1_computation": "PASS",
            "after_r1_output_generation": "PASS",
            "bytes_changed": 0,
            "files_changed": 0,
        },
    }
    write_json(
        PACKAGE_ROOT / "PRIOR_TRACK_H_SHA256_V1.json",
        prior_record,
        prior_relative_paths,
    )

    generated_names = sorted(
        {
            "sanity_baseline_definitions_v1.json",
            "d0_always_on_predictions_v1.csv",
            "d1_never_on_predictions_v1.csv",
            "sanity_baseline_metrics_v1.json",
            "prediction_prevalence_audit_v1.csv",
            "prediction_signature_distribution_v1.csv",
            "raw_score_separability_audit_v1.csv",
            "family_cluster_bootstrap_intervals_v1.csv",
            "family_cluster_bootstrap_differences_v1.csv",
            "family_cluster_bootstrap_replicates_v1.csv",
            "track_h_r1_diagnostic_v1.json",
            "TRACK_H_DIAGNOSTIC_ADDENDUM.md",
            "STATUS_R1.md",
            "PRIOR_TRACK_H_SHA256_V1.json",
        },
        key=lambda value: value.encode("utf-8"),
    )
    output_manifest = {
        "schema_version": "rq2-v2-stage4h-r1-output-sha256-manifest-v1",
        "hash_algorithm": "SHA-256",
        "status": STATUS,
        "prior_track_h_canonical_identity_sha256": EXPECTED_PRIOR_MANIFEST_SHA256,
        "files": [
            {
                "name": name,
                "size_bytes": (PACKAGE_ROOT / name).stat().st_size,
                "sha256": sha256_file(PACKAGE_ROOT / name),
            }
            for name in generated_names
        ],
        "prior_files_modified": 0,
        "learned_models_added": 0,
    }
    write_json(
        PACKAGE_ROOT / "R1_OUTPUT_SHA256_MANIFEST.json",
        output_manifest,
        prior_relative_paths,
    )
    prior_final = prior_artifact_manifest()
    if prior_final != prior_before:
        raise RuntimeError("prior-artifact manifest changed at R1 finalization")

    print(
        json.dumps(
            {
                "status": STATUS,
                "prior_file_count": prior_final["file_count"],
                "prior_identity_sha256": prior_final[
                    "canonical_identity_sha256"
                ],
                "r1_generated_artifact_count": len(output_manifest["files"]),
                "bootstrap_seed": BOOTSTRAP_SEED,
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
                "b2_rag_roc_auc": computation["separability"][
                    "R2V2-B2_PROTOTYPE"
                ]["RAG"]["roc_auc"],
                "b3_rag_roc_auc": computation["separability"]["R2V2-B3_OVR"][
                    "RAG"
                ]["roc_auc"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
