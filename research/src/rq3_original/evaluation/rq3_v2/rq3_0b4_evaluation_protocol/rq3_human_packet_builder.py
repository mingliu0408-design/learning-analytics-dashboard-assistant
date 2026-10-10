"""Build blank blinded human-rating packet objects from validated judge requests."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from .rq3_judge_request_builder import (
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    JudgeRequestError,
    validate_blind_judge_request,
)


class HumanPacketError(ValueError):
    """Raised when a blank blinded human packet cannot be built safely."""


_REQUEST_FIELDS = {
    "schema_version",
    "response_blind_id",
    "student_query",
    "current_lad_page",
    "visible_conversation_history",
    "frozen_dashboard_evidence",
    "course_evidence_available_in_condition",
    "long_term_memory_available_in_condition",
    "planning_support_available_in_condition",
    "candidate_response",
    "frozen_applicability_map",
}


def build_blank_human_rating_packet(
    *,
    packet_blind_id: str,
    rater_role: str,
    judge_requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create a schema-shaped toy/future blank packet; never rate a response."""

    if not isinstance(packet_blind_id, str) or not packet_blind_id.startswith("HRP-"):
        raise HumanPacketError("packet_blind_id must start with HRP-")
    if rater_role not in {"A", "B"}:
        raise HumanPacketError("rater_role must be A or B")
    if not isinstance(judge_requests, Sequence) or isinstance(
        judge_requests, (str, bytes, bytearray)
    ):
        raise HumanPacketError("judge_requests must be a sequence")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for request in judge_requests:
        if not isinstance(request, Mapping) or set(request) != _REQUEST_FIELDS:
            raise HumanPacketError("each source request must have the exact blind request fields")
        try:
            validated_request = validate_blind_judge_request(request)
        except JudgeRequestError as exc:
            raise HumanPacketError("source request violates the blind request contract") from exc
        blind_id = validated_request["response_blind_id"]
        if blind_id in seen:
            raise HumanPacketError("duplicate response_blind_id in packet")
        seen.add(blind_id)
        item = copy.deepcopy(validated_request)
        item.pop("schema_version")
        item["criterion_scores"] = {SCORE_FIELDS[name]: None for name in PRIMARY_CRITERIA}
        item["criterion_notes"] = {SCORE_FIELDS[name]: "" for name in PRIMARY_CRITERIA}
        items.append(item)

    if not items:
        raise HumanPacketError("a packet must contain at least one response")
    return {
        "schema_version": "rq3-human-rating-packet-v1",
        "packet_status": "UNRATED_TEMPLATE",
        "packet_blind_id": packet_blind_id,
        "rater_role": rater_role,
        "rubric_version": "rq3-primary-eight-criterion-rubric-v1",
        "items": items,
        "attestation": {
            "independent_rating_confirmed": None,
            "condition_blindness_confirmed": None,
            "other_rater_scores_unseen_confirmed": None,
            "submitted_at_utc": None,
            "rater_signature": None,
        },
    }
