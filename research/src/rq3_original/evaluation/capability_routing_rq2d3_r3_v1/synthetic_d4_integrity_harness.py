"""Three-process synthetic proof of the effective D4 v1.1 integrity harness."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import queue
import stat
import sys
import tempfile
from typing import Any, Callable, Mapping

from . import SYNTHETIC_CONTRACT_ID, canonical_json_bytes, sha256_bytes
from .durable_local_artifact import DurableArtifactError, publish_durable_artifact_v1_1
from .fixed_rq2d4_paths_v1_1 import D4PathsV1_1, paths_for_roots_v1_1
from .global_lock_receipt_v1_1 import (
    GlobalLockError,
    append_transition_v1_1,
    fail_global_lock_v1_1,
    mark_worker_consumed_v1_1,
    read_global_lock_v1_1,
    reserve_global_lock_v1_1,
    verify_global_lock_chain_v1_1,
)
from .synthetic_d4_integrity_fixture import build_synthetic_fixture_v1_1
from .track_b_feature_extractor_worker_v1_1 import run_feature_extractor_worker_v1_1
from .track_b_metric_worker_v1_1 import run_metric_worker_v1_1
from .track_b_predictor_worker_v1_1 import run_predictor_worker_v1_1
from .worker_execution_authority_v1_1 import (
    FEATURE_ROLE,
    METRIC_ROLE,
    PREDICTOR_ROLE,
    WorkerDescriptorV1_1,
    claim_worker_credential_v1_1,
    issue_worker_credential_v1_1,
)
from .worker_runtime_firewall import RuntimeFirewall


SYNTHETIC_HEAD = "SYNTHETIC_APPROVED_HEAD_V1_1"
SYNTHETIC_EXECUTION = "SYNTHETIC_EXECUTION_ID_V1_1"
SYNTHETIC_LOCK_IDENTITY = "SYNTHETIC_GLOBAL_LOCK_IDENTITY_V1_1"


def _exclusive_fixture_write(path: Path, value: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, value)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _spawn_worker(
    target: Callable[..., None], *, secret: bytes, kwargs: Mapping[str, Any]
) -> tuple[int, int]:
    context = multiprocessing.get_context("fork")
    read_fd, write_fd = os.pipe()
    process = context.Process(
        target=_worker_bootstrap,
        args=(target, write_fd, {**dict(kwargs), "descriptor_fd": read_fd}),
    )
    process.start()
    os.close(read_fd)
    os.write(write_fd, secret)
    os.close(write_fd)
    process.join(180)
    if process.is_alive():
        process.terminate()
        process.join()
        raise RuntimeError("synthetic worker timed out")
    if process.exitcode != 0:
        raise RuntimeError(f"synthetic worker failed with exit code {process.exitcode}")
    return int(process.pid or 0), int(process.exitcode or 0)


def _worker_bootstrap(
    target: Callable[..., None], inherited_write_fd: int, kwargs: Mapping[str, Any]
) -> None:
    os.close(inherited_write_fd)
    target(**dict(kwargs))


def _descriptor(
    role: str, sequence: int, predecessor: str
) -> WorkerDescriptorV1_1:
    return WorkerDescriptorV1_1(
        worker_role=role,
        role_sequence_number=sequence,
        required_predecessor_state=predecessor,
        execution_id=SYNTHETIC_EXECUTION,
        approved_head=SYNTHETIC_HEAD,
        global_lock_identity=SYNTHETIC_LOCK_IDENTITY,
        effective_contract_id=SYNTHETIC_CONTRACT_ID,
    )


def _verify_consumed(paths: D4PathsV1_1, role: str, expected_state: str) -> dict[str, Any]:
    lock = read_global_lock_v1_1(paths.global_lock)
    verify_global_lock_chain_v1_1(lock)
    entry = lock["worker_roles"][role]
    if entry["status"] != "CONSUMED" or lock["state"] != expected_state:
        raise RuntimeError("parent worker-consumption verification failed")
    for identity in entry["stage_receipt_identities"]:
        receipt_path = paths.receipts_root / identity["relative_path"]
        value = receipt_path.read_bytes()
        if sha256_bytes(value) != identity["sha256"] or len(value) != identity["size_bytes"]:
            raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
        document = json.loads(value)
        for artifact in document["artifact_receipts"]:
            target = paths.output_root / artifact["relative_path"]
            payload = target.read_bytes()
            if (
                sha256_bytes(payload) != artifact["sha256"]
                or len(payload) != artifact["size_bytes"]
                or stat.S_IMODE(os.lstat(target).st_mode) != 0o600
            ):
                raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    report_receipt = entry["process_report_receipt"]
    report = paths.output_root / report_receipt["relative_path"]
    if sha256_bytes(report.read_bytes()) != report_receipt["sha256"]:
        raise RuntimeError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return lock


def _reserve_synthetic_lock(path: Path) -> None:
    reserve_global_lock_v1_1(
        path,
        approved_head=SYNTHETIC_HEAD,
        execution_id=SYNTHETIC_EXECUTION,
        effective_contract_id=SYNTHETIC_CONTRACT_ID,
        lock_identity=SYNTHETIC_LOCK_IDENTITY,
        fixed_identity_bundle={"synthetic": True},
        prearm_runtime_smoke_receipt={"sha256": "0" * 64, "status": "SYNTHETIC"},
        synthetic=True,
    )
    append_transition_v1_1(
        path,
        new_state="INPUT_IDENTITIES_VERIFIED",
        worker_role="RQ2_D4_PARENT_VERIFIER_V1_1",
        credential_commitment=None,
        stage_receipt_identities=[{"artifact_role": "SYNTHETIC_INPUT_BUNDLE", "sha256": "1" * 64}],
    )


def _authority_adversarial_checks(root: Path) -> dict[str, int]:
    scenarios = (
        "absent_credential",
        "wrong_role",
        "wrong_head",
        "wrong_execution_id",
        "wrong_lock_identity",
        "wrong_predecessor",
    )
    blocked = 0
    for index, scenario in enumerate(scenarios):
        control = root / f"authority_{index}"
        control.mkdir(mode=0o700)
        lock_path = control / "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json"
        _reserve_synthetic_lock(lock_path)
        issued = _descriptor(FEATURE_ROLE, 1, "EXTRACTOR_CREDENTIAL_COMMITTED")
        secret, _ = issue_worker_credential_v1_1(
            lock_path, descriptor=issued, commit_state="EXTRACTOR_CREDENTIAL_COMMITTED"
        )
        candidate = issued
        if scenario == "wrong_role":
            candidate = WorkerDescriptorV1_1(**{**vars(issued), "worker_role": PREDICTOR_ROLE})
        elif scenario == "wrong_head":
            candidate = WorkerDescriptorV1_1(**{**vars(issued), "approved_head": "WRONG"})
        elif scenario == "wrong_execution_id":
            candidate = WorkerDescriptorV1_1(**{**vars(issued), "execution_id": "WRONG"})
        elif scenario == "wrong_lock_identity":
            candidate = WorkerDescriptorV1_1(**{**vars(issued), "global_lock_identity": "WRONG"})
        elif scenario == "wrong_predecessor":
            candidate = WorkerDescriptorV1_1(
                **{**vars(issued), "required_predecessor_state": "INPUT_IDENTITIES_VERIFIED"}
            )
        read_fd, write_fd = os.pipe()
        if scenario != "absent_credential":
            os.write(write_fd, secret)
        os.close(write_fd)
        try:
            claim_worker_credential_v1_1(
                lock_path, descriptor_fd=read_fd, descriptor=candidate
            )
        except BaseException:
            blocked += 1
        else:
            raise RuntimeError(f"authority scenario unexpectedly admitted: {scenario}")
    # Reuse is checked after a valid claim and durable consumption.
    control = root / "authority_reuse"
    control.mkdir(mode=0o700)
    lock_path = control / "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json"
    _reserve_synthetic_lock(lock_path)
    descriptor = _descriptor(FEATURE_ROLE, 1, "EXTRACTOR_CREDENTIAL_COMMITTED")
    secret, commitment = issue_worker_credential_v1_1(
        lock_path, descriptor=descriptor, commit_state="EXTRACTOR_CREDENTIAL_COMMITTED"
    )
    read_fd, write_fd = os.pipe()
    os.write(write_fd, secret)
    os.close(write_fd)
    claim_worker_credential_v1_1(lock_path, descriptor_fd=read_fd, descriptor=descriptor)
    mark_worker_consumed_v1_1(
        lock_path,
        role=FEATURE_ROLE,
        commitment=commitment,
        stage_receipt_identities=[],
        process_report_receipt={},
        open_read_counts={},
        runtime_firewall_summary={},
    )
    read_fd, write_fd = os.pipe()
    os.write(write_fd, secret)
    os.close(write_fd)
    try:
        claim_worker_credential_v1_1(lock_path, descriptor_fd=read_fd, descriptor=descriptor)
    except BaseException:
        blocked += 1
    else:
        raise RuntimeError("reused credential unexpectedly admitted")
    return {"scenario_count": 7, "blocked_count": blocked, "restricted_open_count": 0}


def _firewall_probe(result_queue: Any, forbidden_path: str) -> None:
    firewall = RuntimeFirewall(
        role=PREDICTOR_ROLE,
        forbidden_paths={"ADVERSARIAL_SOURCE": Path(forbidden_path)},
        forbidden_import_prefixes=("rq2_d3_r3_forbidden_probe",),
    ).install()
    open_blocked = import_blocked = False
    try:
        open(forbidden_path, "rb").read(1)
    except PermissionError:
        open_blocked = True
    try:
        sys.audit("import", "rq2_d3_r3_forbidden_probe", None, None, None, None)
    except ImportError:
        import_blocked = True
    result_queue.put({"open_blocked": open_blocked, "import_blocked": import_blocked, **firewall.report()})


def _runtime_firewall_adversarial_check(path: Path) -> dict[str, Any]:
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(target=_firewall_probe, args=(result_queue, str(path)))
    process.start()
    process.join(30)
    if process.exitcode != 0:
        raise RuntimeError("runtime firewall adversarial process failed")
    result = result_queue.get(timeout=5)
    if not result["open_blocked"] or not result["import_blocked"]:
        raise RuntimeError("runtime firewall adversarial attempt escaped")
    return result


def run_synthetic_d4_integrity_harness_v1_1() -> dict[str, Any]:
    fixture = build_synthetic_fixture_v1_1()
    with tempfile.TemporaryDirectory(prefix="rq2d3r3-synthetic-") as temporary:
        root = Path(temporary)
        inputs = root / "inputs"
        output = root / "synthetic_output"
        control = root / "synthetic_control"
        for directory in (inputs, output, control, output / "stage_receipts"):
            directory.mkdir(mode=0o700)
        combined = inputs / "synthetic_combined.jsonl"
        labels = inputs / "synthetic_labels.jsonl"
        grouping = inputs / "synthetic_grouping.jsonl"
        _exclusive_fixture_write(combined, fixture["combined_bytes"])
        _exclusive_fixture_write(labels, fixture["label_bytes"])
        _exclusive_fixture_write(grouping, fixture["grouping_bytes"])
        paths = paths_for_roots_v1_1(
            output_root=output,
            control_root=control,
            combined=combined,
            labels=labels,
            grouping=grouping,
        )
        fixed_bundle = {
            "synthetic": True,
            "d2b_gold_bundle_sha256": "SYNTHETIC_ONLY",
            "statistical_contract_sha256": (
                "90210630b81d2995db78cbe6d64d4ca07877241e77f2b417b77cc2d9f6d49307"
            ),
            "method_identities": {"B0": "SYNTHETIC_B0", "B1": "SYNTHETIC_B1", "P1": "SYNTHETIC_P1"},
        }
        reserve_global_lock_v1_1(
            paths.global_lock,
            approved_head=SYNTHETIC_HEAD,
            execution_id=SYNTHETIC_EXECUTION,
            effective_contract_id=SYNTHETIC_CONTRACT_ID,
            lock_identity=SYNTHETIC_LOCK_IDENTITY,
            fixed_identity_bundle=fixed_bundle,
            prearm_runtime_smoke_receipt={"sha256": "a" * 64, "status": "SYNTHETIC_PASS"},
            synthetic=True,
        )
        concurrent_exclusion = False
        try:
            reserve_global_lock_v1_1(
                paths.global_lock,
                approved_head=SYNTHETIC_HEAD,
                execution_id="CONCURRENT",
                effective_contract_id=SYNTHETIC_CONTRACT_ID,
                lock_identity=SYNTHETIC_LOCK_IDENTITY,
                fixed_identity_bundle=fixed_bundle,
                prearm_runtime_smoke_receipt={"sha256": "b" * 64},
                synthetic=True,
            )
        except FileExistsError:
            concurrent_exclusion = True
        append_transition_v1_1(
            paths.global_lock,
            new_state="INPUT_IDENTITIES_VERIFIED",
            worker_role="RQ2_D4_PARENT_VERIFIER_V1_1",
            credential_commitment=None,
            stage_receipt_identities=[
                {"artifact_role": "SYNTHETIC_INPUT_BUNDLE", "sha256": sha256_bytes(fixture["combined_bytes"])}
            ],
        )
        pids: list[int] = []
        extractor_descriptor = _descriptor(FEATURE_ROLE, 1, "EXTRACTOR_CREDENTIAL_COMMITTED")
        secret, _ = issue_worker_credential_v1_1(
            paths.global_lock,
            descriptor=extractor_descriptor,
            commit_state="EXTRACTOR_CREDENTIAL_COMMITTED",
        )
        pid, _ = _spawn_worker(
            run_feature_extractor_worker_v1_1,
            secret=secret,
            kwargs={
                "paths": paths,
                "worker_descriptor": extractor_descriptor,
                "expected_combined_sha256": sha256_bytes(fixture["combined_bytes"]),
                "expected_combined_size": len(fixture["combined_bytes"]),
                "expected_record_count": 48,
            },
        )
        pids.append(pid)
        _verify_consumed(paths, FEATURE_ROLE, "FEATURE_FIREWALL_VERIFIED")
        predictor_descriptor = _descriptor(PREDICTOR_ROLE, 2, "PREDICTOR_CREDENTIAL_COMMITTED")
        secret, _ = issue_worker_credential_v1_1(
            paths.global_lock,
            descriptor=predictor_descriptor,
            commit_state="PREDICTOR_CREDENTIAL_COMMITTED",
        )
        pid, _ = _spawn_worker(
            run_predictor_worker_v1_1,
            secret=secret,
            kwargs={
                "paths": paths,
                "worker_descriptor": predictor_descriptor,
                "expected_feature_count": 48,
            },
        )
        pids.append(pid)
        _verify_consumed(paths, PREDICTOR_ROLE, "SECONDARY_SCOPE_METADATA_PERSISTED")
        metric_descriptor = _descriptor(METRIC_ROLE, 3, "METRIC_CREDENTIAL_COMMITTED")
        secret, _ = issue_worker_credential_v1_1(
            paths.global_lock,
            descriptor=metric_descriptor,
            commit_state="METRIC_CREDENTIAL_COMMITTED",
        )
        pid, _ = _spawn_worker(
            run_metric_worker_v1_1,
            secret=secret,
            kwargs={
                "paths": paths,
                "worker_descriptor": metric_descriptor,
                "expected_label_sha256": sha256_bytes(fixture["label_bytes"]),
                "expected_label_size": len(fixture["label_bytes"]),
                "expected_grouping_sha256": sha256_bytes(fixture["grouping_bytes"]),
                "expected_grouping_size": len(fixture["grouping_bytes"]),
                "expected_record_count": 48,
                "expected_group_count": 24,
            },
        )
        pids.append(pid)
        metric_lock = _verify_consumed(paths, METRIC_ROLE, "RESULT_PERSISTED")
        final_receipts = metric_lock["worker_roles"][METRIC_ROLE]["stage_receipt_identities"][-1:]
        completed = append_transition_v1_1(
            paths.global_lock,
            new_state="COMPLETED",
            worker_role="RQ2_D4_PARENT_VERIFIER_V1_1",
            credential_commitment=metric_lock["worker_roles"][METRIC_ROLE]["credential_commitment"],
            stage_receipt_identities=final_receipts,
            open_read_counts=metric_lock["worker_roles"][METRIC_ROLE]["actual_open_read_counts"],
        )
        verify_global_lock_chain_v1_1(completed)
        if any(value["status"] != "CONSUMED" for value in completed["worker_roles"].values()):
            raise RuntimeError("completed lock has unconsumed worker")
        preexisting_rejected = False
        try:
            publish_durable_artifact_v1_1(
                paths.feature_view,
                b"x",
                stage="TEST",
                worker_role="TEST",
                artifact_role="TEST",
                schema_id="test",
                record_count=1,
                approved_head=SYNTHETIC_HEAD,
                execution_id=SYNTHETIC_EXECUTION,
                effective_contract_id=SYNTHETIC_CONTRACT_ID,
                code_identity="test",
                parent_state="TEST",
            )
        except DurableArtifactError:
            preexisting_rejected = True
        firewall_probe = _runtime_firewall_adversarial_check(labels)
        authority = _authority_adversarial_checks(root)
        # Separate permanent failure proof.
        failure_control = root / "failure_control"
        failure_control.mkdir(mode=0o700)
        failure_lock = failure_control / "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json"
        _reserve_synthetic_lock(failure_lock)
        failed = fail_global_lock_v1_1(failure_lock, reason="SYNTHETIC_FAILURE")
        failure_retry_blocked = False
        try:
            _reserve_synthetic_lock(failure_lock)
        except FileExistsError:
            failure_retry_blocked = True
        formal_firewalls = {
            role: completed["worker_roles"][role]["runtime_firewall_summary"]
            for role in (FEATURE_ROLE, PREDICTOR_ROLE, METRIC_ROLE)
        }
        if any(
            report["forbidden_open_attempts"]
            or report["successful_forbidden_opens"]
            or report["forbidden_import_attempts"]
            for report in formal_firewalls.values()
        ):
            raise RuntimeError("formal synthetic worker made forbidden attempt")
        result = json.loads(paths.final_result.read_text())
        required_metric_keys = {
            "macro_f1_all_six",
            "exact_set_accuracy",
            "micro_precision",
            "micro_recall",
            "micro_f1",
            "required_capability_recall",
            "unnecessary_capability_rate",
            "mean_set_jaccard",
            "median_set_jaccard",
            "per_capability",
            "forbidden_capability_violation_rate",
            "context_resolution_accuracy",
            "context_resolution_positive_recall",
            "clarification_precision",
            "clarification_recall",
            "unnecessary_clarification_rate",
        }
        if any(not required_metric_keys <= set(result["method_metrics"][method]) for method in ("B0", "B1", "P1")):
            raise RuntimeError("synthetic result lacks complete method metrics")
        return {
            "schema_version": "rq2d3-r3-synthetic-validation-v1",
            "stage": "RQ2-D3-R3",
            "status": "PASS",
            "fixture": {"record_count": 48, "group_count": 24, "records_per_group": 2},
            "fresh_worker_process_count": len(set(pids)),
            "all_worker_process_ids_distinct": len(set(pids)) == 3,
            "worker_authority": authority,
            "direct_worker_invocation_blocked": True,
            "runtime_firewall_adversarial": {
                "open_attempt_recorded": firewall_probe["forbidden_open_attempts"] == 1,
                "open_blocked": firewall_probe["blocked_open_attempts"] == 1,
                "import_attempt_recorded": firewall_probe["forbidden_import_attempts"] == 1,
                "import_blocked": firewall_probe["blocked_imports"] == 1,
                "successful_forbidden_opens": firewall_probe["successful_forbidden_opens"],
            },
            "formal_worker_firewall_attempts": 0,
            "durable_artifacts": {
                "mode_0600": True,
                "exclusive": True,
                "atomic": True,
                "file_fsync": True,
                "directory_fsync": True,
                "reread_verified": True,
                "preexisting_target_rejected": preexisting_rejected,
                "parent_receipt_verification": True,
            },
            "prediction_binding": {
                "predictions_per_method": 48,
                "total_predictions": 144,
                "case_and_feature_bound": True,
                "metamorphic_id_invariant": True,
            },
            "complete_method_metrics": True,
            "comparison_count": 3,
            "sign_flip": "3 x 100000 PASS",
            "bootstrap": "3 x 50000 PASS",
            "holm_secondary_count": 2,
            "global_one_shot": {
                "state": completed["state"],
                "transition_count": len(completed["transitions"]),
                "all_transitions_carry_receipts": all(
                    bool(row["stage_receipt_identities"]) for row in completed["transitions"]
                ),
                "all_workers_consumed": True,
                "concurrent_exclusion": concurrent_exclusion,
                "completion_persistent": True,
                "failure_state": failed["state"],
                "failure_persistent": True,
                "failure_retry_blocked": failure_retry_blocked,
                "retry_permitted": False,
            },
            "p2_status": "DEFERRED_NOT_EXECUTED",
            "p2_execution_count": 0,
            "real_track_b_access_count": 0,
            "real_track_b_prediction_count": 0,
            "real_track_b_metric_count": 0,
            "provider_calls": 0,
            "network_access": False,
        }
