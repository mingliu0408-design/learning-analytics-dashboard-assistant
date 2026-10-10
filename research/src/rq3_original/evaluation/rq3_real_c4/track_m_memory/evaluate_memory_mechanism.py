"""Run the offline RQ3-REAL-C4 Track M Memory-mechanism evaluation.

This script performs no response generation, provider/Judge call, P3 call, or
final RQ3 scoring.  It uses synthetic learners, deterministic mock write
candidates, one SQLite database per scenario, and optional hash-verified local
MPNet retrieval.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import socket
import statistics
import sys
import tempfile
from time import perf_counter
from typing import Any, Iterator, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.build_unified_benchmark import additional_scenarios  # noqa: E402
from utils.c4_memory.c4_memory_provider import C4LearnerMemoryProvider  # noqa: E402
from utils.c4_memory.c4_memory_retriever import (  # noqa: E402
    FrozenLocalMPNetBackend,
    discover_local_mpnet_path,
)
from utils.c4_memory.c4_memory_store import C4MemoryStore, sha256_object  # noqa: E402
from utils.c4_memory.c4_memory_writer import StructuredMemoryCandidate  # noqa: E402


TRACK_DIR = Path(__file__).resolve().parent
FIXTURE_PATH = TRACK_DIR / "historical_replay_cases_v1.json"
AUDIT_PATH = TRACK_DIR / "historical_memory_scenario_audit_v1.csv"
RESULTS_PATH = TRACK_DIR / "memory_mechanism_results_v1.json"
GAP_PATH = TRACK_DIR / "persistent_memory_gap_registry_v1.csv"
REPORT_PATH = TRACK_DIR / "REAL_C4_MEMORY_RESULTS.md"
STATUS_PATH = TRACK_DIR / "STATUS.md"
RQ2_COMMITMENT_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "capability_routing_rq2c0_r2_v1"
    / "controlled_mechanism_fixture_semantic_commitment_v1.jsonl"
)
QUERY_TIME = "2026-09-01T12:00:00+00:00"


class NetworkAccessAttempt(RuntimeError):
    pass


@dataclass
class NetworkGuard:
    attempts: int = 0

    def blocked_operation(self, *args: Any, **kwargs: Any) -> None:
        self.attempts += 1
        raise NetworkAccessAttempt("NETWORK_ACCESS_BLOCKED_IN_TRACK_M")


@contextmanager
def deny_network() -> Iterator[NetworkGuard]:
    guard = NetworkGuard()
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    class GuardedSocket(original_socket):  # type: ignore[misc, valid-type]
        def connect(self, *args: Any, **kwargs: Any) -> None:
            guard.blocked_operation(*args, **kwargs)

        def connect_ex(self, *args: Any, **kwargs: Any) -> int:
            guard.blocked_operation(*args, **kwargs)
            return 1

    # Keep socket.socket as a class so libraries that use it in isinstance()
    # checks continue to work.  Only DNS and outbound connection operations are
    # denied; local tensor/model work remains unaffected.
    socket.socket = GuardedSocket  # type: ignore[assignment]
    socket.create_connection = guard.blocked_operation  # type: ignore[assignment]
    socket.getaddrinfo = guard.blocked_operation  # type: ignore[assignment]
    try:
        yield guard
    finally:
        socket.socket = original_socket  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metric(value: float, numerator: float, denominator: int, definition: str) -> dict[str, Any]:
    return {
        "value": round(float(value), 6),
        "numerator": round(float(numerator), 6),
        "denominator": int(denominator),
        "definition": definition,
    }


def safe_rate(numerator: float, denominator: int) -> float:
    return float(numerator) / denominator if denominator else 0.0


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


def resolve_candidate(candidate: Mapping[str, Any], aliases: Mapping[str, str | None]) -> dict[str, Any]:
    value = dict(candidate)
    target = value.get("target_memory_id")
    if isinstance(target, str) and target.startswith("@"):
        alias = target[1:]
        resolved = aliases.get(alias)
        if not resolved:
            raise RuntimeError(f"UNRESOLVED_TARGET_ALIAS:{alias}")
        value["target_memory_id"] = resolved
    return value


def run_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    semantic_backend: Any,
    temporary_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    write_correct = 0
    write_total = 0
    relevant_scenarios = 0
    recall_hits = {1: 0.0, 3: 0.0, 5: 0.0}
    exact_target_hits = 0
    selected_total = 0
    wrong_selected = 0
    other_learner_selected = 0
    stale_selected = 0
    visible_duplicate_selected = 0
    abstention_correct = 0
    abstention_total = 0
    update_correct = 0
    update_total = 0
    persistence_correct = 0
    persistence_total = 0
    semantic_only_target_hits = 0
    latency_ms: list[float] = []
    operation_coverage: set[str] = set()
    scenario_results: list[dict[str, Any]] = []

    for case in cases:
        scenario_id = str(case["scenario_id"])
        database_path = temporary_root / f"{scenario_id.lower()}.sqlite"
        aliases: dict[str, str | None] = {}
        alias_students: dict[str, str] = {}
        write_rows: list[dict[str, Any]] = []
        primary_student = str(case["student_id"])
        store = C4MemoryStore(database_path, clock=lambda: QUERY_TIME)
        provider = C4LearnerMemoryProvider(
            store,
            semantic_backend=semantic_backend,
            clock=lambda: QUERY_TIME,
        )
        for index, write in enumerate(case.get("writes", []), 1):
            student_id = str(write.get("student_id_override") or primary_student)
            candidate_value = resolve_candidate(write["candidate"], aliases)
            result = provider.writer.apply_candidate(
                student_id=student_id,
                source_session_id=str(write["source_session_id"]),
                source_turn_id=str(write["source_turn_id"]),
                source_text=str(write["source_text"]),
                candidate=StructuredMemoryCandidate.from_mapping(candidate_value),
                source_role=str(write.get("source_role", "USER")),
                claim_basis=str(write.get("claim_basis", "EXPLICIT_USER_STATEMENT")),
                unrelated_sensitive_information=bool(write.get("unrelated_sensitive_information", False)),
                importance=float(write.get("importance", 0.5)),
                consent_status=str(write.get("consent_status", "GRANTED")),
                event_at=str(write["event_at"]),
                valid_from=write.get("valid_from"),
                valid_to=write.get("valid_to"),
            )
            alias = str(write["alias"])
            aliases[alias] = result.memory_id
            alias_students[alias] = student_id
            expected_operation = str(write["expected_applied_operation"])
            operation_match = result.applied_operation == expected_operation
            write_correct += int(operation_match)
            write_total += 1
            operation_coverage.add(result.applied_operation)
            write_rows.append(
                {
                    "write_index": index,
                    "alias": alias,
                    "requested_operation": result.requested_operation,
                    "expected_applied_operation": expected_operation,
                    "actual_applied_operation": result.applied_operation,
                    "operation_correct": operation_match,
                    "accepted": result.accepted,
                    "reason_code": result.reason_code,
                }
            )
        integrity_before = store.integrity_check()
        store.close()

        reopened = C4MemoryStore(database_path, clock=lambda: QUERY_TIME)
        reopened_provider = C4LearnerMemoryProvider(
            reopened,
            semantic_backend=semantic_backend,
            clock=lambda: QUERY_TIME,
        )
        for alias, memory_id in aliases.items():
            if memory_id is None:
                continue
            persistence_total += 1
            owner = alias_students[alias]
            persistence_correct += int(reopened.get_memory(owner, memory_id) is not None)

        status_expectations = dict(case.get("expected_statuses", {}))
        if status_expectations:
            update_total += 1
            all_correct = True
            for alias, expected_status in status_expectations.items():
                memory_id = aliases.get(alias)
                owner = alias_students.get(alias, primary_student)
                record = reopened.get_memory(owner, str(memory_id)) if memory_id else None
                if record is None or record.status != expected_status:
                    all_correct = False
            update_correct += int(all_correct)

        if case.get("policy_only"):
            scenario_results.append(
                {
                    "scenario_id": scenario_id,
                    "classification": case["classification"],
                    "store_reopened": True,
                    "write_results": write_rows,
                    "retrieval_status": "NOT_APPLICABLE_POLICY_ONLY",
                    "integrity_before_reopen": integrity_before,
                    "integrity_after_reopen": reopened.integrity_check(),
                }
            )
            reopened.close()
            continue

        started = perf_counter()
        envelope = reopened_provider.retrieve(
            primary_student,
            str(case["student_query"]),
            case.get("visible_history", []),
            top_k=5,
        )
        elapsed_ms = (perf_counter() - started) * 1000.0
        latency_ms.append(elapsed_ms)
        selected_items = list(envelope["selected_memory_items"])
        selected_ids = [str(item["memory_id"]) for item in selected_items]
        expected_ids = {
            str(aliases[alias])
            for alias in case.get("expected_target_aliases", [])
            if aliases.get(alias)
        }
        if expected_ids:
            relevant_scenarios += 1
            for k in (1, 3, 5):
                recall_hits[k] += len(expected_ids & set(selected_ids[:k])) / len(expected_ids)
            exact_target_hits += int(bool(selected_ids) and selected_ids[0] in expected_ids)
        if case.get("expect_no_match"):
            abstention_total += 1
            abstention_correct += int(envelope["status"] == "NO_MATCH" and not selected_ids)
        selected_total += len(selected_ids)
        wrong_selected += len([memory_id for memory_id in selected_ids if memory_id not in expected_ids])
        other_ids = {
            str(aliases[alias])
            for alias in case.get("other_learner_aliases", [])
            if aliases.get(alias)
        }
        other_learner_selected += len(set(selected_ids) & other_ids)
        stale_ids = {
            str(aliases[alias])
            for alias in case.get("stale_aliases", [])
            if aliases.get(alias)
        }
        stale_selected += len(set(selected_ids) & stale_ids)
        visible_text = "\n".join(
            str(item.get("content", "")) if isinstance(item, Mapping) else str(item)
            for item in case.get("visible_history", [])
        ).casefold()
        visible_duplicate_selected += sum(
            1 for item in selected_items if str(item["content"]).casefold() in visible_text
        )
        if expected_ids and selected_items:
            top = selected_items[0]
            components = top["relevance_components"]
            if top["memory_id"] in expected_ids and components["lexical"] == 0.0 and components["semantic_supported"]:
                semantic_only_target_hits += 1

        scenario_results.append(
            {
                "scenario_id": scenario_id,
                "source_reference": case["source_reference"],
                "classification": case["classification"],
                "store_reopened": True,
                "write_results": write_rows,
                "retrieval_status": envelope["status"],
                "selected_memory_ids": selected_ids,
                "expected_target_memory_ids": sorted(expected_ids),
                "top_1_correct": bool(expected_ids and selected_ids and selected_ids[0] in expected_ids),
                "latency_ms": round(elapsed_ms, 3),
                "visible_history_excluded_count": envelope["retrieval"]["visible_history_excluded_count"],
                "limitations": envelope["limitations"],
                "envelope_sha256": envelope["envelope_sha256"],
                "internal_embeddings_exposed": envelope["retrieval"]["embeddings_exposed"],
                "integrity_before_reopen": integrity_before,
                "integrity_after_reopen": reopened.integrity_check(),
            }
        )
        reopened.close()

    metrics = {
        "write_operation_accuracy": metric(
            safe_rate(write_correct, write_total),
            write_correct,
            write_total,
            "Exact expected versus applied ADD/UPDATE/SUPERSEDE/DELETE/NOOP operation over deterministic mock candidates.",
        ),
        "retrieval_recall_at_1": metric(
            safe_rate(recall_hits[1], relevant_scenarios),
            recall_hits[1],
            relevant_scenarios,
            "Macro Recall@1 over scenarios with one or more persistent target memories.",
        ),
        "retrieval_recall_at_3": metric(
            safe_rate(recall_hits[3], relevant_scenarios),
            recall_hits[3],
            relevant_scenarios,
            "Macro Recall@3 over scenarios with one or more persistent target memories.",
        ),
        "retrieval_recall_at_5": metric(
            safe_rate(recall_hits[5], relevant_scenarios),
            recall_hits[5],
            relevant_scenarios,
            "Macro Recall@5 over scenarios with one or more persistent target memories.",
        ),
        "exact_target_accuracy": metric(
            safe_rate(exact_target_hits, relevant_scenarios),
            exact_target_hits,
            relevant_scenarios,
            "Top-1 selected memory is an exact expected target.",
        ),
        "wrong_memory_rate": metric(
            safe_rate(wrong_selected, selected_total),
            wrong_selected,
            selected_total,
            "Selected memories outside the scenario's expected target set divided by all selected memories.",
        ),
        "cross_learner_leakage_rate": metric(
            safe_rate(other_learner_selected, selected_total),
            other_learner_selected,
            selected_total,
            "Selected memories belonging to another learner divided by all selected memories.",
        ),
        "update_supersession_accuracy": metric(
            safe_rate(update_correct, update_total),
            update_correct,
            update_total,
            "Cases where all expected ACTIVE/SUPERSEDED/DELETED version states were exact after reopen.",
        ),
        "stale_memory_rate": metric(
            safe_rate(stale_selected, selected_total),
            stale_selected,
            selected_total,
            "Expired, superseded, or deleted target memories selected divided by all selected memories.",
        ),
        "abstention_accuracy": metric(
            safe_rate(abstention_correct, abstention_total),
            abstention_correct,
            abstention_total,
            "NO_MATCH with zero selected items on no-relevant, visible-duplicate, expired, and deleted controls.",
        ),
        "visible_history_duplication_rate": metric(
            safe_rate(visible_duplicate_selected, selected_total),
            visible_duplicate_selected,
            selected_total,
            "Selected items already present in visible history divided by all selected memories.",
        ),
        "persistence_after_store_reopen_accuracy": metric(
            safe_rate(persistence_correct, persistence_total),
            persistence_correct,
            persistence_total,
            "Written memory identities found after closing and reopening each per-scenario SQLite store.",
        ),
        "semantic_only_target_hit_count": {
            "value": semantic_only_target_hits,
            "definition": "Correct top-1 targets with zero FTS lexical score and semantic support above threshold.",
        },
        "latency_ms": {
            "count": len(latency_ms),
            "mean": round(statistics.fmean(latency_ms), 3) if latency_ms else 0.0,
            "median": round(statistics.median(latency_ms), 3) if latency_ms else 0.0,
            "p95": round(percentile(latency_ms, 0.95), 3),
            "maximum": round(max(latency_ms), 3) if latency_ms else 0.0,
            "scope": "End-to-end local provider retrieval; first call includes local model load when configured.",
        },
        "operation_coverage": sorted(operation_coverage),
    }
    return metrics, scenario_results


def classification_for_fixture(category: str) -> str:
    upper = category.upper()
    if "SENSITIVE" in upper or "PRIVACY" in upper or "NO_RELEVANT" in upper:
        return "no-relevant-Memory control"
    if "CORRECTION" in upper or "LATEST" in upper:
        return "update/correction"
    if "SUPERSEDED" in upper or "STALE" in upper or "CANCELLED" in upper:
        return "superseded Memory"
    if "PLAN" in upper:
        return "active plan state"
    if "PREFERENCE" in upper:
        return "semantic profile"
    if "GOAL" in upper or "CONSTRAINT" in upper:
        return "cross-session episodic Memory"
    if "CROSS_SESSION" in upper or "MULTI_HOP" in upper:
        return "cross-session episodic Memory"
    if "WRITE" in upper:
        return "cross-session episodic Memory"
    return "no-relevant-Memory control"


AUDIT_COLUMNS = [
    "audit_id",
    "source_path",
    "source_record_id",
    "accessible",
    "payload_access",
    "historical_classification",
    "long_term_memory_applicable",
    "replayed_into_sqlite",
    "replay_status",
    "notes",
]


def build_audit(cases: Sequence[Mapping[str, Any]], scenario_results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result_ids = {str(row["scenario_id"]) for row in scenario_results}
    rows: list[dict[str, Any]] = [
        {
            "audit_id": "AUDIT-MISSING-MULTITURN",
            "source_path": "evaluation/multiturn_scenarios.jsonl",
            "source_record_id": "ALL",
            "accessible": False,
            "payload_access": "FILE_ABSENT_IN_ASSET_SPARSE_WORKTREE",
            "historical_classification": "same-session working Memory",
            "long_term_memory_applicable": False,
            "replayed_into_sqlite": False,
            "replay_status": "NOT_REPLAYED_SOURCE_MISSING",
            "notes": "Canonical short-term diagnostic file is absent; no substitute was copied or reconstructed.",
        },
        {
            "audit_id": "AUDIT-MISSING-UNIFIED",
            "source_path": "evaluation/unified_benchmark_scenarios.jsonl",
            "source_record_id": "memory_follow_up and hybrid_memory_and_retrieval",
            "accessible": False,
            "payload_access": "FILE_ABSENT_IN_ASSET_SPARSE_WORKTREE",
            "historical_classification": "visible-history only",
            "long_term_memory_applicable": False,
            "replayed_into_sqlite": False,
            "replay_status": "NOT_REPLAYED_SOURCE_MISSING",
            "notes": "The immutable 62-case unified JSONL is absent; accessible in-code H cases are audited separately.",
        },
    ]
    for item in additional_scenarios():
        scenario_id = str(item.get("source_scenario_id", ""))
        if not (item.get("expected_memory") or scenario_id == "H014"):
            continue
        classification = "no-relevant-Memory control" if scenario_id == "H014" else "visible-history only"
        rows.append(
            {
                "audit_id": f"AUDIT-UNIFIED-{scenario_id}",
                "source_path": "evaluation/build_unified_benchmark.py",
                "source_record_id": scenario_id,
                "accessible": True,
                "payload_access": "FULL_IN_CODE_SCENARIO",
                "historical_classification": classification,
                "long_term_memory_applicable": False,
                "replayed_into_sqlite": False,
                "replay_status": "NOT_APPLICABLE_VISIBLE_HISTORY_OR_SELF_CONTAINED",
                "notes": (
                    "Self-contained negative control with no Memory antecedent."
                    if scenario_id == "H014"
                    else "Numbered assistant content is already visible and remains short-term reference resolution, not persistent Memory."
                ),
            }
        )
    for case in cases:
        source = str(case["source_reference"])
        is_track_m_control = source.startswith("Track M")
        rows.append(
            {
                "audit_id": f"AUDIT-{case['scenario_id']}",
                "source_path": source.split(":", 1)[0],
                "source_record_id": str(case["scenario_id"]),
                "accessible": True,
                "payload_access": "SYNTHETIC_TEST_DERIVATION" if not is_track_m_control else "DETERMINISTIC_GAP_CONTROL",
                "historical_classification": str(case["classification"]),
                "long_term_memory_applicable": not bool(case.get("policy_only")),
                "replayed_into_sqlite": str(case["scenario_id"]) in result_ids,
                "replay_status": (
                    "POLICY_ONLY_NO_RETRIEVAL"
                    if case.get("policy_only")
                    else "REPLAYED_CLOSE_REOPEN_RETRIEVE"
                ),
                "notes": "Synthetic learner and deterministic candidate; no real student PII and no answer generation.",
            }
        )
    for row in load_jsonl(RQ2_COMMITMENT_PATH):
        category = str(row.get("fixture_category", ""))
        fixture_id = str(row.get("fixture_id", ""))
        rows.append(
            {
                "audit_id": f"AUDIT-RQ2-{fixture_id}",
                "source_path": str(RQ2_COMMITMENT_PATH.relative_to(PROJECT_ROOT)),
                "source_record_id": fixture_id,
                "accessible": True,
                "payload_access": "METADATA_ONLY_PRIVATE_PAYLOAD_EXCLUDED",
                "historical_classification": classification_for_fixture(category),
                "long_term_memory_applicable": category.startswith("PM_"),
                "replayed_into_sqlite": False,
                "replay_status": "NOT_REPLAYABLE_METADATA_ONLY",
                "notes": f"Fixture category {category}; commitment exposes hashes/counts but no learner text payload.",
            }
        )
    return rows


GAP_COLUMNS = [
    "gap_id",
    "category",
    "status",
    "evidence",
    "impact",
    "next_dataset_requirement",
]


def build_gaps() -> list[dict[str, str]]:
    return [
        {
            "gap_id": "GAP-001",
            "category": "canonical short-term scenarios",
            "status": "MISSING_SOURCE_FILE",
            "evidence": "evaluation/multiturn_scenarios.jsonl absent in this asset-sparse worktree",
            "impact": "Cannot enumerate or replay every original short-term diagnostic row",
            "next_dataset_requirement": "Provide the immutable file with provenance hash; do not reconstruct it",
        },
        {
            "gap_id": "GAP-002",
            "category": "unified benchmark Memory subset",
            "status": "MISSING_SOURCE_FILE",
            "evidence": "evaluation/unified_benchmark_scenarios.jsonl absent; only in-code H cases accessible",
            "impact": "Full memory_follow_up and hybrid subset coverage is unavailable",
            "next_dataset_requirement": "Provide immutable unified scenarios without response or Judge outputs",
        },
        {
            "gap_id": "GAP-003",
            "category": "RQ2 persistent fixture payloads",
            "status": "METADATA_ONLY",
            "evidence": "Semantic commitments expose fixture IDs, hashes, and categories but not private text",
            "impact": "Historical RQ2 persistent cases cannot be faithfully replayed into SQLite",
            "next_dataset_requirement": "Authorized de-identified payload package bound to existing commitment hashes",
        },
        {
            "gap_id": "GAP-004",
            "category": "longitudinal learner data",
            "status": "NOT_AVAILABLE",
            "evidence": "Track M uses synthetic learners only",
            "impact": "No claim about real-user frequency, learning outcome, or months-long persistence",
            "next_dataset_requirement": "Consented, de-identified multi-session longitudinal benchmark",
        },
        {
            "gap_id": "GAP-005",
            "category": "multilingual and code-switching Memory",
            "status": "NOT_COVERED",
            "evidence": "Replay cases are English",
            "impact": "Chinese/English cross-language retrieval robustness is unknown",
            "next_dataset_requirement": "Human-authored bilingual paraphrase and correction pairs",
        },
        {
            "gap_id": "GAP-006",
            "category": "multi-hop and multi-memory composition",
            "status": "UNDER_COVERED",
            "evidence": "Most replay cases have one exact target",
            "impact": "Joint goal-plus-constraint-plus-plan Recall and ordering remain uncertain",
            "next_dataset_requirement": "Cross-session cases with two or more independently necessary target types",
        },
        {
            "gap_id": "GAP-007",
            "category": "ambiguous correction targeting",
            "status": "UNDER_COVERED",
            "evidence": "Track M correction controls use explicit target memory IDs",
            "impact": "Natural-language corrections with multiple plausible targets must fail closed but are not measured here",
            "next_dataset_requirement": "Adversarial zero-target, one-target, and multi-target correction set",
        },
        {
            "gap_id": "GAP-008",
            "category": "sensitive-information policy",
            "status": "CONTROL_ONLY",
            "evidence": "One synthetic unrelated-sensitive rejection control",
            "impact": "Breadth of sensitive-category false positives and false negatives is unknown",
            "next_dataset_requirement": "Privacy-reviewed red-team set with no real identifiers",
        },
        {
            "gap_id": "GAP-009",
            "category": "C4 and Streamlit integration",
            "status": "OUT_OF_SCOPE_NOT_EXECUTED",
            "evidence": "Track M stops before C4 integration and does not modify Streamlit",
            "impact": "P3-to-provider invocation correctness and UI control usability are not evaluated",
            "next_dataset_requirement": "Separate authorization and integration protocol after Track M review",
        },
        {
            "gap_id": "GAP-010",
            "category": "final response quality",
            "status": "PROHIBITED_NOT_EXECUTED",
            "evidence": "No responses or Judge calls in Track M",
            "impact": "Mechanism metrics do not establish grounded response quality or learning benefit",
            "next_dataset_requirement": "Separate governed downstream evaluation; Track M artifacts alone are insufficient",
        },
    ]


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_report(results: Mapping[str, Any]) -> str:
    metrics = results["mechanism_metrics"]
    source = results["scenario_coverage"]
    latency = metrics["latency_ms"]
    tests = results["tests"]
    return f"""# RQ3-REAL Track M Persistent Learner Memory Results

