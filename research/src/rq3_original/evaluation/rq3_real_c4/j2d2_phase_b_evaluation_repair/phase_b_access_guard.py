"""Write-ahead, hash-bound access to Phase-B scientific sources.

No network code, evaluation, or outcome aggregation is provided here. Callers
must obtain expected source hashes from frozen source manifests or the direct
authorization before reading controlled content. The ledger contains metadata
only and is closed permanently by the Phase-B completion receipt.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENTRY = HERE / "J2D2_PHASE_B_ENTRY_RECEIPT_V1.json"
LEDGER = HERE / "PHASE_B_CONTROLLED_ACCESS_LEDGER.jsonl"
ENTRY_SHA256 = "abf6fd158e68a406008bee838a74adc9d0cc3e87feef0ad649ea790c0feb44e4"
AUTHORITY_STATUS = "CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT"
AUTHORITY = ROOT / "evaluation/rq3_real_c4/j2d2_corrected_applicability_freeze/APPLICABILITY_V2_PHASE_A_AUTHORITY_RESOLUTION_V1.json"
AUTHORITY_SHA256 = "7cc28f87a1add40f2903ca884126d73613aaded67dffef186ab2e648a0bafb7e"
ROLES = frozenset({
    "candidate_response_source", "judge_request_source", "judge_result_source",
    "judge_attempt_journal", "judge_terminal_source", "judge_error_journal",
    "human_completed_rating", "human_completed_attestation", "human_blank_packet",
    "restricted_identity_mapping", "historical_support_code", "package_source",
    "generated_controlled_artifact", "preservation_hash_only",
})
USES = frozenset({
    "identity_and_structure_only", "payload_byte_preservation_and_applicability_replacement",
    "parser_v3_validity_and_result_eligibility_only", "human_v1_structure_and_attestation_validation",
    "human_applicability_impact_and_blank_amendment_construction",
    "offline_package_construction_or_validation", "immutable_source_integrity_only",
    "targeted_offline_test_inspection",
})


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_entry() -> dict:
    raw = ENTRY.read_bytes()
    if sha256(raw) != ENTRY_SHA256:
        raise RuntimeError("PHASE_B_ENTRY_RECEIPT_HASH_MISMATCH")
    receipt = json.loads(raw)
    if receipt["final_phase_a_authority_status"] != AUTHORITY_STATUS:
        raise RuntimeError("PHASE_A_NOT_CERTIFIED")
    if receipt["write_count"] != 1 or receipt["overwrite_permitted"] is not False:
        raise RuntimeError("ENTRY_NOT_WRITE_ONCE")
    if receipt["score_bearing_files_opened_before_receipt"] != 0 or receipt["candidate_response_files_opened_before_receipt"] != 0:
        raise RuntimeError("PRE_ENTRY_CONTROLLED_SOURCE_EXPOSURE")
    authority_raw = AUTHORITY.read_bytes()
    if sha256(authority_raw) != AUTHORITY_SHA256:
        raise RuntimeError("PHASE_A_AUTHORITY_HASH_MISMATCH")
    authority = json.loads(authority_raw)
    if authority["final_phase_a_status"] != AUTHORITY_STATUS or authority["original_receipt_status"] != "PRESERVED_QUALIFIED_BY_PHASE_A_BOUNDARY_INCIDENT":
        raise RuntimeError("PHASE_A_AUTHORITY_OR_INCIDENT_QUALIFICATION_MISMATCH")
    return receipt


def read_controlled(path: Path | str, *, expected_sha256: str, role: str, permitted_use: str) -> bytes:
    """Fsync authorization metadata before opening the specified source.

    The expected SHA-256 is supplied by an authoritative manifest. No preliminary
    content read is used to discover it. A mismatch fails closed without returning
    content to the caller. Every call has its own durable write-ahead record.
    """
    verify_entry()
    if (HERE / "J2D2_PHASE_B_COMPLETION_RECEIPT_V1.json").exists():
        raise RuntimeError("PHASE_B_CONTROLLED_ACCESS_ALREADY_SEALED")
    if role not in ROLES or permitted_use not in USES:
        raise ValueError("UNRECOGNISED_CONTROLLED_ACCESS_ROLE_OR_USE")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise ValueError("EXACT_SOURCE_SHA256_REQUIRED_BEFORE_ACCESS")
    source = Path(path).resolve(strict=True)
    if not source.is_file():
        raise ValueError("CONTROLLED_SOURCE_MUST_BE_FILE")
    record = {
        "schema_version": "PHASE_B_CONTROLLED_ACCESS_V1",
        "event": "READ_AUTHORIZED_BEFORE_SOURCE_OPEN",
        "entry_receipt_sha256": ENTRY_SHA256,
        "source_role": role,
        "source_path": str(source),
        "source_sha256": expected_sha256,
        "timestamp_utc": utc_now(),
        "permitted_use": permitted_use,
        "content_values_recorded": False,
    }
    fd = os.open(LEDGER, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
    with os.fdopen(fd, "a+b") as ledger:
        fcntl.flock(ledger.fileno(), fcntl.LOCK_EX)
        ledger.seek(0)
        previous_lines = ledger.read().splitlines()
        record["sequence"] = len(previous_lines) + 1
        record["previous_record_sha256"] = sha256(previous_lines[-1]) if previous_lines else None
        ledger.write((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode())
        ledger.flush()
        os.fsync(ledger.fileno())
        fcntl.flock(ledger.fileno(), fcntl.LOCK_UN)
    directory_fd = os.open(HERE, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    data = source.read_bytes()
    if sha256(data) != expected_sha256:
        raise RuntimeError("CONTROLLED_SOURCE_HASH_MISMATCH: " + str(source))
    return data


def read_json(path: Path | str, **kwargs):
    return json.loads(read_controlled(path, **kwargs))


def read_jsonl(path: Path | str, **kwargs) -> list[dict]:
    return [json.loads(line) for line in read_controlled(path, **kwargs).splitlines() if line.strip()]
