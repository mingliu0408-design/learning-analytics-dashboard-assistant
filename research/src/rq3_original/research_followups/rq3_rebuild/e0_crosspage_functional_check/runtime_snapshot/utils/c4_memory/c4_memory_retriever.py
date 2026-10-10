"""Learner-isolated lexical and local-semantic persistent Memory retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Protocol, Sequence
import unicodedata

from .c4_memory_store import C4MemoryStore, MemoryRecord, normalise_timestamp


MPNET_REPO_ID = "sentence-transformers/all-mpnet-base-v2"
MPNET_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
MPNET_REQUIRED_HASHES = {
    "config.json": "d46a3e04ded82bba22528424480697d394eeda6a27484e08c5bb2bdf5906cfa0",
    "model.safetensors": "78c0197b6159d92658e319bc1d72e4c73a9a03dd03815e70e555c5ef05615658",
    "tokenizer.json": "b8be2c30ba5dd723a6d5ee26d013da103d5408d92ddcb23747622f9e48f1d842",
}

MEMORY_TYPE_DESCRIPTIONS = {
    "GOAL": "A learning outcome or objective the learner explicitly wants to achieve.",
    "PREFERENCE": "An explicitly stated preference about how, when, or in what format the learner studies.",
    "CONSTRAINT": "A stated limit such as available time, deadline, access restriction, or required boundary.",
    "DIFFICULTY": "A specific learning task, topic, or process the learner explicitly says is difficult.",
    "COMPLETED_ACTION": "A learning action or plan step the learner explicitly reports as finished.",
    "ACTIVE_PLAN": "A current learner-accepted action, commitment, or unfinished study plan.",
    "PROGRESS_UPDATE": "An explicit update about current progress through a learning task or plan.",
    "CORRECTION": "The learner's explicit correction replacing an older goal, preference, constraint, or plan fact.",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "in", "is",
    "it", "me", "my", "of", "on", "or", "said", "say", "that", "the", "this", "to", "was",
    "were", "what", "when", "which", "with", "would", "you", "earlier", "before", "please",
}


class SemanticBackend(Protocol):
    @property
    def identity(self) -> Mapping[str, Any]: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class FrozenLocalMPNetBackend:
    """Load the frozen MPNet snapshot locally with network access disabled.

    The implementation first uses ``sentence-transformers`` when installed and
    otherwise reproduces that snapshot's mean-pooling/normalisation pipeline
    with local ``transformers`` and ``torch``.  No repository ID is passed to a
    loader and ``local_files_only`` is always true.
    """

    def __init__(self, model_path: str | Path, *, verify_hashes: bool = True) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_dir() or self.model_path.name != MPNET_REVISION:
            raise ValueError("FROZEN_MPNET_REVISION_PATH_REQUIRED")
        self._hashes: dict[str, str] = {}
        for filename, expected in MPNET_REQUIRED_HASHES.items():
            path = self.model_path / filename
            if not path.is_file():
                raise ValueError(f"FROZEN_MPNET_FILE_MISSING:{filename}")
            if verify_hashes:
                observed = self._hash_file(path)
                if observed != expected:
                    raise ValueError(f"FROZEN_MPNET_HASH_MISMATCH:{filename}")
                self._hashes[filename] = observed
        self._encoder: Any = None
        self._tokenizer: Any = None
        self._implementation = "NOT_LOADED"

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @property
    def identity(self) -> Mapping[str, Any]:
        return {
            "backend": "FROZEN_LOCAL_MPNET",
            "repo_id": MPNET_REPO_ID,
            "revision": MPNET_REVISION,
            "local_only": True,
            "network_allowed": False,
            "implementation": self._implementation,
            "verified_file_sha256": dict(self._hashes),
        }

    def _load(self) -> None:
        if self._encoder is not None:
            return
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError:
            SentenceTransformer = None  # type: ignore[assignment]
        if SentenceTransformer is not None:
            try:
                self._encoder = SentenceTransformer(
                    str(self.model_path),
                    device="cpu",
                    local_files_only=True,
                )
                self._implementation = "SENTENCE_TRANSFORMERS"
                return
            except TypeError:
                # Older local package: path-only loading is still offline because
                # the argument is an existing directory and offline flags are set.
                self._encoder = SentenceTransformer(str(self.model_path), device="cpu")
                self._implementation = "SENTENCE_TRANSFORMERS_PATH_ONLY"
                return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("LOCAL_MPNET_RUNTIME_UNAVAILABLE") from exc
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self.model_path),
            local_files_only=True,
        )
        self._encoder = AutoModel.from_pretrained(
            str(self.model_path),
            local_files_only=True,
        )
        self._encoder.eval()
        self._encoder.to(torch.device("cpu"))
        self._implementation = "TRANSFORMERS_MEAN_POOL_NORMALISE"

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        clean = [str(text) for text in texts]
        if not clean:
            return []
        self._load()
        if self._implementation.startswith("SENTENCE_TRANSFORMERS"):
            vectors = self._encoder.encode(
                clean,
                batch_size=16,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return [[float(value) for value in vector] for vector in vectors]
        import torch

        output: list[list[float]] = []
        for start in range(0, len(clean), 16):
            batch = clean[start : start + 16]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=384,
                return_tensors="pt",
            )
            with torch.no_grad():
                hidden = self._encoder(**encoded).last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
                summed = torch.sum(hidden * mask, dim=1)
                counts = torch.clamp(mask.sum(dim=1), min=1e-9)
                pooled = summed / counts
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            output.extend([[float(value) for value in row] for row in pooled.tolist()])
        return output


def discover_local_mpnet_path(project_root: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    configured = os.environ.get("C4_MEMORY_MPNET_PATH")
    if configured:
        candidates.append(Path(configured))
    if project_root is not None:
        candidates.append(
            Path(project_root)
            / "semantic_runtime"
            / "models"
            / "all-mpnet-base-v2"
            / MPNET_REVISION
        )
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir() and all((resolved / name).is_file() for name in MPNET_REQUIRED_HASHES):
            return resolved
    return None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("VECTOR_DIMENSION_MISMATCH")
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _tokens(value: str) -> set[str]:
    normalised = unicodedata.normalize("NFKC", value).casefold()
    return {
        token
        for token in re.findall(r"[^\W_]+", normalised, flags=re.UNICODE)
        if len(token) >= 2 and token not in STOPWORDS
    }


def _history_texts(history: Sequence[Mapping[str, Any] | Sequence[Any] | str] | None) -> list[str]:
    if isinstance(history, str):
        try:
            parsed = json.loads(history)
        except json.JSONDecodeError:
            return [history] if history.strip() else []
        if isinstance(parsed, list):
            return _history_texts(parsed)
        return [history] if history.strip() else []
    output: list[str] = []
    for item in history or ():
        if isinstance(item, Mapping):
            content = item.get("content", "")
        elif isinstance(item, str):
            content = item
        elif isinstance(item, Sequence) and len(item) >= 2:
            content = item[1]
        else:
            content = ""
        if content is not None and str(content).strip():
            output.append(str(content))
    return output


def _already_visible(content: str, history_texts: Sequence[str]) -> bool:
    content_norm = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", content)).strip().casefold()
    content_tokens = _tokens(content)
    for text in history_texts:
        history_norm = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()
        if content_norm and (content_norm in history_norm or history_norm in content_norm):
            return True
        history_tokens = _tokens(text)
        union = content_tokens | history_tokens
        if union and len(content_tokens & history_tokens) / len(union) >= 0.78:
            return True
    return False


def _recency_score(created_at: str, query_time: str, half_life_days: float = 180.0) -> float:
    created = datetime.fromisoformat(created_at)
    query = datetime.fromisoformat(query_time)
    age_days = max(0.0, (query - created).total_seconds() / 86400.0)
    return float(0.5 ** (age_days / half_life_days))


@dataclass(frozen=True)
class RetrievedMemory:
    record: MemoryRecord
    lexical_score: float
    semantic_score: float
    type_alignment_score: float
    recency_score: float
    importance_score: float
    confidence_score: float
    fusion_score: float
    lexical_supported: bool
    semantic_supported: bool

    def relevance_components(self) -> dict[str, Any]:
        return {
            "lexical": round(self.lexical_score, 6),
            "semantic": round(self.semantic_score, 6),
            "memory_type_alignment": round(self.type_alignment_score, 6),
            "recency": round(self.recency_score, 6),
            "importance": round(self.importance_score, 6),
            "confidence": round(self.confidence_score, 6),
            "fusion": round(self.fusion_score, 6),
            "lexical_supported": self.lexical_supported,
            "semantic_supported": self.semantic_supported,
        }


@dataclass(frozen=True)
class RetrievalResult:
    selected: tuple[RetrievedMemory, ...]
    query_time: str
    semantic_backend: Mapping[str, Any]
    limitations: tuple[str, ...]
    active_candidate_count: int
    visible_history_excluded_count: int
    conflict_excluded_count: int

    def diagnostics(self) -> dict[str, Any]:
        return {
            "query_time": self.query_time,
            "semantic_backend": dict(self.semantic_backend),
            "limitations": list(self.limitations),
            "active_candidate_count": self.active_candidate_count,
            "visible_history_excluded_count": self.visible_history_excluded_count,
            "conflict_excluded_count": self.conflict_excluded_count,
        }


class C4MemoryRetriever:
    """Retrieve relevant, active Memory after the external capability gate."""

    def __init__(
        self,
        store: C4MemoryStore,
        *,
        semantic_backend: SemanticBackend | None = None,
        clock: Callable[[], str] | None = None,
        semantic_threshold: float = 0.36,
        typed_semantic_floor: float = 0.24,
        type_alignment_threshold: float = 0.20,
        strong_type_semantic_floor: float = 0.14,
        strong_type_alignment_threshold: float = 0.45,
    ) -> None:
        self.store = store
        self.semantic_backend = semantic_backend
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"))
        self.semantic_threshold = float(semantic_threshold)
        self.typed_semantic_floor = float(typed_semantic_floor)
        self.type_alignment_threshold = float(type_alignment_threshold)
        self.strong_type_semantic_floor = float(strong_type_semantic_floor)
        self.strong_type_alignment_threshold = float(strong_type_alignment_threshold)
        for name, value in (
            ("semantic_threshold", self.semantic_threshold),
            ("typed_semantic_floor", self.typed_semantic_floor),
            ("type_alignment_threshold", self.type_alignment_threshold),
            ("strong_type_semantic_floor", self.strong_type_semantic_floor),
            ("strong_type_alignment_threshold", self.strong_type_alignment_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"INVALID_{name.upper()}")

    @staticmethod
    def _resolve_active_conflicts(records: Sequence[MemoryRecord]) -> tuple[list[MemoryRecord], int]:
        grouped: dict[str, list[MemoryRecord]] = {}
        ungrouped: list[MemoryRecord] = []
        for record in records:
            if record.conflict_key:
                grouped.setdefault(record.conflict_key, []).append(record)
            else:
                ungrouped.append(record)
        selected = list(ungrouped)
        excluded = 0
        for candidates in grouped.values():
            candidates = sorted(
                candidates,
                key=lambda value: (
                    value.version,
                    value.last_confirmed_at,
                    value.created_at,
                    value.memory_id,
                ),
                reverse=True,
            )
            selected.append(candidates[0])
            excluded += max(0, len(candidates) - 1)
        selected.sort(key=lambda value: (value.created_at, value.memory_id))
        return selected, excluded

    def retrieve(
        self,
        student_id: str,
        student_query: str,
        visible_history: Sequence[Mapping[str, Any] | Sequence[Any] | str] | None,
        *,
        top_k: int = 5,
        at: str | datetime | None = None,
    ) -> RetrievalResult:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
            raise ValueError("TOP_K_OUT_OF_RANGE")
        query = str(student_query).strip()
        query_time = normalise_timestamp(at or self._clock())
        limitations: list[str] = []
        if not query:
            return RetrievalResult(
                selected=(),
                query_time=query_time,
                semantic_backend={"backend": "NOT_USED", "network_allowed": False},
                limitations=("EMPTY_QUERY",),
                active_candidate_count=0,
                visible_history_excluded_count=0,
                conflict_excluded_count=0,
            )
        active = self.store.list_active_memories(student_id, at=query_time)
        active, conflict_excluded = self._resolve_active_conflicts(active)
        if conflict_excluded:
            limitations.append(f"ACTIVE_CONFLICT_VERSIONS_EXCLUDED:{conflict_excluded}")
        history_text = _history_texts(visible_history)
        filtered = [record for record in active if not _already_visible(record.content, history_text)]
        visible_excluded = len(active) - len(filtered)
        if visible_excluded:
            limitations.append(f"VISIBLE_HISTORY_DUPLICATES_EXCLUDED:{visible_excluded}")
        if not filtered:
            limitations.append("NO_ELIGIBLE_ACTIVE_MEMORY")
            return RetrievalResult(
                selected=(),
                query_time=query_time,
                semantic_backend=(
                    dict(self.semantic_backend.identity)
                    if self.semantic_backend is not None
                    else {"backend": "NOT_CONFIGURED", "network_allowed": False}
                ),
                limitations=tuple(limitations),
                active_candidate_count=len(active),
                visible_history_excluded_count=visible_excluded,
                conflict_excluded_count=conflict_excluded,
            )

        fts_matches = self.store.fts_search(student_id, query, at=query_time, limit=50)
        allowed_ids = {record.memory_id for record in filtered}
        fts_by_id = {match.record.memory_id: match for match in fts_matches if match.record.memory_id in allowed_ids}
        query_tokens = _tokens(query)
        lexical_scores: dict[str, float] = {}
        for memory_id, match in fts_by_id.items():
            content_tokens = _tokens(match.record.content)
            overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            rank_score = 1.0 / math.log2(match.rank_position + 1.0)
            lexical_scores[memory_id] = min(1.0, 0.65 * rank_score + 0.35 * overlap)

        semantic_scores = {record.memory_id: 0.0 for record in filtered}
        type_scores = {record.memory_type: 0.5 for record in filtered}
        semantic_identity: Mapping[str, Any] = {"backend": "NOT_CONFIGURED", "network_allowed": False}
        semantic_available = False
        if self.semantic_backend is None:
            limitations.append("SEMANTIC_BACKEND_NOT_CONFIGURED")
        else:
            try:
                type_names = list(MEMORY_TYPE_DESCRIPTIONS)
                vectors = self.semantic_backend.encode(
                    [query]
                    + [record.content for record in filtered]
                    + [MEMORY_TYPE_DESCRIPTIONS[name] for name in type_names]
                )
                expected = 1 + len(filtered) + len(type_names)
                if len(vectors) != expected:
                    raise RuntimeError("SEMANTIC_VECTOR_COUNT_MISMATCH")
                query_vector = vectors[0]
                for record, vector in zip(filtered, vectors[1 : 1 + len(filtered)]):
                    semantic_scores[record.memory_id] = max(0.0, min(1.0, _cosine(query_vector, vector)))
                type_offset = 1 + len(filtered)
                for name, vector in zip(type_names, vectors[type_offset:]):
                    type_scores[name] = max(0.0, min(1.0, _cosine(query_vector, vector)))
                semantic_identity = dict(self.semantic_backend.identity)
                semantic_available = True
            except Exception as exc:
                semantic_identity = {
                    "backend": "UNAVAILABLE",
                    "network_allowed": False,
                    "failure_type": type(exc).__name__,
                }
                limitations.append(f"SEMANTIC_BACKEND_UNAVAILABLE:{type(exc).__name__}")

        ranked: list[RetrievedMemory] = []
        for record in filtered:
            lexical = lexical_scores.get(record.memory_id, 0.0)
            semantic = semantic_scores.get(record.memory_id, 0.0)
            type_alignment = type_scores.get(record.memory_type, 0.5)
            lexical_supported = lexical >= 0.50
            strong_semantic_support = semantic >= self.semantic_threshold
            typed_semantic_support = (
                semantic >= self.typed_semantic_floor
                and type_alignment >= self.type_alignment_threshold
            )
            strong_type_semantic_support = (
                semantic >= self.strong_type_semantic_floor
                and type_alignment >= self.strong_type_alignment_threshold
            )
            semantic_supported = semantic_available and (
                strong_semantic_support
                or typed_semantic_support
                or strong_type_semantic_support
            )
            hybrid_supported = semantic_available and lexical >= 0.22 and semantic >= 0.28
            if not (lexical_supported or semantic_supported or hybrid_supported):
                continue
            recency = _recency_score(record.created_at, query_time)
            if semantic_available:
                base = 0.38 * lexical + 0.44 * semantic + 0.18 * type_alignment
            else:
                base = 0.82 * lexical + 0.18 * type_alignment
            fusion = min(
                1.0,
                base
                + 0.025 * recency
                + 0.025 * record.importance
                + 0.025 * record.confidence,
            )
            ranked.append(
                RetrievedMemory(
                    record=record,
                    lexical_score=lexical,
                    semantic_score=semantic,
                    type_alignment_score=type_alignment,
                    recency_score=recency,
                    importance_score=record.importance,
                    confidence_score=record.confidence,
                    fusion_score=fusion,
                    lexical_supported=lexical_supported,
                    semantic_supported=semantic_supported,
                )
            )
        ranked.sort(
            key=lambda item: (
                -item.fusion_score,
                -item.semantic_score,
                -item.lexical_score,
                -item.record.version,
                -datetime.fromisoformat(item.record.created_at).timestamp(),
                item.record.memory_id,
            )
        )
        if not ranked:
            limitations.append("NO_RELEVANCE_SUPPORTED")
        return RetrievalResult(
            selected=tuple(ranked[:top_k]),
            query_time=query_time,
            semantic_backend=semantic_identity,
            limitations=tuple(limitations),
            active_candidate_count=len(active),
            visible_history_excluded_count=visible_excluded,
            conflict_excluded_count=conflict_excluded,
        )
