"""Runtime-faithful example scoring, family collapse, and max aggregation."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import torch

from feature_builder import torch_pair_features


ScoreFunction = Callable[[np.ndarray, np.ndarray], np.ndarray]


def clipped_cosine_batch(query_matrix: np.ndarray, candidate_matrix: np.ndarray) -> np.ndarray:
    queries = np.asarray(query_matrix, dtype=np.float64)
    candidates = np.asarray(candidate_matrix, dtype=np.float64)
    if queries.shape != candidates.shape or queries.ndim != 2:
        raise ValueError("cosine inputs must be equal-shape matrices")
    query_norms = np.linalg.norm(queries, axis=1)
    candidate_norms = np.linalg.norm(candidates, axis=1)
    denominators = query_norms * candidate_norms
    scores = np.zeros(len(queries), dtype=np.float64)
    valid = denominators > 0.0
    if np.any(valid):
        scores[valid] = np.sum(queries[valid] * candidates[valid], axis=1) / denominators[valid]
    return np.clip(scores, 0.0, 1.0)


def learned_score_function(model: torch.nn.Module) -> ScoreFunction:
    def score(query_matrix: np.ndarray, candidate_matrix: np.ndarray) -> np.ndarray:
        queries = torch.from_numpy(np.asarray(query_matrix, dtype=np.float32))
        candidates = torch.from_numpy(np.asarray(candidate_matrix, dtype=np.float32))
        features = torch_pair_features(queries, candidates)
        model.eval()
        with torch.no_grad():
            probabilities = torch.sigmoid(model(features))
        return probabilities.detach().cpu().numpy().astype(np.float64, copy=False)

    return score


def rank_dev_record(
    dev_record: dict[str, Any],
    query_vectors: np.ndarray,
    index_records: list[dict[str, Any]],
    index_embeddings: np.ndarray,
    score_function: ScoreFunction,
) -> dict[str, Any]:
    if query_vectors.ndim != 2 or query_vectors.shape[0] != 2:
        raise ValueError("DEV records must have plain and page-prefixed query vectors")
    current_page = dev_record["current_page"]
    eligible_positions: list[int] = []
    selected_query_vectors: list[np.ndarray] = []
    excluded_current_page = 0
    for position, record in enumerate(index_records):
        if record["final_context_requirement"] == "current_page":
            if record["page_context"] != current_page:
                excluded_current_page += 1
                continue
            selected_query_vectors.append(query_vectors[1])
        else:
            selected_query_vectors.append(query_vectors[0])
        eligible_positions.append(position)
    candidate_vectors = np.asarray(index_embeddings[eligible_positions], dtype=np.float32)
    query_matrix = np.asarray(selected_query_vectors, dtype=np.float32)
    scores = np.asarray(score_function(query_matrix, candidate_vectors), dtype=np.float64)
    if scores.shape != (len(eligible_positions),) or not np.isfinite(scores).all():
        raise ValueError("scorer returned invalid example scores")
    if np.any(scores < 0.0) or np.any(scores > 1.0):
        raise ValueError("example scores must be bounded in [0,1]")
    hits = []
    for position, score in zip(eligible_positions, scores.tolist()):
        record = index_records[position]
        hits.append(
            {
                "example_id": record["example_id"],
                "semantic_label": record["final_semantic_label"],
                "source_scope": record["final_source_scope"],
                "paraphrase_family_id": record["final_paraphrase_family_id"],
                "context_requirement": record["final_context_requirement"],
                "page_context": record["page_context"],
                "score": float(score),
            }
        )
    hits.sort(key=lambda row: (-row["score"], row["semantic_label"], row["example_id"]))
    for rank, hit in enumerate(hits, start=1):
        hit["rank"] = rank
    family_best: dict[tuple[str, str], dict[str, Any]] = {}
    for hit in hits:
        family_best.setdefault((hit["semantic_label"], hit["paraphrase_family_id"]), hit)
    family_hits = sorted(
        family_best.values(),
        key=lambda row: (-row["score"], row["semantic_label"], row["example_id"]),
    )
    by_label: dict[str, list[dict[str, Any]]] = {}
    for hit in family_hits:
        by_label.setdefault(hit["semantic_label"], []).append(hit)
    candidates = []
    for label, label_hits in by_label.items():
        ordered = sorted(label_hits, key=lambda row: (-row["score"], row["example_id"]))
        contributor = ordered[0]
        candidates.append(
            {
                "label": label,
                "score": contributor["score"],
                "example_ids": [contributor["example_id"]],
                "suggested_source_scope": contributor["source_scope"],
            }
        )
    candidates.sort(key=lambda row: (-row["score"], row["label"]))
    if not candidates:
        raise ValueError("no eligible intent candidates")
    top1 = candidates[0]
    top2 = candidates[1] if len(candidates) > 1 else None
    margin = top1["score"] - top2["score"] if top2 else None
    oos_score = next(
        (candidate["score"] for candidate in candidates if candidate["label"] == "out_of_scope"),
        0.0,
    )
    gold_label = dev_record["intent_label"]
    gold_rank = next(
        (rank for rank, candidate in enumerate(candidates, start=1) if candidate["label"] == gold_label),
        None,
    )
    return {
        "record_id": dev_record["record_id"],
        "gold_label": gold_label,
        "current_page": current_page,
        "eligible_example_count": len(hits),
        "eligible_label_count": len(candidates),
        "excluded_current_page_records": excluded_current_page,
        "example_hits": hits,
        "intent_ranking": candidates,
        "top1_label": top1["label"],
        "top1_score": top1["score"],
        "top2_label": top2["label"] if top2 else None,
        "top2_score": top2["score"] if top2 else None,
        "margin": margin,
        "out_of_scope_score": float(oos_score),
        "gold_rank": gold_rank,
        "top1_correct": top1["label"] == gold_label,
    }


def evaluate_records(
    dev_records: list[dict[str, Any]],
    query_vector_by_id: dict[str, np.ndarray],
    index_records: list[dict[str, Any]],
    index_embeddings: np.ndarray,
    score_function: ScoreFunction,
) -> list[dict[str, Any]]:
    return [
        rank_dev_record(
            record,
            query_vector_by_id[record["record_id"]],
            index_records,
            index_embeddings,
            score_function,
        )
        for record in dev_records
    ]


def compact_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    return {
        key: prediction[key]
        for key in [
            "record_id",
            "gold_label",
            "current_page",
            "eligible_example_count",
            "eligible_label_count",
            "top1_label",
            "top1_score",
            "top2_label",
            "top2_score",
            "margin",
            "out_of_scope_score",
            "gold_rank",
            "top1_correct",
            "intent_ranking",
        ]
    }

