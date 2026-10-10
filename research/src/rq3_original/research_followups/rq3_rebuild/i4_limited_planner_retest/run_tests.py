"""Offline suites in separate guarded processes; all outputs stay under I4."""
import argparse
import io
import json
import subprocess
import sys
import unittest
from i4_common import *


def child(suite):
    paths={n:ROOT/'research_followups/rq3_rebuild'/d for n,d in
        [('p0','p0_planner_prototype'),('p1','p1_planner_bridge'),('i3','i3_planner_diagnosis_repair')]}
    paths['i4']=HERE
    sys.path.insert(0,str(paths[suite]))
    sys.path.insert(0,str(paths['p0']))
    if suite in ('p0','p1'):
        from p0planner.offline_guard import install
        install()
    else:
        def guard(event,data):
            if event.startswith('socket.') or event=='subprocess.Popen':
                raise PermissionError('I4_OFFLINE_NO_NETWORK_OR_SUBPROCESS')
            if event=='import' and data[0].split('.')[0] in ('openai','torch','sentence_transformers','transformers'):
                raise PermissionError('I4_OFFLINE_NO_MODEL_OR_SDK')
        sys.addaudithook(guard)
    pattern='test_offline_planner.py' if suite=='p0' else 'test_i3.py' if suite=='i3' else 'test_i4.py' if suite=='i4' else 'test_*.py'
    tests=unittest.defaultTestLoader.discover(str(paths[suite]/'tests'),pattern=pattern)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(tests)
    report=dict(suite=suite,tests_run=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        status='PASS' if result.wasSuccessful() else 'FAIL',utc=utc(),provider_calls=0,sdk_client_constructions=0,
        subprocess_or_worker_calls=0,guard_installed=True,python=sys.version,executable=sys.executable)
    out=HERE/'test_output';out.mkdir(exist_ok=True)
    with (out/f'{suite}.txt').open('x') as f:f.write(stream.getvalue())
    write_once(out/f'{suite}.json',report)
    print(canonical(report).decode())
    return 0 if result.wasSuccessful() else 1


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--child',choices=['p0','p1','i3','i4']);args=parser.parse_args()
    if args.child:return child(args.child)
    from run_i4 import binding
    suites=[]
    for suite in ('p0','p1','i3','i4'):
        result=subprocess.run([sys.executable,'-B',str(HERE/'run_tests.py'),'--child',suite],cwd=ROOT,capture_output=True,text=True)
        print(result.stdout,end='')
        if result.stderr:print(result.stderr)
        suites.append(load(HERE/'test_output'/f'{suite}.json'))
    report=dict(status='PASS' if all(x['status']=='PASS' for x in suites) else 'FAIL',suites=suites,
        **{k:sum(x[k] for x in suites) for k in ('tests_run','passed','failures','errors','skipped')},
        code_binding_sha256=sha(binding()),provider_calls=0,sdk_client_constructions=0,
        excluded_suites=[dict(suite='I1 test_i1.py',tests=54,reason='Includes prepare-worker execution; narrower I4 controls and original P0/P1/I3 checks used.'),
                         dict(suite='I1 test_runner_gates.py',tests=8,reason='Invokes original run_pilot.main; prohibited entrypoint is not tested.')],
        development_checks=['One initial I4 source-hash interpretation failure is documented in DEVELOPMENT_ISSUES.md; not counted as a passing test.'],utc=utc())
    write_once(HERE/'OFFLINE_TEST_SUMMARY.json',report)
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
