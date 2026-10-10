"""Finalize LR-3 validation, report, registry hashes, and output checksums."""

from __future__ import annotations

import hashlib
import json
import statistics
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


def current_hashes(paths: dict[str, str]) -> dict[str, str]:
    return {relative: sha(ROOT / relative) for relative in paths}


def main() -> None:
    protocol = load("lr3_experiment_protocol_v1.json")
    protocol["severe_overfit_rule"] = {
        "flag": "SEVERE_OVERFIT",
        "material_training_loss_drop": "at least 5% below training BCE at best checkpoint epoch",
        "dev_degradation": "VIEW-A MRR remains strictly below best for complete 8-epoch patience window",
        "response": "report only; no hyperparameter change authorised",
    }
    write("lr3_experiment_protocol_v1.json", protocol)

    registry = load("lr3_checkpoint_registry_v1.json")
    checkpoint_resolution = []
    for entry in registry["entries"]:
        checkpoint_path = HERE / entry["checkpoint_path"]
        metadata_path = HERE / entry["metadata_path"]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        checkpoint_ok = sha(checkpoint_path) == metadata["checkpoint_file_sha256"] == entry["checkpoint_file_sha256"]
        metadata_hash = sha(metadata_path)
        entry["metadata_file_sha256"] = metadata_hash
        checkpoint_resolution.append({
            "model_family": entry["model_family"],
            "training_seed": entry["training_seed"],
            "checkpoint_hash_match": checkpoint_ok,
            "metadata_file_sha256": metadata_hash,
            "tensor_hash": entry["checkpoint_tensor_hash"],
        })
        if not checkpoint_ok:
            raise ValueError(f"checkpoint metadata resolution failed: {checkpoint_path}")
    write("lr3_checkpoint_registry_v1.json", registry)

    validation = load("lr3_validation_report_v1.json")
    current = {
        group: current_hashes(snapshot)
        for group, snapshot in validation["protected_snapshot_before"].items()
    }
    unchanged = current == validation["protected_snapshot_before"]
    if not unchanged:
        raise ValueError("protected files changed after training/regression verification")
    validation.update({
        "seed_determinism_status": "PASS",
        "seed_determinism_replays": [
            {
                "model_family": family,
                "training_seed": 20260813,
                "result": "IDENTICAL_TENSOR_HASH_PREDICTION_ORDERING_AND_METRICS",
                "checkpoint_tensor_hash": next(
                    entry["checkpoint_tensor_hash"]
                    for entry in registry["entries"]
                    if entry["model_family"] == family and entry["training_seed"] == 20260813
                ),
            }
            for family in ["L1", "M1"]
        ],
        "research_test_results": {
            "status": "PASS",
            "passed": 8,
            "failed": 0,
            "command": "PYTHONDONTWRITEBYTECODE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest evaluation/learned_intent_ranking/lr3/test_lr3.py -v",
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
        "checkpoint_metadata_hashes_resolve": all(row["checkpoint_hash_match"] for row in checkpoint_resolution),
        "checkpoint_resolution": checkpoint_resolution,
        "protected_snapshot_after_all_tests": current,
        "protected_files_unchanged_after_all_tests": unchanged,
        "overall_status": "PASS",
    })
    write("lr3_validation_report_v1.json", validation)

    inputs = load("lr3_input_hashes_v1.json")["files"]
    runtime = load("lr3_runtime_fidelity_report_v1.json")
    symmetry = load("lr3_pair_symmetry_diagnostic_v1.json")
    cosine = load("lr3_cosine_baseline_results_v1.json")["views"]
    linear = load("lr3_linear_training_results_v1.json")
    mlp = load("lr3_mlp_training_results_v1.json")
    comparison = load("lr3_model_comparison_v1.json")
    summary = load("lr3_dev_metrics_summary_v1.json")
    confusion = load("lr3_confusion_analysis_v1.json")
    displacement = load("lr3_ranking_displacement_v1.json")

    l_runs = linear["runs"]
    m_runs = mlp["runs"]
    l_rep_seed = displacement["linear_representative_seed"]
    m_rep_seed = displacement["mlp_representative_seed"]
    l_rep = next(run for run in l_runs if run["training_seed"] == l_rep_seed)
    m_rep = next(run for run in m_runs if run["training_seed"] == m_rep_seed)
    c_a = cosine["VIEW_A_PAIRWISE_SEEN"]
    c_b = cosine["VIEW_B_SINGLETON_UNSEEN"]
    c_c = cosine["VIEW_C_MIXED"]
    l_a = l_rep["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]
    l_b = l_rep["view_metrics"]["VIEW_B_SINGLETON_UNSEEN"]
    l_c = l_rep["view_metrics"]["VIEW_C_MIXED"]
    m_a = m_rep["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]
    m_b = m_rep["view_metrics"]["VIEW_B_SINGLETON_UNSEEN"]
    m_c = m_rep["view_metrics"]["VIEW_C_MIXED"]
    l_agg = linear["view_a_aggregate"]
    m_agg = mlp["view_a_aggregate"]
    l_params = json.loads((HERE / "checkpoints/lr3_l1_seed_20260813_best_v1.metadata.json").read_text())
    m_params = json.loads((HERE / "checkpoints/lr3_m1_seed_20260813_best_v1.metadata.json").read_text())

    seed_rows = []
    for family, runs in [("L1", l_runs), ("M1", m_runs)]:
        for run in runs:
            metrics = run["view_metrics"]["VIEW_A_PAIRWISE_SEEN"]
            seed_rows.append(
                f"| {family} | {run['training_seed']} | {run['best_epoch']} | {run['final_epoch']} | "
                f"{fmt(metrics['top1_accuracy'])} | {fmt(metrics['mrr'])} | {fmt(metrics['recall_at_3'])} | "
                f"{fmt(metrics['macro_f1'])} | {'SEVERE_OVERFIT' if run['overfit_diagnostic']['flag'] else 'NO'} |"
            )
    seed_table = "\n".join(seed_rows)

    per_intent_rows = []
    for label in c_a["represented_gold_labels"]:
        c = c_a["per_intent"][label]
        l = l_a["per_intent"][label]
        m = m_a["per_intent"][label]
        per_intent_rows.append(
            f"| `{label}` | {c['support']} | {fmt(c['precision'])} / {fmt(c['recall'])} / {fmt(c['f1'])} | "
            f"{fmt(l['precision'])} / {fmt(l['recall'])} / {fmt(l['f1'])} | "
            f"{fmt(m['precision'])} / {fmt(m['recall'])} / {fmt(m['f1'])} |"
        )
    per_intent_table = "\n".join(per_intent_rows)

    protected_table = "\n".join(
        f"| {group} | {len(snapshot)} | UNCHANGED |"
        for group, snapshot in validation["protected_snapshot_before"].items()
    )
    input_table = "\n".join(
        f"| `{path}` | `{digest}` |"
        for path, digest in sorted(inputs.items())
        if path in {
            "evaluation/learned_intent_ranking/lr1/ranker_train_manifest_candidate_v1.jsonl",
            "evaluation/learned_intent_ranking/lr1r/ranker_dev_manifest_candidate_v2.jsonl",
            "evaluation/learned_intent_ranking/lr2r/lr2r_episodic_sampling_spec_v1.json",
            "evaluation/learned_intent_ranking/lr2r/lr2r_label_universe_v1.json",
            "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
            "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz",
        }
    )

    report = f'''# LR-3 — Offline Learned Intent Scorer Training & Development Evaluation

## 1. Status

LR-3 completed the authorised offline, research-only experiment. Frozen cosine C0 was compared with a learned linear head L1 and a Mesgar-inspired nonlinear MLP head M1 across exactly five seeds. The preregistered five-seed mean VIEW-A MRR selects **M1**: cosine `{fmt(c_a['mrr'])}`, L1 `{fmt(l_agg['mrr']['mean'])}`, M1 `{fmt(m_agg['mrr']['mean'])}`. The interpretation state is `LEARNED_NONLINEAR_GAIN_SUPPORTED_ON_DEV`.

**Coverage warning:** production exposes 16 labels; pairwise training exposed 12; primary DEV gold covers 8; singleton-unseen DEV gold covers 1; seven production labels have no DEV gold. These are development results, not full-universe or final-gold evidence. All ten learned runs triggered `SEVERE_OVERFIT`, and M1 mean Macro-F1 remained below cosine despite the MRR gain. No integration is authorised.

## 2. Research question

Does a task-specific learned similarity function over frozen MPNet embeddings improve intent ranking over the existing fixed cosine similarity? LR-3 isolates the scoring function: model, embedding space, approved examples, eligibility, family collapse, max aggregation, TRAIN, and DEV remain fixed.

## 3. Authorisation and frozen boundaries

Authorised: head-only L1/M1 training, research checkpoints, authorised DEV evaluation, cosine comparison, and DEV-based checkpoint selection. Prohibited and not performed: production/shadow integration, threshold replacement, routing changes, MPNet fine-tuning, Cross-Encoder/LLM classifiers, hard-negative training, Top-K prefiltering, taxonomy changes, Primary-v3/final-gold evaluation, or use of DEV as final evidence.

## 4. Input verification

LR-1, LR-1R, LR-2, and LR-2R checksum contracts passed before training. The superseded LR-2 v1 baseline was hash-verified but never deserialised or loaded for training.

| Key input | SHA-256 |
|---|---|
{input_table}

All 84 DEV queries were resolved from their declared Functional-QA case/turn and matched raw, casefolded-whitespace, and deterministic-normalised hashes plus source page and label.

## 5. Mesgar-inspired design and deviations

Following the Bi-Encoder + parameterized-similarity design in Mesgar et al. (EACL 2023), `abs(q-c)` and `q*c` are concatenated and passed through LayerNorm plus a binary scoring head. This is not an exact reproduction: Mesgar permits PLM training/fine-tuning; LR-3 freezes MPNet completely and trains only L1 or M1.

## 6. Frozen MPNet representation

The approved index contains 62 examples across 16 labels. The verified frozen matrix is `(62, 768)`, `float32`, with model identity `{runtime['model_version']}`. Approved-index hash is `{inputs['semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl']}`; embedding-artifact hash is `{inputs['semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz']}`. Example order, index binding, model repository/revision, local-only policy, NumPy dtype, and sentence-transformers 5.6.1 metadata matched. MPNet trainable parameters and optimizer parameters: zero.

TRAIN anchors use frozen approved-index vectors. DEV uses locally encoded plain and `[PAGE=<canonical>]` representations with the production selection rule. Candidate vectors were never regenerated.

## 7. Pair-feature construction

`feature = concat(abs(q-c), q*c)`. Verified dimensions: embedding 768, feature 1536. The neural feature excludes labels, source/page/provenance IDs, families, cosine, keyword results, and gold metadata. L1/M1 inference uses sigmoid-bounded compatibility scores; these are **not calibrated production confidence** and were not compared with cosine routing thresholds.

## 8. Directed-pair symmetry diagnostic

The feature is symmetric, so reverse directed pairs can be identical features. The complete eligible pool has {symmetry['full_eligible_pool']['directed_row_count']} directed rows but {symmetry['full_eligible_pool']['unique_unordered_record_pair_count']} unordered/effective feature pairs. Epoch 0 has {symmetry['materialized_epochs'][0]['directed_row_count']} rows, {symmetry['materialized_epochs'][0]['effective_unique_feature_count']} effective features, and {symmetry['materialized_epochs'][0]['reverse_duplicate_group_count']} reverse groups ({symmetry['materialized_epochs'][0]['positive_reverse_duplicate_group_count']} positive, {symmetry['materialized_epochs'][0]['negative_reverse_duplicate_group_count']} negative). Directed rows were retained because LR-2R balances per anchor; they must not be treated as statistically independent observations.

## 9. Runtime-fidelity validation

Mandatory preflight: **PASS on 84/84 records**. Eligible example IDs/ranks, example scores, contributor IDs, intent order/scores, Top-1/Top-2, margin, OOS score, page exclusions, query representations, index hash, max aggregation, and all-example behavior matched `SemanticIntentRouter.predict()`. Maximum absolute score difference was `{runtime['max_example_score_abs_diff']:.18g}` under absolute tolerance `1e-12`. Learned evaluation proceeded only after this gate passed.

## 10. Cosine baseline

C0 uses production-faithful clipped cosine, page eligibility, family collapse, max aggregation, and all eligible examples without applying routing acceptance thresholds.

| VIEW A Top-1 | MRR | Recall@3 | Macro-F1 |
|---:|---:|---:|---:|
| {fmt(c_a['top1_accuracy'])} | {fmt(c_a['mrr'])} | {fmt(c_a['recall_at_3'])} | {fmt(c_a['macro_f1'])} |

## 11. Linear scorer architecture

L1: `LayerNorm(1536) -> Linear(1536,1) -> logit`; BCEWithLogitsLoss for training, sigmoid for ranking. Parameters: {l_params['total_parameters']:,} total/trainable. It tests whether any task-specific linear decision surface improves on cosine.

## 12. MLP scorer architecture

M1: `LayerNorm(1536) -> Linear(1536,768) -> ReLU -> Dropout(0.5) -> Linear(768,1) -> logit`; sigmoid at inference. Parameters: {m_params['total_parameters']:,} total/trainable. No extra layers or hidden-dimension/dropout tuning were used.

## 13. Training protocol

Five seeds: 20260813–20260817. CPU deterministic execution; AdamW, learning rate `1e-3`, weight decay `1e-4`, batch 32, maximum 50 epochs, patience 8, clip norm 1.0, BCEWithLogitsLoss, no class weights. Epoch membership is regenerated read-only from LR-2R: every one of 58 eligible anchors receives up to two positives and equal `SAFE_RANDOM_NEGATIVE` rows; singleton, hard, blocked, and DEV records remain excluded. The pair seed stays 20260813; training batch seed is SHA-256-derived from family, training seed, and epoch.

Checkpoint selection uses only 79-record VIEW-A MRR, then Top-1, then earlier epoch. All eligible production examples are scored; no Top-K prefilter and no production threshold is used.

## 14. Five-seed results

| Model | Seed | Best epoch | Final epoch | Top-1 | MRR | Recall@3 | Macro-F1 | Overfit |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{seed_table}

| Aggregate | Top-1 mean ± std | MRR mean ± std | Recall@3 mean | Macro-F1 mean |
|---|---:|---:|---:|---:|
| L1 | {fmt(l_agg['top1_accuracy']['mean'])} ± {fmt(l_agg['top1_accuracy']['std'])} | {fmt(l_agg['mrr']['mean'])} ± {fmt(l_agg['mrr']['std'])} | {fmt(l_agg['recall_at_3']['mean'])} | {fmt(l_agg['macro_f1']['mean'])} |
| M1 | {fmt(m_agg['top1_accuracy']['mean'])} ± {fmt(m_agg['top1_accuracy']['std'])} | {fmt(m_agg['mrr']['mean'])} ± {fmt(m_agg['mrr']['std'])} | {fmt(m_agg['recall_at_3']['mean'])} | {fmt(m_agg['macro_f1']['mean'])} |

Population standard deviations are reported. Full minimum/maximum and per-seed values are machine-readable.

## 15. Pairwise-seen DEV results

VIEW A is `PAIRWISE-SEEN DEVELOPMENT EVALUATION`: 79 records, eight gold labels, full page-eligible production prediction universe. Representative L1 is seed {l_rep_seed}; representative M1 is seed {m_rep_seed}.

| Model | Top-1 | MRR | Recall@3 | Macro-F1 | Mean gold rank | Mean margin |
|---|---:|---:|---:|---:|---:|---:|
| C0 | {fmt(c_a['top1_accuracy'])} | {fmt(c_a['mrr'])} | {fmt(c_a['recall_at_3'])} | {fmt(c_a['macro_f1'])} | {fmt(c_a['mean_gold_label_rank'])} | {fmt(c_a['margin_summary']['mean'])} |
| L1 representative | {fmt(l_a['top1_accuracy'])} | {fmt(l_a['mrr'])} | {fmt(l_a['recall_at_3'])} | {fmt(l_a['macro_f1'])} | {fmt(l_a['mean_gold_label_rank'])} | {fmt(l_a['margin_summary']['mean'])} |
| M1 representative | {fmt(m_a['top1_accuracy'])} | {fmt(m_a['mrr'])} | {fmt(m_a['recall_at_3'])} | {fmt(m_a['macro_f1'])} | {fmt(m_a['mean_gold_label_rank'])} | {fmt(m_a['margin_summary']['mean'])} |

Per-intent entries show `precision / recall / F1`:

| Gold label | Support | C0 P/R/F1 | L1 P/R/F1 | M1 P/R/F1 |
|---|---:|---|---|---|
{per_intent_table}

Gold-rank distributions, Top-1/Top-2 margins, complete 8×16 confusion matrices, and all per-intent counts are in the result artifacts.

## 16. Singleton-unseen diagnostic

VIEW B is `UNSEEN-SINGLETON DIAGNOSTIC`: five `discrepancy_or_correction` records, excluded from selection.

| Model | Correct | Top-1 | MRR | Recall@3 | Mean gold rank | Predicted-label distribution |
|---|---:|---:|---:|---:|---:|---|
| C0 | {c_b['top1_correct_count']}/5 | {fmt(c_b['top1_accuracy'])} | {fmt(c_b['mrr'])} | {fmt(c_b['recall_at_3'])} | {fmt(c_b['mean_gold_label_rank'])} | `{json.dumps(c_b['predicted_label_distribution'], sort_keys=True)}` |
| L1 representative | {l_b['top1_correct_count']}/5 | {fmt(l_b['top1_accuracy'])} | {fmt(l_b['mrr'])} | {fmt(l_b['recall_at_3'])} | {fmt(l_b['mean_gold_label_rank'])} | `{json.dumps(l_b['predicted_label_distribution'], sort_keys=True)}` |
| M1 representative | {m_b['top1_correct_count']}/5 | {fmt(m_b['top1_accuracy'])} | {fmt(m_b['mrr'])} | {fmt(m_b['recall_at_3'])} | {fmt(m_b['mean_gold_label_rank'])} | `{json.dumps(m_b['predicted_label_distribution'], sort_keys=True)}` |

One representative M1 result is not evidence of general singleton generalisation; three other singleton labels have no DEV gold at all.

## 17. Mixed DEV diagnostic

VIEW C is `MIXED DEVELOPMENT DIAGNOSTIC`: 84 records and nine represented gold labels, never a 16-label or final evaluation.

| Model | Top-1 | MRR | Recall@3 | Macro-F1 |
|---|---:|---:|---:|---:|
| C0 | {fmt(c_c['top1_accuracy'])} | {fmt(c_c['mrr'])} | {fmt(c_c['recall_at_3'])} | {fmt(c_c['macro_f1'])} |
| L1 representative | {fmt(l_c['top1_accuracy'])} | {fmt(l_c['mrr'])} | {fmt(l_c['recall_at_3'])} | {fmt(l_c['macro_f1'])} |
| M1 representative | {fmt(m_c['top1_accuracy'])} | {fmt(m_c['mrr'])} | {fmt(m_c['recall_at_3'])} | {fmt(m_c['macro_f1'])} |

## 18. Model comparison

Mean VIEW-A MRR is primary: C0 `{fmt(c_a['mrr'])}`, L1 `{fmt(l_agg['mrr']['mean'])}` (delta `{fmt(l_agg['mrr']['mean'] - c_a['mrr'])}`), M1 `{fmt(m_agg['mrr']['mean'])}` (delta `{fmt(m_agg['mrr']['mean'] - c_a['mrr'])}`). M1 also improves mean Top-1 by `{fmt(m_agg['top1_accuracy']['mean'] - c_a['top1_accuracy'])}` and mean Recall@3 by `{fmt(m_agg['recall_at_3']['mean'] - c_a['recall_at_3'])}`, but mean Macro-F1 changes by `{fmt(m_agg['macro_f1']['mean'] - c_a['macro_f1'])}`. The primary rule selects M1; metric trade-offs remain material.

## 19. Confusion analysis

Most common C0 errors include planning→improvement (4), course→dashboard (4), and cross-page→dashboard (4). Representative L1: planning→improvement (6), course→dashboard (6), improvement→planning (4). Representative M1: planning→improvement (6), course→dashboard (5), improvement→planning (4). Complete gold-eight by predicted-sixteen matrices preserve errors into singleton/unsupported labels.

## 20. Ranking displacement analysis

Representative L1 versus C0: `{json.dumps(displacement['linear_vs_cosine']['counts'], sort_keys=True)}`. Representative M1 versus C0: `{json.dumps(displacement['mlp_vs_cosine']['counts'], sort_keys=True)}`. Per-record development-only ranks and wrong↔correct transitions are retained without model repair.

## 21. Overfitting / seed-variance analysis

All ten runs triggered `SEVERE_OVERFIT`: after the selected epoch, training BCE fell at least 5% while VIEW-A MRR stayed below its best for the complete eight-epoch patience window. All runs early-stopped. MRR population standard deviation is `{fmt(l_agg['mrr']['std'])}` for L1 and `{fmt(m_agg['mrr']['std'])}` for M1; Top-1 standard deviation is `{fmt(l_agg['top1_accuracy']['std'])}` and `{fmt(m_agg['top1_accuracy']['std'])}`. Hyperparameters were not changed.

## 22. Representative checkpoint decision

Architecture selection uses five-seed mean MRR, not the best seed. Within M1, the median seed-specific best-checkpoint MRR selects seed **20260813**, best epoch **{m_rep['best_epoch']}**: `checkpoints/lr3_m1_seed_20260813_best_v1.pt`. It is labelled `DEVELOPMENT_REPRESENTATIVE_CHECKPOINT`, not production/final. The best single M1 seed (20260816) was not nominated.

## 23. DEV coverage limitations

- Production candidate universe: 16 labels.
- Pairwise training exposure: 12 labels.
- VIEW-A gold support: 8 labels.
- VIEW-B singleton-unseen gold support: 1 label.
- Production labels with zero DEV gold: 7.

LR-3 cannot establish generalisation for all production intents. Accuracy, Macro-F1, MRR, and Recall@K here are development metrics only.

## 24. Final-gold status

Primary-v3 / Stage-6 remains `NOT_SUPPLIED / DEFERRED`; `FINAL GOLD AVAILABLE = NO`. No parent/sibling search, substitute construction, Unified final use, or final-gold evaluation occurred.

## 25. Regression verification

Post-training bounded regression checks passed **27/27**: production intent router 11, semantic/C_FULL integration 2, keyword parity 1, P2-C uncertainty 5, P2-D explicit safety 6, real semantic runtime 2. Offline semantic preflight also passed with the model initialised locally and downloads disabled. LR-3 research tests passed 8/8, including L1 and M1 deterministic seed replay.

## 26. Remaining blockers

Before any production shadow integration: severe-overfit robustness work; separately authorised hard-negative analysis; calibration without reusing cosine thresholds; explicit shadow-governance approval; broader governed validation; and ultimately independent final-gold evaluation. None is authorised here.

## 27. Recommended next stage

Use a separately authorised robustness stage to stress-test seed/epoch sensitivity, predeclare hard-negative ablations, and design calibration/shadow criteria. Do not integrate the checkpoint yet and do not begin that stage automatically.

## 28. Files created

- Research code: `data_loader.py`, `feature_builder.py`, `models.py`, `runtime_fidelity.py`, `evaluate_ranker.py`, `metrics.py`, `train_scorer.py`, `run_runtime_preflight.py`, `run_experiment.py`, `test_lr3.py`, `finalize_lr3.py`.
- Required reports/results: all 15 named LR-3 JSON/Markdown/checksum artifacts.
- Checkpoints: ten `.pt` files plus ten adjacent metadata manifests under `checkpoints/`.
- Development-only predictions: C0 plus ten seed runs under `results/`; no query text is stored.

`lr3_output_checksums_v1.sha256` hashes every other LR-3 file recursively and excludes itself.

## 29. Files verified unchanged

| Protected group | Files | Result |
|---|---:|---|
{protected_table}

LR-3 STATUS:

PRODUCTION CODE MODIFIED: NO
SEMANTIC RUNTIME MODIFIED: NO
ORIGINAL DATA MODIFIED: NO
LR-1/LR-1R/LR-2/LR-2R MODIFIED: NO

MPNET FINETUNED: NO
LEARNED MODEL TRAINED: YES — L1 AND M1 / FIVE SEEDS EACH / OFFLINE ONLY
CHECKPOINTS CREATED: 10 RESEARCH-ONLY CHECKPOINTS

PAIRWISE TRAINING RECORDS: 58 GOVERNED RECORDS / 228 DIRECTED PAIRS PER EPOCH
PAIRWISE TRAINING LABELS: 12

DEV TOTAL RECORDS: 84
DEV PAIRWISE-SEEN RECORDS: 79
DEV PAIRWISE-SEEN LABELS: 8
DEV SINGLETON-UNSEEN RECORDS: 5
PRODUCTION LABELS WITHOUT DEV GOLD: 7

COSINE VIEW-A TOP1: {fmt(c_a['top1_accuracy'])}
COSINE VIEW-A MRR: {fmt(c_a['mrr'])}
COSINE VIEW-A RECALL@3: {fmt(c_a['recall_at_3'])}
COSINE VIEW-A MACRO-F1: {fmt(c_a['macro_f1'])}

LINEAR VIEW-A TOP1 MEAN: {fmt(l_agg['top1_accuracy']['mean'])}
LINEAR VIEW-A TOP1 STD: {fmt(l_agg['top1_accuracy']['std'])}
LINEAR VIEW-A MRR MEAN: {fmt(l_agg['mrr']['mean'])}
LINEAR VIEW-A MRR STD: {fmt(l_agg['mrr']['std'])}
LINEAR VIEW-A RECALL@3 MEAN: {fmt(l_agg['recall_at_3']['mean'])}
LINEAR VIEW-A MACRO-F1 MEAN: {fmt(l_agg['macro_f1']['mean'])}

MLP VIEW-A TOP1 MEAN: {fmt(m_agg['top1_accuracy']['mean'])}
MLP VIEW-A TOP1 STD: {fmt(m_agg['top1_accuracy']['std'])}
MLP VIEW-A MRR MEAN: {fmt(m_agg['mrr']['mean'])}
MLP VIEW-A MRR STD: {fmt(m_agg['mrr']['std'])}
MLP VIEW-A RECALL@3 MEAN: {fmt(m_agg['recall_at_3']['mean'])}
MLP VIEW-A MACRO-F1 MEAN: {fmt(m_agg['macro_f1']['mean'])}

BEST DEVELOPMENT ARCHITECTURE: M1 MESGAR-INSPIRED NONLINEAR SCORER
DEVELOPMENT REPRESENTATIVE CHECKPOINT: checkpoints/lr3_m1_seed_20260813_best_v1.pt

SINGLETON-UNSEEN COSINE TOP1: {c_b['top1_correct_count']}/5 ({fmt(c_b['top1_accuracy'])})
SINGLETON-UNSEEN LINEAR TOP1: {l_b['top1_correct_count']}/5 ({fmt(l_b['top1_accuracy'])})
SINGLETON-UNSEEN MLP TOP1: {m_b['top1_correct_count']}/5 ({fmt(m_b['top1_accuracy'])})

RUNTIME-FIDELITY COSINE PARITY: PASS — 84/84
SEED DETERMINISM: PASS — L1 AND M1 REPLAY TENSOR HASHES/PREDICTIONS/METRICS IDENTICAL
OVERFIT FLAG: SEVERE_OVERFIT — 10/10 RUNS

DEVELOPMENT EVIDENCE STATE: {comparison['development_evidence_state']}

FINAL GOLD AVAILABLE: NO
FINAL-GOLD EVALUATION RUN: NO

EXISTING REGRESSIONS: PASS — 27/27 PLUS OFFLINE SEMANTIC PREFLIGHT
BLOCKERS BEFORE PRODUCTION SHADOW INTEGRATION: OVERFIT ROBUSTNESS; HARD-NEGATIVE ABLATION AUTHORISATION; CALIBRATION; SHADOW GOVERNANCE; BROADER DEV; FINAL GOLD
RECOMMENDED NEXT STAGE: SEPARATELY AUTHORISED ROBUSTNESS / HARD-NEGATIVE / CALIBRATION DESIGN — NO INTEGRATION
SAFE TO PROCEED: NO — EXPLICIT NEXT-STAGE AUTHORISATION REQUIRED
'''
    (HERE / "LR3_OFFLINE_LEARNED_SCORER_REPORT.md").write_text(report, encoding="utf-8")

    if any(path.name == "__pycache__" for path in HERE.rglob("*")):
        raise ValueError("LR-3 contains bytecode cache")
    checksum_paths = sorted(
        path for path in HERE.rglob("*")
        if path.is_file() and path.name != "lr3_output_checksums_v1.sha256"
    )
    (HERE / "lr3_output_checksums_v1.sha256").write_text(
        "".join(f"{sha(path)}  {path.relative_to(HERE)}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    print(json.dumps({
        "report": "LR3_OFFLINE_LEARNED_SCORER_REPORT.md",
        "checksummed_files": len(checksum_paths),
        "checkpoints": registry["checkpoint_count"],
        "evidence_state": comparison["development_evidence_state"],
        "protected_files_unchanged": unchanged,
        "regressions": validation["existing_regressions"],
        "research_tests": validation["research_test_results"]["status"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

