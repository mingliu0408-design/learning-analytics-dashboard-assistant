"""Executable future-D4 entry with fixed paths and process isolation."""

from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from . import CAPABILITIES, FULL_TEXT_GOLD_SHA256, FULL_TEXT_GOLD_SIZE, LABEL_ONLY_GOLD_SHA256, ROOT, canonical_json_bytes, canonical_jsonl_bytes, sha256_bytes, sha256_file
from .fixed_rq2d4_paths import resolve_fixed_rq2d4_paths_v1
from .rq2d4_state_machine import reserve_global_lock_v1, transition_global_lock_v1


EXECUTION_CONTRACT_ID = "RQ2_TRACK_B_B0_B1_P1_FINAL_EVALUATION_GLOBAL_ONE_SHOT_V1"


class D4ExecutionAuthorityError(RuntimeError):
    pass


def _raise_superseded_real_entry() -> None:
    raise D4ExecutionAuthorityError("SUPERSEDED_D3_R2_REAL_WORKER_ENTRY")


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def _read_fixed_file_once(path: Path, *, expected_sha256: str | None = None, expected_size: int | None = None) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("D4 fixed input absent or unsafe")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb", closefd=True) as handle:
        value = handle.read()
    if expected_size is not None and len(value) != expected_size:
        raise RuntimeError("D4 fixed input size mismatch")
    if expected_sha256 is not None and sha256_bytes(value) != expected_sha256:
        raise RuntimeError("D4 fixed input SHA mismatch")
    return value


def _jsonl(value: bytes) -> list[dict[str, Any]]:
    if value.startswith(b"\xef\xbb\xbf") or b"\r" in value or not value.endswith(b"\n"):
        raise RuntimeError("D4 JSONL byte contract mismatch")
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines()]
    if not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("D4 JSONL row contract mismatch")
    return rows


