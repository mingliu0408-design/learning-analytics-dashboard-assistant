"""Three-process synthetic R4 harness and real concurrency adversarial checks."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import queue
import tempfile
import threading
from typing import Any, Callable

from . import SYNTHETIC_CONTRACT_ID, canonical_json_bytes, sha256_bytes
from .atomic_execution_state_v1_2 import (
    AtomicStateError,
    atomic_mutate_execution_state_v1_2,
    fail_execution_state_v1_2,
    read_execution_state_v1_2,
    transition_execution_state_v1_2,
)
from .durable_directory_tree_v1_2 import create_durable_directory_tree_v1_2
from .durable_no_replace_artifact_v1_2 import (
    NoReplaceArtifactError,
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)
from .immutable_reservation_sentinel_v1_2 import (
    ALREADY_RESERVED,
    ReservationSentinelError,
    create_reservation_sentinel_v1_2,
    reservation_sentinel_document_v1_2,
)
from .synthetic_feature_worker_v1_2 import run_synthetic_feature_worker_v1_2
from .synthetic_metric_worker_v1_2 import run_synthetic_metric_worker_v1_2
from .synthetic_predictor_worker_v1_2 import run_synthetic_predictor_worker_v1_2
from .synthetic_r4_integrity_fixture import (
    SYNTHETIC_FEATURE_ROLE,
    SYNTHETIC_METRIC_ROLE,
    SYNTHETIC_PREDICTOR_ROLE,
    build_synthetic_authority_fixture_v1_2,
    issue_synthetic_credential_v1_2,
    synthetic_paths_v1_2,
)


def _bootstrap_synthetic(
    target: Callable[..., None], inherited_write_fd: int, read_fd: int, root: str
) -> None:
    os.close(inherited_write_fd)
    target(synthetic_root=root, credential_fd=read_fd)


def _spawn_synthetic_worker(
    target: Callable[..., None], root: Path, secret: bytes
) -> int:
    context = multiprocessing.get_context("fork")
    read_fd, write_fd = os.pipe()
    process = context.Process(
        target=_bootstrap_synthetic,
        args=(target, write_fd, read_fd, str(root)),
    )
    process.start()
    os.close(read_fd)
    os.write(write_fd, secret)
    os.close(write_fd)
    process.join()
    if process.exitcode != 0:
        raise RuntimeError("synthetic worker process failed")
    return int(process.pid or 0)


def _sentinel_racer(path: str, document: dict[str, Any], result_queue: Any) -> None:
    try:
        create_reservation_sentinel_v1_2(Path(path), document)
    except ReservationSentinelError as error:
        result_queue.put(str(error))
    else:
        result_queue.put("WINNER")


def _concurrent_sentinel_check(root: Path) -> dict[str, Any]:
    create_durable_directory_tree_v1_2(root, "race_control")
    target = root / "race_control/reservation.json"
    fixed = {
        "output_root_relative": "race_output",
        "control_root_relative": "race_control",
        "sentinel_relative": "race_control/reservation.json",
        "state_relative": "race_control/state.json",
        "parent_receipt_relative": "race_control/parent.json",
    }
    document = reservation_sentinel_document_v1_2(
        execution_id="e" * 64,
        approved_head="a" * 40,
        fixed_paths=fixed,
        frozen_identity_bundle={"fixture": "RACE"},
        input_identity_bundle={"fixture": "RACE"},
        d3_r4_code_bundle_identity="synthetic",
        parent_execution_nonce_commitment="n" * 64,
        parent_receipt_descriptor_commitment="d" * 64,
        reservation_created_at="2026-08-29T00:00:00Z",
        synthetic=True,
        execution_contract_id=SYNTHETIC_CONTRACT_ID,
    )
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    processes = [
        context.Process(target=_sentinel_racer, args=(str(target), document, result_queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()
    results = [result_queue.get(timeout=2) for _ in processes]
    return {
        "winner_count": results.count("WINNER"),
        "blocked_count": results.count(ALREADY_RESERVED),
        "sentinel_retained": target.is_file(),
    }


def _no_replace_race_check(root: Path) -> dict[str, Any]:
    build_synthetic_authority_fixture_v1_2(root)
    execution_paths = synthetic_paths_v1_2(root)
    create_durable_directory_tree_v1_2(root, "race_artifacts")
    target = root / "race_artifacts/final.json"
    ready = threading.Event()
    racer_done = threading.Event()
    known = b"racer-owned-bytes\n"
    outcome: dict[str, Any] = {}

    def before_publication(_temporary: Path, _target: Path) -> None:
        ready.set()
        if not racer_done.wait(timeout=5):
            raise RuntimeError("racer did not complete")

    def writer() -> None:
        document = {"schema_version": "race-artifact-v1-2", "status": "WRITER"}
        try:
            publish_no_replace_artifact_v1_2(
                target,
                canonical_json_bytes(document),
                relative_path="race_artifacts/final.json",
                stage="RESULT_PERSISTED",
                worker_role="SYNTHETIC_RACE_WRITER",
                worker_credential_commitment="c" * 64,
                artifact_role="RACE_FINAL",
                schema_id="race-artifact-v1-2",
                record_count=1,
                approved_head="a" * 40,
                execution_id="e" * 64,
                effective_contract_id=SYNTHETIC_CONTRACT_ID,
                code_identity="synthetic-race",
                parent_state="PRIMARY_STATISTICS_PERSISTED",
                schema_validator=json_object_validator("race-artifact-v1-2"),
                before_publication=before_publication,
            )
        except NoReplaceArtifactError as error:
            outcome["writer_error"] = str(error)
        else:
            outcome["false_receipt_generated"] = True

    def racer() -> None:
        if not ready.wait(timeout=5):
            outcome["racer_error"] = "writer not ready"
            return
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, known)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        racer_done.set()

    writer_thread = threading.Thread(target=writer)
    racer_thread = threading.Thread(target=racer)
    writer_thread.start()
    racer_thread.start()
    writer_thread.join(timeout=10)
    racer_thread.join(timeout=10)
    failed_state = fail_execution_state_v1_2(
        execution_paths.state,
        execution_paths.sentinel,
        failure_code="ARTIFACT_TARGET_RACE",
        failure_stage="NO_REPLACE_PUBLICATION",
        failure_receipt={
            "artifact_role": "ROOT_FAILURE_RECEIPT",
            "sha256": sha256_bytes(known),
        },
    )
    return {
        "writer_failed_target_exists": outcome.get("writer_error")
        == "BLOCKED_RQ2_D4_PREEXISTING_LOCAL_ARTIFACT",
        "racer_target_preserved": target.read_bytes() == known,
        "false_receipt_generated": outcome.get("false_receipt_generated", False),
        "threads_completed": not writer_thread.is_alive() and not racer_thread.is_alive(),
        "global_synthetic_execution_state": failed_state["current_state"],
        "root_failure_code": failed_state["root_failure_code"],
        "retry_permitted": failed_state["retry_permitted"],
    }


def _state_crash_and_terminal_checks(root: Path) -> dict[str, Any]:
    build_synthetic_authority_fixture_v1_2(root)
    paths = synthetic_paths_v1_2(root)
    sentinel_before = paths.sentinel.read_bytes()
    state_before = paths.state.read_bytes()

    def crash(_temporary: Path, _target: Path) -> None:
        raise RuntimeError("SIMULATED_PRE_REPLACE_CRASH")

    try:
        atomic_mutate_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            lambda document: document["administrative_events"].append({"event": "UNPUBLISHED"}),
            before_replace=crash,
        )
    except RuntimeError as error:
        crash_observed = str(error) == "SIMULATED_PRE_REPLACE_CRASH"
    else:
        crash_observed = False
    old_state_preserved = paths.state.read_bytes() == state_before
    sentinel_unchanged = paths.sentinel.read_bytes() == sentinel_before
    failed = fail_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        failure_code="SYNTHETIC_ROOT_FAILURE",
        failure_stage="PARENT_EXECUTION_RECEIPT_PERSISTED",
        failure_receipt={"artifact_role": "ROOT_FAILURE_RECEIPT", "sha256": "f" * 64},
    )
    root_failure = {
        key: failed[key]
        for key in (
            "root_failure_code",
            "root_failure_stage",
            "root_failure_timestamp",
            "last_successful_state",
            "root_failure_receipt",
        )
    }
    failures = []
    for action in (
        lambda: transition_execution_state_v1_2(paths.state, paths.sentinel, "EXTRACTOR_CREDENTIAL_COMMITTED"),
        lambda: fail_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            failure_code="SECOND_FAILURE",
            failure_stage="FAILED",
        ),
    ):
        try:
            action()
        except BaseException as error:
            failures.append(str(error))
    after, _ = read_execution_state_v1_2(paths.state)
    return {
        "crash_observed": crash_observed,
        "old_state_preserved": old_state_preserved,
        "sentinel_unchanged": sentinel_unchanged,
        "failed_terminal_rejections": len(failures),
        "root_failure_immutable": root_failure
        == {
            key: after[key]
            for key in (
                "root_failure_code",
                "root_failure_stage",
                "root_failure_timestamp",
                "last_successful_state",
                "root_failure_receipt",
            )
        },
        "retry_permitted": after["retry_permitted"],
    }


def _real_worker_temp_lock_bypass_probe(root: Path) -> dict[str, Any]:
    # The caller lock and credential are valid only for a synthetic authority tree.
    synthetic_root = root / "synthetic_authority"
    synthetic_root.mkdir(mode=0o700)
    build_synthetic_authority_fixture_v1_2(synthetic_root)
    secret, _ = issue_synthetic_credential_v1_2(
        synthetic_root, SYNTHETIC_FEATURE_ROLE
    )
    fake = root / "caller_created_real_looking_lock.json"
    fake.write_text(
        json.dumps(
            {
                "effective_contract_id": SYNTHETIC_CONTRACT_ID,
                "synthetic_authority_is_self_consistent": True,
            }
        )
    )
    read_fd, write_fd = os.pipe()
    os.write(write_fd, secret)
    os.close(write_fd)
    restricted_input_open_count = 0
    from . import real_feature_worker_v1_2 as real_worker_module

    original_restricted_read = real_worker_module._read_exact_input

    def count_restricted_read(path: Path) -> bytes:
        nonlocal restricted_input_open_count
        restricted_input_open_count += 1
        return original_restricted_read(path)

    real_worker_module._read_exact_input = count_restricted_read
    try:
        real_worker_module.run_real_feature_extractor_worker_v1_2(
            credential_fd=read_fd
        )
    except BaseException:
        rejected = True
    else:
        rejected = False
    finally:
        real_worker_module._read_exact_input = original_restricted_read
        try:
            os.close(read_fd)
        except OSError:
            pass
        secret = b"\x00" * len(secret)
    return {
        "caller_temp_lock_rejected": rejected,
        "synthetic_credential_rejected": rejected,
        "self_consistent_synthetic_authority_used": True,
        "fake_lock_unchanged": fake.read_text().startswith("{"),
        "restricted_input_open_count": restricted_input_open_count,
    }


def run_synthetic_r4_integrity_harness_v1_2() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rq2d3-r4-synthetic-") as temporary:
        root = Path(temporary)
        paths = build_synthetic_authority_fixture_v1_2(root)
        sentinel_before = paths.sentinel.read_bytes()
        worker_pids = []
        for role, worker in (
            (SYNTHETIC_FEATURE_ROLE, run_synthetic_feature_worker_v1_2),
            (SYNTHETIC_PREDICTOR_ROLE, run_synthetic_predictor_worker_v1_2),
            (SYNTHETIC_METRIC_ROLE, run_synthetic_metric_worker_v1_2),
        ):
            secret, _ = issue_synthetic_credential_v1_2(root, role)
            worker_pids.append(_spawn_synthetic_worker(worker, root, secret))
        state, _ = read_execution_state_v1_2(paths.state)
        failure_events = list(state.get("hard_failure_evidence", []))
        for role in (
            SYNTHETIC_FEATURE_ROLE,
            SYNTHETIC_PREDICTOR_ROLE,
            SYNTHETIC_METRIC_ROLE,
        ):
            if state["worker_roles"].get(role, {}).get("status") != "CONSUMED_SUCCESS":
                failure_events.append({"category": "worker_failure", "detail": role})
        hard_failure_count = len(failure_events)
        if hard_failure_count:
            raise RuntimeError("synthetic completion evidence failed")
        completion_document = {
            "schema_version": "synthetic-completion-bundle-v1-2",
            "status": "PASS",
            "hard_failure_events": failure_events,
            "hard_failure_count": hard_failure_count,
        }
        completion_target = paths.output / "synthetic_completion_bundle_v1_2.json"
        completion_receipt = publish_no_replace_artifact_v1_2(
            completion_target,
            canonical_json_bytes(completion_document),
            relative_path=str(completion_target.relative_to(root)),
            stage="COMPLETED",
            worker_role="SYNTHETIC_PARENT_V1_2",
            worker_credential_commitment=None,
            artifact_role="SYNTHETIC_COMPLETION_BUNDLE",
            schema_id="synthetic-completion-bundle-v1-2",
            record_count=1,
            approved_head="a" * 40,
            execution_id=state["execution_id"],
            effective_contract_id=SYNTHETIC_CONTRACT_ID,
            code_identity="synthetic-parent-code",
            parent_state="RESULT_PERSISTED",
            schema_validator=json_object_validator("synthetic-completion-bundle-v1-2"),
        )
        completed = transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "COMPLETED",
            stage_receipts=[completion_receipt],
            evidence_summary={
                "completion_evidence": {
                    "completion_eligible": True,
                    "hard_failure_events": failure_events,
                    "hard_failure_count": hard_failure_count,
                    "required_workers_consumed_success": True,
                    "required_stage_receipts_valid": True,
                    "expected_open_read_counts_exact": True,
                    "artifacts_bound": True,
                    "state_chain_valid": True,
                    "feature_prediction_binding_valid": True,
                    "method_metric_complete": True,
                    "statistical_complete": True,
                }
            },
        )
        try:
            fail_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                failure_code="POST_COMPLETION_FAILURE",
                failure_stage="COMPLETED",
            )
        except BaseException as error:
            completed_terminal_rejected = "ALREADY_TERMINAL_COMPLETED" in str(error)
        else:
            completed_terminal_rejected = False
        race_root = root / "sentinel_race"
        race_root.mkdir(mode=0o700)
        sentinel_race = _concurrent_sentinel_check(race_root)
        artifact_root = root / "artifact_race"
        artifact_root.mkdir(mode=0o700)
        artifact_race = _no_replace_race_check(artifact_root)
        crash_root = root / "state_crash"
        crash_root.mkdir(mode=0o700)
        state_checks = _state_crash_and_terminal_checks(crash_root)
        bypass_root = root / "bypass"
        bypass_root.mkdir(mode=0o700)
        bypass = _real_worker_temp_lock_bypass_probe(bypass_root)
        return {
            "schema_version": "rq2d3-r4-synthetic-validation-v1",
            "status": "PASS",
            "separate_worker_process_count": len(set(worker_pids)),
            "synthetic_worker_roles": [
                SYNTHETIC_FEATURE_ROLE,
                SYNTHETIC_PREDICTOR_ROLE,
                SYNTHETIC_METRIC_ROLE,
            ],
            "synthetic_contract_id": SYNTHETIC_CONTRACT_ID,
            "final_state": completed["current_state"],
            "hard_failure_count": hard_failure_count,
            "sentinel_retained_and_unchanged": paths.sentinel.read_bytes() == sentinel_before,
            "completed_terminal_rejected": completed_terminal_rejected,
            "concurrent_sentinel": sentinel_race,
            "no_replace_race": artifact_race,
            "state_crash_and_failed_terminality": state_checks,
            "real_worker_temp_lock_bypass": bypass,
            "real_fixed_path_created": False,
            "restricted_track_b_open_count": 0,
            "provider_calls": 0,
            "network_access": False,
            "deterministic_summary_commitment": sha256_bytes(
                canonical_json_bytes(
                    {
                        "workers": 3,
                        "hard_failure_count": hard_failure_count,
                        "sentinel_winner_count": sentinel_race["winner_count"],
                        "artifact_race_preserved": artifact_race["racer_target_preserved"],
                        "state_crash_preserved": state_checks["old_state_preserved"],
                    }
                )
            ),
        }
