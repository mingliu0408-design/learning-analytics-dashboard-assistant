"""Run the governed retrieval-only R0/R1 comparison and freeze one candidate."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.c4_rag.corpus import (  # noqa: E402
    CANONICAL_CFULL_ROOT,
    CANONICAL_MPNET_ROOT,
    EXPECTED_SOURCE_HASHES,
    MPNET_REVISION,
    PROJECT_ROOT as CORPUS_PROJECT_ROOT,
    legacy_chunk_corpus_hash,
    load_legacy_chunks,
    sha256_file,
    source_identity,
    verify_canonical_sources,
)
from utils.c4_rag.models import EvidenceStrength, RetrievalEnvelope  # noqa: E402
from utils.c4_rag.retrievers import (  # noqa: E402
    C4RAGHybrid,
    C4RAGLegacyLexical,
    R0_ID,
    R1_ID,
    _evidence_strength,
)


OUTPUT_DIR = Path(__file__).resolve().parent
EVALUATION_DATE = "2026-09-01"
EXTERNAL_EVALUATION_ROOT = CANONICAL_CFULL_ROOT / "evaluation"
EXPECTED_INPUT_HASHES = {
    "rag_scenarios.jsonl": "dfb9140b41559e4b448e94dfebf076af7351286d91c9d954d48ac799caae635a",
    "scenarios.jsonl": "e74f1b583c5225da4bb8b999b11c1cf72b8a8f2b89b8633da40982eb675a4d1e",
    "unified_benchmark_scenarios.jsonl": "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
    "unified_reference_evidence_v1.jsonl": "4f2cf3ee185c389f2008402ec143ae6a07b1fd35597a951afb5203c6498a03ea",
}

SOURCE_SPECS = {
    "Module Weekly Pages.html": "AUTHENTIC_RAW_WEEKLY_HTML",
    "Module Handbook.doc": "AUTHENTIC_RAW_HANDBOOK_HTML_IN_DOC",
    "Module Handbook.docx": "AUTHENTIC_RAW_HANDBOOK_DOCX",
    "Module readings.pdf": "AUTHENTIC_RAW_READING_LIST_PDF",
    "moodle_links.pdf": "AUTHENTIC_RAW_MOODLE_LINKS_PDF",
    "references.txt": "AUTHENTIC_REFERENCE_METADATA",
    "course_metadata.py": "AUTHENTIC_CURATED_COURSE_METADATA",
    "manifest.jsonl": "LEGACY_COURSE_SOURCE_MANIFEST",
    "index_metadata_v2.json": "LEGACY_INDEX_METADATA",
    "index_metadata_v2_4.json": "LEGACY_INDEX_METADATA",
    "chunks_v2.json": "LEGACY_PERSISTED_CHUNKS",
    "chunks_v2_4.json": "LEGACY_PERSISTED_CHUNKS",
    "SNAPSHOT_MANIFEST.json": "COURSE_RAG_SOURCE_SNAPSHOT_MANIFEST",
    "handbook.normalized.html": "COURSE_RAG_DERIVED_SOURCE_SNAPSHOT",
    "navigation.normalized.txt": "COURSE_RAG_DERIVED_SOURCE_SNAPSHOT",
    "reading_list.normalized.txt": "COURSE_RAG_DERIVED_SOURCE_SNAPSHOT",
    "weekly_page.sanitized.html": "COURSE_RAG_DERIVED_SOURCE_SNAPSHOT",
    "parents.jsonl": "COURSE_RAG_PERSISTED_PARENT_CHUNKS",
    "children.jsonl": "COURSE_RAG_PERSISTED_CHILD_CHUNKS",
    "bm25.json": "COURSE_RAG_PERSISTED_LEXICAL_INDEX",
    "child_vectors.npy": "COURSE_RAG_PERSISTED_DENSE_INDEX",
    "child_ids.json": "COURSE_RAG_PERSISTED_DENSE_INDEX_IDS",
    "index_manifest.json": "COURSE_RAG_PERSISTED_HYBRID_MANIFEST",
    "rrf.json": "COURSE_RAG_PERSISTED_FUSION_CONFIG",
}

KNOWN_DERIVED_HASHES = {
    "3c4e6c90c286c27bad482aa275278d79c86ae3db7bf39a9bac98abefd2d681f7",
    "eb5dba23451ace6bb5bd0e794796c6c4ce401e0db5aa99f1bbbac5137eddd02f",
    "2b7c62c7dcdbc4da1178f8906e9693711a1833e6c272cc1c839d8ef2354f335c",
    "6219e0f96370891920094ae3690eb3904adc2eb261b6c6f3633cac92c7eab3dc",
    "d83c9097405c388202a773ba6c4cba7c924f9c7eea771a75c29fadfe319bf5bd",
    "f24f8598cc8ab1f14a2b79f8cee85a8a8f5731b93a0732222292119b906f0244",
    "01847ac53395b4ffd67964680e3b05c89f1858fbc77fd0e4161ba7d03afaa237",
    "8db1ebac0e19a750da0f89a6777dcea49f0eac0d26ed04067add701208412e3c",
    "e46607d7abc9ae40ec97f82bf0ece49a6e0f39c8fc25a224b72d4b091284ef3a",
    "d3be6dde9dc063e13bdb5d71b44d93d7ceda0a9d6d08eb45c02ec5746ca39698",
    "e474c0b98c7099136ae80cfb950ab98311bca0f8e2f29c3b9c21c12627479194",
    "863ed569b4f95fc69bba72bec0da0a92678c41558f1317569110a72c89ef3d8e",
    "2a5d797f6c76a565cf2aa8804e8ffb479a4f4d30fa07f8eb130fe35294fa66f2",
    "6563943ae8773c1db88b366c49c25fd8adc0839082d265a14c2f319a95355d26",
    "684c59f4715de14033e1f763363fa264ef3f4f173d427367cb363ee7a35dc7da",
    "b82e6317613e0c978f7b4b9f4c04f4a9a4f0d8eff68e7a62586f8ed43f538047",
    "7c825861560b8dba2b7be4d1915390462a7628637b9aced06c5e3e12e41d432a",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def verify_evaluation_inputs() -> dict[str, str]:
    verified: dict[str, str] = {}
    for name, expected in EXPECTED_INPUT_HASHES.items():
        path = EXTERNAL_EVALUATION_ROOT / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing pre-existing retrieval evaluation source: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Evaluation input hash mismatch for {path}: {actual} != {expected}")
        verified[name] = actual
    return verified


def _spotlight_paths(name: str) -> set[Path]:
    paths: set[Path] = set()
    for root in (Path("/Users/liuming/Downloads"), Path("/Users/liuming/Documents")):
        result = subprocess.run(
            ["mdfind", "-onlyin", str(root), f"kMDItemFSName == '{name}'"],
            check=True,
            text=True,
            capture_output=True,
        )
        paths.update(Path(line) for line in result.stdout.splitlines() if line.strip())
    return {path.resolve() for path in paths if path.is_file()}


def _inventory_path_allowed(path: Path, name: str) -> bool:
    value = str(path)
    if name == "manifest.jsonl":
        return path.parent.name == "course_materials_v2"
    course_rag_only = {
        "SNAPSHOT_MANIFEST.json",
        "handbook.normalized.html",
        "navigation.normalized.txt",
        "reading_list.normalized.txt",
        "weekly_page.sanitized.html",
        "parents.jsonl",
        "children.jsonl",
        "bm25.json",
        "child_vectors.npy",
        "child_ids.json",
        "index_manifest.json",
        "rrf.json",
    }
    if name in course_rag_only:
        return "duteaiapp_course_rag_mvp" in value
    return True


def _format_for(path: Path) -> str:
    if path.name == "Module Handbook.doc":
        return "legacy_doc_filename_html_content"
    return {
        ".html": "html",
        ".docx": "docx",
        ".pdf": "pdf",
        ".txt": "utf8_text",
        ".py": "python_source",
        ".json": "json",
        ".jsonl": "jsonl",
        ".npy": "numpy_array",
    }.get(path.suffix.casefold(), path.suffix.lstrip(".") or "unknown")


def _parseability(path: Path, digest: str, cache: dict[str, str]) -> str:
    if digest in cache:
        return cache[digest]
    try:
        suffix = path.suffix.casefold()
        if path.name == "Module Handbook.doc":
            text = path.read_text(encoding="latin-1")
            if "<html" not in text.casefold():
                raise ValueError("legacy .doc is not the expected HTML content")
        elif suffix in {".html", ".txt"}:
            path.read_text(encoding="utf-8", errors="strict")
        elif suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"))
        elif suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif suffix == ".jsonl":
            read_jsonl(path)
        elif suffix == ".npy":
            import numpy as np

            np.load(path, mmap_mode="r", allow_pickle=False)
        elif suffix == ".pdf":
            # Canonical copies were already extracted into the verified corpus;
            # byte-identical duplicates inherit that parse check.
            if not path.read_bytes().startswith(b"%PDF"):
                raise ValueError("missing PDF signature")
        elif suffix == ".docx":
            import zipfile

            if not zipfile.is_zipfile(path):
                raise ValueError("invalid docx container")
        cache[digest] = "PARSEABLE"
    except Exception as exc:  # pragma: no cover - recorded rather than hidden
        cache[digest] = f"UNPARSEABLE:{type(exc).__name__}"
    return cache[digest]


def _tracking_status(path: Path, tracked: set[Path]) -> str:
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError:
        return "EXTERNAL"
    if path in tracked:
        return "TRACKED"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(path)], cwd=PROJECT_ROOT
    ).returncode == 0
    return "IGNORED" if ignored else "UNTRACKED"


def _metadata_availability(kind: str) -> dict[str, bool]:
    if kind in {
        "AUTHENTIC_RAW_WEEKLY_HTML",
        "AUTHENTIC_RAW_READING_LIST_PDF",
        "AUTHENTIC_RAW_MOODLE_LINKS_PDF",
        "AUTHENTIC_CURATED_COURSE_METADATA",
        "LEGACY_PERSISTED_CHUNKS",
        "COURSE_RAG_PERSISTED_PARENT_CHUNKS",
        "COURSE_RAG_PERSISTED_CHILD_CHUNKS",
    }:
        return {"week": True, "section": True}
    if kind in {
        "AUTHENTIC_RAW_HANDBOOK_HTML_IN_DOC",
        "COURSE_RAG_DERIVED_SOURCE_SNAPSHOT",
        "AUTHENTIC_REFERENCE_METADATA",
    }:
        return {"week": False, "section": True}
    return {"week": False, "section": False}


def build_source_registry() -> dict[str, Any]:
    tracked = {
        (PROJECT_ROOT / line).resolve()
        for line in subprocess.run(
            ["git", "ls-files"], cwd=PROJECT_ROOT, check=True, text=True, capture_output=True
        ).stdout.splitlines()
    }
    parse_cache: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    raw_hashes = set(EXPECTED_SOURCE_HASHES.values())
    for name, kind in SOURCE_SPECS.items():
        paths = sorted(
            (path for path in _spotlight_paths(name) if _inventory_path_allowed(path, name)),
            key=str,
        )
        for path in paths:
            digest = sha256_file(path)
            if digest in raw_hashes:
                authenticity = "AUTHENTIC_FROZEN_SOURCE_HASH_MATCH"
            elif digest in KNOWN_DERIVED_HASHES:
                authenticity = "LEGACY_DERIVED_ARTIFACT_HASH_MATCH"
            else:
                authenticity = "ACCESSIBLE_CANDIDATE_NOT_HASH_BOUND"
            metadata = _metadata_availability(kind)
            records.append(
                {
                    "source_kind": kind,
                    "exact_path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": digest,
                    "format": _format_for(path),
                    "parseability": _parseability(path, digest, parse_cache),
                    "tracked_ignored_external_status": _tracking_status(path, tracked),
                    "apparent_source_authenticity": authenticity,
                    "week_metadata_available": metadata["week"],
                    "section_metadata_available": metadata["section"],
                    "duplicate_content_group": f"sha256:{digest}",
                    "canonical_runtime_source": str(path).startswith(str(CANONICAL_CFULL_ROOT))
                    or path == (PROJECT_ROOT / "utils/course_metadata.py"),
                }
            )
    records.sort(key=lambda row: (row["source_kind"], row["exact_path"]))
    text_bearing = [
        row
        for row in records
        if row["source_kind"].startswith("AUTHENTIC_")
        and row["source_kind"] != "AUTHENTIC_RAW_HANDBOOK_DOCX"
        and row["parseability"] == "PARSEABLE"
    ]
    by_kind = Counter(row["source_kind"] for row in records)
    return {
        "schema_version": "course-source-registry-v1",
        "evaluation_date": EVALUATION_DATE,
        "discovery_scope": {
            "roots": ["/Users/liuming/Downloads", "/Users/liuming/Documents"],
            "method": "macOS Spotlight exact-filename discovery plus canonical hash verification",
            "filename_allowlist": sorted(SOURCE_SPECS),
            "raw_course_documents_copied_into_track": False,
        },
        "authentic_text_bearing_course_corpus_available": bool(text_bearing),
        "canonical_corpus_root": str(CANONICAL_CFULL_ROOT),
        "expected_frozen_source_hashes": EXPECTED_SOURCE_HASHES,
        "missing_expected_paths_in_rq3_worktree": [
            str(PROJECT_ROOT / relative)
            for relative in EXPECTED_SOURCE_HASHES
            if relative != "utils/course_metadata.py" and not (PROJECT_ROOT / relative).exists()
        ],
        "summary": {
            "record_count": len(records),
            "unique_content_hash_count": len({row["sha256"] for row in records}),
            "authentic_text_bearing_record_count": len(text_bearing),
            "records_by_kind": dict(sorted(by_kind.items())),
            "unparseable_record_count": sum(
                not row["parseability"].startswith("PARSEABLE") for row in records
            ),
            "unverified_candidate_count": sum(
                row["apparent_source_authenticity"] == "ACCESSIBLE_CANDIDATE_NOT_HASH_BOUND"
                for row in records
            ),
        },
        "records": records,
    }


def _selected_case_ids(unified: Sequence[Mapping[str, Any]], rag_ids: set[str]) -> set[str]:
    selected: set[str] = set()
    for row in unified:
        source_dataset = str(row.get("source_dataset") or "")
        source_id = str(row.get("source_scenario_id") or "")
        group = str(row.get("scenario_group") or "")
        if source_dataset == "rag_diagnostic" and source_id in rag_ids:
            selected.add(str(row["scenario_id"]))
        elif source_dataset == "main_benchmark" and source_id in {"S023", "S024"}:
            selected.add(str(row["scenario_id"]))
        elif group in {"hybrid_memory_and_retrieval", "hybrid_evidence_and_retrieval"}:
            selected.add(str(row["scenario_id"]))
    return selected


def load_evaluation_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    input_hashes = verify_evaluation_inputs()
    raw_rag = read_jsonl(EXTERNAL_EVALUATION_ROOT / "rag_scenarios.jsonl")
    original = read_jsonl(EXTERNAL_EVALUATION_ROOT / "scenarios.jsonl")
    unified = read_jsonl(EXTERNAL_EVALUATION_ROOT / "unified_benchmark_scenarios.jsonl")
    references = {
        row["scenario_id"]: row
        for row in read_jsonl(EXTERNAL_EVALUATION_ROOT / "unified_reference_evidence_v1.jsonl")
    }
    rag_ids = {str(row["scenario_id"]) for row in raw_rag}
    selected_ids = _selected_case_ids(unified, rag_ids)
    rows: list[dict[str, Any]] = []
    for row in unified:
        if str(row["scenario_id"]) not in selected_ids:
            continue
        reference = references[str(row["scenario_id"])]
        gold_chunks = list(reference.get("reference_course_evidence") or [])
        gold_ids = [str(value) for value in reference.get("reference_chunk_ids") or []]
        gold_strengths = {
            str(value.get("chunk_id")): _evidence_strength(_ReferenceChunk(value)).value
            for value in gold_chunks
        }
        source_files = [str(value.get("source_file") or "") for value in gold_chunks]
        expected_documents = [source_identity(value)[0] for value in source_files if value]
        rows.append(
            {
                "scenario_id": str(row["scenario_id"]),
                "source_dataset": str(row.get("source_dataset") or ""),
                "source_scenario_id": str(row.get("source_scenario_id") or ""),
                "scenario_group": str(row.get("scenario_group") or ""),
                "query": str(row.get("student_query") or ""),
                "current_page": str(row.get("page") or ""),
                "visible_history": row.get("conversation_history") or [],
                "query_type": str(row.get("gold_query_type") or row.get("query_type") or ""),
                "retrieval_enabled": bool(row.get("gold_expected_retrieval")),
                "gold_chunk_ids": gold_ids,
                "gold_evidence_strength_by_chunk": gold_strengths,
                "expected_document_ids": list(dict.fromkeys(expected_documents)),
                "expected_topics": list(row.get("expected_topics") or []),
            }
        )
    rows.sort(key=lambda value: value["scenario_id"])
    covered_rag = {
        row["source_scenario_id"] for row in rows if row["source_dataset"] == "rag_diagnostic"
    }
    covered_original = {
        row["source_scenario_id"] for row in rows if row["source_dataset"] == "main_benchmark"
    }
    if covered_rag != rag_ids:
        raise ValueError(f"Not all raw RAG scenarios are covered: {sorted(rag_ids - covered_rag)}")
    if covered_original != {"S023", "S024"}:
        raise ValueError("Original 25-scenario course-evidence subset was not covered exactly")
    provenance = {
        "input_hashes": input_hashes,
        "raw_rag_scenarios_total": len(raw_rag),
        "raw_rag_scenarios_covered": len(covered_rag),
        "original_scenarios_total": len(original),
        "original_course_evidence_applicable_ids": sorted(covered_original),
        "unified_union_case_count": len(rows),
        "unified_selected_ids": [row["scenario_id"] for row in rows],
        "deduplication": "Unified records retain each raw RAG and applicable original source ID once; handwritten hybrid cases are added once.",
        "reference_evidence_review_statuses": sorted(
            {str(references[row["scenario_id"]].get("review_status") or "") for row in rows}
        ),
        "reference_evidence_limitation": "Existing reference evidence has its own approved/revised review status; this Track measures retrieval only and does not score generated-answer quality.",
    }
    return rows, provenance


class _ReferenceChunk:
    def __init__(self, value: Mapping[str, Any]) -> None:
        self.chunk_id = value.get("chunk_id")
        self.source_file = value.get("source_file")
        self.source_type = value.get("source_type")
        self.title = value.get("title")
        self.text = value.get("text")
        self.week = value.get("week")
        self.page = value.get("page")
        self.task_type = value.get("task_type")
        self.metadata = value.get("metadata") or {}


def _entity_targets(case: Mapping[str, Any]) -> list[str]:
    targets: list[str] = []
    match = re.search(r"\b(?:w|week\s*)(10|[1-9])\b", str(case["query"]), flags=re.I)
    if match:
        targets.append(f"w{match.group(1)}")
    if re.search(r"\bpart\s+a\b", str(case["query"]), flags=re.I):
        targets.append("part a")
    generic = {
        "reflection", "reflective writing", "debate", "forum", "readings", "link",
        "assessment", "laboratory coat", "w4", "w5",
    }
    for topic in case.get("expected_topics") or []:
        value = str(topic).strip().casefold()
        if value and value not in generic and value not in targets:
            targets.append(value)
    return targets


def _ndcg(relevance: Sequence[int], relevant_count: int, k: int = 5) -> float:
    dcg = sum(value / math.log2(rank + 1) for rank, value in enumerate(relevance[:k], start=1))
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(relevant_count, k) + 1))
    return dcg / ideal if ideal else 0.0


def score_case(case: Mapping[str, Any], envelope: RetrievalEnvelope) -> dict[str, Any]:
    selected = list(envelope.selected_chunks)
    ids = [item.chunk_id for item in selected]
    gold_ids = list(case["gold_chunk_ids"])
    gold_set = set(gold_ids)
    relevance = [int(value in gold_set) for value in ids]
    first_relevant = next((index for index, value in enumerate(relevance, start=1) if value), None)
    expected_docs = set(case["expected_document_ids"])
    no_result_expected = not gold_ids
    top_strength = (
        selected[0].evidence_strength.value if selected else EvidenceStrength.NO_RESULT.value
    )
    expected_strengths = set(case["gold_evidence_strength_by_chunk"].values())
    if no_result_expected:
        evidence_strength_correct = top_strength == EvidenceStrength.NO_RESULT.value
    else:
        evidence_strength_correct = bool(
            selected
            and selected[0].chunk_id in gold_set
            and top_strength in expected_strengths
        )
    targets = _entity_targets(case) if gold_ids else []
    selected_text = " ".join(
        " ".join(
            (
                item.chunk_id,
                item.document_title,
                item.week or "",
                item.section or "",
                item.text,
            )
        ).casefold()
        for item in selected[:5]
    )
    entity_correct = bool(targets) and all(target in selected_text for target in targets)
    metadata_intent = bool(
        re.search(
            r"\b(?:where is|link|which reference|what readings|readings should)\b",
            str(case["query"]),
            flags=re.I,
        )
    )
    unsupported_top = bool(
        gold_ids
        and not metadata_intent
        and selected
        and selected[0].evidence_strength
        in {
            EvidenceStrength.TITLE_AND_METADATA_ONLY,
            EvidenceStrength.LINK_ONLY,
            EvidenceStrength.WEAK_MATCH,
        }
    )
    return {
        "scenario_id": case["scenario_id"],
        "source_dataset": case["source_dataset"],
        "source_scenario_id": case["source_scenario_id"],
        "scenario_group": case["scenario_group"],
        "query": case["query"],
        "current_page": case["current_page"],
        "retrieval_enabled": case["retrieval_enabled"],
        "gold_chunk_ids": gold_ids,
        "gold_evidence_strength_by_chunk": case["gold_evidence_strength_by_chunk"],
        "expected_document_ids": case["expected_document_ids"],
        "expected_topics": case["expected_topics"],
        "result_status": envelope.result_status.value,
        "selected_chunk_ids": ids,
        "selected_document_ids": [item.document_id for item in selected],
        "selected_evidence_strengths": [item.evidence_strength.value for item in selected],
        "lexical_scores": [item.lexical_score for item in selected],
        "dense_scores": [item.dense_score for item in selected],
        "fusion_ranks": [item.fusion_rank for item in selected],
        "source_sha256s": [item.source_sha256 for item in selected],
        "limitations": list(envelope.limitations),
        "recall_at_1": (sum(relevance[:1]) / len(gold_ids)) if gold_ids else None,
        "recall_at_3": (sum(relevance[:3]) / len(gold_ids)) if gold_ids else None,
        "recall_at_5": (sum(relevance[:5]) / len(gold_ids)) if gold_ids else None,
        "reciprocal_rank": (1.0 / first_relevant) if first_relevant else 0.0,
        "ndcg_at_5": _ndcg(relevance, len(gold_ids), 5) if gold_ids else None,
        "source_document_correct_top_1": bool(
            selected and expected_docs and selected[0].document_id in expected_docs
        ) if expected_docs else None,
        "chunk_correct_top_1": bool(selected and selected[0].chunk_id in gold_set) if gold_ids else None,
        "evidence_strength_correct": evidence_strength_correct,
        "entity_targets": targets,
        "exact_week_entity_correct": entity_correct if targets else None,
        "no_result_expected": no_result_expected,
        "no_result_correct": (not selected) if no_result_expected else None,
        "weak_match": any(
            item.evidence_strength == EvidenceStrength.WEAK_MATCH for item in selected
        ),
        "title_link_only_unsupported_top": unsupported_top,
        "latency_ms": envelope.latency_ms,
    }


def _mean(values: Iterable[float | bool | None]) -> float | None:
    rows = [float(value) for value in values if value is not None]
    return sum(rows) / len(rows) if rows else None


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latencies = sorted(float(row["latency_ms"]) for row in rows)

    def percentile(p: float) -> float:
        if not latencies:
            return 0.0
        position = (len(latencies) - 1) * p
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return latencies[lower]
        return latencies[lower] + (latencies[upper] - latencies[lower]) * (position - lower)

    evidence_rows = [row for row in rows if row["gold_chunk_ids"]]
    no_result_rows = [row for row in rows if row["no_result_expected"]]
    entity_rows = [row for row in rows if row["exact_week_entity_correct"] is not None]
    return {
        "case_count": len(rows),
        "evidence_case_count": len(evidence_rows),
        "no_result_case_count": len(no_result_rows),
        "entity_week_case_count": len(entity_rows),
        "evidence_recall_at_1": _mean(row["recall_at_1"] for row in evidence_rows),
        "evidence_recall_at_3": _mean(row["recall_at_3"] for row in evidence_rows),
        "evidence_recall_at_5": _mean(row["recall_at_5"] for row in evidence_rows),
        "mrr": _mean(row["reciprocal_rank"] for row in evidence_rows),
        "ndcg_at_5": _mean(row["ndcg_at_5"] for row in evidence_rows),
        "source_document_accuracy_top_1": _mean(
            row["source_document_correct_top_1"] for row in rows
        ),
        "chunk_accuracy_top_1": _mean(row["chunk_correct_top_1"] for row in rows),
        "evidence_strength_accuracy": _mean(row["evidence_strength_correct"] for row in rows),
        "exact_week_entity_accuracy": _mean(
            row["exact_week_entity_correct"] for row in entity_rows
        ),
        "no_result_accuracy": _mean(row["no_result_correct"] for row in no_result_rows),
        "weak_match_rate": _mean(row["weak_match"] for row in rows),
        "title_link_only_unsupported_rate": _mean(
            row["title_link_only_unsupported_top"] for row in rows
        ),
        "latency_ms": {
            "mean": statistics.mean(latencies) if latencies else 0.0,
            "median": statistics.median(latencies) if latencies else 0.0,
            "p95": percentile(0.95),
            "maximum": max(latencies) if latencies else 0.0,
        },
    }


def _round_metrics(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_metrics(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_metrics(item) for item in value]
    return value


def select_implementation(metrics: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    preference = [
        ("evidence_recall_at_5", "higher"),
        ("mrr", "higher"),
        ("no_result_accuracy", "higher"),
        ("title_link_only_unsupported_rate", "lower"),
        ("exact_week_entity_accuracy", "higher"),
        ("latency_ms.mean", "lower"),
    ]
    trace: list[dict[str, Any]] = []

    def value(method: str, field: str) -> float:
        if field == "latency_ms.mean":
            return float(metrics[method]["latency_ms"]["mean"])
        return float(metrics[method][field])

    for field, direction in preference:
        r0 = value(R0_ID, field)
        r1 = value(R1_ID, field)
        row = {"criterion": field, "preference": direction, "R0": r0, "R1": r1}
        if math.isclose(r0, r1, rel_tol=0.0, abs_tol=1e-12):
            row["outcome"] = "TIE_CONTINUE"
            trace.append(row)
            continue
        if direction == "higher":
            winner = R0_ID if r0 > r1 else R1_ID
        else:
            winner = R0_ID if r0 < r1 else R1_ID
        row["outcome"] = f"SELECT_{winner}"
        trace.append(row)
        return winner, trace
    trace.append(
        {
            "criterion": "exact_tie_simplicity",
            "preference": "R0 wins exact ties",
            "outcome": f"SELECT_{R0_ID}",
        }
    )
    return R0_ID, trace


def _write_results_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )


def _code_hashes() -> dict[str, str]:
    paths = sorted((PROJECT_ROOT / "utils/c4_rag").glob("*.py"))
    paths.extend(sorted(OUTPUT_DIR.glob("*.py")))
    return {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in paths}


def _model_hashes() -> dict[str, str]:
    return {
        name: sha256_file(CANONICAL_MPNET_ROOT / name)
        for name in ("config.json", "model.safetensors", "tokenizer.json", "modules.json")
    }


def _package_version(name: str) -> str | None:
    try:
        module = __import__(name)
        return str(getattr(module, "__version__", "unknown"))
    except Exception:
        return None


def identity_artifacts(
    registry_hash: str,
    corpus_hash: str,
    chunk_count: int,
    hybrid: C4RAGHybrid,
) -> tuple[dict[str, Any], dict[str, Any]]:
    code_hashes = _code_hashes()
    shared = {
        "evaluation_date": EVALUATION_DATE,
        "canonical_corpus_root": str(CANONICAL_CFULL_ROOT),
        "course_source_registry_sha256": registry_hash,
        "source_hashes": EXPECTED_SOURCE_HASHES,
        "chunk_count": chunk_count,
        "chunk_corpus_hash": corpus_hash,
        "top_k": 5,
        "response_generation_calls": 0,
        "provider_network_calls": 0,
        "streamlit_execution": False,
        "rq3_outcome_scoring": False,
    }
    r0 = {
        "schema_version": "c4-rag-r0-identity-v1",
        "implementation_id": R0_ID,
        **shared,
        "status": "FROZEN_LEGACY_REPRODUCTION",
        "legacy_code_hashes": {
            path: sha256_file(PROJECT_ROOT / path)
            for path in (
                "utils/course_material_retriever.py",
                "utils/c_full_service.py",
                "utils/c_full_retrieval_adapter.py",
                "utils/retrieval_v2/sufficiency.py",
                "course_materials_v2/manifest.jsonl",
                "evaluation/outputs/retrieval_v2/index_v2_4/index_metadata_v2_4.json",
            )
        },
        "adapter_code_hashes": {
            key: value for key, value in code_hashes.items() if key.startswith("utils/c4_rag/")
        },
        "behaviour": {
            "legacy_entrypoint": "utils.course_material_retriever.retrieve_course_chunks",
            "legacy_ranking_modified": False,
            "legacy_threshold_modified": False,
            "legacy_chunk_ids_modified": False,
            "external_source_path_binding_only": True,
            "source_scope_authority": "upstream P3 and C_FULL source-scope decision",
        },
    }
    r1 = {
        "schema_version": "c4-rag-r1-identity-v1",
        "implementation_id": R1_ID,
        **shared,
        "status": "EVALUATED_HYBRID_CANDIDATE",
        "code_hashes": code_hashes,
        "architecture": {
            "chunks": "same deterministic legacy chunk IDs with title/week/page/section metadata",
            "lexical": {"algorithm": "field-aware BM25", "k1": 1.5, "b": 0.75},
            "dense": dict(hybrid.embedder.identity),
            "metadata_filters": ["week", "document/source", "current page", "task type"],
            "fusion": {
                "algorithm": "deterministic weighted reciprocal-rank fusion",
                "rrf_constant": hybrid.rrf_constant,
                "lexical_votes": 2,
                "dense_votes": 1,
            },
            "candidate_depth_per_ranker": 50,
            "cross_encoder": False,
            "fine_tuning": False,
            "external_embedding_api_calls": 0,
        },
        "model_file_hashes": _model_hashes(),
        "runtime": {
            "python": platform.python_version(),
            "executable": sys.executable,
            "numpy": _package_version("numpy"),
            "torch": _package_version("torch"),
            "transformers": _package_version("transformers"),
        },
    }
    return r0, r1


def _metric_table(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [
        ("Recall@1", "evidence_recall_at_1"),
        ("Recall@3", "evidence_recall_at_3"),
        ("Recall@5", "evidence_recall_at_5"),
        ("MRR", "mrr"),
        ("nDCG@5", "ndcg_at_5"),
        ("Source/document acc.", "source_document_accuracy_top_1"),
        ("Chunk acc.@1", "chunk_accuracy_top_1"),
        ("Evidence-strength acc.", "evidence_strength_accuracy"),
        ("Exact week/entity acc.", "exact_week_entity_accuracy"),
        ("No-result acc.", "no_result_accuracy"),
        ("Weak-match rate", "weak_match_rate"),
        ("Title/link unsupported rate", "title_link_only_unsupported_rate"),
    ]
    lines = ["| Metric | R0 | R1 |", "|---|---:|---:|"]
    for label, field in rows:
        lines.append(
            f"| {label} | {metrics[R0_ID][field]:.6f} | {metrics[R1_ID][field]:.6f} |"
        )
    lines.append(
        f"| Mean latency ms | {metrics[R0_ID]['latency_ms']['mean']:.3f} | {metrics[R1_ID]['latency_ms']['mean']:.3f} |"
    )
    return "\n".join(lines)


def write_reports(
    output_dir: Path,
    registry: Mapping[str, Any],
    provenance: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
    selected: str,
    trace: Sequence[Mapping[str, Any]],
    corpus_hash: str,
    chunk_count: int,
) -> None:
    decisive = next((row for row in trace if str(row.get("outcome", "")).startswith("SELECT_")), trace[-1])
    report = f"""# RQ3-REAL-C4 Track R Course-RAG results

