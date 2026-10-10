"""Model-independent semantic intent retrieval for offline shadow evaluation.

Nothing in this module is connected to C_FULL production routing. Index files
are read only when a router is explicitly constructed, and embedding backends
are invoked only by ``predict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from importlib import metadata as importlib_metadata
import json
import math
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

from utils.intent_example_index import (
    APPROVED_INDEX_VERSION,
    CANONICAL_PAGES,
    RETRIEVAL_TEXT_VERSION,
    ApprovedIntentExample,
    compute_file_sha256,
    load_approved_index,
    normalise_example_query,
)
from utils.intent_schema import (
    INTENT_SCHEMA_VERSION,
    IntentCandidate,
    IntentReasonCode,
    SemanticIntentResult,
)


DEFAULT_AGGREGATION_METHOD = "top_family_mean"
DEFAULT_PER_INTENT_FAMILY_LIMIT = 3
DEFAULT_EXAMPLE_TOP_K = 12
DEFAULT_CANDIDATE_LIMIT = 8
AGGREGATION_METHODS = ("max", "top_family_mean")


class EmbeddingBackend(Protocol):
    @property
    def model_version(self) -> str:
        ...

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        ...


class EmbeddingBackendUnavailable(RuntimeError):
    """Expected absence of a local backend, safe to expose as a reason code."""

    def __init__(self, reason: str = "local_embedding_backend_unavailable") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FrozenIntentIndex:
    records: tuple[ApprovedIntentExample, ...]
    index_version: str
    retrieval_text_version: str
    index_sha256: str
    record_count: int

    def __post_init__(self) -> None:
        if self.index_version != APPROVED_INDEX_VERSION:
            raise ValueError("Frozen intent index version mismatch")
        if self.retrieval_text_version != RETRIEVAL_TEXT_VERSION:
            raise ValueError("Frozen retrieval-text version mismatch")
        if self.record_count != len(self.records):
            raise ValueError("Frozen intent index record count mismatch")
        if self.record_count != 62:
            raise ValueError("Frozen approved intent index must contain 62 records")


def load_frozen_intent_index(
    index_path: str | Path,
    index_sha256_path: str | Path,
    metadata_path: str | Path,
) -> FrozenIntentIndex:
    index_path = Path(index_path)
    sha_path = Path(index_sha256_path)
    metadata_path = Path(metadata_path)
    actual_hash = compute_file_sha256(index_path)
    sha_line = sha_path.read_text(encoding="utf-8").strip()
    parts = sha_line.split("  ")
    if len(parts) != 2 or len(parts[0]) != 64:
        raise ValueError("Frozen index SHA-256 file has an invalid format")
    expected_hash, expected_filename = parts
    if expected_filename != index_path.name:
        raise ValueError("Frozen index SHA-256 filename mismatch")
    if expected_hash != actual_hash:
        raise ValueError("Frozen index SHA-256 mismatch")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("approved_index_sha256") != actual_hash:
        raise ValueError("Frozen index metadata SHA-256 mismatch")
    if metadata.get("approved_index_version") != APPROVED_INDEX_VERSION:
        raise ValueError("Frozen index metadata version mismatch")
    if metadata.get("retrieval_text_version") != RETRIEVAL_TEXT_VERSION:
        raise ValueError("Frozen retrieval-text metadata version mismatch")
    if metadata.get("intent_schema_version") != INTENT_SCHEMA_VERSION:
        raise ValueError("Frozen intent schema metadata version mismatch")
    if metadata.get("final_index_count") != 62:
        raise ValueError("Frozen index metadata record count mismatch")
    records = load_approved_index(index_path)
    if any(record.approved_index_version != APPROVED_INDEX_VERSION for record in records):
        raise ValueError("Frozen record index version mismatch")
    if any(record.retrieval_text_version != RETRIEVAL_TEXT_VERSION for record in records):
        raise ValueError("Frozen record retrieval-text version mismatch")
    return FrozenIntentIndex(
        records=records,
        index_version=APPROVED_INDEX_VERSION,
        retrieval_text_version=RETRIEVAL_TEXT_VERSION,
        index_sha256=actual_hash,
        record_count=len(records),
    )


def validate_embedding_matrix(
    matrix: np.ndarray,
    *,
    expected_rows: int,
    expected_dimension: int | None = None,
) -> np.ndarray:
    if not isinstance(matrix, np.ndarray):
        raise ValueError("Embedding backend must return a numpy.ndarray")
    if matrix.ndim != 2:
        raise ValueError("Embedding backend must return a two-dimensional matrix")
    if matrix.shape[0] != expected_rows:
        raise ValueError("Embedding row count does not match input text count")
    if matrix.shape[1] <= 0:
        raise ValueError("Embedding dimension must be greater than zero")
    if expected_dimension is not None and matrix.shape[1] != expected_dimension:
        raise ValueError("Embedding dimension changed within one router lifecycle")
    if not np.issubdtype(matrix.dtype, np.number):
        raise ValueError("Embedding matrix must have a numeric dtype")
    numeric = np.asarray(matrix, dtype=np.float64)
    if not np.isfinite(numeric).all():
        raise ValueError("Embedding matrix contains non-finite values")
    return numeric


def clipped_cosine_similarities(
    query_vector: np.ndarray,
    index_matrix: np.ndarray,
) -> np.ndarray:
    query = np.asarray(query_vector, dtype=np.float64)
    matrix = np.asarray(index_matrix, dtype=np.float64)
    if query.ndim != 1:
        raise ValueError("Query embedding must be one-dimensional")
    if matrix.ndim != 2:
        raise ValueError("Index embeddings must be two-dimensional")
    if matrix.shape[1] != query.shape[0]:
        raise ValueError("Query/index embedding dimension mismatch")
    if query.shape[0] <= 0:
        raise ValueError("Embedding dimension must be greater than zero")
    if not np.isfinite(query).all() or not np.isfinite(matrix).all():
        raise ValueError("Cosine input contains non-finite values")
    query_norm = float(np.linalg.norm(query))
    row_norms = np.linalg.norm(matrix, axis=1)
    denominators = row_norms * query_norm
    scores = np.zeros(matrix.shape[0], dtype=np.float64)
    valid = denominators > 0.0
    if np.any(valid):
        scores[valid] = (matrix[valid] @ query) / denominators[valid]
    return np.clip(scores, 0.0, 1.0)


@dataclass(frozen=True)
class SemanticExampleHit:
    example_id: str
    semantic_label: str
    source_scope: str
    paraphrase_family_id: str
    context_requirement: str
    page_context: str
    score: float
    rank: int

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.score)) or not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("Semantic example score must be finite and in [0, 1]")
        if self.rank < 1:
            raise ValueError("Semantic example rank must start at one")
        object.__setattr__(self, "score", float(self.score))

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "semantic_label": self.semantic_label,
            "source_scope": self.source_scope,
            "paraphrase_family_id": self.paraphrase_family_id,
            "context_requirement": self.context_requirement,
            "page_context": self.page_context,
            "score": self.score,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class SemanticRouterPrediction:
    result: SemanticIntentResult
    example_hits: tuple[SemanticExampleHit, ...] = field(default_factory=tuple)
    query_representations: tuple[str, ...] = field(default_factory=tuple)
    index_sha256: str = ""
    excluded_current_page_records: int = 0
    excluded_example_count: int = 0
    excluded_family_count: int = 0
    aggregation_method: str = DEFAULT_AGGREGATION_METHOD
    example_top_k: int = DEFAULT_EXAMPLE_TOP_K
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT
    aggregate_all_examples: bool = True
    reason: str = ""
    production_integration: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.result.status,
            "result": self.result.to_dict(),
            "example_hits": [hit.to_dict() for hit in self.example_hits],
            "query_representations": list(self.query_representations),
            "index_sha256": self.index_sha256,
            "excluded_current_page_records": self.excluded_current_page_records,
            "excluded_example_count": self.excluded_example_count,
            "excluded_family_count": self.excluded_family_count,
            "aggregation_method": self.aggregation_method,
            "example_top_k": self.example_top_k,
            "candidate_limit": self.candidate_limit,
            "aggregate_all_examples": self.aggregate_all_examples,
            "reason": self.reason,
            "production_integration": self.production_integration,
        }


def collapse_hits_by_family(
    hits: Sequence[SemanticExampleHit],
) -> tuple[SemanticExampleHit, ...]:
    """Keep one best example per semantic-label/family pair."""

    best: dict[tuple[str, str], SemanticExampleHit] = {}
    for hit in sorted(hits, key=lambda item: (-item.score, item.semantic_label, item.example_id)):
        best.setdefault((hit.semantic_label, hit.paraphrase_family_id), hit)
    return tuple(
        sorted(best.values(), key=lambda item: (-item.score, item.semantic_label, item.example_id))
    )


def _suggest_scope(contributors: Sequence[SemanticExampleHit]) -> str:
    highest = max(hit.score for hit in contributors)
    scopes = {
        hit.source_scope
        for hit in contributors
        if math.isclose(hit.score, highest, rel_tol=0.0, abs_tol=1e-15)
    }
    return next(iter(scopes)) if len(scopes) == 1 else "undetermined"


def aggregate_intent_candidates(
    family_hits: Sequence[SemanticExampleHit],
    *,
    aggregation_method: str = DEFAULT_AGGREGATION_METHOD,
    per_intent_family_limit: int = DEFAULT_PER_INTENT_FAMILY_LIMIT,
) -> tuple[IntentCandidate, ...]:
    if aggregation_method not in AGGREGATION_METHODS:
        raise ValueError("Unsupported intent aggregation method")
    if per_intent_family_limit < 1:
        raise ValueError("per_intent_family_limit must be at least one")
    grouped: dict[str, list[SemanticExampleHit]] = {}
    for hit in family_hits:
        grouped.setdefault(hit.semantic_label, []).append(hit)
    candidates = []
    for label, items in grouped.items():
        ordered = sorted(items, key=lambda item: (-item.score, item.example_id))
        if aggregation_method == "max":
            contributors = ordered[:1]
            score = contributors[0].score
        else:
            contributors = ordered[:per_intent_family_limit]
            score = float(sum(item.score for item in contributors) / len(contributors))
        candidates.append(
            IntentCandidate(
                label=label,
                score=score,
                suggested_source_scope=_suggest_scope(contributors),
                example_ids=tuple(item.example_id for item in contributors),
                reason_codes=(IntentReasonCode.SEMANTIC_RETRIEVAL_AVAILABLE,),
            )
        )
    return tuple(sorted(candidates, key=lambda item: (-item.score, item.label)))


class SentenceTransformerEmbeddingBackend:
    """Optional local-only adapter; import and model loading are both lazy."""

    def __init__(
        self,
        local_model_path: str | Path | None,
        *,
        repo_id: str | None = None,
        revision: str | None = None,
        device: str = "cpu",
        batch_size: int = 32,
        allow_model_download: bool = False,
    ) -> None:
        self.local_model_path = (
            Path(local_model_path).expanduser() if local_model_path else None
        )
        self.repo_id = str(repo_id or "").strip()
        self.revision = str(revision or "").strip()
        self.device = str(device).strip() or "cpu"
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")
        self.batch_size = int(batch_size)
        # Deprecated compatibility field. Runtime loading is always local-only;
        # downloads belong exclusively to the preparation script.
        self.allow_model_download = bool(allow_model_download)
        self._model: Any | None = None

    @property
    def model_version(self) -> str:
        if self.local_model_path is None:
            return "sentence-transformer-local-unavailable"
        if not self.repo_id or not self.revision:
            return f"sentence-transformer-local-unversioned:{self.local_model_path.name}"
        try:
            package_version = importlib_metadata.version("sentence-transformers")
        except importlib_metadata.PackageNotFoundError:
            package_version = "unavailable"
        return (
            f"{self.repo_id}@{self.revision}"
            f"|sentence-transformers={package_version}"
        )

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self.local_model_path is None:
            raise EmbeddingBackendUnavailable("local_embedding_backend_unavailable")
        if not self.local_model_path.exists():
            raise EmbeddingBackendUnavailable("local_model_path_not_found")
        if self.revision and self.local_model_path.name != self.revision:
            raise EmbeddingBackendUnavailable("local_model_revision_path_mismatch")
        try:
            from sentence_transformers import SentenceTransformer
        except (ImportError, ModuleNotFoundError) as exc:
            raise EmbeddingBackendUnavailable(
                "sentence_transformers_package_unavailable"
            ) from exc
        try:
            self._model = SentenceTransformer(
                str(self.local_model_path),
                device=self.device,
                local_files_only=True,
            )
        except TypeError as exc:
            raise EmbeddingBackendUnavailable(
                "local_only_loading_not_supported"
            ) from exc
        except Exception as exc:
            raise EmbeddingBackendUnavailable("local_model_load_failed") from exc
        if hasattr(self._model, "eval"):
            self._model.eval()
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts or any(not str(text).strip() for text in texts):
            raise ValueError("Embedding input texts must be non-empty")
        model = self._load_model()
        return np.asarray(
            model.encode(
                list(texts),
                batch_size=self.batch_size,
                device=self.device,
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )


def _npz_scalar(archive: Any, name: str) -> str:
    if name not in archive.files:
        raise ValueError(f"Embedding artifact is missing {name}")
    value = np.asarray(archive[name])
    if value.size != 1:
        raise ValueError(f"Embedding artifact field {name} must be scalar")
    return str(value.reshape(-1)[0])


@dataclass(frozen=True)
class PrecomputedIndexEmbeddingStore:
    """Verified frozen-index vectors; query vectors still come from the model."""

    artifact_path: Path
    sha256_path: Path

    def load(
        self,
        *,
        frozen_index: FrozenIntentIndex,
        backend: EmbeddingBackend,
    ) -> np.ndarray:
        artifact = Path(self.artifact_path)
        expected_line = Path(self.sha256_path).read_text(encoding="utf-8").strip()
        parts = expected_line.split("  ")
        if len(parts) != 2 or len(parts[0]) != 64 or parts[1] != artifact.name:
            raise ValueError("Embedding artifact SHA-256 file is invalid")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != parts[0]:
            raise ValueError("Embedding artifact SHA-256 mismatch")
        with np.load(artifact, allow_pickle=False) as archive:
            if _npz_scalar(archive, "approved_index_sha256") != frozen_index.index_sha256:
                raise ValueError("Embedding artifact index SHA-256 mismatch")
            if _npz_scalar(archive, "approved_index_version") != frozen_index.index_version:
                raise ValueError("Embedding artifact index version mismatch")
            if _npz_scalar(archive, "retrieval_text_version") != frozen_index.retrieval_text_version:
                raise ValueError("Embedding artifact retrieval-text version mismatch")
            if _npz_scalar(archive, "model_version") != str(backend.model_version):
                raise ValueError("Embedding artifact model version mismatch")
            example_ids = tuple(str(item) for item in np.asarray(archive["example_ids"]).tolist())
            expected_ids = tuple(record.example_id for record in frozen_index.records)
            if example_ids != expected_ids:
                raise ValueError("Embedding artifact example order mismatch")
            raw = np.asarray(archive["embeddings"])
            if raw.dtype != np.float32:
                raise ValueError("Embedding artifact dtype must be float32")
            matrix = validate_embedding_matrix(raw, expected_rows=frozen_index.record_count)
        return matrix


class SemanticIntentRouter:
    """Read-only semantic example retriever for shadow-mode diagnostics."""

    def __init__(
        self,
        *,
        embedding_backend: EmbeddingBackend,
        index_path: str | Path,
        index_sha256_path: str | Path,
        metadata_path: str | Path,
        aggregation_method: str = DEFAULT_AGGREGATION_METHOD,
        per_intent_family_limit: int = DEFAULT_PER_INTENT_FAMILY_LIMIT,
        precomputed_index_store: PrecomputedIndexEmbeddingStore | None = None,
    ) -> None:
        if aggregation_method not in AGGREGATION_METHODS:
            raise ValueError("Unsupported aggregation method")
        if per_intent_family_limit < 1:
            raise ValueError("per_intent_family_limit must be at least one")
        self.embedding_backend = embedding_backend
        self.aggregation_method = aggregation_method
        self.per_intent_family_limit = per_intent_family_limit
        self.precomputed_index_store = precomputed_index_store
        self._frozen_index: FrozenIntentIndex | None = None
        self._index_invalid = False
        try:
            self._frozen_index = load_frozen_intent_index(
                index_path,
                index_sha256_path,
                metadata_path,
            )
        except Exception:
            self._index_invalid = True
        self._index_embeddings: np.ndarray | None = None
        self._index_cache_key: tuple[str, str, str] | None = None

    @property
    def frozen_index(self) -> FrozenIntentIndex | None:
        return self._frozen_index

    def _model_version(self) -> str:
        version = str(self.embedding_backend.model_version).strip()
        if not version:
            raise ValueError("Embedding backend model_version must be non-empty")
        return version

    def _ensure_index_embeddings(self, model_version: str) -> np.ndarray:
        if self._frozen_index is None:
            raise ValueError("Frozen index is unavailable")
        cache_key = (
            self._frozen_index.index_sha256,
            model_version,
            self._frozen_index.retrieval_text_version,
        )
        if self._index_embeddings is not None and self._index_cache_key == cache_key:
            return self._index_embeddings
        if self.precomputed_index_store is not None:
            matrix = self.precomputed_index_store.load(
                frozen_index=self._frozen_index,
                backend=self.embedding_backend,
            )
        else:
            texts = [record.retrieval_text for record in self._frozen_index.records]
            if not texts or any(not text.strip() for text in texts):
                raise ValueError("Frozen index contains an empty retrieval text")
            encoded = self.embedding_backend.encode(texts)
            matrix = validate_embedding_matrix(encoded, expected_rows=len(texts))
        self._index_embeddings = matrix
        self._index_cache_key = cache_key
        return matrix

    def _failure(
        self,
        *,
        status: str,
        reason_code: IntentReasonCode,
        reason: str,
        model_version: str = "not-run",
        aggregation_method: str | None = None,
        example_top_k: int = DEFAULT_EXAMPLE_TOP_K,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> SemanticRouterPrediction:
        index_version = (
            self._frozen_index.index_version if self._frozen_index else "invalid"
        )
        index_sha = self._frozen_index.index_sha256 if self._frozen_index else ""
        return SemanticRouterPrediction(
            result=SemanticIntentResult(
                status=status,
                reason_codes=(reason_code,),
                model_version=model_version,
                index_version=index_version,
            ),
            index_sha256=index_sha,
            aggregation_method=aggregation_method or self.aggregation_method,
            example_top_k=example_top_k,
            candidate_limit=candidate_limit,
            reason=reason,
        )

    def predict(
        self,
        query: str,
        *,
        current_page: str | None = None,
        top_k: int = DEFAULT_EXAMPLE_TOP_K,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        aggregate_all_examples: bool = True,
        excluded_example_ids: Sequence[str] = (),
        excluded_family_ids: Sequence[str] = (),
    ) -> SemanticRouterPrediction:
        if top_k < 1 or candidate_limit < 1:
            raise ValueError("top_k and candidate_limit must be at least one")
        query_text = str(query).strip()
        if not query_text:
            return self._failure(
                status="error",
                reason_code=IntentReasonCode.SEMANTIC_EMPTY_QUERY,
                reason="empty_query",
                example_top_k=top_k,
                candidate_limit=candidate_limit,
            )
        if self._index_invalid or self._frozen_index is None:
            return self._failure(
                status="error",
                reason_code=IntentReasonCode.SEMANTIC_INDEX_INVALID,
                reason="frozen_index_invalid",
                example_top_k=top_k,
                candidate_limit=candidate_limit,
            )
        canonical_page: str | None = None
        if current_page is not None:
            page_lookup = {page.casefold(): page for page in CANONICAL_PAGES}
            canonical_page = page_lookup.get(str(current_page).strip().casefold())
            if canonical_page is None:
                return self._failure(
                    status="error",
                    reason_code=IntentReasonCode.SEMANTIC_PAGE_INVALID,
                    reason="invalid_current_page",
                    example_top_k=top_k,
                    candidate_limit=candidate_limit,
                )
        representations = [query_text]
        if canonical_page is not None:
            representations.append(f"[PAGE={canonical_page}] {query_text}")
        model_version = "not-run"
        try:
            model_version = self._model_version()
            index_embeddings = self._ensure_index_embeddings(model_version)
            query_encoded = self.embedding_backend.encode(representations)
            query_matrix = validate_embedding_matrix(
                query_encoded,
                expected_rows=len(representations),
                expected_dimension=index_embeddings.shape[1],
            )
        except EmbeddingBackendUnavailable as exc:
            return self._failure(
                status="unavailable",
                reason_code=IntentReasonCode.SEMANTIC_UNAVAILABLE,
                reason=exc.reason,
                model_version=model_version,
                example_top_k=top_k,
                candidate_limit=candidate_limit,
            )
        except Exception:
            return self._failure(
                status="error",
                reason_code=IntentReasonCode.SEMANTIC_BACKEND_INVALID,
                reason="embedding_backend_invalid",
                model_version=model_version,
                example_top_k=top_k,
                candidate_limit=candidate_limit,
            )

        all_hits_unranked: list[tuple[ApprovedIntentExample, float]] = []
        excluded_current_page = 0
        excluded_examples = frozenset(str(item) for item in excluded_example_ids)
        excluded_families = frozenset(str(item) for item in excluded_family_ids)
        excluded_example_count = 0
        excluded_family_count = 0
        plain_scores = clipped_cosine_similarities(query_matrix[0], index_embeddings)
        page_scores = (
            clipped_cosine_similarities(query_matrix[1], index_embeddings)
            if canonical_page is not None
            else None
        )
        for position, record in enumerate(self._frozen_index.records):
            if record.example_id in excluded_examples:
                excluded_example_count += 1
                continue
            if record.final_paraphrase_family_id in excluded_families:
                excluded_family_count += 1
                continue
            if record.final_context_requirement == "current_page":
                if canonical_page is None or record.page_context != canonical_page:
                    excluded_current_page += 1
                    continue
                assert page_scores is not None
                score = float(page_scores[position])
            else:
                score = float(plain_scores[position])
            all_hits_unranked.append((record, score))
        all_hits_unranked.sort(
            key=lambda item: (-item[1], item[0].final_semantic_label, item[0].example_id)
        )
        all_hits = tuple(
            SemanticExampleHit(
                example_id=record.example_id,
                semantic_label=record.final_semantic_label,
                source_scope=record.final_source_scope,
                paraphrase_family_id=record.final_paraphrase_family_id,
                context_requirement=record.final_context_requirement,
                page_context=record.page_context,
                score=score,
                rank=rank,
            )
            for rank, (record, score) in enumerate(all_hits_unranked, start=1)
        )
        displayed_hits = all_hits[:top_k]
        aggregation_hits = all_hits if aggregate_all_examples else displayed_hits
        family_hits = collapse_hits_by_family(aggregation_hits)
        all_candidates = aggregate_intent_candidates(
            family_hits,
            aggregation_method=self.aggregation_method,
            per_intent_family_limit=self.per_intent_family_limit,
        )
        returned_candidates = all_candidates[:candidate_limit]
        if not returned_candidates:
            return self._failure(
                status="error",
                reason_code=IntentReasonCode.SEMANTIC_BACKEND_INVALID,
                reason="no_eligible_semantic_candidates",
                model_version=model_version,
                example_top_k=top_k,
                candidate_limit=candidate_limit,
            )
        winner = returned_candidates[0]
        second = returned_candidates[1] if len(returned_candidates) > 1 else None
        margin = winner.score - second.score if second is not None else None
        out_of_scope_score = next(
            (
                candidate.score
                for candidate in all_candidates
                if candidate.label == "out_of_scope"
            ),
            0.0,
        )
        result = SemanticIntentResult(
            status="available",
            winning_label=winner.label,
            winning_score=winner.score,
            second_label=second.label if second else None,
            second_score=second.score if second else None,
            margin=margin,
            candidates=returned_candidates,
            suggested_source_scope=winner.suggested_source_scope,
            out_of_scope_score=out_of_scope_score,
            requires_clarification=False,
            reason_codes=(IntentReasonCode.SEMANTIC_RETRIEVAL_AVAILABLE,),
            model_version=model_version,
            index_version=self._frozen_index.index_version,
        )
        return SemanticRouterPrediction(
            result=result,
            example_hits=displayed_hits,
            query_representations=tuple(representations),
            index_sha256=self._frozen_index.index_sha256,
            excluded_current_page_records=excluded_current_page,
            excluded_example_count=excluded_example_count,
            excluded_family_count=excluded_family_count,
            aggregation_method=self.aggregation_method,
            example_top_k=top_k,
            candidate_limit=candidate_limit,
            aggregate_all_examples=aggregate_all_examples,
            production_integration=False,
        )
