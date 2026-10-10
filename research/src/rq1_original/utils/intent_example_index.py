"""Governed Stage-3A intent-example candidates and human-review tooling.

This module contains data contracts and offline validation/export helpers only.
It does not classify production queries, compute embeddings, rank examples, or
integrate with C_FULL routing.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import csv
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from utils.intent_schema import (
    INTENT_SCHEMA_VERSION,
    LEGACY_QUERY_TYPES,
    SEMANTIC_INTENT_LABELS,
    SOURCE_SCOPE_LABELS,
)


INTENT_EXAMPLE_SCHEMA_VERSION = "intent-example-schema-v1"

CONTEXT_REQUIREMENTS = (
    "query_only",
    "current_page",
    "conversation_history",
    "memory_resolution",
    "multi_source_context",
)
FAMILY_ASSIGNMENT_METHODS = (
    "source_defined",
    "manual_candidate",
    "template_family",
    "singleton_pending_review",
)
PROVENANCE_TYPES = (
    "human_reviewed_benchmark",
    "existing_test_candidate",
    "human_authored_candidate",
)
SOURCE_REVIEW_STATUSES = ("approved", "revised", "not_previously_reviewed")
INDEX_REVIEW_STATUSES = ("pending", "approved", "rejected")
HUMAN_DECISIONS = ("", "approved", "revised", "rejected")
INTENDED_PARTITIONS = (
    "development_candidate",
    "diagnostic_only",
    "future_heldout_reserved",
    "excluded",
)

BENCHMARK_SOURCE = "evaluation/unified_benchmark_scenarios.jsonl"
CANDIDATE_FILE = "evaluation/intent_examples_candidate_v1.jsonl"
REVIEW_FILE = "evaluation/intent_examples_human_review_v1.csv"
METADATA_FILE = "evaluation/intent_example_index_metadata_v1.json"
STAGE3A_GENERATED_AT = "2026-08-03T00:00:00Z"

APPROVED_INDEX_VERSION = "intent-approved-index-v1"
RETRIEVAL_TEXT_VERSION = "intent-retrieval-text-v1"
REVIEW_SOURCE = "researcher_confirmed_assisted_review"
COMPLETED_REVIEW_FILE = "evaluation/intent_examples_human_review_v1_completed.csv"
APPROVED_INDEX_FILE = "evaluation/intent_examples_approved_index_v1.jsonl"
APPROVED_INDEX_SHA256_FILE = "evaluation/intent_examples_approved_index_v1.sha256"
APPROVED_METADATA_FILE = "evaluation/intent_example_approved_metadata_v1.json"
REVIEW_AUDIT_FILE = "evaluation/intent_example_review_audit_v1.json"
STAGE3B_FREEZE_TIMESTAMP = "2026-08-03T00:00:00Z"
CANONICAL_PAGES = ("Overview", "Resources", "Lecture", "Debate", "Reflection")

HUMAN_REVIEW_COLUMNS = (
    "example_id",
    "query",
    "page_context",
    "semantic_label_proposed",
    "source_scope_proposed",
    "context_requirement",
    "index_eligibility_proposed",
    "exclusion_reason",
    "paraphrase_family_id",
    "provenance_type",
    "source_path",
    "source_record_id",
    "source_review_status",
    "intended_partition",
    "index_review_status",
    "human_decision",
    "human_corrected_semantic_label",
    "human_corrected_source_scope",
    "human_corrected_context_requirement",
    "human_corrected_index_eligibility",
    "human_corrected_paraphrase_family_id",
    "human_notes",
)

_PENDING_HUMAN_FIELDS = (
    "human_decision",
    "human_corrected_semantic_label",
    "human_corrected_source_scope",
    "human_corrected_context_requirement",
    "human_corrected_index_eligibility",
    "human_corrected_paraphrase_family_id",
    "human_notes",
)


def normalise_example_query(query: str) -> str:
    """Return a stable, meaning-preserving key for duplicate detection."""

    text = unicodedata.normalize("NFKC", str(query))
    return re.sub(r"\s+", " ", text.strip()).casefold()


def _validate_non_empty(name: str, value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _json_safe_slot_hints(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("slot_hints must be a mapping")
    copied = json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
    if not isinstance(copied, dict):
        raise ValueError("slot_hints must serialise to a JSON object")
    return MappingProxyType(copied)


@dataclass(frozen=True)
class IntentExampleRecord:
    """One proposed example; Stage 3A records are never self-approved."""

    example_id: str
    query: str
    normalised_query: str
    semantic_label_proposed: str
    legacy_query_type_proposed: str | None
    source_scope_proposed: str
    context_requirement: str
    index_eligibility_proposed: bool
    exclusion_reason: str
    page_context: str
    slot_hints: Mapping[str, object]
    paraphrase_family_id: str
    family_assignment_method: str
    provenance_type: str
    source_path: str
    source_record_id: str
    source_gold_label_version: str
    source_review_status: str
    source_reviewed_by: str
    index_review_status: str = "pending"
    human_decision: str = ""
    human_corrected_semantic_label: str = ""
    human_corrected_source_scope: str = ""
    human_corrected_context_requirement: str = ""
    human_corrected_index_eligibility: str = ""
    human_corrected_paraphrase_family_id: str = ""
    human_notes: str = ""
    intended_partition: str = "development_candidate"
    example_schema_version: str = INTENT_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.example_schema_version != INTENT_EXAMPLE_SCHEMA_VERSION:
            raise ValueError("Unknown intent-example schema version")
        example_id = _validate_non_empty("example_id", self.example_id)
        if not re.fullmatch(r"IE-[A-Z0-9-]+", example_id):
            raise ValueError(f"Invalid example_id: {example_id!r}")
        query = _validate_non_empty("query", self.query)
        expected_normalised = normalise_example_query(query)
        if self.normalised_query != expected_normalised:
            raise ValueError("normalised_query does not match the stable normaliser")
        if self.semantic_label_proposed not in SEMANTIC_INTENT_LABELS:
            raise ValueError("Invalid proposed semantic label")
        if self.legacy_query_type_proposed is not None:
            if self.legacy_query_type_proposed not in LEGACY_QUERY_TYPES:
                raise ValueError("Invalid proposed legacy query type")
        if self.semantic_label_proposed in LEGACY_QUERY_TYPES:
            if self.legacy_query_type_proposed != self.semantic_label_proposed:
                raise ValueError("Legacy semantic candidates must retain the same legacy type")
        elif self.legacy_query_type_proposed is not None:
            raise ValueError("Future semantic outcomes cannot be forced into a legacy type")
        if self.source_scope_proposed not in SOURCE_SCOPE_LABELS:
            raise ValueError("Invalid proposed source scope")
        if self.context_requirement not in CONTEXT_REQUIREMENTS:
            raise ValueError("Invalid context requirement")
        if not isinstance(self.index_eligibility_proposed, bool):
            raise ValueError("index_eligibility_proposed must be boolean")
        exclusion_reason = str(self.exclusion_reason).strip()
        if self.index_eligibility_proposed and exclusion_reason:
            raise ValueError("Eligible candidates cannot have an exclusion reason")
        if not self.index_eligibility_proposed and not exclusion_reason:
            raise ValueError("Ineligible candidates require an exclusion reason")
        if self.context_requirement in {"conversation_history", "memory_resolution"}:
            if self.index_eligibility_proposed:
                raise ValueError("History/Memory-dependent candidates are not index eligible")
            if self.intended_partition != "diagnostic_only":
                raise ValueError("History/Memory-dependent candidates must be diagnostic-only")
        family_id = _validate_non_empty(
            "paraphrase_family_id", self.paraphrase_family_id
        )
        if not re.fullmatch(r"PF-[A-Z0-9-]+", family_id):
            raise ValueError(f"Invalid paraphrase family ID: {family_id!r}")
        if self.family_assignment_method not in FAMILY_ASSIGNMENT_METHODS:
            raise ValueError("Invalid family assignment method")
        if self.provenance_type not in PROVENANCE_TYPES:
            raise ValueError("Invalid provenance type")
        _validate_non_empty("source_path", self.source_path)
        _validate_non_empty("source_record_id", self.source_record_id)
        if self.source_review_status not in SOURCE_REVIEW_STATUSES:
            raise ValueError("Invalid source review status")
        if self.provenance_type == "human_reviewed_benchmark":
            if self.source_review_status not in {"approved", "revised"}:
                raise ValueError("Benchmark candidates require approved/revised source gold")
            _validate_non_empty("source_gold_label_version", self.source_gold_label_version)
            _validate_non_empty("source_reviewed_by", self.source_reviewed_by)
        elif self.source_review_status != "not_previously_reviewed":
            raise ValueError("Non-benchmark candidates are not previously reviewed")
        if self.index_review_status not in INDEX_REVIEW_STATUSES:
            raise ValueError("Invalid index review status")
        if self.human_decision not in HUMAN_DECISIONS:
            raise ValueError("Invalid human review decision")
        if self.human_corrected_index_eligibility not in {"", "true", "false"}:
            raise ValueError("Corrected index eligibility must be blank, true, or false")
        if self.index_review_status == "pending":
            if any(str(getattr(self, name)).strip() for name in _PENDING_HUMAN_FIELDS):
                raise ValueError("Pending candidates must have empty human-review fields")
        elif not self.human_decision:
            raise ValueError("A completed index review requires a human decision")
        if self.intended_partition not in INTENDED_PARTITIONS:
            raise ValueError("Invalid intended partition")
        if self.provenance_type in {
            "human_reviewed_benchmark",
            "human_authored_candidate",
        } and self.intended_partition == "future_heldout_reserved":
            raise ValueError("Current Stage-3A material cannot be future held-out")
        if self.index_eligibility_proposed:
            if self.intended_partition != "development_candidate":
                raise ValueError("Eligible candidates must be development candidates")
        elif self.intended_partition not in {"diagnostic_only", "excluded"}:
            raise ValueError("Ineligible candidates must be diagnostic-only or excluded")
        object.__setattr__(self, "example_id", example_id)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "exclusion_reason", exclusion_reason)
        object.__setattr__(self, "page_context", str(self.page_context).strip())
        object.__setattr__(self, "slot_hints", _json_safe_slot_hints(self.slot_hints))
        object.__setattr__(self, "paraphrase_family_id", family_id)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "IntentExampleRecord":
        values = dict(payload)
        values.setdefault("slot_hints", {})
        values.setdefault("legacy_query_type_proposed", None)
        return cls(**values)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "query": self.query,
            "normalised_query": self.normalised_query,
            "semantic_label_proposed": self.semantic_label_proposed,
            "legacy_query_type_proposed": self.legacy_query_type_proposed,
            "source_scope_proposed": self.source_scope_proposed,
            "context_requirement": self.context_requirement,
            "index_eligibility_proposed": self.index_eligibility_proposed,
            "exclusion_reason": self.exclusion_reason,
            "page_context": self.page_context,
            "slot_hints": dict(self.slot_hints),
            "paraphrase_family_id": self.paraphrase_family_id,
            "family_assignment_method": self.family_assignment_method,
            "provenance_type": self.provenance_type,
            "source_path": self.source_path,
            "source_record_id": self.source_record_id,
            "source_gold_label_version": self.source_gold_label_version,
            "source_review_status": self.source_review_status,
            "source_reviewed_by": self.source_reviewed_by,
            "index_review_status": self.index_review_status,
            "human_decision": self.human_decision,
            "human_corrected_semantic_label": self.human_corrected_semantic_label,
            "human_corrected_source_scope": self.human_corrected_source_scope,
            "human_corrected_context_requirement": self.human_corrected_context_requirement,
            "human_corrected_index_eligibility": self.human_corrected_index_eligibility,
            "human_corrected_paraphrase_family_id": self.human_corrected_paraphrase_family_id,
            "human_notes": self.human_notes,
            "intended_partition": self.intended_partition,
            "example_schema_version": self.example_schema_version,
        }


def load_candidate_examples(path: str | Path) -> tuple[IntentExampleRecord, ...]:
    records = tuple(
        IntentExampleRecord.from_dict(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    validate_candidate_examples(records)
    return records


def group_by_semantic_label(
    records: Iterable[IntentExampleRecord],
) -> dict[str, tuple[IntentExampleRecord, ...]]:
    return _group_records(records, lambda item: item.semantic_label_proposed)


def group_by_paraphrase_family(
    records: Iterable[IntentExampleRecord],
) -> dict[str, tuple[IntentExampleRecord, ...]]:
    return _group_records(records, lambda item: item.paraphrase_family_id)


def group_by_context_requirement(
    records: Iterable[IntentExampleRecord],
) -> dict[str, tuple[IntentExampleRecord, ...]]:
    return _group_records(records, lambda item: item.context_requirement)


def _group_records(records: Iterable[IntentExampleRecord], key) -> dict[str, tuple[IntentExampleRecord, ...]]:
    grouped: dict[str, list[IntentExampleRecord]] = defaultdict(list)
    for record in records:
        grouped[str(key(record))].append(record)
    return {
        name: tuple(sorted(items, key=lambda item: item.example_id))
        for name, items in sorted(grouped.items())
    }


def derive_proposed_source_scope(
    source: Mapping[str, object] | IntentExampleRecord,
    context_requirement: str | None = None,
) -> str:
    """Map audited capabilities to a proposed scope without production routing."""

    if isinstance(source, IntentExampleRecord):
        return source.source_scope_proposed
    context = context_requirement or str(source.get("context_requirement") or "")
    expected_memory = bool(source.get("gold_expected_memory"))
    if expected_memory and context in {"conversation_history", "memory_resolution"}:
        return "undetermined"
    capabilities = {str(item) for item in source.get("gold_required_capabilities", []) or []}
    has_course = "course_material_retrieval" in capabilities
    has_dashboard = "dashboard_evidence" in capabilities
    if has_course and has_dashboard:
        return "hybrid"
    if has_course:
        return "course_only"
    if has_dashboard:
        return "dashboard_only"
    return "undetermined"


def find_label_conflicts(records: Iterable[IntentExampleRecord]) -> list[dict[str, Any]]:
    grouped: dict[str, list[IntentExampleRecord]] = defaultdict(list)
    for record in records:
        grouped[record.normalised_query].append(record)
    conflicts = []
    for query, items in sorted(grouped.items()):
        labels = sorted({item.semantic_label_proposed for item in items})
        if len(labels) > 1:
            conflicts.append(
                {
                    "normalised_query": query,
                    "example_ids": sorted(item.example_id for item in items),
                    "semantic_labels": labels,
                }
            )
    return conflicts


def find_family_conflicts(records: Iterable[IntentExampleRecord]) -> list[dict[str, Any]]:
    records_tuple = tuple(records)
    conflicts: list[dict[str, Any]] = []
    for family_id, items in group_by_paraphrase_family(records_tuple).items():
        labels = sorted({item.semantic_label_proposed for item in items})
        contexts = sorted({item.context_requirement for item in items})
        scopes = sorted({item.source_scope_proposed for item in items})
        partitions = sorted({item.intended_partition for item in items})
        reasons = []
        if len(labels) > 1:
            reasons.append("multiple_semantic_labels")
        if len(contexts) > 1:
            reasons.append("multiple_context_requirements")
        if len(scopes) > 1:
            reasons.append("multiple_source_scopes")
        if len(partitions) > 1:
            reasons.append("multiple_partitions")
        if reasons:
            conflicts.append(
                {
                    "family_id": family_id,
                    "example_ids": [item.example_id for item in items],
                    "reasons": reasons,
                }
            )
    duplicate_groups: dict[str, list[IntentExampleRecord]] = defaultdict(list)
    for record in records_tuple:
        duplicate_groups[record.normalised_query].append(record)
    for query, items in sorted(duplicate_groups.items()):
        families = sorted({item.paraphrase_family_id for item in items})
        if len(families) > 1:
            conflicts.append(
                {
                    "normalised_query": query,
                    "example_ids": sorted(item.example_id for item in items),
                    "reasons": ["duplicate_query_across_families"],
                }
            )
    return conflicts


def find_partition_leakage(records: Iterable[IntentExampleRecord]) -> list[dict[str, Any]]:
    records_tuple = tuple(records)
    leakage: list[dict[str, Any]] = []
    for family_id, items in group_by_paraphrase_family(records_tuple).items():
        partitions = sorted({item.intended_partition for item in items})
        if len(partitions) > 1:
            leakage.append(
                {
                    "family_id": family_id,
                    "partitions": partitions,
                    "example_ids": [item.example_id for item in items],
                }
            )
    for record in records_tuple:
        if record.intended_partition == "future_heldout_reserved" and record.provenance_type in {
            "human_reviewed_benchmark",
            "human_authored_candidate",
        }:
            leakage.append(
                {
                    "example_id": record.example_id,
                    "reason": "stage3a_material_marked_future_heldout",
                }
            )
    return leakage


def validate_candidate_examples(records: Sequence[IntentExampleRecord]) -> None:
    identifiers = [record.example_id for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate example_id")
    normalised = [record.normalised_query for record in records]
    if len(normalised) != len(set(normalised)):
        conflicts = find_label_conflicts(records)
        suffix = " with conflicting labels" if conflicts else ""
        raise ValueError(f"Duplicate normalised query{suffix}")
    family_conflicts = find_family_conflicts(records)
    if family_conflicts:
        raise ValueError(f"Paraphrase-family conflicts: {family_conflicts}")
    leakage = find_partition_leakage(records)
    if leakage:
        raise ValueError(f"Partition leakage: {leakage}")


def deduplicate_candidate_examples(
    records: Iterable[IntentExampleRecord],
) -> tuple[IntentExampleRecord, ...]:
    grouped: dict[str, list[IntentExampleRecord]] = defaultdict(list)
    for record in records:
        grouped[record.normalised_query].append(record)
    if find_label_conflicts(record for items in grouped.values() for record in items):
        raise ValueError("Cannot deduplicate queries with conflicting semantic labels")
    selected = []
    for items in grouped.values():
        families = {item.paraphrase_family_id for item in items}
        if len(families) > 1:
            raise ValueError("Duplicate normalised queries must use the same family")
        selected.append(sorted(items, key=lambda item: item.example_id)[0])
    return tuple(sorted(selected, key=lambda item: item.example_id))


def _effective_index_eligibility(record: IntentExampleRecord) -> bool:
    if record.human_decision == "revised" and record.human_corrected_index_eligibility:
        return record.human_corrected_index_eligibility == "true"
    return record.index_eligibility_proposed


def select_approved_index_examples(
    records: Iterable[IntentExampleRecord],
) -> tuple[IntentExampleRecord, ...]:
    return tuple(
        sorted(
            (
                record
                for record in records
                if record.index_review_status == "approved"
                and record.human_decision in {"approved", "revised"}
                and _effective_index_eligibility(record)
            ),
            key=lambda item: item.example_id,
        )
    )


def export_human_review_csv(
    records: Iterable[IntentExampleRecord], path: str | Path
) -> None:
    target = Path(path)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HUMAN_REVIEW_COLUMNS)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item.example_id):
            payload = record.to_dict()
            payload["index_eligibility_proposed"] = (
                "true" if record.index_eligibility_proposed else "false"
            )
            writer.writerow({column: payload.get(column, "") for column in HUMAN_REVIEW_COLUMNS})


def load_human_review_csv(path: str | Path) -> tuple[dict[str, str], ...]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != HUMAN_REVIEW_COLUMNS:
            raise ValueError("Human-review CSV columns do not match the versioned contract")
        rows = tuple(dict(row) for row in reader)
    for row in rows:
        if row["human_decision"] not in HUMAN_DECISIONS:
            raise ValueError("Invalid human decision in review CSV")
        if row["human_corrected_index_eligibility"] not in {"", "true", "false"}:
            raise ValueError("Invalid corrected index eligibility in review CSV")
    return rows


def _counter(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def build_index_metadata(
    records: Sequence[IntentExampleRecord],
    *,
    source_scenario_dispositions: Sequence[Mapping[str, object]] = (),
    generated_at: str = STAGE3A_GENERATED_AT,
) -> dict[str, Any]:
    records_tuple = tuple(records)
    family_groups = group_by_paraphrase_family(records_tuple)
    duplicate_count = len(records_tuple) - len(
        {record.normalised_query for record in records_tuple}
    )
    label_conflicts = find_label_conflicts(records_tuple)
    family_conflicts = find_family_conflicts(records_tuple)
    partition_leakage = find_partition_leakage(records_tuple)
    benchmark_source_labels = Counter(
        record.semantic_label_proposed
        for record in records_tuple
        if record.provenance_type == "human_reviewed_benchmark"
    )
    all_source_statuses = Counter(
        str(item.get("source_review_status") or "")
        for item in source_scenario_dispositions
    )
    return {
        "schema_version": INTENT_EXAMPLE_SCHEMA_VERSION,
        "intent_schema_version": INTENT_SCHEMA_VERSION,
        "candidate_file": CANDIDATE_FILE,
        "review_file": REVIEW_FILE,
        "generated_at": generated_at,
        "total_candidates": len(records_tuple),
        "source_benchmark_candidates": sum(
            record.provenance_type == "human_reviewed_benchmark"
            for record in records_tuple
        ),
        "existing_test_candidates": sum(
            record.provenance_type == "existing_test_candidate"
            for record in records_tuple
        ),
        "human_authored_candidates": sum(
            record.provenance_type == "human_authored_candidate"
            for record in records_tuple
        ),
        "counts_by_semantic_label": _counter(
            record.semantic_label_proposed for record in records_tuple
        ),
        "counts_by_source_scope": _counter(
            record.source_scope_proposed for record in records_tuple
        ),
        "counts_by_context_requirement": _counter(
            record.context_requirement for record in records_tuple
        ),
        "counts_by_provenance": _counter(
            record.provenance_type for record in records_tuple
        ),
        "counts_by_source_review_status": _counter(
            record.source_review_status for record in records_tuple
        ),
        "source_benchmark_review_status_counts": dict(sorted(all_source_statuses.items())),
        "counts_by_intended_partition": _counter(
            record.intended_partition for record in records_tuple
        ),
        "counts_by_index_eligibility": _counter(
            str(record.index_eligibility_proposed).lower() for record in records_tuple
        ),
        "paraphrase_family_count": len(family_groups),
        "singleton_family_count": sum(len(items) == 1 for items in family_groups.values()),
        "paraphrase_family_report": [
            {
                "family_id": family_id,
                "member_count": len(items),
                "semantic_labels": sorted(
                    {item.semantic_label_proposed for item in items}
                ),
                "source_scopes": sorted(
                    {item.source_scope_proposed for item in items}
                ),
                "context_requirements": sorted(
                    {item.context_requirement for item in items}
                ),
                "provenance_types": sorted(
                    {item.provenance_type for item in items}
                ),
            }
            for family_id, items in family_groups.items()
        ],
        "duplicate_query_count": duplicate_count,
        "label_conflict_count": len(label_conflicts),
        "family_conflict_count": len(family_conflicts),
        "partition_leakage_count": len(partition_leakage),
        "pending_review_count": sum(
            record.index_review_status == "pending" for record in records_tuple
        ),
        "approved_index_count": len(select_approved_index_examples(records_tuple)),
        "deterministic_classifier_outputs_used_as_semantic_labels": 0,
        "source_benchmark_scenarios_total": len(source_scenario_dispositions),
        "source_benchmark_scenarios_handled": len(source_scenario_dispositions),
        "benchmark_documented_exclusion_count": sum(
            item.get("disposition") == "excluded" for item in source_scenario_dispositions
        ),
        "source_scenario_dispositions": [dict(item) for item in source_scenario_dispositions],
        "missing_legacy_labels_in_source_benchmark": sorted(
            set(LEGACY_QUERY_TYPES) - set(benchmark_source_labels)
        ),
        "underrepresented_legacy_labels_in_source_benchmark": dict(
            sorted(
                (label, count)
                for label, count in benchmark_source_labels.items()
                if count < 3
            )
        ),
        "development_data_warning": (
            "The current unified benchmark is used only as development candidate "
            "material for the semantic router. It must not be reused as the primary "
            "held-out semantic-routing evaluation."
        ),
        "approval_warning": "No candidate is approved for semantic retrieval yet.",
        "future_outcome_definitions": {
            "social_interaction": "Social greeting, gratitude, wellbeing, or farewell interaction.",
            "unsupported_task": "Learning-related action the assistant cannot execute or evidence reliably.",
            "out_of_scope": "Request unrelated to the learning-analytics assistant task.",
            "ambiguous": "Insufficient referent or task information when no context is supplied.",
        },
        "manual_review_focus": [
            {
                "source_record_ids": ["U022", "U026", "U031"],
                "reason": "Same query appears with different history and Memory conditions; U026 is retained as diagnostic and U022/U031 are documented exclusions.",
            },
            {
                "source_record_ids": ["U036"],
                "reason": "Generic metric wording depends on current page while unrelated history is present.",
            },
            {
                "source_record_ids": ["U058", "U060"],
                "reason": "Conversation referents overlap course retrieval and must not bypass Memory guards.",
            },
            {
                "source_record_ids": ["U042", "U043", "U044", "U047", "U055"],
                "reason": "Human gold labels and capability-derived scopes are unusual and require index-specific review.",
            },
        ],
    }


_ALLOWED_BENCHMARK_FIELDS = (
    "scenario_id",
    "source_dataset",
    "source_scenario_id",
    "page",
    "student_query",
    "gold_query_type",
    "gold_expected_route",
    "gold_expected_memory",
    "gold_expected_retrieval",
    "gold_required_capabilities",
    "gold_label_version",
    "gold_review_status",
    "gold_reviewed_by",
    "gold_review_notes",
)

_BENCHMARK_EXCLUSIONS = {
    "U022": (
        "Exact normalized-query duplicate of U026/U031 with a different context "
        "condition; U026 is retained as the conservative diagnostic record."
    ),
    "U031": (
        "Exact normalized-query duplicate of U022/U026 with a different Memory "
        "condition; U026 is retained as the conservative diagnostic record."
    ),
}

_CONVERSATION_HISTORY_IDS = {
    "U026",
    "U027",
    "U028",
    "U029",
    "U032",
    "U058",
    "U060",
    "U062",
}
_MEMORY_RESOLUTION_IDS = {"U033", "U034", "U035", "U037"}
_CURRENT_PAGE_IDS = {
    "U005",
    "U007",
    "U008",
    "U009",
    "U016",
    "U017",
    "U018",
    "U036",
}
_MULTI_SOURCE_CONTEXT_IDS = {"U059"}

_BENCHMARK_FAMILY_GROUPS = {
    "PF-ACCESS-EMAIL-VISIBILITY-001": {"U003", "U020"},
    "PF-DASHBOARD-TAILOR-DATA-001": {"U005", "U007"},
    "PF-ACTIVITY-IMPROVEMENT-001": {"U013", "U015"},
    "PF-CURRENT-ACTIVITY-IMPROVEMENT-001": {"U016", "U017"},
    "PF-REFLECTION-STRUCTURE-001": {"U023", "U038"},
    "PF-COURSE-WEEK-LECTURE-TOPIC-001": {"U024", "U040", "U041"},
    "PF-MEMORY-POINT-EXPLANATION-001": {"U027", "U062"},
    "PF-MEMORY-STEP-REFERENCE-001": {"U028", "U032"},
    "PF-MEMORY-NEXT-ACTION-001": {"U033", "U034"},
    "PF-PLAN-CONTINUATION-CONTEXT-001": {"U035", "U037"},
    "PF-COURSE-RESOURCE-LOOKUP-001": {"U042", "U047"},
    "PF-METRIC-INTERPRETATION-001": {"U010", "U045"},
    "PF-METRIC-DEFINITION-001": {"U002", "U048", "U049", "U050", "U051", "U052"},
    "PF-CROSS-PAGE-RELATIONSHIP-001": {"U053", "U054", "U056"},
}
_BENCHMARK_FAMILY_BY_ID = {
    scenario_id: family_id
    for family_id, scenario_ids in _BENCHMARK_FAMILY_GROUPS.items()
    for scenario_id in scenario_ids
}


def _read_allowed_benchmark_rows(path: str | Path) -> tuple[dict[str, object], ...]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        selected = {name: raw.get(name) for name in _ALLOWED_BENCHMARK_FIELDS}
        selected["conversation_history_nonempty"] = bool(raw.get("conversation_history"))
        rows.append(selected)
    return tuple(rows)


def _context_for_benchmark(scenario_id: str) -> str:
    if scenario_id in _CONVERSATION_HISTORY_IDS:
        return "conversation_history"
    if scenario_id in _MEMORY_RESOLUTION_IDS:
        return "memory_resolution"
    if scenario_id in _CURRENT_PAGE_IDS:
        return "current_page"
    if scenario_id in _MULTI_SOURCE_CONTEXT_IDS:
        return "multi_source_context"
    return "query_only"


def _slot_hints(query: str, page_context: str) -> dict[str, object]:
    hints: dict[str, object] = {}
    if page_context:
        hints["page"] = page_context
    week_match = re.search(r"\b(?:w|week\s*)(\d{1,2})\b", query, flags=re.IGNORECASE)
    if week_match:
        hints["week"] = f"W{int(week_match.group(1))}"
    metric_match = re.search(
        r"\b(?:Resources_views|Debate_replies|Total_chars|Video View %)\b",
        query,
        flags=re.IGNORECASE,
    )
    if metric_match:
        hints["metric"] = metric_match.group(0)
    duration_match = re.search(r"\b(?:next\s+)?\d+\s+days?\b", query, flags=re.IGNORECASE)
    if duration_match:
        hints["duration"] = duration_match.group(0)
    return hints


def _make_record(
    *,
    example_id: str,
    query: str,
    semantic_label: str,
    source_scope: str,
    context_requirement: str,
    page_context: str,
    paraphrase_family_id: str,
    family_assignment_method: str,
    provenance_type: str,
    source_path: str,
    source_record_id: str,
    source_gold_label_version: str = "",
    source_review_status: str = "not_previously_reviewed",
    source_reviewed_by: str = "",
) -> IntentExampleRecord:
    eligible = context_requirement not in {"conversation_history", "memory_resolution"}
    if context_requirement == "conversation_history":
        exclusion_reason = "Requires conversation history to resolve an otherwise incomplete referent."
    elif context_requirement == "memory_resolution":
        exclusion_reason = "Requires existing Memory state; the semantic index must not bypass the Memory hard guard."
    else:
        exclusion_reason = ""
    return IntentExampleRecord(
        example_id=example_id,
        query=query,
        normalised_query=normalise_example_query(query),
        semantic_label_proposed=semantic_label,
        legacy_query_type_proposed=(
            semantic_label if semantic_label in LEGACY_QUERY_TYPES else None
        ),
        source_scope_proposed=source_scope,
        context_requirement=context_requirement,
        index_eligibility_proposed=eligible,
        exclusion_reason=exclusion_reason,
        page_context=page_context,
        slot_hints=_slot_hints(query, page_context),
        paraphrase_family_id=paraphrase_family_id,
        family_assignment_method=family_assignment_method,
        provenance_type=provenance_type,
        source_path=source_path,
        source_record_id=source_record_id,
        source_gold_label_version=source_gold_label_version,
        source_review_status=source_review_status,
        source_reviewed_by=source_reviewed_by,
        intended_partition=("development_candidate" if eligible else "diagnostic_only"),
    )


def extract_benchmark_candidates(
    path: str | Path,
) -> tuple[tuple[IntentExampleRecord, ...], tuple[dict[str, object], ...]]:
    records: list[IntentExampleRecord] = []
    dispositions: list[dict[str, object]] = []
    for row in _read_allowed_benchmark_rows(path):
        scenario_id = str(row.get("scenario_id") or "")
        review_status = str(row.get("gold_review_status") or "")
        if review_status not in {"approved", "revised"}:
            dispositions.append(
                {
                    "scenario_id": scenario_id,
                    "source_review_status": review_status,
                    "disposition": "excluded",
                    "reason": "Source gold is not approved or revised.",
                }
            )
            continue
        if scenario_id in _BENCHMARK_EXCLUSIONS:
            dispositions.append(
                {
                    "scenario_id": scenario_id,
                    "source_review_status": review_status,
                    "disposition": "excluded",
                    "reason": _BENCHMARK_EXCLUSIONS[scenario_id],
                }
            )
            continue
        context = _context_for_benchmark(scenario_id)
        family_id = _BENCHMARK_FAMILY_BY_ID.get(
            scenario_id, f"PF-BENCH-{scenario_id}"
        )
        record = _make_record(
            example_id=f"IE-BENCH-{scenario_id}",
            query=str(row.get("student_query") or ""),
            semantic_label=str(row.get("gold_query_type") or ""),
            source_scope=derive_proposed_source_scope(row, context),
            context_requirement=context,
            page_context=str(row.get("page") or ""),
            paraphrase_family_id=family_id,
            family_assignment_method=(
                "template_family"
                if scenario_id in _BENCHMARK_FAMILY_BY_ID
                else "singleton_pending_review"
            ),
            provenance_type="human_reviewed_benchmark",
            source_path=BENCHMARK_SOURCE,
            source_record_id=scenario_id,
            source_gold_label_version=str(row.get("gold_label_version") or ""),
            source_review_status=review_status,
            source_reviewed_by=str(row.get("gold_reviewed_by") or ""),
        )
        records.append(record)
        dispositions.append(
            {
                "scenario_id": scenario_id,
                "source_review_status": review_status,
                "disposition": (
                    "candidate"
                    if record.intended_partition == "development_candidate"
                    else "diagnostic_only"
                ),
                "example_id": record.example_id,
            }
        )
    return (
        tuple(sorted(records, key=lambda item: item.example_id)),
        tuple(sorted(dispositions, key=lambda item: str(item["scenario_id"]))),
    )


_EXISTING_TEST_CANDIDATES = (
    {
        "example_id": "IE-TEST-MEMORY-CURRENT-GOAL-001",
        "query": "What is my current goal?",
        "semantic_label": "memory_state_query",
        "source_scope": "undetermined",
        "context_requirement": "memory_resolution",
        "page_context": "",
        "family_id": "PF-MEMORY-CURRENT-GOAL-001",
        "source_path": "test_query_classification_trace.py",
        "source_record_id": "TRACE_CASES:memory_state_query",
    },
    {
        "example_id": "IE-TEST-HYBRID-COURSE-REFLECTION-001",
        "query": "How should I use the W5 lecture in my reflection?",
        "semantic_label": "hybrid_course_and_planning",
        "source_scope": "hybrid",
        "context_requirement": "multi_source_context",
        "page_context": "Reflection",
        "family_id": "PF-HYBRID-COURSE-REFLECTION-001",
        "source_path": "test_query_classification_trace.py",
        "source_record_id": "TRACE_CASES:hybrid_course_and_planning",
    },
    {
        "example_id": "IE-TEST-QUANT-LECTURE-COMPLETION-001",
        "query": "How is my lecture completion calculated?",
        "semantic_label": "quantitative_metric_query",
        "source_scope": "dashboard_only",
        "context_requirement": "query_only",
        "page_context": "Lecture",
        "family_id": "PF-QUANT-LECTURE-COMPLETION-001",
        "source_path": "test_query_classification_trace.py",
        "source_record_id": "TRACE_CASES:quantitative_metric_query",
    },
)


_HUMAN_AUTHORED_CANDIDATES = (
    ("IE-FUTURE-SOCIAL-001", "Hello", "social_interaction", "query_only", "PF-SOCIAL-GREETING-001"),
    ("IE-FUTURE-SOCIAL-002", "Hi there", "social_interaction", "query_only", "PF-SOCIAL-GREETING-001"),
    ("IE-FUTURE-SOCIAL-003", "Thanks for your help", "social_interaction", "query_only", "PF-SOCIAL-GRATITUDE-001"),
    ("IE-FUTURE-SOCIAL-004", "Goodbye", "social_interaction", "query_only", "PF-SOCIAL-FAREWELL-001"),
    ("IE-FUTURE-UNSUPPORTED-001", "Can you submit my assignment for me?", "unsupported_task", "query_only", "PF-UNSUPPORTED-SUBMISSION-001"),
    ("IE-FUTURE-UNSUPPORTED-002", "Please upload my reflection to Moodle.", "unsupported_task", "query_only", "PF-UNSUPPORTED-SUBMISSION-001"),
    ("IE-FUTURE-UNSUPPORTED-003", "Can you change my grade?", "unsupported_task", "query_only", "PF-UNSUPPORTED-GRADE-CHANGE-001"),
    ("IE-FUTURE-UNSUPPORTED-004", "Can you email my lecturer?", "unsupported_task", "query_only", "PF-UNSUPPORTED-EXTERNAL-COMMS-001"),
    ("IE-FUTURE-OOS-001", "Can you help me get a visa?", "out_of_scope", "query_only", "PF-OOS-VISA-001"),
    ("IE-FUTURE-OOS-002", "What is the football score?", "out_of_scope", "query_only", "PF-OOS-SPORTS-001"),
    ("IE-FUTURE-OOS-003", "Give me a dinner recipe.", "out_of_scope", "query_only", "PF-OOS-RECIPE-001"),
    ("IE-FUTURE-OOS-004", "Book me a flight to Paris.", "out_of_scope", "query_only", "PF-OOS-TRAVEL-BOOKING-001"),
    ("IE-FUTURE-AMBIGUOUS-001", "What does that mean?", "ambiguous", "conversation_history", "PF-AMBIGUOUS-REFERENT-EXPLANATION-001"),
    ("IE-FUTURE-AMBIGUOUS-002", "Can you explain it?", "ambiguous", "conversation_history", "PF-AMBIGUOUS-REFERENT-EXPLANATION-001"),
    ("IE-FUTURE-AMBIGUOUS-003", "What about the other one?", "ambiguous", "conversation_history", "PF-AMBIGUOUS-ALTERNATIVE-001"),
    ("IE-FUTURE-AMBIGUOUS-004", "Is this good?", "ambiguous", "conversation_history", "PF-AMBIGUOUS-EVALUATION-001"),
)


def build_stage3a_candidates(
    benchmark_path: str | Path,
) -> tuple[tuple[IntentExampleRecord, ...], tuple[dict[str, object], ...]]:
    benchmark_records, dispositions = extract_benchmark_candidates(benchmark_path)
    test_records = tuple(
        _make_record(
            example_id=str(item["example_id"]),
            query=str(item["query"]),
            semantic_label=str(item["semantic_label"]),
            source_scope=str(item["source_scope"]),
            context_requirement=str(item["context_requirement"]),
            page_context=str(item["page_context"]),
            paraphrase_family_id=str(item["family_id"]),
            family_assignment_method="singleton_pending_review",
            provenance_type="existing_test_candidate",
            source_path=str(item["source_path"]),
            source_record_id=str(item["source_record_id"]),
        )
        for item in _EXISTING_TEST_CANDIDATES
    )
    future_records = tuple(
        _make_record(
            example_id=example_id,
            query=query,
            semantic_label=label,
            source_scope=("undetermined" if label == "ambiguous" else "no_supported_source"),
            context_requirement=context,
            page_context="",
            paraphrase_family_id=family_id,
            family_assignment_method=(
                "template_family"
                if family_id in {
                    "PF-SOCIAL-GREETING-001",
                    "PF-UNSUPPORTED-SUBMISSION-001",
                    "PF-AMBIGUOUS-REFERENT-EXPLANATION-001",
                }
                else "manual_candidate"
            ),
            provenance_type="human_authored_candidate",
            source_path="utils/intent_example_index.py",
            source_record_id=example_id.removeprefix("IE-"),
        )
        for example_id, query, label, context, family_id in _HUMAN_AUTHORED_CANDIDATES
    )
    records = tuple(sorted(benchmark_records + test_records + future_records, key=lambda item: item.example_id))
    validate_candidate_examples(records)
    return records, dispositions


def write_stage3a_artifacts(
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root)
    records, dispositions = build_stage3a_candidates(root / BENCHMARK_SOURCE)
    candidate_path = root / CANDIDATE_FILE
    candidate_path.write_text(
        "".join(
            json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    export_human_review_csv(records, root / REVIEW_FILE)
    metadata = build_index_metadata(
        records,
        source_scenario_dispositions=dispositions,
    )
    (root / METADATA_FILE).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


_APPROVED_REVIEW_NOTE = (
    "Researcher-confirmed assisted review: proposed semantic label, source "
    "scope, context requirement, index eligibility and paraphrase family accepted."
)

_RESEARCHER_CONFIRMED_REVISIONS: dict[str, dict[str, str]] = {
    "IE-BENCH-U042": {
        "human_corrected_semantic_label": "course_content_question",
        "human_notes": (
            "Researcher-confirmed assisted review: the query asks for Week 4 "
            "readings and is semantically a course-content lookup. The operational "
            "benchmark label dashboard_interpretation is not reused as the semantic intent."
        ),
    },
    "IE-BENCH-U043": {
        "human_corrected_semantic_label": "course_content_question",
        "human_corrected_paraphrase_family_id": "PF-COURSE-SESSION-LINK-001",
        "human_notes": (
            "Researcher-confirmed assisted review: locating a Week 5 live-session "
            "link is a course-content or course-navigation lookup rather than a "
            "cross-page relationship request."
        ),
    },
    "IE-BENCH-U044": {
        "human_corrected_semantic_label": "course_content_question",
        "human_corrected_paraphrase_family_id": "PF-COURSE-ASSESSMENT-TASK-001",
        "human_notes": (
            "Researcher-confirmed assisted review: asking what assessment Part A "
            "requires is a course or assessment content question rather than "
            "dashboard interpretation."
        ),
    },
    "IE-BENCH-U047": {
        "human_corrected_semantic_label": "course_content_question",
        "human_notes": (
            "Researcher-confirmed assisted review: asking which reference explains "
            "individual reflection is a course-resource lookup rather than "
            "dashboard interpretation."
        ),
    },
    "IE-BENCH-U055": {
        "human_corrected_semantic_label": "cross_page_relationship",
        "human_corrected_paraphrase_family_id": "PF-CROSS-PAGE-RELATIONSHIP-001",
        "human_notes": (
            "Researcher-confirmed assisted review: the query explicitly asks how "
            "lecture-video activity connects to debate preparation, so its semantic "
            "intent is cross-page relationship."
        ),
    },
}


def compute_file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apply_completed_review(
    pending_review_path: str | Path,
    completed_review_path: str | Path,
) -> tuple[dict[str, str], ...]:
    """Apply only the explicitly researcher-confirmed Stage-3B decisions."""

    pending_path = Path(pending_review_path)
    completed_path = Path(completed_review_path)
    if pending_path.resolve() == completed_path.resolve():
        raise ValueError("Completed review must not overwrite the pending review file")
    before_hash = compute_file_sha256(pending_path)
    rows = [dict(row) for row in load_human_review_csv(pending_path)]
    if len(rows) != 79 or len({row["example_id"] for row in rows}) != 79:
        raise ValueError("Pending review must contain exactly 79 unique examples")
    for row in rows:
        if row["index_review_status"] != "pending":
            raise ValueError("Original review contains a non-pending record")
        if any(row[name] for name in _PENDING_HUMAN_FIELDS):
            raise ValueError("Original pending review already contains human decisions")
        row["index_review_status"] = "approved"
        row["human_decision"] = "approved"
        row["human_notes"] = _APPROVED_REVIEW_NOTE
        revision = _RESEARCHER_CONFIRMED_REVISIONS.get(row["example_id"])
        if revision:
            row["human_decision"] = "revised"
            row.update(revision)
    with completed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HUMAN_REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {column: row.get(column, "") for column in HUMAN_REVIEW_COLUMNS}
            for row in rows
        )
    if compute_file_sha256(pending_path) != before_hash:
        raise RuntimeError("Original pending review changed during completed-review build")
    return tuple(rows)


def _validate_corrected_fields(row: Mapping[str, str]) -> None:
    label = row["human_corrected_semantic_label"]
    scope = row["human_corrected_source_scope"]
    context = row["human_corrected_context_requirement"]
    eligibility = row["human_corrected_index_eligibility"]
    family = row["human_corrected_paraphrase_family_id"]
    if label and label not in SEMANTIC_INTENT_LABELS:
        raise ValueError("Invalid corrected semantic label")
    if scope and scope not in SOURCE_SCOPE_LABELS:
        raise ValueError("Invalid corrected source scope")
    if context and context not in CONTEXT_REQUIREMENTS:
        raise ValueError("Invalid corrected context requirement")
    if eligibility not in {"", "true", "false"}:
        raise ValueError("Invalid corrected index eligibility")
    if family and not re.fullmatch(r"PF-[A-Z0-9-]+", family):
        raise ValueError("Invalid corrected paraphrase family ID")


def validate_completed_review(
    candidate_records: Sequence[IntentExampleRecord],
    completed_rows: Sequence[Mapping[str, str]],
) -> None:
    candidates = {record.example_id: record for record in candidate_records}
    if len(candidates) != len(candidate_records):
        raise ValueError("Candidate records contain duplicate IDs")
    row_ids = [str(row.get("example_id") or "") for row in completed_rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("Completed review contains duplicate IDs")
    if set(row_ids) != set(candidates):
        missing = sorted(set(candidates) - set(row_ids))
        extra = sorted(set(row_ids) - set(candidates))
        raise ValueError(f"Completed review ID mismatch; missing={missing}, extra={extra}")
    if len(completed_rows) != 79:
        raise ValueError("Completed review must contain exactly 79 records")
    immutable_columns = (
        "query",
        "page_context",
        "semantic_label_proposed",
        "source_scope_proposed",
        "context_requirement",
        "exclusion_reason",
        "paraphrase_family_id",
        "provenance_type",
        "source_path",
        "source_record_id",
        "source_review_status",
        "intended_partition",
    )
    for row in completed_rows:
        record = candidates[str(row["example_id"])]
        expected = record.to_dict()
        expected["index_eligibility_proposed"] = (
            "true" if record.index_eligibility_proposed else "false"
        )
        for column in immutable_columns + ("index_eligibility_proposed",):
            if str(row.get(column) or "") != str(expected[column]):
                raise ValueError(
                    f"Completed review modified immutable field {column} for {record.example_id}"
                )
        decision = str(row.get("human_decision") or "")
        if decision not in {"approved", "revised", "rejected"}:
            raise ValueError("Completed review contains an invalid decision")
        expected_status = "rejected" if decision == "rejected" else "approved"
        if row.get("index_review_status") != expected_status:
            raise ValueError("Index review status conflicts with human decision")
        _validate_corrected_fields(row)
        corrected = [str(row.get(name) or "") for name in (
            "human_corrected_semantic_label",
            "human_corrected_source_scope",
            "human_corrected_context_requirement",
            "human_corrected_index_eligibility",
            "human_corrected_paraphrase_family_id",
        )]
        if decision == "approved" and any(corrected):
            raise ValueError("Approved records cannot contain corrected fields")
        if decision == "revised":
            effective_changes = (
                bool(row.get("human_corrected_semantic_label"))
                and row["human_corrected_semantic_label"] != record.semantic_label_proposed,
                bool(row.get("human_corrected_source_scope"))
                and row["human_corrected_source_scope"] != record.source_scope_proposed,
                bool(row.get("human_corrected_context_requirement"))
                and row["human_corrected_context_requirement"] != record.context_requirement,
                bool(row.get("human_corrected_index_eligibility"))
                and row["human_corrected_index_eligibility"]
                != str(record.index_eligibility_proposed).lower(),
                bool(row.get("human_corrected_paraphrase_family_id"))
                and row["human_corrected_paraphrase_family_id"]
                != record.paraphrase_family_id,
            )
            if not any(effective_changes):
                raise ValueError("Revised records require at least one effective correction")
        if not str(row.get("human_notes") or "").strip():
            raise ValueError("Every completed review decision requires notes")


@dataclass(frozen=True)
class ReviewedIntentExample:
    example_id: str
    query: str
    final_semantic_label: str
    final_legacy_query_type: str | None
    final_source_scope: str
    final_context_requirement: str
    final_index_eligibility: bool
    final_paraphrase_family_id: str
    final_partition: str
    page_context: str
    slot_hints: Mapping[str, object]
    provenance_type: str
    source_path: str
    source_record_id: str
    review_decision: str
    review_source: str = REVIEW_SOURCE
    intent_schema_version: str = INTENT_SCHEMA_VERSION
    intent_example_schema_version: str = INTENT_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.final_semantic_label not in SEMANTIC_INTENT_LABELS:
            raise ValueError("Invalid final semantic label")
        if self.final_legacy_query_type is not None and self.final_legacy_query_type not in LEGACY_QUERY_TYPES:
            raise ValueError("Invalid final legacy query type")
        if self.final_semantic_label in LEGACY_QUERY_TYPES:
            if self.final_legacy_query_type != self.final_semantic_label:
                raise ValueError("Final legacy type must follow a corrected legacy semantic label")
        elif self.final_legacy_query_type is not None:
            raise ValueError("Future semantic outcomes cannot have a final legacy type")
        if self.final_source_scope not in SOURCE_SCOPE_LABELS:
            raise ValueError("Invalid final source scope")
        if self.final_context_requirement not in CONTEXT_REQUIREMENTS:
            raise ValueError("Invalid final context requirement")
        if self.review_decision not in {"approved", "revised", "rejected"}:
            raise ValueError("Invalid review decision")
        if self.review_source != REVIEW_SOURCE:
            raise ValueError("Invalid review source")
        if self.final_partition not in INTENDED_PARTITIONS:
            raise ValueError("Invalid final partition")
        object.__setattr__(self, "slot_hints", _json_safe_slot_hints(self.slot_hints))


def resolve_reviewed_example(
    record: IntentExampleRecord,
    completed_row: Mapping[str, str],
) -> ReviewedIntentExample:
    if completed_row.get("example_id") != record.example_id:
        raise ValueError("Review row does not match candidate record")
    decision = str(completed_row.get("human_decision") or "")
    final_label = str(
        completed_row.get("human_corrected_semantic_label")
        or record.semantic_label_proposed
    )
    final_scope = str(
        completed_row.get("human_corrected_source_scope")
        or record.source_scope_proposed
    )
    final_context = str(
        completed_row.get("human_corrected_context_requirement")
        or record.context_requirement
    )
    eligibility_text = str(completed_row.get("human_corrected_index_eligibility") or "")
    final_eligibility = (
        eligibility_text == "true" if eligibility_text else record.index_eligibility_proposed
    )
    final_family = str(
        completed_row.get("human_corrected_paraphrase_family_id")
        or record.paraphrase_family_id
    )
    final_partition = record.intended_partition
    if decision == "rejected":
        final_eligibility = False
        final_partition = "excluded"
    if final_context in {"conversation_history", "memory_resolution"}:
        final_eligibility = False
        final_partition = "diagnostic_only"
    final_legacy = final_label if final_label in LEGACY_QUERY_TYPES else None
    return ReviewedIntentExample(
        example_id=record.example_id,
        query=record.query,
        final_semantic_label=final_label,
        final_legacy_query_type=final_legacy,
        final_source_scope=final_scope,
        final_context_requirement=final_context,
        final_index_eligibility=final_eligibility,
        final_paraphrase_family_id=final_family,
        final_partition=final_partition,
        page_context=record.page_context,
        slot_hints=record.slot_hints,
        provenance_type=record.provenance_type,
        source_path=record.source_path,
        source_record_id=record.source_record_id,
        review_decision=decision,
    )


def _canonical_page(page_context: str) -> str:
    lookup = {page.casefold(): page for page in CANONICAL_PAGES}
    canonical = lookup.get(str(page_context).strip().casefold())
    if canonical is None:
        raise ValueError(f"Current-page example has an invalid page: {page_context!r}")
    return canonical


def build_retrieval_text(record: ReviewedIntentExample) -> str:
    if record.final_context_requirement == "query_only":
        return record.query
    if record.final_context_requirement == "current_page":
        return f"[PAGE={_canonical_page(record.page_context)}] {record.query}"
    if record.final_context_requirement == "multi_source_context":
        if record.final_source_scope != "hybrid":
            raise ValueError("Multi-source examples require a final hybrid scope")
        return record.query
    raise ValueError("Diagnostic context cannot produce first-index retrieval text")


@dataclass(frozen=True)
class ApprovedIntentExample:
    example_id: str
    query: str
    retrieval_text: str
    final_semantic_label: str
    final_legacy_query_type: str | None
    final_source_scope: str
    final_context_requirement: str
    final_paraphrase_family_id: str
    page_context: str
    slot_hints: Mapping[str, object]
    provenance_type: str
    source_path: str
    source_record_id: str
    review_decision: str
    review_source: str = REVIEW_SOURCE
    intended_partition: str = "development_candidate"
    retrieval_text_version: str = RETRIEVAL_TEXT_VERSION
    intent_schema_version: str = INTENT_SCHEMA_VERSION
    intent_example_schema_version: str = INTENT_EXAMPLE_SCHEMA_VERSION
    approved_index_version: str = APPROVED_INDEX_VERSION

    def __post_init__(self) -> None:
        _validate_non_empty("example_id", self.example_id)
        _validate_non_empty("query", self.query)
        _validate_non_empty("retrieval_text", self.retrieval_text)
        if self.final_semantic_label not in SEMANTIC_INTENT_LABELS:
            raise ValueError("Invalid approved semantic label")
        if self.final_semantic_label in LEGACY_QUERY_TYPES:
            if self.final_legacy_query_type != self.final_semantic_label:
                raise ValueError("Approved legacy label/type mismatch")
        elif self.final_legacy_query_type is not None:
            raise ValueError("Approved future outcome has a legacy query type")
        if self.final_source_scope not in SOURCE_SCOPE_LABELS:
            raise ValueError("Invalid approved source scope")
        if self.final_source_scope == "undetermined":
            raise ValueError("Undetermined source scope cannot enter the approved index")
        if self.final_source_scope == "no_supported_source" and self.final_semantic_label in LEGACY_QUERY_TYPES:
            raise ValueError("Legacy task intents cannot use no_supported_source")
        if self.final_context_requirement not in {
            "query_only",
            "current_page",
            "multi_source_context",
        }:
            raise ValueError("Diagnostic context leaked into the approved index")
        if self.final_context_requirement == "current_page":
            expected = f"[PAGE={_canonical_page(self.page_context)}] {self.query}"
            if self.retrieval_text != expected:
                raise ValueError("Current-page retrieval text is not page-prefixed")
        elif self.retrieval_text != self.query:
            raise ValueError("Non-page retrieval text must equal the original query")
        if self.final_context_requirement == "multi_source_context" and self.final_source_scope != "hybrid":
            raise ValueError("Multi-source index records require hybrid scope")
        if self.intended_partition != "development_candidate":
            raise ValueError("Only development candidates can enter the approved index")
        if self.review_decision not in {"approved", "revised"}:
            raise ValueError("Only approved/revised decisions can enter the index")
        if self.review_source != REVIEW_SOURCE:
            raise ValueError("Invalid approved-index review source")
        if self.retrieval_text_version != RETRIEVAL_TEXT_VERSION:
            raise ValueError("Invalid retrieval-text version")
        if self.approved_index_version != APPROVED_INDEX_VERSION:
            raise ValueError("Invalid approved-index version")
        object.__setattr__(self, "slot_hints", _json_safe_slot_hints(self.slot_hints))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ApprovedIntentExample":
        return cls(**dict(payload))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "query": self.query,
            "retrieval_text": self.retrieval_text,
            "final_semantic_label": self.final_semantic_label,
            "final_legacy_query_type": self.final_legacy_query_type,
            "final_source_scope": self.final_source_scope,
            "final_context_requirement": self.final_context_requirement,
            "final_paraphrase_family_id": self.final_paraphrase_family_id,
            "page_context": self.page_context,
            "slot_hints": dict(self.slot_hints),
            "provenance_type": self.provenance_type,
            "source_path": self.source_path,
            "source_record_id": self.source_record_id,
            "review_decision": self.review_decision,
            "review_source": self.review_source,
            "intended_partition": self.intended_partition,
            "retrieval_text_version": self.retrieval_text_version,
            "intent_schema_version": self.intent_schema_version,
            "intent_example_schema_version": self.intent_example_schema_version,
            "approved_index_version": self.approved_index_version,
        }


def build_approved_index(
    reviewed_records: Iterable[ReviewedIntentExample],
) -> tuple[ApprovedIntentExample, ...]:
    approved: list[ApprovedIntentExample] = []
    for record in reviewed_records:
        if record.review_decision not in {"approved", "revised"}:
            continue
        if not record.final_index_eligibility:
            continue
        if record.final_partition != "development_candidate":
            continue
        if record.final_context_requirement in {"conversation_history", "memory_resolution"}:
            continue
        if record.final_source_scope == "undetermined":
            continue
        if record.final_context_requirement == "multi_source_context" and record.final_source_scope != "hybrid":
            continue
        approved.append(
            ApprovedIntentExample(
                example_id=record.example_id,
                query=record.query,
                retrieval_text=build_retrieval_text(record),
                final_semantic_label=record.final_semantic_label,
                final_legacy_query_type=record.final_legacy_query_type,
                final_source_scope=record.final_source_scope,
                final_context_requirement=record.final_context_requirement,
                final_paraphrase_family_id=record.final_paraphrase_family_id,
                page_context=record.page_context,
                slot_hints=record.slot_hints,
                provenance_type=record.provenance_type,
                source_path=record.source_path,
                source_record_id=record.source_record_id,
                review_decision=record.review_decision,
            )
        )
    result = tuple(sorted(approved, key=lambda item: item.example_id))
    validate_approved_index(result)
    return result


def _approved_index_findings(
    records: Sequence[ApprovedIntentExample],
) -> dict[str, Any]:
    ids = [record.example_id for record in records]
    retrieval_texts = [record.retrieval_text for record in records]
    normalised = [normalise_example_query(text) for text in retrieval_texts]
    label_conflicts = 0
    by_text: dict[str, list[ApprovedIntentExample]] = defaultdict(list)
    for record, key in zip(records, normalised):
        by_text[key].append(record)
    for items in by_text.values():
        if len({item.final_semantic_label for item in items}) > 1 or len(
            {item.final_source_scope for item in items}
        ) > 1:
            label_conflicts += 1
    family_conflicts = 0
    by_family: dict[str, list[ApprovedIntentExample]] = defaultdict(list)
    for record in records:
        by_family[record.final_paraphrase_family_id].append(record)
    for items in by_family.values():
        if any(
            len(values) > 1
            for values in (
                {item.final_semantic_label for item in items},
                {item.final_source_scope for item in items},
                {item.final_context_requirement for item in items},
                {item.intended_partition for item in items},
            )
        ):
            family_conflicts += 1
    partition_leakage = sum(
        record.intended_partition != "development_candidate" for record in records
    )
    context_leakage = sum(
        record.final_context_requirement in {"conversation_history", "memory_resolution"}
        or (
            record.final_context_requirement == "current_page"
            and not record.retrieval_text.startswith("[PAGE=")
        )
        for record in records
    )
    forbidden_keys = {
        "student_id",
        "dashboard_data",
        "conversation_history",
        "assistant_response",
        "gold_expected_answer",
        "rag_chunk_text",
        "retrieved_course_evidence",
        "predicted_query_type",
        "deterministic_query_type",
        "embedding",
        "similarity_score",
        "candidate_ranking",
        "llm_output",
    }
    sensitive_leakage = sum(
        bool(forbidden_keys.intersection(record.to_dict())) for record in records
    )
    return {
        "duplicate_example_id_count": len(ids) - len(set(ids)),
        "duplicate_retrieval_text_count": len(retrieval_texts) - len(set(retrieval_texts)),
        "duplicate_normalised_retrieval_text_count": len(normalised) - len(set(normalised)),
        "label_conflict_count": label_conflicts,
        "family_conflict_count": family_conflicts,
        "partition_leakage_count": partition_leakage,
        "context_leakage_count": context_leakage,
        "sensitive_field_leakage_count": sensitive_leakage,
    }


def validate_approved_index(records: Sequence[ApprovedIntentExample]) -> dict[str, Any]:
    findings = _approved_index_findings(records)
    if any(findings.values()):
        raise ValueError(f"Approved-index validation failed: {findings}")
    if list(records) != sorted(records, key=lambda item: item.example_id):
        raise ValueError("Approved index is not stably sorted by example_id")
    return findings


def _serialise_approved_index(records: Sequence[ApprovedIntentExample]) -> bytes:
    validate_approved_index(records)
    return "".join(
        json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")


def load_approved_index(path: str | Path) -> tuple[ApprovedIntentExample, ...]:
    records = tuple(
        ApprovedIntentExample.from_dict(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    validate_approved_index(records)
    return records


def build_approved_metadata(
    *,
    completed_rows: Sequence[Mapping[str, str]],
    reviewed_records: Sequence[ReviewedIntentExample],
    approved_records: Sequence[ApprovedIntentExample],
    original_pending_review_sha256: str,
    completed_review_sha256: str,
    candidate_file_sha256: str,
    approved_index_sha256: str,
    deterministic_rebuild_match: bool,
    created_at: str = STAGE3B_FREEZE_TIMESTAMP,
) -> dict[str, Any]:
    findings = validate_approved_index(approved_records)
    families: dict[str, list[ApprovedIntentExample]] = defaultdict(list)
    for record in approved_records:
        families[record.final_paraphrase_family_id].append(record)
    decision_counts = Counter(str(row["human_decision"]) for row in completed_rows)
    excluded_contexts = Counter(
        record.final_context_requirement
        for record in reviewed_records
        if record.example_id not in {item.example_id for item in approved_records}
    )
    future_labels = ("social_interaction", "unsupported_task", "out_of_scope", "ambiguous")
    return {
        "approved_index_version": APPROVED_INDEX_VERSION,
        "retrieval_text_version": RETRIEVAL_TEXT_VERSION,
        "intent_schema_version": INTENT_SCHEMA_VERSION,
        "intent_example_schema_version": INTENT_EXAMPLE_SCHEMA_VERSION,
        "review_source": REVIEW_SOURCE,
        "review_decision_source": "Researcher-confirmed assisted review",
        "original_pending_review_file": REVIEW_FILE,
        "original_pending_review_sha256": original_pending_review_sha256,
        "completed_review_file": COMPLETED_REVIEW_FILE,
        "completed_review_sha256": completed_review_sha256,
        "candidate_file": CANDIDATE_FILE,
        "candidate_file_sha256": candidate_file_sha256,
        "approved_index_file": APPROVED_INDEX_FILE,
        "approved_index_sha256": approved_index_sha256,
        "total_candidates": len(completed_rows),
        "approved_decisions": decision_counts.get("approved", 0),
        "revised_decisions": decision_counts.get("revised", 0),
        "rejected_decisions": decision_counts.get("rejected", 0),
        "final_index_count": len(approved_records),
        "excluded_from_index_count": len(reviewed_records) - len(approved_records),
        "counts_by_final_semantic_label": _counter(
            record.final_semantic_label for record in approved_records
        ),
        "counts_by_final_source_scope": _counter(
            record.final_source_scope for record in approved_records
        ),
        "counts_by_final_context_requirement": _counter(
            record.final_context_requirement for record in approved_records
        ),
        "counts_by_review_decision": dict(sorted(decision_counts.items())),
        "counts_by_provenance": _counter(
            record.provenance_type for record in approved_records
        ),
        "counts_by_page_context": _counter(
            record.page_context or "<none>" for record in approved_records
        ),
        "excluded_counts_by_context_requirement": dict(sorted(excluded_contexts.items())),
        "multi_source_context_included_count": sum(
            record.final_context_requirement == "multi_source_context"
            for record in approved_records
        ),
        "multi_source_context_excluded_count": excluded_contexts.get(
            "multi_source_context", 0
        ),
        "approved_future_outcomes_by_category": {
            label: sum(record.final_semantic_label == label for record in approved_records)
            for label in future_labels
        },
        "paraphrase_family_count": len(families),
        "singleton_family_count": sum(len(items) == 1 for items in families.values()),
        **findings,
        "deterministic_rebuild_hash_match": deterministic_rebuild_match,
        "deterministic_classifier_labels_used": 0,
        "embedding_model": None,
        "semantic_retrieval_enabled": False,
        "production_integration_enabled": False,
        "development_data_warning": (
            "The approved index was derived partly from the existing unified "
            "benchmark and must not be reused as the primary held-out "
            "semantic-routing evaluation set."
        ),
        "created_at": created_at,
    }


def build_review_audit(
    *,
    completed_rows: Sequence[Mapping[str, str]],
    original_file_sha256_before: str,
    original_file_sha256_after: str,
    index_freeze_timestamp: str = STAGE3B_FREEZE_TIMESTAMP,
) -> dict[str, Any]:
    decisions = Counter(str(row["human_decision"]) for row in completed_rows)
    revised_rows = sorted(
        (row for row in completed_rows if row["human_decision"] == "revised"),
        key=lambda row: row["example_id"],
    )
    corrected_names = (
        "human_corrected_semantic_label",
        "human_corrected_source_scope",
        "human_corrected_context_requirement",
        "human_corrected_index_eligibility",
        "human_corrected_paraphrase_family_id",
    )
    return {
        "review_method": REVIEW_SOURCE,
        "review_decision_source": "Researcher-confirmed assisted review",
        "researcher_confirmation_status": "confirmed",
        "assistant_assistance_used": True,
        "independent_second_rater": False,
        "inter_rater_agreement_available": False,
        "total_records": len(completed_rows),
        "approved": decisions.get("approved", 0),
        "revised": decisions.get("revised", 0),
        "rejected": decisions.get("rejected", 0),
        "revised_record_ids": [row["example_id"] for row in revised_rows],
        "revised_fields_by_record": {
            row["example_id"]: [name for name in corrected_names if row.get(name)]
            for row in revised_rows
        },
        "original_file_preserved": (
            original_file_sha256_before == original_file_sha256_after
        ),
        "original_file_sha256_before": original_file_sha256_before,
        "original_file_sha256_after": original_file_sha256_after,
        "decision_timestamp": None,
        "index_freeze_timestamp": index_freeze_timestamp,
        "notes": (
            "The candidate annotations were reviewed with AI assistance and "
            "subsequently confirmed by the researcher before index freezing. "
            "This was not an independent second-rater or inter-rater agreement study."
        ),
    }


def freeze_approved_index(
    *,
    candidate_path: str | Path,
    pending_review_path: str | Path,
    completed_review_path: str | Path,
    approved_index_path: str | Path,
    approved_index_sha256_path: str | Path,
    approved_metadata_path: str | Path,
    review_audit_path: str | Path,
    freeze_timestamp: str = STAGE3B_FREEZE_TIMESTAMP,
) -> dict[str, Any]:
    """Explicitly freeze the confirmed review; imports never trigger writes."""

    candidate_path = Path(candidate_path)
    pending_review_path = Path(pending_review_path)
    completed_review_path = Path(completed_review_path)
    approved_index_path = Path(approved_index_path)
    approved_index_sha256_path = Path(approved_index_sha256_path)
    approved_metadata_path = Path(approved_metadata_path)
    review_audit_path = Path(review_audit_path)

    pending_before = compute_file_sha256(pending_review_path)
    candidate_before = compute_file_sha256(candidate_path)
    candidate_records = load_candidate_examples(candidate_path)
    apply_completed_review(pending_review_path, completed_review_path)
    completed_rows = load_human_review_csv(completed_review_path)
    validate_completed_review(candidate_records, completed_rows)
    decision_counts = Counter(row["human_decision"] for row in completed_rows)
    revised_ids = {
        row["example_id"]
        for row in completed_rows
        if row["human_decision"] == "revised"
    }
    if decision_counts != Counter({"approved": 74, "revised": 5}):
        raise ValueError(f"Unexpected confirmed decision counts: {decision_counts}")
    if revised_ids != set(_RESEARCHER_CONFIRMED_REVISIONS):
        raise ValueError("Completed review does not contain the five confirmed revisions")
    rows_by_id = {row["example_id"]: row for row in completed_rows}
    reviewed_records = tuple(
        resolve_reviewed_example(record, rows_by_id[record.example_id])
        for record in candidate_records
    )
    approved_records = build_approved_index(reviewed_records)
    first_bytes = _serialise_approved_index(approved_records)
    second_bytes = _serialise_approved_index(tuple(approved_records))
    first_hash = hashlib.sha256(first_bytes).hexdigest()
    second_hash = hashlib.sha256(second_bytes).hexdigest()
    if first_bytes != second_bytes or first_hash != second_hash:
        raise RuntimeError("Approved index is not deterministic across rebuilds")
    approved_index_path.write_bytes(first_bytes)
    if compute_file_sha256(approved_index_path) != first_hash:
        raise RuntimeError("Written approved-index hash does not match serialized bytes")
    approved_index_sha256_path.write_text(
        f"{first_hash}  {approved_index_path.name}\n",
        encoding="utf-8",
    )
    pending_after = compute_file_sha256(pending_review_path)
    candidate_after = compute_file_sha256(candidate_path)
    if pending_before != pending_after:
        raise RuntimeError("Original pending review was modified")
    if candidate_before != candidate_after:
        raise RuntimeError("Stage-3A candidate file was modified")
    completed_hash = compute_file_sha256(completed_review_path)
    metadata = build_approved_metadata(
        completed_rows=completed_rows,
        reviewed_records=reviewed_records,
        approved_records=approved_records,
        original_pending_review_sha256=pending_before,
        completed_review_sha256=completed_hash,
        candidate_file_sha256=candidate_before,
        approved_index_sha256=first_hash,
        deterministic_rebuild_match=(first_hash == second_hash),
        created_at=freeze_timestamp,
    )
    audit = build_review_audit(
        completed_rows=completed_rows,
        original_file_sha256_before=pending_before,
        original_file_sha256_after=pending_after,
        index_freeze_timestamp=freeze_timestamp,
    )
    approved_metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    review_audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "metadata": metadata,
        "audit": audit,
        "approved_records": approved_records,
        "reviewed_records": reviewed_records,
    }