## Scope and status

`C4_LEARNER_MEMORY_V1` is implemented and evaluated offline. This Track did not call OpenAI, generate a student response, call a Judge, launch or modify Streamlit, execute a controlled RQ3 shard, run final RQ3 scoring, modify P3, modify `conversation_memory.py`, or integrate the provider into C4.

## 1. Existing Memory classification

The existing `utils/conversation_memory.py` remains short-term, rule-based working Memory. Numbered references whose antecedent is already in visible history are classified as `visible-history only` or `same-session working Memory`; they are not claimed as long-term Memory. The audit contains {source['audit_row_count']} rows. The canonical `multiturn_scenarios.jsonl` and generated unified benchmark JSONL are absent in this asset-sparse checkout, while accessible in-code unified cases and RQ2 metadata commitments are explicitly audited without reconstruction.

## 2. New schema and operations

The implementation uses a versioned SQLite schema, learner-scoped rows, FTS5, temporal validity, consent state, content SHA-256, append-only replacement versions, explicit supersession links, deletion tombstones, event audit rows, and a separate database per scenario/run. Supported types are GOAL, PREFERENCE, CONSTRAINT, DIFFICULTY, COMPLETED_ACTION, ACTIVE_PLAN, PROGRESS_UPDATE, and CORRECTION. Supported candidate operations are ADD, UPDATE, SUPERSEDE, DELETE, and NOOP.