## Corpus/source status

- Status: `AUTHENTIC_TEXT_BEARING_COURSE_CORPUS_RECOVERED`.
- {registry['summary']['record_count']} accessible source/manifest/index path records were registered; {registry['summary']['unique_content_hash_count']} unique byte identities.
- All six frozen canonical source hashes passed. The RQ3 worktree itself remains sparse; raw documents were neither copied into it nor embedded in this report.
- Recovered legacy corpus: {chunk_count} unique deterministic chunks, corpus hash `{corpus_hash}`.

## R0 identity and reproduction

- `{R0_ID}` calls the unchanged `utils/course_material_retriever.py` entrypoint.
- Only the verified external source paths are rebound in process; code, thresholds, scoring, chunking, and chunk IDs remain unchanged.
- Source-scope and evidence-sufficiency control hashes are recorded in `c4_rag_r0_identity_v1.json`.

## R1 architecture

- `{R1_ID}` uses the same chunks and provenance, field-aware BM25, frozen local `all-mpnet-base-v2@{MPNET_REVISION}` embeddings, metadata filters, and deterministic weighted RRF.
- Zero fine-tuning, zero external embedding calls, and no cross-encoder.
- Evidence classes are enforced per selected item; only `FULL_TEXT_SUPPORT`, `BODY_EXCERPT`, and `SUMMARY_SUPPORT` may support substantive claims.

