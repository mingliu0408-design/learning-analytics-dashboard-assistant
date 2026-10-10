"""Text-free local embedding caches shared by all twenty RQ1-B runs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import EMBEDDING_DIR, ROOT
from .governed_data_loader import sha256_file


def matrix_sha256(matrix: np.ndarray) -> str:
    value = np.asarray(matrix, dtype=np.float32)
    return hashlib.sha256(value.tobytes(order="C")).hexdigest()


def _text_array(values: Iterable[str]) -> np.ndarray:
    rows = [str(value) for value in values]
    width = max((len(value) for value in rows), default=1)
    return np.asarray(rows, dtype=f"<U{width}")


def _write_npz(
    path: Path,
    *,
    record_ids: list[str],
    embeddings: np.ndarray,
    representation_hashes: list[str],
    encoder_identity: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        record_ids=_text_array(record_ids),
        embeddings=np.asarray(embeddings, dtype=np.float32),
        representation_sha256=_text_array(representation_hashes),
        encoder_identity=_text_array([encoder_identity]),
        dtype=_text_array(["float32"]),
    )


def _load_npz(
    path: Path,
    *,
    expected_ids: list[str],
    expected_hashes: list[str],
    encoder_identity: str,
) -> np.ndarray:
    with np.load(path, allow_pickle=False) as archive:
        ids = [str(value) for value in archive["record_ids"].tolist()]
        hashes = [str(value) for value in archive["representation_sha256"].tolist()]
        identity = str(np.asarray(archive["encoder_identity"]).reshape(-1)[0])
        matrix = np.asarray(archive["embeddings"], dtype=np.float32).copy()
    if ids != expected_ids or hashes != expected_hashes or identity != encoder_identity:
        raise ValueError("embedding cache identity mismatch")
    if matrix.shape != (len(expected_ids), 768) or not np.isfinite(matrix).all():
        raise ValueError("embedding cache matrix mismatch")
    return matrix


def build_or_load_embedding_cache(
    bundle: dict[str, Any],
    model: Any,
    dev_vectors: dict[str, np.ndarray],
) -> dict[str, Any]:
    EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)
    encoder_identity = (
        "sentence-transformers/all-mpnet-base-v2@"
        "e8c3b32edf5434bc2275fc9bab85f82640a19130"
    )
    ordered_records = sorted(bundle["records"], key=lambda row: row["record_id"])
    candidate_positions = {
        example_id: position
        for position, example_id in enumerate(bundle["frozen"]["example_ids"])
    }
    new_records = [row for row in ordered_records if row["record_id"] not in candidate_positions]
    if len(new_records) != 256:
        raise ValueError("expected exactly 256 newly encoded Eedi representations")
    new_path = EMBEDDING_DIR / "rq1b_eedi_train_embeddings_v1.npz"
    new_ids = [row["record_id"] for row in new_records]
    new_hashes = [row["representation_sha256"] for row in new_records]
    cache_reused = new_path.is_file()
    if cache_reused:
        new_matrix = _load_npz(
            new_path,
            expected_ids=new_ids,
            expected_hashes=new_hashes,
            encoder_identity=encoder_identity,
        )
    else:
        new_matrix = np.asarray(
            model.encode(
                [row["representation"] for row in new_records],
                batch_size=32,
                device="cpu",
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )
        if new_matrix.shape != (256, 768) or not np.isfinite(new_matrix).all():
            raise ValueError("new TRAIN embedding result mismatch")
        _write_npz(
            new_path,
            record_ids=new_ids,
            embeddings=new_matrix,
            representation_hashes=new_hashes,
            encoder_identity=encoder_identity,
        )

    new_by_id = {record_id: new_matrix[index] for index, record_id in enumerate(new_ids)}
    train_matrix_rows: list[np.ndarray] = []
    for row in ordered_records:
        record_id = row["record_id"]
        if record_id in candidate_positions:
            vector = bundle["frozen"]["embeddings"][candidate_positions[record_id]]
        else:
            vector = new_by_id[record_id]
        train_matrix_rows.append(np.asarray(vector, dtype=np.float32))
    train_matrix = np.stack(train_matrix_rows).astype(np.float32, copy=False)
    train_path = EMBEDDING_DIR / "rq1b_train_embeddings_v1.npz"
    _write_npz(
        train_path,
        record_ids=[row["record_id"] for row in ordered_records],
        embeddings=train_matrix,
        representation_hashes=[row["representation_sha256"] for row in ordered_records],
        encoder_identity=encoder_identity,
    )

    dev_ids: list[str] = []
    dev_hashes: list[str] = []
    dev_matrix_rows: list[np.ndarray] = []
    for row in bundle["dev_records"]:
        record_id = row["record_id"]
        plain = str(row["query"]).strip()
        page = f"[PAGE={row['current_page']}] {plain}"
        vectors = np.asarray(dev_vectors[record_id], dtype=np.float32)
        if vectors.shape != (2, 768):
            raise ValueError("DEV vector cache input shape mismatch")
        for variant, text, vector in zip(("PLAIN", "PAGE"), (plain, page), vectors, strict=True):
            dev_ids.append(f"{record_id}::{variant}")
            dev_hashes.append(hashlib.sha256(text.encode("utf-8")).hexdigest())
            dev_matrix_rows.append(vector)
    dev_matrix = np.stack(dev_matrix_rows).astype(np.float32, copy=False)
    dev_path = EMBEDDING_DIR / "rq1b_dev_query_embeddings_v1.npz"
    _write_npz(
        dev_path,
        record_ids=dev_ids,
        embeddings=dev_matrix,
        representation_hashes=dev_hashes,
        encoder_identity=encoder_identity,
    )

    embedding_by_id = {
        row["record_id"]: train_matrix[index]
        for index, row in enumerate(ordered_records)
    }
    manifest = {
        "schema_version": "rq1b-embedding-manifest-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "encoder_identity": encoder_identity,
        "encoder_device": "cpu",
        "encoder_frozen": True,
        "pooling_policy": "FROZEN_SENTENCE_TRANSFORMER_MPNET_POOLING",
        "normalisation_policy": "FROZEN_MODEL_MODULE_PIPELINE",
        "dtype": "float32",
        "embedding_dimension": 768,
        "approved_candidate_embedding": {
            "relative_path": "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz",
            "record_count": 62,
            "shape": [62, 768],
            "artifact_sha256": bundle["frozen"]["embedding_artifact_sha256"],
            "matrix_sha256": bundle["frozen"]["embedding_matrix_sha256"],
        },
        "governed_train_embedding": {
            "record_count": 318,
            "reused_approved_count": 62,
            "new_eedi_encoded_count": 256,
            "shape": list(train_matrix.shape),
            "matrix_sha256": matrix_sha256(train_matrix),
            "local_cache_relative_path": str(train_path.relative_to(ROOT)),
            "local_cache_sha256": sha256_file(train_path),
        },
        "new_eedi_embedding": {
            "record_count": 256,
            "shape": list(new_matrix.shape),
            "matrix_sha256": matrix_sha256(new_matrix),
            "local_cache_relative_path": str(new_path.relative_to(ROOT)),
            "local_cache_sha256": sha256_file(new_path),
            "cache_reused": cache_reused,
        },
        "dev_embedding": {
            "logical_record_count": 84,
            "effective_variant_count": 168,
            "shape": list(dev_matrix.shape),
            "matrix_sha256": matrix_sha256(dev_matrix),
            "local_cache_relative_path": str(dev_path.relative_to(ROOT)),
            "local_cache_sha256": sha256_file(dev_path),
            "encoded_once_by_runtime_fidelity_preflight": True,
        },
        "cache_shared_across_run_count": 20,
        "cache_contains_text": False,
        "cache_tracked": False,
        "final_gold_accessed": False,
    }
    return {
        "manifest": manifest,
        "embedding_by_id": embedding_by_id,
        "dev_vectors": dev_vectors,
    }
