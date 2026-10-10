# Actual RQ3 templates

- `final_system_reused62_v1.txt` and `final_schema_reused62_v1.json`: actual final-answer interface for the confirmed41 lineage. Source: `src/rq3_original/research_followups/rq3_rebuild/a_reuse62/interfaces.py`. Runtime enum values are restricted to retained source IDs.
- `typed_ordinary_action_advice_schemas.json` and `typed_explicit_schedule_schemas.json`: `[local_schema, strict_provider_schema]` returned by the actual I5 `schemas(kind)` function. Candidate instruction construction also uses the actual I1 renderer and I3 `repair_v1.py`; it includes source-specific reference catalogs, so the entire runtime prompt cannot be reduced to one static text file.
- `p3_{rag,memory,b4_planning}_system.txt`, `_schema.json`, `_few_shot.json`: exact model-visible frozen specialist/joint-role templates and controlled synthetic DEV examples. `FrozenP3` verifies the preserved source packages before construction. These examples are not student records or a replacement for study inputs.

Historical I1 templates are preserved within source for dependency/provenance purposes; they are not attributed to every historical answer. See `docs/RQ3_IMPLEMENTATION.md` and `configs/rq3/execution_versions.json` for source stages and limitations. No model is called to export or inspect these templates.
