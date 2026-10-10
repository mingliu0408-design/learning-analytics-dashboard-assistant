"""Fail-closed validation for RQ2-V2 Stage 1 Track A scenario packets."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping

from build_writer_packets import (
    MASTER_PATH,
    PACKET_PATHS,
    SHUFFLE_SEEDS,
    WRITER_FIELDS,
    expected_packet_rows,
    load_master,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]
STAGE0_ROOT = PROJECT_ROOT / "evaluation" / "capability_routing_rq2_v2_stage0"
CONTENT_AUDIT_PATH = PACKAGE_ROOT / "SCENARIO_CONTENT_AUDIT.md"
EXPECTED_COMBINATIONS = {f"{value:03b}" for value in range(8)}
EXPECTED_PAGES = {"Overview", "Resources", "Lecture", "Debate", "Reflection"}
CAPABILITY_FIELDS = (
    "proposed_rag_required",
    "proposed_memory_required",
    "proposed_planning_required",
)
REQUIRED_MASTER_FIELDS = {
    "schema_version",
    "scenario_family_id",
    "review_case_id",
    "scenario_blueprint_provenance",
    "label_status",
    "scenario_type",
    "current_page",
    "controlled_dashboard_context",
    "visible_conversation_history",
    "writer_facing_student_background",
    "writer_facing_request_goal",
    "course_knowledge_state",
    "long_term_memory_state",
    "proposed_dialogue_action",
    "proposed_rag_required",
    "proposed_memory_required",
    "proposed_planning_required",
    "core_capability_route_execution",
    "design_rationale",
    "contrast_group_id",
    "contrast_axis",
    "contrast_variant",
    "source_or_design_notes",
}
FORBIDDEN_SPLIT_FIELDS = {
    "partition",
    "split",
    "dataset_split",
    "final_partition",
    "development_partition",
    "test_partition",
}
FORBIDDEN_PACKET_TERMS = re.compile(
    r"\b(?:RAG|Memory|Planning|router|capability labels?|APIs?)\b", re.IGNORECASE
)
BANNED_RAG_META_CUES = (
    "not shown",
    "not supplied",
    "not provided",
    "no definition",
    "retrieval is available",
    "framework is absent",
    "does not explain",
    "does not supply",
    "is unavailable",
    "are unavailable",
)
FORBIDDEN_PACKET_FIELDS = {
    "proposed_dialogue_action",
    "proposed_rag_required",
    "proposed_memory_required",
    "proposed_planning_required",
    "design_rationale",
    "hidden_memory_payload",
    "hidden_course_evidence_text",
    "controlled_course_evidence_id",
    "verified_course_evidence_id",
}
UTTERANCE_ID_PATTERN = re.compile(r"^R2V2-U-[0-9]{3}-[AB]$")
BLINDED_FAMILY_ID_PATTERN = re.compile(r"^R2V2-SF-[0-9]{3}$")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")


class TrackAValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TrackAValidationError(message)


def _signature(row: Mapping[str, Any]) -> str:
    return "".join("1" if bool(row[field]) else "0" for field in CAPABILITY_FIELDS)


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _read_packet(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        return fields, list(reader)


def validate_required_fields(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows, 1):
        missing = REQUIRED_MASTER_FIELDS - set(row)
        _require(not missing, f"master row {index} missing fields: {sorted(missing)}")
        _require(
            row["schema_version"] == "rq2-v2-stage1-track-a-blueprint-v1",
            f"master row {index} schema version drift",
        )
        _require(
            row["scenario_blueprint_provenance"]
            == "CODEX_ASSISTED_RESEARCHER_SCENARIO_DESIGN",
            f"master row {index} provenance drift",
        )
        _require(
            row["label_status"] == "DESIGN_TARGET_NOT_FINAL_HUMAN_GOLD",
            f"master row {index} labels are not explicitly provisional",
        )
        _require(
            isinstance(row["visible_conversation_history"], list),
            f"master row {index} visible history must be a list",
        )
        for turn in row["visible_conversation_history"]:
            _require(
                isinstance(turn, dict)
                and set(turn) == {"role", "content"}
                and turn["role"] in {"user", "assistant"}
                and isinstance(turn["content"], str)
                and bool(turn["content"].strip()),
                f"master row {index} has invalid visible-history turn",
            )
        _require(
            all(isinstance(row[field], bool) for field in CAPABILITY_FIELDS),
            f"master row {index} proposed labels must be booleans",
        )


def validate_counts_and_combinations(rows: list[dict[str, Any]]) -> None:
    _require(len(rows) == 54, f"expected 54 scenario families, observed {len(rows)}")
    family_ids = [str(row["scenario_family_id"]) for row in rows]
    review_ids = [str(row["review_case_id"]) for row in rows]
    _require(len(set(family_ids)) == 54, "scenario_family_id values must be unique")
    _require(len(set(review_ids)) == 54, "review_case_id values must be unique")
    answerable = [row for row in rows if row["scenario_type"] == "ANSWERABLE"]
    clarifications = [
        row for row in rows if row["scenario_type"] == "CLARIFICATION_CONTEXT_INSUFFICIENT"
    ]
    _require(len(answerable) == 48, f"expected 48 answerable families, observed {len(answerable)}")
    _require(len(clarifications) == 6, f"expected 6 clarification families, observed {len(clarifications)}")
    counts = Counter(_signature(row) for row in answerable)
    _require(set(counts) == EXPECTED_COMBINATIONS, f"combination membership drift: {sorted(counts)}")
    _require(all(counts[key] == 6 for key in EXPECTED_COMBINATIONS), f"combination counts drift: {dict(sorted(counts.items()))}")
    for row in answerable:
        _require(row["proposed_dialogue_action"] == "ANSWER", f"{row['scenario_family_id']} must be ANSWER")
        _require(row["core_capability_route_execution"] is True, f"{row['scenario_family_id']} must execute its proposed route")


def validate_stage0_clarification_contract(rows: list[dict[str, Any]]) -> None:
    contract_path = STAGE0_ROOT / "data" / "clarification_scenario_contract_v1.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    _require(contract["dialogue_action"] == "CLARIFY", "Stage 0 clarification action drift")
    _require(contract["core_capability_route_execution"] is False, "Stage 0 clarification route drift")
    clarifications = [
        row for row in rows if row["scenario_type"] == "CLARIFICATION_CONTEXT_INSUFFICIENT"
    ]
    _require(len(clarifications) == contract["target_scenario_family_count"], "clarification count differs from Stage 0")
    for row in clarifications:
        _require(row["proposed_dialogue_action"] == contract["dialogue_action"], f"{row['scenario_family_id']} clarification action drift")
        _require(row["core_capability_route_execution"] is contract["core_capability_route_execution"], f"{row['scenario_family_id']} clarification route must be disabled")
        _require(not any(row[field] for field in CAPABILITY_FIELDS), f"{row['scenario_family_id']} CLARIFY cannot carry capability targets")


def validate_pages_and_distinctness(rows: list[dict[str, Any]]) -> None:
    pages = Counter(str(row["current_page"]) for row in rows)
    _require(set(pages) == EXPECTED_PAGES, f"LAD page membership drift: {dict(pages)}")
    _require(max(pages.values()) - min(pages.values()) <= 2, f"LAD pages are imbalanced: {dict(pages)}")
    answerable = [row for row in rows if row["scenario_type"] == "ANSWERABLE"]
    by_combination: dict[str, set[str]] = defaultdict(set)
    fingerprints: set[str] = set()
    for row in answerable:
        by_combination[_signature(row)].add(str(row["current_page"]))
        visible = {
            "page": row["current_page"],
            "dashboard": row["controlled_dashboard_context"],
            "history": row["visible_conversation_history"],
            "background": row["writer_facing_student_background"],
            "goal": row["writer_facing_request_goal"],
        }
        fingerprint = hashlib.sha256(
            json.dumps(visible, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        _require(fingerprint not in fingerprints, f"duplicate answerable blueprint: {row['scenario_family_id']}")
        fingerprints.add(fingerprint)
    _require(all(len(pages_seen) >= 5 for pages_seen in by_combination.values()), "each capability combination must span all five LAD pages")


def validate_contrasts(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group_id = row["contrast_group_id"]
        if group_id is None:
            _require(row["contrast_axis"] is None and row["contrast_variant"] is None, f"{row['scenario_family_id']} has partial contrast metadata")
            continue
        _require(isinstance(group_id, str) and bool(group_id), f"{row['scenario_family_id']} has invalid contrast_group_id")
        groups[group_id].append(row)
    counts = Counter(str(members[0]["contrast_axis"]) for members in groups.values())
    for axis in ("RAG", "MEMORY", "PLANNING", "CLARIFICATION"):
        _require(counts[axis] >= 3, f"insufficient {axis} contrast groups: {counts[axis]}")
    field_for_axis = {
        "RAG": "proposed_rag_required",
        "MEMORY": "proposed_memory_required",
        "PLANNING": "proposed_planning_required",
    }
    for group_id, members in groups.items():
        _require(len(members) == 2, f"contrast group {group_id} must contain exactly two families")
        axes = {member["contrast_axis"] for member in members}
        variants = {member["contrast_variant"] for member in members}
        _require(len(axes) == 1 and len(variants) == 2, f"contrast group {group_id} metadata drift")
        _require(len({member["current_page"] for member in members}) == 1, f"contrast group {group_id} must hold page constant")
        axis = str(members[0]["contrast_axis"])
        if axis in field_for_axis:
            _require(all(member["scenario_type"] == "ANSWERABLE" for member in members), f"{group_id} capability contrast must be answerable")
            changed = {
                field
                for field in CAPABILITY_FIELDS
                if bool(members[0][field]) != bool(members[1][field])
            }
            _require(changed == {field_for_axis[axis]}, f"contrast group {group_id} changes {sorted(changed)}")
        else:
            _require({member["proposed_dialogue_action"] for member in members} == {"ANSWER", "CLARIFY"}, f"{group_id} must contrast ANSWER and CLARIFY")


def validate_no_split_or_final_utterances(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        present = FORBIDDEN_SPLIT_FIELDS & {str(key).casefold() for key in row}
        _require(not present, f"{row['scenario_family_id']} assigns a forbidden split field: {sorted(present)}")
        _require("natural_student_query" not in row, f"{row['scenario_family_id']} embeds a final utterance")


def validate_memory_payload_separation(rows: list[dict[str, Any]]) -> None:
    memory_positive = [row for row in rows if row["proposed_memory_required"]]
    _require(len(memory_positive) == 24, f"expected 24 Memory-positive families, observed {len(memory_positive)}")
    for row in rows:
        payload = row.get("hidden_memory_payload")
        if row["proposed_memory_required"]:
            _require(isinstance(payload, str) and bool(payload.strip()), f"{row['scenario_family_id']} lacks hidden_memory_payload")
            visible = json.dumps(
                {
                    "dashboard": row["controlled_dashboard_context"],
                    "history": row["visible_conversation_history"],
                    "background": row["writer_facing_student_background"],
                    "goal": row["writer_facing_request_goal"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            _require(payload not in visible, f"{row['scenario_family_id']} exposes its hidden Memory payload")
            background = str(row["writer_facing_student_background"]).casefold()
            _require("earlier-session" in background, f"{row['scenario_family_id']} lacks an indirect earlier-session instruction")
            _require("do not state" in background and "invent" in background, f"{row['scenario_family_id']} lacks a do-not-restate instruction")
        else:
            _require(payload is None, f"{row['scenario_family_id']} must not carry hidden long-term Memory data")

    packet_text_parts: list[str] = []
    for path in PACKET_PATHS.values():
        if path.is_file():
            _, packet_rows = _read_packet(path)
            packet_text_parts.extend(value for packet_row in packet_rows for value in packet_row.values())
    packet_text = "\n".join(packet_text_parts)
    for row in memory_positive:
        _require(str(row["hidden_memory_payload"]) not in packet_text, f"{row['scenario_family_id']} hidden Memory payload occurs in a writer packet")


def validate_course_evidence_and_rag_cues(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        context = str(row["controlled_dashboard_context"]).casefold()
        hits = [cue for cue in BANNED_RAG_META_CUES if cue in context]
        _require(not hits, f"{row['scenario_family_id']} visible dashboard context contains RAG meta cues: {hits}")

    course_rows = [row for row in rows if row.get("course_evidence_provenance")]
    _require(len(course_rows) == 28, f"expected 28 course-evidence scenarios, observed {len(course_rows)}")
    provenance_counts = Counter(str(row["course_evidence_provenance"]) for row in course_rows)
    _require(
        provenance_counts == Counter({"VERIFIED_COURSE_METADATA": 12, "CONTROLLED_HYPOTHETICAL": 16}),
        f"course-evidence provenance counts drift: {dict(provenance_counts)}",
    )
    _require(sum(bool(row["proposed_rag_required"]) for row in course_rows) == 24, "course-evidence rows must include exactly 24 RAG-positive families")

    for row in course_rows:
        sid = str(row["scenario_family_id"])
        text = row.get("hidden_course_evidence_text")
        _require(isinstance(text, str) and bool(text.strip()), f"{sid} lacks hidden course evidence text")
        provenance = row["course_evidence_provenance"]
        if provenance == "VERIFIED_COURSE_METADATA":
            _require(isinstance(row.get("verified_course_evidence_id"), str), f"{sid} lacks verified evidence ID")
            _require(row.get("controlled_course_evidence_id") is None, f"{sid} mixes verified and controlled evidence IDs")
            _require(str(row.get("course_evidence_source", "")).startswith("utils/course_metadata.py:W"), f"{sid} verified evidence source drift")
        elif provenance == "CONTROLLED_HYPOTHETICAL":
            _require(isinstance(row.get("controlled_course_evidence_id"), str), f"{sid} lacks controlled_course_evidence_id")
            _require(row.get("verified_course_evidence_id") is None, f"{sid} mixes controlled and verified evidence IDs")
            _require(row.get("course_evidence_source") == "RESEARCHER_CONTROLLED_HYPOTHETICAL_NOT_AUTHENTIC_CORPUS", f"{sid} controlled evidence source drift")
        else:
            raise TrackAValidationError(f"{sid} has unknown course-evidence provenance: {provenance}")

        context = str(row["controlled_dashboard_context"])
        if row["proposed_rag_required"]:
            _require(text not in context, f"{sid} RAG-positive context exposes the hidden evidence statement")
        else:
            _require(text in context, f"{sid} RAG-negative supplied-context case lacks its visible evidence statement")

    _require(CONTENT_AUDIT_PATH.is_file(), "SCENARIO_CONTENT_AUDIT.md is missing")
    audit_text = CONTENT_AUDIT_PATH.read_text(encoding="utf-8")
    for row in course_rows:
        sid = str(row["scenario_family_id"])
        evidence_id = row.get("verified_course_evidence_id") or row.get(
            "controlled_course_evidence_id"
        )
        _require(sid in audit_text, f"content audit omits scenario {sid}")
        _require(str(evidence_id) in audit_text, f"content audit omits evidence ID {evidence_id}")


def validate_privacy_and_shortcuts(rows: list[dict[str, Any]]) -> None:
    all_text = "\n".join(text for row in rows for text in _walk_strings(row))
    _require(not EMAIL_PATTERN.search(all_text), "possible email address found in master")
    _require(not SECRET_PATTERN.search(all_text), "possible API secret found in master")
    answerable = [row for row in rows if row["scenario_type"] == "ANSWERABLE"]
    planning_goals = [str(row["writer_facing_request_goal"]) for row in answerable if row["proposed_planning_required"]]
    explicit_plan_count = sum(bool(re.search(r"\bplan\b", goal, re.IGNORECASE)) for goal in planning_goals)
    _require(explicit_plan_count < len(planning_goals) / 2, "too many Planning targets use the explicit word plan")
    memory_text = " ".join(str(row["writer_facing_request_goal"]) for row in answerable if row["proposed_memory_required"])
    _require("you remember" not in memory_text.casefold(), "Memory targets use a trivial 'you remember' shortcut")
    rag_text = " ".join(str(row["writer_facing_request_goal"]) for row in answerable if row["proposed_rag_required"])
    _require("course material" not in rag_text.casefold(), "RAG targets use a trivial 'course material' shortcut")


def validate_writer_packets(rows: list[dict[str, Any]]) -> None:
    observed: dict[str, list[dict[str, str]]] = {}
    for writer, path in PACKET_PATHS.items():
        _require(path.is_file(), f"missing writer packet {writer}: {path}")
        fields, packet_rows = _read_packet(path)
        _require(fields == WRITER_FIELDS, f"writer packet {writer} header drift: {fields}")
        _require(not (FORBIDDEN_PACKET_FIELDS & set(fields)), f"writer packet {writer} exposes hidden fields")
        _require(len(packet_rows) == 54, f"writer packet {writer} must contain 54 rows")
        _require(all(row["natural_student_query"] == "" for row in packet_rows), f"writer packet {writer} contains a student utterance")
        expected = expected_packet_rows(writer, rows)
        _require(packet_rows == expected, f"writer packet {writer} differs from deterministic blinded export seed {SHUFFLE_SEEDS[writer]}")
        packet_text = "\n".join(value for row in packet_rows for value in row.values())
        _require(not FORBIDDEN_PACKET_TERMS.search(packet_text), f"writer packet {writer} exposes system terminology")
        _require(not re.search(r"R2V2-C[01]{3}-F[0-9]{2}", packet_text), f"writer packet {writer} exposes internal capability-coded family IDs")

        utterance_ids = [row["utterance_id"] for row in packet_rows]
        family_ids = [row["scenario_family_id"] for row in packet_rows]
        _require(len(set(utterance_ids)) == 54, f"writer packet {writer} utterance IDs must be unique")
        _require(len(set(family_ids)) == 54, f"writer packet {writer} family aliases must be unique")
        _require(all(UTTERANCE_ID_PATTERN.fullmatch(value) and value.endswith(f"-{writer}") for value in utterance_ids), f"writer packet {writer} utterance ID format drift")
        _require(all(BLINDED_FAMILY_ID_PATTERN.fullmatch(value) for value in family_ids), f"writer packet {writer} family alias format drift")
        observed[writer] = packet_rows

    ids_a = [row["review_case_id"] for row in observed["A"]]
    ids_b = [row["review_case_id"] for row in observed["B"]]
    _require(set(ids_a) == set(ids_b) and len(set(ids_a)) == 54, "writer packets do not contain the same 54 blinded family IDs")
    _require(ids_a != ids_b, "writer packet orders must differ")
    by_review = {
        writer: {row["review_case_id"]: row for row in packet_rows}
        for writer, packet_rows in observed.items()
    }
    for review_case_id in set(ids_a):
        row_a = by_review["A"][review_case_id]
        row_b = by_review["B"][review_case_id]
        _require(row_a["scenario_family_id"] == row_b["scenario_family_id"], f"{review_case_id} A/B family aliases differ")
        _require(row_a["utterance_id"] != row_b["utterance_id"], f"{review_case_id} A/B utterance IDs must differ")


def run_validation(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    materialised = rows if rows is not None else load_master(MASTER_PATH)
    checks: dict[str, str] = {}
    failures: list[dict[str, str]] = []

    def check(name: str, function: Callable[[], None]) -> None:
        try:
            function()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = "FAIL"
            failures.append({"check": name, "error": f"{type(exc).__name__}: {exc}"})

    check("required_master_fields", lambda: validate_required_fields(materialised))
    check("family_and_combination_counts", lambda: validate_counts_and_combinations(materialised))
    check("stage0_clarification_contract", lambda: validate_stage0_clarification_contract(materialised))
    check("lad_pages_and_distinctness", lambda: validate_pages_and_distinctness(materialised))
    check("controlled_contrast_groups", lambda: validate_contrasts(materialised))
    check("no_dev_test_split_or_final_utterances", lambda: validate_no_split_or_final_utterances(materialised))
    check("hidden_memory_payload_separation", lambda: validate_memory_payload_separation(materialised))
    check("course_evidence_and_rag_meta_cues", lambda: validate_course_evidence_and_rag_cues(materialised))
    check("privacy_and_shortcut_guards", lambda: validate_privacy_and_shortcuts(materialised))
    check("blinded_writer_packets", lambda: validate_writer_packets(materialised))

    answerable = [row for row in materialised if row.get("scenario_type") == "ANSWERABLE"]
    clarifications = [row for row in materialised if row.get("scenario_type") == "CLARIFICATION_CONTEXT_INSUFFICIENT"]
    page_distribution = dict(sorted(Counter(str(row["current_page"]) for row in materialised).items()))
    combination_counts = dict(sorted(Counter(_signature(row) for row in answerable).items()))
    contrast_groups: dict[str, str] = {}
    for row in materialised:
        if row.get("contrast_group_id"):
            contrast_groups[str(row["contrast_group_id"])] = str(row["contrast_axis"])
    contrast_group_counts = dict(sorted(Counter(contrast_groups.values()).items()))
    course_evidence_counts = dict(
        sorted(
            Counter(
                str(row["course_evidence_provenance"])
                for row in materialised
                if row.get("course_evidence_provenance")
            ).items()
        )
    )
    return {
        "schema_version": "rq2-v2-stage1-track-a-r1-validation-report-v1",
        "status": "PASS" if not failures else "FAIL",
        "check_count": len(checks),
        "pass_count": sum(value == "PASS" for value in checks.values()),
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "scenario_family_count": len(materialised),
        "answerable_family_count": len(answerable),
        "clarification_family_count": len(clarifications),
        "combination_counts": combination_counts,
        "page_distribution": page_distribution,
        "contrast_group_counts": contrast_group_counts,
        "hidden_memory_payload_count": sum(
            bool(row.get("hidden_memory_payload")) for row in materialised
        ),
        "course_evidence_counts": course_evidence_counts,
        "writer_packet_unique_utterance_ids": {"A": 54, "B": 54},
        "final_dev_test_split_assigned": False,
        "natural_student_utterance_count": 0,
        "provider_call_count": 0,
        "model_training_performed": False,
    }


def main() -> int:
    report = run_validation()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
