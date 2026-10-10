"""Shared, validated embedding adapters for Track C B2 and B3."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

from utils.semantic_intent_router import (
    EmbeddingBackendUnavailable,
    SentenceTransformerEmbeddingBackend,
    validate_embedding_matrix,
)

from .errors import EmbeddingAdapterError


FROZEN_REPO_ID = "sentence-transformers/all-mpnet-base-v2"
FROZEN_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
FROZEN_DIMENSION = 768


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Minimum adapter contract used identically by both Track C methods."""

    @property
    def model_id(self) -> str:
        ...

    @property
    def dimension(self) -> int:
        ...

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        ...


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EmbeddingAdapterError(f"required encoder config is unavailable: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingAdapterError(f"unable to read encoder config: {path}") from exc
    if not isinstance(value, dict):
        raise EmbeddingAdapterError(f"encoder config must be a JSON object: {path}")
    return value


class FrozenMpnetEmbeddingAdapter:
    """Reuse the repository C0 MPNet backend without index access or download.

    ``project_root`` may point at another checkout containing the exact frozen
    local assets. Nothing is copied. The Stage 0 and production identities must
    agree before the existing local-only backend is constructed.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        batch_size: int = 32,
        device: str = "cpu",
    ) -> None:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise EmbeddingAdapterError(f"project root is unavailable: {root}")
        stage0_config = _load_json_object(
            root
            / "evaluation/capability_routing_rq2_v2_stage0/config/"
            "b1_legacy_interface_v1.json"
        )
        runtime_config = _load_json_object(
            root / "semantic_runtime/config/semantic_routing_config.json"
        )
        stage0_encoder = stage0_config.get("encoder") or {}
        runtime_encoder = runtime_config.get("model") or {}
        expected_identity = {
            "repo_id": FROZEN_REPO_ID,
            "revision": FROZEN_REVISION,
            "local_files_only": True,
        }
        for field, expected in expected_identity.items():
            if stage0_encoder.get(field) != expected or runtime_encoder.get(field) != expected:
                raise EmbeddingAdapterError(
                    f"frozen MPNet identity mismatch for {field}: expected {expected!r}"
                )
        if int(stage0_encoder.get("embedding_dimension", 0)) != FROZEN_DIMENSION:
            raise EmbeddingAdapterError("frozen MPNet embedding dimension mismatch")
        if runtime_config.get("allow_network_downloads") is not False:
            raise EmbeddingAdapterError("semantic runtime does not prohibit downloads")
        local_relative = Path(str(stage0_encoder.get("local_path", "")))
        if local_relative.is_absolute() or ".." in local_relative.parts:
            raise EmbeddingAdapterError("frozen MPNet local path is unsafe")
        model_path = root / local_relative
        if not model_path.is_dir():
            raise EmbeddingAdapterError(
                "expected frozen local MPNet assets are unavailable at " + str(model_path)
            )
        if model_path.name != FROZEN_REVISION:
            raise EmbeddingAdapterError("frozen MPNet revision directory mismatch")
        required_members = ("config.json", "modules.json", "tokenizer.json")
        missing = [name for name in required_members if not (model_path / name).is_file()]
        if missing:
            raise EmbeddingAdapterError(
                "frozen local MPNet assets are incomplete: " + ", ".join(missing)
            )
        self._model_id = f"{FROZEN_REPO_ID}@{FROZEN_REVISION}"
        self._backend = SentenceTransformerEmbeddingBackend(
            model_path,
            repo_id=FROZEN_REPO_ID,
            revision=FROZEN_REVISION,
            device=device,
            batch_size=batch_size,
            allow_model_download=False,
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return FROZEN_DIMENSION

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        try:
            raw = self._backend.encode(texts)
            validated = validate_embedding_matrix(
                raw,
                expected_rows=len(texts),
                expected_dimension=FROZEN_DIMENSION,
            )
        except EmbeddingBackendUnavailable as exc:
            raise EmbeddingAdapterError(
                f"frozen local MPNet backend unavailable: {exc.reason}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise EmbeddingAdapterError(f"invalid frozen MPNet output: {exc}") from exc
        return np.asarray(validated, dtype=np.float64)


def adapter_signature(adapter: EmbeddingAdapter) -> tuple[str, int]:
    try:
        model_id = str(adapter.model_id).strip()
        dimension = int(adapter.dimension)
    except Exception as exc:
        raise EmbeddingAdapterError("embedding adapter identity is unavailable") from exc
    if not model_id:
        raise EmbeddingAdapterError("embedding adapter model_id must be non-empty")
    if dimension < 1:
        raise EmbeddingAdapterError("embedding adapter dimension must be positive")
    return model_id, dimension


def validated_encode(
    adapter: EmbeddingAdapter,
    texts: Sequence[str],
) -> np.ndarray:
    """Encode one non-empty batch and enforce stable numeric shape and norms."""

    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise EmbeddingAdapterError("embedding texts must be non-empty strings")
    _model_id, dimension = adapter_signature(adapter)
    try:
        matrix = np.asarray(adapter.encode(texts))
        validated = validate_embedding_matrix(
            matrix,
            expected_rows=len(texts),
            expected_dimension=dimension,
        )
    except EmbeddingAdapterError:
        raise
    except Exception as exc:
        raise EmbeddingAdapterError(f"embedding adapter failed: {exc}") from exc
    norms = np.linalg.norm(validated, axis=1)
    if np.any(norms <= 0.0):
        positions = np.flatnonzero(norms <= 0.0).tolist()
        raise EmbeddingAdapterError(f"zero-norm embedding rows: {positions}")
    return np.asarray(validated, dtype=np.float64)
