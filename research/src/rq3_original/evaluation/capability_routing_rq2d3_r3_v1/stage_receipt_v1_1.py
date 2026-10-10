"""Durable stage receipts whose identities are committed into the global lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from . import canonical_json_bytes, sha256_bytes
from .durable_local_artifact import json_object_validator, publish_durable_artifact_v1_1


def build_stage_receipt_v1_1(
    *,
    stage: str,
    worker_role: str,
    approved_head: str,
    execution_id: str,
    effective_contract_id: str,
    code_identity: str,
    parent_state: str,
    artifact_receipts: Sequence[Mapping[str, Any]],
    open_read_counts: Mapping[str, Any],
    runtime_firewall_summary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "track-b-stage-receipt-v1-1",
        "stage": stage,
        "worker_role": worker_role,
        "approved_head": approved_head,
        "execution_id": execution_id,
        "effective_contract_id": effective_contract_id,
        "code_identity": code_identity,
        "parent_state": parent_state,
        "artifact_receipts": [dict(receipt) for receipt in artifact_receipts],
        "open_read_counts": dict(open_read_counts),
        "runtime_firewall_summary": dict(runtime_firewall_summary),
    }


def persist_stage_receipt_v1_1(
    target: Path, document: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = canonical_json_bytes(document)
    artifact_receipt = publish_durable_artifact_v1_1(
        target,
        value,
        stage=str(document["stage"]),
        worker_role=str(document["worker_role"]),
        artifact_role="STAGE_RECEIPT",
        schema_id="track-b-stage-receipt-v1-1",
        record_count=1,
        approved_head=str(document["approved_head"]),
        execution_id=str(document["execution_id"]),
        effective_contract_id=str(document["effective_contract_id"]),
        code_identity=str(document["code_identity"]),
        parent_state=str(document["parent_state"]),
        schema_validator=json_object_validator("track-b-stage-receipt-v1-1"),
    )
    identity = {
        "relative_path": target.name,
        "sha256": sha256_bytes(value),
        "size_bytes": len(value),
        "stage": document["stage"],
    }
    return artifact_receipt, identity


def stage_receipt_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-stage-receipt-contract-v1-1",
        "status": "FROZEN",
        "required_fields": [
            "stage",
            "worker_role",
            "approved_head",
            "execution_id",
            "effective_contract_id",
            "code_identity",
            "parent_state",
            "artifact_receipts",
            "open_read_counts",
            "runtime_firewall_summary",
        ],
        "receipt_durably_persisted": True,
        "receipt_sha_bound_to_global_lock": True,
    }
