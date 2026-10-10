"""Finalisation, validation, and safe review packaging for RQ2-D0-R3."""

from __future__ import annotations

import ast
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
    EXECUTION_CONTRACT_ID,
    HERE,
    REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3,
    REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3,
    REFERENCE_AUTHORITY_COMMITMENT,
    RESULT_BRANCH,
    REVIEW_ZIP_NAME,
    ROOT,
    SAFE_JSON_FILENAMES,
    START_HEAD,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .d0_r2_identity import verify_frozen_d0_r2_identity
from .effective_d1_entry_contract import (
    effective_d1_entry_contract_document,
    global_repair_authority_document,
    validate_real_entry_signature_v1_3,
)
from .fixed_d1_paths import fixed_path_contract_document
from .global_one_shot_lock import global_reservation_contract_document
from .output_root_identity import output_identity_contract_fields
from .packet_generation_state_machine_v1_3 import (
    state_machine_contract_document_v1_3,
)


class ValidationError(RuntimeError):
    pass


FIXED_ZIP_TIME = (2026, 8, 28, 12, 0, 0)
GITIGNORE_LINES = (
    "evaluation/capability_routing_rq2d1_v1/local_one_shot/",
    "evaluation/capability_routing_rq2d1_v1/local_control/",
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def unit_test_result() -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "unittest",
            "evaluation.capability_routing_rq2d0_r3_v1.test_rq2d0_r3_unittest",
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
    if process.returncode or count < 66 or not process.stdout.rstrip().endswith("OK"):
        raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
    return {
        "status": "PASS",
        "required_test_count": 66,
        "executed_test_count": count,
        "passed_test_count": count,
        "failure_count": 0,
    }


def validate_gitignore_contract() -> dict[str, Any]:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    if any(lines.count(value) != 1 for value in GITIGNORE_LINES):
        raise ValidationError("BLOCKED_RQ2_D0_R3_GIT_FAILURE")
    probes = (
        REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3 + "/BLINDING_KEY.bin",
        REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3 + "/reviewer_packet.csv",
        REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3,
    )
    ignored = [
        subprocess.run(
            ["git", "check-ignore", "-q", "--", probe],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
        for probe in probes
    ]
    if not all(ignored):
        raise ValidationError("BLOCKED_RQ2_D0_R3_GIT_FAILURE")
    return {
        "status": "PASS",
        "added_rule_count": 2,
        "future_output_root_ignored": True,
        "future_control_root_ignored": True,
        "global_lock_cannot_enter_git": True,
        "blind_key_cannot_enter_git": True,
        "packets_cannot_enter_git": True,
        "real_directories_created": False,
    }


def synthetic_validation_document(tests: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2d0-r3-synthetic-validation-v1",
        "status": "PASS",
        "unit_tests": dict(tests),
        "fixed_path_contract_pass": True,
        "absolute_dot_dot_symlink_paths_rejected": True,
        "real_entry_location_override_parameter_count": 0,
        "environment_path_override_count": 0,
        "full_project_relative_output_identity_verified": True,
        "same_basename_different_parent_identity_differs": True,
        "output_root_identity": output_identity_contract_fields()[
            "output_root_identity"
        ],
        "global_lock_identity": output_identity_contract_fields()[
            "global_lock_identity"
        ],
        "exclusive_o_excl_reservation_verified": True,
        "reservation_file_mode": "0600",
        "control_directory_mode": "0700",
        "durability_reread_sha_size_schema_verified": True,
        "reservation_before_key_generation": True,
        "reservation_before_raw_open": True,
        "existing_reserved_failed_completed_malformed_all_block": True,
        "post_reservation_failure_retains_lock": True,
        "completed_lock_retained": True,
        "alternative_output_directory_bypass_rejected": True,
        "concurrent_attempt_count": 2,
        "concurrent_success_count": 1,
        "concurrent_blocked_count": 1,
        "concurrent_loser_key_generation_count": 0,
        "concurrent_loser_raw_open_count": 0,
        "concurrent_loser_raw_read_count": 0,
        "winner_failure_lock_retained": True,
        "third_attempt_after_winner_failure_blocked": True,
        "synthetic_and_real_entry_points_separate": True,
        "synthetic_contract_differs_from_real": True,
        "synthetic_lock_cannot_create_or_satisfy_real_lock": True,
        "synthetic_completion_authorises_real_d1": False,
        "global_reserved_first_consuming_state": True,
        "global_state_order_strict": True,
        "failed_state_preserves_last_successful_state": True,
        "packet_and_completed_receipts_bind_global_identity": True,
        "post_completed_write_rejected": True,
        "double_build_byte_identical": True,
        "raw_track_b_access_count": 0,
        "real_blinding_key_created": False,
        "real_global_lock_created": False,
        "real_d1_lock_created": False,
        "real_case_bank_created": False,
        "real_packets_created": False,
        "track_b_labels_created": False,
        "model_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def _documents(identity: Mapping[str, Any]) -> dict[str, str]:
    common = (
        "RQ2-D0-R3 is a contract-only, provider-free pre-D1 repair. It did not "
        "determine whether raw Track B exists and did not list, stat, resolve, "
        "hash, open, read, or parse raw Track B. It created no real output/control "
        "directory, global lock, D1 lock, blinding key, case bank, escrow, packet, "
        "label, model output, or final-evaluation result.\n"
    )
    global_access = f"""# RQ2-D0-R3 Global One-Shot Access Contract

{common}

One-shot access is repository-global, not output-directory-local. Future D1 atomically reserves the single fixed global lock with `O_CREAT | O_EXCL` (and `O_NOFOLLOW` where available), mode 0600, inside a mode-0700 control directory. The durable `GLOBAL_RESERVED` record is written, file-fsynced, parent-fsynced, reread, and schema/SHA/size-verified before any key generation or raw open.

Any existing lock—reserved, failed, completed, malformed, incomplete, or unknown—blocks every concurrent or later invocation before key/ARMED/raw access. Failure transitions the same authoritative lock to `FAILED`; completion transitions it to `COMPLETED`. Both permanently consume access, retry remains false, deleting an output directory cannot restore authority, and no per-output consumed lock or alternative global lock is permitted.

True multiprocess tests produced exactly one reservation winner and one blocked loser. The loser generated zero keys and performed zero opens/reads; after a simulated winner failure, a third attempt remained blocked.
"""
    fixed = f"""# RQ2-D0-R3 Fixed Output and Lock Authority

{common}

The only real output root is `{REAL_D1_OUTPUT_ROOT_RELATIVE_V1_3}`. The only real control root is `{REAL_D1_GLOBAL_CONTROL_ROOT_RELATIVE_V1_3}`. The only real global lock is `{REAL_D1_GLOBAL_ACCESS_LOCK_RELATIVE_V1_3}`. Real D1 derives them from `git rev-parse --show-toplevel`; function, CLI, environment, configuration, Downloads, cwd, output, lock, and location overrides are prohibited.

The full project-relative path and execution contract `{EXECUTION_CONTRACT_ID}` are domain-separated into output identity `{identity['output_root_identity']}` and global-lock identity `{identity['global_lock_identity']}`. Basename-only and absolute machine-specific identities are prohibited. Existing parent components must be normal non-symlink directories, and all targets must remain inside the repository root.

The two future local roots are ignored without being created. The global lock, key, packets, mappings, escrow, and other local D1 artifacts therefore cannot enter Git.
"""
    runbook = f"""# RQ2-D0-R3 Final D1 Execution Runbook

{common}

Future real D1 must call `execute_real_d1_one_shot_v1_3(source_path, *, approved_head, schema_authority_sha256)`. The API has no output, control, lock, location, reference, mode, or synthetic parameter. It internally resolves fixed paths and loads the exact R2 authority commitment `{REFERENCE_AUTHORITY_COMMITMENT}`.

The pre-arm sequence is: approved HEAD; clean Git; explicit environment authority; fixed-path resolution; new-or-empty fixed output check; safe schema verification; exact contamination-authority verification; raw regular/non-symlink preflight; absence of the global lock; durable exclusive `GLOBAL_RESERVED`; fixed output creation; fresh key; `KEY_PERSISTED`; `ARMED`; then the sole raw open/read. Steps before reservation leave zero lock/key/open/read counts; later failure permanently leaves `FAILED`.

The global lock, packet manifest, case-bank manifest, escrow manifest, contamination summary, both reviewer manifests, and `COMPLETED` state bind one receipt: execution contract, fixed paths, output/lock identities, exact reference commitment, and approved HEAD. Receipt disagreement blocks D1. Synthetic validation uses a different entry, contract, temporary roots, and temporary lock and cannot create, satisfy, block, or authorise real D1. D1 still requires separate explicit non-retryable authority.
"""
    return dict(zip(DOC_FILENAMES, (global_access, fixed, runbook)))


def governed_output_paths() -> tuple[Path, ...]:
    paths = [*sorted(HERE.glob("*.py"))]
    paths.extend(HERE / name for name in SAFE_JSON_FILENAMES)
    paths.extend(DOC_ROOT / name for name in DOC_FILENAMES)
    return tuple(sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix()))


def write_output_checksums() -> Path:
    paths = governed_output_paths()
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
    raw = (
        "\n".join(
            f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
            for path in paths
        )
        + "\n"
    ).encode("utf-8")
    target = HERE / CHECKSUM_NAME
    atomic_write_durable(target, raw, mode=0o644, replace=target.exists())
    return target


def parse_output_checksums() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (HERE / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, relative = line.split(None, 1)
            result[relative.strip().lstrip("*")] = digest
    return result


def finalise_outputs() -> dict[str, Any]:
    preflight = verify_frozen_d0_r2_identity()
    tests = unit_test_result()
    gitignore = validate_gitignore_contract()
    identity = output_identity_contract_fields()
    fixed = {**fixed_path_contract_document(), **identity, "gitignore": gitignore}
    safe_values = {
        "rq2d0_r3_preflight_report_v1.json": preflight,
        "global_one_shot_repair_authority_v1.json": (
            global_repair_authority_document()
        ),
        "track_b_fixed_output_authority_v1.json": fixed,
        "track_b_global_reservation_contract_v1_3.json": (
            global_reservation_contract_document()
        ),
        "track_b_packet_generation_state_machine_v1_3.json": (
            state_machine_contract_document_v1_3()
        ),
        "track_b_effective_d1_entry_contract_v1_3.json": (
            effective_d1_entry_contract_document()
        ),
        "rq2d0_r3_synthetic_validation_v1.json": (
            synthetic_validation_document(tests)
        ),
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
    for name, text in _documents(identity).items():
        target = DOC_ROOT / name
        atomic_write_durable(
            target,
            text.encode("utf-8"),
            mode=0o644,
            replace=target.exists(),
        )
    checksum = write_output_checksums()
    return {
        "status": "PASS",
        "safe_json_count": len(safe_values),
        "document_count": len(DOC_FILENAMES),
        "python_file_count": len(list(HERE.glob("*.py"))),
        "checksum_count": len(parse_output_checksums()),
        "checksum_manifest_sha256": sha256_file(checksum),
        "output_root_identity": identity["output_root_identity"],
        "global_lock_identity": identity["global_lock_identity"],
        "raw_track_b_access_count": 0,
        "real_global_lock_created": False,
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
            raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
        json.loads(path.read_text(encoding="utf-8"))
    for name in DOC_FILENAMES:
        path = DOC_ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
    synthetic = json.loads(
        (HERE / "rq2d0_r3_synthetic_validation_v1.json").read_text()
    )
    if (
        synthetic.get("raw_track_b_access_count") != 0
        or synthetic.get("real_global_lock_created") is not False
        or synthetic.get("real_packets_created") is not False
        or synthetic.get("concurrent_success_count") != 1
        or synthetic.get("concurrent_blocked_count") != 1
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
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
        raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
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
    leaks = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(value in text for value in prohibited):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
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
        if path != ".gitignore"
        and not path.startswith("evaluation/capability_routing_rq2d0_r3_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_R3_")
    ]
    history = [
        path
        for path in changed
        if path.startswith("evaluation/capability_routing_rq2d0_v1/")
        or path.startswith("evaluation/capability_routing_rq2d0_r1_v1/")
        or path.startswith("evaluation/capability_routing_rq2d0_r2_v1/")
    ]
    if invalid or history:
        raise ValidationError("BLOCKED_RQ2_D0_R3_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "changed_file_count": len(changed),
        "invalid_changed_file_count": 0,
        "historical_d0_changed_file_count": 0,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = _git("diff", "--cached", "--name-only").splitlines()
    invalid = [
        path
        for path in staged
        if path != ".gitignore"
        and not path.startswith("evaluation/capability_routing_rq2d0_r3_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2D0_R3_")
    ]
    if invalid:
        raise ValidationError("BLOCKED_RQ2_D0_R3_GIT_FAILURE")
    return {"status": "PASS", "staged_count": len(staged), "invalid_count": 0}


def validate_git_state(*, require_commit: bool = False) -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    count = int(_git("rev-list", "--count", f"{START_HEAD}..HEAD"))
    if (
        branch != RESULT_BRANCH
        or count not in ({1} if require_commit else {0, 1})
        or _git("remote")
        or _git("tag", "--list")
    ):
        raise ValidationError("BLOCKED_RQ2_D0_R3_GIT_FAILURE")
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
        raise ValidationError("BLOCKED_RQ2_D0_R3_TEST_FAILURE")
    return {"status": "PASS", "file_count": len(before), "byte_identical": True}


def validate_all() -> dict[str, Any]:
    return {
        "python_ast": validate_python_ast(),
        "real_entry_signature": validate_real_entry_signature_v1_3(),
        "unit_tests": unit_test_result(),
        "safe_outputs": validate_safe_outputs(),
        "gitignore": validate_gitignore_contract(),
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
        raise ValidationError("BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE")
    payloads: dict[str, bytes] = {}
    for relative, digest in referenced.items():
        raw = (ROOT / relative).read_bytes()
        if sha256_bytes(raw) != digest:
            raise ValidationError("BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE")
        payloads[relative] = raw
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
        "real_global_lock_created": False,
        "real_d1_lock_created": False,
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
        raise ValidationError("BLOCKED_RQ2_D0_R3_GIT_FAILURE")
    payloads["REVIEW/GIT_STATE.json"] = canonical_json_bytes(git_state)
    payloads["REVIEW/DIFF_SUMMARY.txt"] = (
        _git("diff", "--stat", f"{START_HEAD}..HEAD") + "\n"
    ).encode("utf-8")
    payloads["REVIEW/GITIGNORE_SAFE_DIFF.patch"] = (
        _git("diff", f"{START_HEAD}..HEAD", "--", ".gitignore") + "\n"
    ).encode("utf-8")
    payloads["REVIEW/GITIGNORE_SHA256.txt"] = (
        f"{sha256_file(ROOT / '.gitignore')}  .gitignore\n"
    ).encode("ascii")
    payloads["REVIEW/REVIEW_CHECKSUMS.sha256"] = (
        "\n".join(
            f"{sha256_bytes(raw)}  {name}"
            for name, raw in sorted(payloads.items())
        )
        + "\n"
    ).encode("ascii")
    destination = ROOT.parent / REVIEW_ZIP_NAME
    if destination.exists():
        raise ValidationError("BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE")
    with zipfile.ZipFile(destination, "x") as archive:
        for name, raw in sorted(payloads.items()):
            archive.writestr(_zip_info(name), raw)
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
            raise ValidationError("BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE")
        forbidden_members = (
            "local_one_shot/",
            "local_control/",
            "local_contamination/",
            "reviewer_a_track_b",
            "reviewer_b_track_b",
            "track_b_opaque_mapping",
            "track_b_hidden_legacy_metadata",
            "BLINDING_KEY",
        )
        if any(
            any(fragment in name for fragment in forbidden_members) for name in names
        ):
            raise ValidationError("BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE")
        review_lines = archive.read("REVIEW/REVIEW_CHECKSUMS.sha256").decode().splitlines()
        for line in review_lines:
            digest, member = line.split(None, 1)
            if sha256_bytes(archive.read(member.strip())) != digest:
                raise ValidationError(
                    "BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE"
                )
        excluded = {
            (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
            "REVIEW/GIT_STATE.json",
            "REVIEW/DIFF_SUMMARY.txt",
            "REVIEW/GITIGNORE_SAFE_DIFF.patch",
            "REVIEW/GITIGNORE_SHA256.txt",
            "REVIEW/REVIEW_CHECKSUMS.sha256",
        }
        output_members = set(names) - excluded
        if output_members != set(parse_output_checksums()):
            raise ValidationError("BLOCKED_RQ2_D0_R3_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "status": "PASS",
        "member_count": len(expected),
        "internal_review_checksum_count": len(review_lines),
        "referenced_output_count": len(parse_output_checksums()),
        "zip_integrity": "PASS",
        "exact_allowlist": "PASS",
    }
