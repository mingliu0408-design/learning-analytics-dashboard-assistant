# RQ3 implementation and limits

The release preserves author research code under `src/rq3_original/`, with the native `utils`, `research_followups` and `evaluation` layout so its actual dependency imports and source guards remain usable. `metadata/source_map_rq3.json` records each source path, local historical commit, original hash, public hash and adaptation. These source commits identify local frozen research history; no public blob URL is asserted for them.

The default result reproduction is separate from these system tests. Run the L2 implementation checks from the repository root:

```sh
python checks/check_rq3.py
```

This runs seven synthetic checks using Python's standard library and a new temporary SQLite database. It tests scope filtering across five pages, unknown versus observed-zero semantics, evaluation-sidecar exclusion, all six mode gates with an explicitly synthetic route, exact frozen P3 payload construction, actual R0 lexical retrieval, persistent/read-only Memory, typed planner schemas and retained-citation validation. It performs no P3 inference, generator call, model encoding, Judge call or new human rating. The fixture is newly invented release-test material and is not any of the 41 study tasks. The fixed synthetic route validates orchestration only; it is not an estimate of router accuracy.

## Actual components

| Component | Source entry within `src/rq3_original/` | Release behavior |
|---|---|---|
| Five-page evidence | `utils/c4_dashboard_scoped/{scope,aggregate,select,integration}.py` | Overview, Resources, Lecture, Debate and Reflection; identity/course/time filtering, scoped metric definitions, missing/unknown states and provenance |
| Study page/source projection | `experiments/rq3_original25_plus_review_r1/adapter.py` | Original25 source recontextualisation and synthetic expanded-task event/record projection; runtime source guard excludes evaluation fields |
| R0 lexical course retrieval | `utils/course_material_retriever.py`, `utils/c4_rag/retrievers.py`, `utils/c4_rebuild/rag.py` | Real scorer; upstream-authorised injected corpus bypasses the old second semantic gate; `top_k=5` and relevance thresholds retained |
| P3 and clarification | `utils/c4_rebuild/i1/frozen_p3.py`, `utils/c4_real_adapters.py`, `evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/` | CG1 deterministic clarification; P3 consumes exactly four original semantic fields, with three frozen LLM role payloads |
| Persistent Memory | `utils/c4_memory/`, `utils/c4_rebuild/{memory,i1/memory}.py`, `research_followups/rq3_rebuild/{m0_memory_data,m1_memory_completeness}/code/` | SQLite schema, strict writer, FTS/optional semantic retrieval, read-only reopen, links, source roles, consent and native-version checks |
| Planner | `research_followups/rq3_rebuild/p0_planner_prototype/`, `p1_planner_bridge/`, `i3_planner_diagnosis_repair/`, `i5_typed_action_planner/`, `utils/c4_rebuild/planning.py` | Actual encoded constraint checks, exact source-reference projection, candidate/repair payloads and ordinary-advice versus calendar schema |
| Six modes and orchestration | `utils/c4_rebuild/{contracts,service,generation}.py`, `utils/c4_rebuild/i1/{orchestrator,durable,transport}.py`, `experiments/rq3_original25_plus_review_r1/run_batch.py` | S0 page only; S1 evidence; S2 evidence+RAG; S3 evidence+Memory; S4 evidence+Planner; S5 all modules. Activation still requires mode, gate and explicit access |
| Historical continuation | `experiments/rq3_original25_plus_review_r1/confirmed41_repair_continuation_2026-09-08/` and `confirmed41_memory_isolation_continuation_2026-09-08/` | A1 source-time/Planning interface and A3 credential-free worker isolation, retry/unknown accounting and continuation code retained for inspection |

The historical continuation launchers intentionally retain their original manifest/approval/parent-ledger checks. They are not a standalone regeneration command: they require withheld source states, per-run ledgers and input bindings. The portable default entry does not invoke them. Their deployment/run-specific path defaults have been replaced with relative external-input placeholders. No old history or private ledger is included.

## Historical execution versions

`configs/rq3/execution_versions.json` is a projection of the supplied frozen final handoff: A supplied 168 selected answers, A1 12, A2 3 and A3 63. All 246 task/mode slots are retained in its stage map. No answer text, raw source content or private prompt payload is published there. A3's final handoff is not evidence that all answers used the A3 interface.

