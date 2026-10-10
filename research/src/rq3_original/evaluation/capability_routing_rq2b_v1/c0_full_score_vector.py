"""Frozen C0 identity and full-score-vector adapter for RQ2-B.

This research-only module delegates all semantic scoring to the existing
production runtime.  It does not copy candidate text, cosine logic, page
eligibility rules, thresholds, or aggregation code.  The fixed output axis is
the frozen RQ1 16-intent universe; an intent with no page-eligible example is
represented by ``score=0.0`` and ``eligible=false`` and is never inserted into
the eligible ranking used by P1 policies.

Natural-language inputs are accepted only by the scoring call and are never
returned.  Detailed per-case outputs therefore remain suitable for an ignored
local ledger, while :func:`aggregate_c0_runtime_results` returns a query-free
summary suitable for a tracked runtime preflight.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import math
import os
from pathlib import Path
import socket
from typing import Any, Iterator, Mapping, Sequence
from unittest.mock import patch

import numpy as np

from evaluation.learned_intent_ranking.lr3.data_loader import (
    load_frozen_candidate_artifacts,
)
from utils.intent_example_index import CANONICAL_PAGES
from utils.production_intent_router import (
    load_production_semantic_router,
    route_production_intent,
)

from . import ROOT, RQ1_FINAL_ROUTER, RQ2BError, safe_distribution


C0_APPROVED_INDEX_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
)
C0_EMBEDDINGS_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz"
)
C0_MODEL_RELATIVE = Path(
    "semantic_runtime/models/all-mpnet-base-v2/"
    "e8c3b32edf5434bc2275fc9bab85f82640a19130"
)
C0_CONFIG_RELATIVE = Path("semantic_runtime/config/semantic_routing_config.json")

C0_APPROVED_INDEX_SHA256 = (
    "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
)
C0_EMBEDDINGS_SHA256 = (
    "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
)
C0_MODEL_REPO_ID = "sentence-transformers/all-mpnet-base-v2"
C0_MODEL_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
C0_AGGREGATION = "max"
C0_RECORD_COUNT = 62
C0_LABEL_COUNT = 16
C0_EMBEDDING_DIMENSION = 768
C0_FULL_EXAMPLE_TOP_K = 62
C0_FULL_CANDIDATE_LIMIT = 16
C0_PARITY_TOLERANCE = 1e-12

# This is the RQ1-C0 frozen label axis, in its canonical lexicographic order.
# It is an identity assertion, not a newly selected candidate membership.
C0_LABEL_AXIS = (
    "access_or_capability_question",
    "course_content_question",
    "cross_page_relationship",
    "dashboard_interpretation",
    "discrepancy_or_correction",
    "emotional_or_justification",
    "hybrid_course_and_planning",
    "improvement_recommendation",
    "metric_clarification",
    "out_of_scope",
    "planning_or_strategy",
    "quantitative_metric_query",
    "reflection_structure_question",
    "social_interaction",
    "technical_data_question",
    "unsupported_task",
)

OFFLINE_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OPENAI_API_KEY": "",
    "CUDA_VISIBLE_DEVICES": "",
}


class C0IdentityError(RQ2BError):
    """Frozen C0 runtime or artifact identity does not match the contract."""


class C0ParityError(RQ2BError):
    """Full-vector C0 output diverges from the production semantic runtime."""


@dataclass(frozen=True)
class C0RoutingInput:
    """The complete and deliberately narrow feature surface for C0 scoring."""

    review_case_id: str
    query: str
    current_page: str

    def __post_init__(self) -> None:
        if not str(self.review_case_id).strip():
            raise ValueError("review_case_id must be a non-empty opaque identity")
        if not str(self.query).strip():
            raise ValueError("query must be non-empty")
        _canonical_page(self.current_page)


class _PredictionSpy:
    """Count production-wrapper calls without changing the wrapped runtime."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.call_count = 0
        self.last_prediction: Any | None = None

    def predict(self, *args: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_prediction = self.runtime.predict(*args, **kwargs)
        return self.last_prediction


def _blocked_network(*_args: Any, **_kwargs: Any) -> Any:
    raise C0IdentityError("BLOCKED_RQ2_B_C0_IDENTITY: network access attempted")


@contextmanager
def c0_offline_environment() -> Iterator[None]:
    """Force local-only CPU execution and fail closed on socket access."""

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, OFFLINE_ENVIRONMENT, clear=False))
        stack.enter_context(patch("socket.create_connection", _blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect", _blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect_ex", _blocked_network))
        yield


