"""Strict preflight against the actual frozen SemanticIntentRouter runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from evaluate_ranker import clipped_cosine_batch, rank_dev_record


@dataclass
class RecordingBackend:
    backend: Any
    last_texts: tuple[str, ...] = ()
    last_matrix: np.ndarray | None = None

    @property
    def model_version(self) -> str:
        return str(self.backend.model_version)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.asarray(self.backend.encode(texts), dtype=np.float32)
        self.last_texts = tuple(str(text) for text in texts)
        self.last_matrix = matrix.copy()
        return matrix


def run_runtime_fidelity_preflight(
    dev_records: list[dict[str, Any]],
    frozen: dict[str, Any],
    tolerance: float = 1e-12,
) -> tuple[dict[str, Any], dict[str, np.ndarray], list[dict[str, Any]], Any]:
    from utils.production_intent_router import (
        clear_production_semantic_router_cache,
        load_production_semantic_router,
    )

    clear_production_semantic_router_cache()
    router = load_production_semantic_router()
    original_backend = router.embedding_backend
    model = original_backend._load_model()
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    recorder = RecordingBackend(original_backend)
    router.embedding_backend = recorder
    query_vectors: dict[str, np.ndarray] = {}
    independent_predictions = []
    parity_rows = []
    max_example_diff = 0.0
    max_intent_diff = 0.0
    failures = []
    for dev in dev_records:
        oracle = router.predict(
            dev["query"],
            current_page=dev["current_page"],
            top_k=62,
            candidate_limit=16,
            aggregate_all_examples=True,
        )
        if oracle.result.status != "available" or recorder.last_matrix is None:
            raise RuntimeError(f"runtime unavailable for {dev['record_id']}: {oracle.reason}")
        expected_representations = (
            dev["query"].strip(),
            f"[PAGE={dev['current_page']}] {dev['query'].strip()}",
        )
        if recorder.last_texts != expected_representations:
            raise ValueError(f"runtime representation mismatch: {dev['record_id']}")
        vectors = recorder.last_matrix.copy()
        query_vectors[dev["record_id"]] = vectors
        independent = rank_dev_record(
            dev,
            vectors,
            frozen["index_records"],
            frozen["embeddings"],
            clipped_cosine_batch,
        )
        independent_predictions.append(independent)
        oracle_hits = list(oracle.example_hits)
        oracle_candidates = list(oracle.result.candidates)
        hit_ids_match = [hit.example_id for hit in oracle_hits] == [hit["example_id"] for hit in independent["example_hits"]]
        hit_ranks_match = [hit.rank for hit in oracle_hits] == [hit["rank"] for hit in independent["example_hits"]]
        candidate_labels_match = [item.label for item in oracle_candidates] == [item["label"] for item in independent["intent_ranking"]]
        contributor_ids_match = [list(item.example_ids) for item in oracle_candidates] == [item["example_ids"] for item in independent["intent_ranking"]]
        example_diffs = [
            abs(float(left.score) - float(right["score"]))
            for left, right in zip(oracle_hits, independent["example_hits"])
        ]
        intent_diffs = [
            abs(float(left.score) - float(right["score"]))
            for left, right in zip(oracle_candidates, independent["intent_ranking"])
        ]
        record_example_diff = max(example_diffs, default=0.0)
        record_intent_diff = max(intent_diffs, default=0.0)
        max_example_diff = max(max_example_diff, record_example_diff)
        max_intent_diff = max(max_intent_diff, record_intent_diff)
        scalar_match = all(
            [
                oracle.result.winning_label == independent["top1_label"],
                oracle.result.second_label == independent["top2_label"],
                abs(float(oracle.result.winning_score) - independent["top1_score"]) <= tolerance,
                abs(float(oracle.result.second_score) - independent["top2_score"]) <= tolerance,
                abs(float(oracle.result.margin) - independent["margin"]) <= tolerance,
                abs(float(oracle.result.out_of_scope_score) - independent["out_of_scope_score"]) <= tolerance,
                oracle.excluded_current_page_records == independent["excluded_current_page_records"],
                tuple(oracle.query_representations) == expected_representations,
                oracle.aggregation_method == "max",
                oracle.aggregate_all_examples is True,
                oracle.index_sha256 == frozen["approved_index_sha256"],
            ]
        )
        passed = all(
            [
                hit_ids_match,
                hit_ranks_match,
                candidate_labels_match,
                contributor_ids_match,
                record_example_diff <= tolerance,
                record_intent_diff <= tolerance,
                scalar_match,
            ]
        )
        if not passed:
            failures.append(dev["record_id"])
        parity_rows.append(
            {
                "record_id": dev["record_id"],
                "current_page": dev["current_page"],
                "eligible_example_count": len(oracle_hits),
                "eligible_label_count": len(oracle_candidates),
                "excluded_current_page_records": oracle.excluded_current_page_records,
                "eligible_example_ids_exact": hit_ids_match,
                "example_ranks_exact": hit_ranks_match,
                "intent_ordering_exact": candidate_labels_match,
                "contributor_example_ids_exact": contributor_ids_match,
                "max_example_score_abs_diff": record_example_diff,
                "max_intent_score_abs_diff": record_intent_diff,
                "top1_top2_margin_oos_exact_within_tolerance": scalar_match,
                "pass": passed,
            }
        )
    if failures:
        raise RuntimeError(f"runtime-fidelity parity failed for: {failures}")
    mpnet_parameters = list(model.parameters())
    report = {
        "schema_version": "lr3-runtime-fidelity-report-v1",
        "status": "PASS",
        "gate": "LEARNED_MODEL_EVALUATION_ALLOWED",
        "record_count": len(dev_records),
        "tolerance": {"relative": 0.0, "absolute": tolerance},
        "exact_eligible_example_id_matches": sum(row["eligible_example_ids_exact"] for row in parity_rows),
        "exact_intent_ordering_matches": sum(row["intent_ordering_exact"] for row in parity_rows),
        "top1_label_matches": sum(row["top1_top2_margin_oos_exact_within_tolerance"] for row in parity_rows),
        "max_example_score_abs_diff": max_example_diff,
        "max_intent_score_abs_diff": max_intent_diff,
        "failure_count": 0,
        "aggregation": "max",
        "aggregate_all_examples": True,
        "candidate_limit_for_preflight": 16,
        "example_top_k_for_preflight": 62,
        "model_version": recorder.model_version,
        "mpnet_parameter_count": sum(parameter.numel() for parameter in mpnet_parameters),
        "mpnet_trainable_parameter_count_in_lr3": sum(parameter.numel() for parameter in mpnet_parameters if parameter.requires_grad),
        "records": parity_rows,
    }
    return report, query_vectors, independent_predictions, model

