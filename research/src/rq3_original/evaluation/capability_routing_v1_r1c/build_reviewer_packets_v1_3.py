"""Build two blank source-blinded v1.3 reviewer packets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import random
import subprocess
from typing import Any, Iterable, Mapping

from . import (
    HERE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    ROOT,
    canonical_json_bytes,
    id_set_sha256,
    sha256_file,
)
from .combined_bank_v1_3 import build_combined_bank_v1_3
from .human_review_schema_v1_3 import (
    DEFINITION_REFERENCE,
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    validate_blank_packet,
)


REVIEWER_A_SEED = 20260825
REVIEWER_B_SEED = 20260826


class ReviewerPacketV13Error(RuntimeError):
    pass


def _sanitised_history(value: Any) -> str:
    if not value:
        return ""
    if not isinstance(value, list):
        raise ReviewerPacketV13Error("conversation history must be a list")
    visible: list[dict[str, Any]] = []
    for position, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ReviewerPacketV13Error("conversation history item must be an object")
        visible.append(
            {
                "role": str(item.get("role") or "unknown"),
                "turn_order": int(item.get("turn_order", position)),
                "content": str(item.get("content") or ""),
            }
        )
    return json.dumps(
        visible, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _packet_row(case: Mapping[str, Any], review_case_id: str) -> dict[str, Any]:
    return {
        "review_case_id": review_case_id,
        "current_query": str(case["current_query"]),
        "current_page": str(case["current_page"]),
        "necessary_conversation_history": _sanitised_history(
            case.get("necessary_conversation_history")
        ),
        "turn_index": int(case.get("turn_index", 0)),
        "capability_definition_reference": DEFINITION_REFERENCE,
        **{field: "" for field in HUMAN_FIELDS},
    }


def _csv_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[*VISIBLE_FIELDS, *HUMAN_FIELDS],
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _ordered_id_sha(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _assert_ignored(root: Path, relative: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        raise ReviewerPacketV13Error("review packet path is not ignored")


def _read_packet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_reviewer_packets_v1_3(root: Path = ROOT) -> dict[str, Any]:
    combined, mapping, _ = build_combined_bank_v1_3(root)
    review_by_canonical = {
        str(row["canonical_case_id"]): str(row["review_case_id"])
        for row in mapping
    }
    source_rows = [
        _packet_row(case, review_by_canonical[str(case["canonical_case_id"])])
        for case in combined
    ]
    rows_a = list(source_rows)
    rows_b = list(source_rows)
    random.Random(REVIEWER_A_SEED).shuffle(rows_a)
    random.Random(REVIEWER_B_SEED).shuffle(rows_b)
    ids_a = [str(row["review_case_id"]) for row in rows_a]
    ids_b = [str(row["review_case_id"]) for row in rows_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b or len(ids_a) != 60:
        raise ReviewerPacketV13Error("A/B case-set or order contract failed")
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    packet_a = root / LOCAL_REVIEW_A_RELATIVE
    packet_b = root / LOCAL_REVIEW_B_RELATIVE
    packet_a.parent.mkdir(parents=True, exist_ok=True)
    packet_a.write_bytes(_csv_bytes(rows_a))
    packet_b.write_bytes(_csv_bytes(rows_b))
    _assert_ignored(root, LOCAL_REVIEW_A_RELATIVE)
    _assert_ignored(root, LOCAL_REVIEW_B_RELATIVE)
    observed_a = _read_packet(packet_a)
    observed_b = _read_packet(packet_b)
    validate_blank_packet(observed_a)
    validate_blank_packet(observed_b)
    source_by_review = {
        str(row["review_case_id"]): str(row["source_bank"]) for row in mapping
    }
    authentic_history_count = sum(
        bool(row["necessary_conversation_history"])
        for row in observed_a
        if source_by_review[row["review_case_id"]] == "authentic"
    )
    if authentic_history_count:
        raise ReviewerPacketV13Error("authentic assistant context entered packet")
    blank_per_packet = len(observed_a) * len(HUMAN_FIELDS)
    manifest = {
        "row_count": 60,
        "case_set_sha256": id_set_sha256(ids_a),
        "reviewer_a_packet_sha256": sha256_file(packet_a),
        "reviewer_b_packet_sha256": sha256_file(packet_b),
        "reviewer_a_order_sha256": _ordered_id_sha(ids_a),
        "reviewer_b_order_sha256": _ordered_id_sha(ids_b),
        "human_field_blank_count": {
            "reviewer_a": blank_per_packet,
            "reviewer_b": blank_per_packet,
            "total": blank_per_packet * 2,
        },
        "authentic_history_count": 0,
        "source_blinding_status": "PASS",
    }
    (HERE / "reviewer_packet_manifest_v1_3.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


if __name__ == "__main__":
    result = build_reviewer_packets_v1_3()
    print(json.dumps({"status": "PASS", "row_count": result["row_count"]}))
