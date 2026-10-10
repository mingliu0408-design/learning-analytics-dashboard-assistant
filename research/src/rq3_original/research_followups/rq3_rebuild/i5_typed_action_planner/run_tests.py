"""Guarded offline suites; repeatable only in fresh pre-live test directories."""
import argparse
import io
import os
import subprocess
import sys
import unittest
from i5_common import *


def child(suite, output):
    paths = {n: ROOT / 'research_followups/rq3_rebuild' / d for n,d in
        [('p0','p0_planner_prototype'),('p1','p1_planner_bridge'),('i3','i3_planner_diagnosis_repair')]}
    paths['i5'] = HERE
    sys.path.insert(0,str(paths[suite])); sys.path.insert(0,str(paths['p0']))
    if suite in ('p0','p1'):
        from p0planner.offline_guard import install
        install()
    def guard(event, data):
        if event.startswith('socket.') or event == 'subprocess.Popen':
            raise PermissionError('I5_OFFLINE_NO_NETWORK_OR_SUBPROCESS')
        if event == 'import' and data[0].split('.')[0] in ('openai','torch','sentence_transformers','transformers'):
            raise PermissionError('I5_OFFLINE_NO_MODEL_OR_SDK')
        if event == 'open' and isinstance(data[0], (str,bytes)):
            name = os.fsdecode(data[0])
            if Path(name).name in ('.env','auth.json','credentials.json'):
                raise PermissionError('I5_OFFLINE_NO_CREDENTIAL_FILES')
    sys.addaudithook(guard)
    original_getitem = os._Environ.__getitem__
    def protected_getitem(self, key):
        if any(s in str(key).upper() for s in ('API_KEY', 'ACCESS_TOKEN', 'SECRET', 'PASSWORD')):
            raise PermissionError('I5_OFFLINE_NO_CREDENTIAL_ENV')
        return original_getitem(self,key)
    os._Environ.__getitem__ = protected_getitem
    pattern = 'test_offline_planner.py' if suite == 'p0' else 'test_i3.py' if suite == 'i3' else 'test_*.py'
    tests = unittest.defaultTestLoader.discover(str(paths[suite] / 'tests'), pattern=pattern)
    stream = io.StringIO(); result = unittest.TextTestRunner(stream=stream,verbosity=2).run(tests)
    report = dict(suite=suite,tests_run=result.testsRun,
        passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        status='PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',utc=utc(),
        provider_calls=0,sdk_client_constructions=0,credential_reads=0,guard_installed=True,
        input_policy='Copied historical snapshots and independent synthetic fixtures only',
        python=sys.version,executable=sys.executable)
    with (output / (suite + '.txt')).open('x') as f:
        f.write(stream.getvalue())
    write_once(output / (suite + '.json'),report)
    print(canonical(report).decode())
    return 0 if report['status']=='PASS' else 1


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--child',choices=['p0','p1','i3','i5'])
    parser.add_argument('--run',required=True); args=parser.parse_args()
    require(args.run.isalnum(), 'SAFE_RUN_LABEL_REQUIRED')
    output = HERE / 'offline_runs' / args.run
    require(not OUTPUT.exists(), 'NO_TEST_OR_CODE_REWORK_AFTER_LIVE_START')
    if args.child:
        return child(args.child,output)
    output.mkdir(parents=True,exist_ok=False)
    from run_i5 import binding
    before = binding(); suites=[]
    for suite in ('p0','p1','i3','i5'):
        result = subprocess.run([sys.executable,'-B',str(HERE/'run_tests.py'),'--child',suite,'--run',args.run],
                                cwd=ROOT,capture_output=True,text=True)
        print(result.stdout,end='')
        if result.stderr: print(result.stderr)
        if (output / (suite+'.json')).exists():
            suites.append(load(output / (suite+'.json')))
        else:
            suites.append(dict(suite=suite,status='FAIL',tests_run=0,passed=0,failures=0,errors=1,skipped=0))
        if result.returncode != 0:
            suites[-1]['status']='FAIL'
    require(binding()==before,'CODE_CHANGED_DURING_OFFLINE_TESTS')
    report=dict(status='PASS' if all(x['status']=='PASS' for x in suites) else 'FAIL',suites=suites,
        **{k:sum(x[k] for x in suites) for k in ('tests_run','passed','failures','errors','skipped')},
        code_binding_sha256=sha(before),provider_calls=0,sdk_client_constructions=0,credential_reads=0,
        excluded_suites=[dict(suite='I1 worker/orchestrator and real runner tests',reason='Would invoke excluded module preparation or historical execution entrypoints; not counted as passed.')],
        test_output_directory=str(output.relative_to(HERE)),utc=utc())
    write_once(output/'SUMMARY.json',report)
    print(canonical(report).decode())
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
