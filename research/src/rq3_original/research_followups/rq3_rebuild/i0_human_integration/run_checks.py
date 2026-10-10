"""Retain real local test results under I0; inherited source bytes stay unchanged."""
import argparse
from hashlib import sha256
from datetime import datetime, timezone
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',choices=['i0','p1','m1','r1'],required=True)
    args=p.parse_args()
    (HERE/'.runtime').mkdir(exist_ok=True)
    out=Path(tempfile.mkdtemp(prefix=args.suite+'_',dir=HERE/'receipts'))
    started=datetime.now(timezone.utc).isoformat()
    if args.suite=='i0':
        suite=unittest.defaultTestLoader.discover(str(HERE),pattern='test_integration.py')
    elif args.suite=='p1':
        location=HERE.parent/'p1_planner_bridge'
        sys.path.insert(0,str(location))
        suite=unittest.defaultTestLoader.discover(str(location/'tests'))
    elif args.suite=='m1':
        from utils.c4_rebuild.memory import m1_dependencies, M1
        m1_dependencies()
        sys.path.insert(0,str(M1/'tests'))
        module=importlib.import_module('test_m1_relations')
        class TestPaths:
            # Only the inherited TEST module's scratch directory is redirected.
            # Implementation paths and test fixtures still resolve at M1.
            def __truediv__(self, child):
                return HERE/'.runtime' if child=='.runtime' else M1/child
        module.OWNED=TestPaths()
        suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    else:
        from utils.c4_rag_lab.common import offline_guard
        location=HERE.parent/'r1_retrieval_lab'
        suite=unittest.defaultTestLoader.discover(str(location),pattern='test_lab.py')
    stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report=dict(suite=args.suite,started=started,ended=datetime.now(timezone.utc).isoformat(),
        interpreter=sys.executable,python=sys.version,tests_run=result.testsRun,
        passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        success=result.wasSuccessful(),scope='SYNTHETIC_ENGINEERING_AND_EXPOSED_REGRESSION_ONLY',
        generation_calls=0,judge_calls=0,ratings_created=0)
    report['i0_source_hashes']={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()
        for p in sorted(list((ROOT/'utils/c4_rebuild').glob('*.py'))+list(HERE.glob('*.py')))}
    (out/'TEST_OUTPUT.txt').write_text(stream.getvalue())
    (out/'TEST_REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(**{k:v for k,v in report.items() if k!='i0_source_hashes'},result_directory=str(out))))
    if not result.wasSuccessful():print(stream.getvalue()[-16000:])
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
