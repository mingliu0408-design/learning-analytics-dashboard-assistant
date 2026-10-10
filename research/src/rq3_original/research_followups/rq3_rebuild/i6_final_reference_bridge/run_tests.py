"""Offline network/credential/SDK guard with fresh I6-only output directories."""
import argparse
import io
import os
import subprocess
import sys
import unittest
from i6_common import *

def child(suite, output):
    if suite != 'i6':
        # Invoke only the I5 offline suite function with an I6 destination.
        # The old run_tests main and all historical live entrypoints are unused.
        import importlib.util
        spec=importlib.util.spec_from_file_location('frozen_i5_offline',I5/'run_tests.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.child(suite, output)
    def guard(event,data):
        if event.startswith('socket.') or event=='subprocess.Popen': raise PermissionError('I6_OFFLINE_NETWORK_PROCESS_BLOCKED')
        if event=='import' and data[0].split('.')[0] in ('openai','torch','transformers','sentence_transformers'):
            raise PermissionError('I6_OFFLINE_SDK_MODEL_BLOCKED')
        if event=='open' and isinstance(data[0],(str,bytes)) and Path(os.fsdecode(data[0])).name in ('.env','auth.json','credentials.json'):
            raise PermissionError('I6_OFFLINE_CREDENTIAL_FILE_BLOCKED')
    sys.addaudithook(guard)
    getitem=os._Environ.__getitem__
    def safe_getitem(self,key):
        if any(s in str(key).upper() for s in ('API_KEY','ACCESS_TOKEN','SECRET','PASSWORD')):
            raise PermissionError('I6_OFFLINE_CREDENTIAL_ENV_BLOCKED')
        return getitem(self,key)
    os._Environ.__getitem__=safe_getitem
    sys.path.insert(0,str(I5/'tests'))
    tests=unittest.defaultTestLoader.discover(str(HERE/'tests'))
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(tests)
    report=dict(suite=suite,tests_run=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        status='PASS' if result.wasSuccessful() and not result.skipped else 'FAIL',guard_installed=True,
        provider_calls=0,sdk_client_constructions=0,credential_reads=0,utc=utc())
    (output/'i6.txt').write_text(stream.getvalue())
    write_once(output/'i6.json',report);print(canonical(report).decode())
    return 0 if report['status']=='PASS' else 1

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--child',choices=['p0','p1','i3','i5','i6']);parser.add_argument('--run',required=True)
    args=parser.parse_args();require(args.run.isalnum(),'SAFE_OFFLINE_RUN_LABEL')
    require(not OUTPUT.exists(),'NO_TEST_REWORK_AFTER_LIVE_START')
    output=HERE/'offline_runs'/args.run
    if args.child:return child(args.child,output)
    output.mkdir(parents=True,exist_ok=False)
    import run_i6
    before=run_i6.binding(); suites=[]
    for suite in ('p0','p1','i3','i5','i6'):
        r=subprocess.run([sys.executable,'-B',str(HERE/'run_tests.py'),'--child',suite,'--run',args.run],cwd=ROOT,capture_output=True,text=True)
        print(r.stdout,end='')
        if r.stderr:print(r.stderr)
        report=load(output/(suite+'.json')) if (output/(suite+'.json')).exists() else dict(suite=suite,status='FAIL',tests_run=0,passed=0,failures=0,errors=1,skipped=0)
        if r.returncode:report['status']='FAIL'
        suites.append(report)
    require(before==run_i6.binding(),'CODE_CHANGED_DURING_OFFLINE_TESTS')
    result=dict(status='PASS' if all(x['status']=='PASS' for x in suites) else 'FAIL',suites=suites,
        **{k:sum(x[k] for x in suites) for k in ('tests_run','passed','failures','errors','skipped')},
        code_binding_sha256=sha(before),provider_calls=0,sdk_client_constructions=0,credential_reads=0,
        test_output_directory=str(output.relative_to(HERE)),utc=utc())
    write_once(output/'SUMMARY.json',result)
    if result['status']=='PASS':write_once(HERE/'OFFLINE_TEST_SUMMARY.json',result)
    print(canonical(dict(status=result['status'],tests_run=result['tests_run'],passed=result['passed'])).decode())
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