## Retrieval evaluation

- Union: {provenance['unified_union_case_count']} cases, covering all {provenance['raw_rag_scenarios_total']} raw RAG scenarios, the two course-applicable cases from the original 25-scenario bank, and three pre-existing unified hybrid cases.
- Existing reference-evidence status: `{', '.join(provenance['reference_evidence_review_statuses'])}`. This limits the result to retrieval engineering evidence, not final answer-quality Gold.

{_metric_table(metrics)}

## Selected implementation

- Selected: `{selected}`.
- Decisive preference step: `{decisive.get('criterion')}` ({decisive.get('outcome')}).
- The full predeclared lexicographic trace is in `retrieval_comparison_v1.json`; no method was selected from one favourable metric outside that order.
- Frozen only for later C4 integration. C4 integration was not performed.

## Guard and execution boundary

- No student answers were generated.
- No OpenAI/provider/Judge calls were made.
- Streamlit was not executed or modified.
- The frozen RQ2 P3 Specialist was not modified.
- No unrelated Dashboard evidence fallback exists in the provider.
- Test command: `PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/bioredirect/bin/python3.11 -m unittest evaluation.rq3_real_c4.track_r_rag.test_track_r_rag`.
"""
    (output_dir / "REAL_C4_RAG_RESULTS.md").write_text(report, encoding="utf-8")
    status = f"""# STATUS

