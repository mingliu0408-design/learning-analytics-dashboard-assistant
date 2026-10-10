"""Local-only CapabilityCaseV1 schema and content fingerprints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from . import canonical_json_bytes
from .context_envelope import normalise_query


class CapabilityCaseError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _normalise_history(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position, raw in enumerate(history):
        row = dict(raw)
        rows.append(
            {
                "role": str(row.get("role") or "unknown"),
                "turn_order": int(row.get("turn_order", position)),
                "source": str(row.get("source") or "conversation"),
                "content": str(row.get("content") or "").strip(),
                **(
                    {"relevant": bool(row["relevant"])}
                    if "relevant" in row
                    else {}
                ),
                **(
                    {"explicit_goal": row["explicit_goal"]}
                    if row.get("explicit_goal") not in (None, "")
                    else {}
                ),
                **(
                    {"explicit_constraint": row["explicit_constraint"]}
                    if row.get("explicit_constraint") not in (None, "")
                    else {}
                ),
                **(
                    {"correction": row["correction"]}
                    if row.get("correction") not in (None, "", {})
                    else {}
                ),
                **(
                    {"referenced_items": list(row["referenced_items"])}
                    if row.get("referenced_items")
                    else {}
                ),
            }
        )
    rows.sort(key=lambda value: value["turn_order"])
    return rows


def _reject_personal_text(value: str) -> None:
    if re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", value, re.IGNORECASE):
        raise CapabilityCaseError("email-like content is forbidden")
    if re.search(r"\b(?:firebase|student[_ -]?id)\b", value, re.IGNORECASE):
        raise CapabilityCaseError("identity-like content is forbidden")


@dataclass(frozen=True)
class CapabilityCaseV1:
    case_id: str
    source_dataset: str
    source_scenario_id: str
    turn_index: int
    current_query: str
    current_page: str
    conversation_history: tuple[Mapping[str, Any], ...] = ()
    existing_expected_intent: str = ""
    existing_expected_route: str = ""
    existing_expected_source_scope: str = ""
    existing_expected_memory: bool | None = None
    existing_expected_retrieval: bool | None = None
    existing_required_capabilities: tuple[str, ...] = ()
    scenario_category: str = ""
    scenario_family: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.case_id or not self.source_dataset or not self.source_scenario_id:
            raise CapabilityCaseError("case identity fields are required")
        if not self.current_query.strip():
            raise CapabilityCaseError("current query is required")
        _reject_personal_text(self.current_query)
        for row in self.conversation_history:
            _reject_personal_text(str(row.get("content") or ""))
        if self.turn_index < 0:
            raise CapabilityCaseError("turn_index must be non-negative")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CapabilityCaseV1":
        history = _normalise_history(value.get("conversation_history") or [])
        base = {
            "case_id": str(value["case_id"]),
            "source_dataset": str(value["source_dataset"]),
            "source_scenario_id": str(value["source_scenario_id"]),
            "turn_index": int(value.get("turn_index", 0)),
            "current_query": str(value["current_query"]).strip(),
            "current_page": str(value.get("current_page") or "Overview"),
            "conversation_history": tuple(history),
            "existing_expected_intent": str(value.get("existing_expected_intent") or ""),
            "existing_expected_route": str(value.get("existing_expected_route") or ""),
            "existing_expected_source_scope": str(
                value.get("existing_expected_source_scope") or ""
            ),
            "existing_expected_memory": value.get("existing_expected_memory"),
            "existing_expected_retrieval": value.get("existing_expected_retrieval"),
            "existing_required_capabilities": tuple(
                str(item) for item in value.get("existing_required_capabilities") or []
            ),
            "scenario_category": str(value.get("scenario_category") or "unspecified"),
            "scenario_family": str(value.get("scenario_family") or "unspecified"),
            "provenance": dict(value.get("provenance") or {}),
        }
        identity_value = {
            key: (list(item) if isinstance(item, tuple) else item)
            for key, item in base.items()
            if key != "content_hash"
        }
        return cls(**base, content_hash=_digest(identity_value))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["conversation_history"] = [dict(row) for row in self.conversation_history]
        value["existing_required_capabilities"] = list(
            self.existing_required_capabilities
        )
        return value

    def hashes(self) -> dict[str, str]:
        history = [dict(row) for row in self.conversation_history]
        exact_query_hash = hashlib.sha256(self.current_query.encode("utf-8")).hexdigest()
        normalised_query_hash = hashlib.sha256(
            normalise_query(self.current_query).encode("utf-8")
        ).hexdigest()
        return {
            "exact_query_hash": exact_query_hash,
            "normalised_query_hash": normalised_query_hash,
            "query_page_hash": _digest(
                [normalise_query(self.current_query), self.current_page]
            ),
            "query_context_hash": _digest(
                [normalise_query(self.current_query), self.current_page, history]
            ),
            "source_scenario_hash": _digest(
                [self.source_dataset, self.source_scenario_id, self.turn_index]
            ),
        }


def capability_case_schema_document() -> dict[str, Any]:
    return {
        "schema_version": "capability-case-schema-v1",
        "record_schema_version": "capability-case-v1",
        "storage_policy": "FULL_RECORDS_LOCAL_ONLY_IGNORED",
        "fields": [
            "case_id",
            "source_dataset",
            "source_scenario_id",
            "turn_index",
            "current_query",
            "current_page",
            "conversation_history",
            "existing_expected_intent",
            "existing_expected_route",
            "existing_expected_source_scope",
            "existing_expected_memory",
            "existing_expected_retrieval",
            "existing_required_capabilities",
            "scenario_category",
            "scenario_family",
            "provenance",
            "content_hash",
        ],
        "tracked_summary_policy": [
            "COUNTS",
            "SOURCE_COUNTS",
            "CONTENT_HASH",
            "CATEGORY_DISTRIBUTION",
            "DUPLICATE_COUNTS",
        ],
        "tracked_natural_language_allowed": False,
    }
