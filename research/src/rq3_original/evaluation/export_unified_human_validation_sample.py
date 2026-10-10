"""Export a six-mode blind, stratified human-validation package."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import random
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.unified_evaluation_contract import (  # noqa: E402
    EXPECTED_MODES,
    GOLD_LABELS_PATH,
    QUALITY_DIMENSIONS,
    REFERENCE_EVIDENCE_PATH,
    load_gold_overlay,
    load_jsonl,
    rows_by_id,
)


RESPONSES = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_llm_responses_v1.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "human_validation_v1"
CATEGORY_GROUPS = {
    "dashboard_interpretation": {"dashboard_interpretation", "cross_page_evidence_synthesis", "metric_clarification", "technical_access_or_discrepancy"},
    "recommendation_planning": {"recommendation_planning"},
    "memory": {"memory_follow_up"},
    "retrieval": {"course_material_retrieval"},
    "negative_control": {"negative_control"},
    "hybrid": {"hybrid_memory_and_retrieval", "hybrid_evidence_and_retrieval"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export blind human-validation sample for all six modes.")
    parser.add_argument("--responses", type=Path, default=RESPONSES)
    parser.add_argument("--gold-labels", type=Path, default=GOLD_LABELS_PATH)
    parser.add_argument("--reference-evidence", type=Path, default=REFERENCE_EVIDENCE_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sample-scenarios", type=int, choices=[8, 12], default=12)
    parser.add_argument("--seed", type=int, default=20260712)
    return parser.parse_args()


def validate_six_mode_coverage(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        grouped.setdefault(str(row.get("scenario_id", "")), []).append(row)
    for scenario_id, rows in grouped.items():
        modes = [str(row.get("mode", "")) for row in rows]
        if len(modes) != len(set(modes)) or set(modes) != set(EXPECTED_MODES):
            raise ValueError(f"{scenario_id} does not have exactly one response for each of six modes")
    return grouped


def select_stratified_scenarios(
    grouped: Mapping[str, list[dict[str, Any]]], gold: Mapping[str, Mapping[str, Any]], count: int, seed: int,
) -> list[str]:
    rng = random.Random(seed)
    pools: dict[str, list[str]] = {}
    for category, groups in CATEGORY_GROUPS.items():
        pools[category] = sorted(
            scenario_id for scenario_id in grouped
            if gold.get(scenario_id, {}).get("gold_scenario_group") in groups
        )
        rng.shuffle(pools[category])
        if not pools[category]:
            raise ValueError(f"No scenarios available for stratum {category}")
    selected = [pools[category].pop() for category in CATEGORY_GROUPS]
    remaining = sorted(set(grouped) - set(selected))
    rng.shuffle(remaining)
    selected.extend(remaining[: count - len(selected)])
    return selected[:count]


def build_blind_package(
    records: list[dict[str, Any]], gold: Mapping[str, Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]], scenario_count: int, seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    grouped = validate_six_mode_coverage(records)
    selected = select_stratified_scenarios(grouped, gold, scenario_count, seed)
    annotator_rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for case_number, scenario_id in enumerate(selected, start=1):
        case_id = f"CASE-{case_number:02d}"
        shuffled = list(grouped[scenario_id])
        random.Random(seed + case_number).shuffle(shuffled)
        for response_number, record in enumerate(shuffled, start=1):
            anonymous_id = f"{case_id}-R{response_number}"
            label = gold[scenario_id]
            reference = references[scenario_id]
            common = {
                "case_id": case_id,
                "anonymous_response_id": anonymous_id,
                "current_page": reference.get("reference_page", ""),
                "student_query": reference.get("reference_student_query", ""),
                "conversation_history": json.dumps(reference.get("reference_conversation_history", []), ensure_ascii=False),
                "reference_dashboard_evidence": json.dumps(reference.get("reference_dashboard_evidence", {}), ensure_ascii=False, sort_keys=True),
                "reference_course_evidence": json.dumps(reference.get("reference_course_evidence", []), ensure_ascii=False, sort_keys=True),
                "reference_source_restrictions": json.dumps(reference.get("reference_source_restrictions", {}), ensure_ascii=False, sort_keys=True),
                "assistant_response": record.get("response") or record.get("generated_response", ""),
            }
            for dimension in label.get("gold_applicable_quality_dimensions", []):
                annotator_rows.append({**common, "dimension": dimension, "human_score_1_to_5": "", "human_rationale": ""})
            key_rows.append({
                "anonymous_response_id": anonymous_id,
                "case_id": case_id,
                "scenario_id": scenario_id,
                "mode": record.get("mode", ""),
                "scenario_group": label.get("gold_scenario_group", ""),
            })
    return annotator_rows, key_rows, selected


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, annotator_rows: list[dict[str, Any]]) -> None:
    import pandas as pd
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(annotator_rows).to_excel(writer, index=False, sheet_name="Ratings")


def write_instructions(path: Path, scenario_count: int, seed: int) -> None:
    path.write_text(
        "# Human Validation Instructions\n\n"
        f"This blind package contains {scenario_count} scenarios × 6 anonymous responses. Shuffle seed: `{seed}`.\n\n"
        "Score only the listed dimension for each row. Use integer scores 1–5. Higher is better except "
        "`unsupported_claims_risk`, where 1 is low risk and 5 is high risk. Cite a specific response passage "
        "in the rationale. Do not open the separate answer key until annotation is complete.\n\n"
        "Scores are ordinal. Do not infer mode or internal mechanisms from writing style.\n",
        encoding="utf-8",
    )


def export_package(
    records: list[dict[str, Any]], gold: Mapping[str, Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]], output_dir: Path, scenario_count: int, seed: int,
) -> dict[str, Any]:
    annotator, key, selected = build_blind_package(records, gold, references, scenario_count, seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "annotator_sample_v1.csv", annotator)
    write_xlsx(output_dir / "annotator_sample_v1.xlsx", annotator)
    write_csv(output_dir / "answer_key_v1.csv", key)
    (output_dir / "answer_key_v1.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_instructions(output_dir / "annotation_instructions_v1.md", scenario_count, seed)
    agreement_rows = [
        {"anonymous_response_id": row["anonymous_response_id"], "dimension": dimension, "llm_score": "", "human_rater_1": "", "human_rater_2": ""}
        for row in key for dimension in gold[row["scenario_id"]].get("gold_applicable_quality_dimensions", [])
    ]
    write_csv(output_dir / "agreement_analysis_template_v1.csv", agreement_rows)
    return {"selected_scenarios": selected, "response_count": len(key), "annotation_row_count": len(annotator)}


def main() -> None:
    args = parse_args()
    responses, gold_path, reference_path, output_dir = [
        path if path.is_absolute() else PROJECT_ROOT / path
        for path in (args.responses, args.gold_labels, args.reference_evidence, args.output_dir)
    ]
    report = export_package(
        load_jsonl(responses), load_gold_overlay(gold_path), rows_by_id(load_jsonl(reference_path)),
        output_dir, args.sample_scenarios, args.seed,
    )
    print(f"Exported {report['response_count']} blind responses from {len(report['selected_scenarios'])} scenarios to {output_dir}")


if __name__ == "__main__":
    main()
