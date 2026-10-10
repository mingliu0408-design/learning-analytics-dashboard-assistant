# G0-R1 original code recovery identity

[The machine-readable manifest](../research/metadata/g0_r1_code_recovery.json) records original Git blob IDs, SHA-256 hashes, published SHA-256 hashes, sizes, categories and every recorded transformation. Its source commit is `fdd9848b2a92b5f50675d193a4765e02dfa9ebb8`; source labels and paths are project-relative, with no author filesystem paths.

The integrated `research/src/rq3_original` tree contains **1,557 files matched to original Git objects**: 1,554 selected code/resource paths plus the original `Home.py`, original `requirements.txt` and the clarification-gate configuration. **1,548 remain byte-identical; 9 have documented public path/configuration changes or credential redaction.** The complete 1,554-path selection has no missing paths. Verification found and recovered the original Unicode-named `pages/1 - 👨🏼‍💻 Individual Feedback.py`, which the initial 1,553-path extraction had missed. Its exact Git bytes passed the publication scanner and Python AST parsing. The new `public_core_worker.py` is separately labelled as a G0-R1 adapter, rather than attributed to original research.

The nine original-file changes are limited to:

- `utils/course_material_retriever.py`: defer the private course-metadata import to its optional legacy loader; preserve the supplied-corpus scorer.
- `utils/c4_rag/corpus.py`: use relative/configured course and model resources; replace the author Anaconda `sys.path` injection with normal optional dependency installation.
- `utils/c4_rebuild/i1/native_backend.py`: select the model subprocess interpreter and pinned model directory from explicit configuration or portable defaults; preserve worker protocol, revision and model hash checks.
- `evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_full_dev_prompt_package_v1.json`: replace author-specific model/config path metadata; retain prompt content and few-shot examples.
- `evaluation/rq3_real_c4/i0_integration/build_r1_route_packages.py`: use a relative historical archive directory and bind the public prompt-package byte hash.
- `evaluation/rq3_real_c4/j2d1_applicability_provenance_audit/build_j2d1_artifacts.py`: remove the authentication-related HMAC field value. The redacted public field does not establish an original administrative authentication check.
- `experiments/rq3_original25_plus_review_r1/confirmed41_memory_isolation_continuation_2026-09-08/checkpoints.py`, `research_followups/rq3_rebuild/i5_typed_action_planner/i5_common.py` and `research_followups/rq3_rebuild/a_reuse62_replay_v2/replay_common.py`: replace author-specific historical packet/archive/output or dashboard paths with project-relative locations.

The original Streamlit Home and Individual Feedback sources are retained for inspection. The deployed entrypoint is `app.py`; its five public pages use the restored scoped data and original research components through the session adapter. Original author Firebase login/logging paths are not called by that entrypoint.

## RQ1/RQ2 source mapping

The manifest also verifies the separate `rq1_original` and `rq2_original` copies against their actual original bytes. All 39 RQ1 files originate from the identified Git commit and have an integrated RQ3 counterpart. Of the 71 RQ2 files, 62 originate from that Git commit and 9 originate from the exact named R7 archive, whose whole-archive hash and member hashes were re-read. Public copies include explicitly documented path adapters; they are not silently treated as byte-identical.

Five RQ2 mapping/model JSON files are present in `rq2_original` without an integrated relative-path copy: B1 mapping, B2 and B3 models, and P2/P3 specialist-composition models. The 9 R7 archive sources are also retained in `rq2_original/r7`; where their original content matches another integrated file, that identity is recorded separately from relative-path presence. No absent integrated copy is fabricated.

这些记录区分原始代码、公开移植副本与本轮新适配器。原Git对象和研究目录未改动，Gold、历史回答与论文统计未重跑或改写。文件身份核验证明恢复字节及其去向；训练复现条件、付费实时调用和线上运行状态由各自验证记录单独说明。
