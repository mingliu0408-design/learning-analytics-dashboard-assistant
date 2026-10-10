"""Query-free failure summaries for B0, B1 and P1 predictions."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from . import CAPABILITIES


def aggregate_error_analysis(
    *,
    rows_by_model: Mapping[str, Sequence[Mapping[str, Any]]],
    family_by_id: Mapping[str, str] | None = None,
    data_role: str,
) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for model_id, rows in sorted(rows_by_model.items()):
        false_positive = Counter({name: 0 for name in CAPABILITIES})
        false_negative = Counter({name: 0 for name in CAPABILITIES})
        mismatch_by_family: dict[str, int] = defaultdict(int)
        exact_mismatch = 0
        over_prediction = 0
        under_prediction = 0
        for row in rows:
            gold = set(row.get("gold_capabilities") or ())
            predicted = set(row.get("predicted_capabilities") or ())
            case_id = str(row["review_case_id"])
            for capability in predicted - gold:
                false_positive[capability] += 1
            for capability in gold - predicted:
                false_negative[capability] += 1
            if gold != predicted:
                exact_mismatch += 1
                if family_by_id is not None:
                    mismatch_by_family[str(family_by_id[case_id])] += 1
            over_prediction += int(bool(predicted - gold))
            under_prediction += int(bool(gold - predicted))
        models[model_id] = {
            "record_count": len(rows),
            "exact_set_mismatch_count": exact_mismatch,
            "cases_with_any_over_prediction": over_prediction,
            "cases_with_any_under_prediction": under_prediction,
            "false_positive_count_by_capability": dict(false_positive),
            "false_negative_count_by_capability": dict(false_negative),
            "exact_set_mismatch_count_by_family": dict(
                sorted(mismatch_by_family.items())
            ),
        }
    return {
        "schema_version": "rq2b-error-analysis-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "data_role": data_role,
        "models": models,
        "query_text_included": False,
        "history_included": False,
        "rationale_included": False,
        "failure_analysis_is_aggregate_only": True,
    }
