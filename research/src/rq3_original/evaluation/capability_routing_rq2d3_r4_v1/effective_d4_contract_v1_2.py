"""The sole effective real D4 v1.2 parent entry; never invoked in RQ2-D3-R4."""

from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import subprocess
from typing import Any, Callable, Mapping

from . import (
    C0_EMBEDDINGS_SHA256,
    C0_INDEX_SHA256,
    COMBINED_SHA256,
    COMBINED_SIZE,
    D2B_GOLD_BUNDLE_SHA256,
    D3_R1_STATISTICAL_SHA256,
    D3_R2_GROUPING_SHA256,
    EFFECTIVE_CONTRACT_ID,
    GROUP_COUNT,
    GROUPING_SIZE,
    LABEL_SHA256,
    LABEL_SIZE,
    METRIC_IMPLEMENTATION_SHA256,
    P1_POLICY,
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
    fail_execution_state_v1_2,
    initial_execution_state_document_v1_2,
    initialise_execution_state_v1_2,
    read_execution_state_v1_2,
    transition_execution_state_v1_2,
    verify_execution_state_document_v1_2,
)
from .completion_bundle_v1_2 import build_completion_bundle_v1_2
from .completion_evidence_v1_2 import (
    derive_completion_evidence_v1_2,
    require_completion_eligible_v1_2,
)
from .durable_directory_tree_v1_2 import create_durable_directory_tree_v1_2
from .durable_no_replace_artifact_v1_2 import (
    json_object_validator,
    publish_no_replace_artifact_v1_2,
)
from .fixed_real_d4_paths_v1_2 import (
    CONTROL_ROOT_RELATIVE,
    OUTPUT_ROOT_RELATIVE,
    PARENT_RECEIPT_RELATIVE,
    SENTINEL_RELATIVE,
    STATE_RELATIVE,
    resolve_fixed_real_d4_paths_v1_2,
)
from .fixed_real_worker_authority_v1_2 import (
    FEATURE_ROLE,
    METRIC_ROLE,
    PREDICTOR_ROLE,
    REAL_CODE_BUNDLE_FILES,
    fixed_real_code_bundle_identity_v1_2,
    issue_fixed_real_worker_credential_v1_2,
)
from .immutable_reservation_sentinel_v1_2 import (
    ALREADY_RESERVED,
    ReservationSentinelError,
    create_reservation_sentinel_v1_2,
    reservation_sentinel_document_v1_2,
)
from .parent_execution_receipt_v1_2 import (
    parent_execution_receipt_document_v1_2,
    parent_receipt_descriptor_commitment_v1_2,
    persist_parent_execution_receipt_v1_2,
)
from .strict_project_relative_path import read_regular_nofollow
from .strict_receipt_verifier_v1_2 import verify_strict_artifact_receipt_v1_2


class EffectiveD4V1_2Error(RQ2D3R4Error):
    pass


CODE_FILES = REAL_CODE_BUNDLE_FILES


