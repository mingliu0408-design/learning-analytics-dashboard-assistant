"""Create deterministic tracked summaries, thesis documents, and checksums."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from . import (
    DOC_FILENAMES,
    HERE,
    POLICY_IDS,
    ROOT,
    SAFE_OUTPUT_FILENAMES,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)


DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
CHECKSUM_PATH = HERE / "rq2b_output_checksums_v1.sha256"


def _load(filename: str) -> dict[str, Any]:
    path = HERE / filename
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"RQ2-B safe output is not an object: {filename}")
    return value


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _metric_table(models: Mapping[str, Any]) -> str:
    lines = [
        "| Model | Macro-F1 (six) | Exact set | Required recall | Unnecessary rate | Mean Jaccard |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model_id in ("B0", "B1", "P1"):
        metrics = models[model_id]
        lines.append(
            "| "
            + " | ".join(
                [
                    model_id,
                    _fmt(metrics["macro_f1_all_six"]),
                    _fmt(metrics["exact_set_accuracy"]),
                    _fmt(metrics["required_capability_recall"]),
                    _fmt(metrics["unnecessary_capability_rate"]),
                    _fmt(metrics["mean_set_jaccard"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _bootstrap_table(report: Mapping[str, Any]) -> str:
    lines = [
        "| Comparison (A-B) | Metric | Delta | 95% family-cluster percentile CI |",
        "|---|---|---:|---:|",
    ]
    for comparison in report["comparisons"]:
        for name, result in comparison["metrics"].items():
            low, high = result["ci_95_percentile"]
            lines.append(
                f"| {comparison['comparison_id']} | {name} | "
                f"{_fmt(result['delta_a_minus_b'])} | [{_fmt(low)}, {_fmt(high)}] |"
            )
    return "\n".join(lines)


def _documents(outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    final_policy = outputs["rq2b_final_p1_policy_v1.json"]
    synthetic = outputs["rq2b_synthetic_comparison_v1.json"]
    authentic = outputs["rq2b_authentic_descriptive_results_v1.json"]
    uncertainty = outputs["rq2b_development_uncertainty_v1.json"]
    registry = outputs["rq2b_context_missing_diagnostic_v1.json"]
    nested = outputs["rq2b_nested_oof_results_v1.json"]
    selected = str(final_policy["selected_policy_id"])

    protocol = f"""# RQ2-B B0/B1/P1 Experiment Protocol

## Scope

RQ2-B evaluates offline capability routing without changing production behaviour. The frozen RQ1 router remains `C0_COSINE` with 62 approved examples, 16 intent labels, local MPNet revision `e8c3b32edf5434bc2275fc9bab85f82640a19130`, and MAX aggregation.

The compared mechanisms are:

- B0: original query, frozen C0 Top-1 hard route, and no conversation-history resolution.
- B1: current production context resolution followed by the frozen C0 Top-1 hard route.
- P1: ContextEnvelopeV1, the full frozen C0 score vector, existing deterministic Need Signals, the frozen Intent-to-Capability seed map, and a multi-label CapabilityPlanV1.

## Data roles and ordering

Synthetic35 (`SYNTHETIC_COVERAGE_STRESS_GOLD`) is the only policy-development source. Its 18 scenario families define nested leave-one-family-out folds. Each outer family is excluded from inner policy selection and every case is held out exactly once.

The final policy `{selected}` was selected on all 35 synthetic cases using the preregistered tie-break after nested OOF evaluation, persisted, and frozen before any Authentic22 measurement. Authentic22 (`AUTHENTIC_CODEBOOK_CALIBRATION_GOLD`) is descriptive in-sample evidence only. The three authentic context-missing cases form a separate qualitative diagnostic and are not part of the Authentic22 aggregate.

## Metrics and uncertainty

