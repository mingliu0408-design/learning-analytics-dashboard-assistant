"""Build two complete, differently ordered, blank human-review packets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import random
import subprocess
from typing import Any, Iterable

from . import (
    LOCAL_BANK_RELATIVE,
    LOCAL_REVIEW_A_RELATIVE,
    LOCAL_REVIEW_B_RELATIVE,
    ROOT,
    canonical_json_bytes,
    sha256_file,
)
from .capability_case_schema import CapabilityCaseV1
from .context_envelope import build_context_envelope


REVIEWER_A_SEED = 20260825
REVIEWER_B_SEED = 20260826
DEFINITION_REFERENCE = (
    "docs/thesis_mainline/rq2/RQ2A_CAPABILITY_SCHEMA_AND_ANNOTATION_GUIDE.md"
)
VISIBLE_FIELDS = (
    "case_id",
    "current_query",
    "current_page",
    "necessary_conversation_history",
    "turn_index",
    "source_dataset",
    "capability_definition_reference",
)
HUMAN_FIELDS = (
    "review_decision",
    "context_resolution_required",
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
    "forbidden_capabilities",
    "reviewer_rationale",
    "reviewer_id",
    "review_date",
)
REVIEW_DECISIONS = (
    "ACCEPT_AS_PRESENTED",
    "REVISE_CAPABILITIES",
    "UNCERTAIN",
    "EXCLUDE_CASE",
)


def _load_bank(root: Path) -> list[CapabilityCaseV1]:
    path = root / LOCAL_BANK_RELATIVE
    rows = [
        CapabilityCaseV1.from_mapping(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) < 20:
        raise RuntimeError("BLOCKED_RQ2_A_INSUFFICIENT_DEVELOPMENT_CASES")
    return rows


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


def _row(case: CapabilityCaseV1) -> dict[str, str | int]:
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


def _csv_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
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


def _shuffled(cases: list[CapabilityCaseV1], seed: int) -> list[CapabilityCaseV1]:
    result = list(cases)
    random.Random(seed).shuffle(result)
    return result


def _id_hash(values: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _assert_ignored(root: Path, relative: Path) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative.as_posix()], cwd=root
    )
    if result.returncode != 0:
        raise RuntimeError(f"review packet is not ignored: {relative.as_posix()}")


def build_review_packets(root: Path = ROOT) -> dict[str, Any]:
    cases = _load_bank(root)
    a_cases = _shuffled(cases, REVIEWER_A_SEED)
    b_cases = _shuffled(cases, REVIEWER_B_SEED)
    a_ids = [case.case_id for case in a_cases]
    b_ids = [case.case_id for case in b_cases]
    if set(a_ids) != set(b_ids) or len(a_ids) != len(b_ids):
        raise RuntimeError("reviewer packet case sets differ")
    if a_ids == b_ids:
        raise RuntimeError("reviewer packet row orders unexpectedly match")

    a_path = root / LOCAL_REVIEW_A_RELATIVE
    b_path = root / LOCAL_REVIEW_B_RELATIVE
    a_path.parent.mkdir(parents=True, exist_ok=True)
    a_path.write_bytes(_csv_bytes(_row(case) for case in a_cases))
    b_path.write_bytes(_csv_bytes(_row(case) for case in b_cases))
    _assert_ignored(root, LOCAL_REVIEW_A_RELATIVE)
    _assert_ignored(root, LOCAL_REVIEW_B_RELATIVE)

    manifest = {
        "schema_version": "capability-review-packet-manifest-v1",
        "stage": "RQ2-A",
        "status": "READY_FOR_BLINDED_HUMAN_REVIEW",
        "packet_count": 2,
        "canonical_case_count": len(cases),
        "reviewer_a_seed": REVIEWER_A_SEED,
        "reviewer_b_seed": REVIEWER_B_SEED,
        "reviewer_a_record_count": len(a_cases),
        "reviewer_b_record_count": len(b_cases),
        "case_set_sha256": _id_hash(sorted(a_ids)),
        "reviewer_a_order_sha256": _id_hash(a_ids),
        "reviewer_b_order_sha256": _id_hash(b_ids),
        "reviewer_a_packet_sha256": sha256_file(a_path),
        "reviewer_b_packet_sha256": sha256_file(b_path),
        "same_case_set": True,
        "different_row_order": True,
        "all_canonical_cases_included": True,
        "sampling_performed": False,
        "visible_fields": list(VISIBLE_FIELDS),
        "blank_human_fields": list(HUMAN_FIELDS),
        "allowed_review_decisions": list(REVIEW_DECISIONS),
        "all_human_fields_blank": True,
        "legacy_baseline_visible": False,
        "c0_scores_visible": False,
        "intent_proposal_visible": False,
        "capability_proposal_visible": False,
        "other_reviewer_visible": False,
        "maximum_history_turns_visible": 4,
        "packets_local_only": True,
        "packets_ignored": True,
        "tracked_packet_rows": False,
    }
    target = root / "evaluation/capability_routing_v1/capability_review_packet_manifest_v1.json"
    target.write_bytes(canonical_json_bytes(manifest))
    return manifest


if __name__ == "__main__":
    value = build_review_packets()
    print(
        json.dumps(
            {
                "status": value["status"],
                "canonical_case_count": value["canonical_case_count"],
                "human_fields_blank": value["all_human_fields_blank"],
            },
            sort_keys=True,
        )
    )
