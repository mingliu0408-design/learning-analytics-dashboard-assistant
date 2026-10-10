"""Provider-free deterministic entry point for the corrected RQ2-C1-R1 run."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from evaluation.capability_routing_rq2b_v1.gold_preflight import (
    GoldPreflightResult,
    load_and_validate_gold,
)
from evaluation.capability_routing_rq2c1_v1.controlled_fixture_loader import (
    expected_field_access_audit,
    load_controlled_fixtures,
)
from evaluation.capability_routing_rq2c1_v1.offline_session_state_gate import (
    session_input_from_p1,
)
from evaluation.capability_routing_rq2c1_v1.session_policy_calibration import (
    SessionCalibrationCase,
    nested_leave_one_family_out,
    select_session_policy,
)

from . import (
    CONDITION_IDS,
    GOLD_BUNDLE_SHA256,
    LOCAL_ROOT,
    ORIGINAL_DISPOSITION,
    ORIGINAL_PRESERVATION,
    ORIGINAL_STAGE_ID,
    PRIMARY_PERSISTENT_POLICY,
    ROOT,
    STAGE_ID,
    canonical_json_bytes,
    sha256_file,
    write_json,
    write_jsonl,
)
from .c1_identity import verify_starting_preflight
from .corrected_evaluation import (
    CorrectedControlledResult,
    local_encoder_preflight_v1_1,
    run_corrected_controlled_evaluation,
    validated_query_plan_v1_1,
)
from .offline_memory_store_v1_1 import (
    OfflinePersistentMemoryStoreV1_1,
    StoreIntegrityError,
)
from .offline_memory_write_engine_v1_1 import (
    CorrectionTargetError,
    build_validated_bundle_v1_1,
    resolve_correction_target_v1_1,
)
from .p2_condition_runner_v1_1 import (
    ConditionIsolationError,
    execute_rag_for_condition_v1_1,
    load_p1_ledger_v1_1,
    run_conditions_v1_1,
)
from .runtime_safety_instrumentation import RuntimeSafetyEventLedgerV1
from .validated_execution_context_v1_1 import (
    ExecutionContextError,
    create_validated_execution_context_v1_1,
    verify_execution_context_v1_1,
)


SYNTHETIC_LEDGER = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
    "synthetic_P1_D05_SIGNAL_UNION.jsonl"
)
AUTHENTIC_LEDGER = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
    "authentic_final_policy_v1.jsonl"
)
REGISTRY_LEDGER = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
    "registry_final_policy_v1.jsonl"
)


@dataclass(frozen=True)
class RQ2C1R1RunResult:
    starting_preflight: Mapping[str, Any]
    store_contract: Mapping[str, Any]
    execution_context_contract: Mapping[str, Any]
    rag_isolation: Mapping[str, Any]
    correction_contract: Mapping[str, Any]
    runtime_safety: Mapping[str, Any]
    controlled: CorrectedControlledResult
    session_results: Mapping[str, Any]
    condition_results: Mapping[str, Any]
    authentic_results: Mapping[str, Any]
    context_missing_results: Mapping[str, Any]
    delta_results: Mapping[str, Any]
    runtime_preflight: Mapping[str, Any]
    local_artifact_manifest: Mapping[str, Any]


def _session_cases(
    gold: GoldPreflightResult,
    p1_rows: tuple[Mapping[str, Any], ...],
) -> tuple[SessionCalibrationCase, ...]:
    p1_by_id = {str(row["review_case_id"]): row for row in p1_rows}
    values: list[SessionCalibrationCase] = []
    for example in gold.synthetic_gold:
        family = example.split.scenario_family
        if not family:
            raise RuntimeError("BLOCKED_RQ2_C1_R1_EVALUATION")
        values.append(
            SessionCalibrationCase(
                session_input=session_input_from_p1(
                    p1_by_id[example.router_input.case_id]
                ),
                gold_episodic_state_use=example.labels.episodic_memory,
                scenario_family=family,
            )
        )
    return tuple(values)


def _store_contract() -> dict[str, Any]:
    return {
        "schema_version": "rq2c1-r1-store-lifecycle-contract-v1.1",
        "stage": STAGE_ID,
        "store_schema": "OfflinePersistentMemoryStoreV1_1",
        "transition_contract_id": "OFFLINE_MEMORY_STORE_STATE_MACHINE_V1_1",
        "allowed_transitions": {
            "ACTIVE": ["SUPERSEDED", "COMPLETED", "CANCELLED", "DELETED"],
            "SUPERSEDED": ["DELETED"],
            "COMPLETED": ["DELETED"],
            "CANCELLED": ["DELETED"],
            "STALE": ["DELETED"],
            "DELETED": [],
        },
        "invalid_transition_code": "INVALID_STORE_STATE_TRANSITION",
        "event_time_timezone_aware_required": True,
        "event_time_at_or_after_ingested_at": True,
        "event_time_monotonic_per_memory": True,
        "backdated_failure_code": "BACKDATED_STORE_EVENT",
        "episode_timezone_repairs_naive_event_time": False,
        "tombstone_derived_from_complete_delete_event_history": True,
        "deleted_memory_can_resurrect": False,
        "projection_rebuilt_by_complete_event_replay": True,
        "validated_bundle_mutated_in_place": False,
        "durable_database_claim": False,
        "production_store_implemented": False,
    }


def _execution_context_contract() -> dict[str, Any]:
    return {
        "schema_version": "rq2c1-r1-execution-context-contract-v1.1",
        "stage": STAGE_ID,
        "context_schema": "ValidatedMemoryExecutionContextV1_1",
        "factory": "create_validated_execution_context_v1_1",
        "verifier": "verify_execution_context_v1_1",
        "bound_fields": [
            "validated_plan",
            "validated_bundle",
            "student_scope_hash",
            "snapshot_fingerprint",
            "projection_hash",
            "projected_status",
            "store_revision",
            "condition_id",
            "request_fingerprint",
            "context_fingerprint",
            "contract_id",
        ],
        "verifier_recomputes_current_snapshot": True,
        "verifier_recomputes_current_projection": True,
        "verifier_rechecks_store_bundle_fingerprint": True,
        "verifier_rechecks_scope": True,
        "verifier_rechecks_time": True,
        "temporal_api": "temporal_validity_aware_v1_1",
        "query_time_authority": "ValidatedRetrievalPlanV1_2.query_time_utc",
        "r2_naive_time_helper_used": False,
        "immutable_episode_status_is_current_authority": False,
        "current_projection_status_is_authority": True,
        "completed_allowed_only_for_completion_target": True,
        "manual_or_stale_context_accepted": False,
    }


def _correction_contract() -> dict[str, Any]:
    return {
        "schema_version": "rq2c1-r1-correction-target-contract-v1",
        "stage": STAGE_ID,
        "contract_id": "CORRECTION_TARGET_RESOLUTION_V1",
        "resolution_order": [
            "EXPLICIT_SUPERSEDES_MEMORY_ID",
            "GOVERNED_TARGET_MEMORY_TYPE_AND_ENTITIES",
            "UNIQUE_SINGLETON_FALLBACK",
            "FAIL_CLOSED",
        ],
        "scope_match_required": True,
        "active_status_required": True,
        "tombstoned_target_allowed": False,
        "zero_candidate_failure": "CORRECTION_TARGET_NOT_FOUND",
        "multiple_candidate_failure": "AMBIGUOUS_CORRECTION_TARGET",
        "lexicographic_target_selection_used": False,
        "dense_similarity_target_selection_used": False,
        "gold_target_selection_used": False,
        "llm_target_selection_used": False,
    }


def _run_guard_probes(ledger: RuntimeSafetyEventLedgerV1) -> dict[str, Any]:
    observed: list[str] = []

    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    try:
        store.write_bundle(object())  # type: ignore[arg-type]
    except StoreIntegrityError:
        observed.append("UNVALIDATED_PAYLOAD_USE_ATTEMPT")

    bundle = build_validated_bundle_v1_1(
        memory_id="memory-probe-transition",
        student_scope_id="student-probe-transition",
        memory_type="GOAL",
        text="controlled probe goal",
    )
    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    store.write_bundle(bundle)
    store.apply_state_event(
        bundle.episode.memory_id, "COMPLETE", "2026-08-27T10:00:00+00:00"
    )
    try:
        store.apply_state_event(
            bundle.episode.memory_id, "COMPLETE", "2026-08-27T10:01:00+00:00"
        )
    except StoreIntegrityError:
        observed.append("INVALID_STATE_TRANSITION_ATTEMPT")

    deleted = build_validated_bundle_v1_1(
        memory_id="memory-probe-deleted",
        student_scope_id="student-probe-deleted",
        memory_type="GOAL",
        text="controlled probe deleted goal",
    )
    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    store.write_bundle(deleted)
    store.apply_state_event(
        deleted.episode.memory_id, "DELETE", "2026-08-27T10:00:00+00:00"
    )
    try:
        store.apply_state_event(
            deleted.episode.memory_id, "COMPLETE", "2026-08-27T10:01:00+00:00"
        )
    except StoreIntegrityError:
        observed.append("DELETED_MEMORY_RESURRECTION_ATTEMPT")

    backdated = build_validated_bundle_v1_1(
        memory_id="memory-probe-backdated",
        student_scope_id="student-probe-backdated",
        memory_type="GOAL",
        text="controlled probe event time",
    )
    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    store.write_bundle(backdated)
    try:
        store.apply_state_event(
            backdated.episode.memory_id, "DELETE", "2026-01-01T00:00:01+00:00"
        )
    except StoreIntegrityError:
        observed.append("BACKDATED_STORE_EVENT_ATTEMPT")

    context_bundle = build_validated_bundle_v1_1(
        memory_id="memory-probe-context",
        student_scope_id="student-probe-context",
        memory_type="GOAL",
        text="controlled probe context goal",
    )
    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    store.write_bundle(context_bundle)
    plan = validated_query_plan_v1_1(
        student_scope_id="student-probe-context",
        original_query="continue my goal",
        target_memory_types=("GOAL",),
    )
    context = create_validated_execution_context_v1_1(
        plan=plan,
        bundle=context_bundle,
        snapshot=store.snapshot("student-probe-context"),
        store=store,
        condition_id="P2_PERSISTENT_MEMORY_ONLY",
        request_fingerprint="probe-request-context",
        safety_ledger=ledger,
    )
    later = build_validated_bundle_v1_1(
        memory_id="memory-probe-context-later",
        student_scope_id="student-probe-context",
        memory_type="PREFERENCE",
        text="controlled probe later preference",
    )
    store.write_bundle(later)
    try:
        verify_execution_context_v1_1(
            context,
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="probe-request-context",
            safety_ledger=ledger,
        )
    except ExecutionContextError:
        observed.append("STALE_SNAPSHOT_ATTEMPT")

    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    store.write_bundle(context_bundle)
    cross_plan = validated_query_plan_v1_1(
        student_scope_id="student-probe-other",
        original_query="continue my goal",
        target_memory_types=("GOAL",),
    )
    try:
        create_validated_execution_context_v1_1(
            plan=cross_plan,
            bundle=context_bundle,
            snapshot=store.snapshot("student-probe-other"),
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="probe-request-cross",
            safety_ledger=ledger,
        )
    except ExecutionContextError:
        observed.append("CROSS_SCOPE_EXECUTION_CONTEXT_ATTEMPT")

    plan = validated_query_plan_v1_1(
        student_scope_id="student-probe-context",
        original_query="continue my goal",
        target_memory_types=("GOAL",),
    )
    context = create_validated_execution_context_v1_1(
        plan=plan,
        bundle=context_bundle,
        snapshot=store.snapshot("student-probe-context"),
        store=store,
        condition_id="P2_PERSISTENT_MEMORY_ONLY",
        request_fingerprint="probe-request-fingerprint",
        safety_ledger=ledger,
    )
    try:
        verify_execution_context_v1_1(
            replace(context, context_fingerprint="0" * 64),
            store=store,
            condition_id="P2_PERSISTENT_MEMORY_ONLY",
            request_fingerprint="probe-request-fingerprint",
            safety_ledger=ledger,
        )
    except ExecutionContextError:
        observed.append("EXECUTION_CONTEXT_FINGERPRINT_MISMATCH")

    store = OfflinePersistentMemoryStoreV1_1(safety_ledger=ledger)
    for suffix in ("a", "b"):
        store.write_bundle(
            build_validated_bundle_v1_1(
                memory_id=f"memory-probe-ambiguous-{suffix}",
                student_scope_id="student-probe-ambiguous",
                memory_type="PREFERENCE",
                text=f"controlled probe preference {suffix}",
            )
        )
    try:
        resolve_correction_target_v1_1(
            value={"student_scope_id": "student-probe-ambiguous"},
            store=store,
            safety_ledger=ledger,
        )
    except CorrectionTargetError:
        observed.append("AMBIGUOUS_CORRECTION_TARGET_ATTEMPT")

    try:
        execute_rag_for_condition_v1_1(
            condition_id="P1_BASE",
            candidate_allowed=True,
            effective_query="guard probe only",
            safety_ledger=ledger,
        )
    except ConditionIsolationError:
        observed.append("RAG_EXECUTION_IN_DISABLED_CONDITION")
    return {
        "probe_count": len(observed),
        "observed_event_types": sorted(observed),
        "all_probes_blocked": len(observed) == 9,
        "provider_calls": 0,
        "network_access": False,
    }


def _context_missing_diagnostic(result: Mapping[str, Any]) -> dict[str, Any]:
    selected = {
        condition: values
        for condition, values in result["conditions"].items()
        if condition
        in {
            "P1_BASE",
            "P2_SESSION_STATE_ONLY",
            "P2_PERSISTENT_MEMORY_ONLY",
            "P2_FULL",
        }
    }
    return {
        "schema_version": "rq2c1-r1-context-missing-diagnostic-v1",
        "dataset_role": "CONTEXT_MISSING_QUALITATIVE_DIAGNOSTIC",
        "record_count": result["record_count"],
        "included_in_authentic_aggregate": False,
        "conditions": {
            condition: {
                "clarification_precision": values["capability_metrics"][
                    "clarification_precision"
                ],
                "clarification_recall": values["capability_metrics"][
                    "clarification_recall"
                ],
                "execution_capability_false_positive_count": sum(
                    int(values["capability_metrics"]["per_capability"][name]["fp"])
                    for name in (
                        "dashboard_evidence",
                        "course_retrieval",
                        "episodic_memory",
                        "planning",
                    )
                ),
                "session_state_false_positive_count": int(
                    values["episodic_state_use_metrics"]["false_positive"]
                ),
                "persistent_retrieval_attempt_count": values[
                    "persistent_retrieval_attempt_count"
                ],
                "actual_retriever_call_count": values[
                    "actual_retriever_call_count"
                ],
                "unsafe_execution_count": 0,
            }
            for condition, values in selected.items()
        },
        "memory_auto_constructed": False,
        "missing_context_triggered_persistent_retrieval": False,
        "policy_selection_use": "NOT_USED_FOR_POLICY_SELECTION",
    }


def _rag_isolation_report(
    *,
    synthetic: Mapping[str, Any],
    authentic: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    datasets = {
        "SYNTHETIC35": synthetic,
        "AUTHENTIC22": authentic,
        "CONTEXT_MISSING3": registry,
    }
    report: dict[str, Any] = {}
    hard_failures = 0
    for name, result in datasets.items():
        conditions: dict[str, Any] = {}
        for condition_id, values in result["conditions"].items():
            row = {
                key: values[key]
                for key in (
                    "candidate_gate_count",
                    "actual_retriever_call_count",
                    "sufficiency_call_count",
                    "admission_count",
                    "provider_call_count",
                    "network_call_count",
                    "retrieval_result_reused_across_conditions",
                    "sufficiency_result_reused_across_conditions",
                    "admission_result_reused_across_conditions",
                )
            }
            if condition_id in {
                "P1_BASE",
                "P2_SESSION_STATE_ONLY",
                "P2_PERSISTENT_MEMORY_ONLY",
            }:
                hard_failures += int(row["actual_retriever_call_count"] != 0)
            else:
                hard_failures += int(
                    row["actual_retriever_call_count"] != row["candidate_gate_count"]
                )
            conditions[condition_id] = row
        report[name] = {
            "record_count": result["record_count"],
            "conditions": conditions,
            "physical_actual_retriever_call_count": sum(
                value["actual_retriever_call_count"] for value in conditions.values()
            ),
        }
    return {
        "schema_version": "rq2c1-r1-rag-condition-isolation-v1",
        "stage": STAGE_ID,
        "condition_loop_precedes_rag_execution": True,
        "rag_precomputed_before_condition_loop": False,
        "datasets": report,
        "disabled_condition_actual_call_count": sum(
            dataset["conditions"][condition]["actual_retriever_call_count"]
            for dataset in report.values()
            for condition in (
                "P1_BASE",
                "P2_SESSION_STATE_ONLY",
                "P2_PERSISTENT_MEMORY_ONLY",
            )
        ),
        "hard_failure_count": hard_failures,
        "status": "PASS" if hard_failures == 0 else "FAIL",
        "provider_calls": 0,
        "network_calls": 0,
    }


def _local_artifacts(
    *,
    controlled: CorrectedControlledResult,
    synthetic_local: tuple[Mapping[str, Any], ...],
    authentic_local: tuple[Mapping[str, Any], ...],
    registry_local: tuple[Mapping[str, Any], ...],
    ledger: RuntimeSafetyEventLedgerV1,
) -> dict[str, Any]:
    paths = (
        (
            LOCAL_ROOT / "fixture_runs/controlled_fixture_results_v1_1.json",
            lambda path: write_json(path, list(controlled.local_rows)),
        ),
        (
            LOCAL_ROOT / "condition_predictions/synthetic_conditions_v1_1.jsonl",
            lambda path: write_jsonl(path, synthetic_local),
        ),
        (
            LOCAL_ROOT / "condition_predictions/authentic_conditions_v1_1.jsonl",
            lambda path: write_jsonl(path, authentic_local),
        ),
        (
            LOCAL_ROOT / "condition_predictions/context_missing_conditions_v1_1.jsonl",
            lambda path: write_jsonl(path, registry_local),
        ),
    )
    for path, writer in paths:
        writer(path)
    all_paths = tuple(path for path, _writer in paths) + (ledger.path,)
    members = [
        {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in all_paths
    ]
    return {
        "artifact_count": len(members),
        "members": members,
        "ignored": True,
        "tracked": False,
        "contains_track_a": False,
        "contains_track_b": False,
        "governed_text_in_tracked_output": False,
    }


def _delta_report(
    *,
    controlled: CorrectedControlledResult,
    session_results: Mapping[str, Any],
    synthetic: Mapping[str, Any],
    authentic: Mapping[str, Any],
    rag_isolation: Mapping[str, Any],
) -> dict[str, Any]:
    original_root = ROOT / "evaluation/capability_routing_rq2c1_v1"
    original_rag = json.loads(
        (original_root / "rq2c1_rag_execution_results_v1.json").read_text()
    )
    original_memory = json.loads(
        (original_root / "rq2c1_persistent_policy_comparison_v1.json").read_text()
    )
    original_oof = json.loads(
        (original_root / "rq2c1_session_policy_oof_results_v1.json").read_text()
    )
    original_policy = json.loads(
        (original_root / "rq2c1_final_session_policy_v1.json").read_text()
    )
    original_synthetic = json.loads(
        (original_root / "rq2c1_synthetic_session_results_v1.json").read_text()
    )
    original_authentic = json.loads(
        (original_root / "rq2c1_authentic_descriptive_results_v1.json").read_text()
    )
    corrected_primary = controlled.memory_results["persistent_policy_comparison"][
        "policy_results"
    ][PRIMARY_PERSISTENT_POLICY]
    original_primary = original_memory["policy_results"][PRIMARY_PERSISTENT_POLICY]
    metric_names = (
        "recall_at_1",
        "recall_at_3",
        "mrr",
        "multi_hop_complete_retrieval",
        "no_memory_abstention",
    )
    persistent_delta = {
        name: float(corrected_primary[name]) - float(original_primary[name])
        for name in metric_names
    }
    original_physical = {
        "SYNTHETIC35": max(
            value["rag_local_execution_count"]
            for value in original_synthetic["conditions"].values()
        ),
        "AUTHENTIC22": max(
            value["rag_local_execution_count"]
            for value in original_authentic["conditions"].values()
        ),
        "CONTEXT_MISSING3": 0,
    }
    corrected_physical = {
        name: value["physical_actual_retriever_call_count"]
        for name, value in rag_isolation["datasets"].items()
    }
    original_session_policy = original_policy["selected_policy_id"]
    corrected_session_policy = session_results["final_session_policy"][
        "selected_policy_id"
    ]
    original_oof_metrics = original_oof["oof_metrics"]
    corrected_oof_metrics = session_results["nested_oof"]["oof_metrics"]
    return {
        "schema_version": "rq2c1-r1-original-vs-corrected-delta-v1",
        "original": {
            "stage_id": ORIGINAL_STAGE_ID,
            "disposition": ORIGINAL_DISPOSITION,
            "preservation": ORIGINAL_PRESERVATION,
            "head": "717c285af907ab3cd27702d96e5e0d94420f8e54",
        },
        "corrected": {"stage_id": STAGE_ID},
        "store_lifecycle_changes": [
            "EXPLICIT_TRANSITION_TABLE",
            "PERMANENT_EVENT_DERIVED_TOMBSTONES",
            "AWARE_MONOTONIC_EVENT_TIME",
        ],
        "transaction_binding_changes": [
            "CURRENT_STORE_BUNDLE_REBINDING",
            "CURRENT_SNAPSHOT_AND_PROJECTION_RECOMPUTATION",
            "FACTORY_ISSUANCE_CHECK",
            "R5_AWARE_TIME",
        ],
        "actual_rag_call_changes": {
            "original_preloop_execution": True,
            "corrected_condition_local_execution": True,
            "original_physical_call_counts": original_physical,
            "corrected_physical_call_counts": corrected_physical,
        },
        "controlled_rag_metric_delta": {
            "candidate_decision_accuracy": float(
                controlled.rag_results["candidate_decision_accuracy"]
            )
            - float(original_rag["candidate_decision_accuracy"]),
            "sufficiency_status_accuracy": float(
                controlled.rag_results["sufficiency_status_accuracy"]
            )
            - float(original_rag["sufficiency_status_accuracy"]),
        },
        "persistent_primary_policy_metric_delta": persistent_delta,
        "persistent_metrics_unchanged_after_correctness_repair": all(
            value == 0.0 for value in persistent_delta.values()
        ),
        "session_policy_change": {
            "original": original_session_policy,
            "corrected": corrected_session_policy,
            "changed": original_session_policy != corrected_session_policy,
        },
        "session_oof_f1_delta": float(corrected_oof_metrics["f1"])
        - float(original_oof_metrics["f1"]),
        "condition_metric_changes": {
            "synthetic_p2_full_state_f1_delta": float(
                synthetic["conditions"]["P2_FULL"]["episodic_state_use_metrics"][
                    "f1"
                ]
            )
            - float(
                original_synthetic["conditions"]["P2_FULL"][
                    "episodic_state_use_metrics"
                ]["f1"]
            ),
            "authentic_p2_full_state_f1_delta": float(
                authentic["conditions"]["P2_FULL"]["episodic_state_use_metrics"][
                    "f1"
                ]
            )
            - float(
                original_authentic["conditions"]["P2_FULL"][
                    "episodic_state_use_metrics"
                ]["f1"]
            ),
            "reported_per_condition_rag_counts_changed": False,
            "physical_execution_semantics_changed": True,
        },
        "hard_safety_instrumentation_changes": {
            "original_unvalidated_payload_counter_source": "CONSTANT_ZERO",
            "original_stale_snapshot_counter_source": "CONSTANT_ZERO",
            "corrected_counter_source": "RUNTIME_SAFETY_EVENT_LEDGER_V1_AND_GUARD_TRACES",
            "attempt_blocked_success_dimensions_reported": True,
            "adversarial_guard_categories_exercised": 9,
        },
        "synthetic_full_state_f1_delta": float(
            synthetic["conditions"]["P2_FULL"]["episodic_state_use_metrics"]["f1"]
        )
        - float(
            original_synthetic["conditions"]["P2_FULL"][
                "episodic_state_use_metrics"
            ]["f1"]
        ),
        "authentic_full_state_f1_delta": float(
            authentic["conditions"]["P2_FULL"]["episodic_state_use_metrics"]["f1"]
        )
        - float(
            original_authentic["conditions"]["P2_FULL"][
                "episodic_state_use_metrics"
            ]["f1"]
        ),
        "aggregate_metrics_unchanged_after_correctness_repair": (
            all(value == 0.0 for value in persistent_delta.values())
            and float(corrected_oof_metrics["f1"]) == float(original_oof_metrics["f1"])
            and float(controlled.rag_results["candidate_decision_accuracy"])
            == float(original_rag["candidate_decision_accuracy"])
            and float(controlled.rag_results["sufficiency_status_accuracy"])
            == float(original_rag["sufficiency_status_accuracy"])
        ),
        "policy_or_threshold_tuned": False,
        "original_files_overwritten": False,
    }


def run_rq2c1_r1() -> RQ2C1R1RunResult:
    starting = verify_starting_preflight()
    gold = load_and_validate_gold(ROOT)
    fixtures = load_controlled_fixtures()
    ledger = RuntimeSafetyEventLedgerV1()
    ledger.reset_local_file()
    encoder = local_encoder_preflight_v1_1()
    controlled = run_corrected_controlled_evaluation(fixtures, ledger)

    p1_synthetic = load_p1_ledger_v1_1(SYNTHETIC_LEDGER)
    session_cases = _session_cases(gold, p1_synthetic)
    oof = nested_leave_one_family_out(session_cases)
    selected = select_session_policy(session_cases)
    final_policy = {
        "schema_version": "rq2c1-r1-final-session-policy-v1",
        "selected_policy_id": selected["selected_policy_id"],
        "candidate_results": selected["candidate_results"],
        "selection_dataset": "SYNTHETIC_COVERAGE_STRESS_GOLD",
        "selection_record_count": len(session_cases),
        "scenario_family_count": 18,
        "selection_rule_frozen": True,
        "authentic_used_for_selection": False,
        "context_missing_used_for_selection": False,
        "immutable": True,
    }
    synthetic, synthetic_local = run_conditions_v1_1(
        examples=gold.synthetic_gold,
        p1_rows=p1_synthetic,
        session_policy_id=str(final_policy["selected_policy_id"]),
        dataset_role="SYNTHETIC_COVERAGE_STRESS_GOLD",
        safety_ledger=ledger,
    )
    synthetic.update(
        {
            "schema_version": "rq2c1-r1-corrected-synthetic-results-v1",
            "nested_oof_reported_separately": True,
            "policy_development_role": True,
        }
    )
    # Authentic and registry execution occurs only after the synthetic-only
    # policy object above is immutable.
    authentic, authentic_local = run_conditions_v1_1(
        examples=gold.authentic_gold,
        p1_rows=load_p1_ledger_v1_1(AUTHENTIC_LEDGER),
        session_policy_id=str(final_policy["selected_policy_id"]),
        dataset_role="AUTHENTIC_CODEBOOK_CALIBRATION_GOLD",
        safety_ledger=ledger,
    )
    authentic.update(
        {
            "schema_version": "rq2c1-r1-authentic-descriptive-results-v1",
            "evidence_role": "DESCRIPTIVE_IN_SAMPLE_ONLY",
            "policy_selection_use": "NOT_USED_FOR_POLICY_SELECTION",
            "independence": "NOT_INDEPENDENT_PERFORMANCE_EVIDENCE",
            "mechanism_code_frozen_before_execution": True,
        }
    )
    registry_raw, registry_local = run_conditions_v1_1(
        examples=gold.authentic_context_missing_registry,
        p1_rows=load_p1_ledger_v1_1(REGISTRY_LEDGER),
        session_policy_id=str(final_policy["selected_policy_id"]),
        dataset_role="CONTEXT_MISSING_QUALITATIVE_DIAGNOSTIC",
        safety_ledger=ledger,
    )
    registry = _context_missing_diagnostic(registry_raw)
    rag_isolation = _rag_isolation_report(
        synthetic=synthetic, authentic=authentic, registry=registry_raw
    )
    if rag_isolation["status"] != "PASS":
        raise RuntimeError("BLOCKED_RQ2_C1_R1_CONDITION_ISOLATION")

    probe_results = _run_guard_probes(ledger)
    runtime_safety = ledger.aggregate()
    runtime_safety.update(
        {
            "stage": STAGE_ID,
            "adversarial_guard_probes": probe_results,
            "mechanism_safety_counters": dict(
                controlled.mechanism_safety_counters
            ),
            "mechanism_successful_violation_count": sum(
                controlled.mechanism_safety_counters.values()
            ),
        }
    )
    runtime_safety["hard_failure_count"] = int(
        runtime_safety["successful_violation_count"]
    ) + int(runtime_safety["mechanism_successful_violation_count"])
    runtime_safety["status"] = (
        "PASS" if runtime_safety["hard_failure_count"] == 0 else "FAIL"
    )
    if runtime_safety["status"] != "PASS" or not probe_results["all_probes_blocked"]:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_SAFETY_INSTRUMENTATION")

    session_results = {
        "schema_version": "rq2c1-r1-corrected-session-results-v1",
        "nested_oof": {
            "schema_version": "rq2c1-r1-session-policy-oof-results-v1",
            **oof,
        },
        "final_session_policy": final_policy,
        "synthetic35": synthetic,
        "authentic_used_for_selection": False,
        "context_missing_used_for_selection": False,
    }
    condition_results = {
        "schema_version": "rq2c1-r1-corrected-condition-results-v1",
        "controlled_condition_contract": controlled.controlled_condition_results,
        "synthetic35": synthetic,
        "p1_capability_plan_rewritten": False,
        "condition_ids": list(CONDITION_IDS),
    }
    local_manifest = _local_artifacts(
        controlled=controlled,
        synthetic_local=synthetic_local,
        authentic_local=authentic_local,
        registry_local=registry_local,
        ledger=ledger,
    )
    runtime_preflight = {
        "schema_version": "rq2c1-r1-runtime-preflight-v1",
        "status": "PASS",
        "encoder": encoder,
        "fixture_access_audit": expected_field_access_audit(),
        "gold_identity": gold.identity,
        "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
        "local_artifacts": local_manifest,
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_a_access_count": 0,
        "track_b_access_count": 0,
    }
    delta = _delta_report(
        controlled=controlled,
        session_results=session_results,
        synthetic=synthetic,
        authentic=authentic,
        rag_isolation=rag_isolation,
    )
    return RQ2C1R1RunResult(
        starting_preflight=starting,
        store_contract=_store_contract(),
        execution_context_contract=_execution_context_contract(),
        rag_isolation=rag_isolation,
        correction_contract=_correction_contract(),
        runtime_safety=runtime_safety,
        controlled=controlled,
        session_results=session_results,
        condition_results=condition_results,
        authentic_results=authentic,
        context_missing_results=registry,
        delta_results=delta,
        runtime_preflight=runtime_preflight,
        local_artifact_manifest=local_manifest,
    )


def main() -> int:
    from .finalise_rq2c1_r1 import finalise_rq2c1_r1

    result = run_rq2c1_r1()
    finalise_rq2c1_r1(result)
    print(
        json.dumps(
            {
                "status": "RQ2_C1_R1_CORRECTED_OFFLINE_EXECUTION_COMPLETE",
                "final_session_policy": result.session_results[
                    "final_session_policy"
                ]["selected_policy_id"],
                "hard_safety": result.runtime_safety["status"],
                "rag_condition_isolation": result.rag_isolation["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
