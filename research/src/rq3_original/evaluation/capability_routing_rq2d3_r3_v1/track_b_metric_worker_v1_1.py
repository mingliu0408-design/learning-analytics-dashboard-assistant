"""Credential-gated complete metric and fixed-statistical D4 worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from . import CAPABILITIES, COMPARISONS, METHODS, ROOT, canonical_json_bytes, canonical_jsonl_bytes, sha256_bytes, sha256_file
from .durable_local_artifact import json_object_validator, publish_durable_artifact_v1_1
from .fixed_rq2d4_paths_v1_1 import D4PathsV1_1
from .global_lock_receipt_v1_1 import (
    append_transition_v1_1,
    fail_global_lock_v1_1,
    mark_worker_consumed_v1_1,
    read_global_lock_v1_1,
)
from .stage_receipt_v1_1 import build_stage_receipt_v1_1, persist_stage_receipt_v1_1
from .worker_execution_authority_v1_1 import (
    FEATURE_ROLE,
    METRIC_ROLE,
    PREDICTOR_ROLE,
    WorkerDescriptorV1_1,
    claim_worker_credential_v1_1,
)
from .worker_runtime_firewall import RuntimeFirewall


def _read_once(path: Path, *, expected_sha256: str, expected_size: int) -> bytes:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or observed.st_size != expected_size
    ):
        raise RuntimeError("metric input size mismatch")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        value = os.read(descriptor, expected_size + 1)
    finally:
        os.close(descriptor)
    if len(value) != expected_size or sha256_bytes(value) != expected_sha256:
        raise RuntimeError("metric input identity mismatch")
    return value


def _read_all(path: Path) -> bytes:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o600
    ):
        raise RuntimeError("metric local artifact metadata mismatch")
    size = observed.st_size
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        value = os.read(descriptor, size + 1)
    finally:
        os.close(descriptor)
    if len(value) != size:
        raise RuntimeError("metric artifact read mismatch")
    return value


def _read_receipted_artifact(
    *,
    lock: Mapping[str, Any],
    paths: D4PathsV1_1,
    worker_role: str,
    artifact_role: str,
    target: Path,
) -> tuple[bytes, int]:
    entry = lock.get("worker_roles", {}).get(worker_role)
    if not entry or entry.get("status") != "CONSUMED":
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    receipt_open_count = 0
    matches: list[Mapping[str, Any]] = []
    for identity in entry.get("stage_receipt_identities", []):
        receipt_path = paths.receipts_root / str(identity.get("relative_path"))
        receipt_value = _read_all(receipt_path)
        receipt_open_count += 1
        if (
            sha256_bytes(receipt_value) != identity.get("sha256")
            or len(receipt_value) != identity.get("size_bytes")
        ):
            raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
        receipt = json.loads(receipt_value)
        if receipt.get("schema_version") != "track-b-stage-receipt-v1-1":
            raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
        matches.extend(
            artifact
            for artifact in receipt.get("artifact_receipts", [])
            if artifact.get("artifact_role") == artifact_role
        )
    if len(matches) != 1:
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    artifact = matches[0]
    if artifact.get("relative_path") != target.name or artifact.get("file_mode") != "0600":
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    value = _read_all(target)
    if sha256_bytes(value) != artifact.get("sha256") or len(value) != artifact.get("size_bytes"):
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return value, receipt_open_count


def _jsonl(value: bytes, expected: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if len(rows) != expected or not value.endswith(b"\n"):
        raise RuntimeError("metric JSONL mismatch")
    return rows


def _per_case_metric_validator(expected: int):
    def validate(value: bytes) -> None:
        rows = _jsonl(value, expected)
        if any(
            set(row) != {"review_case_id", "method_id", "exact_set_match", "set_jaccard"}
            for row in rows
        ):
            raise RuntimeError("per-case metric ledger schema mismatch")

    return validate


def _yes(value: Any) -> bool:
    if value in {True, "YES"}:
        return True
    if value in {False, "NO"}:
        return False
    raise ValueError("invalid frozen label value")


def _method_rows(
    predictions: Sequence[Mapping[str, Any]], labels: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result = []
    for prediction in predictions:
        case_id = str(prediction["review_case_id"])
        label = labels[case_id]
        result.append(
            {
                "review_case_id": case_id,
                "gold_capabilities": [name for name in CAPABILITIES if _yes(label[name])],
                "predicted_capabilities": list(prediction["predicted_capabilities"]),
                "forbidden_capabilities": list(label.get("forbidden_capabilities") or ()),
                "gold_context_resolution_required": _yes(label["context_resolution_required"]),
                "predicted_context_resolution_required": bool(
                    prediction["context_resolution_required_prediction"]
                ),
            }
        )
    return result


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def run_metric_worker_v1_1(
    *,
    paths: D4PathsV1_1,
    descriptor_fd: int,
    worker_descriptor: WorkerDescriptorV1_1,
    expected_label_sha256: str,
    expected_label_size: int,
    expected_grouping_sha256: str,
    expected_grouping_size: int,
    expected_record_count: int,
    expected_group_count: int,
) -> None:
    raise RuntimeError("SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY")

    commitment = claim_worker_credential_v1_1(
        paths.global_lock, descriptor_fd=descriptor_fd, descriptor=worker_descriptor
    )
    lock = read_global_lock_v1_1(paths.global_lock)
    code_identity = sha256_file(Path(__file__))
    firewall = RuntimeFirewall(
        role=METRIC_ROLE,
        forbidden_paths={
            "COMBINED_SOURCE": paths.combined_source,
            "D1_MAPPING": ROOT
            / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_opaque_mapping_v1.jsonl",
            "D1_CASE_BANK": ROOT
            / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_canonical_case_bank_v1.jsonl",
            "HIDDEN_LEGACY": ROOT
            / "evaluation/capability_routing_rq2d2b_v1/local_hidden_legacy/hidden_legacy_v1.jsonl",
        },
        forbidden_import_prefixes=(
            "evaluation.capability_routing_rq2d3_r3_v1.frozen_capability_predictor_core_v1_1",
            "evaluation.capability_routing_rq2b_v1.p1_capability_router",
            "evaluation.capability_routing_rq2b_v1.b0_original_query_adapter",
            "utils.production_intent_router",
            "semantic_runtime.runtime",
        ),
    ).install()
    stage_identities: list[dict[str, Any]] = []
    process_report_receipt: dict[str, Any] = {}
    counts = {
        "combined_source_open_count": 0,
        "label_gold_open_count": 0,
        "label_gold_read_count": 0,
        "grouping_open_count": 0,
        "grouping_read_count": 0,
        "feature_view_open_count": 0,
        "prediction_ledger_open_count": 0,
        "stage_receipt_open_count": 0,
    }
    try:
        from .bound_prediction_v1_1 import validate_prediction_set_v1_1
        from .feature_fingerprint_v1_1 import validate_feature_row_v1_1
        from .frozen_complete_metric_binding_v1_1 import (
            load_frozen_complete_track_b_metric_binding_v1_1,
        )
        from .fixed_statistical_execution_v1_1 import (
            run_fixed_synthetic_statistics_v1_1,
            run_fixed_track_b_statistics_v1_1,
        )

        feature_value, feature_receipt_opens = _read_receipted_artifact(
            lock=lock,
            paths=paths,
            worker_role=FEATURE_ROLE,
            artifact_role="FEATURE_ONLY_VIEW",
            target=paths.feature_view,
        )
        features = _jsonl(feature_value, expected_record_count)
        counts["feature_view_open_count"] = 1
        counts["stage_receipt_open_count"] += feature_receipt_opens
        for feature in features:
            validate_feature_row_v1_1(feature)
        prediction_paths = {
            "B0": paths.b0_predictions,
            "B1": paths.b1_predictions,
            "P1": paths.p1_predictions,
        }
        predictions = {}
        for method, path in prediction_paths.items():
            prediction_value, prediction_receipt_opens = _read_receipted_artifact(
                lock=lock,
                paths=paths,
                worker_role=PREDICTOR_ROLE,
                artifact_role=f"{method}_BOUND_PREDICTIONS",
                target=path,
            )
            counts["stage_receipt_open_count"] += prediction_receipt_opens
            predictions[method] = _jsonl(prediction_value, expected_record_count)
        counts["prediction_ledger_open_count"] = 3
        validate_prediction_set_v1_1(
            [row for method in METHODS for row in predictions[method]], features
        )
        label_value = _read_once(
            paths.label_gold,
            expected_sha256=expected_label_sha256,
            expected_size=expected_label_size,
        )
        counts["label_gold_open_count"] = 1
        counts["label_gold_read_count"] = 1
        label_rows = _jsonl(label_value, expected_record_count)
        label_by_id = {str(row["review_case_id"]): row for row in label_rows}
        if len(label_by_id) != expected_record_count:
            raise RuntimeError("duplicate metric label identity")
        append_transition_v1_1(
            paths.global_lock,
            new_state="LABEL_GOLD_OPENED",
            worker_role=METRIC_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[
                {
                    "artifact_role": "LABEL_GOLD_OBSERVED",
                    "sha256": expected_label_sha256,
                    "size_bytes": expected_label_size,
                    "record_count": expected_record_count,
                }
            ],
            open_read_counts=counts,
        )
        grouping_value = _read_once(
            paths.grouping,
            expected_sha256=expected_grouping_sha256,
            expected_size=expected_grouping_size,
        )
        counts["grouping_open_count"] = 1
        counts["grouping_read_count"] = 1
        grouping_rows = _jsonl(grouping_value, expected_record_count)
        by_group: dict[str, list[str]] = {}
        for row in grouping_rows:
            by_group.setdefault(str(row["contrast_group_id"]), []).append(
                str(row["review_case_id"])
            )
        if len(by_group) != expected_group_count or set(map(len, by_group.values())) != {2}:
            raise RuntimeError("metric grouping shape mismatch")
        append_transition_v1_1(
            paths.global_lock,
            new_state="GROUPING_OPENED",
            worker_role=METRIC_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[
                {
                    "artifact_role": "GROUPING_LEDGER_OBSERVED",
                    "sha256": expected_grouping_sha256,
                    "size_bytes": expected_grouping_size,
                    "record_count": expected_record_count,
                    "group_count": expected_group_count,
                }
            ],
            open_read_counts=counts,
        )
        binding = load_frozen_complete_track_b_metric_binding_v1_1()
        metric_rows = {
            method: _method_rows(predictions[method], label_by_id) for method in METHODS
        }
        method_metrics = {
            method: binding.evaluate(metric_rows[method]) for method in METHODS
        }
        per_case_rows = [
            {
                "review_case_id": row["review_case_id"],
                "method_id": method,
                "exact_set_match": set(row["gold_capabilities"])
                == set(row["predicted_capabilities"]),
                "set_jaccard": _jaccard(
                    set(row["gold_capabilities"]), set(row["predicted_capabilities"])
                ),
            }
            for method in METHODS
            for row in metric_rows[method]
        ]
        per_case_receipt = publish_durable_artifact_v1_1(
            paths.per_case_metric_ledger,
            canonical_jsonl_bytes(per_case_rows),
            stage="METHOD_METRICS_PERSISTED",
            worker_role=METRIC_ROLE,
            artifact_role="PER_CASE_METRIC_LEDGER",
            schema_id="track-b-per-case-metric-ledger-v1-1",
            record_count=len(per_case_rows),
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="GROUPING_OPENED",
            schema_validator=_per_case_metric_validator(len(per_case_rows)),
        )
        method_document = {
            "schema_version": "track-b-method-level-metrics-v1-1",
            "method_metrics": method_metrics,
        }
        method_receipt = publish_durable_artifact_v1_1(
            paths.method_metrics,
            canonical_json_bytes(method_document),
            stage="METHOD_METRICS_PERSISTED",
            worker_role=METRIC_ROLE,
            artifact_role="METHOD_LEVEL_METRICS",
            schema_id="track-b-method-level-metrics-v1-1",
            record_count=3,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="GROUPING_OPENED",
            schema_validator=json_object_validator("track-b-method-level-metrics-v1-1"),
        )
        method_stage = build_stage_receipt_v1_1(
            stage="METHOD_METRICS_PERSISTED",
            worker_role=METRIC_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="GROUPING_OPENED",
            artifact_receipts=[per_case_receipt, method_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, method_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "method_metrics_receipt_v1_1.json", method_stage
        )
        stage_identities.append(method_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="METHOD_METRICS_PERSISTED",
            worker_role=METRIC_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[method_identity],
            open_read_counts=counts,
        )
        prediction_sets = {
            method: {
                str(row["review_case_id"]): frozenset(row["predicted_capabilities"])
                for row in predictions[method]
            }
            for method in METHODS
        }
        gold_sets = {
            case_id: frozenset(name for name in CAPABILITIES if _yes(row[name]))
            for case_id, row in label_by_id.items()
        }
        ordered_groups = tuple(
            (group_id, tuple(sorted(case_ids, key=lambda value: value.encode("utf-8"))))
            for group_id, case_ids in sorted(
                by_group.items(), key=lambda item: item[0].encode("utf-8")
            )
        )
        statistics = (
            run_fixed_synthetic_statistics_v1_1(
                ordered_groups=ordered_groups,
                predictions_by_method=prediction_sets,
                gold_by_id=gold_sets,
                method_metrics=method_metrics,
            )
            if lock.get("synthetic")
            else run_fixed_track_b_statistics_v1_1(
                ordered_groups=ordered_groups,
                predictions_by_method=prediction_sets,
                gold_by_id=gold_sets,
                method_metrics=method_metrics,
            )
        )
        statistical_document = {
            "schema_version": "track-b-fixed-statistical-state-v1-1",
            "statistics": statistics,
        }
        statistical_receipt = publish_durable_artifact_v1_1(
            paths.statistical_state,
            canonical_json_bytes(statistical_document),
            stage="PRIMARY_STATISTICS_PERSISTED",
            worker_role=METRIC_ROLE,
            artifact_role="FIXED_STATISTICAL_STATE",
            schema_id="track-b-fixed-statistical-state-v1-1",
            record_count=3,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="METHOD_METRICS_PERSISTED",
            schema_validator=json_object_validator("track-b-fixed-statistical-state-v1-1"),
        )
        statistical_stage = build_stage_receipt_v1_1(
            stage="PRIMARY_STATISTICS_PERSISTED",
            worker_role=METRIC_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="METHOD_METRICS_PERSISTED",
            artifact_receipts=[statistical_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, statistical_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "primary_statistics_receipt_v1_1.json",
            statistical_stage,
        )
        stage_identities.append(statistical_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="PRIMARY_STATISTICS_PERSISTED",
            worker_role=METRIC_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[statistical_identity],
            open_read_counts=counts,
        )
        p2_scope = json.loads(_read_all(paths.p2_scope_metadata))
        result = {
            "schema_version": "track-b-final-evaluation-result-v1-1",
            "status": "RESULT_PERSISTED",
            "execution_id": worker_descriptor.execution_id,
            "approved_head": worker_descriptor.approved_head,
            "gold_bundle_identity": lock["fixed_identity_bundle"]["d2b_gold_bundle_sha256"],
            "grouping_identity": expected_grouping_sha256,
            "method_identities": lock["fixed_identity_bundle"]["method_identities"],
            "metric_identity": binding.implementation_sha256,
            "statistical_identity": lock["fixed_identity_bundle"]["statistical_contract_sha256"],
            "method_metrics": method_metrics,
            "comparisons": statistics["comparisons"],
            "secondary_holm": statistics["secondary_holm"],
            "primary_comparison": statistics["primary"],
            "p2_secondary_scope": p2_scope,
            "runtime_firewall_summary": firewall.report(),
            "open_read_counts": counts,
            "hard_failure_count": 0,
        }
        result_value = canonical_json_bytes(result)
        result_receipt = publish_durable_artifact_v1_1(
            paths.final_result,
            result_value,
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            artifact_role="FINAL_RESULT",
            schema_id="track-b-final-evaluation-result-v1-1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            schema_validator=json_object_validator("track-b-final-evaluation-result-v1-1"),
        )
        manifest = {
            "schema_version": "track-b-final-result-manifest-v1-1",
            "result_sha256": result_receipt["sha256"],
            "result_size_bytes": result_receipt["size_bytes"],
            "input_bundle_commitment": lock["cumulative_artifact_bundle_commitment"],
            "method_metric_sha256": method_receipt["sha256"],
            "statistical_state_sha256": statistical_receipt["sha256"],
            "worker_credential_commitments": {
                role: value["credential_commitment"]
                for role, value in lock["worker_roles"].items()
            },
        }
        manifest_receipt = publish_durable_artifact_v1_1(
            paths.result_manifest,
            canonical_json_bytes(manifest),
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            artifact_role="FINAL_RESULT_MANIFEST",
            schema_id="track-b-final-result-manifest-v1-1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            schema_validator=json_object_validator("track-b-final-result-manifest-v1-1"),
        )
        process_report = {
            "schema_version": "track-b-metric-process-report-v1-1",
            "status": "PASS",
            "worker_role": METRIC_ROLE,
            "method_metric_keys_complete": True,
            "comparison_count": len(COMPARISONS),
            "runtime_firewall_summary": firewall.report(),
            "open_read_counts": counts,
            "result_sha256": result_receipt["sha256"],
        }
        process_report_receipt = publish_durable_artifact_v1_1(
            paths.metric_report,
            canonical_json_bytes(process_report),
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            artifact_role="METRIC_PROCESS_REPORT",
            schema_id="track-b-metric-process-report-v1-1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            schema_validator=json_object_validator("track-b-metric-process-report-v1-1"),
        )
        result_stage = build_stage_receipt_v1_1(
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            artifact_receipts=[result_receipt, manifest_receipt, process_report_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, result_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "result_persisted_receipt_v1_1.json", result_stage
        )
        stage_identities.append(result_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[result_identity],
            open_read_counts=counts,
        )
        mark_worker_consumed_v1_1(
            paths.global_lock,
            role=METRIC_ROLE,
            commitment=commitment,
            stage_receipt_identities=stage_identities,
            process_report_receipt=process_report_receipt,
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
    except BaseException as error:
        try:
            fail_global_lock_v1_1(paths.global_lock, reason=type(error).__name__, worker_role=METRIC_ROLE)
        finally:
            raise


def main() -> int:
    raise SystemExit("BLOCKED_RQ2_D4_WORKER_AUTHORITY: parent pipe required")


if __name__ == "__main__":
    raise SystemExit(main())
