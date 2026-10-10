"""Exact B1 reproduction and provider-free Gold measurement.

This module deliberately does not call ``build_legacy_baseline`` because that
historical entry point writes both the old local ledger and a protected tracked
aggregate.  It instantiates the frozen Legacy adapter directly, reproduces the
original 35-case ledger first, and only then permits measurement of RQ2-B
datasets through that same adapter instance.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

import utils.production_intent_router as production_router

from evaluation.capability_routing_v1 import (
    PREDICTED_CAPABILITIES,
    require_frozen_rq1_router,
    safe_count_distribution,
)
from evaluation.capability_routing_v1.capability_case_schema import CapabilityCaseV1
from evaluation.capability_routing_v1.legacy_hard_route_adapter import (
    LegacyHardRoutingCapabilityAdapterV1,
    _dashboard_fixture,
    provider_free_environment,
)

from .gold_preflight import GoldPreflightResult, RoutingCaseInput


ROOT = Path(__file__).resolve().parents[2]

B1_IDENTITY = "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE"
ORIGINAL_SYNTHETIC_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "capability_development_bank_v1.jsonl"
)
ORIGINAL_SYNTHETIC_BANK_SHA256 = (
    "a791a154638e59436867c50e3fcfc4d15e2d2fef47ee2c52937892b49b0092a6"
)
LEGACY_LEDGER_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_artifacts/"
    "legacy_hard_routing_baseline_v1.jsonl"
)
LEGACY_LEDGER_SHA256 = (
    "801efb2c4ab4b32445e6ec2e51a6bac9173d566cb8136070b557e35d62ca5e80"
)
CORRECTED_AGGREGATE_RELATIVE = Path(
    "evaluation/capability_routing_v1_r1/legacy_capability_projection_v1_1.json"
)

EXPECTED_CAPABILITY_COUNTS = {
    "dashboard_evidence": 12,
    "course_retrieval": 3,
    "episodic_memory": 4,
    "planning": 5,
    "safe_direct_response": 0,
    "clarification": 16,
}


class B1ReproductionError(RuntimeError):
    """Raised if the frozen adapter no longer reproduces the B1 evidence."""


class B1CaseLike(Protocol):
    case_id: str
    current_query: str
    current_page: str
    conversation_history: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class B1LedgerResult:
    ledger_bytes: bytes
    rows: tuple[Mapping[str, Any], ...]
    aggregate: Mapping[str, Any]

    @property
    def ledger_sha256(self) -> str:
        return hashlib.sha256(self.ledger_bytes).hexdigest()


@dataclass(frozen=True)
class B1MeasurementRun:
    reproduction: B1LedgerResult
    synthetic_gold: B1LedgerResult
    authentic_gold: B1LedgerResult
    authentic_context_missing_registry: B1LedgerResult


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_ledger_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    """Match the byte contract used by the historical Legacy ledger."""

    return b"".join(
        json.dumps(
            dict(row),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )


def _verified_file(path: Path, expected_sha256: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected_sha256:
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    return value


def _jsonl(value: bytes) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in value.decode("utf-8").splitlines() if line]
    if not all(isinstance(row, dict) for row in rows):
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    return rows


def _load_original_cases(root: Path) -> list[CapabilityCaseV1]:
    source = _verified_file(
        root / ORIGINAL_SYNTHETIC_BANK_RELATIVE,
        ORIGINAL_SYNTHETIC_BANK_SHA256,
    )
    rows = _jsonl(source)
    if len(rows) != 35 or len({str(row.get("case_id")) for row in rows}) != 35:
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    return [CapabilityCaseV1.from_mapping(row) for row in rows]


def _safe_aggregate(
    rows: Sequence[Mapping[str, Any]], ledger_bytes: bytes
) -> dict[str, Any]:
    calls: Counter[str] = Counter()
    capability_counts: Counter[str] = Counter()
    for row in rows:
        call_counts = row.get("production_call_counts")
        projection = row.get("capability_projection")
        if not isinstance(call_counts, Mapping) or not isinstance(projection, Mapping):
            raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
        calls.update({str(name): int(count) for name, count in call_counts.items()})
        capability_counts.update(
            name for name in PREDICTED_CAPABILITIES if bool(projection.get(name))
        )
    return {
        "schema_version": "rq2b-b1-measurement-aggregate-v1",
        "baseline_identity": B1_IDENTITY,
        "router_identity": "C0_COSINE",
        "record_count": len(rows),
        "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "selected_intent_distribution": safe_count_distribution(
            [str(row.get("selected_intent") or "") for row in rows]
        ),
        "selected_route_distribution": safe_count_distribution(
            [str(row.get("selected_route") or "") for row in rows]
        ),
        "source_scope_distribution": safe_count_distribution(
            [str(row.get("source_scope") or "") for row in rows]
        ),
        "capability_positive_count": {
            name: capability_counts.get(name, 0) for name in PREDICTED_CAPABILITIES
        },
        "retrieval_requested_count": sum(
            bool(row.get("retrieval_requested")) for row in rows
        ),
        "retrieval_used_count": sum(bool(row.get("retrieval_used")) for row in rows),
        "planner_requested_count": sum(
            bool(row.get("planner_requested")) for row in rows
        ),
        "recommendation_plan_present_count": sum(
            bool(row.get("recommendation_plan_present")) for row in rows
        ),
        "working_context_used_count": sum(
            bool(row.get("working_context_used")) for row in rows
        ),
        "episodic_memory_used_count": sum(
            bool(row.get("episodic_memory_used")) for row in rows
        ),
        "working_context_without_episodic_memory_count": sum(
            bool(row.get("working_context_used"))
            and not bool(row.get("episodic_memory_used"))
            for row in rows
        ),
        "production_function_call_counts": dict(sorted(calls.items())),
        "provider_calls": 0,
        "network_access": False,
        "training_performed": False,
        "production_behavior_changed": False,
    }


def _assert_reproduced_aggregate(
    aggregate: Mapping[str, Any], root: Path
) -> None:
    corrected_path = root / CORRECTED_AGGREGATE_RELATIVE
    if not corrected_path.is_file() or corrected_path.is_symlink():
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    corrected = json.loads(corrected_path.read_text(encoding="utf-8"))
    if (
        not isinstance(corrected, dict)
        or corrected.get("baseline_identity") != B1_IDENTITY
        or corrected.get("context_resolution_enabled") is not True
        or corrected.get("original_query_only") is not False
        or aggregate.get("record_count") != 35
        or aggregate.get("ledger_sha256") != LEGACY_LEDGER_SHA256
        or aggregate.get("capability_positive_count") != EXPECTED_CAPABILITY_COUNTS
        or aggregate.get("retrieval_requested_count") != 3
        or aggregate.get("planner_requested_count") != 5
        or aggregate.get("working_context_used_count") != 35
        or aggregate.get("working_context_without_episodic_memory_count") != 31
    ):
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    parity_fields = (
        "record_count",
        "ledger_sha256",
        "selected_intent_distribution",
        "selected_route_distribution",
        "source_scope_distribution",
        "capability_positive_count",
        "retrieval_requested_count",
        "retrieval_used_count",
        "planner_requested_count",
        "recommendation_plan_present_count",
        "working_context_used_count",
        "episodic_memory_used_count",
        "working_context_without_episodic_memory_count",
        "production_function_call_counts",
    )
    if any(aggregate.get(field) != corrected.get(field) for field in parity_fields):
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")


def _measure(
    adapter: LegacyHardRoutingCapabilityAdapterV1,
    cases: Sequence[B1CaseLike],
) -> B1LedgerResult:
    rows = tuple(adapter.measure(case) for case in cases)  # type: ignore[arg-type]
    ledger_bytes = canonical_ledger_bytes(rows)
    return B1LedgerResult(
        ledger_bytes=ledger_bytes,
        rows=rows,
        aggregate=_safe_aggregate(rows, ledger_bytes),
    )


def _reproduce_with_adapter(
    adapter: LegacyHardRoutingCapabilityAdapterV1,
    root: Path,
) -> B1LedgerResult:
    original_cases = _load_original_cases(root)
    historical_bytes = _verified_file(root / LEGACY_LEDGER_RELATIVE, LEGACY_LEDGER_SHA256)
    historical_rows = _jsonl(historical_bytes)
    if (
        len(historical_rows) != 35
        or [case.case_id for case in original_cases]
        != [str(row.get("case_id")) for row in historical_rows]
    ):
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    result = _measure(adapter, original_cases)
    # Both comparisons are intentional: byte equality catches serialization or
    # ordering drift while the digest is the governed external contract.
    if result.ledger_bytes != historical_bytes or result.ledger_sha256 != LEGACY_LEDGER_SHA256:
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    _assert_reproduced_aggregate(result.aggregate, root)
    return result


def reproduce_frozen_b1_source(root: Path = ROOT) -> B1LedgerResult:
    """Remeasure the original 35 cases without writing either old output path."""

    require_frozen_rq1_router(root)
    with provider_free_environment():
        runtime = production_router.load_production_semantic_router()
        adapter = LegacyHardRoutingCapabilityAdapterV1(
            semantic_runtime=runtime,
            dashboard_data=_dashboard_fixture(),
        )
        return _reproduce_with_adapter(adapter, root)


def run_b1_measurement(
    gold: GoldPreflightResult,
    root: Path = ROOT,
) -> B1MeasurementRun:
    """Reproduce B1 first, then measure the three governed RQ2-B datasets."""

    require_frozen_rq1_router(root)
    with provider_free_environment():
        runtime = production_router.load_production_semantic_router()
        adapter = LegacyHardRoutingCapabilityAdapterV1(
            semantic_runtime=runtime,
            dashboard_data=_dashboard_fixture(),
        )
        reproduction = _reproduce_with_adapter(adapter, root)
        synthetic = _measure(
            adapter,
            [example.router_input for example in gold.synthetic_gold],
        )
        authentic = _measure(
            adapter,
            [example.router_input for example in gold.authentic_gold],
        )
        registry = _measure(
            adapter,
            [
                example.router_input
                for example in gold.authentic_context_missing_registry
            ],
        )
    if (
        synthetic.aggregate["record_count"] != 35
        or authentic.aggregate["record_count"] != 22
        or registry.aggregate["record_count"] != 3
    ):
        raise B1ReproductionError("BLOCKED_RQ2_B_B1_REPRODUCTION_MISMATCH")
    return B1MeasurementRun(
        reproduction=reproduction,
        synthetic_gold=synthetic,
        authentic_gold=authentic,
        authentic_context_missing_registry=registry,
    )
