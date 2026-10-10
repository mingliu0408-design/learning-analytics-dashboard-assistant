"""RQ2-V2 Stage 1 Track B rule and frozen-C0 baseline adapters.

This isolated research package contains no training, provider, production, or
final-test execution path.  The development B1 mapping shipped here is
deliberately unfrozen and therefore cannot be used for strict inference.
"""

from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]

B0_MODEL_ID = "R2V2-B0_RULE"
B1_MODEL_ID = "R2V2-B1_LEGACY_INTENT"
