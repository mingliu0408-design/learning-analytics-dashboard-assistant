"""Real, local-only component adapters for RQ3-REAL-C4 integration I0.

This module binds the frozen deterministic Clarification Gate, reviewed
Dashboard evidence packs, selected lexical Course RAG, persistent learner
Memory, the evidence compiler, the unchanged recommendation planner, a future
provider-compatible Generator boundary, and a non-rewriting output guard.

Importing or constructing these adapters makes no provider, response-
generation, Judge, network, or Streamlit call.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Callable, Iterator, Mapping, MutableMapping, Sequence
import unicodedata

from evaluation.capability_routing_rq2_v2_stage4.track_g_b0_b1.clarification_gate import (
    ClarificationGate as FrozenClarificationImplementation,
)
from utils.c4_memory.c4_memory_provider import C4LearnerMemoryProvider
from utils.c4_memory.c4_memory_retriever import SemanticBackend
from utils.c4_memory.c4_memory_store import C4MemoryStore
from utils.c4_memory.c4_memory_writer import StructuredMemoryCandidate
from utils.c4_rag.models import EvidenceStrength, ResultStatus, SUBSTANTIVE_STRENGTHS
from utils.c4_rag.provider import C4CourseRAGProvider
from utils.c4_rag.retrievers import R0_ID
from utils.c4_real_contracts import (
    CLARIFICATION_GATE_ID,
    P3_ROUTER_METHOD_ID,
    C4Mode,
    C4RealRequest,
    ClarificationDecision,
    CompiledEvidence,
    CourseRAGResult,
    CourseSource,
    EvidenceItem,
    EvidenceSynthesisResult,
    ExecutionContext,
    GenerationResult,
    GuardedOutput,
    MemoryItem,
    MemoryReadResult,
    MemoryScope,
    MemoryWriteProposal,
    ModuleActivation,
    P3CapabilityRoute,
    PlannerResult,
    PrimarySemanticInput,
)
from utils.recommendation_planner import build_recommendation_plan

if TYPE_CHECKING:
    from utils.evidence_synthesiser import DashboardData


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLARIFICATION_ROOT = (
    PROJECT_ROOT
    / "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1"
)
CLARIFICATION_CANDIDATES = CLARIFICATION_ROOT / "clarification_candidate_configs_v1.json"
CLARIFICATION_FREEZE = CLARIFICATION_ROOT / "clarification_gate_frozen_v1.json"
GENERATION_PROMPT_PATH = (
    PROJECT_ROOT
    / "evaluation/rq3_real_c4/i0_integration/c4_real_generation_prompt_frozen_v1.txt"
)
GENERATION_SCHEMA_PATH = (
    PROJECT_ROOT
    / "evaluation/rq3_real_c4/i0_integration/c4_real_generation_schema_v1.json"
)
GENERATION_SCHEMA_V2_PROVIDER_PATH = (
    PROJECT_ROOT
    / "evaluation/rq3_real_c4/i1_route_integration/"
    "c4_real_generation_schema_v2_provider_compatible.json"
)

EXPECTED_R0_CORPUS_SHA256 = (
    "daaba43aebeda730db2bd7aef4583729610242a1af44060615c3f4c235e67ede"
)
GENERATOR_MODEL = "gpt-4o-mini-2024-07-18"
GENERATOR_ENDPOINT = "OpenAI Chat Completions"
GENERATOR_MAX_OUTPUT_TOKENS = 512

PRIMARY_SEMANTIC_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSON used for every I0 content identity."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def semantic_input_sha256(primary_input: PrimarySemanticInput | Mapping[str, Any]) -> str:
    payload = (
        primary_input.to_payload()
        if isinstance(primary_input, PrimarySemanticInput)
        else dict(primary_input)
    )
    if tuple(payload) != PRIMARY_SEMANTIC_FIELDS and set(payload) != set(PRIMARY_SEMANTIC_FIELDS):
        raise ValueError("P3 semantic input must contain exactly the frozen four fields")
    return canonical_sha256({key: payload[key] for key in PRIMARY_SEMANTIC_FIELDS})


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FrozenClarificationGateAdapter:
    """Contract adapter around the exact frozen CG1 implementation/config."""

    identity = CLARIFICATION_GATE_ID

    def __init__(
        self,
        *,
        candidate_path: Path = CLARIFICATION_CANDIDATES,
        freeze_path: Path = CLARIFICATION_FREEZE,
    ) -> None:
        candidates = json.loads(candidate_path.read_text(encoding="utf-8"))
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if freeze.get("gate_id") != self.identity:
            raise ValueError("Frozen Clarification Gate identity mismatch")
        if freeze.get("candidate_file_sha256") != sha256_file(candidate_path):
            raise ValueError("Frozen Clarification candidate hash mismatch")
        self._implementation = FrozenClarificationImplementation(candidates)
        self._config_id = str(freeze["selected_config_id"])

    def evaluate(self, primary_input: PrimarySemanticInput) -> ClarificationDecision:
        prediction = self._implementation.predict(
            primary_input.to_payload(), self._config_id
        )
        return ClarificationDecision(
            needs_clarification=prediction.dialogue_action == "CLARIFY",
            reason_code=prediction.matched_clause,
            gate_id=self.identity,
            limitations=(
                "Frozen deterministic CG1; no provider call.",
                f"selected_config={self._config_id}",
            ),
        )


class PrecomputedP3RouteCache:
    """Scenario-level route provider keyed only by canonical semantic input.

    In evaluation mode, missing routes fail closed. In interactive mode, a
    separately injected live router may supply one decision for a cache miss;
    that decision is retained for later ablation/service use of the same input.
    """

    identity = "C4_PRECOMPUTED_P3_ROUTE_CACHE_V1"

    def __init__(
        self,
        routes: Mapping[str, P3CapabilityRoute | Mapping[str, Any]] | None = None,
        *,
        evaluation_mode: bool,
        live_router: Any | None = None,
    ) -> None:
        self.evaluation_mode = bool(evaluation_mode)
        self.live_router = live_router
        self._routes: dict[str, P3CapabilityRoute] = {}
        self.request_count = 0
        self.cache_hit_count = 0
        self.live_decision_count = 0
        for key, value in (routes or {}).items():
            if not re.fullmatch(r"[0-9a-f]{64}", str(key)):
                raise ValueError("Precomputed P3 route key is not a SHA-256 identity")
            self._routes[str(key)] = self._coerce_route(value)

    @staticmethod
    def _coerce_route(value: P3CapabilityRoute | Mapping[str, Any]) -> P3CapabilityRoute:
        if isinstance(value, P3CapabilityRoute):
            route = value
        else:
            allowed = {
                "rag_required",
                "memory_required",
                "planning_required",
                "method_id",
                "decision_id",
                "provider_identity",
                "limitations",
            }
            unexpected = set(value) - allowed
            if unexpected:
                raise ValueError(f"Unexpected precomputed route fields: {sorted(unexpected)}")
            route = P3CapabilityRoute(
                rag_required=value["rag_required"],
                memory_required=value["memory_required"],
                planning_required=value["planning_required"],
                method_id=str(value.get("method_id") or P3_ROUTER_METHOD_ID),
                decision_id=str(value.get("decision_id") or ""),
                provider_identity=str(value.get("provider_identity") or ""),
                limitations=tuple(value.get("limitations") or ()),
            )
        if route.method_id != P3_ROUTER_METHOD_ID:
            raise ValueError("Precomputed route does not use the frozen final Router")
        return route

    def route(self, primary_input: PrimarySemanticInput) -> P3CapabilityRoute:
        self.request_count += 1
        key = semantic_input_sha256(primary_input)
        if key in self._routes:
            self.cache_hit_count += 1
            return self._routes[key]
        if self.evaluation_mode:
            raise KeyError(f"FROZEN_EVALUATION_ROUTE_MISSING:{key}")
        if self.live_router is None:
            raise RuntimeError("LIVE_P3_EXECUTION_NOT_BOUND_OR_AUTHORISED")
        route = self._coerce_route(self.live_router.route(primary_input))
        self._routes[key] = route
        self.live_decision_count += 1
        return route

    def snapshot(self) -> Mapping[str, P3CapabilityRoute]:
        return dict(self._routes)


class C4RealEvidenceSynthesisAdapter:
    """Use real raw inputs when supplied, else consume reviewed frozen packs.

    An empty reviewed pack is represented as a typed empty result. It is not
    replaced with fabricated DataFrames or unrelated evidence.
    """

    identity = "C4_REAL_EVIDENCE_SYNTHESIS_ADAPTER_V1"

    def __init__(self, *, dashboard_data: "DashboardData | None" = None) -> None:
        self.dashboard_data = dashboard_data
        self._cache: dict[str, EvidenceSynthesisResult] = {}
        self.actual_synthesiser_calls = 0
        self.frozen_pack_reads = 0

    def synthesise(
        self, *, request: C4RealRequest, primary_input: PrimarySemanticInput
    ) -> EvidenceSynthesisResult:
        key = semantic_input_sha256(primary_input)
        if key in self._cache:
            return self._cache[key]

        if self.dashboard_data is not None:
            # Pandas is an optional legacy-dashboard dependency. Keep it out
            # of the import-level C4/Streamlit binding path and load it only
            # when actual raw DashboardData was explicitly supplied.
            from utils.evidence_synthesiser import synthesise_evidence

            content = synthesise_evidence(
                query=primary_input.current_query,
                primary_page=primary_input.current_page,
                student_id=request.student_id,
                data=self.dashboard_data,
            )
            self.actual_synthesiser_calls += 1
            result = EvidenceSynthesisResult(
                items=(
                    EvidenceItem(
                        evidence_id="dashboard-real:" + canonical_sha256(content),
                        evidence_type="REAL_SELECTIVE_DASHBOARD_EVIDENCE",
                        content=content,
                        evidence_strength="RAW_INPUT_SYNTHESISED",
                        provenance={
                            "adapter": self.identity,
                            "source": "utils/evidence_synthesiser.py::synthesise_evidence",
                        },
                    ),
                ),
                limitations=tuple(content.get("uncertainty") and [str(content["uncertainty"])] or []),
                status="ACTUAL_SYNTHESISER_EXECUTED",
            )
        else:
            frozen = primary_input.dashboard_context
            if not isinstance(frozen, Mapping):
                raise ValueError(
                    "Dashboard evidence is neither a raw-data binding nor a frozen structured pack"
                )
            self.frozen_pack_reads += 1
            if frozen:
                result = EvidenceSynthesisResult(
                    items=(
                        EvidenceItem(
                            evidence_id="dashboard-frozen:" + canonical_sha256(frozen),
                            evidence_type="FROZEN_OUTPUT_LEVEL_EVIDENCE_PACK",
                            content=dict(frozen),
                            evidence_strength="FROZEN_STRUCTURED_OUTPUT",
                            provenance={
                                "adapter": self.identity,
                                "source": "C4_REAL_PRIMARY_UNIFIED_DATASET_V1 reviewed Dashboard pack",
                                "semantic_input_sha256": key,
                            },
                        ),
                    ),
                    limitations=(
                        "Reviewed output-level Dashboard evidence; raw DataFrames were not available in I0.",
                    ),
                    status="FROZEN_OUTPUT_LEVEL_PACK",
                )
            else:
                result = EvidenceSynthesisResult(
                    items=(),
                    limitations=(
                        "Reviewed typed-empty Dashboard evidence pack; no raw DataFrames were fabricated.",
                    ),
                    status="FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK",
                )
        self._cache[key] = result
        return result


class C4SelectedR0CourseRAGAdapter:
    """P3-authorised integration over the selected R0 lexical ranking.

    C4RealService calls this adapter only after validating the route and
    applying the mode permission. The provider property checks the selected
    implementation and authorised course-corpus identity before retrieval.
    Direct callers must satisfy the same upstream preconditions.
    """

    identity = "C4_REAL_COURSE_RAG_ADAPTER_R0_SINGLE_GATE_V1::C4_RAG_R0_LEXICAL"

    def __init__(self, provider: C4CourseRAGProvider | None = None) -> None:
        self._provider = provider
        self._cache: dict[str, CourseRAGResult] = {}
        self.retrieval_call_count = 0

    @property
    def provider(self) -> C4CourseRAGProvider:
        if self._provider is None:
            self._provider = C4CourseRAGProvider(implementation_id=R0_ID)
        if self._provider.implementation_id != R0_ID:
            raise ValueError("Only C4_RAG_R0_LEXICAL may be selected in C4 REAL")
        retriever = getattr(self._provider, "_retriever", None)
        observed = str(getattr(retriever, "corpus_hash", ""))
        if observed != EXPECTED_R0_CORPUS_SHA256:
            raise ValueError("Selected R0 corpus identity mismatch")
        return self._provider

    @staticmethod
    def _canonical_query(value: str) -> str:
        return unicodedata.normalize("NFC", str(value))

    def _cache_key(self, request: C4RealRequest) -> str:
        provider = self.provider
        retriever = getattr(provider, "_retriever")
        return canonical_sha256(
            {
                "canonical_query": self._canonical_query(request.current_query),
                "current_page": request.current_page,
                "visible_conversation_history": [
                    dict(item) for item in request.visible_conversation_history
                ],
                "selected_rag_implementation": R0_ID,
                "corpus_sha256": retriever.corpus_hash,
            }
        )

    @staticmethod
    def _bounded_content(chunk: Any) -> Mapping[str, Any]:
        common = {
            "document_title": chunk.document_title,
            "week": chunk.week,
            "section": chunk.section,
            "page": chunk.page,
        }
        if chunk.evidence_strength in SUBSTANTIVE_STRENGTHS:
            return {**common, "text": chunk.text}
        if chunk.evidence_strength == EvidenceStrength.LINK_ONLY:
            links = re.findall(r"https?://[^\s)\]}>,]+", str(chunk.text))[:3]
            return {**common, "links": links, "boundary": "LINK_ONLY"}
        return {**common, "boundary": "TITLE_AND_METADATA_ONLY"}

    def retrieve(
        self,
        *,
        request: C4RealRequest,
        evidence: EvidenceSynthesisResult | None,
    ) -> CourseRAGResult:
        del evidence  # Dashboard evidence is never a Course-RAG substitute.
        key = self._cache_key(request)
        if key in self._cache:
            return self._cache[key]
        envelope = self.provider.retrieve(
            request.current_query,
            request.current_page,
            request.visible_conversation_history,
            top_k=5,
            upstream_authorised=True,
        )
        self.retrieval_call_count += 1
        if envelope.implementation_id != R0_ID:
            raise ValueError("Runtime Course-RAG implementation is not selected R0")
        sources: list[CourseSource] = []
        for chunk in envelope.selected_chunks:
            if chunk.evidence_strength == EvidenceStrength.WEAK_MATCH:
                continue
            sources.append(
                CourseSource(
                    source_id=chunk.chunk_id,
                    source_type=chunk.source_type,
                    content=self._bounded_content(chunk),
                    document_title=chunk.document_title,
                    week=chunk.week,
                    section=chunk.section,
                    evidence_strength=chunk.evidence_strength.value,
                    provenance={
                        "document_id": chunk.document_id,
                        "source_path": chunk.source_path,
                        "source_sha256": chunk.source_sha256,
                        "implementation_id": R0_ID,
                    },
                )
            )
        status = envelope.result_status.value
        if status == ResultStatus.NO_RESULT.value:
            sources = []
        result = CourseRAGResult(
            sources=tuple(sources),
            limitations=tuple(envelope.limitations),
            result_status=status,
        )
        self._cache[key] = result
        return result


@dataclass(frozen=True)
class _MemoryBinding:
    database_path: Path
    store_student_id: str
    namespace_sha256: str


class C4PersistentLearnerMemoryAdapter:
    """Track-S adapter over C4_LEARNER_MEMORY_V1 with scoped SQLite stores."""

    identity = "C4_REAL_PERSISTENT_MEMORY_ADAPTER_V1::C4_LEARNER_MEMORY_V1"

    def __init__(
        self,
        memory_database_path: str | Path,
        *,
        evaluation_mode: bool,
        semantic_backend: SemanticBackend | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        supplied = Path(memory_database_path).expanduser().resolve()
        self.evaluation_mode = bool(evaluation_mode)
        if self.evaluation_mode:
            self._database_root = (
                supplied
                if supplied.suffix == ""
                else supplied.parent / (supplied.stem + "_evaluation_namespaces")
            )
            self._interactive_database = None
            self._database_root.mkdir(parents=True, exist_ok=True)
        else:
            self._database_root = supplied.parent
            self._interactive_database = (
                supplied if supplied.suffix else supplied / "c4_real_interactive.sqlite3"
            )
        self.semantic_backend = semantic_backend
        self.clock = clock
        self._known_bindings: MutableMapping[str, set[_MemoryBinding]] = {}
        self.store_open_count = 0
        self.store_close_count = 0

    @staticmethod
    def _scope_payload(scope: MemoryScope) -> dict[str, str]:
        payload = {
            "execution_context": scope.execution_context.value,
            "student_id": scope.student_id,
            "session_id": scope.session_id,
            "scenario_id": scope.scenario_id,
            "condition_id": scope.condition_id,
            "state_reset_id": scope.state_reset_id,
        }
        if any(not str(value).strip() for value in payload.values()):
            raise ValueError("Complete MemoryScope fields are required")
        return payload

    def _binding(self, scope: MemoryScope) -> _MemoryBinding:
        payload = self._scope_payload(scope)
        if self.evaluation_mode:
            if scope.execution_context != ExecutionContext.EVALUATION:
                raise ValueError("Evaluation Memory adapter rejected an interactive scope")
            namespace_hash = canonical_sha256(payload)
            binding = _MemoryBinding(
                database_path=self._database_root / f"c4_eval_{namespace_hash}.sqlite3",
                store_student_id="eval-" + namespace_hash,
                namespace_sha256=namespace_hash,
            )
        else:
            if scope.execution_context != ExecutionContext.INTERACTIVE:
                raise ValueError("Interactive Memory adapter rejected an evaluation scope")
            # Mode/condition is deliberately absent from durable learner
            # identity. The complete MemoryScope remains validated and traced.
            learner_hash = canonical_sha256(
                {
                    "execution_context": "interactive",
                    "student_id": scope.student_id,
                    "architecture": "C4_LEARNER_MEMORY_V1",
                }
            )
            assert self._interactive_database is not None
            binding = _MemoryBinding(
                database_path=self._interactive_database,
                store_student_id="learner-" + learner_hash,
                namespace_sha256=learner_hash,
            )
        self._known_bindings.setdefault(scope.student_id, set()).add(binding)
        return binding

    @contextmanager
    def _open_provider(
        self, binding: _MemoryBinding
    ) -> Iterator[C4LearnerMemoryProvider]:
        store = C4MemoryStore(binding.database_path, clock=self.clock)
        self.store_open_count += 1
        try:
            yield C4LearnerMemoryProvider(
                store,
                semantic_backend=self.semantic_backend,
                clock=self.clock,
            )
        finally:
            store.close()
            self.store_close_count += 1

    @staticmethod
    def _memory_item(value: Mapping[str, Any]) -> MemoryItem:
        version = dict(value.get("timestamp_version") or {})
        provenance = dict(value.get("provenance") or {})
        return MemoryItem(
            memory_id=str(value["memory_id"]),
            item_type=str(value["memory_type"]),
            value=value["content"],
            provenance="C4_LEARNER_MEMORY_V1",
            version=int(version["version"]) if version.get("version") is not None else None,
            timestamp_version=version,
            provenance_details=provenance,
        )

    def is_enabled(self, scope: MemoryScope) -> bool:
        binding = self._binding(scope)
        with self._open_provider(binding) as provider:
            return provider.store.is_memory_enabled(binding.store_student_id)

    def read(self, *, scope: MemoryScope, request: C4RealRequest) -> MemoryReadResult:
        binding = self._binding(scope)
        with self._open_provider(binding) as provider:
            envelope = provider.retrieve(
                binding.store_student_id,
                request.current_query,
                request.visible_conversation_history,
                top_k=5,
            )
        items = tuple(
            self._memory_item(value)
            for value in envelope.get("selected_memory_items", [])
        )
        return MemoryReadResult(
            items=items,
            limitations=tuple(envelope.get("limitations") or ()),
            status=str(envelope.get("status") or "NO_MATCH"),
        )

    def propose_write(
        self,
        *,
        scope: MemoryScope,
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        guarded_output: GuardedOutput,
        planner_result: PlannerResult | None,
    ) -> MemoryWriteProposal | None:
        del scope, request, compiled_evidence, guarded_output, planner_result
        # Interactive writes are human-confirmed/manual; generated or planned
        # assistant content is never auto-committed as a learner fact.
        return None

    def reset(self, scope: MemoryScope) -> None:
        binding = self._binding(scope)
        with self._open_provider(binding) as provider:
            provider.clear_experimental_learner_state(binding.store_student_id)

    def view(self, scope: MemoryScope) -> Sequence[MemoryItem]:
        binding = self._binding(scope)
        with self._open_provider(binding) as provider:
            values = provider.list_active_memories(binding.store_student_id)
        return tuple(
            MemoryItem(
                memory_id=str(value["memory_id"]),
                item_type=str(value["memory_type"]),
                value=value["content"],
                provenance="C4_LEARNER_MEMORY_V1",
                version=int(value["version"]),
                timestamp_version={
                    key: value.get(key)
                    for key in (
                        "created_at",
                        "valid_from",
                        "valid_to",
                        "last_confirmed_at",
                        "version",
                    )
                },
                provenance_details={"content_sha256": value.get("content_sha256")},
            )
            for value in values
        )

    def correct(self, scope: MemoryScope, memory_id: str, value: Any) -> None:
        corrected = str(value).strip()
        if not corrected:
            raise ValueError("Corrected Memory value must be non-empty")
        binding = self._binding(scope)
        with self._open_provider(binding) as provider:
            result = provider.correct_memory(
                student_id=binding.store_student_id,
                target_memory_id=memory_id,
                corrected_content=corrected,
                source_session_id=scope.session_id,
                source_turn_id="human-correction-" + canonical_sha256(corrected)[:16],
                user_turn=corrected,
                evidence_span=corrected,
            )
        if not result.accepted:
            raise ValueError(f"Memory correction rejected: {result.reason_code}")

    def delete(self, scope: MemoryScope, memory_id: str) -> None:
        binding = self._binding(scope)
        instruction = f"Delete memory {memory_id}"
        with self._open_provider(binding) as provider:
            result = provider.delete_memory(
                student_id=binding.store_student_id,
                target_memory_id=memory_id,
                source_session_id=scope.session_id,
                source_turn_id="human-delete-" + canonical_sha256(instruction)[:16],
                user_turn=instruction,
                evidence_span=instruction,
            )
        if not result.accepted:
            raise ValueError(f"Memory deletion rejected: {result.reason_code}")

    def set_enabled(self, scope: MemoryScope, enabled: bool) -> None:
        binding = self._binding(scope)
        with self._open_provider(binding) as provider:
            if enabled:
                provider.enable_memory_for_learner(binding.store_student_id)
            else:
                provider.disable_memory_for_learner(binding.store_student_id)

    def clear_research_memory(self, student_id: str) -> None:
        bindings = set(self._known_bindings.get(student_id, set()))
        if not self.evaluation_mode and self._interactive_database is not None:
            learner_hash = canonical_sha256(
                {
                    "execution_context": "interactive",
                    "student_id": student_id,
                    "architecture": "C4_LEARNER_MEMORY_V1",
                }
            )
            bindings.add(
                _MemoryBinding(
                    self._interactive_database,
                    "learner-" + learner_hash,
                    learner_hash,
                )
            )
        for binding in bindings:
            with self._open_provider(binding) as provider:
                provider.clear_experimental_learner_state(binding.store_student_id)

    def precondition(
        self, scope: MemoryScope, record: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Apply one frozen setup manifest, close, and prove reopen persistence."""

        binding = self._binding(scope)
        aliases: dict[str, str] = {}
        results: list[dict[str, Any]] = []
        with self._open_provider(binding) as provider:
            for write in record.get("writes", []):
                candidate_payload = dict(write["candidate"])
                target_alias = candidate_payload.get("target_alias")
                candidate_payload.pop("target_alias", None)
                if target_alias:
                    candidate_payload["target_memory_id"] = aliases[str(target_alias)]
                result = provider.writer.apply_candidate(
                    student_id=binding.store_student_id,
                    source_session_id=str(write["source_session_id"]),
                    source_turn_id=str(write["source_turn_id"]),
                    source_text=str(write["source_text"]),
                    candidate=StructuredMemoryCandidate.from_mapping(candidate_payload),
                    source_role=str(write["source_role"]),
                    claim_basis=str(write["claim_basis"]),
                    event_at=str(write["event_at"]),
                )
                if result.accepted and result.memory_id:
                    aliases[str(write["alias"])] = result.memory_id
                results.append(
                    {
                        "alias": write["alias"],
                        "accepted": result.accepted,
                        "applied_operation": result.applied_operation,
                        "reason_code": result.reason_code,
                        "memory_id": result.memory_id,
                    }
                )
            integrity_before_close = provider.store.integrity_check()
        # A fresh connection is required for the persistence proof.
        with self._open_provider(binding) as reopened:
            active = reopened.list_active_memories(binding.store_student_id)
            integrity_after_reopen = reopened.store.integrity_check()
        return {
            "namespace_sha256": binding.namespace_sha256,
            "write_results": results,
            "active_memory_ids_after_reopen": [value["memory_id"] for value in active],
            "integrity_before_close": integrity_before_close,
            "integrity_after_reopen": integrity_after_reopen,
            "store_reopened": True,
            "raw_database_path_exposed": False,
        }


