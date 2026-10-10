"""Versioned, research-only schema for LR-2 intent-example pairs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA_VERSION = "lr2-intent-pair-v1"
CONSTRUCTION_VERSION = "lr2-pair-builder-v1"
PAIR_TYPES = {
    "CROSS_FAMILY_POSITIVE",
    "SAME_FAMILY_POSITIVE",
    "SAFE_RANDOM_NEGATIVE",
    "HARD_NEGATIVE_CANDIDATE",
}
REQUIRED_FIELDS = {
    "schema_version",
    "pair_id",
    "anchor_record_id",
    "candidate_record_id",
    "anchor_intent",
    "candidate_intent",
    "target",
    "pair_type",
    "anchor_family_id",
    "candidate_family_id",
    "relationship_class",
    "same_intent",
    "same_family",
    "anchor_query_sha256",
    "candidate_query_sha256",
    "source_dataset_ids",
    "source_record_ids",
    "governance_status",
    "construction_version",
    "pair_policy_reason",
}


class PairValidationError(ValueError):
    """Raised when a pair violates the frozen LR-2 schema or policy."""


def canonical_pair_payload(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stable fields that define pair identity."""
    return {
        "schema_version": pair["schema_version"],
        "construction_version": pair["construction_version"],
        "anchor_record_id": pair["anchor_record_id"],
        "candidate_record_id": pair["candidate_record_id"],
        "target": pair["target"],
        "pair_type": pair["pair_type"],
        "relationship_class": pair["relationship_class"],
    }


def deterministic_pair_id(pair: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        canonical_pair_payload(pair), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "LR2P-" + hashlib.sha256(encoded).hexdigest()[:24].upper()


def validate_pair(pair: Mapping[str, Any], *, baseline: bool = False) -> None:
    missing = REQUIRED_FIELDS - set(pair)
    if missing:
        raise PairValidationError(f"missing required pair fields: {sorted(missing)}")
    if pair["schema_version"] != SCHEMA_VERSION:
        raise PairValidationError("unexpected schema_version")
    if pair["construction_version"] != CONSTRUCTION_VERSION:
        raise PairValidationError("unexpected construction_version")
    if pair["target"] not in {0, 1}:
        raise PairValidationError("target must be 0 or 1")
    if pair["anchor_record_id"] == pair["candidate_record_id"]:
        raise PairValidationError("self-pairs are prohibited")
    if pair["pair_type"] not in PAIR_TYPES:
        raise PairValidationError("unknown pair_type")
    if pair["same_intent"] != (pair["anchor_intent"] == pair["candidate_intent"]):
        raise PairValidationError("same_intent is inconsistent")
    explicit_same_family = bool(
        pair["anchor_family_id"]
        and pair["candidate_family_id"]
        and pair["anchor_family_id"] == pair["candidate_family_id"]
    )
    if pair["same_family"] != explicit_same_family:
        raise PairValidationError("same_family is inconsistent")
    if pair["target"] == 1:
        if not pair["same_intent"]:
            raise PairValidationError("positive target requires same intent")
        if pair["relationship_class"] != "SAME_INTENT_POSITIVE":
            raise PairValidationError("positive relationship class is invalid")
        expected_type = (
            "SAME_FAMILY_POSITIVE" if pair["same_family"] else "CROSS_FAMILY_POSITIVE"
        )
        if pair["pair_type"] != expected_type:
            raise PairValidationError("positive family stratum is inconsistent")
    else:
        if pair["same_intent"]:
            raise PairValidationError("negative target requires different intents")
        if pair["relationship_class"] not in {
            "SAFE_RANDOM_NEGATIVE",
            "HARD_NEGATIVE_CANDIDATE",
        }:
            raise PairValidationError("negative relationship class is invalid")
        if pair["pair_type"] != pair["relationship_class"]:
            raise PairValidationError("negative pair type is inconsistent")
        if pair["same_family"]:
            raise PairValidationError("different-label explicit same-family pair requires review")
    expected_id = deterministic_pair_id(pair)
    if pair["pair_id"] != expected_id:
        raise PairValidationError("pair_id is not deterministic")
    if baseline and pair["target"] == 0:
        if pair["relationship_class"] != "SAFE_RANDOM_NEGATIVE":
            raise PairValidationError("baseline negatives must be SAFE_RANDOM_NEGATIVE")
        if pair["governance_status"] != "CANDIDATE_FOR_LR3_TRAINING":
            raise PairValidationError("baseline governance status is invalid")

