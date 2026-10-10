"""Fail-closed leakage guards for future RQ2-V2 dataset construction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class LeakageIssue:
    code: str
    case_ids: tuple[str, ...]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "case_ids": list(self.case_ids),
            "message": self.message,
        }


class LeakageViolation(ValueError):
    def __init__(self, issues: Iterable[LeakageIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.code for issue in self.issues))


def _normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _input_fingerprint(case: Mapping[str, Any]) -> str:
    model_input = case.get("model_input") or {}
    visible = {
        "current_query": _normalise_text(model_input.get("current_query")),
        "current_page": _normalise_text(model_input.get("current_page")),
        "dashboard_context": _normalise_text(model_input.get("dashboard_context")),
        "visible_conversation_history": [
            {
                "role": _normalise_text(turn.get("role")),
                "content": _normalise_text(turn.get("content")),
            }
            for turn in model_input.get("visible_conversation_history") or []
        ],
        "rag_context_state": model_input.get("rag_context_state"),
        "memory_context_state": model_input.get("memory_context_state"),
    }
    payload = json.dumps(visible, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detect_case_leakage(cases: Iterable[Mapping[str, Any]]) -> list[LeakageIssue]:
    rows = [dict(case) for case in cases]
    issues: list[LeakageIssue] = []
    family_partitions: dict[str, set[str]] = {}
    family_case_ids: dict[str, list[str]] = {}
    family_to_partition: dict[str, set[str]] = {}
    fingerprints: dict[str, list[dict[str, Any]]] = {}
    seen_case_ids: set[str] = set()

    for case in rows:
        case_id = str(case.get("case_id", ""))
        family_id = str(case.get("scenario_family_id", ""))
        partition = str(case.get("partition", ""))
        if case_id in seen_case_ids:
            issues.append(
                LeakageIssue(
                    "DUPLICATE_CASE_ID",
                    (case_id,),
                    "A case ID occurs more than once.",
                )
            )
        seen_case_ids.add(case_id)
        family_partitions.setdefault(family_id, set()).add(partition)
        family_to_partition.setdefault(family_id, set()).add(partition)
        family_case_ids.setdefault(family_id, []).append(case_id)
        fingerprints.setdefault(_input_fingerprint(case), []).append(case)

        provenance = case.get("provenance") or {}
        governance = case.get("governance") or {}
        legacy_pilot_source = (
            str(provenance.get("source_asset_id", "")).startswith("RQ2_V1")
            or "PILOT" in str(provenance.get("source_asset_id", ""))
        )
        if partition == "TEST" and (
            bool(provenance.get("prior_exposure_to_model_selection"))
            or not bool(governance.get("final_test_eligible"))
            or legacy_pilot_source
        ):
            issues.append(
                LeakageIssue(
                    "EXPOSED_OR_INELIGIBLE_CASE_IN_TEST",
                    (case_id,),
                    "Prior-exposed, pilot, or final-test-ineligible material cannot be TEST.",
                )
            )

    for family_id, partitions in family_partitions.items():
        if "DEV" in partitions and "TEST" in partitions:
            issues.append(
                LeakageIssue(
                    "SCENARIO_FAMILY_SPLIT_ACROSS_DEV_TEST",
                    tuple(sorted(family_case_ids[family_id])),
                    f"Scenario family {family_id} occurs in both DEV and TEST.",
                )
            )

    for case in rows:
        provenance = case.get("provenance") or {}
        if provenance.get("type") != "LLM_AUGMENTED":
            continue
        augmentation = provenance.get("augmentation") or {}
        source_partition = augmentation.get("source_partition")
        source_family = str(augmentation.get("source_family_id", ""))
        if source_partition == "TEST" or "TEST" in family_to_partition.get(
            source_family, set()
        ):
            issues.append(
                LeakageIssue(
                    "LLM_AUGMENTATION_DERIVED_FROM_TEST",
                    (str(case.get("case_id", "")),),
                    "LLM augmentation may derive from DEV scenario families only.",
                )
            )

    for duplicate_rows in fingerprints.values():
        family_ids = {str(row.get("scenario_family_id")) for row in duplicate_rows}
        if len(duplicate_rows) > 1 and len(family_ids) > 1:
            issues.append(
                LeakageIssue(
                    "OBVIOUS_DUPLICATE_INPUT_ACROSS_FAMILIES",
                    tuple(sorted(str(row.get("case_id")) for row in duplicate_rows)),
                    "Identical normalised model-visible input occurs in multiple families.",
                )
            )
    return issues


def _walk_payload(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    yield path, value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_payload(item, (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk_payload(item, (*path, str(index)))


def detect_tuning_leakage(
    tuning_payload: Any,
    cases: Iterable[Mapping[str, Any]],
) -> list[LeakageIssue]:
    test_ids = {
        str(case["case_id"])
        for case in cases
        if str(case.get("partition")) == "TEST"
    }
    issues: list[LeakageIssue] = []
    for path, value in _walk_payload(tuning_payload):
        key = path[-1].casefold() if path else ""
        if "gold" in key:
            issues.append(
                LeakageIssue(
                    "GOLD_FIELD_IN_TUNING_PAYLOAD",
                    (),
                    f"Tuning payload contains Gold-like field at {'.'.join(path)}.",
                )
            )
        if isinstance(value, str) and value in test_ids:
            issues.append(
                LeakageIssue(
                    "TEST_CASE_REFERENCED_BY_TUNING",
                    (value,),
                    "A TEST case ID appears in a tuning payload.",
                )
            )
    return issues


def assert_no_leakage(
    cases: Iterable[Mapping[str, Any]], tuning_payload: Any | None = None
) -> None:
    rows = [dict(case) for case in cases]
    issues = detect_case_leakage(rows)
    if tuning_payload is not None:
        issues.extend(detect_tuning_leakage(tuning_payload, rows))
    if issues:
        raise LeakageViolation(issues)
