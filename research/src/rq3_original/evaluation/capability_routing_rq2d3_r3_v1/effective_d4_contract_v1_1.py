"""The sole effective future D4 real entry; never invoked by RQ2-D3-R3."""

from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Callable, Mapping

from . import (
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    EFFECTIVE_CONTRACT_ID,
    FULL_TEXT_GOLD_SHA256,
    FULL_TEXT_GOLD_SIZE,
    LABEL_ONLY_GOLD_SHA256,
    LABEL_ONLY_GOLD_SIZE,
    METRIC_IMPLEMENTATION_SHA256,
    ROOT,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .fixed_rq2d4_paths_v1_1 import D4PathsV1_1, resolve_fixed_rq2d4_paths_v1_1
from .global_lock_receipt_v1_1 import (
    append_transition_v1_1,
    fail_global_lock_v1_1,
    read_global_lock_v1_1,
    reserve_global_lock_v1_1,
    verify_global_lock_chain_v1_1,
)
from .track_b_feature_extractor_worker_v1_1 import run_feature_extractor_worker_v1_1
from .track_b_metric_worker_v1_1 import run_metric_worker_v1_1
from .track_b_predictor_worker_v1_1 import run_predictor_worker_v1_1
from .worker_execution_authority_v1_1 import (
    FEATURE_ROLE,
    METRIC_ROLE,
    PREDICTOR_ROLE,
    WorkerDescriptorV1_1,
    issue_worker_credential_v1_1,
)


REAL_LOCK_IDENTITY = "RQ2_TRACK_B_REPOSITORY_GLOBAL_LOCK_IDENTITY_V1_1"
R3_OUTPUT_CHECKSUM_RELATIVE = (
    "evaluation/capability_routing_rq2d3_r3_v1/"
    "rq2d3_r3_output_checksums_v1.sha256"
)
GOLD_METADATA_MANIFEST_RELATIVE = (
    "evaluation/capability_routing_rq2d2b_v1/"
    "track_b_capability_gold_manifest_v1.json"
)


class EffectiveD4AuthorityError(RuntimeError):
    pass


def effective_code_bundle_identity_v1_1() -> str:
    names = (
        "effective_d4_contract_v1_1.py",
        "worker_execution_authority_v1_1.py",
        "durable_local_artifact.py",
        "stage_receipt_v1_1.py",
        "global_lock_receipt_v1_1.py",
        "worker_runtime_firewall.py",
        "feature_fingerprint_v1_1.py",
        "bound_prediction_v1_1.py",
        "track_b_feature_extractor_worker_v1_1.py",
        "frozen_capability_predictor_core_v1_1.py",
        "track_b_predictor_worker_v1_1.py",
        "frozen_complete_metric_binding_v1_1.py",
        "fixed_statistical_execution_v1_1.py",
        "track_b_metric_worker_v1_1.py",
        "p2_secondary_scope_decision.py",
        "fixed_rq2d4_paths_v1_1.py",
        "rq2d4_state_machine_v1_1.py",
    )
    here = Path(__file__).resolve().parent
    payload = [
        {"relative_name": name, "sha256": sha256_file(here / name)} for name in names
    ]
    return sha256_bytes(canonical_json_bytes(payload))


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def _verify_r3_code_and_contract_checksums() -> int:
    manifest = ROOT / R3_OUTPUT_CHECKSUM_RELATIVE
    if not manifest.is_file() or manifest.is_symlink():
        raise EffectiveD4AuthorityError("future D4 R3 checksum manifest absent")
    observed: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as error:
            raise EffectiveD4AuthorityError("future D4 R3 checksum manifest malformed") from error
        candidate = Path(relative)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or relative in observed
            or not (ROOT / candidate).is_file()
            or (ROOT / candidate).is_symlink()
            or sha256_file(ROOT / candidate) != expected
        ):
            raise EffectiveD4AuthorityError("future D4 R3 checksum mismatch")
        observed.add(relative)
    if len(observed) != 53:
        raise EffectiveD4AuthorityError("future D4 R3 checksum count mismatch")
    return len(observed)


