# Latest W9 runtime mapping

The correct supplied Streamlit interface is bound to the actual selected authorized learner and observation range. Original frozen research modules and study outcomes remain unchanged; only the public adapter adds dashboard scope, trusted session receipts and explicit consent operations. All symbols and line numbers below were read from actual current files. The JSON companion records file SHA-256 and sizes.

W9 reference: original architecture chapter §§3.2–3.4, detailed_architecture.mmd, EXECUTION_METHODS.md and PARAMETERS_AND_STUDY_ROLES.json. This is an engineering mapping, not a paper review.

## What was corrected

- The publication adapter originally used selected frozen study task context instead of the current numeric dashboard learner/week. It now re-reads allowlisted sources and creates the original Snapshot/Scope with no historical seed for a new dashboard session.
- S0/S1 and actual frozen clarification now bypass paid P3. Candidate/FINAL now use original 2048 caps.
- COMPONENTS supports explicit LEXICAL/HYBRID selection and reports the actual backend. MPNet Hybrid was actually run offline; no paid provider inference was performed.
- Model plans are proposals until explicit consent. Native writer and original relation compiler persist adoption/self-report completion. Worker-owned preparation and checker receipts close the reproduced forged cross-session prepared-result path.
- Reflection cohort curves are included as separate visible chart context and eighth source hash. Their averages are not individual learner facts or declared complete coverage.

## Capability map

| Component | Status / entry | Evidence anchor |
|---|---|---|
| Current learner/week source binding | ACTUAL_LOCAL_CORE; `PublicAssistant.bind_dashboard(learner_id, week_start=0, week_end=10, lecture_item_id=None)` | `public_runtime/core.py:52` |
| Evidence and mode/access/clarification gates | ACTUAL_LOCAL_CORE; `PublicAssistant.components/live(mode='S0_PAGE_ONLY'..'S5_FULL')` | `public_runtime/core.py:101` |
| Frozen P3 capability composition | ORIGINAL_EXACT_WIRE_MOCKED; `PublicAssistant.live(..., transport=None or exact mock transport)` | `research/src/rq3_original/utils/c4_rebuild/i1/frozen_p3.py:24` |
| Single gated R0 course RAG | ACTUAL_LOCAL_CORE; `components(rag=True) or positive P3 RAG bit with a mode permission` | `research/src/rq3_original/utils/c4_rebuild/rag.py:9` |
| Full M1 native Memory and Hybrid option | ACTUAL_LOCAL_CORE_AND_REAL_OFFLINE_MODEL; `components/live(memory_backend='LEXICAL'|'HYBRID'); controls.memory_purpose` | `public_runtime/core.py:74` |
| Explicit plan adoption/completion and trusted proposal boundary | NEW_PUBLIC_ADAPTER_USING_ORIGINAL_WRITER_AND_RELATIONS; `memory_accept_plan(task_id,plan,consent=False); memory_complete_action(task_id,action_memory_id,consent=False); memory_task_state(task_id=None)` | `research/src/rq3_original/public_core_worker.py:206` |
| P1+i5 typed candidate and encoded checks | ACTUAL_ORIGINAL_PROJECTION_AND_EXACT_WIRE_MOCKED; `components(planning=True); live with positive P3 Planning and mode permission` | `research/src/rq3_original/utils/c4_rebuild/planning.py:82` |
| Compiler and FINAL citation contract | ACTUAL_ORIGINAL_CORE_AND_EXACT_WIRE_MOCKED; `live FINAL after actual preparation/checking; components gives the original prepared payload without a natural answer` | `research/src/rq3_original/utils/c4_real_adapters.py:1086` |
| RQ1 ranking and RQ2 comparisons | PRESERVED_INDEPENDENT_RESEARCH_ENTRYPOINTS; `research/src/rq3_original/evaluation/learned_intent_ranking/ and capability_routing_rq2_*` | `research/src/rq3_original/evaluation/learned_intent_ranking/lr4b_dev/train_m64.py:114` |
| Historical replay | SAVED_246_RESPONSES_WITH_IDENTITY_CHECK; `PublicAssistant.replay(task_id,mode)` | `public_runtime/core.py:92` |

