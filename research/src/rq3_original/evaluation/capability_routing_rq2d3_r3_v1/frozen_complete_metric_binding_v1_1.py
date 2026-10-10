"""Complete, non-injectable binding to the frozen RQ2-B metric formulas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import CAPABILITIES, METRIC_IMPLEMENTATION_SHA256, ROOT, sha256_file


METRIC_RELATIVE = "evaluation/capability_routing_rq2b_v1/capability_metrics.py"
REQUIRED_TOP_LEVEL = (
    "macro_f1_all_six",
    "exact_set_accuracy",
    "micro_precision",
    "micro_recall",
    "micro_f1",
    "required_capability_recall",
    "unnecessary_capability_rate",
    "mean_set_jaccard",
    "median_set_jaccard",
    "forbidden_capability_violation_rate",
    "context_resolution_accuracy",
    "context_resolution_positive_recall",
    "clarification_precision",
    "clarification_recall",
    "unnecessary_clarification_rate",
)


@dataclass(frozen=True)
class CompleteMetricBindingV1_1:
    implementation_sha256: str
    formula_contract_identity: str

    def evaluate(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        from evaluation.capability_routing_rq2b_v1.capability_metrics import evaluate_capability_predictions

        result = evaluate_capability_predictions(rows)
        if any(name not in result for name in REQUIRED_TOP_LEVEL):
            raise RuntimeError("BLOCKED_RQ2_D3_R3_COMPLETE_METRIC_CONTRACT")
        per_capability = result.get("per_capability")
        if set(per_capability or {}) != set(CAPABILITIES):
            raise RuntimeError("BLOCKED_RQ2_D3_R3_COMPLETE_METRIC_CONTRACT")
        for value in per_capability.values():
            if any(name not in value for name in ("precision", "recall", "f1", "support")):
                raise RuntimeError("BLOCKED_RQ2_D3_R3_COMPLETE_METRIC_CONTRACT")
        return result


def load_frozen_complete_track_b_metric_binding_v1_1() -> CompleteMetricBindingV1_1:
    path = ROOT / METRIC_RELATIVE
    if not path.is_file() or path.is_symlink() or sha256_file(path) != METRIC_IMPLEMENTATION_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_COMPLETE_METRIC_CONTRACT")
    return CompleteMetricBindingV1_1(
        implementation_sha256=METRIC_IMPLEMENTATION_SHA256,
        formula_contract_identity=METRIC_IMPLEMENTATION_SHA256,
    )


def complete_metric_binding_contract_document_v1_1() -> dict[str, object]:
    binding = load_frozen_complete_track_b_metric_binding_v1_1()
    return {
        "schema_version": "track-b-complete-metric-binding-contract-v1-1",
        "status": "FROZEN",
        "factory": "load_frozen_complete_track_b_metric_binding_v1_1()",
        "factory_parameter_count": 0,
        "fixed_relative_path": METRIC_RELATIVE,
        "implementation_sha256": binding.implementation_sha256,
        "formula_contract_identity": binding.formula_contract_identity,
        "caller_callback_accepted": False,
        "caller_metric_list_accepted": False,
        "method_level_metric_keys": list(REQUIRED_TOP_LEVEL),
        "per_capability_metrics": ["precision", "recall", "f1", "support"],
        "capability_order": list(CAPABILITIES),
    }
