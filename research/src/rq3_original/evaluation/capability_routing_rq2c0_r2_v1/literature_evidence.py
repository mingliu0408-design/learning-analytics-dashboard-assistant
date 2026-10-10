"""Publication-safe mapping from user-authorised sources to contract fields."""

from __future__ import annotations

from typing import Any


LITERATURE_EVIDENCE = (
    {
        "source_identity": "LoCoMo",
        "venue_year": "ACL 2024",
        "authorised_summary": "LONG_TERM_MULTI_SESSION_CONVERSATIONAL_MEMORY_BENCHMARK",
        "supported_design_principles": ["CROSS_SESSION_RETRIEVAL_EVALUATION"],
        "contract_fields": ["MemoryRetrievalPlanV1.target_memory_types", "multi_hop_complete"],
    },
    {
        "source_identity": "MemoryOS",
        "venue_year": "EMNLP 2025",
        "authorised_summary": "HIERARCHICAL_SHORT_MID_LONG_TERM_MEMORY_ARCHITECTURE",
        "supported_design_principles": ["LAYERED_MEMORY_ARCHITECTURE"],
        "contract_fields": ["PersistentLearnerMemoryV1_1", "MemoryStateProjectionV1"],
    },
    {
        "source_identity": "PREMem",
        "venue_year": "EMNLP Findings 2025",
        "authorised_summary": "PRE_STORAGE_REASONING_AND_CROSS_SESSION_MEMORY_RELATIONS",
        "supported_design_principles": ["STRUCTURED_WRITE_BOUNDARY", "MEMORY_RELATIONS"],
        "contract_fields": ["candidate_source", "supersedes_memory_id"],
    },
    {
        "source_identity": "ScaffoldLM",
        "venue_year": "ACL 2026",
        "authorised_summary": "ASSESSMENT_DRIVEN_TUTORING_MEMORY_WITH_PLAN_PROGRESS_LEARNER_STATE",
        "supported_design_principles": ["PLAN_PROGRESS_STATE"],
        "contract_fields": ["memory_type", "projection_eligible"],
    },
    {
        "source_identity": "IntelliCode",
        "venue_year": "EACL Demo 2026",
        "authorised_summary": "CENTRALISED_VERSIONED_LEARNER_STATE_AND_CONTROLLED_UPDATES",
        "supported_design_principles": ["VERSIONED_PROJECTION", "CONTROLLED_UPDATE"],
        "contract_fields": ["projection_version", "status_reason"],
    },
    {
        "source_identity": "APEX-MEM",
        "venue_year": "ACL 2026",
        "authorised_summary": "APPEND_ONLY_TEMPORAL_EVENTS_AND_RETRIEVAL_TIME_CONFLICT_RESOLUTION",
        "supported_design_principles": ["APPEND_ONLY_EPISODES", "CONFLICT_RESOLUTION"],
        "contract_fields": ["event_time", "supersedes_memory_id", "conflict_group"],
    },
    {
        "source_identity": "LoCoMo-Plus",
        "venue_year": "ACL 2026",
        "authorised_summary": "IMPLICIT_MEMORY_CONSTRAINTS_AND_CUE_TRIGGER_MISMATCH",
        "supported_design_principles": ["MULTI_SIGNAL_RETRIEVAL", "NO_KEYWORD_ONLY_CLAIM"],
        "contract_fields": ["entity_overlap_count", "dense_score", "explicit_state_link"],
    },
)


def literature_evidence_manifest() -> dict[str, Any]:
    return {
        "schema_version": "persistent-memory-literature-evidence-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN_PUBLICATION_SAFE",
        "evidence_basis": "USER_AUTHORISED_IDENTITIES_AND_SUMMARIES_ONLY",
        "sources": [dict(item) for item in LITERATURE_EVIDENCE],
        "source_count": len(LITERATURE_EVIDENCE),
        "unverified_experimental_metric_count": 0,
        "causal_proof_claimed": False,
        "network_lookup_performed": False,
    }