## Current learner/week source binding

Eight allowlisted CSV hashes bind the numeric learner ID, course, observed week buckets and optional recording. Worker re-reads rows and original Snapshot/Aggregator, rather than trusting client rows or a frozen research task. Reflection cohort series are separate current-chart context, not personal activity facts.

**Boundary:** Calendar UTC dates encode original historical Week buckets. Naive source timestamp timezone and complete coverage are unknown; Echo material weeks and cumulative feature snapshots are not visit-time activity.

Actual source: `public_runtime/core.py:52 PublicAssistant.bind_dashboard`, `public_runtime/dashboard.py:71 build_context`, `public_runtime/dashboard.py:86 validate_context`, `public_runtime/dashboard.py:95 source_selection`, `public_runtime/dashboard.py:150 reflection_cohort_context`, `research/src/rq3_original/public_core_worker.py:68 DashboardPages`, `research/src/rq3_original/utils/c4_dashboard_scoped/aggregate.py:401 aggregate`.

## Evidence and mode/access/clarification gates

S0 current-page-only; S1 adds Evidence; S2 RAG; S3 Memory; S4 Planning; S5 all permissions. Activation is mode AND requirement AND explicit runtime access AND no clarification. S0/S1 bypass P3. Original frozen clarification returns local clarification before constructing a paid client.

**Boundary:** COMPONENTS requirement bits come from visible user controls and are explicitly NO_P3. Permission is not proof of activation or a successful return. Missing schedule fields remain clarification/NOT_CHECKABLE.

Actual source: `public_runtime/core.py:101 PublicAssistant.components`, `public_runtime/core.py:126 PublicAssistant.live`, `research/src/rq3_original/public_core_worker.py:128 request_for`, `research/src/rq3_original/utils/c4_rebuild/service.py:90 ResearchService.prepare`, `research/src/rq3_original/utils/c4_dashboard_scoped/scope.py:187 Snapshot.validate_query`.

## Frozen P3 capability composition

FrozenP3 verifies committed prompt/config/schema/example hashes and accepts exactly current_query/current_page/dashboard_context/visible_conversation_history. RAG specialist + Memory specialist + B4 Planning bit, model gpt-4o-mini-2024-07-18, temperature 0, output caps 32/32/64.

**Boundary:** No paid inference executed. Exact mock validates the same payloads and full downstream chain; it is not an inference-quality result. RQ1/C0 is not inserted into this selected P3 pipeline.

Actual source: `research/src/rq3_original/utils/c4_rebuild/i1/frozen_p3.py:24 FrozenP3`, `research/src/rq3_original/evaluation/rq3_real_c4/i0_integration/route_execution_runner.py:99 build_payload`, `public_runtime/core.py:126 PublicAssistant.live`.

## Single gated R0 course RAG

R0OnExplicitCorpus retains the original corrected lexical scorer over 624 true chunks. upstream_authorised=True avoids a second needs-retrieval gate; at most five matches; positive score and leading threshold 2.0. UndatedR0 keeps fixed corpus temporal provenance.

**Boundary:** No dense course-RAG claim. Raw conversation is ignored by this original R0 scoring path. Public evaluation Gold/ratings are absent from corpus and generation constructors.

Actual source: `research/src/rq3_original/utils/c4_rebuild/rag.py:9 R0OnExplicitCorpus`, `research/src/rq3_original/utils/c4_rebuild/rag.py:29 ProvisionalR0.retrieve`, `research/src/rq3_original/utils/c4_rag/retrievers.py:149 C4RAGLegacyLexical.retrieve`, `research/src/rq3_original/experiments/rq3_original25_plus_review_r1/adapter.py:236 UndatedR0`.

## Full M1 native Memory and Hybrid option

Main UI/API imports no native M1/network guard. Credential-free worker clones native DBs read-only, invokes I1NativeM1/read_bundle, reopens native authority, checks source role/span/hash/version/consent/validity and purpose-bounded links. New dashboard learners start in empty native C4 stores; same learner session shares Memory across pages, other learners/visitors do not. HYBRID uses isolated pinned MPNet model worker with optional LAD_MODEL_PYTHON.