_TOKEN = re.compile(r"[A-Za-z0-9]+|[^\W\s]", re.UNICODE)
_INTERNAL_KEYS = {
    "lexical_score",
    "dense_score",
    "fusion_rank",
    "relevance_components",
    "semantic_backend",
    "embedding",
    "embeddings",
    "database_path",
}


def _safe_evidence_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_evidence_value(nested)
            for key, nested in value.items()
            if str(key).casefold() not in _INTERNAL_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe_evidence_value(item) for item in value]
    return value


_PROVIDER_PROHIBITED_KEYS = frozenset(
    {
        "path",
        "file_path",
        "file",
        "filename",
        "files",
        "source_file",
        "source_files",
        "source_notes",
        "source_path",
        "source_sha256",
        "sha256",
        "evidence_id",
        "chunk_id",
        "document_id",
        "memory_id",
        "database_path",
        "source_session_id",
        "source_turn_id",
        "student_id",
        "scenario_id",
        "mode",
        "mode_id",
        "condition",
        "condition_id",
        "condition_name",
        "route",
        "route_id",
        "method_id",
        "decision_id",
        "lexical_score",
        "dense_score",
        "semantic_score",
        "fusion_score",
        "embedding",
        "embeddings",
        "cache_key",
        "internal_cache_key",
        "gold",
        "gold_label",
        "expected_label",
        "expected_labels",
        "expected_capabilities",
        "reference_answer",
        "historical_judge_score",
        "compiled_evidence_sha256",
    }
)
_PROVIDER_INTERNAL_VALUE = re.compile(
    r"(?:/Users/|/private/|/var/folders/|file://|"
    r"(?:^|\s)(?:evaluation|utils|input|course_materials_v2|System Data)/|"
    r"\.sqlite(?:3)?\b)",
    re.IGNORECASE,
)
_SHA256_VALUE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_OMIT_PROVIDER_VALUE = object()


