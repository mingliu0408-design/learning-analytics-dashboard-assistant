"""Entirely synthetic 48-case/24-group fixture for D4 execution-integrity tests."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from . import CAPABILITIES, canonical_json_bytes, canonical_jsonl_bytes


def _caps(index: int, offset: int = 0) -> list[str]:
    selected = CAPABILITIES[(index + offset) % len(CAPABILITIES)]
    if selected in {"clarification", "safe_direct_response"}:
        return [selected]
    second = CAPABILITIES[(index + offset + 2) % 4]
    return [selected] if index % 4 else list(dict.fromkeys((selected, second)))


def build_synthetic_fixture_v1_1() -> dict[str, Any]:
    combined = []
    labels = []
    grouping = []
    for index in range(48):
        case_id = f"SYN-R3-{index:03d}"
        content = {
            "review_case_id": case_id,
            "current_query": f"SYNTHETIC_FEATURE_{index:03d}",
            "current_page": ("Overview", "Resources", "Planning")[index % 3],
            "necessary_conversation_history": (
                []
                if index % 3
                else [{"role": "user", "content": f"SYNTHETIC_CONTEXT_{index:03d}"}]
            ),
        }
        gold = set(_caps(index, 0))
        label = {
            "review_case_id": case_id,
            "context_resolution_required": "YES" if index % 5 == 0 else "NO",
            **{name: "YES" if name in gold else "NO" for name in CAPABILITIES},
            "forbidden_capabilities": [],
        }
        combined.append({**content, **label})
        labels.append(label)
        grouping.append(
            {"review_case_id": case_id, "contrast_group_id": f"SYN-GRP-{index // 2:03d}"}
        )
    return {
        "fixture_id": "RQ2_D3_R3_SYNTHETIC_D4_INTEGRITY_FIXTURE_V1_1",
        "combined_rows": combined,
        "label_rows": labels,
        "grouping_rows": grouping,
        "combined_bytes": canonical_jsonl_bytes(combined),
        "label_bytes": canonical_jsonl_bytes(labels),
        "grouping_bytes": canonical_jsonl_bytes(grouping),
    }


def synthetic_core_prediction_v1_1(
    method: str, feature: Mapping[str, Any]
) -> dict[str, Any]:
    query = str(feature["current_query"])
    if not query.startswith("SYNTHETIC_FEATURE_"):
        raise ValueError("synthetic core received non-synthetic content")
    index = int(query.rsplit("_", 1)[1])
    offset = {"B0": 1, "B1": 2, "P1": 0}[method]
    capabilities = _caps(index, offset)
    context = False if method == "B0" else index % (7 if method == "B1" else 5) == 0
    trace = {
        "method_id": method,
        "synthetic_index": index,
        "predicted_capabilities": capabilities,
        "context_resolution_required_prediction": context,
    }
    return {
        "context_resolution_required_prediction": context,
        "predicted_capabilities": capabilities,
        "core_prediction_trace_hash": hashlib.sha256(
            b"RQ2_D3_R3_SYNTHETIC_CORE_TRACE_V1_1\x00"
            + canonical_json_bytes(trace).rstrip(b"\n")
        ).hexdigest(),
    }
