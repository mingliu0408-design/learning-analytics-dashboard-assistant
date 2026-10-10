"""Separate conservative quality and mechanism summaries for unified evaluation."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.unified_evaluation_contract import (  # noqa: E402
    EXPECTED_MODES,
    EXPECTED_RECORD_COUNT,
    FROZEN_RESPONSES_SHA256,
    MECHANISM_DIMENSIONS,
    MECHANISM_RUBRIC_VERSION,
    MECHANISM_RUBRIC_VERSION_V2,
    QUALITY_DIMENSIONS,
    EvaluationValidationError,
    load_jsonl,
)


BASE_V1 = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1"
BASE_V2 = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v2"
QUALITY_INPUT = BASE_V2 / "unified_quality_judge_v1_1.jsonl"
MECHANISM_INPUT = BASE_V1 / "unified_mechanism_scores_v2.jsonl"
SUMMARY_OUTPUT_DIR = BASE_V2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise quality and mechanism scores separately.")
    parser.add_argument("--quality", type=Path, default=QUALITY_INPUT)
    parser.add_argument("--mechanism", type=Path, default=MECHANISM_INPUT)
    parser.add_argument("--output-dir", type=Path, default=SUMMARY_OUTPUT_DIR)
    parser.add_argument(
        "--legacy-analysis",
        action="store_true",
        help="Explicitly allow frozen legacy mechanism-v1 input for historical analysis only.",
    )
    return parser.parse_args()


def validate_complete(
    records: list[dict[str, Any]], label: str, dimensions: list[str],
    expected_count: int = EXPECTED_RECORD_COUNT,
) -> None:
    keys = [(str(row.get("scenario_id", "")), str(row.get("mode", ""))) for row in records]
    if len(keys) != len(set(keys)):
        raise EvaluationValidationError("duplicate_keys", f"{label} contains duplicate keys")
    if len(keys) != expected_count:
        raise EvaluationValidationError("incomplete_records", f"{label}: expected {expected_count}, got {len(keys)}")
    if set(mode for _, mode in keys) != set(EXPECTED_MODES):
        raise EvaluationValidationError("mode_coverage", f"{label} does not contain exactly six expected modes")
    mode_counts = Counter(mode for _, mode in keys)
    if any(mode_counts[mode] != expected_count // len(EXPECTED_MODES) for mode in EXPECTED_MODES):
        raise EvaluationValidationError("mode_count_mismatch", f"{label}: {dict(mode_counts)}")
    scenario_modes: dict[str, set[str]] = {}
    for scenario_id, mode in keys:
        scenario_modes.setdefault(scenario_id, set()).add(mode)
    if any(modes != set(EXPECTED_MODES) for modes in scenario_modes.values()):
        raise EvaluationValidationError("missing_scenario_mode_pairs", f"{label} lacks complete six-mode scenarios")
    if any(row.get("judge_failed") for row in records):
        raise EvaluationValidationError("failed_records", f"{label} contains failed records")
    for row in records:
        scores = row.get("scores")
        applicable = set(row.get("applicable_dimensions") or [])
        if not isinstance(scores, dict) or set(scores) != set(dimensions):
            raise EvaluationValidationError("incomplete_score_schema", f"{label} has incomplete scores")
        for dimension in dimensions:
            if (dimension in applicable) != (scores.get(dimension) is not None):
                raise EvaluationValidationError("invalid_applicability_payload", f"{label}: {dimension}")


def validate_mechanism_provenance(records: list[dict[str, Any]], legacy_analysis: bool = False) -> None:
    versions = {str(row.get("mechanism_rubric_version", "")) for row in records}
    if versions != {MECHANISM_RUBRIC_VERSION_V2}:
        if not legacy_analysis or versions != {MECHANISM_RUBRIC_VERSION}:
            raise EvaluationValidationError(
                "mechanism_v2_required",
                f"Mechanism summary requires {MECHANISM_RUBRIC_VERSION_V2}; got {sorted(versions)}. "
                "Use --legacy-analysis only for explicit historical v1 analysis.",
            )
    hashes = {str(row.get("responses_file_sha256", "")) for row in records}
    if hashes != {FROZEN_RESPONSES_SHA256}:
        raise EvaluationValidationError(
            "frozen_response_hash_mismatch",
            f"Mechanism records must reference {FROZEN_RESPONSES_SHA256}; got {sorted(hashes)}",
        )


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def summarise_layer(records: list[dict[str, Any]], dimensions: list[str], overall_field: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mode_rows: list[dict[str, Any]] = []
    dimension_rows: list[dict[str, Any]] = []
    for mode in EXPECTED_MODES:
        subset = [row for row in records if row.get("mode") == mode]
        overall = [float(row[overall_field]) for row in subset if row.get(overall_field) is not None]
        group_means: list[float] = []
        groups = sorted({str(row.get("scenario_group", "")) for row in subset})
        for group in groups:
            values = [float(row[overall_field]) for row in subset if row.get("scenario_group") == group and row.get(overall_field) is not None]
            if values:
                group_means.append(statistics.fmean(values))
        mode_rows.append({
            "mode": mode,
            "micro_score": mean(overall),
            "group_macro_score": mean(group_means),
            "n_applicable_responses": len(overall),
            "n_scenario_groups": len(group_means),
        })
        for dimension in dimensions:
            values = [float(row.get("scores", {}).get(dimension)) for row in subset if row.get("scores", {}).get(dimension) is not None]
            dimension_rows.append({"mode": mode, "dimension": dimension, "mean": mean(values), "n_applicable": len(values)})
    return mode_rows, dimension_rows


def summarise_scenario_groups(
    records: list[dict[str, Any]], overall_field: str, score_layer: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode in EXPECTED_MODES:
        subset = [row for row in records if row.get("mode") == mode]
        for group in sorted({str(row.get("scenario_group", "")) for row in subset}):
            values = [
                float(row[overall_field]) for row in subset
                if row.get("scenario_group") == group and row.get(overall_field) is not None
            ]
            rows.append({
                "score_layer": score_layer,
                "mode": mode,
                "scenario_group": group,
                "mean": mean(values),
                "n_applicable": len(values),
            })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    quality_path, mechanism_path, output_dir = [path if path.is_absolute() else PROJECT_ROOT / path for path in (args.quality, args.mechanism, args.output_dir)]
    quality, mechanism = load_jsonl(quality_path), load_jsonl(mechanism_path)
    validate_complete(quality, "quality", QUALITY_DIMENSIONS)
    validate_complete(mechanism, "mechanism", MECHANISM_DIMENSIONS)
    validate_mechanism_provenance(mechanism, legacy_analysis=args.legacy_analysis)
    if args.legacy_analysis:
        print("WARNING: explicit legacy mechanism analysis enabled; formal summaries require mechanism v2.")
    quality_modes, quality_dims = summarise_layer(quality, QUALITY_DIMENSIONS, "quality_score")
    mechanism_modes, mechanism_dims = summarise_layer(mechanism, MECHANISM_DIMENSIONS, "mechanism_score")
    group_rows = (
        summarise_scenario_groups(quality, "quality_score", "quality")
        + summarise_scenario_groups(mechanism, "mechanism_score", "mechanism")
    )
    suffix = "legacy_v1" if args.legacy_analysis else "v2"
    write_csv(output_dir / f"quality_summary_by_mode_{suffix}.csv", quality_modes)
    write_csv(output_dir / f"quality_dimensions_{suffix}.csv", quality_dims)
    write_csv(output_dir / f"mechanism_summary_by_mode_{suffix}.csv", mechanism_modes)
    write_csv(output_dir / f"mechanism_dimensions_{suffix}.csv", mechanism_dims)
    write_csv(output_dir / f"scenario_group_macro_summary_{suffix}.csv", group_rows)
    summary = {
        "quality": quality_modes,
        "mechanism": mechanism_modes,
        "mechanism_rubric_version": next(iter({row.get("mechanism_rubric_version") for row in mechanism})),
        "combined_score_calculated": False,
    }
    (output_dir / f"unified_separate_summary_{suffix}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8",
    )
    print("Saved separate quality/mechanism micro and group-macro summaries; no combined score was calculated.")


if __name__ == "__main__":
    main()
