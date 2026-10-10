"""Single research orchestration for the frozen three-phase RQ2-D4 evaluation."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Mapping, Sequence

from . import (
    CAPABILITIES,
    COMBINED_SOURCE_SHA256,
    COMPARISONS,
    GOLD_BUNDLE_SHA256,
    GROUPING_SHA256,
    HERE,
    LABEL_GOLD_SHA256,
    LOCAL_RESULTS_RELATIVE,
    METHODS,
    METRIC_IMPLEMENTATION_SHA256,
    MPNET_REVISION,
    OFFLINE_ENVIRONMENT,
    P1_POLICY_ID,
    P1_POLICY_SHA256,
    ROOT,
    START_HEAD,
    STATISTICAL_CONTRACT_SHA256,
    canonical_json_bytes,
    sha256_file,
    write_new,
)
from .score_capability_predictions import LOCAL_RESULT_NAMES
from .starting_state import verify_starting_state_and_inputs


DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"
FIGURE_ROOT = DOC_ROOT / "figures"
DOC_NAMES = (
    "RQ2D4_TRACK_B_FINAL_EVALUATION_RESULTS.md",
    "RQ2D4_STATISTICAL_COMPARISONS.md",
    "RQ2D4_ERROR_AND_CONFUSION_ANALYSIS.md",
    "RQ2D4_RESEARCH_CONCLUSIONS_AND_LIMITATIONS.md",
)
FIGURE_NAMES = (
    "rq2d4_method_overview.png",
    "rq2d4_per_capability_f1.png",
    "rq2d4_context_subset_comparison.png",
)
PYTHON_NAMES = (
    "__init__.py",
    "starting_state.py",
    "build_feature_view.py",
    "run_capability_predictions.py",
    "score_capability_predictions.py",
    "error_analysis.py",
    "run_rq2d4_research_evaluation.py",
    "validate_rq2d4_results.py",
    "test_rq2d4_research_unittest.py",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_phase(module: str) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update(OFFLINE_ENVIRONMENT)
    completed = subprocess.run(
        [sys.executable, "-m", module],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        safe_tail = "\n".join(completed.stderr.splitlines()[-12:])
        raise RuntimeError(
            f"BLOCKED_RQ2_D4_RUNTIME: phase {module} exited {completed.returncode}: {safe_tail}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("BLOCKED_RQ2_D4_RUNTIME")
    receipt = json.loads(lines[-1])
    if receipt.get("status") != "PASS":
        raise RuntimeError("BLOCKED_RQ2_D4_RUNTIME")
    return receipt


def _safe_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key
        in {
            "sha256",
            "size_bytes",
            "record_count",
            "group_count",
            "cases_per_group",
            "regular_non_symlink",
        }
    }


def _safe_phase_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in receipt.items():
        if key in {"relative_path", "feature_view_relative_path"}:
            continue
        if isinstance(value, Mapping):
            safe[key] = {
                nested_key: _safe_identity(nested_value)
                if isinstance(nested_value, Mapping)
                else nested_value
                for nested_key, nested_value in value.items()
                if nested_key != "relative_path"
            }
        else:
            safe[key] = value
    return safe


def _format(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _metrics_table(methods: Mapping[str, Mapping[str, Any]]) -> str:
    keys = (
        ("Macro-F1", "macro_f1_all_six"),
        ("Exact-set accuracy", "exact_set_accuracy"),
        ("Micro precision", "micro_precision"),
        ("Micro recall", "micro_recall"),
        ("Micro F1", "micro_f1"),
        ("Required-capability recall", "required_capability_recall"),
        ("Unnecessary-capability rate", "unnecessary_capability_rate"),
        ("Mean set Jaccard", "mean_set_jaccard"),
        ("Median set Jaccard", "median_set_jaccard"),
        ("Forbidden-capability violation rate", "forbidden_capability_violation_rate"),
        ("Context-resolution accuracy", "context_resolution_accuracy"),
        ("Context-resolution positive recall", "context_resolution_positive_recall"),
        ("Clarification precision", "clarification_precision"),
        ("Clarification recall", "clarification_recall"),
        ("Unnecessary-clarification rate", "unnecessary_clarification_rate"),
    )
    lines = ["| Metric | B0 | B1 | P1 |", "|---|---:|---:|---:|"]
    for label, key in keys:
        lines.append(
            "| " + label + " | " + " | ".join(_format(methods[m][key]) for m in METHODS) + " |"
        )
    return "\n".join(lines)


def _comparison_table(comparisons: Mapping[str, Any]) -> str:
    lines = [
        "| Comparison | Δ Macro-F1 | Δ Exact-set | Δ Required recall | Δ Unnecessary rate | Wins/Ties/Losses | Rank-biserial | Raw p |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in COMPARISONS:
        row = comparisons["comparisons"][name]
        delta = row["observed_deltas"]
        outcomes = row["wins_ties_losses"]
        effect = outcomes["matched_rank_biserial"]["value"]
        p_value = row["clustered_sign_flip"]["p_value"]
        lines.append(
            f"| {name} | {_format(delta['macro_f1_all_six'])} | "
            f"{_format(delta['exact_set_accuracy'])} | "
            f"{_format(delta['required_capability_recall'])} | "
            f"{_format(delta['unnecessary_capability_rate'])} | "
            f"{outcomes['wins']}/{outcomes['ties']}/{outcomes['losses']} | "
            f"{_format(effect)} | {_format(p_value)} |"
        )
    return "\n".join(lines)


def _bootstrap_table(comparisons: Mapping[str, Any]) -> str:
    lines = [
        "| Comparison | Metric | Lower 95% | Upper 95% |",
        "|---|---|---:|---:|",
    ]
    for comparison in COMPARISONS:
        metrics = comparisons["comparisons"][comparison]["whole_cluster_bootstrap"]["metrics"]
        for metric, values in metrics.items():
            lines.append(
                f"| {comparison} | {metric} | {_format(values['lower_95_type7'])} | "
                f"{_format(values['upper_95_type7'])} |"
            )
    return "\n".join(lines)


def _per_capability_table(methods: Mapping[str, Mapping[str, Any]]) -> str:
    lines = [
        "| Capability | Support | B0 F1 | B1 F1 | P1 F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for capability in CAPABILITIES:
        support = methods["B0"]["per_capability"][capability]["support"]
        values = [methods[method]["per_capability"][capability]["f1"] for method in METHODS]
        lines.append(
            f"| {capability} | {support} | " + " | ".join(_format(value) for value in values) + " |"
        )
    return "\n".join(lines)


def _negative_findings(methods: Mapping[str, Mapping[str, Any]], comparisons: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    for comparison in COMPARISONS:
        row = comparisons["comparisons"][comparison]
        for label, key in (
            ("Macro-F1", "macro_f1_all_six"),
            ("Exact-set accuracy", "exact_set_accuracy"),
            ("Required-capability recall", "required_capability_recall"),
        ):
            if float(row["observed_deltas"][key]) <= 0:
                findings.append(f"{comparison} did not improve {label}.")
        if float(row["clustered_sign_flip"]["p_value"]) >= 0.05:
            findings.append(f"{comparison} clustered sign-flip result was not below 0.05.")
    return findings or ["No registered comparison had a non-positive primary descriptive delta."]


def _write_documents(
    methods: Mapping[str, Mapping[str, Any]],
    comparisons: Mapping[str, Any],
    errors: Mapping[str, Any],
) -> None:
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    primary = comparisons["comparisons"]["P1_VS_B1"]
    primary_delta = primary["observed_deltas"]["macro_f1_all_six"]
    direction = "higher" if primary_delta > 0 else "lower" if primary_delta < 0 else "equal"
    results = f"""# RQ2-D4 Track-B Final Capability-Routing Results