def _canonical_page(value: str) -> str:
    lookup = {str(page).casefold(): str(page) for page in CANONICAL_PAGES}
    page = lookup.get(str(value or "").strip().casefold())
    if page is None:
        raise ValueError("current_page is outside the frozen C0 page universe")
    return page


def _root_is_exact(root: Path) -> bool:
    return Path(root).resolve() == ROOT.resolve()


def verify_frozen_c0_identity(root: Path = ROOT) -> dict[str, Any]:
    """Validate the frozen C0 assets and return only safe identity metadata."""

    if not _root_is_exact(root):
        raise C0IdentityError("BLOCKED_RQ2_B_C0_IDENTITY: alternate root rejected")
    frozen = load_frozen_candidate_artifacts()
    config = dict(frozen["config"])
    model = dict(config.get("model") or {})
    approved = dict((config.get("artifacts") or {}).get("approved_index") or {})
    embeddings = dict((config.get("artifacts") or {}).get("embedding_npz") or {})
    metadata = dict(frozen["embedding_metadata"])

    checks = {
        "router_identity": RQ1_FINAL_ROUTER == "C0_COSINE",
        "approved_index_relative": approved.get("path")
        == C0_APPROVED_INDEX_RELATIVE.as_posix(),
        "approved_index_sha256": frozen.get("approved_index_sha256")
        == C0_APPROVED_INDEX_SHA256,
        "embedding_relative": embeddings.get("path")
        == C0_EMBEDDINGS_RELATIVE.as_posix(),
        "embedding_sha256": frozen.get("embedding_artifact_sha256")
        == C0_EMBEDDINGS_SHA256,
        "record_count": len(frozen.get("index_records") or ()) == C0_RECORD_COUNT,
        "unique_example_ids": len(set(frozen.get("example_ids") or ()))
        == C0_RECORD_COUNT,
        "label_axis": tuple(frozen.get("production_labels") or ()) == C0_LABEL_AXIS,
        "label_count": len(frozen.get("production_labels") or ()) == C0_LABEL_COUNT,
        "embedding_shape": tuple(np.asarray(frozen.get("embeddings")).shape)
        == (C0_RECORD_COUNT, C0_EMBEDDING_DIMENSION),
        "embedding_dtype": np.asarray(frozen.get("embeddings")).dtype == np.float32,
        "embedding_dimension": int(frozen.get("embedding_dimension", 0))
        == C0_EMBEDDING_DIMENSION,
        "embedding_bound_to_index": metadata.get("approved_index_sha256")
        == C0_APPROVED_INDEX_SHA256,
        "model_repo": model.get("repo_id") == C0_MODEL_REPO_ID
        and metadata.get("repo_id") == C0_MODEL_REPO_ID,
        "model_revision": model.get("revision") == C0_MODEL_REVISION
        and metadata.get("model_revision") == C0_MODEL_REVISION,
        "model_relative": model.get("local_path") == C0_MODEL_RELATIVE.as_posix(),
        "model_directory": (ROOT / C0_MODEL_RELATIVE).is_dir(),
        "local_files_only": model.get("local_files_only") is True,
        "cpu_only": model.get("device") == "cpu",
        "network_downloads_disabled": config.get("allow_network_downloads") is False,
        "aggregation_max": config.get("aggregation") == C0_AGGREGATION,
        "aggregate_all_examples": config.get("aggregate_all_examples") is True,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    if failures:
        raise C0IdentityError(
            "BLOCKED_RQ2_B_C0_IDENTITY: " + ",".join(failures)
        )

    label_counts: dict[str, int] = {label: 0 for label in C0_LABEL_AXIS}
    for row in frozen["index_records"]:
        label_counts[str(row["final_semantic_label"])] += 1
    return {
        "schema_version": "rq2b-c0-identity-v1",
        "status": "PASS",
        "router_identity": RQ1_FINAL_ROUTER,
        "approved_index_relative_path": C0_APPROVED_INDEX_RELATIVE.as_posix(),
        "approved_index_sha256": C0_APPROVED_INDEX_SHA256,
        "approved_index_record_count": C0_RECORD_COUNT,
        "approved_index_unique_example_id_count": C0_RECORD_COUNT,
        "candidate_label_count": C0_LABEL_COUNT,
        "candidate_label_axis": list(C0_LABEL_AXIS),
        "candidate_count_by_label": dict(sorted(label_counts.items())),
        "embedding_relative_path": C0_EMBEDDINGS_RELATIVE.as_posix(),
        "embedding_artifact_sha256": C0_EMBEDDINGS_SHA256,
        "embedding_shape": [C0_RECORD_COUNT, C0_EMBEDDING_DIMENSION],
        "embedding_dtype": "float32",
        "embedding_matrix_sha256": str(frozen["embedding_matrix_sha256"]),
        "model_repo_id": C0_MODEL_REPO_ID,
        "model_revision": C0_MODEL_REVISION,
        "model_relative_path": C0_MODEL_RELATIVE.as_posix(),
        "model_version": str(metadata["model_version"]),
        "device": "cpu",
        "local_files_only": True,
        "network_downloads_allowed": False,
        "aggregation": C0_AGGREGATION,
        "aggregate_all_examples": True,
        "candidate_membership_changed": False,
        "threshold_changed": False,
    }


def _expected_eligible_labels(runtime: Any, current_page: str) -> frozenset[str]:
    frozen_index = getattr(runtime, "frozen_index", None)
    if frozen_index is None or len(getattr(frozen_index, "records", ())) != C0_RECORD_COUNT:
        raise C0IdentityError("BLOCKED_RQ2_B_C0_IDENTITY: runtime index unavailable")
    page = _canonical_page(current_page)
    return frozenset(
        str(record.final_semantic_label)
        for record in frozen_index.records
        if record.final_context_requirement != "current_page"
        or record.page_context == page
    )


def _require_available(prediction: Any, role: str) -> None:
    result = getattr(prediction, "result", None)
    if result is None or result.status != "available" or not result.candidates:
        reason = str(getattr(prediction, "reason", "") or "unavailable")
        raise C0ParityError(
            f"BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: {role}:{reason}"
        )


def _score_close(left: Any, right: Any) -> bool:
    return math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=C0_PARITY_TOLERANCE
    )


