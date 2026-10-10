"""Credential-gated, one-read feature extractor for the future D4 run."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import canonical_json_bytes, canonical_jsonl_bytes, sha256_bytes, sha256_file
from .durable_local_artifact import json_object_validator, publish_durable_artifact_v1_1
from .fixed_rq2d4_paths_v1_1 import D4PathsV1_1
from .global_lock_receipt_v1_1 import (
    append_transition_v1_1,
    fail_global_lock_v1_1,
    mark_worker_consumed_v1_1,
)
from .stage_receipt_v1_1 import build_stage_receipt_v1_1, persist_stage_receipt_v1_1
from .worker_execution_authority_v1_1 import (
    FEATURE_ROLE,
    WorkerDescriptorV1_1,
    claim_worker_credential_v1_1,
)
from .worker_runtime_firewall import RuntimeFirewall


def _read_once(path: Path, *, expected_sha256: str, expected_size: int) -> bytes:
    value = os.lstat(path)
    if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode) or value.st_size != expected_size:
        raise RuntimeError("extractor input metadata mismatch")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        payload = os.read(descriptor, expected_size + 1)
    finally:
        os.close(descriptor)
    if len(payload) != expected_size or sha256_bytes(payload) != expected_sha256:
        raise RuntimeError("extractor input identity mismatch")
    return payload


def _jsonl(value: bytes, expected_count: int) -> list[dict[str, Any]]:
    if value.startswith(b"\xef\xbb\xbf") or b"\r" in value or not value.endswith(b"\n"):
        raise RuntimeError("extractor JSONL byte contract mismatch")
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if len(rows) != expected_count or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("extractor record count mismatch")
    return rows


def _jsonl_validator(expected_count: int, required: set[str]):
    def validate(value: bytes) -> None:
        rows = _jsonl(value, expected_count)
        if any(set(row) != required for row in rows):
            raise RuntimeError("feature-only schema mismatch")

    return validate


def run_feature_extractor_worker_v1_1(
    *,
    paths: D4PathsV1_1,
    descriptor_fd: int,
    worker_descriptor: WorkerDescriptorV1_1,
    expected_combined_sha256: str,
    expected_combined_size: int,
    expected_record_count: int,
) -> None:
    raise RuntimeError("SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY")

    commitment = claim_worker_credential_v1_1(
        paths.global_lock, descriptor_fd=descriptor_fd, descriptor=worker_descriptor
    )
    code_identity = sha256_file(Path(__file__))
    firewall = RuntimeFirewall(
        role=FEATURE_ROLE,
        forbidden_paths={
            "LABEL_ONLY_GOLD": paths.label_gold,
            "GROUPING_LEDGER": paths.grouping,
        },
        forbidden_import_prefixes=(
            "evaluation.capability_routing_rq2b_v1",
            "evaluation.capability_routing_rq2d3_r1_v1",
            "evaluation.capability_routing_rq2d3_r3_v1.track_b_metric_worker_v1_1",
        ),
    ).install()
    stage_identities: list[dict[str, Any]] = []
    process_report_receipt: dict[str, Any] = {}
    counts = {"combined_source_open_count": 0, "combined_source_read_count": 0}
    try:
        payload = _read_once(
            paths.combined_source,
            expected_sha256=expected_combined_sha256,
            expected_size=expected_combined_size,
        )
        counts = {"combined_source_open_count": 1, "combined_source_read_count": 1}
        combined_rows = _jsonl(payload, expected_record_count)
        append_transition_v1_1(
            paths.global_lock,
            new_state="COMBINED_CASE_SOURCE_OPENED",
            worker_role=FEATURE_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[
                {
                    "artifact_role": "COMBINED_CASE_SOURCE_OBSERVED",
                    "sha256": expected_combined_sha256,
                    "size_bytes": expected_combined_size,
                    "record_count": expected_record_count,
                }
            ],
            open_read_counts=counts,
        )
        from .feature_fingerprint_v1_1 import build_feature_row_v1_1

        features = [build_feature_row_v1_1(row) for row in combined_rows]
        if len({row["review_case_id"] for row in features}) != expected_record_count:
            raise RuntimeError("duplicate feature identity")
        feature_value = canonical_jsonl_bytes(features)
        feature_receipt = publish_durable_artifact_v1_1(
            paths.feature_view,
            feature_value,
            stage="FEATURE_VIEW_PERSISTED",
            worker_role=FEATURE_ROLE,
            artifact_role="FEATURE_ONLY_VIEW",
            schema_id="track-b-feature-only-view-v1-1",
            record_count=expected_record_count,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="COMBINED_CASE_SOURCE_OPENED",
            schema_validator=_jsonl_validator(
                expected_record_count,
                {
                    "review_case_id",
                    "current_query",
                    "current_page",
                    "necessary_conversation_history",
                    "feature_content_fingerprint",
                    "feature_record_fingerprint",
                },
            ),
        )
        feature_stage = build_stage_receipt_v1_1(
            stage="FEATURE_VIEW_PERSISTED",
            worker_role=FEATURE_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="COMBINED_CASE_SOURCE_OPENED",
            artifact_receipts=[feature_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, feature_stage_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "feature_view_persisted_receipt_v1_1.json", feature_stage
        )
        stage_identities.append(feature_stage_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="FEATURE_VIEW_PERSISTED",
            worker_role=FEATURE_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[feature_stage_identity],
            open_read_counts=counts,
        )
        report = {
            "schema_version": "track-b-feature-extractor-report-v1-1",
            "status": "PASS",
            "worker_role": FEATURE_ROLE,
            "combined_source_open_read": "1/1",
            "combined_source_sha256": expected_combined_sha256,
            "combined_source_size_bytes": expected_combined_size,
            "combined_source_record_count": expected_record_count,
            "feature_record_count": len(features),
            "feature_view_sha256": feature_receipt["sha256"],
            "projected_fields": [
                "review_case_id",
                "current_query",
                "current_page",
                "necessary_conversation_history",
            ],
            "forbidden_gold_fields_exported": 0,
            "runtime_firewall_summary": firewall.report(),
        }
        process_report_receipt = publish_durable_artifact_v1_1(
            paths.extractor_report,
            canonical_json_bytes(report),
            stage="FEATURE_FIREWALL_VERIFIED",
            worker_role=FEATURE_ROLE,
            artifact_role="FEATURE_EXTRACTOR_PROCESS_REPORT",
            schema_id="track-b-feature-extractor-report-v1-1",
            record_count=1,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="FEATURE_VIEW_PERSISTED",
            schema_validator=json_object_validator("track-b-feature-extractor-report-v1-1"),
        )
        firewall_stage = build_stage_receipt_v1_1(
            stage="FEATURE_FIREWALL_VERIFIED",
            worker_role=FEATURE_ROLE,
            approved_head=worker_descriptor.approved_head,
            execution_id=worker_descriptor.execution_id,
            effective_contract_id=worker_descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="FEATURE_VIEW_PERSISTED",
            artifact_receipts=[process_report_receipt],
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
        _, firewall_stage_identity = persist_stage_receipt_v1_1(
            paths.receipts_root / "feature_firewall_verified_receipt_v1_1.json",
            firewall_stage,
        )
        stage_identities.append(firewall_stage_identity)
        append_transition_v1_1(
            paths.global_lock,
            new_state="FEATURE_FIREWALL_VERIFIED",
            worker_role=FEATURE_ROLE,
            credential_commitment=commitment,
            stage_receipt_identities=[firewall_stage_identity],
            open_read_counts=counts,
        )
        mark_worker_consumed_v1_1(
            paths.global_lock,
            role=FEATURE_ROLE,
            commitment=commitment,
            stage_receipt_identities=stage_identities,
            process_report_receipt=process_report_receipt,
            open_read_counts=counts,
            runtime_firewall_summary=firewall.report(),
        )
    except BaseException as error:
        try:
            fail_global_lock_v1_1(paths.global_lock, reason=type(error).__name__, worker_role=FEATURE_ROLE)
        finally:
            raise


def main() -> int:
    raise SystemExit("BLOCKED_RQ2_D4_WORKER_AUTHORITY: parent pipe required")


if __name__ == "__main__":
    raise SystemExit(main())
