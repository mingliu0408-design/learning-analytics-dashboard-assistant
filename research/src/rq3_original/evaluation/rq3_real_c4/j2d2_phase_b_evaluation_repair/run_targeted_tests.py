#!/usr/bin/env python3
"""Run only the two explicit Phase-B test modules, with real networking blocked."""

import argparse
import importlib
import io
import json
import sys
import unittest

import phase_b_access_guard as guard
from phase_b_sources import HERE, digest, pretty
from build_phase_b_repair import durable_write_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    guard.verify_entry()
    network_attempts = []
    prohibited_imports = []
    aggregate_attempts = []
    def audit(event, arguments):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "urllib.Request"}:
            network_attempts.append(event)
            raise RuntimeError("REAL_NETWORK_PROHIBITED_IN_PHASE_B_TESTS")
        if event == "import" and arguments[0].split(".")[0] in {"openai", "httpx", "requests", "streamlit"}:
            prohibited_imports.append(arguments[0])
            raise RuntimeError("PROVIDER_OR_STREAMLIT_RUNTIME_IMPORT_PROHIBITED")
    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "recompute_overall_applicable_mean":
            aggregate_attempts.append(frame.f_code.co_name)
            raise RuntimeError("SCORE_AGGREGATE_COMPUTATION_PROHIBITED")
    sys.addaudithook(audit)
    sys.setprofile(profile)
    started = guard.utc_now()
    modules = [importlib.import_module("test_phase_b_repair"), importlib.import_module("test_package")]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    sys.setprofile(None)
    finished = guard.utc_now()
    sources = ["phase_b_access_guard.py", "phase_b_sources.py", "phase_b_model.py", "build_phase_b_repair.py",
               "test_phase_b_repair.py", "run_targeted_tests.py", "package_support/test_package.py",
               "package_support/validate_package.py", "package_support/judge_execution_runner_v3.py",
               "package_support/judge_result_parser_v3.py"]
    report = {"schema_version": "phase-b-targeted-test-results-v1", "attempt": args.attempt,
              "started_at_utc": started, "completed_at_utc": finished,
              "entry_receipt_sha256": guard.ENTRY_SHA256,
              "exact_modules": [module.__name__ for module in modules],
              "tests_run": result.testsRun, "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
              "failed_test_ids": [case.id() for case, details in result.failures + result.errors],
              "real_network_attempts": len(network_attempts), "provider_runtime_imports": len(prohibited_imports),
              "score_aggregate_function_attempts": len(aggregate_attempts),
              "judge_delivery_packages_executed": 0, "synthetic_transport_tests_only": True,
              "provider_calls": 0, "human_amendment_ratings": 0, "agreement_calculations": 0,
              "statistical_analyses": 0, "streamlit_launches": 0,
              "source_hashes": {name: digest((HERE / name).read_bytes()) for name in sources},
              "status": "PASS" if result.wasSuccessful() and not network_attempts and not prohibited_imports and not aggregate_attempts else "FAIL"}
    durable_write_once(HERE / f"PHASE_B_TARGETED_TEST_RESULTS_V{args.attempt}.json", pretty(report))
    durable_write_once(HERE / f"PHASE_B_TARGETED_TEST_OUTPUT_V{args.attempt}.txt", stream.getvalue().encode())
    print(stream.getvalue(), end="")
    print(json.dumps({k: report[k] for k in ("status", "tests_run", "passed", "failed", "errors", "skipped", "real_network_attempts", "score_aggregate_function_attempts")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
