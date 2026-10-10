"""Fail-closed validation helpers for LR-2 research pair artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from pair_schema import deterministic_pair_id, validate_pair


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def verify_checksum_manifest(path: Path, base: Path) -> list[dict]:
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        target = base / relative
        actual = sha256_file(target) if target.is_file() else None
        results.append(
            {
                "path": relative,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": actual == expected,
            }
        )
    if not results or not all(row["match"] for row in results):
        raise ValueError(f"checksum verification failed: {path}")
    return results


def validate_pairs(
    pairs: Iterable[dict],
    *,
    train_ids: set[str],
    dev_ids: set[str],
    label_universe: set[str],
    baseline: bool = False,
) -> dict:
    rows = list(pairs)
    ids = set()
    failures = []
    for row in rows:
        try:
            validate_pair(row, baseline=baseline)
            if row["pair_id"] in ids:
                raise ValueError("duplicate pair_id")
            ids.add(row["pair_id"])
            if row["anchor_record_id"] not in train_ids or row["candidate_record_id"] not in train_ids:
                raise ValueError("pair record does not resolve to governed TRAIN")
            if row["anchor_record_id"] in dev_ids or row["candidate_record_id"] in dev_ids:
                raise ValueError("DEV record appears in TRAIN pair")
            if row["anchor_intent"] not in label_universe or row["candidate_intent"] not in label_universe:
                raise ValueError("pair label is outside LR-2 label universe")
            if row["pair_id"] != deterministic_pair_id(row):
                raise ValueError("non-deterministic pair ID")
        except Exception as exc:  # fail-closed summary, then caller asserts zero
            failures.append({"pair_id": row.get("pair_id"), "error": str(exc)})
    return {
        "record_count": len(rows),
        "valid_record_count": len(rows) - len(failures),
        "failure_count": len(failures),
        "failures": failures,
        "target_counts": dict(sorted(Counter(row["target"] for row in rows).items())),
        "pair_type_counts": dict(sorted(Counter(row["pair_type"] for row in rows).items())),
        "self_pair_count": sum(row["anchor_record_id"] == row["candidate_record_id"] for row in rows),
        "deterministic_pair_id_mismatch_count": sum(row["pair_id"] != deterministic_pair_id(row) for row in rows),
        "dev_record_reference_count": sum(
            row["anchor_record_id"] in dev_ids or row["candidate_record_id"] in dev_ids
            for row in rows
        ),
    }

