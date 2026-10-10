"""Build blinded, synthetic-testable RQ3 judge requests without calling a model.

This module is deliberately pure and offline.  It contains no provider client,
HTTP code, model selection, response generation, or scoring implementation.
"""

from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import hmac
import json
import re
from typing import Any, Iterable, Mapping, Sequence


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

APPLICABILITY_METADATA_FIELDS = frozenset(
    {
        "applicability_metadata_version",
        "student_specific_data_relevant",
        "long_term_memory_relevant",
        "request_requires_advice",
        "gold_planning_required",
        "student_facing_support_appropriate",
        "material_lad_pages",
        "ambiguity_relevant",
        "missing_evidence_relevant",
        "insufficiency_relevant",
        "conflict_relevant",
        "boundary_handling_relevant",
    }
)

_BOOLEAN_METADATA_FIELDS = APPLICABILITY_METADATA_FIELDS - {
    "applicability_metadata_version",
    "material_lad_pages",
}

_FORBIDDEN_STRUCTURAL_KEYS = frozenset(
    {
        "condition",
        "condition_id",
        "condition_name",
        "experimental_condition",
        "rm_condition",
        "route_source",
        "router",
        "router_name",
        "p3",
        "human_gold_route",
        "gold_route",
        "annotation_case_id",
        "scenario_family_id",
        "writer_id",
        "expected_winner",
        "answer_key",
        "other_condition_response",
        "another_condition_response",
    }
)

_FORBIDDEN_EXPERIMENT_TOKENS = (
    "RM00_BASE",
    "RM10_RAG",
    "RM01_MEMORY",
    "RM11_RAG_MEMORY",
    "PLAN00_NO_PLAN",
    "PLAN01_WITH_PLAN",
    "BASE_NEVER_ON",
    "ALWAYS_ON",
    "ORACLE_ROUTE",
    "PREDICTED_ROUTE",
)

_FORBIDDEN_KEY_FRAGMENTS = (
    "condition_id",
    "condition_name",
    "experimental_condition",
    "route_source",
    "router",
    "gold_route",
    "annotation_case",
    "scenario_family",
    "writer_id",
    "expected_winner",
    "answer_key",
    "other_condition",
    "another_condition",
)

