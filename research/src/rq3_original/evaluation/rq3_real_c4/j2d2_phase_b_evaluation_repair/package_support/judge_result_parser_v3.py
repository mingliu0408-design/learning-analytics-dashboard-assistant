#!/usr/bin/env python3
"""Strict offline parser for the C4 REAL Judge continuation transport.

Parser V3 preserves the complete Parser-V2 semantic and applicability
contract.  Its only validity-policy change is removal of the local,
non-schema 500-character per-rationale ceiling.  Rationales remain required
to be strings and non-empty after trimming, and are never changed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping


PRIMARY_CRITERIA = (
    "CLARITY",
    "PERSONALISATION",
    "ACTIONABILITY",
    "CONTEXT_AWARENESS",
    "MOTIVATION_AND_ENGAGEMENT",
    "RELIABILITY",
    "MULTI_PAGE_COHESIVENESS",
    "ERROR_HANDLING",
)

SCORE_FIELDS = {
    "CLARITY": "clarity",
    "PERSONALISATION": "personalisation",
    "ACTIONABILITY": "actionability",
    "CONTEXT_AWARENESS": "context_awareness",
    "MOTIVATION_AND_ENGAGEMENT": "motivation_and_engagement",
    "RELIABILITY": "reliability",
    "MULTI_PAGE_COHESIVENESS": "multi_page_cohesiveness",
    "ERROR_HANDLING": "error_handling",
}

TRANSPORT_SCHEMA_VERSION = "rq3-judge-response-r3d1-r2-transport"
SEMANTIC_SCHEMA_VERSION = "rq3-judge-response-v1"
APPLICABILITY_SCHEMA_VERSION = "rq3-dimension-applicability-map-v1"
_RESULT_ID_RE = re.compile(r"^R3B-[A-F0-9]{20}$")
_NONNEGATIVE_INTEGER_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_SCORES = {"1", "2", "3", "4", "5"}
_PROVIDER_FIELDS = {
    *SCORE_FIELDS.values(),
    "evidence_faithfulness",
    "unsupported_claim_count",
    "criterion_rationales",
    "schema_version",
}


class JudgeResultError(ValueError):
    """Raised when a Provider result violates the V3 transport contract."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise JudgeResultError(
                f"STRICT_SCHEMA_VALIDATION_FAILED: duplicate JSON key: {key}"
            )
        output[key] = value
    return output


