"""Credential-gated B0/B1/P1 predictor with an enforced runtime firewall."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import METHODS, ROOT, canonical_json_bytes, canonical_jsonl_bytes, sha256_file
from .durable_local_artifact import json_object_validator, publish_durable_artifact_v1_1
from .fixed_rq2d4_paths_v1_1 import D4PathsV1_1
from .global_lock_receipt_v1_1 import (
    append_transition_v1_1,
    fail_global_lock_v1_1,
    mark_worker_consumed_v1_1,
    read_global_lock_v1_1,
)
from .p2_secondary_scope_decision import p2_secondary_scope_document_v1_1
from .stage_receipt_v1_1 import build_stage_receipt_v1_1, persist_stage_receipt_v1_1
from .worker_execution_authority_v1_1 import (
    PREDICTOR_ROLE,
    WorkerDescriptorV1_1,
    claim_worker_credential_v1_1,
)
from .worker_runtime_firewall import RuntimeFirewall


def _read_all(path: Path) -> bytes:
    size = os.lstat(path).st_size
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        value = os.read(descriptor, size + 1)
    finally:
        os.close(descriptor)
    if len(value) != size:
        raise RuntimeError("predictor feature read mismatch")
    return value


def _jsonl(value: bytes, expected: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if len(rows) != expected or not value.endswith(b"\n"):
        raise RuntimeError("predictor JSONL mismatch")
    return rows


def _prediction_validator(
    *, method: str, features: Sequence[Mapping[str, Any]], expected_count: int
):
    def validate(value: bytes) -> None:
        from .bound_prediction_v1_1 import validate_prediction_set_v1_1

        rows = _jsonl(value, expected_count)
        expanded = []
        for candidate in METHODS:
            if candidate == method:
                expanded.extend(rows)
            else:
                for feature in features:
                    placeholder = dict(rows[0])
                    placeholder.update(
                        {
                            "review_case_id": feature["review_case_id"],
                            "feature_content_fingerprint": feature["feature_content_fingerprint"],
                            "feature_record_fingerprint": feature["feature_record_fingerprint"],
                            "method_id": candidate,
                        }
                    )
                    from .bound_prediction_v1_1 import bound_prediction_hash_v1_1

                    placeholder["bound_prediction_hash"] = bound_prediction_hash_v1_1(placeholder)
                    expanded.append(placeholder)
        validate_prediction_set_v1_1(expanded, features)

    return validate


def run_predictor_worker_v1_1(
    *,
    paths: D4PathsV1_1,
    descriptor_fd: int,
    worker_descriptor: WorkerDescriptorV1_1,
    expected_feature_count: int,
) -> None:
    raise RuntimeError("SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY")

    commitment = claim_worker_credential_v1_1(
        paths.global_lock, descriptor_fd=descriptor_fd, descriptor=worker_descriptor
    )
    lock = read_global_lock_v1_1(paths.global_lock)
    code_identity = sha256_file(Path(__file__))
    firewall = RuntimeFirewall(
        role=PREDICTOR_ROLE,
        forbidden_paths={
            "COMBINED_SOURCE": paths.combined_source,
            "LABEL_ONLY_GOLD": paths.label_gold,
            "GROUPING_LEDGER": paths.grouping,
            "D1_MAPPING": ROOT
            / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_opaque_mapping_v1.jsonl",
            "D1_CASE_BANK": ROOT
            / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_canonical_case_bank_v1.jsonl",
            "HIDDEN_LEGACY": ROOT
            / "evaluation/capability_routing_rq2d2b_v1/local_hidden_legacy/hidden_legacy_v1.jsonl",
        },
        forbidden_import_prefixes=(
            "evaluation.capability_routing_rq2d3_r1_v1",
            "evaluation.capability_routing_rq2d3_r3_v1.track_b_metric_worker_v1_1",
            "evaluation.capability_routing_rq2d3_r3_v1.frozen_complete_metric_binding_v1_1",
        ),
    ).install()
    stage_identities: list[dict[str, Any]] = []
    process_report_receipt: dict[str, Any] = {}
    counts = {
        "feature_view_open_count": 0,
        "feature_view_read_count": 0,
        "combined_source_open_count": 0,
        "label_gold_open_count": 0,
        "grouping_open_count": 0,
    }
    try:
        from .bound_prediction_v1_1 import bind_prediction_v1_1
        from .feature_fingerprint_v1_1 import validate_feature_row_v1_1

        features = _jsonl(_read_all(paths.feature_view), expected_feature_count)
        counts["feature_view_open_count"] = 1
        counts["feature_view_read_count"] = 1
        for row in features:
            validate_feature_row_v1_1(row)
        if lock.get("synthetic"):
            from .synthetic_d4_integrity_fixture import synthetic_core_prediction_v1_1

            core = None
            predict = synthetic_core_prediction_v1_1
        else:
            from .frozen_capability_predictor_core_v1_1 import (
                CoreRoutingContentV1_1,
                FrozenCapabilityPredictorCoreV1_1,
            )

            core = FrozenCapabilityPredictorCoreV1_1()

            def predict(method: str, feature: Mapping[str, Any]) -> dict[str, Any]:
                return core.predict(
                    method,
                    CoreRoutingContentV1_1(
                        current_query=str(feature["current_query"]),
                        current_page=str(feature["current_page"]),
                        necessary_conversation_history=tuple(
                            dict(item) for item in feature["necessary_conversation_history"]
                        ),
                    ),
                )

        try:
            predictions: dict[str, list[dict[str, Any]]] = {
                method: [
                    bind_prediction_v1_1(feature, method, predict(method, feature))
                    for feature in features
                ]
                for method in METHODS
            }
        finally:
            if core is not None:
                core.close()
        targets = {
            "B0": paths.b0_predictions,
            "B1": paths.b1_predictions,
            "P1": paths.p1_predictions,
        }
        states = {
            "B0": ("B0_PREDICTIONS_PERSISTED", "FEATURE_FIREWALL_VERIFIED"),
            "B1": ("B1_PREDICTIONS_PERSISTED", "B0_PREDICTIONS_PERSISTED"),
            "P1": ("P1_PREDICTIONS_PERSISTED", "B1_PREDICTIONS_PERSISTED"),
        }
        prediction_receipts: dict[str, dict[str, Any]] = {}
        for method in METHODS:
            stage, parent_state = states[method]
            receipt = publish_durable_artifact_v1_1(
                targets[method],
                canonical_jsonl_bytes(predictions[method]),
                stage=stage,
                worker_role=PREDICTOR_ROLE,
                artifact_role=f"{method}_BOUND_PREDICTIONS",
                schema_id="track-b-bound-prediction-v1-1",
                record_count=expected_feature_count,
                approved_head=worker_descriptor.approved_head,
                execution_id=worker_descriptor.execution_id,
                effective_contract_id=worker_descriptor.effective_contract_id,
                code_identity=code_identity,
                parent_state=parent_state,
                schema_validator=_prediction_validator(
                    method=method, features=features, expected_count=expected_feature_count
                ),
            )
            prediction_receipts[method] = receipt
            stage_document = build_stage_receipt_v1_1(
                stage=stage,
                worker_role=PREDICTOR_ROLE,
                approved_head=worker_descriptor.approved_head,
                execution_id=worker_descriptor.execution_id,
                effective_contract_id=worker_descriptor.effective_contract_id,
                code_identity=code_identity,
                parent_state=parent_state,
                artifact_receipts=[receipt],
                open_read_counts=counts,
                runtime_firewall_summary=firewall.report(),
            )
            _, identity = persist_stage_receipt_v1_1(
                paths.receipts_root / f"{method.lower()}_predictions_receipt_v1_1.json",
                stage_document,
            )
            stage_identities.append(identity)
            append_transition_v1_1(
                paths.global_lock,
                new_state=stage,
                worker_role=PREDICTOR_ROLE,
                credential_commitment=commitment,
                stage_receipt_identities=[identity],
                open_read_counts=counts,
            )
        firewall_report = {
            "schema_version": "track-b-prediction-firewall-report-v1-1",
            "status": "PASS",
            "prediction_count": expected_feature_count * 3,
            "prediction_count_by_method": {
                method: len(predictions[method]) for method in METHODS
            },
            "feature_view_open_read": "1/1",
            "runtime_firewall_summary": firewall.report(),
            "review_case_id_used_by_core": False,
        }
        firewall_receipt = publish_durable_artifact_v1_1(
            paths.prediction_firewall_report,
            canonical_json_bytes(firewall_report),
            stage="PREDICTION_FIREWALL_VERIFIED",
            worker_role=PREDICTOR_ROLE,
            artifact_role="PREDICTION_FIREWALL_REPORT",
            schema_id="track-b-prediction-firewall-report-v1-1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="P1_PREDICTIONS_PERSISTED",
            schema_validator=json_object_validator("track-b-prediction-firewall-report-v1-1"),
        )
        process_report = {
            "schema_version": "track-b-predictor-process-report-v1-1",
            "status": "PASS",
            "worker_role": PREDICTOR_ROLE,
            "prediction_receipts": prediction_receipts,
            "runtime_firewall_summary": firewall.report(),
            "open_read_counts": counts,
        }
        process_report_receipt = publish_durable_artifact_v1_1(
            paths.predictor_report,
            canonical_json_bytes(process_report),
            stage="PREDICTION_FIREWALL_VERIFIED",
            worker_role=PREDICTOR_ROLE,
            artifact_role="PREDICTOR_PROCESS_REPORT",
            schema_id="track-b-predictor-process-report-v1-1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="P1_PREDICTIONS_PERSISTED",
            schema_validator=json_object_validator("track-b-predictor-process-report-v1-1"),
        )
        firewall_stage = build_stage_receipt_v1_1(
            stage="PREDICTION_FIREWALL_VERIFIED",
            worker_role=PREDICTOR_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="P1_PREDICTIONS_PERSISTED",
            artifact_receipts=[firewall_receipt, process_report_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, firewall_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "prediction_firewall_receipt_v1_1.json",
            firewall_stage,
        )
        stage_identities.append(firewall_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="PREDICTION_FIREWALL_VERIFIED",
            worker_role=PREDICTOR_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[firewall_identity],
            open_read_counts=counts,
        )
        p2_document = p2_secondary_scope_document_v1_1()
        p2_receipt = publish_durable_artifact_v1_1(
            paths.p2_scope_metadata,
            canonical_json_bytes(p2_document),
            stage="SECONDARY_SCOPE_METADATA_PERSISTED",
            worker_role=PREDICTOR_ROLE,
            artifact_role="P2_SECONDARY_SCOPE_METADATA",
            schema_id="track-b-p2-secondary-scope-decision-v1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PREDICTION_FIREWALL_VERIFIED",
            schema_validator=json_object_validator("track-b-p2-secondary-scope-decision-v1"),
        )
        p2_stage = build_stage_receipt_v1_1(
            stage="SECONDARY_SCOPE_METADATA_PERSISTED",
            worker_role=PREDICTOR_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PREDICTION_FIREWALL_VERIFIED",
            artifact_receipts=[p2_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, p2_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "secondary_scope_metadata_receipt_v1_1.json", p2_stage
        )
        stage_identities.append(p2_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="SECONDARY_SCOPE_METADATA_PERSISTED",
            worker_role=PREDICTOR_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[p2_identity],
            open_read_counts=counts,
        )
        mark_worker_consumed_v1_1(
            paths.global_lock,
            role=PREDICTOR_ROLE,
            commitment=commitment,
            stage_receipt_identities=stage_identities,
            process_report_receipt=process_report_receipt,
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
    except BaseException as error:
        try:
            fail_global_lock_v1_1(paths.global_lock, reason=type(error).__name__, worker_role=PREDICTOR_ROLE)
        finally:
            raise


def main() -> int:
    raise SystemExit("BLOCKED_RQ2_D4_WORKER_AUTHORITY: parent pipe required")


if __name__ == "__main__":
    raise SystemExit(main())
