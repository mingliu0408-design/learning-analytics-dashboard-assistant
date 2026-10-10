"""Finalisation, validation, and safe review packaging for RQ2-D0-R2."""

from __future__ import annotations

import ast
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping
import zipfile

from evaluation.capability_routing_rq2d0_r1_v1.durable_atomic_persistence import (
    atomic_write_durable,
)

from . import (
    CHECKSUM_NAME,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    RESULT_BRANCH,
    REVIEW_ZIP_NAME,
    ROOT,
    SAFE_JSON_FILENAMES,
    START_HEAD,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .contamination_policy_v1_2 import (
    GROUPING_OVERLAP_FIELD,
    IDENTITY_OVERLAP_FIELDS,
    contamination_policy_document_v1_2,
)
from .d0_r1_identity import verify_frozen_d0_r1_identity
from .frozen_reference_authority import (
    exact_reference_binding_contract_document,
    load_frozen_contamination_reference_authority_v1_1,
)
from .packet_generation_state_machine_v1_2 import (
    execute_real_d1_one_shot_v1_2,
    state_machine_contract_document_v1_2,
)
from .track_b_grouping_identity import grouping_semantics_contract_document


class ValidationError(RuntimeError):
    pass


FIXED_ZIP_TIME = (2026, 8, 28, 12, 0, 0)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _unit_test_result() -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "unittest",
            "evaluation.capability_routing_rq2d0_r2_v1.test_rq2d0_r2_unittest",
            "-v",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    match = re.search(r"Ran (\d+) tests", process.stdout)
    count = int(match.group(1)) if match else 0
    if process.returncode or count < 47 or not process.stdout.rstrip().endswith("OK"):
        raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    return {
        "status": "PASS",
        "required_test_count": 47,
        "executed_test_count": count,
        "passed_test_count": count,
        "failure_count": 0,
    }


def synthetic_validation_document(unit_tests: Mapping[str, Any]) -> dict[str, Any]:
    real_parameters = tuple(
        inspect.signature(execute_real_d1_one_shot_v1_2).parameters
    )
    forbidden = {
        "reference_bundle",
        "reference_manifest",
        "reference_source_resolution",
        "reference_path_override",
        "synthetic_reference_authority",
        "mode",
    }
    if forbidden & set(real_parameters):
        raise ValidationError("BLOCKED_RQ2_D0_R2_REFERENCE_INJECTION")
    return {
        "schema_version": "rq2d0-r2-synthetic-validation-v1",
        "status": "PASS",
        "unit_tests": dict(unit_tests),
        "exact_authority_positive_case": True,
        "manifest_sha_substitution_rejected": True,
        "semantic_reserialisation_rejected": True,
        "bundle_sha_substitution_rejected": True,
        "self_consistent_alternative_680_row_authority_rejected": True,
        "source_resolution_substitution_rejected": True,
        "symlink_substitutions_rejected": True,
        "tracked_ignored_role_substitutions_rejected": True,
        "authority_failure_key_generation_count": 0,
        "authority_failure_key_file_creation_count": 0,
        "authority_failure_real_lock_creation_count": 0,
        "authority_failure_raw_open_count": 0,
        "authority_failure_raw_read_count": 0,
        "real_entry_point_parameters": list(real_parameters),
        "real_entry_point_reference_injection_parameters": [],
        "hard_identity_fields": list(IDENTITY_OVERLAP_FIELDS.values()),
        "hard_identity_field_count": 4,
        "grouping_overlap_field": GROUPING_OVERLAP_FIELD[1],
        "grouping_only_overlap_keeps_pass": True,
        "grouping_only_overlap_increments_hard_conflict_count": False,
        "unique_hard_case_count_semantics_verified": True,
        "partition_level_event_count_semantics_verified": True,
        "track_b_grouping_source": "contrast_set_id",
        "contrast_group_count": 24,
        "records_per_contrast_group": 2,
        "scenario_family_id_cluster_role": "NOT_ELIGIBLE_UNIQUE_PER_RECORD",
        "armed_receipt_exact_authority_binding_verified": True,
        "packet_manifest_receipt_binding_verified": True,
        "completed_lock_receipt_binding_verified": True,
        "post_completed_authority_mutation_rejected": True,
        "synthetic_double_build_byte_identical": True,
        "raw_track_b_access_count": 0,
        "real_blinding_key_created": False,
        "real_d1_lock_created": False,
        "real_case_bank_created": False,
        "real_packets_created": False,
        "track_b_labels_created": False,
        "model_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def _documents(authority_commitment: str) -> dict[str, str]:
    common = (
        "RQ2-D0-R2 is a contract-only, provider-free repair. It did not list, "
        "stat, resolve, hash, open, read, or parse raw Track B. It created no "
        "real blinding key, D1 lock, case bank, reviewer packet, label, model "
        "output, or final-evaluation result. D0 and D0-R1 remain byte-identical.\n"
    )
    authority = f"""# RQ2-D0-R2 Exact Reference Authority Binding

{common}

Structural validity is not frozen-authority identity. Future real D1 uses the no-argument `load_frozen_contamination_reference_authority_v1_1()` loader and three fixed repository-relative paths. It rejects caller-supplied bytes, objects, alternate paths, same-name searches, and rebuilt sources. The tracked manifest, ignored/untracked local bundle, and tracked source-resolution file are each checked as regular non-symlink files against exact SHA-256 and byte size before key generation, lock creation, or raw access.

The bundle has exactly 680 canonical JSONL records in eight contiguous frozen partitions. Commitments are recomputed from original LF-terminated line bytes; rows are not reordered. Partition counts, source aliases, source SHAs, required hashes, canonical encoding, final LF, and strictly increasing opaque IDs are verified. The combined authority commitment is `{authority_commitment}`. It binds the three exact file SHAs and the ordered partition/count/raw-line commitments; it is an integrity commitment, not a MAC or digital signature.
"""
    semantics = f"""# RQ2-D0-R2 Contamination Identity and Grouping Semantics

{common}

Hard contamination is limited to four fields: `exact_query_hash`, `normalised_query_hash`, `query_history_hash`, and `source_record_identity_hash`. A unique Track-B case with any such hit against any hard partition counts once in `hard_conflict_count`; case-by-partition events remain separately reported. Exact, normalised, query-plus-history, and source-record counts are preserved per partition.

`family_or_group_hash_if_available` is report-only and is never part of the hard matched-field loop. Grouping-only overlap is not query/context contamination and cannot invalidate final evaluation. Safe registries distinguish `IDENTITY_OVERLAP`, `GROUPING_ONLY_OVERLAP`, and `IDENTITY_AND_GROUPING_OVERLAP` without text, raw IDs, or labels.

Future Track-B grouping uses domain-separated hashing of `contrast_set_id`: 48 cases must form 24 groups of exactly two. `scenario_family_id` is unique per record and is ineligible as a dependence or bootstrap cluster. This correction changes no C0, P1, P2, Gold, fixture, threshold, or statistical seed.
"""
    runbook = f"""# RQ2-D0-R2 Final D1 Pre-Arm Runbook

{common}

Real and synthetic APIs are separate. Future D1 must call `execute_real_d1_one_shot_v1_2(source_path, output_root, *, approved_head, schema_authority_sha256)`; the signature contains no reference injection or mode parameter. Synthetic fixtures use a different entry point and cannot enter a real receipt.

The frozen pre-arm order is: approved HEAD/clean Git/explicit environment authority; new-or-empty output root; safe schema verification; exact authority loading; combined commitment calculation; absence of a real lock; fresh 32-byte key generation and durable persistence; `KEY_PERSISTED`; `ARMED`; then the sole raw Track-B open. Exact-authority failure leaves key generation, key-file creation, real-lock creation, raw-open, and raw-read counts at zero.

The `ARMED` lock, packet manifest, and `COMPLETED` lock repeat the same full authority receipt: paths, file SHAs, sizes, 680-row count, eight partition counts/commitments, normaliser ID, contract ID, and combined commitment `{authority_commitment}`. Persisted outputs and the authority are reverified before `COMPLETED`; later authority mutation is rejected. D1 remains separately authorised and non-retryable. No Track-B human review or final evaluation has begun.
"""
    return dict(zip(DOC_FILENAMES, (authority, semantics, runbook)))


def governed_output_paths() -> tuple[Path, ...]:
    paths = [*sorted(HERE.glob("*.py"))]
    paths.extend(HERE / name for name in SAFE_JSON_FILENAMES)
    paths.extend(DOC_ROOT / name for name in DOC_FILENAMES)
    return tuple(sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix()))


def write_output_checksums() -> Path:
    paths = governed_output_paths()
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    payload = (
        "\n".join(
            f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
            for path in paths
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
    preflight = verify_frozen_d0_r1_identity()
    authority = load_frozen_contamination_reference_authority_v1_1()
    unit_tests = _unit_test_result()
    synthetic = synthetic_validation_document(unit_tests)
    safe_values = {
        "rq2d0_r2_preflight_report_v1.json": preflight,
        "frozen_contamination_reference_authority_v1_1.json": authority.safe_document(),
        "exact_reference_binding_contract_v1.json": (
            exact_reference_binding_contract_document()
        ),
        "track_b_contamination_policy_v1_2.json": (
            contamination_policy_document_v1_2()
        ),
        "track_b_grouping_semantics_contract_v1.json": (
            grouping_semantics_contract_document()
        ),
        "track_b_packet_generation_state_machine_v1_2.json": (
            state_machine_contract_document_v1_2()
        ),
        "rq2d0_r2_synthetic_validation_v1.json": synthetic,
    }
    for name, value in safe_values.items():
        atomic_write_durable(
            HERE / name,
            canonical_json_bytes(value),
            mode=0o644,
            replace=(HERE / name).exists(),
        )
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    for name, text in _documents(authority.authority_commitment).items():
        atomic_write_durable(
            DOC_ROOT / name,
            text.encode("utf-8"),
            mode=0o644,
            replace=(DOC_ROOT / name).exists(),
        )
    checksum_path = write_output_checksums()
    return {
        "status": "PASS",
        "safe_json_count": len(safe_values),
        "document_count": len(DOC_FILENAMES),
        "python_file_count": len(list(HERE.glob("*.py"))),
        "checksum_count": len(parse_output_checksums()),
        "checksum_manifest_sha256": sha256_file(checksum_path),
        "reference_authority_commitment": authority.authority_commitment,
        "reference_record_count": authority.bundle_record_count,
        "partition_count": len(authority.partition_order),
        "raw_track_b_access_count": 0,
    }


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"status": "PASS", "python_file_count": len(paths)}


def validate_safe_outputs() -> dict[str, Any]:
    for name in SAFE_JSON_FILENAMES:
        path = HERE / name
        if not path.is_file() or path.is_symlink():
            raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
        json.loads(path.read_text(encoding="utf-8"))
    for name in DOC_FILENAMES:
        if not (DOC_ROOT / name).is_file() or (DOC_ROOT / name).is_symlink():
            raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    frozen = json.loads(
        (HERE / "frozen_contamination_reference_authority_v1_1.json").read_text()
    )
    synthetic = json.loads(
        (HERE / "rq2d0_r2_synthetic_validation_v1.json").read_text()
    )
    if (
        frozen.get("reference_bundle_record_count") != 680
        or frozen.get("partition_count") != 8
        or synthetic.get("raw_track_b_access_count") != 0
        or synthetic.get("real_d1_lock_created") is not False
        or synthetic.get("real_packets_created") is not False
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    return {
        "status": "PASS",
        "safe_json_count": len(SAFE_JSON_FILENAMES),
        "document_count": len(DOC_FILENAMES),
    }


def validate_output_checksums() -> dict[str, Any]:
    values = parse_output_checksums()
    failed = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if failed or len(values) != len(governed_output_paths()):
        raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    return {"status": "PASS", "checksum_count": len(values), "failure_count": 0}


def governed_text_leak_scan(
    paths: Iterable[Path] | None = None,
) -> dict[str, Any]:
    targets = (
        list(paths)
        if paths is not None
        else [ROOT / relative for relative in parse_output_checksums()]
    )
    prohibited = (
        str(Path.home()) + "/",
        "Synthetic " + "Track B shaped query",
        "Synthetic hidden " + "rationale",
        "PV3-" + "B-0001",
        "OPENAI_" + "API_KEY=",
    )
    leaks: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(value in text for value in prohibited):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    return {
        "status": "PASS",
        "scanned_file_count": len(targets),
        "leak_count": 0,
        "raw_track_b_compared": False,
    }


def protected_source_comparison() -> dict[str, Any]:
    changed = _git("diff", "--name-only", START_HEAD, "--").splitlines()
    invalid = [
        path
        for path in changed
        if not path.startswith("evaluation/capability_routing_rq2d0_r2_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_R2_")
    ]
    historical = [
        path
        for path in changed
        if path.startswith("evaluation/capability_routing_rq2d0_v1/")
        or path.startswith("evaluation/capability_routing_rq2d0_r1_v1/")
    ]
    if invalid or historical:
        raise ValidationError("BLOCKED_RQ2_D0_R2_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "changed_file_count": len(changed),
        "invalid_changed_file_count": 0,
        "d0_d0_r1_changed_file_count": 0,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = _git("diff", "--cached", "--name-only").splitlines()
    invalid = [
        path
        for path in staged
        if not path.startswith("evaluation/capability_routing_rq2d0_r2_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_R2_")
    ]
    if invalid:
        raise ValidationError("BLOCKED_RQ2_D0_R2_GIT_FAILURE")
    return {"status": "PASS", "staged_count": len(staged), "invalid_count": 0}


def validate_git_state(*, require_commit: bool = False) -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    count = int(_git("rev-list", "--count", f"{START_HEAD}..HEAD"))
    accepted = {1} if require_commit else {0, 1}
    if (
        branch != RESULT_BRANCH
        or count not in accepted
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R2_GIT_FAILURE")
    return {
        "status": "PASS",
        "branch": branch,
        "relative_commit_count": count,
        "remote_count": 0,
        "tag_count": 0,
    }


def double_finalisation_byte_identical() -> dict[str, Any]:
    finalise_outputs()
    before = {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for path in (*governed_output_paths(), HERE / CHECKSUM_NAME)
    }
    finalise_outputs()
    after = {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for path in (*governed_output_paths(), HERE / CHECKSUM_NAME)
    }
    if before != after:
        raise ValidationError("BLOCKED_RQ2_D0_R2_TEST_FAILURE")
    return {"status": "PASS", "file_count": len(before), "byte_identical": True}


def validate_all() -> dict[str, Any]:
    authority = load_frozen_contamination_reference_authority_v1_1()
    return {
        "python_ast": validate_python_ast(),
        "exact_authority": {
            "status": "PASS",
            "record_count": authority.bundle_record_count,
            "partition_count": len(authority.partition_order),
            "authority_commitment": authority.authority_commitment,
        },
        "unit_tests": _unit_test_result(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "git": validate_git_state(),
    }


def expected_review_members() -> tuple[str, ...]:
    return (
        *tuple(sorted(parse_output_checksums())),
        (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
        "REVIEW/GIT_STATE.json",
        "REVIEW/DIFF_SUMMARY.txt",
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
        raise ValidationError("BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE")
    payloads: dict[str, bytes] = {}
    for relative, digest in referenced.items():
        payload = (ROOT / relative).read_bytes()
        if sha256_bytes(payload) != digest:
            raise ValidationError("BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE")
        payloads[relative] = payload
    checksum_relative = (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix()
    payloads[checksum_relative] = (HERE / CHECKSUM_NAME).read_bytes()
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    git_state = {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "base_head": START_HEAD,
        "relative_commit_count": int(
            _git("rev-list", "--count", f"{START_HEAD}..HEAD")
        ),
        "remote_count": len(_git("remote").splitlines()) if _git("remote") else 0,
        "tag_count": (
            len(_git("tag", "--list").splitlines()) if _git("tag", "--list") else 0
        ),
        "worktree_clean": not bool(status),
        "index_clean": not bool(_git("diff", "--cached", "--name-only")),
        "raw_track_b_access_count": 0,
        "real_blinding_key_created": False,
        "real_d1_lock_created": False,
        "real_case_bank_created": False,
        "real_packets_created": False,
    }
    if (
        git_state["branch"] != RESULT_BRANCH
        or git_state["relative_commit_count"] != 1
        or git_state["remote_count"]
        or git_state["tag_count"]
        or not git_state["worktree_clean"]
        or not git_state["index_clean"]
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R2_GIT_FAILURE")
    payloads["REVIEW/GIT_STATE.json"] = canonical_json_bytes(git_state)
    payloads["REVIEW/DIFF_SUMMARY.txt"] = (
        _git("diff", "--stat", f"{START_HEAD}..HEAD") + "\n"
    ).encode("utf-8")
    payloads["REVIEW/REVIEW_CHECKSUMS.sha256"] = (
        "\n".join(
            f"{sha256_bytes(payload)}  {name}"
            for name, payload in sorted(payloads.items())
        )
        + "\n"
    ).encode("ascii")
    destination = ROOT.parent / REVIEW_ZIP_NAME
    if destination.exists():
        raise ValidationError("BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE")
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
        if (
            archive.testzip() is not None
            or len(names) != len(set(names))
            or set(names) != expected
        ):
            raise ValidationError("BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE")
        forbidden_members = (
            "local_contamination/",
            "reference_bundle_v1.jsonl",
            "reviewer_a_track_b",
            "reviewer_b_track_b",
            "track_b_opaque_mapping",
            "track_b_hidden_legacy_metadata",
            "blinding_key",
        )
        if any(
            any(fragment in name for fragment in forbidden_members) for name in names
        ):
            raise ValidationError("BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE")
        review_lines = archive.read("REVIEW/REVIEW_CHECKSUMS.sha256").decode().splitlines()
        for line in review_lines:
            digest, member = line.split(None, 1)
            if sha256_bytes(archive.read(member.strip())) != digest:
                raise ValidationError(
                    "BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE"
                )
        referenced = set(parse_output_checksums())
        output_members = {
            name
            for name in names
            if name not in {
                (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
                "REVIEW/GIT_STATE.json",
                "REVIEW/DIFF_SUMMARY.txt",
                "REVIEW/REVIEW_CHECKSUMS.sha256",
            }
        }
        if output_members != referenced:
            raise ValidationError("BLOCKED_RQ2_D0_R2_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "status": "PASS",
        "member_count": len(expected),
        "internal_review_checksum_count": len(review_lines),
        "referenced_output_count": len(referenced),
        "zip_integrity": "PASS",
        "exact_allowlist": "PASS",
    }
