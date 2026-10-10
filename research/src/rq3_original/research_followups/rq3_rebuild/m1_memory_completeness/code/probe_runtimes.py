"""Once per stage/hypothesis; no installation, network or shared runtime mutation."""
import os
import signal
import subprocess
import json
from pathlib import Path
from m1_common import OWNED, sha, utc, write_json, fresh_output
from utils.c4_memory.c4_memory_retriever import MPNET_REVISION, MPNET_REQUIRED_HASHES

LEGACY = Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3')
MODEL = LEGACY / 'semantic_runtime/models/all-mpnet-base-v2' / MPNET_REVISION
INTERPRETERS = ['/opt/anaconda3/bin/python3', str(LEGACY / '.venv/bin/python')]
DEPENDENCIES = {'metadata': [], 'numpy': [], 'torch': ['numpy'], 'tokenizers': [],
                'transformers': ['torch', 'tokenizers'], 'tokenizer': ['transformers'],
                'construction': ['tokenizer'], 'encode': ['construction']}

def child_env():
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONFAULTHANDLER='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
               XDG_CACHE_HOME=str(OWNED/'.runtime/cache'),
               MPLCONFIGDIR=str(OWNED/'.runtime/matplotlib'))
    return env

def snapshot():
    rows = []
    for p in sorted(MODEL.rglob('*')):
        if p.is_file() and (p.name in MPNET_REQUIRED_HASHES or p.suffix in ('.json','.txt')):
            name = p.relative_to(MODEL).as_posix()
            digest = sha(p)
            if name in MPNET_REQUIRED_HASHES: assert digest == MPNET_REQUIRED_HASHES[name]
            rows.append({'path': str(p), 'bytes': p.stat().st_size, 'sha256': digest,
                         'required_sha256': MPNET_REQUIRED_HASHES.get(name)})
    assert set(MPNET_REQUIRED_HASHES) <= {Path(x['path']).name for x in rows}
    return rows

def main():
    out = fresh_output(OWNED/'runtime_diagnostics/stages_v1')
    before = snapshot()
    write_json(out/'SNAPSHOT_BEFORE.json', before)
    cpu = subprocess.run(['/usr/sbin/sysctl','machdep.cpu.brand_string','hw.machine','hw.ncpu'],
                         capture_output=True, text=True)
    results = []
    for i, python in enumerate(INTERPRETERS):
        passed = set()
        for stage, needs in DEPENDENCIES.items():
            record = {'execution_utc': utc(), 'interpreter': python, 'stage': stage,
                      'hypothesis': 'Isolate '+stage+' in existing interpreter '+str(i),
                      'requested_device': 'cpu', 'actual_device': 'UNKNOWN_UNLESS_REPORTED',
                      'cpu_architecture': cpu.stdout, 'process_env_overrides_only': True,
                      'network': 'OFFLINE_FLAGS_AND_PYTHON_SOCKET_AUDIT_GUARD',
                      'core_dumps': 'DISABLED', 'faulthandler': 'ENABLED_BEFORE_NATIVE_IMPORT'}
            if not Path(python).exists() or any(n not in passed for n in needs):
                record.update(status='NOT_RUN_DEPENDENCY_UNAVAILABLE', dependencies=needs,
                              exit_code=None, signal=None, stderr='')
            else:
                command = [python,'-B',str(OWNED/'code/native_stage_worker.py'),stage,str(MODEL)]
                record['command'] = command
                try:
                    run = subprocess.run(command, cwd=OWNED, env=child_env(), capture_output=True,
                                         text=True, timeout=90)
                    record.update(status='PASS' if run.returncode == 0 else 'FAILED',
                                  exit_code=run.returncode,
                                  signal=signal.Signals(-run.returncode).name if run.returncode < 0 else None,
                                  stdout=run.stdout, stderr=run.stderr)
                    if run.returncode == 0: passed.add(stage)
                except subprocess.TimeoutExpired as exc:
                    record.update(status='TIMEOUT', exit_code=None, signal='KILLED_AFTER_TIMEOUT',
                                  stdout=str(exc.stdout or ''), stderr=str(exc.stderr or ''))
            write_json(out/f'{i}_{stage}.json', record)
            results.append(record)
            print(i, stage, record['status'], record['exit_code'], flush=True)
    after = snapshot()
    assert before == after
    write_json(out/'SNAPSHOT_AFTER.json', after)
    working = [r['interpreter'] for r in results if r['stage']=='encode' and r['status']=='PASS']
    write_json(out/'SUMMARY.json', {'execution_end_utc': utc(), 'stages': results,
        'working_interpreters': working, 'snapshot_unchanged': True, 'downloads': 0, 'installs': 0,
        'shared_runtime_changes': 0, 'semantic_status': 'TINY_ENCODE_VERIFIED' if working else 'NOT_RUN',
        'root_cause': 'Stage evidence only; no unsupported version-based causal conclusion.'})

if __name__ == '__main__': main()