Write-operation accuracy was {metrics['write_operation_accuracy']['value']:.6f} ({metrics['write_operation_accuracy']['numerator']:.0f}/{metrics['write_operation_accuracy']['denominator']}). Assistant advice, model/ability inference, unsupported Dashboard interpretation, duplicates, low-confidence candidates, and unrelated sensitive information were deterministic NOOP rejections.

## 3. Retrieval architecture

Retrieval applies learner, ACTIVE/temporal, consent, visible-history, and explicit-conflict guards before deterministic FTS5 plus frozen local MPNet fusion. Query-to-type alignment uses semantic similarity to eight frozen descriptions; it is not a keyword-only trigger. P3 remains the later Memory-needed gate, while this retriever chooses relevant Memory. Internal embeddings never appear in the envelope, and absolute relevance thresholds permit `NO_MATCH`.

Semantic backend status: `{results['semantic_backend']['backend']}` using `{results['semantic_backend'].get('implementation', 'NOT_APPLICABLE')}` at revision `{results['semantic_backend'].get('revision', 'NOT_APPLICABLE')}`; network allowed: `{str(results['semantic_backend'].get('network_allowed', False)).lower()}`.

## 4. Existing scenario coverage

- Replay/evaluation cases: {source['replay_case_count']}
- Retrieval cases after policy-only controls: {source['retrieval_case_count']}
- RQ2 metadata-only fixture commitments audited: {source['rq2_metadata_fixture_count']}
- In-code unified Memory/negative-control cases audited: {source['in_code_unified_case_count']}
- Missing canonical source files: {source['missing_source_file_count']}

