"""Feature-gated C0/C1 DI using the actual C4 compiler and payload builder.

No transport can be enabled through this factory. No Memory/RAG/P3 backend is
constructed. Frozen reviewed-pack factories and historical replay stay intact.
"""
from dataclasses import dataclass
from typing import Sequence, Mapping

from utils.c4_real_contracts import (
    C4Mode, C4RealRequest, C4RealDependencies, EvidenceItem, EvidenceSynthesisResult,
)
from utils.c4_real_service import C4RealService
from utils.c4_real_streamlit import visible_history
from . import VERSION, DOMAINS, PAGES
from .aggregate import aggregate
from .scope import Scope, ScopeError, Snapshot, canonical, digest, instant
from .select import select_domains, SELECTION_VERSION


@dataclass(frozen=True)
class ScopedC4Request(C4RealRequest):
    dashboard_scope: Scope | None = None
    trusted_now: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.dashboard_scope is None or self.student_id != self.dashboard_scope.learner_id:
            raise ScopeError("Request learner and trusted scope differ")
        if self.mode not in {C4Mode.C0_ORIGINAL, C4Mode.C1_EVIDENCE} or self.current_page not in PAGES:
            raise ScopeError("Scoped V1 supports only five-view C0/C1 preparation")
        canonical(self.primary_input.to_payload())


def build_scoped_request(*, snapshot: Snapshot, scope: Scope, query: str, page: str,
                         mode=C4Mode.C1_EVIDENCE, messages: Sequence[Mapping] = (),
                         now=None, request_id="SCOPED_REQUEST", session_id="SCOPED_SESSION"):
    snapshot.validate_query(scope, query, now)
    bundle = aggregate(snapshot, scope)
    return ScopedC4Request(
        request_id=request_id, scenario_id="SCOPED_INTERACTIVE", mode=mode,
        current_query=query, current_page=page, dashboard_context=bundle.visible(page),
        visible_conversation_history=visible_history(messages), student_id=scope.learner_id,
        session_id=session_id, state_reset_id=scope.snapshot, dashboard_scope=scope,
        trusted_now=now.isoformat() if now is not None else None)


class ScopedEvidenceAdapter:
    identity = VERSION

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.actual_synthesiser_calls = 0

    def synthesise(self, *, request, primary_input):
        scope = request.dashboard_scope
        self.snapshot.validate_query(scope, primary_input.current_query,
                                     instant(request.trusted_now) if request.trusted_now else None)
        bundle = aggregate(self.snapshot, scope)
        pages, selection = select_domains(primary_input.current_query, primary_input.current_page)
        visible = DOMAINS if request.current_page == "Overview" else (request.current_page,)
        added = tuple(p for p in pages if p not in visible)
        self.actual_synthesiser_calls += 1
        items = () if not added else (EvidenceItem(
            evidence_id="scoped-added:" + digest([scope.internal(), added, bundle.context(added)]),
            evidence_type="SCOPED_NONCURRENT_ACTIVITY_V1", content=bundle.context(added),
            evidence_strength="SCOPED_RAW_AGGREGATION",
            provenance={"adapter": VERSION, "selection_version": SELECTION_VERSION,
                        "selection": selection, "scope": scope.internal(),
                        "fact_trace": [f.trace() for f in bundle.facts if f.domain in added]}),)
        return EvidenceSynthesisResult(items=items, status="SCOPED_RAW_PREPARED")


class DisabledDependency:
    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            raise RuntimeError("Optional backends and execution are disabled in scoped C0/C1")
        return forbidden


