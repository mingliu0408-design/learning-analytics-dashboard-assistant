"""Receipt bindings required before the future D1 lock may become COMPLETED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class DurableReceiptError(RuntimeError):
    pass


def payload_receipt(payload: bytes, *, record_count: int) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "record_count": int(record_count),
    }


def verify_payload_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    if not path.is_file() or path.is_symlink():
        raise DurableReceiptError("receipt target is missing or unsafe")
    payload = path.read_bytes()
    if (
        hashlib.sha256(payload).hexdigest() != receipt.get("sha256")
        or len(payload) != receipt.get("size_bytes")
    ):
        raise DurableReceiptError("receipt hash or size mismatch")
    suffix = path.suffix.casefold()
    if suffix == ".jsonl":
        count = sum(1 for line in payload.splitlines() if line.strip())
    elif suffix == ".csv":
        count = max(0, len(payload.decode("utf-8-sig").splitlines()) - 1)
    elif suffix == ".json":
        json.loads(payload)
        count = int(receipt.get("record_count", 1))
    else:
        count = int(receipt.get("record_count", 0))
    if count != receipt.get("record_count"):
        raise DurableReceiptError("receipt record count mismatch")


def durable_receipt_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-durable-receipt-contract-v1",
        "status": "FROZEN_BEFORE_D1",
        "persistence_sequence": [
            "exclusive temporary file",
            "write",
            "flush",
            "fsync file",
            "os.replace",
            "fsync parent directory",
            "reread",
            "verify SHA-256",
            "verify size",
            "verify schema",
        ],
        "completed_lock_receipts": [
            "contamination reference manifest",
            "canonical case bank",
            "raw-ID/blinded-ID mapping",
            "hidden legacy escrow",
            "contamination audit summary",
            "Reviewer A packet",
            "Reviewer B packet",
            "packet manifest",
        ],
        "contamination_binding": [
            "reference manifest SHA",
            "reference bundle SHA",
            "audit summary SHA",
            "audit summary size",
            "hard conflict count",
            "sensitivity overlap count",
        ],
        "failure_lock_preserved": True,
        "retry_permitted": False,
        "post_completed_write_permitted": False,
    }
