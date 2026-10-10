"""Frozen dual-gated RAG contract over the existing Retrieval v2.4 interface."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from utils.c_full_retrieval_adapter import retrieve_course_evidence
from utils.retrieval_v2.sufficiency import evaluate_evidence_sufficiency

from . import ROOT, sha256_file


SUFFICIENCY_RELATIVE = Path("utils/retrieval_v2/sufficiency.py")
ADAPTER_RELATIVE = Path("utils/c_full_retrieval_adapter.py")
MODEL_RELATIVE = Path("utils/retrieval_v2/models.py")

EXISTING_TO_P2_STATUS = {
    "sufficient": "SUPPORTED",
    "partially_sufficient": "AMBIGUOUS",
    "metadata_only": "AMBIGUOUS",
    "insufficient": "UNSUPPORTED",
    "no_result": "NO_RESULT",
    "not_applicable": "NOT_APPLICABLE",
}


class RAGContractError(RuntimeError):
    pass


def retrieval_candidate_gate(
    *, p1_course_retrieval: bool, p1_clarification: bool, course_source_authorised: bool
) -> bool:
    return bool(
        p1_course_retrieval and not p1_clarification and course_source_authorised
    )


def normalise_sufficiency_status(existing_status: str) -> str:
    try:
        return EXISTING_TO_P2_STATUS[str(existing_status)]
    except KeyError as exc:
        raise RAGContractError("Unknown frozen sufficiency status") from exc


def evidence_admission_allowed(status: str, supporting_chunk_count: int) -> bool:
    return status == "SUPPORTED" and supporting_chunk_count > 0


def assert_existing_sufficiency_interface() -> dict[str, Any]:
    if not callable(evaluate_evidence_sufficiency) or not callable(retrieve_course_evidence):
        raise RAGContractError("BLOCKED_RQ2_C0_RAG_SUFFICIENCY_INTERFACE_MISSING")
    parameters = tuple(inspect.signature(evaluate_evidence_sufficiency).parameters)
    if parameters != ("plan", "chunks"):
        raise RAGContractError("BLOCKED_RQ2_C0_RAG_SUFFICIENCY_INTERFACE_MISSING")
    return {
        "interface": "utils.retrieval_v2.sufficiency.evaluate_evidence_sufficiency",
        "parameters": list(parameters),
        "sufficiency_sha256": sha256_file(ROOT / SUFFICIENCY_RELATIVE),
        "retrieval_adapter_sha256": sha256_file(ROOT / ADAPTER_RELATIVE),
        "retrieval_models_sha256": sha256_file(ROOT / MODEL_RELATIVE),
        "status": "PASS",
    }


def dual_gated_rag_contract() -> dict[str, Any]:
    interface = assert_existing_sufficiency_interface()
    return {
        "schema_version": "dual-gated-rag-contract-v1",
        "stage": "RQ2-C0",
        "status": "FROZEN",
        "gate_1_retrieval_candidate": {
            "all_required": [
                "P1_COURSE_RETRIEVAL_TRUE",
                "P1_CLARIFICATION_FALSE",
                "COURSE_SOURCE_AUTHORISED",
            ],
            "gold_trigger_allowed": False,
            "c0_low_confidence_trigger_allowed": False,
        },
        "gate_2_evidence_sufficiency": {
            "existing_interface": interface,
            "normalised_statuses": [
                "SUPPORTED",
                "AMBIGUOUS",
                "UNSUPPORTED",
                "NO_RESULT",
                "NOT_APPLICABLE",
            ],
            "existing_status_mapping": dict(sorted(EXISTING_TO_P2_STATUS.items())),
            "evidence_admitted_only_when": "SUPPORTED_WITH_AT_LEAST_ONE_SUPPORTING_CHUNK",
            "non_supported_chunk_prompt_admission": False,
            "llm_support_judgement_allowed": False,
            "retrieval_threshold_changed": False,
        },
        "production_behavior_changed": False,
        "p2_implemented": False,
        "provider_calls": 0,
        "network_access": False,
    }
