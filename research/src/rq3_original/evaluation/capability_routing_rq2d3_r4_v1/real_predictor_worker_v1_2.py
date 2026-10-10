"""Fixed-authority real B0/B1/P1 predictor for future D4."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from . import METHODS, RECORD_COUNT, canonical_json_bytes, canonical_jsonl_bytes, sha256_file
from .atomic_execution_state_v1_2 import (
    fail_execution_state_v1_2,
    read_execution_state_v1_2,
    transition_execution_state_v1_2,
)
from .durable_no_replace_artifact_v1_2 import (
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)
from .fixed_real_worker_authority_v1_2 import (
    PREDICTOR_ROLE,
    claim_fixed_real_worker_authority_v1_2,
    mark_fixed_real_worker_consumed_success_v1_2,
)


def _read_all_nofollow(path: Path) -> bytes:
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise RuntimeError("predictor artifact metadata mismatch")
    size = before.st_size
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise RuntimeError("predictor artifact inode mismatch")
        value = os.read(descriptor, size + 1)
    finally:
        os.close(descriptor)
    if len(value) != size:
        raise RuntimeError("predictor artifact read mismatch")
    return value


def _jsonl(value: bytes, expected: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if len(rows) != expected or not value.endswith(b"\n"):
        raise RuntimeError("predictor JSONL mismatch")
    return rows


def _prediction_validator(
    method: str, features: Sequence[Mapping[str, Any]]
):
    def validate(value: bytes) -> None:
        from evaluation.capability_routing_rq2d3_r3_v1.bound_prediction_v1_1 import (
            validate_bound_prediction_v1_1,
        )

        rows = _jsonl(value, RECORD_COUNT)
        feature_by_id = {row["review_case_id"]: row for row in features}
        if any(
            row.get("method_id") != method
            or row.get("review_case_id") not in feature_by_id
            for row in rows
        ):
            raise RuntimeError("prediction identity mismatch")
        for row in rows:
            validate_bound_prediction_v1_1(row, feature_by_id[row["review_case_id"]])

    return validate


def run_real_predictor_worker_v1_2(*, credential_fd: int) -> None:
    context = claim_fixed_real_worker_authority_v1_2(
        PREDICTOR_ROLE, credential_fd=credential_fd
    )
    paths = context.paths
    code_identity = sha256_file(Path(__file__))
    counts = {
        "feature_view_open_count": 0,
        "feature_view_read_count": 0,
        "combined_source_open_count": 0,
        "label_gold_open_count": 0,
        "grouping_open_count": 0,
    }
    stage_receipts: list[dict[str, Any]] = []
    firewall = None
    try:
        from evaluation.capability_routing_rq2d3_r3_v1.worker_runtime_firewall import (
            RuntimeFirewall,
        )

        firewall = RuntimeFirewall(
            role=PREDICTOR_ROLE,
            forbidden_paths={
                "COMBINED_SOURCE": paths.combined_source,
                "LABEL_ONLY_GOLD": paths.label_gold,
                "GROUPING_LEDGER": paths.grouping,
                "D1_MAPPING": paths.repository_root / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_opaque_mapping_v1.jsonl",
                "D1_CASE_BANK": paths.repository_root / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_canonical_case_bank_v1.jsonl",
                "HIDDEN_LEGACY": paths.repository_root / "evaluation/capability_routing_rq2d2b_v1/local_hidden_legacy/hidden_legacy_v1.jsonl",
            },
            forbidden_import_prefixes=(
                "evaluation.capability_routing_rq2d3_r1_v1",
                "evaluation.capability_routing_rq2d3_r4_v1.real_metric_worker_v1_2",
            ),
        ).install()
        from evaluation.capability_routing_rq2d3_r3_v1.feature_fingerprint_v1_1 import (
            validate_feature_row_v1_1,
        )
        from evaluation.capability_routing_rq2d3_r3_v1.bound_prediction_v1_1 import (
            bind_prediction_v1_1,
        )

        features = _jsonl(_read_all_nofollow(paths.feature_view), RECORD_COUNT)
        counts.update(feature_view_open_count=1, feature_view_read_count=1)
        for row in features:
            validate_feature_row_v1_1(row)
        from evaluation.capability_routing_rq2d3_r3_v1.frozen_capability_predictor_core_v1_1 import (
            CoreRoutingContentV1_1,
            FrozenCapabilityPredictorCoreV1_1,
        )

        core = FrozenCapabilityPredictorCoreV1_1()
        try:
            predictions = {
                method: [
                    bind_prediction_v1_1(
                        feature,
                        method,
                        core.predict(
                            method,
                            CoreRoutingContentV1_1(
                                current_query=str(feature["current_query"]),
                                current_page=str(feature["current_page"]),
                                necessary_conversation_history=tuple(
                                    dict(item)
                                    for item in feature["necessary_conversation_history"]
                                ),
                            ),
                        ),
                    )
                    for feature in features
                ]
                for method in METHODS
            }
        finally:
            core.close()
        targets = {
            "B0": paths.b0_predictions,
            "B1": paths.b1_predictions,
            "P1": paths.p1_predictions,
        }
        stages = {
            "B0": ("B0_PREDICTIONS_PERSISTED", "FEATURE_FIREWALL_VERIFIED"),
            "B1": ("B1_PREDICTIONS_PERSISTED", "B0_PREDICTIONS_PERSISTED"),
            "P1": ("P1_PREDICTIONS_PERSISTED", "B1_PREDICTIONS_PERSISTED"),
        }
        prediction_receipts: dict[str, dict[str, Any]] = {}
        for method in METHODS:
            stage, parent_state = stages[method]
            receipt = publish_no_replace_artifact_v1_2(
                targets[method],
                canonical_jsonl_bytes(predictions[method]),
                relative_path=str(targets[method].relative_to(paths.repository_root)),
                stage=stage,
                worker_role=PREDICTOR_ROLE,
                worker_credential_commitment=context.credential_commitment,
                artifact_role=f"{method}_BOUND_PREDICTIONS",
                schema_id="track-b-bound-prediction-jsonl-v1-2",
                record_count=RECORD_COUNT,
                approved_head=context.descriptor.approved_head,
                execution_id=context.descriptor.execution_id,
                effective_contract_id=context.descriptor.effective_contract_id,
                code_identity=code_identity,
                parent_state=parent_state,
                open_read_counts=counts,
                firewall_summary=firewall.report(),
                schema_validator=_prediction_validator(method, features),
            )
            prediction_receipts[method] = receipt
            stage_receipts.append(receipt)
            transition_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                stage,
                stage_receipts=[receipt],
                evidence_summary={"method": method, "prediction_count": RECORD_COUNT},
            )
        firewall_report = {
            "schema_version": "track-b-prediction-firewall-report-v1-2",
            "status": "PASS",
            "prediction_count": RECORD_COUNT * len(METHODS),
            "prediction_count_by_method": {method: len(predictions[method]) for method in METHODS},
            "feature_view_open_read": "1/1",
            "runtime_firewall_summary": firewall.report(),
            "review_case_id_used_by_core": False,
        }
        firewall_receipt = publish_no_replace_artifact_v1_2(
            paths.prediction_firewall_report,
            canonical_json_bytes(firewall_report),
            relative_path=str(paths.prediction_firewall_report.relative_to(paths.repository_root)),
            stage="PREDICTION_FIREWALL_VERIFIED",
            worker_role=PREDICTOR_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="PREDICTION_FIREWALL_REPORT",
            schema_id="track-b-prediction-firewall-report-v1-2",
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="P1_PREDICTIONS_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-prediction-firewall-report-v1-2"),
        )
        predictor_report = {
            "schema_version": "track-b-predictor-process-report-v1-2",
            "status": "PASS",
            "worker_role": PREDICTOR_ROLE,
            "prediction_receipts": prediction_receipts,
            "runtime_firewall_summary": firewall.report(),
            "open_read_counts": counts,
        }
        predictor_receipt = publish_no_replace_artifact_v1_2(
            paths.predictor_report,
            canonical_json_bytes(predictor_report),
            relative_path=str(paths.predictor_report.relative_to(paths.repository_root)),
            stage="PREDICTION_FIREWALL_VERIFIED",
            worker_role=PREDICTOR_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="PREDICTOR_PROCESS_REPORT",
            schema_id="track-b-predictor-process-report-v1-2",
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="P1_PREDICTIONS_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-predictor-process-report-v1-2"),
        )
        stage_receipts.extend((firewall_receipt, predictor_receipt))
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "PREDICTION_FIREWALL_VERIFIED",
            stage_receipts=[firewall_receipt, predictor_receipt],
            evidence_summary={"firewall_verified": True},
        )
        from evaluation.capability_routing_rq2d3_r3_v1.p2_secondary_scope_decision import (
            p2_secondary_scope_document_v1_1,
        )

        p2_document = p2_secondary_scope_document_v1_1()
        p2_receipt = publish_no_replace_artifact_v1_2(
            paths.p2_scope_metadata,
            canonical_json_bytes(p2_document),
            relative_path=str(paths.p2_scope_metadata.relative_to(paths.repository_root)),
            stage="SECONDARY_SCOPE_METADATA_PERSISTED",
            worker_role=PREDICTOR_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="P2_SECONDARY_SCOPE_METADATA",
            schema_id=str(p2_document["schema_version"]),
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PREDICTION_FIREWALL_VERIFIED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator(str(p2_document["schema_version"])),
        )
        stage_receipts.append(p2_receipt)
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "SECONDARY_SCOPE_METADATA_PERSISTED",
            stage_receipts=[p2_receipt],
            evidence_summary={"p2_status": "DEFERRED_NOT_EXECUTED"},
        )
        mark_fixed_real_worker_consumed_success_v1_2(
            context,
            stage_receipts=stage_receipts,
            open_read_counts=counts,
            firewall_summary=firewall.report(),
        )
    except BaseException as error:
        try:
            fail_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                failure_code=type(error).__name__,
                failure_stage="PREDICTOR",
                failure_receipt={"artifact_role": "ROOT_FAILURE_RECEIPT"},
            )
        finally:
            raise


def main() -> int:
    raise SystemExit("BLOCKED_RQ2_D4_WORKER_AUTHORITY: inherited pipe required")


if __name__ == "__main__":
    raise SystemExit(main())
