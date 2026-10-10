"""Execute the provider-free RQ2-B development and descriptive evaluation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.capability_routing_v1.legacy_hard_route_adapter import (
    LegacyHardRoutingCapabilityAdapterV1,
    _dashboard_fixture,
    provider_free_environment,
)
import utils.c_full_service as production_service
import utils.production_intent_router as production_router

from . import (
    B0_IDENTITY,
    B1_IDENTITY,
    HERE,
    LOCAL_ARTIFACTS_RELATIVE,
    LOCAL_ARTIFACT_SUBDIRECTORIES,
    P1_IDENTITY,
    POLICY_IDS,
    ROOT,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .b0_original_query_adapter import measure_b0_case
from .b1_reproduction_adapter import (
    _measure as measure_b1_cases,
    _reproduce_with_adapter as reproduce_b1_with_adapter,
)
from .c0_full_score_vector import (
    aggregate_c0_runtime_results,
    verify_frozen_c0_identity,
)
from .capability_metrics import attach_gold_for_metrics, evaluate_capability_predictions
from .context_status import derive_context_status
from .development_uncertainty import development_uncertainty_report
from .error_analysis import aggregate_error_analysis
from .family_grouped_calibration import nested_leave_one_family_out
from .gold_preflight import (
    CapabilityLabels,
    GoldExample,
    RoutingCaseInput,
    assert_router_inputs_leakage_safe,
    load_and_validate_gold,
)
from .p1_capability_router import prediction_projection, route_p1_case
from .p1_policy_family import policy_contract_document


class MemoizedSemanticRuntime:
    """In-process deterministic cache; no query or score is persisted here."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._cache: dict[tuple[Any, ...], Any] = {}

    @property
    def frozen_index(self) -> Any:
        return self._runtime.frozen_index

    def predict(self, query: str, **kwargs: Any) -> Any:
        key = (
            str(query),
            tuple(
                sorted(
                    (name, tuple(value) if isinstance(value, list) else value)
                    for name, value in kwargs.items()
                )
            ),
        )
        if key not in self._cache:
            self._cache[key] = self._runtime.predict(query, **kwargs)
        return self._cache[key]


@dataclass(frozen=True)
class ExperimentResult:
    safe_outputs: Mapping[str, Mapping[str, Any]]
    local_ledger_hashes: Mapping[str, str]
    final_policy_id: str
    synthetic_metrics_rows: Mapping[str, Sequence[Mapping[str, Any]]]
    authentic_metrics_rows: Mapping[str, Sequence[Mapping[str, Any]]]


def _labels(examples: Sequence[GoldExample]) -> dict[str, dict[str, Any]]:
    return {
        example.router_input.case_id: {
            "gold_capabilities": list(example.labels.required_capabilities),
            "forbidden_capabilities": list(example.labels.forbidden_capabilities),
            "context_resolution_required": (
                example.labels.context_resolution_required
            ),
        }
        for example in examples
    }


def _family_map(examples: Sequence[GoldExample]) -> dict[str, str]:
    result = {
        example.router_input.case_id: str(example.split.scenario_family or "")
        for example in examples
    }
    if len(set(result.values())) != 18 or any(not value for value in result.values()):
        raise RuntimeError("BLOCKED_RQ2_B_FAMILY_SPLIT_MISMATCH")
    return result


def _b0_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    projection = dict(row["capability_projection"])
    return {
        "review_case_id": str(row["case_id"]),
        "predicted_capabilities": [
            name for name, active in projection.items() if bool(active)
        ],
        "context_resolution_required_prediction": False,
        "model_identity": B0_IDENTITY,
    }


def _context_prediction(case: RoutingCaseInput) -> bool:
    runtime = production_service.prepare_mode_cm_context(
        student_query=case.current_query,
        conversation_history=list(case.conversation_history),
        existing_session_memory=None,
        current_page=case.current_page,
        transactional_course_corrections=True,
        enable_p2a_extensions=True,
    )
    resolution = runtime.memory_resolution
    effective_query = (
        resolution.resolved_query
        if resolution is not None and resolution.resolved
        else case.current_query
    )
    signals = production_service.detect_c_full_need_signals(
        effective_query,
        current_page=case.current_page,
        active_course_item=dict(runtime.structured_memory.get("active_course_item") or {}),
        enable_p2a_extensions=True,
    )
    deterministic_ambiguity = bool(
        resolution is not None
        and not resolution.resolved
        and production_service._is_underspecified_without_context(case.current_query)
        and not production_service._is_natural_course_coverage_query(case.current_query)
    )
    return derive_context_status(
        runtime,
        deterministic_ambiguity_guard=deterministic_ambiguity,
        discrepancy_correction_need=signals.discrepancy_correction_need,
    ).context_resolution_required_prediction


