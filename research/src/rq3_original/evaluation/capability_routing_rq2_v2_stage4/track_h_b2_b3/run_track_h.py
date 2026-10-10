"""Run and freeze the authorized Stage 4H DEV-only B2/B3 experiment."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .track_h import (
    CAPABILITIES,
    DEV_PROTOCOL_ROOT,
    ENCODER_PATH,
    EXPECTED_SOURCE_HASHES,
    FEATURE_PROFILE,
    PACKAGE_ROOT,
    SERIALIZER_VERSION,
    SEMANTIC_FIELDS,
    b2_frozen_payload,
    b3_candidate_grid,
    b3_frozen_payload,
    build_error_registry,
    capability_signature,
    encode_frozen_texts,
    full_dev_b2,
    full_dev_b3,
    learning_curves,
    load_answer_dataset,
    nested_b2,
    nested_b3,
    predict_from_b2_payload,
    predict_from_b3_payload,
    sha256_bytes,
    sha256_file,
    verify_source_hashes,
)


STARTING_HEAD = "1838a5d85db2dcaeba481c7404c36cbfbc94215e"
EXPECTED_BRANCH = "research/rq2-v2-stage4-h-b2-b3"


def _json_ready(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "as_dict"):
        return value.as_dict()
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


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_bytes(_json_bytes(payload))


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (np.floating, float)):
        return format(float(value), ".17g")
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _cell(row.get(field)) for field in fieldnames})


def _prediction_rows(dataset: Any, values: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(dataset.rows):
        item: dict[str, Any] = {
            "annotation_case_id": row["annotation_case_id"],
            "scenario_family_id": row["scenario_family_id"],
            "outer_fold": row["fold_id"],
            "current_page": row["current_page"],
            "gold_capability_signature": capability_signature(dataset.y[index]),
            "predicted_capability_signature": capability_signature(values[index]),
        }
        for column, capability in enumerate(CAPABILITIES):
            token = capability.lower()
            item[f"gold_{token}"] = int(dataset.y[index, column])
            item[f"predicted_{token}"] = int(values[index, column])
        rows.append(item)
    return rows


def _score_rows(
    dataset: Any,
    scores: np.ndarray,
    thresholds: np.ndarray | Sequence[Mapping[str, Any]],
    predictions: np.ndarray,
) -> list[dict[str, Any]]:
    if isinstance(thresholds, np.ndarray):
        threshold_matrix = thresholds
    else:
        threshold_matrix = np.tile(
            [float(item["threshold"]) for item in thresholds], (dataset.size, 1)
        )
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(dataset.rows):
        item: dict[str, Any] = {
            "annotation_case_id": row["annotation_case_id"],
            "scenario_family_id": row["scenario_family_id"],
            "outer_fold": row["fold_id"],
            "current_page": row["current_page"],
        }
        for column, capability in enumerate(CAPABILITIES):
            token = capability.lower()
            item[f"{token}_score"] = float(scores[index, column])
            item[f"{token}_threshold"] = float(threshold_matrix[index, column])
            item[f"{token}_prediction"] = int(predictions[index, column])
        rows.append(item)
    return rows


def _metric_summary(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "macro_f1": metrics["macro_f1"],
        "micro_f1": metrics["micro_f1"],
        "exact_capability_set_match": metrics["exact_capability_set_match"],
        "example_based_f1": metrics["example_based_f1"],
        "jaccard": metrics["jaccard"],
        "hamming_loss": metrics["hamming_loss"],
        "under_routing_rate": metrics["under_routing_rate"],
        "over_routing_rate": metrics["over_routing_rate"],
        "family_both_utterances_correct_rate": metrics[
            "family_both_utterances_correct_rate"
        ],
        "contrast_consistency": metrics["contrast_consistency"]["rate"],
    }


def _threshold_map(items: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {
        capability: float(items[column]["threshold"])
        for column, capability in enumerate(CAPABILITIES)
    }


def _model_roundtrip_checks(
    X: np.ndarray,
    b2_payload: Mapping[str, Any],
    b3_payload: Mapping[str, Any],
) -> dict[str, Any]:
    b2_roundtrip = json.loads(_json_bytes(b2_payload).decode("utf-8"))
    b3_roundtrip = json.loads(_json_bytes(b3_payload).decode("utf-8"))
    b2_scores_before, b2_predictions_before = predict_from_b2_payload(X, b2_payload)
    b2_scores_after, b2_predictions_after = predict_from_b2_payload(X, b2_roundtrip)
    b3_probabilities_before, b3_predictions_before = predict_from_b3_payload(
        X, b3_payload
    )
    b3_probabilities_after, b3_predictions_after = predict_from_b3_payload(
        X, b3_roundtrip
    )
    if not np.array_equal(b2_scores_before, b2_scores_after):
        raise RuntimeError("B2 JSON round-trip changed frozen scores")
    if not np.array_equal(b2_predictions_before, b2_predictions_after):
        raise RuntimeError("B2 JSON round-trip changed frozen predictions")
    if not np.array_equal(b3_probabilities_before, b3_probabilities_after):
        raise RuntimeError("B3 JSON round-trip changed frozen probabilities")
    if not np.array_equal(b3_predictions_before, b3_predictions_after):
        raise RuntimeError("B3 JSON round-trip changed frozen predictions")
    return {
        "b2_roundtrip_exact": True,
        "b2_full_dev_frozen_score_sha256": sha256_bytes(
            np.asarray(b2_scores_before, dtype="<f8").tobytes(order="C")
        ),
        "b2_full_dev_frozen_prediction_sha256": sha256_bytes(
            np.asarray(b2_predictions_before, dtype=np.int8).tobytes(order="C")
        ),
        "b3_roundtrip_exact": True,
        "b3_full_dev_frozen_probability_sha256": sha256_bytes(
            np.asarray(b3_probabilities_before, dtype="<f8").tobytes(order="C")
        ),
        "b3_full_dev_frozen_prediction_sha256": sha256_bytes(
            np.asarray(b3_predictions_before, dtype=np.int8).tobytes(order="C")
        ),
    }


def _results_markdown(
    embedding_identity: Mapping[str, Any],
    b2_nested: Mapping[str, Any],
    b2_full: Mapping[str, Any],
    b3_nested: Mapping[str, Any],
    b3_full: Mapping[str, Any],
    curves: Mapping[str, Any],
) -> str:
    b2n = b2_nested["metrics"]
    b2d = b2_full["diagnostic_metrics"]
    b3n = b3_nested["metrics"]
    b3d = b3_full["selected"]["metrics"]
    selected = b3_full["selected"]["config"]

    def percent(value: float | None) -> str:
        return "NOT_EVALUABLE" if value is None else f"{100.0 * value:.2f}%"

    lines = [
        "# RQ2-V2 Stage 4H B2/B3 DEV Results",
        "",
        "Status: `READY_FOR_STAGE_4H_DEV_REVIEW`",
        "",
        (
            "These are descriptive DEV-only nested estimates and calibration diagnostics. "
            "They are not held-out or final generalization results."
        ),
        "",
        "## Frozen representation",
        "",
        f"- Encoder: `{embedding_identity['model_name']}`",
        f"- Revision: `{embedding_identity['revision']}`",
        f"- Dimension: `{embedding_identity['dimension']}`",
        f"- Serializer: `{embedding_identity['serializer_version']}`",
        f"- Source text SHA-256: `{embedding_identity['source_text_sha256']}`",
        f"- Embedding matrix SHA-256: `{embedding_identity['embedding_matrix_sha256']}`",
        "- Encoding was local-only with network sockets blocked; no model weights are included.",
        "",
        "## Primary nested DEV estimates",
        "",
        "| Model | Macro-F1 | Micro-F1 | Exact set | Jaccard | Under-routing | Over-routing |",
        "|---|---:|---:|---:|---:|---:|---:|",
        (
            f"| B2 prototype | {b2n['macro_f1']:.4f} | {b2n['micro_f1']:.4f} | "
            f"{b2n['exact_capability_set_match']:.4f} | {b2n['jaccard']:.4f} | "
            f"{b2n['under_routing_rate']:.4f} | {b2n['over_routing_rate']:.4f} |"
        ),
        (
            f"| B3 OvR | {b3n['macro_f1']:.4f} | {b3n['micro_f1']:.4f} | "
            f"{b3n['exact_capability_set_match']:.4f} | {b3n['jaccard']:.4f} | "
            f"{b3n['under_routing_rate']:.4f} | {b3n['over_routing_rate']:.4f} |"
        ),
        "",
        "### Per-label nested precision / recall / F1",
        "",
        "| Model | Capability | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|",
    ]
    for model, metrics in (("B2", b2n), ("B3", b3n)):
        for capability in CAPABILITIES:
            item = metrics["per_label"][capability]
            lines.append(
                f"| {model} | {capability} | {item['precision']:.4f} | "
                f"{item['recall']:.4f} | {item['f1']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## Fold-selected B3 configurations",
            "",
            "| Outer fold | C | Class weight | Config ID |",
            "|---|---:|---|---|",
        ]
    )
    for fold in b3_nested["fold_selections"]:
        config = fold["selected_config"]
        weight = "null" if config["class_weight"] is None else config["class_weight"]
        lines.append(
            f"| {fold['outer_fold']} | {config['C']} | {weight} | `{config['config_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Final full-DEV freezes",
            "",
            "B2 thresholds: "
            + ", ".join(
                f"{capability}={b2_full['thresholds'][column]['threshold']:.12g}"
                for column, capability in enumerate(CAPABILITIES)
            )
            + ".",
            "",
            (
                f"B3 configuration: `{selected.config_id}` with C={selected.C} and "
                f"class_weight={'null' if selected.class_weight is None else selected.class_weight}."
            ),
            "",
            "B3 thresholds: "
            + ", ".join(
                f"{capability}={b3_full['selected']['thresholds'][column]['threshold']:.12g}"
                for column, capability in enumerate(CAPABILITIES)
            )
            + ".",
            "",
            "The full-DEV re-thresholded OOF diagnostics are reported separately and are not "
            "substituted for the primary nested estimates.",
            "",
            "| Diagnostic | Macro-F1 | Exact set | Jaccard |",
            "|---|---:|---:|---:|",
            (
                f"| B2 full-DEV calibration diagnostic | {b2d['macro_f1']:.4f} | "
                f"{b2d['exact_capability_set_match']:.4f} | {b2d['jaccard']:.4f} |"
            ),
            (
                f"| B3 selected full-DEV calibration diagnostic | {b3d['macro_f1']:.4f} | "
                f"{b3d['exact_capability_set_match']:.4f} | {b3d['jaccard']:.4f} |"
            ),
            "",
            "## Descriptive grouped learning curves",
            "",
            "| Model | Approx. training-family fraction | Status | Macro-F1 |",
            "|---|---:|---|---:|",
        ]
    )
    for model in ("B2", "B3"):
        for key in ("0.25", "0.50", "0.75", "1.00"):
            item = curves["aggregate"][model][key]
            macro = (
                item["metrics"]["macro_f1"]
                if item["status"] == "EVALUATED"
                else None
            )
            lines.append(
                f"| {model} | {float(key):.0%} | {item['status']} | "
                f"{percent(macro)} |"
            )
    lines.extend(
        [
            "",
            "## Audit boundaries",
            "",
            "- Core training and calibration used only the 64 authorized DEV ANSWER utterances; "
            "the eight CLARIFY utterances were never treated as Capability negatives.",
            "- Writer A/B metrics are `NOT_EVALUABLE`: writer identity is intentionally absent "
            "from the sanitized DEV protocol, and no external join was authorized.",
            "- No held-out escrow/input/Gold material was accessed. No provider was called. "
            "No network or model download was permitted.",
            "- No TEST, P1, RQ3, production, deployment, or additional model work was performed.",
            "",
            "Detailed fold calibrations, page strata, family/contrast metrics, candidate "
            "comparisons, learning-curve fold statuses, and error registries are in the CSV/JSON "
            "artifacts alongside this report.",
            "",
        ]
    )
    return "\n".join(lines)


def _status_markdown(embedding_identity: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# RQ2-V2 Stage 4H Status",
            "",
            "Status: `READY_FOR_STAGE_4H_DEV_REVIEW`",
            "",
            f"Starting HEAD: `{STARTING_HEAD}`",
            f"Authorized branch: `{EXPECTED_BRANCH}`",
            "Scope: `R2V2-B2_PROTOTYPE` and `R2V2-B3_OVR` DEV-only training, "
            "nested calibration, descriptive learning curves, and final DEV freezes.",
            "",
            f"Frozen embedding matrix SHA-256: `{embedding_identity['embedding_matrix_sha256']}`",
            "",
            "Final verification: `PENDING_EXACT_TEST_COUNT_AND_COMMIT`",
            "",
            "No held-out escrow/input/Gold access, provider call, network download, MPNet "
            "fine-tuning, CLARIFY-as-negative training, P1, RQ3, or production work occurred.",
            "",
            "This status records technical DEV-review readiness only. It does not authorize or "
            "claim held-out evaluation, final generalization, deployment, or another track.",
            "",
        ]
    )


def main() -> None:
    source_hashes = verify_source_hashes()
    dataset = load_answer_dataset()
    X, embedding_identity_base = encode_frozen_texts(dataset.serialized_texts)

    b2_nested_result = nested_b2(X, dataset)
    b2_full_result = full_dev_b2(X, dataset)
    b3_nested_result = nested_b3(X, dataset)
    b3_full_result = full_dev_b3(X, dataset)
    final_b3_config = b3_full_result["selected"]["config"]
    curves = learning_curves(X, dataset, final_b3_config)

    embedding_path = PACKAGE_ROOT / "dev_embeddings_v1.npy"
    np.save(embedding_path, np.asarray(X, dtype="<f4"), allow_pickle=False)
    embedding_identity = dict(embedding_identity_base)
    embedding_identity.update(
        {
            "embedding_artifact": "dev_embeddings_v1.npy",
            "embedding_artifact_sha256": sha256_file(embedding_path),
            "deterministic_regeneration": {
                "module": (
                    "evaluation.capability_routing_rq2_v2_stage4."
                    "track_h_b2_b3.run_track_h"
                ),
                "requirements": (
                    "Use the recorded local revision path with HF_HUB_OFFLINE=1, "
                    "TRANSFORMERS_OFFLINE=1, socket blocking, CPU, float32, "
                    "normalize_embeddings=True, batch_size=16, and case-ID bytewise order."
                ),
                "local_encoder_path": str(ENCODER_PATH),
            },
        }
    )

    b2_payload = b2_frozen_payload(
        b2_full_result, embedding_identity, source_hashes
    )
    b3_payload = b3_frozen_payload(
        b3_full_result, embedding_identity, source_hashes
    )
    persistence_checks = _model_roundtrip_checks(X, b2_payload, b3_payload)

    write_json(PACKAGE_ROOT / "dev_embedding_identity_v1.json", embedding_identity)
    write_json(PACKAGE_ROOT / "b2_frozen_model_v1.json", b2_payload)
    write_json(PACKAGE_ROOT / "b3_frozen_model_v1.json", b3_payload)
    write_json(
        PACKAGE_ROOT / "b3_candidate_grid_v1.json",
        {
            "schema_version": "rq2-v2-stage4h-b3-candidate-grid-v1",
            "model_id": "R2V2-B3_OVR",
            "candidate_count": 8,
            "candidates": [candidate.as_dict() for candidate in b3_candidate_grid()],
            "simplicity_order": [
                "smaller C",
                "no class weighting before balanced",
                "UTF-8 bytewise config ID",
            ],
            "grid_expanded_after_scoring": False,
        },
    )

    score_fields = [
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
    ] + [
        f"{capability.lower()}_{suffix}"
        for capability in CAPABILITIES
        for suffix in ("score", "threshold", "prediction")
    ]
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
    write_csv(
        PACKAGE_ROOT / "b2_nested_oof_scores_v1.csv",
        score_fields,
        _score_rows(
            dataset,
            b2_nested_result["scores"],
            b2_nested_result["threshold_by_case"],
            b2_nested_result["predictions"],
        ),
    )
    write_csv(
        PACKAGE_ROOT / "b2_nested_oof_predictions_v1.csv",
        prediction_fields,
        _prediction_rows(dataset, b2_nested_result["predictions"]),
    )
    write_csv(
        PACKAGE_ROOT / "b2_full_dev_oof_scores_v1.csv",
        score_fields,
        _score_rows(
            dataset,
            b2_full_result["oof_scores"],
            b2_full_result["thresholds"],
            b2_full_result["diagnostic_predictions"],
        ),
    )

    probability_fields = [
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
    ] + [
        f"{capability.lower()}_{suffix}"
        for capability in CAPABILITIES
        for suffix in ("probability", "threshold", "prediction")
    ]
    nested_probability_rows = _score_rows(
        dataset,
        b3_nested_result["probabilities"],
        b3_nested_result["threshold_by_case"],
        b3_nested_result["predictions"],
    )
    nested_probability_rows = [
        {
            key.replace("_score", "_probability"): value
            for key, value in row.items()
        }
        for row in nested_probability_rows
    ]
    write_csv(
        PACKAGE_ROOT / "b3_nested_oof_probabilities_v1.csv",
        probability_fields,
        nested_probability_rows,
    )
    write_csv(
        PACKAGE_ROOT / "b3_nested_oof_predictions_v1.csv",
        prediction_fields,
        _prediction_rows(dataset, b3_nested_result["predictions"]),
    )

    outer_selection_fields = [
        "outer_fold",
        "outer_training_cases",
        "outer_validation_cases",
        "selected_config_id",
        "C",
        "class_weight",
        "rag_threshold",
        "memory_threshold",
        "planning_threshold",
        "inner_macro_f1",
        "inner_exact_capability_set_match",
        "inner_jaccard",
        "inner_under_routing_rate",
        "inner_over_routing_rate",
    ]
    outer_selection_rows: list[dict[str, Any]] = []
    for selection in b3_nested_result["fold_selections"]:
        config = selection["selected_config"]
        metrics = selection["inner_oof_metrics"]
        outer_selection_rows.append(
            {
                "outer_fold": selection["outer_fold"],
                "outer_training_cases": selection["outer_training_case_count"],
                "outer_validation_cases": selection["outer_validation_case_count"],
                "selected_config_id": config["config_id"],
                "C": config["C"],
                "class_weight": config["class_weight"],
                "rag_threshold": selection["thresholds"]["RAG"]["threshold"],
                "memory_threshold": selection["thresholds"]["Memory"]["threshold"],
                "planning_threshold": selection["thresholds"]["Planning"]["threshold"],
                "inner_macro_f1": metrics["macro_f1"],
                "inner_exact_capability_set_match": metrics[
                    "exact_capability_set_match"
                ],
                "inner_jaccard": metrics["jaccard"],
                "inner_under_routing_rate": metrics["under_routing_rate"],
                "inner_over_routing_rate": metrics["over_routing_rate"],
            }
        )
    write_csv(
        PACKAGE_ROOT / "b3_outer_fold_selection_v1.csv",
        outer_selection_fields,
        outer_selection_rows,
    )

    candidate_fields = [
        "config_id",
        "C",
        "class_weight",
        "selected_final",
        "macro_f1",
        "micro_f1",
        "exact_capability_set_match",
        "example_based_f1",
        "jaccard",
        "hamming_loss",
        "under_routing_rate",
        "over_routing_rate",
        "family_both_utterances_correct_rate",
        "contrast_consistency",
        "rag_threshold",
        "memory_threshold",
        "planning_threshold",
    ]
    selected_config_id = b3_full_result["selected"]["config"].config_id
    candidate_rows: list[dict[str, Any]] = []
    all_probability_rows: list[dict[str, Any]] = []
    for candidate in b3_full_result["candidate_results"]:
        config = candidate["config"]
        metrics = candidate["metrics"]
        thresholds = [item["threshold"] for item in candidate["thresholds"]]
        candidate_rows.append(
            {
                "config_id": config.config_id,
                "C": config.C,
                "class_weight": config.class_weight,
                "selected_final": config.config_id == selected_config_id,
                **_metric_summary(metrics),
                "rag_threshold": thresholds[0],
                "memory_threshold": thresholds[1],
                "planning_threshold": thresholds[2],
            }
        )
        for index, row in enumerate(dataset.rows):
            item: dict[str, Any] = {
                "config_id": config.config_id,
                "C": config.C,
                "class_weight": config.class_weight,
                "selected_final": config.config_id == selected_config_id,
                "annotation_case_id": row["annotation_case_id"],
                "outer_fold": row["fold_id"],
            }
            for column, capability in enumerate(CAPABILITIES):
                token = capability.lower()
                item[f"{token}_probability"] = candidate["oof_probabilities"][
                    index, column
                ]
                item[f"{token}_threshold"] = thresholds[column]
                item[f"{token}_prediction"] = candidate["predictions"][index, column]
            all_probability_rows.append(item)
    write_csv(
        PACKAGE_ROOT / "b3_full_dev_candidate_results_v1.csv",
        candidate_fields,
        candidate_rows,
    )
    full_probability_fields = [
        "config_id",
        "C",
        "class_weight",
        "selected_final",
        "annotation_case_id",
        "outer_fold",
    ] + [
        f"{capability.lower()}_{suffix}"
        for capability in CAPABILITIES
        for suffix in ("probability", "threshold", "prediction")
    ]
    write_csv(
        PACKAGE_ROOT / "b3_full_dev_oof_probabilities_v1.csv",
        full_probability_fields,
        all_probability_rows,
    )

    error_fields = [
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
        "gold_capability_signature",
        "predicted_capability_signature",
        "false_negative_capabilities",
        "false_positive_capabilities",
    ]
    b2_errors = build_error_registry(dataset, b2_nested_result["predictions"])
    b3_errors = build_error_registry(dataset, b3_nested_result["predictions"])
    write_csv(PACKAGE_ROOT / "b2_error_registry_v1.csv", error_fields, b2_errors)
    write_csv(PACKAGE_ROOT / "b3_error_registry_v1.csv", error_fields, b3_errors)

    learning_fields = [
        "row_type",
        "model",
        "requested_training_family_fraction",
        "outer_fold",
        "status",
        "reason",
        "target_training_families",
        "actual_training_families",
        "actual_training_family_fraction",
        "training_atomic_components",
        "selection_digest",
        "validation_cases",
        "evaluable_outer_folds",
        "macro_f1",
        "micro_f1",
        "exact_capability_set_match",
        "jaccard",
        "example_based_f1",
        "hamming_loss",
        "under_routing_rate",
        "over_routing_rate",
        "family_both_utterances_correct_rate",
        "contrast_consistency",
    ]
    learning_rows: list[dict[str, Any]] = []
    for row in curves["fold_rows"]:
        learning_rows.append({"row_type": "OUTER_FOLD", **row})
    for model in ("B2", "B3"):
        for key in ("0.25", "0.50", "0.75", "1.00"):
            item = curves["aggregate"][model][key]
            aggregate_row: dict[str, Any] = {
                "row_type": "AGGREGATE",
                "model": model,
                "requested_training_family_fraction": item[
                    "requested_training_family_fraction"
                ],
                "outer_fold": "ALL",
                "status": item["status"],
                "reason": item.get("reason", ""),
                "evaluable_outer_folds": item.get("evaluable_outer_folds", 4),
            }
            if item["status"] == "EVALUATED":
                aggregate_row.update(_metric_summary(item["metrics"]))
            learning_rows.append(aggregate_row)
    write_csv(PACKAGE_ROOT / "learning_curves_v1.csv", learning_fields, learning_rows)

    metrics_payload = {
        "schema_version": "rq2-v2-stage4h-track-h-metrics-v1",
        "status": "READY_FOR_STAGE_4H_DEV_REVIEW",
        "interpretation_boundary": (
            "DEV-only nested estimates and full-DEV calibration diagnostics; not final "
            "generalization performance."
        ),
        "population": {
            "answer_utterances": 64,
            "answer_families": 32,
            "clarify_utterances_used_as_capability_negatives": 0,
        },
        "embedding_identity": embedding_identity,
        "b2": {
            "nested_oof_primary_estimate": b2_nested_result["metrics"],
            "nested_fold_calibrations": b2_nested_result["fold_calibrations"],
            "final_thresholds": _threshold_map(b2_full_result["thresholds"]),
            "full_dev_threshold_calibration_diagnostic": b2_full_result[
                "diagnostic_metrics"
            ],
            "nested_error_count": len(b2_errors),
        },
        "b3": {
            "nested_oof_primary_algorithm_estimate": b3_nested_result["metrics"],
            "outer_fold_selections": b3_nested_result["fold_selections"],
            "full_dev_candidate_comparison": [
                {
                    "config": candidate["config"].as_dict(),
                    "thresholds": _threshold_map(candidate["thresholds"]),
                    "metrics": candidate["metrics"],
                }
                for candidate in b3_full_result["candidate_results"]
            ],
            "final_configuration": b3_full_result["selected"]["config"].as_dict(),
            "final_thresholds": _threshold_map(
                b3_full_result["selected"]["thresholds"]
            ),
            "full_dev_threshold_calibration_diagnostic": b3_full_result["selected"][
                "metrics"
            ],
            "nested_error_count": len(b3_errors),
        },
        "learning_curves": curves["aggregate"],
        "persistence_checks": persistence_checks,
        "governance_audit": {
            "authorized_input_root": str(DEV_PROTOCOL_ROOT),
            "authorized_source_sha256": source_hashes,
            "semantic_fields": list(SEMANTIC_FIELDS),
            "feature_profile": FEATURE_PROFILE,
            "serializer_version": SERIALIZER_VERSION,
            "held_out_artifact_access_count": 0,
            "held_out_identifier_count": 0,
            "provider_call_count": 0,
            "network_call_count": 0,
            "model_download_count": 0,
            "mpnet_fine_tune_count": 0,
            "writer_metrics": {
                "status": "NOT_EVALUABLE",
                "reason": (
                    "Writer identity is absent from the sanitized DEV protocol and no "
                    "external writer join was authorized."
                ),
            },
            "prohibited_follow_on_work_performed": [],
        },
    }
    write_json(PACKAGE_ROOT / "track_h_metrics_v1.json", metrics_payload)
    (PACKAGE_ROOT / "TRACK_H_DEV_RESULTS.md").write_text(
        _results_markdown(
            embedding_identity,
            b2_nested_result,
            b2_full_result,
            b3_nested_result,
            b3_full_result,
            curves,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (PACKAGE_ROOT / "STATUS.md").write_text(
        _status_markdown(embedding_identity), encoding="utf-8", newline="\n"
    )

    artifact_names = sorted(
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_file()
        and path.name
        not in {
            "OUTPUT_SHA256_MANIFEST.json",
            "__init__.py",
            "track_h.py",
            "run_track_h.py",
            "test_track_h.py",
            "build_review_zip.py",
        }
    )
    manifest = {
        "schema_version": "rq2-v2-stage4h-output-sha256-manifest-v1",
        "hash_algorithm": "SHA-256",
        "files": [
            {
                "name": name,
                "size_bytes": (PACKAGE_ROOT / name).stat().st_size,
                "sha256": sha256_file(PACKAGE_ROOT / name),
            }
            for name in artifact_names
        ],
        "source_sha256": source_hashes,
        "large_mpnet_weights_included": False,
    }
    write_json(PACKAGE_ROOT / "OUTPUT_SHA256_MANIFEST.json", manifest)

    print(
        json.dumps(
            {
                "status": "READY_FOR_STAGE_4H_DEV_REVIEW",
                "embedding_matrix_sha256": embedding_identity[
                    "embedding_matrix_sha256"
                ],
                "b2_nested_macro_f1": b2_nested_result["metrics"]["macro_f1"],
                "b3_nested_macro_f1": b3_nested_result["metrics"]["macro_f1"],
                "final_b3_config": final_b3_config.as_dict(),
                "artifact_count": len(manifest["files"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