def build_scoped_evidence_service(*, enabled: bool, snapshot: Snapshot, token_budget=12000):
    """Explicit versioned raw factory; request-local aggregation, no shared raw cache."""
    if enabled is not True:
        raise ScopeError("ENABLE_C4_SCOPED_EVIDENCE_V1 must be explicitly enabled")
    from utils.c4_real_adapters import (
        C4RealEvidenceCompilerV1, C4ProviderCompatibleGenerator, FrozenClarificationGateAdapter,
    )

    class PreservingCompiler(C4RealEvidenceCompilerV1):
        identity = "SCOPED_BASELINE_PRESERVING_COMPILER_V1"

        def compile(self, **kwargs):
            request = kwargs["request"]
            if not isinstance(request, ScopedC4Request):
                raise ScopeError("Scoped request contract required")
            snapshot.validate(request.dashboard_scope)
            snapshot.validate_query(request.dashboard_scope, request.current_query,
                                    instant(request.trusted_now) if request.trusted_now else None)
            visible = aggregate(snapshot, request.dashboard_scope).visible(request.current_page)
            if canonical(request.dashboard_context) != canonical(visible):
                raise ScopeError("Current-page facts do not match the trusted chart scope")
            if request.mode == C4Mode.C1_EVIDENCE:
                current = EvidenceItem(
                    evidence_id="scoped-visible:" + digest(visible),
                    evidence_type="LEGACY_RAW_PAGE_CONTEXT", content=visible,
                    evidence_strength="SCOPED_VISIBLE_FACTS")
                extra = kwargs.get("dashboard_evidence") or EvidenceSynthesisResult()
                kwargs["dashboard_evidence"] = EvidenceSynthesisResult(
                    items=(current, *extra.items), limitations=extra.limitations, status=extra.status)
            compiled = super().compile(**kwargs)
            # The legacy compiler may silently omit entire items. New mode fails
            # explicitly rather than silently dropping baseline or added facts.
            if any(s.startswith("TOKEN_BUDGET_EXCLUDED") for s in compiled.limitations):
                raise ScopeError("Visible and selected facts exceed the common evidence budget")
            return compiled

    class PreparationOnlyService(C4RealService):
        def execute(self, request):
            raise RuntimeError("Scoped Evidence V1 is preparation-only; transport is disabled")

        def prepare_generation_request(self, request, *, payload_builder=None):
            if not isinstance(request, ScopedC4Request):
                raise ScopeError("Scoped request contract required")
            snapshot.validate(request.dashboard_scope)
            snapshot.validate_query(request.dashboard_scope, request.current_query,
                                    instant(request.trusted_now) if request.trusted_now else None)
            return super().prepare_generation_request(request, payload_builder=payload_builder)

    forbidden = DisabledDependency()
    return PreparationOnlyService(C4RealDependencies(
        clarification_gate=FrozenClarificationGateAdapter(), p3_router=forbidden,
        evidence_synthesiser=ScopedEvidenceAdapter(snapshot), course_rag=forbidden,
        learner_memory=forbidden, evidence_compiler=PreservingCompiler(token_budget=token_budget),
        planner=forbidden, generator=C4ProviderCompatibleGenerator(execution_authorised=False),
        output_guard=forbidden))


def fact_to_request_trace(snapshot, request, prepared):
    """Internal trace only; redact scope learner/course and source spans for real data export."""
    bundle = aggregate(snapshot, request.dashboard_scope)
    selected, reason = select_domains(request.current_query, request.current_page)
    visible = DOMAINS if request.current_page == "Overview" else (request.current_page,)
    added = tuple(d for d in selected if d not in visible) if request.mode == C4Mode.C1_EVIDENCE else ()
    import json
    final = json.loads(prepared.provider_generation_payload["messages"][1]["content"])
    traced = []
    for fact in bundle.facts:
        if fact.domain not in (*visible, *added):
            continue
        destinations = [(i, record["content"]["activity"][fact.domain][fact.metric])
                        for i, record in enumerate(final["evidence"]["evidence"])
                        if fact.metric in record["content"].get("activity", {}).get(fact.domain, {})]
        if len(destinations) != 1 or destinations[0][1] != fact.public():
            raise ScopeError("Atomic fact did not survive exactly once in the final request")
        index = destinations[0][0]
        raw = snapshot.tables.get(fact.table)
        source_hash = digest([dict(r) for r in raw]) if raw is not None else None
        traced.append({**fact.trace(), "source_table_content_sha256": source_hash,
                       "destination": "current_page_context" if fact.domain in visible else "dashboard_activity",
                       "final_json_pointer_inside_user_message": f"/evidence/evidence/{index}/content/activity/{fact.domain}/{fact.metric}",
                       "final_value_verified": True})
    current_items = [(i, r["content"]) for i, r in enumerate(final["evidence"]["evidence"])
                     if r["source"] == "current_page_context"]
    if len(current_items) != 1 or canonical(current_items[0][1]) != canonical(request.dashboard_context):
        raise ScopeError("Visible current-page rows/calculations did not survive the final request")
    return {"version": VERSION, "selection_version": SELECTION_VERSION, "selection": reason,
            "source_origin": snapshot.origin, "visible_domains": visible, "added_domains": added,
            "added_factual_intervention": any(f.value is not None for f in bundle.facts if f.domain in added),
            "overview_derivation": "References four domain facts exactly once; no cross-system activity sum.",
            "facts": traced,
            "visible_baseline_trace": {"all_values_preserved": True,
                "final_json_pointer_inside_user_message": f"/evidence/evidence/{current_items[0][0]}/content",
                "public_context_sha256": digest(request.dashboard_context),
                "scoped_source_row_spans": {t: [i for i, _ in s.rows] for t, s in bundle.slices.items()}},
            "prepared_input": prepared.provider_generation_payload,
            "hashes": prepared.deterministic_hashes, "generation_sent": prepared.generation_sent}
