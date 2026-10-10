"""I5 identities. Importing does not construct clients or access credentials."""
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import canonical, sha, load, write_once, append, utc

I4 = ROOT / 'research_followups/rq3_rebuild/i4_limited_planner_retest'
I3 = ROOT / 'research_followups/rq3_rebuild/i3_planner_diagnosis_repair'
I1 = ROOT / 'research_followups/rq3_rebuild/i1_pilot_launch'
START = '3d3295b7e0d900183a0a98ec58eca9c99ff1e6ac'
BRANCH = 'research/rq3-rebuild-i1-pilot-launch'
SCOPE = str(HERE.relative_to(ROOT)) + '/'
PACKET = Path('/Users/liuming/Downloads/RQ3_REBUILD_I5_CODEX_TASK_PACKET_2026-09-07.zip')
ARCHIVE = Path('/Users/liuming/Downloads/RQ3_REBUILD_I4_LIMITED_PLANNER_RETEST_REVIEW_2026-09-07.zip')
ARCHIVE_SHA = '02d042fd3cdf59e87ad90fa47774bde1d053125a6d010740e19fdcf08091a3e4'
OUTPUT = Path('/Users/liuming/Downloads/RQ3_REBUILD_I5_TYPED_ACTION_PLAN_OUTPUT_2026-09-07')
ZIP = Path('/Users/liuming/Downloads/RQ3_REBUILD_I5_TYPED_ACTION_PLAN_REVIEW_2026-09-07.zip')
SLOTS = ['I0-SYN-04:S4_EVIDENCE_PLANNING', 'I0-SYN-04:S5_FULL',
         'I0-SYN-06:S5_FULL', 'I0-SYN-07:S4_EVIDENCE_PLANNING', 'I0-SYN-11:S5_FULL']


def require(condition, code):
    if not condition:
        raise ValueError(code)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def file_binding(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'SOURCE_MISSING_OR_SYMLINK:' + str(path))
    return dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path.read_bytes()))


def check_files(rows):
    for row in rows:
        require(file_binding(row['path']) == row, 'SOURCE_DRIFT:' + row['path'])


def repair_module():
    import typed_v1
    return typed_v1


def settings():
    original = load(I4 / 'CONFIG.json')
    original['version'] = 'I5_TYPED_ACTION_CONFIG_V1'
    original['failure_policy'] = 'STOP_AFTER_EXHAUSTED_CANDIDATE_OR_ANY_FAILED_FINAL; CORRECTABLE_INITIAL_MAY_REVISE_ONCE'
    require(original['slots'] == SLOTS, 'FIVE_SLOT_ORDER_MISMATCH')
    return original


def load_slots():
    rows = load(HERE / 'INPUT_BINDINGS.json')
    require([r['logical'] for r in rows] == SLOTS, 'FIVE_SLOT_ORDER_MISMATCH')
    return rows


def prepared(row):
    p = load(HERE / row['directory'] / 'prepared.json')
    require(sha(p) == row['prepared_sha256'], 'PREPARED_SNAPSHOT_HASH_MISMATCH')
    require(sha(p['planner']['bridge']) == row['frozen_input_sha256'], 'BRIDGE_SNAPSHOT_HASH_MISMATCH')
    return p
