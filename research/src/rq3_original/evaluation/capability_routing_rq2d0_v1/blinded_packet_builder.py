"""Deterministic source-blinded A/B packet construction in memory."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import random
from typing import Any, Iterable, Mapping

from .capability_review_schema import (
    DEFINITION_REFERENCE,
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    validate_blank_packet,
)


REVIEWER_A_ORDER_SEED = 20260830
REVIEWER_B_ORDER_SEED = 20260831


class BlindedPacketError(RuntimeError):
    pass


def _opaque_id(raw_case_id: str, blind_key: bytes) -> str:
    if len(blind_key) < 16:
        raise BlindedPacketError("blinding key must be local and at least 16 bytes")
    digest = hmac.new(blind_key, raw_case_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return "TBV1-" + digest[:16].upper()


def _canonical_history(value: Any) -> str:
    if not isinstance(value, list) or len(value) != 2:
        raise BlindedPacketError("effective history must have two turns")
    visible: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"content", "role"}:
            raise BlindedPacketError("effective history item shape mismatch")
        visible.append({"content": str(item["content"]), "role": str(item["role"])})
    return json.dumps(visible, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _csv_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[*VISIBLE_FIELDS, *HUMAN_FIELDS],
        extrasaction="raise",
        lineterminator="\r\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def parse_packet_bytes(raw: bytes) -> list[dict[str, str]]:
    if not raw.startswith(b"\xef\xbb\xbf"):
        raise BlindedPacketError("packet BOM mismatch")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    validate_blank_packet(rows)
    return rows


def _ordered_id_hash(rows: list[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        ("\n".join(str(row["review_case_id"]) for row in rows) + "\n").encode("utf-8")
    ).hexdigest()


def _case_set_hash(rows: list[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        ("\n".join(sorted(str(row["review_case_id"]) for row in rows)) + "\n").encode(
            "utf-8"
        )
    ).hexdigest()


def build_blinded_packets(
    records: list[Mapping[str, Any]], *, blind_key: bytes
) -> tuple[bytes, bytes, dict[str, Any], dict[str, str]]:
    source_rows: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for record in records:
        raw_id = str(record["raw_case_id"])
        review_id = _opaque_id(raw_id, blind_key)
        if review_id in mapping:
            raise BlindedPacketError("opaque review ID collision")
        mapping[review_id] = raw_id
        source_rows.append(
            {
                "review_case_id": review_id,
                "current_query": str(record["effective_current_query"]),
                "current_page": str(record["current_page"]),
                "necessary_conversation_history": _canonical_history(
                    record["effective_conversation_history"]
                ),
                "capability_definition_reference": DEFINITION_REFERENCE,
                **{field: "" for field in HUMAN_FIELDS},
            }
        )
    if len(source_rows) != 48 or len(mapping) != 48:
        raise BlindedPacketError("packet case count mismatch")
    rows_a = [dict(row) for row in source_rows]
    rows_b = [dict(row) for row in source_rows]
    random.Random(REVIEWER_A_ORDER_SEED).shuffle(rows_a)
    random.Random(REVIEWER_B_ORDER_SEED).shuffle(rows_b)
    if [row["review_case_id"] for row in rows_a] == [
        row["review_case_id"] for row in rows_b
    ]:
        raise BlindedPacketError("A/B order must differ")
    if {row["review_case_id"] for row in rows_a} != {
        row["review_case_id"] for row in rows_b
    }:
        raise BlindedPacketError("A/B case set mismatch")
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    packet_a = _csv_bytes(rows_a)
    packet_b = _csv_bytes(rows_b)
    parse_packet_bytes(packet_a)
    parse_packet_bytes(packet_b)
    manifest = {
        "schema_version": "track-b-blinded-packet-manifest-v1",
        "status": "PASS",
        "record_count": 48,
        "reviewer_a_seed": REVIEWER_A_ORDER_SEED,
        "reviewer_b_seed": REVIEWER_B_ORDER_SEED,
        "case_set_sha256": _case_set_hash(rows_a),
        "reviewer_a_order_sha256": _ordered_id_hash(rows_a),
        "reviewer_b_order_sha256": _ordered_id_hash(rows_b),
        "reviewer_a_packet_sha256": hashlib.sha256(packet_a).hexdigest(),
        "reviewer_b_packet_sha256": hashlib.sha256(packet_b).hexdigest(),
        "same_case_set": True,
        "different_order": True,
        "human_field_blank_count_per_packet": 48 * len(HUMAN_FIELDS),
        "raw_scenario_id_visible": False,
        "existing_intent_visible": False,
        "model_output_visible": False,
        "automatic_proposal_visible": False,
        "labels_formed": False,
    }
    return packet_a, packet_b, manifest, mapping


def blinding_contract_document() -> dict[str, Any]:
    return {
        "schema_version": "track-b-blinding-contract-v1",
        "status": "FROZEN_BEFORE_D1_RAW_ACCESS",
        "visible_source_fields": [
            "opaque review_case_id",
            "effective current query",
            "current page",
            "effective conversation history",
            "Capability definitions",
            "blank human fields",
        ],
        "hidden_source_fields": [
            "raw scenario_id",
            "normalised query",
            "all existing Intent labels",
            "source scope",
            "authority flags",
            "hard guards",
            "hybrid policy",
            "scenario category",
            "family",
            "contrast group",
            "difficulty",
            "eligibility flags",
            "all prior review fields and rationales",
            "all model outputs and automatic proposals",
        ],
        "opaque_id_algorithm": "HMAC_SHA256_LOCAL_D1_BLIND_KEY_TRUNCATED_16_HEX",
        "blind_key_storage": "LOCAL_ONLY_NOT_TRACKED_NOT_IN_REVIEW_ZIP",
        "reviewer_a_order_seed": REVIEWER_A_ORDER_SEED,
        "reviewer_b_order_seed": REVIEWER_B_ORDER_SEED,
        "same_case_set_required": True,
        "different_order_required": True,
        "all_human_fields_blank_at_generation": True,
        "real_packets_generated_in_d0": False,
    }
