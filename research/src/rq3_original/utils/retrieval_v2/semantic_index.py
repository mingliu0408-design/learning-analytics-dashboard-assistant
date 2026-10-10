"""Optional local semantic retrieval providers for Retrieval v2."""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import math
from typing import Iterable, Sequence

import numpy as np

from .models import CourseChunkV2


class EmbeddingProviderV2(ABC):
    identifier = "unknown"

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...

    @property
    def warning(self) -> str:
        return ""


class DisabledEmbeddingProvider(EmbeddingProviderV2):
    identifier = "disabled"

    @property
    def available(self) -> bool:
        return False

    @property
    def dimension(self) -> int:
        return 0

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        raise RuntimeError("Semantic embeddings are disabled.")

    @property
    def warning(self) -> str:
        return "Semantic retrieval is unavailable; running BM25 plus metadata reranking."


class FakeEmbeddingProvider(EmbeddingProviderV2):
    """Deterministic hashed token embeddings for tests only."""

    identifier = "fake-deterministic-v1"

    def __init__(self, dimension: int = 48) -> None:
        self._dimension = dimension

    @property
    def available(self) -> bool:
        return True

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in str(text).casefold().split():
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                vectors[row, index] += -1.0 if digest[4] & 1 else 1.0
            norm = float(np.linalg.norm(vectors[row]))
            if norm:
                vectors[row] /= norm
        return vectors


class SentenceTransformerEmbeddingProvider(EmbeddingProviderV2):
    """Local-only sentence-transformer adapter; never downloads a model."""

    def __init__(self, model_name: str) -> None:
        self.identifier = model_name
        self._model = None
        self._warning = ""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name, local_files_only=True)
        except Exception as exc:
            self._warning = (
                f"Local semantic model {model_name!r} is unavailable ({type(exc).__name__}); "
                "no download was attempted."
            )

    @property
    def available(self) -> bool:
        return self._model is not None

    @property
    def dimension(self) -> int:
        if self._model is None:
            return 0
        return int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if self._model is None:
            raise RuntimeError(self._warning or "Local semantic model is unavailable.")
        return np.asarray(
            self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )

    @property
    def warning(self) -> str:
        return self._warning


class SemanticIndexV2:
    def __init__(
        self,
        chunks: Iterable[CourseChunkV2],
        provider: EmbeddingProviderV2,
        embeddings: np.ndarray | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.provider = provider
        texts = [" ".join((item.title, " ".join(item.section_path), item.text)) for item in self.chunks]
        self.embeddings = (
            np.asarray(embeddings, dtype=np.float32)
            if embeddings is not None
            else provider.encode(texts)
            if provider.available and texts
            else np.empty((0, provider.dimension), dtype=np.float32)
        )

    def search(self, query: str, top_k: int) -> list[tuple[CourseChunkV2, float]]:
        if not self.provider.available or not len(self.embeddings):
            return []
        query_vector = self.provider.encode([query])[0]
        query_norm = float(np.linalg.norm(query_vector))
        if not query_norm:
            return []
        matrix_norms = np.linalg.norm(self.embeddings, axis=1)
        denominators = matrix_norms * query_norm
        scores = np.divide(
            self.embeddings @ query_vector,
            denominators,
            out=np.zeros_like(matrix_norms),
            where=denominators != 0,
        )
        ranked = [(self.chunks[index], float(score)) for index, score in enumerate(scores) if math.isfinite(float(score))]
        ranked.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return ranked[: max(0, top_k)]