def _b1_projections(
    rows: Sequence[Mapping[str, Any]], cases: Sequence[RoutingCaseInput]
) -> list[dict[str, Any]]:
    if [str(row["case_id"]) for row in rows] != [case.case_id for case in cases]:
        raise RuntimeError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    return [
        {
            "review_case_id": case.case_id,
            "predicted_capabilities": [
                name
                for name, active in dict(row["capability_projection"]).items()
                if bool(active)
            ],
            "context_resolution_required_prediction": _context_prediction(case),
            "model_identity": B1_IDENTITY,
        }
        for row, case in zip(rows, cases)
    ]


def _metric_rows(
    predictions: Sequence[Mapping[str, Any]], labels: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    return attach_gold_for_metrics(predictions, labels)


def _write_local_jsonl(relative: str, rows: Sequence[Mapping[str, Any]]) -> str:
    path = ROOT / LOCAL_ARTIFACTS_RELATIVE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_jsonl_bytes(dict(row) for row in rows))
    return sha256_file(path)


def _write_local_json(relative: str, value: Any) -> str:
    path = ROOT / LOCAL_ARTIFACTS_RELATIVE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
    return sha256_file(path)


def _measure_b0_set(
    examples: Sequence[GoldExample], *, runtime: Any, dashboard: Any
) -> list[dict[str, Any]]:
    return [
        measure_b0_case(
            case_id=example.router_input.case_id,
            original_query=example.router_input.current_query,
            current_page=example.router_input.current_page,
            semantic_runtime=runtime,
            dashboard_data=dashboard,
        )
        for example in examples
    ]


