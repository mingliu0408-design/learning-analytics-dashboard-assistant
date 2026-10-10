"""Immutable parent-execution receipt bound to the reservation sentinel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import PARENT_RECEIPT_SCHEMA, canonical_json_bytes, sha256_bytes
from .durable_no_replace_artifact_v1_2 import (
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)


def parent_receipt_descriptor_commitment_v1_2(
    *, relative_path: str, effective_contract_id: str, approved_head: str
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "schema_version": PARENT_RECEIPT_SCHEMA,
                "receipt_role": "IMMUTABLE_PARENT_EXECUTION_RECEIPT",
                "relative_path": relative_path,
                "effective_contract_id": effective_contract_id,
                "approved_head": approved_head,
                "publication": "ATOMIC_NO_REPLACE",
            }
        )
    )


def parent_execution_receipt_document_v1_2(
    *,
    execution_id: str,
    approved_head: str,
    effective_contract_id: str,
    sentinel_identity: Mapping[str, Any],
    sentinel_relative: str,
    state_relative: str,
    parent_receipt_relative: str,
    parent_nonce_commitment: str,
    parent_code_identity: str,
    fixed_real_paths: Mapping[str, str],
    input_identity_commitments: Mapping[str, Any],
    created_at: str,
    synthetic: bool,
) -> dict[str, Any]:
    return {
        "schema_version": PARENT_RECEIPT_SCHEMA,
        "receipt_role": "IMMUTABLE_PARENT_EXECUTION_RECEIPT",
        "execution_id": execution_id,
        "approved_head": approved_head,
        "effective_contract_id": effective_contract_id,
        "sentinel_identity": dict(sentinel_identity),
        "sentinel_relative": sentinel_relative,
        "state_relative": state_relative,
        "parent_receipt_relative": parent_receipt_relative,
        "parent_pid": os.getpid(),
        "parent_nonce_commitment": parent_nonce_commitment,
        "parent_code_identity": parent_code_identity,
        "fixed_real_paths": dict(fixed_real_paths),
        "input_identity_commitments": dict(input_identity_commitments),
        "created_at": created_at,
        "synthetic": bool(synthetic),
        "immutable": True,
    }


def persist_parent_execution_receipt_v1_2(
    path: Path,
    document: Mapping[str, Any],
    *,
    relative_path: str,
    sentinel_sha256: str,
) -> dict[str, Any]:
    value = canonical_json_bytes(dict(document))
    receipt = publish_no_replace_artifact_v1_2(
        path,
        value,
        relative_path=relative_path,
        stage="PARENT_EXECUTION_RECEIPT_PERSISTED",
        worker_role="RQ2_D4_PARENT_V1_2",
        worker_credential_commitment=None,
        artifact_role="IMMUTABLE_PARENT_EXECUTION_RECEIPT",
        schema_id=PARENT_RECEIPT_SCHEMA,
        record_count=1,
        approved_head=str(document["approved_head"]),
        execution_id=str(document["execution_id"]),
        effective_contract_id=str(document["effective_contract_id"]),
        code_identity=str(document["parent_code_identity"]),
        parent_state="INPUT_IDENTITIES_VERIFIED",
        schema_validator=json_object_validator(PARENT_RECEIPT_SCHEMA),
    )
    receipt["bound_sentinel_sha256"] = sentinel_sha256
    return receipt


def read_parent_execution_receipt_v1_2(path: Path) -> tuple[dict[str, Any], bytes]:
    before = os.lstat(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise ValueError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise ValueError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    value = b"".join(chunks)
    document = json.loads(value)
    if (
        document.get("schema_version") != PARENT_RECEIPT_SCHEMA
        or document.get("receipt_role") != "IMMUTABLE_PARENT_EXECUTION_RECEIPT"
        or document.get("immutable") is not True
    ):
        raise ValueError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return document, value


def parent_execution_receipt_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-parent-execution-receipt-contract-v1-2",
        "status": "FROZEN",
        "role": "IMMUTABLE_PARENT_EXECUTION_RECEIPT",
        "publication": "ATOMIC_NO_REPLACE",
        "binds_sentinel_identity": True,
        "binds_state_path": True,
        "binds_parent_nonce_commitment": True,
        "binds_parent_code_identity": True,
        "binds_fixed_paths": True,
        "binds_input_commitments": True,
        "mutable_after_creation": False,
    }
