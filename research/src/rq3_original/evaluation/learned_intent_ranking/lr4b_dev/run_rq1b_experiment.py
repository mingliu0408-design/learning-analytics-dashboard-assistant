"""Execute the governed RQ1-B preflights, C0/V0 gates, and twenty M64 runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import (
    PREDICTION_LEDGER_DIR,
    RESULTS_DIR,
    SCENARIO_ORDER,
    TRAINING_SEEDS,
    VIEW_A,
)
from .embedding_cache import build_or_load_embedding_cache
from .evaluate_dev import run_c0_reproduction_gate
from .governed_data_loader import (
    RQ1BInputError,
    canonical_json_bytes,
    load_governed_bundle,
    verify_protected_sources_unchanged,
)
from .model import architecture_manifest
from .pair_builder import PairConstructionError, build_all_scenario_pair_inputs
from .runtime_preflight import RuntimePreflightError, run_runtime_preflight
from .token_budget import (
    ActualTruncationAuthorityRequired,
    SyntheticTruncationError,
    build_token_budget_report,
)
from .train_m64 import train_scenario_seed, verify_v0_reproduction


RUN_BUNDLE_PATH = RESULTS_DIR / "rq1b_run_bundle_v1.json"


def _blocker_for(exc: BaseException) -> str:
    message = str(exc)
    if message.startswith("BLOCKED_RQ1_B_"):
        return message
    if isinstance(exc, RQ1BInputError):
        return "BLOCKED_RQ1_B_INPUT_CONTRACT_MISMATCH"
    if isinstance(exc, RuntimePreflightError):
        return "BLOCKED_RQ1_B_MISSING_LOCAL_RUNTIME_DEPENDENCY"
    if isinstance(exc, ActualTruncationAuthorityRequired):
        return "BLOCKED_RQ1_B_ACTUAL_TRUNCATION_REQUIRES_AUTHORITY"
    if isinstance(exc, PairConstructionError):
        return "BLOCKED_RQ1_B_INSUFFICIENT_SAFE_NEGATIVES"
    if isinstance(exc, SyntheticTruncationError):
        return "BLOCKED_RQ1_B_TEST_FAILURE"
    return "BLOCKED_RQ1_B_OTHER"


def execute() -> dict[str, Any]:
    bundle = load_governed_bundle()
    runtime = run_runtime_preflight(bundle)
    token_report = build_token_budget_report(bundle, runtime["tokenizer"])
    pair_inputs = build_all_scenario_pair_inputs(bundle)
    embeddings = build_or_load_embedding_cache(
        bundle, runtime["model"], runtime["dev_vectors"]
    )

    c0_ledger = PREDICTION_LEDGER_DIR / "rq1b_c0_dev_predictions_v1.json"
    c0 = run_c0_reproduction_gate(
        bundle, runtime["c0_predictions"], c0_ledger
    )
    c0_mrr = float(c0["actual_view_metrics"][VIEW_A]["mrr"])

    runs: list[dict[str, Any]] = []
    v0_runs: list[dict[str, Any]] = []
    for seed in TRAINING_SEEDS:
        print(f"RQ1-B training V0 seed {seed}", flush=True)
        run = train_scenario_seed(
            scenario="V0",
            seed=seed,
            sampler=pair_inputs["samplers"]["V0"],
            bundle=bundle,
            embeddings=embeddings,
            mpnet_model=runtime["model"],
        )
        runs.append(run)
        v0_runs.append(run)
    v0 = verify_v0_reproduction(v0_runs, c0_mrr)

    for scenario in SCENARIO_ORDER[1:]:
        for seed in TRAINING_SEEDS:
            print(f"RQ1-B training {scenario} seed {seed}", flush=True)
            runs.append(
                train_scenario_seed(
                    scenario=scenario,
                    seed=seed,
                    sampler=pair_inputs["samplers"][scenario],
                    bundle=bundle,
                    embeddings=embeddings,
                    mpnet_model=runtime["model"],
                )
            )
    expected_matrix = {
        (scenario, seed) for scenario in SCENARIO_ORDER for seed in TRAINING_SEEDS
    }
    actual_matrix = {(run["scenario"], int(run["seed"])) for run in runs}
    if len(runs) != 20 or actual_matrix != expected_matrix:
        raise RuntimeError("BLOCKED_RQ1_B_EXPERIMENT_INCOMPLETE")
    protected = verify_protected_sources_unchanged()

    run_bundle = {
        "schema_version": "rq1b-local-run-bundle-v1",
        "stage": "RQ1-B",
        "status": "COMPLETE_READY_FOR_DETERMINISTIC_FINALISATION",
        "starting_state": bundle["git_gate"],
        "input_contract": bundle["input_gate"],
        "runtime_preflight": runtime["report"],
        "token_budget": token_report,
        "embedding_manifest": embeddings["manifest"],
        "frozen_evaluation_identity": {
            "candidate_example_count": 62,
            "candidate_label_count": 16,
            "candidate_index_sha256": bundle["frozen"]["approved_index_sha256"],
            "candidate_embedding_sha256": bundle["frozen"]["embedding_artifact_sha256"],
            "aggregation": "MAX",
            "eedi_candidate_count": 0,
            "view_counts": {
                view: len(ids) for view, ids in bundle["view_ids"].items()
            },
            "view_a_gold_label_count": 8,
        },
        "representation_ledger_fingerprint": bundle[
            "representation_ledger_fingerprint"
        ],
        "scenario_membership_fingerprints": bundle[
            "scenario_membership_fingerprints"
        ],
        "architecture": architecture_manifest(),
        "pair_construction": pair_inputs["audit"],
        "data_concentration": pair_inputs["concentration"],
        "c0_reproduction": c0,
        "c0_execution_count": 1,
        "v0_reproduction": v0,
        "runs": runs,
        "run_count": len(runs),
        "experiment_matrix": [
            {"scenario": scenario, "seed": seed}
            for scenario in SCENARIO_ORDER
            for seed in TRAINING_SEEDS
        ],
        "protected_sources": protected,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "final_gold_used": False,
        "final_gold_tuning": False,
        "network_access": False,
        "provider_calls": 0,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_BUNDLE_PATH.write_bytes(canonical_json_bytes(run_bundle))
    return run_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RUN_BUNDLE_PATH)
    args = parser.parse_args(argv)
    try:
        result = execute()
        if args.output != RUN_BUNDLE_PATH:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical_json_bytes(result))
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "run_count": result["run_count"],
                    "c0_reproduction": result["c0_reproduction"]["status"],
                    "v0_reproduction": result["v0_reproduction"]["status"],
                    "final_gold_accessed": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    except (
        RQ1BInputError,
        RuntimePreflightError,
        ActualTruncationAuthorityRequired,
        SyntheticTruncationError,
        PairConstructionError,
        RuntimeError,
        ValueError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": _blocker_for(exc),
                    "final_gold_accessed": False,
                    "raw_text_emitted": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
