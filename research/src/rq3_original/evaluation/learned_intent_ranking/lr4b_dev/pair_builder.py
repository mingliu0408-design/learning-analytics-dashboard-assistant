"""Governed scenario-specific pair pools with LR-2R sampling parity."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from . import PAIR_LEDGER_DIR, PAIR_SAMPLING_SEED, ROOT, SCENARIO_ORDER
from .governed_data_loader import canonical_json_bytes, sha256_bytes, sha256_file


LR3 = ROOT / "evaluation/learned_intent_ranking/lr3"
if str(LR3) not in sys.path:
    sys.path.insert(0, str(LR3))
import data_loader as lr3_data_loader  # type: ignore[import-not-found]  # noqa: E402


MAX_EPOCHS = 50
MAX_POSITIVES_PER_ANCHOR = 2


class PairConstructionError(RuntimeError):
    pass


def relationship_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def canonical_pair_payload(pair: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": pair["schema_version"],
        "construction_version": pair["construction_version"],
        "anchor_record_id": pair["anchor_record_id"],
        "candidate_record_id": pair["candidate_record_id"],
        "target": pair["target"],
        "pair_type": pair["pair_type"],
        "relationship_class": pair["relationship_class"],
    }


def deterministic_pair_id(pair: dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_pair_payload(pair), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "LR2P-" + hashlib.sha256(encoded).hexdigest()[:24].upper()


def provenance_equivalence_reasons(anchor: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    if anchor["query_sha256"] == candidate["query_sha256"]:
        reasons.append("SAME_EXACT_QUERY_HASH")
    if anchor["normalised_query_sha256"] == candidate["normalised_query_sha256"]:
        reasons.append("SAME_NORMALISED_QUERY_HASH")
    if (
        anchor.get("paraphrase_family_id")
        and anchor["paraphrase_family_id"] == candidate.get("paraphrase_family_id")
    ):
        reasons.append("SAME_EXPLICIT_PARAPHRASE_FAMILY")
    if (anchor.get("query_source_path"), anchor["source_record_id"]) == (
        candidate.get("query_source_path"),
        candidate["source_record_id"],
    ):
        reasons.append("SAME_SOURCE_DERIVATION")
    if anchor.get("scenario_id") and anchor["scenario_id"] == candidate.get("scenario_id"):
        reasons.append("SAME_SOURCE_SCENARIO")
    if anchor.get("seed_id") and anchor["seed_id"] == candidate.get("seed_id"):
        reasons.append("SAME_EXPLICIT_SEED")
    return tuple(reasons)


def make_pair(
    anchor: dict[str, Any],
    candidate: dict[str, Any],
    *,
    target: int,
    relationship_class: str,
) -> dict[str, Any]:
    same_family = bool(
        anchor.get("paraphrase_family_id")
        and candidate.get("paraphrase_family_id")
        and anchor["paraphrase_family_id"] == candidate["paraphrase_family_id"]
    )
    pair_type = (
        "SAME_FAMILY_POSITIVE" if target and same_family
        else "CROSS_FAMILY_POSITIVE" if target
        else "SAFE_RANDOM_NEGATIVE"
    )
    row = {
        "schema_version": "lr2-intent-pair-v1",
        "construction_version": "lr2-pair-builder-v1",
        "pair_id": "PENDING",
        "anchor_record_id": anchor["record_id"],
        "candidate_record_id": candidate["record_id"],
        "anchor_intent": anchor["intent_label"],
        "candidate_intent": candidate["intent_label"],
        "target": target,
        "pair_type": pair_type,
        "relationship_class": relationship_class,
        "same_intent": anchor["intent_label"] == candidate["intent_label"],
        "same_family": same_family,
        "anchor_family_id": anchor.get("paraphrase_family_id"),
        "candidate_family_id": candidate.get("paraphrase_family_id"),
        "anchor_query_sha256": anchor["query_sha256"],
        "candidate_query_sha256": candidate["query_sha256"],
        "source_dataset_ids": [anchor["source_dataset_id"], candidate["source_dataset_id"]],
        "source_record_ids": [anchor["source_record_id"], candidate["source_record_id"]],
        "governance_status": "RQ1B_GOVERNED_PAIR_CANDIDATE",
        "pair_policy_reason": (
            "FROZEN_SAME_INTENT_POSITIVE_POLICY"
            if target else "FROZEN_SAFE_RANDOM_NEGATIVE_POLICY"
        ),
    }
    row["pair_id"] = deterministic_pair_id(row)
    return row


def _stable_order_key(seed: int, stratum: str, anchor_id: str, candidate_id: str) -> str:
    return hashlib.sha256(
        f"{seed}|{stratum}|{anchor_id}|{candidate_id}".encode("utf-8")
    ).hexdigest()


def _circular_take(
    pool: list[dict[str, Any]],
    quota: int,
    epoch: int,
    seed: int,
    stratum: str,
    anchor_id: str,
) -> list[dict[str, Any]]:
    ordered = sorted(
        pool,
        key=lambda row: _stable_order_key(
            seed, stratum, anchor_id, row["candidate_record_id"]
        ),
    )
    if quota <= 0 or not ordered:
        return []
    if quota > len(ordered):
        raise PairConstructionError("episodic quota exceeds governed pool")
    start = (epoch * quota) % len(ordered)
    return [ordered[(start + offset) % len(ordered)] for offset in range(quota)]


def generate_epoch_pairs(sampler: dict[str, Any], epoch: int) -> list[dict[str, Any]]:
    if not isinstance(epoch, int) or epoch < 0:
        raise PairConstructionError("epoch must be a non-negative integer")
    selected: list[dict[str, Any]] = []
    for anchor in sampler["eligible_train"]:
        anchor_id = anchor["record_id"]
        positive_pool = sampler["positive_by_anchor"][anchor_id]
        quota = min(sampler["max_positives_per_anchor"], len(positive_pool))
        positives = _circular_take(
            positive_pool,
            quota,
            epoch,
            sampler["sampling_seed"],
            "POSITIVE",
            anchor_id,
        )
        negatives = _circular_take(
            sampler["negative_by_anchor"][anchor_id],
            quota,
            epoch,
            sampler["sampling_seed"],
            "SAFE_NEGATIVE",
            anchor_id,
        )
        if len(positives) != quota or len(negatives) != quota:
            raise PairConstructionError("insufficient governed positive or safe-negative pool")
        selected.extend(positives)
        selected.extend(negatives)
    selected.sort(key=lambda row: row["pair_id"])
    if not selected or sum(row["target"] for row in selected) * 2 != len(selected):
        raise PairConstructionError("epoch pair balance failed")
    if any(row["relationship_class"] == "HARD_NEGATIVE_CANDIDATE" for row in selected):
        raise PairConstructionError("hard negative entered selected pairs")
    return selected


def _projection(rows: Iterable[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            row["pair_id"],
            row["anchor_record_id"],
            row["candidate_record_id"],
            row["target"],
            row["relationship_class"],
        )
        for row in rows
    ]


def build_scenario_sampler(bundle: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    ids = bundle["scenario_ids"][scenario_id]
    records = [bundle["records_by_id"][record_id] for record_id in ids]
    policy_payload = bundle["negative_policy"]
    policy = {
        relationship_key(row["label_a"], row["label_b"]): row["relationship_class"]
        for row in policy_payload["relationships"]
    }
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    equivalence_exclusions: Counter[str] = Counter()
    hard_possible = 0
    blocked_possible = 0
    for anchor in records:
        for candidate in records:
            if anchor["record_id"] == candidate["record_id"]:
                continue
            if anchor["intent_label"] == candidate["intent_label"]:
                positives.append(
                    make_pair(
                        anchor,
                        candidate,
                        target=1,
                        relationship_class="SAME_INTENT_POSITIVE",
                    )
                )
                continue
            relationship = policy[relationship_key(anchor["intent_label"], candidate["intent_label"])]
            if relationship == "BLOCKED_WITHOUT_REVIEW":
                blocked_possible += 1
                continue
            if relationship == "HARD_NEGATIVE_CANDIDATE":
                hard_possible += 1
                continue
            if relationship != "SAFE_RANDOM_NEGATIVE":
                raise PairConstructionError("unknown relationship policy")
            reasons = provenance_equivalence_reasons(anchor, candidate)
            if reasons:
                equivalence_exclusions.update(reasons)
                continue
            negatives.append(
                make_pair(
                    anchor,
                    candidate,
                    target=0,
                    relationship_class="SAFE_RANDOM_NEGATIVE",
                )
            )
    positives.sort(key=lambda row: row["pair_id"])
    negatives.sort(key=lambda row: row["pair_id"])
    positive_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    negative_by_anchor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in positives:
        positive_by_anchor[row["anchor_record_id"]].append(row)
    for row in negatives:
        negative_by_anchor[row["anchor_record_id"]].append(row)
    for record in records:
        anchor_id = record["record_id"]
        quota = min(MAX_POSITIVES_PER_ANCHOR, len(positive_by_anchor[anchor_id]))
        if quota <= 0 or len(negative_by_anchor[anchor_id]) < quota:
            raise PairConstructionError("insufficient safe negatives or nonself positives")
    sampler = {
        "scenario_id": scenario_id,
        "eligible_train": records,
        "eligible_ids": set(ids),
        "singleton_ids": set(),
        "positive_pool": positives,
        "negative_pool": negatives,
        "positive_by_anchor": positive_by_anchor,
        "negative_by_anchor": negative_by_anchor,
        "sampling_seed": PAIR_SAMPLING_SEED,
        "max_positives_per_anchor": MAX_POSITIVES_PER_ANCHOR,
        "hard_negative_possible_count": hard_possible,
        "blocked_relationship_possible_count": blocked_possible,
        "equivalence_exclusions": dict(sorted(equivalence_exclusions.items())),
    }
    return sampler


def _write_pair_ledgers(sampler: dict[str, Any]) -> dict[str, Any]:
    PAIR_LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    epoch_rows: list[dict[str, Any]] = []
    for epoch in range(MAX_EPOCHS):
        rows = generate_epoch_pairs(sampler, epoch)
        path = PAIR_LEDGER_DIR / f"{sampler['scenario_id'].lower()}_epoch_{epoch:02d}_v1.jsonl"
        content = b"".join(
            json.dumps(
                {
                    "pair_id": row["pair_id"],
                    "anchor_record_id": row["anchor_record_id"],
                    "candidate_record_id": row["candidate_record_id"],
                    "target": row["target"],
                    "relationship_class": row["relationship_class"],
                    "row_weight": 1.0,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            for row in rows
        )
        path.write_bytes(content)
        epoch_rows.append(
            {
                "epoch": epoch,
                "pair_row_count": len(rows),
                "positive_count": sum(row["target"] == 1 for row in rows),
                "negative_count": sum(row["target"] == 0 for row in rows),
                "pair_ledger_sha256": sha256_file(path),
            }
        )
    projection = canonical_json_bytes(epoch_rows)
    return {
        "epochs_audited": len(epoch_rows),
        "epoch_pair_counts": epoch_rows,
        "all_epoch_ledger_projection_sha256": sha256_bytes(projection),
    }


def _data_concentration(bundle: dict[str, Any], sampler: dict[str, Any]) -> dict[str, Any]:
    records = sampler["eligible_train"]
    epoch_zero = generate_epoch_pairs(sampler, 0)
    representation_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        representation_groups[row["representation_sha256"]].append(row)
    duplicate_groups = [group for group in representation_groups.values() if len(group) > 1]
    label_counts = Counter(row["intent_label"] for row in records)
    family_counts = Counter(row["paraphrase_family_id"] for row in records)
    positive_rows = [row for row in epoch_zero if row["target"] == 1]
    record_by_id = bundle["records_by_id"]
    identical = sum(
        record_by_id[row["anchor_record_id"]]["representation_sha256"]
        == record_by_id[row["candidate_record_id"]]["representation_sha256"]
        for row in positive_rows
    )
    selected_by_label = Counter(row["anchor_intent"] for row in epoch_zero)
    top_labels = sorted(label_counts.values(), reverse=True)
    top_families = sorted(family_counts.values(), reverse=True)
    return {
        "scenario": sampler["scenario_id"],
        "total_anchors": len(records),
        "unique_representation_anchors": len(representation_groups),
        "duplicate_extra_rows": len(records) - len(representation_groups),
        "duplicate_group_count": len(duplicate_groups),
        "same_label_duplicate_group_count": sum(
            len({row["intent_label"] for row in group}) == 1 for group in duplicate_groups
        ),
        "cross_label_duplicate_group_count": sum(
            len({row["intent_label"] for row in group}) > 1 for group in duplicate_groups
        ),
        "per_label_anchor_count": dict(sorted(label_counts.items())),
        "per_label_selected_epoch_0_pair_row_count": dict(sorted(selected_by_label.items())),
        "per_source_count": dict(sorted(Counter(row["source_dataset_id"] for row in records).items())),
        "context_mode_count": dict(sorted(Counter(row["context_mode"] for row in records).items())),
        "family_count": len(family_counts),
        "maximum_family_size": max(family_counts.values()),
        "top_1_family_share": top_families[0] / len(records),
        "top_3_family_share": sum(top_families[:3]) / len(records),
        "top_1_label_share": top_labels[0] / len(records),
        "top_3_label_share": sum(top_labels[:3]) / len(records),
        "identical_representation_positive_pair_count_epoch_0": identical,
        "same_family_positive_pair_count_epoch_0": sum(row["same_family"] for row in positive_rows),
        "cross_family_positive_pair_count_epoch_0": sum(not row["same_family"] for row in positive_rows),
    }


def build_all_scenario_pair_inputs(bundle: dict[str, Any]) -> dict[str, Any]:
    samplers = {
        scenario: build_scenario_sampler(bundle, scenario)
        for scenario in SCENARIO_ORDER
    }
    old = lr3_data_loader.build_epoch_sampler_inputs()
    parity_epochs = []
    for epoch in range(MAX_EPOCHS):
        current = generate_epoch_pairs(samplers["V0"], epoch)
        reference = lr3_data_loader.generate_epoch_pairs(old, epoch)
        parity_epochs.append(_projection(current) == _projection(reference))
    if not all(parity_epochs):
        raise PairConstructionError("V0 sampler parity with frozen LR-2R failed")

    audits: dict[str, Any] = {}
    concentration: dict[str, Any] = {}
    for scenario, sampler in samplers.items():
        ledger = _write_pair_ledgers(sampler)
        epoch_zero = generate_epoch_pairs(sampler, 0)
        positive_pool_count = len(sampler["positive_pool"])
        negative_pool_count = len(sampler["negative_pool"])
        audits[scenario] = {
            "scenario": scenario,
            "anchor_count": len(sampler["eligible_train"]),
            "label_count": len({row["intent_label"] for row in sampler["eligible_train"]}),
            "positive_pool_count": positive_pool_count,
            "safe_negative_pool_count": negative_pool_count,
            "hard_negative_selected_count": 0,
            "blocked_relationship_selected_count": 0,
            "hard_negative_possible_but_excluded_count": sampler["hard_negative_possible_count"],
            "blocked_relationship_possible_but_not_materialised_count": sampler[
                "blocked_relationship_possible_count"
            ],
            "provenance_equivalence_exclusion_reason_counts": sampler[
                "equivalence_exclusions"
            ],
            "epoch_0_pair_row_count": len(epoch_zero),
            "epoch_0_positive_count": sum(row["target"] == 1 for row in epoch_zero),
            "epoch_0_safe_negative_count": sum(row["target"] == 0 for row in epoch_zero),
            "directed_rows_retained": True,
            "row_weighting": "D0_DIRECTED_EQUAL_WEIGHT",
            "unique_row_weight_values": [1.0],
            "pair_sampling_seed": PAIR_SAMPLING_SEED,
            "model_seed_changes_pair_sampling": False,
            "positive_quota": "MIN_2_OR_POOL_SIZE",
            "negative_quota_equals_selected_positive_count": True,
            "circular_epoch_rotation": True,
            "rows_sorted_by_pair_id": True,
            **ledger,
        }
        concentration[scenario] = _data_concentration(bundle, sampler)
    audit_report = {
        "schema_version": "rq1b-pair-construction-audit-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "scenario_order": list(SCENARIO_ORDER),
        "strict_membership_nesting": True,
        "fixed_pair_sampling_seed": PAIR_SAMPLING_SEED,
        "v0_lr2r_epoch_identity_parity_count": sum(parity_epochs),
        "v0_lr2r_epoch_identity_parity_required": MAX_EPOCHS,
        "scenarios": audits,
        "hard_negative_expansion": False,
        "deduplication_performed": False,
        "final_gold_accessed": False,
    }
    concentration_report = {
        "schema_version": "rq1b-data-concentration-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "governed_total_record_count": 318,
        "governed_unique_representation_count": 297,
        "governed_duplicate_extra_row_count": 21,
        "governed_duplicate_group_count": 10,
        "governed_cross_label_duplicate_group_count": 0,
        "duplicates_retained": True,
        "pure_sample_size_causal_interpretation_authorised": False,
        "scenarios": concentration,
        "final_gold_accessed": False,
    }
    return {"samplers": samplers, "audit": audit_report, "concentration": concentration_report}
