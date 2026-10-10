"""Run deterministic Stage 0 contract validation and toy-only dry-runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import MODEL_IDS, PACKAGE_ROOT, PROJECT_ROOT
from .contracts import (
    Stage0ContractError,
    load_json,
    load_jsonl,
    load_stage0_contracts,
    validate_b1_legacy_contract,
    validate_case,
    validate_clarification_contract,
    validate_contract,
    validate_contrast_pair,
    validate_dataset_registry,
    validate_prediction,
    validate_scenario_matrix,
)
from .interfaces import run_no_paid_api_dry_run
from .leakage import assert_no_leakage
from .metrics import evaluate_contrast_consistency, evaluate_predictions


EXPECTED_ASSET_COUNTS = {
    "RQ1_C0_APPROVED_INTENT_INDEX": 62,
    "RQ1_C0_FROZEN_EMBEDDINGS": 62,
    "RQ2_V1_AUTHENTIC_PILOT": 22,
    "RQ2_V1_AUTHENTIC_CONTEXT_MISSING": 3,
    "RQ2_V1_SYNTHETIC_STRESS": 35,
    "RQ2_V1_TRACK_B_FINAL_GOLD": 48,
    "COURSE_RAG_MANIFEST_V2": 6,
    "RQ2_V1_CONTROLLED_MECHANISM_FIXTURES": 28,
    "LEGACY_UNIFIED_CHATBOT_BENCHMARK": 62,
}


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


def _validate_registry_reality(registry: dict[str, Any]) -> None:
    entries = {entry["asset_id"]: entry for entry in registry["assets"]}
    if set(entries) != set(EXPECTED_ASSET_COUNTS):
        raise Stage0ContractError("dataset registry asset membership drift")
    for asset_id, expected in EXPECTED_ASSET_COUNTS.items():
        if entries[asset_id]["record_count"] != expected:
            raise Stage0ContractError(f"registry count drift for {asset_id}")

    line_count_assets = {
        "RQ1_C0_APPROVED_INTENT_INDEX",
        "RQ2_V1_AUTHENTIC_PILOT",
        "RQ2_V1_AUTHENTIC_CONTEXT_MISSING",
        "RQ2_V1_SYNTHETIC_STRESS",
        "COURSE_RAG_MANIFEST_V2",
        "LEGACY_UNIFIED_CHATBOT_BENCHMARK",
    }
    for asset_id in line_count_assets:
        entry = entries[asset_id]
        observed = _line_count(PROJECT_ROOT / entry["path"])
        if observed != entry["record_count"]:
            raise Stage0ContractError(f"on-disk count drift for {asset_id}")

    track_b = load_json(PROJECT_ROOT / entries["RQ2_V1_TRACK_B_FINAL_GOLD"]["path"])
    if track_b.get("record_count") != 48:
        raise Stage0ContractError("legacy Track B count drift")
    mechanisms = load_json(
        PROJECT_ROOT / entries["RQ2_V1_CONTROLLED_MECHANISM_FIXTURES"]["path"]
    )
    if mechanisms.get("total") != 28:
        raise Stage0ContractError("controlled mechanism fixture count drift")


def _validate_stage0_boundary(cases: list[dict[str, Any]]) -> None:
    if any(case["partition"] == "TEST" for case in cases):
        raise Stage0ContractError("Stage 0 toy fixtures must not create TEST cases")
    if any(not case["governance"]["fixture_only"] for case in cases):
        raise Stage0ContractError("Stage 0 case payloads must remain toy-only")
    if any(case["provenance"]["type"] == "AUTHENTIC" for case in cases):
        raise Stage0ContractError("Stage 0 must not invent authentic fixtures")


def run_validation() -> dict[str, Any]:
    assets = load_stage0_contracts()
    cases = load_jsonl(PACKAGE_ROOT / "fixtures" / "toy_cases_v1.jsonl")
    predictions = load_jsonl(PACKAGE_ROOT / "fixtures" / "toy_predictions_v1.jsonl")
    contrast_pairs = load_jsonl(
        PACKAGE_ROOT / "fixtures" / "toy_contrast_pairs_v1.jsonl"
    )
    checks: dict[str, str] = {}
    failures: list[dict[str, str]] = []

    def check(name: str, function: Callable[[], Any]) -> None:
        try:
            function()
            checks[name] = "PASS"
        except Exception as exc:  # validation report must retain all failures
            checks[name] = "FAIL"
            failures.append({"check": name, "error": f"{type(exc).__name__}: {exc}"})

    check("capability_contract", lambda: validate_contract(assets["capability_contract"]))
    check(
        "b1_frozen_rq1_identity",
        lambda: validate_b1_legacy_contract(assets["b1_legacy_contract"]),
    )
    check(
        "dataset_registry_schema",
        lambda: validate_dataset_registry(assets["dataset_registry"]),
    )
    check(
        "dataset_registry_repository_reality",
        lambda: _validate_registry_reality(assets["dataset_registry"]),
    )
    check("scenario_matrix_2x2x2", lambda: validate_scenario_matrix(assets["scenario_matrix"]))
    check(
        "clarification_scenario_contract",
        lambda: validate_clarification_contract(assets["clarification_contract"]),
    )
    check("toy_case_schema", lambda: [validate_case(case) for case in cases])
    check(
        "toy_prediction_schema",
        lambda: [validate_prediction(prediction) for prediction in predictions],
    )
    check(
        "contrast_pair_schema",
        lambda: [validate_contrast_pair(pair) for pair in contrast_pairs],
    )
    check("leakage_guards_clean_fixture", lambda: assert_no_leakage(cases))
    check("metric_harness", lambda: evaluate_predictions(cases, predictions))
    check(
        "contrast_consistency_hook",
        lambda: evaluate_contrast_consistency(cases, predictions, contrast_pairs),
    )
    check(
        "all_six_model_interfaces",
        lambda: (
            run_no_paid_api_dry_run(cases[0])
            if len(MODEL_IDS) == 6
            else (_ for _ in ()).throw(Stage0ContractError("model ID count drift"))
        ),
    )
    check(
        "no_paid_api_dry_run",
        lambda: run_no_paid_api_dry_run(cases[0]),
    )
    check("stage0_no_benchmark_construction", lambda: _validate_stage0_boundary(cases))

    dry_run = run_no_paid_api_dry_run(cases[0]) if not failures else {
        "provider_calls": 0,
        "network_access": False,
        "training_performed": False,
        "final_test_executed": False,
    }
    return {
        "schema_version": "rq2-v2-stage0-validation-report-v1",
        "status": "PASS" if not failures else "FAIL",
        "check_count": len(checks),
        "pass_count": sum(value == "PASS" for value in checks.values()),
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "toy_fixture_case_count": len(cases),
        "planned_benchmark_case_count_created": 0,
        "provider_calls": dry_run["provider_calls"],
        "network_access": dry_run["network_access"],
        "training_performed": dry_run["training_performed"],
        "final_test_executed": dry_run["final_test_executed"],
        "rq3_executed": False,
    }


def main() -> int:
    report = run_validation()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