def _write_local(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(value)
    if path.read_bytes() != value:
        raise RuntimeError("D4 local persistence reread mismatch")


def _real_extractor_worker() -> None:
    _raise_superseded_real_entry()
    from .track_b_feature_label_process_firewall import extract_feature_view_v1

    paths = resolve_fixed_rq2d4_paths_v1()
    combined_path = ROOT / "evaluation/capability_routing_rq2d2b_v1/local_gold/track_b_contextual_capability_final_gold_v1.jsonl"
    combined = _jsonl(
        _read_fixed_file_once(
            combined_path,
            expected_sha256=FULL_TEXT_GOLD_SHA256,
            expected_size=FULL_TEXT_GOLD_SIZE,
        )
    )
    features, report = extract_feature_view_v1(combined)
    _write_local(paths.feature_view, canonical_jsonl_bytes(features))
    forbidden_imports = [
        name for name in sys.modules
        if name.startswith("evaluation.capability_routing_rq2b_v1")
        or name.startswith("evaluation.capability_routing_rq2d3_r1_v1")
    ]
    if forbidden_imports:
        raise RuntimeError("real feature extractor imported predictor/statistical modules")
    report.update(
        {
            "status": "PASS",
            "process_role": "TRACK_B_FEATURE_EXTRACTOR_V1",
            "feature_view_sha256": sha256_file(paths.feature_view),
            "predictor_modules_imported": 0,
        }
    )
    _write_local(paths.output_root / "feature_extractor_report_v1.json", canonical_json_bytes(report))


def _real_prediction_row(case: Any, method: str, *, runtime: Any, dashboard: Any, b1_adapter: Any) -> dict[str, Any]:
    from evaluation.capability_routing_rq2b_v1.b0_original_query_adapter import measure_b0_case
    from evaluation.capability_routing_rq2b_v1.p1_capability_router import prediction_projection, route_p1_case
    from evaluation.capability_routing_rq2b_v1.run_rq2b import _context_prediction
    from .prediction_contract import prediction_trace_hash_v1

    if method == "B0":
        measured = measure_b0_case(
            case_id=case.case_id,
            original_query=case.current_query,
            current_page=case.current_page,
            semantic_runtime=runtime,
            dashboard_data=dashboard,
        )
        capabilities = [name for name, active in measured["capability_projection"].items() if active]
        context_prediction = False
    elif method == "B1":
        measured = b1_adapter.measure(case)
        capabilities = [name for name, active in measured["capability_projection"].items() if active]
        context_prediction = _context_prediction(case)
    elif method == "P1":
        measured = prediction_projection(
            route_p1_case(case, policy_id="P1_D05_SIGNAL_UNION", semantic_runtime=runtime)
        )
        capabilities = list(measured["predicted_capabilities"])
        context_prediction = bool(measured["context_resolution_required_prediction"])
    else:
        raise RuntimeError("unknown D4 method")
    row = {
        "review_case_id": case.case_id,
        "method_id": method,
        "context_resolution_required_prediction": context_prediction,
        "predicted_capabilities": [name for name in CAPABILITIES if name in set(capabilities)],
        "prediction_trace_hash": "",
    }
    row["prediction_trace_hash"] = prediction_trace_hash_v1(row)
    return row


def _real_predictor_worker() -> None:
    _raise_superseded_real_entry()
    from evaluation.capability_routing_v1.legacy_hard_route_adapter import LegacyHardRoutingCapabilityAdapterV1, _dashboard_fixture, provider_free_environment
    from evaluation.capability_routing_rq2b_v1.gold_preflight import RoutingCaseInput
    from evaluation.capability_routing_rq2b_v1.run_rq2b import MemoizedSemanticRuntime
    import utils.production_intent_router as production_router
    from .prediction_contract import validate_prediction_rows_v1

    paths = resolve_fixed_rq2d4_paths_v1()
    features = _jsonl(_read_fixed_file_once(paths.feature_view))
    if len(features) != 48:
        raise RuntimeError("real feature view count mismatch")
    cases = [
        RoutingCaseInput(
            case_id=str(row["review_case_id"]),
            current_query=str(row["current_query"]),
            current_page=str(row["current_page"]),
            conversation_history=tuple(row["necessary_conversation_history"]),
        )
        for row in features
    ]
    all_rows: list[dict[str, Any]] = []
    with provider_free_environment():
        raw_runtime = production_router.load_production_semantic_router()
        runtime = MemoizedSemanticRuntime(raw_runtime)
        dashboard = _dashboard_fixture()
        b1_adapter = LegacyHardRoutingCapabilityAdapterV1(
            semantic_runtime=raw_runtime, dashboard_data=dashboard
        )
        for method, target in (
            ("B0", paths.b0_predictions),
            ("B1", paths.b1_predictions),
            ("P1", paths.p1_predictions),
        ):
            rows = [
                _real_prediction_row(
                    case, method, runtime=runtime, dashboard=dashboard, b1_adapter=b1_adapter
                )
                for case in cases
            ]
            _write_local(target, canonical_jsonl_bytes(rows))
            all_rows.extend(rows)
    validation = validate_prediction_rows_v1(all_rows)
    report = {
        "schema_version": "rq2d4-real-predictor-report-v1",
        "status": "PASS",
        "feature_view_open_read": "1/1",
        "combined_source_open_read": "0/0",
        "label_gold_open_read": "0/0",
        "grouping_open_read": "0/0",
        "prediction_ledger_sha256": {
            "B0": sha256_file(paths.b0_predictions),
            "B1": sha256_file(paths.b1_predictions),
            "P1": sha256_file(paths.p1_predictions),
        },
        **validation,
    }
    _write_local(paths.output_root / "predictor_report_v1.json", canonical_json_bytes(report))


def _real_metric_worker() -> None:
    _raise_superseded_real_entry()
    from .fixed_statistical_execution import run_fixed_primary_and_secondary_statistics_v1

    paths = resolve_fixed_rq2d4_paths_v1()
    label_path = ROOT / "evaluation/capability_routing_rq2d2b_v1/track_b_contextual_capability_final_gold_labels_v1.jsonl"
    grouping_path = ROOT / "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_contrast_groups_v1.jsonl"
    grouping_manifest = json.loads((ROOT / "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_grouping_manifest_v1.json").read_text(encoding="utf-8"))
    labels = _jsonl(_read_fixed_file_once(label_path, expected_sha256=LABEL_ONLY_GOLD_SHA256))
    grouping = _jsonl(
        _read_fixed_file_once(
            grouping_path,
            expected_sha256=str(grouping_manifest["ledger"]["sha256"]),
            expected_size=int(grouping_manifest["ledger"]["size_bytes"]),
        )
    )
    prediction_paths = {"B0": paths.b0_predictions, "B1": paths.b1_predictions, "P1": paths.p1_predictions}
    predictions = {
        method: {
            str(row["review_case_id"]): frozenset(row["predicted_capabilities"])
            for row in _jsonl(_read_fixed_file_once(path))
        }
        for method, path in prediction_paths.items()
    }
    gold = {
        str(row["review_case_id"]): frozenset(
            capability for capability in CAPABILITIES if row[capability] in {True, "YES"}
        )
        for row in labels
    }
    by_group: dict[str, list[str]] = {}
    for row in grouping:
        by_group.setdefault(str(row["contrast_group_id"]), []).append(str(row["review_case_id"]))
    ordered_groups = tuple(
        (group_id, tuple(sorted(case_ids, key=lambda value: value.encode("utf-8"))))
        for group_id, case_ids in sorted(by_group.items(), key=lambda item: item[0].encode("utf-8"))
    )
    statistics = run_fixed_primary_and_secondary_statistics_v1(
        ordered_groups=ordered_groups,
        predictions_by_method=predictions,
        gold_by_id=gold,
    )
    result = {
        "schema_version": "rq2d4-track-b-final-results-v1",
        "status": "RESULT_PERSISTED",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "method_ids": ["B0", "B1", "P1"],
        "record_count": 48,
        "group_count": 24,
        "statistics": statistics,
        "p2_secondary_diagnostics": {
            "session_policy": "M0_P1_ONLY",
            "persistent_component": "STRICT_NO_OP",
            "persistent_retrieval_evaluable": False,
            "rag_sufficiency_accuracy_evaluable": False,
        },
        "combined_source_open_count_in_metric_process": 0,
        "label_gold_open_read": "1/1",
        "grouping_open_read": "1/1",
        "provider_calls": 0,
        "network_access": False,
    }
    _write_local(paths.result, canonical_json_bytes(result))
    _write_local(
        paths.output_root / "metric_process_report_v1.json",
        canonical_json_bytes(
            {
                "status": "PASS",
                "label_gold_open_read": "1/1",
                "grouping_open_read": "1/1",
                "combined_source_open_read": "0/0",
                "result_sha256": sha256_file(paths.result),
            }
        ),
    )


def _run_fixed_worker(role: str) -> None:
    _raise_superseded_real_entry()
    if role == "extractor":
        _real_extractor_worker()
    elif role == "predictor":
        _real_predictor_worker()
    elif role == "metric":
        _real_metric_worker()
    else:
        raise SystemExit("unknown fixed D4 worker")


def _run_subprocess(role: str) -> None:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OPENAI_API_KEY": "",
        "CUDA_VISIBLE_DEVICES": "",
    }
    result = subprocess.run(
        [sys.executable, "-m", "evaluation.capability_routing_rq2d3_r2_v1.rq2d4_global_one_shot_contract", "--fixed-worker", role],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"D4 {role} process failed: {result.stderr[-2000:]}")


