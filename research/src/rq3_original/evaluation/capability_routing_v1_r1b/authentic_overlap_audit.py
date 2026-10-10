"""Aggregate overlap audit for the authentic user-turn subset."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from evaluation.learned_intent_ranking.rq1c.final_input_schema import (
    CONTAMINATION_NORMALISATION,
    deterministic_normalised_query,
)

from . import HERE, REFERENCE_SOURCES, ROOT, canonical_json_bytes, sha256_file
from .authentic_case_builder import build_authentic_cases
from .authentic_source_authority import validate_authority_package


class OverlapAuditError(RuntimeError):
    pass


EXPECTED_OVERLAPS = {
    "candidate_62": {"exact": 20, "contamination_normalised": 24},
    "unified_benchmark_62": {"exact": 21, "contamination_normalised": 25},
    "legacy_scenarios_25": {"exact": 21, "contamination_normalised": 25},
    "rq1_expanded_train_318": {
        "exact_query_hash": 20,
        "casefolded_whitespace_hash": 24,
        "lr4a_normalised_hash": 19,
    },
    "rq1_dev_84": {
        "exact_query_hash": 0,
        "casefolded_whitespace_hash": 0,
        "lr4a_normalised_hash": 0,
    },
}


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def casefolded_whitespace(value: str) -> str:
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", str(value)).strip()
    ).casefold()


def lr4a_normalised(value: str) -> str:
    folded = casefolded_whitespace(value)
    spaced = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in folded
    )
    return re.sub(r"\s+", " ", spaced).strip()


def reject_prohibited_track_path(relative: str | PurePosixPath) -> PurePosixPath:
    raw = str(relative).replace("\\", "/")
    candidate = PurePosixPath(raw)
    lowered = raw.casefold()
    if candidate.is_absolute() or ".." in candidate.parts:
        raise PermissionError("path boundary rejected")
    if any(
        token in lowered
        for token in (
            "local_final_gold",
            "final_results_local",
            "rq2_final_contextual_heldout",
            "track_a",
            "track_b",
        )
    ):
        raise PermissionError("held-out track boundary rejected before filesystem access")
    return candidate


def _read_reference(root: Path, role: str) -> list[dict[str, Any]]:
    identity = REFERENCE_SOURCES[role]
    relative = reject_prohibited_track_path(identity["relative_path"])
    path = root.joinpath(*relative.parts)
    if not path.is_file() or path.is_symlink():
        raise OverlapAuditError(f"governed reference unavailable: {role}")
    if sha256_file(path) != identity["sha256"]:
        raise OverlapAuditError(f"governed reference hash mismatch: {role}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if len(rows) != identity["record_count"]:
        raise OverlapAuditError(f"governed reference count mismatch: {role}")
    return rows


def _text_overlap(
    queries: list[str], references: list[str], transform: Callable[[str], str]
) -> int:
    identities = {transform(value) for value in references}
    return sum(transform(value) in identities for value in queries)


def build_overlap_audit(root: Path = ROOT) -> dict[str, Any]:
    queries = [row["current_query"] for row in build_authentic_cases(root)]
    candidate = _read_reference(root, "candidate_62")
    unified = _read_reference(root, "unified_benchmark_62")
    legacy = _read_reference(root, "legacy_scenarios_25")
    train = _read_reference(root, "rq1_expanded_train_318")
    dev = _read_reference(root, "rq1_dev_84")

    train_hash_sets = {
        "exact_query_hash": {str(row["query_sha256"]) for row in train},
        "casefolded_whitespace_hash": {
            str(row["casefolded_whitespace_query_sha256"]) for row in train
        },
        "lr4a_normalised_hash": {
            str(row["normalised_query_sha256"]) for row in train
        },
    }
    dev_hash_sets = {
        "exact_query_hash": {str(row["query_sha256"]) for row in dev},
        "casefolded_whitespace_hash": {
            str(row["casefolded_whitespace_query_sha256"]) for row in dev
        },
        "lr4a_normalised_hash": {
            str(row["normalised_query_sha256"]) for row in dev
        },
    }
    query_hashes = {
        "exact_query_hash": [_sha_text(value) for value in queries],
        "casefolded_whitespace_hash": [
            _sha_text(casefolded_whitespace(value)) for value in queries
        ],
        "lr4a_normalised_hash": [
            _sha_text(lr4a_normalised(value)) for value in queries
        ],
    }
    observed = {
        "candidate_62": {
            "exact": _text_overlap(queries, [str(row["query"]) for row in candidate], lambda x: x),
            "contamination_normalised": _text_overlap(
                queries,
                [str(row["query"]) for row in candidate],
                deterministic_normalised_query,
            ),
        },
        "unified_benchmark_62": {
            "exact": _text_overlap(
                queries, [str(row["student_query"]) for row in unified], lambda x: x
            ),
            "contamination_normalised": _text_overlap(
                queries,
                [str(row["student_query"]) for row in unified],
                deterministic_normalised_query,
            ),
        },
        "legacy_scenarios_25": {
            "exact": _text_overlap(
                queries, [str(row["student_query"]) for row in legacy], lambda x: x
            ),
            "contamination_normalised": _text_overlap(
                queries,
                [str(row["student_query"]) for row in legacy],
                deterministic_normalised_query,
            ),
        },
        "rq1_expanded_train_318": {
            mode: sum(value in train_hash_sets[mode] for value in query_hashes[mode])
            for mode in train_hash_sets
        },
        "rq1_dev_84": {
            mode: sum(value in dev_hash_sets[mode] for value in query_hashes[mode])
            for mode in dev_hash_sets
        },
    }
    if observed != EXPECTED_OVERLAPS:
        raise OverlapAuditError("BLOCKED_RQ2_A_R1B_OVERLAP_AUDIT_MISMATCH")
    authority = validate_authority_package()["manifest"]
    track_a = authority["overlap_audit"]["rq1_track_a_128"]
    if track_a != {"contamination_normalised_overlap": 0, "exact_overlap": 0}:
        raise OverlapAuditError("safe Track-A authority metadata mismatch")
    return {
        "schema_version": "authentic-overlap-audit-v1",
        "stage": "RQ2-A-R1B",
        "status": "PASS",
        "authentic_case_count": len(queries),
        "normalisation_contracts": {
            "contamination_normalised": CONTAMINATION_NORMALISATION,
            "casefolded_whitespace": "NFKC_TRIM_COLLAPSE_WHITESPACE_CASEFOLD",
            "lr4a_normalised": (
                "NFKC_TRIM_COLLAPSE_WHITESPACE_CASEFOLD_"
                "REPLACE_UNICODE_PUNCTUATION_WITH_SPACE"
            ),
        },
        "reference_sources": {
            role: {
                "sha256": identity["sha256"],
                "record_count": identity["record_count"],
            }
            for role, identity in REFERENCE_SOURCES.items()
        },
        "observed_overlap": observed,
        "expected_overlap": EXPECTED_OVERLAPS,
        "all_recomputable_counts_match": True,
        "track_a_overlap_from_safe_authority_only": {
            "exact": 0,
            "contamination_normalised": 0,
            "raw_track_accessed": False,
        },
        "track_b": {
            "role": "RQ2_FINAL_CONTEXTUAL_HELDOUT",
            "searched": False,
            "listed": False,
            "accessed": False,
        },
        "methodological_conclusion": (
            "AUTHENTIC_SUBSET_NOT_INDEPENDENT_OF_C0_RQ1_TRAIN_OR_LEGACY_MATERIAL"
        ),
        "permitted_model_result_role": (
            "DESCRIPTIVE_IN_SAMPLE_AUTHENTICITY_DIAGNOSTIC"
        ),
        "eligible_for_primary_development_selection": False,
        "eligible_for_final_comparison": False,
        "per_case_overlap_ledger_tracked": False,
    }


def write_overlap_audit(root: Path = ROOT) -> dict[str, Any]:
    value = build_overlap_audit(root)
    (HERE / "authentic_overlap_audit_v1.json").write_bytes(canonical_json_bytes(value))
    return value
