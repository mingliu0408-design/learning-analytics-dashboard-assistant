"""Safe third-human adjudicator independence attestation."""

from __future__ import annotations

from typing import Any


def adjudicator_independence_attestation() -> dict[str, Any]:
    return {
        "schema_version": "human-adjudicator-independence-attestation-v1",
        "stage": "RQ2-A-R2B",
        "status": "FROZEN",
        "authority_basis": "USER_EXPLICIT_ATTESTATION",
        "attestation_date": "2026-08-26",
        "adjudicator_is_third_human": True,
        "adjudicator_is_reviewer_a": False,
        "adjudicator_is_reviewer_b": False,
        "used_chatgpt": False,
        "used_codex": False,
        "used_other_ai": False,
        "viewed_hidden_proposal": False,
        "viewed_c0_scores": False,
        "viewed_legacy_outputs": False,
        "viewed_intent_predictions": False,
        "viewed_expected_gold": False,
        "adjudicator_id": "HUMAN_ADJUDICATOR",
        "personally_identifying_information_recorded": False,
    }


def validate_adjudicator_independence_attestation(value: dict[str, Any]) -> None:
    expected = adjudicator_independence_attestation()
    if value != expected:
        raise ValueError("BLOCKED_RQ2_A_R2B_ATTESTATION")
