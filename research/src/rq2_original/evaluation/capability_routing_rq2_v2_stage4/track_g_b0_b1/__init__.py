"""RQ2-V2 Stage 4G DEV-only clarification, B0, and B1 evaluation."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
STAGE4_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]

CLARIFICATION_GATE_ID = "R2V2-CG1_CLARIFICATION_RULE"
B0_MODEL_ID = "R2V2-B0_RULE"
B1_MODEL_ID = "R2V2-B1_LEGACY_INTENT"
CAPABILITIES = ("RAG", "Memory", "Planning")

__all__ = [
    "B0_MODEL_ID",
    "B1_MODEL_ID",
    "CAPABILITIES",
    "CLARIFICATION_GATE_ID",
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "STAGE4_ROOT",
]
