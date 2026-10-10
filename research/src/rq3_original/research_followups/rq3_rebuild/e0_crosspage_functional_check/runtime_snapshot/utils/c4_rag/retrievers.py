"""Frozen lexical R0 and small local hybrid R1 implementations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import time
from typing import Any, Iterable, Mapping, Protocol, Sequence

from utils import course_material_retriever as legacy

from .corpus import (
    CANONICAL_MPNET_ROOT,
    MPNET_REVISION,
    legacy_chunk_corpus_hash,
    load_legacy_chunks,
    resolved_hybrid_query,
    section_for_chunk,
    source_identity,
)
from .models import (
    EvidenceStrength,
    RetrievalEnvelope,
    ResultStatus,
    SUBSTANTIVE_STRENGTHS,
    SelectedChunk,
)


R0_ID = "C4_RAG_R0_LEXICAL"
R1_ID = "C4_RAG_R1_HYBRID"

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
        "for", "from", "have", "how", "i", "in", "is", "it", "me", "my", "of",
        "on", "or", "should", "the", "this", "to", "what", "where", "which", "with",
        "you", "your", "course", "material", "materials", "say", "says", "tell", "help",
    }
)


def tokenise(text: str) -> list[str]:
    values: list[str] = []
    for raw in _TOKEN_RE.findall(str(text or "")):
        token = raw.casefold()
        if token.endswith("ies") and len(token) > 5:
            token = token[:-3] + "y"
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
            token = token[:-1]
        values.append(token)
    return values


def content_tokens(text: str) -> set[str]:
    return {token for token in tokenise(text) if token not in _STOPWORDS and len(token) > 1}


def _legacy_query_type(query: str, current_page: str, provided: str | None) -> str:
    if provided:
        return str(provided)
    q = str(query).casefold()
    page = str(current_page or "").casefold()
    if page == "reflection" or "reflect" in q:
        return "reflection_structure_question"
    if page == "debate" or "debate" in q or "forum" in q:
        return "debate_guidance"
    if "link" in q or "where is" in q:
        return "access_or_capability_question"
    return "course_content_question"


def _evidence_strength(chunk: Any, *, strong_match: bool = True) -> EvidenceStrength:
    if not strong_match:
        return EvidenceStrength.WEAK_MATCH
    source_type = str(getattr(chunk, "source_type", ""))
    text = str(getattr(chunk, "text", ""))
    lowered = text.casefold()
    if source_type == "course_metadata":
        return EvidenceStrength.SUMMARY_SUPPORT
    if source_type == "moodle_link":
        return EvidenceStrength.LINK_ONLY
    if source_type in {"reading", "literature"}:
        return EvidenceStrength.TITLE_AND_METADATA_ONLY
    url_count = lowered.count("http://") + lowered.count("https://") + lowered.count(" url")
    word_count = len(tokenise(text))
    if url_count and word_count < 45:
        return EvidenceStrength.LINK_ONLY
    if word_count < 24:
        return EvidenceStrength.TITLE_AND_METADATA_ONLY
    if source_type in {"weekly_page", "handbook"}:
        return EvidenceStrength.BODY_EXCERPT
    return EvidenceStrength.WEAK_MATCH


def _status_for(items: Sequence[SelectedChunk]) -> ResultStatus:
    if not items:
        return ResultStatus.NO_RESULT
    if any(item.evidence_strength in SUBSTANTIVE_STRENGTHS for item in items):
        return ResultStatus.SUPPORTED
    if all(item.evidence_strength == EvidenceStrength.WEAK_MATCH for item in items):
        return ResultStatus.WEAK_MATCH
    return ResultStatus.LIMITED_EVIDENCE


def _selected_chunk(
    chunk: Any,
    *,
    rank: int,
    lexical_score: float | None,
    dense_score: float | None,
    fusion_rank: int | None,
    strong_match: bool = True,
) -> SelectedChunk:
    document_id, document_title, source_hash = source_identity(str(chunk.source_file))
    strength = _evidence_strength(chunk, strong_match=strong_match)
    return SelectedChunk(
        rank=rank,
        chunk_id=str(chunk.chunk_id),
        document_id=document_id,
        document_title=document_title,
        source_path=str(chunk.source_file),
        source_sha256=source_hash,
        source_type=str(chunk.source_type),
        text=str(chunk.text),
        week=str(chunk.week) if chunk.week else None,
        section=section_for_chunk(chunk),
        page=str(chunk.page) if chunk.page else None,
        evidence_strength=strength,
        substantive_claim_support=strength in SUBSTANTIVE_STRENGTHS,
        lexical_score=round(float(lexical_score), 8) if lexical_score is not None else None,
        dense_score=round(float(dense_score), 8) if dense_score is not None else None,
        fusion_rank=fusion_rank,
    )


class C4RAGLegacyLexical:
    """Adapter around the byte-frozen legacy retriever; ranking is unchanged."""

    implementation_id = R0_ID

    def __init__(self) -> None:
        self.chunks = load_legacy_chunks()
        self.corpus_hash = legacy_chunk_corpus_hash(self.chunks)

    def retrieve(
        self,
        student_query: str,
        current_page: str,
        visible_history: Any,
        *,
        top_k: int = 5,
        retrieval_enabled: bool = True,
        query_type: str | None = None,
    ) -> RetrievalEnvelope:
        del visible_history  # Legacy R0 did not consume raw history.
        started = time.perf_counter()
        query = str(student_query or "").strip()
        if not retrieval_enabled or not query:
            return RetrievalEnvelope(
                implementation_id=self.implementation_id,
                query=query,
                result_status=ResultStatus.NO_RESULT,
                selected_chunks=(),
                limitations=("Retrieval was not enabled by the upstream capability decision.",),
                latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )
        effective_query_type = _legacy_query_type(query, current_page, query_type)
        result = legacy.retrieve_course_chunks(
            query,
            query_type=effective_query_type,
            top_k=max(1, int(top_k)),
        )
        items = tuple(
            _selected_chunk(
                chunk,
                rank=rank,
                lexical_score=legacy._score_chunk(query, effective_query_type, chunk),
                dense_score=None,
                fusion_rank=rank,
            )
            for rank, chunk in enumerate(result.chunks, start=1)
        )
        limitations = ["Frozen legacy lexical scoring; no dense representation."]
        if not items:
            limitations.append(result.reason)
        return RetrievalEnvelope(
            implementation_id=self.implementation_id,
            query=query,
            result_status=_status_for(items),
            selected_chunks=items,
            limitations=tuple(limitations),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )


class DenseEmbedder(Protocol):
    identity: Mapping[str, Any]

    def encode(self, texts: Sequence[str]) -> Any: ...


class LocalMPNetEmbedder:
    """Local-only mean-pooled MPNet encoder; no download or hosted API path."""

    def __init__(self) -> None:
        if not CANONICAL_MPNET_ROOT.is_dir():
            raise FileNotFoundError(f"Frozen local MPNet snapshot missing: {CANONICAL_MPNET_ROOT}")
        required = ("config.json", "model.safetensors", "tokenizer.json", "modules.json")
        missing = [name for name in required if not (CANONICAL_MPNET_ROOT / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Frozen local MPNet files missing: {missing}")
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        self._np = np
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(CANONICAL_MPNET_ROOT), local_files_only=True
        )
        self._model = AutoModel.from_pretrained(
            str(CANONICAL_MPNET_ROOT), local_files_only=True
        )
        self._model.eval()
        self.identity = {
            "backend": "LOCAL_TRANSFORMERS_MEAN_POOL_NORMALISE",
            "repo_id": "sentence-transformers/all-mpnet-base-v2",
            "revision": MPNET_REVISION,
            "local_path": str(CANONICAL_MPNET_ROOT),
            "dimension": 768,
            "local_files_only": True,
            "fine_tuning": False,
            "external_embedding_api_calls": 0,
        }

    def encode(self, texts: Sequence[str]) -> Any:
        rows: list[Any] = []
        for start in range(0, len(texts), 16):
            batch = [str(value) for value in texts[start : start + 16]]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=384,
                return_tensors="pt",
            )
            with self._torch.inference_mode():
                hidden = self._model(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
                pooled = self._torch.nn.functional.normalize(pooled, p=2, dim=1)
            rows.append(pooled.cpu().numpy().astype("float32"))
        if not rows:
            return self._np.zeros((0, 768), dtype="float32")
        return self._np.concatenate(rows, axis=0)


class _BM25Field:
    def __init__(self, texts: Sequence[str], *, k1: float, b: float) -> None:
        self.k1 = k1
        self.b = b
        self.documents = [tokenise(text) for text in texts]
        self.frequencies = [Counter(tokens) for tokens in self.documents]
        self.lengths = [len(tokens) for tokens in self.documents]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        document_frequency: Counter[str] = Counter()
        for tokens in self.documents:
            document_frequency.update(set(tokens))
        size = len(self.documents)
        self.idf = {
            term: math.log(1.0 + (size - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }

    def score(self, terms: Sequence[str], index: int) -> float:
        if not self.average_length:
            return 0.0
        frequencies = self.frequencies[index]
        length = self.lengths[index]
        total = 0.0
        for term in terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            denominator = frequency + self.k1 * (
                1.0 - self.b + self.b * length / self.average_length
            )
            total += self.idf.get(term, 0.0) * frequency * (self.k1 + 1.0) / denominator
        return total


class FieldAwareBM25:
    def __init__(self, chunks: Sequence[Any], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = tuple(chunks)
        fields = {
            "title": [str(item.title) for item in chunks],
            "section": [section_for_chunk(item) or "" for item in chunks],
            "body": [str(item.text) for item in chunks],
            "metadata": [
                " ".join(
                    filter(
                        None,
                        (
                            str(item.week or ""),
                            str(item.page or ""),
                            str(item.task_type or ""),
                            str(item.source_type or ""),
                            str(item.source_file or ""),
                        ),
                    )
                )
                for item in chunks
            ],
        }
        self.fields = {
            name: _BM25Field(values, k1=k1, b=b) for name, values in fields.items()
        }
        self.weights = {"title": 3.4, "section": 2.8, "body": 1.0, "metadata": 3.6}

    def scores(self, query: str) -> list[float]:
        terms = tokenise(query)
        return [
            sum(
                self.weights[name] * field.score(terms, index)
                for name, field in self.fields.items()
            )
            for index in range(len(self.chunks))
        ]


def _extract_week(text: str) -> str | None:
    match = re.search(r"\b(?:w|week\s*)(10|[1-9])\b", str(text), flags=re.IGNORECASE)
    return f"W{match.group(1)}" if match else None


def _source_family(chunk: Any) -> str:
    return str(getattr(chunk, "source_type", "")).casefold()


def _metadata_compatible(chunk: Any, query: str, current_page: str) -> bool:
    q = query.casefold()
    requested_week = _extract_week(query)
    if requested_week and chunk.week not in {requested_week, None}:
        return False
    source = _source_family(chunk)
    task = str(getattr(chunk, "task_type", "") or "").casefold()
    haystack = " ".join(
        (str(getattr(chunk, "title", "")), str(getattr(chunk, "text", "")))
    ).casefold()
    page = str(current_page or "").casefold()
    if "handbook" in q and source != "handbook":
        return False
    if re.search(r"\b(?:reference|citation)\b", q) and source != "literature":
        return False
    if re.search(r"\b(?:reading|readings|paper|article)\b", q):
        return source in {"reading", "literature"} or (
            source == "weekly_page" and task == "reading"
        )
    if re.search(r"\b(?:live session link|moodle link|recording link)\b", q):
        return source == "moodle_link" or (
            source == "weekly_page" and task in {"moodle_link", "lecture"}
        )
    if re.search(r"\b(?:lecture|pre-recorded|recorded lecture)\b", q):
        return source == "course_metadata" or (
            source == "weekly_page" and task == "lecture"
        ) or (source == "handbook" and "session" in haystack)
    if "part a" in q or "assessment" in q:
        return source == "handbook" or (
            source == "weekly_page" and task in {"assessment", "reflection"}
        )
    if "reflect" in q and re.search(r"\b(?:structure|writing|part)\b", q):
        return source == "handbook"
    if "debate" in q or "forum" in q:
        return source == "weekly_page" and task == "debate"
    if page == "reflection":
        return source in {"handbook", "weekly_page", "literature", "course_metadata"}
    if page == "debate":
        return source in {"weekly_page", "moodle_link", "handbook"}
    if page == "lecture":
        return source in {"course_metadata", "weekly_page", "handbook", "reading"}
    if page == "resources":
        return source in {"reading", "weekly_page", "moodle_link", "literature"}
    if page == "assessment":
        return source in {"handbook", "weekly_page", "moodle_link"}
    return True


def _embedding_text(chunk: Any) -> str:
    return "\n".join(
        (
            f"Title: {chunk.title}",
            f"Section: {section_for_chunk(chunk) or ''}",
            f"Week: {chunk.week or ''}; Page: {chunk.page or ''}; Type: {chunk.task_type or chunk.source_type}",
            str(chunk.text),
        )
    )


class C4RAGHybrid:
    """Field-aware BM25 + local MPNet + deterministic reciprocal-rank fusion."""

    implementation_id = R1_ID

    def __init__(
        self,
        *,
        chunks: Sequence[Any] | None = None,
        embedder: DenseEmbedder | None = None,
        rrf_constant: int = 60,
    ) -> None:
        self.chunks = tuple(chunks or load_legacy_chunks())
        self.corpus_hash = legacy_chunk_corpus_hash(self.chunks)
        self.rrf_constant = int(rrf_constant)
        self.lexical = FieldAwareBM25(self.chunks)
        self.embedder = embedder or LocalMPNetEmbedder()
        self.dense_matrix = self.embedder.encode([_embedding_text(item) for item in self.chunks])

    def retrieve(
        self,
        student_query: str,
        current_page: str,
        visible_history: Any,
        *,
        top_k: int = 5,
        retrieval_enabled: bool = True,
        query_type: str | None = None,
    ) -> RetrievalEnvelope:
        del query_type  # Upstream P3 already authorised retrieval; R1 does not reclassify it.
        started = time.perf_counter()
        query = str(student_query or "").strip()
        if not retrieval_enabled or not query:
            return RetrievalEnvelope(
                implementation_id=self.implementation_id,
                query=query,
                result_status=ResultStatus.NO_RESULT,
                selected_chunks=(),
                limitations=("Retrieval was not enabled by the upstream capability decision.",),
                latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )
        resolved, history_used = resolved_hybrid_query(query, visible_history)
        eligible = [
            index
            for index, chunk in enumerate(self.chunks)
            if _metadata_compatible(chunk, resolved, current_page)
        ]
        lexical_scores = self.lexical.scores(resolved)
        query_vector = self.embedder.encode([resolved])[0]
        dense_scores = self.dense_matrix @ query_vector

        lexical_ranked = sorted(
            (index for index in eligible if lexical_scores[index] > 0.0),
            key=lambda index: (-lexical_scores[index], str(self.chunks[index].chunk_id)),
        )[:50]
        dense_ranked = sorted(
            eligible,
            key=lambda index: (-float(dense_scores[index]), str(self.chunks[index].chunk_id)),
        )[:50]
        lexical_ranks = {index: rank for rank, index in enumerate(lexical_ranked, start=1)}
        dense_ranks = {index: rank for rank, index in enumerate(dense_ranked, start=1)}
        fused: dict[int, float] = {}
        for index, rank in lexical_ranks.items():
            # Lexical evidence receives two votes; dense evidence is the small
            # hybrid candidate's deterministic secondary vote.
            fused[index] = fused.get(index, 0.0) + 2.0 / (self.rrf_constant + rank)
        for index, rank in dense_ranks.items():
            fused[index] = fused.get(index, 0.0) + 1.0 / (self.rrf_constant + rank)

        query_terms = content_tokens(resolved)
        strong_indexes: list[int] = []
        for index in fused:
            chunk = self.chunks[index]
            chunk_terms = content_tokens(
                " ".join(
                    (
                        str(chunk.title),
                        section_for_chunk(chunk) or "",
                        str(chunk.text),
                        str(chunk.week or ""),
                        str(chunk.task_type or ""),
                    )
                )
            )
            overlap = len(query_terms & chunk_terms)
            exact_week = bool(_extract_week(resolved) and chunk.week == _extract_week(resolved))
            exact_part = "part a" in resolved.casefold() and "part a" in " ".join(
                (str(chunk.title), str(chunk.text))
            ).casefold()
            if overlap >= 2 or exact_week or exact_part:
                strong_indexes.append(index)

        ranked = sorted(
            strong_indexes,
            key=lambda index: (
                -fused[index],
                -lexical_scores[index],
                -float(dense_scores[index]),
                str(self.chunks[index].chunk_id),
            ),
        )
        selected_indexes = ranked[: max(1, int(top_k))]
        items = tuple(
            _selected_chunk(
                self.chunks[index],
                rank=rank,
                lexical_score=lexical_scores[index],
                dense_score=float(dense_scores[index]),
                fusion_rank=rank,
            )
            for rank, index in enumerate(selected_indexes, start=1)
        )
        limitations = [
            "Dense similarity is local selection evidence, not permission to make an unsupported claim.",
            "Only FULL_TEXT_SUPPORT, BODY_EXCERPT, or SUMMARY_SUPPORT may support substantive claims.",
        ]
        if history_used:
            limitations.append("Bounded visible history was appended deterministically; no model rewrite was used.")
        if not items:
            limitations.append("No candidate passed the deterministic lexical/metadata/dense relevance guard.")
        if items and not any(item.substantive_claim_support for item in items):
            limitations.append("Retrieved items support only identification, metadata, or links.")
        return RetrievalEnvelope(
            implementation_id=self.implementation_id,
            query=query,
            result_status=_status_for(items),
            selected_chunks=items,
            limitations=tuple(limitations),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )
