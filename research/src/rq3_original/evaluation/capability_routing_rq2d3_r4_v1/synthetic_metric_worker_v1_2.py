"""Technically separate synthetic metric worker; no real worker entry import."""

from __future__ import annotations

from pathlib import Path

from . import SYNTHETIC_CONTRACT_ID, canonical_json_bytes
from .atomic_execution_state_v1_2 import transition_execution_state_v1_2
from .durable_no_replace_artifact_v1_2 import json_object_validator, publish_no_replace_artifact_v1_2
from .synthetic_r4_integrity_fixture import (
    SYNTHETIC_METRIC_ROLE,
    claim_synthetic_credential_v1_2,
    mark_synthetic_consumed_v1_2,
)


def run_synthetic_metric_worker_v1_2(*, synthetic_root: str, credential_fd: int) -> None:
    root = Path(synthetic_root)
    paths, commitment = claim_synthetic_credential_v1_2(
        root, SYNTHETIC_METRIC_ROLE, credential_fd
    )
    receipts = []
    stages = (
        ("LABEL_GOLD_OPENED", "SYNTHETIC_LABEL_OBSERVED", "METRIC_CREDENTIAL_COMMITTED"),
        ("GROUPING_OPENED", "SYNTHETIC_GROUPING_OBSERVED", "LABEL_GOLD_OPENED"),
        ("METHOD_METRICS_PERSISTED", "SYNTHETIC_METHOD_METRICS", "GROUPING_OPENED"),
        ("PRIMARY_STATISTICS_PERSISTED", "SYNTHETIC_STATISTICS", "METHOD_METRICS_PERSISTED"),
        ("RESULT_PERSISTED", "SYNTHETIC_RESULT", "PRIMARY_STATISTICS_PERSISTED"),
    )
    for stage, role, parent in stages:
        document = {"schema_version": f"{role.lower()}-v1-2", "status": "PASS"}
        target = paths.output / f"{role.lower()}.json"
        receipt = publish_no_replace_artifact_v1_2(
            target,
            canonical_json_bytes(document),
            relative_path=str(target.relative_to(root)),
            stage=stage,
            worker_role=SYNTHETIC_METRIC_ROLE,
            worker_credential_commitment=commitment,
            artifact_role=role,
            schema_id=document["schema_version"],
            record_count=1,
            approved_head="a" * 40,
            execution_id=__import__("hashlib").sha256(b"RQ2_D3_R4_SYNTHETIC_EXECUTION_V1_2").hexdigest(),
            effective_contract_id=SYNTHETIC_CONTRACT_ID,
            code_identity="synthetic-metric-code",
            parent_state=parent,
            schema_validator=json_object_validator(document["schema_version"]),
        )
        receipts.append(receipt)
        transition_execution_state_v1_2(
            paths.state, paths.sentinel, stage, stage_receipts=[receipt], evidence_summary={"synthetic": True}
        )
    mark_synthetic_consumed_v1_2(paths, SYNTHETIC_METRIC_ROLE, commitment, receipts)
