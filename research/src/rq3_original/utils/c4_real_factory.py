"""Dependency factory for the feature-flagged C4 REAL research service.

Construction performs local identity checks only. It does not launch
Streamlit, call P3, retrieve course evidence, read learner Memory, generate a
response, or call a Judge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.c4_memory.c4_memory_retriever import (
    FrozenLocalMPNetBackend,
    SemanticBackend,
    discover_local_mpnet_path,
)
from utils.c4_rag.corpus import CANONICAL_CFULL_ROOT, verify_canonical_sources
from utils.c4_real_adapters import (
    C4DeterministicOutputGuard,
    C4PersistentLearnerMemoryAdapter,
    C4RealEvidenceCompilerV1,
    C4RealEvidenceSynthesisAdapter,
    C4RecommendationPlannerAdapter,
    C4SelectedR0CourseRAGAdapter,
    FrozenClarificationGateAdapter,
    PrecomputedP3RouteCache,
)
from utils.c4_real_contracts import C4RealDependencies
from utils.c4_real_service import C4RealService
from utils.c4_real_trace import InMemoryTraceSink


def build_c4_real_dependencies(
    *,
    route_provider: PrecomputedP3RouteCache,
    course_asset_root: str | Path,
    memory_database_path: str | Path,
    generator: Any,
    evaluation_mode: bool,
    trace_sink: Any | None = None,
    semantic_memory_backend: SemanticBackend | None = None,
    output_guard: Any | None = None,
    memory_clock: Any | None = None,
) -> C4RealDependencies:
    """Bind every real C4 dependency under the frozen I0 identities.

    Evaluation route providers must already contain precomputed routes and
    fail on misses. Interactive providers may have a separately authorised
    live delegate. The course asset root must be the recovered, byte-verified
    corpus root selected by Track R.
    """

    resolved_course_root = Path(course_asset_root).expanduser().resolve()
    if resolved_course_root != CANONICAL_CFULL_ROOT.resolve():
        raise ValueError("C4 REAL accepts only the frozen recovered Course-RAG corpus root")
    verify_canonical_sources()
    if route_provider.evaluation_mode != bool(evaluation_mode):
        raise ValueError("Route-provider and dependency-factory execution modes differ")

    backend = semantic_memory_backend
    if backend is None:
        model_path = discover_local_mpnet_path(resolved_course_root)
        if model_path is None:
            raise FileNotFoundError("Frozen local MPNet Memory backend is unavailable")
        backend = FrozenLocalMPNetBackend(model_path, verify_hashes=True)

    return C4RealDependencies(
        clarification_gate=FrozenClarificationGateAdapter(),
        p3_router=route_provider,
        evidence_synthesiser=C4RealEvidenceSynthesisAdapter(dashboard_data=None),
        course_rag=C4SelectedR0CourseRAGAdapter(),
        learner_memory=C4PersistentLearnerMemoryAdapter(
            memory_database_path,
            evaluation_mode=bool(evaluation_mode),
            semantic_backend=backend,
            clock=memory_clock,
        ),
        evidence_compiler=C4RealEvidenceCompilerV1(),
        planner=C4RecommendationPlannerAdapter(),
        generator=generator,
        output_guard=output_guard or C4DeterministicOutputGuard(),
        trace_sink=trace_sink or InMemoryTraceSink(),
    )


def build_c4_real_service(**kwargs: Any) -> C4RealService:
    return C4RealService(build_c4_real_dependencies(**kwargs))


__all__ = ["build_c4_real_dependencies", "build_c4_real_service"]
