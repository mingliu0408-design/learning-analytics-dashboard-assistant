"""Future real D1 global state machine with no output-location override."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Mapping

from evaluation.capability_routing_rq2d0_v1.track_b_schema_contract import (
    parse_track_b_csv_bytes,
)
from evaluation.capability_routing_rq2d0_r1_v1.blinding_key_governance import (
    KEY_FILE_NAME,
    generate_fresh_key,
    persist_key,
)
from evaluation.capability_routing_rq2d0_r1_v1.durable_atomic_persistence import (
    atomic_write_durable,
)
from evaluation.capability_routing_rq2d0_r1_v1.durable_contamination_receipt import (
    payload_receipt,
    verify_payload_receipt,
)
from evaluation.capability_routing_rq2d0_r1_v1.legacy_escrow_contract import (
    ESCROW_FILE_NAME,
    build_legacy_escrow_rows,
    escrow_jsonl_bytes,
)
from evaluation.capability_routing_rq2d0_r1_v1.packet_generation_state_machine_v1_1 import (
    _build_packets,
    _jsonl_bytes,
    _raw_source_rows,
)
from evaluation.capability_routing_rq2d0_r2_v1.contamination_policy_v1_2 import (
    audit_hash_identities_v1_2,
    require_final_independence_v1_2,
    target_identity,
)
from evaluation.capability_routing_rq2d0_r2_v1.frozen_reference_authority import (
    load_frozen_contamination_reference_authority_v1_1,
)
from evaluation.capability_routing_rq2d0_r2_v1.track_b_grouping_identity import (
    grouping_hash_from_track_b_record,
    validate_track_b_contrast_groups,
)

from . import (
    EXECUTION_CONTRACT_ID,
    REAL_D1_ENVIRONMENT_AUTHORITY,
    REFERENCE_AUTHORITY_COMMITMENT,
    ROOT,
    TRACK_B_FILE_NAME,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
    TRACK_B_SIZE_BYTES,
    canonical_json_bytes,
    sha256_bytes,
)
from .fixed_d1_paths import (
    ResolvedRealD1FixedPathsV1_3,
    resolve_real_d1_fixed_paths_v1_3,
    validate_output_root_new_or_empty_v1_3,
)
from .global_one_shot_lock import (
    GLOBAL_RECEIPT_FIELDS,
    GlobalAccessAlreadyReserved,
    assert_global_access_unreserved_v1_3,
    build_real_global_reservation_payload_v1_3,
    global_receipt_from_lock,
    mark_global_failed_v1_3,
    read_global_lock_v1_3,
    require_global_receipt_match,
    reserve_global_track_b_access_v1_3,
    update_global_state_v1_3,
    utc_now_iso,
)
from .output_root_identity import (
    fixed_global_lock_identity_v1_3,
    fixed_output_root_identity_v1_3,
)


class StateMachineV1_3Error(RuntimeError):
    pass


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo_root, text=True, stderr=subprocess.STDOUT
    ).strip()


def _discover_repo_root() -> Path:
    output = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=ROOT,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()
    return Path(output)


def _verify_git_and_environment(repo_root: Path, approved_head: str) -> None:
    if (
        _git(repo_root, "rev-parse", "HEAD") != approved_head
        or _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
        or _git(repo_root, "remote")
        or _git(repo_root, "tag", "--list")
        or os.environ.get(REAL_D1_ENVIRONMENT_AUTHORITY) != "YES"
    ):
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")


def _verify_schema_authority(repo_root: Path, expected_sha256: str) -> None:
    path = (
        repo_root
        / "evaluation/capability_routing_rq2d0_v1/track_b_schema_authority_v1.json"
    )
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION") from exc
    if (
        stat.S_ISLNK(mode)
        or not stat.S_ISREG(mode)
        or sha256_bytes(path.read_bytes()) != expected_sha256
    ):
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")


def _validate_raw_source_preflight(source_path: Path) -> None:
    if source_path.name != TRACK_B_FILE_NAME:
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")
    try:
        stat_result = source_path.lstat()
    except FileNotFoundError as exc:
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION") from exc
    if (
        stat.S_ISLNK(stat_result.st_mode)
        or not stat.S_ISREG(stat_result.st_mode)
        or stat_result.st_size != TRACK_B_SIZE_BYTES
    ):
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_fixed_output_after_reservation(
    paths: ResolvedRealD1FixedPathsV1_3,
) -> None:
    if not paths.output_root.exists():
        os.mkdir(paths.output_root, 0o700)
        os.chmod(paths.output_root, 0o700, follow_symlinks=False)
        _fsync_directory(paths.output_root.parent)
    mode = paths.output_root.lstat().st_mode
    if (
        stat.S_ISLNK(mode)
        or not stat.S_ISDIR(mode)
        or stat.S_IMODE(mode) != 0o700
    ):
        raise StateMachineV1_3Error("BLOCKED_RQ2_D0_R3_FIXED_PATH_CONTRACT")
    refreshed = resolve_real_d1_fixed_paths_v1_3(paths.repo_root)
    if (
        refreshed.output_root != paths.output_root
        or refreshed.global_lock_path != paths.global_lock_path
        or fixed_output_root_identity_v1_3()
        != global_receipt_from_lock(
            read_global_lock_v1_3(paths.global_lock_path)
        )["output_root_identity"]
        or fixed_global_lock_identity_v1_3()
        != global_receipt_from_lock(
            read_global_lock_v1_3(paths.global_lock_path)
        )["global_lock_identity"]
    ):
        raise StateMachineV1_3Error("BLOCKED_RQ2_D0_R3_OUTPUT_IDENTITY")


def _source_record_identity_hash(raw_id: str) -> str:
    return hashlib.sha256(
        b"RQ2_SOURCE_RECORD_IDENTITY_V1\x00" + raw_id.encode("utf-8")
    ).hexdigest()


def _global_receipt(lock: Mapping[str, Any]) -> dict[str, Any]:
    return {field: lock[field] for field in GLOBAL_RECEIPT_FIELDS}


def _safe_manifest(
    *, schema_version: str, record_count: int, global_receipt: Mapping[str, Any]
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": schema_version,
            "record_count": record_count,
            "global_receipt": dict(global_receipt),
        }
    )


def _persist(
    payloads: dict[str, tuple[Path, bytes, int]],
    role: str,
    path: Path,
    payload: bytes,
    count: int,
) -> None:
    atomic_write_durable(path, payload, mode=0o600)
    payloads[role] = (path, payload, count)


def _execute_after_reservation(
    source_path: Path,
    paths: ResolvedRealD1FixedPathsV1_3,
    *,
    authority: Any,
) -> dict[str, Any]:
    lock_path = paths.global_lock_path
    raw_open_count = 0
    raw_read_count = 0
    try:
        _create_fixed_output_after_reservation(paths)
        key = generate_fresh_key()
        key_receipt = persist_key(paths.output_root / KEY_FILE_NAME, key)
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="GLOBAL_RESERVED",
            next_state="KEY_PERSISTED",
            updates={
                "key_commitment": key_receipt["key_commitment"],
                "key_size_bytes": key_receipt["key_length_bytes"],
                "key_file_mode": key_receipt["file_mode_octal"],
            },
        )
        lock = update_global_state_v1_3(
            lock_path, expected_state="KEY_PERSISTED", next_state="ARMED"
        )
        with source_path.open("rb") as handle:
            raw_open_count = 1
            raw = handle.read()
            raw_read_count = 1
        if sha256_bytes(raw) != TRACK_B_SHA256 or len(raw) != TRACK_B_SIZE_BYTES:
            raise StateMachineV1_3Error("raw source identity mismatch")
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="ARMED",
            next_state="OPENED",
            updates={
                "raw_open_count": raw_open_count,
                "raw_read_count": raw_read_count,
                "raw_asset_sha256": sha256_bytes(raw),
                "raw_asset_size_bytes": len(raw),
            },
        )
        records, schema_report = parse_track_b_csv_bytes(
            raw, mode="D1_AUTHORISED_RAW"
        )
        source_rows = _raw_source_rows(raw)
        if len(records) != TRACK_B_RECORD_COUNT or len(source_rows) != TRACK_B_RECORD_COUNT:
            raise StateMachineV1_3Error("Track-B record count mismatch")
        grouping = validate_track_b_contrast_groups(records)
        receipt = _global_receipt(lock)
        payloads: dict[str, tuple[Path, bytes, int]] = {}

        authority_payload = canonical_json_bytes(
            {
                "schema_version": "track-b-reference-authority-receipt-v1.3",
                "status": "PASS",
                "global_receipt": receipt,
                "exact_reference_receipt": authority.safe_receipt(),
            }
        )
        _persist(
            payloads,
            "reference_authority_receipt",
            paths.output_root / "track_b_reference_authority_receipt_v1_3.json",
            authority_payload,
            authority.bundle_record_count,
        )
        case_bank = _jsonl_bytes(records)
        case_path = paths.output_root / "track_b_canonical_case_bank_v1.jsonl"
        _persist(payloads, "canonical_case_bank", case_path, case_bank, 48)
        case_manifest = _safe_manifest(
            schema_version="track-b-canonical-case-bank-manifest-v1.3",
            record_count=48,
            global_receipt=receipt,
        )
        _persist(
            payloads,
            "canonical_case_bank_manifest",
            paths.output_root / "track_b_canonical_case_bank_manifest_v1_3.json",
            case_manifest,
            48,
        )
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="OPENED",
            next_state="CASE_BANK_PERSISTED",
        )

        escrow = escrow_jsonl_bytes(build_legacy_escrow_rows(source_rows))
        _persist(
            payloads,
            "hidden_legacy_escrow",
            paths.output_root / ESCROW_FILE_NAME,
            escrow,
            48,
        )
        escrow_manifest = _safe_manifest(
            schema_version="track-b-legacy-escrow-manifest-v1.3",
            record_count=48,
            global_receipt=receipt,
        )
        _persist(
            payloads,
            "legacy_escrow_manifest",
            paths.output_root / "track_b_legacy_escrow_manifest_v1_3.json",
            escrow_manifest,
            48,
        )
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="CASE_BANK_PERSISTED",
            next_state="LEGACY_ESCROW_PERSISTED",
        )

        identities = [
            target_identity(
                query=str(record["effective_current_query"]),
                history=record["effective_conversation_history"],
                source_record_identity_hash=_source_record_identity_hash(
                    str(record["raw_case_id"])
                ),
                family_or_group_hash=grouping_hash_from_track_b_record(record),
            )
            for record in records
        ]
        audit = audit_hash_identities_v1_2(identities, authority.reference_rows)
        audit.update(
            {
                "global_receipt": receipt,
                "reference_authority_commitment": authority.authority_commitment,
                "grouping_validation": grouping,
            }
        )
        audit_payload = canonical_json_bytes(audit)
        _persist(
            payloads,
            "contamination_audit_summary",
            paths.output_root / "track_b_contamination_audit_summary_v1_3.json",
            audit_payload,
            48,
        )
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="LEGACY_ESCROW_PERSISTED",
            next_state="CONTAMINATION_AUDIT_PERSISTED",
            updates={
                "hard_conflict_count": audit["hard_conflict_count"],
                "sensitivity_overlap_count": audit["sensitivity_overlap_count"],
                "contamination_status": audit["status"],
            },
        )
        require_final_independence_v1_2(audit)

        packet_a, packet_b, packet_seed, mapping = _build_packets(records, key)
        packet = json.loads(packet_seed)
        packet.update(
            {
                "schema_version": "track-b-packet-manifest-v1.3",
                "global_receipt": receipt,
                "key_commitment": lock["key_commitment"],
                "contamination_audit_sha256": sha256_bytes(audit_payload),
                "legacy_escrow_sha256": sha256_bytes(escrow),
            }
        )
        packet_payload = canonical_json_bytes(packet)
        _persist(
            payloads,
            "reviewer_a_packet",
            paths.output_root / "reviewer_a_track_b_capability_review_v1.csv",
            packet_a,
            48,
        )
        _persist(
            payloads,
            "reviewer_b_packet",
            paths.output_root / "reviewer_b_track_b_capability_review_v1.csv",
            packet_b,
            48,
        )
        for reviewer, packet_bytes in (("a", packet_a), ("b", packet_b)):
            reviewer_manifest = canonical_json_bytes(
                {
                    "schema_version": "track-b-reviewer-packet-manifest-v1.3",
                    "reviewer": reviewer.upper(),
                    "packet_sha256": sha256_bytes(packet_bytes),
                    "record_count": 48,
                    "global_receipt": receipt,
                }
            )
            _persist(
                payloads,
                f"reviewer_{reviewer}_packet_manifest",
                paths.output_root
                / f"reviewer_{reviewer}_track_b_packet_manifest_v1_3.json",
                reviewer_manifest,
                48,
            )
        _persist(
            payloads,
            "packet_manifest",
            paths.output_root / "track_b_packet_manifest_v1_3.json",
            packet_payload,
            48,
        )
        _persist(
            payloads,
            "raw_to_blinded_mapping",
            paths.output_root / "track_b_opaque_mapping_v1.jsonl",
            mapping,
            48,
        )
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="CONTAMINATION_AUDIT_PERSISTED",
            next_state="REVIEW_PACKETS_PERSISTED",
        )

        receipts = {
            role: payload_receipt(payload, record_count=count)
            for role, (_, payload, count) in sorted(payloads.items())
        }
        for role, (path, _, _) in payloads.items():
            verify_payload_receipt(path, receipts[role])
        current_authority = load_frozen_contamination_reference_authority_v1_1()
        if current_authority.authority_commitment != authority.authority_commitment:
            raise StateMachineV1_3Error(
                "BLOCKED_RQ2_D1_GLOBAL_RECEIPT_MISMATCH"
            )
        authoritative = read_global_lock_v1_3(lock_path)
        for value in (
            json.loads(case_manifest)["global_receipt"],
            json.loads(escrow_manifest)["global_receipt"],
            audit["global_receipt"],
            packet["global_receipt"],
            json.loads(
                (
                    paths.output_root
                    / "reviewer_a_track_b_packet_manifest_v1_3.json"
                ).read_text(encoding="utf-8")
            )["global_receipt"],
            json.loads(
                (
                    paths.output_root
                    / "reviewer_b_track_b_packet_manifest_v1_3.json"
                ).read_text(encoding="utf-8")
            )["global_receipt"],
        ):
            require_global_receipt_match(value, authoritative)
        lock = update_global_state_v1_3(
            lock_path,
            expected_state="REVIEW_PACKETS_PERSISTED",
            next_state="COMPLETED",
            updates={
                "persisted": True,
                "schema_validation_status": schema_report["status"],
                "outputs": receipts,
                "completed_global_receipt": receipt,
                "human_labels_formed": False,
                "raw_open_count": raw_open_count,
                "raw_read_count": raw_read_count,
            },
        )
        return lock
    except Exception as exc:
        try:
            mark_global_failed_v1_3(
                lock_path,
                failure_stage=str(read_global_lock_v1_3(lock_path).get("state")),
                failure_code=type(exc).__name__,
                failure_timestamp=utc_now_iso(),
                raw_open_count=raw_open_count,
                raw_read_count=raw_read_count,
            )
        except GlobalAccessAlreadyReserved:
            pass
        raise


def execute_real_d1_one_shot_v1_3(
    source_path: Path,
    *,
    approved_head: str,
    schema_authority_sha256: str,
) -> dict[str, Any]:
    """Future real entry: fixed output and global lock are internal constants."""

    repo_root = _discover_repo_root()
    _verify_git_and_environment(repo_root, approved_head)
    paths = resolve_real_d1_fixed_paths_v1_3(repo_root)
    validate_output_root_new_or_empty_v1_3(paths.output_root)
    _verify_schema_authority(repo_root, schema_authority_sha256)
    authority = load_frozen_contamination_reference_authority_v1_1()
    if authority.authority_commitment != REFERENCE_AUTHORITY_COMMITMENT:
        raise StateMachineV1_3Error("BLOCKED_RQ2_D1_PREARM_VALIDATION")
    _validate_raw_source_preflight(source_path)
    assert_global_access_unreserved_v1_3(paths.global_lock_path)
    reservation = build_real_global_reservation_payload_v1_3(
        approved_head=approved_head,
        safe_schema_authority_sha256=schema_authority_sha256,
        reference_authority_commitment=authority.authority_commitment,
        reservation_created_at=utc_now_iso(),
    )
    reserve_global_track_b_access_v1_3(paths, reservation)
    return _execute_after_reservation(source_path, paths, authority=authority)


def state_machine_contract_document_v1_3() -> dict[str, Any]:
    return {
        "schema_version": "track-b-packet-generation-state-machine-v1.3",
        "status": "FROZEN_BEFORE_REAL_D1",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "real_entry_point": "execute_real_d1_one_shot_v1_3",
        "global_lock_is_only_consumed_access_authority": True,
        "per_output_consumed_lock_permitted": False,
        "prearm_order": [
            "approved HEAD",
            "clean worktree and index",
            "explicit D1 environment authority",
            "resolve and validate fixed paths",
            "validate fixed output root new-or-empty",
            "verify safe schema authority",
            "load exact contamination authority",
            "calculate exact authority commitment",
            "validate raw source regular non-symlink",
            "verify no global lock exists",
            "atomically create durable GLOBAL_RESERVED lock",
            "create fixed output root if absent",
            "generate fresh 32-byte key",
            "durably persist key",
            "update global lock to KEY_PERSISTED",
            "update global lock to ARMED",
            "raw open",
            "raw read",
            "continue D1 state machine",
        ],
        "pre_reservation_failure_global_lock_count": 0,
        "pre_reservation_failure_key_count": 0,
        "pre_reservation_failure_raw_open_count": 0,
        "pre_reservation_failure_raw_read_count": 0,
        "post_reservation_failure_state": "FAILED",
        "global_lock_retained_after_failure": True,
        "global_lock_retained_after_completion": True,
        "retry_permitted": False,
        "post_completed_write_permitted": False,
        "all_future_manifests_bind_global_receipt": True,
        "real_d1_executed_in_rq2_d0_r3": False,
    }
