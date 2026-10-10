"""Build and validate the isolated role-enriched Retrieval v2.4 index."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from utils.retrieval_v2.index_store import load_index_bundle_v2

from .config import DEFAULT_CONFIG_V24, RETRIEVAL_VERSION_V24, ROLE_EXTRACTION_VERSION, RetrievalConfigV24
from .models import CourseChunkV24
from .roles import derive_content_roles


class IndexValidationErrorV24(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedIndexBundleV24:
    metadata: dict[str, Any]
    chunks: tuple[CourseChunkV24, ...]
    backend_mode: str = "lexical_degraded"
    validation_warnings: tuple[str, ...] = ()


def compute_index_hash_v24(chunks: tuple[CourseChunkV24, ...] | list[CourseChunkV24]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.chunk_id):
        digest.update(
            json.dumps(
                chunk.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        )
    return digest.hexdigest()


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _role_counts(chunks: tuple[CourseChunkV24, ...] | list[CourseChunkV24]) -> dict[str, int]:
    counts = Counter(role for chunk in chunks for role in chunk.content_roles)
    return dict(sorted(counts.items()))


def build_index_v24(config: RetrievalConfigV24 = DEFAULT_CONFIG_V24) -> dict[str, Any]:
    base = load_index_bundle_v2()
    chunks = [
        CourseChunkV24.from_v23(chunk, derive_content_roles(chunk)) for chunk in base.chunks
    ]
    payload = {
        "retrieval_version": RETRIEVAL_VERSION_V24,
        "base_retrieval_version": base.metadata["retrieval_version"],
        "base_index_hash": base.metadata["index_hash"],
        "manifest_hash": base.metadata["manifest_hash"],
        "source_hashes": base.metadata["source_hashes"],
        "chunking_configuration": base.metadata["chunking_configuration"],
        "role_extraction_version": ROLE_EXTRACTION_VERSION,
        "retrieval_configuration": config.fingerprint_dict(),
    }
    fingerprint = _fingerprint(payload)
    metadata_path = config.index_dir / "index_metadata_v2_4.json"
    chunks_path = config.index_dir / "chunks_v2_4.json"
    if metadata_path.is_file() and chunks_path.is_file():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        if existing.get("build_fingerprint") == fingerprint:
            try:
                load_index_bundle_v24(config)
            except IndexValidationErrorV24:
                pass
            else:
                return {**existing, "rebuilt": False}
    metadata = {
        **payload,
        "build_fingerprint": fingerprint,
        "index_hash": compute_index_hash_v24(chunks),
        "document_count": len({chunk.document_id for chunk in chunks}),
        "chunk_count": len(chunks),
        "chunks_with_roles": sum(bool(chunk.content_roles) for chunk in chunks),
        "content_role_counts": _role_counts(chunks),
        "backend_mode": "lexical_degraded",
        "semantic_backend_available": False,
        "creation_time": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(chunks_path, [chunk.to_dict() for chunk in chunks])
    _atomic_json(metadata_path, metadata)
    return {**metadata, "rebuilt": True}


def load_index_bundle_v24(
    config: RetrievalConfigV24 = DEFAULT_CONFIG_V24,
) -> LoadedIndexBundleV24:
    metadata_path = config.index_dir / "index_metadata_v2_4.json"
    chunks_path = config.index_dir / "chunks_v2_4.json"
    if not metadata_path.is_file() or not chunks_path.is_file():
        raise IndexValidationErrorV24(
            "Retrieval v2.4 index is missing. Build explicitly with: "
            "python -m utils.retrieval_v2_4.index_store build"
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        chunks = tuple(
            CourseChunkV24.from_dict(item)
            for item in json.loads(chunks_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise IndexValidationErrorV24(f"Unreadable Retrieval v2.4 index: {exc}") from exc
    base = load_index_bundle_v2()
    expected_payload = {
        "retrieval_version": RETRIEVAL_VERSION_V24,
        "base_retrieval_version": base.metadata["retrieval_version"],
        "base_index_hash": base.metadata["index_hash"],
        "manifest_hash": base.metadata["manifest_hash"],
        "source_hashes": base.metadata["source_hashes"],
        "chunking_configuration": base.metadata["chunking_configuration"],
        "role_extraction_version": ROLE_EXTRACTION_VERSION,
        "retrieval_configuration": config.fingerprint_dict(),
    }
    checks = {
        "retrieval_version": metadata.get("retrieval_version") == RETRIEVAL_VERSION_V24,
        "base_index_hash": metadata.get("base_index_hash") == base.metadata["index_hash"],
        "source_hashes": metadata.get("source_hashes") == base.metadata["source_hashes"],
        "role_extraction_version": metadata.get("role_extraction_version") == ROLE_EXTRACTION_VERSION,
        "build_fingerprint": metadata.get("build_fingerprint") == _fingerprint(expected_payload),
        "chunk_count": metadata.get("chunk_count") == len(chunks),
        "document_count": metadata.get("document_count") == len({chunk.document_id for chunk in chunks}),
        "index_hash": metadata.get("index_hash") == compute_index_hash_v24(chunks),
        "role_counts": metadata.get("content_role_counts") == _role_counts(chunks),
    }
    failed = [name for name, valid in checks.items() if not valid]
    if failed:
        raise IndexValidationErrorV24(
            "Retrieval v2.4 index validation failed: " + ", ".join(failed)
        )
    return LoadedIndexBundleV24(metadata=metadata, chunks=chunks)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_CONFIG_V24.index_dir)
    args = parser.parse_args(argv)
    config = RetrievalConfigV24(**{**DEFAULT_CONFIG_V24.__dict__, "index_dir": args.index_dir})
    print(json.dumps(build_index_v24(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
