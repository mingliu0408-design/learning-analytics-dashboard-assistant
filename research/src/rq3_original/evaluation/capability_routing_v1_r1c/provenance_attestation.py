"""Freeze safe user-attested provenance without copying governed dialogue text."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.capability_routing_v1_r1b.authentic_source_authority import (
    load_authentic_rows,
)

from . import (
    AUTHENTIC_ASSISTANT_COUNT,
    AUTHENTIC_BANK_ALIAS,
    AUTHENTIC_RECORD_COUNT,
    AUTHENTIC_SOURCE_SHA256,
    AUTHENTIC_USER_COUNT,
    HERE,
    ROOT,
    canonical_json_bytes,
)


class ProvenanceAttestationError(RuntimeError):
    pass


def build_provenance_attestation(root: Path = ROOT) -> dict[str, Any]:
    rows, identity = load_authentic_rows(root)
    roles = Counter(row["role"] for row in rows)
    if identity["sha256"] != AUTHENTIC_SOURCE_SHA256:
        raise ProvenanceAttestationError("authentic source identity mismatch")
    if (len(rows), roles["user"], roles["assistant"]) != (
        AUTHENTIC_RECORD_COUNT,
        AUTHENTIC_USER_COUNT,
        AUTHENTIC_ASSISTANT_COUNT,
    ):
        raise ProvenanceAttestationError("authentic source role counts mismatch")
    return {
        "schema_version": "rq2-authentic-provenance-attestation-v1",
        "stage": "RQ2-A-R1C",
        "confirmation_basis": "USER_EXPLICIT_ATTESTATION",
        "confirmation_date": "2026-08-26",
        "source_sha256": AUTHENTIC_SOURCE_SHA256,
        "source_record_count": AUTHENTIC_RECORD_COUNT,
        "role_user_count": AUTHENTIC_USER_COUNT,
        "role_assistant_count": AUTHENTIC_ASSISTANT_COUNT,
        "role_user_origin": (
            "VERBATIM_OR_DEIDENTIFIED_EXCERPTS_FROM_168_AUTHENTIC_STUDENT_QUERIES"
        ),
        "role_assistant_origin": "ORIGINAL_DEPLOYMENT_GPT4_OUTPUTS",
        "researcher_rewriting": False,
        "researcher_splicing": False,
        "few_shot_reconstruction": False,
        "adjacent_row_conversation_linkage": "not_confirmed",
        "automatic_session_inference_authorised": False,
        "author_email_evidence_exists": False,
        "conversation_id_present": False,
        "session_id_present": False,
        "timestamp_present": False,
        "all_adjacent_pairs_confirmed": False,
    }


def authentic_bank_role_document() -> dict[str, Any]:
    return {
        "schema_version": "authentic-bank-role-v1.1",
        "stage": "RQ2-A-R1C",
        "alias": AUTHENTIC_BANK_ALIAS,
        "authentic_student_origin": True,
        "student_origin_confirmation": "USER_EXPLICIT_ATTESTATION",
        "assistant_outputs_original": True,
        "assistant_outputs_used_as_context": False,
        "conversation_id_present": False,
        "session_id_present": False,
        "timestamp_present": False,
        "adjacent_pair_linkage_confirmed": False,
        "research_roles": [
            "CODEBOOK_AND_HUMAN_ANNOTATION_CALIBRATION",
            "DESCRIPTIVE_IN_SAMPLE_AUTHENTICITY_DIAGNOSTIC",
            "QUALITATIVE_EVIDENCE",
        ],
        "eligible_for_threshold_selection": False,
        "eligible_for_independent_performance_evaluation": False,
        "eligible_for_final_evaluation": False,
        "eligible_for_educational_effectiveness_claim": False,
        "eligible_for_broad_generalisation": False,
        "query_text_tracked": False,
        "assistant_text_tracked": False,
    }


def write_provenance_contracts(root: Path = ROOT) -> dict[str, Any]:
    del root
    attestation = build_provenance_attestation(ROOT)
    (HERE / "authentic_provenance_attestation_v1.json").write_bytes(
        canonical_json_bytes(attestation)
    )
    (HERE / "authentic_bank_role_v1_1.json").write_bytes(
        canonical_json_bytes(authentic_bank_role_document())
    )
    return attestation