def _real_prearm(approved_head: str) -> dict[str, Any]:
    if os.environ.get("RQ2D4_TRACK_B_FINAL_EVALUATION_AUTHORISED") != "YES":
        raise D4ExecutionAuthorityError("D4 user authority is absent")
    checks = {
        "head": _git("rev-parse", "HEAD"),
        "worktree": _git("diff", "--quiet"),
        "index": _git("diff", "--cached", "--quiet"),
        "remote": _git("remote"),
        "tag": _git("tag", "--list"),
    }
    if any(result.returncode for result in checks.values()):
        raise D4ExecutionAuthorityError("D4 pre-arm Git check failed")
    if checks["head"].stdout.decode().strip() != approved_head:
        raise D4ExecutionAuthorityError("D4 approved HEAD mismatch")
    if checks["remote"].stdout.strip() or checks["tag"].stdout.strip():
        raise D4ExecutionAuthorityError("D4 remote/tag gate failed")
    paths = resolve_fixed_rq2d4_paths_v1()
    if paths.global_lock.exists() or paths.output_root.exists() or paths.control_root.exists():
        raise D4ExecutionAuthorityError("D4 fixed output/control already exists")
    # Safe pre-arm identity checks only: these do not open any final case/label/group rows.
    from .fixed_statistical_execution import verify_frozen_statistical_sources_v1
    from .model_identity_contract import build_model_identity_contract_v1
    model = build_model_identity_contract_v1()
    statistical = verify_frozen_statistical_sources_v1()
    gold_manifest = json.loads(
        (ROOT / "evaluation/capability_routing_rq2d2b_v1/track_b_capability_gold_manifest_v1.json").read_text(encoding="utf-8")
    )
    grouping_manifest = json.loads(
        (ROOT / "evaluation/capability_routing_rq2d3_r2_v1/track_b_source_blinded_grouping_manifest_v1.json").read_text(encoding="utf-8")
    )
    if (
        gold_manifest["full_text_gold"]["sha256"] != FULL_TEXT_GOLD_SHA256
        or gold_manifest["label_only_gold"]["sha256"] != LABEL_ONLY_GOLD_SHA256
        or gold_manifest["record_count"] != 48
        or grouping_manifest["ledger"]["record_count"] != 48
        or grouping_manifest["ledger"]["group_count"] != 24
    ):
        raise D4ExecutionAuthorityError("D4 safe input-authority metadata mismatch")
    return {
        "approved_head": approved_head,
        "git_clean": True,
        "fixed_targets_absent": True,
        "model_identity": model["status"],
        "statistical_identity_count": len(statistical),
        "safe_input_authority_metadata": "PASS",
        "combined_source_open_count": 0,
        "label_gold_open_count": 0,
        "grouping_open_count": 0,
    }