def _provider_safe_nested(value: Any) -> Any:
    """Remove internal identity/provenance values from student-visible data."""

    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, nested in value.items():
            clean_key = str(key)
            if clean_key.casefold() in _PROVIDER_PROHIBITED_KEYS:
                continue
            projected = _provider_safe_nested(nested)
            if projected is not _OMIT_PROVIDER_VALUE:
                output[clean_key] = projected
        return output
    if isinstance(value, (list, tuple)):
        return [
            projected
            for item in value
            if (projected := _provider_safe_nested(item)) is not _OMIT_PROVIDER_VALUE
        ]
    if isinstance(value, Path):
        return _OMIT_PROVIDER_VALUE
    if isinstance(value, str):
        if _PROVIDER_INTERNAL_VALUE.search(value) or _SHA256_VALUE.fullmatch(value):
            return _OMIT_PROVIDER_VALUE
    return value


def project_provider_evidence(compiled_evidence: CompiledEvidence) -> Mapping[str, Any]:
    """Create the allowlisted V1 provider projection of compiled evidence.

    Internal compilation keeps exact IDs, hashes, paths, versions, and source
    provenance.  This projection deliberately reconstructs a smaller object;
    it does not recursively pass through arbitrary compiled records.
    """

    content = compiled_evidence.content
    if not isinstance(content, Mapping):
        content = {}
    projected: list[dict[str, Any]] = []
    for item in content.get("selected_evidence", ()) or ():
        if not isinstance(item, Mapping):
            continue
        source_kind = str(item.get("source_kind") or "")
        record: dict[str, Any] = {"source_kind": source_kind}
        if source_kind == "DASHBOARD":
            for key in ("evidence_type", "evidence_strength", "content"):
                if key in item:
                    value = _provider_safe_nested(item[key])
                    if value is not _OMIT_PROVIDER_VALUE:
                        record[key] = value
        elif source_kind == "COURSE_RAG":
            for key in (
                "source_type",
                "document_title",
                "week",
                "section",
                "evidence_strength",
                "content",
            ):
                if key in item:
                    value = _provider_safe_nested(item[key])
                    if value is not _OMIT_PROVIDER_VALUE:
                        record[key] = value
        elif source_kind == "LEARNER_MEMORY":
            for key in ("memory_type", "content"):
                if key in item:
                    value = _provider_safe_nested(item[key])
                    if value is not _OMIT_PROVIDER_VALUE:
                        record[key] = value
        else:
            continue
        projected.append(record)

    if "legacy_raw_page_context" in content:
        legacy = _provider_safe_nested(content.get("legacy_raw_page_context"))
        if legacy is not _OMIT_PROVIDER_VALUE:
            projected.append(
                {
                    "source_kind": "DASHBOARD",
                    "evidence_type": "LEGACY_RAW_PAGE_CONTEXT",
                    "evidence_strength": "FROZEN_STRUCTURED_OUTPUT",
                    "content": legacy,
                }
            )

    typed_absence: list[dict[str, str]] = []
    for item in content.get("typed_absence", ()) or ():
        if not isinstance(item, Mapping):
            continue
        source_kind = str(item.get("source_kind") or "")
        status = str(item.get("status") or "")
        if source_kind and status:
            typed_absence.append({"source_kind": source_kind, "status": status})

    limitations = []
    for limitation in compiled_evidence.limitations:
        safe = _provider_safe_nested(str(limitation))
        if safe is not _OMIT_PROVIDER_VALUE and str(safe).strip():
            limitations.append(str(safe))
    return {
        "schema_version": "c4-real-provider-evidence-projection-v1",
        "evidence": projected,
        "typed_absence": typed_absence,
        "limitations": list(dict.fromkeys(limitations)),
    }


