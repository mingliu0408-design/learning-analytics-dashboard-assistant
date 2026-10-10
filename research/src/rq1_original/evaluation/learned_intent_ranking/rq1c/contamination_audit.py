"""Hash-only contamination checks performed after one-shot parsing, before scoring."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import ROOT
from .final_input_schema import deterministic_normalised_query


class FinalEvaluationInvalid(RuntimeError):
    """A preregistered final-set integrity gate failed."""


TRAIN_MANIFEST = (
    "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
    "ranker_expanded_train_manifest_candidate_v2.jsonl"
)
DEV_MANIFEST = (
    "evaluation/learned_intent_ranking/lr1r/"
    "ranker_dev_manifest_candidate_v2.jsonl"
)
CANDIDATE_INDEX = "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"

EXPECTED_REFERENCE_HASHES = {
    TRAIN_MANIFEST: "623bcdeaad62ae20559c616dc57aedfb22bd2d006f0beb6888da88d549c40805",
    DEV_MANIFEST: "7765ffbbe48fcde543b60561f22a03cef596235af07eed58540aacb64334f09f",
    CANDIDATE_INDEX: "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line
    ]


def build_reference_identity_sets(root: Path = ROOT) -> dict[str, Any]:
    rows_by_role: dict[str, list[dict[str, Any]]] = {}
    for role, relative in (
        ("TRAIN", TRAIN_MANIFEST),
        ("DEV", DEV_MANIFEST),
        ("CANDIDATE", CANDIDATE_INDEX),
    ):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise FinalEvaluationInvalid("governed contamination reference unavailable")
        if _sha256_file(path) != EXPECTED_REFERENCE_HASHES[relative]:
            raise FinalEvaluationInvalid("governed contamination reference hash mismatch")
        rows_by_role[role] = _read_jsonl(path)
    if {role: len(rows) for role, rows in rows_by_role.items()} != {
        "TRAIN": 318,
        "DEV": 84,
        "CANDIDATE": 62,
    }:
        raise FinalEvaluationInvalid("governed contamination reference count mismatch")
    result: dict[str, Any] = {}
    for role, rows in rows_by_role.items():
        exact_hashes: set[str] = set()
        normalised_hashes: set[str] = set()
        family_ids: set[str] = set()
        for row in rows:
            if role == "CANDIDATE":
                query = str(row["query"])
                exact_hashes.add(_sha256_text(query))
                normalised_hashes.add(_sha256_text(deterministic_normalised_query(query)))
                family = str(row.get("final_paraphrase_family_id") or "").strip()
            else:
                exact_hashes.add(str(row["query_sha256"]))
                normalised_hashes.add(str(row["normalised_query_sha256"]))
                family = str(
                    row.get("paraphrase_family_id")
                    or row.get("final_paraphrase_family_id")
                    or ""
                ).strip()
            if family:
                family_ids.add(family)
        result[role] = {
            "record_count": len(rows),
            "exact_query_hashes": exact_hashes,
            "normalised_query_hashes": normalised_hashes,
            "family_ids": family_ids,
        }
    return result


def _duplicate_extra_count(values: Iterable[str]) -> int:
    counts = Counter(values)
    return sum(value - 1 for value in counts.values() if value > 1)


def audit_contamination(
    final_records: list[Mapping[str, Any]],
    references: Mapping[str, Any],
) -> dict[str, Any]:
    record_ids = [str(row["record_id"]) for row in final_records]
    queries = [str(row["query"]) for row in final_records]
    normalised = [deterministic_normalised_query(value) for value in queries]
    exact_hashes = [_sha256_text(value) for value in queries]
    normalised_hashes = [_sha256_text(value) for value in normalised]
    duplicate_record_ids = _duplicate_extra_count(record_ids)
    duplicate_queries = _duplicate_extra_count(queries)
    duplicate_normalised = _duplicate_extra_count(normalised)
    labels_by_query: dict[str, set[str]] = defaultdict(set)
    labels_by_normalised: dict[str, set[str]] = defaultdict(set)
    for row, query, normal in zip(final_records, queries, normalised, strict=True):
        labels_by_query[query].add(str(row["gold_label"]))
        labels_by_normalised[normal].add(str(row["gold_label"]))
    conflicting_raw = sum(len(values) > 1 for values in labels_by_query.values())
    conflicting_normalised = sum(
        len(values) > 1 for values in labels_by_normalised.values()
    )
    same_label_duplicate_groups = sum(
        len(values) == 1 and queries.count(query) > 1
        for query, values in labels_by_query.items()
    )
    overlap: dict[str, dict[str, int]] = {}
    final_exact_set = set(exact_hashes)
    final_normalised_set = set(normalised_hashes)
    final_families = {str(row.get("family_id") or "") for row in final_records} - {""}
    for role in ("TRAIN", "DEV", "CANDIDATE"):
        reference = references[role]
        overlap[role] = {
            "exact_query_overlap_count": len(
                final_exact_set & set(reference["exact_query_hashes"])
            ),
            "normalised_query_overlap_count": len(
                final_normalised_set & set(reference["normalised_query_hashes"])
            ),
            "family_overlap_count": len(
                final_families & set(reference.get("family_ids") or set())
            ),
        }
    hard_overlap_count = sum(
        row["exact_query_overlap_count"] + row["normalised_query_overlap_count"]
        for row in overlap.values()
    )
    hard_failure_count = (
        duplicate_record_ids
        + hard_overlap_count
        + conflicting_raw
        + conflicting_normalised
    )
    return {
        "schema_version": "rq1c-final-contamination-audit-v1",
        "status": "PASS" if hard_failure_count == 0 else "FINAL_EVALUATION_INVALID",
        "record_count": len(final_records),
        "duplicate_record_id_extra_count": duplicate_record_ids,
        "internal_duplicate_query_extra_count": duplicate_queries,
        "internal_duplicate_normalised_query_extra_count": duplicate_normalised,
        "conflicting_identical_query_group_count": conflicting_raw,
        "conflicting_identical_normalised_query_group_count": conflicting_normalised,
        "same_label_internal_duplicate_group_count": same_label_duplicate_groups,
        "reference_overlap": overlap,
        "hard_overlap_count": hard_overlap_count,
        "hard_failure_count": hard_failure_count,
        "same_label_duplicate_policy": "RETAIN_PRIMARY_AND_REPORT_UNIQUE_QUERY_SENSITIVITY",
        "family_overlap_policy": "REPORT_SECONDARY_CLUSTER_SENSITIVITY_WITHOUT_MODEL_CHANGE",
        "query_text_emitted": False,
    }


def require_contamination_clear(report: Mapping[str, Any]) -> None:
    if report.get("status") != "PASS" or int(report.get("hard_failure_count", -1)) != 0:
        raise FinalEvaluationInvalid("FINAL_EVALUATION_INVALID")
