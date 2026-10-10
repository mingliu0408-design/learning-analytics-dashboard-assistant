"""Write thesis reports by transcribing frozen aggregate F0/F1 results only.

This script has no condition-level input, Human mode join, score calibration,
Provider client, module execution, or external citation retrieval.
"""
from __future__ import annotations

from collections import Counter
import json

from f1_common import *
from f1_controlled_unblinding_guard import verify_entry
from f1_entry_binding import ENTRY_RECEIPT_SHA256

MODE_SHORT = ["C0", "C1", "C2", "C3", "C4", "C5", "C5 − RAG", "C5 − Memory", "C5 − Planning"]
CONTRAST_SHORT = ["C1 − C0", "C2 − C1", "C3 − C1", "C4 − C1", "C5 − C1",
                  "C5 − (C5 − RAG)", "C5 − (C5 − Memory)", "C5 − (C5 − Planning)"]
CRITERION_NAMES = ["Clarity", "Personalisation", "Actionability", "Context Awareness",
                   "Motivation and Engagement", "Reliability", "Multi-page Cohesiveness", "Error Handling"]
OUTCOME_NAMES = dict(zip(SECONDARY, CRITERION_NAMES + ["Evidence Faithfulness", "Unsupported Claim Count"]))


def fmt(value, places=4):
    return "NA" if value is None else f"{value:.{places}f}"


def table(headers, rows):
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join(
        "| " + " | ".join(str(x).replace("|", "\\|") for x in row) + " |" for row in rows) + "\n"


def wtl(row):
    return f'{row["wins"]}/{row["ties"]}/{row["losses"]}'


def interval(row, key="bootstrap"):
    return f'[{fmt(row[key]["ci_low"])}, {fmt(row[key]["ci_high"])}]'


def measurement_outputs():
    hh_path = F0 / "c4_real_blinded_human_human_agreement_v1.json"
    hl_path = F0 / "c4_real_blinded_human_llm_agreement_v1.json"
    hh, hl = read_json(hh_path), read_json(hl_path)
    pooled = hl["pooled_human_observations_vs_llm_judge"]
    bias_rows = []
    for criterion, display in zip(CRITERIA, CRITERION_NAMES):
        key = criterion.lower()
        a = hl["human_a_vs_llm_judge"]["per_criterion"][key]
        b = hl["human_b_vs_llm_judge"]["per_criterion"][key]
        p = pooled["per_criterion"][key]
        bias_rows.append({"criterion": criterion, "display": display,
            "human_a_pair_count": a["n"], "human_b_pair_count": b["n"], "pooled_pair_count": p["n"],
            "judge_minus_human_a": a["criterion_level_bias_source_b_minus_source_a"],
            "judge_minus_human_b": b["criterion_level_bias_source_b_minus_source_a"],
            "pooled_judge_minus_human": p["criterion_level_bias_source_b_minus_source_a"]})
    metadata = {"schema_version": "F1_FROZEN_MEASUREMENT_SUMMARY_V1",
        "source_hashes": {str(x.relative_to(ROOT)): sha(x) for x in [hh_path, hl_path]},
        "operation": "EXACT_TRANSCRIPTION_OF_F0_AGGREGATES_NO_RECALCULATION",
        "unique_human_visible_items": hh["unique_items"], "human_raters": 2,
        "human_human_pooled": hh["pooled"], "human_llm_pooled": pooled["pooled"],
        "criterion_biases": bias_rows, "pooled_overall_bias": hl["not_computed"]["pooled_bias"],
        "human_mode_effects_computed": 0, "human_judge_score_averaging_operations": 0,
        "judge_calibration_operations": 0, "raw_ratings_or_rationales_copied": 0}
    write_json(HERE / "F1_FROZEN_MEASUREMENT_SUMMARY_V1.json", metadata)
    write_csv(HERE / "F1_FROZEN_CRITERION_JUDGE_MINUS_HUMAN_BIAS_V1.csv", bias_rows)
    bias_table = table(["Criterion", "Judge − A", "Judge − B", "Pooled Judge − Human", "Pooled n"], [
        [r["display"], repr(r["judge_minus_human_a"]), repr(r["judge_minus_human_b"]),
         repr(r["pooled_judge_minus_human"]), r["pooled_pair_count"]] for r in bias_rows])
    text = f"""# Measurement validation and interpretation

The frozen Human raters applied the rubric relatively consistently. The LLM Judge was systematically more generous and is not interchangeable with a Human rater. The primary F1 results therefore compare **LLM-Judge-rated response quality**, with caution about absolute score levels.

These are unchanged F0 aggregates for 44 unique Human-visible items rated by two Humans. The pooled denominators count applicable criterion-item observations, not independent students, independent scenarios, or mode-level treatment observations. Human–Human counts each jointly applicable criterion-item pair once. Human–LLM concatenates each Human–Judge pairing; it does not average the two Human scores or treat 552 observations as 552 independent items.

| Frozen comparison | Exact | Within one point | MAE | Quadratic weighted kappa | Spearman |
| --- | --- | --- | --- | --- | --- |
| Human–Human | 189/276 | 274/276 | NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED | 0.8542154167707932 | 0.8728525479786775 |
| Pooled Human–LLM | 186/552 | 421/552 | 0.9619565217391305 | 0.3616242748772869 | 0.4537074855476746 |

## Frozen criterion-level bias

Positive values mean that the Judge assigned a higher score than the named Human source. Values below are transcribed at frozen precision. They were calculated in F0 while mode identities remained closed; F1 has not recalculated, rescaled or used them to alter a score.

{bias_table}
The largest reported criterion biases concern Error Handling, Reliability, Context Awareness and Multi-page Cohesiveness. This limits substantive interpretations of high absolute Judge scores. Pairing may reduce stable Judge leniency; it does not establish that leniency is condition-invariant, and no assumption of such invariance has been empirically validated here. Criterion applicability and the selected 44-item validation sample also limit transfer of these agreement results to the complete 62-scenario experiment.

No Human-based treatment-effect estimate was predeclared. F1 computes no Human mode effects, no Human–Judge average outcome, no score correction, and no calibration. A pooled overall bias remains `NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED`; it is not inferred from the criterion table. Human agreement is measurement evidence, not a replacement primary endpoint or a Human validation of the eight treatment contrasts.

F0 Human–Human source SHA-256: `{sha(hh_path)}`. F0 Human–LLM source SHA-256: `{sha(hl_path)}`. Machine-readable transcription: `F1_FROZEN_MEASUREMENT_SUMMARY_V1.json` and `F1_FROZEN_CRITERION_JUDGE_MINUS_HUMAN_BIAS_V1.csv`.
"""
    write_once_bytes(HERE / "C4_REAL_F1_MEASUREMENT_VALIDATION_INTERPRETATION.md", text.encode())
    return metadata, bias_table