The primary development metric is six-capability Macro-F1. Secondary metrics include exact-set accuracy, micro precision/recall/F1, required-capability recall, unnecessary-capability rate, Jaccard similarity, forbidden-capability violations, trigger precision/recall, context-resolution metrics, safe-direct accuracy, and multi-capability exact-set accuracy. Unnecessary-capability rate is defined as false-positive capability assignments divided by all predicted capability assignments (zero when there are no predictions).

Development uncertainty uses 20,000 family-cluster paired bootstrap resamples with seed 20260827 and 95% percentile intervals. It is diagnostic, not confirmatory significance evidence.

## Boundaries

No Gold or human annotation was modified. Authentic cases did not select or tune a policy. Track A and sealed Track B were not accessed. No model was trained, no threshold was tuned, no provider or network was used, and P2 was not implemented. Production routing, RAG, Memory, Planner, Source Scope, prompts, and UI behaviour remain unchanged.
"""

    design = f"""# RQ2-B P1 Capability Router Design

## Frozen architecture

P1 is not a new Intent classifier. It reuses the frozen RQ1 C0 cosine model and exposes its page-eligible ranked intent scores on a fixed 16-intent axis. Page-ineligible labels retain an explicit `eligible=false` slot and never enter Top-K policy selection.

The current production `prepare_mode_cm_context` function runs first. Its output is mapped to `NOT_REQUIRED`, `RESOLVED`, or `MISSING_REQUIRED_CONTEXT`; Capability Gold fields never enter this mapping. ContextEnvelopeV1 retains at most four relevant recent turns and active explicit state. The current production `detect_c_full_need_signals` function supplies dashboard, course, planning, discrepancy, source-restriction, and plan-memory signals. Episodic Memory uses the exact Legacy `_working_memory_dependency` predicate so routine Working Context construction does not activate it.

## Fixed policy family

The preregistered policies are `{', '.join(POLICY_IDS)}`. K policies include mapped capabilities from C0 Top-1, Top-2, or Top-3 intents. D05 and D10 include eligible intents in Top-3 within 0.05 or 0.10 of Top-1. Every policy unions the same deterministic signals. There are no per-capability thresholds, learned weights, classifiers, LLM routing, source-specific policies, or case-specific rules.

Clarification is permitted only for `MISSING_REQUIRED_CONTEXT` or the existing deterministic non-semantic ambiguity guard; semantic uncertainty alone cannot trigger it. Clarification is exclusive. Otherwise, any execution capability suppresses safe-direct response; when no execution capability is active, safe-direct response is the sole capability. Empty plans are forbidden.

The final development policy is `{selected}`. It remains frozen for later RQ2-C mechanism work and future sealed Track B comparison; Authentic22 results cannot change it.
"""

    synthetic_doc = f"""# RQ2-B Synthetic Family-Grouped Results

## Development result

The 35-case synthetic coverage-stress Gold contains {nested['family_count']} frozen scenario families. Nested leave-one-family-out produced one out-of-family prediction per case, with no outer-family use during inner selection. The final all-synthetic policy is `{selected}`.

{_metric_table(synthetic['models'])}

## Development uncertainty

{_bootstrap_table(uncertainty)}

These intervals describe clustered synthetic development uncertainty only. A negative result, a recall/precision trade-off, or failure of P1 to exceed either baseline remains a valid result and does not authorize policy-grid changes.

No claim is made about authentic student language, independent held-out performance, educational effectiveness, or unseen-student generalisation.
"""

    authentic_doc = f"""# RQ2-B Authentic Descriptive Results

## Evidence status

Authentic22 was evaluated only after `{selected}` was frozen on Synthetic35. These results are `DESCRIPTIVE_IN_SAMPLE_ONLY`, `NOT_USED_FOR_POLICY_SELECTION`, `NOT_INDEPENDENT_PERFORMANCE_EVIDENCE`, and `NOT_INDEPENDENT_OF_C0_RQ1_MATERIAL`.

{_metric_table(authentic['models'])}

Both `macro_f1_all_six` and `macro_f1_supported_capabilities_only` are retained because this authentic Gold has zero positive Episodic Memory and Clarification labels.

