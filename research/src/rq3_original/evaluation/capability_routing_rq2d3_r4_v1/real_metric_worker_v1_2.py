"""Fixed-authority complete-metric and frozen-statistical real D4 worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from . import (
    CAPABILITIES,
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    GROUP_COUNT,
    GROUPING_SIZE,
    LABEL_SHA256,
    LABEL_SIZE,
    METHODS,
    RECORD_COUNT,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_bytes,
    sha256_file,
)
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
    METRIC_ROLE,
    claim_fixed_real_worker_authority_v1_2,
    mark_fixed_real_worker_consumed_success_v1_2,
)


def _read_all(path: Path, *, mode: int | None = None) -> bytes:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or (mode is not None and stat.S_IMODE(observed.st_mode) != mode)
    ):
        raise RuntimeError("metric artifact metadata mismatch")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or (observed.st_dev, observed.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise RuntimeError("metric artifact inode mismatch")
        value = os.read(descriptor, observed.st_size + 1)
    finally:
        os.close(descriptor)
    if len(value) != observed.st_size:
        raise RuntimeError("metric artifact read mismatch")
    return value


def _read_exact_input(path: Path, expected_sha: str, expected_size: int) -> bytes:
    value = _read_all(path)
    if len(value) != expected_size or sha256_bytes(value) != expected_sha:
        raise RuntimeError("metric input identity mismatch")
    return value


def _jsonl(value: bytes, expected: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if len(rows) != expected or not value.endswith(b"\n"):
        raise RuntimeError("metric JSONL mismatch")
    return rows


def _yes(value: Any) -> bool:
    if value in {True, "YES"}:
        return True
    if value in {False, "NO"}:
        return False
    raise ValueError("invalid frozen label value")


def _method_rows(
    predictions: Sequence[Mapping[str, Any]], labels: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
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


def _per_case_validator(value: bytes) -> None:
    rows = _jsonl(value, RECORD_COUNT * len(METHODS))
    required = {"review_case_id", "method_id", "exact_set_match", "set_jaccard"}
    if any(set(row) != required for row in rows):
        raise RuntimeError("per-case metric schema mismatch")


def _find_receipt(state: Mapping[str, Any], artifact_role: str) -> Mapping[str, Any]:
    matches = [
        receipt
        for receipt in state.get("stage_receipts", [])
        if receipt.get("artifact_role") == artifact_role
    ]
    if len(matches) != 1:
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return matches[0]


def _read_bound_artifact(
    state: Mapping[str, Any], path: Path, artifact_role: str
) -> bytes:
    receipt = _find_receipt(state, artifact_role)
    value = _read_all(path, mode=0o600)
    if sha256_bytes(value) != receipt.get("sha256") or len(value) != receipt.get("size_bytes"):
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return value


def run_real_metric_worker_v1_2(*, credential_fd: int) -> None:
    context = claim_fixed_real_worker_authority_v1_2(
        METRIC_ROLE, credential_fd=credential_fd
    )
    paths = context.paths
    code_identity = sha256_file(Path(__file__))
    stage_receipts: list[dict[str, Any]] = []
    counts = {
        "combined_source_open_count": 0,
        "label_gold_open_count": 0,
        "label_gold_read_count": 0,
        "grouping_open_count": 0,
        "grouping_read_count": 0,
        "feature_view_open_count": 0,
        "prediction_ledger_open_count": 0,
    }
    firewall = None
    try:
        from evaluation.capability_routing_rq2d3_r3_v1.worker_runtime_firewall import (
            RuntimeFirewall,
        )

        firewall = RuntimeFirewall(
            role=METRIC_ROLE,
            forbidden_paths={
                "COMBINED_SOURCE": paths.combined_source,
                "D1_MAPPING": paths.repository_root / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_opaque_mapping_v1.jsonl",
                "D1_CASE_BANK": paths.repository_root / "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_canonical_case_bank_v1.jsonl",
                "HIDDEN_LEGACY": paths.repository_root / "evaluation/capability_routing_rq2d2b_v1/local_hidden_legacy/hidden_legacy_v1.jsonl",
            },
            forbidden_import_prefixes=(
                "evaluation.capability_routing_rq2d3_r3_v1.frozen_capability_predictor_core_v1_1",
                "evaluation.capability_routing_rq2b_v1.p1_capability_router",
                "evaluation.capability_routing_rq2b_v1.b0_original_query_adapter",
                "utils.production_intent_router",
                "semantic_runtime.runtime",
            ),
        ).install()
        from evaluation.capability_routing_rq2d3_r3_v1.bound_prediction_v1_1 import (
            validate_prediction_set_v1_1,
        )
        from evaluation.capability_routing_rq2d3_r3_v1.feature_fingerprint_v1_1 import (
            validate_feature_row_v1_1,
        )

        state, _ = read_execution_state_v1_2(paths.state)
        features = _jsonl(
            _read_bound_artifact(state, paths.feature_view, "FEATURE_ONLY_VIEW"), RECORD_COUNT
        )
        counts["feature_view_open_count"] = 1
        for feature in features:
            validate_feature_row_v1_1(feature)
        prediction_paths = {
            "B0": paths.b0_predictions,
            "B1": paths.b1_predictions,
            "P1": paths.p1_predictions,
        }
        predictions = {
            method: _jsonl(
                _read_bound_artifact(
                    state, prediction_paths[method], f"{method}_BOUND_PREDICTIONS"
                ),
                RECORD_COUNT,
            )
            for method in METHODS
        }
        counts["prediction_ledger_open_count"] = len(METHODS)
        validate_prediction_set_v1_1(
            [row for method in METHODS for row in predictions[method]], features
        )
        label_value = _read_exact_input(paths.label_gold, LABEL_SHA256, LABEL_SIZE)
        counts.update(label_gold_open_count=1, label_gold_read_count=1)
        label_rows = _jsonl(label_value, RECORD_COUNT)
        label_by_id = {str(row["review_case_id"]): row for row in label_rows}
        if len(label_by_id) != RECORD_COUNT:
            raise RuntimeError("duplicate label identity")
        label_receipt = {
            "artifact_role": "LABEL_GOLD_OBSERVED",
            "relative_path": str(paths.label_gold.relative_to(paths.repository_root)),
            "sha256": LABEL_SHA256,
            "size_bytes": LABEL_SIZE,
            "record_count": RECORD_COUNT,
            "open_count": 1,
            "read_count": 1,
        }
        stage_receipts.append(label_receipt)

        def update_label_counts(document: dict[str, Any]) -> None:
            document["open_read_counters"].update(counts)

        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "LABEL_GOLD_OPENED",
            stage_receipts=[label_receipt],
            evidence_summary={"label_identity_verified": True},
            mutation=update_label_counts,
        )
        grouping_value = _read_exact_input(
            paths.grouping, D3_R2_GROUPING_SHA256, GROUPING_SIZE
        )
        counts.update(grouping_open_count=1, grouping_read_count=1)
        grouping_rows = _jsonl(grouping_value, RECORD_COUNT)
        by_group: dict[str, list[str]] = {}
        for row in grouping_rows:
            by_group.setdefault(str(row["contrast_group_id"]), []).append(
                str(row["review_case_id"])
            )
        if len(by_group) != GROUP_COUNT or set(map(len, by_group.values())) != {2}:
            raise RuntimeError("grouping shape mismatch")
        grouping_receipt = {
            "artifact_role": "GROUPING_LEDGER_OBSERVED",
            "relative_path": str(paths.grouping.relative_to(paths.repository_root)),
            "sha256": D3_R2_GROUPING_SHA256,
            "size_bytes": GROUPING_SIZE,
            "record_count": RECORD_COUNT,
            "group_count": GROUP_COUNT,
            "group_size": 2,
            "open_count": 1,
            "read_count": 1,
        }
        stage_receipts.append(grouping_receipt)

        def update_group_counts(document: dict[str, Any]) -> None:
            document["open_read_counters"].update(counts)

        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "GROUPING_OPENED",
            stage_receipts=[grouping_receipt],
            evidence_summary={"grouping_identity_verified": True},
            mutation=update_group_counts,
        )
        from evaluation.capability_routing_rq2d3_r3_v1.frozen_complete_metric_binding_v1_1 import (
            load_frozen_complete_track_b_metric_binding_v1_1,
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
        per_case_receipt = publish_no_replace_artifact_v1_2(
            paths.per_case_metric_ledger,
            canonical_jsonl_bytes(per_case_rows),
            relative_path=str(paths.per_case_metric_ledger.relative_to(paths.repository_root)),
            stage="METHOD_METRICS_PERSISTED",
            worker_role=METRIC_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="PER_CASE_METRIC_LEDGER",
            schema_id="track-b-per-case-metric-ledger-jsonl-v1-2",
            record_count=len(per_case_rows),
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="GROUPING_OPENED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=_per_case_validator,
        )
        method_document = {
            "schema_version": "track-b-method-level-metrics-v1-2",
            "method_metrics": method_metrics,
        }
        method_receipt = publish_no_replace_artifact_v1_2(
            paths.method_metrics,
            canonical_json_bytes(method_document),
            relative_path=str(paths.method_metrics.relative_to(paths.repository_root)),
            stage="METHOD_METRICS_PERSISTED",
            worker_role=METRIC_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="METHOD_LEVEL_METRICS",
            schema_id="track-b-method-level-metrics-v1-2",
            record_count=len(METHODS),
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="GROUPING_OPENED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-method-level-metrics-v1-2"),
        )
        stage_receipts.extend((per_case_receipt, method_receipt))
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "METHOD_METRICS_PERSISTED",
            stage_receipts=[per_case_receipt, method_receipt],
            evidence_summary={"method_count": len(METHODS), "metric_binding": binding.implementation_sha256},
        )
        from evaluation.capability_routing_rq2d3_r3_v1.fixed_statistical_execution_v1_1 import (
            run_fixed_track_b_statistics_v1_1,
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
        statistics = run_fixed_track_b_statistics_v1_1(
            ordered_groups=ordered_groups,
            predictions_by_method=prediction_sets,
            gold_by_id=gold_sets,
            method_metrics=method_metrics,
        )
        statistical_document = {
            "schema_version": "track-b-fixed-statistical-state-v1-2",
            "statistics": statistics,
        }
        statistical_receipt = publish_no_replace_artifact_v1_2(
            paths.statistical_state,
            canonical_json_bytes(statistical_document),
            relative_path=str(paths.statistical_state.relative_to(paths.repository_root)),
            stage="PRIMARY_STATISTICS_PERSISTED",
            worker_role=METRIC_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="FIXED_STATISTICAL_STATE",
            schema_id="track-b-fixed-statistical-state-v1-2",
            record_count=len(statistics.get("comparisons", {})),
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="METHOD_METRICS_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-fixed-statistical-state-v1-2"),
        )
        stage_receipts.append(statistical_receipt)
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "PRIMARY_STATISTICS_PERSISTED",
            stage_receipts=[statistical_receipt],
            evidence_summary={"fixed_statistics_complete": True},
        )
        current_state, _ = read_execution_state_v1_2(paths.state)
        pre_result_failures = list(current_state.get("hard_failure_evidence", []))
        for evidence in current_state.get("firewall_evidence", []):
            if int(evidence.get("successful_forbidden_opens", 0)):
                pre_result_failures.append({"category": "runtime_firewall_violation", "detail": "open"})
            if int(evidence.get("successful_forbidden_imports", 0)):
                pre_result_failures.append({"category": "runtime_firewall_violation", "detail": "import"})
        pre_result_hard_failure_count = len(pre_result_failures)
        if pre_result_hard_failure_count:
            raise RuntimeError("pre-result hard failure evidence present")
        p2_scope = json.loads(_read_all(paths.p2_scope_metadata, mode=0o600))
        result = {
            "schema_version": "track-b-final-evaluation-result-v1-2",
            "status": "RESULT_PERSISTED",
            "execution_id": context.descriptor.execution_id,
            "approved_head": context.descriptor.approved_head,
            "gold_bundle_identity": D2B_GOLD_BUNDLE_SHA256,
            "grouping_identity": D3_R2_GROUPING_SHA256,
            "metric_identity": binding.implementation_sha256,
            "statistical_identity": D3_R1_STATISTICAL_SHA256,
            "method_metrics": method_metrics,
            "comparisons": statistics["comparisons"],
            "secondary_holm": statistics["secondary_holm"],
            "primary_comparison": statistics["primary"],
            "p2_secondary_scope": p2_scope,
            "runtime_firewall_summary": firewall.report(),
            "open_read_counts": counts,
            "pre_result_hard_failure_events": pre_result_failures,
            "pre_result_hard_failure_count": pre_result_hard_failure_count,
            "completion_eligibility_derived_by_parent_after_receipt_verification": True,
        }
        result_receipt = publish_no_replace_artifact_v1_2(
            paths.final_result,
            canonical_json_bytes(result),
            relative_path=str(paths.final_result.relative_to(paths.repository_root)),
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="FINAL_RESULT",
            schema_id="track-b-final-evaluation-result-v1-2",
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-final-evaluation-result-v1-2"),
        )
        manifest = {
            "schema_version": "track-b-final-result-manifest-v1-2",
            "result_sha256": result_receipt["sha256"],
            "result_size_bytes": result_receipt["size_bytes"],
            "method_metric_sha256": method_receipt["sha256"],
            "statistical_state_sha256": statistical_receipt["sha256"],
            "pre_result_hard_failure_count": pre_result_hard_failure_count,
        }
        manifest_receipt = publish_no_replace_artifact_v1_2(
            paths.result_manifest,
            canonical_json_bytes(manifest),
            relative_path=str(paths.result_manifest.relative_to(paths.repository_root)),
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="FINAL_RESULT_MANIFEST",
            schema_id="track-b-final-result-manifest-v1-2",
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-final-result-manifest-v1-2"),
        )
        process_report = {
            "schema_version": "track-b-metric-process-report-v1-2",
            "status": "PASS",
            "worker_role": METRIC_ROLE,
            "method_metric_keys_complete": True,
            "comparison_count": len(statistics["comparisons"]),
            "runtime_firewall_summary": firewall.report(),
            "open_read_counts": counts,
            "result_sha256": result_receipt["sha256"],
            "hard_failure_count_source": "len(pre_result_hard_failure_events)",
            "pre_result_hard_failure_count": pre_result_hard_failure_count,
        }
        report_receipt = publish_no_replace_artifact_v1_2(
            paths.metric_report,
            canonical_json_bytes(process_report),
            relative_path=str(paths.metric_report.relative_to(paths.repository_root)),
            stage="RESULT_PERSISTED",
            worker_role=METRIC_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="METRIC_PROCESS_REPORT",
            schema_id="track-b-metric-process-report-v1-2",
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="PRIMARY_STATISTICS_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-metric-process-report-v1-2"),
        )
        stage_receipts.extend((result_receipt, manifest_receipt, report_receipt))
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "RESULT_PERSISTED",
            stage_receipts=[result_receipt, manifest_receipt, report_receipt],
            evidence_summary={
                "result_persisted": True,
                "pre_result_hard_failure_count": pre_result_hard_failure_count,
            },
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
                failure_stage="METRIC",
                failure_receipt={"artifact_role": "ROOT_FAILURE_RECEIPT"},
            )
        finally:
            raise


def main() -> int:
    raise SystemExit("BLOCKED_RQ2_D4_WORKER_AUTHORITY: inherited pipe required")


if __name__ == "__main__":
    raise SystemExit(main())
