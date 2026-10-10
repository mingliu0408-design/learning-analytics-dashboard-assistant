"""Build two blank source-blinded v1.2 reviewer packets."""

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
from .combined_bank_builder import build_combined_bank
from .human_review_schema_v1_2 import (
    DEFINITION_REFERENCE,
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    validate_blank_packet,
)
from .source_blinded_review_ids import build_review_id_mapping


REVIEWER_A_SEED = 20260825
REVIEWER_B_SEED = 20260826


class ReviewerPacketV12Error(RuntimeError):
    pass


def _sanitised_history(value: Any) -> str:
    if not value:
        return ""
    if not isinstance(value, list):
        raise ReviewerPacketV12Error("candidate history must be a list")
    visible: list[dict[str, Any]] = []
    for position, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ReviewerPacketV12Error("candidate history item must be an object")
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


def _packet_row(
    case: Mapping[str, Any], review_case_id: str
) -> dict[str, Any]:
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


def _shuffled(rows: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    result = list(rows)
    random.Random(seed).shuffle(result)
    return result


def _ordered_id_sha(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _assert_ignored(root: Path, relative: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        raise ReviewerPacketV12Error("review packet path is not ignored")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_reviewer_packets_v1_2(root: Path = ROOT) -> dict[str, Any]:
    combined, combined_manifest = build_combined_bank(root)
    mapping, mapping_summary = build_review_id_mapping(combined, root)
    review_id_by_canonical = {
        row["canonical_case_id"]: row["review_case_id"] for row in mapping
    }
    packet_source_rows = [
        _packet_row(case, review_id_by_canonical[str(case["canonical_case_id"])])
        for case in combined
    ]
    rows_a = _shuffled(packet_source_rows, REVIEWER_A_SEED)
    rows_b = _shuffled(packet_source_rows, REVIEWER_B_SEED)
    ids_a = [str(row["review_case_id"]) for row in rows_a]
    ids_b = [str(row["review_case_id"]) for row in rows_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise ReviewerPacketV12Error("A/B case-set or order contract failed")
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    packet_a = root / LOCAL_REVIEW_A_RELATIVE
    packet_b = root / LOCAL_REVIEW_B_RELATIVE
    packet_a.parent.mkdir(parents=True, exist_ok=True)
    packet_a.write_bytes(_csv_bytes(rows_a))
    packet_b.write_bytes(_csv_bytes(rows_b))
    _assert_ignored(root, LOCAL_REVIEW_A_RELATIVE)
    _assert_ignored(root, LOCAL_REVIEW_B_RELATIVE)
    observed_a = _read_rows(packet_a)
    observed_b = _read_rows(packet_b)
    validate_blank_packet(observed_a)
    validate_blank_packet(observed_b)
    manifest = {
        "schema_version": "reviewer-packet-manifest-v1.2",
        "stage": "RQ2-A-R1B",
        "status": "READY_FOR_TWO_INDEPENDENT_HUMAN_REVIEWERS",
        "combined_case_count": 60,
        "authentic_case_count": 25,
        "synthetic_case_count": 35,
        "packet_count": 2,
        "reviewer_a_seed": REVIEWER_A_SEED,
        "reviewer_b_seed": REVIEWER_B_SEED,
        "reviewer_a_record_count": len(rows_a),
        "reviewer_b_record_count": len(rows_b),
        "review_case_id_set_sha256": id_set_sha256(ids_a),
        "reviewer_a_order_sha256": _ordered_id_sha(ids_a),
        "reviewer_b_order_sha256": _ordered_id_sha(ids_b),
        "reviewer_a_packet_sha256": sha256_file(packet_a),
        "reviewer_b_packet_sha256": sha256_file(packet_b),
        "reviewer_a_packet_size_bytes": packet_a.stat().st_size,
        "reviewer_b_packet_size_bytes": packet_b.stat().st_size,
        "same_case_set": True,
        "different_row_order": True,
        "visible_fields": list(VISIBLE_FIELDS),
        "blank_human_fields": list(HUMAN_FIELDS),
        "all_human_fields_blank": True,
        "source_identity_hidden": True,
        "authentic_synthetic_label_hidden": True,
        "canonical_case_id_hidden": True,
        "source_dataset_hidden": True,
        "overlap_status_hidden": True,
        "legacy_output_hidden": True,
        "c0_scores_hidden": True,
        "intent_proposal_hidden": True,
        "capability_proposal_hidden": True,
        "other_reviewer_result_hidden": True,
        "source_blinded_review_ids": True,
        "source_blinded_mapping_sha256": mapping_summary["mapping_sha256"],
        "source_blinded_mapping_local_only": True,
        "same_source_blinded_id_in_both_packets": True,
        "packets_local_only": True,
        "packets_ignored": True,
        "packets_tracked": False,
        "old_packets_modified": False,
        "human_review_completed": False,
        "combined_bank_manifest_sha256": sha256_file(
            HERE / "combined_calibration_bank_manifest_v1_2.json"
        ),
        "combined_bank_case_count": combined_manifest["total_case_count"],
    }
    (HERE / "reviewer_packet_manifest_v1_2.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


if __name__ == "__main__":
    value = build_reviewer_packets_v1_2()
    print(
        json.dumps(
            {
                "status": value["status"],
                "combined_case_count": value["combined_case_count"],
                "all_human_fields_blank": value["all_human_fields_blank"],
            },
            sort_keys=True,
        )
    )