def _load_json_object(
    raw: str | bytes | bytearray | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return copy.deepcopy(dict(raw))
    if not isinstance(raw, (str, bytes, bytearray)):
        raise JudgeResultError("INVALID_JSON: result must be JSON text or an object")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except JudgeResultError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JudgeResultError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: root is not an object")
    return value


def validate_applicability_map(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "freeze_status",
        "criteria",
        "applicable_primary_count",
        "applicability_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: field set")
    if value["schema_version"] != APPLICABILITY_SCHEMA_VERSION:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: schema version")
    if value["freeze_status"] != "FROZEN_BEFORE_CANDIDATE_SCORING":
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: freeze status")
    criteria = value["criteria"]
    if not isinstance(criteria, Mapping) or set(criteria) != set(PRIMARY_CRITERIA):
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: criteria field set")
    if any(type(criteria[name]) is not bool for name in PRIMARY_CRITERIA):
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: non-boolean flag")
    count = sum(criteria[name] for name in PRIMARY_CRITERIA)
    if count < 3 or type(value["applicable_primary_count"]) is not int:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: count type/range")
    if value["applicable_primary_count"] != count:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: count mismatch")
    expected_hash = hashlib.sha256(
        canonical_json_bytes({name: criteria[name] for name in PRIMARY_CRITERIA})
    ).hexdigest()
    if value["applicability_sha256"] != expected_hash:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: hash")
    return copy.deepcopy(dict(value))


def recompute_overall_applicable_mean(
    semantic_scores: Mapping[str, Any], applicability_map: Mapping[str, Any]
) -> float:
    applicability = validate_applicability_map(applicability_map)
    scores: list[int] = []
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        value = semantic_scores.get(field)
        if applicability["criteria"][criterion]:
            if type(value) is not int or not 1 <= value <= 5:
                raise JudgeResultError(
                    f"APPLICABILITY_CONTRACT_VIOLATION: {field} must be 1-5"
                )
            scores.append(value)
        elif value != "NA":
            raise JudgeResultError(
                f"APPLICABILITY_CONTRACT_VIOLATION: {field} must be NA"
            )
    return sum(scores) / len(scores)


def parse_judge_result(
    raw: str | bytes | bytearray | Mapping[str, Any],
    applicability_map: Mapping[str, Any],
    *,
    expected_judge_result_blind_id: str,
) -> dict[str, Any]:
    """Return the unchanged semantic score object after strict local parsing."""

    payload = _load_json_object(raw)
    if set(payload) != _PROVIDER_FIELDS:
        missing = sorted(_PROVIDER_FIELDS - set(payload))
        extra = sorted(set(payload) - _PROVIDER_FIELDS)
        raise JudgeResultError(
            f"STRICT_SCHEMA_VALIDATION_FAILED: missing={missing}, extra={extra}"
        )
    if payload["schema_version"] != TRANSPORT_SCHEMA_VERSION:
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: schema version")
    if not isinstance(expected_judge_result_blind_id, str) or not _RESULT_ID_RE.fullmatch(
        expected_judge_result_blind_id
    ):
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: expected result ID")

    semantic: dict[str, Any] = {}
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        value = payload[field]
        if not isinstance(value, str) or value not in _SCORES | {"NA"}:
            raise JudgeResultError(f"STRICT_SCHEMA_VALIDATION_FAILED: {field}")
        semantic[field] = value if value == "NA" else int(value)

    evidence = payload["evidence_faithfulness"]
    if not isinstance(evidence, str) or evidence not in _SCORES:
        raise JudgeResultError(
            "STRICT_SCHEMA_VALIDATION_FAILED: evidence_faithfulness"
        )
    unsupported = payload["unsupported_claim_count"]
    if not isinstance(unsupported, str) or not _NONNEGATIVE_INTEGER_RE.fullmatch(
        unsupported
    ):
        raise JudgeResultError(
            "STRICT_SCHEMA_VALIDATION_FAILED: unsupported_claim_count"
        )

    rationales = payload["criterion_rationales"]
    expected_rationales = set(SCORE_FIELDS.values())
    if not isinstance(rationales, Mapping) or set(rationales) != expected_rationales:
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: criterion_rationales")
    copied_rationales: dict[str, str] = {}
    for field in sorted(expected_rationales):
        rationale = rationales[field]
        if not isinstance(rationale, str) or not rationale.strip():
            raise JudgeResultError(
                f"STRICT_SCHEMA_VALIDATION_FAILED: {field} rationale"
            )
        copied_rationales[field] = rationale

    applicability = validate_applicability_map(applicability_map)
    local_mean = recompute_overall_applicable_mean(semantic, applicability)
    return {
        "response_blind_id": expected_judge_result_blind_id,
        **semantic,
        "evidence_faithfulness": int(evidence),
        "unsupported_claim_count": int(unsupported),
        "overall_applicable_mean": local_mean,
        "criterion_rationales": copied_rationales,
        "schema_version": SEMANTIC_SCHEMA_VERSION,
    }


def rationale_lengths(
    raw: str | bytes | bytearray | Mapping[str, Any],
) -> dict[str, int]:
    """Return rationale character lengths without modifying the result."""

    payload = _load_json_object(raw)
    rationales = payload.get("criterion_rationales")
    if not isinstance(rationales, Mapping):
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: criterion_rationales")
    output: dict[str, int] = {}
    for field in sorted(SCORE_FIELDS.values()):
        value = rationales.get(field)
        if not isinstance(value, str):
            raise JudgeResultError(
                f"STRICT_SCHEMA_VALIDATION_FAILED: {field} rationale"
            )
        output[field] = len(value)
    return output


def retryable_failure_code(exc: BaseException) -> str | None:
    text = str(exc)
    for code in (
        "INVALID_JSON",
        "STRICT_SCHEMA_VALIDATION_FAILED",
        "APPLICABILITY_CONTRACT_VIOLATION",
    ):
        if code in text:
            return code
    return None


__all__ = [
    "APPLICABILITY_SCHEMA_VERSION",
    "JudgeResultError",
    "PRIMARY_CRITERIA",
    "SCORE_FIELDS",
    "SEMANTIC_SCHEMA_VERSION",
    "TRANSPORT_SCHEMA_VERSION",
    "canonical_json_bytes",
    "parse_judge_result",
    "rationale_lengths",
    "recompute_overall_applicable_mean",
    "retryable_failure_code",
    "validate_applicability_map",
]