## Scope

This source-blinded held-out evaluation compares frozen B0, B1, and `{P1_POLICY_ID}` over 48 Track-B cases. RQ1 evaluated intent ranking; this RQ2 result evaluates capability routing. RQ3 end-to-end response-quality ablation has not started.

## Complete method metrics

{_metrics_table(methods)}

## Per-capability F1

{_per_capability_table(methods)}

## Primary finding

P1 Macro-F1 was {direction} than B1 by {_format(primary_delta)}. This is a held-out capability-routing result, not evidence about generated-answer quality, learning outcomes, or production readiness.

## Frozen execution boundaries

No post-result tuning, policy change, threshold change, Gold change, statistical-seed change, P2/RAG/Memory execution, LLM Judge, or production integration occurred.
"""
    statistics = f"""# RQ2-D4 Statistical Comparisons

The primary comparison is P1 versus B1 and retains its unadjusted two-sided clustered sign-flip p-value. Holm adjustment applies only to the two secondary comparisons. Confidence intervals use 50,000 whole-cluster resamples over 24 two-case contrast groups; sign-flip tests use 100,000 draws.

## Observed differences and sign-flip results

{_comparison_table(comparisons)}

## Type-7 percentile confidence intervals

{_bootstrap_table(comparisons)}

## Holm-adjusted secondary results

