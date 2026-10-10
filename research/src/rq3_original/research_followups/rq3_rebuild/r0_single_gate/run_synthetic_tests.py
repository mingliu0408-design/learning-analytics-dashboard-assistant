"""Run only R0 synthetic tests with persistent, numbered attempt receipts."""
import io
from datetime import datetime, timezone
import sys
import unittest
from offline_common import OUT, offline_guard, write_json

attempt = 1
while (OUT / f'SYNTHETIC_TEST_ATTEMPT_{attempt:02d}.json').exists():
    attempt += 1
started = datetime.now(timezone.utc).isoformat()
with offline_guard() as counters:
    import test_p3_single_gate as tests
    suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
report = {'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
          'synthetic_only': True, 'tests_run': result.testsRun, 'failures': len(result.failures),
          'errors': len(result.errors), 'skips': len(result.skipped), 'passed': result.wasSuccessful(),
          'guard_counters': counters, 'generator_calls': 0, 'judge_calls': 0,
          'real_input_diagnostic_runs': 0, 'test_output': stream.getvalue(), 'exit_traces': tests.TRACES}
write_json(OUT / f'SYNTHETIC_TEST_ATTEMPT_{attempt:02d}.json', report)
print(stream.getvalue())
print(counters)
sys.exit(0 if result.wasSuccessful() else 1)