def _verify_gold_metadata_manifest() -> dict[str, Any]:
    path = ROOT / GOLD_METADATA_MANIFEST_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise EffectiveD4AuthorityError("future D4 Gold metadata absent")
    document = json.loads(path.read_text(encoding="utf-8"))
    combined = document.get("full_text_gold")
    labels = document.get("label_only_gold")
    if (
        document.get("status") != "TRACK_B_CAPABILITY_GOLD_FROZEN"
        or document.get("gold_bundle_sha256") != D2B_GOLD_BUNDLE_SHA256
        or document.get("record_count") != 48
        or document.get("eligible_for_final_evaluation") is not True
        or not isinstance(combined, Mapping)
        or combined.get("relative_path")
        != "evaluation/capability_routing_rq2d2b_v1/local_gold/track_b_contextual_capability_final_gold_v1.jsonl"
        or combined.get("sha256") != FULL_TEXT_GOLD_SHA256
        or combined.get("size_bytes") != FULL_TEXT_GOLD_SIZE
        or combined.get("record_count") != 48
        or not isinstance(labels, Mapping)
        or labels.get("relative_path")
        != "evaluation/capability_routing_rq2d2b_v1/track_b_contextual_capability_final_gold_labels_v1.jsonl"
        or labels.get("sha256") != LABEL_ONLY_GOLD_SHA256
        or labels.get("size_bytes") != LABEL_ONLY_GOLD_SIZE
        or labels.get("record_count") != 48
    ):
        raise EffectiveD4AuthorityError("future D4 Gold metadata mismatch")
    return {
        "manifest_sha256": sha256_file(path),
        "gold_bundle_sha256": D2B_GOLD_BUNDLE_SHA256,
        "record_count": 48,
    }


def _safe_prearm(approved_head: str) -> dict[str, Any]:
    if os.environ.get("RQ2D4_TRACK_B_FINAL_EVALUATION_AUTHORISED") != "YES":
        raise EffectiveD4AuthorityError("future D4 user authority absent")
    if (
        _git("rev-parse", "HEAD").stdout.decode().strip() != approved_head
        or _git("diff", "--quiet").returncode
        or _git("diff", "--cached", "--quiet").returncode
        or _git("status", "--porcelain=v1", "--untracked-files=all").stdout.strip()
        or _git("remote").stdout.strip()
        or _git("tag", "--list").stdout.strip()
    ):
        raise EffectiveD4AuthorityError("future D4 Git prearm mismatch")
    paths = resolve_fixed_rq2d4_paths_v1_1()
    for target in (paths.global_lock, paths.output_root, paths.control_root):
        try:
            os.lstat(target)
        except FileNotFoundError:
            continue
        raise EffectiveD4AuthorityError("future D4 fixed target already exists")
    r3_checksum_count = _verify_r3_code_and_contract_checksums()
    gold_metadata = _verify_gold_metadata_manifest()
    from .legacy_entrypoint_revocation import legacy_entrypoint_inventory_v1

    if legacy_entrypoint_inventory_v1().get("status") != "PASS":
        raise EffectiveD4AuthorityError("future D4 legacy-entry supersession mismatch")
    # This is deliberately performed in a fresh process so the parent later forks no loaded model.
    command = (
        "import json;"
        "from evaluation.capability_routing_rq2d3_r3_v1.prearm_runtime_smoke "
        "import run_prearm_runtime_smoke_v1_1;"
        "print(json.dumps(run_prearm_runtime_smoke_v1_1(),sort_keys=True))"
    )
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OPENAI_API_KEY": "",
        "CUDA_VISIBLE_DEVICES": "",
    }
    smoke_process = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", command],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if smoke_process.returncode:
        raise EffectiveD4AuthorityError("future D4 runtime smoke failed")
    smoke = json.loads(smoke_process.stdout.splitlines()[-1])
    if smoke.get("status") != "PASS" or smoke.get("pre_reservation_content_read_count") != 0:
        raise EffectiveD4AuthorityError("future D4 runtime smoke contract mismatch")
    preflight_contract = json.loads(
        (
            ROOT
            / "evaluation/capability_routing_rq2d3_r3_v1/"
            "rq2d3_r3_preflight_report_v1.json"
        ).read_text(encoding="utf-8")
    )
    if (
        sha256_file(ROOT / "evaluation/capability_routing_rq2d3_r1_v1/rq2_final_statistical_contract_v1_1.json")
        != D3_R1_STATISTICAL_SHA256
        or preflight_contract.get("frozen_identities", {}).get("d3_r2_grouping_ledger_sha256")
        != D3_R2_GROUPING_SHA256
        or sha256_file(ROOT / "evaluation/capability_routing_rq2b_v1/capability_metrics.py")
        != METRIC_IMPLEMENTATION_SHA256
    ):
        raise EffectiveD4AuthorityError("future D4 frozen identity mismatch")
    return {
        "paths": paths,
        "runtime_smoke": smoke,
        "code_identity": effective_code_bundle_identity_v1_1(),
        "r3_output_checksum_count": r3_checksum_count,
        "gold_metadata": gold_metadata,
    }


