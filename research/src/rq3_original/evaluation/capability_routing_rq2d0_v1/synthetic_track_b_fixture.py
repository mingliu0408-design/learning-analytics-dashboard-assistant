"""Generate 48 wholly synthetic records with the governed Track-B shape."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from . import SAFE_AUTHORITY_COPY_ROOT, sha256_bytes
from .track_b_schema_contract import exact_columns, load_schema_authority


SYNTHETIC_FIXTURE_ROLE = "SYNTHETIC_TRACK_B_SHAPED_HARNESS_ONLY"


def _history(index: int, *, revised: bool = False) -> str:
    marker = "revised" if revised else "original"
    return json.dumps(
        [
            {"content": f"Synthetic {marker} user turn {index:02d}", "role": "user"},
            {
                "content": f"Synthetic {marker} assistant turn {index:02d}",
                "role": "assistant",
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _base_value(field: dict[str, Any]) -> str:
    if "constant_value" in field:
        return str(field["constant_value"])
    allowed = field.get("allowed_values")
    if allowed:
        return str(allowed[0])
    logical = str(field.get("logical_type") or "")
    if logical == "json_object":
        return "{}"
    if logical.startswith("optional_"):
        return ""
    return "SYNTHETIC"


def build_synthetic_track_b_csv(
    authority_root: Path = SAFE_AUTHORITY_COPY_ROOT,
) -> bytes:
    authority, profile, _ = load_schema_authority(authority_root)
    columns = exact_columns(authority)
    fields = {str(item["name"]): item for item in profile["fields"]}
    rows: list[dict[str, str]] = []
    for index in range(48):
        number = index + 1
        row = {name: _base_value(fields[name]) for name in columns}
        row.update(
            {
                "scenario_id": f"PV3-B-{number:04d}",
                "current_query": f"Synthetic Track B shaped query {number:02d}",
                "normalised_current_query": f"synthetic track b shaped query {number:02d}",
                "current_page": "Overview",
                "conversation_history": _history(number),
                "history_turn_count": "2",
                "history_required": "True",
                "final_effective_task_intent": "SYNTHETIC_HIDDEN_INTENT",
                "final_expected_legacy_query_type": "SYNTHETIC_HIDDEN_LEGACY",
                "final_expected_source_scope": "synthetic_scope",
                "final_expected_authority_flags": "{}",
                "final_expected_hard_guard_triggered": "False",
                "final_expected_source_scope_locked": "False",
                "final_expected_hybrid_policy_class": "SYNTHETIC_HIDDEN_POLICY",
                "expected_hybrid_policy_class_scored": "False",
                "expected_production_action": "SYNTHETIC_HIDDEN_ACTION",
                "scenario_category": "SYNTHETIC_CATEGORY",
                "scenario_family_id": f"PV3-BF-{number:04d}",
                "contrast_set_id": f"PV3-BCS-{index // 2 + 1:04d}",
                "difficulty": "synthetic",
                "semantic_accuracy_denominator_eligible": "False",
                "hybrid_evaluation_eligible": "True",
                "threshold_selection_eligible": "False",
                "primary_heldout_eligible": "True",
                "review_decision": "approved",
                "review_method": "SYNTHETIC_HARNESS_ONLY",
                "reviewed_dataset_version": "SYNTHETIC_TRACK_B_SHAPE_V1",
                "scenario_schema_version": "SYNTHETIC_TRACK_B_SHAPE_V1",
                "authoring_provenance": "D0_SYNTHETIC_HARNESS",
                "authoring_notes_safe": "Synthetic structure only",
                "human_decision": "approved",
                "human_rationale": "Synthetic hidden rationale",
                "human_final_label": "SYNTHETIC_HIDDEN_INTENT",
                "human_final_source_scope": "synthetic_scope",
                "human_final_context_requirement": "conversation_history",
                "human_final_page_context": "Overview",
                "human_naturalness": "synthetic",
                "human_unambiguity": "synthetic",
                "human_difficulty_confirmed": "yes",
                "human_independence_confirmed": "yes",
                "human_privacy_check": "pass",
                "human_revised_query": "",
                "human_revised_history": _history(number, revised=True) if index == 0 else "",
                "human_revised_expected_fields": (
                    json.dumps(
                        {"final_expected_source_scope": "synthetic_scope"},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if index == 0
                    else ""
                ),
                "reviewer_id": "SYNTHETIC",
                "review_timestamp": "2026-08-27T00:00:00+00:00",
                "review_status": "SYNTHETIC_HARNESS_ONLY",
            }
        )
        rows.append(row)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=list(columns), extrasaction="raise", lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def synthetic_fixture_identity(raw: bytes) -> dict[str, Any]:
    return {
        "role": SYNTHETIC_FIXTURE_ROLE,
        "record_count": 48,
        "sha256": sha256_bytes(raw),
        "contains_authentic_student_data": False,
        "may_be_used_as_final_evidence": False,
    }
