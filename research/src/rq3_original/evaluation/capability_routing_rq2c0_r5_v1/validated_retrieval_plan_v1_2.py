"""Validated, UTC-bound wrapper for the historical R2 retrieval plan."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    RetrievalPlanV1_1,
)
from evaluation.capability_routing_rq2c0_r4_v1.student_scope_hash_contract import (
    validate_pseudonymous_student_scope_id_v1,
)

from . import VALIDATED_PLAN_ID
from .retrieval_time_integrity_v1 import parse_timezone_aware_iso8601_v1_1
from .validated_bundle_fingerprint_v1 import canonical_component_bytes_v1


PLAN_FINGERPRINT_DOMAIN = b"RQ2_VALIDATED_RETRIEVAL_PLAN_V1_2\x00"


class ValidatedRetrievalPlanError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedRetrievalPlanV1_2:
    original_plan: RetrievalPlanV1_1
    student_scope_id: str
    query_time_utc: str
    target_memory_types: tuple[str, ...]
    original_query: str
    resolved_query: str
    resolver_authorised: bool
    memory_required: bool
    plan_fingerprint: str
    validation_contract_id: str


def _bound_plan_values(plan: RetrievalPlanV1_1, query_time_utc: str) -> dict[str, Any]:
    return {
        "student_scope_id": plan.student_scope_id,
        "query_time_utc": query_time_utc,
        "target_memory_types": list(plan.target_memory_types),
        "original_query": plan.original_query,
        "resolved_query": plan.resolved_query,
        "resolver_authorised": plan.resolver_authorised,
        "memory_required": plan.memory_required,
        "validation_contract_id": VALIDATED_PLAN_ID,
    }


def _validate_plan_shape(plan: RetrievalPlanV1_1) -> None:
    if type(plan) is not RetrievalPlanV1_1:
        raise ValidatedRetrievalPlanError("UNVALIDATED_RETRIEVAL_PLAN_TYPE")
    if (
        not isinstance(plan.target_memory_types, tuple)
        or any(not isinstance(value, str) for value in plan.target_memory_types)
        or not isinstance(plan.original_query, str)
        or not isinstance(plan.resolved_query, str)
        or type(plan.resolver_authorised) is not bool
        or type(plan.memory_required) is not bool
    ):
        raise ValidatedRetrievalPlanError("INVALID_RETRIEVAL_PLAN_SCHEMA")


def validate_and_bind_retrieval_plan_v1_2(
    plan: RetrievalPlanV1_1,
) -> ValidatedRetrievalPlanV1_2:
    _validate_plan_shape(plan)
    validate_pseudonymous_student_scope_id_v1(plan.student_scope_id)
    query = parse_timezone_aware_iso8601_v1_1(plan.query_time, "query_time")
    query_utc = query.isoformat()
    values = _bound_plan_values(plan, query_utc)
    fingerprint = hashlib.sha256(
        PLAN_FINGERPRINT_DOMAIN + canonical_component_bytes_v1(values)
    ).hexdigest()
    return ValidatedRetrievalPlanV1_2(
        original_plan=plan,
        student_scope_id=plan.student_scope_id,
        query_time_utc=query_utc,
        target_memory_types=plan.target_memory_types,
        original_query=plan.original_query,
        resolved_query=plan.resolved_query,
        resolver_authorised=plan.resolver_authorised,
        memory_required=plan.memory_required,
        plan_fingerprint=fingerprint,
        validation_contract_id=VALIDATED_PLAN_ID,
    )


def verify_validated_retrieval_plan_v1_2(plan: ValidatedRetrievalPlanV1_2) -> None:
    if type(plan) is not ValidatedRetrievalPlanV1_2:
        raise ValidatedRetrievalPlanError("UNVALIDATED_RETRIEVAL_PLAN_TYPE")
    expected = validate_and_bind_retrieval_plan_v1_2(plan.original_plan)
    if plan != expected or not re.fullmatch(r"[0-9a-f]{64}", plan.plan_fingerprint):
        raise ValidatedRetrievalPlanError("STALE_OR_MUTATED_RETRIEVAL_PLAN")


def validated_retrieval_plan_contract() -> dict[str, Any]:
    return {
        "schema_version": "validated-retrieval-plan-contract-v1.2",
        "stage": "RQ2-C0-R5",
        "status": "FROZEN",
        "contract_id": VALIDATED_PLAN_ID,
        "historical_input_schema": "RetrievalPlanV1_1",
        "future_rq2c1_required_schema": "ValidatedRetrievalPlanV1_2",
        "query_time": "TIMEZONE_AWARE_AND_CANONICAL_UTC",
        "student_scope_contract": "RQ2_MEMORY_SCOPE_V1",
        "fingerprint_domain_hex": PLAN_FINGERPRINT_DOMAIN.hex(),
        "bound_fields": [
            "student_scope_id",
            "query_time_utc",
            "target_memory_types",
            "original_query",
            "resolved_query",
            "resolver_authorised",
            "memory_required",
            "validation_contract_id",
        ],
        "gold_fields_allowed": False,
        "source_role_allowed": False,
        "fixture_expected_fields_allowed": False,
        "raw_r2_plan_authorised_for_effective_retrieval": False,
        "actual_retrieval_executed": False,
    }