```json
{json.dumps(comparisons['secondary_holm'], indent=2, sort_keys=True)}
```

These tests are scientific summaries, not a policy-replacement or production-deployment gate.
"""
    error_lines: list[str] = []
    for method in METHODS:
        summary = errors["per_method_capability_set_errors"][method]
        error_lines.append(
            f"- {method}: exact {summary['exact_set_correct_count']}; under-prediction "
            f"{summary['under_prediction_count']}; over-prediction {summary['over_prediction_count']}; "
            f"mixed {summary['mixed_error_count']}."
        )
    context_lines: list[str] = []
    for subset, payload in errors["context_subsets"].items():
        values = ", ".join(
            f"{method} Macro-F1={_format(payload['methods'][method]['macro_f1_all_six'])}"
            for method in METHODS
        )
        context_lines.append(f"- {subset} (n={payload['record_count']}): {values}.")
    clarification_lines = [
        f"- {method}: recall={_format(errors['clarification']['methods'][method]['clarification_recall'])}; "
        f"false negatives={errors['clarification']['methods'][method]['false_negative_count']}; "
        f"unnecessary clarifications={errors['clarification']['methods'][method]['unnecessary_clarification_count']}."
        for method in METHODS
    ]
    error_doc = f"""# RQ2-D4 Error and Confusion Analysis

All material below is aggregate-only; no case identifier or governed text is reported.

## Capability-set error patterns

{chr(10).join(error_lines)}

## Context-required subsets

{chr(10).join(context_lines)}

## Clarification

Gold clarification support is 4 cases.

{chr(10).join(clarification_lines)}

## Contrast-pair consistency

```json
{json.dumps(errors['contrast_pair_consistency'], indent=2, sort_keys=True)}
```

The common Gold-set to predicted-set transitions in the safe aggregate result use capability names and counts only.
"""
    negatives = "\n".join(f"- {item}" for item in _negative_findings(methods, comparisons))
    conclusion = f"""# RQ2-D4 Research Conclusions and Limitations

## Thesis-level conclusion

The experiment provides independent held-out evidence about capability-set prediction for the frozen B0, B1, and P1 methods. The primary P1-versus-B1 Macro-F1 delta is {_format(primary_delta)}. Interpretation must jointly consider exact-set accuracy, required-capability recall, unnecessary-capability rate, clustered confidence intervals, and the Jaccard-utility sign-flip result.

## Negative or null findings

{negatives}

Negative and non-significant findings are retained as valid results. No threshold, policy, comparison, metric, seed, or Gold label was changed after observing Track-B outcomes.

## Limitations

- The evaluation contains 48 source-blinded cases arranged in 24 contrast groups.
- Capability routing is not the same construct as RAG evidence quality, persistent-memory retrieval quality, or final answer quality.
- P2, RAG, and Memory execution count is zero; their diagnostics remain deferred to RQ3.
- The study does not establish student learning effects, unseen-population generalisation, or production readiness.
- The clustered sign-flip utility is exact six-capability set Jaccard; it does not directly test Macro-F1.
- Human-adjudicated Gold remains subject to annotation and construct-validity limitations.

## Stage boundary

