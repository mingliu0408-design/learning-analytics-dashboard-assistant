"""Explicit M1 + inherited M0 tests; temporary writes redirected into M1 only."""
import argparse
import importlib
import io
import sys
import unittest
from m1_common import OWNED,M0,fresh_output,write_json,utc,sha


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();out=fresh_output(args.output)
    sys.path.insert(0,str(OWNED/'tests'));sys.path.append(str(M0/'tests'))
    inherited=importlib.import_module('test_inherited_harness')
    inherited.OWNED=OWNED  # Sole effect: the inherited test's temporary-state root.
    import run_diagnostics as m0_diagnostics
    m0_diagnostics.OWNED=OWNED  # Only used for the fake-worker-death test's stderr temporary.
    names=['test_m1_relations','test_standalone','test_saved_diagnostics','test_packaging','test_inherited_harness']
    if (OWNED/'tests/test_m1_packaging.py').exists():names.append('test_m1_packaging')
    start=utc();suite=unittest.TestLoader().loadTestsFromNames(names);stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (out/'TEST_OUTPUT.txt').write_text(stream.getvalue())
    report={'start_utc':start,'end_utc':utc(),'command':sys.argv,'interpreter':sys.executable,
        'modules':names,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'success':result.wasSuccessful(),'semantic_inference_in_unit_tests':'NOT_RUN',
        'runtime_inference_report':'Separate runtime and hybrid diagnostic receipts',
        'test_source_hashes':[{'path':str(p),'sha256':sha(p)} for p in sorted((OWNED/'tests').glob('*.py'))]}
    write_json(out/'TEST_REPORT.json',report);print(stream.getvalue());print(report)
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':sys.exit(main())
