"""Frozen identities and paths for the authorized RQ2-V2 Stage 5E run."""

from __future__ import annotations

from pathlib import Path


FINAL_SCORING_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FINAL_SCORING_DIR.parents[2]
STAGE4_ROOT = PROJECT_ROOT / "evaluation/capability_routing_rq2_v2_stage4"
STAGE5_ROOT = PROJECT_ROOT / "evaluation/capability_routing_rq2_v2_stage5"

EXPECTED_WORKTREE = Path(
    "external_inputs/stage5-e-final-scoring"
)
EXPECTED_BRANCH = "research/rq2-v2-stage5-e-final-scoring"
STARTING_HEAD = "dcce63c3bdb25c695d37537c926284734dbc8860"

INTEGRATED_COMMITS = (
    (
        "641f0b3ad871d216184a6ae983af15b0f69f4311",
        "4ed8632decba4afe511bed712a8a674184717bfd",
        "RQ2-V2 Stage 4N-R1: freeze final Router selection for RQ3",
    ),
    (
        "82ff279fcc095bbfaeeda3f0bd2122d39e8c4057",
        "ed84c4a334e1d34ab49e8327758072621f0a39db",
        "RQ2-V2 Stage 5A: execute frozen deterministic methods on TEST",
    ),
    (
        "919dbfdbe96f36ca0bc010f6d65017ece126612d",
        "1189e501f92b53fe32abe4b4e0366a2fdcd66ad2",
        "RQ2-V2 Stage 5B: execute frozen B4 on TEST",
    ),
    (
        "770916af3c7f371590e6efa9248a95b66e968a14",
        "4a3c6353cdd9f1fc50d1d6ce99a16d9a9ddb8a87",
        "RQ2-V2 Stage 5C: execute frozen RAG Specialist on TEST",
    ),
    (
        "fb548930e12aea41f6a824f35ad1ccf7a2ec0979",
        "65259afa3be84dc9b4195743ed6c88ccacef1c18",
        "RQ2-V2 Stage 5D: execute frozen Memory Specialist on TEST",
    ),
)

DETERMINISTIC_PATH = (
    STAGE5_ROOT
    / "track_a_deterministic_test_predictions/deterministic_test_terminal_results_v1.jsonl"
)
B4_PATH = (
    STAGE5_ROOT
    / "track_b_b4_test_predictions/b4_test_terminal_results_v1.jsonl"
)
RAG_SPECIALIST_PATH = (
    STAGE5_ROOT
    / "track_c_rag_specialist_test_predictions/rag_specialist_test_terminal_results_v1.jsonl"
)
MEMORY_SPECIALIST_PATH = (
    STAGE5_ROOT
    / "track_d_memory_specialist_test_predictions/memory_specialist_test_terminal_results_v1.jsonl"
)

PREDICTION_HASHES = {
    str(DETERMINISTIC_PATH.relative_to(PROJECT_ROOT)): (
        "3f0cad65e0d08a011e7514ddcce10fda4ac4fcb4b2d104ed6ae4e0c0e2b67f90"
    ),
    str(B4_PATH.relative_to(PROJECT_ROOT)): (
        "f8c0c0e8e1debc34b99107ee6b1850391a911bfcb15e16be82bcb54c562d5270"
    ),
    str(RAG_SPECIALIST_PATH.relative_to(PROJECT_ROOT)): (
        "bb3cc640c61e0986acb1c664a684f6b3b476c1940a6fc2fd456871725885cf75"
    ),
    str(MEMORY_SPECIALIST_PATH.relative_to(PROJECT_ROOT)): (
        "a731107848b8816a67cd889e411ab2cf82a9c4dfbaff903dd5f4cdae15fa2cb5"
    ),
}

ELIGIBILITY_PATH = (
    STAGE4_ROOT / "final_router_selection/final_router_selection_eligibility_v1.json"
)
SELECTION_RULE_PATH = (
    STAGE4_ROOT / "final_router_selection/final_router_selection_rule_v1.json"
)
SELECTION_IMPLEMENTATION_PATH = STAGE4_ROOT / "final_router_selection/selection_rule.py"
METHOD_REGISTRY_PATH = STAGE4_ROOT / "final_integration/final_method_registry_v1.json"
SCORING_PROTOCOL_PATH = STAGE4_ROOT / "final_integration/final_test_scoring_protocol_v1.json"
BINDING_PATH = STAGE4_ROOT / "final_router_selection/RQ2_FINAL_ROUTER_FOR_RQ3.json"

ELIGIBILITY_SHA256 = "ce09cb5ec5bd718b77686e755e97f17d05fb99fb9a507a7c6f1425a20052bca3"
SELECTION_RULE_SHA256 = "afdb2d37117e025810a2086e2a2133a5a88a2ee735b2a67477a295cec1e044f9"
METHOD_REGISTRY_SHA256 = "14de4a304fa351ee7491d2fd9207fe0a9364c9367ad017d33e6cdb3cec75fac7"
SCORING_PROTOCOL_SHA256 = "1612a17a81e2defc441b6d085fd4b2fbff4306175f7df3aff29cfd0ee81fc5ef"

