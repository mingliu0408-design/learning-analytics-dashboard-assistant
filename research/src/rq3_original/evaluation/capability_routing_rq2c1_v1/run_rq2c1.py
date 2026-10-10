"""Deterministic provider-free entry point for RQ2-C1 offline execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from evaluation.capability_routing_rq2b_v1.gold_preflight import (
    GoldPreflightResult,
    load_and_validate_gold,
)

from . import (
    GOLD_INPUTS,
    LOCAL_ROOT,
    LOCAL_SUBDIRECTORIES,
    LOCAL_LEDGER_INPUTS,
    ROOT,
    write_json,
    write_jsonl,
    sha256_file,
)
from .authentic_descriptive_evaluation import (
    evaluate_authentic_after_freeze,
    evaluate_context_missing_after_freeze,
)
from .controlled_evaluation import ControlledEvaluationResult, run_controlled_evaluation
from .controlled_fixture_loader import expected_field_access_audit, load_controlled_fixtures
from .error_analysis import build_error_analysis
from .offline_persistent_retrieval_engine import local_encoder_preflight
from .offline_session_state_gate import session_input_from_p1
from .p2_condition_runner import load_p1_ledger, run_conditions
from .session_policy_calibration import (
    SessionCalibrationCase,
    nested_leave_one_family_out,
    select_session_policy,
)
from .starting_state import verify_starting_state


SYNTHETIC_LEDGER = Path(
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/"
    "synthetic_P1_D05_SIGNAL_UNION.jsonl"
)


@dataclass(frozen=True)
class RQ2C1RunResult:
    starting_preflight: Mapping[str, Any]
    runtime_preflight: Mapping[str, Any]
    store_contract: Mapping[str, Any]
    transaction_contract: Mapping[str, Any]
    controlled: ControlledEvaluationResult
    session_oof: Mapping[str, Any]
    final_session_policy: Mapping[str, Any]
    synthetic_results: Mapping[str, Any]
    authentic_results: Mapping[str, Any]
    context_missing_results: Mapping[str, Any]
    error_analysis: Mapping[str, Any]
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
            raise RuntimeError("BLOCKED_RQ2_C1_SESSION_POLICY")
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


def _local_artifacts(
    *,
    controlled: ControlledEvaluationResult,
    synthetic_local: tuple[Mapping[str, Any], ...],
    authentic_local: tuple[Mapping[str, Any], ...],
    registry_local: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    for relative in LOCAL_SUBDIRECTORIES:
        (LOCAL_ROOT / relative).mkdir(parents=True, exist_ok=True)
    paths = (
        (
            LOCAL_ROOT / "fixture_runs/controlled_fixture_results_v1.json",
            lambda path: write_json(path, list(controlled.local_rows)),
        ),
        (
            LOCAL_ROOT / "condition_predictions/synthetic_conditions_v1.jsonl",
            lambda path: write_jsonl(path, synthetic_local),
        ),
        (
            LOCAL_ROOT / "condition_predictions/authentic_conditions_v1.jsonl",
            lambda path: write_jsonl(path, authentic_local),
        ),
        (
            LOCAL_ROOT / "condition_predictions/context_missing_conditions_v1.jsonl",
            lambda path: write_jsonl(path, registry_local),
        ),
    )
    for path, writer in paths:
        writer(path)
    members = [
        {
            "relative_path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path, _writer in paths
    ]
    return {
        "artifact_count": len(members),
        "members": members,
        "ignored": True,
        "tracked": False,
        "contains_track_a": False,
        "contains_track_b": False,
    }


def _store_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    store = {
        "schema_version": "offline-memory-store-contract-v1",
        "store_id": "OfflinePersistentMemoryStoreV1",
        "scope": "SINGLE_PROCESS_FIXTURE_ONLY_LOCAL_ONLY",
        "durable_database_claim": False,
        "encrypted_disk_store_implemented": False,
        "immutable_validated_bundles": True,
        "append_only_events": ["WRITE", "SUPERSEDE", "COMPLETE", "CANCEL", "DELETE"],
        "derived_projection": True,
        "tombstone_registry": True,
        "monotonic_revision": True,
        "unique_identifiers": [
            "memory_id",
            "episode_id",
            "payload_id",
            "store_event_id",
        ],
        "payload_text_tracked": False,
        "production_namespace": False,
    }
    transaction = {
        "schema_version": "store-snapshot-and-transaction-contract-v1",
        "snapshot_schema": "StoreSnapshotV1",
        "execution_context_schema": "ValidatedMemoryExecutionContextV1",
        "bound_fields": [
            "validated_plan_fingerprint",
            "validated_bundle_fingerprint",
            "snapshot_fingerprint",
            "store_revision",
            "condition_id",
            "request_fingerprint",
        ],
        "stale_revision_failure": "STALE_STORE_SNAPSHOT",
        "cross_query_reuse": False,
        "cross_scope_reuse": False,
        "cross_revision_reuse": False,
        "cross_condition_reuse": False,
        "restart_from_candidate_generation_after_revision_change": True,
    }
    return store, transaction


def run_rq2c1() -> RQ2C1RunResult:
    starting = verify_starting_state()
    gold = load_and_validate_gold(ROOT)
    fixtures = load_controlled_fixtures()
    encoder = local_encoder_preflight()
    controlled = run_controlled_evaluation(fixtures)
    p1_synthetic = load_p1_ledger(SYNTHETIC_LEDGER)
    session_cases = _session_cases(gold, p1_synthetic)
    oof = nested_leave_one_family_out(session_cases)
    final = select_session_policy(session_cases)
    final_policy = {
        "schema_version": "rq2c1-final-session-policy-v1",
        "selected_policy_id": final["selected_policy_id"],
        "candidate_results": final["candidate_results"],
        "selection_dataset": "SYNTHETIC_COVERAGE_STRESS_GOLD",
        "selection_record_count": len(session_cases),
        "scenario_family_count": 18,
        "selection_rule_frozen": True,
        "authentic_used_for_selection": False,
        "context_missing_used_for_selection": False,
        "immutable": True,
    }
    synthetic, synthetic_local = run_conditions(
        examples=gold.synthetic_gold,
        p1_rows=p1_synthetic,
        session_policy_id=str(final_policy["selected_policy_id"]),
        dataset_role="SYNTHETIC_COVERAGE_STRESS_GOLD",
    )
    synthetic.update(
        {
            "schema_version": "rq2c1-synthetic-session-results-v1",
            "nested_oof_reported_separately": True,
            "policy_development_role": True,
        }
    )
    # Authentic and registry execution starts only after final_policy exists and
    # carries immutable=true.
    authentic, authentic_local = evaluate_authentic_after_freeze(
        examples=gold.authentic_gold, session_policy_manifest=final_policy
    )
    registry, registry_local = evaluate_context_missing_after_freeze(
        examples=gold.authentic_context_missing_registry,
        session_policy_manifest=final_policy,
    )
    error = build_error_analysis(
        controlled=controlled.persistent_policy_results,
        oof=oof,
        synthetic=synthetic,
        authentic=authentic,
    )
    local_manifest = _local_artifacts(
        controlled=controlled,
        synthetic_local=synthetic_local,
        authentic_local=authentic_local,
        registry_local=registry_local,
    )
    store_contract, transaction_contract = _store_contracts()
    runtime = {
        "schema_version": "rq2c1-runtime-preflight-v1",
        "status": "PASS",
        "encoder": encoder,
        "fixture_access_audit": expected_field_access_audit(),
        "gold_identity_status": gold.identity,
        "local_inputs": {
            name: {"sha256": digest, "record_count": count}
            for name, (_path, digest, count) in GOLD_INPUTS.items()
        },
        "p1_local_ledgers": {
            name: {"sha256": digest} for name, (_path, digest) in LOCAL_LEDGER_INPUTS.items()
        },
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_a_access_count": 0,
        "track_b_access_count": 0,
        "local_artifact_manifest": local_manifest,
    }
    return RQ2C1RunResult(
        starting_preflight=starting,
        runtime_preflight=runtime,
        store_contract=store_contract,
        transaction_contract=transaction_contract,
        controlled=controlled,
        session_oof=oof,
        final_session_policy=final_policy,
        synthetic_results=synthetic,
        authentic_results=authentic,
        context_missing_results=registry,
        error_analysis=error,
        local_artifact_manifest=local_manifest,
    )


def main() -> int:
    from .finalise_rq2c1 import finalise_rq2c1

    result = run_rq2c1()
    finalise_rq2c1(result)
    print(
        json.dumps(
            {
                "status": "RQ2_C1_OFFLINE_EXECUTION_COMPLETE",
                "final_session_policy": result.final_session_policy[
                    "selected_policy_id"
                ],
                "hard_safety": result.controlled.hard_safety["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