def _prepare_real_roots(paths: D4PathsV1_1) -> None:
    stage_root = paths.control_root.parent
    try:
        value = os.lstat(stage_root)
    except FileNotFoundError:
        os.mkdir(stage_root, 0o700)
    else:
        if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
            raise EffectiveD4AuthorityError("unsafe D4 stage root")
    os.mkdir(paths.control_root, 0o700)


def _prepare_output_after_reservation(paths: D4PathsV1_1) -> None:
    os.mkdir(paths.output_root, 0o700)
    os.mkdir(paths.receipts_root, 0o700)


def _spawn(
    target: Callable[..., None], *, secret: bytes, kwargs: Mapping[str, Any]
) -> None:
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
    process.join()
    if process.exitcode != 0:
        raise EffectiveD4AuthorityError("future D4 worker failed")


def _worker_bootstrap(
    target: Callable[..., None], inherited_write_fd: int, kwargs: Mapping[str, Any]
) -> None:
    os.close(inherited_write_fd)
    target(**dict(kwargs))


def _verify_worker(paths: D4PathsV1_1, role: str, state: str) -> dict[str, Any]:
    lock = read_global_lock_v1_1(paths.global_lock)
    verify_global_lock_chain_v1_1(lock)
    entry = lock["worker_roles"].get(role)
    if not entry or entry.get("status") != "CONSUMED" or lock.get("state") != state:
        raise EffectiveD4AuthorityError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    for identity in entry["stage_receipt_identities"]:
        receipt_path = paths.receipts_root / identity["relative_path"]
        value = receipt_path.read_bytes()
        if sha256_bytes(value) != identity["sha256"] or len(value) != identity["size_bytes"]:
            raise EffectiveD4AuthorityError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
        receipt = json.loads(value)
        for artifact in receipt["artifact_receipts"]:
            target = paths.output_root / artifact["relative_path"]
            observed = target.read_bytes()
            if (
                sha256_bytes(observed) != artifact["sha256"]
                or len(observed) != artifact["size_bytes"]
                or stat.S_IMODE(os.lstat(target).st_mode) != 0o600
            ):
                raise EffectiveD4AuthorityError("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return lock


def execute_real_rq2d4_one_shot_v1_1(*, approved_head: str) -> dict[str, Any]:
    """Execute the future real one-shot only after separate, explicit D4 authority."""

    raise EffectiveD4AuthorityError("SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY")

    prearm = _safe_prearm(approved_head)
    paths: D4PathsV1_1 = prearm["paths"]
    fixed_bundle = {
        "approved_head": approved_head,
        "d2b_gold_bundle_sha256": D2B_GOLD_BUNDLE_SHA256,
        "d2b_gold_metadata_manifest_sha256": prearm["gold_metadata"]["manifest_sha256"],
        "combined_source": {"sha256": FULL_TEXT_GOLD_SHA256, "size_bytes": FULL_TEXT_GOLD_SIZE, "record_count": 48},
        "label_gold": {"sha256": LABEL_ONLY_GOLD_SHA256, "size_bytes": LABEL_ONLY_GOLD_SIZE, "record_count": 48},
        "grouping": {"sha256": D3_R2_GROUPING_SHA256, "size_bytes": 4176, "record_count": 48, "group_count": 24},
        "statistical_contract_sha256": D3_R1_STATISTICAL_SHA256,
        "metric_binding_sha256": METRIC_IMPLEMENTATION_SHA256,
        "c0_index_sha256": "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
        "c0_embeddings_sha256": "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8",
        "method_identities": {
            "B0": "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION",
            "B1": "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE",
            "P1": "P1_D05_SIGNAL_UNION",
        },
        "p1_policy_sha256": "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942",
        "d3_r3_code_bundle_identity": prearm["code_identity"],
        "d3_r3_output_checksum_count": prearm["r3_output_checksum_count"],
    }
    _prepare_real_roots(paths)
    execution_id = hashlib.sha256(
        b"RQ2_D4_EXECUTION_ID_V1_1\x00" + approved_head.encode("ascii")
    ).hexdigest()
    reserve_global_lock_v1_1(
        paths.global_lock,
        approved_head=approved_head,
        execution_id=execution_id,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        lock_identity=REAL_LOCK_IDENTITY,
        fixed_identity_bundle=fixed_bundle,
        prearm_runtime_smoke_receipt={
            "sha256": prearm["runtime_smoke"]["prearm_runtime_smoke_receipt_sha256"],
            "status": "PASS",
        },
        synthetic=False,
    )
    try:
        append_transition_v1_1(
            paths.global_lock,
            new_state="INPUT_IDENTITIES_VERIFIED",
            worker_role="RQ2_D4_PARENT_VERIFIER_V1_1",
            credential_commitment=None,
            stage_receipt_identities=[{"artifact_role": "FIXED_INPUT_IDENTITY_BUNDLE", "sha256": sha256_bytes(canonical_json_bytes(fixed_bundle))}],
        )
        _prepare_output_after_reservation(paths)
        extractor = WorkerDescriptorV1_1(
            FEATURE_ROLE, 1, "EXTRACTOR_CREDENTIAL_COMMITTED", execution_id,
            approved_head, REAL_LOCK_IDENTITY, EFFECTIVE_CONTRACT_ID,
        )
        secret, _ = issue_worker_credential_v1_1(
            paths.global_lock, descriptor=extractor, commit_state="EXTRACTOR_CREDENTIAL_COMMITTED"
        )
        _spawn(
            run_feature_extractor_worker_v1_1,
            secret=secret,
            kwargs={
                "paths": paths,
                "worker_descriptor": extractor,
                "expected_combined_sha256": FULL_TEXT_GOLD_SHA256,
                "expected_combined_size": FULL_TEXT_GOLD_SIZE,
                "expected_record_count": 48,
            },
        )
        _verify_worker(paths, FEATURE_ROLE, "FEATURE_FIREWALL_VERIFIED")
        predictor = WorkerDescriptorV1_1(
            PREDICTOR_ROLE, 2, "PREDICTOR_CREDENTIAL_COMMITTED", execution_id,
            approved_head, REAL_LOCK_IDENTITY, EFFECTIVE_CONTRACT_ID,
        )
        secret, _ = issue_worker_credential_v1_1(
            paths.global_lock, descriptor=predictor, commit_state="PREDICTOR_CREDENTIAL_COMMITTED"
        )
        _spawn(
            run_predictor_worker_v1_1,
            secret=secret,
            kwargs={"paths": paths, "worker_descriptor": predictor, "expected_feature_count": 48},
        )
        _verify_worker(paths, PREDICTOR_ROLE, "SECONDARY_SCOPE_METADATA_PERSISTED")
        metric = WorkerDescriptorV1_1(
            METRIC_ROLE, 3, "METRIC_CREDENTIAL_COMMITTED", execution_id,
            approved_head, REAL_LOCK_IDENTITY, EFFECTIVE_CONTRACT_ID,
        )
        secret, _ = issue_worker_credential_v1_1(
            paths.global_lock, descriptor=metric, commit_state="METRIC_CREDENTIAL_COMMITTED"
        )
        _spawn(
            run_metric_worker_v1_1,
            secret=secret,
            kwargs={
                "paths": paths,
                "worker_descriptor": metric,
                "expected_label_sha256": LABEL_ONLY_GOLD_SHA256,
                "expected_label_size": LABEL_ONLY_GOLD_SIZE,
                "expected_grouping_sha256": D3_R2_GROUPING_SHA256,
                "expected_grouping_size": 4176,
                "expected_record_count": 48,
                "expected_group_count": 24,
            },
        )
        lock = _verify_worker(paths, METRIC_ROLE, "RESULT_PERSISTED")
        result_receipts = lock["worker_roles"][METRIC_ROLE]["stage_receipt_identities"][-1:]
        completed = append_transition_v1_1(
            paths.global_lock,
            new_state="COMPLETED",
            worker_role="RQ2_D4_PARENT_VERIFIER_V1_1",
            credential_commitment=lock["worker_roles"][METRIC_ROLE]["credential_commitment"],
            stage_receipt_identities=result_receipts,
            open_read_counts=lock["worker_roles"][METRIC_ROLE]["actual_open_read_counts"],
        )
        verify_global_lock_chain_v1_1(completed)
        if any(value["status"] != "CONSUMED" for value in completed["worker_roles"].values()):
            raise EffectiveD4AuthorityError("future D4 worker consumption incomplete")
        result = json.loads(paths.final_result.read_text())
        return {
            "status": "COMPLETED",
            "execution_id": execution_id,
            "result_sha256": sha256_file(paths.final_result),
            "result": result,
            "retry_permitted": False,
        }
    except BaseException as error:
        try:
            fail_global_lock_v1_1(paths.global_lock, reason=type(error).__name__)
        finally:
            raise


def effective_d4_contract_document_v1_1() -> dict[str, Any]:
    parameters = tuple(inspect.signature(execute_real_rq2d4_one_shot_v1_1).parameters)
    if parameters != ("approved_head",):
        raise RuntimeError("effective D4 signature drift")
    return {
        "schema_version": "track-b-effective-d4-contract-v1-1",
        "status": "FROZEN",
        "execution_contract_id": EFFECTIVE_CONTRACT_ID,
        "real_entry": "execute_real_rq2d4_one_shot_v1_1(*, approved_head: str)",
        "entry_parameters": list(parameters),
        "forbidden_parameters": [
            "input_path", "output_path", "lock_path", "worker_role", "credential",
            "gold_path", "grouping_path", "model_path", "method_list", "metric_list",
            "callback", "threshold", "comparison", "seed", "draw_count", "resample_count",
            "p2_switch",
        ],
        "d3_r2_real_entry_authorised": False,
        "worker_self_authority": False,
        "prearm_before_reservation": True,
        "credential_transport": "INHERITED_ANONYMOUS_PIPE_FD",
        "parent_trusts_exit_code_only": False,
        "parent_independent_receipt_verification": True,
        "all_paths_repository_fixed": True,
        "retry_permitted": False,
        "d4_execution_count": 0,
        "r3_output_checksums_verified_before_reservation": True,
        "d2b_gold_metadata_verified_before_reservation": True,
    }