`TRACK_R_RETRIEVAL_EVALUATED_AWAITING_FINAL_VALIDATION`

- Corpus gate: PASS
- R0 reproduction: COMPLETE
- R1 hybrid candidate: COMPLETE
- Retrieval-only evaluation: COMPLETE
- Selected implementation: `{selected}`
- Generation/provider calls: ZERO
- C4 integration: NOT STARTED
- Commit and review ZIP: PENDING FINAL VALIDATION
"""
    (output_dir / "STATUS.md").write_text(status, encoding="utf-8")


def run(output_dir: Path) -> dict[str, Any]:
    if PROJECT_ROOT != CORPUS_PROJECT_ROOT:
        raise ValueError("Project-root resolution mismatch")
    verify_canonical_sources()
    registry = build_source_registry()
    if not registry["authentic_text_bearing_course_corpus_available"]:
        raise RuntimeError("BLOCKED_MISSING_AUTHENTIC_COURSE_CORPUS")
    output_dir.mkdir(parents=True, exist_ok=True)
    registry_path = output_dir / "course_source_registry_v1.json"
    write_json(registry_path, registry)

    cases, provenance = load_evaluation_cases()
    chunks = load_legacy_chunks()
    corpus_hash = legacy_chunk_corpus_hash(chunks)
    r0 = C4RAGLegacyLexical()
    r1 = C4RAGHybrid(chunks=chunks)
    methods = {R0_ID: r0, R1_ID: r1}
    scored: dict[str, list[dict[str, Any]]] = {R0_ID: [], R1_ID: []}
    for method_id, retriever in methods.items():
        for case in cases:
            envelope = retriever.retrieve(
                case["query"],
                case["current_page"],
                case["visible_history"],
                top_k=5,
                retrieval_enabled=bool(case["retrieval_enabled"]),
                query_type=str(case["query_type"]),
            )
            scored[method_id].append(score_case(case, envelope))
        # Ranking determinism check in the same process; latency is excluded.
        probe = cases[0]
        first = retriever.retrieve(
            probe["query"], probe["current_page"], probe["visible_history"],
            top_k=5, retrieval_enabled=bool(probe["retrieval_enabled"]),
            query_type=str(probe["query_type"]),
        )
        second = retriever.retrieve(
            probe["query"], probe["current_page"], probe["visible_history"],
            top_k=5, retrieval_enabled=bool(probe["retrieval_enabled"]),
            query_type=str(probe["query_type"]),
        )
        if first.chunk_ids != second.chunk_ids:
            raise AssertionError(f"Non-deterministic ranking for {method_id}")

    metrics_raw = {method: aggregate(rows) for method, rows in scored.items()}
    selected, selection_trace = select_implementation(metrics_raw)
    metrics = _round_metrics(metrics_raw)
    _write_results_csv(output_dir / "retrieval_results_r0_v1.csv", scored[R0_ID])
    _write_results_csv(output_dir / "retrieval_results_r1_v1.csv", scored[R1_ID])

    registry_hash = sha256_file(registry_path)
    r0_identity, r1_identity = identity_artifacts(
        registry_hash, corpus_hash, len(chunks), r1
    )
    write_json(output_dir / "c4_rag_r0_identity_v1.json", r0_identity)
    write_json(output_dir / "c4_rag_r1_identity_v1.json", r1_identity)
    comparison = {
        "schema_version": "retrieval-comparison-v1",
        "evaluation_date": EVALUATION_DATE,
        "evaluation_provenance": provenance,
        "metrics": metrics,
        "predeclared_preference_order": [
            "higher evidence Recall@5",
            "higher MRR",
            "higher no-result accuracy",
            "lower weak/title-only unsupported rate",
            "higher exact entity/week accuracy",
            "lower latency",
            "R0 wins exact ties because it is simpler",
        ],
        "selection_trace": _round_metrics(selection_trace),
        "selected_implementation_id": selected,
        "generation_or_judge_metrics_included": False,
    }
    comparison_path = output_dir / "retrieval_comparison_v1.json"
    write_json(comparison_path, comparison)
    selected_identity_path = (
        output_dir / "c4_rag_r0_identity_v1.json"
        if selected == R0_ID
        else output_dir / "c4_rag_r1_identity_v1.json"
    )
    frozen = {
        "schema_version": "selected-c4-rag-frozen-v1",
        "evaluation_date": EVALUATION_DATE,
        "status": "FROZEN_FOR_LATER_C4_INTEGRATION",
        "selected_implementation_id": selected,
        "selected_identity_file": selected_identity_path.name,
        "selected_identity_sha256": sha256_file(selected_identity_path),
        "retrieval_comparison_sha256": sha256_file(comparison_path),
        "preference_trace": _round_metrics(selection_trace),
        "write_count": 1,
        "overwrite_permitted": False,
        "c4_integration_executed": False,
        "response_generation_calls": 0,
        "provider_network_calls": 0,
        "judge_calls": 0,
        "rq3_outcome_scoring": False,
    }
    write_json(output_dir / "selected_c4_rag_frozen_v1.json", frozen)
    write_reports(
        output_dir, registry, provenance, metrics, selected, selection_trace, corpus_hash, len(chunks)
    )
    return {
        "selected": selected,
        "metrics": metrics,
        "source_records": registry["summary"]["record_count"],
        "chunk_count": len(chunks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    result = run(args.output_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
