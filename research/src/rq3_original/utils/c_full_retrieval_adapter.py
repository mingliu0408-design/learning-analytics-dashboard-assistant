"""Narrow production adapter for C_FULL course-evidence retrieval.

The adapter preserves the historical Retrieval v1 behaviour and exposes the
frozen Retrieval v2.4 lexical system through one normalised contract.  Audit
diagnostics and generator-visible evidence are deliberately separate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from functools import lru_cache
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Literal, Mapping

from utils.course_material_retriever import (
    RetrievalResult,
    chunks_to_dicts,
    retrieve_course_chunks,
    retrieval_result_to_dict,
)


RetrievalBackend = Literal["v1", "v2_4"]
FROZEN_V2_4_INDEX_HASH = "778aa5879b8fe6bb3183139fe66db82ee9fcce3ddcece948b435072fdfa1b683"
FROZEN_V2_4_METADATA_SHA256 = "2b7c62c7dcdbc4da1178f8906e9693711a1833e6c272cc1c839d8ef2354f335c"
V2_4_VERSION = "retrieval_v2.4"


class RetrievalBackendUnavailable(RuntimeError):
    """Raised when a requested persisted retrieval backend cannot be trusted."""


@dataclass(frozen=True)
class CourseEvidenceResult:
    """Normalised C_FULL retrieval result with strict audit/generation isolation."""

    retrieval_backend_requested: str
    retrieval_backend_used: str | None
    retrieval_version: str
    backend_mode: str
    semantic_backend_available: bool
    retrieval_available: bool
    compatibility_result: Any
    audit: dict[str, Any]
    generation: dict[str, Any]
    prompt_text: str | None
    allowed_chunks: list[dict[str, Any]]
    supporting_sources: list[dict[str, Any]]
    warnings: list[str]

    @property
    def retrieval_requested(self) -> bool:
        return bool(self.audit.get("retrieval_requested"))

    @property
    def retrieval_used(self) -> bool:
        return bool(self.audit.get("retrieval_used"))

    @property
    def evidence_sufficiency(self) -> dict[str, Any]:
        return dict(self.audit.get("evidence_sufficiency") or {})

    @property
    def supporting_chunk_ids(self) -> list[str]:
        return list(self.generation.get("supporting_chunk_ids") or [])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def v2_4_streamlit_cache_key(index_dir: Path | None = None) -> tuple[str, str, str]:
    """Return the non-student cache key required for the persisted v2.4 bundle."""

    from utils.retrieval_v2_4.config import DEFAULT_CONFIG_V24

    resolved_dir = Path(index_dir or DEFAULT_CONFIG_V24.index_dir).resolve()
    metadata_path = resolved_dir / "index_metadata_v2_4.json"
    if not metadata_path.is_file():
        raise RetrievalBackendUnavailable(
            "Retrieval v2.4 index metadata is missing; course evidence was not checked."
        )
    return V2_4_VERSION, _sha256_file(metadata_path), str(resolved_dir)


def v2_4_query_plan(query: str) -> dict[str, Any]:
    """Use the frozen v2.4 query analyser without loading or querying the index."""

    from utils.retrieval_v2_4.query_analysis import analyse_query_v24

    return analyse_query_v24(str(query or "")).to_dict()


def v2_4_retrieval_requested(query: str) -> bool:
    return bool(v2_4_query_plan(query).get("retrieval_requested"))


@lru_cache(maxsize=4)
def load_persisted_v2_4_retriever(index_dir: str | Path | None = None) -> Any:
    """Load and validate the frozen lexical bundle without ingestion or rebuilding."""

    from utils.retrieval_v2_4.config import DEFAULT_CONFIG_V24
    from utils.retrieval_v2_4.retriever import CourseMaterialRetrieverV24

    resolved_dir = Path(index_dir or DEFAULT_CONFIG_V24.index_dir).resolve()
    metadata_path = resolved_dir / "index_metadata_v2_4.json"
    if not metadata_path.is_file():
        raise RetrievalBackendUnavailable(
            "Retrieval v2.4 index metadata is missing; course evidence was not checked."
        )
    metadata_sha = _sha256_file(metadata_path)
    if metadata_sha != FROZEN_V2_4_METADATA_SHA256:
        raise RetrievalBackendUnavailable(
            "Retrieval v2.4 index metadata does not match the frozen production bundle; "
            "course evidence was not checked."
        )
    config = replace(DEFAULT_CONFIG_V24, index_dir=resolved_dir)
    try:
        retriever = CourseMaterialRetrieverV24(config=config)
    except Exception as exc:
        raise RetrievalBackendUnavailable(
            "Retrieval v2.4 persisted index is missing, stale, or invalid; "
            "course evidence was not checked."
        ) from exc
    metadata = retriever.index_metadata
    if metadata.get("retrieval_version") != V2_4_VERSION:
        raise RetrievalBackendUnavailable("Unexpected Retrieval v2.4 index version")
    if metadata.get("index_hash") != FROZEN_V2_4_INDEX_HASH:
        raise RetrievalBackendUnavailable("Retrieval v2.4 frozen index hash mismatch")
    if (
        metadata.get("backend_mode") != "lexical_degraded"
        or metadata.get("semantic_backend_available") is not False
    ):
        raise RetrievalBackendUnavailable(
            "Retrieval v2.4 production backend must be lexical_degraded with semantics unavailable"
        )
    return retriever


def _noop_v2_4_result(query: str) -> CourseEvidenceResult:
    sufficiency = {
        "status": "not_applicable",
        "answerable": False,
        "required_content_level": "title_and_metadata",
        "available_content_levels": [],
        "supporting_chunk_ids": [],
        "unsupported_requested_claim_types": [],
        "reason": "Course-material retrieval was not applicable to this query.",
        "user_facing_boundary": "No course-material claim should be added.",
        "allowed_claim_scope": [],
    }
    audit = {
        "query": query,
        "original_query": query,
        "canonical_retrieval_query": query,
        "query_plan": {"retrieval_requested": False, "facets": []},
        "retrieval_requested": False,
        "retrieval_used": False,
        "retrieved_chunks": [],
        "retrieved_chunk_ids": [],
        "retrieved_chunk_titles": [],
        "retrieved_sources": [],
        "evidence_sufficiency": sufficiency,
        "stage_audit": {},
        "candidate_diagnostics": {},
        "reason": sufficiency["reason"],
        "warnings": [],
        "index_version": V2_4_VERSION,
        "retrieval_version": V2_4_VERSION,
        "index_hash": FROZEN_V2_4_INDEX_HASH,
        "backend_mode": "lexical_degraded",
        "semantic_backend_available": False,
        "retrieval_backend_requested": "v2_4",
        "retrieval_backend_used": "v2_4",
        "retrieval_available": True,
        "source_provenance": [],
    }
    generation = {
        "evidence_sufficiency": _generation_sufficiency(sufficiency),
        "supporting_chunk_ids": [],
        "allowed_chunks": [],
    }
    return CourseEvidenceResult(
        retrieval_backend_requested="v2_4",
        retrieval_backend_used="v2_4",
        retrieval_version=V2_4_VERSION,
        backend_mode="lexical_degraded",
        semantic_backend_available=False,
        retrieval_available=True,
        compatibility_result=SimpleNamespace(
            query=query, chunks=[], retrieval_used=False, reason=sufficiency["reason"]
        ),
        audit=audit,
        generation=generation,
        prompt_text=None,
        allowed_chunks=[],
        supporting_sources=[],
        warnings=[],
    )


def _safe_v2_4_chunk(item: Any) -> dict[str, Any]:
    chunk = item.chunk
    return {
        "chunk_id": chunk.chunk_id,
        "source_title": chunk.metadata.get("document_title") or chunk.title,
        "title": chunk.title,
        "week": chunk.week,
        "section": " > ".join(chunk.section_path) or None,
        "page": chunk.page_number,
        "material_type": chunk.material_type,
        "content_level": chunk.content_level,
        "text": chunk.text,
    }


def _source_from_chunk(chunk: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk.get("chunk_id"),
        "source_title": chunk.get("source_title") or chunk.get("title"),
        "title": chunk.get("title"),
        "week": chunk.get("week"),
        "section": chunk.get("section"),
        "page": chunk.get("page"),
        "material_type": chunk.get("material_type"),
        "content_level": chunk.get("content_level"),
    }


def _dedupe_sources(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for chunk in chunks:
        source = _source_from_chunk(chunk)
        identity = (
            source["chunk_id"],
            source["source_title"],
            source["week"],
            source["section"],
            source["page"],
        )
        if identity not in seen:
            seen.add(identity)
            sources.append(source)
    return sources


def _format_generation_prompt(generation: Mapping[str, Any]) -> str:
    sufficiency = generation.get("evidence_sufficiency") or {}
    sections = [
        "Course retrieval status:",
        f"status={sufficiency.get('status')}",
        "Allowed claim scope: "
        + (", ".join(sufficiency.get("allowed_claim_scope") or []) or "none"),
        "Boundary: " + str(sufficiency.get("user_facing_boundary") or ""),
        "Use only approved supporting chunks below for course claims. Do not use general model knowledge to fill missing course evidence.",
    ]
    allowed = list(generation.get("allowed_chunks") or [])
    if not allowed:
        sections.append("No approved course-evidence chunks are available to the generator.")
    for chunk in allowed:
        labels = (
            f"chunk_id={chunk.get('chunk_id')}; source_title={chunk.get('source_title')}; "
            f"week={chunk.get('week') or 'unspecified'}; section={chunk.get('section') or 'unspecified'}; "
            f"page={chunk.get('page') or 'unspecified'}; material_type={chunk.get('material_type')}; "
            f"content_level={chunk.get('content_level')}"
        )
        sections.append(f"[{labels}]\nRelevant text: {chunk.get('text', '')}")
    return "\n\n".join(sections)


def _generation_sufficiency(sufficiency: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the sufficiency fields approved for model generation."""

    return {
        "status": sufficiency.get("status"),
        "allowed_claim_scope": list(sufficiency.get("allowed_claim_scope") or []),
        "user_facing_boundary": str(sufficiency.get("user_facing_boundary") or ""),
        "supporting_chunk_ids": list(sufficiency.get("supporting_chunk_ids") or []),
    }


