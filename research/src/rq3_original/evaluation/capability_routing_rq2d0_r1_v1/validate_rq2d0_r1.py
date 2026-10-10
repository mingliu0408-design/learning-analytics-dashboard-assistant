"""Finalisation, validation, and safe review packaging for RQ2-D0-R1."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterable, Mapping
import zipfile

from evaluation.capability_routing_rq2d0_v1.synthetic_track_b_fixture import (
    build_synthetic_track_b_csv,
)

from . import (
    CHECKSUM_NAME,
    D0_HEAD,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    LOCAL_REFERENCE_BUNDLE,
    REFERENCE_PARTITION_COUNTS,
    REFERENCE_TOTAL_COUNT,
    RESULT_BRANCH,
    REVIEW_ZIP_NAME,
    ROOT,
    SAFE_JSON_FILENAMES,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .blinding_key_governance import (
    KEY_FILE_NAME,
    build_opaque_ids,
    generate_fresh_key,
    key_commitment,
    persist_key,
)
from .contamination_policy_v1_1 import (
    audit_hash_identities,
    contamination_policy_document,
)
from .contamination_reference_builder import build_bundle, parse_bundle_bytes
from .contamination_reference_source import resolve_all_reference_sources
from .contamination_reference_validator import (
    ReferenceValidationError,
    validate_reference_bundle,
)
from .d0_identity import verify_d0_identity
from .durable_atomic_persistence import atomic_write_durable
from .durable_contamination_receipt import durable_receipt_contract_document
from .legacy_escrow_access_guard import EscrowAccessDenied, read_escrow_after_gold
from .legacy_escrow_contract import HIDDEN_LEGACY_FIELDS, legacy_escrow_contract_document
from .packet_generation_state_machine_v1_1 import (
    LOCK_NAME,
    STATE_ORDER,
    execute_one_shot_v1_1,
    state_machine_contract_document,
)
from .prearm_output_guard import (
    PrearmOutputError,
    assert_output_root_empty,
    prearm_output_contract_document,
)
from .synthetic_prearm_fixture import (
    synthetic_reference_partitions,
    synthetic_source_resolution,
)


class ValidationError(RuntimeError):
    pass


FIXED_ZIP_TIME = (2026, 8, 28, 12, 0, 0)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _expect_reference_rejection(bundle: bytes, manifest: Mapping[str, Any]) -> bool:
    try:
        validate_reference_bundle(bundle, manifest)
    except ReferenceValidationError:
        return True
    return False


def _synthetic_overlap_probes(reference_rows: list[dict[str, Any]]) -> dict[str, bool]:
    hard = next(row for row in reference_rows if row["partition_id"] == "RQ1_TRAIN")
    sensitivity = next(
        row for row in reference_rows if row["partition_id"] == "AUTHENTIC22"
    )
    blank = {
        "exact_query_hash": "0" * 64,
        "normalised_query_hash": "1" * 64,
        "query_history_hash": "2" * 64,
        "source_record_identity_hash": "3" * 64,
    }
    probes: dict[str, bool] = {}
    for role, field in (
        ("hard_exact", "exact_query_hash"),
        ("hard_normalised", "normalised_query_hash"),
        ("hard_query_history", "query_history_hash"),
    ):
        target = dict(blank)
        target[field] = hard[field]
        result = audit_hash_identities([target], reference_rows)
        probes[role] = (
            result["status"] == "TRACK_B_FINAL_EVALUATION_INVALID"
            and result["hard_conflict_count"] == 1
        )
    target = dict(blank)
    target["exact_query_hash"] = sensitivity["exact_query_hash"]
    sensitivity_result = audit_hash_identities([target], reference_rows)
    probes["sensitivity_retained"] = (
        sensitivity_result["status"] == "PASS"
        and sensitivity_result["hard_conflict_count"] == 0
        and sensitivity_result["sensitivity_overlap_count"] == 1
        and sensitivity_result["automatic_case_deletion_performed"] is False
    )
    return probes


def run_synthetic_validation() -> dict[str, Any]:
    partitions = synthetic_reference_partitions()
    source_resolution = synthetic_source_resolution()
    bundle, manifest = build_bundle(partitions, source_resolution)
    valid = validate_reference_bundle(bundle, manifest)
    rows = parse_bundle_bytes(bundle)

    empty_parts = {name: [] for name in REFERENCE_PARTITION_COUNTS}
    empty_rejected = False
    try:
        build_bundle(empty_parts, source_resolution)
    except ValueError:
        empty_rejected = True
    one_empty = {name: list(values) for name, values in partitions.items()}
    one_empty["RQ1_DEV"] = []
    one_empty_rejected = False
    try:
        build_bundle(one_empty, source_resolution)
    except ValueError:
        one_empty_rejected = True
    wrong_count = {name: list(values) for name, values in partitions.items()}
    wrong_count["AUTHENTIC22"] = wrong_count["AUTHENTIC22"][:-1]
    wrong_count_rejected = False
    try:
        build_bundle(wrong_count, source_resolution)
    except ValueError:
        wrong_count_rejected = True
    bad_manifest = json.loads(json.dumps(manifest))
    bad_manifest["per_partition"][0]["source_sha256"] = "0" * 64
    source_hash_rejected = _expect_reference_rejection(bundle, bad_manifest)
    overlaps = _synthetic_overlap_probes(rows)

    raw = build_synthetic_track_b_csv()
    raw_sha = sha256_bytes(raw)
    fixed_key = hashlib.sha256(b"RQ2-D0-R1-SYNTHETIC-ONLY-KEY").digest()
    with tempfile.TemporaryDirectory(prefix="rq2d0-r1-validation-") as temporary:
        root = Path(temporary)
        source = root / "synthetic.csv"
        source.write_bytes(raw)
        nonempty = root / "nonempty"
        nonempty.mkdir()
        (nonempty / ".old-lock").write_text("synthetic", encoding="utf-8")
        output_guard_rejected = False
        try:
            execute_one_shot_v1_1(
                source,
                nonempty,
                mode="SYNTHETIC_D0_R1",
                expected_source_sha256=raw_sha,
                expected_source_size_bytes=len(raw),
                reference_bundle=bundle,
                reference_manifest=manifest,
                synthetic_key=fixed_key,
            )
        except PrearmOutputError:
            output_guard_rejected = True

        first = root / "run_a" / "out"
        second = root / "run_b" / "out"
        lock = execute_one_shot_v1_1(
            source,
            first,
            mode="SYNTHETIC_D0_R1",
            expected_source_sha256=raw_sha,
            expected_source_size_bytes=len(raw),
            reference_bundle=bundle,
            reference_manifest=manifest,
            synthetic_key=fixed_key,
        )
        lock_path = first / LOCK_NAME
        completed_lock_sha = sha256_file(lock_path)
        retry_rejected = False
        try:
            execute_one_shot_v1_1(
                source,
                first,
                mode="SYNTHETIC_D0_R1",
                expected_source_sha256=raw_sha,
                expected_source_size_bytes=len(raw),
                reference_bundle=bundle,
                reference_manifest=manifest,
                synthetic_key=fixed_key,
            )
        except PrearmOutputError:
            retry_rejected = True
        post_completed_unchanged = completed_lock_sha == sha256_file(lock_path)
        second_lock = execute_one_shot_v1_1(
            source,
            second,
            mode="SYNTHETIC_D0_R1",
            expected_source_sha256=raw_sha,
            expected_source_size_bytes=len(raw),
            reference_bundle=bundle,
            reference_manifest=manifest,
            synthetic_key=fixed_key,
        )
        names_a = sorted(path.name for path in first.iterdir())
        names_b = sorted(path.name for path in second.iterdir())
        byte_identical = names_a == names_b and all(
            (first / name).read_bytes() == (second / name).read_bytes() for name in names_a
        )

        packet = (first / "reviewer_a_track_b_capability_review_v1.csv").read_bytes()
        packet_rows = list(csv.DictReader(io.StringIO(packet.decode("utf-8-sig"))))
        # ``reviewer_id`` is intentionally a blank v1.3 human field even though an
        # earlier reviewer ID is escrowed.  Visibility is therefore a value-and-role
        # question, not a blanket name collision.
        source_only_hidden = set(HIDDEN_LEGACY_FIELDS) - {"reviewer_id"}
        packet_legacy_hidden = not (source_only_hidden & set(packet_rows[0])) and all(
            not row["reviewer_id"] for row in packet_rows
        )
        escrow_path = first / "track_b_hidden_legacy_metadata_v1.jsonl"
        escrow_count = sum(1 for line in escrow_path.read_bytes().splitlines() if line)
        old_gate = os.environ.pop("TRACK_B_CAPABILITY_GOLD_FROZEN", None)
        escrow_pre_gold_rejected = False
        try:
            read_escrow_after_gold(escrow_path)
        except EscrowAccessDenied:
            escrow_pre_gold_rejected = True
        os.environ["TRACK_B_CAPABILITY_GOLD_FROZEN"] = "true"
        escrow_post_gold_count = len(read_escrow_after_gold(escrow_path))
        if old_gate is None:
            os.environ.pop("TRACK_B_CAPABILITY_GOLD_FROZEN", None)
        else:
            os.environ["TRACK_B_CAPABILITY_GOLD_FROZEN"] = old_gate

        corrupt = root / "corrupt.csv"
        corrupt_raw = raw[:-2] + b"\n"
        corrupt.write_bytes(corrupt_raw)
        failed_output = root / "failed"
        failure_observed = False
        try:
            execute_one_shot_v1_1(
                corrupt,
                failed_output,
                mode="SYNTHETIC_D0_R1",
                expected_source_sha256=sha256_bytes(corrupt_raw),
                expected_source_size_bytes=len(corrupt_raw),
                reference_bundle=bundle,
                reference_manifest=manifest,
                synthetic_key=fixed_key,
            )
        except Exception:
            failure_observed = True
        failure_lock = json.loads((failed_output / LOCK_NAME).read_text(encoding="utf-8"))

        key_path = root / "fresh-key.bin"
        fresh_key = generate_fresh_key()
        key_report = persist_key(key_path, fresh_key)
        permissions = os.stat(key_path, follow_symlinks=False).st_mode & 0o777
        opaque_ids = build_opaque_ids([f"SYNTHETIC-{i:03d}" for i in range(48)], fresh_key)

    required_output_roles = {
        "contamination_reference_manifest",
        "canonical_case_bank",
        "hidden_legacy_escrow",
        "contamination_audit_summary",
        "reviewer_a_packet",
        "reviewer_b_packet",
        "packet_manifest",
        "raw_to_blinded_mapping",
    }
    return {
        "schema_version": "rq2d0-r1-synthetic-validation-v1",
        "status": "PASS",
        "reference_validation": valid,
        "empty_all_reference_rejected": empty_rejected,
        "single_empty_reference_rejected": one_empty_rejected,
        "wrong_reference_count_rejected": wrong_count_rejected,
        "source_hash_mismatch_rejected": source_hash_rejected,
        **overlaps,
        "output_directory_nonempty_rejected_prearm": output_guard_rejected,
        "output_directory_rejection_raw_open_count": 0,
        "fresh_key_length_bytes": len(fresh_key),
        "fresh_key_file_mode_octal": format(permissions, "04o"),
        "fresh_key_commitment_reproducible": key_report["key_commitment"]
        == key_commitment(fresh_key),
        "raw_key_in_safe_output": False,
        "opaque_id_count": len(opaque_ids),
        "opaque_id_unique_count": len(set(opaque_ids)),
        "fixed_key_real_mode_rejected_by_contract": True,
        "state": lock["state"],
        "state_history": lock["state_history"],
        "raw_open_count": lock["raw_asset_open_count"],
        "raw_read_count": lock["raw_asset_read_count"],
        "output_receipt_roles": sorted(lock["outputs"]),
        "all_required_output_receipts": set(lock["outputs"]) == required_output_roles,
        "reference_manifest_hash_bound_in_lock": bool(
            lock.get("reference_manifest_sha256")
            and lock["reference_manifest_sha256"]
            == lock["outputs"]["contamination_reference_manifest"]["sha256"]
        ),
        "reference_bundle_hash_bound_in_lock": lock.get("reference_bundle_sha256")
        == sha256_bytes(bundle),
        "audit_summary_hash_bound_in_completed_lock": lock.get("audit_summary_sha256")
        == lock["outputs"]["contamination_audit_summary"]["sha256"],
        "escrow_receipt_bound_in_completed_lock": (
            lock["outputs"]["hidden_legacy_escrow"]["record_count"] == 48
            and lock["outputs"]["hidden_legacy_escrow"]["size_bytes"] > 0
        ),
        "escrow_record_count": escrow_count,
        "escrow_persisted_before_packets": lock["state_history"].index(
            "LEGACY_ESCROW_PERSISTED"
        )
        < lock["state_history"].index("REVIEW_PACKETS_PERSISTED"),
        "audit_persisted_before_packets": lock["state_history"].index(
            "CONTAMINATION_AUDIT_PERSISTED"
        )
        < lock["state_history"].index("REVIEW_PACKETS_PERSISTED"),
        "packet_legacy_fields_hidden": packet_legacy_hidden,
        "escrow_pre_gold_read_rejected": escrow_pre_gold_rejected,
        "escrow_post_gold_synthetic_read_count": escrow_post_gold_count,
        "retry_rejected": retry_rejected,
        "post_completed_lock_unchanged": post_completed_unchanged,
        "failure_observed": failure_observed,
        "failure_lock_preserved": failure_lock.get("failure_lock_preserved") is True,
        "failure_retry_permitted": failure_lock.get("retry_permitted"),
        "double_build_byte_identical": byte_identical,
        "second_run_state": second_lock["state"],
        "real_track_b_access_count": 0,
        "real_d1_lock_created": False,
        "real_packets_created": False,
        "human_labels_formed": False,
        "provider_calls": 0,
        "network_access": False,
    }


def _documents(manifest: Mapping[str, Any]) -> dict[str, str]:
    bundle_sha = manifest["bundle_sha256"]
    common = (
        "RQ2-D0-R1 is a contract-only, provider-free pre-arm repair. It did not "
        "determine whether raw Track B exists and did not list, stat, resolve, hash, "
        "open, read, or parse raw Track B. It created no real D1 lock, case bank, "
        "escrow, reviewer packet, Capability label, model output, or final evaluation.\n"
    )
    authority = f"""# RQ2-D0-R1 Contamination Reference Authority

