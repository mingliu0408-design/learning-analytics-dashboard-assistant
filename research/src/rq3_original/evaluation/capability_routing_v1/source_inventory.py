"""Exact allowlisted development-source inventory for RQ2-A."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import ROOT, sha256_file
from .capability_case_schema import CapabilityCaseV1


class SourceBoundaryError(RuntimeError):
    pass


ALLOWED_TRACKED_SOURCES = (
    "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
    "evaluation/unified_benchmark_scenarios.jsonl",
    "evaluation/multiturn_scenarios.jsonl",
    "evaluation/rag_scenarios.jsonl",
    "evaluation/scenarios.jsonl",
)


def assert_allowed_source(relative: str) -> str:
    candidate = str(relative).replace("\\", "/")
    if candidate not in ALLOWED_TRACKED_SOURCES:
        raise SourceBoundaryError("development source is outside the exact allowlist")
    return candidate


def _tracked(root: Path, relative: str) -> bool:
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def build_source_inventory(root: Path = ROOT) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for relative in ALLOWED_TRACKED_SOURCES:
        assert_allowed_source(relative)
        is_tracked = _tracked(root, relative)
        if not is_tracked:
            rows.append({"relative_path": relative, "status": "NOT_PRESENT"})
            continue
        source_path = root / relative
        if not source_path.is_file() or source_path.is_symlink():
            raise SourceBoundaryError("allowlisted tracked source is not a regular file")
        with source_path.open("r", encoding="utf-8") as handle:
            record_count = sum(1 for line in handle if line.strip())
        rows.append(
            {
                "relative_path": relative,
                "status": "PRESENT",
                "record_count": record_count,
                "sha256": sha256_file(source_path),
            }
        )
    return {
        "schema_version": "capability-source-inventory-v1",
        "stage": "RQ2-A",
        "status": "PASS",
        "allowlist_count": len(ALLOWED_TRACKED_SOURCES),
        "present_count": sum(row["status"] == "PRESENT" for row in rows),
        "not_present_count": sum(row["status"] == "NOT_PRESENT" for row in rows),
        "sources": rows,
        "other_directories_searched": False,
        "external_data_used": False,
    }


def _first(value: Mapping[str, Any], names: Iterable[str], default: Any = "") -> Any:
    for name in names:
        if value.get(name) not in (None, ""):
            return value[name]
    return default


def _history(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = _first(value, ("conversation_history", "history", "messages"), [])
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for position, item in enumerate(raw):
        if isinstance(item, Mapping):
            content = _first(item, ("content", "text", "query", "student_query"), "")
            rows.append(
                {
                    "role": str(item.get("role") or "unknown"),
                    "turn_order": position,
                    "source": "allowlisted_development_source",
                    "content": str(content),
                    "relevant": True,
                }
            )
    return rows


def load_allowlisted_cases(root: Path = ROOT) -> list[CapabilityCaseV1]:
    """Load only present allowlisted JSONL sources; never search for substitutes."""

    cases: list[CapabilityCaseV1] = []
    for relative in ALLOWED_TRACKED_SOURCES:
        if not _tracked(root, relative):
            continue
        source_path = root / assert_allowed_source(relative)
        for line_number, line in enumerate(
            source_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                raise SourceBoundaryError("JSONL record must be an object")
            query = _first(raw, ("current_query", "student_query", "query"), "")
            if not str(query).strip():
                continue
            scenario_id = str(
                _first(raw, ("scenario_id", "case_id", "id"), f"line-{line_number}")
            )
            cases.append(
                CapabilityCaseV1.from_mapping(
                    {
                        "case_id": f"SRC-{len(cases) + 1:04d}",
                        "source_dataset": relative,
                        "source_scenario_id": scenario_id,
                        "turn_index": int(raw.get("turn_index", 0)),
                        "current_query": str(query),
                        "current_page": str(
                            _first(raw, ("current_page", "page"), "Overview")
                        ),
                        "conversation_history": _history(raw),
                        "existing_expected_intent": str(
                            _first(raw, ("expected_intent", "intent"), "")
                        ),
                        "existing_expected_route": str(raw.get("expected_route") or ""),
                        "existing_expected_source_scope": str(
                            raw.get("expected_source_scope") or ""
                        ),
                        "existing_expected_memory": raw.get("expected_memory"),
                        "existing_expected_retrieval": raw.get("expected_retrieval"),
                        "existing_required_capabilities": list(
                            raw.get("required_capabilities") or []
                        ),
                        "scenario_category": str(raw.get("category") or "imported"),
                        "scenario_family": str(raw.get("family") or scenario_id),
                        "provenance": {
                            "source_line": line_number,
                            "tracked_safe_source": True,
                        },
                    }
                )
            )
    return cases