def _v2_4_result(query: str, top_k: int, retriever: Any) -> CourseEvidenceResult:
    runtime = retriever.retrieve(query, top_k=top_k)
    audit = runtime.to_audit_dict()
    audit.setdefault(
        "retrieved_chunk_titles", [item.chunk.title for item in runtime.retrieved_chunks]
    )
    if runtime.index_hash != FROZEN_V2_4_INDEX_HASH:
        raise RetrievalBackendUnavailable("Retrieval v2.4 frozen index hash mismatch")
    sufficiency = runtime.evidence_sufficiency.to_dict()
    supporting = set(sufficiency["supporting_chunk_ids"])
    allow_content = sufficiency["status"] not in {
        "insufficient",
        "no_result",
        "not_applicable",
    }
    approved_items = [
        item
        for item in runtime.retrieved_chunks
        if allow_content and item.chunk.chunk_id in supporting
    ]
    allowed_chunks = [_safe_v2_4_chunk(item) for item in approved_items]
    sources = _dedupe_sources(allowed_chunks)
    generation = {
        "evidence_sufficiency": _generation_sufficiency(sufficiency),
        "supporting_chunk_ids": [item.chunk.chunk_id for item in approved_items],
        "allowed_chunks": allowed_chunks,
    }
    warnings: list[str] = []
    audit.update(
        {
            "warnings": warnings,
            "retrieval_version": runtime.index_version,
            "retrieval_backend_requested": "v2_4",
            "retrieval_backend_used": "v2_4",
            "retrieval_available": True,
            "source_provenance": sources,
        }
    )
    compatibility = SimpleNamespace(
        query=query,
        chunks=[item.chunk for item in approved_items],
        retrieval_used=bool(approved_items),
        reason=runtime.reason,
    )
    result = CourseEvidenceResult(
        retrieval_backend_requested="v2_4",
        retrieval_backend_used="v2_4",
        retrieval_version=runtime.index_version,
        backend_mode=runtime.backend_mode,
        semantic_backend_available=runtime.semantic_backend_available,
        retrieval_available=True,
        compatibility_result=compatibility,
        audit=audit,
        generation=generation,
        prompt_text=_format_generation_prompt(generation),
        allowed_chunks=allowed_chunks,
        supporting_sources=sources,
        warnings=warnings,
    )
    validate_generation_isolation(result)
    return result


