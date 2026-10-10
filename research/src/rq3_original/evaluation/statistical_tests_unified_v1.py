"""Predefined paired tests with Wilcoxon primary, sign robustness, and Holm correction."""

from __future__ import annotations

import argparse
import csv
import json
import math
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
    MECHANISM_RUBRIC_VERSION_V2,
    EvaluationValidationError,
    load_jsonl,
)


BASE_V1 = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1"
BASE_V2 = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v2"
CONFIG = PROJECT_ROOT / "evaluation" / "unified_primary_comparisons.json"
QUALITY_INPUT = BASE_V2 / "unified_quality_judge_v1_1.jsonl"
MECHANISM_INPUT = BASE_V1 / "unified_mechanism_scores_v2.jsonl"
STATISTICS_CSV = BASE_V2 / "unified_primary_statistics_v2.csv"
STATISTICS_JSON = BASE_V2 / "unified_primary_statistics_v2.json"
STATISTICS_MARKDOWN = BASE_V2 / "unified_primary_statistics_v2.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run predefined unified paired tests.")
    parser.add_argument("--quality", type=Path, default=QUALITY_INPUT)
    parser.add_argument("--mechanism", type=Path, default=MECHANISM_INPUT)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, default=STATISTICS_CSV)
    parser.add_argument("--json-output", type=Path, default=STATISTICS_JSON)
    parser.add_argument("--markdown-output", type=Path, default=STATISTICS_MARKDOWN)
    return parser.parse_args()


def sign_test_p_value(differences: list[float]) -> float | None:
    wins = sum(value > 0 for value in differences)
    losses = sum(value < 0 for value in differences)
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)


def wilcoxon_p_value(differences: list[float]) -> float | None:
    if not differences or all(value == 0 for value in differences):
        return 1.0
    if sum(value != 0 for value in differences) < 2:
        return None
    try:
        from scipy.stats import wilcoxon
        return float(wilcoxon(differences, zero_method="pratt", alternative="two-sided").pvalue)
    except Exception:
        return None


def matched_rank_biserial(differences: list[float]) -> float | None:
    nonzero = [(abs(value), 1 if value > 0 else -1) for value in differences if value != 0]
    if not nonzero:
        return 0.0
    ordered = sorted(nonzero)
    ranks: list[tuple[float, int]] = []
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2
        ranks.extend((average_rank, sign) for _, sign in ordered[index:end])
        index = end
    positive = sum(rank for rank, sign in ranks if sign > 0)
    negative = sum(rank for rank, sign in ranks if sign < 0)
    total = positive + negative
    return round((positive - negative) / total, 4) if total else 0.0


def cohens_dz_all(differences: list[float]) -> float | None:
    if len(differences) < 2:
        return None
    standard_deviation = statistics.stdev(differences)
    return round(statistics.fmean(differences) / standard_deviation, 4) if standard_deviation else 0.0


def holm_adjust(p_values: list[float | None]) -> list[float | None]:
    valid = sorted(((value, index) for index, value in enumerate(p_values) if value is not None), key=lambda item: item[0])
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    count = len(valid)
    for rank, (value, original_index) in enumerate(valid):
        running = max(running, min(1.0, value * (count - rank)))
        adjusted[original_index] = running
    return adjusted


