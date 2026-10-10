"""Build deterministic source-separated human Gold and local full-text copies."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

from evaluation.capability_routing_v1_r1c.build_reviewer_packets_v1_3 import (
    _sanitised_history,
)
from evaluation.capability_routing_v1_r1c.human_review_schema_v1_3 import (
    validate_forbidden_capabilities,
)

from . import (
    AUTHENTIC_LABELS_RELATIVE,
    AUTHENTIC_REGISTRY_LABELS_RELATIVE,
    CANONICAL_A_RELATIVE,
    CANONICAL_A_SHA256,
    CANONICAL_ADJUDICATION_SHA256,
    CANONICAL_B_RELATIVE,
    CANONICAL_B_SHA256,
    CAPABILITIES,
    COMBINED_BANK_RELATIVE,
    COMBINED_BANK_SHA256,
    EXPECTED_AUTHENTIC_DISTRIBUTION,
    EXPECTED_SYNTHETIC_DISTRIBUTION,
    GOLD_RELEVANT_FIELDS,
    LABEL_ONLY_FIELDS,
    LOCAL_AUTHENTIC_GOLD_RELATIVE,
    LOCAL_AUTHENTIC_REGISTRY_RELATIVE,
    LOCAL_COMBINED_GOLD_RELATIVE,
    LOCAL_SYNTHETIC_GOLD_RELATIVE,
    ROOT,
    RQ2AR2BError,
    SOURCE_MAPPING_RELATIVE,
    SOURCE_MAPPING_SHA256,
    SYNTHETIC_LABELS_RELATIVE,
    canonical_jsonl_bytes,
    sha256_file,
)
from .eligibility_amendment import synthetic_clarification_exception_applies
from .gold_policy_v1_1 import (
    AUTHENTIC_GOLD,
    AUTHENTIC_REGISTRY,
    EXCLUDED,
    SYNTHETIC_GOLD,
    authentic_destination,
    synthetic_destination,
)


LOCAL_OUTPUTS = (
    LOCAL_AUTHENTIC_GOLD_RELATIVE,
    LOCAL_SYNTHETIC_GOLD_RELATIVE,
    LOCAL_AUTHENTIC_REGISTRY_RELATIVE,
    LOCAL_COMBINED_GOLD_RELATIVE,
)
TRACKED_LABEL_OUTPUTS = (
    AUTHENTIC_LABELS_RELATIVE,
    SYNTHETIC_LABELS_RELATIVE,
    AUTHENTIC_REGISTRY_LABELS_RELATIVE,
)


class GoldBuilderError(RQ2AR2BError):
    pass


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _verified_file(path: Path, expected_sha256: str, blocker: str) -> None:
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected_sha256:
        raise GoldBuilderError(blocker)


def load_gold_inputs(
    canonical_adjudication_path: Path, root: Path = ROOT
) -> dict[str, Any]:
    inputs = {
        "reviewer_a": root / CANONICAL_A_RELATIVE,
        "reviewer_b": root / CANONICAL_B_RELATIVE,
        "mapping": root / SOURCE_MAPPING_RELATIVE,
        "combined": root / COMBINED_BANK_RELATIVE,
        "adjudication": canonical_adjudication_path,
    }
    for key, expected in (
        ("reviewer_a", CANONICAL_A_SHA256),
        ("reviewer_b", CANONICAL_B_SHA256),
        ("mapping", SOURCE_MAPPING_SHA256),
        ("combined", COMBINED_BANK_SHA256),
        ("adjudication", CANONICAL_ADJUDICATION_SHA256),
    ):
        _verified_file(inputs[key], expected, "BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")

    rows_a = _csv_rows(inputs["reviewer_a"])
    rows_b = _csv_rows(inputs["reviewer_b"])
    mapping = _jsonl_rows(inputs["mapping"])
    combined = _jsonl_rows(inputs["combined"])
    adjudication = _csv_rows(inputs["adjudication"])
    by_a = {row["review_case_id"]: row for row in rows_a}
    by_b = {row["review_case_id"]: row for row in rows_b}
    mapping_by_review = {str(row["review_case_id"]): row for row in mapping}
    combined_by_canonical = {
        str(row["canonical_case_id"]): row for row in combined
    }
    if (
        len(rows_a) != 60
        or len(rows_b) != 60
        or len(by_a) != 60
        or len(by_b) != 60
        or set(by_a) != set(by_b)
        or len(mapping) != 60
        or len(mapping_by_review) != 60
        or set(mapping_by_review) != set(by_a)
        or len(combined) != 60
        or len(combined_by_canonical) != 60
        or len(adjudication) != 5
    ):
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    source_counts = Counter(str(row["source_bank"]) for row in mapping)
    if source_counts != {"authentic": 25, "synthetic": 35}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    for review_case_id, source in mapping_by_review.items():
        canonical_id = str(source["canonical_case_id"])
        case = combined_by_canonical.get(canonical_id)
        if case is None or case["source_bank"] != source["source_bank"]:
            raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
        for reviewer in (by_a[review_case_id], by_b[review_case_id]):
            if reviewer["current_query"] != case["current_query"] or reviewer[
                "current_page"
            ] != case["current_page"]:
                raise GoldBuilderError(
                    "BLOCKED_RQ2_A_R2B_UNRESOLVED_HUMAN_DISAGREEMENT"
                )
            if reviewer["necessary_conversation_history"] != _sanitised_history(
                case.get("necessary_conversation_history")
            ):
                raise GoldBuilderError(
                    "BLOCKED_RQ2_A_R2B_UNRESOLVED_HUMAN_DISAGREEMENT"
                )
    return {
        "rows_a": rows_a,
        "rows_b": rows_b,
        "mapping": mapping,
        "combined": combined,
        "adjudication": adjudication,
    }


def _normalised_forbidden(value: Any) -> list[str]:
    observed = set(validate_forbidden_capabilities(value))
    return [capability for capability in CAPABILITIES if capability in observed]


def _adjudicated_decision(row: Mapping[str, str]) -> dict[str, Any]:
    result = {
        field: row[f"adjudicated_{field}"]
        for field in GOLD_RELEVANT_FIELDS
        if field != "forbidden_capabilities"
    }
    result["forbidden_capabilities"] = _normalised_forbidden(
        row["adjudicated_forbidden_capabilities"]
    )
    result["missing_context_disposition"] = (
        row["missing_context_disposition"] or None
    )
    result["query_rewrite_performed"] = False
    result["assistant_context_attached"] = False
    result["gold_decision_source"] = "HUMAN_ADJUDICATION"
    return result


def _consensus_decision(
    reviewer_a: Mapping[str, str], reviewer_b: Mapping[str, str]
) -> dict[str, Any]:
    disagreements = [
        field
        for field in GOLD_RELEVANT_FIELDS
        if reviewer_a[field].strip() != reviewer_b[field].strip()
    ]
    if disagreements:
        raise GoldBuilderError(
            "BLOCKED_RQ2_A_R2B_UNRESOLVED_HUMAN_DISAGREEMENT"
        )
    result: dict[str, Any] = {
        field: reviewer_a[field].strip()
        for field in GOLD_RELEVANT_FIELDS
        if field != "forbidden_capabilities"
    }
    result["forbidden_capabilities"] = _normalised_forbidden(
        reviewer_a["forbidden_capabilities"]
    )
    result["missing_context_disposition"] = None
    result["query_rewrite_performed"] = False
    result["assistant_context_attached"] = False
    result["gold_decision_source"] = "HUMAN_CONSENSUS"
    return result


def _validate_final_decision(row: Mapping[str, Any]) -> None:
    if row["case_validity"] not in {"INCLUDE_VALID_CASE", "EXCLUDE_INVALID_CASE"}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if row["context_link_valid"] not in {"YES", "NO", "NOT_APPLICABLE"}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if row["context_sufficient"] not in {"YES", "NO", "NOT_APPLICABLE"}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if row["capability_unambiguous"] not in {"YES", "NO"}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if row["context_resolution_required"] not in {"YES", "NO"} or any(
        row[capability] not in {"YES", "NO"} for capability in CAPABILITIES
    ):
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    active = {capability for capability in CAPABILITIES if row[capability] == "YES"}
    forbidden = set(row["forbidden_capabilities"])
    if active & forbidden:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if "clarification" in active and active != {"clarification"}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if "safe_direct_response" in active and active != {"safe_direct_response"}:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if not active and row["case_validity"] == "INCLUDE_VALID_CASE":
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")
    if row["query_rewrite_performed"] or row["assistant_context_attached"]:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")


def _label_row(
    review_case_id: str,
    source_role: str,
    destination: str,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    value = {
        "review_case_id": review_case_id,
        "source_role": source_role,
        "gold_inclusion_status": destination,
        "gold_decision_source": decision["gold_decision_source"],
        "context_link_valid": decision["context_link_valid"],
        "context_sufficient": decision["context_sufficient"],
        "capability_unambiguous": decision["capability_unambiguous"],
        "context_resolution_required": decision["context_resolution_required"],
        **{capability: decision[capability] for capability in CAPABILITIES},
        "forbidden_capabilities": list(decision["forbidden_capabilities"]),
        "missing_context_disposition": decision["missing_context_disposition"],
    }
    if tuple(value) != LABEL_ONLY_FIELDS:
        raise GoldBuilderError("tracked label-only field order mismatch")
    return value


def _full_text_row(
    label: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        **dict(label),
        "canonical_case_id": str(case["canonical_case_id"]),
        "source_bank_alias": str(case["source_bank_alias"]),
        "current_query": str(case["current_query"]),
        "current_page": str(case["current_page"]),
        "necessary_conversation_history": case["necessary_conversation_history"],
        "turn_index": int(case["turn_index"]),
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
    }


def _distribution(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    materialised = list(rows)
    return {
        **{
            capability: sum(row[capability] == "YES" for row in materialised)
            for capability in CAPABILITIES
        },
        "context_resolution_required": sum(
            row["context_resolution_required"] == "YES" for row in materialised
        ),
        "multi_capability_cases": sum(
            sum(row[capability] == "YES" for capability in CAPABILITIES) > 1
            for row in materialised
        ),
    }


def build_source_separated_gold_bytes(
    canonical_adjudication_path: Path, root: Path = ROOT
) -> dict[str, Any]:
    inputs = load_gold_inputs(canonical_adjudication_path, root)
    by_a = {row["review_case_id"]: row for row in inputs["rows_a"]}
    by_b = {row["review_case_id"]: row for row in inputs["rows_b"]}
    mapping_by_review = {
        str(row["review_case_id"]): row for row in inputs["mapping"]
    }
    combined_by_canonical = {
        str(row["canonical_case_id"]): row for row in inputs["combined"]
    }
    adjudication_by_review = {
        row["review_case_id"]: row for row in inputs["adjudication"]
    }

    all_decisions: list[dict[str, Any]] = []
    authentic_labels: list[dict[str, Any]] = []
    synthetic_labels: list[dict[str, Any]] = []
    registry_labels: list[dict[str, Any]] = []
    authentic_full: list[dict[str, Any]] = []
    synthetic_full: list[dict[str, Any]] = []
    registry_full: list[dict[str, Any]] = []

    for review_case_id in sorted(by_a):
        source = mapping_by_review[review_case_id]
        source_role = str(source["source_bank"])
        case = combined_by_canonical[str(source["canonical_case_id"])]
        if review_case_id in adjudication_by_review:
            decision = _adjudicated_decision(adjudication_by_review[review_case_id])
        else:
            decision = _consensus_decision(by_a[review_case_id], by_b[review_case_id])
        decision = {
            "review_case_id": review_case_id,
            "source_role": source_role,
            **decision,
        }
        _validate_final_decision(decision)
        destination = (
            authentic_destination(decision)
            if source_role == "authentic"
            else synthetic_destination(decision)
        )
        label = _label_row(review_case_id, source_role, destination, decision)
        full = _full_text_row(label, case)
        all_decisions.append({**decision, "gold_inclusion_status": destination})
        if destination == AUTHENTIC_GOLD:
            authentic_labels.append(label)
            authentic_full.append(full)
        elif destination == AUTHENTIC_REGISTRY:
            registry_labels.append(label)
            registry_full.append(full)
        elif destination == SYNTHETIC_GOLD:
            synthetic_labels.append(label)
            synthetic_full.append(full)
        elif destination != EXCLUDED:
            raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")

    included_full = sorted(authentic_full + synthetic_full, key=lambda row: row["review_case_id"])
    authentic_labels.sort(key=lambda row: row["review_case_id"])
    synthetic_labels.sort(key=lambda row: row["review_case_id"])
    registry_labels.sort(key=lambda row: row["review_case_id"])
    authentic_full.sort(key=lambda row: row["review_case_id"])
    synthetic_full.sort(key=lambda row: row["review_case_id"])
    registry_full.sort(key=lambda row: row["review_case_id"])

    composition = {
        "total_reviewed_cases": len(all_decisions),
        "authentic_total": sum(row["source_role"] == "authentic" for row in all_decisions),
        "authentic_gold": len(authentic_labels),
        "authentic_context_missing_registry": len(registry_labels),
        "synthetic_total": sum(row["source_role"] == "synthetic" for row in all_decisions),
        "synthetic_gold": len(synthetic_labels),
        "synthetic_excluded": sum(
            row["source_role"] == "synthetic"
            and row["gold_inclusion_status"] == EXCLUDED
            for row in all_decisions
        ),
        "combined_gold": len(included_full),
        "consensus_cases": sum(
            row["gold_decision_source"] == "HUMAN_CONSENSUS"
            for row in all_decisions
        ),
        "adjudicated_cases": sum(
            row["gold_decision_source"] == "HUMAN_ADJUDICATION"
            for row in all_decisions
        ),
        "included_adjudicated_gold_cases": sum(
            row["gold_decision_source"] == "HUMAN_ADJUDICATION"
            and row["gold_inclusion_status"] in {AUTHENTIC_GOLD, SYNTHETIC_GOLD}
            for row in all_decisions
        ),
        "adjudicated_authentic_registry_cases": sum(
            row["gold_decision_source"] == "HUMAN_ADJUDICATION"
            and row["gold_inclusion_status"] == AUTHENTIC_REGISTRY
            for row in all_decisions
        ),
    }
    expected_composition = {
        "total_reviewed_cases": 60,
        "authentic_total": 25,
        "authentic_gold": 22,
        "authentic_context_missing_registry": 3,
        "synthetic_total": 35,
        "synthetic_gold": 35,
        "synthetic_excluded": 0,
        "combined_gold": 57,
        "consensus_cases": 55,
        "adjudicated_cases": 5,
        "included_adjudicated_gold_cases": 2,
        "adjudicated_authentic_registry_cases": 3,
    }
    if composition != expected_composition:
        raise GoldBuilderError("BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH")

    authentic_distribution = _distribution(authentic_labels)
    synthetic_distribution = _distribution(synthetic_labels)
    synthetic_exception_count = sum(
        synthetic_clarification_exception_applies(row)
        for row in all_decisions
        if row["gold_inclusion_status"] == SYNTHETIC_GOLD
    )
    synthetic_distribution["synthetic_clarification_exception_cases"] = (
        synthetic_exception_count
    )
    if any(
        authentic_distribution[key] != expected
        for key, expected in EXPECTED_AUTHENTIC_DISTRIBUTION.items()
    ) or synthetic_distribution != EXPECTED_SYNTHETIC_DISTRIBUTION:
        raise GoldBuilderError(
            "BLOCKED_RQ2_A_R2B_CAPABILITY_DISTRIBUTION_MISMATCH"
        )

    output_rows = {
        AUTHENTIC_LABELS_RELATIVE: authentic_labels,
        SYNTHETIC_LABELS_RELATIVE: synthetic_labels,
        AUTHENTIC_REGISTRY_LABELS_RELATIVE: registry_labels,
        LOCAL_AUTHENTIC_GOLD_RELATIVE: authentic_full,
        LOCAL_SYNTHETIC_GOLD_RELATIVE: synthetic_full,
        LOCAL_AUTHENTIC_REGISTRY_RELATIVE: registry_full,
        LOCAL_COMBINED_GOLD_RELATIVE: included_full,
    }
    output_bytes = {
        relative: canonical_jsonl_bytes(rows) for relative, rows in output_rows.items()
    }
    return {
        "output_rows": output_rows,
        "output_bytes": output_bytes,
        "composition": composition,
        "authentic_distribution": authentic_distribution,
        "synthetic_distribution": synthetic_distribution,
        "all_decisions": all_decisions,
    }


def _is_ignored(root: Path, relative: Path) -> bool:
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", "--", relative.as_posix()],
            cwd=root,
            check=False,
        ).returncode
        == 0
    )


def write_source_separated_gold(
    build: Mapping[str, Any], root: Path = ROOT
) -> None:
    for relative, value in build["output_bytes"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    for relative in LOCAL_OUTPUTS:
        if not _is_ignored(root, relative):
            raise GoldBuilderError("local full-text Gold is not ignored")
    for relative in TRACKED_LABEL_OUTPUTS:
        if _is_ignored(root, relative):
            raise GoldBuilderError("tracked label-only Gold is unexpectedly ignored")
        rows = build["output_rows"][relative]
        if any(tuple(row) != LABEL_ONLY_FIELDS for row in rows):
            raise GoldBuilderError("tracked Gold contains an unauthorised field")


def validate_persisted_gold(
    build: Mapping[str, Any], root: Path = ROOT
) -> dict[str, dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    for relative, expected in build["output_bytes"].items():
        path = root / relative
        if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
            raise GoldBuilderError("persisted Gold differs from deterministic build")
        members[relative.as_posix()] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "record_count": len(build["output_rows"][relative]),
            "local_only": relative in LOCAL_OUTPUTS,
        }
    return dict(sorted(members.items()))
