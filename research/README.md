# LAD Assistant: dissertation reproducibility

Code snapshot for *Capability Routing and Downstream Utility in a Modular Learning Analytics Dashboard Assistant*.

The repository covers RQ1 intent ranking, RQ2 capability routing, and RQ3 evidence, retrieval, persistent memory and planning. It includes the actual research implementations, prompts and schemas, selected saved numerical inputs, and the S7/R7 analysis code. It does not contain the original student records, private conversations, course corpus or model weights.

## Run the saved-material recomputation

Use Python 3.12 and an isolated environment. Dependency installation needs a package index; the analysis itself is offline and needs no API key.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-reproduce.txt
.venv/bin/python scripts/reproduce_all.py --offline --output outputs/reproduction
.venv/bin/python checks/check_snapshot.py
.venv/bin/python checks/check_rq3.py
```

The main command reconstructs results from the supplied numerical inputs and validates them against frozen reference values. It denies socket connections and DNS lookup within its Python process. It writes new outputs and a run receipt under `outputs/reproduction`; reference results are comparison oracles, not the output source.

## What is reproduced

| Level | Included and bounded coverage |
| --- | --- |
| L1: saved-material results | RQ1 metrics from rank counts and confusion matrices; RQ2 original core32/full36 routing metrics and R7 serializer sensitivity from saved predictions/Gold; RQ3 aggregation from anonymous numerical scores and the exact S7 exploratory supplement. |
| L2: synthetic module checks | Offline execution of the exported RQ3 module contracts using explicitly synthetic inputs and temporary stores. These are not the original experiment. |
| L3: full rerun | Actual implementation and configuration sources, input interfaces and missing-resource instructions. Training, fixed-model inference, generation, P3 and Judge/API calls were not executed for this release. |

RQ1 per-record rankings are not included, so its paired significance tests cannot be reconstructed from these aggregate counts. RQ2 selection used the same TEST evaluation; R7 does not turn it into independent validation. RQ3 retains the original17 questions and new12 families separately, all negative families, two fixed raters and one selected answer per condition. S7 is post-hoc and conditional: none of its 15 comparisons passes Holm 0.05. Numerical recomputation does not recreate or validate human judgment or establish student learning benefits.

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for inputs, outputs and coverage; [DATA_AVAILABILITY.md](DATA_AVAILABILITY.md) for data layers; and [docs/](docs/) for component details. Exact source identities and adaptation records are in [metadata/](metadata/). Historical source commits identify local research snapshots and are not claimed to be public GitHub commits.

## Cite the fixed version

Use [v1.0.0](https://github.com/mingliu0408-design/lad-assistant-reproducibility/releases/tag/v1.0.0), [CITATION.cff](CITATION.cff) and the release commit. This version identifies a code snapshot with the stated data limits. Subsequent supplements require a new version; the cited tag will not be moved.

Public visibility does not grant a new blanket licence. See [LICENSING.md](LICENSING.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The complete dissertation and local review archives are excluded.
