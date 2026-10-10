"""Agreement utilities for completed human-validation ratings; never fabricates ratings."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_V2 = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v2"


def exact_agreement(left: Iterable[int], right: Iterable[int]) -> float:
    pairs = list(zip(left, right))
    return sum(a == b for a, b in pairs) / len(pairs) if pairs else math.nan


def adjacent_agreement(left: Iterable[int], right: Iterable[int]) -> float:
    pairs = list(zip(left, right))
    return sum(abs(a - b) <= 1 for a, b in pairs) / len(pairs) if pairs else math.nan


def spearman_correlation(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Spearman correlation requires equal lists with at least two ratings")
    from scipy.stats import spearmanr
    return float(spearmanr(left, right).statistic)


def weighted_cohens_kappa(left: list[int], right: list[int], minimum: int = 1, maximum: int = 5) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Weighted kappa requires non-empty equal-length ratings")
    categories = list(range(minimum, maximum + 1))
    observed = {(a, b): 0 for a in categories for b in categories}
    left_counts = {a: 0 for a in categories}
    right_counts = {b: 0 for b in categories}
    for a, b in zip(left, right):
        observed[(a, b)] += 1
        left_counts[a] += 1
        right_counts[b] += 1
    denominator = (maximum - minimum) ** 2
    observed_disagreement = sum(((a - b) ** 2 / denominator) * count for (a, b), count in observed.items()) / len(left)
    expected_disagreement = sum(
        ((a - b) ** 2 / denominator) * (left_counts[a] / len(left)) * (right_counts[b] / len(left))
        for a in categories for b in categories
    )
    return 1 - observed_disagreement / expected_disagreement if expected_disagreement else 1.0


def icc_two_way_absolute(ratings_by_target: list[list[float]]) -> float:
    """ICC(A,1) for two or more human raters using a two-way random model."""
    if len(ratings_by_target) < 2 or not ratings_by_target or len(ratings_by_target[0]) < 2:
        raise ValueError("ICC requires at least two targets and two raters")
    raters = len(ratings_by_target[0])
    if any(len(row) != raters for row in ratings_by_target):
        raise ValueError("Every target must have the same raters")
    targets = len(ratings_by_target)
    grand = statistics.fmean(value for row in ratings_by_target for value in row)
    target_means = [statistics.fmean(row) for row in ratings_by_target]
    rater_means = [statistics.fmean(row[index] for row in ratings_by_target) for index in range(raters)]
    ms_targets = raters * sum((value - grand) ** 2 for value in target_means) / (targets - 1)
    ms_raters = targets * sum((value - grand) ** 2 for value in rater_means) / (raters - 1)
    residual = sum(
        (ratings_by_target[i][j] - target_means[i] - rater_means[j] + grand) ** 2
        for i in range(targets) for j in range(raters)
    )
    ms_error = residual / ((targets - 1) * (raters - 1))
    denominator = ms_targets + (raters - 1) * ms_error + raters * (ms_raters - ms_error) / targets
    return (ms_targets - ms_error) / denominator if denominator else math.nan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyse completed human/LLM agreement files.")
    parser.add_argument("--ratings", type=Path, required=True)
    parser.add_argument("--answer-key", type=Path, required=True)
    parser.add_argument("--llm-quality", type=Path, default=BASE_V2 / "unified_quality_judge_v1_1.jsonl")
    parser.add_argument("--output-csv", type=Path, default=BASE_V2 / "human_validation_v1" / "agreement_results_v1_1.csv")
    parser.add_argument("--output-json", type=Path, default=BASE_V2 / "human_validation_v1" / "agreement_results_v1_1.json")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _parse_rating(value: str) -> int | None:
    value = str(value or "").strip()
    if not value:
        return None
    if not value.isdigit() or not 1 <= int(value) <= 5:
        raise ValueError(f"Rating must be an integer 1-5, got {value!r}")
    return int(value)


def safe_spearman(left: list[int], right: list[int]) -> tuple[float | None, str]:
    if len(left) < 3:
        return None, "insufficient_sample"
    if len(set(left)) == 1 or len(set(right)) == 1:
        return None, "constant_scores"
    return spearman_correlation(left, right), "ok"


def analyse_files(ratings: list[dict[str, str]], answer_key: list[dict[str, str]], llm_rows: list[dict]) -> dict:
    key = {row["anonymous_response_id"]: row for row in answer_key}
    llm = {(str(row.get("scenario_id", "")), str(row.get("mode", ""))): row for row in llm_rows}
    joined: list[dict] = []
    warnings: list[str] = []
    for row in ratings:
        anonymous_id = row.get("anonymous_response_id", "")
        dimension = row.get("dimension", "")
        if anonymous_id not in key:
            warnings.append(f"Missing answer-key row for {anonymous_id}")
            continue
        identity = key[anonymous_id]
        llm_row = llm.get((identity.get("scenario_id", ""), identity.get("mode", "")))
        if not llm_row:
            warnings.append(f"Missing LLM score for {anonymous_id}")
            continue
        human_1 = _parse_rating(row.get("human_score_1_to_5") or row.get("human_rater_1") or "")
        human_2 = _parse_rating(row.get("human_rater_2", ""))
        llm_score = (llm_row.get("scores") or {}).get(dimension)
        if human_1 is None:
            warnings.append(f"Missing primary human rating for {anonymous_id}/{dimension}")
            continue
        if isinstance(llm_score, bool) or type(llm_score) is not int:
            warnings.append(f"Missing/invalid LLM score for {anonymous_id}/{dimension}")
            continue
        joined.append({"dimension": dimension, "human_1": human_1, "human_2": human_2, "llm": llm_score})
    results: list[dict] = []
    for dimension in sorted({row["dimension"] for row in joined}):
        subset = [row for row in joined if row["dimension"] == dimension]
        human_1 = [row["human_1"] for row in subset]
        llm_scores = [row["llm"] for row in subset]
        rho, rho_status = safe_spearman(human_1, llm_scores)
        second = [row for row in subset if row["human_2"] is not None]
        h1_second = [row["human_1"] for row in second]
        h2 = [row["human_2"] for row in second]
        icc = None
        icc_status = "not_available"
        if len(second) >= 2:
            try:
                icc = icc_two_way_absolute([[row["human_1"], row["human_2"]] for row in second])
                icc_status = "ok" if not math.isnan(icc) else "undefined"
            except ValueError as exc:
                icc_status = str(exc)
        results.append({
            "dimension": dimension,
            "n_human_llm": len(subset),
            "spearman_human_llm": rho,
            "spearman_status": rho_status,
            "weighted_kappa_human_llm": weighted_cohens_kappa(human_1, llm_scores) if subset else None,
            "exact_agreement_human_llm": exact_agreement(human_1, llm_scores),
            "adjacent_agreement_human_llm": adjacent_agreement(human_1, llm_scores),
            "n_human_human": len(second),
            "weighted_kappa_human_human": weighted_cohens_kappa(h1_second, h2) if second else None,
            "exact_agreement_human_human": exact_agreement(h1_second, h2) if second else None,
            "adjacent_agreement_human_human": adjacent_agreement(h1_second, h2) if second else None,
            "icc_human_human": icc,
            "icc_status": icc_status,
        })
    return {"results": results, "warnings": warnings, "joined_rating_count": len(joined)}


def main() -> None:
    args = parse_args()
    paths = [path if path.is_absolute() else PROJECT_ROOT / path for path in (args.ratings, args.answer_key, args.llm_quality, args.output_csv, args.output_json)]
    ratings_path, key_path, llm_path, output_csv, output_json = paths
    if not args.overwrite and (output_csv.exists() or output_json.exists()):
        raise SystemExit("Agreement output exists; use --overwrite to replace versioned agreement results.")
    report = analyse_files(_read_csv(ratings_path), _read_csv(key_path), _read_jsonl(llm_path))
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = report["results"]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["dimension"])
        writer.writeheader()
        writer.writerows(rows)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Agreement analysis saved: {len(rows)} dimensions; warnings={len(report['warnings'])}")


if __name__ == "__main__":
    main()
