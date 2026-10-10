"""RQ2-V2 Stage 4-0 DEV-only protocol and deterministic CV freeze.

This package contains research protocol metadata and validation helpers only.
It does not train, invoke, or evaluate a Router.
"""

from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent

DEV_CV_SEED = 20260831
FEATURE_PROFILE = "R2V2_PRIMARY_SEMANTIC_INPUT_V1"
STARTING_HEAD = "ae30c78c00c88768f8c5b9622d3b48216a859a91"
EXPECTED_BRANCH = "research/rq2-v2-stage4-dev-protocol"
EXPECTED_COMMIT_SUBJECT = (
    "RQ2-V2 Stage 4-0: freeze DEV calibration protocol and CV folds"
)
READY_STATUS = "READY_FOR_PARALLEL_RQ2_V2_STAGE_4_DEV_MODEL_TRACKS"

DEV_RELEASE_BASENAME = "RQ2_V2_DEV_ONLY_DATA_RELEASE_2026-08-31.zip"
DEV_RELEASE_SHA256 = (
    "accc086f91a8c8a7e1e94ce1ab45f5de5266d38265b1c2a59ff3571ee0218066"
)
STAGE3C_RELEASE_BASENAME = (
    "RQ2_V2_STAGE_3C_CONTRAST_SAFE_SPLIT_FREEZE_REVIEW_2026-08-31.zip"
)
STAGE3C_RELEASE_SHA256 = (
    "75ff94a88a40ae6e58b297a4e93f6ef84e2a2441d9735284aa8b2d0f47183b5d"
)

DEV_ALLOWED_MEMBERS = (
    "DEV_README.md",
    "DEV_SHA256_MANIFEST.json",
    "dev_capability_gold_v1.csv",
    "dev_capability_gold_v1.jsonl",
)

MODEL_IDS = (
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_LLM",
    "R2V2-P1_HYBRID",
)

PRIMARY_SEMANTIC_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
B1_HISTORICAL_FIELDS = ("current_query", "current_page")
CAPABILITY_NAMES = ("RAG", "Memory", "Planning")
ANSWER_SIGNATURES = tuple(f"{value:03b}" for value in range(8))
ROUTING_SIGNATURES = (*ANSWER_SIGNATURES, "CLARIFY")
LAD_PAGES = ("Debate", "Lecture", "Overview", "Reflection", "Resources")
FOLD_IDS = tuple(f"DEV-CV-FOLD-{value}" for value in range(1, 5))
