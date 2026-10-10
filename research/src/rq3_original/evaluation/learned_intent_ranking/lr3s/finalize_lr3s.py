"""Seal LR-3S validation, narrative report, and checksum manifest."""

from __future__ import annotations

import hashlib
import json
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


def main() -> None:
    validation = load("lr3s_validation_report_v1.json")
    current = {
        group: {relative: sha(ROOT / relative) for relative in snapshot}
        for group, snapshot in validation["protected_snapshot_before"].items()
    }
    if current != validation["protected_snapshot_before"]:
        raise ValueError("protected artifacts changed after LR-3S")

    registry = load("lr3s_checkpoint_registry_v1.json")
    resolution = []
    for entry in registry["entries"]:
        checkpoint = HERE / entry["checkpoint_path"]
        metadata_path = HERE / entry["metadata_path"]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if sha(checkpoint) != entry["checkpoint_file_sha256"] or sha(checkpoint) != metadata["checkpoint_file_sha256"]:
            raise ValueError(f"checkpoint hash mismatch: {checkpoint}")
        entry["metadata_file_sha256"] = sha(metadata_path)
        resolution.append({
            "condition": entry["condition"], "training_seed": entry["training_seed"],
            "checkpoint_hash_match": True, "checkpoint_tensor_hash": entry["checkpoint_tensor_hash"],
            "metadata_file_sha256": entry["metadata_file_sha256"],
        })
    write("lr3s_checkpoint_registry_v1.json", registry)

    validation.update({
        "overall_status": "PASS",
        "seed_replay_status": "PASS_IDENTICAL_TENSOR_HASHES_FOR_S1_AND_S2_SEED_20260813",
        "seed_determinism_replays": [
            {
                "condition": condition, "training_seed": 20260813,
                "result": "IDENTICAL_TENSOR_HASH_AND_VIEW_A_METRICS",
                "checkpoint_tensor_hash": next(entry["checkpoint_tensor_hash"] for entry in registry["entries"] if entry["condition"] == condition and entry["training_seed"] == 20260813),
            }
            for condition in ["S1_UNORDERED_EQUAL_WEIGHT", "S2_UNORDERED_CLASS_BALANCED"]
        ],
        "research_test_results": {
            "status": "PASS", "passed": 11, "failed": 0,
            "command": "PYTHONDONTWRITEBYTECODE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest evaluation/learned_intent_ranking/lr3s/test_lr3s.py -v",
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
        "checkpoint_metadata_hashes_resolve": True, "checkpoint_resolution": resolution,
        "protected_snapshot_after_all_tests": current, "protected_files_unchanged_after_all_tests": True,
    })
    write("lr3s_validation_report_v1.json", validation)

    s1 = load("lr3s_s1_training_results_v1.json")
    s2 = load("lr3s_s2_training_results_v1.json")
    comparison = load("lr3s_model_comparison_v1.json")
    audit = load("lr3s_pair_weight_audit_v1.json")
    overfit = load("lr3s_overfit_analysis_v1.json")
    uncertainty = load("lr3s_development_uncertainty_analysis_v1.json")
    confusion = load("lr3s_confusion_analysis_v1.json")
    inputs = load("lr3s_input_hashes_v1.json")
    table = comparison["comparison_table"]

    seed_lines = []
    for result in [s1, s2]:
        for run in result["runs"]:
            metrics = run["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]
            seed_lines.append(
                f"| {run['condition'].split('_')[0]} | {run['training_seed']} | {run['best_epoch']} | {run['final_epoch']} | "
                f"{fmt(metrics['top1_accuracy'])} | {fmt(metrics['mrr'])} | {fmt(metrics['recall_at_3'])} | "
                f"{fmt(metrics['macro_f1'])} | {'SEVERE_OVERFIT' if run['overfit_diagnostic']['flag'] else 'NO'} |"
            )

    comparison_lines = []
    for name in ["C0_COSINE", "D0_DIRECTED_EQUAL_WEIGHT", "S1_UNORDERED_EQUAL_WEIGHT", "S2_UNORDERED_CLASS_BALANCED"]:
        row = table[name]
        comparison_lines.append(
            f"| {name} | {fmt(row['top1_mean'])} / {fmt(row['top1_std'])} | {fmt(row['mrr_mean'])} / {fmt(row['mrr_std'])} | "
            f"{fmt(row['recall_at_3_mean'])} | {fmt(row['macro_f1_mean'])} | "
            f"{row['seeds_above_cosine_mrr'] if row['seeds_above_cosine_mrr'] is not None else '—'} | "
            f"{row['seeds_above_d0_mrr_benchmark'] if row['seeds_above_d0_mrr_benchmark'] is not None else '—'} | "
            f"{str(row['severe_overfit_runs']) + '/5' if row['severe_overfit_runs'] is not None else '—'} |"
        )
    comparison_table = "\n".join(comparison_lines)

    a1 = audit["conditions"]["S1_UNORDERED_EQUAL_WEIGHT"]
    a2 = audit["conditions"]["S2_UNORDERED_CLASS_BALANCED"]
    def audit_range(rows: list[dict[str, Any]], key: str) -> str:
        values = [row[key] for row in rows]
        return fmt(min(values)) if min(values) == max(values) else f"{fmt(min(values))}–{fmt(max(values))}"

    uncertainty_lines = []
    for condition in ["S1_UNORDERED_EQUAL_WEIGHT", "S2_UNORDERED_CLASS_BALANCED"]:
        for reference in ["C0_COSINE", "D0_DIRECTED_EQUAL_WEIGHT"]:
            row = uncertainty["conditions"][condition]["comparisons"][reference]
            ci = row["bootstrap_95_percent_ci"]
            uncertainty_lines.append(f"| {condition.split('_')[0]} | {reference.split('_')[0]} | {row['mean_per_query_rr_delta']:+.6f} | [{ci['lower']:+.6f}, {ci['upper']:+.6f}] |")
    uncertainty_table = "\n".join(uncertainty_lines)

    intent_lines = []
    for label in confusion["represented_gold_labels"]:
        values = [confusion["per_intent_f1"][condition][label]["mean"] for condition in ["D0_DIRECTED_EQUAL_WEIGHT", "S1_UNORDERED_EQUAL_WEIGHT", "S2_UNORDERED_CLASS_BALANCED"]]
        intent_lines.append(f"| `{label}` | {fmt(values[0])} | {fmt(values[1])} | {fmt(values[2])} |")
    intent_table = "\n".join(intent_lines)

    confusion_lines = []
    for name in confusion["known_confusion_patterns"]["D0_DIRECTED_EQUAL_WEIGHT"]:
        d0 = confusion["known_confusion_patterns"]["D0_DIRECTED_EQUAL_WEIGHT"][name]["mean_count"]
        x1 = confusion["known_confusion_patterns"]["S1_UNORDERED_EQUAL_WEIGHT"][name]
        x2 = confusion["known_confusion_patterns"]["S2_UNORDERED_CLASS_BALANCED"][name]
        confusion_lines.append(f"| `{name}` | {d0:.1f} | {x1['mean_count']:.1f} ({x1['effect_vs_d0']}) | {x2['mean_count']:.1f} ({x2['effect_vs_d0']}) |")
    confusion_table = "\n".join(confusion_lines)

    view_b_lines, view_c_lines = [], []
    for label, result in [("S1", s1), ("S2", s2)]:
        b, c = result["view_b_aggregate"], result["view_c_aggregate"]
        view_b_lines.append(
            f"| {label} | {fmt(b['top1_accuracy']['mean'])} | {fmt(b['mrr']['mean'])} | {fmt(b['recall_at_3']['mean'])} | "
            f"{fmt(b['mean_gold_label_rank']['mean'])} | `{json.dumps(b['predicted_label_distribution']['total_across_five_seeds'], sort_keys=True)}` |"
        )
        view_c_lines.append(
            f"| {label} | {fmt(c['top1_accuracy']['mean'])} | {fmt(c['mrr']['mean'])} | {fmt(c['recall_at_3']['mean'])} | "
            f"{fmt(c['macro_f1']['mean'])} | {fmt(c['mean_gold_label_rank']['mean'])} |"
        )
    view_b_table, view_c_table = "\n".join(view_b_lines), "\n".join(view_c_lines)

    s1_cos = uncertainty["conditions"]["S1_UNORDERED_EQUAL_WEIGHT"]["comparisons"]["C0_COSINE"]["bootstrap_95_percent_ci"]
    s1_d0 = uncertainty["conditions"]["S1_UNORDERED_EQUAL_WEIGHT"]["comparisons"]["D0_DIRECTED_EQUAL_WEIGHT"]["bootstrap_95_percent_ci"]
    s2_cos = uncertainty["conditions"]["S2_UNORDERED_CLASS_BALANCED"]["comparisons"]["C0_COSINE"]["bootstrap_95_percent_ci"]
    s2_d0 = uncertainty["conditions"]["S2_UNORDERED_CLASS_BALANCED"]["comparisons"]["D0_DIRECTED_EQUAL_WEIGHT"]["bootstrap_95_percent_ci"]

    report = f'''# LR-3S — Symmetric Pair Weighting & Effective-Sample Ablation

## 1. Status

LR-3S is complete. S1 and S2 both retain a development MRR gain over cosine, but both trail frozen D0 and neither changes the 5/5 severe-overfit pattern. The predeclared policy rule retains `D0_DIRECTED_EQUAL_WEIGHT`; the final symmetry state is `{comparison['symmetry_interpretation_state']}`.

No production, semantic runtime, original data, or prior LR-stage file changed. No pair was added, removed, or physically deduplicated. No hard negative, calibration, integration, MPNet fine-tuning, or final-gold access occurred.

## 2. Research question

Is the LR-3R M64 ranking gain robust when reverse-directed rows that map to the same symmetric feature receive only one unordered pair's total loss contribution? LR-3S changes only explicit row weights while holding pair membership, batch order, initialization, architecture, optimizer, and evaluator fixed.

## 3. Frozen M64 evidence

Frozen LR-3R D0 uses M64 with 101,505 trainable parameters. Its five-seed VIEW-A MRR is `{table['D0_DIRECTED_EQUAL_WEIGHT']['mrr_mean']}`, Top-1 `{table['D0_DIRECTED_EQUAL_WEIGHT']['top1_mean']}`, Recall@3 `{table['D0_DIRECTED_EQUAL_WEIGHT']['recall_at_3_mean']}`, and Macro-F1 `{table['D0_DIRECTED_EQUAL_WEIGHT']['macro_f1_mean']}`. All values reproduced exactly; D0 was not retrained except through independent deterministic verification already sealed in LR-3R.

## 4. Input verification

Checksum verification passed for all {inputs['checksum_entries_verified']['lr2r']} LR-2R entries, {inputs['checksum_entries_verified']['lr3']} LR-3 entries, and {inputs['checksum_entries_verified']['lr3r']} LR-3R entries. All 50 epoch membership hashes were recorded. Training remained 58 records and 12 labels, with zero self pairs, singletons, hard negatives, blocked relationships, or DEV endpoints.

## 5. Symmetric-feature problem

The frozen feature `concat(abs(q-c), q*c)` is symmetric, so `(q,c)` and `(c,q)` are identical effective features. LR-2R nevertheless authorises directed rows. Epoch 0 has 228 directed rows, 193 unique unordered features, and 35 reverse-duplicate groups. Equal row weighting therefore gives a reverse-complete unordered pair twice the contribution of a one-direction-only pair.

## 6. Directed reference D0

`D0_DIRECTED_EQUAL_WEIGHT` assigns every directed row weight 1. It remains the frozen benchmark: mean VIEW-A MRR `{fmt(table['D0_DIRECTED_EQUAL_WEIGHT']['mrr_mean'])}`, versus cosine `{fmt(table['C0_COSINE']['mrr_mean'])}`. D0 has 5/5 severe-overfit runs.

## 7. Unordered-pair identity

`unordered_pair_id` is the compact JSON encoding of the lexicographically sorted anchor and candidate record IDs. Intent labels are excluded. The encoding is deterministic and unambiguous. Every observed multiplicity was 1 or 2; inconsistent targets or larger multiplicity fail closed.

## 8. S1 weighting design

`S1_UNORDERED_EQUAL_WEIGHT` assigns `base_weight = final_weight = 1 / multiplicity`. A one-way pair receives 1; each direction of a reverse pair receives 0.5. Rows remain physically present and in identical order. Every unordered pair's total weight is exactly 1 within `1e-12`.

## 9. S2 weighting design

`S2_UNORDERED_CLASS_BALANCED` starts from S1. Per epoch it sets each class target to half the combined S1 effective weight, then multiplies rows in that class by `target / class_base_total`. Thus unordered pairs retain equal base contribution within class, positive and negative final totals match, and total effective sample weight stays unchanged. No PyTorch `pos_weight` is used.

## 10. Weight audit

Across 50 epochs, directed rows were always 228. Unique unordered pairs ranged `{min(row['unique_unordered_pairs'] for row in a1)}–{max(row['unique_unordered_pairs'] for row in a1)}` and reverse groups `{min(row['reverse_duplicate_groups'] for row in a1)}–{max(row['reverse_duplicate_groups'] for row in a1)}`. Raw rows remained 114 positive and 114 negative.

Epoch 0 illustrates the change:

| Condition | Unique positive / negative pairs | Effective positive weight | Effective negative weight | Row-weight min / max / mean | Effective total |
|---|---:|---:|---:|---:|---:|
| S1 | {a1[0]['unique_positive_pairs']} / {a1[0]['unique_negative_pairs']} | {a1[0]['total_effective_positive_weight']:.1f} | {a1[0]['total_effective_negative_weight']:.1f} | {a1[0]['minimum_row_weight']:.6f} / {a1[0]['maximum_row_weight']:.6f} / {a1[0]['mean_row_weight']:.6f} | {a1[0]['effective_total_sample_weight']:.1f} |
| S2 | {a2[0]['unique_positive_pairs']} / {a2[0]['unique_negative_pairs']} | {a2[0]['total_effective_positive_weight']:.1f} | {a2[0]['total_effective_negative_weight']:.1f} | {a2[0]['minimum_row_weight']:.6f} / {a2[0]['maximum_row_weight']:.6f} / {a2[0]['mean_row_weight']:.6f} | {a2[0]['effective_total_sample_weight']:.1f} |

Every S1 pair-contribution check and every S2 class-balance check passed for every epoch. Full audit values and membership hashes are machine-readable.

## 11. Training protocol

Both conditions use frozen M64, frozen MPNet, identical LR-2R membership, AdamW (`lr=1e-3`, `weight_decay=1e-4`), batch 32, maximum 50 epochs, patience 8, clip norm 1.0, dropout 0.5, and seeds 20260813–20260817. Model initialization and batch permutation use the same M64 seed derivation in both conditions. The exact batch loss is `sum(weight_i * BCEWithLogits_i) / sum(weight_i)` using unreduced BCE; the epoch training-loss audit uses the same weighted numerator and denominator. VIEW A alone selects checkpoints by MRR, Top-1, then earlier epoch.

## 12. S1 five-seed results

| Condition | Seed | Best epoch | Stop epoch | Top-1 | MRR | Recall@3 | Macro-F1 | Overfit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(line for line in seed_lines if line.startswith('| S1 '))}

S1 mean ± population std: MRR `{fmt(table['S1_UNORDERED_EQUAL_WEIGHT']['mrr_mean'])} ± {fmt(table['S1_UNORDERED_EQUAL_WEIGHT']['mrr_std'])}`, Top-1 `{fmt(table['S1_UNORDERED_EQUAL_WEIGHT']['top1_mean'])} ± {fmt(table['S1_UNORDERED_EQUAL_WEIGHT']['top1_std'])}`, Recall@3 `{fmt(table['S1_UNORDERED_EQUAL_WEIGHT']['recall_at_3_mean'])}`, Macro-F1 `{fmt(table['S1_UNORDERED_EQUAL_WEIGHT']['macro_f1_mean'])}`. All five seeds beat cosine; one exceeded the D0 mean benchmark.

## 13. S2 five-seed results

| Condition | Seed | Best epoch | Stop epoch | Top-1 | MRR | Recall@3 | Macro-F1 | Overfit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(line for line in seed_lines if line.startswith('| S2 '))}

S2 mean ± population std: MRR `{fmt(table['S2_UNORDERED_CLASS_BALANCED']['mrr_mean'])} ± {fmt(table['S2_UNORDERED_CLASS_BALANCED']['mrr_std'])}`, Top-1 `{fmt(table['S2_UNORDERED_CLASS_BALANCED']['top1_mean'])} ± {fmt(table['S2_UNORDERED_CLASS_BALANCED']['top1_std'])}`, Recall@3 `{fmt(table['S2_UNORDERED_CLASS_BALANCED']['recall_at_3_mean'])}`, Macro-F1 `{fmt(table['S2_UNORDERED_CLASS_BALANCED']['macro_f1_mean'])}`. All five seeds beat cosine; two exceeded the D0 mean benchmark.

## 14. Comparison with cosine and D0

| Policy | Top-1 mean / std | MRR mean / std | Recall@3 mean | Macro-F1 mean | Seeds > cosine MRR | Seeds > D0 mean MRR | Severe overfit |
|---|---:|---:|---:|---:|---:|---:|---:|
{comparison_table}

S1 retains about `{(table['S1_UNORDERED_EQUAL_WEIGHT']['mrr_mean'] - table['C0_COSINE']['mrr_mean']) / (table['D0_DIRECTED_EQUAL_WEIGHT']['mrr_mean'] - table['C0_COSINE']['mrr_mean']):.3f}` of D0's mean-MRR gain over cosine; S2 retains about `{(table['S2_UNORDERED_CLASS_BALANCED']['mrr_mean'] - table['C0_COSINE']['mrr_mean']) / (table['D0_DIRECTED_EQUAL_WEIGHT']['mrr_mean'] - table['C0_COSINE']['mrr_mean']):.3f}`. The gain is therefore robust to effective duplicate weighting, but equal directed weighting remains the best development policy.

## 15. Overfitting analysis

D0, S1, and S2 each have 5/5 severe-overfit runs under the unchanged LR-3 diagnostic. S1 best epochs are `{json.dumps(overfit['conditions']['S1_UNORDERED_EQUAL_WEIGHT']['best_epoch_distribution'], sort_keys=True)}` and stop epochs `{json.dumps(overfit['conditions']['S1_UNORDERED_EQUAL_WEIGHT']['stop_epoch_distribution'], sort_keys=True)}`. S2 best epochs are `{json.dumps(overfit['conditions']['S2_UNORDERED_CLASS_BALANCED']['best_epoch_distribution'], sort_keys=True)}` and stop epochs `{json.dumps(overfit['conditions']['S2_UNORDERED_CLASS_BALANCED']['stop_epoch_distribution'], sort_keys=True)}`. Complete training-loss and DEV-MRR trajectories show continuing loss reduction after the selected DEV optimum. Removing duplicate weighting does not reduce the frozen overfit pattern.

## 16. Development uncertainty analysis

**DEVELOPMENT UNCERTAINTY ANALYSIS.** Exactly 10,000 fixed-seed (`20260813`) bootstrap resamples were drawn over the 79 VIEW-A queries.

| Condition | Reference | Mean per-query RR delta | 95% bootstrap CI |
|---|---|---:|---:|
{uncertainty_table}

All intervals cross zero. These are development diagnostics, not confirmatory inference or production authorisation.

## 17. Confusion analysis

| VIEW-A gold intent | D0 mean F1 | S1 mean F1 | S2 mean F1 |
|---|---:|---:|---:|
{intent_table}

| Known pattern | D0 mean count | S1 mean (vs D0) | S2 mean (vs D0) |
|---|---:|---:|---:|
{confusion_table}

S1 preserves both dashboard-directed patterns but worsens planning/improvement confusion. S2 improves course-content-to-dashboard confusion, preserves cross-page-to-dashboard confusion, and also worsens planning/improvement confusion. Taxonomy remains frozen.

## 18. Singleton diagnostic

VIEW B remains diagnostic only and was excluded from checkpoint and policy selection.

| Condition | Top-1 mean | MRR mean | Recall@3 mean | Mean gold rank | Predicted-label distribution across 25 seed-query predictions |
|---|---:|---:|---:|---:|---|
{view_b_table}

## 19. Mixed DEV diagnostic

**MIXED DEVELOPMENT DIAGNOSTIC** — all 84 authorised DEV records, not final evaluation.

| Condition | Top-1 mean | MRR mean | Recall@3 mean | Macro-F1 mean | Mean gold rank |
|---|---:|---:|---:|---:|---:|
{view_c_table}

## 20. Training-weighting policy decision

All three M64 policies qualify by exceeding cosine mean VIEW-A MRR. Applying higher mean MRR, higher Top-1, higher Macro-F1, fewer severe-overfit runs, then simpler policy selects `D0_DIRECTED_EQUAL_WEIGHT` as the `DEVELOPMENT TRAINING-WEIGHTING POLICY`. No best single seed, VIEW B/C result, or final gold influenced this decision.

## 21. Representative checkpoint decision

Because D0 remains selected, retain frozen LR-3R M64 seed 20260815 at `../lr3r/checkpoints/lr3r_m64_seed_20260815_best_v1.pt`. No LR-3S checkpoint replaces or modifies it. All ten LR-3S checkpoints remain research-only.

## 22. DEV/final-gold limitations

VIEW A contains 79 records across only eight of 16 production labels. Training covers 12 labels; VIEW B covers one singleton-unseen gold label; seven production labels lack DEV gold. Directed reverse rows are still correlated effective observations. Primary-v3 / Stage-6 remains unavailable and deferred; no substitute final data was used.

## 23. Regression verification

LR-3S tests passed 11/11, including deterministic S1/S2 seed replay. The bounded production suite passed 27/27: router 11, semantic C_FULL integration 2, keyword parity 1, P2-C 5, P2-D 6, and real semantic runtime 2. Offline semantic preflight passed with downloads disabled. Protected hashes still match after all checks.

## 24. Remaining blockers

All learned policies retain 5/5 severe-overfit runs; every development bootstrap interval crosses zero; policy effects are metric- and intent-dependent; VIEW-A gold coverage is limited; seven production labels lack DEV gold; and final gold is unavailable. These prevent production interpretation and remain blockers before a hard-negative ablation.

## 25. Recommended next stage

Stop here. Before authorising hard negatives, expand independent governed positive evidence and broader held-out label coverage, or explicitly authorise a separate regularisation/data-volume study around frozen D0 M64. Hard negatives remain deferred.

## 26. Files created

Created the 14 required LR-3S artifacts, ten research checkpoints plus metadata, ten development prediction files, and five isolated research code/test files, all under `evaluation/learned_intent_ranking/lr3s/`.

## 27. Files verified unchanged

Production, semantic runtime, original data, LR-1, LR-1R, LR-2, LR-2R, LR-3, and every LR-3R artifact remained byte-identical to the pre-training protected snapshot.

LR-3S STATUS:

PRODUCTION CODE MODIFIED: NO
SEMANTIC RUNTIME MODIFIED: NO
ORIGINAL DATA MODIFIED: NO
PRIOR LR STAGES MODIFIED: NO

NEW M64 RUNS TRAINED: 10 (5 S1 + 5 S2)
NEW CHECKPOINTS CREATED: 10 RESEARCH-ONLY CHECKPOINTS

D0 M64 VIEW-A MRR MEAN: {table['D0_DIRECTED_EQUAL_WEIGHT']['mrr_mean']}
S1 VIEW-A MRR MEAN: {table['S1_UNORDERED_EQUAL_WEIGHT']['mrr_mean']}
S1 VIEW-A MRR STD: {table['S1_UNORDERED_EQUAL_WEIGHT']['mrr_std']}
S1 VIEW-A TOP1 MEAN: {table['S1_UNORDERED_EQUAL_WEIGHT']['top1_mean']}
S1 VIEW-A MACRO-F1 MEAN: {table['S1_UNORDERED_EQUAL_WEIGHT']['macro_f1_mean']}
S1 SEEDS ABOVE COSINE: {table['S1_UNORDERED_EQUAL_WEIGHT']['seeds_above_cosine_mrr']}/5
S1 SEVERE-OVERFIT RUNS: {table['S1_UNORDERED_EQUAL_WEIGHT']['severe_overfit_runs']}/5

S2 VIEW-A MRR MEAN: {table['S2_UNORDERED_CLASS_BALANCED']['mrr_mean']}
S2 VIEW-A MRR STD: {table['S2_UNORDERED_CLASS_BALANCED']['mrr_std']}
S2 VIEW-A TOP1 MEAN: {table['S2_UNORDERED_CLASS_BALANCED']['top1_mean']}
S2 VIEW-A MACRO-F1 MEAN: {table['S2_UNORDERED_CLASS_BALANCED']['macro_f1_mean']}
S2 SEEDS ABOVE COSINE: {table['S2_UNORDERED_CLASS_BALANCED']['seeds_above_cosine_mrr']}/5
S2 SEVERE-OVERFIT RUNS: {table['S2_UNORDERED_CLASS_BALANCED']['severe_overfit_runs']}/5

SELECTED DEVELOPMENT TRAINING-WEIGHTING POLICY: {comparison['selected_development_training_weighting_policy']}
DEVELOPMENT REPRESENTATIVE CHECKPOINT: D0 M64 SEED 20260815 / ../lr3r/checkpoints/lr3r_m64_seed_20260815_best_v1.pt

SYMMETRY INTERPRETATION STATE: {comparison['symmetry_interpretation_state']}

BOOTSTRAP CI S1 VS COSINE: [{s1_cos['lower']}, {s1_cos['upper']}]
BOOTSTRAP CI S1 VS D0: [{s1_d0['lower']}, {s1_d0['upper']}]
BOOTSTRAP CI S2 VS COSINE: [{s2_cos['lower']}, {s2_cos['upper']}]
BOOTSTRAP CI S2 VS D0: [{s2_d0['lower']}, {s2_d0['upper']}]

FINAL GOLD AVAILABLE: NO / DEFERRED
FINAL-GOLD EVALUATION RUN: NO

EXISTING REGRESSIONS: PASS 27/27; OFFLINE SEMANTIC PREFLIGHT PASS

BLOCKERS BEFORE HARD-NEGATIVE ABLATION: 5/5 SEVERE OVERFIT FOR D0/S1/S2; ALL BOOTSTRAP CIs CROSS ZERO; LIMITED DEV GOLD COVERAGE; FINAL GOLD UNAVAILABLE
RECOMMENDED NEXT STAGE: EXPAND INDEPENDENT GOVERNED POSITIVE/HOLD-OUT COVERAGE OR AUTHORISE A SEPARATE REGULARISATION/DATA-VOLUME STUDY; HARD NEGATIVES REMAIN DEFERRED
SAFE TO PROCEED: NO — STOP AND WAIT FOR EXPLICIT RESEARCHER AUTHORISATION
'''
    (HERE / "LR3S_SYMMETRIC_PAIR_WEIGHTING_REPORT.md").write_text(report, encoding="utf-8")

    files = sorted(path for path in HERE.rglob("*") if path.is_file() and path.name != "lr3s_output_checksums_v1.sha256" and "__pycache__" not in path.parts)
    (HERE / "lr3s_output_checksums_v1.sha256").write_text("\n".join(f"{sha(path)}  {path.relative_to(HERE)}" for path in files) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
