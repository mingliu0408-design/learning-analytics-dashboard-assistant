"""Audit the frozen unified gold-label overlay without relabelling it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.unified_evaluation_contract import (  # noqa: E402
    CAPABILITIES,
    EXPECTED_ROUTES,
    GOLD_LABELS_PATH,
    GOLD_LABEL_VERSION,
    MECHANISM_DIMENSIONS,
    QUALITY_DIMENSIONS,
    QUERY_TYPES,
    SCENARIO_GROUPS,
    SCENARIOS_PATH,
    REFERENCE_EVIDENCE_PATH,
    REFERENCE_EVIDENCE_VERSION,
    load_jsonl,
)


OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v2"
REQUIRED_FIELDS = {
    "scenario_id",
    "gold_query_type",
    "gold_scenario_group",
    "gold_expected_route",
    "gold_expected_memory",
    "gold_expected_retrieval",
    "gold_required_capabilities",
    "gold_applicable_quality_dimensions",
    "gold_applicable_mechanism_dimensions",
    "gold_notes",
    "gold_label_version",
    "gold_review_status",
    "gold_reviewed_by",
    "gold_reviewed_at",
    "gold_review_notes",
}
COMPLETED_REVIEW_STATUSES = {"approved", "revised"}


def review_is_complete(row: dict[str, Any], *, status_field: str, notes_field: str) -> bool:
    return row.get(status_field) in COMPLETED_REVIEW_STATUSES and bool(str(row.get(notes_field, "")).strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit frozen unified gold labels.")
    parser.add_argument("--scenarios", type=Path, default=SCENARIOS_PATH)
    parser.add_argument("--gold-labels", type=Path, default=GOLD_LABELS_PATH)
    parser.add_argument("--reference-evidence", type=Path, default=REFERENCE_EVIDENCE_PATH)
    parser.add_argument("--json-report", type=Path, default=OUTPUT_DIR / "gold_label_audit.json")
    parser.add_argument("--markdown-report", type=Path, default=OUTPUT_DIR / "gold_label_audit.md")
    return parser.parse_args()


def normalise_query(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def token_similarity(left: str, right: str) -> float:
    a, b = set(normalise_query(left).split()), set(normalise_query(right).split())
    return len(a & b) / len(a | b) if a or b else 1.0


def audit_gold_labels(
    scenarios: list[dict[str, Any]], labels: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocking: list[dict[str, str]] = []
    review: list[dict[str, str]] = []
    scenario_ids = [str(row.get("scenario_id", "")) for row in scenarios]
    label_ids = [str(row.get("scenario_id", "")) for row in labels]
    scenario_set, label_set = set(scenario_ids), set(label_ids)

    def block(code: str, message: str) -> None:
        blocking.append({"code": code, "message": message})

    def flag(code: str, message: str) -> None:
        review.append({"code": code, "message": message})

    for duplicate in sorted({value for value in label_ids if label_ids.count(value) > 1}):
        block("duplicate_scenario_id", duplicate)
    for scenario_id in sorted(scenario_set - label_set):
        block("missing_gold_label", scenario_id)
    for scenario_id in sorted(label_set - scenario_set):
        block("unknown_scenario_id", scenario_id)

    scenario_lookup = {str(row.get("scenario_id", "")): row for row in scenarios}
    label_lookup: dict[str, dict[str, Any]] = {}
    for row in labels:
        scenario_id = str(row.get("scenario_id", ""))
        if scenario_id in label_lookup:
            continue
        label_lookup[scenario_id] = row
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            block("missing_gold_fields", f"{scenario_id}: {sorted(missing)}")
            continue
        enum_checks = [
            ("gold_query_type", QUERY_TYPES),
            ("gold_scenario_group", SCENARIO_GROUPS),
            ("gold_expected_route", EXPECTED_ROUTES),
        ]
        for field, allowed in enum_checks:
            if row.get(field) not in allowed:
                block("invalid_enum", f"{scenario_id}: {field}={row.get(field)!r}")
        if row.get("gold_label_version") != GOLD_LABEL_VERSION:
            block("gold_version_mismatch", f"{scenario_id}: {row.get('gold_label_version')!r}")
        review_status = row.get("gold_review_status")
        if review_status not in {"pending", "approved", "revised"}:
            block("invalid_gold_review_status", f"{scenario_id}: {review_status!r}")
        if review_status not in COMPLETED_REVIEW_STATUSES:
            block("gold_review_not_approved", scenario_id)
        elif not all(str(row.get(field, "")).strip() for field in ("gold_reviewed_by", "gold_reviewed_at", "gold_review_notes")):
            block("incomplete_gold_review_provenance", scenario_id)
        for field in ("gold_expected_memory", "gold_expected_retrieval"):
            if type(row.get(field)) is not bool:
                block("invalid_boolean", f"{scenario_id}: {field}")
        capabilities = row.get("gold_required_capabilities")
        quality = row.get("gold_applicable_quality_dimensions")
        mechanism = row.get("gold_applicable_mechanism_dimensions")
        if not isinstance(capabilities, list) or not set(capabilities) <= CAPABILITIES:
            block("invalid_capabilities", f"{scenario_id}: {capabilities!r}")
            capabilities = []
        if not isinstance(quality, list) or not set(quality) <= set(QUALITY_DIMENSIONS):
            block("invalid_quality_dimensions", f"{scenario_id}: {quality!r}")
            quality = []
        if not isinstance(mechanism, list) or not set(mechanism) <= set(MECHANISM_DIMENSIONS):
            block("invalid_mechanism_dimensions", f"{scenario_id}: {mechanism!r}")
            mechanism = []
        group = row.get("gold_scenario_group")
        expected_route_by_group = {
            "dashboard_interpretation": "dashboard_interpretation",
            "metric_clarification": "metric_clarification",
            "technical_access_or_discrepancy": "direct_technical_access_or_discrepancy",
            "recommendation_planning": "recommendation_planning",
            "memory_follow_up": "memory_follow_up",
            "course_material_retrieval": "course_material_retrieval",
            "cross_page_evidence_synthesis": "cross_page_evidence_synthesis",
            "hybrid_memory_and_retrieval": "hybrid_memory_and_retrieval",
            "hybrid_evidence_and_retrieval": "hybrid_evidence_and_retrieval",
        }
        if expected_route_by_group.get(group) != row.get("gold_expected_route"):
            if group != "negative_control":
                block("scenario_group_route_inconsistency", scenario_id)
        required_capability_by_group = {
            "recommendation_planning": "recommendation_planning",
            "memory_follow_up": "short_term_memory",
            "course_material_retrieval": "course_material_retrieval",
            "technical_access_or_discrepancy": "technical_access_handling",
            "hybrid_memory_and_retrieval": "hybrid",
            "hybrid_evidence_and_retrieval": "hybrid",
        }
        required_capability = required_capability_by_group.get(group)
        if required_capability and required_capability not in capabilities:
            block("scenario_group_capability_inconsistency", f"{scenario_id}: missing {required_capability}")
        if group in {"course_material_retrieval", "hybrid_memory_and_retrieval", "hybrid_evidence_and_retrieval"} and not row.get("gold_expected_retrieval"):
            block("retrieval_group_without_retrieval", scenario_id)
        if group in {"memory_follow_up", "hybrid_memory_and_retrieval"} and not row.get("gold_expected_memory"):
            block("memory_group_without_memory", scenario_id)
        if row.get("gold_expected_retrieval") and "course_material_retrieval" not in capabilities:
            block("retrieval_capability_missing", scenario_id)
        if row.get("gold_expected_memory") and "short_term_memory" not in capabilities:
            block("memory_capability_missing", scenario_id)
        if group == "metric_clarification" and "personalisation" in quality:
            block("metric_definition_requires_personalisation", scenario_id)
        if group == "negative_control" and ({"short_term_memory", "course_material_retrieval"} & set(capabilities)):
            block("negative_control_has_forbidden_capability", scenario_id)
        query = str(scenario_lookup.get(scenario_id, {}).get("student_query", ""))
        explicit_meaning_query = bool(re.search(r"^\s*what does .+ mean\??\s*$", query, re.I))
        if explicit_meaning_query and row.get("gold_query_type") != "metric_clarification":
            if not review_is_complete(row, status_field="gold_review_status", notes_field="gold_review_notes"):
                flag("metric_meaning_query_not_metric_clarification", scenario_id)
        elif group == "metric_clarification" and row.get("gold_query_type") != "metric_clarification":
            if not review_is_complete(row, status_field="gold_review_status", notes_field="gold_review_notes"):
                flag("metric_group_query_type_requires_review", scenario_id)
        if group == "negative_control" and re.search(r"\b(?:improve|recommend|suggest|what should i do|how should i)\b", query, re.I):
            if not review_is_complete(row, status_field="gold_review_status", notes_field="gold_review_notes"):
                flag("negative_control_recommendation_route_requires_review", scenario_id)
        if (
            row.get("gold_query_type") == "improvement_recommendation"
            and "recommendation_planning" in capabilities
            and row.get("gold_expected_route") == "dashboard_interpretation"
            and not re.search(r"\b(?:alternate|alternative)[ -]route\b", str(row.get("gold_review_notes", "")), re.I)
        ):
            block("recommendation_planning_mislabelled_dashboard", scenario_id)
        if row.get("gold_query_type") == "metric_clarification" and row.get("gold_expected_route") == "dashboard_interpretation":
            block("metric_clarification_mislabelled_dashboard", scenario_id)
        if row.get("gold_expected_retrieval") and "retrieval_grounding" not in set(mechanism):
            block("retrieval_mechanisms_missing", scenario_id)
        if row.get("gold_expected_memory") and "memory_resolution_accuracy" not in mechanism:
            block("memory_mechanism_missing", scenario_id)

    comparable = sorted(scenario_set & label_set)
    for index, left_id in enumerate(comparable):
        for right_id in comparable[index + 1:]:
            left_s, right_s = scenario_lookup[left_id], scenario_lookup[right_id]
            similarity = token_similarity(str(left_s.get("student_query", "")), str(right_s.get("student_query", "")))
            if similarity < 0.8:
                continue
            left_l, right_l = label_lookup[left_id], label_lookup[right_id]
            signature_fields = ("gold_query_type", "gold_scenario_group", "gold_expected_memory", "gold_expected_retrieval")
            unresolved = any(
                not review_is_complete(row, status_field="gold_review_status", notes_field="gold_review_notes")
                for row in (left_l, right_l)
            )
            if any(left_l.get(field) != right_l.get(field) for field in signature_fields) and unresolved:
                flag("similar_query_conflicting_labels", f"{left_id} vs {right_id} (similarity={similarity:.2f})")
            if normalise_query(str(left_s.get("student_query", ""))) == normalise_query(str(right_s.get("student_query", ""))) and left_s.get("conversation_history") != right_s.get("conversation_history"):
                if unresolved:
                    flag("history_changes_interpretation", f"{left_id} vs {right_id}")

    # These two cases are semantic paraphrases, so contradictory retrieval gold is always blocking.
    for left_id, right_id in (("U024", "U040"),):
        if left_id in label_lookup and right_id in label_lookup:
            left, right = label_lookup[left_id], label_lookup[right_id]
            if left.get("gold_expected_retrieval") != right.get("gold_expected_retrieval"):
                block("equivalent_course_queries_conflicting_retrieval", f"{left_id} vs {right_id}")
                reviewed = all(
                    review_is_complete(row, status_field="gold_review_status", notes_field="gold_review_notes")
                    for row in (left, right)
                )
                if not reviewed:
                    flag("near_duplicate_course_content_conflicting_retrieval", f"{left_id} vs {right_id}")

    references = reference_rows or []
    reference_ids = [str(row.get("scenario_id", "")) for row in references]
    for duplicate in sorted({value for value in reference_ids if reference_ids.count(value) > 1}):
        block("duplicate_reference_evidence", duplicate)
    reference_lookup = {str(row.get("scenario_id", "")): row for row in references}
    for scenario_id in sorted(scenario_set - set(reference_ids)):
        block("missing_reference_evidence", scenario_id)
    for scenario_id in sorted(set(reference_ids) - scenario_set):
        block("unknown_reference_evidence", scenario_id)
    for scenario_id, row in reference_lookup.items():
        required_reference_fields = {
            "reference_student_query", "reference_conversation_history", "reference_page",
            "reference_dashboard_evidence", "reference_course_evidence",
            "reference_source_restrictions", "reference_evidence_notes",
            "reference_chunk_ids", "reference_evidence_version", "review_status",
        }
        if required_reference_fields - set(row):
            block("missing_reference_evidence_fields", f"{scenario_id}: {sorted(required_reference_fields - set(row))}")
        if row.get("reference_evidence_version") != REFERENCE_EVIDENCE_VERSION:
            block("reference_evidence_version_mismatch", scenario_id)
        scenario = scenario_lookup.get(scenario_id, {})
        if (
            row.get("reference_student_query") != scenario.get("student_query")
            or row.get("reference_conversation_history") != scenario.get("conversation_history", [])
            or row.get("reference_page") != scenario.get("page")
        ):
            block("reference_scenario_identity_mismatch", scenario_id)
        forbidden_reference_keys = {
            "mode", "route", "selected_route", "query_type", "memory_resolution",
            "retrieval_used", "recommendation_plan", "c_full_mode_c_route",
            "selected_sources", "selected_evidence_sources",
        }

        def nested_keys(value: Any) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(nested_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(nested_keys(item) for item in value)) if value else set()
            return set()

        leaked = nested_keys(row) & forbidden_reference_keys
        if leaked:
            block("forbidden_reference_metadata", f"{scenario_id}: {sorted(leaked)}")
        if row.get("review_status") not in COMPLETED_REVIEW_STATUSES:
            block("reference_evidence_not_approved", scenario_id)
        elif not all(str(row.get(field, "")).strip() for field in ("reviewed_by", "reviewed_at", "review_notes")):
            block("incomplete_reference_review_provenance", scenario_id)

        label = label_lookup.get(scenario_id, {})
        course_evidence = list(row.get("reference_course_evidence") or [])
        restrictions = row.get("reference_source_restrictions") or {}
        mechanism = set(label.get("gold_applicable_mechanism_dimensions") or [])
        if (
            label.get("gold_expected_retrieval")
            and not course_evidence
            and restrictions.get("course_evidence_available") is True
        ):
            block("empty_course_evidence_marked_available", scenario_id)
        if "course_context_use" in mechanism and not course_evidence:
            block("course_context_use_without_reference_evidence", scenario_id)
        if label.get("gold_expected_retrieval") and course_evidence and "course_context_use" not in mechanism:
            block("course_context_use_missing_with_reference_evidence", scenario_id)

    return {
        "gold_label_version": GOLD_LABEL_VERSION,
        "scenario_count": len(scenarios),
        "gold_label_count": len(labels),
        "blocking_issue_count": len(blocking),
        "manual_review_finding_count": len(review),
        "blocking_issues": blocking,
        "manual_review_findings": review,
        "status": "PASS" if not blocking else "FAIL",
        "labels_changed_by_audit": False,
    }


def write_reports(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Unified Gold-Label Audit",
        "",
        f"Status: **{report['status']}**",
        "",
        f"- Scenarios: {report['scenario_count']}",
        f"- Gold rows: {report['gold_label_count']}",
        f"- Blocking issues: {report['blocking_issue_count']}",
        f"- Manual-review findings: {report['manual_review_finding_count']}",
        "- The audit never changes labels.",
        "",
        "## Blocking issues",
        "",
    ]
    lines.extend(f"- `{item['code']}`: {item['message']}" for item in report["blocking_issues"])
    if not report["blocking_issues"]:
        lines.append("None.")
    lines.extend(["", "## Manual-review findings", ""])
    lines.extend(f"- `{item['code']}`: {item['message']}" for item in report["manual_review_findings"])
    if not report["manual_review_findings"]:
        lines.append("None.")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    report = audit_gold_labels(
        load_jsonl(args.scenarios), load_jsonl(args.gold_labels), load_jsonl(args.reference_evidence)
    )
    write_reports(report, args.json_report, args.markdown_report)
    print(f"Gold-label audit: {report['status']}; blocking={report['blocking_issue_count']}; review={report['manual_review_finding_count']}")
    if report["blocking_issue_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
