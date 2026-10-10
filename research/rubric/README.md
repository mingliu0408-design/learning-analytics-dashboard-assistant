# Frozen rating instrument components

`LOCAL_OPERATIONAL_ANCHORS.json` preserves the actual eight criterion names,
1–5 scale, Chinese explanations, and forty Chinese local operational anchors
from the frozen final246 rating packet. The local operationalization and pending
calibration labels are retained. These are the historical local anchors, not a
newly translated or validated scale.

The criterion framework is attributed to Yildiz Uzun, Andrea Gauthier and Mutlu
Cukurova, *What Students Ask, How a Generative AI Assistant Responds: Exploring
Higher Education Students’ Dialogues on Learning Analytics Feedback*, supplied
accepted manuscript, page 7, Table 1. The original packet's third-party English
criterion-description transcriptions are omitted because redistribution
permission was not supplied. Citation metadata is retained; no rights in that
paper or its text are granted by this release. See `LICENSING.md` and
`THIRD_PARTY_NOTICES.md`.

`FIXED_APPLICABILITY_41.json` is an exact projection of the anonymous numerical
score file: 208 true and 120 false task-criterion positions, with the same mask
in all modes. It contains no original task content, learner mapping, or private
rationale. Multi-page Cohesiveness remains false for all 41 tasks.

`rating_validation.py` exports the actual frozen H0 CSV reader, schema checker,
and rating validator, with only the resource root adapted. Its dependency is
Python's standard library. `schemas/ratings.schema.json` is the original schema.
The validator rejects missing complete scores, applicable `NA`, non-`NA` for
inapplicable criteria, and unresolved applicability disputes. It never generates
scores. The schema includes field names for supplied records; no actual identity,
signature, declaration, or textual rating record is distributed.

`checks/test_rubric_validation.py` uses clearly synthetic validation records.
Those integers are software fixtures, not new study scores or an original
experiment. The saved-score aggregation lives in `reproduce/s7.py` and starts
from the permitted anonymous criterion table. No H9/D9 material is included.