def report_inputs():
    names = ["MODE_SUMMARIES", "PRIMARY_CONTRAST_RESULTS", "SECONDARY_OUTCOME_RESULTS"]
    mode, primary, secondary = [read_json(HERE / f"C4_REAL_F1_{n}_V1.json")["records"] for n in names]
    cohorts = read_json(HERE / "C4_REAL_F1_FROZEN_COHORT_SENSITIVITY_V1.json")["cohorts"]
    strata = read_json(HERE / "C4_REAL_F1_MECHANISM_STRATIFIED_DESCRIPTIVES_V1.json")["strata"]
    mechanism = read_json(HERE / "C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json")
    mode_ids = read_json(HERE / "C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json")["mode_identities"]
    return mode, primary, secondary, cohorts, strata, mechanism, mode_ids


def primary_tables(mode, primary, mode_ids):
    lookup = {(r["mode_id"], r["outcome"]): r for r in mode}
    mode_rows = [lookup[(m, PRIMARY_OUTCOME)] for m in mode_ids]
    levels = table(["Mode", "Scenarios / families", "Mean", "Median", "SD (descriptive)", "Minimum", "Maximum"],
        [[short, "62 / 62", fmt(r["mean"]), fmt(r["median"]), fmt(r["standard_deviation_descriptive_only"]),
          fmt(r["minimum"]), fmt(r["maximum"])] for short, r in zip(MODE_SHORT, mode_rows)])
    effects = table(["Contrast (left − right)", "Mean Δ", "Median Δ", "95% bootstrap CI", "Raw sign-flip p", "Holm p"],
        [[short, fmt(r["paired_mean_difference"]), fmt(r["paired_median_difference"]), interval(r),
          fmt(r["raw_p_value"], 6), fmt(r["holm_adjusted_p_value"], 6)] for short, r in zip(CONTRAST_SHORT, primary)])
    robustness = table(["Contrast", "Wilcoxon p", "Nonzero families", "Paired dz", "Rank-biserial", "Wins / ties / losses"],
        [[short, fmt(r["wilcoxon_p_value"], 8), r["nonzero_family_count"], fmt(r["paired_dz"], 6),
          fmt(r["rank_biserial"], 6), wtl(r)] for short, r in zip(CONTRAST_SHORT, primary)])
    marginal = table(["Contrast", "Left mean", "Left median", "Right mean", "Right median", "Excluded cases / families"],
        [[short, fmt(r["left_mean"]), fmt(r["left_median"]), fmt(r["right_mean"]), fmt(r["right_median"]),
          f'{r["excluded_case_count"]} / {r["excluded_family_count"]}'] for short, r in zip(CONTRAST_SHORT, primary)])
    return levels, effects, robustness, marginal


def secondary_tables(secondary):
    return "\n".join("### " + OUTCOME_NAMES[outcome] + "\n\n" + table(
        ["Contrast", "Applicable n", "Left mean", "Right mean", "Mean Δ", "Median Δ", "W/T/L", "NA exclusions"],
        [[CONTRAST_SHORT[[x[0] for x in CONTRASTS].index(r["contrast_id"])], r["applicable_pair_count"],
          fmt(r["left_mean"]), fmt(r["right_mean"]), fmt(r["paired_mean_difference"]),
          fmt(r["paired_median_difference"]), wtl(r),
          "; ".join(f'{k}={v}' for k, v in r["exclusion_reason_counts"].items()) or "None"]
         for r in secondary if r["outcome"] == outcome]) for outcome in SECONDARY)


def cohort_tables(cohorts):
    return "\n".join("### " + c["cohort_id"] + f' (n = {c["scenario_count"]})\n\n' + table(
        ["Contrast", "Paired scenarios / families", "Mean Δ", "Median Δ", "W/T/L", "Exploratory 95% bootstrap interval"],
        [[short, f'{r["paired_scenario_count"]} / {r["scenario_family_count"]}', fmt(r["paired_mean_difference"]),
          fmt(r["paired_median_difference"]), wtl(r), interval(r, "exploratory_bootstrap")]
         for short, r in zip(CONTRAST_SHORT, c["contrasts"])]) for c in cohorts)


def mechanism_tables(mechanism):
    rows = mechanism["modes"]
    statuses = lambda r, key, names: "/".join(str(r[key].get(n, 0)) for n in names)
    per_mode = table(["Mode", "Evidence calls", "P3 lookups", "RAG S/L/N", "Memory A/N", "Planner U/I", "Zero steps", "Projected generator tokens"],
        [[short, r["evidence_synthesis_call_count"], r["p3_lookup_count"],
          statuses(r, "rag_status_counts", ["SUPPORTED", "LIMITED_EVIDENCE", "NO_RESULT"]),
          statuses(r, "memory_status_counts", ["AVAILABLE", "NO_MATCH"]),
          statuses(r, "planner_status_counts", ["USED", "INSUFFICIENT_EVIDENCE"]),
          r["planner_zero_step_count"], r["condition_projected_generator_total_tokens"]["sum"]]
         for short, r in zip(MODE_SHORT, rows)])
    usage = mechanism["actual_and_counterfactual_usage"]
    provider = table(["Historical stage", "Canonical / logical units", "Recorded attempts", "Known input tokens", "Known output tokens", "Known total tokens"], [
        ["P3 Router precomputation", 186, 186, 293203, 1736, 294939],
        ["Final R3 generation (all attempts)", 147, 149, 127762, 23568, 151330],
        ["Final accepted R3 responses (subset above)", 147, "Included above", 125818, 23155, 148973],
        ["All Judge histories (208 returned outputs)", "149 final results", 213, 621542, 82610, 704152],
        ["Canonical Judge results (subset above)", 149, "Included above", 446343, 59654, 505997],
        ["Superseded G2 generation (excluded from final scores)", "Historical only", 197, 120366, 25597, 145963],
    ])
    unavailable = {}
    for r in mechanism["predeclared_metric_coverage"]:
        if r["status"] == "NOT_EVALUABLE_SOURCE_NOT_AVAILABLE":
            unavailable.setdefault(r["metric"], set()).add(r["reason"])
    unavailable_table = table(["Predeclared metric", "Reason for NOT_EVALUABLE_SOURCE_NOT_AVAILABLE"],
        [[metric, " ".join(sorted(reasons))] for metric, reasons in sorted(unavailable.items())])
    return per_mode, provider, unavailable_table


