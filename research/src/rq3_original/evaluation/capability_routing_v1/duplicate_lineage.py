"""Duplicate classification and canonical lineage without text in summaries."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from . import canonical_json_bytes, safe_count_distribution
from .capability_case_schema import CapabilityCaseV1


@dataclass(frozen=True)
class CanonicalisationResult:
    canonical_cases: tuple[CapabilityCaseV1, ...]
    lineage_rows: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


def _group_id(key: str) -> str:
    return "DG-" + hashlib.sha256(key.encode("ascii")).hexdigest()[:16]


def canonicalise_cases(cases: Iterable[CapabilityCaseV1]) -> CanonicalisationResult:
    rows = tuple(cases)
    if not rows:
        raise ValueError("development case collection is empty")
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("case_id values must be unique before canonicalisation")

    by_exact_context: dict[str, list[CapabilityCaseV1]] = defaultdict(list)
    by_normalised_query: dict[str, list[CapabilityCaseV1]] = defaultdict(list)
    for row in rows:
        hashes = row.hashes()
        by_exact_context[hashes["query_context_hash"]].append(row)
        by_normalised_query[hashes["normalised_query_hash"]].append(row)

    canonical: list[CapabilityCaseV1] = []
    lineage: list[dict[str, Any]] = []
    exact_duplicate_extra_count = 0
    for context_hash, group in sorted(by_exact_context.items()):
        ordered = sorted(group, key=lambda item: (item.content_hash, item.case_id))
        canonical_row = ordered[0]
        canonical.append(canonical_row)
        exact_duplicate_extra_count += len(ordered) - 1
        lineage.append(
            {
                "duplicate_group_id": _group_id(context_hash),
                "canonical_case_id": canonical_row.case_id,
                "member_case_ids": [item.case_id for item in ordered],
                "all_source_lineage": [
                    {
                        "source_dataset": item.source_dataset,
                        "source_scenario_id": item.source_scenario_id,
                        "turn_index": item.turn_index,
                        "content_hash": item.content_hash,
                    }
                    for item in ordered
                ],
                "duplicate_class": (
                    "EXACT_DUPLICATE" if len(ordered) > 1 else "UNIQUE_CONTEXT"
                ),
                "query_context_hash": context_hash,
            }
        )

    query_only_group_count = 0
    context_variant_group_count = 0
    page_variant_group_count = 0
    for group in by_normalised_query.values():
        context_hashes = {item.hashes()["query_context_hash"] for item in group}
        pages = {item.current_page for item in group}
        histories = {
            hashlib.sha256(canonical_json_bytes([dict(row) for row in item.conversation_history])).hexdigest()
            for item in group
        }
        if len(context_hashes) > 1:
            query_only_group_count += 1
            if len(histories) > 1:
                context_variant_group_count += 1
            if len(pages) > 1:
                page_variant_group_count += 1

    canonical.sort(key=lambda item: item.case_id)
    lineage.sort(key=lambda item: item["canonical_case_id"])
    summary = {
        "schema_version": "capability-duplicate-lineage-summary-v1",
        "stage": "RQ2-A",
        "status": "PASS",
        "raw_case_count": len(rows),
        "canonical_case_count": len(canonical),
        "exact_duplicate_extra_count": exact_duplicate_extra_count,
        "exact_duplicate_group_count": sum(
            row["duplicate_class"] == "EXACT_DUPLICATE" for row in lineage
        ),
        "query_only_duplicate_group_count": query_only_group_count,
        "context_variant_group_count": context_variant_group_count,
        "page_variant_group_count": page_variant_group_count,
        "same_family_group_count": sum(
            count > 1
            for count in safe_count_distribution([row.scenario_family for row in rows]).values()
        ),
        "context_variants_merged": False,
        "page_variants_merged": False,
        "all_source_lineage_preserved": True,
        "canonical_selection_rule": "LOWEST_CONTENT_HASH_THEN_CASE_ID_WITHIN_IDENTICAL_QUERY_PAGE_CONTEXT",
    }
    return CanonicalisationResult(tuple(canonical), tuple(lineage), summary)
