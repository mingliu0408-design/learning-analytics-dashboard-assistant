"""Strictly parse frozen-format RQ3 judge output and recompute its primary mean."""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any, Mapping

from .rq3_judge_request_builder import (
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    validate_frozen_applicability_map,
)


RESPONSE_SCHEMA_VERSION = "rq3-judge-response-v1"
_RATIONALE_FIELDS = tuple(SCORE_FIELDS[name] for name in PRIMARY_CRITERIA)
_REQUIRED_FIELDS = {
    "response_blind_id",
    *SCORE_FIELDS.values(),
    "evidence_faithfulness",
    "unsupported_claim_count",
    "overall_applicable_mean",
    "criterion_rationales",
    "schema_version",
}
_BLIND_ID_RE = re.compile(r"^R3B-[A-F0-9]{20}$")


class JudgeResponseError(ValueError):
    """Raised when judge output violates schema or frozen applicability."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise JudgeResponseError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _load_payload(raw_response: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw_response, Mapping):
        return copy.deepcopy(dict(raw_response))
    if not isinstance(raw_response, (str, bytes, bytearray)):
        raise JudgeResponseError("judge response must be JSON text or a mapping")
    try:
        value = json.loads(raw_response, object_pairs_hook=_reject_duplicate_keys)
    except JudgeResponseError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JudgeResponseError("judge response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise JudgeResponseError("judge response root must be an object")
    return value


def _is_score(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 5


def recompute_overall_applicable_mean(
    score_payload: Mapping[str, Any], frozen_applicability_map: Mapping[str, Any]
) -> float:
    applicability = validate_frozen_applicability_map(frozen_applicability_map)
    scores: list[int] = []
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        value = score_payload.get(field)
        if applicability["criteria"][criterion]:
            if not _is_score(value):
                raise JudgeResponseError(f"{field} must be an integer from 1 to 5")
            scores.append(value)
        elif value != "NA":
            raise JudgeResponseError(f"{field} must be NA because frozen applicability is false")
    if len(scores) < 3:
        raise JudgeResponseError("fewer than three applicable primary scores")
    return sum(scores) / len(scores)


def parse_judge_response(
    raw_response: str | bytes | Mapping[str, Any],
    frozen_applicability_map: Mapping[str, Any],
    *,
    expected_response_blind_id: str | None = None,
) -> dict[str, Any]:
    """Validate one response and replace its reported mean with the local mean.

    The reported mean is checked only as an integrity signal.  The returned
    primary aggregate is always recomputed from applicable primary dimensions;
    neither technical audit participates in that arithmetic.
    """

    payload = _load_payload(raw_response)
    if set(payload) != _REQUIRED_FIELDS:
        missing = sorted(_REQUIRED_FIELDS - set(payload))
        extra = sorted(set(payload) - _REQUIRED_FIELDS)
        raise JudgeResponseError(f"judge response fields mismatch; missing={missing}, extra={extra}")
    if payload["schema_version"] != RESPONSE_SCHEMA_VERSION:
        raise JudgeResponseError("unsupported judge-response schema version")
    blind_id = payload["response_blind_id"]
    if not isinstance(blind_id, str) or not _BLIND_ID_RE.fullmatch(blind_id):
        raise JudgeResponseError("invalid response_blind_id")
    if expected_response_blind_id is not None and blind_id != expected_response_blind_id:
        raise JudgeResponseError("response_blind_id does not match the request")

    local_mean = recompute_overall_applicable_mean(payload, frozen_applicability_map)

    evidence_score = payload["evidence_faithfulness"]
    if not _is_score(evidence_score):
        raise JudgeResponseError("evidence_faithfulness must be an integer from 1 to 5")
    unsupported_count = payload["unsupported_claim_count"]
    if type(unsupported_count) is not int or unsupported_count < 0:
        raise JudgeResponseError("unsupported_claim_count must be a non-negative integer")

    reported_mean = payload["overall_applicable_mean"]
    if type(reported_mean) not in (int, float) or not math.isfinite(reported_mean):
        raise JudgeResponseError("overall_applicable_mean must be a finite number")
    if not math.isclose(float(reported_mean), local_mean, rel_tol=0.0, abs_tol=1e-9):
        raise JudgeResponseError("judge-reported mean does not match the local recomputation")

    rationales = payload["criterion_rationales"]
    if not isinstance(rationales, Mapping) or set(rationales) != set(_RATIONALE_FIELDS):
        raise JudgeResponseError("criterion_rationales must contain the exact eight fields")
    for field in _RATIONALE_FIELDS:
        rationale = rationales[field]
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 500:
            raise JudgeResponseError(f"{field} rationale must contain 1 to 500 characters")

    validated = copy.deepcopy(payload)
    validated["overall_applicable_mean"] = local_mean
    return validated