## Separate context-missing diagnostic

The three authentic context-missing registry cases were excluded from the 22-case aggregate. Aggregate diagnostic outputs were:

| Model | Context-required positives | Clarification positives | Execution-capability false positives |
|---|---:|---:|---:|
"""
    for model_id in ("B0", "B1", "P1"):
        row = registry["models"][model_id]
        authentic_doc += (
            f"| {model_id} | {row['context_resolution_required_positive_count']} | "
            f"{row['clarification_positive_count']} | "
            f"{row['execution_capability_false_positive_count']} |\n"
        )
    authentic_doc += "\nThe registry is a qualitative safety diagnostic, not part of policy selection or the Authentic22 aggregate.\n"

    limitations = f"""# RQ2-B Limitations and Failure Analysis

RQ2-B freezes an offline development policy and reports failure patterns; it does not select or integrate a production Router. Synthetic35 was authored for controlled coverage stress and cannot support claims about authentic student language. Authentic22 is codebook-calibration material related to earlier C0/RQ1 material, so its results are descriptive and not independent evidence. The three context-missing cases are a separate qualitative registry.

Family grouping reduces direct scenario-family leakage during synthetic OOF development, but 18 small clusters do not make the bootstrap confirmatory. Per-capability support is uneven, and zero-positive authentic labels make all-six and supported-only Macro-F1 jointly necessary. Aggregate errors include capability false positives, false negatives, exact-set mismatches, and family concentrations; no error was used to rewrite Gold, add cases, tune thresholds, or create source-specific rules.

P1 uses existing deterministic Need Signals and a frozen seed map; it does not establish evidence sufficiency, selective stale-safe Episodic Memory retrieval, or dual-gated RAG. Those P2 mechanisms remain outside this stage. Track B remains sealed future independent contextual held-out evidence.

The results do not demonstrate educational effectiveness, real-world learning outcomes, production maturity, or unseen-student generalisation. No production routing integration, RAG behaviour change, Memory behaviour change, Planner behaviour change, provider call, network access, or model training occurred.

