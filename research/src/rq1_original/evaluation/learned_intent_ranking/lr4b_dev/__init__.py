"""Governed RQ1-B development training package.

Only aggregate, text-free outputs from this package are eligible for Git.  Raw
representations, embeddings, predictions, histories, and checkpoints remain in
the explicitly ignored local paths declared below.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

STAGE = "RQ1-B"
STARTING_BRANCH = "research/rq1-a-r1-contract-repair"
STARTING_HEAD = "31d3b1ca64a3d3db1749ea4a32d97d181c2a70af"
STARTING_PARENT = "5b85d3171f57196678db9d0490f4f1be147ba0ea"
MAINLINE_HEAD = "8d3b6d6850bbf22c676371f613ad62e2389bd1e7"
TARGET_BRANCH = "research/rq1-b-lr4b-development"

FINAL_GOLD_ROOT = PurePosixPath(
    "evaluation/learned_intent_ranking/lr1r/primary_v3_input"
)
LOCAL_MODEL_RELATIVE = PurePosixPath(
    "semantic_runtime/models/all-mpnet-base-v2/"
    "e8c3b32edf5434bc2275fc9bab85f82640a19130"
)
LOCAL_ROOT = HERE / "local_artifacts"
EMBEDDING_DIR = LOCAL_ROOT / "embeddings"
PAIR_LEDGER_DIR = LOCAL_ROOT / "pair_ledgers"
PREDICTION_LEDGER_DIR = LOCAL_ROOT / "prediction_ledgers"
TRAINING_HISTORY_DIR = LOCAL_ROOT / "training_histories"
CHECKPOINT_DIR = HERE / "checkpoints"
RESULTS_DIR = HERE / "results"
TMP_DIR = HERE / "tmp"

SCENARIO_COUNTS = {"V0": 58, "V1": 131, "V2": 154, "V3": 316}
SCENARIO_ORDER = tuple(SCENARIO_COUNTS)
TRAINING_SEEDS = (20260813, 20260814, 20260815, 20260816, 20260817)
PAIR_SAMPLING_SEED = 20260813

VIEW_A = "VIEW_A_PAIRWISE_SEEN"
VIEW_B = "VIEW_B_SINGLETON_UNSEEN"
VIEW_C = "VIEW_C_MIXED"
VIEW_KEYS = (VIEW_A, VIEW_B, VIEW_C)
METRIC_KEYS = ("mrr", "top1_accuracy", "recall_at_3", "macro_f1")

SAFE_JSON_FILENAMES = (
    "rq1b_runtime_preflight_v1.json",
    "rq1b_token_budget_summary_v1.json",
    "rq1b_embedding_manifest_v1.json",
    "rq1b_c0_reproduction_v1.json",
    "rq1b_pair_construction_audit_v1.json",
    "rq1b_v0_reproduction_v1.json",
    "rq1b_per_seed_metrics_v1.json",
    "rq1b_scenario_comparison_v1.json",
    "rq1b_scenario_selection_v1.json",
    "rq1b_representative_checkpoint_manifest_v1.json",
    "rq1b_confusion_analysis_v1.json",
    "rq1b_overfit_analysis_v1.json",
    "rq1b_data_concentration_v1.json",
    "rq1b_development_uncertainty_v1.json",
    "rq1b_validation_report_v1.json",
)

DOC_FILENAMES = (
    "RQ1B_RUNTIME_AND_TOKEN_PREFLIGHT.md",
    "RQ1B_DEVELOPMENT_TRAINING_REPORT.md",
    "RQ1B_GOVERNED_EVIDENCE_EXPANSION_INTERPRETATION.md",
)
