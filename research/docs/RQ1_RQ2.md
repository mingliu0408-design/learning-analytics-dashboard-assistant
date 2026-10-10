# RQ1, RQ2 and serializer-sensitivity reproduction

This snapshot contains the original research algorithms, with a separate lightweight saved-result path. `metadata/source_map_rq1_rq2.json` records the source commit or frozen ZIP member and the source/release SHA-256 of each extracted file. These historical commits identify local source history; they are not claimed to be public GitHub commits. Private directory prefixes were replaced by `external_inputs/`; algorithm bodies and frozen thresholds were retained. The original `.git` history was not copied.

## Tested saved-material calculations (L1)

The shared command `python scripts/reproduce_all.py --offline --output outputs/reproduction` invokes the following three modules. No encoder, training routine or API client is imported by these calculations.

| Component | Released input | Calculation and checks | Output |
|---|---|---|---|
| RQ1 | `data/reproduction/rq1/counts.json`: 16-label confusion matrices and Gold-rank histograms for 128 cases, K0/C0 and five M64 seeds | MRR, top-1 accuracy, Recall@3, fixed-16 macro-F1, mean Gold rank and top-1 count; all targets checked within 1e-14 | `rq1/metrics.json` |
| RQ2 | `data/reproduction/rq2/evaluation_sidecar.jsonl` and `complete_predictions.jsonl`: 36 anonymous cases, frozen action/Gold and all 11 complete methods | Original `metrics.py` computes full metric objects for 32 ANSWER cases and all 36 cases, including family/contrast and anonymous source-label strata | `rq2/metrics.json` |
| R7 | `data/reproduction/r7/`: all 36 saved B2/B3 predictions for each representation and frozen B0/B4 terminal bits | Original analysis recomposes P1, computes core32/full36 metrics and all case, bit and scalar changes | `r7/METRICS_ALL.json`, `CHANGE_SUMMARY.json`, `CASE_COMPARISON.jsonl`, `BIT_COMPARISON.jsonl`, `ALL_METRIC_DELTAS.json` |

RQ1 starts from **aggregate sufficient counts**, not a released per-record ranking/Gold ledger. Its main metrics are recomputed by weighted sums and confusion-matrix arithmetic, not copied from target means. The resulting C0 MRR is 0.5353797461219336 and representative M64 (seed 20260815) MRR is 0.3942398096694972. The five-seed results and the negative representative comparison remain intact. The count inputs cannot recover per-record pairing: this release does **not** recompute RQ1 paired bootstrap/randomisation, reconstruct individual rankings, or establish the original Gold assignments. Per-record historical prediction ledgers were not present in the supplied frozen archives or the bound Git tree; ignored source-workspace outputs were not read. The original individual-ranking metric and statistical code remains available for appropriately supplied inputs.

RQ2 retains four CLARIFY cases with null capability Gold. Their latent method bits are retained but never scored against fabricated capability Gold. The ANSWER subset contains 16 complete two-utterance families. `writer_id` values A/B are existing anonymous stimulus-source categories needed for the frozen metric strata; no identity mapping or personal declaration is included. Eleven methods include the diagnostic always/never-on baselines and exploratory P4, as well as B0–B4 and P1–P3. P3 core macro-F1 recomputes to 0.9310754604872252. The result is a frozen-prediction evaluation, not a new model run or an investigation of scoring provenance.

R7 uses the original labelled TEST representation and the compact DEV JSON representation. The labelled replay matches the original B2/B3 scores and all compared metrics exactly. Compact representation changes six B2 case signatures, four B3 signatures and zero P1 signatures. B2 retains the four worsened cases, and P1 fallback count changes from 35 to 36. No new statistical test is added. Every computed metric/change object is compared against separate files in `results/reference/`; reference files are comparison oracles, never substitutes for calculation inputs.

## Actual source and prompt coverage

`src/rq1_original/` preserves the original Python layout and import dependencies for:

- C0 cosine example ranking, label-wise maximum aggregation and deterministic tie behavior in `evaluation/learned_intent_ranking/lr3/evaluate_ranker.py`, with the real semantic/production routers in `utils/`.
- M64 feature construction (absolute difference plus elementwise product), 1536-dimensional input, LayerNorm → Linear(64) → ReLU → dropout(0.5) → Linear(1), 101,505 trainable parameters, and original deterministic head training in `lr3r/compact_train.py` plus governed `lr4b_dev/train_m64.py`.
- Pair construction, representation/token-budget rules, data/checkpoint loaders, final fixed-16 scoring, and the frozen statistical decision contract. Original source guards on protected study assets are retained, not bypassed to make a missing-data study rerun appear successful.