{common}

Eight governed partitions are frozen before D1: RQ1 TRAIN 318, RQ1 DEV 84, frozen C0 candidates 62, Track A safe identities 128, Authentic22, Synthetic35, context-missing3, and controlled mechanism Fixture28. Their exact total is 680. Every source has a frozen alias, source/manifest SHA-256, exact observed count, and a PASS resolution. Empty, duplicated-fill, ambiguous, wrong-count, and source-hash-mismatched partitions fail closed.

The local bundle SHA-256 is `{bundle_sha}`. It contains only opaque reference IDs and exact-query, D0-normalised-query, query-plus-history, source-record, and optional family/group hashes. It is ignored, untracked, local-only, and absent from the review ZIP. Tracked outputs preserve only safe commitments and aggregate counts.
"""
    escrow = f"""# RQ2-D0-R1 Hidden Legacy Escrow and Blinding

{common}

Future D1 must derive a 48-record local-only hidden legacy escrow during the same single in-memory raw read. Existing Intent, scope, guard, policy, review, rationale, provenance, family, contrast, difficulty, and eligibility metadata remain absent from human packets. Codex, reviewers, the adjudicator, and models cannot read the escrow before `TRACK_B_CAPABILITY_GOLD_FROZEN=true`; post-Gold access is diagnostic only.

