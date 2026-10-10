# Project and research material map

The runtime entrypoint is `app.py`. The public repository keeps code and the small datasets needed for no-key playback and real local component demonstrations. The full research archive is a separate GitHub Release asset; its exact identity is in `data/manifest.json`. Only an uploaded and anonymously downloaded asset establishes public availability.

| Material | Actual destination | Recovered source and boundary |
|---|---|---|
| Original Streamlit UI and complete Evidence/P3/R0/M1/Planner/FINAL | `research/src/rq3_original/` | Final implementation Git `fdd9848`; public application adapter preserves worker isolation |
| Original learner logs, aggregated metrics and course originals | `data/dashboard/` | 46 anonymous learner join IDs retained; display names replaced consistently; HTML authentication/scripts/contact text removed |
| 624-chunk actual R0 course corpus | `data/course/corpus.jsonl` | Frozen generic course corpus; no Gold or rating references |
| 41 tasks, 246 mode identities, 179 unique answer texts | `data/replay/` | Actual accepted historical answers; replay never claims new generation |
| All49 runtime roster and eight unrun originals | `data/replay/runtime_tasks.jsonl` | `final_tasks.jsonl` contains41 selected task IDs; unrun tasks have no invented answers |
| Actual page snapshots, eight history/Memory operation sources | `data/replay/source_materials/` | Source labels replace author absolute paths |
| Original native Memory seeds and graph/source events | `data/replay/native_initial/{task_id}/` |49 read-only original seed DBs; visitor writes use an independent session copy |
| RQ1 final128 actual query/Gold | `research/data/evaluation/rq1/final128_query_gold.csv` |128 rows verified against frozen hash/size; evaluation only, never runtime input |
| RQ3 Gold/reference | `research/data/evaluation/rq3/evaluation_reference.jsonl` |Evaluation only; never passed to generation or RAG |
| Anonymous actual ratings, 40 H9 anchors, S7/R7/D9 analyses | Release `studies/ratings`, `h9`, `s7`, `r7`, `d9` | Original frozen values and methods preserved; identity attachments excluded |
| Latest W9 thesis and final supplement | Release `studies/thesis_w9`, `supplement_w9` | Actual W9 Git HEAD955fa3; no论文 or result rewriting |
| Legacy62x9, DEV inputs/results, failure/unknown records | Release `historical_tracked/` |Original source-relative tree makes historical versions explicit |
| Small trained heads and known embedding arrays | Release `historical_tracked/`, `local_model_resources/` |No full dependency/model cache; MPNet identity remains separately pinned |
|183 inherited module checkpoints |Not found in authorised sources |No fabricated historical execution chain |
|Eight unknown attempt completions |Unknown |No reconstruction from means or later answers |
|Secrets, signed identity paperwork, fonts, `.git`, environments |Excluded |Not needed for public research execution |

`data/manifest.json` lists every public runtime file's original and publication SHA-256, length and transformation. The larger archive includes `PUBLIC_FILE_MANIFEST.json` for every archive member except its own manifest. Private recovery indexes, source paths and internal audit files remain outside the repository. No new blanket MIT/CC0 licence is assigned.

Full RQ1 training/inference/threshold/history sources: `research/src/rq3_original/evaluation/learned_intent_ranking/`. Full RQ2 sources: `research/src/rq3_original/evaluation/capability_routing_rq2_v2_stage4/` plus adjacent stage0/stage1/stage5 trees. The narrower `rq1_original/` and `rq2_original/` copies retain their earlier snapshot identity; all recovered code origins and transformations are enumerated in `research/metadata/g0_r1_code_recovery.json`. The 1554-file selected source recovery is complete, including the original Unicode Individual Feedback page.
