"""Run P1 only, network disabled. Each run gets a fresh retained report directory."""
from datetime import datetime,timezone
from pathlib import Path
import io,json,sys,tempfile,unittest
from p1bridge.contracts import ROOT,canonical
from p0planner.offline_guard import install


def main():
    install();started=datetime.now(timezone.utc).isoformat()
    out=Path(tempfile.mkdtemp(prefix='p1_run_',dir=ROOT/'reports'))
    stream=io.StringIO();suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report=dict(started_at_utc=started,completed_at_utc=datetime.now(timezone.utc).isoformat(),
        executable=sys.executable,python=sys.version,tests_run=result.testsRun,
        passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        network_guard='INSTALLED',real_calls=0,final_generation_calls=0,
        scope='P1 unit tests only; mocks demonstrate mechanics, no model inference.')
    (out/'TEST_OUTPUT.txt').write_text(stream.getvalue());(out/'TEST_REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(stream.getvalue());print(json.dumps(report,indent=2));print('REPORT_DIRECTORY',out)
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
