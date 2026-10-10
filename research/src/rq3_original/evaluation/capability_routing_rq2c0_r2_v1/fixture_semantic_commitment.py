"""Tracked-safe per-fixture semantic commitments with no governed text."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from . import AMENDMENT_CONTRACT_ID, sha256_bytes
from .fixture_semantic_validator import load_frozen_fixture_rows
from .text_normalisation import normalised_text_hash


def build_semantic_commitments(
    validation_report: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    validation_by_id = {
        item["fixture_id"]: item
        for item in validation_report["per_fixture_validation"]
    }
    commitments: list[dict[str, Any]] = []
    for fixture, raw_line in load_frozen_fixture_rows():
        validation = validation_by_id[fixture["fixture_id"]]
        statuses = Counter(
            str(item.get("status") or "UNSPECIFIED")
            for item in fixture["initial_store_state"]
        )
        scopes = {
            str(item.get("student_scope_id"))
            for item in fixture["initial_store_state"]
            if item.get("student_scope_id")
        }
        commitments.append(
            {
                "fixture_id": fixture["fixture_id"],
                "record_hash": sha256_bytes(raw_line),
                "mechanism_group": fixture["mechanism_group"],
                "fixture_category": fixture["fixture_category"],
                "initial_store_item_count": len(fixture["initial_store_state"]),
                "initial_status_distribution": dict(sorted(statuses.items())),
                "initial_scope_count": len(scopes),
                "input_text_hash": normalised_text_hash(
                    fixture["input_event_or_query"]["text"]
                ),
                "expected_write_authorised": bool(
                    fixture["expected_write_decision"].get("write_authorised")
                ),
                "expected_retrieval_count": len(fixture["expected_retrieval_ids"]),
                "expected_admission_count": len(fixture["expected_admission_ids"]),
                "expected_rejection_reason_codes": sorted(
                    set(fixture["expected_rejection_reasons"].values())
                ),
                "expected_clarification": fixture["expected_clarification"],
                "expected_security_state": fixture["expected_security_state"],
                "coverage_tags": list(fixture["coverage_tags"]),
                "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
                "initial_store_state_semantics": validation[
                    "initial_store_state_semantics"
                ],
                "retrieval_id_existence_rule_applied": validation[
                    "retrieval_id_existence_rule_applied"
                ],
                "evidence_sufficiency_applicable": validation[
                    "evidence_sufficiency_applicable"
                ],
                "evidence_admission_applicable": validation[
                    "evidence_admission_applicable"
                ],
                "semantic_validation_status": validation[
                    "semantic_validation_status"
                ],
            }
        )
    return tuple(commitments)
