"""Nested leave-one-family-out development selection for Synthetic35."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from . import POLICY_IDS, RQ2BError, safe_distribution
from .capability_metrics import attach_gold_for_metrics, evaluate_capability_predictions
from .p1_policy_family import validate_capability_plan


def _safety_summary(
    predictions: Sequence[Mapping[str, Any]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, int | bool]:
    counts = Counter(
        clarification_exclusivity_violation=0,
        safe_direct_exclusivity_violation=0,
        empty_capability_plan=0,
        forbidden_capability_violation=0,
    )
    for row in predictions:
        case_id = str(row["review_case_id"])
        checks = validate_capability_plan(row["predicted_capabilities"])
        counts.update({name: int(value) for name, value in checks.items()})
        forbidden = set(labels_by_id[case_id].get("forbidden_capabilities") or ())
        counts["forbidden_capability_violation"] += int(
            bool(set(row["predicted_capabilities"]) & forbidden)
        )
    result = {key: int(value) for key, value in sorted(counts.items())}
    result["selection_eligible"] = not any(result.values())
    return result


def _selection_key(policy_id: str, metrics: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -float(metrics["macro_f1_all_six"]),
        -float(metrics["required_capability_recall"]),
        -float(metrics["exact_set_accuracy"]),
        float(metrics["unnecessary_capability_rate"]),
        -float(metrics["mean_set_jaccard"]),
        float(metrics["mean_predicted_capability_count"]),
        str(policy_id),
    )


def select_policy(
    *,
    predictions_by_policy: Mapping[str, Sequence[Mapping[str, Any]]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    eligible_case_ids: set[str],
) -> dict[str, Any]:
    """Select using only the provided (inner or all-development) identities."""

    candidates: list[dict[str, Any]] = []
    for policy_id in POLICY_IDS:
        rows = [
            dict(row)
            for row in predictions_by_policy[policy_id]
            if str(row["review_case_id"]) in eligible_case_ids
        ]
        scoped_labels = {case_id: labels_by_id[case_id] for case_id in eligible_case_ids}
        metrics = evaluate_capability_predictions(
            attach_gold_for_metrics(rows, scoped_labels)
        )
        safety = _safety_summary(rows, scoped_labels)
        candidates.append(
            {
                "policy_id": policy_id,
                "record_count": len(rows),
                "metrics": metrics,
                "safety": safety,
            }
        )
    legal = [row for row in candidates if row["safety"]["selection_eligible"]]
    if not legal:
        raise RQ2BError("BLOCKED_RQ2_B_NO_SAFE_P1_POLICY")
    selected = min(
        legal,
        key=lambda row: _selection_key(row["policy_id"], row["metrics"]),
    )
    return {
        "selected_policy_id": selected["policy_id"],
        "selection_rule": [
            "higher_six_capability_macro_f1",
            "higher_required_capability_recall",
            "higher_exact_set_accuracy",
            "lower_unnecessary_capability_rate",
            "higher_mean_capability_set_jaccard",
            "lower_mean_predicted_capability_count",
            "lexicographically_lower_policy_id",
        ],
        "candidate_results": candidates,
    }


def nested_leave_one_family_out(
    *,
    predictions_by_policy: Mapping[str, Sequence[Mapping[str, Any]]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    family_by_id: Mapping[str, str],
) -> dict[str, Any]:
    if set(family_by_id) != set(labels_by_id):
        raise RQ2BError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
    families = sorted(set(family_by_id.values()))
    if len(families) != 18:
        raise RQ2BError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
    expected_ids = set(labels_by_id)
    for policy_id in POLICY_IDS:
        observed = [str(row["review_case_id"]) for row in predictions_by_policy[policy_id]]
        if len(observed) != len(set(observed)) or set(observed) != expected_ids:
            raise RQ2BError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")

    by_policy_id = {
        policy_id: {
            str(row["review_case_id"]): dict(row)
            for row in predictions_by_policy[policy_id]
        }
        for policy_id in POLICY_IDS
    }
    folds: list[dict[str, Any]] = []
    oof_predictions: list[dict[str, Any]] = []
    for family in families:
        held_out = {case_id for case_id, value in family_by_id.items() if value == family}
        inner = expected_ids - held_out
        if not held_out or not inner:
            raise RQ2BError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
        selection = select_policy(
            predictions_by_policy=predictions_by_policy,
            labels_by_id=labels_by_id,
            eligible_case_ids=inner,
        )
        selected_id = selection["selected_policy_id"]
        for case_id in sorted(held_out):
            row = dict(by_policy_id[selected_id][case_id])
            row["outer_held_out_family"] = family
            row["selected_inner_policy_id"] = selected_id
            oof_predictions.append(row)
        folds.append(
            {
                "outer_held_out_family": family,
                "outer_case_count": len(held_out),
                "inner_case_count": len(inner),
                "outer_case_id_commitment": sorted(held_out),
                "inner_case_id_commitment": sorted(inner),
                "selection": selection,
            }
        )
    oof_ids = [str(row["review_case_id"]) for row in oof_predictions]
    if len(oof_ids) != len(expected_ids) or set(oof_ids) != expected_ids:
        raise RQ2BError("BLOCKED_RQ2_B_FAMILY_LEAKAGE")
    for fold in folds:
        if set(fold["outer_case_id_commitment"]) & set(
            fold["inner_case_id_commitment"]
        ):
            raise RQ2BError("BLOCKED_RQ2_B_FAMILY_LEAKAGE")
    oof_predictions.sort(key=lambda row: str(row["review_case_id"]))
    metrics = evaluate_capability_predictions(
        attach_gold_for_metrics(oof_predictions, labels_by_id)
    )
    final_selection = select_policy(
        predictions_by_policy=predictions_by_policy,
        labels_by_id=labels_by_id,
        eligible_case_ids=expected_ids,
    )
    return {
        "schema_version": "rq2b-nested-family-calibration-v1",
        "record_count": len(oof_predictions),
        "family_count": len(families),
        "family_distribution": safe_distribution(family_by_id.values()),
        "fold_count": len(folds),
        "each_case_outer_held_out_exactly_once": True,
        "outer_family_excluded_from_inner_selection": True,
        "folds": folds,
        "oof_predictions": oof_predictions,
        "oof_metrics": metrics,
        "final_all_synthetic_selection": final_selection,
    }
