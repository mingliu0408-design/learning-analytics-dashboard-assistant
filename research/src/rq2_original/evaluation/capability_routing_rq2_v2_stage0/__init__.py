"""RQ2-V2 Stage 0 capability-routing contracts and offline harness skeleton.

This package is intentionally isolated from the legacy RQ2 implementation.  It
contains no final benchmark, trained router, threshold tuning, provider call,
or RQ3 execution path.
"""

from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]

CONTRACT_SCHEMA_VERSION = "rq2-v2-contract-v1"
CASE_SCHEMA_VERSION = "rq2-v2-case-v1"
PREDICTION_SCHEMA_VERSION = "rq2-v2-prediction-v1"
DATASET_REGISTRY_SCHEMA_VERSION = "rq2-v2-dataset-registry-v1"
SCENARIO_MATRIX_SCHEMA_VERSION = "rq2-v2-scenario-matrix-row-v1"

CAPABILITY_FIELDS = (
    "rag_required",
    "memory_required",
    "planning_required",
)

MODEL_IDS = (
    "R2V2-B0_RULE",
    "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE",
    "R2V2-B3_OVR",
    "R2V2-B4_LLM",
    "R2V2-P1_HYBRID",
)

DIALOGUE_ACTIONS = ("ANSWER", "CLARIFY")
PARTITIONS = ("DEV", "TEST", "PILOT")
PROVENANCE_TYPES = (
    "AUTHENTIC",
    "HUMAN_ELICITED",
    "RESEARCHER_SYNTHETIC",
    "LLM_AUGMENTED",
)

