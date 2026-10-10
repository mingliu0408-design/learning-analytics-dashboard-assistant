"""Run deterministic Stage 4K tests and optionally record aggregate counts."""

from __future__ import annotations

import argparse
import io
import json
import unittest

from .rag_specialist_protocol import TEST_RESULTS_PATH, atomic_write_json, utc_now


def run(*, write_result: bool) -> dict[str, object]:
    suite = unittest.defaultTestLoader.discover(
        str(TEST_RESULTS_PATH.parent / "tests"),
        pattern="test_*.py",
        top_level_dir=str(TEST_RESULTS_PATH.parents[3]),
    )
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    summary: dict[str, object] = {
        "schema_version": "rq2-v2-stage4-k-rag-specialist-test-results-v1",
        "recorded_at": utc_now(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": result.wasSuccessful(),
        "failed_test_ids": [test.id() for test, _ in result.failures],
        "error_test_ids": [test.id() for test, _ in result.errors],
        "provider_calls": 0,
    }
    if write_result:
        atomic_write_json(TEST_RESULTS_PATH, summary)
    print(stream.getvalue(), end="")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    summary = run(write_result=not args.no_write)
    return 0 if summary["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
