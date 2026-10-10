"""One-time, role-specific worker credentials delivered only through an inherited FD."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import secrets
from typing import Any

from . import canonical_json_bytes
from .global_lock_receipt_v1_1 import (
    commit_worker_credential_v1_1,
    mark_worker_claimed_v1_1,
)


CREDENTIAL_DOMAIN = b"RQ2_D4_WORKER_CREDENTIAL_V1_1\x00"
FEATURE_ROLE = "TRACK_B_FEATURE_EXTRACTOR_V1_1"
PREDICTOR_ROLE = "TRACK_B_B0_B1_P1_PREDICTOR_V1_1"
METRIC_ROLE = "TRACK_B_FINAL_METRIC_WORKER_V1_1"
ROLES = (FEATURE_ROLE, PREDICTOR_ROLE, METRIC_ROLE)


@dataclass(frozen=True)
class WorkerDescriptorV1_1:
    worker_role: str
    role_sequence_number: int
    required_predecessor_state: str
    execution_id: str
    approved_head: str
    global_lock_identity: str
    effective_contract_id: str


def credential_commitment_v1_1(secret: bytes, descriptor: WorkerDescriptorV1_1) -> str:
    if len(secret) != 32 or descriptor.worker_role not in ROLES:
        raise ValueError("invalid worker credential")
    return hashlib.sha256(
        CREDENTIAL_DOMAIN
        + secret
        + b"\x00"
        + canonical_json_bytes(asdict(descriptor)).rstrip(b"\n")
    ).hexdigest()


def issue_worker_credential_v1_1(
    lock_path: Path, *, descriptor: WorkerDescriptorV1_1, commit_state: str
) -> tuple[bytes, str]:
    raise PermissionError("SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY")

    secret = secrets.token_bytes(32)
    commitment = credential_commitment_v1_1(secret, descriptor)
    commit_worker_credential_v1_1(
        lock_path, descriptor=asdict(descriptor), commitment=commitment, commit_state=commit_state
    )
    return secret, commitment


def read_credential_once_v1_1(descriptor_fd: int) -> bytes:
    try:
        value = os.read(descriptor_fd, 33)
    finally:
        os.close(descriptor_fd)
    if len(value) != 32:
        raise PermissionError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    return value


def claim_worker_credential_v1_1(
    lock_path: Path, *, descriptor_fd: int, descriptor: WorkerDescriptorV1_1
) -> str:
    secret = read_credential_once_v1_1(descriptor_fd)
    commitment = credential_commitment_v1_1(secret, descriptor)
    mark_worker_claimed_v1_1(
        lock_path, descriptor=asdict(descriptor), commitment=commitment
    )
    secret = b"\x00" * len(secret)
    return commitment


def worker_authority_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-worker-authority-contract-v1-1",
        "status": "FROZEN",
        "roles": list(ROLES),
        "credential_bytes": 32,
        "credential_source": "CSPRNG",
        "credential_transport": "INHERITED_ANONYMOUS_PIPE_FD",
        "credential_in_cli": False,
        "credential_in_environment": False,
        "credential_file": False,
        "credential_logged": False,
        "global_lock_stores_commitment_only": True,
        "claim_before_restricted_open": True,
        "claim_before_business_import": True,
        "credential_reuse_permitted": False,
    }
