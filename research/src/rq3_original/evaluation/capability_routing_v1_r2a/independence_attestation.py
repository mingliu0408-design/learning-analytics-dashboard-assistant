"""Safe user-authorised human-review independence attestation."""

from __future__ import annotations

from typing import Any


def independence_attestation_document() -> dict[str, Any]:
    return {
        "schema_version": "human-review-independence-attestation-v1",
        "stage": "RQ2-A-R2A",
        "authority_basis": "USER_EXPLICIT_ATTESTATION",
        "attestation_date": "2026-08-26",
        "reviewer_count": 2,
        "reviewers_are_different_humans": True,
        "completed_independently": True,
        "viewed_other_reviewer_answers": False,
        "discussed_cases_before_freeze": False,
        "used_ai_annotation_tools": False,
        "viewed_hidden_proposal": False,
        "viewed_c0_scores": False,
        "viewed_legacy_outputs": False,
        "reviewer_ids": ["REVIEWER_A", "REVIEWER_B"],
        "real_names_or_contact_details_recorded": False,
    }