def _unavailable_v2_4(query: str, warning: str) -> CourseEvidenceResult:
    sufficiency = {
        "status": "insufficient",
        "answerable": False,
        "required_content_level": "unknown",
        "available_content_levels": [],
        "supporting_chunk_ids": [],
        "unsupported_requested_claim_types": [],
        "reason": "The configured course-retrieval backend was unavailable.",
        "user_facing_boundary": (
            "Course retrieval is temporarily unavailable, so course evidence was not checked."
        ),
        "allowed_claim_scope": [],
    }
    audit = {
        "query": query,
        "original_query": query,
        "canonical_retrieval_query": query,
        "query_plan": {},
        "retrieval_requested": True,
        "retrieval_used": False,
        "retrieved_chunks": [],
        "retrieved_chunk_ids": [],
        "retrieved_chunk_titles": [],
        "retrieved_sources": [],
        "evidence_sufficiency": sufficiency,
        "stage_audit": {},
        "candidate_diagnostics": {},
        "reason": sufficiency["reason"],
        "warnings": [warning],
        "index_version": V2_4_VERSION,
        "retrieval_version": V2_4_VERSION,
        "index_hash": None,
        "backend_mode": "unavailable",
        "semantic_backend_available": False,
        "retrieval_backend_requested": "v2_4",
        "retrieval_backend_used": None,
        "retrieval_available": False,
        "source_provenance": [],
    }
    generation = {
        "evidence_sufficiency": _generation_sufficiency(sufficiency),
        "supporting_chunk_ids": [],
        "allowed_chunks": [],
    }
    return CourseEvidenceResult(
        retrieval_backend_requested="v2_4",
        retrieval_backend_used=None,
        retrieval_version=V2_4_VERSION,
        backend_mode="unavailable",
        semantic_backend_available=False,
        retrieval_available=False,
        compatibility_result=SimpleNamespace(
            query=query, chunks=[], retrieval_used=False, reason=sufficiency["reason"]
        ),
        audit=audit,
        generation=generation,
        prompt_text=_format_generation_prompt(generation),
        allowed_chunks=[],
        supporting_sources=[],
        warnings=[warning],
    )


