"""Schema and frozen category inventory for the local controlled fixture bank."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


MECHANISM_GROUP_COUNTS = {
    "PERSISTENT_FRESHNESS_CONFLICT": 3,
    "PERSISTENT_PRIVACY_CONTROL": 2,
    "PERSISTENT_RETRIEVAL": 5,
    "PERSISTENT_WRITE_UPDATE": 4,
    "RAG_CANDIDATE_GATE": 6,
    "RAG_SUFFICIENCY_GATE": 8,
}

FIXTURE_CATEGORY_COUNTS = {
    "PM_FRESHNESS_COMPLETED_CANCELLED_REJECTION": 1,
    "PM_FRESHNESS_LATEST_CORRECTION_WINS": 1,
    "PM_FRESHNESS_STALE_REJECTION": 1,
    "PM_PRIVACY_CROSS_STUDENT_ISOLATION": 1,
    "PM_PRIVACY_DELETED_TOMBSTONE_REJECTION": 1,
    "PM_RETRIEVE_CROSS_SESSION_UNFINISHED_PLAN": 1,
    "PM_RETRIEVE_GOAL_ENTITY_LINKED": 1,
    "PM_RETRIEVE_MULTI_HOP_PREFERENCE_CONSTRAINT": 1,
    "PM_RETRIEVE_NO_RELEVANT_ABSTENTION": 1,
    "PM_RETRIEVE_PARAPHRASED_PREFERENCE": 1,
    "PM_WRITE_CORRECTION_SUPERSEDES": 1,
    "PM_WRITE_EXPLICIT_CONSTRAINT_GOAL": 1,
    "PM_WRITE_EXPLICIT_PREFERENCE": 1,
    "PM_WRITE_SENSITIVE_INFERRED_REJECTED": 1,
    "RAG_COURSE_CAPABILITY_ABSENT": 1,
    "RAG_COURSE_CAPABILITY_AUTHORISED_SOURCE": 2,
    "RAG_CLARIFICATION_BLOCKS_RETRIEVAL": 2,
    "RAG_EXPLICIT_SOURCE_RESTRICTION": 1,
    "RAG_SUFFICIENCY_AMBIGUOUS": 2,
    "RAG_SUFFICIENCY_NO_RESULT": 2,
    "RAG_SUFFICIENCY_SUPPORTED": 2,
    "RAG_SUFFICIENCY_UNSUPPORTED": 2,
}

REQUIRED_FIXTURE_FIELDS = (
    "fixture_id",
    "mechanism_group",
    "fixture_category",
    "initial_store_state",
    "input_event_or_query",
    "expected_write_decision",
    "expected_retrieval_ids",
    "expected_admission_ids",
    "expected_rejection_reasons",
    "expected_clarification",
    "expected_security_state",
    "contract_basis",
    "coverage_tags",
)


@dataclass(frozen=True)
class ControlledMechanismFixtureV1:
    fixture_id: str
    mechanism_group: str
    fixture_category: str
    initial_store_state: tuple[Mapping[str, Any], ...]
    input_event_or_query: Mapping[str, Any]
    expected_write_decision: Mapping[str, Any]
    expected_retrieval_ids: tuple[str, ...]
    expected_admission_ids: tuple[str, ...]
    expected_rejection_reasons: Mapping[str, str]
    expected_clarification: bool
    expected_security_state: str
    contract_basis: tuple[str, ...]
    coverage_tags: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ControlledMechanismFixtureV1":
        if set(value) != set(REQUIRED_FIXTURE_FIELDS):
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: schema fields")
        item = cls(
            fixture_id=str(value["fixture_id"]),
            mechanism_group=str(value["mechanism_group"]),
            fixture_category=str(value["fixture_category"]),
            initial_store_state=tuple(value["initial_store_state"]),
            input_event_or_query=dict(value["input_event_or_query"]),
            expected_write_decision=dict(value["expected_write_decision"]),
            expected_retrieval_ids=tuple(value["expected_retrieval_ids"]),
            expected_admission_ids=tuple(value["expected_admission_ids"]),
            expected_rejection_reasons=dict(value["expected_rejection_reasons"]),
            expected_clarification=value["expected_clarification"],
            expected_security_state=str(value["expected_security_state"]),
            contract_basis=tuple(value["contract_basis"]),
            coverage_tags=tuple(value["coverage_tags"]),
        )
        item.validate()
        return item

    def validate(self) -> None:
        if not self.fixture_id.startswith("RQ2P2-FX-"):
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: fixture id")
        if self.mechanism_group not in MECHANISM_GROUP_COUNTS:
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: mechanism group")
        if self.fixture_category not in FIXTURE_CATEGORY_COUNTS:
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: category")
        if not isinstance(self.expected_clarification, bool):
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: clarification")
        if not isinstance(self.input_event_or_query.get("text"), str):
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: controlled text")
        if not self.contract_basis or not self.expected_security_state:
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: contract basis")
        if len(set(self.expected_retrieval_ids)) != len(self.expected_retrieval_ids):
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: retrieval ids")
        if not set(self.expected_admission_ids).issubset(self.expected_retrieval_ids):
            raise ValueError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: admission ids")

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def fixture_schema_contract() -> dict[str, Any]:
    return {
        "schema_version": "controlled-mechanism-fixture-schema-v1",
        "required_fields": list(REQUIRED_FIXTURE_FIELDS),
        "expected_record_count": 28,
        "expected_mechanism_group_counts": dict(sorted(MECHANISM_GROUP_COUNTS.items())),
        "expected_fixture_category_counts": dict(sorted(FIXTURE_CATEGORY_COUNTS.items())),
        "full_text_storage": "LOCAL_IGNORED_ONLY",
    }
