"""Fresh 32-byte D1 blinding-key persistence and domain-separated IDs."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets
from typing import Iterable

from .durable_atomic_persistence import atomic_write_durable


KEY_LENGTH_BYTES = 32
KEY_FILE_NAME = ".track_b_blinding_key_v1.bin"
COMMITMENT_DOMAIN = b"RQ2_TRACK_B_BLIND_KEY_V1\x00"
OPAQUE_ID_DOMAIN = b"RQ2_TRACK_B_REVIEW_CASE_V1\x00"


class BlindingKeyError(RuntimeError):
    pass


def generate_fresh_key() -> bytes:
    key = secrets.token_bytes(KEY_LENGTH_BYTES)
    if len(key) != KEY_LENGTH_BYTES:
        raise BlindingKeyError("fresh blinding key length mismatch")
    return key


def key_commitment(key: bytes) -> str:
    if len(key) != KEY_LENGTH_BYTES:
        raise BlindingKeyError("blinding key must contain exactly 32 bytes")
    return hashlib.sha256(COMMITMENT_DOMAIN + key).hexdigest()


def persist_key(path: Path, key: bytes) -> dict[str, object]:
    commitment = key_commitment(key)
    receipt = atomic_write_durable(path, key, mode=0o600)
    permissions = os.stat(path, follow_symlinks=False).st_mode & 0o777
    if permissions != 0o600 or path.read_bytes() != key:
        raise BlindingKeyError("blinding key persistence verification failed")
    return {
        "key_commitment": commitment,
        "key_length_bytes": len(key),
        "file_mode_octal": "0600",
        "persisted": True,
        "reread_verified": True,
        "raw_key_emitted": False,
        "durable_size_bytes": receipt["size_bytes"],
    }


def opaque_review_id(raw_scenario_id: str, key: bytes) -> str:
    key_commitment(key)
    digest = hmac.new(
        key, OPAQUE_ID_DOMAIN + str(raw_scenario_id).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return "TBV1-" + digest[:16].upper()


def build_opaque_ids(raw_ids: Iterable[str], key: bytes) -> list[str]:
    values = [opaque_review_id(value, key) for value in raw_ids]
    if len(values) != len(set(values)):
        raise BlindingKeyError("opaque review ID collision")
    return values


def assert_real_mode_key_input(*, supplied_key: bytes | None) -> None:
    if supplied_key is not None:
        raise BlindingKeyError("real D1 rejects fixed or externally supplied keys")


def blinding_key_contract_document() -> dict[str, object]:
    return {
        "schema_version": "track-b-blinding-key-contract-v1",
        "status": "FROZEN_BEFORE_D1",
        "real_key_generation": "secrets.token_bytes(32)",
        "key_length_bytes": KEY_LENGTH_BYTES,
        "key_file": "LOCAL_ONLY_MODE_0600",
        "durability": [
            "file_fsync",
            "parent_directory_fsync",
            "reread_verification",
        ],
        "commitment_algorithm": (
            "SHA256(b'RQ2_TRACK_B_BLIND_KEY_V1\\x00' + key_bytes)"
        ),
        "opaque_id_algorithm": (
            "TBV1- + first16UpperHex(HMAC-SHA256(key, "
            "b'RQ2_TRACK_B_REVIEW_CASE_V1\\x00' + raw_scenario_id))"
        ),
        "opaque_id_collision_check_count": 48,
        "fixed_key_permitted_in_real_mode": False,
        "environment_reusable_key_permitted": False,
        "raw_key_in_git_review_logs_stdout_or_safe_json": False,
    }
