"""Non-injectable real metric factory and separate synthetic factory."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_rq2d3_r1_v1.cluster_bootstrap import MetricCallbackBindingV1

from . import CAPABILITIES, METRIC_IMPLEMENTATION_RELATIVE, METRIC_IMPLEMENTATION_SHA256, ROOT, sha256_file


REAL_METRIC_KEYS = (
    "SIX_CAPABILITY_MACRO_F1",
    "EXACT_SET_ACCURACY",
    "REQUIRED_CAPABILITY_RECALL",
    "UNNECESSARY_CAPABILITY_RATE",
)


def _load_frozen_module() -> Any:
    path = ROOT / METRIC_IMPLEMENTATION_RELATIVE
    if not path.is_file() or path.is_symlink() or sha256_file(path) != METRIC_IMPLEMENTATION_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R2_METRIC_BINDING")
    module = importlib.import_module("evaluation.capability_routing_rq2b_v1.capability_metrics")
    if Path(module.__file__).resolve() != path.resolve() or sha256_file(Path(module.__file__)) != METRIC_IMPLEMENTATION_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R2_METRIC_BINDING")
    return module


def load_frozen_track_b_metric_binding_v1() -> MetricCallbackBindingV1:
    """Load the only real Track-B metric binding; accepts no caller overrides."""

    module = _load_frozen_module()

    def metric(name: str):
        return lambda rows: float(module.evaluate_capability_predictions(rows)[name])

    callbacks = MappingProxyType(
        {
            "SIX_CAPABILITY_MACRO_F1": metric("macro_f1_all_six"),
            "EXACT_SET_ACCURACY": metric("exact_set_accuracy"),
            "REQUIRED_CAPABILITY_RECALL": metric("required_capability_recall"),
            "UNNECESSARY_CAPABILITY_RATE": metric("unnecessary_capability_rate"),
        }
    )
    return MetricCallbackBindingV1(
        binding_id="TRACK_B_FROZEN_RQ2B_CAPABILITY_METRICS_V1",
        implementation_sha256=METRIC_IMPLEMENTATION_SHA256,
        callbacks=callbacks,
        synthetic_test_only=False,
    )


def _row_sets(row: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    return set(row["gold_capabilities"]), set(row["predicted_capabilities"])


def _synthetic_macro(rows: Sequence[Mapping[str, Any]]) -> float:
    values = []
    for capability in CAPABILITIES:
        tp = fp = fn = 0
        for row in rows:
            gold, predicted = _row_sets(row)
            tp += int(capability in gold and capability in predicted)
            fp += int(capability not in gold and capability in predicted)
            fn += int(capability in gold and capability not in predicted)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        values.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(values) / len(values)


def _synthetic_exact(rows: Sequence[Mapping[str, Any]]) -> float:
    return sum(int(_row_sets(row)[0] == _row_sets(row)[1]) for row in rows) / len(rows)


def _synthetic_required(rows: Sequence[Mapping[str, Any]]) -> float:
    found = total = 0
    for row in rows:
        gold, predicted = _row_sets(row)
        found += len(gold & predicted)
        total += len(gold)
    return found / total if total else 0.0


def _synthetic_unnecessary(rows: Sequence[Mapping[str, Any]]) -> float:
    unnecessary = predicted_total = 0
    for row in rows:
        gold, predicted = _row_sets(row)
        unnecessary += len(predicted - gold)
        predicted_total += len(predicted)
    return unnecessary / predicted_total if predicted_total else 0.0


def load_synthetic_metric_binding_v1() -> MetricCallbackBindingV1:
    return MetricCallbackBindingV1(
        binding_id="SYNTHETIC_TEST_ONLY_TRACK_B_METRICS_V1",
        implementation_sha256="SYNTHETIC_TEST_ONLY",
        callbacks=MappingProxyType(
            {
                "SIX_CAPABILITY_MACRO_F1": _synthetic_macro,
                "EXACT_SET_ACCURACY": _synthetic_exact,
                "REQUIRED_CAPABILITY_RECALL": _synthetic_required,
                "UNNECESSARY_CAPABILITY_RATE": _synthetic_unnecessary,
            }
        ),
        synthetic_test_only=True,
    )


def metric_binding_contract_document_v1() -> dict[str, Any]:
    binding = load_frozen_track_b_metric_binding_v1()
    return {
        "schema_version": "track-b-frozen-metric-binding-contract-v1",
        "status": "FROZEN",
        "real_factory": "load_frozen_track_b_metric_binding_v1()",
        "factory_parameter_count": 0,
        "fixed_relative_path": str(METRIC_IMPLEMENTATION_RELATIVE),
        "implementation_sha256": METRIC_IMPLEMENTATION_SHA256,
        "module_file_identity_verified": True,
        "metric_keys": list(binding.callbacks),
        "caller_callback_accepted": False,
        "caller_implementation_sha_accepted": False,
        "caller_metric_list_accepted": False,
        "synthetic_factory_separate": True,
    }
