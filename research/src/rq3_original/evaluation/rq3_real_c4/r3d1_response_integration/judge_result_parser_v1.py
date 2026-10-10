#!/usr/bin/env python3
"""Strict local parser for the frozen C4 REAL Judge transport response.

This module is deliberately offline. It converts the provider-compatible
decimal strings back to the unchanged RQ3 semantic score types, enforces the
pre-response applicability map, rejects duplicate JSON keys, and recomputes
the primary mean locally.
"""

from __future__ import annotations

import copy
import json
import math
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

TRANSPORT_SCHEMA_VERSION = "rq3-judge-response-v2-transport"
SEMANTIC_SCHEMA_VERSION = "rq3-judge-response-v1"
APPLICABILITY_SCHEMA_VERSION = "rq3-dimension-applicability-map-v1"
_JUDGE_RESULT_BLIND_ID_RE = re.compile(r"^R3B-[A-F0-9]{20}$")
_NONNEGATIVE_INTEGER_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_REQUIRED_FIELDS = {
    "response_blind_id",
    *SCORE_FIELDS.values(),
    "evidence_faithfulness",
    "unsupported_claim_count",
    "overall_applicable_mean",
    "criterion_rationales",
    "schema_version",
}


class JudgeResultError(ValueError):
    """Raised when Judge output violates the frozen transport contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise JudgeResultError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _load_json_object(raw: str | bytes | bytearray | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return copy.deepcopy(dict(raw))
    if not isinstance(raw, (str, bytes, bytearray)):
        raise JudgeResultError("Judge response must be JSON text or an object")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except JudgeResultError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JudgeResultError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: root must be an object")
    return value


def validate_applicability_map(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version",
        "freeze_status",
        "criteria",
        "applicable_primary_count",
        "applicability_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: field set")
    if value["schema_version"] != APPLICABILITY_SCHEMA_VERSION:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: schema version")
    if value["freeze_status"] != "FROZEN_BEFORE_CANDIDATE_SCORING":
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: freeze status")
    criteria = value["criteria"]
    if not isinstance(criteria, Mapping) or set(criteria) != set(PRIMARY_CRITERIA):
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: criteria")
    if any(type(criteria[name]) is not bool for name in PRIMARY_CRITERIA):
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: non-boolean flag")
    count = sum(criteria[name] for name in PRIMARY_CRITERIA)
    if count < 3 or value["applicable_primary_count"] != count:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: count")
    import hashlib

    expected_hash = hashlib.sha256(
        _canonical_json({name: criteria[name] for name in PRIMARY_CRITERIA}).encode("utf-8")
    ).hexdigest()
    if value["applicability_sha256"] != expected_hash:
        raise JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: hash")
    return copy.deepcopy(dict(value))


def recompute_overall_applicable_mean(
    score_payload: Mapping[str, Any], applicability_map: Mapping[str, Any]
) -> float:
    applicability = validate_applicability_map(applicability_map)
    scores: list[int] = []
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        value = score_payload.get(field)
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
    expected_judge_result_blind_id: str | None = None,
) -> dict[str, Any]:
    """Validate V2 transport output and return immutable V1 semantic values."""

    payload = _load_json_object(raw)
    if set(payload) != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS - set(payload))
        extra = sorted(set(payload) - _REQUIRED_FIELDS)
        raise JudgeResultError(
            f"STRICT_SCHEMA_VALIDATION_FAILED: missing={missing}, extra={extra}"
        )
    if payload["schema_version"] != TRANSPORT_SCHEMA_VERSION:
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: schema version")
    blind_id = payload["response_blind_id"]
    if not isinstance(blind_id, str) or not _JUDGE_RESULT_BLIND_ID_RE.fullmatch(blind_id):
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: opaque result ID")
    if expected_judge_result_blind_id is not None and blind_id != expected_judge_result_blind_id:
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: result ID mismatch")

    semantic = copy.deepcopy(payload)
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        value = semantic[field]
        if value == "NA":
            continue
        if value not in {"1", "2", "3", "4", "5"}:
            raise JudgeResultError(f"STRICT_SCHEMA_VALIDATION_FAILED: {field}")
        semantic[field] = int(value)
    evidence = semantic["evidence_faithfulness"]
    if evidence not in {"1", "2", "3", "4", "5"}:
        raise JudgeResultError(
            "STRICT_SCHEMA_VALIDATION_FAILED: evidence_faithfulness"
        )
    semantic["evidence_faithfulness"] = int(evidence)
    unsupported = semantic["unsupported_claim_count"]
    if not isinstance(unsupported, str) or not _NONNEGATIVE_INTEGER_RE.fullmatch(unsupported):
        raise JudgeResultError(
            "STRICT_SCHEMA_VALIDATION_FAILED: unsupported_claim_count"
        )
    semantic["unsupported_claim_count"] = int(unsupported)
    reported = semantic["overall_applicable_mean"]
    if not isinstance(reported, str) or not _DECIMAL_RE.fullmatch(reported):
        raise JudgeResultError(
            "STRICT_SCHEMA_VALIDATION_FAILED: overall_applicable_mean"
        )
    reported_value = float(reported)
    if not math.isfinite(reported_value):
        raise JudgeResultError(
            "STRICT_SCHEMA_VALIDATION_FAILED: overall_applicable_mean"
        )

    rationales = semantic["criterion_rationales"]
    expected_rationales = set(SCORE_FIELDS.values())
    if not isinstance(rationales, Mapping) or set(rationales) != expected_rationales:
        raise JudgeResultError("STRICT_SCHEMA_VALIDATION_FAILED: criterion_rationales")
    for field in sorted(expected_rationales):
        rationale = rationales[field]
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 500:
            raise JudgeResultError(
                f"STRICT_SCHEMA_VALIDATION_FAILED: {field} rationale"
            )

    local_mean = recompute_overall_applicable_mean(semantic, applicability_map)
    if not math.isclose(reported_value, local_mean, rel_tol=0.0, abs_tol=1e-9):
        raise JudgeResultError(
            "APPLICABILITY_CONTRACT_VIOLATION: reported mean differs from local mean"
        )
    semantic["overall_applicable_mean"] = local_mean
    semantic["schema_version"] = SEMANTIC_SCHEMA_VERSION
    return semantic


def retryable_failure_code(exc: BaseException) -> str | None:
    """Return the sole authorized retry class for a parser failure."""

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
    "JudgeResultError",
    "PRIMARY_CRITERIA",
    "SCORE_FIELDS",
    "parse_judge_result",
    "recompute_overall_applicable_mean",
    "retryable_failure_code",
    "validate_applicability_map",
]

