"""Verified external source binding and legacy chunk recovery."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from utils import course_material_retriever as legacy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_CFULL_ROOT = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3"
)
MPNET_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
CANONICAL_MPNET_ROOT = (
    CANONICAL_CFULL_ROOT
    / "semantic_runtime/models/all-mpnet-base-v2"
    / MPNET_REVISION
)

EXPECTED_SOURCE_HASHES = {
    "System Data/Module/Module Weekly Pages.html": "799e0c07bd5655cc3caffa80b320cd4cafda4677d3e1664d951acb0b45740489",
    "System Data/Module/Module Handbook.doc": "296ca2e803bf687d328153268354211332f093ca19c691166b53532be62c077f",
    "System Data/Module/Module readings.pdf": "351e4e33919cdb5fe29347ed9df2fdf37eca794b736ac88cca4c610bedf087f0",
    "input/moodle_links.pdf": "85d5b03508d2e124e32f812dc4bd6ec96110851b275254a271f53cb3119b1d27",
    "input/references.txt": "136e26d35ac435b062192551b14216cf049f3e2b5022cf585389e6762f9cb8e9",
    "utils/course_metadata.py": "b8975fc20897fc1b98d2bcb5076e3950300e5498b46cf4793840980a6a1a9d83",
}

LEGACY_SOURCE_PATHS = {
    "weekly_pages": CANONICAL_CFULL_ROOT / "System Data/Module/Module Weekly Pages.html",
    "handbook": CANONICAL_CFULL_ROOT / "System Data/Module/Module Handbook.doc",
    "readings": CANONICAL_CFULL_ROOT / "System Data/Module/Module readings.pdf",
    "moodle_links": CANONICAL_CFULL_ROOT / "input/moodle_links.pdf",
    "references": CANONICAL_CFULL_ROOT / "input/references.txt",
}

SOURCE_DOCUMENTS = {
    "System Data/Module/Module Weekly Pages.html": (
        "module_weekly_pages",
        "Module Weekly Pages",
    ),
    "System Data/Module/Module Handbook.doc": ("module_handbook", "Module Handbook"),
    "System Data/Module/Module readings.pdf": (
        "module_reading_list",
        "Module readings",
    ),
    "input/moodle_links.pdf": ("moodle_links", "moodle_links"),
    "input/references.txt": ("dashboard_references", "references"),
    "utils/course_metadata.py": ("verified_lecture_metadata", "course_metadata"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_canonical_sources() -> dict[str, str]:
    """Fail closed unless every canonical course source matches its frozen hash."""

    verified: dict[str, str] = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        path = PROJECT_ROOT / relative if relative == "utils/course_metadata.py" else CANONICAL_CFULL_ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"BLOCKED_MISSING_AUTHENTIC_COURSE_CORPUS: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(
                f"Authentic course source hash mismatch for {path}: {actual} != {expected}"
            )
        verified[relative] = actual
    return verified


def _ensure_pdf_parser_available() -> None:
    """Expose the already-installed pure-Python pypdf package to Python 3.11.

    The compatible torch runtime is Python 3.11 while the local pypdf package is
    installed under the base Python 3.13 tree.  Import pypdf alone while that
    directory is temporarily visible, then remove the directory before any
    numerical or transformer imports.  No package or environment is modified.
    """

    try:
        __import__("pypdf")
        return
    except ModuleNotFoundError:
        pass
    candidate = Path("/opt/anaconda3/lib/python3.13/site-packages")
    if not candidate.is_dir():
        raise RuntimeError("An installed local PDF parser was not available")
    value = str(candidate)
    sys.path.append(value)
    try:
        __import__("pypdf")
    finally:
        if value in sys.path:
            sys.path.remove(value)


@lru_cache(maxsize=1)
def load_legacy_chunks() -> tuple[Any, ...]:
    """Recover the exact legacy chunks without editing the legacy module."""

    verify_canonical_sources()
    _ensure_pdf_parser_available()
    legacy.COURSE_MATERIAL_PATHS = dict(LEGACY_SOURCE_PATHS)
    chunks = tuple(legacy.build_course_chunks())
    if not chunks:
        raise RuntimeError("BLOCKED_MISSING_AUTHENTIC_COURSE_CORPUS")
    ids = [str(chunk.chunk_id) for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Legacy course chunk IDs are not unique")
    # Make the unchanged public legacy entrypoint reuse the verified corpus.
    legacy._CHUNK_CACHE = list(chunks)
    return chunks


def legacy_chunk_corpus_hash(chunks: Sequence[Any] | None = None) -> str:
    values = chunks or load_legacy_chunks()
    rows = [
        {
            "chunk_id": item.chunk_id,
            "source_file": item.source_file,
            "source_type": item.source_type,
            "title": item.title,
            "text": item.text,
            "week": item.week,
            "page": item.page,
            "task_type": item.task_type,
            "metadata": item.metadata,
        }
        for item in values
    ]
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_identity(source_file: str) -> tuple[str, str, str]:
    relative = str(source_file)
    document_id, title = SOURCE_DOCUMENTS.get(
        relative,
        (re.sub(r"[^a-z0-9]+", "_", Path(relative).stem.casefold()).strip("_"), Path(relative).stem),
    )
    source_hash = EXPECTED_SOURCE_HASHES.get(relative, "")
    if not source_hash:
        path = PROJECT_ROOT / relative
        if path.is_file():
            source_hash = sha256_file(path)
    return document_id, title, source_hash


def section_for_chunk(chunk: Any) -> str | None:
    metadata = dict(getattr(chunk, "metadata", {}) or {})
    return str(
        metadata.get("section_title")
        or metadata.get("section_path")
        or getattr(chunk, "title", "")
        or ""
    ).strip() or None


def normalise_history(visible_history: Any) -> tuple[dict[str, str], ...]:
    if not visible_history:
        return ()
    if isinstance(visible_history, str):
        return ({"role": "unknown", "content": visible_history},)
    rows: list[dict[str, str]] = []
    if isinstance(visible_history, Mapping):
        visible_history = [visible_history]
    for value in visible_history:
        if isinstance(value, Mapping):
            content = str(value.get("content") or value.get("text") or "").strip()
            role = str(value.get("role") or "unknown").strip()
        else:
            content = str(value).strip()
            role = "unknown"
        if content:
            rows.append({"role": role, "content": content})
    return tuple(rows)


def resolved_hybrid_query(query: str, visible_history: Any) -> tuple[str, bool]:
    """Deterministically expose bounded visible context; no model rewrite."""

    current = str(query or "").strip()
    history = normalise_history(visible_history)
    anaphoric = bool(
        re.search(
            r"\b(?:second|first|third|this|that|those|these|it|what about|continue|earlier)\b",
            current,
            flags=re.IGNORECASE,
        )
    )
    if not history or not anaphoric:
        return current, False
    context = " ".join(item["content"] for item in history[-2:])[-800:]
    return f"{current}\nVisible conversation context: {context}", True
