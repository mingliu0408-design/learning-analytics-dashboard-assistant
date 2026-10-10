"""Build blank v1.1 packets for two independent human reviewers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import random
import subprocess
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_v1.capability_case_schema import CapabilityCaseV1
from evaluation.capability_routing_v1.context_envelope import build_context_envelope

from . import (
    HERE,
    LOCAL_CANONICAL_BANK_RELATIVE,
    NEW_REVIEW_A_RELATIVE,
    NEW_REVIEW_B_RELATIVE,
    OLD_REVIEW_A_RELATIVE,
    OLD_REVIEW_B_RELATIVE,
    OLD_REVIEW_PACKET_IDENTITIES,
    ROOT,
    canonical_json_bytes,
    sha256_file,
)
from .human_review_schema import (
    DEFINITION_REFERENCE,
    HUMAN_FIELDS,
    VISIBLE_FIELDS,
    validate_blank_packet,
)


REVIEWER_A_SEED = 20260825
REVIEWER_B_SEED = 20260826


class PacketBuildError(RuntimeError):
    pass


def _load_canonical_cases(root: Path) -> list[CapabilityCaseV1]:
    bank = root / LOCAL_CANONICAL_BANK_RELATIVE
    cases = [
        CapabilityCaseV1.from_mapping(json.loads(line))
        for line in bank.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(cases) != 35 or len({case.case_id for case in cases}) != 35:
        raise PacketBuildError("canonical synthetic calibration bank identity mismatch")
    return cases


def _necessary_history(case: CapabilityCaseV1) -> str:
    envelope = build_context_envelope(
        case_id=case.case_id,
        original_query=case.current_query,
        current_page=case.current_page,
        conversation_history=case.conversation_history,
        context_resolution_required=bool(case.conversation_history),
    )
    return json.dumps(
        list(envelope.recent_relevant_turns),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _packet_row(case: CapabilityCaseV1) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "current_query": case.current_query,
        "current_page": case.current_page,
        "necessary_conversation_history": _necessary_history(case),
        "turn_index": case.turn_index,
        "source_dataset": case.source_dataset,
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


def _shuffle(cases: list[CapabilityCaseV1], seed: int) -> list[CapabilityCaseV1]:
    ordered = list(cases)
    random.Random(seed).shuffle(ordered)
    return ordered


def _read_rows(file_path: Path) -> list[dict[str, str]]:
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _id_hash(values: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _assert_old_packets_unchanged(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for relative, expected in OLD_REVIEW_PACKET_IDENTITIES.items():
        packet = root / relative
        rows = _read_rows(packet)
        observed = {
            "sha256": sha256_file(packet),
            "size_bytes": packet.stat().st_size,
            "record_count": len(rows),
        }
        if observed != expected:
            raise PacketBuildError(f"old reviewer packet changed: {relative}")
        result[relative] = observed
    return result


def _assert_ignored(root: Path, relative: Path) -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=root
    )
    if ignored.returncode != 0:
        raise PacketBuildError(f"new reviewer packet is not ignored: {relative}")


def build_reviewer_packets_v1_1(root: Path = ROOT) -> dict[str, Any]:
    old_identities = _assert_old_packets_unchanged(root)
    cases = _load_canonical_cases(root)
    cases_a = _shuffle(cases, REVIEWER_A_SEED)
    cases_b = _shuffle(cases, REVIEWER_B_SEED)
    ids_a = [case.case_id for case in cases_a]
    ids_b = [case.case_id for case in cases_b]
    if set(ids_a) != set(ids_b) or ids_a == ids_b:
        raise PacketBuildError("new reviewer packet set/order contract failed")

    old_a_ids = [row["case_id"] for row in _read_rows(root / OLD_REVIEW_A_RELATIVE)]
    old_b_ids = [row["case_id"] for row in _read_rows(root / OLD_REVIEW_B_RELATIVE)]
    if ids_a != old_a_ids or ids_b != old_b_ids:
        raise PacketBuildError("v1.1 seed order diverged from frozen v1 order")

    rows_a = [_packet_row(case) for case in cases_a]
    rows_b = [_packet_row(case) for case in cases_b]
    validate_blank_packet(rows_a)
    validate_blank_packet(rows_b)
    packet_a = root / NEW_REVIEW_A_RELATIVE
    packet_b = root / NEW_REVIEW_B_RELATIVE
    packet_a.parent.mkdir(parents=True, exist_ok=True)
    packet_a.write_bytes(_csv_bytes(rows_a))
    packet_b.write_bytes(_csv_bytes(rows_b))
    _assert_ignored(root, NEW_REVIEW_A_RELATIVE)
    _assert_ignored(root, NEW_REVIEW_B_RELATIVE)

    manifest = {
        "schema_version": "reviewer-packet-manifest-v1.1",
        "stage": "RQ2-A-R1",
        "status": "READY_FOR_TWO_INDEPENDENT_HUMAN_REVIEWERS",
        "calibration_bank_role": "SYNTHETIC_CAPABILITY_CALIBRATION_ONLY",
        "canonical_case_count": len(cases),
        "packet_count": 2,
        "reviewer_a_seed": REVIEWER_A_SEED,
        "reviewer_b_seed": REVIEWER_B_SEED,
        "reviewer_a_record_count": len(rows_a),
        "reviewer_b_record_count": len(rows_b),
        "case_set_sha256": _id_hash(sorted(ids_a)),
        "reviewer_a_order_sha256": _id_hash(ids_a),
        "reviewer_b_order_sha256": _id_hash(ids_b),
        "reviewer_a_packet_sha256": sha256_file(packet_a),
        "reviewer_b_packet_sha256": sha256_file(packet_b),
        "reviewer_a_packet_size_bytes": packet_a.stat().st_size,
        "reviewer_b_packet_size_bytes": packet_b.stat().st_size,
        "same_case_set": True,
        "different_row_order": True,
        "same_seed_order_as_corresponding_v1_packet": True,
        "old_packets_unchanged": True,
        "old_packet_identities": old_identities,
        "visible_fields": list(VISIBLE_FIELDS),
        "blank_human_fields": list(HUMAN_FIELDS),
        "all_human_fields_blank": True,
        "accept_as_presented_present": False,
        "hidden_proposal_visible": False,
        "legacy_output_visible": False,
        "c0_scores_visible": False,
        "old_packet_answers_visible": False,
        "other_reviewer_visible": False,
        "required_human_reviewer_count": 2,
        "reviewer_ids_must_differ_at_closure": True,
        "llm_reviewer_substitution_allowed": False,
        "packets_local_only": True,
        "packets_ignored": True,
        "packets_tracked": False,
        "sampling_performed": False,
    }
    (HERE / "reviewer_packet_manifest_v1_1.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


if __name__ == "__main__":
    value = build_reviewer_packets_v1_1()
    print(
        json.dumps(
            {
                "status": value["status"],
                "canonical_case_count": value["canonical_case_count"],
                "all_human_fields_blank": value["all_human_fields_blank"],
            },
            sort_keys=True,
        )
    )
