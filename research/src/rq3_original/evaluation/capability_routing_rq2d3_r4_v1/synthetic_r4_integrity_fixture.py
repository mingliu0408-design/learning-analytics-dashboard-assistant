"""Synthetic-only authority and fixture; it cannot satisfy fixed real authority."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
from typing import Any, Mapping, Sequence

from . import SYNTHETIC_CONTRACT_ID, canonical_json_bytes, sha256_bytes, utc_timestamp
from .atomic_execution_state_v1_2 import (
    atomic_mutate_execution_state_v1_2,
    initial_execution_state_document_v1_2,
    initialise_execution_state_v1_2,
    read_execution_state_v1_2,
    transition_execution_state_v1_2,
)
from .durable_directory_tree_v1_2 import create_durable_directory_tree_v1_2
from .immutable_reservation_sentinel_v1_2 import (
    create_reservation_sentinel_v1_2,
    reservation_sentinel_document_v1_2,
)
from .parent_execution_receipt_v1_2 import (
    parent_execution_receipt_document_v1_2,
    parent_receipt_descriptor_commitment_v1_2,
    persist_parent_execution_receipt_v1_2,
)


SYNTHETIC_CREDENTIAL_DOMAIN = b"RQ2_D3_R4_SYNTHETIC_WORKER_CREDENTIAL_V1_2\x00"
SYNTHETIC_FEATURE_ROLE = "SYNTHETIC_FEATURE_WORKER_V1_2"
SYNTHETIC_PREDICTOR_ROLE = "SYNTHETIC_PREDICTOR_WORKER_V1_2"
SYNTHETIC_METRIC_ROLE = "SYNTHETIC_METRIC_WORKER_V1_2"

SYNTHETIC_CONFIG = {
    SYNTHETIC_FEATURE_ROLE: ("PARENT_EXECUTION_RECEIPT_PERSISTED", "EXTRACTOR_CREDENTIAL_COMMITTED"),
    SYNTHETIC_PREDICTOR_ROLE: ("FEATURE_FIREWALL_VERIFIED", "PREDICTOR_CREDENTIAL_COMMITTED"),
    SYNTHETIC_METRIC_ROLE: ("SECONDARY_SCOPE_METADATA_PERSISTED", "METRIC_CREDENTIAL_COMMITTED"),
}


@dataclass(frozen=True)
class SyntheticPathsV1_2:
    root: Path
    control: Path
    output: Path
    sentinel: Path
    state: Path
    parent_receipt: Path


def synthetic_paths_v1_2(root: Path) -> SyntheticPathsV1_2:
    return SyntheticPathsV1_2(
        root=root,
        control=root / "synthetic_control",
        output=root / "synthetic_output",
        sentinel=root / "synthetic_control/SYNTHETIC_RESERVATION_V1_2.json",
        state=root / "synthetic_control/SYNTHETIC_STATE_V1_2.json",
        parent_receipt=root / "synthetic_control/SYNTHETIC_PARENT_V1_2.json",
    )


def build_synthetic_authority_fixture_v1_2(root: Path) -> SyntheticPathsV1_2:
    paths = synthetic_paths_v1_2(root)
    create_durable_directory_tree_v1_2(root, "synthetic_control")
    create_durable_directory_tree_v1_2(root, "synthetic_output")
    approved_head = "a" * 40
    execution_id = hashlib.sha256(b"RQ2_D3_R4_SYNTHETIC_EXECUTION_V1_2").hexdigest()
    fixed_paths = {
        "output_root_relative": "synthetic_output",
        "control_root_relative": "synthetic_control",
        "sentinel_relative": "synthetic_control/SYNTHETIC_RESERVATION_V1_2.json",
        "state_relative": "synthetic_control/SYNTHETIC_STATE_V1_2.json",
        "parent_receipt_relative": "synthetic_control/SYNTHETIC_PARENT_V1_2.json",
    }
    nonce_commitment = hashlib.sha256(b"synthetic-parent-nonce").hexdigest()
    descriptor_commitment = parent_receipt_descriptor_commitment_v1_2(
        relative_path=fixed_paths["parent_receipt_relative"],
        effective_contract_id=SYNTHETIC_CONTRACT_ID,
        approved_head=approved_head,
    )
    sentinel_document = reservation_sentinel_document_v1_2(
        execution_id=execution_id,
        approved_head=approved_head,
        fixed_paths=fixed_paths,
        frozen_identity_bundle={"fixture": "SYNTHETIC_SAFE_IDS_ONLY"},
        input_identity_bundle={"record_count": 4, "contains_governed_text": False},
        d3_r4_code_bundle_identity="synthetic-code",
        parent_execution_nonce_commitment=nonce_commitment,
        parent_receipt_descriptor_commitment=descriptor_commitment,
        reservation_created_at="2026-08-29T00:00:00Z",
        synthetic=True,
        execution_contract_id=SYNTHETIC_CONTRACT_ID,
    )
    sentinel_identity = create_reservation_sentinel_v1_2(paths.sentinel, sentinel_document)
    state_document = initial_execution_state_document_v1_2(
        execution_id=execution_id,
        approved_head=approved_head,
        effective_contract_id=SYNTHETIC_CONTRACT_ID,
        sentinel_sha256=sentinel_identity["sha256"],
        synthetic=True,
        transition_timestamp="2026-08-29T00:00:01Z",
    )
    initialise_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        state_document,
        state_relative_path=fixed_paths["state_relative"],
    )
    transition_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        "INPUT_IDENTITIES_VERIFIED",
        stage_receipts=[{"artifact_role": "SYNTHETIC_INPUT_IDENTITIES", "sha256": "b" * 64}],
        evidence_summary={"synthetic_inputs_verified": True},
    )
    parent_document = parent_execution_receipt_document_v1_2(
        execution_id=execution_id,
        approved_head=approved_head,
        effective_contract_id=SYNTHETIC_CONTRACT_ID,
        sentinel_identity=sentinel_identity,
        sentinel_relative=fixed_paths["sentinel_relative"],
        state_relative=fixed_paths["state_relative"],
        parent_receipt_relative=fixed_paths["parent_receipt_relative"],
        parent_nonce_commitment=nonce_commitment,
        parent_code_identity="synthetic-parent-code",
        fixed_real_paths=fixed_paths,
        input_identity_commitments={"fixture": "SAFE"},
        created_at="2026-08-29T00:00:02Z",
        synthetic=True,
    )
    parent_receipt = persist_parent_execution_receipt_v1_2(
        paths.parent_receipt,
        parent_document,
        relative_path=fixed_paths["parent_receipt_relative"],
        sentinel_sha256=sentinel_identity["sha256"],
    )

    def bind_parent(document: dict[str, Any]) -> None:
        document["parent_receipt_sha256"] = parent_receipt["sha256"]

    transition_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        "PARENT_EXECUTION_RECEIPT_PERSISTED",
        stage_receipts=[parent_receipt],
        evidence_summary={"synthetic_parent_receipt": True},
        mutation=bind_parent,
    )
    return paths


def _synthetic_commitment(secret: bytes, role: str, state: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        SYNTHETIC_CREDENTIAL_DOMAIN
        + secret
        + b"\x00"
        + canonical_json_bytes(
            {
                "worker_role": role,
                "execution_id": state["execution_id"],
                "approved_head": state["approved_head"],
                "effective_contract_id": state["effective_contract_id"],
            }
        ).rstrip(b"\n")
    ).hexdigest()


def issue_synthetic_credential_v1_2(root: Path, role: str) -> tuple[bytes, str]:
    paths = synthetic_paths_v1_2(root)
    state, _ = read_execution_state_v1_2(paths.state)
    predecessor, commit_state = SYNTHETIC_CONFIG[role]
    if (
        state.get("synthetic") is not True
        or state.get("effective_contract_id") != SYNTHETIC_CONTRACT_ID
        or state.get("current_state") != predecessor
        or role in state.get("worker_roles", {})
    ):
        raise PermissionError("SYNTHETIC_WORKER_AUTHORITY_REJECTED")
    secret = secrets.token_bytes(32)
    commitment = _synthetic_commitment(secret, role, state)

    def commit(document: dict[str, Any]) -> None:
        document["worker_roles"][role] = {
            "status": "ISSUED",
            "credential_commitment": commitment,
            "stage_receipts": [],
            "open_read_counts": {},
            "firewall_summary": {},
        }

    transition_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        commit_state,
        stage_receipts=[{"artifact_role": "SYNTHETIC_CREDENTIAL_COMMITMENT", "sha256": commitment}],
        evidence_summary={"synthetic_worker_role": role},
        mutation=commit,
    )
    return secret, commitment


def claim_synthetic_credential_v1_2(
    root: Path, role: str, credential_fd: int
) -> tuple[SyntheticPathsV1_2, str]:
    paths = synthetic_paths_v1_2(root)
    state, _ = read_execution_state_v1_2(paths.state)
    _, commit_state = SYNTHETIC_CONFIG[role]
    entry = state.get("worker_roles", {}).get(role)
    try:
        secret = bytearray(os.read(credential_fd, 33))
    finally:
        os.close(credential_fd)
    if (
        len(secret) != 32
        or state.get("synthetic") is not True
        or state.get("effective_contract_id") != SYNTHETIC_CONTRACT_ID
        or state.get("current_state") != commit_state
        or not entry
        or entry.get("status") != "ISSUED"
    ):
        raise PermissionError("SYNTHETIC_WORKER_AUTHORITY_REJECTED")
    try:
        commitment = _synthetic_commitment(bytes(secret), role, state)
    finally:
        for index in range(len(secret)):
            secret[index] = 0
    if commitment != entry.get("credential_commitment"):
        raise PermissionError("SYNTHETIC_WORKER_AUTHORITY_REJECTED")

    def claim(document: dict[str, Any]) -> None:
        current = document["worker_roles"][role]
        if current.get("status") != "ISSUED":
            raise PermissionError("SYNTHETIC_WORKER_AUTHORITY_REJECTED")
        current["status"] = "CLAIMED"

    atomic_mutate_execution_state_v1_2(paths.state, paths.sentinel, claim)
    return paths, commitment


def mark_synthetic_consumed_v1_2(
    paths: SyntheticPathsV1_2,
    role: str,
    commitment: str,
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    def consume(document: dict[str, Any]) -> None:
        entry = document["worker_roles"][role]
        if entry.get("status") != "CLAIMED" or entry.get("credential_commitment") != commitment:
            raise PermissionError("SYNTHETIC_WORKER_AUTHORITY_REJECTED")
        entry["status"] = "CONSUMED_SUCCESS"
        entry["stage_receipts"] = [dict(row) for row in receipts]
        entry["open_read_counts"] = {"synthetic_restricted_open_count": 0}
        entry["firewall_summary"] = {
            "successful_forbidden_opens": 0,
            "successful_forbidden_imports": 0,
        }

    atomic_mutate_execution_state_v1_2(paths.state, paths.sentinel, consume)