def _v1_result(
    query: str,
    query_type: str | None,
    top_k: int,
    retrieval_needed: bool,
    *,
    requested_backend: str = "v1",
) -> CourseEvidenceResult:
    historical = (
        retrieve_course_chunks(query, query_type, top_k=top_k)
        if retrieval_needed
        else RetrievalResult(
            query=query,
            chunks=[],
            retrieval_used=False,
            reason="Course-material retrieval was not needed for this resolved query.",
        )
    )
    audit = retrieval_result_to_dict(historical)
    chunk_values = chunks_to_dicts(historical.chunks)
    supporting = [chunk["chunk_id"] for chunk in chunk_values]
    status = (
        "sufficient"
        if historical.retrieval_used
        else "no_result" if retrieval_needed
        else "not_applicable"
    )
    sufficiency = {
        "status": status,
        "answerable": bool(historical.retrieval_used),
        "required_content_level": "legacy_unspecified",
        "available_content_levels": [],
        "supporting_chunk_ids": supporting,
        "unsupported_requested_claim_types": [],
        "reason": historical.reason,
        "user_facing_boundary": (
            "Use only the retrieved legacy course text."
            if historical.retrieval_used
            else "No relevant legacy course evidence was retrieved."
        ),
        "allowed_claim_scope": ["legacy_course_text"] if historical.retrieval_used else [],
    }
    allowed = [
        {
            "chunk_id": value["chunk_id"],
            "source_title": value["title"],
            "title": value["title"],
            "week": value.get("week"),
            "section": value.get("page"),
            "page": value.get("page"),
            "material_type": value.get("task_type") or value.get("source_type"),
            "content_level": "legacy_unspecified",
            "text": value["text"],
        }
        for value in chunk_values
    ]
    warnings = (
        ["Retrieval v2.4 was unavailable; explicit configuration enabled Retrieval v1 fallback."]
        if requested_backend == "v2_4"
        else []
    )
    generation = {
        "evidence_sufficiency": _generation_sufficiency(sufficiency),
        "supporting_chunk_ids": supporting,
        "allowed_chunks": allowed,
    }
    audit.update(
        {
            "retrieval_requested": retrieval_needed,
            "evidence_sufficiency": sufficiency,
            "retrieval_backend_requested": requested_backend,
            "retrieval_backend_used": "v1",
            "retrieval_available": True,
            "retrieval_version": "retrieval_v1",
            "backend_mode": "legacy_lexical",
            "semantic_backend_available": False,
            "index_hash": None,
            "warnings": warnings,
            "source_provenance": _dedupe_sources(allowed),
        }
    )
    return CourseEvidenceResult(
        retrieval_backend_requested=requested_backend,
        retrieval_backend_used="v1",
        retrieval_version="retrieval_v1",
        backend_mode="legacy_lexical",
        semantic_backend_available=False,
        retrieval_available=True,
        compatibility_result=historical,
        audit=audit,
        generation=generation,
        prompt_text=_format_generation_prompt(generation) if requested_backend == "v2_4" else None,
        allowed_chunks=allowed,
        supporting_sources=_dedupe_sources(allowed),
        warnings=warnings,
    )


