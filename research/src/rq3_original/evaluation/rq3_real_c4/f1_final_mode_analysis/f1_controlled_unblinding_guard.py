"""Verify the sealed entry and durably log metadata before every identity read."""
from __future__ import annotations

import csv
import fcntl
import io
import json
import os
from pathlib import Path

from f1_common import (HERE, ROOT, RI, RECEIPT, LEDGER, FINAL_RECEIPT, canonical_bytes,
                       now, read_json, sha, sha_bytes, fsync_dir)


def verify_entry():
    from f1_entry_binding import ENTRY_RECEIPT_SHA256
    if sha(RECEIPT) != ENTRY_RECEIPT_SHA256:
        raise RuntimeError("F1_ENTRY_RECEIPT_HASH_MISMATCH")
    receipt = read_json(RECEIPT)
    if receipt["mode_mappings_opened_before_receipt"] != 0 or receipt["system_comparisons_computed_before_receipt"] != 0:
        raise RuntimeError("F1_ENTRY_NOT_PRE_UNBLINDING")
    for name, digest in receipt["sealed_implementation_hashes"].items():
        if sha(HERE / name) != digest:
            raise RuntimeError("F1_SEALED_IMPLEMENTATION_HASH_MISMATCH")
    for name, digest in receipt["sealed_metadata_hashes"].items():
        if sha(HERE / name) != digest:
            raise RuntimeError("F1_SEALED_METADATA_HASH_MISMATCH")
    return receipt, ENTRY_RECEIPT_SHA256


def controlled_bytes(path, purpose, reader_script):
    """Purpose and reader are stable labels; the ledger never receives data values."""
    if FINAL_RECEIPT.exists():
        raise RuntimeError("F1_ACCESS_CLOSED_BY_FINAL_FREEZE")
    if purpose not in {"SCHEMA_INSPECTION", "IDENTITY_JOIN", "SOURCE_INTEGRITY_TEST",
                       "PAIR_REGISTRY_TEST", "MECHANISM_SYNTHESIS", "COHORT_IDENTITY_VERIFICATION"}:
        raise RuntimeError("F1_UNDECLARED_ACCESS_PURPOSE")
    if not reader_script.endswith(".py") or "/" in reader_script or "\\" in reader_script:
        raise RuntimeError("F1_INVALID_READER_LABEL")
    receipt, receipt_hash = verify_entry()
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT) or path.suffix not in {".csv", ".json", ".jsonl", ".md"}:
        raise RuntimeError("F1_SOURCE_OUTSIDE_FROZEN_ARTIFACT_SCOPE")
    relative = str(path.relative_to(ROOT))
    snapshot = read_json(HERE / "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json")
    expected = snapshot["files"].get(relative)
    if expected is None:
        if path.parent != RI or not path.name.startswith("c4_real_f1_"):
            raise RuntimeError("F1_SOURCE_NOT_IN_PRE_UNBLINDING_SNAPSHOT")
        metadata = read_json(HERE / "F1_RESTRICTED_ANALYSIS_METADATA_V1.json")
        expected = next((x["sha256"] for x in metadata["files"] if x["filename"] == path.name), None)
        if expected is None:
            raise RuntimeError("F1_RESTRICTED_OUTPUT_WITHOUT_FROZEN_METADATA")
    fd = os.open(LEDGER, os.O_RDWR | os.O_APPEND)
    with os.fdopen(fd, "a+b") as ledger:
        fcntl.flock(ledger.fileno(), fcntl.LOCK_EX)
        ledger.seek(0)
        lines = ledger.read().splitlines()
        record = {
            "schema_version": "F1_CONTROLLED_UNBLINDING_ACCESS_V1",
            "access_sequence": len(lines) + 1,
            "timestamp_utc": now(),
            "entry_receipt_sha256": receipt_hash,
            "source_path": relative,
            "source_sha256": expected,
            "purpose": purpose,
            "reader_script": reader_script,
            "access_operation": "READ_FROZEN_ARTIFACT_AFTER_FSYNC_RECORD",
            "previous_record_sha256": sha_bytes(lines[-1]) if lines else None,
        }
        ledger.write(canonical_bytes(record) + b"\n")
        ledger.flush()
        os.fsync(ledger.fileno())
        fsync_dir(LEDGER.parent)
        # The durable access record exists before any source bytes are decoded.
        content = path.read_bytes()
        if sha_bytes(content) != expected:
            raise RuntimeError("F1_CONTROLLED_SOURCE_HASH_MISMATCH")
        fcntl.flock(ledger.fileno(), fcntl.LOCK_UN)
    return content


def controlled_json(path, purpose, reader_script):
    return json.loads(controlled_bytes(path, purpose, reader_script))


def controlled_jsonl(path, purpose, reader_script):
    return [json.loads(x) for x in controlled_bytes(path, purpose, reader_script).splitlines() if x.strip()]


def controlled_csv(path, purpose, reader_script):
    return list(csv.DictReader(io.StringIO(controlled_bytes(path, purpose, reader_script).decode("utf-8-sig"))))
