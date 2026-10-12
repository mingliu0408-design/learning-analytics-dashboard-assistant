# Verified Streamlit Community Cloud deployment · 2026-10-12

[Open the actual application](https://learning-analytics-dashboard-assistant-ekqehs9bochsxp3xlmfmdn.streamlit.app/). Repository: `mingliu0408-design/learning-analytics-dashboard-assistant`; branch: `main`; entrypoint: `app.py`; saved Python version: `3.13`. The version was selected in the real dropdown, saved and reopened before Deploy. No author API key or Secrets were configured.

The deployed runtime is the unchanged tested Supervisor core from commit `00f471cec61e4574c9e835d580355710d5157201`. The follow-up documentation commit records the verified URL and does not change the runtime or research inputs.

## Actual online checks

- Introduction / Overview: six navigation controls and actual learner activity metrics rendered.
- Resources: original Moodle lines and heatmap; learner-001 has 155 source events in the displayed window.
- Lecture: original cumulative Panopto bars; nine saved lecture rows, three with positive view counts for learner-001.
- Debate: directed `streamlit_agraph` component rendered with Replying/Viewing controls; eight posts, 13 outgoing replies and 65 outgoing views for the selected window.
- Reflection: actual character-edit and cohort curves; the displayed learner has zero recorded edits; generation coverage remains separate from chart zero.
- Next Steps: original reflection form and editable plan table rendered; no automatic Memory write.
- REPLAY: saved original-01/S0 displayed with `SAVED_HISTORICAL_ANSWER_NO_NEW_MODEL_CALL` identity.
- COMPONENTS: actual original R0 plus complete isolated native M1 LEXICAL execution with a public test question. `rag_calls=1`, `memory_calls=1`, `readonly_state_unchanged=true`, `NO_LLM_NO_NATURAL_ANSWER_GENERATION`.

The cloud browser check used the owner account. Independent HTTP validation started with a fresh empty in-memory cookie jar and no account credentials, Authorization header or browser cookies. The platform's anonymous 303 bootstrap issued five site cookies and reached the app with HTTP 200. The actual application endpoint `/~/+/_stcore/health` returned `200 / ok`. The outer `/_stcore/health` returns wrapper HTML and is not treated as health confirmation. Anonymous cookie or redirect token values were not recorded in publication evidence.

Machine-readable public UI evidence: [cloud_validation_2026-10-12.json](deployment/cloud_validation_2026-10-12.json). The detailed redirect receipt remains in the private author audit directory with token parameters redacted.

## Scope and limits

Paid provider calls: zero. Historical answers, ratings, papers and statistics were not regenerated or modified. Dashboard writable Memory begins empty per visitor and learner; Community Cloud storage is temporary. Public course/replay seeds remain read-only; evaluation Gold is excluded from generation and RAG.

Default Cloud dependencies omit the optional pinned MPNet resources. Native LEXICAL components were actually tested online; complete MPNet/Hybrid was actually tested locally. Visitor-key LIVE wiring was verified with exact mocks and localhost HTTP tests; cloud paid inference and full cloud Hybrid are not claimed. The original P1 does not reconstruct arbitrary adopted text plans into its full typed active-plan structure.

## 中文说明

上方是已经实际运行并验证的在线地址。六页、历史回放、原R0和完整隔离M1词法组件均已在线执行。匿名访问与实际应用健康检查独立验证通过。没有填写作者key、调用付费模型、重跑论文回答或改动研究统计。云端完整Hybrid需要额外模型及依赖，当前尚未配置；本地已有真实MPNet/Hybrid实测。
