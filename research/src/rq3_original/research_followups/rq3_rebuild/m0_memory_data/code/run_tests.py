"""Explicit local test modules only; never discovers repository-wide tests."""
import argparse
import io
import sys
import unittest
from pathlib import Path
from common import OWNED, disable_network, write_json, utc
disable_network()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--standalone", action="store_true")
    args = p.parse_args()
    args.output.resolve().relative_to(OWNED)
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(OWNED / "tests"))
    names = ["test_standalone", "test_saved_diagnostics", "test_packaging"] + ([] if args.standalone else ["test_inherited_harness"])
    start = utc()
    suite = unittest.TestLoader().loadTestsFromNames(names)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    (args.output / "TEST_OUTPUT.txt").write_text(output.getvalue())
    report = {"start_utc": start, "end_utc": utc(), "command": sys.argv,
        "python_executable": sys.executable, "modules": names, "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "successful": result.wasSuccessful(), "network": "DISABLED", "semantic_inference": "NOT_RUN_MECHANICS_ONLY",
        "factual_completeness_is_not_a_unit_test_pass": True}
    write_json(args.output / "TEST_REPORT.json", report)
    print(output.getvalue()); print(report)
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__": sys.exit(main())