def effective_code_bundle_identity_v1_2() -> str:
    return fixed_real_code_bundle_identity_v1_2()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def _safe_prearm_v1_2(approved_head: str) -> dict[str, Any]:
    if os.environ.get("RQ2D4_TRACK_B_FINAL_EVALUATION_AUTHORISED") != "YES":
        raise EffectiveD4V1_2Error("future D4 user authority absent")
    paths = resolve_fixed_real_d4_paths_v1_2()
    root = paths.repository_root
    if (
        _git(root, "rev-parse", "HEAD").stdout.decode().strip() != approved_head
        or _git(root, "diff", "--quiet").returncode
        or _git(root, "diff", "--cached", "--quiet").returncode
        or _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.strip()
        or _git(root, "remote").stdout.strip()
        or _git(root, "tag", "--list").stdout.strip()
    ):
        raise EffectiveD4V1_2Error("future D4 Git prearm mismatch")
    # Any existing sentinel consumes the global one-shot, even if malformed.
    try:
        os.lstat(paths.sentinel)
    except FileNotFoundError:
        pass
    else:
        raise EffectiveD4V1_2Error(ALREADY_RESERVED)
    for target in (paths.control_root, paths.state, paths.parent_receipt, paths.output_root):
        try:
            os.lstat(target)
        except FileNotFoundError:
            continue
        raise EffectiveD4V1_2Error("future D4 fixed target already exists")
    manifest_path = root / "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    combined = manifest.get("full_text_gold", {})
    labels = manifest.get("label_only_gold", {})
    if (
        manifest.get("gold_bundle_sha256") != D2B_GOLD_BUNDLE_SHA256
        or combined.get("sha256") != COMBINED_SHA256
        or combined.get("size_bytes") != COMBINED_SIZE
        or combined.get("record_count") != RECORD_COUNT
        or labels.get("sha256") != LABEL_SHA256
        or labels.get("size_bytes") != LABEL_SIZE
        or labels.get("record_count") != RECORD_COUNT
        or sha256_file(root / "evaluation/capability_routing_rq2d3_r1_v1/rq2_final_statistical_contract_v1_1.json")
        != D3_R1_STATISTICAL_SHA256
        or sha256_file(root / "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl")
        != D3_R2_GROUPING_SHA256
        or sha256_file(root / "evaluation/capability_routing_rq2b_v1/capability_metrics.py")
        != METRIC_IMPLEMENTATION_SHA256
    ):
        raise EffectiveD4V1_2Error("future D4 frozen identity mismatch")
    smoke = json.loads(
        (root / "evaluation/capability_routing_rq2d3_r3_v1/rq2d3_r3_prearm_runtime_smoke_v1.json").read_text()
    )
    parity = json.loads(
        (root / "evaluation/capability_routing_rq2d3_r3_v1/rq2d3_r3_development_reexecution_parity_v1.json").read_text()
    )
    if (
        smoke.get("status") != "PASS"
        or smoke.get("pre_reservation_content_read_count") != 0
        or parity.get("status") != "PASS"
        or parity.get("dataset_method_run_count") != 9
        or any(row.get("status") != "PASS" for row in parity.get("datasets", []))
    ):
        raise EffectiveD4V1_2Error("future D4 prearm smoke/parity mismatch")
    return {
        "paths": paths,
        "gold_manifest_sha256": sha256_file(manifest_path),
        "prearm_smoke": smoke,
        "parity": parity,
        "code_bundle_identity": effective_code_bundle_identity_v1_2(),
    }


def _fixed_identity_bundle(prearm: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "d2b_gold_bundle_sha256": D2B_GOLD_BUNDLE_SHA256,
        "d3_r1_statistical_contract_sha256": D3_R1_STATISTICAL_SHA256,
        "d3_r2_grouping_sha256": D3_R2_GROUPING_SHA256,
        "metric_implementation_sha256": METRIC_IMPLEMENTATION_SHA256,
        "c0_index_sha256": C0_INDEX_SHA256,
        "c0_embeddings_sha256": C0_EMBEDDINGS_SHA256,
        "b0_identity": "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION",
        "b1_identity": "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE",
        "p1_identity": P1_POLICY,
        "p1_policy_sha256": P1_POLICY_SHA256,
        "d3_r4_code_bundle_identity": prearm["code_bundle_identity"],
        "prearm_smoke_receipt_sha256": prearm["prearm_smoke"]["prearm_runtime_smoke_receipt_sha256"],
        "development_parity_status": "9/9 PASS",
        "p2_status": "DEFERRED_NOT_EXECUTED_IN_RQ2_D4",
    }


def _input_identity_bundle() -> dict[str, Any]:
    return {
        "combined_source": {"sha256": COMBINED_SHA256, "size_bytes": COMBINED_SIZE, "record_count": RECORD_COUNT},
        "label_gold": {"sha256": LABEL_SHA256, "size_bytes": LABEL_SIZE, "record_count": RECORD_COUNT},
        "grouping": {"sha256": D3_R2_GROUPING_SHA256, "size_bytes": GROUPING_SIZE, "record_count": RECORD_COUNT, "group_count": GROUP_COUNT, "group_size": 2},
    }


def _spawn_real_worker(target: Callable[..., None], secret: bytes) -> None:
    context = multiprocessing.get_context("fork")
    read_fd, write_fd = os.pipe()
    process = context.Process(target=_worker_bootstrap, args=(target, write_fd, read_fd))
    process.start()
    os.close(read_fd)
    os.write(write_fd, secret)
    os.close(write_fd)
    process.join()
    if process.exitcode != 0:
        raise EffectiveD4V1_2Error("future D4 worker failed")