Every valid persistent replay wrote to SQLite, closed the store, reopened it, and then retrieved. Same-session visible antecedents were audited but not relabelled as cross-session Memory.

## 5. Mechanism metrics

| Metric | Result | Count basis |
|---|---:|---:|
| Write operation accuracy | {metrics['write_operation_accuracy']['value']:.6f} | {metrics['write_operation_accuracy']['numerator']:.0f}/{metrics['write_operation_accuracy']['denominator']} |
| Recall@1 | {metrics['retrieval_recall_at_1']['value']:.6f} | {metrics['retrieval_recall_at_1']['numerator']:.0f}/{metrics['retrieval_recall_at_1']['denominator']} |
| Recall@3 | {metrics['retrieval_recall_at_3']['value']:.6f} | {metrics['retrieval_recall_at_3']['numerator']:.0f}/{metrics['retrieval_recall_at_3']['denominator']} |
| Recall@5 | {metrics['retrieval_recall_at_5']['value']:.6f} | {metrics['retrieval_recall_at_5']['numerator']:.0f}/{metrics['retrieval_recall_at_5']['denominator']} |
| Exact target accuracy | {metrics['exact_target_accuracy']['value']:.6f} | {metrics['exact_target_accuracy']['numerator']:.0f}/{metrics['exact_target_accuracy']['denominator']} |
| Wrong-memory rate | {metrics['wrong_memory_rate']['value']:.6f} | {metrics['wrong_memory_rate']['numerator']:.0f}/{metrics['wrong_memory_rate']['denominator']} |
| Cross-learner leakage | {metrics['cross_learner_leakage_rate']['value']:.6f} | {metrics['cross_learner_leakage_rate']['numerator']:.0f}/{metrics['cross_learner_leakage_rate']['denominator']} |
| Update/supersession accuracy | {metrics['update_supersession_accuracy']['value']:.6f} | {metrics['update_supersession_accuracy']['numerator']:.0f}/{metrics['update_supersession_accuracy']['denominator']} |
| Stale-memory rate | {metrics['stale_memory_rate']['value']:.6f} | {metrics['stale_memory_rate']['numerator']:.0f}/{metrics['stale_memory_rate']['denominator']} |
| Abstention accuracy | {metrics['abstention_accuracy']['value']:.6f} | {metrics['abstention_accuracy']['numerator']:.0f}/{metrics['abstention_accuracy']['denominator']} |
| Visible-history duplication | {metrics['visible_history_duplication_rate']['value']:.6f} | {metrics['visible_history_duplication_rate']['numerator']:.0f}/{metrics['visible_history_duplication_rate']['denominator']} |
| Persistence after reopen | {metrics['persistence_after_store_reopen_accuracy']['value']:.6f} | {metrics['persistence_after_store_reopen_accuracy']['numerator']:.0f}/{metrics['persistence_after_store_reopen_accuracy']['denominator']} |
| Semantic-only exact target hits | {metrics['semantic_only_target_hit_count']['value']} | count |

