"""Standalone, network-disabled focused tests with fresh owned report output."""
from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from p0planner.offline_guard import install
from p0planner.controller import run_planner
from p0planner.providers import MockProvider
from p0planner.schema import ROOT, load_schema, schema_errors
from p0planner.contracts import canonical
from tools.build_fixtures import baseline, window


def main():
    install()
    started = datetime.now(timezone.utc).isoformat()
    # tempfile remains within this isolated task/extracted review directory.
    report_parent = ROOT / "reports"
    report_parent.mkdir(exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="offline_run_", dir=report_parent))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_offline_planner.py")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    cases = json.loads((ROOT / "fixtures/synthetic_cases.json").read_text())["cases"]
    runs = []
    for case in cases:
        provider = MockProvider(case["mock_candidates"])
        value = run_planner(case["runtime_input"], provider, max_repairs=case["max_repairs"], planning_enabled=case["planning_enabled"])
        assert not schema_errors(value, load_schema("PLANNER_OUTPUT_SCHEMA_DRAFT.json"))
        runs.append(dict(case_id=case["case_id"], labels=case["labels"], result=value))
    (out / "MOCK_REPAIR_LOOP_TRACE.jsonl").write_text("".join(canonical(x) + "\n" for x in runs))
    perturbations = []
    for dimension in ("budget", "availability"):
        original, candidate = baseline()
        changed = deepcopy(original)
        if dimension == "budget":
            changed["hard_constraints"]["budget"]["minutes"] = 10
            changed_path = "$.hard_constraints.budget.minutes"
        else:
            changed["hard_constraints"]["schedule"]["allowed_windows"] = [window("2026-09-07T10:00:00+02:00", "2026-09-07T11:00:00+02:00")]
            changed_path = "$.hard_constraints.schedule.allowed_windows"
        providers = [MockProvider([candidate]), MockProvider([candidate])]
        results = [run_planner(inp, provider) for inp, provider in zip((original, changed), providers)]
        assert [r["status"] for r in results] == ["PASSED_ENCODED_CHECKS", "BOUNDED_REPAIR_EXHAUSTED"]
        assert providers[0].requests[0].sha256 != providers[1].requests[0].sha256
        assert results[0]["repair_history"][0]["candidate"] == results[1]["repair_history"][0]["candidate"]
        perturbations.append(dict(dimension=dimension, changed_path=changed_path,
                                  same_candidate_sha256=hashlib.sha256(canonical(candidate).encode()).hexdigest(),
                                  all_other_runtime_input_fixed=True, results=results,
                                  interpretation="Request sensitivity and deterministic checking only; no model adaptation demonstrated."))
    (out / "INPUT_PERTURBATION_RESULTS.json").write_text(json.dumps(perturbations, indent=2) + "\n")
    (out / "test_output.txt").write_text(stream.getvalue())
    report = dict(started_at_utc=started, completed_at_utc=datetime.now(timezone.utc).isoformat(),
                  python=sys.version, executable=sys.executable, command="python3 -B run_tests.py",
                  standalone=True, source="MODEL_AUTHORED_SYNTHETIC_DEVELOPMENT_FIXTURES", network_guard="INSTALLED_AND_TESTED",
                  tests_run=result.testsRun, passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
                  failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                  fixture_cases=len(cases), real_provider_calls=0,
                  mock_candidate_calls=sum(r["result"]["provider_calls"]["candidate"] for r in runs),
                  mock_repair_calls=sum(r["result"]["provider_calls"]["repair"] for r in runs),
                  call_count_scope="29 fixture trace replays only; unit-test mocks and four perturbation replays counted separately from these counters; no real provider calls anywhere.",
                  perturbation_pairs=2, perturbation_mock_candidate_calls=4,
                  per_case=[dict(case_id=r["case_id"], status=r["result"]["status"], failure_kind=r["result"]["failure_kind"],
                                 issue_codes=sorted({i["code"] for i in r["result"]["encoded_check_results"]["issues"]}),
                                 calls=r["result"]["provider_calls"]) for r in runs])
    (out / "TEST_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(stream.getvalue())
    print(json.dumps({k:v for k,v in report.items() if k!='per_case'}, indent=2))
    print("REPORT_DIRECTORY", out)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
