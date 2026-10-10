"""Run specified offline unit suites, never original run/execute entrypoints."""
import argparse
from datetime import datetime, timezone
import io
import sys
import unittest
from i3_common import HERE, ROOT, write


def main():
    parser=argparse.ArgumentParser();parser.add_argument('suite',choices=['p0','p1','i1','i3']);args=parser.parse_args()
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
    paths={'p0':ROOT/'research_followups/rq3_rebuild/p0_planner_prototype',
           'p1':ROOT/'research_followups/rq3_rebuild/p1_planner_bridge',
           'i1':ROOT/'research_followups/rq3_rebuild/i1_pilot_launch','i3':HERE}
    base=paths[args.suite];sys.path.insert(0,str(base))
    if args.suite in ('p0','p1'):
        sys.path.insert(0,str(paths['p0']))
        from p0planner.offline_guard import install
        install()
    else:
        def guard(event, data):
            if event.startswith('socket.'):
                raise PermissionError('I3_TEST_NO_NETWORK')
            if event=='subprocess.Popen':
                command=data[1]
                # Original I1 tests may use this network-disabled finite worker only.
                if args.suite!='i1' or len(command)!=3 or command[1]!='-B' or command[2]!=str(paths['i1']/'offline_worker.py'):
                    raise PermissionError('I3_TEST_NO_EXECUTION_OR_INFERENCE_SUBPROCESS')
            if event=='import' and data[0].split('.')[0] in ('torch','sentence_transformers','transformers','openai'):
                raise PermissionError('I3_TEST_NO_REAL_MODEL_OR_SDK_IMPORT')
        sys.addaudithook(guard)
    pattern={'p0':'test_offline_planner.py','p1':'test_*.py','i1':'test_i1.py','i3':'test_i3.py'}[args.suite]
    suite=unittest.defaultTestLoader.discover(str(base/'tests'),pattern=pattern)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    out=HERE/'test_output';out.mkdir(exist_ok=True)
    (out/f'{args.suite}.txt').write_text(stream.getvalue())
    report=dict(suite=args.suite,tests_run=result.testsRun,passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),python=sys.version,executable=sys.executable,
        completed_at=datetime.now(timezone.utc).isoformat(),provider_calls=0,model_inference=0,
        original_execution_entrypoints_run=False,network_guard=True,
        excluded_original_suites=['I1 test_runner_gates.py: invokes run_pilot.main; omitted to honor no execution-script tests.'] if args.suite=='i1' else [])
    write(f'test_output/{args.suite}.json',report)
    print(stream.getvalue());print(report)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