def index_scores(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        key = (str(row.get("scenario_id", "")), str(row.get("mode", "")))
        if key in out:
            raise EvaluationValidationError("duplicate_pair", str(key))
        if row.get("judge_failed"):
            raise EvaluationValidationError("failed_record", str(key))
        out[key] = row
    return out


def validate_statistical_inputs(
    quality: list[dict[str, Any]], mechanism: list[dict[str, Any]],
    expected_count: int = EXPECTED_RECORD_COUNT,
) -> None:
    quality_index = index_scores(quality)
    mechanism_index = index_scores(mechanism)
    if len(quality_index) != expected_count or len(mechanism_index) != expected_count:
        raise EvaluationValidationError(
            "incomplete_statistical_inputs",
            f"Expected {expected_count} quality and mechanism records; got {len(quality_index)} and {len(mechanism_index)}",
        )
    if set(quality_index) != set(mechanism_index):
        missing_quality = sorted(set(mechanism_index) - set(quality_index))
        missing_mechanism = sorted(set(quality_index) - set(mechanism_index))
        raise EvaluationValidationError(
            "missing_paired_observations",
            f"missing_quality={missing_quality[:5]}; missing_mechanism={missing_mechanism[:5]}",
        )
    expected_per_mode = expected_count // len(EXPECTED_MODES)
    for label, index in (("quality", quality_index), ("mechanism", mechanism_index)):
        counts = {mode: sum(key[1] == mode for key in index) for mode in EXPECTED_MODES}
        if set(key[1] for key in index) != set(EXPECTED_MODES) or any(count != expected_per_mode for count in counts.values()):
            raise EvaluationValidationError("mode_count_mismatch", f"{label}: {counts}")
        scenario_modes: dict[str, set[str]] = {}
        for scenario_id, mode in index:
            scenario_modes.setdefault(scenario_id, set()).add(mode)
        if len(scenario_modes) != expected_per_mode or any(modes != set(EXPECTED_MODES) for modes in scenario_modes.values()):
            raise EvaluationValidationError(
                "missing_paired_observations", f"{label} does not contain every scenario in all six modes",
            )
    versions = {str(row.get("mechanism_rubric_version", "")) for row in mechanism}
    if versions != {MECHANISM_RUBRIC_VERSION_V2}:
        raise EvaluationValidationError(
            "mechanism_v2_required", f"Statistics require {MECHANISM_RUBRIC_VERSION_V2}; got {sorted(versions)}",
        )
    quality_hashes = {str(row.get("responses_file_sha256", "")) for row in quality}
    mechanism_hashes = {str(row.get("responses_file_sha256", "")) for row in mechanism}
    if quality_hashes != {FROZEN_RESPONSES_SHA256} or mechanism_hashes != {FROZEN_RESPONSES_SHA256}:
        raise EvaluationValidationError(
            "response_hash_mismatch",
            f"Quality/mechanism must reference the same frozen response hash; quality={sorted(quality_hashes)}, mechanism={sorted(mechanism_hashes)}",
        )


def run_predefined_tests(quality: list[dict[str, Any]], mechanism: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    indexes = {"quality": index_scores(quality), "mechanism": index_scores(mechanism)}
    results: list[dict[str, Any]] = []
    for test in config.get("tests", []):
        layer = str(test["score_layer"])
        index = indexes[layer]
        groups = set(test["scenario_groups"])
        scenario_ids = sorted({scenario_id for (scenario_id, _), row in index.items() if row.get("scenario_group") in groups})
        for dimension in test["dimensions"]:
            differences: list[float] = []
            for scenario_id in scenario_ids:
                left_key, right_key = (scenario_id, test["mode_1"]), (scenario_id, test["mode_2"])
                if left_key not in index or right_key not in index:
                    raise EvaluationValidationError("missing_pair", f"{test['test_id']} {scenario_id}")
                left = index[left_key].get("scores", {}).get(dimension)
                right = index[right_key].get("scores", {}).get(dimension)
                if (left is None) != (right is None):
                    raise EvaluationValidationError("unequal_mode_coverage", f"{test['test_id']} {scenario_id} {dimension}")
                if left is not None:
                    differences.append(float(right) - float(left))
            if not differences:
                raise EvaluationValidationError("no_applicable_pairs", f"{test['test_id']} {dimension}")
            results.append({
                "test_id": test["test_id"], "family": test["family"], "status": test["status"],
                "score_layer": layer, "mode_1": test["mode_1"], "mode_2": test["mode_2"],
                "dimension": dimension, "n_paired": len(differences),
                "mode_2_wins": sum(value > 0 for value in differences),
                "ties": sum(value == 0 for value in differences),
                "mode_1_wins": sum(value < 0 for value in differences),
                "median_difference_mode2_minus_mode1": statistics.median(differences),
                "wilcoxon_raw_p": wilcoxon_p_value(differences),
                "sign_test_raw_p": sign_test_p_value(differences),
                "matched_rank_biserial": matched_rank_biserial(differences),
                "cohens_dz_secondary": cohens_dz_all(differences),
            })
    for family in sorted({row["family"] for row in results}):
        positions = [index for index, row in enumerate(results) if row["family"] == family]
        for source, target in (("wilcoxon_raw_p", "wilcoxon_holm_p"), ("sign_test_raw_p", "sign_test_holm_p")):
            adjusted = holm_adjust([results[index][source] for index in positions])
            for position, value in zip(positions, adjusted):
                results[position][target] = value
        for position in positions:
            row = results[position]
            row["significant_primary"] = bool(row["status"] == "primary" and row.get("wilcoxon_holm_p") is not None and row["wilcoxon_holm_p"] < config.get("alpha", 0.05))
    return results


def main() -> None:
    args = parse_args()
    quality_path, mechanism_path, config_path, output, json_output, markdown_output = [
        path if path.is_absolute() else PROJECT_ROOT / path
        for path in (args.quality, args.mechanism, args.config, args.output, args.json_output, args.markdown_output)
    ]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    quality = load_jsonl(quality_path)
    mechanism = load_jsonl(mechanism_path)
    validate_statistical_inputs(quality, mechanism)
    rows = run_predefined_tests(quality, mechanism, config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "mechanism_rubric_version": MECHANISM_RUBRIC_VERSION_V2,
        "responses_file_sha256": FROZEN_RESPONSES_SHA256,
        "statistical_policy": {
            "primary": "paired Wilcoxon signed-rank",
            "robustness": "exact sign test",
            "multiplicity": "Holm correction within families",
            "effect_sizes": ["matched rank-biserial correlation", "Cohen's dz including zero differences"],
        },
        "results": rows,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Unified primary statistics v2", "",
        f"- Mechanism rubric: `{MECHANISM_RUBRIC_VERSION_V2}`",
        f"- Frozen response SHA-256: `{FROZEN_RESPONSES_SHA256}`", "",
        "| Test | Layer | Modes | Dimension | n | Wins / ties / losses | Wilcoxon Holm p | Sign Holm p |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['test_id']} | {row['score_layer']} | {row['mode_1']} vs {row['mode_2']} | "
            f"{row['dimension']} | {row['n_paired']} | {row['mode_2_wins']} / {row['ties']} / {row['mode_1_wins']} | "
            f"{row.get('wilcoxon_holm_p')} | {row.get('sign_test_holm_p')} |"
        )
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} predefined paired tests to {output}")


if __name__ == "__main__":
    main()
