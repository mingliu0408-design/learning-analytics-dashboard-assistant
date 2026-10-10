"""C0 DEV84 and RQ2 development artifact parity before any D4 execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from evaluation.learned_intent_ranking.lr3.data_loader import load_dev_views
from evaluation.learned_intent_ranking.lr4b_dev.evaluate_dev import evaluate_all_views
from evaluation.learned_intent_ranking.lr4b_dev.runtime_preflight import run_runtime_preflight
from evaluation.learned_intent_ranking.rq1c.final_model_runner import _load_dev_and_frozen, _ranking_identity

from . import ROOT, sha256_file


REQUIRED_RQ2_HASHES = {
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/synthetic_P1_D05_SIGNAL_UNION.jsonl": "75ab3d6c1ff4d58b652d5b089ff6f2b289ada756cfc4640cb1cc2df8040916ae",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/authentic_final_policy_v1.jsonl": "070c034bf8de35f6dd9465e1a858916c6fc39dfeffaecbfd16ceed10cff7951f",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/registry_final_policy_v1.jsonl": "82a42f1b3a48c10efe8a193ad273560c5141fc6a3e542219f8a8efcfff453e4e",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/envelopes/context_envelopes_v1.jsonl": "63a458712cfd6cf16e60d114a601617168703919fd5e8cc5d2207ae9d860a6a0",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/c0_score_vectors/c0_full_score_vectors_v1.jsonl": "0f418a12c3a5f1a0fcbf473ae718022ab3d7a4efeca52acc739b240c36629342",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/error_ledgers/metric_join_rows_v1.json": "497919bf72d32eb23666ca989de748b201a75aaf4f2c7ba2c8527fe7615bd1a9",
}


def _max_score_delta(actual: Mapping[str, Any], reference: Mapping[str, Any]) -> float:
    maximum = 0.0
    for key in ("top1_score", "top2_score", "margin", "out_of_scope_score"):
        left = actual.get(key)
        right = reference.get(key)
        if left is None and right is None:
            continue
        maximum = max(maximum, abs(float(left) - float(right)))
    actual_ranking = actual["intent_ranking"]
    reference_ranking = reference["intent_ranking"]
    if len(actual_ranking) != len(reference_ranking):
        raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")
    for left, right in zip(actual_ranking, reference_ranking):
        if left["label"] != right["label"] or tuple(left["example_ids"]) != tuple(right["example_ids"]):
            raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")
        maximum = max(maximum, abs(float(left["score"]) - float(right["score"])))
    return maximum


def run_development_parity_v1() -> dict[str, Any]:
    dev_records, frozen = _load_dev_and_frozen(ROOT)
    runtime = run_runtime_preflight({"dev_records": dev_records, "frozen": frozen})
    actual_rows = runtime["c0_predictions"]
    c0_report = json.loads((ROOT / "evaluation/learned_intent_ranking/lr4b_dev/rq1b_c0_reproduction_v1.json").read_text(encoding="utf-8"))
    ledger_relative = Path(str(c0_report["local_prediction_ledger_relative_path"]))
    ledger_path = ROOT / ledger_relative
    if sha256_file(ledger_path) != c0_report["local_prediction_ledger_sha256"]:
        raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")
    reference_payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    reference_rows = reference_payload["predictions"]
    if len(actual_rows) != 84 or len(reference_rows) != 84:
        raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")
    reference_by_id = {str(row["record_id"]): row for row in reference_rows}
    ranking_matches = 0
    maximum_score_delta = 0.0
    for row in actual_rows:
        reference = reference_by_id[str(row["record_id"])]
        ranking_matches += int(_ranking_identity(row) == _ranking_identity(reference))
        maximum_score_delta = max(maximum_score_delta, _max_score_delta(row, reference))
    bundle = {"view_ids": load_dev_views(dev_records), "frozen": frozen}
    metrics = evaluate_all_views(actual_rows, bundle)
    metrics_exact = metrics == c0_report["actual_view_metrics"]
    maximum_metric_delta = 0.0 if metrics_exact else float("inf")
    if ranking_matches != 84 or maximum_score_delta > 1e-12 or maximum_metric_delta > 1e-12:
        raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")

    rq2b_validation = json.loads((ROOT / "evaluation/capability_routing_rq2b_v1/rq2b_validation_report_v1.json").read_text(encoding="utf-8"))
    frozen_hashes = dict(rq2b_validation["local_ledger_sha256"])
    if any(sha256_file(ROOT / relative) != expected for relative, expected in frozen_hashes.items()):
        raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")
    if any(frozen_hashes.get(relative) != expected for relative, expected in REQUIRED_RQ2_HASHES.items()):
        raise RuntimeError("BLOCKED_RQ2_D3_R2_DEVELOPMENT_PARITY")
    b0 = json.loads((ROOT / "evaluation/capability_routing_rq2b_v1/rq2b_b0_contract_v1.json").read_text(encoding="utf-8"))
    b1 = json.loads((ROOT / "evaluation/capability_routing_rq2b_v1/rq2b_b1_reproduction_v1.json").read_text(encoding="utf-8"))
    return {
        "schema_version": "rq2d3-r2-development-parity-v1",
        "stage": "RQ2-D3-R2",
        "status": "PASS",
        "c0_dev84": {
            "record_count": 84,
            "ranking_identity_match_count": ranking_matches,
            "ranking_identity_required": 84,
            "score_vector_identity": maximum_score_delta == 0.0,
            "maximum_absolute_score_delta": maximum_score_delta,
            "metric_identity": metrics_exact,
            "maximum_absolute_metric_delta": maximum_metric_delta,
            "tolerance": 1e-12,
            "reference_ledger_sha256": c0_report["local_prediction_ledger_sha256"],
        },
        "rq2_development": {
            "synthetic_record_count": 35,
            "authentic_record_count": 22,
            "context_missing_record_count": 3,
            "b0_identity": b0["baseline_identity"],
            "b1_identity": b1["baseline_identity"],
            "p1_identity": "P1_D05_SIGNAL_UNION",
            "verified_local_ledger_count": len(frozen_hashes),
            "verified_local_ledger_sha256": dict(sorted(frozen_hashes.items())),
            "required_identity_subset": dict(sorted(REQUIRED_RQ2_HASHES.items())),
        },
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_b_feature_access_count": 0,
        "track_b_prediction_count": 0,
        "track_b_metric_count": 0,
    }