def main():
    verify_entry()
    measurement, bias_table = measurement_outputs()
    mode, primary, secondary, cohorts, strata, mechanism, mode_ids = report_inputs()
    levels, effects, robustness, marginal = primary_tables(mode, primary, mode_ids)
    mechanism_modes, provider, unavailable = mechanism_tables(mechanism)
    authority = read_json(HERE / "F1_SOURCE_AUTHORITY_METADATA_V1.json")
    mode_description = [
        "Original context without Evidence-Synthesis or the three optional components",
        "Evidence-Synthesis; RAG, Memory and Planning unavailable",
        "Evidence-Synthesis with RAG available behind frozen P3",
        "Evidence-Synthesis with Memory available behind frozen P3",
        "Evidence-Synthesis with Planning available behind frozen P3",
        "Evidence-Synthesis with RAG, Memory and Planning available behind frozen P3",
        "Full C4 with RAG unavailable",
        "Full C4 with Memory unavailable",
        "Full C4 with Planning unavailable",
    ]
    mode_key = table(["Display", "Frozen mode identity", "Configuration"],
                     list(zip(MODE_SHORT, mode_ids, mode_description)))
    contrast_key = table(["Frozen contrast identity", "Left", "Right", "Holm family"], CONTRASTS)
    all_levels = table(["Mode", "Outcome", "Applicable n", "NA n", "Mean", "Median"],
        [[MODE_SHORT[mode_ids.index(r["mode_id"])], r["outcome"], r["applicable_score_count"],
          r["na_count"], fmt(r["mean"]), fmt(r["median"])] for r in mode if r["outcome"] != PRIMARY_OUTCOME])
    interpretation = table(["Contrast", "Frozen decision interpretation"],
        [[s, "Evidence of higher Judge-rated primary outcome" if r["reliable_improvement_established_under_frozen_judge_analysis"]
          else "The experiment does not establish a reliable improvement"] for s, r in zip(CONTRAST_SHORT, primary)])
    stratum_table = table(["Frozen reference stratum", "Scenarios", "Role"],
                         [[s["stratum"], s["scenario_count"], s["analysis_role"]] for s in strata])

    statistical = f"""# Final real-C4 RQ3 statistical results

The full C4 system did not establish a reliable improvement over the Evidence baseline on the frozen LLM-Judge-rated primary outcome. None of the five primary add-one contrasts passed its Holm family. The targeted comparison of full C4 with Planning removed supported a higher Judge-rated outcome when Planning was available: mean paired difference 0.0949501, pointwise 95% bootstrap interval [0.0345622, 0.1695469], Holm p = 0.0230998. All eight contrasts, including null and negative estimates, are retained below.

## Population, outcome and identities

There are 558 condition records, 62 frozen scenarios and nine modes per scenario, with exactly 62 records per mode. The frozen pair key is `scenario_id`. The analysis column `scenario_family_id` is its exact one-to-one alias: 62 families, one paired scenario per family. The real-C4 mode registry declares paired scenarios. Track-D does not contain a separate literal family field or a multi-case grouping; later frozen response-integration code and Human sample metadata use the same scenario-as-family binding. No score-informed grouping was introduced.

The 149 corrected Judge result identities are projected by exact frozen identity keys onto all 558 conditions. They correspond to 147 canonical generated response identities. Neither 149 requests nor 558 rows is an independent-observation denominator. All eight primary contrasts have 62 complete scenario pairs and 62 families; there are zero excluded cases or families. Exact-request sharing and inactive routes preserve valid zero paired differences.

The primary endpoint is the exact F0 `OVERALL_APPLICABLE_MEAN`: the arithmetic mean of the applicable scores among the eight primary rubric dimensions for that condition. Evidence Faithfulness and Unsupported Claim Count are separate secondary audits. Applicability can differ between modes, so primary means can average different criterion sets. The primary endpoint is not recomputed over a common-criterion subset.

{mode_key}
## Primary mode summaries

The standard deviation is descriptive. Means use the 62 condition observations associated with each mode, including score reuse under exact request identity. Display rounding here does not alter frozen numeric inputs or machine-readable outputs.

{levels}
## Exact predeclared comparisons

Positive differences favor the left mode on the Judge-rated primary endpoint. The first five contrasts form one primary add-one Holm family; the last three form one targeted remove-one family. No sequential C1→C2→C3→C4 comparison and no controlled-RQ3 RM/Oracle comparison was executed.

{contrast_key}
{effects}
All paired medians are zero. The intervals are **pointwise**, not multiplicity-adjusted. The confirmatory p-value is the two-sided family sign-flip p-value, adjusted separately over five and three comparisons. Thus the positive interval for C4−C1 and negative interval for C2−C1 do not override their Holm results (0.078849 and 0.155278). A confidence interval excluding zero alone is insufficient for the stated reliable-improvement interpretation.

{interpretation}
## Robustness, effect sizes and complete-pair marginals

Wilcoxon is the predeclared robustness analysis, with exact conditional average-rank enumeration by dynamic programming, dropped zero differences, tied average ranks and no continuity correction. Its p-values below are unadjusted robustness results and do not replace the primary sign-flip/Holm decision. Paired dz uses the sample SD of family differences. Matched rank-biserial uses the signed sum of nonzero ranks. No magnitude labels were predeclared.

{robustness}
{marginal}
## Secondary response outcomes — SECONDARY_EXPLORATORY

Each criterion comparison uses only pairs applicable on both sides; NA is not zero or an imputed score. `NA_BOTH_SIDES`, `NA_LEFT_ONLY` and `NA_RIGHT_ONLY` state which side lacks an applicable criterion. There are no criterion p-values or additional Holm families. Unsupported Claim Count retains the numerical left-minus-right difference but defines a win as a lower count. All other listed outcomes define a win as a higher value. Tie tolerance is 1e-12.

For C5−C1, the descriptive changes include Actionability +0.3214 (n=28), Personalisation +0.2162 (n=37), Motivation and Engagement +0.2500 (n=40), and Error Handling −0.2000 (n=10). Multi-page Cohesiveness is +0.5000 on only six applicable pairs. Faithfulness is −0.0161 and Unsupported Claim Count +0.0161 (both n=62). These observations are exploratory; they neither establish criterion-level significance nor validate a reliable full-system improvement.

{secondary_tables(secondary)}
## Frozen cohort sensitivity — exploratory

Original-25 and the nine-scenario persistent-Memory cohort have exact identities frozen before response generation. Both retain the complete-pair rule and the same fixed bootstrap procedure. The intervals below are explicitly exploratory, with no confirmatory p-values or Holm adjustments. They do not supersede the full 62-scenario results or support a subgroup significance claim.

{cohort_tables(cohorts)}
## Router-selected and mechanism-stratified descriptions

Stratum membership uses the frozen P3 flags or actual mechanism status of **C5_FULL_C4**, as specified in the sealed F1 plan before unblinding. All eight contrasts are reported for every stratum in `C4_REAL_F1_MECHANISM_STRATIFIED_DESCRIPTIVES_V1.json`. These strata were not selected by score direction. No inference is performed within them and they are not unbiased component causal effects.

{stratum_table}
## Mechanism and efficiency

The table preserves availability, activation and returned state. RAG S/L/N means SUPPORTED/LIMITED_EVIDENCE/NO_RESULT; Memory A/N means AVAILABLE/NO_MATCH; Planner U/I means USED/INSUFFICIENT_EVIDENCE. Zero-step counts refer to activated Planner results. Token totals project each frozen accepted response onto 62 separate interactions per mode and are not experimental billing totals.

{mechanism_modes}
Across conditions there were 496 Evidence-Synthesis calls, 434 P3 cache lookups, 84 RAG activations, 76 Memory activations and 60 Planner activations in the frozen replay. The 84 logical retrievals reused 21 actual computations and 63 cache hits. Per-condition cache events were not retained, so retrieval computations/cache hits cannot be attributed to activated modes; absent activation is a known zero. RAG returned 36 SUPPORTED, 12 LIMITED_EVIDENCE and 36 NO_RESULT states, with 240 selected sources: 60 BODY_EXCERPT, 12 SUMMARY_SUPPORT, 44 LINK_ONLY and 124 TITLE_AND_METADATA_ONLY. These support classes are not interchangeable.

Memory returned 8 AVAILABLE and 68 NO_MATCH states, selecting 12 items (8 ACTIVE_PLAN and 4 GOAL). The target queries produced no Memory writes; persistent preconditioning is a separate earlier operation. The frozen selected-item status diagnostic found no superseded selection. Planner returned 54 USED and 6 INSUFFICIENT_EVIDENCE states, with six zero-step outputs and 162 emitted action steps. Frozen structural status/evidence-hash diagnostics found no inconsistency; they are not independent semantic step-support labels. The bounded forced-OFF result check is distinct from a complete cross-learner leakage audit.

{provider}
The Router/R3/Judge histories contain 548 recorded physical attempts; including superseded G2 gives 745. These are retained historical accounting scopes, not a verified wire-send or monetary billing total. Of 213 recorded Judge starts, 208 returned outputs; three completion/billing outcomes remain unknown and two recorded API rejections produced no result. Canonical Judge usage is counted once per 149 result identities, never multiplied by 558. Historical G2 output does not enter any final response or score.

For 558 separate interactions **with the same frozen precomputed route cache**, the frozen-response projection is 558 generator calls, 434 route lookups, zero evaluation-only Judge calls, 449,888 input tokens, 76,699 output tokens and 526,587 total tokens. It assumes replay of the same accepted responses; it is not a prediction of future generated length. An uncached live P3 call estimate is `NOT_EVALUABLE_SOURCE_NOT_AVAILABLE` because no frozen cache/skip deployment rule exists. Every mode is associated with 60 distinct canonical generator requests, but these sets overlap across modes and must not be added or used as the scoring denominator.

Cost status is `COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY`. Historical router-only approximate price information is not an authoritative frozen pricing schedule for the complete generator/Judge workload. No new price table or monetary total was introduced. All 26 registered mechanism/efficiency metrics appear for each of nine modes (234 coverage records), including explicit missing-source statuses:

{unavailable}
## Measurement and execution provenance

Human–Human agreement was 189/276 exact and 274/276 within one point, weighted kappa 0.8542154167707932 and Spearman 0.8728525479786775. Pooled Human–LLM agreement was 186/552 exact and 421/552 within one point, MAE 0.9619565217391305, weighted kappa 0.3616242748772869 and Spearman 0.4537074855476746. These are unchanged blinded F0 statistics on 44 unique items, not Human mode effects. The complete bias table and interpretation are in `C4_REAL_F1_MEASUREMENT_VALIDATION_INTERPRETATION.md`.

F0 integrity remains qualified by `QUALIFIED_PACING_EVIDENCE_LIMITATION`: recorded request-start times do not prove the monotonic pacing reference or strict 15-second HTTP wire-send compliance. Applicability V2 remains `CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT`; the original Phase-A boundary incident is preserved, with the clean-room certification and separate Phase-B repair disclosed. Neither history was rewritten or used to rerun an accepted result in F1.

## Full descriptive mode profile

These tables include all primary dimensions and the two separate audits. Applicable counts and NA counts sum to 62 for every mode-outcome row.

{all_levels}
Machine-readable authorities retain full floating-point precision: `C4_REAL_F1_MODE_SUMMARIES_V1.json`, `C4_REAL_F1_PRIMARY_CONTRAST_RESULTS_V1.json`, `C4_REAL_F1_SECONDARY_OUTCOME_RESULTS_V1.json`, the frozen cohort/stratum JSON files and `C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json`. CSV counterparts are supplied where requested. No qualitative response examples, raw candidate text, raw rationale or restricted condition mapping appears in this report.
"""
    write_once_bytes(HERE / "C4_REAL_FINAL_RQ3_STATISTICAL_RESULTS.md", statistical.encode())

    method = f"""# Final real-C4 RQ3 method and analysis audit

This is the final, directly authorized offline F1 analysis of the frozen real-C4 experiment. The run entered `{EXPECTED_ROOT}`, branch `{EXPECTED_BRANCH}`, at `{STARTING_HEAD}`. The entry gate recorded zero modified/deleted/staged tracked files and exactly the three retained historical J2D2 untracked files. It verified the 32-byte HMAC key by size and commitment without exposing the key. Its pre-analysis byte snapshot covers 838 pre-existing source files; final preservation checks are recorded separately and bind this snapshot.

## Source authority and pre-unblinding ordering

All 17 user-specified hashes passed before any restricted mode content was read. F0 status was `READY_FOR_FINAL_MODE_UNBLINDING_AND_PREDECLARED_STATISTICAL_ANALYSIS`, with 149 corrected Judge identities, 558 condition projections, 44 Human-visible items per rater, zero missing/duplicate identities and zero excluded Judge selections. F0 had zero mode unblindings and zero treatment-effect analyses. The HMAC commitment is `{authority["f0_hmac_commitment"]}`. F0 completion receipt SHA-256 is `b5400029eac0d14f271f8238cf5706bff6b039f29d976a7fb94a8ecbe666d5ad`.

The hierarchy, plan, generic procedures and implementation were sealed and fsynced before mode access. F1 entry receipt SHA-256 is `{ENTRY_RECEIPT_SHA256}`. It records `write_count=1`, `overwrite_permitted=false`, zero prior mode-map reads and zero prior system comparisons. The control guard verifies that digest and every sealed implementation/metadata hash, appends a metadata-only hash-chained access record, flushes/fsyncs it, then opens a frozen identity source and checks its source hash. The final receipt closes further controlled identity access and binds the completed ledger digest.

The real-C4 mode registry controls nine identities, eight left-minus-right contrasts, the paired-scenario design, and separate five/three Holm families. The generic contract supplies compatible statistical procedures only. RM00/RM10/RM01/RM11 and BASE/ALWAYS/ORACLE/PREDICTED formulas were never treated as C4 comparisons. This authority order is recorded in `F1_ANALYSIS_CONTRACT_HIERARCHY_V1.json` before mapping access.

## Exact identity projection and paired units

The join uses the frozen condition-to-generation `replay_record_id`, corrected Judge payload identities and frozen scenario/mode maps. It does not use query/answer similarity or row order. Historical response-to-mode mappings are many-to-many membership relations, so a generated answer or shared response ID is not treated as a unique condition key. The corrected Judge projection matches the frozen canonical parsed result exactly for all 558 conditions. Every original F0 primary mean remains bit-for-bit equal as a parsed numerical value; no rationale or score was changed.

`scenario_id` is the frozen pair key. Real-C4 specifies a paired scenario. Track-D has no separate literal family column or multi-case family mapping; the frozen response-integration `select_human_families` code uses `scenario_id` as family, and its Human sample metadata reports 62 eligible scenario families. F1's `scenario_family_id` is an exact alias, not a new grouping. Therefore there are 62 one-scenario families for every complete primary contrast. Had a frozen family contained multiple complete cases, its arithmetic mean paired difference would enter sign-flip, Wilcoxon and paired-effect calculations; bootstrap would retain all complete members of each sampled family occurrence. That generic rule is tested synthetically without changing this dataset's clustering.

The raw condition CSV/JSONL and 496-row eight-contrast pair registry are stored only in ignored, untracked `restricted_internal`, with mode 0600. Public metadata records filenames, schemas, counts and hashes, not raw condition identities, query/response text or rationales. All cases meet the complete-pair rule here. A missing side excludes the entire pair; a criterion NA excludes the criterion pair with an explicit reason. Shared exact payloads remain in the scenario estimand as zero differences rather than being deduplicated away.

These are system-level comparisons of component availability behind a frozen P3 Router over the complete 62-scenario population. Route-positive and mechanism-success subsets do not define the confirmatory estimand. Each mode's 60 associated canonical generator requests among 62 conditions also demonstrates why scenarios are not independent fresh generation trials. The prescribed scenario unit is preserved; no post-result clustering or sensitivity contrast is invented to address this limitation.

## Sealed numerical procedures

Let d_fj be the left-minus-right primary difference for complete paired case j in frozen family f, and d̄_f its within-family arithmetic mean. In this dataset j=1 for every family. Scores are not rounded before calculations. The fixed numerical tolerance is 1e-12 for wins/ties/losses, zero differences, tied absolute ranks and the at-least-as-extreme sign-flip comparison.

* Bootstrap: resample F eligible families with replacement 10,000 times, retaining every complete member for each sampled family occurrence; compute the mean across those retained paired cases; take empirical 2.5th/97.5th percentiles with NumPy's linear quantile rule. Seed 20260831, `Generator(PCG64)`, reset per contrast/cohort. F<2 yields `NOT_ESTIMABLE_INSUFFICIENT_FAMILIES`. Intervals are pointwise.
* Sign-flip: statistic |mean(d̄_f)|, two-sided, with zero differences retained. Enumerate every 2^F assignment for F≤20. For F>20, use exactly 100,000 independent sign assignments with seed 20260831 and p=(1+extreme)/(1+100000). All eight actual contrasts have F=62 and use this Monte Carlo branch. No stopping or method choice depends on the p-value.
* Wilcoxon robustness: drop |d̄_f|≤1e-12; assign average ranks to absolute nonzero differences, using the same fixed tie tolerance. The exact conditional two-sided distribution of those ranks is computed by integer dynamic programming after doubling average ranks; no automatic normal/exact method switch or continuity correction. All-zero data yields `NOT_ESTIMABLE_ALL_ZERO_WITH_EXACT_AGREEMENT_REPORTED`. This exact tied-rank choice was sealed before unblinding.
* Paired Cohen dz = mean(d̄_f)/s(d̄_f), with sample SD (F−1 denominator); zero SD yields `NOT_ESTIMABLE_ZERO_STANDARD_DEVIATION`. Insufficient families remain non-estimable. Matched rank-biserial = (W+−W−)/(W++W−) over nonzero average ranks; all-zero input yields `NOT_ESTIMABLE_ALL_ZERO`. No numerical magnitude thresholds were declared.
* Holm: within each frozen family, sort the complete raw sign-flip p-values; adjusted p at rank i is min(1, max over j≤i of (m−j+1)p_(j)). Apply once to the five primary add-one contrasts and once to the three targeted remove-one contrasts. No secondary or subgroup p-value enters either family. Wilcoxon p-values are reported as unadjusted robustness checks.

The primary mean uses only the applicable subset of the eight primary dimensions. Its applicability set may vary by condition. Evidence Faithfulness and Unsupported Claim Count are excluded. Secondary pairs require both sides applicable and receive descriptive means, medians and wins/ties/losses only. Original-25 and the persistent-Memory nine retain frozen pre-response membership and exploratory bootstrap intervals. P3/status strata use C5_FULL_C4 as the fixed membership reference and receive no interval, permutation or confirmatory inference.

## Measurement and remediation provenance

Human measurements are transcribed from the unchanged blinded F0 summaries; no Human rating file is joined to an unblinded mode. No Judge score was calibrated, averaged with Human ratings, rescaled or replaced. The 44-item Human validation sample supports measurement interpretation, not a predeclared Human treatment estimate.

Applicability V2 status is `CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT`. The stopped original Phase-A boundary incident remains disclosed. A score-isolated clean-room replay certified the unchanged Phase-A applicability decisions; the later Phase-B repair had its own direct authorization. F0 integrated 33 retained unchanged result identities plus corrected A=39, B=38 and C=39 (149 total). Of the 33 retained results, 32 had historical terminal records and one was materialized from the exact Phase-B-selected raw attempt under Parser V3; the absence of that old terminal record was not hidden. Human applicability repair and all score amendments were completed before F1; F1 made none. The source authority and full Phase-A/Phase-B hash bindings remain in the frozen F0 metadata.

Pacing remains `QUALIFIED_PACING_EVIDENCE_LIMITATION`. A configured 15-second interval was an operational rate-limit safeguard, not a treatment. Recorded `request_started_at_utc` differences do not establish the monotonic reference or actual HTTP wire-send intervals, so strict 15-second wire-send compliance is not claimed. F0 accepted corrected B/C/completed A only when identity, payload, model, Parser V3, applicability and canonical coverage passed and no selected result had an unresolved Provider error. No result was rerun or excluded solely to produce different timing evidence. The historical interrupted A order-39 completion/billing outcome remains unknown; only its separately authorized `execution_output_v2` supplies the canonical result.

## Mechanism and efficiency scope

All mechanism outputs are summaries of already frozen replay traces, returned statuses, selected-item/source metadata and recorded usage; no component was rerun. RAG trigger precision/recall/F1 uses availability-gated frozen P3 flags against the final dataset's frozen `required_capabilities` requirement, not retrospectively inferred relevance. Chunk-level relevance and several Memory/Planner correctness metrics lack a frozen crosswalk or aligned truth labels and remain `NOT_EVALUABLE_SOURCE_NOT_AVAILABLE`. An old hard-coded constraint diagnostic is not substituted for independent constraint-adherence measurement. Zero forced-OFF output checks and zero selected superseded items do not constitute a complete leakage or memory-correctness audit.

Actual recorded Router, final generation and Judge attempts are separated from superseded G2 history and from the condition-level frozen-response deployment projection. The 149 canonical Judge uses are never multiplied by 558. Unknown completion/billing and latency sources are not imputed. Full-run monetary cost is `COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY`; no current or retrospective price schedule is introduced.

## Figures, privacy and final gate

Four figures use only `F1_FIGURE_SOURCE_DATA_V1.json`, bound to aggregate result hashes. All eight effects, all nine modes, all eight criteria and all three mechanism status panels are retained. The source exports editable PDF/SVG, PNG at 300 dpi and TIFF at 600 dpi at a fixed 180 mm width. Display rounding is confined to labels. The source validator, PDF glyph audit, final Matplotlib text/stroke geometry and comparable panel alignment are recorded. PyMuPDF is not installed; the provided PDF collision tool returns a dependency blocker. Under the user's offline constraint no network installation is attempted and no PDF collision pass is claimed. Backend geometry and whole-figure visual inspection provide a disclosed alternative, not a relabelled PDF audit.

Only targeted F1 statistical/source-integrity tests are run. Exact results are in `F1_TARGETED_TEST_REPORT_V1.json`; visual QA, source preservation, ledger metadata and review-package checks have separate artifacts. Preparation diagnostics describe resolved schema assumptions and figure preflight corrections without rewriting scientific inputs, sealed methods or existing output results. The final receipt is written once only after those gates pass, binds the completed ledger and all scientific outputs, and closes further unblinding. New tracked work is restricted to the F1 directory; all previous artifacts and the three retained historical files remain unchanged. Exactly one commit and one explicit-allowlist review ZIP complete this authorization. F1 Provider/network/Judge/generation/Human-rating/Streamlit and component execution counts are all zero.
"""
    write_once_bytes(HERE / "C4_REAL_FINAL_RQ3_METHOD_AND_ANALYSIS_AUDIT.md", method.encode())

    limitations = """# Limits of the final real-C4 RQ3 analysis

The full-system comparison with Evidence does not establish a reliable improvement. Only the predeclared targeted Planning removal contrast supplies evidence of a higher Judge-rated primary outcome under the frozen sign-flip/Holm analysis. This result is conditional on the frozen scenarios, P3 decisions, accepted response identities, rubric, applicability and Judge procedure.

1. **Measurement validity.** Human–Human agreement was relatively consistent, while Human–LLM agreement was materially lower and the Judge was more generous, particularly on Reliability, Error Handling, Context Awareness and Multi-page Cohesiveness. Absolute scores near the top of the scale require caution. Pairing may attenuate stable leniency but does not establish condition-invariant bias. No Human mode effects were predeclared or computed, and the 44-item validation sample cannot certify Human-perceived effects across all 62 scenarios.

2. **Scope and replication.** These are 62 frozen paired scenarios, not 62 independent students or fresh repeated generation trials. The nine mode conditions share scenario context, and exact-request reuse can also produce identical responses across different scenario identities. Each mode is associated with 60 distinct canonical generator requests for 62 conditions. The declared one-scenario-per-family structure was retained without regrouping after results. Inference describes the prescribed scenario-based analysis; it does not quantify independent generation variability, new courses, institutions or student populations.

3. **Outcome composition.** OVERALL_APPLICABLE_MEAN averages the applicable primary dimensions separately for each condition. Applicability can change across modes, particularly Error Handling; consequently a mean difference can reflect different included criterion sets as well as score differences. F1 preserves the frozen endpoint instead of switching to a common-criterion score. Secondary criterion analyses require both sides applicable and can have small or zero denominators (six for Multi-page Cohesiveness; no C1−C0 Error Handling pair).

4. **Multiplicity and uncertainty.** Pointwise bootstrap intervals are not multiplicity-adjusted. A positive interval or low raw p-value does not override the separate five/three Holm families. All eight primary paired medians are zero, with many ties retained. Non-significance does not demonstrate equivalence or absence of effect. Wilcoxon is an unadjusted robustness check and is not substituted for the primary test. No dz size labels or minimum practically meaningful difference were predeclared.

5. **Component availability and selection.** Primary effects concern making components available behind frozen P3, including valid route-inactive zero pairs. They are not effects among activated or successful-only cases. Router-selected and mechanism-status strata are descriptive and can be selected on response-generation mechanisms; they are not unbiased component causal effects. Original-25 and persistent-Memory nine are frozen exploratory sensitivities, and their intervals do not establish subgroup significance.

6. **Mechanism observability.** RAG SUPPORT/LIMITED/NO_RESULT, Memory AVAILABLE/NO_MATCH and Planner USED/INSUFFICIENT are frozen status labels. They do not supply independent correctness for retrieval chunks, current Memory values, every planning step or constraint. Several required truth/crosswalk sources were never frozen for these 558 conditions. Such metrics are explicitly NOT_EVALUABLE_SOURCE_NOT_AVAILABLE. The 21 RAG computations and 63 cache hits are available in aggregate, but per-mode attribution is unavailable. Bounded zero forced-OFF/selected-superseded diagnostics do not establish absence of every learner leakage or Memory failure.

7. **Efficiency and cost.** Known token totals describe recorded or canonical attempts in clearly separated scopes. Three Judge completion/billing outcomes remain unknown; start records are not verified wire-send counts. Counterfactual usage assumes each accepted frozen response is replayed as a separate interaction with a precomputed route cache; it is not a forecast of uncached live P3 use or future answer lengths. End-to-end latency is unavailable. Historical Router price approximations do not authorize a complete monetary cost; COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY remains explicit.

8. **Pacing evidence.** The configured 15-second guard was operational. Durable request-start records do not establish monotonic-reference or HTTP wire-send compliance. The canonical results retain QUALIFIED_PACING_EVIDENCE_LIMITATION; they were not rerun or removed to improve timing evidence. The interrupted original A order-39 outcome remains unknown even though a separately authorized v2 result completes canonical coverage.

9. **Applicability remediation history.** Applicability V2 was certified by score-isolated clean-room replay after a disclosed Phase-A access-boundary incident. The incident, stopped receipt, certification and independently authorized Phase-B repair remain part of the provenance. F1 does not erase the incident, reinterpret old execution statuses or claim that it never occurred. No applicability, Judge/Human score, rationale or identity artifact was changed in F1.

10. **Figure audit environment.** The offline environment supports Matplotlib, editable vector export, PDF glyph checks, 1.5-point panel alignment and backend-rendered geometry plus visual inspection. It lacks PyMuPDF for the provided PDF collision tool. That check is recorded as not auditable, without a network install or a claim of PDF collision validation. The export is thesis-ready; current journal submission specifications were not independently retrieved.

No result in this package supports a claim of improved real student learning outcomes, grades or satisfaction; Human-perceived improvement across the full dataset; or generalisation to other courses or institutions. No qualitative responses were selected from score extremes. These limits are part of the result, not reasons to modify the frozen outcome or launch new model execution in this authorization.
"""
    write_once_bytes(HERE / "C4_REAL_FINAL_RQ3_LIMITATIONS.md", limitations.encode())

    selected_secondary = [r for r in secondary if r["contrast_id"] == "C5_MINUS_C1"]
    secondary_brief = table(["Outcome", "Applicable pairs", "C5 − C1 mean Δ", "Wins / ties / losses"],
        [[OUTCOME_NAMES[r["outcome"]], r["applicable_pair_count"], fmt(r["paired_mean_difference"]), wtl(r)]
         for r in selected_secondary])
    manuscript = f"""# Real-C4 response-quality results — manuscript draft

Across 62 paired scenarios, the full C4 system did not establish a reliable improvement over the Evidence baseline on the frozen Judge-rated response-quality outcome. None of the five primary add-one comparisons passed Holm correction. In the separate targeted remove-one family, full C4 scored higher than full C4 with Planning removed (paired mean difference 0.0950, pointwise 95% bootstrap CI 0.0346 to 0.1695; Holm p=0.023100). This is evidence within the frozen Judge-based analysis, rather than a measure of student learning.

## Evaluation population and configurations

The final dataset comprised 558 conditions: nine configurations for each of 62 scenarios. The frozen paired-scenario design provided 62 families with one paired scenario per family. Here `scenario_family_id` is an exact alias of the frozen `scenario_id`; Track-D supplied no separate multi-case grouping. All eight contrasts had 62 complete pairs, with no scenario or family exclusions. Exact identity projection associated the conditions with 149 corrected Judge result identities and 147 canonical generated responses. Shared requests did not remove conditions, and identical outputs contributed zero differences. These request counts were not treated as independent sample sizes.

C0 used original context, and C1 added Evidence-Synthesis. C2, C3 and C4 respectively made RAG, Memory and Planning available alongside Evidence-Synthesis behind the frozen P3 Router. C5 enabled all three; its targeted ablations made RAG, Memory or Planning unavailable. Availability did not imply activation on every scenario. The primary outcome was the exact F0 OVERALL_APPLICABLE_MEAN over the applicable subset of eight primary rubric dimensions. Evidence Faithfulness and Unsupported Claim Count remained separate audits. Because applicability is condition-specific, the set of averaged dimensions can differ between modes.

{levels}
The mode means and medians are descriptive. Their absolute levels should be interpreted with the Human–Judge measurement comparison below. Neither a marginal mode ranking nor the 558 condition rows provides an independent treatment test.

## Predeclared paired comparisons

The five primary contrasts were C1−C0, C2−C1, C3−C1, C4−C1 and C5−C1. The three targeted contrasts were C5−(C5−RAG), C5−(C5−Memory) and C5−(C5−Planning), always left minus right. Each used all 62 scenarios, including route-inactive cases. Confidence intervals used 10,000 family-cluster bootstrap replicates with seed 20260831 and percentile limits. The two-sided sign-flip test used 100,000 family-level sign assignments with the same seed and the plus-one correction; Holm adjustment was applied separately across five and three contrasts.

{effects}
For full C4 versus Evidence, the mean difference was 0.0830 (95% CI −0.0207 to 0.1931; raw p=0.144179, Holm p=0.432536). The experiment therefore does not establish a reliable full-system improvement. Adding Planning to Evidence had a positive pointwise interval but Holm p=0.078849; adding RAG had a negative pointwise interval but Holm p=0.155278. Neither establishes a reliable improvement under the frozen interpretation rule. Adding Memory and the targeted RAG/Memory removal comparisons also did not establish a reliable improvement. These findings do not establish equivalence or an absence of all possible effects.

Only the targeted Planning removal comparison met the predeclared interpretation for higher Judge-rated response quality. It yielded eight wins, 54 ties and no losses, with paired median difference zero. Full C4 versus Evidence yielded 17 wins, 35 ties and ten losses, also with median difference zero. All eight contrasts are retained without selection by sign or significance.

{robustness}
The robustness analysis used exact conditional Wilcoxon signed ranks with zeros dropped and average tied ranks. Its unadjusted p-values are reported without replacing the primary sign-flip/Holm decision. Paired dz uses the sample SD of family differences; rank-biserial uses nonzero signed ranks. No small/medium/large thresholds were predeclared for these numerical effects.

## Descriptive criteria and frozen sensitivities

Secondary scores used only pairs applicable on both sides. They were labelled SECONDARY_EXPLORATORY, with no criterion-level significance tests. For the central full-system versus Evidence comparison, the complete descriptive profile was:

{secondary_brief}
Unsupported Claim Count is favorable when lower, although the reported difference remains left minus right. Error Handling had only ten jointly applicable C5−C1 pairs; 20 additional pairs were applicable only on the C5 side and were excluded from that criterion comparison. Multi-page Cohesiveness had six applicable pairs. These denominators prevent interpreting the profile as uniform evidence across all scenarios. The complete 80-row secondary analysis for all eight contrasts is retained with exact NA reasons.

The original-25 and persistent-Memory nine were fixed before response generation. Original-25 C5−C1 had mean difference 0.0227 (exploratory 95% interval −0.1133 to 0.1571), and its targeted Planning removal comparison was 0.0457 (0.0000 to 0.1200). In the persistent-Memory nine, the corresponding differences were 0.4709 (0.1508 to 0.8599) and 0.3419 (0.1349 to 0.5463). These are exploratory sensitivity intervals, with no confirmatory p-values or subgroup significance claims. Every one of the eight contrasts is retained for both cohorts. P3-required and actual mechanism-status strata use the predeclared C5_FULL_C4 reference and remain descriptive; they are not unbiased component causal estimates.

## Mechanism operation and efficiency

Frozen replay records distinguished component activation from substantive returned content. Across the 558 conditions, Evidence-Synthesis ran 496 times and P3 was looked up from its cache 434 times. RAG was activated 84 times, reusing 21 retrieval computations and 63 cache hits; returned states were 36 SUPPORTED, 12 LIMITED_EVIDENCE and 36 NO_RESULT. Its 240 selected sources included 60 body excerpts, 12 summaries, 44 link-only sources and 124 title/metadata-only sources. Memory was activated 76 times, with 8 AVAILABLE and 68 NO_MATCH states, selecting 12 items (eight active plans and four goals). Planner was activated 60 times, yielding 54 USED and six INSUFFICIENT_EVIDENCE/zero-step results and 162 action steps. No target-query Memory writes, selected superseded items or structural Planner status/hash inconsistencies were recorded. These are bounded operational diagnostics, not independently labelled correctness or a complete leakage audit.

Actual generation used 147 canonical requests and 149 physical attempts, totaling 151,330 known tokens over all attempts (148,973 for canonical accepted responses). Router precomputation had 186 component requests and 294,939 tokens. Judge evaluation was separate overhead: 149 canonical result requests used 505,997 tokens; all 208 returned Judge outputs used 704,152 known tokens across a history of 213 recorded starts. Three completion/billing outcomes remain unknown and two starts ended in recorded API rejections. Superseded G2 history comprised 197 observed calls and 145,963 tokens and was excluded from every final response and score. Recorded attempts are not a verified HTTP wire-send/billing total.

Treating all 558 frozen conditions as separate interactions with the same precomputed route cache gives a counterfactual projection of 558 generator calls and 526,587 tokens, with zero evaluation-only Judge calls. This reuses accepted response lengths rather than forecasting future generation. It is separate from actual deduplicated experiment usage, and Judge usage is never multiplied by 558. End-to-end latency, uncached deployment P3 calls and metrics without aligned frozen truth remain NOT_EVALUABLE_SOURCE_NOT_AVAILABLE. Cost remains COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY because no complete authoritative pricing schedule was frozen before result access.

## Measurement and provenance limitations

On 44 unique Human-visible items, Human–Human agreement was 189/276 exact and 274/276 within one point (weighted kappa 0.8542154167707932; Spearman 0.8728525479786775). Pooled Human–LLM agreement was 186/552 exact and 421/552 within one point, MAE 0.9619565217391305, weighted kappa 0.3616242748772869 and Spearman 0.4537074855476746. The pooled denominators count applicable criterion observations, not independent items. Humans applied the rubric relatively consistently, but the Judge was not interchangeable with a Human rater. Frozen Judge-minus-Human biases were positive across criteria, including Reliability +1.5340909090909092, Error Handling +1.7727272727272727, Context Awareness +1.0340909090909092 and Multi-page Cohesiveness +1.0. Absolute Judge levels require caution. Pairing may reduce stable leniency but does not demonstrate condition-invariant bias. No Human mode effects, recalibration or Human–Judge score averaging were performed.

The canonical evaluation retains QUALIFIED_PACING_EVIDENCE_LIMITATION: the configured 15-second safeguard and recorded request-start times do not establish monotonic-reference or HTTP wire-send compliance. The interrupted original A order-39 outcome remains unknown; its separately authorized v2 supplies the canonical result. Applicability V2 is CERTIFIED_BY_SCORE_ISOLATED_REPLAY_WITH_DISCLOSED_PRIOR_INCIDENT. A score-isolated clean-room replay certified the applicability decisions after the disclosed Phase-A boundary incident, followed by a separately authorized Phase-B repair. F1 preserves this history and changes no applicability decision, score, rationale or frozen identity.

These findings concern frozen LLM-Judge-rated response quality under the scenario-based analysis. Exact-request reuse and the single frozen response set limit inference about fresh independent generation. They do not support claims of improved real student learning, grades, satisfaction, Human-perceived improvement across the full dataset or generalisation to other courses and institutions.

## Figure legends

**Figure 1. All eight predeclared paired effects.** Points are mean left-minus-right differences in OVERALL_APPLICABLE_MEAN across 62 paired scenarios/families; error bars are pointwise 95% family-cluster percentile bootstrap intervals (10,000 replicates, seed 20260831). The dashed line marks zero. The right column gives two-sided Monte Carlo sign-flip p-values adjusted separately with Holm for the five add-one and three targeted remove-one contrasts (100,000 assignments, seed 20260831). Zero differences are retained. No response example or contrast was selected by its score.

**Figure 2. Nine-mode primary-outcome levels.** Circles and ticks show the mean and median of 62 condition observations per mode. The horizontal score range is expanded and explicitly labelled. These are descriptive summaries, with no inferential intervals, mode-ranking test or independent-149-request weighting. Configuration names follow the frozen registry.

**Figure 3. Descriptive criterion profile.** Cells show mean score and applicable count for all eight primary dimensions and nine modes. The color scale is fixed from 1 to 5. NA denotes no applicable score; Error Handling in C0 has n=0. Denominators vary across criteria and modes. This descriptive heatmap contains no criterion-level significance claims; the two secondary audits are reported separately.

**Figure 4. Frozen component activation outcomes.** Panels a–c decompose RAG, Memory and Planner activation into the frozen returned-status categories for all nine modes. Each mode has 62 conditions; inactive cases are outside the bars, and the three panels share a 0–25 activation-count scale. Labels at bar ends show total activated conditions. The states describe operational results, not independently verified retrieval, Memory or planning correctness. The full source-data and editable PDF/SVG plus PNG/TIFF exports accompany the analysis.
"""
    write_once_bytes(HERE / "C4_REAL_FINAL_RQ3_MANUSCRIPT_RESULTS_DRAFT.md", manuscript.encode())

    write_json(HERE / "F1_MANUSCRIPT_EVIDENCE_AND_CLAIM_AUDIT_V1.json", {
        "schema_version": "F1_MANUSCRIPT_EVIDENCE_AND_CLAIM_AUDIT_V1",
        "argument": "No reliable full-C4 improvement over Evidence; one targeted Planning removal result under the frozen Judge analysis.",
        "language": "English", "writing_mode": "SOURCE_GROUNDED_COMPLETED_RESULTS",
        "required_manuscript_topics": {x: True for x in ["final_sample_and_units", "nine_modes", "primary_outcome",
            "exact_eight_contrasts", "condition_summaries", "effects_ci_holm", "effect_sizes", "secondary_criteria",
            "mechanism_efficiency", "human_validation", "judge_bias", "pacing_evidence", "applicability_v2_remediation",
            "no_student_learning_claim"]},
        "evidence_allocation": {"primary_claims": "C4_REAL_F1_PRIMARY_CONTRAST_RESULTS_V1.json",
            "absolute_levels": "C4_REAL_F1_MODE_SUMMARIES_V1.json", "exploratory_criteria": "C4_REAL_F1_SECONDARY_OUTCOME_RESULTS_V1.json",
            "mechanism_scope_and_unknowns": "C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json",
            "human_measurement": "F1_FROZEN_MEASUREMENT_SUMMARY_V1.json", "authority": "F1_SOURCE_AUTHORITY_METADATA_V1.json"},
        "terminology": {"system_level_effect": "Component availability behind frozen P3 across all 62 scenarios",
            "primary_quality": "LLM-Judge-rated OVERALL_APPLICABLE_MEAN", "scenario_family": "Exact alias of frozen scenario_id, one scenario per family",
            "secondary": "Descriptive only", "sensitivity": "Frozen-cohort exploratory", "mechanism_stratum": "Router-selected descriptive, no causal effect claim"},
        "qualitative_examples_selected": 0, "unblinded_human_treatment_effects": 0,
        "new_scientific_contrasts": 0, "external_citations_invented_or_retrieved": 0,
        "raw_candidate_or_rationale_in_reports": False,
        "manuscript_sha256": sha(HERE / "C4_REAL_FINAL_RQ3_MANUSCRIPT_RESULTS_DRAFT.md")})
    print("Measurement interpretation, four complete reports and claim audit written from frozen aggregates.")


if __name__ == "__main__":
    main()