**Boundary:** LEXICAL and HYBRID are distinct reported identities. Supported purposes GOAL_RECALL/PLAN_CONTINUATION/COMPLETION_RECALL permit guarded expansion; UNKNOWN is seed-only. Fresh current-window visible-history duplicates remain excluded by the original retriever. Cloud temporary storage is not durable cross-visit Memory.

Actual source: `public_runtime/core.py:74 PublicAssistant.call`, `research/src/rq3_original/public_core_worker.py:163 session_memory`, `research/src/rq3_original/utils/c4_rebuild/memory.py:31 m1_dependencies`, `research/src/rq3_original/utils/c4_rebuild/memory.py:13 clone_native_states`, `research/src/rq3_original/utils/c4_rebuild/memory.py:81 NativeM1.authority_for`, `research/src/rq3_original/utils/c4_rebuild/i1/memory.py:32 I1NativeM1`, `research/src/rq3_original/utils/c4_rebuild/i1/native_backend.py:13 I1LocalBackend`, `research/src/rq3_original/research_followups/rq3_rebuild/m1_memory_completeness/code/relations.py:131 read_bundle`.

## Explicit plan adoption/completion and trusted proposal boundary

Actual worker prepare persists a random session receipt and the original complete prepared result. Candidate payload/check re-read that record and reject changed scope/source/content. An original successful candidate check issues a second receipt, required by FINAL and proposal registration. Model proposals remain outside Memory until literal Boolean consent=True. Original C4 writer records USER ACTIVE_PLAN/PROGRESS_UPDATE and USER self-reported COMPLETED_ACTION; original compile_sidecar validates the three supported relations.

**Boundary:** No automatic model suggestion write, inferred user Goal, or VERIFIED_SYSTEM_EVENT. Completion uses immutable native accepted-action ID, not model task ID. Staged DB/graph validation prevents policy-rejection partial writes; final SQLite and JSON commits are individual in the serial session adapter, not a cross-process multi-file transaction guarantee.

Actual source: `research/src/rq3_original/public_core_worker.py:206 save_runtime_receipt`, `research/src/rq3_original/public_core_worker.py:228 verified_preparation`, `research/src/rq3_original/public_core_worker.py:238 save_candidate_receipt`, `research/src/rq3_original/public_core_worker.py:247 verified_candidate`, `research/src/rq3_original/public_core_worker.py:308 plan_operation`, `research/src/rq3_original/public_core_worker.py:256 native_fact`, `research/src/rq3_original/public_core_worker.py:275 confirmed_relation`, `research/src/rq3_original/public_core_worker.py:288 validate_confirmed_graph`, `research/src/rq3_original/utils/c4_memory/c4_memory_writer.py:234 C4MemoryWriter.apply_candidate`, `research/src/rq3_original/research_followups/rq3_rebuild/m1_memory_completeness/code/relations.py:47 compile_sidecar`.

## P1+i5 typed candidate and encoded checks

Original source-binding projection, bridge checks and candidate checks remain intact. Candidate uses i1_candidate_v1, fixed 2048 token cap, at most one eligible repair. Authoritative completion relations map to accepted native action task IDs and support no-repeat checks. Explicit scheduling needs user-supplied timezone/windows/horizon.

**Boundary:** The frozen fields_for encodes Goal, numeric constraint and completion-action links; arbitrary raw ACTIVE_PLAN text is NOT automatically decoded into typed active_plan. P1 planner_input.active_plan remains None and i0_diagnostics.active_plan_adoption remains NOT_ESTABLISHED even though the public UI has explicit adopted-plan state and M1 chosen_active_plan_id. This limitation is not silently weakened. Semantic support and unencoded constraints are not established by the checker.

Actual source: `research/src/rq3_original/utils/c4_rebuild/planning.py:82 fields_for`, `research/src/rq3_original/utils/c4_rebuild/planning.py:123 project`, `research/src/rq3_original/utils/c4_rebuild/planning.py:162 bridge_from_m1`, `research/src/rq3_original/experiments/rq3_original25_plus_review_r1/adapter.py:180 planner_for`, `research/src/rq3_original/utils/c4_rebuild/i1/renderer.py:75 candidate_payload`.

