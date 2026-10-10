"""Completely synthetic 48-case/24-group fixture for the frozen D4 harness."""

from __future__ import annotations

from typing import Any

from . import CAPABILITIES


def build_synthetic_track_b_final_fixture_v1() -> dict[str, list[dict[str, Any]]]:
    combined: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    grouping: list[dict[str, Any]] = []
    for index in range(48):
        case_id = f"SYN-D4-CASE-{index + 1:03d}"
        group_id = f"SYN-D4-GROUP-{index // 2 + 1:02d}"
        primary = CAPABILITIES[index % len(CAPABILITIES)]
        gold = {primary}
        if index % 5 == 0 and primary not in {"clarification", "safe_direct_response"}:
            extra = CAPABILITIES[(index + 1) % 4]
            gold.add(extra)
        if "clarification" in gold:
            gold = {"clarification"}
        if "safe_direct_response" in gold:
            gold = {"safe_direct_response"}
        feature = {
            "review_case_id": case_id,
            "current_query": f"Q{index + 1:03d}",
            "current_page": ("overview", "dashboard", "course", "planning")[index % 4],
            "necessary_conversation_history": [] if index % 7 else [
                {"role": "user", "content": f"H{index + 1:03d}"}
            ],
        }
        label = {
            "review_case_id": case_id,
            "context_resolution_required": bool(index % 7 == 0),
            **{capability: ("YES" if capability in gold else "NO") for capability in CAPABILITIES},
            "forbidden_capabilities": [],
        }
        combined.append({**feature, **{key: value for key, value in label.items() if key != "review_case_id"}})
        labels.append(label)
        grouping.append({"review_case_id": case_id, "contrast_group_id": group_id})
    return {"combined": combined, "labels": labels, "grouping": grouping}


def synthetic_fixture_contract_document_v1() -> dict[str, Any]:
    fixture = build_synthetic_track_b_final_fixture_v1()
    return {
        "fixture_id": "RQ2_D3_R2_SYNTHETIC_TRACK_B_FINAL_FIXTURE_V1",
        "synthetic": True,
        "combined_record_count": len(fixture["combined"]),
        "label_record_count": len(fixture["labels"]),
        "grouping_record_count": len(fixture["grouping"]),
        "group_count": len({row["contrast_group_id"] for row in fixture["grouping"]}),
        "cases_per_group": 2,
        "uses_real_track_b_text": False,
        "uses_real_track_b_labels": False,
        "uses_real_track_b_ids": False,
    }
