"""Execute a privacy-safe parity check against the production keyword router.

The governed query is held only long enough to invoke the two existing
production entry points.  Returned records and tracked reports deliberately do
not retain it.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from unittest import mock

from evaluation.learned_intent_ranking.lr4b.contract_schema import (
    authorised_project_path,
    sha256_file,
)
from utils.evidence_synthesiser import classify_query_detailed
from utils.production_intent_router import (
    KEYWORD_BASELINE,
    route_production_intent,
)


FIXTURE_RELATIVE_PATH = (
    "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
)
FIXTURE_SHA256 = "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
FIXTURE_RECORD_COUNT = 62


class KeywordParityError(RuntimeError):
    """Fail-closed parity error whose message contains no governed text."""


class SemanticRuntimeForbidden(RuntimeError):
    """Raised by the parity-only semantic-loader sentinel."""


@dataclass(frozen=True)
class KeywordBaselineResult:
    """Text-free result of adapting one query to K0's one-item ranking."""

    example_id: str
    deterministic_intent: str
    deterministic_rule_id: str
    production_selected_intent: str
    production_keyword_intent: str
    production_keyword_rule_id: str
    ranking: tuple[str, ...]
    semantic_status: str
    semantic_candidate: str | None
    semantic_accepted: bool
    routing_source: str
    fallback_reason: str

    @property
    def is_contract_match(self) -> bool:
        return (
            self.production_selected_intent
            == self.production_keyword_intent
            == self.deterministic_intent
            and self.production_keyword_rule_id == self.deterministic_rule_id
            and len(self.ranking) == 1
            and self.ranking[0] == self.production_selected_intent
            and self.semantic_status == "not_run"
            and self.semantic_candidate is None
            and self.semantic_accepted is False
            and self.routing_source == "keyword"
            and self.fallback_reason == "keyword_baseline_mode"
        )


def load_approved_fixture(project_root: Path) -> tuple[dict[str, str], ...]:
    """Load only the in-memory fields required by the parity execution."""

    fixture_path = authorised_project_path(project_root, FIXTURE_RELATIVE_PATH)
    if not fixture_path.is_file() or fixture_path.is_symlink():
        raise KeywordParityError("approved parity fixture is unavailable")
    if sha256_file(fixture_path) != FIXTURE_SHA256:
        raise KeywordParityError("approved parity fixture fingerprint mismatch")

    rows: list[dict[str, str]] = []
    for line in fixture_path.read_text(encoding="utf-8-sig").splitlines():
        if not line:
            continue
        payload = json.loads(line)
        example_id = str(payload.get("example_id", "")).strip()
        query = str(payload.get("query", ""))
        if not example_id or not query:
            raise KeywordParityError("approved parity fixture field missing")
        rows.append({"example_id": example_id, "query": query})
    if len(rows) != FIXTURE_RECORD_COUNT or len({row["example_id"] for row in rows}) != len(rows):
        raise KeywordParityError("approved parity fixture count mismatch")
    return tuple(rows)


def adapt_keyword_query(example_id: str, query: str) -> KeywordBaselineResult:
    """Call both current production keyword entry points for one fixture row."""

    deterministic = classify_query_detailed(query)
    production = route_production_intent(query, mode=KEYWORD_BASELINE)
    ranking = (production.selected_intent,)
    return KeywordBaselineResult(
        example_id=str(example_id),
        deterministic_intent=deterministic.legacy_query_type,
        deterministic_rule_id=deterministic.rule_id,
        production_selected_intent=production.selected_intent,
        production_keyword_intent=production.keyword_intent,
        production_keyword_rule_id=production.keyword_rule_id,
        ranking=ranking,
        semantic_status=production.semantic_status,
        semantic_candidate=production.semantic_candidate,
        semantic_accepted=production.semantic_accepted,
        routing_source=production.routing_source,
        fallback_reason=production.fallback_reason,
    )


def execute_keyword_parity_records(
    fixture_rows: Iterable[Mapping[str, str]],
) -> tuple[KeywordBaselineResult, ...]:
    """Execute all rows without copying governed query text into the result."""

    return tuple(
        adapt_keyword_query(str(row["example_id"]), str(row["query"]))
        for row in fixture_rows
    )


def summarise_keyword_parity(
    results: Iterable[KeywordBaselineResult],
    *,
    semantic_loader_call_count: int,
) -> dict[str, object]:
    """Create the allowlisted, aggregate-only tracked parity report."""

    rows = tuple(results)
    mismatches = [row for row in rows if not row.is_contract_match]
    matches = len(rows) - len(mismatches)
    return {
        "schema_version": "rq1a-r1-keyword-parity-v1",
        "stage": "RQ1-A-R1",
        "status": "PASS" if not mismatches and semantic_loader_call_count == 0 else "FAIL",
        "fixture_sha256": FIXTURE_SHA256,
        "record_count": len(rows),
        "match_count": matches,
        "mismatch_count": len(mismatches),
        "parity_percentage": round(100.0 * matches / len(rows), 6) if rows else 0.0,
        "mismatch_example_ids": [row.example_id for row in mismatches],
        "deterministic_label_counts": dict(sorted(Counter(
            row.deterministic_intent for row in rows
        ).items())),
        "production_label_counts": dict(sorted(Counter(
            row.production_selected_intent for row in rows
        ).items())),
        "keyword_rule_id_counts": dict(sorted(Counter(
            row.production_keyword_rule_id for row in rows
        ).items())),
        "ranking_length": 1,
        "semantic_loader_call_count": semantic_loader_call_count,
        "semantic_runtime_called": semantic_loader_call_count != 0,
        "provider_calls": False,
        "network_access": False,
        "raw_text_emitted": False,
    }


def execute_keyword_parity(project_root: Path) -> dict[str, object]:
    """Run the real 62-row parity check with a semantic-loader tripwire."""

    fixture_rows = load_approved_fixture(project_root)

    def forbidden_loader(*_args: object, **_kwargs: object) -> object:
        raise SemanticRuntimeForbidden("semantic runtime called during keyword parity")

    with mock.patch(
        "utils.production_intent_router.load_production_semantic_router",
        side_effect=forbidden_loader,
    ) as semantic_loader:
        results = execute_keyword_parity_records(fixture_rows)
        loader_calls = semantic_loader.call_count
    report = summarise_keyword_parity(
        results,
        semantic_loader_call_count=loader_calls,
    )
    if len(results) != FIXTURE_RECORD_COUNT:
        raise KeywordParityError("keyword parity record-count mismatch")
    if report["mismatch_count"] != 0:
        raise KeywordParityError("keyword parity mismatch")
    if loader_calls != 0:
        raise KeywordParityError("semantic runtime called during keyword parity")
    return report
