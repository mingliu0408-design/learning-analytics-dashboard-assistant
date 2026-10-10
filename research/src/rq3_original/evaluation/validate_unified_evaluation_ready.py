"""Single blocking preflight for the final 62 × 6 unified evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.audit_unified_gold_labels import audit_gold_labels  # noqa: E402
from evaluation.export_unified_human_validation_sample import export_package  # noqa: E402
from evaluation.evaluate_unified_mechanisms import (  # noqa: E402
    OUTPUT as MECHANISM_V2_OUTPUT,
    V1_OUTPUT as LEGACY_MECHANISM_V1_OUTPUT,
    course_context_score,
    metric_definition_guard_score,
    negative_control_score,
    plan_state_consistency_score,
    retrieval_grounding_score,
    route_matches,
)
from evaluation.summarise_unified_evaluation_v1 import MECHANISM_INPUT as SUMMARY_MECHANISM_INPUT  # noqa: E402
from evaluation.statistical_tests_unified_v1 import MECHANISM_INPUT as STATISTICS_MECHANISM_INPUT  # noqa: E402
from evaluation.judge_unified_response_quality import build_blind_quality_payload  # noqa: E402
from evaluation.unified_evaluation_contract import (  # noqa: E402
    EXPECTED_MODES,
    EXPECTED_SCENARIO_COUNT,
    GOLD_LABELS_PATH,
    MECHANISM_DIMENSIONS,
    QUALITY_DIMENSIONS,
    REFERENCE_EVIDENCE_PATH,
    SCENARIOS_PATH,
    file_sha256,
    load_gold_overlay,
    load_jsonl,
    rows_by_id,
    validate_dimension_payload,
)


JSON_REPORT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_preflight_report_v2.json"
MARKDOWN_REPORT = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_preflight_report_v2.md"
COMPARISONS = PROJECT_ROOT / "evaluation" / "unified_primary_comparisons.json"
TEST_HASHES = PROJECT_ROOT / "evaluation" / "frozen_production_test_hashes_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_preflight(
    scenarios_path: Path = SCENARIOS_PATH,
    gold_path: Path = GOLD_LABELS_PATH,
    reference_path: Path = REFERENCE_EVIDENCE_PATH,
    *,
    check_frozen_tests: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, function: Callable[[], Any]) -> None:
        try:
            detail = function()
            checks.append({"name": name, "passed": True, "detail": detail})
        except Exception as exc:
            checks.append({"name": name, "passed": False, "detail": f"{type(exc).__name__}: {exc}"})

    scenarios = load_jsonl(scenarios_path)
    labels = load_jsonl(gold_path)
    reference_rows = load_jsonl(reference_path)
    gold = load_gold_overlay(gold_path)
    references = rows_by_id(reference_rows)

    def scenario_identity() -> str:
        ids = [str(row.get("scenario_id", "")) for row in scenarios]
        if len(ids) != EXPECTED_SCENARIO_COUNT or len(set(ids)) != EXPECTED_SCENARIO_COUNT:
            raise ValueError(f"Expected 62 unique scenarios, got {len(ids)} rows/{len(set(ids))} unique")
        return "62 unique scenarios"

    check("exactly_62_unique_scenarios", scenario_identity)
    check("exactly_6_expected_modes", lambda: EXPECTED_MODES if len(EXPECTED_MODES) == 6 and len(set(EXPECTED_MODES)) == 6 else (_ for _ in ()).throw(ValueError("Mode contract invalid")))

    audit = audit_gold_labels(scenarios, labels, reference_rows)
    check("complete_gold_overlay", lambda: "audit PASS" if audit["blocking_issue_count"] == 0 else (_ for _ in ()).throw(ValueError(audit["blocking_issues"])))
    check(
        "no_unresolved_manual_review_findings",
        lambda: "none" if not audit["manual_review_findings"] else (_ for _ in ()).throw(ValueError(audit["manual_review_findings"])),
    )

    def no_circular_derivation() -> str:
        source = (PROJECT_ROOT / "evaluation" / "build_unified_benchmark.py").read_text(encoding="utf-8")
        forbidden = [name for name in ("classify_query", "should_use_course_retrieval") if name in source]
        if forbidden:
            raise ValueError(f"Production classifiers referenced by gold builder: {forbidden}")
        return "gold builder contains no production classifier/retrieval-gate calls"

    check("no_circular_gold_derivation", no_circular_derivation)
    check("benchmark_gold_reference_hashes", lambda: {
        "scenario_set_sha256": file_sha256(scenarios_path),
        "gold_labels_sha256": file_sha256(gold_path),
        "reference_evidence_sha256": file_sha256(reference_path),
    })

    def blind_equivalence_check() -> str:
        scenario = scenarios[0]
        scenario_id = str(scenario["scenario_id"])
        payloads: list[str] = []
        for mode in EXPECTED_MODES:
            record = {
                **scenario,
                "mode": mode,
                "response": f"Response from {mode}",
                "rq1_evidence_summary": {"c_full_mode_c_route": mode},
                "memory_resolution": {"secret": mode},
                "retrieval_result": {"course_retrieval": mode},
                "retrieved_context_chunks": [{"mode": mode}],
            }
            payload = build_blind_quality_payload(record, gold[scenario_id], references[scenario_id])
            payload.pop("final_assistant_response")
            serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if any(forbidden in serialised for forbidden in ("c_full_mode_c_route", "memory_resolution", "course_retrieval")):
                raise ValueError("Mode-specific nested metadata leaked into blind payload")
            payloads.append(serialised)
        if len(set(payloads)) != 1:
            raise ValueError("Non-response blind payload differs across modes")
        return "six non-response blind payloads are byte-equivalent"

    check("mode_blind_reference_payload_equivalence", blind_equivalence_check)

    def adversarial_mechanism_check() -> str:
        if route_matches("hybrid_course_and_planning", "course_material_retrieval"):
            raise ValueError("Hybrid route passed as pure retrieval")
        citation_reference = {
            "reference_course_evidence": [{"chunk_id": "x", "title": "W5 Core Reading", "text": "W5 Core Reading: Paper X, Author Y, 2020."}],
            "reference_chunk_ids": ["x"],
        }
        hallucination = {"retrieval_used": True, "response": "The paper proves that multimodal analytics improves achievement."}
        refusal = {"retrieval_used": True, "response": "The indexed material contains only the title and citation, so I cannot reliably summarise its arguments."}
        if retrieval_grounding_score(hallucination, citation_reference) != 1:
            raise ValueError("Hallucinated citation-only answer passed grounding")
        if retrieval_grounding_score(refusal, citation_reference) != 5:
            raise ValueError("Correct citation-only refusal failed grounding")
        empty_course_reference = {"reference_course_evidence": [], "reference_chunk_ids": []}
        grounded_empty_result = {
            "retrieval_used": True,
            "response": "No relevant course material was found, so I cannot answer this from the indexed course sources.",
        }
        invented_empty_result = {
            "retrieval_used": True,
            "response": "No relevant course material was found, but the course states that laboratory coats must be size M.",
        }
        if retrieval_grounding_score(grounded_empty_result, empty_course_reference) != 5:
            raise ValueError("Grounded no-result retrieval response failed grounding")
        if retrieval_grounding_score(invented_empty_result, empty_course_reference) != 1:
            raise ValueError("Invented no-reference course answer passed grounding")
        if retrieval_grounding_score({**grounded_empty_result, "retrieval_used": False}, empty_course_reference) != 1:
            raise ValueError("Unattempted no-reference retrieval passed grounding")
        part_a_reference = {"reference_course_evidence": [{"text": "Part A requires a critical reflection."}]}
        if course_context_score({"response": "Please review the course page.", "expected_topics": ["Part A"]}, part_a_reference) == 5:
            raise ValueError("Topic present only in chunk counted as used")
        if plan_state_consistency_score({"response": "1. Mean\n2. Median"}) != 1:
            raise ValueError("Analytical numbered list counted as plan")
        invented = {"student_query": "How should I do 2 and 3?", "response": "You chose original step 2.", "memory_resolution": {}}
        if negative_control_score(invented) != 1:
            raise ValueError("Invented antecedent passed negative control")
        qualified = {"student_query": "What does Video View % mean?", "response": "This is not a course completion rate. It reports the percentage of a video watched."}
        if metric_definition_guard_score(qualified, {}) != 5:
            raise ValueError("Correct completion-rate qualification was penalised")
        return "exact route and adversarial mechanism guards pass"

    check("adversarial_mechanism_checks", adversarial_mechanism_check)

    def schema_check() -> str:
        applicable = gold[scenarios[0]["scenario_id"]]["gold_applicable_quality_dimensions"]
        payload = {
            "scores": {dimension: (3 if dimension in applicable else None) for dimension in QUALITY_DIMENSIONS},
            "rationales": {dimension: ("Specific valid rationale." if dimension in applicable else None) for dimension in QUALITY_DIMENSIONS},
        }
        validate_dimension_payload(payload, applicable, QUALITY_DIMENSIONS)
        if set(MECHANISM_DIMENSIONS) != set(MECHANISM_DIMENSIONS):
            raise ValueError("Mechanism schema invalid")
        return "strict quality schema and fixed mechanism schema valid"

    check("judge_schemas_valid", schema_check)

    def comparison_check() -> str:
        config = json.loads(COMPARISONS.read_text(encoding="utf-8"))
        required = {"rq1_evidence_synthesis", "rq2_recommendation_planning", "memory_contribution", "retrieval_contribution", "integrated_system_secondary"}
        actual = {test.get("test_id") for test in config.get("tests", [])}
        if actual != required:
            raise ValueError(f"Comparison IDs mismatch: {actual}")
        if any(test.get("score_layer") not in {"quality", "mechanism"} or not test.get("dimensions") for test in config["tests"]):
            raise ValueError("Invalid comparison layer/dimensions")
        allowed_by_layer = {"quality": set(QUALITY_DIMENSIONS), "mechanism": set(MECHANISM_DIMENSIONS)}
        for test in config["tests"]:
            if not set(test["dimensions"]) <= allowed_by_layer[test["score_layer"]]:
                raise ValueError(f"Invalid dimensions for {test['test_id']}")
        return f"{len(actual)} predefined comparisons"

    check("primary_comparison_configuration_valid", comparison_check)

    def exporter_check() -> str:
        synthetic: list[dict[str, Any]] = []
        for scenario in scenarios:
            for mode in EXPECTED_MODES:
                synthetic.append({
                    **scenario,
                    "mode": mode,
                    "response": f"Synthetic local response for {scenario['scenario_id']}.",
                    "rq1_evidence_summary": {},
                    "retrieved_context_chunks": [],
                })
        with tempfile.TemporaryDirectory() as directory:
            report = export_package(synthetic, gold, references, Path(directory), 12, 20260712)
            if report["response_count"] != 72:
                raise ValueError(report)
            rows = list(csv.DictReader((Path(directory) / "annotator_sample_v1.csv").open(encoding="utf-8")))
            for case_id in {row["case_id"] for row in rows}:
                case_rows = [row for row in rows if row["case_id"] == case_id]
                for field in ("reference_dashboard_evidence", "reference_course_evidence", "reference_source_restrictions", "conversation_history", "student_query", "current_page"):
                    if len({row[field] for row in case_rows}) != 1:
                        raise ValueError(f"Human package varies {field} within {case_id}")
        return "12 scenarios × 6 modes = 72 blind responses"

    check("human_validation_exporter_dry_run", exporter_check)

    def cli_flags_check() -> str:
        for filename in ("run_unified_llm_generation.py", "judge_unified_response_quality.py", "evaluate_unified_mechanisms.py"):
            source = (PROJECT_ROOT / "evaluation" / filename).read_text(encoding="utf-8")
            if "--resume" not in source or "--overwrite" not in source:
                raise ValueError(f"{filename} lacks resume/overwrite")
        return "generation, quality judge, and mechanism evaluator expose resume/overwrite"

    check("checkpoint_cli_controls", cli_flags_check)

    def mechanism_v2_integration_check() -> str:
        expected = PROJECT_ROOT / "evaluation" / "outputs" / "evaluation_integrity_v1" / "unified_mechanism_scores_v2.jsonl"
        if MECHANISM_V2_OUTPUT.resolve() != expected.resolve():
            raise ValueError(f"Evaluator default is not v2: {MECHANISM_V2_OUTPUT}")
        if SUMMARY_MECHANISM_INPUT.resolve() != expected.resolve():
            raise ValueError(f"Summary default is not v2: {SUMMARY_MECHANISM_INPUT}")
        if STATISTICS_MECHANISM_INPUT.resolve() != expected.resolve():
            raise ValueError(f"Statistics default is not v2: {STATISTICS_MECHANISM_INPUT}")
        if LEGACY_MECHANISM_V1_OUTPUT.resolve() == expected.resolve():
            raise ValueError("Frozen legacy v1 and formal v2 destinations are not distinct")
        readme = (PROJECT_ROOT / "evaluation" / "UNIFIED_BENCHMARK_README.md").read_text(encoding="utf-8")
        required = [
            "unified_mechanism_scores_v2.jsonl",
            "mechanism_rubric_version = unified-mechanism-v2",
            "--gold-labels evaluation/unified_benchmark_gold_labels.jsonl",
            "--reference-evidence evaluation/unified_reference_evidence_v1.jsonl",
        ]
        missing = [item for item in required if item not in readme]
        if missing:
            raise ValueError(f"README lacks formal v2 instructions: {missing}")
        return "evaluator, summary, statistics and README consistently select mechanism v2"

    check("post_generation_mechanism_v2_integration", mechanism_v2_integration_check)

    def frozen_tests_check() -> str:
        manifest = json.loads(TEST_HASHES.read_text(encoding="utf-8"))["sha256"]
        # P1 consolidates executable checks under tests/ while retaining the
        # frozen file bytes and legacy manifest names.
        changed = []
        for name, expected in manifest.items():
            path = PROJECT_ROOT / name
            if not path.exists():
                path = PROJECT_ROOT / "tests" / name
            if sha256(path) != expected:
                changed.append(name)
        if changed:
            raise ValueError(f"Frozen test files changed: {changed}")
        return f"{len(manifest)} frozen production/regression test files unchanged"

    if check_frozen_tests:
        check("frozen_production_tests_unchanged", frozen_tests_check)
    blocking = [item for item in checks if not item["passed"]]
    return {
        "status": "PASS" if not blocking else "FAIL",
        "blocking_issue_count": len(blocking),
        "checks": checks,
        "gold_audit_manual_review_findings": audit["manual_review_findings"],
        "formal_generation_ready": not blocking,
    }


def write_reports(report: dict[str, Any]) -> None:
    JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Unified Evaluation Preflight",
        "",
        f"Status: **{report['status']}**",
        "",
        f"Blocking issues: **{report['blocking_issue_count']}**",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- {'PASS' if item['passed'] else 'FAIL'} — `{item['name']}`: {item['detail']}" for item in report["checks"])
    lines.extend(["", "## Manual-review findings from gold audit", ""])
    findings = report["gold_audit_manual_review_findings"]
    lines.extend(f"- `{item['code']}`: {item['message']}" for item in findings)
    if not findings:
        lines.append("None.")
    MARKDOWN_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    report = run_preflight()
    write_reports(report)
    print(f"Unified evaluation preflight: {report['status']}; blocking={report['blocking_issue_count']}")
    if report["blocking_issue_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