def _p1_policy_grid(
    examples: Sequence[GoldExample], *, runtime: Any
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    full: dict[str, list[dict[str, Any]]] = {policy: [] for policy in POLICY_IDS}
    projections: dict[str, list[dict[str, Any]]] = {policy: [] for policy in POLICY_IDS}
    for example in examples:
        for policy_id in POLICY_IDS:
            row = route_p1_case(
                example.router_input,
                policy_id=policy_id,
                semantic_runtime=runtime,
            )
            full[policy_id].append(row)
            projections[policy_id].append(prediction_projection(row))
    return full, projections


def _p1_one_policy(
    examples: Sequence[GoldExample], *, runtime: Any, policy_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    full = [
        route_p1_case(
            example.router_input,
            policy_id=policy_id,
            semantic_runtime=runtime,
        )
        for example in examples
    ]
    return full, [prediction_projection(row) for row in full]


def _safe_nested(nested: Mapping[str, Any]) -> dict[str, Any]:
    selections = Counter(
        str(fold["selection"]["selected_policy_id"]) for fold in nested["folds"]
    )
    candidate_metrics = {
        row["policy_id"]: {
            "metrics": row["metrics"],
            "safety": row["safety"],
        }
        for row in nested["final_all_synthetic_selection"]["candidate_results"]
    }
    return {
        "schema_version": "rq2b-nested-oof-results-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "data_role": "SYNTHETIC_COVERAGE_STRESS_GOLD",
        "record_count": nested["record_count"],
        "family_count": nested["family_count"],
        "fold_count": nested["fold_count"],
        "family_distribution": nested["family_distribution"],
        "each_case_outer_held_out_exactly_once": True,
        "outer_family_excluded_from_inner_selection": True,
        "outer_selected_policy_distribution": dict(sorted(selections.items())),
        "nested_oof_metrics": nested["oof_metrics"],
        "final_all_synthetic_candidate_results": candidate_metrics,
        "final_selected_policy_id": nested["final_all_synthetic_selection"][
            "selected_policy_id"
        ],
        "authentic_used_for_selection": False,
        "registry_used_for_selection": False,
        "natural_language_included": False,
    }


def _model_metrics(
    *,
    b0: Sequence[Mapping[str, Any]],
    b1: Sequence[Mapping[str, Any]],
    p1: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "B0": evaluate_capability_predictions(b0),
        "B1": evaluate_capability_predictions(b1),
        "P1": evaluate_capability_predictions(p1),
    }


def _context_missing_summary(
    predictions: Mapping[str, Sequence[Mapping[str, Any]]]
) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for name, rows in predictions.items():
        models[name] = {
            "record_count": len(rows),
            "context_resolution_required_positive_count": sum(
                bool(row.get("context_resolution_required_prediction")) for row in rows
            ),
            "clarification_positive_count": sum(
                "clarification" in set(row.get("predicted_capabilities") or ())
                for row in rows
            ),
            "execution_capability_false_positive_count": sum(
                len(
                    set(row.get("predicted_capabilities") or ())
                    & {
                        "dashboard_evidence",
                        "course_retrieval",
                        "episodic_memory",
                        "planning",
                    }
                )
                for row in rows
            ),
        }
    return {
        "schema_version": "rq2b-context-missing-diagnostic-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "data_role": "CONTEXT_MISSING_QUALITATIVE_DIAGNOSTIC",
        "included_in_authentic_aggregate": False,
        "models": models,
    }


def run_rq2b(root: Path = ROOT) -> ExperimentResult:
    if root.resolve() != ROOT.resolve():
        raise RuntimeError("BLOCKED_RQ2_B_STARTING_STATE_MISMATCH")
    local_root = root / LOCAL_ARTIFACTS_RELATIVE
    for name in LOCAL_ARTIFACT_SUBDIRECTORIES:
        (local_root / name).mkdir(parents=True, exist_ok=True)

    gold = load_and_validate_gold(root)
    all_inputs = [example.router_input for example in (
        *gold.synthetic_gold,
        *gold.authentic_gold,
        *gold.authentic_context_missing_registry,
    )]
    assert_router_inputs_leakage_safe(all_inputs)
    synthetic_labels = _labels(gold.synthetic_gold)
    authentic_labels = _labels(gold.authentic_gold)
    family_by_id = _family_map(gold.synthetic_gold)
    local_hashes: dict[str, str] = {}

    with provider_free_environment():
        raw_runtime = production_router.load_production_semantic_router()
        runtime = MemoizedSemanticRuntime(raw_runtime)
        dashboard = _dashboard_fixture()
        adapter = LegacyHardRoutingCapabilityAdapterV1(
            semantic_runtime=raw_runtime, dashboard_data=dashboard
        )

        # Development phase: B1 reproduction and Synthetic35 only.
        b1_reproduction = reproduce_b1_with_adapter(adapter, root)
        b1_synthetic = measure_b1_cases(
            adapter, [example.router_input for example in gold.synthetic_gold]
        )
        b0_synthetic_full = _measure_b0_set(
            gold.synthetic_gold, runtime=runtime, dashboard=dashboard
        )
        b0_synthetic = [_b0_projection(row) for row in b0_synthetic_full]
        b1_synthetic_projection = _b1_projections(
            b1_synthetic.rows,
            [example.router_input for example in gold.synthetic_gold],
        )
        p1_synthetic_full, p1_synthetic_by_policy = _p1_policy_grid(
            gold.synthetic_gold, runtime=runtime
        )
        # Required deterministic double run. Memoization changes no prediction.
        _, p1_synthetic_second = _p1_policy_grid(gold.synthetic_gold, runtime=runtime)
        if canonical_json_bytes(p1_synthetic_by_policy) != canonical_json_bytes(
            p1_synthetic_second
        ):
            raise RuntimeError("BLOCKED_RQ2_B_POLICY_FAMILY")

        nested = nested_leave_one_family_out(
            predictions_by_policy=p1_synthetic_by_policy,
            labels_by_id=synthetic_labels,
            family_by_id=family_by_id,
        )
        nested_second = nested_leave_one_family_out(
            predictions_by_policy=p1_synthetic_by_policy,
            labels_by_id=synthetic_labels,
            family_by_id=family_by_id,
        )
        if canonical_json_bytes(nested) != canonical_json_bytes(nested_second):
            raise RuntimeError("BLOCKED_RQ2_B_FAMILY_LEAKAGE")
        final_policy_id = str(
            nested["final_all_synthetic_selection"]["selected_policy_id"]
        )
        frozen_selection_payload = {
            "schema_version": "rq2b-final-p1-policy-v1",
            "stage": "RQ2-B",
            "status": "FROZEN",
            "selected_policy_id": final_policy_id,
            "selection_data_role": "SYNTHETIC_COVERAGE_STRESS_GOLD",
            "selection_record_count": 35,
            "selection_family_count": 18,
            "selection_rule": nested["final_all_synthetic_selection"][
                "selection_rule"
            ],
            "frozen_before_authentic_evaluation": True,
            "authentic_used_for_selection": False,
            "registry_used_for_selection": False,
            "threshold_grid_modified": False,
            "immutable_for_future_rq2c_and_track_b": True,
        }
        final_policy_output = {
            **frozen_selection_payload,
            "frozen_selection_payload_sha256": sha256_bytes(
                canonical_json_bytes(frozen_selection_payload)
            ),
            "persisted_policy_bytes_verified_unchanged_after_authentic": True,
        }
        # Persistence is intentionally before the first Authentic22 measurement.
        write_canonical_json(HERE / "rq2b_final_p1_policy_v1.json", final_policy_output)
        pre_authentic_policy_bytes = (
            HERE / "rq2b_final_p1_policy_v1.json"
        ).read_bytes()
        pre_authentic_policy_sha256 = sha256_bytes(pre_authentic_policy_bytes)

        # Descriptive phase starts only after the final policy is durably frozen.
        b0_authentic_full = _measure_b0_set(
            gold.authentic_gold, runtime=runtime, dashboard=dashboard
        )
        b1_authentic = measure_b1_cases(
            adapter, [example.router_input for example in gold.authentic_gold]
        )
        p1_authentic_full, p1_authentic_projection = _p1_one_policy(
            gold.authentic_gold, runtime=runtime, policy_id=final_policy_id
        )

        # Context-missing registry stays separate from the Authentic22 aggregate.
        b0_registry_full = _measure_b0_set(
            gold.authentic_context_missing_registry,
            runtime=runtime,
            dashboard=dashboard,
        )
        b1_registry = measure_b1_cases(
            adapter,
            [
                example.router_input
                for example in gold.authentic_context_missing_registry
            ],
        )
        p1_registry_full, p1_registry_projection = _p1_one_policy(
            gold.authentic_context_missing_registry,
            runtime=runtime,
            policy_id=final_policy_id,
        )
        post_authentic_policy_bytes = (
            HERE / "rq2b_final_p1_policy_v1.json"
        ).read_bytes()
        if post_authentic_policy_bytes != pre_authentic_policy_bytes:
            raise RuntimeError("BLOCKED_RQ2_B_AUTHENTIC_SELECTION_LEAKAGE")
        post_authentic_policy_sha256 = sha256_bytes(post_authentic_policy_bytes)

    b0_authentic = [_b0_projection(row) for row in b0_authentic_full]
    b1_authentic_projection = _b1_projections(
        b1_authentic.rows,
        [example.router_input for example in gold.authentic_gold],
    )
    b0_registry = [_b0_projection(row) for row in b0_registry_full]
    b1_registry_projection = _b1_projections(
        b1_registry.rows,
        [example.router_input for example in gold.authentic_context_missing_registry],
    )

    synthetic_metric_rows = {
        "B0": _metric_rows(b0_synthetic, synthetic_labels),
        "B1": _metric_rows(b1_synthetic_projection, synthetic_labels),
        "P1": _metric_rows(nested["oof_predictions"], synthetic_labels),
    }
    authentic_metric_rows = {
        "B0": _metric_rows(b0_authentic, authentic_labels),
        "B1": _metric_rows(b1_authentic_projection, authentic_labels),
        "P1": _metric_rows(p1_authentic_projection, authentic_labels),
    }
    uncertainty = development_uncertainty_report(
        p1_rows=synthetic_metric_rows["P1"],
        b0_rows=synthetic_metric_rows["B0"],
        b1_rows=synthetic_metric_rows["B1"],
        family_by_id=family_by_id,
    )
    uncertainty_second = development_uncertainty_report(
        p1_rows=synthetic_metric_rows["P1"],
        b0_rows=synthetic_metric_rows["B0"],
        b1_rows=synthetic_metric_rows["B1"],
        family_by_id=family_by_id,
    )
    if canonical_json_bytes(uncertainty) != canonical_json_bytes(uncertainty_second):
        raise RuntimeError("BLOCKED_RQ2_B_METRIC_CONTRACT")

    # Local-only ledgers and hashes.
    local_hashes["b1_reproduction"] = _write_local_jsonl(
        "b1_predictions/b1_original35_reproduction_v1.jsonl",
        b1_reproduction.rows,
    )
    for role, rows in (
        ("synthetic", b0_synthetic_full),
        ("authentic", b0_authentic_full),
        ("registry", b0_registry_full),
    ):
        local_hashes[f"b0_{role}"] = _write_local_jsonl(
            f"b0_predictions/b0_{role}_v1.jsonl", rows
        )
    for role, result in (
        ("synthetic", b1_synthetic),
        ("authentic", b1_authentic),
        ("registry", b1_registry),
    ):
        local_hashes[f"b1_{role}"] = _write_local_jsonl(
            f"b1_predictions/b1_{role}_v1.jsonl", result.rows
        )
    for policy_id, rows in p1_synthetic_full.items():
        local_hashes[f"p1_synthetic_{policy_id}"] = _write_local_jsonl(
            f"p1_predictions/synthetic_{policy_id}.jsonl", rows
        )
    local_hashes["p1_authentic_final"] = _write_local_jsonl(
        "p1_predictions/authentic_final_policy_v1.jsonl", p1_authentic_full
    )
    local_hashes["p1_registry_final"] = _write_local_jsonl(
        "p1_predictions/registry_final_policy_v1.jsonl", p1_registry_full
    )
    all_first_policy = [
        *p1_synthetic_full[POLICY_IDS[0]],
        *p1_authentic_full,
        *p1_registry_full,
    ]
    local_hashes["envelopes"] = _write_local_jsonl(
        "envelopes/context_envelopes_v1.jsonl",
        [row["context_envelope"] for row in all_first_policy],
    )
    local_hashes["c0_score_vectors"] = _write_local_jsonl(
        "c0_score_vectors/c0_full_score_vectors_v1.jsonl",
        [row["c0_score_vector"] for row in all_first_policy],
    )
    local_hashes["policy_selection_trace"] = _write_local_json(
        "policy_selection_traces/nested_lofo_selection_v1.json", nested
    )

    c0_rows = [row["c0_score_vector"] for row in all_first_policy]
    c0_identity = verify_frozen_c0_identity(root)
    c0_runtime = aggregate_c0_runtime_results(c0_rows, identity=c0_identity)
    b0_contract = {
        "schema_version": "rq2b-b0-contract-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "baseline_identity": B0_IDENTITY,
        "original_query_only": True,
        "context_resolution_enabled": False,
        "prepare_mode_cm_context_call_count": 0,
        "conversation_history_read_count": 0,
        "structured_memory_read_count": 0,
        "episodic_memory_positive_count": 0,
        "record_counts": {"synthetic": 35, "authentic": 22, "registry": 3},
        "local_ledger_sha256": {
            role: local_hashes[f"b0_{role}"]
            for role in ("synthetic", "authentic", "registry")
        },
        "provider_calls": 0,
        "network_access": False,
        "training_performed": False,
        "production_behavior_changed": False,
    }
    b1_report = {
        "schema_version": "rq2b-b1-reproduction-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "baseline_identity": B1_IDENTITY,
        "reproduction": b1_reproduction.aggregate,
        "reproduced_ledger_sha256": b1_reproduction.ledger_sha256,
        "reproduced_ledger_byte_identical": True,
        "measurements": {
            "synthetic": b1_synthetic.aggregate,
            "authentic": b1_authentic.aggregate,
            "registry": b1_registry.aggregate,
        },
        "local_ledger_sha256": {
            role: local_hashes[f"b1_{role}"]
            for role in ("synthetic", "authentic", "registry")
        },
        "provider_calls": 0,
        "network_access": False,
        "training_performed": False,
        "production_behavior_changed": False,
    }
    family_manifest = {
        "schema_version": "rq2b-family-split-manifest-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "data_role": "SYNTHETIC_COVERAGE_STRESS_GOLD",
        "record_count": 35,
        "family_count": 18,
        "family_distribution": nested["family_distribution"],
        "split_method": "NESTED_LEAVE_ONE_SCENARIO_FAMILY_OUT",
        "outer_fold_count": 18,
        "each_case_outer_held_out_exactly_once": True,
        "scenario_family_used_as_prediction_feature": False,
        "authentic_used_for_split_or_selection": False,
    }
    synthetic_comparison = {
        "schema_version": "rq2b-synthetic-comparison-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "data_role": "SYNTHETIC_COVERAGE_STRESS_GOLD",
        "development_only": True,
        "family_grouped": True,
        "models": _model_metrics(**{
            "b0": synthetic_metric_rows["B0"],
            "b1": synthetic_metric_rows["B1"],
            "p1": synthetic_metric_rows["P1"],
        }),
    }
    authentic_results = {
        "schema_version": "rq2b-authentic-descriptive-results-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "data_role": "AUTHENTIC_CODEBOOK_CALIBRATION_GOLD",
        "evidence_status": [
            "DESCRIPTIVE_IN_SAMPLE_ONLY",
            "NOT_USED_FOR_POLICY_SELECTION",
            "NOT_INDEPENDENT_PERFORMANCE_EVIDENCE",
            "NOT_INDEPENDENT_OF_C0_RQ1_MATERIAL",
        ],
        "record_count": 22,
        "frozen_p1_policy_id": final_policy_id,
        "models": _model_metrics(**{
            "b0": authentic_metric_rows["B0"],
            "b1": authentic_metric_rows["B1"],
            "p1": authentic_metric_rows["P1"],
        }),
        "policy_changed_after_authentic": False,
        "pre_authentic_policy_file_sha256": pre_authentic_policy_sha256,
        "post_authentic_policy_file_sha256": post_authentic_policy_sha256,
        "policy_bytes_unchanged_after_authentic": True,
    }
    registry_predictions = {
        "B0": b0_registry,
        "B1": b1_registry_projection,
        "P1": p1_registry_projection,
    }
    error_report = {
        "schema_version": "rq2b-error-analysis-bundle-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "synthetic": aggregate_error_analysis(
            rows_by_model=synthetic_metric_rows,
            family_by_id=family_by_id,
            data_role="SYNTHETIC_COVERAGE_STRESS_GOLD",
        ),
        "authentic": aggregate_error_analysis(
            rows_by_model=authentic_metric_rows,
            data_role="AUTHENTIC_CODEBOOK_CALIBRATION_GOLD_DESCRIPTIVE_ONLY",
        ),
    }
    local_hashes["error_metrics_rows"] = _write_local_json(
        "error_ledgers/metric_join_rows_v1.json",
        {
            "synthetic": synthetic_metric_rows,
            "authentic": authentic_metric_rows,
        },
    )

    safe_outputs: dict[str, Mapping[str, Any]] = {
        "rq2b_gold_preflight_v1.json": {
            "schema_version": "rq2b-gold-preflight-v1",
            "stage": "RQ2-B",
            **dict(gold.identity),
            "gold_modified": False,
            "human_annotation_modified": False,
            "tracked_natural_language_included": False,
        },
        "rq2b_runtime_preflight_v1.json": c0_runtime,
        "rq2b_b0_contract_v1.json": b0_contract,
        "rq2b_b1_reproduction_v1.json": b1_report,
        "rq2b_p1_policy_family_v1.json": {
            **policy_contract_document(),
            "router_identity": P1_IDENTITY,
            "intent_capability_seed_map_modified": False,
            "existing_need_signals_called": True,
            "legacy_memory_dependency_helper_called": True,
        },
        "rq2b_family_split_manifest_v1.json": family_manifest,
        "rq2b_nested_oof_results_v1.json": _safe_nested(nested),
        "rq2b_final_p1_policy_v1.json": final_policy_output,
        "rq2b_synthetic_comparison_v1.json": synthetic_comparison,
        "rq2b_development_uncertainty_v1.json": uncertainty,
        "rq2b_authentic_descriptive_results_v1.json": authentic_results,
        "rq2b_context_missing_diagnostic_v1.json": _context_missing_summary(
            registry_predictions
        ),
        "rq2b_error_analysis_v1.json": error_report,
    }
    for filename, value in safe_outputs.items():
        if filename == "rq2b_final_p1_policy_v1.json":
            if (HERE / filename).read_bytes() != canonical_json_bytes(value):
                raise RuntimeError("BLOCKED_RQ2_B_AUTHENTIC_SELECTION_LEAKAGE")
        else:
            write_canonical_json(HERE / filename, value)
    return ExperimentResult(
        safe_outputs=safe_outputs,
        local_ledger_hashes=dict(sorted(local_hashes.items())),
        final_policy_id=final_policy_id,
        synthetic_metrics_rows=synthetic_metric_rows,
        authentic_metrics_rows=authentic_metric_rows,
    )


def main() -> int:
    result = run_rq2b()
    print(
        json.dumps(
            {
                "status": "PASS",
                "final_policy_id": result.final_policy_id,
                "safe_output_count": len(result.safe_outputs),
                "local_ledger_count": len(result.local_ledger_hashes),
                "provider_calls": 0,
                "network_access": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