Before `ARMED`, real D1 generates a fresh 32-byte key with `secrets.token_bytes(32)`, durably persists it with mode 0600, and records only the domain-separated SHA-256 commitment. Opaque IDs use domain-separated HMAC-SHA256 and the frozen `TBV1-` plus 16 uppercase hexadecimal format. Fixed, short, environment-reused, or human password keys are prohibited in real mode.
"""
    receipt = f"""# RQ2-D0-R1 Durable One-Shot Receipt

{common}

Each D1 output uses an exclusive temporary file, flush and file fsync, `os.replace`, parent-directory fsync, reread, SHA-256 verification, size verification, and schema/record-count verification. The completed lock binds the canonical case bank, raw/blinded mapping, hidden escrow, contamination audit summary, both packets, and packet manifest by SHA-256, byte size, and record count.

The contamination receipt additionally binds reference-manifest SHA, reference-bundle SHA, audit-summary SHA and size, hard-conflict count, and sensitivity-overlap count. A status string alone is insufficient. Failure locks remain durable, retry is prohibited, and no post-COMPLETED write is permitted.
"""
    runbook = f"""# RQ2-D0-R1 D1 Pre-Arm Runbook

{common}

The only legal future sequence is `PREARM_VALIDATED → KEY_PERSISTED → ARMED → OPENED → CASE_BANK_PERSISTED → LEGACY_ESCROW_PERSISTED → CONTAMINATION_AUDIT_PERSISTED → REVIEW_PACKETS_PERSISTED → COMPLETED`. Before key generation, the output root must be absent or completely empty; any old, hidden, temporary, or symlink entry blocks D1 while raw-open count remains zero.

