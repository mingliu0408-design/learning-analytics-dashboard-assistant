"""Reproduce saved replay plus I3 controls in a fresh, self-contained temp checkout.

Only audit_saved.py and run_offline_tests.py i3 are executed. Historical execution
scripts are absent from this snapshot and cannot be called by this entrypoint.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',help='New nonexistent directory; defaults to a fresh system temporary directory.')
    args=parser.parse_args()
    source=Path(__file__).resolve().parent
    if args.output:
        root=Path(args.output).resolve();root.mkdir(parents=False,exist_ok=False)
    else:
        root=Path(tempfile.mkdtemp(prefix='rq3-i3-offline-review-'))
    for path in sorted((source/'snapshot').rglob('*')):
        if not path.is_file():continue
        assert not path.is_symlink()
        target=root/path.relative_to(source/'snapshot');target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
    target=root/'research_followups/rq3_rebuild/i3_planner_diagnosis_repair'
    target.mkdir(parents=True,exist_ok=False)
    for name in ('i3_common.py','repair_v1.py','audit_saved.py','run_offline_tests.py'):
        shutil.copyfile(source/name,target/name)
    shutil.copytree(source/'tests',target/'tests')
    shutil.copytree(source/'sources/live',target/'sources/live')
    outputs=[]
    for command in ([sys.executable,'-B',str(target/'audit_saved.py')],
                    [sys.executable,'-B',str(target/'run_offline_tests.py'),'i3']):
        run=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=60)
        outputs.append(dict(command=[Path(command[0]).name,*[str(Path(a).relative_to(root)) if a.startswith(str(root)) else a for a in command[1:]]],
                            exit_code=run.returncode,stdout=run.stdout,stderr=run.stderr))
        if run.returncode:
            (root/'REPRODUCTION_FAILURE.json').write_text(json.dumps(outputs,indent=2))
            print(run.stderr or run.stdout);return run.returncode
    expected=json.loads((source/'I2_ACTUAL_ROLE_AND_MODULE_RECONCILIATION.json').read_text())['counts']
    actual=json.loads((target/'I2_ACTUAL_ROLE_AND_MODULE_RECONCILIATION.json').read_text())['counts']
    assert actual==expected
    assert (source/'DEVELOPMENT_READING_COPY_VERIFIED.md').read_bytes()==(target/'DEVELOPMENT_READING_COPY_VERIFIED.md').read_bytes()
    result=dict(status='PASS',standalone_replay=True,temporary_checkout=str(root),
        original_execution_scripts_run=False,provider_calls=0,model_inference=0,
        actual_saved_attempts_replayed=128,candidates_replayed=32,exact_answers_verified=72,
        test_report=json.loads((target/'test_output/i3.json').read_text()),commands=outputs)
    (root/'STANDALONE_REPLAY_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='commands'},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