ESCROW_ZIP = Path("external_inputs/RQ2_V2_TEST_ESCROW_2026-08-31.zip")
ESCROW_ZIP_SHA256 = "6a07f32d4777cb9c31a1974a96f8c9e5bb5ff498c2c2fd5254334ef297e83fdf"
ESCROW_MEMBER_HASHES = {
    "FROZEN_SPLIT_SUMMARY.md": "05108de9a4850799de315a868904e579be4508959e2a18d8ef16c83cec633887",
    "TEST_ESCROW_SHA256_MANIFEST.json": "086f443fcf812478400b6660dc963b60cc895ae8e018000e133751131aa1de9d",
    "test_gold_escrow_v1.csv": "7c235ab230b6cdb0f477558a9302eec2775bcceace63ddb95dc68f9ba8025c05",
    "test_gold_escrow_v1.jsonl": "71b3de9500939f7605ea13bc8615072e92a05e398125f29b18a41b4717801341",
    "test_inputs_frozen_v1.csv": "96e5926a1c3165d3d28378fd5302c76c43867a7a8e7e47006fd0f54d745f5b78",
    "test_inputs_frozen_v1.jsonl": "284e332dab6f91051960f84a717f8742283166db587d5b544eeb894a5b907cd8",
}
ESCROW_MEMBER_ALLOWLIST = tuple(sorted(ESCROW_MEMBER_HASHES))

STAGE4_TEST_INPUT_DIR = STAGE4_ROOT / "final_integration/test_inputs"
STAGE4_TEST_INPUT_HASHES = {
    "FROZEN_SPLIT_SUMMARY.md": ESCROW_MEMBER_HASHES["FROZEN_SPLIT_SUMMARY.md"],
    "TEST_ESCROW_SHA256_MANIFEST.json": ESCROW_MEMBER_HASHES[
        "TEST_ESCROW_SHA256_MANIFEST.json"
    ],
    "test_inputs_frozen_v1.csv": ESCROW_MEMBER_HASHES["test_inputs_frozen_v1.csv"],
    "test_inputs_frozen_v1.jsonl": ESCROW_MEMBER_HASHES["test_inputs_frozen_v1.jsonl"],
}

TEST_GOLD_FIELDS = (
    "annotation_case_id",
    "canonical_scenario_family_id",
    "utterance_id",
    "writer_id",
    "current_page",
    "final_family_routing_signature",
    "atomic_component_id",
    "contrast_group_id",
    "contrast_axis",
    "final_case_validity",
    "final_naturalness",
    "final_dialogue_action",
    "final_rag_required",
    "final_memory_required",
    "final_planning_required",
    "partition",
    "split_seed",
    "split_version",
    "split_status",
    "escrow_status",
)

DETERMINISTIC_METHOD_IDS = (
    "R2V2-CG1_CLARIFICATION_RULE",
    "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON",
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
)
COMPLETE_METHOD_IDS = (
    "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON",
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_JOINT_LLM",
    "R2V2-P1_HYBRID",
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
    "R2V2-P3_RAG_MEMORY_SPECIALISTS",
    "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION",
)
ELIGIBLE_METHOD_IDS = (
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_JOINT_LLM",
    "R2V2-P1_HYBRID",
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
    "R2V2-P3_RAG_MEMORY_SPECIALISTS",
)
ALL_METHOD_IDS = (
    "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON",
    "R2V2-CG1_CLARIFICATION_RULE",
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_JOINT_LLM",
    "R2V2-P1_HYBRID",
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
    "R2V2-P3_RAG_MEMORY_SPECIALISTS",
    "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION",
    "R2V2-RAG_SPECIALIST",
    "R2V2-MEMORY_SPECIALIST",
)

CAPABILITY_KEYS = ("rag", "memory", "planning")
CAPABILITY_FIELDS = ("rag_required", "memory_required", "planning_required")
MODEL_ID = "gpt-4o-mini-2024-07-18"
BOOTSTRAP_SEED = 20260831
BOOTSTRAP_REPLICATES = 10_000
INPUT_USD_PER_MILLION = 0.15
CACHED_INPUT_USD_PER_MILLION = 0.075
OUTPUT_USD_PER_MILLION = 0.60

PRE_SCORING_RECEIPT_PATH = FINAL_SCORING_DIR / "PRE_SCORING_HARNESS_RECEIPT.json"
ACCESS_RECEIPT_PATH = FINAL_SCORING_DIR / "TEST_GOLD_ACCESS_RECEIPT.json"
INTERNAL_REVIEW_ZIP = Path(
    "external_inputs/RQ2_V2_STAGE_5E_FINAL_TEST_SCORING_REVIEW_2026-08-31.zip"
)
RQ3_HANDOFF_ZIP = Path(
    "external_inputs/RQ2_V2_FINAL_ROUTER_FOR_RQ3_HANDOFF_2026-08-31.zip"
)

SCORING_SOURCE_NAMES = (
    "__init__.py",
    "constants.py",
    "compositions.py",
    "metrics.py",
    "scoring.py",
    "freeze_pre_scoring.py",
    "run_final_scoring.py",
    "validate_final_scoring.py",
    "build_review_packages.py",
    "tests/__init__.py",
    "tests/test_final_scoring_toy.py",
    "tests/test_final_scoring_artifacts.py",
)
