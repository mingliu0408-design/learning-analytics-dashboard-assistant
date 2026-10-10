"""Run bounded H0-only unit tests; keep every attempt, including failures."""
import datetime
import io
import json
import platform
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    runs = ROOT / 'test_results'
    runs.mkdir(exist_ok=True)
    number = 1
    while (runs / f'attempt_{number:03d}').exists():number += 1
    out = runs / f'attempt_{number:03d}'
    out.mkdir()
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py'))
    (out / 'TEST_STDOUT.txt').write_text(stream.getvalue())
    report = {'status':'PASS' if result.wasSuccessful() else 'FAIL', 'tests_run':result.testsRun, 'failures':len(result.failures), 'errors':len(result.errors), 'skipped':len(result.skipped), 'python_version':platform.python_version(),'executable':sys.executable,'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'scope':'H0 offline program fixtures only; no real scores or source-data execution', 'failed_tests':[str(t) for t,_ in result.failures+result.errors], 'attempt':out.name}
    (out / 'TEST_RESULTS.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not result.wasSuccessful():print(stream.getvalue())
    sys.exit(not result.wasSuccessful())