def _worker_bootstrap(
    target: Callable[..., None], inherited_write_fd: int, credential_fd: int
) -> None:
    os.close(inherited_write_fd)
    target(credential_fd=credential_fd)


def _artifact_by_role(state: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    matches = [row for row in state.get("stage_receipts", []) if row.get("artifact_role") == role]
    if len(matches) != 1:
        raise EffectiveD4V1_2Error("BLOCKED_RQ2_D4_DURABLE_RECEIPT_MISMATCH")
    return matches[0]


def _jsonl_schema_validator(expected_count: int):
    def validate(value: bytes) -> None:
        if not value.endswith(b"\n"):
            raise ValueError("JSONL newline absent")
        rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
        if len(rows) != expected_count or not all(isinstance(row, dict) for row in rows):
            raise ValueError("JSONL schema/count mismatch")

    return validate


def _verify_completion_artifacts_v1_2(
    state: Mapping[str, Any], paths: Any
) -> dict[str, Any]:
    feature_code = sha256_file(Path(__file__).parent / "real_feature_worker_v1_2.py")
    predictor_code = sha256_file(Path(__file__).parent / "real_predictor_worker_v1_2.py")
    metric_code = sha256_file(Path(__file__).parent / "real_metric_worker_v1_2.py")
    specifications = {
        "FEATURE_ONLY_VIEW": (paths.feature_view, FEATURE_ROLE, feature_code, "FEATURE_VIEW_PERSISTED", "COMBINED_CASE_SOURCE_OPENED", "track-b-feature-only-view-jsonl-v1-2", _jsonl_schema_validator(RECORD_COUNT)),
        "FEATURE_EXTRACTOR_PROCESS_REPORT": (paths.extractor_report, FEATURE_ROLE, feature_code, "FEATURE_FIREWALL_VERIFIED", "FEATURE_VIEW_PERSISTED", "track-b-feature-extractor-report-v1-2", json_object_validator("track-b-feature-extractor-report-v1-2")),
        "B0_BOUND_PREDICTIONS": (paths.b0_predictions, PREDICTOR_ROLE, predictor_code, "B0_PREDICTIONS_PERSISTED", "FEATURE_FIREWALL_VERIFIED", "track-b-bound-prediction-jsonl-v1-2", _jsonl_schema_validator(RECORD_COUNT)),
        "B1_BOUND_PREDICTIONS": (paths.b1_predictions, PREDICTOR_ROLE, predictor_code, "B1_PREDICTIONS_PERSISTED", "B0_PREDICTIONS_PERSISTED", "track-b-bound-prediction-jsonl-v1-2", _jsonl_schema_validator(RECORD_COUNT)),
        "P1_BOUND_PREDICTIONS": (paths.p1_predictions, PREDICTOR_ROLE, predictor_code, "P1_PREDICTIONS_PERSISTED", "B1_PREDICTIONS_PERSISTED", "track-b-bound-prediction-jsonl-v1-2", _jsonl_schema_validator(RECORD_COUNT)),
        "PREDICTION_FIREWALL_REPORT": (paths.prediction_firewall_report, PREDICTOR_ROLE, predictor_code, "PREDICTION_FIREWALL_VERIFIED", "P1_PREDICTIONS_PERSISTED", "track-b-prediction-firewall-report-v1-2", json_object_validator("track-b-prediction-firewall-report-v1-2")),
        "PREDICTOR_PROCESS_REPORT": (paths.predictor_report, PREDICTOR_ROLE, predictor_code, "PREDICTION_FIREWALL_VERIFIED", "P1_PREDICTIONS_PERSISTED", "track-b-predictor-process-report-v1-2", json_object_validator("track-b-predictor-process-report-v1-2")),
        "P2_SECONDARY_SCOPE_METADATA": (paths.p2_scope_metadata, PREDICTOR_ROLE, predictor_code, "SECONDARY_SCOPE_METADATA_PERSISTED", "PREDICTION_FIREWALL_VERIFIED", "track-b-p2-secondary-scope-decision-v1", json_object_validator("track-b-p2-secondary-scope-decision-v1")),
        "PER_CASE_METRIC_LEDGER": (paths.per_case_metric_ledger, METRIC_ROLE, metric_code, "METHOD_METRICS_PERSISTED", "GROUPING_OPENED", "track-b-per-case-metric-ledger-jsonl-v1-2", _jsonl_schema_validator(RECORD_COUNT * 3)),
        "METHOD_LEVEL_METRICS": (paths.method_metrics, METRIC_ROLE, metric_code, "METHOD_METRICS_PERSISTED", "GROUPING_OPENED", "track-b-method-level-metrics-v1-2", json_object_validator("track-b-method-level-metrics-v1-2")),
        "FIXED_STATISTICAL_STATE": (paths.statistical_state, METRIC_ROLE, metric_code, "PRIMARY_STATISTICS_PERSISTED", "METHOD_METRICS_PERSISTED", "track-b-fixed-statistical-state-v1-2", json_object_validator("track-b-fixed-statistical-state-v1-2")),
        "FINAL_RESULT": (paths.final_result, METRIC_ROLE, metric_code, "RESULT_PERSISTED", "PRIMARY_STATISTICS_PERSISTED", "track-b-final-evaluation-result-v1-2", json_object_validator("track-b-final-evaluation-result-v1-2")),
        "FINAL_RESULT_MANIFEST": (paths.result_manifest, METRIC_ROLE, metric_code, "RESULT_PERSISTED", "PRIMARY_STATISTICS_PERSISTED", "track-b-final-result-manifest-v1-2", json_object_validator("track-b-final-result-manifest-v1-2")),
        "METRIC_PROCESS_REPORT": (paths.metric_report, METRIC_ROLE, metric_code, "RESULT_PERSISTED", "PRIMARY_STATISTICS_PERSISTED", "track-b-metric-process-report-v1-2", json_object_validator("track-b-metric-process-report-v1-2")),
    }
    failures: list[dict[str, str]] = []
    verified_roles: list[str] = []
    state_chain_valid = False
    try:
        verify_execution_state_document_v1_2(state)
    except BaseException as error:
        failures.append(
            {
                "category": "state_chain_failure",
                "detail": type(error).__name__,
            }
        )
    else:
        state_chain_valid = True
    input_specifications = {
        "COMBINED_CASE_SOURCE_OBSERVED": {
            "sha256": COMBINED_SHA256,
            "size_bytes": COMBINED_SIZE,
            "record_count": RECORD_COUNT,
            "open_count": 1,
            "read_count": 1,
        },
        "LABEL_GOLD_OBSERVED": {
            "sha256": LABEL_SHA256,
            "size_bytes": LABEL_SIZE,
            "record_count": RECORD_COUNT,
            "open_count": 1,
            "read_count": 1,
        },
        "GROUPING_LEDGER_OBSERVED": {
            "sha256": D3_R2_GROUPING_SHA256,
            "size_bytes": GROUPING_SIZE,
            "record_count": RECORD_COUNT,
            "group_count": GROUP_COUNT,
            "group_size": 2,
            "open_count": 1,
            "read_count": 1,
        },
    }
    for artifact_role, expected in input_specifications.items():
        try:
            receipt = _artifact_by_role(state, artifact_role)
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise ValueError("input observation receipt mismatch")
        except BaseException as error:
            failures.append(
                {
                    "category": "input_open_read_count_mismatch",
                    "detail": f"{artifact_role}:{type(error).__name__}",
                }
            )
        else:
            verified_roles.append(artifact_role)
    for artifact_role, specification in specifications.items():
        target, worker_role, code_identity, stage, parent_state, schema_id, validator = specification
        try:
            receipt = _artifact_by_role(state, artifact_role)
            if receipt.get("relative_path") != str(target.relative_to(paths.repository_root)):
                raise ValueError("fixed artifact path mismatch")
            verify_strict_artifact_receipt_v1_2(
                paths.repository_root,
                receipt,
                expected_bindings={
                    "approved_head": state["approved_head"],
                    "execution_id": state["execution_id"],
                    "effective_contract_id": EFFECTIVE_CONTRACT_ID,
                    "worker_role": worker_role,
                    "worker_credential_commitment": state["worker_roles"][worker_role]["credential_commitment"],
                    "code_identity": code_identity,
                    "parent_state": parent_state,
                    "stage": stage,
                    "schema_id": schema_id,
                    "relative_path": str(target.relative_to(paths.repository_root)),
                    "artifact_role": artifact_role,
                    "open_read_counts": state["worker_roles"][worker_role]["open_read_counts"],
                    "firewall_summary": state["worker_roles"][worker_role]["firewall_summary"],
                },
                schema_validator=validator,
            )
        except BaseException as error:
            failures.append(
                {
                    "category": "artifact_receipt_verification_failure",
                    "detail": f"{artifact_role}:{type(error).__name__}",
                }
            )
        else:
            verified_roles.append(artifact_role)
    feature_prediction_binding_valid = False
    method_metric_complete = False
    statistical_complete = False
    try:
        from evaluation.capability_routing_rq2d3_r3_v1.bound_prediction_v1_1 import validate_prediction_set_v1_1
        from evaluation.capability_routing_rq2d3_r3_v1.feature_fingerprint_v1_1 import validate_feature_row_v1_1

        feature_rows = [
            json.loads(line)
            for line in read_regular_nofollow(
                paths.repository_root,
                str(paths.feature_view.relative_to(paths.repository_root)),
                expected_mode=0o600,
            ).decode("utf-8").splitlines()
        ]
        for row in feature_rows:
            validate_feature_row_v1_1(row)
        prediction_rows = []
        for target in (paths.b0_predictions, paths.b1_predictions, paths.p1_predictions):
            prediction_rows.extend(
                json.loads(line)
                for line in read_regular_nofollow(
                    paths.repository_root,
                    str(target.relative_to(paths.repository_root)),
                    expected_mode=0o600,
                ).decode("utf-8").splitlines()
            )
        validate_prediction_set_v1_1(prediction_rows, feature_rows)
        feature_prediction_binding_valid = True
    except BaseException as error:
        failures.append(
            {
                "category": "feature_prediction_binding_failure",
                "detail": type(error).__name__,
            }
        )
    try:
        method_document = json.loads(
            read_regular_nofollow(
                paths.repository_root,
                str(paths.method_metrics.relative_to(paths.repository_root)),
                expected_mode=0o600,
            )
        )
        metric_keys = {
            "macro_f1_all_six",
            "exact_set_accuracy",
            "required_capability_recall",
            "unnecessary_capability_rate",
        }
        method_metrics = method_document.get("method_metrics", {})
        method_metric_complete = set(method_metrics) == {"B0", "B1", "P1"} and all(
            metric_keys <= set(value) for value in method_metrics.values()
        )
        if not method_metric_complete:
            raise ValueError("method metric completeness")
    except BaseException as error:
        failures.append(
            {
                "category": "method_metric_completeness_failure",
                "detail": type(error).__name__,
            }
        )
    try:
        statistical_document = json.loads(
            read_regular_nofollow(
                paths.repository_root,
                str(paths.statistical_state.relative_to(paths.repository_root)),
                expected_mode=0o600,
            )
        )
        statistics = statistical_document.get("statistics", {})
        statistical_complete = (
            set(statistics.get("comparisons", {}))
            == {"P1_VS_B1", "B1_VS_B0", "P1_VS_B0"}
            and statistics.get("primary") is not None
            and statistics.get("secondary_holm") is not None
        )
        if not statistical_complete:
            raise ValueError("statistical completeness")
    except BaseException as error:
        failures.append(
            {
                "category": "statistical_completeness_failure",
                "detail": type(error).__name__,
            }
        )
    return {
        "verified_artifact_roles": verified_roles,
        "artifact_verification_failures": failures,
        "artifacts_bound": len(verified_roles)
        == len(specifications) + len(input_specifications),
        "state_chain_valid": state_chain_valid,
        "feature_prediction_binding_valid": feature_prediction_binding_valid,
        "method_metric_complete": method_metric_complete,
        "statistical_complete": statistical_complete,
    }


def execute_real_rq2d4_one_shot_v1_2(*, approved_head: str) -> dict[str, Any]:
    """Execute only after a future, separate D4 authority explicitly enables it."""

    prearm = _safe_prearm_v1_2(approved_head)
    paths = prearm["paths"]
    create_durable_directory_tree_v1_2(
        paths.repository_root, "evaluation/capability_routing_rq2d4_v1/local_control"
    )
    parent_nonce = secrets.token_bytes(32)
    parent_nonce_commitment = hashlib.sha256(
        b"RQ2_D4_PARENT_NONCE_V1_2\x00" + parent_nonce
    ).hexdigest()
    execution_id = hashlib.sha256(
        b"RQ2_D4_EXECUTION_ID_V1_2\x00"
        + approved_head.encode("ascii")
        + b"\x00"
        + parent_nonce_commitment.encode("ascii")
    ).hexdigest()
    fixed_paths = {
        "output_root_relative": OUTPUT_ROOT_RELATIVE,
        "control_root_relative": CONTROL_ROOT_RELATIVE,
        "sentinel_relative": SENTINEL_RELATIVE,
        "state_relative": STATE_RELATIVE,
        "parent_receipt_relative": PARENT_RECEIPT_RELATIVE,
    }
    descriptor_commitment = parent_receipt_descriptor_commitment_v1_2(
        relative_path=PARENT_RECEIPT_RELATIVE,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        approved_head=approved_head,
    )
    sentinel_document = reservation_sentinel_document_v1_2(
        execution_id=execution_id,
        approved_head=approved_head,
        fixed_paths=fixed_paths,
        frozen_identity_bundle=_fixed_identity_bundle(prearm),
        input_identity_bundle=_input_identity_bundle(),
        d3_r4_code_bundle_identity=prearm["code_bundle_identity"],
        parent_execution_nonce_commitment=parent_nonce_commitment,
        parent_receipt_descriptor_commitment=descriptor_commitment,
        reservation_created_at=utc_timestamp(),
        synthetic=False,
    )
    sentinel_identity = create_reservation_sentinel_v1_2(
        paths.sentinel, sentinel_document
    )
    state_document = initial_execution_state_document_v1_2(
        execution_id=execution_id,
        approved_head=approved_head,
        effective_contract_id=EFFECTIVE_CONTRACT_ID,
        sentinel_sha256=sentinel_identity["sha256"],
        synthetic=False,
    )
    initialise_execution_state_v1_2(
        paths.state,
        paths.sentinel,
        state_document,
        state_relative_path=STATE_RELATIVE,
    )
    try:
        identity_receipt = {
            "artifact_role": "FIXED_INPUT_IDENTITY_BUNDLE",
            "sha256": sha256_bytes(canonical_json_bytes(_input_identity_bundle())),
            "record_count": RECORD_COUNT,
        }
        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "INPUT_IDENTITIES_VERIFIED",
            stage_receipts=[identity_receipt],
            evidence_summary={"fixed_input_identities_verified": True},
        )
        parent_document = parent_execution_receipt_document_v1_2(
            execution_id=execution_id,
            approved_head=approved_head,
            effective_contract_id=EFFECTIVE_CONTRACT_ID,
            sentinel_identity=sentinel_identity,
            sentinel_relative=SENTINEL_RELATIVE,
            state_relative=STATE_RELATIVE,
            parent_receipt_relative=PARENT_RECEIPT_RELATIVE,
            parent_nonce_commitment=parent_nonce_commitment,
            parent_code_identity=sha256_file(Path(__file__)),
            fixed_real_paths=fixed_paths,
            input_identity_commitments=_input_identity_bundle(),
            created_at=utc_timestamp(),
            synthetic=False,
        )
        parent_receipt = persist_parent_execution_receipt_v1_2(
            paths.parent_receipt,
            parent_document,
            relative_path=PARENT_RECEIPT_RELATIVE,
            sentinel_sha256=sentinel_identity["sha256"],
        )

        def bind_parent(document: dict[str, Any]) -> None:
            document["parent_receipt_sha256"] = parent_receipt["sha256"]

        transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "PARENT_EXECUTION_RECEIPT_PERSISTED",
            stage_receipts=[parent_receipt],
            evidence_summary={"parent_receipt_verified": True},
            mutation=bind_parent,
        )
        create_durable_directory_tree_v1_2(
            paths.repository_root, "evaluation/capability_routing_rq2d4_v1/local_one_shot/stage_receipts"
        )
        from .real_feature_worker_v1_2 import run_real_feature_extractor_worker_v1_2
        from .real_metric_worker_v1_2 import run_real_metric_worker_v1_2
        from .real_predictor_worker_v1_2 import run_real_predictor_worker_v1_2

        for role, worker in (
            (FEATURE_ROLE, run_real_feature_extractor_worker_v1_2),
            (PREDICTOR_ROLE, run_real_predictor_worker_v1_2),
            (METRIC_ROLE, run_real_metric_worker_v1_2),
        ):
            secret, _ = issue_fixed_real_worker_credential_v1_2(role)
            try:
                _spawn_real_worker(worker, secret)
            finally:
                secret = b"\x00" * len(secret)
        state, _ = read_execution_state_v1_2(paths.state)
        verification = _verify_completion_artifacts_v1_2(state, paths)
        if verification["artifact_verification_failures"]:
            def record_verification_failures(document: dict[str, Any]) -> None:
                document["hard_failure_evidence"].extend(
                    verification["artifact_verification_failures"]
                )

            atomic_mutate_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                record_verification_failures,
            )
            state, _ = read_execution_state_v1_2(paths.state)
        required_receipt_roles = (
            "FEATURE_ONLY_VIEW",
            "FEATURE_EXTRACTOR_PROCESS_REPORT",
            "B0_BOUND_PREDICTIONS",
            "B1_BOUND_PREDICTIONS",
            "P1_BOUND_PREDICTIONS",
            "PREDICTION_FIREWALL_REPORT",
            "PREDICTOR_PROCESS_REPORT",
            "P2_SECONDARY_SCOPE_METADATA",
            "LABEL_GOLD_OBSERVED",
            "GROUPING_LEDGER_OBSERVED",
            "PER_CASE_METRIC_LEDGER",
            "METHOD_LEVEL_METRICS",
            "FIXED_STATISTICAL_STATE",
            "FINAL_RESULT",
            "FINAL_RESULT_MANIFEST",
            "METRIC_PROCESS_REPORT",
        )
        expected_counts = {
            f"{FEATURE_ROLE}:combined_source_open_count": 1,
            f"{FEATURE_ROLE}:combined_source_read_count": 1,
            f"{PREDICTOR_ROLE}:feature_view_open_count": 1,
            f"{PREDICTOR_ROLE}:feature_view_read_count": 1,
            f"{PREDICTOR_ROLE}:combined_source_open_count": 0,
            f"{PREDICTOR_ROLE}:label_gold_open_count": 0,
            f"{PREDICTOR_ROLE}:grouping_open_count": 0,
            f"{METRIC_ROLE}:label_gold_open_count": 1,
            f"{METRIC_ROLE}:label_gold_read_count": 1,
            f"{METRIC_ROLE}:grouping_open_count": 1,
            f"{METRIC_ROLE}:grouping_read_count": 1,
            f"{METRIC_ROLE}:combined_source_open_count": 0,
        }
        evidence = derive_completion_evidence_v1_2(
            state,
            required_stage_receipt_roles=required_receipt_roles,
            expected_open_read_counts=expected_counts,
            artifacts_bound=bool(verification["artifacts_bound"]),
            state_chain_valid=bool(verification["state_chain_valid"]),
            feature_prediction_binding_valid=bool(
                verification["feature_prediction_binding_valid"]
            ),
            method_metric_complete=bool(verification["method_metric_complete"]),
            statistical_complete=bool(verification["statistical_complete"]),
        )
        require_completion_eligible_v1_2(evidence)
        bundle = build_completion_bundle_v1_2(
            immutable_sentinel_identity=sentinel_identity,
            parent_execution_receipt_identity=parent_receipt,
            state_chain_commitment=state["state_file_chain_commitment"],
            combined_source_observed_identity=_artifact_by_role(state, "COMBINED_CASE_SOURCE_OBSERVED"),
            feature_view_identity=_artifact_by_role(state, "FEATURE_ONLY_VIEW"),
            extractor_report_identity=_artifact_by_role(state, "FEATURE_EXTRACTOR_PROCESS_REPORT"),
            b0_prediction_identity=_artifact_by_role(state, "B0_BOUND_PREDICTIONS"),
            b1_prediction_identity=_artifact_by_role(state, "B1_BOUND_PREDICTIONS"),
            p1_prediction_identity=_artifact_by_role(state, "P1_BOUND_PREDICTIONS"),
            predictor_report_identity=_artifact_by_role(state, "PREDICTOR_PROCESS_REPORT"),
            runtime_firewall_report_identities=[
                _artifact_by_role(state, "FEATURE_EXTRACTOR_PROCESS_REPORT"),
                _artifact_by_role(state, "PREDICTION_FIREWALL_REPORT"),
                _artifact_by_role(state, "METRIC_PROCESS_REPORT"),
            ],
            p2_deferred_scope_metadata_identity=_artifact_by_role(state, "P2_SECONDARY_SCOPE_METADATA"),
            label_gold_observed_identity=_artifact_by_role(state, "LABEL_GOLD_OBSERVED"),
            grouping_observed_identity=_artifact_by_role(state, "GROUPING_LEDGER_OBSERVED"),
            complete_method_metrics_identity=_artifact_by_role(state, "METHOD_LEVEL_METRICS"),
            pairwise_statistics_identity=_artifact_by_role(state, "FIXED_STATISTICAL_STATE"),
            metric_report_identity=_artifact_by_role(state, "METRIC_PROCESS_REPORT"),
            per_case_metric_ledger_identity=_artifact_by_role(state, "PER_CASE_METRIC_LEDGER"),
            final_result_identity=_artifact_by_role(state, "FINAL_RESULT"),
            result_manifest_identity=_artifact_by_role(state, "FINAL_RESULT_MANIFEST"),
            all_stage_receipts=state["stage_receipts"],
            worker_credential_commitments={
                role: item["credential_commitment"] for role, item in state["worker_roles"].items()
            },
            worker_role_terminal_states={
                role: item["status"] for role, item in state["worker_roles"].items()
            },
            evidence_derived_hard_failure_count=evidence["hard_failure_count"],
        )
        completion_receipt = publish_no_replace_artifact_v1_2(
            paths.completion_bundle,
            canonical_json_bytes(bundle),
            relative_path=str(paths.completion_bundle.relative_to(paths.repository_root)),
            stage="COMPLETED",
            worker_role="RQ2_D4_PARENT_V1_2",
            worker_credential_commitment=None,
            artifact_role="COMPLETION_BUNDLE",
            schema_id="track-b-completion-bundle-v1-2",
            record_count=1,
            approved_head=approved_head,
            execution_id=execution_id,
            effective_contract_id=EFFECTIVE_CONTRACT_ID,
            code_identity=sha256_file(Path(__file__)),
            parent_state="RESULT_PERSISTED",
            open_read_counts=state["open_read_counters"],
            firewall_summary={"hard_failure_count": evidence["hard_failure_count"]},
            schema_validator=json_object_validator("track-b-completion-bundle-v1-2"),
        )
        completed = transition_execution_state_v1_2(
            paths.state,
            paths.sentinel,
            "COMPLETED",
            stage_receipts=[completion_receipt],
            evidence_summary={"completion_evidence": evidence},
        )
        return {
            "status": completed["current_state"],
            "execution_id": execution_id,
            "completion_bundle_sha256": completion_receipt["sha256"],
            "hard_failure_count": evidence["hard_failure_count"],
            "retry_permitted": False,
        }
    except BaseException as error:
        try:
            fail_execution_state_v1_2(
                paths.state,
                paths.sentinel,
                failure_code=type(error).__name__,
                failure_stage="D4_PARENT",
                failure_receipt={"artifact_role": "ROOT_FAILURE_RECEIPT"},
            )
        except BaseException:
            pass
        finally:
            raise


