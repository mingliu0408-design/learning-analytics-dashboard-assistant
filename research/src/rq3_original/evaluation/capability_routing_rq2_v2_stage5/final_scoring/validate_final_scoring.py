"""Read-only validation of immutable Stage 5E outputs after Gold scoring."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from evaluation.capability_routing_rq2_v2_stage4.final_router_selection.selection_rule import (
    COVERAGE_FIELDS,
    select_final_router,
)

from .constants import (
    ACCESS_RECEIPT_PATH,
    ALL_METHOD_IDS,
    BINDING_PATH,
    COMPLETE_METHOD_IDS,
    ELIGIBILITY_PATH,
    ELIGIBLE_METHOD_IDS,
    FINAL_SCORING_DIR,
    PREDICTION_HASHES,
    PRE_SCORING_RECEIPT_PATH,
    PROJECT_ROOT,
    SELECTION_RULE_PATH,
)
from .metrics import bootstrap_analysis
from .scoring import (
    Stage5EError,
    canonical_json_bytes,
    read_json,
    read_jsonl,
    sha256_file,
)


def _require(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise Stage5EError(message)
    checks.append(message)


def validate_outputs(*, recompute_bootstrap: bool = True) -> dict[str, Any]:
    checks: list[str] = []
    _require(PRE_SCORING_RECEIPT_PATH.is_file(), "pre-scoring receipt exists", checks)
    _require(ACCESS_RECEIPT_PATH.is_file(), "Gold access receipt exists", checks)
    _require(BINDING_PATH.is_file(), "write-once binding exists", checks)
    pre = read_json(PRE_SCORING_RECEIPT_PATH)
    for relative, expected in pre["scoring_source_file_hashes"].items():
        _require(
            sha256_file(PROJECT_ROOT / relative) == expected,
            f"scoring source unchanged: {relative}",
            checks,
        )
    for relative, expected in PREDICTION_HASHES.items():
        _require(
            sha256_file(PROJECT_ROOT / relative) == expected,
            f"prediction source unchanged: {relative}",
            checks,
        )

    access = read_json(ACCESS_RECEIPT_PATH)
    extraction_dir = Path(access["fresh_temporary_extraction_directory"])
    _require(extraction_dir.is_dir(), "fresh extraction directory retained", checks)
    _require(
        sha256_file(extraction_dir / "test_gold_escrow_v1.csv")
        == access["gold_csv_sha256"],
        "Gold CSV hash matches access receipt",
        checks,
    )
    _require(
        sha256_file(extraction_dir / "test_gold_escrow_v1.jsonl")
        == access["gold_jsonl_sha256"],
        "Gold JSONL hash matches access receipt",
        checks,
    )

    normalized = read_jsonl(FINAL_SCORING_DIR / "final_test_normalized_records_v1.jsonl")
    _require(len(normalized) == 36, "normalized record count is 36", checks)
    normalized_ids = {row["annotation_case_id"] for row in normalized}
    _require(len(normalized_ids) == 36, "normalized annotation IDs are unique", checks)
    families: dict[str, int] = {}
    for row in normalized:
        family = row["canonical_scenario_family_id"]
        families[family] = families.get(family, 0) + 1
    _require(
        len(families) == 18 and set(families.values()) == {2},
        "normalized family structure is 18 pairs",
        checks,
    )

    complete_rows = read_jsonl(
        FINAL_SCORING_DIR / "final_test_complete_method_predictions_v1.jsonl"
    )
    _require(len(complete_rows) == 396, "complete prediction row count is 396", checks)
    _require(
        {row["method_id"] for row in complete_rows} == set(COMPLETE_METHOD_IDS),
        "complete method universe is exact",
        checks,
    )
    by_method: dict[str, dict[str, tuple[bool, bool, bool]]] = {
        method_id: {} for method_id in COMPLETE_METHOD_IDS
    }
    for row in complete_rows:
        by_method[row["method_id"]][row["annotation_case_id"]] = (
            row["rag_required"],
            row["memory_required"],
            row["planning_required"],
        )
        _require(
            row["prediction_status"] == "FROZEN_COMPLETE_NO_IMPUTATION",
            f"no imputation: {row['method_id']} {row['annotation_case_id']}",
            checks,
        )
    _require(
        all(set(values) == normalized_ids for values in by_method.values()),
        "every complete method covers all 36 cases",
        checks,
    )

    method_results = read_json(FINAL_SCORING_DIR / "final_test_method_results_v1.json")
    _require(method_results["method_count"] == 14, "method result count is 14", checks)
    _require(
        tuple(row["method_id"] for row in method_results["methods"]) == ALL_METHOD_IDS,
        "14-method registry order is preserved",
        checks,
    )
    with (FINAL_SCORING_DIR / "final_router_selection_candidate_table_v1.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        candidates = list(csv.DictReader(handle))
    _require(len(candidates) == 8, "selection candidate count is 8", checks)
    _require(
        tuple(row["method_id"] for row in candidates) == ELIGIBLE_METHOD_IDS,
        "selection candidates match frozen order",
        checks,
    )
    parsed_candidates: list[dict[str, Any]] = []
    numeric_fields = (
        "core_macro_f1_gold_answer_cases",
        "exact_capability_set_match",
        "jaccard",
        "under_routing_rate",
        "over_routing_rate",
        "family_both_utterances_correct_rate",
        "complete_gold_pattern_contrast_match_rate",
        "counterfactual_provider_component_call_count",
        "counterfactual_token_cost",
        "method_tier_number",
    )
    for row in candidates:
        value: dict[str, Any] = dict(row)
        for field in COVERAGE_FIELDS:
            value[field] = row[field] == "true"
        for field in numeric_fields:
            value[field] = row[field]
        parsed_candidates.append(value)
    _require(
        all(all(row[field] is True for field in COVERAGE_FIELDS) for row in parsed_candidates),
        "all eight candidates pass all five coverage gates",
        checks,
    )
    selected = select_final_router(
        parsed_candidates, read_json(ELIGIBILITY_PATH), read_json(SELECTION_RULE_PATH)
    )
    selection_result = read_json(
        FINAL_SCORING_DIR / "final_router_selection_result_v1.json"
    )
    _require(
        selected == selection_result["selected_method_id"],
        "frozen selection result recomputes exactly",
        checks,
    )
    _require(selected in ELIGIBLE_METHOD_IDS, "selected method is eligible", checks)
    _require(
        selected != "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION",
        "selected method is not P4",
        checks,
    )
    binding = read_json(BINDING_PATH)
    _require(binding["selected_method_id"] == selected, "binding matches selection", checks)
    _require(binding["write_count"] == 1, "binding write count is one", checks)
    _require(binding["overwrite_permitted"] is False, "binding overwrite is prohibited", checks)
    _require(binding["p4_selection_permitted"] is False, "binding prohibits P4", checks)

    if recompute_bootstrap:
        answer_rows = [row for row in normalized if row["gold_dialogue_action"] == "ANSWER"]
        recomputed = bootstrap_analysis(answer_rows, by_method)
        stored_path = FINAL_SCORING_DIR / "final_test_bootstrap_v1.json"
        _require(
            canonical_json_bytes(recomputed) == stored_path.read_bytes(),
            "bootstrap bytes are deterministic",
            checks,
        )

    costs = read_json(FINAL_SCORING_DIR / "final_test_cost_and_calls_v1.json")
    _require(costs["stage5e_new_provider_calls"] == 0, "Stage 5E provider calls are zero", checks)
    source = read_json(FINAL_SCORING_DIR / "FINAL_TEST_SOURCE_MANIFEST.json")
    _require(source["network_calls_during_stage5e"] == 0, "Stage 5E network calls are zero", checks)
    _require(source["prediction_reruns"] == 0, "prediction reruns are zero", checks)
    _require(source["rq3_executions"] == 0, "RQ3 executions are zero", checks)

    output_manifest = read_json(FINAL_SCORING_DIR / "FINAL_STAGE5E_SHA256_MANIFEST.json")
    for entry in output_manifest["files"]:
        path = FINAL_SCORING_DIR / entry["name"]
        _require(
            path.is_file()
            and sha256_file(path) == entry["sha256"]
            and path.stat().st_size == entry["size_bytes"],
            f"output manifest entry matches: {entry['name']}",
            checks,
        )
    _require(
        sha256_file(BINDING_PATH) == output_manifest["external_binding"]["sha256"],
        "external binding hash matches output manifest",
        checks,
    )
    return {
        "status": "PASS",
        "check_count": len(checks),
        "selected_method_id": selected,
        "bootstrap_recomputed": recompute_bootstrap,
    }


def main() -> int:
    print(json.dumps(validate_outputs(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