## Compiler and FINAL citation contract

Original common compiler budget is 12000 regex units with complete-request cap 50000. Omitted Memory facts, IDs and links cannot re-enter through planner/raw envelope. Original reused62_final_v1 wire returns answer and cited_evidence_ids; model snapshot/temp0 and fixed 2048 cap. Citation IDs must be retained source IDs, and all FINAL checks remain.

**Boundary:** Citation membership is not semantic entailment; final prose fidelity to the accepted typed plan is NOT_CHECKED. No research answers, ratings or paper statistics are regenerated.

Actual source: `research/src/rq3_original/utils/c4_real_adapters.py:1086 C4RealEvidenceCompilerV1`, `research/src/rq3_original/utils/c4_rebuild/service.py:90 ResearchService.prepare`, `research/src/rq3_original/utils/c4_rebuild/i1/renderer.py:38 material`, `research/src/rq3_original/utils/c4_rebuild/generation.py:64 check_final_fields`, `public_runtime/core.py:126 PublicAssistant.live`.

## RQ1 ranking and RQ2 comparisons

Original RQ1 K0 keyword/C0 MPNet MAX over 62 examples and16 labels/M64 training and final inference remain separate. RQ2 specialist/comparison/frozen serializers remain available as research code. Final UI uses the selected frozen P3 only.

**Boundary:** Earlier independent algorithms are not serial runtime stages of P3. Governed training/final evaluation scripts keep their original exact authorization/worktree/artifact preflight and may require original manifests/checkpoints; this task does not re-arm or rerun studies or use Gold for generation.

Actual source: `research/src/rq3_original/evaluation/learned_intent_ranking/lr4b_dev/train_m64.py:114 train_scenario_seed`, `research/src/rq3_original/evaluation/learned_intent_ranking/rq1c/final_model_runner.py:612 prepare_final_runtime_bundle`, `research/src/rq3_original/evaluation/learned_intent_ranking/rq1c/final_model_runner.py:661 run_final_evaluation_in_memory`, `research/src/rq3_original/evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/rag_specialist_protocol.py:354 verify_required_protocol`, `research/src/rq3_original/evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/memory_specialist_common.py:288 verify_frozen_sources`.

## Historical replay

246 immutable task/mode answer slots for41 actual questions are verified with original answer_sha256. This selection is independent of currently displayed dashboard learner/week.

**Boundary:** New query replay is rejected. A research task scope or seed cannot stand in for the selected current learner.

Actual source: `public_runtime/core.py:92 PublicAssistant.replay`.

## Validation and integration API

`python -m unittest tests.test_runtime tests.test_dashboard_runtime tests.test_plan_memory -v`: 25 backend tests passed in43.078seconds with original core, actual local CSV/native SQLite, provider-only exact mocks and local HTTP provider isolation. Seven plan tests include the exact forged prepared-result attack, stolen cross-session runtime/candidate receipts, changed checked plan, literal consent, native policy rollback and immutable completed-action ID projection.

Actual offline Hybrid receipt: pinned MPNet revision `e8c3b32edf5434bc2275fc9bab85f82640a19130`, backend `M1_HYBRID_LINKS_DEV_CANDIDATE`, status PASS, read-only hashes unchanged, paid calls0. UI tests, all-suite CI, browser captures and deployment are reported by the other task owners.

`memory_task_state()` returns `{plans:[{plan_sha256,plan_memory_id,plan,origin:"USER",adoption_basis:"EXPLICIT_UI_CONSENT",actions:[{step_id,action,action_memory_id,completion_memory_id,completed,completion_basis}]}],learner_id,course_id}`. `completion_basis` is `EXPLICIT_USER_SELF_REPORT` for a recorded completion and None otherwise. Adoption and completion default to denied consent; only Boolean True writes.

The session adapter is serial and temporary in Community Cloud. It stages native policy and relation validation, then commits SQLite and sidecars individually. It does not claim concurrent cross-process atomicity or durable cloud Memory. RQ1/RQ2 frozen evaluation is preserved but not rerun. P1 does not automatically recover typed active_plan from arbitrary natural-language native records; source links and completion constraints are real, semantic plan recovery remains unsupported.
