"""Source-aware Retrieval v2 orchestration and inspection CLI."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Iterable

import numpy as np

from .chunking import expand_neighbour_context
from .config import DEFAULT_CONFIG, RETRIEVAL_VERSION, RetrievalConfigV2
from .fusion import reciprocal_rank_fusion
from .index_store import (
    IndexValidationErrorV2,
    LoadedIndexBundleV2,
    build_index,
    compute_index_hash,
    load_index_bundle_v2,
)
from .lexical_index import BM25IndexV2, tokenise
from .manifest import load_manifest, manifest_hash
from .models import CourseChunkV2, RetrievalResultV2, RetrievedChunkV2
from .query_analysis import analyse_query
from .reranker import rerank_candidates
from .semantic_index import (
    DisabledEmbeddingProvider,
    EmbeddingProviderV2,
    SemanticIndexV2,
    SentenceTransformerEmbeddingProvider,
)
from .sufficiency import evaluate_evidence_sufficiency


class CourseMaterialRetrieverV2:
    """Extensible BM25/semantic retrieval with a mandatory sufficiency gate."""

    def __init__(
        self,
        chunks: Iterable[CourseChunkV2] | None = None,
        embedding_provider: EmbeddingProviderV2 | None = None,
        config: RetrievalConfigV2 = DEFAULT_CONFIG,
        embeddings: np.ndarray | None = None,
        index_metadata: dict[str, object] | None = None,
        validation_warnings: Iterable[str] = (),
        backend_mode: str | None = None,
    ) -> None:
        if chunks is None:
            bundle = load_index_bundle_v2(config)
            chunks = bundle.chunks
            index_metadata = bundle.metadata
            loaded_warnings = list(bundle.validation_warnings)
            selected_provider = embedding_provider or DisabledEmbeddingProvider()
            if bundle.backend_mode == "hybrid" and selected_provider.available:
                expected_identifier = str(bundle.embedding_provider_metadata["identifier"])
                expected_dimension = int(bundle.embedding_provider_metadata["dimension"])
                if selected_provider.identifier != expected_identifier:
                    raise IndexValidationErrorV2(
                        f"Query embedding provider identifier {selected_provider.identifier!r} "
                        f"does not match persisted index identifier {expected_identifier!r}."
                    )
                if selected_provider.dimension != expected_dimension:
                    raise IndexValidationErrorV2(
                        f"Query embedding dimension {selected_provider.dimension} does not match "
                        f"persisted dimension {expected_dimension}."
                    )
                embeddings = bundle.embeddings
                backend_mode = "hybrid"
            elif bundle.backend_mode == "hybrid":
                embeddings = None
                backend_mode = "lexical_degraded"
                loaded_warnings.append(
                    "Persisted semantic embeddings were validated, but the matching local query "
                    "embedding model is unavailable; runtime is lexical_degraded."
                )
            else:
                embeddings = None
                backend_mode = "lexical_degraded"
                if selected_provider.available:
                    loaded_warnings.append(
                        "The persisted index is lexical-only; the supplied semantic provider was not activated."
                    )
                    selected_provider = DisabledEmbeddingProvider()
            embedding_provider = selected_provider
            validation_warnings = loaded_warnings
        self.config = config
        self.manifest_records = load_manifest(config.manifest_path)
        self.chunks = list(chunks)
        self.embedding_provider = embedding_provider or DisabledEmbeddingProvider()
        self.lexical_index = BM25IndexV2(self.chunks)
        self.semantic_index = SemanticIndexV2(
            self.chunks,
            self.embedding_provider,
            embeddings=embeddings if self.embedding_provider.available else None,
        )
        self._embeddings_by_chunk: dict[str, np.ndarray] = {}
        if self.embedding_provider.available and len(self.semantic_index.embeddings) == len(self.chunks):
            self._embeddings_by_chunk = {
                chunk.chunk_id: self.semantic_index.embeddings[index]
                for index, chunk in enumerate(self.chunks)
            }
        metadata = dict(index_metadata or {})
        self.index_version = str(metadata.get("retrieval_version") or RETRIEVAL_VERSION)
        self.corpus_manifest_hash = str(
            metadata.get("manifest_hash") or manifest_hash(config.manifest_path)
        )
        self.index_hash = str(metadata.get("index_hash") or compute_index_hash(self.chunks))
        self.source_presence = {
            document_id: bool(source_hash)
            for document_id, source_hash in dict(metadata.get("source_hashes") or {}).items()
        }
        if not self.source_presence:
            self.source_presence = {
                record.document_id: any(chunk.document_id == record.document_id for chunk in self.chunks)
                for record in self.manifest_records if record.enabled
            }
        self.backend_mode = backend_mode or (
            "hybrid" if self.embedding_provider.available and self._embeddings_by_chunk else "lexical_degraded"
        )
        self.validation_warnings = tuple(validation_warnings)

    @classmethod
    def from_persisted_index(
        cls,
        config: RetrievalConfigV2 = DEFAULT_CONFIG,
        *,
        embedding_provider: EmbeddingProviderV2 | None = None,
        semantic_disabled: bool = False,
        embedding_model: str | None = None,
        require_fresh: bool = True,
        allow_lexical_degraded: bool = True,
        rebuild_if_stale: bool = False,
    ) -> "CourseMaterialRetrieverV2":
        """Construct from a validated persisted bundle without re-ingestion."""

        try:
            bundle = load_index_bundle_v2(
                config,
                require_fresh=require_fresh,
                allow_lexical_degraded=allow_lexical_degraded,
            )
        except IndexValidationErrorV2:
            if not rebuild_if_stale:
                raise
            semantic_requested = embedding_provider is not None or bool(embedding_model)
            build_index(
                config=config,
                semantic_disabled=semantic_disabled or not semantic_requested,
                embedding_model=embedding_model,
                embedding_provider=None if semantic_disabled else embedding_provider,
            )
            bundle = load_index_bundle_v2(
                config,
                require_fresh=require_fresh,
                allow_lexical_degraded=allow_lexical_degraded,
            )

        warnings = list(bundle.validation_warnings)
        provider: EmbeddingProviderV2
        runtime_embeddings: np.ndarray | None = None
        runtime_backend = "lexical_degraded"
        semantic_declared = bool(
            bundle.embedding_provider_metadata.get("semantic_index_declared")
        )
        if semantic_declared and not semantic_disabled:
            provider = embedding_provider or (
                SentenceTransformerEmbeddingProvider(embedding_model)
                if embedding_model
                else DisabledEmbeddingProvider()
            )
            if provider.available:
                expected_identifier = str(bundle.embedding_provider_metadata["identifier"])
                expected_dimension = int(bundle.embedding_provider_metadata["dimension"])
                if provider.identifier != expected_identifier:
                    raise IndexValidationErrorV2(
                        f"Query embedding provider identifier {provider.identifier!r} does not match "
                        f"persisted index identifier {expected_identifier!r}."
                    )
                if provider.dimension != expected_dimension:
                    raise IndexValidationErrorV2(
                        f"Query embedding dimension {provider.dimension} does not match persisted "
                        f"dimension {expected_dimension}."
                    )
                runtime_embeddings = bundle.embeddings
                runtime_backend = "hybrid"
            else:
                message = (
                    "Persisted semantic embeddings were validated, but the matching local query "
                    "embedding model is unavailable; runtime is lexical_degraded."
                )
                if not allow_lexical_degraded:
                    raise IndexValidationErrorV2(message)
                warnings.extend(filter(None, (message, provider.warning)))
        else:
            provider = DisabledEmbeddingProvider()
            if semantic_declared and semantic_disabled:
                warnings.append(
                    "Persisted semantic embeddings were validated but explicitly disabled for this query runtime."
                )
            elif embedding_provider is not None or embedding_model:
                warnings.append(
                    "The persisted index is lexical-only; the requested semantic provider was not activated."
                )
        return cls(
            chunks=bundle.chunks,
            embedding_provider=provider,
            config=config,
            embeddings=runtime_embeddings,
            index_metadata=bundle.metadata,
            validation_warnings=warnings,
            backend_mode=runtime_backend,
        )

    def retrieve(
        self,
        query: str,
        query_type: str | None = None,
        top_k: int | None = None,
        expand_context: bool = False,
    ) -> RetrievalResultV2:
        started = time.perf_counter()
        plan = analyse_query(query, query_type)
        backend_mode = self.backend_mode
        warnings = tuple(dict.fromkeys(filter(None, (*self.validation_warnings, self.embedding_provider.warning))))
        present = dict(self.source_presence)
        base_diagnostics = {
            "manifest_document_presence": present,
            "corpus_document_count": len({chunk.document_id for chunk in self.chunks}),
            "corpus_chunk_count": len(self.chunks),
            "strict_filter_applied": False,
            "strict_filter_candidate_count": 0,
            "controlled_fallback_used": False,
            "lexical_candidate_count": 0,
            "semantic_candidate_count": 0,
        }
        if not plan.retrieval_requested:
            sufficiency = evaluate_evidence_sufficiency(plan, ())
            return RetrievalResultV2(
                query=query,
                query_plan=plan,
                retrieval_requested=False,
                retrieval_used=False,
                backend_mode=backend_mode,
                semantic_backend_available=backend_mode == "hybrid",
                retrieved_chunks=(),
                candidate_diagnostics=base_diagnostics,
                evidence_sufficiency=sufficiency,
                reason=plan.reason,
                warnings=warnings,
                index_version=self.index_version,
                corpus_manifest_hash=self.corpus_manifest_hash,
                index_hash=self.index_hash,
                latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

        pool = self.chunks
        strict_applied = bool(plan.reliable_filters)
        if strict_applied:
            strict = [chunk for chunk in pool if self._matches_reliable_filters(chunk, plan)]
        else:
            strict = pool
        fallback = strict_applied and not strict
        search_pool = strict
        relaxed_filters: list[str] = []
        if fallback:
            # Relax the most specific constraint first while retaining explicit
            # week/material intent where possible. This makes fallback visible
            # and controlled rather than silently searching an unrelated corpus.
            for ignored in ({"assessment_part"}, {"assessment_part", "material_type"}, set(plan.reliable_filters)):
                candidate_pool = [
                    chunk for chunk in pool
                    if self._matches_reliable_filters(chunk, plan, ignored=ignored)
                ]
                if candidate_pool:
                    search_pool = candidate_pool
                    relaxed_filters = sorted(ignored & set(plan.reliable_filters))
                    break
        lexical = BM25IndexV2(search_pool).search(query, self.config.lexical_candidate_top_k)
        subset_embeddings: np.ndarray | None = None
        if backend_mode == "hybrid":
            subset_embeddings = np.asarray(
                [self._embeddings_by_chunk[chunk.chunk_id] for chunk in search_pool],
                dtype=np.float32,
            )
        semantic = SemanticIndexV2(
            search_pool,
            self.embedding_provider,
            embeddings=subset_embeddings,
        ).search(query, self.config.semantic_candidate_top_k)
        query_terms = set(tokenise(query))
        lexical = [
            item for item in lexical
            if item[1] >= self.config.minimum_lexical_score
            and (
                len(query_terms & set(tokenise(" ".join((item[0].title, item[0].text))))) >= 2
                or (
                    len(query_terms) <= 2
                    and bool(query_terms & set(tokenise(" ".join((item[0].title, item[0].text)))))
                )
            )
        ]
        ranked_lists = [lexical, semantic]
        fused = reciprocal_rank_fusion(ranked_lists, self.config.rrf_constant)
        selected = rerank_candidates(
            fused,
            plan,
            top_k or self.config.final_top_k,
            self.config.maximum_chunks_per_source,
        )

        # A semantic-only zero/negative match or pure metadata boost is not a relevant result.
        candidate_ids = {chunk.chunk_id for chunk, _score in lexical} | {
            chunk.chunk_id for chunk, score in semantic if score > 0.15
        }
        selected = [item for item in selected if item.chunk.chunk_id in candidate_ids]
        context_expanded = False
        if expand_context and self.config.enable_neighbour_expansion and selected:
            expanded_chunks = expand_neighbour_context(
                [item.chunk for item in selected],
                self.chunks,
                self.config.maximum_prompt_expanded_context_chars,
            )
            by_id = {item.chunk.chunk_id: item for item in selected}
            expanded_items: list[RetrievedChunkV2] = []
            for chunk in expanded_chunks:
                if chunk.chunk_id in by_id:
                    expanded_items.append(by_id[chunk.chunk_id])
                else:
                    parent = next(
                        (
                            item for item in selected
                            if chunk.chunk_id in {item.chunk.previous_chunk_id, item.chunk.next_chunk_id}
                        ),
                        selected[0],
                    )
                    expanded_items.append(
                        RetrievedChunkV2(
                            chunk=chunk,
                            reranker_score=parent.reranker_score,
                            rerank_reason=("neighbour_context_expansion",),
                            metadata_matches=dict(parent.metadata_matches),
                            expanded_from_chunk_id=parent.chunk.chunk_id,
                        )
                    )
            selected = expanded_items
            context_expanded = True
        sufficiency = evaluate_evidence_sufficiency(plan, selected)
        diagnostics = {
            **base_diagnostics,
            "strict_filter_applied": strict_applied,
            "strict_filter_candidate_count": len(strict),
            "controlled_fallback_used": fallback,
            "relaxed_filters": relaxed_filters,
            "lexical_candidate_count": len(lexical),
            "semantic_candidate_count": len(semantic),
            "candidate_document_ids": sorted({item.chunk.document_id for item in selected}),
            "context_expanded": context_expanded,
            "documents_present_but_not_retrieved": sorted(
                document_id for document_id, exists in present.items()
                if exists and document_id not in {item.chunk.document_id for item in selected}
            ),
        }
        return RetrievalResultV2(
            query=query,
            query_plan=plan,
            retrieval_requested=True,
            retrieval_used=bool(selected),
            backend_mode=backend_mode,
            semantic_backend_available=backend_mode == "hybrid",
            retrieved_chunks=tuple(selected),
            candidate_diagnostics=diagnostics,
            evidence_sufficiency=sufficiency,
            reason=sufficiency.reason,
            warnings=warnings,
            index_version=self.index_version,
            corpus_manifest_hash=self.corpus_manifest_hash,
            index_hash=self.index_hash,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )

    @staticmethod
    def _matches_reliable_filters(
        chunk: CourseChunkV2, plan: object, ignored: set[str] | None = None
    ) -> bool:
        ignored = ignored or set()
        if "week" not in ignored and getattr(plan, "week", None) and chunk.week != plan.week:
            return False
        material = getattr(plan, "material_type", None)
        if "material_type" not in ignored and material:
            haystack = " ".join((chunk.material_type, chunk.title, *chunk.section_path)).casefold()
            if material == "lecture":
                if "lecture" not in haystack:
                    return False
            elif material == "assessment":
                if not any(term in haystack for term in ("assessment", "part a", "part b", "criteria")):
                    return False
            elif material not in haystack:
                return False
        part = getattr(plan, "assessment_part", None)
        if "assessment_part" not in ignored and part and chunk.assessment_part != part and part.casefold() not in " ".join(chunk.section_path).casefold():
            return False
        return True


_DEFAULT_RETRIEVER: CourseMaterialRetrieverV2 | None = None


def retrieve_course_materials_v2(
    query: str,
    query_type: str | None = None,
    top_k: int | None = None,
    retriever: CourseMaterialRetrieverV2 | None = None,
) -> RetrievalResultV2:
    global _DEFAULT_RETRIEVER
    if retriever is None:
        if _DEFAULT_RETRIEVER is None:
            _DEFAULT_RETRIEVER = CourseMaterialRetrieverV2.from_persisted_index()
        retriever = _DEFAULT_RETRIEVER
    return retriever.retrieve(query, query_type=query_type, top_k=top_k)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect Retrieval v2")
    parser.add_argument("command", choices=["query"])
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=DEFAULT_CONFIG.final_top_k)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_CONFIG.index_dir)
    semantic = parser.add_mutually_exclusive_group()
    semantic.add_argument("--semantic-disabled", action="store_true")
    semantic.add_argument("--embedding-model")
    parser.add_argument("--rebuild-if-stale", action="store_true")
    args = parser.parse_args(argv)
    config = replace(DEFAULT_CONFIG, index_dir=args.index_dir)
    retriever = CourseMaterialRetrieverV2.from_persisted_index(
        config,
        semantic_disabled=args.semantic_disabled,
        embedding_model=args.embedding_model,
        rebuild_if_stale=args.rebuild_if_stale,
    )
    result = retriever.retrieve(args.query, top_k=args.top_k)
    print(json.dumps(result.to_audit_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