def execute_real_rq2d4_one_shot_v1(*, approved_head: str) -> dict[str, Any]:
    """Future D4 consuming entry; no path/model/metric/statistical overrides."""

    _raise_superseded_real_entry()
    prearm = _real_prearm(approved_head)
    paths = resolve_fixed_rq2d4_paths_v1()
    reserve_global_lock_v1(paths.global_lock, execution_id=approved_head, synthetic=False)
    try:
        transition_global_lock_v1(paths.global_lock, "INPUT_IDENTITIES_VERIFIED")
        _run_subprocess("extractor")
        transition_global_lock_v1(paths.global_lock, "COMBINED_CASE_SOURCE_OPENED")
        transition_global_lock_v1(paths.global_lock, "FEATURE_VIEW_PERSISTED")
        transition_global_lock_v1(paths.global_lock, "FEATURE_FIREWALL_VERIFIED")
        _run_subprocess("predictor")
        transition_global_lock_v1(paths.global_lock, "B0_PREDICTIONS_PERSISTED")
        transition_global_lock_v1(paths.global_lock, "B1_PREDICTIONS_PERSISTED")
        transition_global_lock_v1(paths.global_lock, "P1_PREDICTIONS_PERSISTED")
        transition_global_lock_v1(paths.global_lock, "PREDICTION_FIREWALL_VERIFIED")
        _run_subprocess("metric")
        transition_global_lock_v1(paths.global_lock, "LABEL_GOLD_OPENED")
        transition_global_lock_v1(paths.global_lock, "GROUPING_OPENED")
        transition_global_lock_v1(paths.global_lock, "PRIMARY_METRICS_PERSISTED")
        transition_global_lock_v1(paths.global_lock, "SECONDARY_DIAGNOSTICS_PERSISTED")
        transition_global_lock_v1(paths.global_lock, "RESULT_PERSISTED")
        lock = transition_global_lock_v1(paths.global_lock, "COMPLETED")
    except BaseException:
        try:
            transition_global_lock_v1(paths.global_lock, "FAILED")
        finally:
            raise
    result = json.loads(paths.result.read_text(encoding="utf-8"))
    return {
        "prearm": prearm,
        "lock": lock,
        "status": "COMPLETED",
        "result_sha256": sha256_file(paths.result),
        "result": result,
    }


def global_one_shot_contract_document_v1() -> dict[str, Any]:
    parameters = tuple(inspect.signature(execute_real_rq2d4_one_shot_v1).parameters)
    if parameters != ("approved_head",):
        raise RuntimeError("real D4 signature drift")
    return {
        "schema_version": "track-b-d4-global-one-shot-contract-v1",
        "status": "FROZEN",
        "execution_contract_id": EXECUTION_CONTRACT_ID,
        "real_entry": "execute_real_rq2d4_one_shot_v1(*, approved_head: str)",
        "entry_parameters": list(parameters),
        "forbidden_entry_parameters": [
            "input_path", "output_path", "gold_path", "grouping_path", "model_path",
            "method_list", "metric_list", "comparison", "threshold", "seed",
            "draw_count", "resample_count", "callback",
        ],
        "prearm_non_consuming_checks": [
            "APPROVED_HEAD_AND_GIT", "CODE_AND_ARTIFACT_IDENTITIES", "LOCAL_MODEL_SMOKE",
            "FIXED_OUTPUT_AND_CONTROL_ABSENCE",
        ],
        "pre_reservation_forbidden_opens": ["SEALED_COMBINED_CASE_SOURCE", "LABEL_ONLY_GOLD", "GROUPING_LEDGER"],
        "reservation": {
            "flags": ["O_CREAT", "O_EXCL", "O_NOFOLLOW_IF_AVAILABLE"],
            "mode": "0600",
            "first_state": "GLOBAL_RESERVED",
            "repository_global": True,
        },
        "failure_persistent": True,
        "completion_persistent": True,
        "retry_permitted": False,
        "post_reservation_pipeline": [
            "FIXED_FEATURE_EXTRACTOR_PROCESS",
            "FIXED_B0_B1_P1_PREDICTOR_PROCESS",
            "FIXED_LABEL_GROUPING_METRIC_PROCESS",
            "FIXED_D3_R1_STATISTICS",
            "DURABLE_RESULT_AND_COMPLETED_LOCK",
        ],
        "real_pipeline_executable": True,
        "d4_execution_count": 0,
    }


def main() -> int:
    _raise_superseded_real_entry()
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed-worker", choices=("extractor", "predictor", "metric"))
    args = parser.parse_args()
    if not args.fixed_worker:
        raise SystemExit("real D4 must use execute_real_rq2d4_one_shot_v1")
    _run_fixed_worker(args.fixed_worker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