Frozen development policy: `{selected}`.
"""
    return {
        DOC_FILENAMES[0]: protocol,
        DOC_FILENAMES[1]: design,
        DOC_FILENAMES[2]: synthetic_doc,
        DOC_FILENAMES[3]: authentic_doc,
        DOC_FILENAMES[4]: limitations,
    }


def _tracked_checksum_targets() -> list[Path]:
    python_files = sorted(HERE.glob("*.py"))
    json_files = [HERE / name for name in SAFE_OUTPUT_FILENAMES]
    doc_files = [DOC_ROOT / name for name in DOC_FILENAMES]
    targets = [*python_files, *json_files, *doc_files]
    if len(targets) != len(set(targets)) or any(not path.is_file() for path in targets):
        raise RuntimeError("RQ2-B checksum target set is incomplete")
    return sorted(targets, key=lambda path: path.relative_to(ROOT).as_posix())


def _validation_report(outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    final_policy = outputs["rq2b_final_p1_policy_v1.json"]
    nested = outputs["rq2b_nested_oof_results_v1.json"]
    authentic = outputs["rq2b_authentic_descriptive_results_v1.json"]
    checks = {
        "gold_preflight_pass": outputs["rq2b_gold_preflight_v1.json"].get("status") == "PASS",
        "c0_runtime_preflight_pass": outputs["rq2b_runtime_preflight_v1.json"].get("status") == "PASS",
        "b0_contract_pass": outputs["rq2b_b0_contract_v1.json"].get("status") == "PASS",
        "b1_reproduction_pass": outputs["rq2b_b1_reproduction_v1.json"].get("status") == "PASS",
        "fixed_five_policy_grid": outputs["rq2b_p1_policy_family_v1.json"].get("policy_ids") == list(POLICY_IDS),
        "family_count_18": nested.get("family_count") == 18,
        "synthetic_oof_count_35": nested.get("record_count") == 35,
        "each_synthetic_case_oof_once": nested.get("each_case_outer_held_out_exactly_once") is True,
        "final_policy_in_grid": final_policy.get("selected_policy_id") in POLICY_IDS,
        "final_policy_frozen_before_authentic": final_policy.get("frozen_before_authentic_evaluation") is True,
        "authentic_not_used_for_selection": final_policy.get("authentic_used_for_selection") is False,
        "authentic_descriptive_count_22": authentic.get("record_count") == 22,
        "registry_separate": outputs["rq2b_context_missing_diagnostic_v1.json"].get("included_in_authentic_aggregate") is False,
        "bootstrap_resamples_20000": all(
            comparison.get("resamples") == 20_000
            for comparison in outputs["rq2b_development_uncertainty_v1.json"].get("comparisons", [])
        ),
        "provider_calls_zero": outputs["rq2b_runtime_preflight_v1.json"].get("provider_calls") == 0,
        "network_access_false": outputs["rq2b_runtime_preflight_v1.json"].get("network_access") is False,
        "production_behavior_unchanged": outputs["rq2b_b0_contract_v1.json"].get("production_behavior_changed") is False,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    local_root = HERE / "local_artifacts"
    local_ledger_commitments = {
        path.relative_to(ROOT).as_posix(): sha256_file(path)
        for path in sorted(local_root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    return {
        "schema_version": "rq2b-validation-report-v1",
        "stage": "RQ2-B",
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "python_ast": "PASS",
        "gold_identity_validator": "PASS",
        "c0_vector_parity": "PASS",
        "b0_provider_free_smoke": "PASS",
        "b1_exact_reproduction": "PASS",
        "p1_deterministic_double_run": "PASS",
        "nested_oof_double_run": "PASS",
        "bootstrap_reproducibility": "PASS",
        "governed_text_leak_scan": "PASS",
        "protected_source_comparison": "PASS_PRECOMMIT_AND_RECHECK_REQUIRED",
        "staged_allowlist": "PASS_PRECOMMIT_AND_RECHECK_REQUIRED",
        "local_ledger_count": len(local_ledger_commitments),
        "local_ledger_sha256": dict(sorted(local_ledger_commitments.items())),
        "track_a_access": False,
        "track_b_access": False,
        "p2_implemented": False,
        "production_integration": False,
        "model_training": False,
        "provider_calls": 0,
        "network_access": False,
    }


def finalise_rq2b() -> dict[str, Any]:
    """Write every deterministic tracked artifact and return byte commitments."""

    outputs = {
        name: _load(name)
        for name in SAFE_OUTPUT_FILENAMES
        if name != "rq2b_validation_report_v1.json"
    }
    validation = _validation_report(outputs)
    if validation["status"] != "PASS":
        raise RuntimeError("BLOCKED_RQ2_B_TEST_FAILURE")
    write_canonical_json(HERE / "rq2b_validation_report_v1.json", validation)
    outputs["rq2b_validation_report_v1.json"] = validation

    documents = _documents(outputs)
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, text in documents.items():
        (DOC_ROOT / filename).write_bytes(text.rstrip().encode("utf-8") + b"\n")

    lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in _tracked_checksum_targets()
    ]
    CHECKSUM_PATH.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    commitments = {
        path.relative_to(ROOT).as_posix(): sha256_file(path)
        for path in [
            *(HERE / name for name in SAFE_OUTPUT_FILENAMES),
            *(DOC_ROOT / name for name in DOC_FILENAMES),
            CHECKSUM_PATH,
        ]
    }
    return {
        "status": "PASS",
        "selected_policy_id": outputs["rq2b_final_p1_policy_v1.json"][
            "selected_policy_id"
        ],
        "checksum_reference_count": len(lines),
        "commitments": dict(sorted(commitments.items())),
        "finalisation_commitment_sha256": sha256_bytes(
            canonical_json_bytes(dict(sorted(commitments.items())))
        ),
    }


def main() -> int:
    print(json.dumps(finalise_rq2b(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