def _score_c0_input(
    routing_input: C0RoutingInput,
    *,
    runtime: Any,
    protected_guard_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """Score one narrow routing input; caller is responsible for offline guard."""

    page = _canonical_page(routing_input.current_page)
    full_prediction = runtime.predict(
        routing_input.query,
        current_page=page,
        top_k=C0_FULL_EXAMPLE_TOP_K,
        candidate_limit=C0_FULL_CANDIDATE_LIMIT,
        aggregate_all_examples=True,
    )
    _require_available(full_prediction, "full")
    default_prediction = runtime.predict(
        routing_input.query,
        current_page=page,
        aggregate_all_examples=True,
    )
    _require_available(default_prediction, "default")

    full_result = full_prediction.result
    default_result = default_prediction.result
    raw_top1_parity = bool(
        full_result.winning_label == default_result.winning_label
        and _score_close(full_result.winning_score, default_result.winning_score)
    )
    if not raw_top1_parity:
        raise C0ParityError(
            "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: full/default Top-1 mismatch"
        )

    candidates = tuple(full_result.candidates)
    candidate_by_label = {str(candidate.label): candidate for candidate in candidates}
    if len(candidate_by_label) != len(candidates):
        raise C0ParityError(
            "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: duplicate intent candidate"
        )
    expected_eligible = _expected_eligible_labels(runtime, page)
    if frozenset(candidate_by_label) != expected_eligible:
        raise C0ParityError(
            "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: page eligibility mismatch"
        )
    if not expected_eligible <= frozenset(C0_LABEL_AXIS):
        raise C0IdentityError(
            "BLOCKED_RQ2_B_C0_IDENTITY: runtime emitted unknown intent"
        )

    axes = []
    for label in C0_LABEL_AXIS:
        candidate = candidate_by_label.get(label)
        axes.append(
            {
                "intent_id": label,
                "eligible": candidate is not None,
                "score": float(candidate.score) if candidate is not None else 0.0,
            }
        )
    eligible_ranking = [
        {
            "rank": rank,
            "intent_id": str(candidate.label),
            "score": float(candidate.score),
        }
        for rank, candidate in enumerate(candidates, start=1)
    ]

    spy = _PredictionSpy(runtime)
    decision = route_production_intent(
        routing_input.query,
        current_page=page,
        mode="semantic_enhanced",
        protected_guard_reasons=tuple(protected_guard_reasons),
        semantic_runtime=spy,
    )
    if spy.call_count not in (0, 1):
        raise C0ParityError(
            "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: production semantic call count"
        )
    production_semantic_ran = spy.call_count == 1
    if production_semantic_ran:
        _require_available(spy.last_prediction, "production")
        production_candidate_parity = bool(
            decision.semantic_candidate == full_result.winning_label
            and spy.last_prediction.result.winning_label == full_result.winning_label
            and _score_close(
                spy.last_prediction.result.winning_score,
                full_result.winning_score,
            )
        )
        if not production_candidate_parity:
            raise C0ParityError(
                "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: production semantic candidate mismatch"
            )
    else:
        production_candidate_parity = bool(
            decision.semantic_status == "not_run" and decision.semantic_candidate is None
        )
        if not production_candidate_parity:
            raise C0ParityError(
                "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: skipped semantic state mismatch"
            )

    return {
        "schema_version": "rq2b-c0-full-score-vector-v1",
        "review_case_id": routing_input.review_case_id,
        "router_identity": RQ1_FINAL_ROUTER,
        "current_page": page,
        "intent_axis_count": len(axes),
        "intent_axes": axes,
        "eligible_intent_count": len(eligible_ranking),
        "eligible_ranking": eligible_ranking,
        "page_ineligible_intents": [
            axis["intent_id"] for axis in axes if not axis["eligible"]
        ],
        "top1_intent": str(full_result.winning_label),
        "top1_score": float(full_result.winning_score),
        "top2_intent": str(full_result.second_label),
        "top2_score": float(full_result.second_score),
        "top1_margin": float(full_result.margin),
        "out_of_scope_score": float(full_result.out_of_scope_score),
        "raw_full_default_top1_parity": raw_top1_parity,
        "production_semantic_runtime_called": production_semantic_ran,
        "production_semantic_runtime_call_count": spy.call_count,
        "production_semantic_candidate_parity": production_candidate_parity,
        "production_selected_intent": str(decision.selected_intent),
        "production_routing_source": str(decision.routing_source),
        "production_semantic_status": str(decision.semantic_status),
        "production_semantic_accepted": bool(decision.semantic_accepted),
        "full_runtime_predict_call_count": 1,
        "default_runtime_predict_call_count": 1,
        "aggregate_all_examples": True,
        "aggregation": C0_AGGREGATION,
        "query_returned": False,
        "history_read": False,
        "gold_feature_used": False,
        "network_access": False,
        "provider_calls": 0,
        "model_training": False,
    }


def score_c0_full_vector(
    query: str,
    current_page: str,
    *,
    review_case_id: str,
    runtime: Any | None = None,
    protected_guard_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """Return one local-only, query-free C0 vector and parity trace."""

    routing_input = C0RoutingInput(
        review_case_id=review_case_id,
        query=query,
        current_page=current_page,
    )
    with c0_offline_environment():
        selected_runtime = runtime or load_production_semantic_router()
        return _score_c0_input(
            routing_input,
            runtime=selected_runtime,
            protected_guard_reasons=protected_guard_reasons,
        )


def aggregate_c0_runtime_results(
    rows: Sequence[Mapping[str, Any]],
    *,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a tracked-safe aggregate from ignored per-case C0 vectors."""

    values = [dict(row) for row in rows]
    for row in values:
        if row.get("intent_axis_count") != C0_LABEL_COUNT:
            raise C0ParityError(
                "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: vector axis count"
            )
        if row.get("raw_full_default_top1_parity") is not True:
            raise C0ParityError(
                "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: raw Top-1 aggregate"
            )
        if row.get("production_semantic_candidate_parity") is not True:
            raise C0ParityError(
                "BLOCKED_RQ2_B_C0_SCORE_VECTOR_PARITY: production parity aggregate"
            )
        if any(key in row for key in ("query", "history", "conversation_history")):
            raise C0ParityError(
                "BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE: governed text in C0 result"
            )

    missing_counts: dict[str, int] = {label: 0 for label in C0_LABEL_AXIS}
    for row in values:
        for label in row.get("page_ineligible_intents") or ():
            if label not in missing_counts:
                raise C0IdentityError(
                    "BLOCKED_RQ2_B_C0_IDENTITY: unknown ineligible intent"
                )
            missing_counts[str(label)] += 1
    eligible_counts = [int(row["eligible_intent_count"]) for row in values]
    semantic_runs = sum(bool(row["production_semantic_runtime_called"]) for row in values)
    report = {
        "schema_version": "rq2b-c0-runtime-preflight-v1",
        "stage": "RQ2-B",
        "status": "PASS",
        "router_identity": RQ1_FINAL_ROUTER,
        "record_count": len(values),
        "fixed_intent_axis_count": C0_LABEL_COUNT,
        "all_vectors_have_fixed_axis": True,
        "eligible_intent_count_distribution": safe_distribution(
            str(value) for value in eligible_counts
        ),
        "minimum_eligible_intent_count": min(eligible_counts) if eligible_counts else None,
        "maximum_eligible_intent_count": max(eligible_counts) if eligible_counts else None,
        "page_ineligible_intent_count": {
            label: count for label, count in sorted(missing_counts.items()) if count
        },
        "raw_full_default_top1_parity_count": sum(
            row["raw_full_default_top1_parity"] is True for row in values
        ),
        "production_semantic_candidate_parity_count": sum(
            row["production_semantic_candidate_parity"] is True for row in values
        ),
        "production_semantic_runtime_run_count": semantic_runs,
        "production_semantic_guard_skip_count": len(values) - semantic_runs,
        "production_selected_intent_distribution": safe_distribution(
            str(row["production_selected_intent"]) for row in values
        ),
        "production_routing_source_distribution": safe_distribution(
            str(row["production_routing_source"]) for row in values
        ),
        "full_runtime_predict_call_count": len(values),
        "default_runtime_predict_call_count": len(values),
        "production_runtime_predict_call_count": sum(
            int(row["production_semantic_runtime_call_count"]) for row in values
        ),
        "aggregation": C0_AGGREGATION,
        "aggregate_all_examples": True,
        "query_or_history_present": False,
        "gold_feature_used": False,
        "candidate_membership_changed": False,
        "threshold_changed": False,
        "model_training": False,
        "provider_calls": 0,
        "network_access": False,
    }
    if identity is not None:
        report["identity"] = dict(identity)
    return report


def run_c0_runtime_preflight(
    inputs: Sequence[C0RoutingInput],
    *,
    root: Path = ROOT,
    runtime: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run deterministic C0 parity and return ``(safe_report, local_rows)``."""

    identity = verify_frozen_c0_identity(root)
    with c0_offline_environment():
        selected_runtime = runtime or load_production_semantic_router()
        rows = [
            _score_c0_input(value, runtime=selected_runtime)
            for value in inputs
        ]
    return aggregate_c0_runtime_results(rows, identity=identity), rows


__all__ = [
    "C0_AGGREGATION",
    "C0_APPROVED_INDEX_SHA256",
    "C0_EMBEDDINGS_SHA256",
    "C0_LABEL_AXIS",
    "C0IdentityError",
    "C0ParityError",
    "C0RoutingInput",
    "aggregate_c0_runtime_results",
    "c0_offline_environment",
    "run_c0_runtime_preflight",
    "score_c0_full_vector",
    "verify_frozen_c0_identity",
]