No RQ3 work, LLM Judge execution, end-to-end generation experiment, or production integration has started.
"""
    payloads = {
        DOC_NAMES[0]: results,
        DOC_NAMES[1]: statistics,
        DOC_NAMES[2]: error_doc,
        DOC_NAMES[3]: conclusion,
    }
    for name, value in payloads.items():
        write_new(DOC_ROOT / name, value.encode("utf-8"), mode=0o644)


def _write_figures(
    methods: Mapping[str, Mapping[str, Any]], errors: Mapping[str, Any]
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    colours = {"B0": "#7f8c8d", "B1": "#2980b9", "P1": "#c0392b"}

    overview_metrics = (
        ("Macro-F1", "macro_f1_all_six"),
        ("Exact set", "exact_set_accuracy"),
        ("Required recall", "required_capability_recall"),
        ("Mean Jaccard", "mean_set_jaccard"),
    )
    x = np.arange(len(overview_metrics))
    width = 0.24
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    for index, method in enumerate(METHODS):
        ax.bar(
            x + (index - 1) * width,
            [methods[method][key] for _, key in overview_metrics],
            width,
            label=method,
            color=colours[method],
        )
    ax.set_ylim(0, 1)
    ax.set_ylabel("Score")
    ax.set_xticks(x, [label for label, _ in overview_metrics])
    ax.set_title("RQ2-D4 frozen method comparison")
    ax.legend()
    fig.savefig(FIGURE_ROOT / FIGURE_NAMES[0], dpi=180, metadata={"Software": "RQ2-D4"})
    plt.close(fig)

    x = np.arange(len(CAPABILITIES))
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    for index, method in enumerate(METHODS):
        ax.bar(
            x + (index - 1) * width,
            [methods[method]["per_capability"][capability]["f1"] for capability in CAPABILITIES],
            width,
            label=method,
            color=colours[method],
        )
    ax.set_ylim(0, 1)
    ax.set_ylabel("F1")
    ax.set_xticks(x, CAPABILITIES, rotation=24, ha="right")
    ax.set_title("Per-capability F1 on Track-B")
    ax.legend()
    fig.savefig(FIGURE_ROOT / FIGURE_NAMES[1], dpi=180, metadata={"Software": "RQ2-D4"})
    plt.close(fig)

    subsets = ("CONTEXT_RESOLUTION_REQUIRED_YES", "CONTEXT_RESOLUTION_REQUIRED_NO")
    x = np.arange(len(subsets))
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    for index, method in enumerate(METHODS):
        ax.bar(
            x + (index - 1) * width,
            [errors["context_subsets"][subset]["methods"][method]["macro_f1_all_six"] for subset in subsets],
            width,
            label=method,
            color=colours[method],
        )
    ax.set_ylim(0, 1)
    ax.set_ylabel("Macro-F1")
    ax.set_xticks(x, ["Context required (n=39)", "Context not required (n=9)"])
    ax.set_title("Context-subset comparison")
    ax.legend()
    fig.savefig(FIGURE_ROOT / FIGURE_NAMES[2], dpi=180, metadata={"Software": "RQ2-D4"})
    plt.close(fig)


def _all_checksum_targets() -> list[Path]:
    targets = [HERE / name for name in PYTHON_NAMES]
    targets += [
        HERE / "rq2d4_final_metrics_v1.json",
        HERE / "rq2d4_final_comparisons_v1.json",
        HERE / "rq2d4_final_error_summary_v1.json",
        HERE / "rq2d4_result_freeze_v1.json",
        HERE / "rq2d4_runtime_report_v1.json",
        HERE / "rq2d4_per_capability_metrics_v1.csv",
    ]
    targets += [DOC_ROOT / name for name in DOC_NAMES]
    targets += [FIGURE_ROOT / name for name in FIGURE_NAMES]
    return targets


def run_research_evaluation() -> dict[str, Any]:
    result_targets = [
        HERE / name for name in (
            "rq2d4_final_metrics_v1.json",
            "rq2d4_final_comparisons_v1.json",
            "rq2d4_final_error_summary_v1.json",
            "rq2d4_result_freeze_v1.json",
            "rq2d4_runtime_report_v1.json",
            "rq2d4_per_capability_metrics_v1.csv",
            "rq2d4_output_checksums_v1.sha256",
        )
    ] + [DOC_ROOT / name for name in DOC_NAMES] + [FIGURE_ROOT / name for name in FIGURE_NAMES]
    local_targets = [
        ROOT / LOCAL_RESULTS_RELATIVE / name for name in (*LOCAL_RESULT_NAMES.values(), "rq2d4_execution_manifest_v1.json")
    ]
    if any(path.exists() or path.is_symlink() for path in result_targets + local_targets):
        raise RuntimeError("BLOCKED_RQ2_D4_RUNTIME: prior result target present")

    started_at = _utc_now()
    starting = verify_starting_state_and_inputs()

    from evaluation.capability_routing_rq2d3_r3_v1.development_reexecution_parity_v1_1 import (
        run_development_reexecution_parity_v1_1,
    )
    from evaluation.capability_routing_rq2d3_r3_v1.prearm_runtime_smoke import (
        run_prearm_runtime_smoke_v1_1,
    )

    development = run_development_reexecution_parity_v1_1()
    if development.get("status") != "PASS" or development.get("prediction_mismatch_count") != 0:
        raise RuntimeError("BLOCKED_RQ2_D4_DEVELOPMENT_PARITY")
    smoke = run_prearm_runtime_smoke_v1_1()
    if smoke.get("status") != "PASS" or smoke.get("network_attempts") != 0:
        raise RuntimeError("BLOCKED_RQ2_D4_RUNTIME")

    phase_a = _run_phase("evaluation.capability_routing_rq2d4_research_v1.build_feature_view")
    phase_b = _run_phase("evaluation.capability_routing_rq2d4_research_v1.run_capability_predictions")
    phase_c = _run_phase("evaluation.capability_routing_rq2d4_research_v1.score_capability_predictions")
    if len({phase_a["process_id"], phase_b["process_id"], phase_c["process_id"]}) != 3:
        raise RuntimeError("BLOCKED_RQ2_D4_RUNTIME")

    local_root = ROOT / LOCAL_RESULTS_RELATIVE
    local_metrics = _json(local_root / LOCAL_RESULT_NAMES["metrics"])
    local_comparisons = _json(local_root / LOCAL_RESULT_NAMES["comparisons"])
    local_errors = _json(local_root / LOCAL_RESULT_NAMES["errors"])
    local_context = _json(local_root / LOCAL_RESULT_NAMES["context"])
    per_capability_payload = (local_root / LOCAL_RESULT_NAMES["per_capability"]).read_bytes()
    methods = local_metrics["methods"]

    completed_at = _utc_now()
    safe_starting = {
        "status": starting["status"],
        "starting_branch": starting["starting_branch"],
        "starting_head": starting["starting_head"],
        "gold_bundle_sha256": starting["gold_bundle_sha256"],
        "record_counts": {
            "label_only": starting["label_record_count"],
            "combined": starting["combined_record_count"],
            "grouping": starting["grouping_record_count"],
        },
        "contrast_group_count": starting["contrast_group_count"],
        "cases_per_group": starting["cases_per_group"],
        "c0_candidate_records": starting["c0_candidate_records"],
        "c0_label_count": starting["c0_label_count"],
        "c0_embedding_shape": starting["c0_embedding_shape"],
        "c0_aggregation": starting["c0_aggregation"],
        "mpnet_revision": starting["mpnet_revision"],
        "p1_policy": starting["p1_policy"],
        "input_hashes": {
            name: value["sha256"] for name, value in starting["identities"].items()
        },
    }
    runtime_report = {
        "schema_version": "rq2d4-runtime-report-v1",
        "status": "PASS",
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "starting_state": safe_starting,
        "development_parity": development,
        "runtime_smoke": smoke,
        "phases": {
            "feature_projection": _safe_phase_receipt(phase_a),
            "prediction": _safe_phase_receipt(phase_b),
            "scoring": _safe_phase_receipt(phase_c),
        },
        "phase_process_count": 3,
        "all_phase_processes_distinct": True,
        "python_version": platform.python_version(),
        "torch_version": importlib.metadata.version("torch"),
        "sentence_transformers_version": importlib.metadata.version("sentence-transformers"),
        "transformers_version": importlib.metadata.version("transformers"),
        "model_revision": MPNET_REVISION,
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_b_prediction_execution_count": 1,
        "track_b_scoring_execution_count": 1,
        "pre_prediction_recovery": {
            "failed_attempt_count": 1,
            "failure_stage": "PHASE_B_INPUT_SCHEMA_BEFORE_FIRST_PREDICTION",
            "reason": "FROZEN_HISTORY_JSON_STRING_REQUIRED_DESERIALISATION",
            "failed_feature_view_sha256": "ac98156f1567f78ea45b2d87a959bad71193f00a73913028fcdde39ab431f42b",
            "failed_feature_view_record_count": 48,
            "combined_source_open_count": 1,
            "prediction_files_created": 0,
            "label_gold_open_count": 0,
            "grouping_open_count": 0,
            "scoring_execution_count": 0,
            "policy_or_threshold_change": False,
        },
    }
    final_metrics = {
        "schema_version": "rq2d4-final-metrics-v1",
        "status": "FROZEN_TRACK_B_FINAL_RESULT",
        "data_role": "INDEPENDENT_SOURCE_BLINDED_HELDOUT_CAPABILITY_EVALUATION",
        "record_count": 48,
        "methods": methods,
        "context_subsets": local_context,
        "clarification": local_errors["clarification"],
        "frozen_input_identities": safe_starting,
        "p2_secondary_diagnostics": "DEFERRED_TO_RQ3_END_TO_END_ABLATION",
        "p2_execution_count": 0,
        "p2_performance_claims": False,
    }
    final_comparisons = {
        **local_comparisons,
        "status": "FROZEN_TRACK_B_FINAL_RESULT",
        "primary_comparison": "P1_VS_B1",
        "secondary_comparisons": ["B1_VS_B0", "P1_VS_B0"],
        "policy_replacement_gate": False,
    }
    final_errors = {**local_errors, "status": "FROZEN_TRACK_B_FINAL_RESULT"}

    write_new(HERE / "rq2d4_final_metrics_v1.json", canonical_json_bytes(final_metrics), mode=0o644)
    write_new(HERE / "rq2d4_final_comparisons_v1.json", canonical_json_bytes(final_comparisons), mode=0o644)
    write_new(HERE / "rq2d4_final_error_summary_v1.json", canonical_json_bytes(final_errors), mode=0o644)
    write_new(HERE / "rq2d4_runtime_report_v1.json", canonical_json_bytes(runtime_report), mode=0o644)
    write_new(HERE / "rq2d4_per_capability_metrics_v1.csv", per_capability_payload, mode=0o644)

    _write_documents(methods, final_comparisons, final_errors)
    _write_figures(methods, final_errors)

    pre_freeze_targets = [
        HERE / "rq2d4_final_metrics_v1.json",
        HERE / "rq2d4_final_comparisons_v1.json",
        HERE / "rq2d4_final_error_summary_v1.json",
        HERE / "rq2d4_runtime_report_v1.json",
        HERE / "rq2d4_per_capability_metrics_v1.csv",
        *[DOC_ROOT / name for name in DOC_NAMES],
        *[FIGURE_ROOT / name for name in FIGURE_NAMES],
    ]
    result_hashes = {str(path.relative_to(ROOT)): sha256_file(path) for path in pre_freeze_targets}
    freeze = {
        "schema_version": "rq2d4-result-freeze-v1",
        "status": "FROZEN",
        "commit": START_HEAD,
        "commit_role": "EXECUTION_BASE_COMMIT",
        "result_commit_reported_in_git_state": True,
        "completion_timestamp": completed_at,
        "input_hashes": {
            "gold_bundle": GOLD_BUNDLE_SHA256,
            "label_only_gold": LABEL_GOLD_SHA256,
            "combined_source": COMBINED_SOURCE_SHA256,
            "grouping": GROUPING_SHA256,
            "p1_policy": P1_POLICY_SHA256,
        },
        "method_identities": {
            "B0": "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION",
            "B1": "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE",
            "P1": P1_POLICY_ID,
        },
        "metric_identity": METRIC_IMPLEMENTATION_SHA256,
        "statistical_identity": STATISTICAL_CONTRACT_SHA256,
        "python_version": platform.python_version(),
        "torch_version": runtime_report["torch_version"],
        "sentence_transformers_version": runtime_report["sentence_transformers_version"],
        "model_revision": MPNET_REVISION,
        "result_hashes": result_hashes,
        "first_successful_result": True,
        "reproduction_may_verify_but_not_replace": True,
        "post_result_tuning": False,
        "policy_change": False,
        "threshold_change": False,
        "gold_change": False,
        "statistical_seed_change": False,
    }
    write_new(HERE / "rq2d4_result_freeze_v1.json", canonical_json_bytes(freeze), mode=0o644)

    execution_manifest = {
        "schema_version": "rq2d4-local-execution-manifest-v1",
        "status": "COMPLETED",
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "starting_head": START_HEAD,
        "development_parity_status": development["status"],
        "runtime_smoke_status": smoke["status"],
        "phase_receipts": {"A": phase_a, "B": phase_b, "C": phase_c},
        "provider_calls": 0,
        "network_access": False,
        "post_result_tuning": False,
        "pre_prediction_recovery": runtime_report["pre_prediction_recovery"],
    }
    write_new(
        local_root / "rq2d4_execution_manifest_v1.json",
        canonical_json_bytes(execution_manifest),
    )

    checksum_lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT)}"
        for path in sorted(_all_checksum_targets(), key=lambda item: str(item.relative_to(ROOT)))
    ]
    checksum_payload = ("\n".join(checksum_lines) + "\n").encode("utf-8")
    write_new(HERE / "rq2d4_output_checksums_v1.sha256", checksum_payload, mode=0o644)
    return {
        "status": "READY_FOR_CHATGPT_RQ2_D4_REVIEW",
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "development_parity": "PASS",
        "runtime_smoke": "PASS",
        "phase_process_count": 3,
        "track_b_prediction_execution_count": 1,
        "track_b_scoring_execution_count": 1,
        "safe_output_checksum_count": len(checksum_lines),
        "p2_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def main() -> int:
    print(json.dumps(run_research_evaluation(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