def retrieve_course_evidence(
    query: str,
    *,
    backend: RetrievalBackend,
    top_k: int,
    context: Mapping[str, Any] | None = None,
) -> CourseEvidenceResult:
    """Retrieve through v1 or frozen v2.4 and return one stable C_FULL contract."""

    if backend not in {"v1", "v2_4"}:
        raise ValueError("backend must be 'v1' or 'v2_4'")
    options = dict(context or {})
    query = str(query or "").strip()
    query_type = options.get("query_type")
    retrieval_needed = bool(options.get("retrieval_needed", True))
    if backend == "v1":
        return _v1_result(query, query_type, top_k, retrieval_needed)
    if not retrieval_needed:
        return _noop_v2_4_result(query)

    allow_fallback = bool(options.get("allow_v1_fallback", False))
    try:
        injected_error = options.get("v2_4_retriever_error")
        if injected_error:
            raise RetrievalBackendUnavailable(str(injected_error))
        retriever = options.get("v2_4_retriever") or load_persisted_v2_4_retriever()
        return _v2_4_result(query, top_k, retriever)
    except Exception as exc:
        if allow_fallback:
            return _v1_result(
                query,
                query_type,
                top_k,
                retrieval_needed,
                requested_backend="v2_4",
            )
        warning = (
            "Retrieval v2.4 index is unavailable or invalid; course evidence was not checked."
        )
        return _unavailable_v2_4(query, warning)


def validate_generation_isolation(result: CourseEvidenceResult) -> None:
    """Fail closed if any generator-visible chunk is not sufficiency-approved."""

    approved_generation_fields = {
        "evidence_sufficiency",
        "supporting_chunk_ids",
        "allowed_chunks",
    }
    unexpected_generation_fields = set(result.generation) - approved_generation_fields
    if unexpected_generation_fields:
        raise AssertionError(
            "Generator-visible retrieval context leaked audit fields: "
            f"{sorted(unexpected_generation_fields)}"
        )
    approved_sufficiency_fields = {
        "status",
        "allowed_claim_scope",
        "user_facing_boundary",
        "supporting_chunk_ids",
    }
    unexpected_sufficiency_fields = set(
        result.generation.get("evidence_sufficiency") or {}
    ) - approved_sufficiency_fields
    if unexpected_sufficiency_fields:
        raise AssertionError(
            "Generator-visible sufficiency leaked audit fields: "
            f"{sorted(unexpected_sufficiency_fields)}"
        )
    supporting = set(result.evidence_sufficiency.get("supporting_chunk_ids") or [])
    allowed_ids = {str(chunk.get("chunk_id")) for chunk in result.allowed_chunks}
    if allowed_ids - supporting:
        raise AssertionError(
            "Generator-visible course chunks are not all in supporting_chunk_ids"
        )
    if set(result.generation.get("supporting_chunk_ids") or []) != allowed_ids:
        raise AssertionError("Generation supporting IDs do not match approved chunks")
    forbidden_fields = {
        "lexical_rank",
        "fused_rank",
        "rerank_rank",
        "reranker_score",
        "rerank_reasons",
        "gate_reasons",
        "matched_facets",
        "stage_audit",
        "candidate_diagnostics",
        "source_hash",
    }
    for chunk in result.allowed_chunks:
        leaked = forbidden_fields & set(chunk)
        if leaked:
            raise AssertionError(f"Generator-visible chunk leaked audit fields: {sorted(leaked)}")


