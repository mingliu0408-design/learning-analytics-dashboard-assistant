"""Versioned, atomic Retrieval v2 index storage."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

from .chunking import chunk_documents
from .config import DEFAULT_CONFIG, RETRIEVAL_VERSION, RetrievalConfigV2
from .ingestion import ingest_manifest
from .manifest import load_manifest, manifest_hash, sha256_file, source_path_for
from .models import CourseChunkV2
from .semantic_index import (
    DisabledEmbeddingProvider,
    EmbeddingProviderV2,
    SentenceTransformerEmbeddingProvider,
)


class IndexValidationErrorV2(RuntimeError):
    """Raised when a persisted Retrieval v2 index is missing, stale, or corrupt."""


@dataclass(frozen=True)
class LoadedIndexBundleV2:
    """Validated authoritative runtime index data."""

    metadata: dict[str, Any]
    chunks: tuple[CourseChunkV2, ...]
    embeddings: np.ndarray | None
    backend_mode: str
    embedding_provider_metadata: dict[str, Any]
    validation_warnings: tuple[str, ...] = ()


def compute_index_hash(chunks: list[CourseChunkV2] | tuple[CourseChunkV2, ...]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.chunk_id):
        digest.update(
            json.dumps(
                chunk.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        )
    return digest.hexdigest()


def chunking_configuration(config: RetrievalConfigV2) -> dict[str, Any]:
    return {
        "target_chunk_chars": config.target_chunk_chars,
        "min_chunk_chars": config.min_chunk_chars,
        "max_chunk_chars": config.max_chunk_chars,
        "overlap_chars": config.overlap_chars,
        "maximum_prompt_expanded_context_chars": config.maximum_prompt_expanded_context_chars,
        "maximum_chunks_per_source": config.maximum_chunks_per_source,
    }


def _current_source_hashes(config: RetrievalConfigV2) -> dict[str, str]:
    records = load_manifest(config.manifest_path)
    hashes: dict[str, str] = {}
    for record in records:
        if not record.enabled:
            continue
        path = source_path_for(record)
        hashes[record.document_id] = sha256_file(path) if path.is_file() else ""
    return hashes


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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


def _atomic_numpy(path: Path, value: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".npy", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            np.save(handle, value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_index(
    config: RetrievalConfigV2 = DEFAULT_CONFIG,
    semantic_disabled: bool = True,
    embedding_model: str | None = None,
    embedding_provider: EmbeddingProviderV2 | None = None,
) -> dict[str, Any]:
    records = load_manifest(config.manifest_path)
    documents = ingest_manifest(records)
    chunks = chunk_documents(documents, config)
    provider = embedding_provider or (
        DisabledEmbeddingProvider()
        if semantic_disabled
        else SentenceTransformerEmbeddingProvider(embedding_model or config.embedding_model)
    )
    if not semantic_disabled and not provider.available:
        raise RuntimeError(
            provider.warning
            or "The requested local embedding model is unavailable; no download was attempted."
        )
    source_hashes = {document.document_id: document.source_hash for document in documents}
    settings = chunking_configuration(config)
    fingerprint_payload = {
        "retrieval_version": RETRIEVAL_VERSION,
        "manifest_hash": manifest_hash(config.manifest_path),
        "source_hashes": source_hashes,
        "chunking_configuration": settings,
        "embedding_model_identifier": provider.identifier,
    }
    build_fingerprint = _fingerprint(fingerprint_payload)
    metadata_path = config.index_dir / "index_metadata_v2.json"
    chunks_path = config.index_dir / "chunks_v2.json"
    if metadata_path.exists() and chunks_path.exists():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        if existing.get("build_fingerprint") == build_fingerprint:
            try:
                load_index_bundle_v2(config, require_fresh=True)
            except IndexValidationErrorV2:
                pass
            else:
                return {**existing, "rebuilt": False}
    metadata = {
        **fingerprint_payload,
        "build_fingerprint": build_fingerprint,
        "index_hash": compute_index_hash(chunks),
        "semantic_backend_available": provider.available,
        "backend_mode": "hybrid" if provider.available else "lexical_degraded",
        "embedding_dimension": provider.dimension,
        "creation_time": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "extraction_warnings": {
            document.document_id: list(document.warnings)
            for document in documents if document.warnings
        },
    }
    if provider.available:
        embedding_texts = [
            " ".join((chunk.title, " ".join(chunk.section_path), chunk.text)) for chunk in chunks
        ]
        embeddings = provider.encode(embedding_texts)
        _atomic_numpy(config.index_dir / "embeddings_v2.npy", embeddings)
        metadata["embedding_rows"] = int(embeddings.shape[0])
        metadata["embeddings_hash"] = hashlib.sha256(embeddings.tobytes()).hexdigest()
    _atomic_json(chunks_path, [chunk.to_dict() for chunk in chunks])
    _atomic_json(metadata_path, metadata)
    return {**metadata, "rebuilt": True}


def load_chunks(config: RetrievalConfigV2 = DEFAULT_CONFIG) -> list[CourseChunkV2]:
    """Compatibility helper that never silently builds an index."""

    return list(load_index_bundle_v2(config).chunks)


def load_index_bundle_v2(
    config: RetrievalConfigV2 = DEFAULT_CONFIG,
    *,
    require_fresh: bool = True,
    allow_lexical_degraded: bool = True,
) -> LoadedIndexBundleV2:
    """Load and validate the authoritative persisted Retrieval v2 bundle."""

    metadata_path = config.index_dir / "index_metadata_v2.json"
    chunks_path = config.index_dir / "chunks_v2.json"
    build_command = "python -m utils.retrieval_v2.index_store build --semantic-disabled"
    missing = [str(path) for path in (metadata_path, chunks_path) if not path.is_file()]
    if missing:
        raise IndexValidationErrorV2(
            "Retrieval v2 index is missing: " + ", ".join(missing)
            + f". Build it explicitly with: {build_command}"
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        raw_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
        chunks = tuple(CourseChunkV2.from_dict(item) for item in raw_chunks)
    except Exception as exc:
        raise IndexValidationErrorV2(
            f"Retrieval v2 index JSON is unreadable or invalid: {type(exc).__name__}: {exc}"
        ) from exc

    errors: list[str] = []
    warnings: list[str] = []
    stored_version = str(metadata.get("retrieval_version") or "")
    if require_fresh and stored_version != RETRIEVAL_VERSION:
        errors.append(f"retrieval_version expected {RETRIEVAL_VERSION}, found {stored_version}")
    if int(metadata.get("chunk_count", -1)) != len(chunks):
        errors.append(
            f"chunk_count expected {metadata.get('chunk_count')}, loaded {len(chunks)}"
        )
    document_count = len({chunk.document_id for chunk in chunks})
    if int(metadata.get("document_count", -1)) != document_count:
        errors.append(
            f"document_count expected {metadata.get('document_count')}, loaded {document_count}"
        )
    loaded_index_hash = compute_index_hash(chunks)
    if metadata.get("index_hash") != loaded_index_hash:
        errors.append(
            f"index_hash expected {metadata.get('index_hash')}, computed {loaded_index_hash}"
        )

    embedding_identifier = str(metadata.get("embedding_model_identifier") or "")
    if require_fresh:
        current_manifest_hash = manifest_hash(config.manifest_path)
        if metadata.get("manifest_hash") != current_manifest_hash:
            errors.append(
                f"manifest_hash expected {metadata.get('manifest_hash')}, current {current_manifest_hash}"
            )
        current_source_hashes = _current_source_hashes(config)
        if metadata.get("source_hashes") != current_source_hashes:
            changed = sorted(
                key for key in set(current_source_hashes) | set(metadata.get("source_hashes") or {})
                if current_source_hashes.get(key) != (metadata.get("source_hashes") or {}).get(key)
            )
            errors.append("source_hashes changed for: " + ", ".join(changed))
        current_chunking = chunking_configuration(config)
        if metadata.get("chunking_configuration") != current_chunking:
            errors.append("chunking_configuration does not match current RetrievalConfigV2")
        expected_payload = {
            "retrieval_version": RETRIEVAL_VERSION,
            "manifest_hash": current_manifest_hash,
            "source_hashes": current_source_hashes,
            "chunking_configuration": current_chunking,
            "embedding_model_identifier": embedding_identifier,
        }
        expected_fingerprint = _fingerprint(expected_payload)
        if metadata.get("build_fingerprint") != expected_fingerprint:
            errors.append(
                f"build_fingerprint expected {expected_fingerprint}, found {metadata.get('build_fingerprint')}"
            )

    semantic_declared = bool(metadata.get("semantic_backend_available")) or metadata.get("backend_mode") == "hybrid"
    embeddings: np.ndarray | None = None
    embeddings_path = config.index_dir / "embeddings_v2.npy"
    if semantic_declared:
        if not embedding_identifier or embedding_identifier == "disabled":
            errors.append(
                "semantic index metadata must declare a usable embedding model identifier"
            )
        if int(metadata.get("embedding_dimension", 0)) <= 0:
            errors.append("semantic index metadata must declare a positive embedding dimension")
        if not embeddings_path.is_file():
            errors.append("semantic index metadata declares embeddings, but embeddings_v2.npy is missing")
        else:
            try:
                embeddings = np.load(embeddings_path, allow_pickle=False)
            except Exception as exc:
                errors.append(f"embeddings_v2.npy could not be loaded: {type(exc).__name__}: {exc}")
            if embeddings is not None:
                if embeddings.ndim != 2:
                    errors.append(f"embeddings must be a 2D matrix, found shape {embeddings.shape}")
                else:
                    stored_rows = int(metadata.get("embedding_rows", -1))
                    stored_dimension = int(metadata.get("embedding_dimension", -1))
                    if embeddings.shape[0] != stored_rows or stored_rows != len(chunks):
                        errors.append(
                            f"embedding row count mismatch: metadata={stored_rows}, matrix={embeddings.shape[0]}, chunks={len(chunks)}"
                        )
                    if embeddings.shape[1] != stored_dimension:
                        errors.append(
                            f"embedding dimension mismatch: metadata={stored_dimension}, matrix={embeddings.shape[1]}"
                        )
                    computed_embeddings_hash = hashlib.sha256(embeddings.tobytes()).hexdigest()
                    if metadata.get("embeddings_hash") != computed_embeddings_hash:
                        errors.append(
                            f"embeddings_hash expected {metadata.get('embeddings_hash')}, computed {computed_embeddings_hash}"
                        )
    elif embeddings_path.exists():
        warnings.append("An undeclared embeddings_v2.npy file exists and was ignored.")

    backend_mode = "hybrid" if semantic_declared else "lexical_degraded"
    if backend_mode == "lexical_degraded" and not allow_lexical_degraded:
        errors.append("A lexical-degraded index is valid, but allow_lexical_degraded is false")
    if errors:
        raise IndexValidationErrorV2(
            "Persisted Retrieval v2 index validation failed: " + "; ".join(errors)
            + ". Rebuild explicitly with: " + build_command
        )
    return LoadedIndexBundleV2(
        metadata=metadata,
        chunks=chunks,
        embeddings=embeddings,
        backend_mode=backend_mode,
        embedding_provider_metadata={
            "identifier": embedding_identifier,
            "dimension": int(metadata.get("embedding_dimension", 0)),
            "rows": int(metadata.get("embedding_rows", 0)),
            "semantic_index_declared": semantic_declared,
        },
        validation_warnings=tuple(warnings),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the Retrieval v2 index")
    parser.add_argument("command", choices=["build"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--semantic-disabled", action="store_true")
    mode.add_argument("--embedding-model")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_CONFIG.index_dir)
    args = parser.parse_args(argv)
    config = RetrievalConfigV2(
        **{
            **DEFAULT_CONFIG.__dict__,
            "index_dir": args.index_dir,
        }
    )
    metadata = build_index(
        config=config,
        semantic_disabled=not bool(args.embedding_model),
        embedding_model=args.embedding_model,
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
