"""Fixed-authority, one-read real feature extractor for future D4."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import (
    COMBINED_SHA256,
    COMBINED_SIZE,
    RECORD_COUNT,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_bytes,
    sha256_file,
)
from .atomic_execution_state_v1_2 import (
    fail_execution_state_v1_2,
    transition_execution_state_v1_2,
)
from .durable_no_replace_artifact_v1_2 import (
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)
from .fixed_real_worker_authority_v1_2 import (
    FEATURE_ROLE,
    claim_fixed_real_worker_authority_v1_2,
    mark_fixed_real_worker_consumed_success_v1_2,
)


def _read_exact_input(path: Path) -> bytes:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or observed.st_size != COMBINED_SIZE
    ):
        raise RuntimeError("combined source metadata mismatch")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or (observed.st_dev, observed.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise RuntimeError("combined source inode mismatch")
        value = os.read(descriptor, COMBINED_SIZE + 1)
    finally:
        os.close(descriptor)
    if len(value) != COMBINED_SIZE or sha256_bytes(value) != COMBINED_SHA256:
        raise RuntimeError("combined source identity mismatch")
    return value


def _jsonl(value: bytes) -> list[dict[str, Any]]:
    if value.startswith(b"\xef\xbb\xbf") or b"\r" in value or not value.endswith(b"\n"):
        raise RuntimeError("combined source JSONL byte mismatch")
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if len(rows) != RECORD_COUNT or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("combined source record mismatch")
    return rows


def _feature_validator(value: bytes) -> None:
    rows = _jsonl(value)
    expected = {
        "review_case_id",
        "current_query",
        "current_page",
        "necessary_conversation_history",
        "feature_content_fingerprint",
        "feature_record_fingerprint",
    }
    if any(set(row) != expected for row in rows):
        raise RuntimeError("feature-only schema mismatch")


def _update_counts(counts: Mapping[str, int]):
    def update(document: dict[str, Any]) -> None:
        document["open_read_counters"].update(counts)

    return update


def run_real_feature_extractor_worker_v1_2(*, credential_fd: int) -> None:
    context = claim_fixed_real_worker_authority_v1_2(
        FEATURE_ROLE, credential_fd=credential_fd
    )
    paths = context.paths
    code_identity = sha256_file(Path(__file__))
    stage_receipts: list[dict[str, Any]] = []
    counts = {"combined_source_open_count": 0, "combined_source_read_count": 0}
    firewall = None
    try:
        # Restricted modules and audit hooks are deliberately loaded only after claim.
        from evaluation.capability_routing_rq2d3_r3_v1.worker_runtime_firewall import (
            RuntimeFirewall,
        )

        firewall = RuntimeFirewall(
            role=FEATURE_ROLE,
            forbidden_paths={"LABEL_ONLY_GOLD": paths.label_gold, "GROUPING_LEDGER": paths.grouping},
            forbidden_import_prefixes=(
                "evaluation.capability_routing_rq2b_v1",
                "evaluation.capability_routing_rq2d3_r1_v1",
                "evaluation.capability_routing_rq2d3_r4_v1.real_metric_worker_v1_2",
            ),
        ).install()
        payload = _read_exact_input(paths.combined_source)
        counts.update(combined_source_open_count=1, combined_source_read_count=1)
        rows = _jsonl(payload)
        observed_receipt = {
            "artifact_role": "COMBINED_CASE_SOURCE_OBSERVED",
            "relative_path": str(paths.combined_source.relative_to(paths.repository_root)),
            "sha256": COMBINED_SHA256,
            "size_bytes": COMBINED_SIZE,
            "record_count": RECORD_COUNT,
            "open_count": 1,
            "read_count": 1,
        }
        stage_receipts.append(observed_receipt)
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "COMBINED_CASE_SOURCE_OPENED",
            stage_receipts=[observed_receipt],
            evidence_summary={"combined_source_identity_verified": True},
            mutation=_update_counts(counts),
        )
        from evaluation.capability_routing_rq2d3_r3_v1.feature_fingerprint_v1_1 import (
            build_feature_row_v1_1,
        )

        features = [build_feature_row_v1_1(row) for row in rows]
        if len({row["review_case_id"] for row in features}) != RECORD_COUNT:
            raise RuntimeError("duplicate feature identity")
        feature_receipt = publish_no_replace_artifact_v1_2(
            paths.feature_view,
            canonical_jsonl_bytes(features),
            relative_path=str(paths.feature_view.relative_to(paths.repository_root)),
            stage="FEATURE_VIEW_PERSISTED",
            worker_role=FEATURE_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="FEATURE_ONLY_VIEW",
            schema_id="track-b-feature-only-view-jsonl-v1-2",
            record_count=RECORD_COUNT,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="COMBINED_CASE_SOURCE_OPENED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=_feature_validator,
        )
        stage_receipts.append(feature_receipt)
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "FEATURE_VIEW_PERSISTED",
            stage_receipts=[feature_receipt],
            evidence_summary={"feature_record_count": RECORD_COUNT},
        )
        report = {
            "schema_version": "track-b-feature-extractor-report-v1-2",
            "status": "PASS",
            "worker_role": FEATURE_ROLE,
            "combined_source_open_read": "1/1",
            "combined_source_sha256": COMBINED_SHA256,
            "combined_source_size_bytes": COMBINED_SIZE,
            "combined_source_record_count": RECORD_COUNT,
            "feature_record_count": len(features),
            "feature_view_sha256": feature_receipt["sha256"],
            "forbidden_gold_fields_exported": 0,
            "runtime_firewall_summary": firewall.report(),
        }
        report_receipt = publish_no_replace_artifact_v1_2(
            paths.extractor_report,
            canonical_json_bytes(report),
            relative_path=str(paths.extractor_report.relative_to(paths.repository_root)),
            stage="FEATURE_FIREWALL_VERIFIED",
            worker_role=FEATURE_ROLE,
            worker_credential_commitment=context.credential_commitment,
            artifact_role="FEATURE_EXTRACTOR_PROCESS_REPORT",
            schema_id="track-b-feature-extractor-report-v1-2",
            record_count=1,
            approved_head=context.descriptor.approved_head,
            execution_id=context.descriptor.execution_id,
            effective_contract_id=context.descriptor.effective_contract_id,
            code_identity=code_identity,
            parent_state="FEATURE_VIEW_PERSISTED",
            open_read_counts=counts,
            firewall_summary=firewall.report(),
            schema_validator=json_object_validator("track-b-feature-extractor-report-v1-2"),
        )
        stage_receipts.append(report_receipt)
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "FEATURE_FIREWALL_VERIFIED",
            stage_receipts=[report_receipt],
            evidence_summary={"firewall_verified": True},
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
                failure_stage="FEATURE_EXTRACTOR",
                failure_receipt={"artifact_role": "ROOT_FAILURE_RECEIPT"},
            )
        finally:
            raise


def main() -> int:
    raise SystemExit("BLOCKED_RQ2_D4_WORKER_AUTHORITY: inherited pipe required")


if __name__ == "__main__":
    raise SystemExit(main())