def validate_prompt_isolation(prompt: str, result: CourseEvidenceResult) -> None:
    """Assert that prompt chunk IDs/text come only from approved supporting evidence."""

    validate_generation_isolation(result)
    supporting = set(result.supporting_chunk_ids)
    prompt_ids = set(re.findall(r"\bv2_[0-9a-f]{20}\b", str(prompt)))
    if prompt_ids - supporting:
        raise AssertionError(
            f"Prompt contains non-supporting course chunk IDs: {sorted(prompt_ids - supporting)}"
        )
    for chunk in result.audit.get("retrieved_chunks") or []:
        if chunk.get("chunk_id") in supporting:
            continue
        rejected_text = str(chunk.get("text") or "").strip()
        if rejected_text and rejected_text in prompt:
            raise AssertionError("Prompt contains rejected/non-supporting course text")


def safe_retrieval_details(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Project runtime audit data into the non-sensitive Streamlit status panel."""

    sufficiency = dict(audit.get("evidence_sufficiency") or {})
    sources = list(audit.get("source_provenance") or [])
    return {
        "backend_requested": audit.get("retrieval_backend_requested"),
        "backend_used": audit.get("retrieval_backend_used"),
        "runtime_mode": audit.get("backend_mode"),
        "semantic_retrieval": (
            "available" if audit.get("semantic_backend_available") else "unavailable"
        ),
        "retrieval_requested": bool(audit.get("retrieval_requested")),
        "retrieval_used": bool(audit.get("retrieval_used")),
        "retrieval_available": bool(audit.get("retrieval_available", True)),
        "sufficiency_status": sufficiency.get("status"),
        "source_titles": [source.get("source_title") for source in sources],
        "source_locations": [
            {
                "week": source.get("week"),
                "section": source.get("section"),
                "page": source.get("page"),
                "material_type": source.get("material_type"),
            }
            for source in sources
        ],
        "supporting_chunk_ids": list(sufficiency.get("supporting_chunk_ids") or []),
        "warnings": list(audit.get("warnings") or []),
        "index_version": audit.get("retrieval_version") or audit.get("index_version"),
        "index_hash": audit.get("index_hash"),
    }


def render_supporting_sources(
    sources: list[Mapping[str, Any]],
    sufficiency_status: str,
) -> list[str]:
    """Render compact, non-fabricated labels for supporting sources only."""

    lines: list[str] = []
    collection_titles = {
        "dute_ai readings",
        "module weekly pages",
        "verified lecture metadata",
    }
    for source in sources:
        source_title = str(source.get("source_title") or "").strip()
        source_title = re.split(r"\s+URL:\s*", source_title, maxsplit=1)[0].strip()
        title = str(source.get("title") or "").strip()
        title = re.split(r"\s+URL:\s*", title, maxsplit=1)[0].strip()
        if source_title and title and source_title != title:
            if source_title.casefold() in collection_titles:
                label = f"{title} — {source_title}"
            elif title.casefold() in collection_titles:
                label = f"{source_title} — {title}"
            else:
                label = source_title
        else:
            label = source_title or title or "Course source"
        if len(label) > 180:
            label = label[:177].rstrip() + "…"
        week = str(source.get("week") or "").strip()
        if week and week.casefold() not in label.casefold():
            label += f" — {week}"
        if source.get("page"):
            label += f" (page {source['page']})"
        if sufficiency_status == "metadata_only":
            label += " — Source identified; full content is not indexed."
        lines.append(label)
    return list(dict.fromkeys(lines))