_BLIND_ID_RE = re.compile(r"^R3B-[A-F0-9]{20}$")
JUDGE_RANDOMISATION_SEED = 20260901
BLINDING_PROTOCOL_VERSION = "rq3-blinding-and-randomisation-v1"
JUDGE_REQUEST_FIELDS = frozenset(
    {
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
)


class ApplicabilityFreezeError(ValueError):
    """Raised when applicability cannot be deterministically frozen."""


class BlindingError(ValueError):
    """Raised when a blinded identifier or schedule is invalid."""


class JudgeRequestError(ValueError):
    """Raised when a judge request would violate the frozen blind contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _require_plain_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ApplicabilityFreezeError(f"{field} must be a JSON boolean")
    return value


def freeze_applicability(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the eight-criterion applicability map from pre-response metadata.

    Unknown fields are rejected so candidate text or judge output cannot enter
    this decision.  The returned hash commits only to the public applicability
    map; restricted case and condition identifiers are neither needed nor
    exposed.
    """

    if not isinstance(metadata, Mapping):
        raise ApplicabilityFreezeError("metadata must be a mapping")
    keys = set(metadata)
    if keys != APPLICABILITY_METADATA_FIELDS:
        missing = sorted(APPLICABILITY_METADATA_FIELDS - keys)
        extra = sorted(keys - APPLICABILITY_METADATA_FIELDS)
        raise ApplicabilityFreezeError(f"metadata keys mismatch; missing={missing}, extra={extra}")
    if metadata["applicability_metadata_version"] != "rq3-applicability-source-metadata-v1":
        raise ApplicabilityFreezeError("unsupported applicability metadata version")

    flags = {
        field: _require_plain_bool(metadata[field], field)
        for field in sorted(_BOOLEAN_METADATA_FIELDS)
    }
    pages = metadata["material_lad_pages"]
    if not isinstance(pages, list) or not pages:
        raise ApplicabilityFreezeError("material_lad_pages must be a non-empty JSON array")
    if any(not isinstance(page, str) or not page.strip() for page in pages):
        raise ApplicabilityFreezeError("each material LAD page must be a non-empty string")
    if len(set(pages)) != len(pages):
        raise ApplicabilityFreezeError("material_lad_pages must not contain duplicates")

    criteria = {
        "CLARITY": True,
        "PERSONALISATION": (
            flags["student_specific_data_relevant"] or flags["long_term_memory_relevant"]
        ),
        "ACTIONABILITY": flags["request_requires_advice"] or flags["gold_planning_required"],
        "CONTEXT_AWARENESS": True,
        "MOTIVATION_AND_ENGAGEMENT": flags["student_facing_support_appropriate"],
        "RELIABILITY": True,
        "MULTI_PAGE_COHESIVENESS": len(pages) > 1,
        "ERROR_HANDLING": any(
            flags[field]
            for field in (
                "ambiguity_relevant",
                "missing_evidence_relevant",
                "insufficiency_relevant",
                "conflict_relevant",
                "boundary_handling_relevant",
            )
        ),
    }
    if tuple(criteria) != PRIMARY_CRITERIA:
        raise AssertionError("internal criterion order changed")
    applicable_count = sum(criteria.values())
    if applicable_count < 3:
        raise ApplicabilityFreezeError("at least three primary criteria must be applicable")
    digest = hashlib.sha256(_canonical_json(criteria).encode("utf-8")).hexdigest()
    return {
        "schema_version": "rq3-dimension-applicability-map-v1",
        "freeze_status": "FROZEN_BEFORE_CANDIDATE_SCORING",
        "criteria": criteria,
        "applicable_primary_count": applicable_count,
        "applicability_sha256": digest,
    }


def validate_frozen_applicability_map(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate and copy a frozen applicability map."""

    expected_keys = {
        "schema_version",
        "freeze_status",
        "criteria",
        "applicable_primary_count",
        "applicability_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ApplicabilityFreezeError("invalid frozen applicability-map fields")
    if value["schema_version"] != "rq3-dimension-applicability-map-v1":
        raise ApplicabilityFreezeError("invalid applicability-map schema version")
    if value["freeze_status"] != "FROZEN_BEFORE_CANDIDATE_SCORING":
        raise ApplicabilityFreezeError("applicability map was not frozen before scoring")
    criteria = value["criteria"]
    if not isinstance(criteria, Mapping) or set(criteria) != set(PRIMARY_CRITERIA):
        raise ApplicabilityFreezeError("applicability map must contain the exact eight criteria")
    if any(type(criteria[name]) is not bool for name in PRIMARY_CRITERIA):
        raise ApplicabilityFreezeError("applicability values must be JSON booleans")
    count = sum(criteria[name] for name in PRIMARY_CRITERIA)
    if type(value["applicable_primary_count"]) is not int or value["applicable_primary_count"] != count:
        raise ApplicabilityFreezeError("applicable-primary count mismatch")
    if count < 3:
        raise ApplicabilityFreezeError("fewer than three primary criteria are applicable")
    expected_digest = hashlib.sha256(_canonical_json(dict(criteria)).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(value["applicability_sha256"]), expected_digest):
        raise ApplicabilityFreezeError("applicability-map hash mismatch")
    return {
        "schema_version": value["schema_version"],
        "freeze_status": value["freeze_status"],
        "criteria": {name: criteria[name] for name in PRIMARY_CRITERIA},
        "applicable_primary_count": value["applicable_primary_count"],
        "applicability_sha256": value["applicability_sha256"],
    }


def _require_blinding_key(blinding_key: bytes) -> bytes:
    if not isinstance(blinding_key, bytes) or len(blinding_key) < 16:
        raise BlindingError("blinding_key must be at least 16 bytes")
    return blinding_key


def _prf_hex(blinding_key: bytes, purpose: str, *parts: str) -> str:
    key = _require_blinding_key(blinding_key)
    if any(not isinstance(part, str) or not part for part in parts):
        raise BlindingError("blinding inputs must be non-empty strings")
    message = "|".join(
        [BLINDING_PROTOCOL_VERSION, str(JUDGE_RANDOMISATION_SEED), purpose, *parts]
    ).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def make_response_blind_id(
    blinding_key: bytes,
    restricted_family_key: str,
    restricted_response_source_key: str,
) -> str:
    """Create an opaque deterministic ID; never expose either restricted input."""

    digest = _prf_hex(
        blinding_key,
        "response-blind-id",
        restricted_family_key,
        restricted_response_source_key,
    )
    return "R3B-" + digest[:20].upper()


def deterministic_response_order(
    restricted_records: Sequence[Mapping[str, Any]],
    blinding_key: bytes,
) -> list[dict[str, Any]]:
    """Interleave family blocks and randomise answer order using keyed hashes.

    The input is a restricted mapping-stage object.  It is never a judge or
    human packet.  At most one response per family is emitted in a round while
    two or more families remain, which prevents routine family adjacency.
    """

    _require_blinding_key(blinding_key)
    if not isinstance(restricted_records, Sequence) or isinstance(
        restricted_records, (str, bytes, bytearray)
    ):
        raise BlindingError("restricted_records must be a sequence")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_sources: set[str] = set()
    for record in restricted_records:
        if not isinstance(record, Mapping):
            raise BlindingError("every schedule record must be a mapping")
        if set(record) != {"scenario_family_id", "response_source_key"}:
            raise BlindingError("schedule records require exactly two restricted keys")
        family = record["scenario_family_id"]
        source = record["response_source_key"]
        if not isinstance(family, str) or not family or not isinstance(source, str) or not source:
            raise BlindingError("restricted schedule keys must be non-empty strings")
        if source in seen_sources:
            raise BlindingError("response_source_key values must be unique")
        seen_sources.add(source)
        grouped[family].append(
            {
                "scenario_family_id": family,
                "response_source_key": source,
                "response_blind_id": make_response_blind_id(blinding_key, family, source),
            }
        )

    for family, rows in grouped.items():
        rows.sort(
            key=lambda row: _prf_hex(
                blinding_key, "answer-order", family, row["response_source_key"]
            )
        )

    output: list[dict[str, Any]] = []
    previous_family: str | None = None
    round_index = 0
    while any(grouped.values()):
        active = [family for family, rows in grouped.items() if rows]
        active.sort(
            key=lambda family: _prf_hex(
                blinding_key, "family-round-order", str(round_index), family
            )
        )
        if len(active) > 1 and active[0] == previous_family:
            active = active[1:] + active[:1]
        for family in active:
            output.append(grouped[family].pop(0))
            previous_family = family
        round_index += 1
    return output


def _walk_forbidden_structure(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise JudgeRequestError(f"non-string JSON key at {path}")
            folded_key = key.casefold()
            if folded_key in _FORBIDDEN_STRUCTURAL_KEYS or any(
                fragment in folded_key for fragment in _FORBIDDEN_KEY_FRAGMENTS
            ):
                raise JudgeRequestError(f"forbidden experimental field at {path}.{key}")
            _walk_forbidden_structure(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_structure(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for token in _FORBIDDEN_EXPERIMENT_TOKENS:
            if token.casefold() in value.casefold():
                raise JudgeRequestError(f"forbidden experimental token at {path}")
        if re.search(r"(?<![A-Za-z0-9])P3(?![A-Za-z0-9])", value, flags=re.IGNORECASE):
            raise JudgeRequestError(f"forbidden P3 token at {path}")


def validate_blind_judge_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate a built or loaded blind request before packet use."""

    if not isinstance(value, Mapping) or set(value) != JUDGE_REQUEST_FIELDS:
        raise JudgeRequestError("blind judge request has missing or extra fields")
    if value["schema_version"] != "rq3-blind-judge-request-v1":
        raise JudgeRequestError("unsupported blind judge request version")
    blind_id = value["response_blind_id"]
    if not isinstance(blind_id, str) or not _BLIND_ID_RE.fullmatch(blind_id):
        raise JudgeRequestError("response_blind_id does not match the frozen opaque format")
    for field in ("student_query", "current_lad_page", "candidate_response"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise JudgeRequestError(f"{field} must be a non-empty string")
    history = value["visible_conversation_history"]
    if not isinstance(history, list) or any(
        not isinstance(turn, str) or not turn.strip() for turn in history
    ):
        raise JudgeRequestError("visible_conversation_history must be an array of strings")
    normalized = copy.deepcopy(dict(value))
    normalized["frozen_applicability_map"] = validate_frozen_applicability_map(
        value["frozen_applicability_map"]
    )
    _walk_forbidden_structure(normalized)
    try:
        _canonical_json(normalized)
    except (TypeError, ValueError) as exc:
        raise JudgeRequestError("judge request must be finite JSON data") from exc
    return normalized


def build_judge_request(
    *,
    response_blind_id: str,
    student_query: str,
    current_lad_page: str,
    visible_conversation_history: Sequence[str],
    frozen_dashboard_evidence: Any,
    course_evidence_available_in_condition: Any,
    long_term_memory_available_in_condition: Any,
    planning_support_available_in_condition: Any,
    candidate_response: str,
    frozen_applicability_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one strict blind request payload; perform no scoring or I/O."""

    if not isinstance(response_blind_id, str) or not _BLIND_ID_RE.fullmatch(response_blind_id):
        raise JudgeRequestError("response_blind_id does not match the frozen opaque format")
    for name, value in (
        ("student_query", student_query),
        ("current_lad_page", current_lad_page),
        ("candidate_response", candidate_response),
    ):
        if not isinstance(value, str) or not value.strip():
            raise JudgeRequestError(f"{name} must be a non-empty string")
    if not isinstance(visible_conversation_history, Sequence) or isinstance(
        visible_conversation_history, (str, bytes, bytearray)
    ):
        raise JudgeRequestError("visible_conversation_history must be an array of strings")
    if any(not isinstance(turn, str) or not turn.strip() for turn in visible_conversation_history):
        raise JudgeRequestError("visible conversation turns must be non-empty strings")

    applicability = validate_frozen_applicability_map(frozen_applicability_map)
    payload = {
        "schema_version": "rq3-blind-judge-request-v1",
        "response_blind_id": response_blind_id,
        "student_query": student_query,
        "current_lad_page": current_lad_page,
        "visible_conversation_history": list(visible_conversation_history),
        "frozen_dashboard_evidence": copy.deepcopy(frozen_dashboard_evidence),
        "course_evidence_available_in_condition": copy.deepcopy(
            course_evidence_available_in_condition
        ),
        "long_term_memory_available_in_condition": copy.deepcopy(
            long_term_memory_available_in_condition
        ),
        "planning_support_available_in_condition": copy.deepcopy(
            planning_support_available_in_condition
        ),
        "candidate_response": candidate_response,
        "frozen_applicability_map": applicability,
    }
    return validate_blind_judge_request(payload)


def blind_ids_only(schedule: Iterable[Mapping[str, Any]]) -> list[str]:
    """Project a restricted schedule to the only identifier packets may use."""

    blind_ids: list[str] = []
    for row in schedule:
        blind_id = row.get("response_blind_id") if isinstance(row, Mapping) else None
        if not isinstance(blind_id, str) or not _BLIND_ID_RE.fullmatch(blind_id):
            raise BlindingError("schedule contains an invalid response blind ID")
        blind_ids.append(blind_id)
    if len(blind_ids) != len(set(blind_ids)):
        raise BlindingError("schedule contains duplicate response blind IDs")
    return blind_ids
