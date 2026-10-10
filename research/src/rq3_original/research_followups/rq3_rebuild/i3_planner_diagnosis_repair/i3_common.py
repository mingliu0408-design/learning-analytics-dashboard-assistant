"""I3-namespaced offline utilities; avoid historical modules named common."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIVE = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07')
I2_ZIP = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_EXECUTION_REVIEW_2026-09-07.zip')
PACKET = Path('/Users/liuming/Downloads/RQ3_REBUILD_I3_PLANNER_REPAIR_CODEX_TASK_PACKET_2026-09-07.zip')
START = 'b762632b58f924979a090a1aa23c05a8139242f4'
BRANCH = 'research/rq3-rebuild-i1-pilot-launch'
SCOPE = str(HERE.relative_to(ROOT)) + '/'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(name, value):
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode())


def jsonl(name, rows):
    (HERE / name).write_bytes(b''.join(canonical(row)+b'\n' for row in rows))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def live_records():
    source = HERE/'sources/live'
    stages = {(s['logical'], s['stage']): (p, s)
              for p in (source/'stages').glob('*.json') for s in [read(p)]}
    attempts = [read(p) for p in (source/'attempts').glob('*.start.json')]
    return source, stages, sorted(attempts, key=lambda x: (x['logical'], x['attempt']))


def reference(path, pointer=''):
    return str(path.relative_to(HERE)) + ('#'+pointer if pointer else '')