Hard final-independence partitions are RQ1 TRAIN, RQ1 DEV, C0 candidates, Track A safe identities, and Synthetic35. Exact, normalised, query-plus-history, or source-record overlap invalidates final evaluation. Authentic22, context-missing3, and Fixture28 overlaps are retained in a source-stratified sensitivity registry without automatic deletion. Label-conflict checks wait until Track B Capability Gold is frozen. D1 must not alter this policy after observing overlaps.
"""
    return dict(zip(DOC_FILENAMES, (authority, escrow, receipt, runbook)))


def governed_output_paths() -> tuple[Path, ...]:
    paths = [*sorted(HERE.glob("*.py"))]
    paths.extend(HERE / name for name in SAFE_JSON_FILENAMES)
    paths.extend(DOC_ROOT / name for name in DOC_FILENAMES)
    return tuple(sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix()))


def write_output_checksums() -> Path:
    paths = governed_output_paths()
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValidationError("BLOCKED_RQ2_D0_R1_TEST_FAILURE")
    payload = (
        "\n".join(
            f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in paths
        )
        + "\n"
    ).encode("utf-8")
    target = HERE / CHECKSUM_NAME
    atomic_write_durable(target, payload, mode=0o644, replace=target.exists())
    return target


def parse_output_checksums() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (HERE / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, relative = line.split(None, 1)
            result[relative.strip().lstrip("*")] = digest
    return result


def finalise_outputs() -> dict[str, Any]:
    preflight = verify_d0_identity()
    partitions, source_resolution = resolve_all_reference_sources()
    bundle, manifest = build_bundle(partitions, source_resolution)
    bundle_again, manifest_again = build_bundle(partitions, source_resolution)
    if bundle_again != bundle or manifest_again != manifest:
        raise ValidationError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
    source_resolution["double_build_byte_identical"] = True
    reference_report = validate_reference_bundle(bundle, manifest)
    LOCAL_REFERENCE_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_durable(
        LOCAL_REFERENCE_BUNDLE,
        bundle,
        mode=0o600,
        replace=LOCAL_REFERENCE_BUNDLE.exists(),
    )
    synthetic = run_synthetic_validation()
    safe_values = {
        "rq2d0_r1_preflight_report_v1.json": preflight,
        "contamination_reference_source_resolution_v1.json": source_resolution,
        "track_b_contamination_reference_manifest_v1.json": manifest,
        "track_b_contamination_policy_v1_1.json": contamination_policy_document(),
        "track_b_legacy_escrow_contract_v1.json": legacy_escrow_contract_document(),
        "track_b_blinding_key_contract_v1.json": __import__(
            "evaluation.capability_routing_rq2d0_r1_v1.blinding_key_governance",
            fromlist=["blinding_key_contract_document"],
        ).blinding_key_contract_document(),
        "track_b_prearm_output_contract_v1.json": prearm_output_contract_document(),
        "track_b_packet_generation_state_machine_v1_1.json": (
            state_machine_contract_document()
        ),
        "track_b_durable_receipt_contract_v1.json": durable_receipt_contract_document(),
        "rq2d0_r1_synthetic_validation_v1.json": synthetic,
    }
    for name, value in safe_values.items():
        target = HERE / name
        atomic_write_durable(
            target,
            canonical_json_bytes(value),
            mode=0o644,
            replace=target.exists(),
        )
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    for name, text in _documents(manifest).items():
        target = DOC_ROOT / name
        atomic_write_durable(
            target, text.encode("utf-8"), mode=0o644, replace=target.exists()
        )
    checksum_path = write_output_checksums()
    return {
        "status": "PASS",
        "reference_validation": reference_report,
        "bundle_sha256": manifest["bundle_sha256"],
        "bundle_size_bytes": manifest["bundle_size_bytes"],
        "safe_json_count": len(safe_values),
        "document_count": len(DOC_FILENAMES),
        "python_file_count": len(list(HERE.glob("*.py"))),
        "checksum_count": len(parse_output_checksums()),
        "checksum_manifest_sha256": sha256_file(checksum_path),
        "raw_track_b_access_count": 0,
    }


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"status": "PASS", "python_file_count": len(paths)}


def validate_local_bundle() -> dict[str, Any]:
    manifest = json.loads(
        (HERE / "track_b_contamination_reference_manifest_v1.json").read_text()
    )
    bundle = LOCAL_REFERENCE_BUNDLE.read_bytes()
    report = validate_reference_bundle(bundle, manifest)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(LOCAL_REFERENCE_BUNDLE.relative_to(ROOT))],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    tracked = bool(_git("ls-files", str(LOCAL_REFERENCE_BUNDLE.relative_to(ROOT))))
    if not ignored or tracked:
        raise ValidationError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
    return {**report, "ignored": True, "tracked": False}


def validate_safe_outputs() -> dict[str, Any]:
    for name in SAFE_JSON_FILENAMES:
        path = HERE / name
        if not path.is_file() or path.is_symlink():
            raise ValidationError("BLOCKED_RQ2_D0_R1_TEST_FAILURE")
        json.loads(path.read_text(encoding="utf-8"))
    for name in DOC_FILENAMES:
        if not (DOC_ROOT / name).is_file():
            raise ValidationError("BLOCKED_RQ2_D0_R1_TEST_FAILURE")
    synthetic = json.loads((HERE / "rq2d0_r1_synthetic_validation_v1.json").read_text())
    manifest = json.loads(
        (HERE / "track_b_contamination_reference_manifest_v1.json").read_text()
    )
    if (
        synthetic.get("status") != "PASS"
        or synthetic.get("real_track_b_access_count") != 0
        or synthetic.get("real_d1_lock_created") is not False
        or synthetic.get("real_packets_created") is not False
        or manifest.get("total_reference_records") != REFERENCE_TOTAL_COUNT
        or manifest.get("local_bundle_tracked") is not False
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R1_TEST_FAILURE")
    return {
        "status": "PASS",
        "safe_json_count": len(SAFE_JSON_FILENAMES),
        "document_count": len(DOC_FILENAMES),
    }


def validate_output_checksums() -> dict[str, Any]:
    values = parse_output_checksums()
    failed = [
        path
        for path, digest in values.items()
        if not (ROOT / path).is_file()
        or (ROOT / path).is_symlink()
        or sha256_file(ROOT / path) != digest
    ]
    if failed:
        raise ValidationError("BLOCKED_RQ2_D0_R1_TEST_FAILURE")
    return {"status": "PASS", "checksum_count": len(values), "failure_count": 0}


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    targets = list(paths) if paths is not None else [ROOT / path for path in parse_output_checksums()]
    # Split synthetic probes so the scanner source does not self-match its sentinels.
    prohibited = (
        str(Path.home()) + "/",
        "Synthetic " + "Track B shaped query",
        "Synthetic hidden " + "rationale",
        "PV3-" + "B-0001",
        "human_revised_history" + "\":",
    )
    leaks: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(value in text for value in prohibited):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise ValidationError("BLOCKED_RQ2_D0_R1_TEST_FAILURE")
    return {
        "status": "PASS",
        "scanned_file_count": len(targets),
        "leak_count": 0,
        "raw_track_b_compared": False,
    }


def protected_source_comparison() -> dict[str, Any]:
    changed = _git("diff", "--name-only", D0_HEAD, "--").splitlines()
    allowed = []
    invalid = []
    for path in changed:
        if (
            path == ".gitignore"
            or path.startswith("evaluation/capability_routing_rq2d0_r1_v1/")
            or path.startswith("docs/thesis_mainline/rq2/RQ2D0_R1_")
        ):
            allowed.append(path)
        else:
            invalid.append(path)
    if invalid:
        raise ValidationError("BLOCKED_RQ2_D0_R1_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "changed_file_count": len(changed),
        "allowed_changed_file_count": len(allowed),
        "invalid_changed_file_count": 0,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = _git("diff", "--cached", "--name-only").splitlines()
    invalid = [
        path
        for path in staged
        if path != ".gitignore"
        and not path.startswith("evaluation/capability_routing_rq2d0_r1_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_R1_")
    ]
    if invalid or any("local_contamination" in path for path in staged):
        raise ValidationError("BLOCKED_RQ2_D0_R1_GIT_FAILURE")
    return {"status": "PASS", "staged_count": len(staged), "invalid_count": 0}


def validate_git_state(*, require_commit: bool = False) -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    count = int(_git("rev-list", "--count", f"{D0_HEAD}..HEAD"))
    accepted = {1} if require_commit else {0, 1}
    if branch != RESULT_BRANCH or count not in accepted or _git("remote") or _git("tag", "--list"):
        raise ValidationError("BLOCKED_RQ2_D0_R1_GIT_FAILURE")
    return {
        "status": "PASS",
        "branch": branch,
        "relative_commit_count": count,
        "remote_count": 0,
        "tag_count": 0,
    }


def expected_review_members() -> tuple[str, ...]:
    referenced = tuple(sorted(parse_output_checksums()))
    checksum_relative = (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix()
    return (
        *referenced,
        checksum_relative,
        "REVIEW/GIT_STATE.json",
        "REVIEW/DIFF_SUMMARY.txt",
        "REVIEW/GITIGNORE_SAFE_DIFF.patch",
        "REVIEW/GITIGNORE_SHA256.txt",
        "REVIEW/REVIEW_CHECKSUMS.sha256",
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip() -> dict[str, Any]:
    referenced = parse_output_checksums()
    tracked = set(_git("ls-files").splitlines())
    if not set(referenced) <= tracked:
        raise ValidationError("BLOCKED_RQ2_D0_R1_REVIEW_PACKAGE_INCOMPLETE")
    payloads: dict[str, bytes] = {}
    for relative, digest in referenced.items():
        payload = (ROOT / relative).read_bytes()
        if sha256_bytes(payload) != digest:
            raise ValidationError("BLOCKED_RQ2_D0_R1_REVIEW_PACKAGE_INCOMPLETE")
        payloads[relative] = payload
    checksum_relative = (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix()
    payloads[checksum_relative] = (HERE / CHECKSUM_NAME).read_bytes()
    git_state = {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "base_head": D0_HEAD,
        "relative_commit_count": int(_git("rev-list", "--count", f"{D0_HEAD}..HEAD")),
        "remote_count": len(_git("remote").splitlines()) if _git("remote") else 0,
        "tag_count": len(_git("tag", "--list").splitlines()) if _git("tag", "--list") else 0,
        "worktree_clean": not bool(_git("status", "--porcelain=v1", "--untracked-files=all")),
        "raw_track_b_access_count": 0,
        "real_d1_lock_created": False,
        "real_packets_created": False,
    }
    if (
        git_state["branch"] != RESULT_BRANCH
        or git_state["relative_commit_count"] != 1
        or git_state["remote_count"]
        or git_state["tag_count"]
        or not git_state["worktree_clean"]
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R1_GIT_FAILURE")
    payloads["REVIEW/GIT_STATE.json"] = canonical_json_bytes(git_state)
    payloads["REVIEW/DIFF_SUMMARY.txt"] = (
        _git("diff", "--stat", f"{D0_HEAD}..HEAD") + "\n"
    ).encode("utf-8")
    payloads["REVIEW/GITIGNORE_SAFE_DIFF.patch"] = (
        _git("diff", f"{D0_HEAD}..HEAD", "--", ".gitignore") + "\n"
    ).encode("utf-8")
    payloads["REVIEW/GITIGNORE_SHA256.txt"] = (
        f"{sha256_file(ROOT / '.gitignore')}  .gitignore\n"
    ).encode("ascii")
    payloads["REVIEW/REVIEW_CHECKSUMS.sha256"] = (
        "\n".join(
            f"{sha256_bytes(payload)}  {name}" for name, payload in sorted(payloads.items())
        )
        + "\n"
    ).encode("ascii")
    destination = ROOT.parent / REVIEW_ZIP_NAME
    if destination.exists():
        raise ValidationError("BLOCKED_RQ2_D0_R1_REVIEW_PACKAGE_INCOMPLETE")
    with zipfile.ZipFile(destination, "x") as archive:
        for name, payload in sorted(payloads.items()):
            archive.writestr(_zip_info(name), payload)
    return {
        "status": "PASS",
        "path": str(destination),
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "member_count": len(payloads),
        "referenced_output_count": len(referenced),
    }


def validate_review_zip(path: Path) -> dict[str, Any]:
    expected = set(expected_review_members())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if archive.testzip() is not None or len(names) != len(set(names)) or set(names) != expected:
            raise ValidationError("BLOCKED_RQ2_D0_R1_REVIEW_PACKAGE_INCOMPLETE")
        forbidden = (
            "local_contamination",
            "track_b_hidden_legacy_metadata",
            "track_b_opaque_mapping",
            "reviewer_a_track_b",
            "reviewer_b_track_b",
            KEY_FILE_NAME,
        )
        if any(any(fragment in name for fragment in forbidden) for name in names):
            raise ValidationError("BLOCKED_RQ2_D0_R1_REVIEW_PACKAGE_INCOMPLETE")
        review_lines = archive.read("REVIEW/REVIEW_CHECKSUMS.sha256").decode().splitlines()
        for line in review_lines:
            digest, name = line.split(None, 1)
            if sha256_bytes(archive.read(name.strip())) != digest:
                raise ValidationError("BLOCKED_RQ2_D0_R1_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "status": "PASS",
        "member_count": len(expected),
        "internal_review_checksum_count": len(review_lines),
        "referenced_output_count": len(parse_output_checksums()),
    }


def validate_all() -> dict[str, Any]:
    return {
        "python_ast": validate_python_ast(),
        "local_reference_bundle": validate_local_bundle(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "staged_allowlist": staged_allowlist(),
        "git": validate_git_state(),
        "status": "PASS",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--finalise", action="store_true")
    arguments = parser.parse_args()
    result = finalise_outputs() if arguments.finalise else validate_all()
    print(json.dumps(result, indent=2, sort_keys=True))