PROVIDER_EVIDENCE_PROJECTION_V2_ID = "c4-real-provider-evidence-projection-v2"
_V2_NEUTRAL_ABSENCE = {
    ("COURSE_RAG", "NO_RESULT"): (
        "No sufficiently relevant course material was found for this request."
    ),
    ("LEARNER_MEMORY", "NO_MATCH"): (
        "No relevant earlier-session learner information was available for this request."
    ),
    ("DASHBOARD", "FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK"): (
        "No student activity evidence was available for this page."
    ),
}


def _project_provider_evidence_item_v2(item: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Remove implementation metadata from one already allowlisted V1 item."""

    source_kind = str(item.get("source_kind") or "")
    record: dict[str, Any]
    if source_kind == "DASHBOARD":
        record = {
            "source": (
                "current_page_context"
                if item.get("evidence_type") == "LEGACY_RAW_PAGE_CONTEXT"
                else "dashboard_activity"
            )
        }
        if "content" in item:
            record["content"] = item["content"]
        return "DASHBOARD", record
    if source_kind == "COURSE_RAG":
        record = {"source": "course_material"}
        for key in (
            "document_title",
            "week",
            "section",
            "evidence_strength",
            "content",
        ):
            if key in item:
                record[key] = item[key]
        return "COURSE_RAG", record
    if source_kind == "LEARNER_MEMORY":
        record = {"source": "learner_memory"}
        for key in ("memory_type", "content"):
            if key in item:
                record[key] = item[key]
        return "LEARNER_MEMORY", record
    return None


def project_provider_evidence_v2_from_v1(
    provider_projection_v1: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Create the hygiene-repaired V2 projection from a frozen V1 projection.

    Exact canonical-byte deduplication is maintained independently for
    Dashboard, course-material, and learner-Memory items.  First occurrence
    order is preserved.  Module-off limitations are dropped; only typed
    activated/no-result outcomes receive neutral student-facing wording.
    """

    projected: list[dict[str, Any]] = []
    seen_by_kind: dict[str, set[bytes]] = {
        "DASHBOARD": set(),
        "COURSE_RAG": set(),
        "LEARNER_MEMORY": set(),
    }
    for item in provider_projection_v1.get("evidence", ()) or ():
        if not isinstance(item, Mapping):
            continue
        result = _project_provider_evidence_item_v2(item)
        if result is None:
            continue
        source_kind, record = result
        identity = canonical_json_bytes(record)
        if identity in seen_by_kind[source_kind]:
            continue
        seen_by_kind[source_kind].add(identity)
        projected.append(record)

    availability_notes: list[str] = []
    for item in provider_projection_v1.get("typed_absence", ()) or ():
        if not isinstance(item, Mapping):
            continue
        note = _V2_NEUTRAL_ABSENCE.get(
            (str(item.get("source_kind") or ""), str(item.get("status") or ""))
        )
        if note and note not in availability_notes:
            availability_notes.append(note)
    return {
        "evidence": projected,
        "availability_notes": availability_notes,
    }


def project_provider_evidence_v2(compiled_evidence: CompiledEvidence) -> Mapping[str, Any]:
    """Create the V2 student-relevant projection without altering internals."""

    return project_provider_evidence_v2_from_v1(
        project_provider_evidence(compiled_evidence)
    )


_PROVIDER_PLAN_FIELDS = (
    "student_state",
    "main_issue",
    "recommended_action",
    "why_this_matters",
    "why_this_fits_the_student",
    "action_steps",
    "supporting_evidence",
    "uncertainty_or_limitations",
    "learner_constraints",
)


def project_provider_planning_support(
    planner_result: PlannerResult | None,
) -> Mapping[str, Any] | None:
    """Project a Planner result without internal evidence or learner IDs."""

    if planner_result is None:
        return None
    plan: dict[str, Any] | None = None
    if isinstance(planner_result.plan, Mapping):
        plan = {}
        for key in _PROVIDER_PLAN_FIELDS:
            if key not in planner_result.plan:
                continue
            value = _provider_safe_nested(planner_result.plan[key])
            if value is not _OMIT_PROVIDER_VALUE:
                plan[key] = value
    limitations = []
    for limitation in planner_result.limitations:
        safe = _provider_safe_nested(str(limitation))
        if safe is not _OMIT_PROVIDER_VALUE and str(safe).strip():
            limitations.append(str(safe))
    return {
        "status": planner_result.status,
        "plan": plan,
        "limitations": list(dict.fromkeys(limitations)),
    }


class C4RealEvidenceCompilerV1:
    """Deterministic, provenance-preserving compiler with one stable hash."""

    identity = "C4_REAL_EVIDENCE_COMPILER_V1"

    def __init__(self, *, token_budget: int = 3200) -> None:
        if not isinstance(token_budget, int) or token_budget < 512:
            raise ValueError("Evidence token budget must be an integer of at least 512")
        self.token_budget = token_budget

    @staticmethod
    def _tokens(value: Any) -> int:
        return len(_TOKEN.findall(canonical_json_bytes(value).decode("utf-8")))

    def compile(
        self,
        *,
        request: C4RealRequest,
        clarification: ClarificationDecision,
        route: P3CapabilityRoute | None,
        activation: ModuleActivation,
        dashboard_evidence: EvidenceSynthesisResult | None,
        course_rag: CourseRAGResult | None,
        learner_memory: MemoryReadResult | None,
    ) -> CompiledEvidence:
        del route  # Route content must never enter provider-facing evidence.
        context = {
            "current_query": request.current_query,
            "current_page": request.current_page,
            "visible_conversation_history": [
                dict(item) for item in request.visible_conversation_history
            ],
        }
        content: dict[str, Any] = {"request_context": context}
        limitations: list[str] = []
        evidence_ids: list[str] = []

        if request.mode == C4Mode.C0_ORIGINAL:
            content["legacy_raw_page_context"] = _safe_evidence_value(
                request.dashboard_context
            )
            content["explicit_selected_evidence"] = None
        else:
            selected: list[dict[str, Any]] = []
            seen: set[str] = set()

            def append(record: dict[str, Any], evidence_id: str) -> None:
                clean = _safe_evidence_value(record)
                identity = canonical_sha256(clean)
                if identity in seen:
                    return
                candidate = {**content, "selected_evidence": [*selected, clean]}
                if self._tokens(candidate) > self.token_budget:
                    limitations.append(f"TOKEN_BUDGET_EXCLUDED:{evidence_id}")
                    return
                seen.add(identity)
                selected.append(clean)
                evidence_ids.append(evidence_id)

            for item in dashboard_evidence.items if dashboard_evidence else ():
                append(
                    {
                        "evidence_id": item.evidence_id,
                        "source_kind": "DASHBOARD",
                        "evidence_type": item.evidence_type,
                        "evidence_strength": item.evidence_strength,
                        "provenance": dict(item.provenance),
                        "content": item.content,
                    },
                    item.evidence_id,
                )
            for source in course_rag.sources if course_rag else ():
                append(
                    {
                        "evidence_id": source.source_id,
                        "source_kind": "COURSE_RAG",
                        "source_type": source.source_type,
                        "document_title": source.document_title,
                        "week": source.week,
                        "section": source.section,
                        "evidence_strength": source.evidence_strength,
                        "provenance": dict(source.provenance),
                        "content": source.content,
                    },
                    source.source_id,
                )
            for memory in learner_memory.items if learner_memory else ():
                append(
                    {
                        "evidence_id": memory.memory_id,
                        "source_kind": "LEARNER_MEMORY",
                        "memory_type": memory.item_type,
                        "version": memory.version,
                        "timestamp_version": dict(memory.timestamp_version),
                        "provenance": {
                            "representation": memory.provenance,
                            **dict(memory.provenance_details),
                        },
                        "content": memory.value,
                    },
                    memory.memory_id,
                )
            content["selected_evidence"] = selected
            absence: list[dict[str, str]] = []
            if activation.rag and course_rag is not None and not course_rag.sources:
                absence.append({"source_kind": "COURSE_RAG", "status": course_rag.result_status})
            if activation.memory and learner_memory is not None and not learner_memory.items:
                absence.append({"source_kind": "LEARNER_MEMORY", "status": learner_memory.status})
            if dashboard_evidence is not None and not dashboard_evidence.items:
                absence.append({"source_kind": "DASHBOARD", "status": dashboard_evidence.status})
            content["typed_absence"] = absence

        if clarification.needs_clarification:
            limitations.append("CLARIFICATION_REQUIRED; no optional evidence path executed")
        for source_limitations in (
            dashboard_evidence.limitations if dashboard_evidence else (),
            course_rag.limitations if course_rag else (),
            learner_memory.limitations if learner_memory else (),
        ):
            limitations.extend(str(value) for value in source_limitations)
        limitations = list(dict.fromkeys(limitations))
        token_count = self._tokens(content)
        if token_count > self.token_budget:
            raise ValueError("Mandatory C4 evidence exceeds the deterministic token budget")
        digest = canonical_sha256(content)
        return CompiledEvidence(
            content=content,
            evidence_ids=tuple(evidence_ids),
            limitations=tuple(limitations),
            compiled_evidence_sha256=digest,
            deterministic_token_count=token_count,
            deterministic_token_budget=self.token_budget,
        )


def validate_planner_evidence_consistency(
    plan: Mapping[str, Any], compiled_evidence: CompiledEvidence
) -> tuple[str, ...]:
    """Return deterministic consistency errors without changing plan content."""

    errors: list[str] = []
    content = compiled_evidence.content
    selected = content.get("selected_evidence", []) if isinstance(content, Mapping) else []
    available_ids = {
        str(item.get("evidence_id"))
        for item in selected
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    provenance = plan.get("source_provenance", [])
    used_ids = {
        str(item.get("evidence_id"))
        for item in provenance
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    if not used_ids.issubset(available_ids):
        errors.append("PLANNER_PROVENANCE_OUTSIDE_COMPILED_EVIDENCE")
    constraints = {
        str(item.get("content"))
        for item in selected
        if isinstance(item, Mapping)
        and item.get("source_kind") == "LEARNER_MEMORY"
        and item.get("memory_type") == "CONSTRAINT"
    }
    planned_constraints = {str(value) for value in plan.get("learner_constraints", [])}
    if constraints != planned_constraints:
        errors.append("PLANNER_DROPPED_OR_CREATED_LEARNER_CONSTRAINT")
    for item in provenance:
        if isinstance(item, Mapping) and item.get("source_kind") not in {
            "DASHBOARD",
            "COURSE_RAG",
            "LEARNER_MEMORY",
        }:
            errors.append("PLANNER_UNKNOWN_PROVENANCE_KIND")
    return tuple(dict.fromkeys(errors))


class C4RecommendationPlannerAdapter:
    """Read-only wrapper around utils/recommendation_planner.py."""

    identity = "C4_REAL_RECOMMENDATION_PLANNER_ADAPTER_V1"

    def __init__(self) -> None:
        self.call_count = 0

    def plan(
        self, *, request: C4RealRequest, compiled_evidence: CompiledEvidence
    ) -> PlannerResult:
        self.call_count += 1
        content = compiled_evidence.content
        selected = content.get("selected_evidence", []) if isinstance(content, Mapping) else []
        dashboard_pack: Mapping[str, Any] = {}
        course_chunks: list[dict[str, Any]] = []
        constraints: list[str] = []
        provenance: list[dict[str, Any]] = []
        for item in selected:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("source_kind") or "")
            provenance.append(
                {
                    "evidence_id": item.get("evidence_id"),
                    "source_kind": kind,
                    "evidence_strength": item.get("evidence_strength"),
                }
            )
            if kind == "DASHBOARD" and isinstance(item.get("content"), Mapping):
                dashboard_pack = item["content"]
            elif kind == "COURSE_RAG":
                source_content = item.get("content")
                if isinstance(source_content, Mapping):
                    text = str(
                        source_content.get("text")
                        or source_content.get("document_title")
                        or item.get("document_title")
                        or ""
                    )
                else:
                    text = str(source_content or "")
                if text:
                    course_chunks.append(
                        {
                            "source_type": "course_material",
                            "text": text,
                            "source_id": item.get("evidence_id"),
                        }
                    )
            elif kind == "LEARNER_MEMORY" and item.get("memory_type") == "CONSTRAINT":
                constraints.append(str(item.get("content")))

        if not dashboard_pack and not course_chunks and not constraints:
            return PlannerResult(
                status="INSUFFICIENT_EVIDENCE",
                plan=None,
                limitations=("No compiled evidence supports deterministic Planning.",),
            )
        # Keep pandas off the import-level Streamlit/factory path while using
        # the existing deterministic classifier whenever Planning executes.
        from utils.evidence_synthesiser import classify_query

        evidence_summary = {
            "primary_page": request.current_page,
            "current_page": request.current_page,
            "query_type": classify_query(request.current_query),
            "selected_evidence": dict(dashboard_pack),
            "uncertainty": "Compiled evidence boundaries remain authoritative.",
        }
        raw_plan = build_recommendation_plan(
            student_query=request.current_query,
            current_page=request.current_page,
            student_id=request.student_id,
            evidence_summary=evidence_summary,
            retrieved_context_chunks=course_chunks,
        )
        raw_plan.pop("student_id", None)
        raw_plan.pop("query_type", None)
        raw_plan["learner_constraints"] = constraints
        raw_plan["source_provenance"] = provenance
        raw_plan["compiled_evidence_sha256"] = compiled_evidence.compiled_evidence_sha256
        errors = validate_planner_evidence_consistency(raw_plan, compiled_evidence)
        if errors:
            return PlannerResult(status="UNSUPPORTED_OR_INCONSISTENT", plan=None, limitations=errors)
        return PlannerResult(status="USED", plan=raw_plan)


class ProviderExecutionNotAuthorised(RuntimeError):
    """Raised before transport access when I0 has not authorised generation."""


class C4ProviderCompatibleGenerator:
    """Future Chat Completions adapter; disabled unless explicitly armed."""

    identity = "C4_REAL_OPENAI_CHAT_COMPLETIONS_GENERATOR_V1"

    def __init__(
        self,
        *,
        transport: Callable[[Mapping[str, Any]], Any] | None = None,
        execution_authorised: bool = False,
    ) -> None:
        self.transport = transport
        self.execution_authorised = bool(execution_authorised)
        self.transport_call_count = 0

    @staticmethod
    def _generation_input(
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> dict[str, Any]:
        return {
            "current_query": request.current_query,
            "current_page": request.current_page,
            "visible_conversation_history": [
                dict(item) for item in request.visible_conversation_history
            ],
            "evidence": project_provider_evidence_v2(compiled_evidence),
            "planning_support": project_provider_planning_support(planner_result),
        }

    def _build_request_payload(
        self,
        *,
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
        schema_path: Path,
        schema_name: str,
    ) -> Mapping[str, Any]:
        prompt = GENERATION_PROMPT_PATH.read_text(encoding="utf-8")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return {
            "model": GENERATOR_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": canonical_json_bytes(
                        self._generation_input(request, compiled_evidence, planner_result)
                    ).decode("utf-8"),
                },
            ],
            "temperature": 0,
            "max_tokens": GENERATOR_MAX_OUTPUT_TOKENS,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }

    def build_request_payload(
        self,
        *,
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> Mapping[str, Any]:
        """Build the preserved V1 transport payload for existing callers."""

        return self._build_request_payload(
            request=request,
            compiled_evidence=compiled_evidence,
            planner_result=planner_result,
            schema_path=GENERATION_SCHEMA_PATH,
            schema_name="c4_real_generation_response_v1",
        )

    def build_request_payload_v2(
        self,
        *,
        request: C4RealRequest,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> Mapping[str, Any]:
        """Build the provider-compatible V2 payload without transport access."""

        return self._build_request_payload(
            request=request,
            compiled_evidence=compiled_evidence,
            planner_result=planner_result,
            schema_path=GENERATION_SCHEMA_V2_PROVIDER_PATH,
            schema_name="c4_real_generation_response_v2_provider_compatible",
        )

    @staticmethod
    def _parse(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if set(parsed) != {"answer_text"} or not isinstance(parsed["answer_text"], str):
            return None
        if not parsed["answer_text"].strip():
            return None
        return parsed["answer_text"]

    def generate(
        self,
        *,
        request: C4RealRequest,
        clarification: ClarificationDecision,
        route: P3CapabilityRoute | None,
        activation: ModuleActivation,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> GenerationResult:
        del clarification, route, activation
        if not self.execution_authorised or self.transport is None:
            raise ProviderExecutionNotAuthorised(
                "I0 freezes the Generator contract but authorises zero generation calls"
            )
        payload = self.build_request_payload(
            request=request,
            compiled_evidence=compiled_evidence,
            planner_result=planner_result,
        )
        last_error = "INVALID_STRICT_STRUCTURED_OUTPUT"
        for attempt in range(2):
            self.transport_call_count += 1
            raw = self.transport(payload)
            answer = self._parse(raw)
            if answer is not None:
                return GenerationResult(
                    text=answer,
                    generator_identity=self.identity,
                    output_kind="STRICT_ANSWER_TEXT_V1",
                )
            if attempt == 0:
                continue
        raise ValueError(last_error)


class C4OutputGuardViolation(ValueError):
    pass


class C4DeterministicOutputGuard:
    """Flag/fail unsupported output without rewriting substantive content."""

    identity = "C4_REAL_DETERMINISTIC_OUTPUT_GUARD_V1"
    _INTERNAL_TERMS = re.compile(
        r"\b(?:C[0-5](?:_[A-Z_]+)?|P3|R2V2|ablation|capability route|router decision)\b",
        re.IGNORECASE,
    )
    _DETAIL = re.compile(
        r"\b(?:W\d{1,2}|week\s*\d{1,2}|\d+(?:\.\d+)?%?|https?://\S+)",
        re.IGNORECASE,
    )

    @staticmethod
    def _words(value: str) -> int:
        return len(re.findall(r"\b\w+\b", value, re.UNICODE))

    def apply(
        self,
        *,
        request: C4RealRequest,
        generated: GenerationResult,
        activation: ModuleActivation,
        compiled_evidence: CompiledEvidence,
        planner_result: PlannerResult | None,
    ) -> GuardedOutput:
        text = str(generated.text or "").strip()
        failures: list[str] = []
        if not text:
            failures.append("EMPTY_ANSWER")
        if self._INTERNAL_TERMS.search(text):
            failures.append("INTERNAL_EXPERIMENT_OR_ROUTER_TERMINOLOGY")
        evidence_text = canonical_json_bytes(
            {
                "query": request.current_query,
                "history": [dict(item) for item in request.visible_conversation_history],
                "compiled": compiled_evidence.content,
                "plan": planner_result.plan if planner_result else None,
            }
        ).decode("utf-8")
        supported_details = set(self._DETAIL.findall(evidence_text))
        unsupported_details = [
            value for value in self._DETAIL.findall(text) if value not in supported_details
        ]
        if unsupported_details:
            failures.append("UNSUPPORTED_NUMERIC_COURSE_OR_LINK_DETAIL")
        if not activation.planning:
            ordered_steps = len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+", text))
            if ordered_steps >= 2 or re.search(r"\bfirst\b.{0,180}\bthen\b", text, re.I | re.S):
                failures.append("DETAILED_PLAN_WHILE_PLANNING_DISABLED")
        absence = []
        if isinstance(compiled_evidence.content, Mapping):
            absence = compiled_evidence.content.get("typed_absence", []) or []
        absence_by_kind = {
            str(item.get("source_kind")): str(item.get("status"))
            for item in absence
            if isinstance(item, Mapping)
        }
        if absence_by_kind.get("LEARNER_MEMORY") == "NO_MATCH" and re.search(
            r"\b(?:you (?:said|told me|mentioned)|your (?:goal|preference|constraint))\b",
            text,
            re.IGNORECASE,
        ):
            visible = request.current_query + " " + " ".join(
                str(item.get("content") or "") for item in request.visible_conversation_history
            )
            if not re.search(
                r"\b(?:goal|preference|constraint|said|mentioned)\b", visible, re.IGNORECASE
            ):
                failures.append("FABRICATED_LEARNER_FACT")
        if absence_by_kind.get("COURSE_RAG") == "NO_RESULT":
            if self._words(text) > 140 or re.search(
                r"\b(?:the course states|the reading argues|the lecture explains)\b",
                text,
                re.IGNORECASE,
            ):
                failures.append("UNBOUNDED_NO_RESULT_HANDLING")
        selected = (
            compiled_evidence.content.get("selected_evidence", [])
            if isinstance(compiled_evidence.content, Mapping)
            else []
        )
        metadata_only = any(
            isinstance(item, Mapping)
            and item.get("evidence_strength") in {"TITLE_AND_METADATA_ONLY", "LINK_ONLY"}
            for item in selected
        )
        substantive_course = any(
            isinstance(item, Mapping)
            and item.get("source_kind") == "COURSE_RAG"
            and item.get("evidence_strength")
            in {"FULL_TEXT_SUPPORT", "BODY_EXCERPT", "SUMMARY_SUPPORT"}
            for item in selected
        )
        if metadata_only and not substantive_course and re.search(
            r"\b(?:argues|concludes|demonstrates|finds that|explains that)\b", text, re.IGNORECASE
        ):
            failures.append("DETAIL_EXCEEDS_EVIDENCE_STRENGTH")
        if failures:
            raise C4OutputGuardViolation(";".join(dict.fromkeys(failures)))
        return GuardedOutput(
            text=text,
            generator_identity=generated.generator_identity,
            output_kind=generated.output_kind,
            limitations=generated.limitations,
            guard_flags=(),
        )


__all__ = [
    "C4DeterministicOutputGuard",
    "C4OutputGuardViolation",
    "C4PersistentLearnerMemoryAdapter",
    "C4ProviderCompatibleGenerator",
    "C4RealEvidenceCompilerV1",
    "C4RealEvidenceSynthesisAdapter",
    "C4RecommendationPlannerAdapter",
    "C4SelectedR0CourseRAGAdapter",
    "FrozenClarificationGateAdapter",
    "PrecomputedP3RouteCache",
    "ProviderExecutionNotAuthorised",
    "canonical_json_bytes",
    "canonical_sha256",
    "semantic_input_sha256",
    "PROVIDER_EVIDENCE_PROJECTION_V2_ID",
    "project_provider_evidence",
    "project_provider_evidence_v2",
    "project_provider_evidence_v2_from_v1",
    "project_provider_planning_support",
    "validate_planner_evidence_consistency",
]
