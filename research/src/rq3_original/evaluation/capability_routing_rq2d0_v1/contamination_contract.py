"""Pre-registered in-memory Track-B contamination audit contract."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping


class ContaminationError(RuntimeError):
    pass


REFERENCE_PARTITIONS = (
    "RQ1_TRAIN",
    "RQ1_DEV",
    "C0_FROZEN_62_CANDIDATES",
    "TRACK_A_SAFE_IDENTITIES",
    "AUTHENTIC22",
    "SYNTHETIC35",
    "CONTEXT_MISSING3",
    "CONTROLLED_MECHANISM_FIXTURE28",
)


def normalise_query(value: str) -> str:
    folded = unicodedata.normalize("NFKC", str(value)).casefold()
    without_punctuation = "".join(
        "" if unicodedata.category(char).startswith("P") else char for char in folded
    )
    return re.sub(r"\s+", " ", without_punctuation).strip()


def history_commitment(history: Any) -> str:
    return hashlib.sha256(
        json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def query_history_commitment(query: str, history: Any) -> str:
    return hashlib.sha256(
        (
            normalise_query(query)
            + "\x00"
            + json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ).encode("utf-8")
    ).hexdigest()


def audit_contamination(
    records: Iterable[Mapping[str, Any]],
    references: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, Any]:
    records = list(records)
    reference_rows: list[dict[str, str]] = []
    id_reference: set[str] = set()
    source_reference: set[str] = set()
    for partition, rows in references.items():
        if partition not in REFERENCE_PARTITIONS:
            raise ContaminationError("unknown contamination reference partition")
        for row in rows:
            query = str(row.get("query") or row.get("effective_current_query") or "")
            history = row.get("history") or row.get("effective_conversation_history") or []
            if query:
                reference_rows.append(
                    {
                        "partition": partition,
                        "query": query,
                        "normalised": normalise_query(query),
                        "query_history": query_history_commitment(query, history),
                        "label": str(row.get("gold_label") or row.get("label") or ""),
                    }
                )
            if row.get("record_id"):
                id_reference.add(str(row["record_id"]))
            if row.get("source_record_id"):
                source_reference.add(str(row["source_record_id"]))
    exact = normalised = context = id_collision = source_collision = 0
    forbidden_identity_collision = same_label_overlap = soft_overlap = 0
    seen_ids: set[str] = set()
    seen_exact: dict[str, str] = {}
    conflicting = duplicate_id = 0
    for row in records:
        query = str(row["effective_current_query"])
        history = row["effective_conversation_history"]
        raw_id = str(row["raw_case_id"])
        label = str(row.get("gold_label") or "")
        normalised_query = normalise_query(query)
        context_key = query_history_commitment(query, history)
        for reference in reference_rows:
            exact_match = query == reference["query"]
            normalised_match = normalised_query == reference["normalised"]
            context_match = context_key == reference["query_history"]
            exact += int(exact_match)
            normalised += int(normalised_match)
            context += int(context_match)
            any_match = exact_match or normalised_match or context_match
            if not any_match:
                continue
            if reference["partition"] in {"RQ1_TRAIN", "TRACK_A_SAFE_IDENTITIES"}:
                forbidden_identity_collision += 1
            elif label and reference["label"] and label != reference["label"]:
                conflicting += 1
            elif label and reference["label"] and label == reference["label"]:
                same_label_overlap += 1
            else:
                soft_overlap += 1
        id_collision += int(raw_id in id_reference)
        source_collision += int(raw_id in source_reference)
        duplicate_id += int(raw_id in seen_ids)
        seen_ids.add(raw_id)
        key = query_history_commitment(query, history)
        if key in seen_exact and label and seen_exact[key] and label != seen_exact[key]:
            conflicting += 1
        seen_exact[key] = label
    hard_failure_count = sum(
        (
            forbidden_identity_collision,
            id_collision,
            source_collision,
            duplicate_id,
            conflicting,
        )
    )
    if hard_failure_count:
        raise ContaminationError("TRACK_B_FINAL_EVALUATION_INVALID")
    return {
        "status": "PASS",
        "record_count": len(records),
        "exact_query_overlap_count": exact,
        "normalised_query_overlap_count": normalised,
        "query_history_overlap_count": context,
        "record_id_collision_count": id_collision,
        "source_record_collision_count": source_collision,
        "duplicate_record_id_count": duplicate_id,
        "conflicting_label_duplicate_count": conflicting,
        "forbidden_train_or_final_identity_collision_count": forbidden_identity_collision,
        "same_label_overlap_count": same_label_overlap,
        "non_forbidden_unlabelled_overlap_count": soft_overlap,
        "hard_failure_count": 0,
        "same_label_duplicates": "RETAIN_PRIMARY_AND_REPORT_SENSITIVITY",
        "family_or_session_clusters": "SENSITIVITY_ONLY_NO_POST_HOC_REMOVAL",
        "raw_text_emitted": False,
    }


def contamination_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-contamination-contract-v1",
        "status": "FROZEN_BEFORE_D1_RAW_ACCESS",
        "audit_timing": "IN_MEMORY_AFTER_SINGLE_RAW_READ_BEFORE_PACKET_PERSISTENCE",
        "reference_partitions": list(REFERENCE_PARTITIONS),
        "audits": [
            "exact query overlap",
            "normalised query overlap",
            "query plus history overlap",
            "case-ID collision",
            "source-record collision",
            "family/session collision when available",
        ],
        "hard_conflicts": {
            "same_query_or_context_with_conflicting_labels": "TRACK_B_FINAL_EVALUATION_INVALID",
            "duplicate_record_id": "TRACK_B_FINAL_EVALUATION_INVALID",
            "forbidden_train_or_final_identity_collision": "TRACK_B_FINAL_EVALUATION_INVALID",
        },
        "same_label_duplicates": "RETAIN_PRIMARY_AND_REPORT_SENSITIVITY",
        "family_or_session_clusters": "SENSITIVITY_ONLY_NO_POST_HOC_REMOVAL",
        "no_threshold_or_policy_change": True,
    }