`src/rq2_original/` preserves B0 rule routing, the B1 real intent adapter, B2 prototype and B3 one-vs-rest implementations, the effective frozen `track_h.py` fitting/inference functions, the two serializers, B4 response parsing, P1 policy, the Clarification Gate, specialist contracts, and pure P1/P2/P3/P4 composition. Frozen B2/B3 authored numeric heads and thresholds are included. The third-party MPNet encoder weights are excluded.

Actual final DEV-selected B4/RAG/Memory prompt packages, their few-shot examples and output schemas are in the original `evaluation/capability_routing_rq2_v2_stage4/` subtrees. Their examples are controlled synthetic development stimuli and are not presented as student records. Stage1 B4 files are clearly an earlier mock-only harness; historical final B4 used the Stage4 frozen full-DEV package. The final B4 configuration records `gpt-4o-mini-2024-07-18`, temperature 0 and 64 maximum output tokens. See `prompts/rq2/README.md` for paths. No newer prompt is claimed to have generated older predictions.

## Synthetic contract checks (L2)

`python -m unittest checks.test_rq1_rq2 -v` runs seven tests: all saved calculations; inconsistent count rejection; the intact family and CLARIFY/NA boundary; preservation of R7 negative changes; the original serializers' exclusion of top-level Gold; and refusal to encode without explicit opt-in. The serializer fixture is created within the test and is explicitly synthetic. These tests do not regenerate the original experimental queries or predictions.

## Full encoder/training/service runs (L3; not executed)

The optional command interface is `python -m reproduce.r7_infer --help` (tested). Actual inference requires `--encode-once --inputs PATH --encoder PATH --output NEW_DIRECTORY`. It loads exact frozen serializer/head function ASTs and checks three pinned encoder file hashes. It permits exactly 36 supplied semantic cases and two representation passes; existing output directories are refused. It uses local-only MPNet, CPU, batch size 16, normalized float32 embeddings, dimension 768 and the historical R7 maximum sequence length 384. It never loads Gold, trains or retunes a threshold. No encoder pass was executed for this release.

The external input JSONL schema is `configs/schemas/r7_semantic_input.schema.json`: one anonymous case ID plus the four runtime fields only. Original TEST text is withheld, so this interface cannot reconstruct those texts from the public numerical sidecar. Applying it to new/synthetic text is a new input experiment and must not be labelled the original study.

The encoder is `sentence-transformers/all-mpnet-base-v2`, revision `e8c3b32edf5434bc2275fc9bab85f82640a19130`. Obtain it separately under its upstream licence, and retain its notices. The frozen historical R7 runtime versions are recorded in `configs/r7_encoder_runtime.json` (NumPy 2.1.1, Torch 2.12.1, Transformers 5.15.0, sentence-transformers 5.6.1, tokenizers 0.22.2, scikit-learn 1.9.0). These are historical observations, not dependencies installed by the default command. New platform/library versions can change numerical results.

RQ1 full inference additionally needs the frozen 62-example candidate index/embeddings, 16-label taxonomy binding, the external query/Gold inputs, the original five M64 checkpoints and their manifests. Training additionally needs the governed train/DEV representation and pair manifests. None of those absent assets is replaced with a fabricated dataset. The preserved RQ1 orchestration contains original study-state/hash gates and is not advertised as a portable ready-to-run study CLI. The algorithm functions and input schemas are inspectable and reusable with separately governed inputs; the release only claims tested L1/L2 execution.

The optional source dependency families are NumPy, Torch, sentence-transformers, Transformers, scikit-learn, pandas and jsonschema. They are not installed or imported merely to run the standard-library RQ1/RQ2/R7 saved calculations. L2's serializer test uses NumPy from the lightweight reproduction environment. Full service runs need the original runtime contexts, provider credentials and model snapshot, and can incur costs; they are outside this release execution. Nothing here reruns P3 or an LLM Judge, adds human scores, trains a model, deploys a service or changes the dissertation.
