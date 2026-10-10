"""Versioned RQ1-A-R1 contract-integrity supplement.

This package is deliberately evaluation-only.  It neither trains nor loads a
model and it never resolves the protected final-gold location.
"""

from .keyword_baseline_adapter import (
    FIXTURE_SHA256,
    KeywordBaselineResult,
    execute_keyword_parity,
)
from .statistical_decision_contract import (
    paired_approximate_randomisation_test,
    paired_bootstrap_ci,
    paired_effect_size,
    select_representative_seed,
)

__all__ = (
    "FIXTURE_SHA256",
    "KeywordBaselineResult",
    "execute_keyword_parity",
    "paired_approximate_randomisation_test",
    "paired_bootstrap_ci",
    "paired_effect_size",
    "select_representative_seed",
)
