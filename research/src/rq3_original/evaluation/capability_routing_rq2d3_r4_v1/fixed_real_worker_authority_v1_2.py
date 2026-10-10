"""Fixed repository-global authority for the three real D4 workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
from typing import Any, Mapping, Sequence

from . import (
    C0_EMBEDDINGS_SHA256,
    C0_INDEX_SHA256,
    COMBINED_SHA256,
    COMBINED_SIZE,
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    EFFECTIVE_CONTRACT_ID,
    GROUPING_SIZE,
    LABEL_SHA256,
    LABEL_SIZE,
    METRIC_IMPLEMENTATION_SHA256,
    P1_POLICY_SHA256,
    RECORD_COUNT,
    RQ2D3R4Error,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    utc_timestamp,
)
from .atomic_execution_state_v1_2 import (
    atomic_mutate_execution_state_v1_2,
    read_execution_state_v1_2,
    transition_execution_state_v1_2,
)
from .fixed_real_d4_paths_v1_2 import (
    CONTROL_ROOT_RELATIVE,
    OUTPUT_ROOT_RELATIVE,
    PARENT_RECEIPT_RELATIVE,
    SENTINEL_RELATIVE,
    STATE_RELATIVE,
    FixedRealD4PathsV1_2,
    resolve_fixed_real_d4_paths_v1_2,
)
from .immutable_reservation_sentinel_v1_2 import read_reservation_sentinel_v1_2
from .parent_execution_receipt_v1_2 import read_parent_execution_receipt_v1_2
from .parent_execution_receipt_v1_2 import parent_receipt_descriptor_commitment_v1_2
from .strict_project_relative_path import project_path


class FixedWorkerAuthorityError(RQ2D3R4Error):
    pass


FEATURE_ROLE = "TRACK_B_FEATURE_EXTRACTOR_V1_2"
PREDICTOR_ROLE = "TRACK_B_B0_B1_P1_PREDICTOR_V1_2"
METRIC_ROLE = "TRACK_B_FINAL_METRIC_WORKER_V1_2"
ROLES = (FEATURE_ROLE, PREDICTOR_ROLE, METRIC_ROLE)
CREDENTIAL_DOMAIN = b"RQ2_D4_FIXED_REAL_WORKER_CREDENTIAL_V1_2\x00"

REAL_CODE_BUNDLE_FILES = (
    "effective_d4_contract_v1_2.py",
    "fixed_real_d4_paths_v1_2.py",
    "strict_project_relative_path.py",
    "immutable_reservation_sentinel_v1_2.py",
    "parent_execution_receipt_v1_2.py",
    "atomic_execution_state_v1_2.py",
    "terminal_state_machine_v1_2.py",
    "fixed_real_worker_authority_v1_2.py",
    "real_feature_worker_v1_2.py",
    "real_predictor_worker_v1_2.py",
    "real_metric_worker_v1_2.py",
    "durable_directory_tree_v1_2.py",
    "durable_no_replace_artifact_v1_2.py",
    "strict_receipt_verifier_v1_2.py",
    "completion_evidence_v1_2.py",
    "completion_bundle_v1_2.py",
)

ROLE_CONFIG = {
    FEATURE_ROLE: {
        "sequence": 1,
        "issue_predecessor": "PARENT_EXECUTION_RECEIPT_PERSISTED",
        "commit_state": "EXTRACTOR_CREDENTIAL_COMMITTED",
        "module": "real_feature_worker_v1_2.py",
    },
    PREDICTOR_ROLE: {
        "sequence": 2,
        "issue_predecessor": "FEATURE_FIREWALL_VERIFIED",
        "commit_state": "PREDICTOR_CREDENTIAL_COMMITTED",
        "module": "real_predictor_worker_v1_2.py",
    },
    METRIC_ROLE: {
        "sequence": 3,
        "issue_predecessor": "SECONDARY_SCOPE_METADATA_PERSISTED",
        "commit_state": "METRIC_CREDENTIAL_COMMITTED",
        "module": "real_metric_worker_v1_2.py",
    },
}


@dataclass(frozen=True)
class FixedWorkerDescriptorV1_2:
    worker_role: str
    role_sequence_number: int
    issue_predecessor_state: str
    credential_commit_state: str
    execution_id: str
    approved_head: str
    effective_contract_id: str
    sentinel_sha256: str
    parent_receipt_sha256: str
    worker_code_identity: str


@dataclass(frozen=True)
class FixedWorkerContextV1_2:
    worker_role: str
    credential_commitment: str
    descriptor: FixedWorkerDescriptorV1_2
    paths: FixedRealD4PathsV1_2
    state_version_at_claim: int


def fixed_real_code_bundle_identity_v1_2() -> str:
    here = Path(__file__).parent
    entries = [
        {"relative_name": name, "sha256": sha256_file(here / name)}
        for name in REAL_CODE_BUNDLE_FILES
    ]
    return sha256_bytes(canonical_json_bytes(entries))


def _worker_code_identity(role: str) -> str:
    config = ROLE_CONFIG.get(role)
    if config is None:
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    return sha256_file(Path(__file__).parent / str(config["module"]))


def credential_commitment_v1_2(
    secret: bytes, descriptor: FixedWorkerDescriptorV1_2
) -> str:
    if len(secret) != 32 or descriptor.worker_role not in ROLES:
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    return hashlib.sha256(
        CREDENTIAL_DOMAIN
        + secret
        + b"\x00"
        + canonical_json_bytes(asdict(descriptor)).rstrip(b"\n")
    ).hexdigest()


def _git_head(root: Path) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    return process.stdout.strip()


def _require_regular_0600(path: Path) -> None:
    observed = os.lstat(path)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_ISLNK(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o600
    ):
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")


def _load_fixed_real_authority(
    role: str,
) -> tuple[
    FixedRealD4PathsV1_2,
    dict[str, Any],
    bytes,
    dict[str, Any],
    bytes,
    dict[str, Any],
    bytes,
]:
    if role not in ROLES:
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    paths = resolve_fixed_real_d4_paths_v1_2()
    exact_paths = {
        "output_root": paths.repository_root / OUTPUT_ROOT_RELATIVE,
        "control_root": paths.repository_root / CONTROL_ROOT_RELATIVE,
        "sentinel": paths.repository_root / SENTINEL_RELATIVE,
        "state": paths.repository_root / STATE_RELATIVE,
        "parent_receipt": paths.repository_root / PARENT_RECEIPT_RELATIVE,
    }
    if any(getattr(paths, name) != expected for name, expected in exact_paths.items()):
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    for relative, expected in (
        (SENTINEL_RELATIVE, paths.sentinel),
        (STATE_RELATIVE, paths.state),
        (PARENT_RECEIPT_RELATIVE, paths.parent_receipt),
    ):
        if project_path(paths.repository_root, relative) != expected:
            raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    sentinel, sentinel_value = read_reservation_sentinel_v1_2(paths.sentinel)
    _require_regular_0600(paths.state)
    state, state_value = read_execution_state_v1_2(paths.state)
    _require_regular_0600(paths.parent_receipt)
    parent, parent_value = read_parent_execution_receipt_v1_2(paths.parent_receipt)
    sentinel_sha = sha256_bytes(sentinel_value)
    parent_sha = sha256_bytes(parent_value)
    fixed_paths = {
        "output_root_relative": OUTPUT_ROOT_RELATIVE,
        "control_root_relative": CONTROL_ROOT_RELATIVE,
        "sentinel_relative": SENTINEL_RELATIVE,
        "state_relative": STATE_RELATIVE,
        "parent_receipt_relative": PARENT_RECEIPT_RELATIVE,
    }
    frozen = sentinel.get("frozen_identity_bundle", {})
    inputs = sentinel.get("expected_input_identities", {})
    expected_parent_descriptor = parent_receipt_descriptor_commitment_v1_2(
        relative_path=PARENT_RECEIPT_RELATIVE,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        approved_head=str(sentinel.get("approved_head")),
    )
    observed_code_bundle = fixed_real_code_bundle_identity_v1_2()
    if (
        sentinel.get("execution_contract_id") != EFFECTIVE_CONTRACT_ID
        or sentinel.get("synthetic") is not False
        or sentinel.get("retry_permitted") is not False
        or sentinel.get("access_consumed") is not True
        or any(sentinel.get(f"fixed_{key}") != value for key, value in fixed_paths.items())
        or sentinel.get("parent_receipt_descriptor_commitment")
        != expected_parent_descriptor
        or frozen.get("d2b_gold_bundle_sha256") != D2B_GOLD_BUNDLE_SHA256
        or frozen.get("d3_r1_statistical_contract_sha256") != D3_R1_STATISTICAL_SHA256
        or frozen.get("d3_r2_grouping_sha256") != D3_R2_GROUPING_SHA256
        or frozen.get("metric_implementation_sha256") != METRIC_IMPLEMENTATION_SHA256
        or frozen.get("c0_index_sha256") != C0_INDEX_SHA256
        or frozen.get("c0_embeddings_sha256") != C0_EMBEDDINGS_SHA256
        or frozen.get("p1_policy_sha256") != P1_POLICY_SHA256
        or frozen.get("d3_r4_code_bundle_identity") != observed_code_bundle
        or sentinel.get("d3_r4_code_bundle_identity") != observed_code_bundle
        or inputs.get("combined_source")
        != {"sha256": COMBINED_SHA256, "size_bytes": COMBINED_SIZE, "record_count": RECORD_COUNT}
        or inputs.get("label_gold")
        != {"sha256": LABEL_SHA256, "size_bytes": LABEL_SIZE, "record_count": RECORD_COUNT}
        or inputs.get("grouping")
        != {
            "sha256": D3_R2_GROUPING_SHA256,
            "size_bytes": GROUPING_SIZE,
            "record_count": RECORD_COUNT,
            "group_count": 24,
            "group_size": 2,
        }
        or state.get("effective_contract_id") != EFFECTIVE_CONTRACT_ID
        or state.get("synthetic") is not False
        or state.get("execution_id") != sentinel.get("execution_id")
        or state.get("approved_head") != sentinel.get("approved_head")
        or state.get("sentinel_sha256") != sentinel_sha
        or state.get("parent_receipt_sha256") != parent_sha
        or parent.get("effective_contract_id") != EFFECTIVE_CONTRACT_ID
        or parent.get("synthetic") is not False
        or parent.get("execution_id") != state.get("execution_id")
        or parent.get("approved_head") != state.get("approved_head")
        or parent.get("sentinel_identity", {}).get("sha256") != sentinel_sha
        or parent.get("sentinel_relative") != SENTINEL_RELATIVE
        or parent.get("state_relative") != STATE_RELATIVE
        or parent.get("parent_receipt_relative") != PARENT_RECEIPT_RELATIVE
        or parent.get("parent_nonce_commitment")
        != sentinel.get("parent_execution_nonce_commitment")
        or parent.get("fixed_real_paths") != fixed_paths
        or parent.get("input_identity_commitments") != inputs
        or parent.get("parent_code_identity")
        != sha256_file(Path(__file__).parent / "effective_d4_contract_v1_2.py")
        or _git_head(paths.repository_root) != state.get("approved_head")
    ):
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    return paths, sentinel, sentinel_value, state, state_value, parent, parent_value


def _descriptor_for_state(
    role: str,
    state: Mapping[str, Any],
    sentinel_value: bytes,
    parent_value: bytes,
) -> FixedWorkerDescriptorV1_2:
    config = ROLE_CONFIG[role]
    return FixedWorkerDescriptorV1_2(
        worker_role=role,
        role_sequence_number=int(config["sequence"]),
        issue_predecessor_state=str(config["issue_predecessor"]),
        credential_commit_state=str(config["commit_state"]),
        execution_id=str(state["execution_id"]),
        approved_head=str(state["approved_head"]),
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        sentinel_sha256=sha256_bytes(sentinel_value),
        parent_receipt_sha256=sha256_bytes(parent_value),
        worker_code_identity=_worker_code_identity(role),
    )


def issue_fixed_real_worker_credential_v1_2(worker_role: str) -> tuple[bytes, str]:
    """Parent-only issuer; paths and descriptor are always internally derived."""

    paths, _, sentinel_value, state, _, _, parent_value = _load_fixed_real_authority(
        worker_role
    )
    config = ROLE_CONFIG[worker_role]
    if (
        state.get("current_state") != config["issue_predecessor"]
        or worker_role in state.get("worker_roles", {})
    ):
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    descriptor = _descriptor_for_state(worker_role, state, sentinel_value, parent_value)
    secret = secrets.token_bytes(32)
    commitment = credential_commitment_v1_2(secret, descriptor)

    def commit(document: dict[str, Any]) -> None:
        if worker_role in document.get("worker_roles", {}):
            raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
        document["worker_roles"][worker_role] = {
            "status": "ISSUED",
            "descriptor": asdict(descriptor),
            "credential_commitment": commitment,
            "issued_at": utc_timestamp(),
            "stage_receipts": [],
            "open_read_counts": {},
            "firewall_summary": {},
        }

    transition_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        str(config["commit_state"]),
        stage_receipts=[
            {
                "artifact_role": "WORKER_CREDENTIAL_COMMITMENT",
                "worker_role": worker_role,
                "sha256": commitment,
            }
        ],
        evidence_summary={"worker_role": worker_role, "credential_committed": True},
        mutation=commit,
    )
    return secret, commitment


def _read_credential_once(credential_fd: int) -> bytearray:
    try:
        value = os.read(credential_fd, 33)
    except OSError as error:
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY") from error
    finally:
        try:
            os.close(credential_fd)
        except OSError:
            pass
    if len(value) != 32:
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    return bytearray(value)


def claim_fixed_real_worker_authority_v1_2(
    worker_role: str, *, credential_fd: int
) -> FixedWorkerContextV1_2:
    """Validate fixed sentinel/state/parent receipt before any restricted business import."""

    paths, _, sentinel_value, state, _, _, parent_value = _load_fixed_real_authority(
        worker_role
    )
    entry = state.get("worker_roles", {}).get(worker_role)
    config = ROLE_CONFIG[worker_role]
    expected_descriptor = _descriptor_for_state(
        worker_role, state, sentinel_value, parent_value
    )
    if (
        state.get("current_state") != config["commit_state"]
        or not entry
        or entry.get("status") != "ISSUED"
        or entry.get("descriptor") != asdict(expected_descriptor)
    ):
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
    secret = _read_credential_once(credential_fd)
    try:
        commitment = credential_commitment_v1_2(bytes(secret), expected_descriptor)
    finally:
        for index in range(len(secret)):
            secret[index] = 0
    if commitment != entry.get("credential_commitment"):
        raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")

    def claim(document: dict[str, Any]) -> None:
        current = document.get("worker_roles", {}).get(worker_role)
        if (
            document.get("current_state") != config["commit_state"]
            or not current
            or current.get("status") != "ISSUED"
            or current.get("credential_commitment") != commitment
            or current.get("descriptor") != asdict(expected_descriptor)
        ):
            raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
        current["status"] = "CLAIMED"
        current["claimed_at"] = utc_timestamp()
        document["administrative_events"].append(
            {
                "event": "WORKER_CREDENTIAL_CLAIMED",
                "worker_role": worker_role,
                "credential_commitment": commitment,
                "timestamp": utc_timestamp(),
            }
        )

    updated = atomic_mutate_execution_state_v1_2(
        paths.state, paths.sentinel, claim
    )
    return FixedWorkerContextV1_2(
        worker_role=worker_role,
        credential_commitment=commitment,
        descriptor=expected_descriptor,
        paths=paths,
        state_version_at_claim=int(updated["state_version"]),
    )


def mark_fixed_real_worker_consumed_success_v1_2(
    context: FixedWorkerContextV1_2,
    *,
    stage_receipts: Sequence[Mapping[str, Any]],
    open_read_counts: Mapping[str, int],
    firewall_summary: Mapping[str, Any],
) -> dict[str, Any]:
    def consume(document: dict[str, Any]) -> None:
        entry = document.get("worker_roles", {}).get(context.worker_role)
        if (
            not entry
            or entry.get("status") != "CLAIMED"
            or entry.get("credential_commitment") != context.credential_commitment
        ):
            raise FixedWorkerAuthorityError("BLOCKED_RQ2_D4_WORKER_AUTHORITY")
        entry["status"] = "CONSUMED_SUCCESS"
        entry["consumed_at"] = utc_timestamp()
        entry["stage_receipts"] = [dict(row) for row in stage_receipts]
        entry["open_read_counts"] = dict(open_read_counts)
        entry["firewall_summary"] = dict(firewall_summary)
        for key, value in open_read_counts.items():
            document["open_read_counters"][key] = value
            document["open_read_counters"][f"{context.worker_role}:{key}"] = value
        document["firewall_evidence"].append(dict(firewall_summary))

    return atomic_mutate_execution_state_v1_2(
        context.paths.state, context.paths.sentinel, consume
    )


def fixed_real_worker_authority_contract_document_v1_2() -> dict[str, object]:
    return {
        "schema_version": "track-b-fixed-real-worker-authority-contract-v1-2",
        "status": "FROZEN",
        "roles": list(ROLES),
        "worker_signatures": {
            FEATURE_ROLE: "run_real_feature_extractor_worker_v1_2(*, credential_fd: int)",
            PREDICTOR_ROLE: "run_real_predictor_worker_v1_2(*, credential_fd: int)",
            METRIC_ROLE: "run_real_metric_worker_v1_2(*, credential_fd: int)",
        },
        "fixed_repository_root_source": "git rev-parse --show-toplevel from code checkout",
        "fixed_sentinel": SENTINEL_RELATIVE,
        "fixed_state": STATE_RELATIVE,
        "fixed_parent_receipt": PARENT_RECEIPT_RELATIVE,
        "caller_path_parameter": False,
        "caller_identity_parameter": False,
        "caller_descriptor_parameter": False,
        "synthetic_parameter": False,
        "credential_transport": "INHERITED_ANONYMOUS_PIPE_FD",
        "credential_read_count": 1,
        "credential_bytes": 32,
        "credential_reuse_permitted": False,
        "d3_r4_code_bundle_bound_to_sentinel": True,
        "d3_r4_code_bundle_reverified_by_each_worker": True,
        "claim_before_restricted_import": True,
        "claim_before_restricted_open": True,
        "temporary_lock_authorises_real_worker": False,
        "synthetic_state_authorises_real_worker": False,
    }
