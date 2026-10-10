"""One invocation of the unchanged prepared CLI; preserve exit, never retry."""
from pathlib import Path
from datetime import datetime, timezone
import os
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import write_once, load

HERE = Path(__file__).resolve().parent
AUTH = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_AUTHORIZATION_2026-09-07.json')
OUTPUT = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07')
COMMAND = ['/opt/anaconda3/bin/python3', '-B',
    'research_followups/rq3_rebuild/i1_pilot_launch/run_pilot.py',
    '--execute', '--approval', str(AUTH), '--output', str(OUTPUT)]

if __name__ == '__main__':
    assert not OUTPUT.exists()
    assert load(AUTH)['status'] == 'AUTHORIZED'
    started = datetime.now(timezone.utc).isoformat()
    write_once(HERE/'EXECUTION_LAUNCH_RECEIPT.json', dict(command=COMMAND, cwd=str(ROOT),
        started_at=started, retries_by_supervisor=0, resume=False,
        api_key_available_in_existing_environment=bool(os.environ.get('OPENAI_API_KEY'))))
    t0 = time.monotonic()
    result = subprocess.run(COMMAND, cwd=ROOT, capture_output=True)
    # Never print captured tracebacks or credential-bearing diagnostics to tools.
    secret = os.environ.get('OPENAI_API_KEY', '').encode()
    console = result.stdout + b'\n--- STDERR ---\n' + result.stderr
    if secret:
        console = console.replace(secret, b'[REDACTED_API_CREDENTIAL]')
    with (HERE/'LIVE_RUN_CONSOLE.txt').open('xb') as f:
        f.write(console)
        f.flush()
        os.fsync(f.fileno())
    write_once(HERE/'EXECUTION_PROCESS_RECEIPT.json', dict(command=COMMAND,
        started_at=started, ended_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=time.monotonic()-t0, returncode=result.returncode,
        output_exists=OUTPUT.exists(), supervisor_invocations=1,
        retries_by_supervisor=0, resume=False))
    print('ORIGINAL_RUNNER_EXIT_CODE=' + str(result.returncode))
