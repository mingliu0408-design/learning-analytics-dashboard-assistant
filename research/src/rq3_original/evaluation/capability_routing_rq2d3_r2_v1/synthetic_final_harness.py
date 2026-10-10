"""Process-isolated synthetic D4 harness and global-lock validation."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from typing import Any, Mapping

from . import CAPABILITIES, ROOT, canonical_json_bytes, canonical_jsonl_bytes, sha256_file


def _read_jsonl_once(path: Path) -> list[dict[str, Any]]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb", closefd=True) as handle:
        data = handle.read()
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_jsonl_bytes(rows))


def _extractor_worker(combined_path: Path, feature_path: Path, report_path: Path) -> None:
    from .track_b_feature_label_process_firewall import extract_feature_view_v1

    combined = _read_jsonl_once(combined_path)
    features, report = extract_feature_view_v1(combined)
    _write_jsonl(feature_path, features)
    forbidden_prefixes = (
        "evaluation.capability_routing_rq2b_v1.b0_",
        "evaluation.capability_routing_rq2b_v1.b1_",
        "evaluation.capability_routing_rq2b_v1.p1_",
        "evaluation.capability_routing_rq2d3_r1_v1",
    )
    imported = [name for name in sys.modules if name.startswith(forbidden_prefixes)]
    if imported:
        raise RuntimeError("extractor imported predictor/statistical modules")
    report.update({"process_role": "TRACK_B_FEATURE_EXTRACTOR_V1", "process_id": os.getpid(), "predictor_modules_imported": 0, "feature_view_sha256": sha256_file(feature_path)})
    report_path.write_bytes(canonical_json_bytes(report))


def _prediction_for_feature(feature: Mapping[str, Any], method: str) -> dict[str, Any]:
    from .prediction_contract import prediction_trace_hash_v1

    match = re.search(r"(\d{3})$", str(feature["current_query"]))
    if not match:
        raise ValueError("synthetic query token absent")
    index = int(match.group(1)) - 1
    if method == "B0":
        capabilities = {CAPABILITIES[index % len(CAPABILITIES)]}
        context = False
    elif method == "B1":
        capabilities = {CAPABILITIES[(index + (1 if index % 4 == 0 else 0)) % len(CAPABILITIES)]}
        context = bool(feature["necessary_conversation_history"])
    elif method == "P1":
        capabilities = {CAPABILITIES[index % len(CAPABILITIES)]}
        if index % 5 == 0 and not capabilities & {"clarification", "safe_direct_response"}:
            capabilities.add(CAPABILITIES[(index + 1) % 4])
        context = bool(feature["necessary_conversation_history"])
    else:
        raise ValueError(method)
    if "clarification" in capabilities:
        capabilities = {"clarification"}
    if "safe_direct_response" in capabilities:
        capabilities = {"safe_direct_response"}
    row = {
        "review_case_id": str(feature["review_case_id"]),
        "method_id": method,
        "context_resolution_required_prediction": context,
        "predicted_capabilities": sorted(capabilities, key=CAPABILITIES.index),
        "prediction_trace_hash": "",
    }
    row["prediction_trace_hash"] = prediction_trace_hash_v1(row)
    return row


def _predictor_worker(feature_path: Path, output_root: Path, report_path: Path) -> None:
    from .prediction_contract import validate_prediction_rows_v1
    from .track_b_feature_label_process_firewall import validate_feature_view_v1

    features = _read_jsonl_once(feature_path)
    validate_feature_view_v1(features)
    all_rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for method in ("B0", "B1", "P1"):
        rows = [_prediction_for_feature(feature, method) for feature in features]
        path = output_root / f"{method.lower()}_predictions.jsonl"
        _write_jsonl(path, rows)
        hashes[method] = sha256_file(path)
        all_rows.extend(rows)
    validation = validate_prediction_rows_v1(all_rows)
    forbidden_imports = [
        name for name in sys.modules
        if name.startswith("evaluation.capability_routing_rq2d3_r1_v1")
        or name.endswith("capability_metrics")
    ]
    if forbidden_imports:
        raise RuntimeError("predictor imported label/metric/statistical module")
    report = {
        "process_role": "TRACK_B_FRESH_PREDICTOR_V1",
        "process_id": os.getpid(),
        "feature_view_open_count": 1,
        "feature_view_read_count": 1,
        "combined_source_open_count": 0,
        "label_gold_open_count": 0,
        "grouping_open_count": 0,
        "forbidden_predictor_import_count": 0,
        "prediction_ledger_sha256": hashes,
        **validation,
    }
    report_path.write_bytes(canonical_json_bytes(report))


def _metric_worker(label_path: Path, grouping_path: Path, output_root: Path, result_path: Path, report_path: Path) -> None:
    from .fixed_statistical_execution import run_fixed_synthetic_statistics_v1

    labels = _read_jsonl_once(label_path)
    grouping = _read_jsonl_once(grouping_path)
    predictions: dict[str, dict[str, frozenset[str]]] = {}
    for method in ("B0", "B1", "P1"):
        rows = _read_jsonl_once(output_root / f"{method.lower()}_predictions.jsonl")
        predictions[method] = {str(row["review_case_id"]): frozenset(row["predicted_capabilities"]) for row in rows}
    gold = {
        str(row["review_case_id"]): frozenset(
            capability for capability in CAPABILITIES if row[capability] == "YES"
        )
        for row in labels
    }
    by_group: dict[str, list[str]] = {}
    for row in grouping:
        by_group.setdefault(str(row["contrast_group_id"]), []).append(str(row["review_case_id"]))
    ordered_groups = tuple(
        (group_id, tuple(sorted(case_ids)))
        for group_id, case_ids in sorted(by_group.items())
    )
    result = run_fixed_synthetic_statistics_v1(
        ordered_groups=ordered_groups,
        predictions_by_method=predictions,
        gold_by_id=gold,
    )
    result_path.write_bytes(canonical_json_bytes(result))
    report = {
        "process_role": "TRACK_B_FRESH_METRIC_PROCESS_V1",
        "process_id": os.getpid(),
        "combined_source_open_count": 0,
        "label_gold_open_count": 1,
        "label_gold_read_count": 1,
        "grouping_open_count": 1,
        "grouping_read_count": 1,
        "prediction_ledgers_open_count": 3,
        "predictions_persisted_before_label_open": True,
        "statistics_result_sha256": sha256_file(result_path),
        "primary_comparison": "P1_VS_B1",
        "secondary_holm_count": 2,
    }
    report_path.write_bytes(canonical_json_bytes(report))


def _run_worker(args: list[str]) -> None:
    role = args[0]
    paths = [Path(value) for value in args[1:]]
    if role == "extractor" and len(paths) == 3:
        _extractor_worker(*paths)
    elif role == "predictor" and len(paths) == 3:
        _predictor_worker(*paths)
    elif role == "metric" and len(paths) == 5:
        _metric_worker(*paths)
    else:
        raise SystemExit("invalid synthetic worker invocation")


def _subprocess(role: str, *paths: Path) -> None:
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OPENAI_API_KEY": "",
        "CUDA_VISIBLE_DEVICES": "",
    }
    result = subprocess.run(
        [sys.executable, "-m", "evaluation.capability_routing_rq2d3_r2_v1.synthetic_final_harness", "--worker", role, *(str(path) for path in paths)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"synthetic {role} worker failed: {result.stderr[-1000:]}")


def _global_lock_validation(root: Path) -> dict[str, Any]:
    from .rq2d4_state_machine import GLOBAL_STATE_ORDER, GlobalOneShotConsumedError, reserve_global_lock_v1, transition_global_lock_v1

    complete_lock = root / "complete" / "GLOBAL.json"
    reserve_global_lock_v1(complete_lock, execution_id="synthetic-complete", synthetic=True)
    for state in GLOBAL_STATE_ORDER[1:]:
        final = transition_global_lock_v1(complete_lock, state)
    completion_retry_blocked = False
    try:
        reserve_global_lock_v1(complete_lock, execution_id="retry", synthetic=True)
    except GlobalOneShotConsumedError:
        completion_retry_blocked = True

    failed_lock = root / "failed" / "GLOBAL.json"
    reserve_global_lock_v1(failed_lock, execution_id="synthetic-failed", synthetic=True)
    failed = transition_global_lock_v1(failed_lock, "FAILED")
    failure_retry_blocked = False
    try:
        reserve_global_lock_v1(failed_lock, execution_id="retry", synthetic=True)
    except GlobalOneShotConsumedError:
        failure_retry_blocked = True

    concurrent_lock = root / "concurrent" / "GLOBAL.json"
    barrier = threading.Barrier(2)
    def attempt(value: str) -> str:
        barrier.wait()
        try:
            reserve_global_lock_v1(concurrent_lock, execution_id=value, synthetic=True)
            return "RESERVED"
        except GlobalOneShotConsumedError:
            return "EXCLUDED"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, ("left", "right")))
    if outcomes != ["EXCLUDED", "RESERVED"]:
        raise RuntimeError("synthetic concurrent exclusion failed")
    return {
        "complete_state": final["state"],
        "complete_history_count": len(final["state_history"]),
        "completion_retry_blocked": completion_retry_blocked,
        "failed_state": failed["state"],
        "failure_retry_blocked": failure_retry_blocked,
        "concurrent_outcomes": outcomes,
        "exclusive_creation": True,
        "lock_mode_0600": (complete_lock.stat().st_mode & 0o777) == 0o600,
    }


def run_synthetic_final_harness_v1() -> dict[str, Any]:
    from .synthetic_track_b_final_fixture import build_synthetic_track_b_final_fixture_v1, synthetic_fixture_contract_document_v1

    fixture = build_synthetic_track_b_final_fixture_v1()
    with tempfile.TemporaryDirectory(prefix="rq2d3-r2-synthetic-") as temporary_name:
        root = Path(temporary_name)
        combined_path = root / "combined.jsonl"
        labels_path = root / "labels.jsonl"
        grouping_path = root / "grouping.jsonl"
        feature_path = root / "feature.jsonl"
        prediction_root = root / "predictions"
        extractor_report_path = root / "extractor_report.json"
        predictor_report_path = root / "predictor_report.json"
        metric_report_path = root / "metric_report.json"
        statistics_path = root / "statistics.json"
        _write_jsonl(combined_path, fixture["combined"])
        _write_jsonl(labels_path, fixture["labels"])
        _write_jsonl(grouping_path, fixture["grouping"])
        _subprocess("extractor", combined_path, feature_path, extractor_report_path)
        extractor = json.loads(extractor_report_path.read_text(encoding="utf-8"))
        _subprocess("predictor", feature_path, prediction_root, predictor_report_path)
        predictor = json.loads(predictor_report_path.read_text(encoding="utf-8"))
        if not all((prediction_root / f"{method}_predictions.jsonl").is_file() for method in ("b0", "b1", "p1")):
            raise RuntimeError("predictions not persisted before metric process")
        _subprocess("metric", labels_path, grouping_path, prediction_root, statistics_path, metric_report_path)
        metric = json.loads(metric_report_path.read_text(encoding="utf-8"))
        statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
        lock = _global_lock_validation(root / "locks")
    pids = {extractor["process_id"], predictor["process_id"], metric["process_id"]}
    if len(pids) != 3:
        raise RuntimeError("synthetic workers were not fresh processes")
    return {
        "schema_version": "rq2d3-r2-synthetic-validation-v1",
        "stage": "RQ2-D3-R2",
        "status": "PASS",
        "fixture": synthetic_fixture_contract_document_v1(),
        "process_isolation": {
            "fresh_process_count": 3,
            "all_process_ids_distinct": True,
            "extractor": {key: value for key, value in extractor.items() if key != "process_id"},
            "predictor": {key: value for key, value in predictor.items() if key != "process_id"},
            "metric": {key: value for key, value in metric.items() if key != "process_id"},
        },
        "fixed_statistics": {
            "contract_id": statistics["contract_id"],
            "synthetic_test_only": statistics["synthetic_test_only"],
            "comparison_count": len(statistics["comparisons"]),
            "primary": statistics["primary"],
            "secondary_holm_count": len(statistics["secondary_holm"]),
            "sign_flip_draws": statistics["fixed_draws"],
            "bootstrap_resamples": statistics["fixed_resamples"],
            "type7": statistics["type7"],
            "comparison_summaries": {
                comparison: {
                    "wins_ties_losses": value["wins_ties_losses"],
                    "sign_flip": {key: value["clustered_sign_flip"][key] for key in ("draw_count", "seed", "extreme_count", "p_numerator", "p_denominator", "p_value")},
                    "bootstrap": {"resamples": value["whole_cluster_bootstrap"]["resamples"], "seed": value["whole_cluster_bootstrap"]["seed"], "metrics": value["whole_cluster_bootstrap"]["metrics"]},
                }
                for comparison, value in statistics["comparisons"].items()
            },
        },
        "global_one_shot": lock,
        "p2_secondary_only": True,
        "persistent_component": "STRICT_NO_OP",
        "real_track_b_access_count": 0,
        "real_track_b_prediction_count": 0,
        "real_track_b_metric_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("worker_args", nargs="*")
    args = parser.parse_args()
    if not args.worker:
        raise SystemExit("synthetic harness must be invoked by the stage validator")
    _run_worker(args.worker_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