def effective_d4_contract_document_v1_2() -> dict[str, Any]:
    parameters = tuple(inspect.signature(execute_real_rq2d4_one_shot_v1_2).parameters)
    if parameters != ("approved_head",):
        raise RuntimeError("effective D4 v1.2 signature drift")
    return {
        "schema_version": "track-b-effective-d4-contract-v1-2",
        "status": "FROZEN",
        "execution_contract_id": EFFECTIVE_CONTRACT_ID,
        "real_parent_entry": "execute_real_rq2d4_one_shot_v1_2(*, approved_head: str)",
        "entry_parameters": list(parameters),
        "forbidden_parameters": [
            "path", "lock", "state_file", "worker_role", "credential", "input_identity",
            "expected_sha", "size", "count", "synthetic_flag", "gold_path", "grouping_path",
            "model_path", "method_list", "metric_list", "callback", "threshold", "comparison",
            "seed", "draw_count", "resample_count", "p2_switch",
        ],
        "v1_real_authorised": False,
        "v1_1_real_authorised": False,
        "v1_2_real_authorised_only_after_separate_d4_authority": True,
        "fixed_repository_paths": True,
        "immutable_reservation_sentinel": True,
        "atomic_mutable_state_receipt": True,
        "immutable_parent_execution_receipt": True,
        "workers_use_inherited_anonymous_pipe": True,
        "final_artifacts_atomic_no_replace": True,
        "completion_evidence_derived": True,
        "retry_permitted": False,
        "d4_execution_count_in_r4": 0,
    }
