# Frozen RQ2 prompts, few-shot examples and schemas

The real files remain beside their original source modules under `src/rq2_original/evaluation/` so their relationships remain inspectable:

- `capability_routing_rq2_v2_stage4/track_i_b4/b4_final_full_dev_prompt_package_v1.json`: final DEV-selected B4 prompt package and eight synthetic few-shot examples.
- `capability_routing_rq2_v2_stage4/track_i_b4/b4_response_schema_v2.json` and `b4_final_frozen_configuration_v2.json`: final output contract and generation parameters.
- `capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json` and `memory_specialist_final_full_dev_prompt_package_v1.json`: the actual specialist prompt packages, paired with their `*_schema_v1.json` and `*_prompt_frozen_v1.txt` files.
- `capability_routing_rq2_v2_stage1/track_d_b4_p1/prompt_template.txt`: earlier mock-only Stage1 interface, not the final historical B4 prompt.

Controlled DEV examples are synthetic stimuli, not original student records. Released package metadata has private path prefixes replaced by `external_inputs/`; model-visible prompt/example strings are preserved. Historical source hashes and release hashes are separate in `metadata/source_map_rq1_rq2.json`. No claim is made that a later package produced an earlier prediction.
