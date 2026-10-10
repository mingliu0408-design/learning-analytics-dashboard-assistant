"""Fail-closed, mechanism-specific semantic validation of the unchanged R1 bank."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import stat
from typing import Any, Mapping

from . import (
    AMENDMENT_AUTHORITY_TYPE,
    AMENDMENT_CONTRACT_ID,
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    R1_FIXTURE_BANK_PATH,
    sha256_bytes,
    sha256_file,
)


RAG_CANDIDATE_GROUP = "RAG_CANDIDATE_GATE"
RAG_SUFFICIENCY_GROUP = "RAG_SUFFICIENCY_GATE"
PERSISTENT_GROUPS = (
    "PERSISTENT_WRITE_UPDATE",
    "PERSISTENT_RETRIEVAL",
    "PERSISTENT_FRESHNESS_CONFLICT",
    "PERSISTENT_PRIVACY_CONTROL",
)
GOVERNED_GROUPS = (RAG_CANDIDATE_GROUP, RAG_SUFFICIENCY_GROUP, *PERSISTENT_GROUPS)


class FixtureSemanticError(RuntimeError):
    pass


def fixture_validation_amendment_authority() -> dict[str, Any]:
    return {
        "schema_version": "fixture-semantic-validation-amendment-v1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN",
        "authority_type": AMENDMENT_AUTHORITY_TYPE,
        "authorisation_date": "2026-08-27",
        "authorised_change": "MECHANISM_SPECIFIC_INITIAL_STATE_AND_RETRIEVAL_ID_SEMANTICS",
        "original_blocked_finding": "EXPECTED_RAG_CANDIDATE_OUTPUT_ID_NOT_IN_PRE_RETRIEVAL_STATE",
        "original_blocker": "BLOCKED_RQ2_C0_R2_FIXTURE_SEMANTIC_MISMATCH",
        "fixture_text_change_authorised": False,
        "fixture_membership_change_authorised": False,
        "expected_decision_change_authorised": False,
        "coverage_change_authorised": False,
        "fixture_bank_hash_change_authorised": False,
        "p1_change_authorised": False,
        "capability_gold_change_authorised": False,
        "threshold_change_authorised": False,
        "model_output_change_authorised": False,
        "production_behaviour_change_authorised": False,
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
    }


def mechanism_specific_field_semantics_contract() -> dict[str, Any]:
    core_rows = [
        {
            "mechanism_group": RAG_CANDIDATE_GROUP,
            "initial_store_state_semantics": "PRE_RETRIEVAL_STATE",
            "retrieval_ids_must_exist_in_initial_state": False,
            "admission_ids_must_be_empty": True,
            "admission_ids_must_be_subset_of_retrieval_ids": "NOT_APPLICABLE",
            "evidence_sufficiency_applicable": False,
            "evidence_admission_applicable": False,
            "field_derived_validation_required": True,
        },
        {
            "mechanism_group": RAG_SUFFICIENCY_GROUP,
            "initial_store_state_semantics": "PRECONSTRUCTED_RETRIEVED_CHUNK_STATE",
            "retrieval_ids_must_exist_in_initial_state": True,
            "admission_ids_must_be_empty": False,
            "admission_ids_must_be_subset_of_retrieval_ids": True,
            "evidence_sufficiency_applicable": True,
            "evidence_admission_applicable": True,
            "field_derived_validation_required": True,
        },
        {
            "mechanism_group": "PERSISTENT_MEMORY_FAMILY",
            "initial_store_state_semantics": "PERSISTENT_MEMORY_EPISODE_STORE",
            "retrieval_ids_must_exist_in_initial_state": True,
            "admission_ids_must_be_empty": False,
            "admission_ids_must_be_subset_of_retrieval_ids": True,
            "evidence_sufficiency_applicable": False,
            "evidence_admission_applicable": True,
            "field_derived_validation_required": True,
        },
    ]
    details = [
        {
            "mechanism_group": group,
            "family_contract_row": "PERSISTENT_MEMORY_FAMILY",
            "initial_store_state_semantics": "PERSISTENT_MEMORY_EPISODE_STORE",
        }
        for group in PERSISTENT_GROUPS
    ]
    return {
        "schema_version": "mechanism-specific-fixture-field-semantics-v1-1",
        "stage": "RQ2-C0-R2",
        "status": "FROZEN",
        "contract_id": AMENDMENT_CONTRACT_ID,
        "dispatch_by_exact_mechanism_group": True,
        "unknown_group_policy": "FAIL_CLOSED",
        "candidate_exception_silent_fallback": False,
        "core_rows": core_rows,
        "governed_persistent_group_rows": details,
    }


def _assert_bank_file(path: Path) -> None:
    mode = path.lstat().st_mode
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise FixtureSemanticError("BLOCKED_RQ2_C0_R2_FIXTURE_BANK_MUTATED")


def load_frozen_fixture_rows(
    path: Path = R1_FIXTURE_BANK_PATH,
) -> tuple[tuple[dict[str, Any], bytes], ...]:
    _assert_bank_file(path)
    payload = path.read_bytes()
    lines = payload.splitlines(keepends=True)
    if (
        sha256_bytes(payload) != EXPECTED_FIXTURE_BANK_SHA256
        or len(payload) != EXPECTED_FIXTURE_BANK_SIZE
        or len(lines) != EXPECTED_FIXTURE_RECORD_COUNT
    ):
        raise FixtureSemanticError("BLOCKED_RQ2_C0_R2_FIXTURE_BANK_MUTATED")
    rows: list[tuple[dict[str, Any], bytes]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FixtureSemanticError("BLOCKED_RQ2_C0_R2_FIXTURE_SEMANTIC_MISMATCH") from exc
        if not isinstance(value, dict):
            raise FixtureSemanticError("BLOCKED_RQ2_C0_R2_FIXTURE_SEMANTIC_MISMATCH")
        rows.append((value, line))
    return tuple(rows)


def _store_ids(fixture: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in fixture["initial_store_state"]:
        identifier = str(item.get("memory_id") or item.get("evidence_id") or "")
        if identifier:
            result.add(identifier)
    return result


def _candidate_category(fixture: Mapping[str, Any]) -> str:
    query = fixture["input_event_or_query"]
    if bool(query.get("p1_clarification")):
        return "RAG_CLARIFICATION_BLOCKS_RETRIEVAL"
    if not bool(query.get("p1_course_retrieval")):
        return "RAG_COURSE_CAPABILITY_ABSENT"
    if not bool(query.get("source_authorised")):
        return "RAG_EXPLICIT_SOURCE_RESTRICTION"
    return "RAG_COURSE_CAPABILITY_AUTHORISED_SOURCE"


def _candidate_tag(category: str) -> str:
    return (
        "RAG_CANDIDATE_ALLOWED"
        if category == "RAG_COURSE_CAPABILITY_AUTHORISED_SOURCE"
        else "RAG_CANDIDATE_BLOCKED"
    )


def validate_rag_candidate_gate_fixture(
    fixture: Mapping[str, Any], global_store_ids: set[str]
) -> dict[str, Any]:
    if fixture.get("mechanism_group") != RAG_CANDIDATE_GROUP:
        raise FixtureSemanticError("BLOCKED_RQ2_C0_R2_FIXTURE_GROUP_MISMATCH")
    initial = fixture["initial_store_state"]
    retrieval_ids = list(fixture["expected_retrieval_ids"])
    admission_ids = list(fixture["expected_admission_ids"])
    if admission_ids:
        raise FixtureSemanticError("candidate-gate admission IDs must be empty")
    if any(
        "support_status" in item or "content_level" in item or "supporting_chunk_ids" in item
        for item in initial
    ):
        raise FixtureSemanticError("candidate-gate cannot encode evidence sufficiency")
    if len(retrieval_ids) != len(set(retrieval_ids)) or any(
        not isinstance(value, str) or not value for value in retrieval_ids
    ):
        raise FixtureSemanticError("candidate-gate downstream IDs invalid")
    if set(retrieval_ids) & global_store_ids:
        raise FixtureSemanticError("candidate-gate downstream ID collision")
    query = fixture["input_event_or_query"]
    candidate_allowed = bool(
        query.get("p1_course_retrieval")
        and not query.get("p1_clarification")
        and query.get("source_authorised")
    )
    if candidate_allowed != bool(retrieval_ids):
        raise FixtureSemanticError("candidate decision mismatch")
    if not candidate_allowed and retrieval_ids:
        raise FixtureSemanticError("blocked candidate has retrieval IDs")
    derived_category = _candidate_category(fixture)
    derived_tags = {_candidate_tag(derived_category)}
    if fixture["fixture_category"] != derived_category or set(fixture["coverage_tags"]) != derived_tags:
        raise FixtureSemanticError("candidate category or tag mismatch")
    return {
        "fixture_id": fixture["fixture_id"],
        "mechanism_group": RAG_CANDIDATE_GROUP,
        "fixture_category": derived_category,
        "semantic_validation_status": "PASS",
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
        "initial_store_state_semantics": "PRE_RETRIEVAL_STATE",
        "retrieval_id_existence_rule_applied": "DOWNSTREAM_OUTPUT_COMMITMENT_NOT_PREEXISTING_STORE_ITEM",
        "evidence_sufficiency_applicable": False,
        "evidence_admission_applicable": False,
        "derived_coverage_tags": sorted(derived_tags),
        "downstream_retrieval_id_commitment": bool(retrieval_ids),
        "empty_pre_retrieval_state": not initial,
    }


def _derive_sufficiency_status(fixture: Mapping[str, Any]) -> str:
    initial = fixture["initial_store_state"]
    if not initial:
        return "NO_RESULT"
    statuses = {str(item.get("support_status") or "") for item in initial}
    if len(statuses) != 1 or not statuses <= {"SUPPORTED", "AMBIGUOUS", "UNSUPPORTED"}:
        raise FixtureSemanticError("RAG sufficiency state is not field-derived")
    return statuses.pop()


def validate_rag_sufficiency_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    if fixture.get("mechanism_group") != RAG_SUFFICIENCY_GROUP:
        raise FixtureSemanticError("Candidate Gate exception cannot apply to RAG Sufficiency")
    store_ids = _store_ids(fixture)
    retrieval_ids = set(fixture["expected_retrieval_ids"])
    admission_ids = set(fixture["expected_admission_ids"])
    if not retrieval_ids <= store_ids or not admission_ids <= retrieval_ids or not admission_ids <= store_ids:
        raise FixtureSemanticError("strict RAG retrieval-ID existence check failed")
    derived_status = _derive_sufficiency_status(fixture)
    expected_category = f"RAG_SUFFICIENCY_{derived_status}"
    expected_tag = f"RAG_{derived_status}"
    if fixture["fixture_category"] != expected_category or set(fixture["coverage_tags"]) != {expected_tag}:
        raise FixtureSemanticError("RAG sufficiency category or tag mismatch")
    if derived_status == "SUPPORTED":
        if not retrieval_ids or admission_ids != retrieval_ids:
            raise FixtureSemanticError("SUPPORTED evidence admission mismatch")
    elif admission_ids:
        raise FixtureSemanticError("non-supported evidence admitted")
    reasons = set(fixture["expected_rejection_reasons"].values())
    expected_reason = {
        "AMBIGUOUS": "AMBIGUOUS_EVIDENCE",
        "UNSUPPORTED": "UNSUPPORTED_EVIDENCE",
        "NO_RESULT": "NO_RESULT",
    }.get(derived_status)
    if expected_reason is None and reasons:
        raise FixtureSemanticError("SUPPORTED evidence has rejection reason")
    if expected_reason is not None and expected_reason not in reasons:
        raise FixtureSemanticError("RAG sufficiency rejection reason mismatch")
    return {
        "fixture_id": fixture["fixture_id"],
        "mechanism_group": RAG_SUFFICIENCY_GROUP,
        "fixture_category": expected_category,
        "semantic_validation_status": "PASS",
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
        "initial_store_state_semantics": "PRECONSTRUCTED_RETRIEVED_CHUNK_STATE",
        "retrieval_id_existence_rule_applied": "STRICT_RETRIEVED_CHUNK_ID_EXISTENCE",
        "evidence_sufficiency_applicable": True,
        "evidence_admission_applicable": True,
        "derived_evidence_sufficiency": derived_status,
        "derived_coverage_tags": [expected_tag],
    }


def _persistent_rejection_supported(
    fixture: Mapping[str, Any], identifier: str, reason: str
) -> bool:
    items = {
        str(item.get("memory_id") or ""): item
        for item in fixture["initial_store_state"]
        if item.get("memory_id")
    }
    item = items.get(identifier)
    query = fixture["input_event_or_query"]
    if reason == "SENSITIVE_PROFILE_INFERENCE" and identifier == "write":
        return (
            query.get("kind") == "MODEL_INFERENCE_ONLY"
            or fixture["expected_write_decision"].get("memory_type", "").startswith("INFERRED_")
        )
    if item is None:
        return False
    if reason == "STALE":
        return item.get("status") == "STALE" or bool(item.get("valid_until"))
    if reason == "SUPERSEDED":
        return item.get("status") == "SUPERSEDED" or (
            query.get("kind") == "EXPLICIT_STUDENT_CORRECTION"
            and fixture["expected_write_decision"].get("supersedes") == identifier
        )
    if reason == "CANCELLED_OR_COMPLETED":
        return item.get("status") in {"CANCELLED", "COMPLETED"}
    if reason == "CROSS_STUDENT_SCOPE":
        return bool(query.get("student_scope_id")) and (
            item.get("student_scope_id") != query.get("student_scope_id")
        )
    if reason == "DELETED":
        return item.get("status") == "DELETED" and bool(item.get("tombstone"))
    if reason == "RELEVANCE_UNSUPPORTED":
        return not set(item.get("entities") or ()) & set(query.get("entities") or ())
    return False


def _derive_persistent_tags(fixture: Mapping[str, Any]) -> set[str]:
    category = fixture["fixture_category"]
    mapping = {
        "PM_WRITE_EXPLICIT_PREFERENCE": {"WRITE_AUTHORISED"},
        "PM_WRITE_EXPLICIT_CONSTRAINT_GOAL": {"WRITE_AUTHORISED"},
        "PM_WRITE_CORRECTION_SUPERSEDES": {"WRITE_AUTHORISED", "SUPERSEDED_REJECTION"},
        "PM_WRITE_SENSITIVE_INFERRED_REJECTED": {"WRITE_REJECTED"},
        "PM_RETRIEVE_PARAPHRASED_PREFERENCE": {"ADDITIONAL_PERSISTENT_RETRIEVAL_REQUIRED"},
        "PM_RETRIEVE_GOAL_ENTITY_LINKED": {"ADDITIONAL_PERSISTENT_RETRIEVAL_REQUIRED"},
        "PM_RETRIEVE_CROSS_SESSION_UNFINISHED_PLAN": {"ADDITIONAL_PERSISTENT_RETRIEVAL_REQUIRED"},
        "PM_RETRIEVE_MULTI_HOP_PREFERENCE_CONSTRAINT": {
            "ADDITIONAL_PERSISTENT_RETRIEVAL_REQUIRED",
            "MULTI_HOP_RETRIEVAL",
        },
        "PM_RETRIEVE_NO_RELEVANT_ABSTENTION": {"NO_RELEVANT_MEMORY_ABSTENTION"},
        "PM_FRESHNESS_STALE_REJECTION": {"STALE_REJECTION"},
        "PM_FRESHNESS_LATEST_CORRECTION_WINS": {"SUPERSEDED_REJECTION"},
        "PM_FRESHNESS_COMPLETED_CANCELLED_REJECTION": {"COMPLETED_CANCELLED_REJECTION"},
        "PM_PRIVACY_CROSS_STUDENT_ISOLATION": {"CROSS_STUDENT_REJECTION"},
        "PM_PRIVACY_DELETED_TOMBSTONE_REJECTION": {"DELETED_MEMORY_REJECTION"},
    }
    try:
        return mapping[category]
    except KeyError as exc:
        raise FixtureSemanticError("unknown persistent category") from exc


def validate_persistent_memory_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    group = str(fixture.get("mechanism_group") or "")
    if group not in PERSISTENT_GROUPS:
        raise FixtureSemanticError("Candidate Gate exception cannot apply to persistent fixture")
    store_ids = _store_ids(fixture)
    retrieval_ids = set(fixture["expected_retrieval_ids"])
    admission_ids = set(fixture["expected_admission_ids"])
    if not retrieval_ids <= store_ids or not admission_ids <= retrieval_ids or not admission_ids <= store_ids:
        raise FixtureSemanticError("strict persistent retrieval-ID existence check failed")
    for identifier, reason in fixture["expected_rejection_reasons"].items():
        if not _persistent_rejection_supported(fixture, str(identifier), str(reason)):
            raise FixtureSemanticError("persistent rejection reason not field-derived")

    category = fixture["fixture_category"]
    write = fixture["expected_write_decision"]
    if category.startswith("PM_WRITE_"):
        if category == "PM_WRITE_SENSITIVE_INFERRED_REJECTED":
            if write.get("write_authorised") is not False:
                raise FixtureSemanticError("write rejection not field-derived")
        elif write.get("write_authorised") is not True:
            raise FixtureSemanticError("authorised write not field-derived")
    if category == "PM_WRITE_CORRECTION_SUPERSEDES":
        old_id = str(write.get("supersedes") or "")
        if (
            not old_id
            or old_id not in store_ids
            or fixture["input_event_or_query"].get("kind") != "EXPLICIT_STUDENT_CORRECTION"
        ):
            raise FixtureSemanticError("correction supersession relation missing")
    if category == "PM_RETRIEVE_MULTI_HOP_PREFERENCE_CONSTRAINT":
        items = {
            item["memory_id"]: item for item in fixture["initial_store_state"]
        }
        required_types = {
            items[identifier]["memory_type"] for identifier in admission_ids
        }
        if len(required_types) < 2:
            raise FixtureSemanticError("multi-hop required types not field-derived")

    derived_tags = _derive_persistent_tags(fixture)
    if set(fixture["coverage_tags"]) != derived_tags:
        raise FixtureSemanticError("persistent category or tag mismatch")
    return {
        "fixture_id": fixture["fixture_id"],
        "mechanism_group": group,
        "fixture_category": category,
        "semantic_validation_status": "PASS",
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
        "initial_store_state_semantics": "PERSISTENT_MEMORY_EPISODE_STORE",
        "retrieval_id_existence_rule_applied": "STRICT_PERSISTENT_MEMORY_ID_EXISTENCE",
        "evidence_sufficiency_applicable": False,
        "evidence_admission_applicable": True,
        "derived_coverage_tags": sorted(derived_tags),
    }


def validate_fixture_semantics(
    fixture: Mapping[str, Any], global_store_ids: set[str] | None = None
) -> dict[str, Any]:
    group = fixture.get("mechanism_group")
    if group == RAG_CANDIDATE_GROUP:
        return validate_rag_candidate_gate_fixture(fixture, global_store_ids or set())
    if group == RAG_SUFFICIENCY_GROUP:
        return validate_rag_sufficiency_fixture(fixture)
    if group in PERSISTENT_GROUPS:
        return validate_persistent_memory_fixture(fixture)
    raise FixtureSemanticError(
        "BLOCKED_RQ2_C0_R2_MECHANISM_SEMANTICS_CONTRACT: unknown mechanism group"
    )


def validate_all_fixture_semantics() -> dict[str, Any]:
    before = sha256_file(R1_FIXTURE_BANK_PATH)
    rows = load_frozen_fixture_rows()
    fixture_ids = [str(row["fixture_id"]) for row, _ in rows]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise FixtureSemanticError("duplicate fixture ID")
    global_store_ids = {
        identifier
        for fixture, _ in rows
        for identifier in _store_ids(fixture)
    }
    validations: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for fixture, _ in rows:
        try:
            validations.append(validate_fixture_semantics(fixture, global_store_ids))
        except FixtureSemanticError as exc:
            failures.append(
                {"fixture_id": str(fixture.get("fixture_id") or ""), "failure": str(exc)}
            )
    after = sha256_file(R1_FIXTURE_BANK_PATH)
    if before != EXPECTED_FIXTURE_BANK_SHA256 or after != before:
        raise FixtureSemanticError("BLOCKED_RQ2_C0_R2_FIXTURE_BANK_MUTATED")
    if failures:
        raise FixtureSemanticError(
            "BLOCKED_RQ2_C0_R2_FIXTURE_SEMANTIC_MISMATCH: "
            + ",".join(item["fixture_id"] for item in failures)
        )
    groups = Counter(item["mechanism_group"] for item in validations)
    candidate = [item for item in validations if item["mechanism_group"] == RAG_CANDIDATE_GROUP]
    sufficiency = [item for item in validations if item["mechanism_group"] == RAG_SUFFICIENCY_GROUP]
    persistent = [item for item in validations if item["mechanism_group"] in PERSISTENT_GROUPS]
    by_id = {item["fixture_id"]: item for item in validations}
    report = {
        "schema_version": "controlled-mechanism-fixture-semantic-validation-v1-1",
        "stage": "RQ2-C0-R2",
        "status": "PASS",
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
        "fixture_count": len(rows),
        "passed_fixture_count": len(validations),
        "failed_fixture_count": 0,
        "group_counts": dict(sorted(groups.items())),
        "rag_candidate_gate_count": len(candidate),
        "rag_sufficiency_gate_count": len(sufficiency),
        "persistent_fixture_count": len(persistent),
        "candidate_gate_empty_pre_retrieval_state_count": sum(
            bool(item["empty_pre_retrieval_state"]) for item in candidate
        ),
        "candidate_gate_downstream_id_commitment_count": sum(
            bool(item["downstream_retrieval_id_commitment"]) for item in candidate
        ),
        "candidate_gate_admission_id_violation_count": 0,
        "strict_rag_retrieval_id_existence_checks": {
            "fixtures_checked": len(sufficiency),
            "failures": 0,
        },
        "strict_persistent_retrieval_id_existence_checks": {
            "fixtures_checked": len(persistent),
            "failures": 0,
        },
        "fx_001_validation": by_id["RQ2P2-FX-001"],
        "fx_002_validation": by_id["RQ2P2-FX-002"],
        "per_fixture_validation": validations,
        "fixture_bank_sha_before": before,
        "fixture_bank_sha_after": after,
        "fixture_bank_size_bytes": R1_FIXTURE_BANK_PATH.stat().st_size,
        "fixture_bank_record_count": len(rows),
        "fixture_text_change_count": 0,
        "fixture_membership_change_count": 0,
        "expected_decision_change_count": 0,
        "coverage_change_count": 0,
    }
    return report


def legacy_validation_alias(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "controlled-mechanism-fixture-semantic-validation-v1",
        "stage": "RQ2-C0-R2",
        "status": "PASS_VIA_VERSIONED_MECHANISM_SPECIFIC_AMENDMENT",
        "superseded_by": "controlled_mechanism_fixture_semantic_validation_v1_1.json",
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
        "fixture_count": report["fixture_count"],
        "passed_fixture_count": report["passed_fixture_count"],
        "failed_fixture_count": report["failed_fixture_count"],
        "fixture_bank_sha256": report["fixture_bank_sha_after"],
    }