The frozen run bindings identify A at `911202546d094d3d6cf82d0db22088ea10e3648d`, A1 at `c73a90e18ec90f75187675b20e4b30db04dd18e7`, A2 at `83f49fda604733416480f54499f3630b49a0e104`, and A3 at `54e1dafe59d0cc9215856387cad92af9acd097b3`. A uses `REUSED62_REPLAY_INTERFACE_V1`; A1–A3 also bind `A1_PLANNING_INTENT_DECLARED_SOURCE_TIME_V1`. A2 and A3 differ in the recovery controls. The exported source came from fixed commit `fdd9848b2a92b5f50675d193a4765e02dfa9ebb8`. Five key renderer/interface/planner/adapter source files were checked byte-for-byte against A3's execution commit; the comparison is recorded. Other files must not be inferred identical across all historical stages.

## Prompts, examples and schema

`prompts/rq3/` contains the exact `REUSED62_REPLAY_INTERFACE_V1` FINAL system string and response schema, plus actual typed candidate local/wire schema pairs and the frozen RAG, Memory and B4 Planning role prompts, schemas and eight controlled synthetic DEV few-shot examples per role. Candidate instructions are assembled by the preserved I1 renderer, I3 repair contract and I5 typed planner; those files are the authoritative actual templates. A1 modifies bound source-time/intent interpretation, without replacing their prompt text. The older I1 FINAL schema remains in source as a dependency/historical interface, and is not mislabeled as the final 246-answer template.

Frozen P3 uses `gpt-4o-mini-2024-07-18`, temperature 0, role output limits 32/32/64. Generation uses the same model and temperature with 2,048 output tokens for CANDIDATE and FINAL. Evidence/request caps are 12,000/50,000 token-estimate units. `configs/rq3/frozen_parameters.json` explicitly identifies its source as the historical proposed base configuration; execution authorization and continuation controls are distinct run bindings.

One B4 package contained two private encoder-provenance paths outside model-visible fields. Those paths were replaced, and its containing-file guard was rebound to the public hash. The original source hash is retained in the source map. Prompts, few-shot inputs/outputs, schema and model parameters were unchanged. The other source guards and the P0 dependency lock remain effective.

## Inputs and optional dependencies for L3

Full re-execution requires separately authorised source material and runtime bindings. It is not executed by this release task. In particular, the repository withholds the original student dashboards, private conversation/source-event histories, native Memory databases, course full texts, per-request source bindings/approvals, original generated answer texts and paid-service credentials. It does not invent replacements for them. The original loader contracts and missing-file errors are retained.

The course interface accepts explicit `CourseChunk` records (`chunk_id`, `source_file`, `source_type`, `title`, `text`, optional `week`, `page`, `task_type`, `metadata`) through `R0OnExplicitCorpus`. The canonical loader additionally requires the frozen course files and exact metadata hash named in `utils/c4_rag/corpus.py`. The metadata implementation/content is withheld; its import is delayed to actual corpus ingestion. Set `LAD_COURSE_SOURCE_ROOT` to an authorised corpus root when using that loader. A different corpus is an explicitly new run and cannot reproduce the historical material by being given the same filename.

Native hybrid Memory needs the frozen `sentence-transformers/all-mpnet-base-v2` snapshot at revision `e8c3b32edf5434bc2275fc9bab85f82640a19130`, local `torch` and `transformers`, and the original graph/source-event/database contracts. Set `LAD_MPNET_PATH` and, if needed, `LAD_MODEL_PYTHON` explicitly. Models are loaded locally; model weights are not distributed. Corpus parsing may require `pypdf`. Optional service execution requires the `openai` package and the explicit runtime API environment/key, with no import-time client construction. The default tests need none of these packages or weights. This release does not claim that an untested modern optional environment reproduces the historical encoder/provider environment.

Encoded planner checks do not establish semantic support, plan adoption, completion, real-world feasibility, learning gains or teacher approval. Memory retrieval is not proof of learner commitment. Negative cases, missing/ambiguous states, original17/new12-family strata and the original statistical claims remain unchanged.
