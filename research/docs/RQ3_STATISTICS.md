# RQ3 saved-score aggregation and S7 exploratory supplement

The offline calculation starts at the released anonymous criterion scores in
`data/reproduction/rq3/SCORE_COMPONENTS.csv`. This is a numerical projection of
saved scores, not raw student data, response text, a new rating round, or a
verification of the rating process. The two fixed anonymous rating columns are
`Rater1_score` and `Rater2_score`.

Run from the repository root after installing `requirements-reproduce.txt` in an
isolated environment:

```sh
python -m reproduce.s7 --output outputs/s7
python -m unittest checks.test_s7_fixtures checks.test_rubric_validation -v
```

The historical S7 runtime used Python 3.12.14 and NumPy 2.3.5. The reproducibility
requirements pin NumPy 2.3.5. The program uses no model, network, API key, private
absolute path, or original database. Do not run Python with `-O`: the frozen
implementation uses assertions to enforce its input and analysis contract.

## Released numerical level and fixed aggregation

There are 41 task identities, six modes, eight criterion positions per answer,
and two fixed rating columns. The file contains 1,968 rows: 1,248 numeric scores
and 720 fixed `NA` positions per rater. There are 208 applicable and 120
inapplicable task-criterion combinations before repeating the mask across modes.
All tasks, A/B conditions, zero differences, and negative differences remain.
Multi-page Cohesiveness is fixed `NA` throughout; it has no score denominator.
Blank values are never interpreted as zero or silently omitted.

The original code performs exact arithmetic with `fractions.Fraction`. It first
averages applicable criteria within an answer for each rater, then the two rater
means equally. The original stratum has 17 question units. The new stratum has 12
families, each formed by equally averaging its two A/B task-condition means.
It does not pool all criterion positions into one denominator. The two strata
remain separate: neither 41 tasks nor 246 answers is a count of independent
students.

The program reconstructs 246 answer means, 174 unit-mode means, 12 stratum-mode
means, 24 focus-mode means, and 435 unit differences. Values in
`results/reference/s7/inputs/` only check that reconstruction agrees with the
frozen tables. Arithmetic proceeds from the reconstructed criterion scores.
The saved source rater headers were relabelled neutrally; values are unchanged.

## Frozen S7 procedure

`data/reproduction/s7/EXPLORATORY_SPEC.json` is the byte-identical saved S7-R1
specification. Its status is
`POST_HOC_EXPLORATORY_CONDITIONAL_SUPPLEMENT`: descriptive results had already
been seen. The supplementary freeze is not historical preregistration.

- Bootstrap: 50,000 stratified paired whole-family resamples, seed `20260908`,
  `numpy.random.default_rng`, one int64 index array of shape `(50000, 4, 3)`.
  The order is E/R/M/P, with families 01/02/03 within each focus. The same indices
  carry all six modes. Each focus keeps weight one quarter. Integer common
  denominators precede float conversion. The 2.5th and 97.5th percentiles use
  NumPy's `linear` quantile method.
- Sign flips: all 4,096 signs of the same 12 paired family differences, a
  two-sided absolute mean statistic, exact rational extreme comparisons.
- Multiplicity: Holm adjustment across all 15 new-stratum mode contrasts at
  alpha 0.05, with no selected subset or changed family.
- Influence: 12 new-family deletions retain equal one-quarter focus weights by
  renormalizing within the affected focus; 17 original-question deletions use
  equal weights over the remaining 16 questions.
- Raters: four stratum-by-rater S5-minus-S0 summaries are descriptive; neither
  rater is resampled and there is no inference over a rater population.

No other tests, thresholds, scores, exclusions, agreement coefficients or
calibrations are introduced.

## Outputs and comparison

| Output | Computation |
|---|---|
| `ANSWER_MEANS_RECONSTRUCTED.csv` | Applicable-criterion and fixed-rater means for all 246 answers |
| `MODE_MEANS_REPRODUCED.csv` | Separate original17 and new12-family mode means |
| `ALL_UNIT_DELTAS_EXACT.csv` | All 435 exact unit-level differences, including 179 zeros and 116 negatives |
| `ALL_15_NEW_CONTRASTS.csv` | Full fixed bootstrap, sign-flip and Holm table |
| `ALL_15_ORIGINAL_DESCRIPTIVE_CONTRASTS.csv` | All original-stratum descriptive contrasts |
| `S5_S0_LEAVE_ONE_OUT.csv` | All 29 fixed deletion values |
| `RATER_S5_S0_DESCRIPTIVE.csv` | Fixed-rater descriptive directions |
| `BOOTSTRAP_INDICES.npy`, `BOOTSTRAP_CONTRAST_DISTRIBUTION.npy` | Recomputed bootstrap arrays |
| `COMPUTATION_RECEIPT.json` | Input/design counts, software versions and output-hash verification |

The seven deterministic CSV files and both NumPy arrays are checked byte for
byte by SHA-256 against the original frozen S7 outputs. Reference CSVs are
included for inspection. The large reference arrays are represented by their
original hashes and are regenerated, not copied into outputs. Receipt timestamps
and implementation hash necessarily describe the new run rather than the old
one. Source file hashes and publication adaptations are recorded in
`metadata/source_map_s7.json`.

The original17 S5-minus-S0 mean is exactly `271/4760`; the new-family mean is
exactly `977/1440`. For the latter, the conditional bootstrap interval is
`[0.3111111111111111, 1.0364087301587301]`, the sign-flip fraction is `1/64`, and
its 15-test Holm-adjusted fraction is `15/64`. These are verification targets;
they are not used to manufacture output values. All 15 adjusted results and all
negative family differences remain in the output.

## Interpretation and withheld inputs

The bootstrap interval describes conditional resampling stability for these
fixed constructed families and fixed ratings. Three observed families per focus
provide no guaranteed nominal or simultaneous coverage. The exact sign-flip
reference requires joint invariance under independent sign flips, an assumption
not established by these purposively constructed observations. Enumerating 4,096
configurations removes Monte Carlo error, not assumption uncertainty. Holm's
conditional error control requires valid component p values and does not correct
historical post hoc selection.

The 29 deletion values describe deterministic influence. These calculations do
not establish effects for real students, learning gains, natural demand
prevalence, isolated module causality, or synergy. The original and new strata
differ in their design and must not be pooled to enlarge the apparent sample.
Identical response strings never merge task-condition identities.

Original response text, course documents, learner histories, private mappings,
rater declarations, and signatures are withheld. Their absence prevents a public
reader from independently re-rating the responses or fully regenerating the
historical answers. Recalculation of the released numerical records is complete;
regeneration and new human evaluation are separate activities requiring those
inputs and appropriate permissions. No H9/D9 active output was read or included.
The rubric folder preserves the actual local Chinese anchors and validator code;
it does not claim that a later English translation was the historical instrument.
