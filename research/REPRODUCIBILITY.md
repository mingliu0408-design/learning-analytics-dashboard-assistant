# Reproduction map for v1.0.0

The input level is part of each result. The default command runs only saved-data arithmetic. It does not train, encode with a model, call P3/LLM providers, regenerate answers or add ratings. All paths are relative to this repository or explicit output/resource arguments.

| Dissertation scope | Starting data | Entrypoint | New output under `outputs/reproduction/` | Boundary |
| --- | --- | --- | --- | --- |
| RQ1, Chapter 4 ranking results / Appendix A | `data/reproduction/rq1/counts.json`: frozen rank counts and confusion matrices | `reproduce/rq1.py` | `rq1/metrics.json` | Marginal metrics for K0, C0 and five M64 seeds; per-record and paired tests unavailable |
| RQ2, Chapter 4 frozen TEST / Appendix A-B | `data/reproduction/rq2/`: anonymous 36-case Gold and 11 complete prediction methods | `reproduce/rq2.py` with original metric functions | `rq2/metrics.json` | Core32 and complete36; retains four CLARIFY cases without invented capability Gold; includes diagnostic/ineligible methods without making them eligible |
| R7, W8 Table 4.4 and serializer supplement | `data/reproduction/r7/`: saved original/test-labelled/compact predictions and numeric sidecars | `reproduce/r7.py` with frozen `analyze.py` | `r7/METRICS_ALL.json`, `CHANGE_SUMMARY.json`, `ALL_METRIC_DELTAS.json` and complete case/bit tables | Recalculates representation comparison; encoding and training not run |
| RQ3 Chapter 4 and Appendix E descriptive results | `data/reproduction/rq3/SCORE_COMPONENTS.csv`: 1,968 anonymous criterion positions, two fixed raters | `reproduce/s7.py` | `s7/ANSWER_MEANS_RECONSTRUCTED.csv`, `MODE_MEANS_REPRODUCED.csv`, all unit differences | Scores/NA and frozen applicability are inputs; no validation of how ratings were produced |
| S7, W8 exploratory supplement | Reconstructed original17 question units and new12 A/B family units plus `EXPLORATORY_SPEC.json` | `reproduce/s7.py` | All 15 new-stratum contrasts, 15 original descriptive contrasts, 29 deletions, fixed-rater summaries and bootstrap arrays | Exact original specification; all negatives and NA retained; post-hoc conditional interpretation |
| RQ3 actual module contracts | Explicit synthetic fixtures and temporary stores | `checks/check_rq3.py` | Console receipt | L2 software tests, not the 246 historical answers or educational effectiveness |

## Environment and validation

The release preparation used an isolated CPython 3.12.14 environment with only NumPy 2.3.5 added for numerical reproduction. Python and NumPy versions are recorded by each main run. Dependency acquisition requires network access; analysis is separately guarded offline. No model files or source-workspace Python paths are used by this command.

The README commands are the primary recipe. After setting up its virtual environment, these bounded numerical/schema fixtures can also be run:

```sh
.venv/bin/python -m unittest discover -s checks -p 'test_*.py' -v
```

Do not use Python's `-O` option: the frozen source uses assertions to enforce its contracts. Missing required files, identity mismatches, invalid NA or mismatching frozen results cause failure rather than a manufactured PASS. Generated outputs, virtual environments, caches and databases are ignored by Git.

`checks/check_snapshot.py` checks every file listed in `metadata/PUBLIC_FILE_MANIFEST.json`; that manifest excludes itself to avoid a recursive self-hash. The release ZIP and remote Git commit have separate hashes in the release receipt. This proves file integrity, not data authenticity or scientific validity.

Release preparation verifies the saved-material and synthetic commands locally before push. The final external release receipt records the subsequent independent GitHub clone, exact tag checkout, actual command results, remote commit and downloaded public-asset hashes. A local run is not treated as that remote verification.

## Full rerun interfaces and missing prerequisites

The `src/*_original` trees contain the actual research code and necessary import closure, with source/version maps and recorded path adaptations. The historical training, models and service workflows are optional. See `docs/RQ1_RQ2.md`, `docs/RQ3_IMPLEMENTATION.md` and `docs/RQ3_STATISTICS.md` for exact resources, actual prompts and schemas, frozen configuration and historical-version qualifications.

RQ1 needs the historical data, index and trained heads to regenerate per-record ranks. RQ2 model inference needs the frozen encoder/heads and authorized contextual inputs; full router runs also need the appropriate API configuration. RQ3 full generation needs the authorized dashboard inputs, course corpus, persistent-history state and providers. These resources are not supplied as synthetic substitutes. The wrapper `python -m reproduce.r7_infer --help` documents the fixed-model serializer inference interface and requires explicit opt-in before encoding. Its help and rejection path were tested; inference was not executed.

The release makes no guarantee of byte-identical future provider responses. Historical selected answers came from recorded execution stages; the exported source version is not asserted to have generated every prior answer. See the RQ3 historical provenance notes. H9/D9 active work is excluded; later delivered supplements need a new version.