Retrieval latency (local end-to-end): median {latency['median']:.3f} ms, mean {latency['mean']:.3f} ms, p95 {latency['p95']:.3f} ms, maximum {latency['maximum']:.3f} ms over {latency['count']} retrievals. The first measured call includes model loading when MPNet is configured, so the distribution is descriptive rather than a production latency claim.

## 6. Remaining dataset gaps

The gap registry contains {results['gap_registry_count']} explicit gaps, including absent canonical scenario JSONLs, metadata-only historical persistent fixtures, real longitudinal data, bilingual/code-switch cases, multi-hop Memory, ambiguous correction targets, broader privacy red-teaming, C4/UI integration, and final-response quality. These limitations prevent claims about real-student outcomes, deployment readiness, or final RQ3 performance.

## 7. Tests

Offline tests passed: {tests['passed']}/{tests['total']}. Test command: `{tests['command']}`. Network and provider calls remained blocked/absent. The result suite covers persistence after reopen, learner isolation, all five operations, duplicate suppression, correction precedence, temporal validity, lexical and semantic retrieval, NO_MATCH, visible-history exclusion, assistant-advice rejection, deterministic reset, local-only model identity, envelope hashing, and forbidden-boundary scans.

## Interpretation boundary

These are small deterministic mechanism diagnostics, not final RQ3 scoring and not evidence that C4 responses improve learning. Stop before C4 integration.
"""


def build_status(results: Mapping[str, Any]) -> str:
    tests = results["tests"]
    return f"""# RQ3-REAL-C4 Track M Status

