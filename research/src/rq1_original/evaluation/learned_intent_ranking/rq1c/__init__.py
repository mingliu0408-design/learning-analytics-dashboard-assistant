"""RQ1-C0-R2 repaired sealed final-evaluation harness.

This package may operate on safe authority metadata, synthetic fixtures,
authorised DEV data, the frozen candidate index, and the five frozen V0
checkpoints.  Only :mod:`sealed_access` may open the raw Track-A asset, and
that entry point is reserved for a separately authorised RQ1-C1 execution.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

BASE_BRANCH = "research/rq1-b-lr4b-development"
BASE_HEAD = "551007d7ef46583933501da29db2db0909934343"
BASE_PARENT = "31d3b1ca64a3d3db1749ea4a32d97d181c2a70af"
R1_HARNESS_BRANCH = "research/rq1-c0-r1-final-evaluation-harness"
R1_HARNESS_HEAD = "ec9bcd6fe435cb8c772feb6d0a0a625eb0c91b5e"
R1_HARNESS_PARENT = BASE_HEAD
TARGET_BRANCH = "research/rq1-c0-r2-final-harness-repair"

AUTHORITY_BRIDGE_PATH = Path(
    "external_inputs/RQ1_C_PRIMARY_V3_AUTHORITY_BRIDGE_2026-08-25.zip"
)
AUTHORITY_BRIDGE_SHA256 = (
    "d6455d3e877ca9def32b60f2bbaba7f7485bb4f88f1e3086f467713cb624a9d9"
)
AUTHORITY_CANDIDATE_NAME = (
    "RQ1C_PRIMARY_V3_FINAL_GOLD_AUTHORITY_CANDIDATE_V1.json"
)
AUTHORITY_CANDIDATE_SHA256 = (
    "aca437b1969a69b8b661b924e265c5cd26a9a72ec84a9a206b182959588c18dc"
)
AUTHORITY_BRIDGE_MEMBERS = (
    "RQ1C_AUTHORITY_BRIDGE_CHECKSUMS.sha256",
    "RQ1C_PRIMARY_V3_AUTHORITY_BRIDGE_REPORT.md",
    AUTHORITY_CANDIDATE_NAME,
)

TRACK_A_ALIAS = "PRIMARY_V3_TRACK_A_RQ1_FINAL_GOLD_V1"
TRACK_A_FILE_NAME = (
    "primary_v3_semantic_heldout_human_review_researcher_final_v1.csv"
)
TRACK_A_RELATIVE_PATH = PurePosixPath(
    "evaluation/learned_intent_ranking/rq1c/local_final_gold/"
    + TRACK_A_FILE_NAME
)
TRACK_A_SHA256 = (
    "5d40f0a4a6b460e77271ee9815fce1b0954c1d7e05c7a4cd2f5d8e28ff09eb8f"
)
TRACK_A_SIZE_BYTES = 129_236

TRACK_B_FILE_NAME = (
    "primary_v3_hybrid_context_human_review_researcher_final_v1.csv"
)
TRACK_B_SHA256 = (
    "52c14dbc9e79b3c211e47ffd72697ec6ed87eec0478353066eb5d2f1ab45f351"
)

AUTHORITY_CONTRACT_RELATIVE = PurePosixPath(
    "evaluation/learned_intent_ranking/rq1c/"
    "rq1c_final_gold_authority_contract_v1.json"
)
AUTHORITY_CONTRACT_SHA256 = (
    "16d1c81c3e23f01746200f9517732b24150970ca570443cef695f131e7ee2a00"
)
LOCAL_ARTIFACTS_RELATIVE = PurePosixPath(
    "evaluation/learned_intent_ranking/rq1c/local_artifacts"
)
LOCK_FILE_NAME = "FINAL_GOLD_ACCESS_CONSUMED_V1.json"
FINAL_RESULT_RELATIVE = PurePosixPath(
    "evaluation/learned_intent_ranking/rq1c/final_results_local/"
    "rq1c_final_evaluation_results_v1.json"
)
FINAL_RESULT_TEMP_FILE_NAME = ".rq1c_final_evaluation_results_v1.json.tmp"

V0_SEEDS = (20260813, 20260814, 20260815, 20260816, 20260817)
REPRESENTATIVE_SEED = 20260815

STATISTICAL_CONTRACT_SHA256 = (
    "36e2f9894a00eb2988661a2982080dbd3bbc42e19b06f270855e472e3169a69f"
)
STATISTICAL_MODULE_SHA256 = (
    "c0f1d2197976a0c5f425f3844271f8a54942f5cf68c398f8d1664b41f6602f38"
)
EFFECTIVE_EXPERIMENT_CONTRACT_SHA256 = (
    "e1e97e9c781a5b549caacf02aac66cc54057a934889a1c3910ccf31a1bcfa2b1"
)

LABEL_UNIVERSE = (
    "access_or_capability_question",
    "course_content_question",
    "cross_page_relationship",
    "dashboard_interpretation",
    "discrepancy_or_correction",
    "emotional_or_justification",
    "hybrid_course_and_planning",
    "improvement_recommendation",
    "metric_clarification",
    "out_of_scope",
    "planning_or_strategy",
    "quantitative_metric_query",
    "reflection_structure_question",
    "social_interaction",
    "technical_data_question",
    "unsupported_task",
)
