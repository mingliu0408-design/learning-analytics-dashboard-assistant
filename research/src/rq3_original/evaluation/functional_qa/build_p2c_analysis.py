"""Build read-only P2-C Top-k diagnostics from the frozen semantic runtime."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.production_intent_router import load_production_semantic_router


QA_ROOT = Path(__file__).resolve().parent
RESULTS = QA_ROOT / "results"
ANALYSIS = QA_ROOT / "analysis"
BEFORE_PATH = RESULTS / "functional_qa_after_stabilisation_v2.json"
AFTER_PATH = RESULTS / "functional_qa_after_safe_fallback_v3.json"


def records(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["layers"]["mechanism"]["records"]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No analysis rows for {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ranked_prediction(router: Any, record: Mapping[str, Any]) -> tuple[Any, list[Any], list[Any]]:
    prediction = router.predict(
        str(record.get("effective_query") or record["original_query"]),
        current_page=str((record.get("expected") or {}).get("page") or "Overview"),
        top_k=12,
        candidate_limit=64,
        aggregate_all_examples=True,
    )
    if prediction.result.status != "available":
        raise RuntimeError(f"Semantic runtime unavailable for {record['case_id']}")
    return prediction, list(prediction.result.candidates), list(prediction.example_hits)


def candidate_fields(candidates: list[Any], target: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for index in range(3):
        candidate = candidates[index] if index < len(candidates) else None
        values[f"semantic_top{index + 1}"] = candidate.label if candidate else ""
        values[f"top{index + 1}_score"] = candidate.score if candidate else ""
    target_index = next((i for i, item in enumerate(candidates) if item.label == target), None)
    target_score = candidates[target_index].score if target_index is not None else None
    values["target_rank"] = target_index + 1 if target_index is not None else ""
    values["target_score"] = target_score if target_score is not None else ""
    values["top1_minus_target_score"] = (
        candidates[0].score - target_score if candidates and target_score is not None else ""
    )
    return values


def nearest_fields(hits: list[Any], index_by_id: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for index in range(3):
        hit = hits[index] if index < len(hits) else None
        example = index_by_id.get(hit.example_id) if hit else None
        values[f"nearest_example_{index + 1}"] = example.query if example else ""
        values[f"nearest_example_{index + 1}_intent"] = hit.semantic_label if hit else ""
        values[f"nearest_example_{index + 1}_score"] = hit.score if hit else ""
    return values


def failure_class(candidates: list[Any], target: str) -> str:
    rank = next((i + 1 for i, item in enumerate(candidates) if item.label == target), None)
    if rank == 1:
        return "POLICY_REJECTION_WITH_CORRECT_TOP1"
    if rank in {2, 3}:
        return "POLICY_REJECTION_WITH_PLANNING_IN_TOP3" if target == "planning_or_strategy" else "POLICY_REJECTION_WITH_TARGET_IN_TOP3"
    if rank is None or rank > 3:
        return "REPRESENTATION_ERROR_PLANNING_OUTSIDE_TOP3" if target == "planning_or_strategy" else "REPRESENTATION_ERROR_TARGET_OUTSIDE_TOP3"
    return "REPRESENTATION_ERROR_WRONG_TOP1"


def explanation(candidates: list[Any], target: str, score: float, margin: float) -> str:
    rank = next((i + 1 for i, item in enumerate(candidates) if item.label == target), None)
    if rank == 1:
        failed = []
        if score < 0.513765:
            failed.append("score")
        if margin < 0.190380:
            failed.append("margin")
        return "Correct Top-1 representation, rejected by frozen " + " and ".join(failed) + " policy."
    if rank in {2, 3}:
        return "Target remains in Top-3, but cross-intent similarity/generic wording gives another label Top-1; policy correctly does not accept it."
    return "Target is outside Top-3, indicating weak example coverage or embedding representation for this wording rather than threshold-only rejection."


def product_before(record: Mapping[str, Any]) -> str:
    return f"MISLEADING_ROUTE:{record.get('selected_route') or ''}"


def build_family_rows(
    *,
    router: Any,
    before_rows: list[dict[str, Any]],
    after_by_key: Mapping[tuple[str, int], dict[str, Any]],
    family: str,
    target: str,
) -> list[dict[str, Any]]:
    frozen = router.frozen_index
    assert frozen is not None
    index_by_id = {record.example_id: record for record in frozen.records}
    output = []
    for record in before_rows:
        if record["family"] != family or record.get("passed"):
            continue
        prediction, candidates, hits = ranked_prediction(router, record)
        candidate_data = candidate_fields(candidates, target)
        after = after_by_key[(record["case_id"], record["turn_index"])]
        target_name = "planning" if target == "planning_or_strategy" else "improvement"
        row = {
            "case_id": record["case_id"],
            "query": record["original_query"],
            "keyword_intent": record.get("keyword_intent"),
            "keyword_rule_id": record.get("keyword_rule_id"),
            "semantic_top1": candidate_data["semantic_top1"],
            "top1_score": candidate_data["top1_score"],
            "semantic_top2": candidate_data["semantic_top2"],
            "top2_score": candidate_data["top2_score"],
            "semantic_top3": candidate_data["semantic_top3"],
            "top3_score": candidate_data["top3_score"],
            f"{target_name}_rank": candidate_data["target_rank"],
            f"{target_name}_score": candidate_data["target_score"],
            f"top1_minus_{target_name}_score": candidate_data["top1_minus_target_score"],
            "top1_margin": prediction.result.margin,
            "accepted": record.get("semantic_accepted"),
            "final_selected_intent": after.get("selected_intent"),
            "product_behaviour_before_P2C": product_before(record),
            "product_behaviour_after_P2C": after.get("product_safety_outcome"),
            **nearest_fields(hits, index_by_id),
            "failure_class": failure_class(candidates, target),
            "analysis": explanation(
                candidates,
                target,
                float(prediction.result.winning_score or 0.0),
                float(prediction.result.margin or 0.0),
            ),
        }
        output.append(row)
    return output


def build_metrics_rows(router: Any, before_rows: list[dict[str, Any]], after_by_key: Mapping[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    frozen = router.frozen_index
    assert frozen is not None
    index_by_id = {record.example_id: record for record in frozen.records}
    output = []
    confusion_labels = {
        "quantitative_metric_query", "metric_clarification", "dashboard_interpretation",
        "emotional_or_justification", "technical_data_question",
    }
    for record in before_rows:
        if record["family"] != "quantitative_metric" or record.get("passed"):
            continue
        prediction, candidates, hits = ranked_prediction(router, record)
        data = candidate_fields(candidates, "quantitative_metric_query")
        top3 = [item.label for item in candidates[:3]]
        after = after_by_key[(record["case_id"], record["turn_index"])]
        output.append({
            "case_id": record["case_id"], "query": record["original_query"],
            "keyword_intent": record.get("keyword_intent"), "keyword_rule_id": record.get("keyword_rule_id"),
            "semantic_top1": data["semantic_top1"], "top1_score": data["top1_score"],
            "semantic_top2": data["semantic_top2"], "top2_score": data["top2_score"],
            "semantic_top3": data["semantic_top3"], "top3_score": data["top3_score"],
            "quantitative_metric_rank": data["target_rank"], "quantitative_metric_score": data["target_score"],
            "top1_margin": prediction.result.margin,
            "confusion_labels_in_top3": "|".join(item for item in top3 if item in confusion_labels),
            **nearest_fields(hits, index_by_id),
            "failure_class": failure_class(candidates, "quantitative_metric_query"),
            "safe_fallback_behaviour": after.get("product_safety_outcome"),
            "analysis": explanation(candidates, "quantitative_metric_query", float(prediction.result.winning_score or 0.0), float(prediction.result.margin or 0.0)),
        })
    return output


def build_oos_rows(router: Any, before_rows: list[dict[str, Any]], after_by_key: Mapping[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    frozen = router.frozen_index
    assert frozen is not None
    index_by_id = {record.example_id: record for record in frozen.records}
    output = []
    for record in before_rows:
        if record["family"] != "unsupported_out_of_scope" or record.get("passed"):
            continue
        prediction, candidates, hits = ranked_prediction(router, record)
        data = candidate_fields(candidates, "out_of_scope")
        oos_score = float(data["target_score"] or 0.0)
        best_non_oos = max((item.score for item in candidates if item.label != "out_of_scope"), default=0.0)
        rank = int(data["target_rank"] or 999)
        limitation = "THRESHOLD_POLICY_CONSERVATIVE" if rank == 1 else "OOS_REPRESENTATION_WEAK"
        after = after_by_key[(record["case_id"], record["turn_index"])]
        output.append({
            "case_id": record["case_id"], "query": record["original_query"],
            "keyword_intent": record.get("keyword_intent"), "keyword_rule_id": record.get("keyword_rule_id"),
            "semantic_top1": data["semantic_top1"], "top1_score": data["top1_score"],
            "semantic_top2": data["semantic_top2"], "top2_score": data["top2_score"],
            "semantic_top3": data["semantic_top3"], "top3_score": data["top3_score"],
            "oos_rank": data["target_rank"], "oos_score": data["target_score"],
            "oos_margin_over_best_non_oos": oos_score - best_non_oos,
            "top1_margin": prediction.result.margin,
            **nearest_fields(hits, index_by_id),
            "limitation_type": limitation,
            "safe_fallback_behaviour": after.get("product_safety_outcome"),
            "analysis": (
                "OOS is Top-1 but fails the frozen OOS score/margin policy."
                if rank == 1 else
                "OOS is not Top-1; the frozen representation favours an in-scope label, so this is not threshold-only."
            ),
        })
    return output


def main() -> None:
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    before_rows = records(BEFORE_PATH)
    after_rows = records(AFTER_PATH)
    after_by_key = {(row["case_id"], row["turn_index"]): row for row in after_rows}
    router = load_production_semantic_router()

    planning = build_family_rows(
        router=router, before_rows=before_rows, after_by_key=after_by_key,
        family="planning_or_strategy", target="planning_or_strategy",
    )
    improvement = build_family_rows(
        router=router, before_rows=before_rows, after_by_key=after_by_key,
        family="improvement_recommendation", target="improvement_recommendation",
    )
    metrics = build_metrics_rows(router, before_rows, after_by_key)
    oos = build_oos_rows(router, before_rows, after_by_key)
    write_csv(ANALYSIS / "planning_failure_analysis_v1.csv", planning)
    write_csv(ANALYSIS / "improvement_failure_analysis_v1.csv", improvement)
    write_csv(ANALYSIS / "metrics_failure_analysis_v1.csv", metrics)
    write_csv(ANALYSIS / "oos_failure_analysis_v1.csv", oos)

    result = json.loads(AFTER_PATH.read_text(encoding="utf-8"))
    result["p2c_safe_fallback"] = {
        "strict_functional_correctness": result["layers"]["mechanism"]["summary"],
        "product_safety": result["layers"]["mechanism"]["summary"]["product_safety"],
        "uncertainty_fallback_turns": sum(row.get("uncertainty_fallback_used", False) for row in after_rows),
        "planning_top1": sum(row["planning_rank"] == 1 for row in planning),
        "planning_top3": sum(isinstance(row["planning_rank"], int) and row["planning_rank"] <= 3 for row in planning),
        "planning_outside_top3": sum(not isinstance(row["planning_rank"], int) or row["planning_rank"] > 3 for row in planning),
        "analysis_files": [
            "evaluation/functional_qa/analysis/planning_failure_analysis_v1.csv",
            "evaluation/functional_qa/analysis/improvement_failure_analysis_v1.csv",
            "evaluation/functional_qa/analysis/metrics_failure_analysis_v1.csv",
            "evaluation/functional_qa/analysis/oos_failure_analysis_v1.csv",
        ],
    }
    AFTER_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "planning_rows": len(planning), "improvement_rows": len(improvement),
        "metrics_rows": len(metrics), "oos_rows": len(oos),
        "planning_failure_classes": dict(Counter(row["failure_class"] for row in planning)),
        "metrics_top1": dict(Counter(row["semantic_top1"] for row in metrics)),
        "oos_limitations": dict(Counter(row["limitation_type"] for row in oos)),
    }, indent=2))


if __name__ == "__main__":
    main()
