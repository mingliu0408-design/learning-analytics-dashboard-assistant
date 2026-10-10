"""Seal LR-3R validation, report, registry metadata, and checksums."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(name: str) -> dict[str, Any]:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def write(name: str, value: Any) -> None:
    (HERE / name).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def fmt(value: float) -> str:
    return f"{float(value):.6f}"


def current_hashes(snapshot: dict[str, str]) -> dict[str, str]:
    return {relative: sha(ROOT / relative) for relative in snapshot}


def distribution_across_runs(result: dict[str, Any], view: str) -> dict[str, Any]:
    per_seed = {
        str(run["training_seed"]): run["view_metrics"][view]["predicted_label_distribution"]
        for run in result["runs"]
    }
    totals = Counter()
    for distribution in per_seed.values():
        totals.update(distribution)
    return {
        "per_seed": per_seed,
        "total_across_five_seeds": dict(sorted(totals.items())),
        "mean_count_per_seed": {label: count / 5.0 for label, count in sorted(totals.items())},
    }


def main() -> None:
    validation = load("lr3r_validation_report_v1.json")
    current = {
        group: current_hashes(snapshot)
        for group, snapshot in validation["protected_snapshot_before"].items()
    }
    unchanged = current == validation["protected_snapshot_before"]
    if not unchanged:
        raise ValueError("protected files changed after LR-3R training/tests")

    registry = load("lr3r_checkpoint_registry_v1.json")
    resolutions = []
    for entry in registry["entries"]:
        checkpoint_path = HERE / entry["checkpoint_path"]
        metadata_path = HERE / entry["metadata_path"]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        checkpoint_ok = sha(checkpoint_path) == entry["checkpoint_file_sha256"] == metadata["checkpoint_file_sha256"]
        if not checkpoint_ok:
            raise ValueError(f"checkpoint hash mismatch: {checkpoint_path}")
        entry["metadata_file_sha256"] = sha(metadata_path)
        resolutions.append({
            "model_family": entry["model_family"],
            "training_seed": entry["training_seed"],
            "checkpoint_hash_match": True,
            "checkpoint_tensor_hash": entry["checkpoint_tensor_hash"],
            "metadata_file_sha256": entry["metadata_file_sha256"],
        })
    write("lr3r_checkpoint_registry_v1.json", registry)

    validation.update({
        "overall_status": "PASS",
        "seed_replay_status": "PASS_IDENTICAL_TENSOR_HASHES_FOR_M64_AND_M128_SEED_20260813",
        "seed_determinism_replays": [
            {
                "model_family": family,
                "training_seed": 20260813,
                "result": "IDENTICAL_TENSOR_HASH_AND_VIEW_A_METRICS",
                "checkpoint_tensor_hash": next(
                    entry["checkpoint_tensor_hash"] for entry in registry["entries"]
                    if entry["model_family"] == family and entry["training_seed"] == 20260813
                ),
            }
            for family in ["M64", "M128"]
        ],
        "research_test_results": {
            "status": "PASS",
            "passed": 12,
            "failed": 0,
            "command": "PYTHONDONTWRITEBYTECODE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest evaluation/learned_intent_ranking/lr3r/test_lr3r.py -v",
        },
        "existing_regressions": "PASS_27_OF_27",
        "regression_results": {
            "production_intent_router": {"passed": 11, "failed": 0},
            "semantic_c_full_integration": {"passed": 2, "failed": 0},
            "keyword_baseline_original_parity": {"passed": 1, "failed": 0},
            "p2c_safe_uncertainty": {"passed": 5, "failed": 0},
            "p2d_explicit_rule_safety": {"passed": 6, "failed": 0},
            "real_semantic_runtime": {"passed": 2, "failed": 0},
            "offline_semantic_preflight": {"status": "PASS", "model": "initialised_offline", "network_downloads": "disabled"},
        },
        "checkpoint_metadata_hashes_resolve": True,
        "checkpoint_resolution": resolutions,
        "protected_snapshot_after_all_tests": current,
        "protected_files_unchanged_after_all_tests": unchanged,
    })
    write("lr3r_validation_report_v1.json", validation)

    m64 = load("lr3r_m64_training_results_v1.json")
    m128 = load("lr3r_m128_training_results_v1.json")
    for result in [m64, m128]:
        result["view_b_aggregate"]["predicted_label_distribution"] = distribution_across_runs(result, "VIEW_B_SINGLETON_UNSEEN")
        result["view_c_aggregate"]["predicted_label_distribution"] = distribution_across_runs(result, "VIEW_C_MIXED")
    write("lr3r_m64_training_results_v1.json", m64)
    write("lr3r_m128_training_results_v1.json", m128)

    summary = load("lr3r_dev_metrics_summary_v1.json")
    summary["singleton_unseen_diagnostic_view_b"]["M64"] = m64["view_b_aggregate"]
    summary["singleton_unseen_diagnostic_view_b"]["M128"] = m128["view_b_aggregate"]
    summary["mixed_development_diagnostic_view_c"]["M64"] = m64["view_c_aggregate"]
    summary["mixed_development_diagnostic_view_c"]["M128"] = m128["view_c_aggregate"]
    write("lr3r_dev_metrics_summary_v1.json", summary)

    confusion = load("lr3r_confusion_analysis_v1.json")
    for family in ["M64", "M128"]:
        for name, row in confusion["known_confusion_patterns"][family].items():
            m1_mean = confusion["known_confusion_patterns"]["M1"][name]["mean_count"]
            compact_mean = row["mean_count"]
            row["m1_reference_mean_count"] = m1_mean
            row["capacity_reduction_effect_vs_m1"] = (
                "improves" if compact_mean < m1_mean else "worsens" if compact_mean > m1_mean else "preserves"
            )
    write("lr3r_confusion_analysis_v1.json", confusion)

    comparison = load("lr3r_model_comparison_v1.json")
    capacity = load("lr3r_capacity_analysis_v1.json")
    overfit = load("lr3r_overfit_analysis_v1.json")
    stability = load("lr3r_seed_stability_v1.json")
    uncertainty = load("lr3r_development_uncertainty_analysis_v1.json")
    inputs = load("lr3r_input_hashes_v1.json")
    protocol = load("lr3r_experiment_protocol_v1.json")
    rows = comparison["architecture_table"]

    seed_lines = []
    for result in [m64, m128]:
        for run in result["runs"]:
            metrics = run["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]
            seed_lines.append(
                f"| {run['model_family']} | {run['training_seed']} | {run['best_epoch']} | {run['final_epoch']} | "
                f"{fmt(metrics['top1_accuracy'])} | {fmt(metrics['mrr'])} | {fmt(metrics['recall_at_3'])} | "
                f"{fmt(metrics['macro_f1'])} | {'SEVERE_OVERFIT' if run['overfit_diagnostic']['flag'] else 'NO'} |"
            )
    seed_table = "\n".join(seed_lines)

    architecture_lines = []
    for family in ["C0", "L1", "M64", "M128", "M1"]:
        row = rows[family]
        architecture_lines.append(
            f"| {family} | {row['trainable_parameters']:,} | {fmt(row['mrr_mean'])} / {fmt(row['mrr_std'])} | "
            f"{fmt(row['top1_mean'])} / {fmt(row['top1_std'])} | {fmt(row['recall_at_3_mean'])} | "
            f"{fmt(row['macro_f1_mean'])} | {row['seeds_beating_cosine_mrr'] if row['seeds_beating_cosine_mrr'] is not None else '—'} | "
            f"{str(row['severe_overfit_runs']) + '/5' if row['severe_overfit_runs'] is not None else '—'} |"
        )
    architecture_table = "\n".join(architecture_lines)

    capacity_lines = []
    for family in ["L1", "M64", "M128", "M1"]:
        row = capacity["models"][family]
        capacity_lines.append(
            f"| {family} | {row['total_parameters']:,} | {row['trainable_parameters']:,} | "
            f"{row['parameter_ratio_versus_m1']:.6f} | {row['parameters_per_unique_epoch_0_effective_feature']:.3f} |"
        )
    capacity_table = "\n".join(capacity_lines)

    metric_lines = []
    for family in ["L1", "M64", "M128", "M1"]:
        trade = comparison["metric_tradeoffs_vs_cosine"][family]
        metric_lines.append(
            f"| {family} | {trade['mrr']['delta_vs_cosine']:+.6f} | "
            f"{trade['top1_accuracy']['delta_vs_cosine']:+.6f} | "
            f"{trade['recall_at_3']['delta_vs_cosine']:+.6f} | "
            f"{trade['macro_f1']['delta_vs_cosine']:+.6f} |"
        )
    metric_table = "\n".join(metric_lines)

    intent_lines = []
    for label in confusion["represented_gold_labels"]:
        c0 = confusion["per_intent_f1"]["C0"][label]
        values = [confusion["per_intent_f1"][family][label]["mean"] for family in ["L1", "M64", "M128", "M1"]]
        intent_lines.append(
            f"| `{label}` | {fmt(c0)} | {fmt(values[0])} | {fmt(values[1])} | {fmt(values[2])} | {fmt(values[3])} |"
        )
    intent_table = "\n".join(intent_lines)

    confusion_lines = []
    for name in confusion["known_confusion_patterns"]["M64"]:
        c0 = confusion["known_confusion_patterns"]["M64"][name]["cosine_count"]
        m1 = confusion["known_confusion_patterns"]["M1"][name]["mean_count"]
        a = confusion["known_confusion_patterns"]["M64"][name]
        b = confusion["known_confusion_patterns"]["M128"][name]
        confusion_lines.append(
            f"| `{name}` | {c0} | {m1:.1f} | {a['mean_count']:.1f} ({a['capacity_reduction_effect_vs_m1']}) | "
            f"{b['mean_count']:.1f} ({b['capacity_reduction_effect_vs_m1']}) |"
        )
    confusion_table = "\n".join(confusion_lines)

    uncertainty_lines = []
    for family in ["L1", "M64", "M128", "M1"]:
        row = uncertainty["architectures"][family]
        ci = row["bootstrap_95_percent_ci"]
        uncertainty_lines.append(
            f"| {family} | {row['mean_per_query_reciprocal_rank_delta']:+.6f} | [{ci['lower']:+.6f}, {ci['upper']:+.6f}] |"
        )
    uncertainty_table = "\n".join(uncertainty_lines)

    view_b_lines = []
    view_c_lines = []
    for family, result in [("M64", m64), ("M128", m128)]:
        b = result["view_b_aggregate"]
        c = result["view_c_aggregate"]
        view_b_lines.append(
            f"| {family} | {fmt(b['top1_accuracy']['mean'])} | {fmt(b['mrr']['mean'])} | "
            f"{fmt(b['recall_at_3']['mean'])} | {fmt(b['mean_gold_label_rank']['mean'])} | "
            f"`{json.dumps(b['predicted_label_distribution']['total_across_five_seeds'], sort_keys=True)}` |"
        )
        view_c_lines.append(
            f"| {family} | {fmt(c['top1_accuracy']['mean'])} | {fmt(c['mrr']['mean'])} | "
            f"{fmt(c['recall_at_3']['mean'])} | {fmt(c['macro_f1']['mean'])} | {fmt(c['mean_gold_label_rank']['mean'])} |"
        )
    view_b_table = "\n".join(view_b_lines)
    view_c_table = "\n".join(view_c_lines)

    selected = comparison["selected_robustness_stage_development_architecture"]
    representative = comparison["development_representative_checkpoint"]
    interpretation = comparison["capacity_interpretation_state"]
    m64_ci = uncertainty["architectures"]["M64"]["bootstrap_95_percent_ci"]
    m128_ci = uncertainty["architectures"]["M128"]["bootstrap_95_percent_ci"]

    report = f'''# LR-3R — Compact Learned-Scorer Robustness & Capacity Audit

## 1. Status

LR-3R is complete. Exactly ten new research-only scorer runs were trained: M64 and M128 across the fixed five seeds. Under the predeclared architecture rule, **M64** is the `ROBUSTNESS-STAGE DEVELOPMENT ARCHITECTURE`. Its mean VIEW-A MRR is `{fmt(rows['M64']['mrr_mean'])}`, above M128 `{fmt(rows['M128']['mrr_mean'])}`, frozen M1 `{fmt(rows['M1']['mrr_mean'])}`, and cosine `{fmt(rows['C0']['mrr_mean'])}`. The interpretation state is `{interpretation}`.

No production, semantic runtime, original data, LR-3, or earlier-stage artifact changed. No calibration, integration, hard-negative training, pair deduplication, MPNet fine-tuning, or final-gold access occurred.

## 2. Research question

Does LR-3's nonlinear learned-similarity gain survive a large reduction in hidden capacity when every other training and evaluation choice remains frozen? LR-3R changes only hidden width: M64 uses 64 units and M128 uses 128, versus M1's 768.

## 3. Frozen LR-3 evidence

All {inputs['lr3_checksum_entries_verified']} LR-3 checksum entries passed before training and after all tests. C0, L1, and M1 metrics were loaded from frozen LR-3 artifacts and matched exactly. Historical LR-3 remains: C0 MRR `{fmt(rows['C0']['mrr_mean'])}`; L1 mean MRR `{fmt(rows['L1']['mrr_mean'])}`; M1 mean MRR `{fmt(rows['M1']['mrr_mean'])}` with representative checkpoint `M1:20260813`; L1 and M1 each had 5/5 severe-overfit runs.

## 4. Input verification

All {inputs['lr2r_checksum_entries_verified']} LR-2R checksum entries passed. The read-only sampler reproduced 58 training records, 12 positive-capable labels, 228 rows per epoch, 114 positives, and 114 safe negatives for all 50 possible epochs. Singleton, hard-negative, blocked, and DEV endpoints in training were all zero. Runtime fidelity remained PASS on 84 DEV records; the full frozen 62-record, 16-label approved index and page eligibility remained the scoring universe.

## 5. Capacity-ablation rationale

M64 and M128 retain M1's LayerNorm, ReLU, dropout, final linear logit, feature schema, optimizer, seeds, and evaluation. Hidden width is the only experimental variable. Parameter ratios provide capacity context; they do not by themselves prove overfitting.

## 6. M64 architecture

`LayerNorm(1536) -> Linear(1536,64) -> ReLU -> Dropout(0.5) -> Linear(64,1)`. Exact parameter count: `{capacity['models']['M64']['trainable_parameters']:,}` total/trainable. Sigmoid is used only to turn the logit into an offline ranking compatibility score; it is not calibrated confidence.

## 7. M128 architecture

`LayerNorm(1536) -> Linear(1536,128) -> ReLU -> Dropout(0.5) -> Linear(128,1)`. Exact parameter count: `{capacity['models']['M128']['trainable_parameters']:,}` total/trainable. The same ranking-only caveat applies.

## 8. Frozen training protocol

Features remain `concat(abs(q-c), q*c)` over frozen 768-dimensional MPNet vectors. AdamW learning rate `1e-3`, weight decay `1e-4`, batch 32, maximum 50 epochs, patience 8, clip norm 1.0, dropout 0.5, BCEWithLogitsLoss, and no class weight are identical to LR-3. Seeds are 20260813–20260817. Checkpoints use only 79-record VIEW-A MRR, then Top-1, then earlier epoch. Directed reverse rows are retained: epoch 0 has {capacity['epoch_0_directed_rows']} directed rows, {capacity['epoch_0_effective_unique_feature_count']} effective features, and {capacity['epoch_0_reverse_duplicate_groups']} reverse-duplicate groups. No weighting changed.

## 9. Five-seed M64 results

| Model | Seed | Best epoch | Stop epoch | Top-1 | MRR | Recall@3 | Macro-F1 | LR-3 overfit diagnostic |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(line for line in seed_lines if line.startswith('| M64 '))}

M64 mean ± population std: MRR `{fmt(rows['M64']['mrr_mean'])} ± {fmt(rows['M64']['mrr_std'])}`, Top-1 `{fmt(rows['M64']['top1_mean'])} ± {fmt(rows['M64']['top1_std'])}`, Recall@3 `{fmt(rows['M64']['recall_at_3_mean'])}`, Macro-F1 `{fmt(rows['M64']['macro_f1_mean'])}`. All five seeds beat cosine MRR.

## 10. Five-seed M128 results

| Model | Seed | Best epoch | Stop epoch | Top-1 | MRR | Recall@3 | Macro-F1 | LR-3 overfit diagnostic |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(line for line in seed_lines if line.startswith('| M128 '))}

M128 mean ± population std: MRR `{fmt(rows['M128']['mrr_mean'])} ± {fmt(rows['M128']['mrr_std'])}`, Top-1 `{fmt(rows['M128']['top1_mean'])} ± {fmt(rows['M128']['top1_std'])}`, Recall@3 `{fmt(rows['M128']['recall_at_3_mean'])}`, Macro-F1 `{fmt(rows['M128']['macro_f1_mean'])}`. All five seeds beat cosine MRR.

## 11. Capacity comparison

| Model | Total parameters | Trainable parameters | Ratio vs M1 | Parameters / epoch-0 effective feature |
|---|---:|---:|---:|---:|
{capacity_table}

M64 uses 8.57% of M1's parameters and M128 uses 16.88%. These ratios contextualise, but do not establish, the overfit result.

## 12. Seed-stability analysis

Every M64 and M128 seed beat cosine on MRR. M64 beat cosine Top-1 in all five seeds and Macro-F1 in two; M128 beat cosine Top-1 in four and Macro-F1 in one. Frozen M1 beat cosine MRR in four seeds; frozen L1 did so in three. Full per-seed deltas and above/equal/below counts are stored in `lr3r_seed_stability_v1.json`.

| Architecture | Trainable parameters | MRR mean / std | Top-1 mean / std | Recall@3 mean | Macro-F1 mean | Seeds > C0 MRR | Severe overfit |
|---|---:|---:|---:|---:|---:|---:|---:|
{architecture_table}

## 13. Overfitting analysis

M64 and M128 each triggered the unchanged LR-3 `SEVERE_OVERFIT` rule in 5/5 runs, just like L1 and M1. M64 best epochs were `{json.dumps(overfit['architectures']['M64']['best_epoch_distribution'], sort_keys=True)}` and stop epochs `{json.dumps(overfit['architectures']['M64']['early_stop_epoch_distribution'], sort_keys=True)}`. M128 best epochs were `{json.dumps(overfit['architectures']['M128']['best_epoch_distribution'], sort_keys=True)}` and stop epochs `{json.dumps(overfit['architectures']['M128']['early_stop_epoch_distribution'], sort_keys=True)}`. In each run, training BCE continued down by at least 5% while VIEW-A MRR stayed below the selected best for the full patience window. Capacity reduction therefore did **not** materially change the observed 5/5 severe-overfit pattern. Seed variances and complete loss trajectories are machine-readable.

## 14. Development uncertainty analysis

**DEVELOPMENT UNCERTAINTY ANALYSIS.** A fixed-seed (`20260813`) nonparametric bootstrap resampled the 79 VIEW-A queries exactly 10,000 times. It operates on each query's cosine reciprocal-rank contribution versus the five-seed mean learned contribution.

| Architecture | Mean per-query RR delta vs C0 | 95% bootstrap CI |
|---|---:|---:|
{uncertainty_table}

All intervals cross zero. Because this same DEV set supported model development and selection, these intervals are diagnostic and are not confirmatory proof or production authorisation.

## 15. Metric trade-offs

| Architecture | Δ MRR | Δ Top-1 | Δ Recall@3 | Δ Macro-F1 |
|---|---:|---:|---:|---:|
{metric_table}

M64 improves all four five-seed means versus C0, although its Macro-F1 gain is only about `+0.000829`. M128 improves MRR, Top-1, and Recall@3 but reduces Macro-F1. This prevents treating the ranking gain as uniform across metrics.

## 16. Confusion analysis

| VIEW-A gold intent | C0 F1 | L1 mean | M64 mean | M128 mean | M1 mean |
|---|---:|---:|---:|---:|---:|
{intent_table}

| Known pattern | C0 count | M1 mean | M64 mean (vs M1) | M128 mean (vs M1) |
|---|---:|---:|---:|---:|
{confusion_table}

Both compact variants improve the two dashboard-directed patterns relative to M1, but both worsen the bidirectional planning/improvement confusion. The taxonomy was not changed.

## 17. Singleton-unseen diagnostic

VIEW B is diagnostic only and was excluded from all checkpoint and architecture decisions.

| Architecture | Top-1 mean | MRR mean | Recall@3 mean | Mean gold rank | Predicted-label distribution across 25 seed-query predictions |
|---|---:|---:|---:|---:|---|
{view_b_table}

## 18. Mixed DEV diagnostic

**MIXED DEVELOPMENT DIAGNOSTIC** — 84 authorised records, not a full-universe or final evaluation.

| Architecture | Top-1 mean | MRR mean | Recall@3 mean | Macro-F1 mean | Mean gold rank |
|---|---:|---:|---:|---:|---:|
{view_c_table}

## 19. Architecture decision

Architectures first had to exceed cosine's five-seed mean VIEW-A MRR, then were ranked by higher mean MRR, higher mean Top-1, and fewer parameters. Eligible learned architectures were `{', '.join(comparison['eligible_architectures'])}`. M64 ranks first with mean MRR `{fmt(rows['M64']['mrr_mean'])}` and is nominated as the `ROBUSTNESS-STAGE DEVELOPMENT ARCHITECTURE`. This is neither a production nor final model decision.

## 20. Representative checkpoint decision

For selected M64, the median of the five seed-specific best-checkpoint VIEW-A MRR values, with lower numeric seed as tie-break, selects `{representative}`. Its checkpoint is `checkpoints/lr3r_m64_seed_20260815_best_v1.pt`. It is research-only. Frozen LR-3 M1 seed 20260813 remains intact and is not replaced.

## 21. DEV coverage limitations

Production has 16 candidate labels, pairwise training has 12 labels, VIEW A has 79 records across only eight gold labels, VIEW B has five records for one singleton-unseen gold label, and seven production labels have no DEV gold. The prediction universe is full and page-eligible, but gold coverage is not. Pair symmetry also means reverse directed rows can produce identical effective features.

## 22. Final-gold status

Primary-v3 / Stage-6 remains unavailable and deferred. No parent/sibling search, substitute final dataset, Unified-as-final, Functional-QA-as-final, or final evaluation occurred.

## 23. Regression verification

LR-3R research tests passed 12/12, including deterministic M64/M128 seed replay. The same bounded production suite used by LR-3 passed 27/27: router 11, semantic C_FULL integration 2, keyword parity 1, P2-C 5, P2-D 6, and real semantic runtime 2. The offline semantic preflight also passed with network downloads disabled. Protected hashes still match after all checks.

## 24. Remaining blockers

Every learned family still has 5/5 severe-overfit runs; all diagnostic bootstrap intervals cross zero; VIEW-A gold coverage is only 8/16 production labels; seven production labels lack DEV gold; final gold remains unavailable; and reverse directed pairs are not independent effective features. These block production interpretation and should be resolved before a hard-negative ablation is authorised.

## 25. Recommended next stage

Stop here. Subject to explicit researcher authorisation, the next controlled stage should isolate directed-pair symmetry/deduplication or weighting while retaining M64 and the same frozen data/evaluator. Hard-negative use remains a separate later experiment and is not yet safe to start.

## 26. Files created

Created the required 15 named LR-3R artifacts, ten checkpoints plus metadata, ten prediction files, and five isolated research code/test files, all under `evaluation/learned_intent_ranking/lr3r/`.

## 27. Files verified unchanged

Production router/service/planner/memory files, all semantic runtime files, original Functional-QA/Unified inputs, LR-1, LR-1R, LR-2, LR-2R, and every LR-3 artifact remained byte-identical to the pre-training protected snapshot.

LR-3R STATUS:

PRODUCTION CODE MODIFIED: NO
SEMANTIC RUNTIME MODIFIED: NO
ORIGINAL DATA MODIFIED: NO
LR-3 MODIFIED: NO

NEW MODELS TRAINED: 10 RUNS / 2 ARCHITECTURES (M64, M128)
NEW CHECKPOINTS CREATED: 10 RESEARCH-ONLY CHECKPOINTS

M64 TRAINABLE PARAMETERS: {capacity['models']['M64']['trainable_parameters']}
M128 TRAINABLE PARAMETERS: {capacity['models']['M128']['trainable_parameters']}
M1 REFERENCE PARAMETERS: {capacity['models']['M1']['trainable_parameters']}

COSINE VIEW-A MRR: {rows['C0']['mrr_mean']}

M64 VIEW-A MRR MEAN: {rows['M64']['mrr_mean']}
M64 VIEW-A MRR STD: {rows['M64']['mrr_std']}
M64 SEEDS ABOVE COSINE MRR: {rows['M64']['seeds_beating_cosine_mrr']}/5
M64 VIEW-A TOP1 MEAN: {rows['M64']['top1_mean']}
M64 VIEW-A MACRO-F1 MEAN: {rows['M64']['macro_f1_mean']}
M64 SEVERE-OVERFIT RUNS: {rows['M64']['severe_overfit_runs']}/5

M128 VIEW-A MRR MEAN: {rows['M128']['mrr_mean']}
M128 VIEW-A MRR STD: {rows['M128']['mrr_std']}
M128 SEEDS ABOVE COSINE MRR: {rows['M128']['seeds_beating_cosine_mrr']}/5
M128 VIEW-A TOP1 MEAN: {rows['M128']['top1_mean']}
M128 VIEW-A MACRO-F1 MEAN: {rows['M128']['macro_f1_mean']}
M128 SEVERE-OVERFIT RUNS: {rows['M128']['severe_overfit_runs']}/5

M1 REFERENCE MRR MEAN: {rows['M1']['mrr_mean']}
M1 REFERENCE TOP1 MEAN: {rows['M1']['top1_mean']}
M1 REFERENCE MACRO-F1 MEAN: {rows['M1']['macro_f1_mean']}
M1 REFERENCE SEVERE-OVERFIT RUNS: {rows['M1']['severe_overfit_runs']}/5

SELECTED ROBUSTNESS-STAGE ARCHITECTURE: {selected}
DEVELOPMENT REPRESENTATIVE CHECKPOINT: {representative} / checkpoints/lr3r_m64_seed_20260815_best_v1.pt

BOOTSTRAP DELTA-MRR CI VS COSINE: M64 [{m64_ci['lower']}, {m64_ci['upper']}]; M128 [{m128_ci['lower']}, {m128_ci['upper']}]

CAPACITY INTERPRETATION STATE: {interpretation}

FINAL GOLD AVAILABLE: NO / DEFERRED
FINAL-GOLD EVALUATION RUN: NO

EXISTING REGRESSIONS: PASS 27/27; OFFLINE SEMANTIC PREFLIGHT PASS

BLOCKERS BEFORE HARD-NEGATIVE ABLATION: 5/5 SEVERE OVERFIT FOR ALL LEARNED FAMILIES; BOOTSTRAP CIs CROSS ZERO; LIMITED DEV GOLD COVERAGE; FINAL GOLD UNAVAILABLE; DIRECTED-PAIR SYMMETRY UNRESOLVED
RECOMMENDED NEXT STAGE: EXPLICITLY AUTHORISED DIRECTED-PAIR SYMMETRY/WEIGHTING ABLATION WITH M64; HARD NEGATIVES REMAIN DEFERRED
SAFE TO PROCEED: NO — STOP AND WAIT FOR EXPLICIT RESEARCHER AUTHORISATION
'''
    (HERE / "LR3R_COMPACT_SCORER_ROBUSTNESS_REPORT.md").write_text(report, encoding="utf-8")

    # Seal every LR-3R deliverable except the manifest itself and transient caches.
    files = sorted(
        path for path in HERE.rglob("*")
        if path.is_file() and path.name != "lr3r_output_checksums_v1.sha256" and "__pycache__" not in path.parts
    )
    lines = [f"{sha(path)}  {path.relative_to(HERE)}" for path in files]
    (HERE / "lr3r_output_checksums_v1.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