- Track: `RQ3-REAL-C4 Track M`
- Architecture: `C4_LEARNER_MEMORY_V1`
- Status: `COMPLETE_OFFLINE_MEMORY_MECHANISM_ONLY`
- C4 integration: `NOT_STARTED`
- Frozen P3 changed or called: `NO`
- `conversation_memory.py` changed: `NO`
- Streamlit changed or launched: `NO`
- Real LLM/provider calls: `0`
- Response generation: `0`
- Judge calls: `0`
- Controlled RQ3 shards executed: `0`
- Final RQ3 scoring: `NOT_RUN`
- Real student PII: `NONE`
- Tests: `{tests['passed']}/{tests['total']} passed`
- Network socket attempts during mechanism evaluation: `{results['execution_boundaries']['network_socket_attempts']}`
- Review boundary: `STOP_BEFORE_C4_INTEGRATION`

The ending Git commit and external review-ZIP SHA-256 are reported in the completion handoff because neither artifact can self-embed its own final identity.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mpnet-path", type=Path)
    parser.add_argument("--lexical-only", action="store_true")
    parser.add_argument("--tests-passed", type=int, default=0)
    parser.add_argument("--tests-total", type=int, default=0)
    parser.add_argument("--tests-command", default="NOT_YET_RUN")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixture = load_json(FIXTURE_PATH)
    cases = list(fixture["cases"])
    if args.lexical_only:
        backend = None
    else:
        model_path = args.mpnet_path or discover_local_mpnet_path(PROJECT_ROOT)
        backend = FrozenLocalMPNetBackend(model_path) if model_path is not None else None
    with tempfile.TemporaryDirectory(prefix="rq3_track_m_memory_") as temp_dir:
        with deny_network() as network_guard:
            metrics, scenario_results = run_cases(
                cases,
                semantic_backend=backend,
                temporary_root=Path(temp_dir),
            )
    audit_rows = build_audit(cases, scenario_results)
    gap_rows = build_gaps()
    rq2_count = len(load_jsonl(RQ2_COMMITMENT_PATH))
    in_code_count = sum(1 for row in audit_rows if str(row["audit_id"]).startswith("AUDIT-UNIFIED-"))
    missing_count = sum(1 for row in audit_rows if row["accessible"] is False)
    retrieval_count = sum(1 for case in cases if not case.get("policy_only"))
    semantic_identity = (
        dict(backend.identity)
        if backend is not None
        else {"backend": "NOT_CONFIGURED", "network_allowed": False}
    )
    semantic_failures = [
        str(row["scenario_id"])
        for row in scenario_results
        if any(
            str(limitation).startswith("SEMANTIC_BACKEND_UNAVAILABLE:")
            for limitation in row.get("limitations", [])
        )
    ]
    if backend is not None and (
        semantic_identity.get("implementation") in {None, "NOT_LOADED"}
        or semantic_failures
    ):
        raise RuntimeError(
            "CONFIGURED_MPNET_DID_NOT_EXECUTE:"
            + ",".join(semantic_failures or ["NO_LOAD_EVIDENCE"])
        )
    results: dict[str, Any] = {
        "schema_version": "memory-mechanism-results-v1",
        "architecture_id": "C4_LEARNER_MEMORY_V1",
        "track": "RQ3-REAL-C4-TRACK-M",
        "generated_at": QUERY_TIME,
        "fixture_identity": {
            "path": str(FIXTURE_PATH.relative_to(PROJECT_ROOT)),
            "sha256": file_sha256(FIXTURE_PATH),
        },
        "semantic_backend": semantic_identity,
        "scenario_coverage": {
            "replay_case_count": len(cases),
            "retrieval_case_count": retrieval_count,
            "audit_row_count": len(audit_rows),
            "rq2_metadata_fixture_count": rq2_count,
            "in_code_unified_case_count": in_code_count,
            "missing_source_file_count": missing_count,
            "separate_database_per_case": True,
            "close_reopen_before_retrieval": True,
        },
        "mechanism_metrics": metrics,
        "scenario_results": scenario_results,
        "gap_registry_count": len(gap_rows),
        "tests": {
            "passed": args.tests_passed,
            "total": args.tests_total,
            "command": args.tests_command,
        },
        "execution_boundaries": {
            "network_guard_enabled": True,
            "network_socket_attempts": network_guard.attempts,
            "openai_calls": 0,
            "llm_provider_calls": 0,
            "response_generations": 0,
            "judge_calls": 0,
            "streamlit_launches": 0,
            "controlled_rq3_shards_executed": 0,
            "final_rq3_scoring_runs": 0,
            "p3_calls": 0,
            "c4_integrations": 0,
        },
        "interpretation_limitations": [
            "SMALL_DETERMINISTIC_MECHANISM_DIAGNOSTIC",
            "NOT_FINAL_RQ3_SCORING",
            "NOT_RESPONSE_QUALITY_EVALUATION",
            "NO_REAL_STUDENT_OUTCOME_CLAIM",
            "MISSING_CANONICAL_SCENARIO_JSONL_FILES",
            "RQ2_PERSISTENT_FIXTURES_METADATA_ONLY",
            "STOP_BEFORE_C4_INTEGRATION",
        ],
    }
    results["result_sha256"] = sha256_object(results)
    write_csv(AUDIT_PATH, AUDIT_COLUMNS, audit_rows)
    write_csv(GAP_PATH, GAP_COLUMNS, gap_rows)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(build_report(results), encoding="utf-8")
    STATUS_PATH.write_text(build_status(results), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "COMPLETE_OFFLINE_MECHANISM_ONLY",
                "replay_cases": len(cases),
                "audit_rows": len(audit_rows),
                "gap_rows": len(gap_rows),
                "semantic_backend": semantic_identity["backend"],
                "network_socket_attempts": network_guard.attempts,
                "result_sha256": results["result_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
