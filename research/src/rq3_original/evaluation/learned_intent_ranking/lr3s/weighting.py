"""Governed row-weight construction for the LR-3S symmetry ablation."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Any


CONDITIONS = ("S1_UNORDERED_EQUAL_WEIGHT", "S2_UNORDERED_CLASS_BALANCED")


def unordered_pair_id(anchor_record_id: str, candidate_record_id: str) -> str:
    """Return an unambiguous deterministic canonical identity without labels."""
    return json.dumps(sorted([anchor_record_id, candidate_record_id]), ensure_ascii=False, separators=(",", ":"))


def directed_membership_hash(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        identity = {
            "pair_id": row["pair_id"],
            "anchor_record_id": row["anchor_record_id"],
            "candidate_record_id": row["candidate_record_id"],
            "target": row["target"],
            "relationship_class": row["relationship_class"],
        }
        digest.update(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def weight_epoch_rows(rows: list[dict[str, Any]], condition: str, epoch: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if condition not in CONDITIONS:
        raise ValueError(f"unsupported LR-3S condition: {condition}")
    pair_ids = [unordered_pair_id(row["anchor_record_id"], row["candidate_record_id"]) for row in rows]
    multiplicities = Counter(pair_ids)
    unexpected = {pair_id: value for pair_id, value in multiplicities.items() if value not in {1, 2}}
    if unexpected:
        raise ValueError(f"unexpected unordered-pair multiplicities: {unexpected}")
    target_by_pair: dict[str, int] = {}
    for pair_id, row in zip(pair_ids, rows):
        target = int(row["target"])
        if pair_id in target_by_pair and target_by_pair[pair_id] != target:
            raise ValueError("unordered pair has inconsistent targets")
        target_by_pair[pair_id] = target

    base_weights = [1.0 / multiplicities[pair_id] for pair_id in pair_ids]
    positive_base = math.fsum(weight for weight, row in zip(base_weights, rows) if int(row["target"]) == 1)
    negative_base = math.fsum(weight for weight, row in zip(base_weights, rows) if int(row["target"]) == 0)
    if positive_base <= 0.0 or negative_base <= 0.0:
        raise ValueError("both classes must have positive effective weight")
    if condition == "S1_UNORDERED_EQUAL_WEIGHT":
        multipliers = {0: 1.0, 1: 1.0}
    else:
        balanced_target = (positive_base + negative_base) / 2.0
        multipliers = {0: balanced_target / negative_base, 1: balanced_target / positive_base}

    weighted_rows = []
    contributions: dict[str, float] = defaultdict(float)
    for row, pair_id, base_weight in zip(rows, pair_ids, base_weights):
        target = int(row["target"])
        final_weight = base_weight * multipliers[target]
        enriched = dict(row)
        enriched.update({
            "unordered_pair_id": pair_id,
            "unordered_pair_multiplicity": multiplicities[pair_id],
            "base_pair_weight": base_weight,
            "class_multiplier": multipliers[target],
            "final_row_weight": final_weight,
        })
        weighted_rows.append(enriched)
        contributions[pair_id] += base_weight if condition.startswith("S2_") else final_weight

    positive_final = math.fsum(row["final_row_weight"] for row in weighted_rows if int(row["target"]) == 1)
    negative_final = math.fsum(row["final_row_weight"] for row in weighted_rows if int(row["target"]) == 0)
    tolerance = 1e-12
    if condition == "S1_UNORDERED_EQUAL_WEIGHT" and any(abs(value - 1.0) > tolerance for value in contributions.values()):
        raise ValueError("S1 unordered-pair contribution is not exactly one within tolerance")
    if condition == "S2_UNORDERED_CLASS_BALANCED":
        if any(abs(value - 1.0) > tolerance for value in contributions.values()):
            raise ValueError("S2 base unordered-pair contribution is not one within tolerance")
        if abs(positive_final - negative_final) > tolerance:
            raise ValueError("S2 class totals are not equal")

    unique_positive = sum(target == 1 for target in target_by_pair.values())
    unique_negative = sum(target == 0 for target in target_by_pair.values())
    weights = [row["final_row_weight"] for row in weighted_rows]
    audit = {
        "epoch": epoch,
        "condition": condition,
        "directed_membership_sha256": directed_membership_hash(rows),
        "directed_rows": len(rows),
        "unique_unordered_pairs": len(multiplicities),
        "reverse_duplicate_groups": sum(value == 2 for value in multiplicities.values()),
        "multiplicity_distribution": dict(sorted(Counter(str(value) for value in multiplicities.values()).items())),
        "raw_positive_rows": sum(int(row["target"]) == 1 for row in rows),
        "raw_negative_rows": sum(int(row["target"]) == 0 for row in rows),
        "unique_positive_pairs": unique_positive,
        "unique_negative_pairs": unique_negative,
        "positive_base_weight": positive_base,
        "negative_base_weight": negative_base,
        "positive_class_multiplier": multipliers[1],
        "negative_class_multiplier": multipliers[0],
        "total_effective_positive_weight": positive_final,
        "total_effective_negative_weight": negative_final,
        "minimum_row_weight": min(weights),
        "maximum_row_weight": max(weights),
        "mean_row_weight": math.fsum(weights) / len(weights),
        "effective_total_sample_weight": math.fsum(weights),
        "per_unordered_pair_contribution_verified": True,
        "class_balance_verified": condition == "S2_UNORDERED_CLASS_BALANCED" and abs(positive_final - negative_final) <= tolerance,
        "membership_unchanged": True,
        "unexpected_multiplicity_count": 0,
        "numerical_tolerance": tolerance,
    }
    return weighted_rows, audit
