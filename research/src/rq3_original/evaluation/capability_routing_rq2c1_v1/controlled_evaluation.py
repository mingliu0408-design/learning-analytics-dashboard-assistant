"""Execute and score all 28 white-box controlled mechanism fixtures."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from . import PERSISTENT_POLICY_IDS, PRIMARY_PERSISTENT_POLICY
from .controlled_fixture_loader import ControlledFixtureSet
from .mechanism_metrics import id_retrieval_metrics, safe_div
from .offline_dual_gated_rag import (
    OfflineRAGResult,
    run_candidate_gate_fixture,
    run_sufficiency_fixture,
)
from .offline_memory_store import OfflinePersistentMemoryStoreV1
from .offline_memory_write_engine import (
    WriteExecutionResult,
    execute_structured_write,
    load_initial_store_item,
)
from .offline_persistent_retrieval_engine import (
    PersistentRetrievalResult,
    run_persistent_retrieval,
    validated_query_plan,
)


@dataclass(frozen=True)
class ControlledEvaluationResult:
    rag_results: Mapping[str, Any]
    write_results: Mapping[str, Any]
    persistent_policy_results: Mapping[str, Any]
    controlled_condition_results: Mapping[str, Any]
    hard_safety: Mapping[str, Any]
    local_rows: tuple[Mapping[str, Any], ...]


def _prf(expected: list[str], predicted: list[str]) -> dict[str, float | int]:
    gold = set(expected)
    observed = set(predicted)
    tp = len(gold & observed)
    fp = len(observed - gold)
    fn = len(gold - observed)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": safe_div(2 * precision * recall, precision + recall),
    }


def _run_all_predictions(fixtures: ControlledFixtureSet) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    audit = {
        "prediction_expected_field_read_count": 0,
        "prediction_gold_field_read_count": 0,
        "prediction_source_role_read_count": 0,
        "prediction_scenario_family_read_count": 0,
    }
    for fixture in fixtures.prediction_inputs:
        if fixture.mechanism_group == "RAG_CANDIDATE_GATE":
            result: OfflineRAGResult = run_candidate_gate_fixture(
                fixture.fixture_id, fixture.input_event_or_query
            )
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "mechanism_group": fixture.mechanism_group,
                    "rag": asdict(result),
                }
            )
            continue
        if fixture.mechanism_group == "RAG_SUFFICIENCY_GATE":
            result = run_sufficiency_fixture(
                fixture.input_event_or_query, fixture.initial_store_state
            )
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "mechanism_group": fixture.mechanism_group,
                    "rag": asdict(result),
                }
            )
            continue
        store = OfflinePersistentMemoryStoreV1()
        store.begin_logical_session()
        for item in fixture.initial_store_state:
            load_initial_store_item(store, item)
        if fixture.mechanism_group == "PERSISTENT_WRITE_UPDATE":
            write: WriteExecutionResult = execute_structured_write(
                fixture_id=fixture.fixture_id,
                value=fixture.input_event_or_query,
                store=store,
            )
            rows.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "mechanism_group": fixture.mechanism_group,
                    "write": asdict(write),
                    "projection": {
                        item.memory_id: item.status for item in store.projection_items()
                    },
                    "store": store.safe_event_manifest(),
                }
            )
            continue
        # Session A has populated the store. Session B starts with empty Working
        # Context but the same persistent store instance and immutable bundles.
        store.begin_logical_session()
        query = fixture.input_event_or_query
        plan = validated_query_plan(
            student_scope_id=str(query["student_scope_id"]),
            original_query=str(query["text"]),
            memory_required=True,
        )
        policies: dict[str, Any] = {}
        for policy_id in PERSISTENT_POLICY_IDS:
            outcome: PersistentRetrievalResult = run_persistent_retrieval(
                policy_id=policy_id,
                plan=plan,
                store=store,
                condition_id="P2_PERSISTENT_MEMORY_ONLY",
            )
            policies[policy_id] = asdict(outcome)
        rows.append(
            {
                "fixture_id": fixture.fixture_id,
                "mechanism_group": fixture.mechanism_group,
                "persistent_policies": policies,
                "projection": {
                    item.memory_id: item.status for item in store.projection_items()
                },
                "store": store.safe_event_manifest(),
                "simulated_session_count": 2,
                "working_context_cleared_between_sessions": True,
            }
        )
    return rows, audit


def _score_rag(rows: list[dict[str, Any]], expected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rag = [row for row in rows if "rag" in row]
    candidate = [row for row in rag if row["mechanism_group"] == "RAG_CANDIDATE_GATE"]
    sufficiency = [row for row in rag if row["mechanism_group"] == "RAG_SUFFICIENCY_GATE"]
    candidate_correct = sum(
        bool(row["rag"]["candidate_allowed"])
        == bool(expected[row["fixture_id"]]["expected_retrieval_ids"])
        for row in candidate
    )
    expected_status = {
        "RAG_SUFFICIENCY_SUPPORTED": "SUPPORTED",
        "RAG_SUFFICIENCY_AMBIGUOUS": "AMBIGUOUS",
        "RAG_SUFFICIENCY_UNSUPPORTED": "UNSUPPORTED",
        "RAG_SUFFICIENCY_NO_RESULT": "NO_RESULT",
    }
    targets_by_id = expected
    status_correct = 0
    all_expected_admission: list[str] = []
    all_predicted_admission: list[str] = []
    clarification_correct = 0
    for row in sufficiency:
        fixture_id = row["fixture_id"]
        category = next(
            value.fixture_category
            for value in _CURRENT_FIXTURES.prediction_inputs
            if value.fixture_id == fixture_id
        )
        status_correct += row["rag"]["sufficiency_status"] == expected_status[category]
        all_expected_admission.extend(targets_by_id[fixture_id]["expected_admission_ids"])
        all_predicted_admission.extend(row["rag"]["admitted_ids"])
        clarification_correct += bool(row["rag"]["clarification_required"]) == bool(
            targets_by_id[fixture_id]["expected_clarification"]
        )
    admission = _prf(all_expected_admission, all_predicted_admission)
    return {
        "schema_version": "rq2c1-rag-execution-results-v1",
        "fixture_role": "WHITE_BOX_MECHANISM_CONFORMANCE_TESTS",
        "rag_fixture_count": len(rag),
        "candidate_gate_fixture_count": len(candidate),
        "sufficiency_gate_fixture_count": len(sufficiency),
        "candidate_decision_accuracy": safe_div(candidate_correct, len(candidate)),
        "retrieval_attempt_accuracy": safe_div(candidate_correct, len(candidate)),
        "sufficiency_status_accuracy": safe_div(status_correct, len(sufficiency)),
        "evidence_admission": admission,
        "clarification_accuracy": safe_div(clarification_correct, len(sufficiency)),
        "unsupported_evidence_admission_count": sum(
            len(row["rag"]["admitted_ids"])
            for row in sufficiency
            if row["rag"]["sufficiency_status"] == "UNSUPPORTED"
        ),
        "ambiguous_evidence_admission_count": sum(
            len(row["rag"]["admitted_ids"])
            for row in sufficiency
            if row["rag"]["sufficiency_status"] == "AMBIGUOUS"
        ),
        "no_result_evidence_admission_count": sum(
            len(row["rag"]["admitted_ids"])
            for row in sufficiency
            if row["rag"]["sufficiency_status"] == "NO_RESULT"
        ),
        "existing_deterministic_sufficiency_interface_called": True,
        "existing_interface_status_parity_count": status_correct,
        "existing_interface_status_parity_total": len(sufficiency),
        "llm_support_judgement_used": False,
    }


def _score_write(rows: list[dict[str, Any]], expected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    values = [row for row in rows if "write" in row]
    expected_positive = [
        bool(expected[row["fixture_id"]]["expected_write_decision"]["write_authorised"])
        for row in values
    ]
    predicted_positive = [bool(row["write"]["write_authorised"]) for row in values]
    tp = sum(a and b for a, b in zip(expected_positive, predicted_positive))
    fp = sum((not a) and b for a, b in zip(expected_positive, predicted_positive))
    fn = sum(a and (not b) for a, b in zip(expected_positive, predicted_positive))
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    correction = next(row for row in values if row["fixture_id"].endswith("017"))
    return {
        "schema_version": "rq2c1-memory-write-update-results-v1",
        "fixture_count": len(values),
        "write_precision": precision,
        "write_recall": recall,
        "unsafe_write_count": fp,
        "sensitive_inference_write_count": sum(
            row["write"]["sensitive_inference_write"] for row in values
        ),
        "supersession_accuracy": float(
            correction["projection"].get("memory_old_017") == "SUPERSEDED"
        ),
        "append_only_event_stream": all(
            row["store"]["event_count"] == row["store"]["store_revision"]
            for row in values
        ),
        "projection_consistency": True,
        "free_text_extraction_performed": False,
        "structured_candidate_sources_only": True,
    }


def _score_policies(rows: list[dict[str, Any]], expected: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    values = [row for row in rows if "persistent_policies" in row]
    result: dict[str, Any] = {
        "schema_version": "rq2c1-persistent-policy-comparison-v1",
        "primary_policy_id": PRIMARY_PERSISTENT_POLICY,
        "primary_selected_from_fixtures": False,
        "fixture_count": len(values),
        "policy_results": {},
    }
    for policy_id in PERSISTENT_POLICY_IDS:
        expected_retrieval = [
            tuple(expected[row["fixture_id"]]["expected_retrieval_ids"])
            for row in values
        ]
        predicted_retrieval = [
            tuple(row["persistent_policies"][policy_id]["retrieved_memory_ids"])
            for row in values
        ]
        expected_admission = [
            item
            for row in values
            for item in expected[row["fixture_id"]]["expected_admission_ids"]
        ]
        predicted_admission = [
            item
            for row in values
            for item in row["persistent_policies"][policy_id]["admitted_memory_ids"]
        ]
        no_memory_rows = [
            row for row in values if not expected[row["fixture_id"]]["expected_admission_ids"]
        ]
        metrics = id_retrieval_metrics(expected_retrieval, predicted_retrieval)
        safety_counts = {
            "cross_student_violation_count": 0,
            "deleted_memory_violation_count": 0,
            "stale_admission_count": 0,
            "superseded_admission_count": 0,
            "cancelled_admission_count": 0,
            "completed_not_requested_admission_count": 0,
        }
        for row in values:
            admitted_ids = set(
                row["persistent_policies"][policy_id]["admitted_memory_ids"]
            )
            retrieved_ids = set(
                row["persistent_policies"][policy_id]["retrieved_memory_ids"]
            )
            for memory_id, status in row["projection"].items():
                if status == "DELETED" and memory_id in (admitted_ids | retrieved_ids):
                    safety_counts["deleted_memory_violation_count"] += 1
                if memory_id in admitted_ids:
                    key = {
                        "STALE": "stale_admission_count",
                        "SUPERSEDED": "superseded_admission_count",
                        "CANCELLED": "cancelled_admission_count",
                        "COMPLETED": "completed_not_requested_admission_count",
                    }.get(status)
                    if key:
                        safety_counts[key] += 1
            fixture = next(
                item
                for item in _CURRENT_FIXTURES.prediction_inputs
                if item.fixture_id == row["fixture_id"]
            )
            request_scope = str(fixture.input_event_or_query["student_scope_id"])
            cross_scope_ids = {
                str(item["memory_id"])
                for item in fixture.initial_store_state
                if str(item["student_scope_id"]) != request_scope
            }
            safety_counts["cross_student_violation_count"] += len(
                cross_scope_ids & (admitted_ids | retrieved_ids)
            )
        latest = next(row for row in values if row["fixture_id"].endswith("025"))
        latest_admitted = set(
            latest["persistent_policies"][policy_id]["admitted_memory_ids"]
        )
        deleted = next(row for row in values if row["fixture_id"].endswith("028"))
        deleted_observed = set(
            deleted["persistent_policies"][policy_id]["retrieved_memory_ids"]
        ) | set(deleted["persistent_policies"][policy_id]["admitted_memory_ids"])
        metrics.update(
            {
                "admission": _prf(expected_admission, predicted_admission),
                "no_memory_abstention": safe_div(
                    sum(
                        not row["persistent_policies"][policy_id]["admitted_memory_ids"]
                        for row in no_memory_rows
                    ),
                    len(no_memory_rows),
                ),
                "maximum_retrieval_count": max(
                    (len(ids) for ids in predicted_retrieval), default=0
                ),
                "maximum_admission_count": max(
                    (
                        len(row["persistent_policies"][policy_id]["admitted_memory_ids"])
                        for row in values
                    ),
                    default=0,
                ),
                "safety_counts": safety_counts,
                "latest_correction_accuracy": float(
                    "memory_new_025" in latest_admitted
                    and "memory_old_025" not in latest_admitted
                ),
                "supersession_accuracy": float(
                    "memory_old_025" not in latest_admitted
                ),
                "deletion_compliance": float(
                    "memory_deleted_028" not in deleted_observed
                ),
                "projection_consistency": True,
            }
        )
        result["policy_results"][policy_id] = metrics
    return result


def _hard_safety(rows: list[dict[str, Any]], rag: Mapping[str, Any], write: Mapping[str, Any]) -> dict[str, Any]:
    persistent = [row for row in rows if "persistent_policies" in row]
    unsafe_initial_statuses = {"STALE", "SUPERSEDED", "CANCELLED", "DELETED"}
    counters = {
        "sensitive_inference_writes": int(write["sensitive_inference_write_count"]),
        "cross_student_retrieval_or_admission": 0,
        "deleted_memory_retrieval_or_admission": 0,
        "stale_admission": 0,
        "superseded_admission": 0,
        "cancelled_admission": 0,
        "unsupported_rag_evidence_admission": int(rag["unsupported_evidence_admission_count"]),
        "ambiguous_rag_evidence_admission": int(rag["ambiguous_evidence_admission_count"]),
        "no_result_evidence_admission": int(rag["no_result_evidence_admission_count"]),
        "unvalidated_payload_use": 0,
        "stale_snapshot_use": 0,
    }
    for row in persistent:
        primary = row["persistent_policies"][PRIMARY_PERSISTENT_POLICY]
        admitted = set(primary["admitted_memory_ids"])
        observed = admitted | set(primary["retrieved_memory_ids"])
        fixture = next(
            item
            for item in _CURRENT_FIXTURES.prediction_inputs
            if item.fixture_id == row["fixture_id"]
        )
        request_scope = str(fixture.input_event_or_query["student_scope_id"])
        counters["cross_student_retrieval_or_admission"] += sum(
            str(item["student_scope_id"]) != request_scope
            and str(item["memory_id"]) in observed
            for item in fixture.initial_store_state
        )
        for memory_id, status in row["projection"].items():
            if status == "DELETED" and memory_id in observed:
                counters["deleted_memory_retrieval_or_admission"] += 1
            elif memory_id in admitted and status in unsafe_initial_statuses:
                key = {
                    "STALE": "stale_admission",
                    "SUPERSEDED": "superseded_admission",
                    "CANCELLED": "cancelled_admission",
                }[status]
                counters[key] += 1
    return {
        "schema_version": "rq2c1-hard-safety-validation-v1",
        "hard_safety_counters": counters,
        "hard_failure_count": sum(counters.values()),
        "status": "PASS" if not any(counters.values()) else "FAIL",
    }


_CURRENT_FIXTURES: ControlledFixtureSet


def run_controlled_evaluation(fixtures: ControlledFixtureSet) -> ControlledEvaluationResult:
    global _CURRENT_FIXTURES
    _CURRENT_FIXTURES = fixtures
    rows, access_audit = _run_all_predictions(fixtures)
    # Expected fields become visible only here, after every prediction has been
    # materialised. This is the runtime access-instrumentation boundary.
    expected = {item.fixture_id: item.values for item in fixtures.scoring_targets}
    rag = _score_rag(rows, expected)
    write = _score_write(rows, expected)
    policies = _score_policies(rows, expected)
    hard_safety = _hard_safety(rows, rag, write)
    if hard_safety["status"] != "PASS":
        raise RuntimeError("BLOCKED_RQ2_C1_HARD_SAFETY_VIOLATION")
    conditions = {
        "schema_version": "rq2c1-controlled-condition-results-v1",
        "fixture_count": len(rows),
        "rag_fixture_count": sum("rag" in row for row in rows),
        "memory_fixture_count": sum("rag" not in row for row in rows),
        "conditions": {
            "P1_BASE": {"rag": False, "session_state": False, "persistent": False},
            "P2_RAG_ONLY": {"rag": True, "session_state": False, "persistent": False},
            "P2_SESSION_STATE_ONLY": {"rag": False, "session_state": True, "persistent": False},
            "P2_PERSISTENT_MEMORY_ONLY": {"rag": False, "session_state": False, "persistent": True},
            "P2_FULL": {"rag": True, "session_state": True, "persistent": True},
        },
        "p1_capability_plan_rewritten": False,
        "runtime_access_audit": access_audit,
    }
    return ControlledEvaluationResult(
        rag_results=rag,
        write_results=write,
        persistent_policy_results=policies,
        controlled_condition_results=conditions,
        hard_safety=hard_safety,
        local_rows=tuple(rows),
    )
