"""Offline transport adapter for the frozen RQ3 Judge semantic contract."""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Mapping

from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_request_builder import (
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_response_parser import (
    JudgeResponseError,
    parse_judge_response,
)


TRANSPORT_SCHEMA_VERSION = "rq3-judge-response-v2-transport"
SEMANTIC_SCHEMA_VERSION = "rq3-judge-response-v1"
_NONNEGATIVE_INTEGER = re.compile(r"^(?:0|[1-9][0-9]*)$")


def normalise_judge_transport_v2(
    value: Mapping[str, Any],
    frozen_applicability_map: Mapping[str, Any],
    *,
    expected_response_blind_id: str | None = None,
) -> dict[str, Any]:
    """Convert V2 transport strings and validate them under the V1 semantics."""

    if not isinstance(value, Mapping):
        raise JudgeResponseError("judge V2 transport response must be an object")
    payload = copy.deepcopy(dict(value))
    if payload.get("schema_version") != TRANSPORT_SCHEMA_VERSION:
        raise JudgeResponseError("unsupported Judge V2 transport schema version")
    for criterion in PRIMARY_CRITERIA:
        field = SCORE_FIELDS[criterion]
        score = payload.get(field)
        if score == "NA":
            continue
        if score not in {"1", "2", "3", "4", "5"}:
            raise JudgeResponseError(f"{field} is not a V2 score string")
        payload[field] = int(score)
    evidence_score = payload.get("evidence_faithfulness")
    if evidence_score not in {"1", "2", "3", "4", "5"}:
        raise JudgeResponseError("invalid V2 evidence_faithfulness")
    payload["evidence_faithfulness"] = int(evidence_score)
    unsupported = payload.get("unsupported_claim_count")
    if not isinstance(unsupported, str) or not _NONNEGATIVE_INTEGER.fullmatch(unsupported):
        raise JudgeResponseError("invalid V2 unsupported_claim_count")
    payload["unsupported_claim_count"] = int(unsupported)
    mean_text = payload.get("overall_applicable_mean")
    if not isinstance(mean_text, str):
        raise JudgeResponseError("invalid V2 overall_applicable_mean")
    try:
        mean_value = float(mean_text)
    except ValueError as exc:
        raise JudgeResponseError("invalid V2 overall_applicable_mean") from exc
    if not math.isfinite(mean_value):
        raise JudgeResponseError("invalid V2 overall_applicable_mean")
    payload["overall_applicable_mean"] = mean_value
    payload["schema_version"] = SEMANTIC_SCHEMA_VERSION
    return parse_judge_response(
        payload,
        frozen_applicability_map,
        expected_response_blind_id=expected_response_blind_id,
    )


__all__ = [
    "SEMANTIC_SCHEMA_VERSION",
    "TRANSPORT_SCHEMA_VERSION",
    "normalise_judge_transport_v2",
]
