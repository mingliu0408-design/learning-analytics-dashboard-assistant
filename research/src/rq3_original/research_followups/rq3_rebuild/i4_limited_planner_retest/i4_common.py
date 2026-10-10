"""I4 identities and write-once helpers; importing never reads credentials."""
from pathlib import Path
import sys
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import canonical, sha, load, write_once, append, utc

I3 = ROOT / 'research_followups/rq3_rebuild/i3_planner_diagnosis_repair'
I1 = ROOT / 'research_followups/rq3_rebuild/i1_pilot_launch'
OLD = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07')
OUTPUT = Path('/Users/liuming/Downloads/RQ3_REBUILD_I4_LIMITED_PLANNER_RETEST_OUTPUT_2026-09-07')
ZIP = Path('/Users/liuming/Downloads/RQ3_REBUILD_I4_LIMITED_PLANNER_RETEST_REVIEW_2026-09-07.zip')
PACKET = Path('/Users/liuming/Downloads/RQ3_REBUILD_I4_CODEX_TASK_PACKET_2026-09-07.zip')
START = '14d3342f38eba1063e613f73878667729e642ad9'
BRANCH = 'research/rq3-rebuild-i1-pilot-launch'
SCOPE = str(HERE.relative_to(ROOT)) + '/'
SLOTS = ['I0-SYN-04:S4_EVIDENCE_PLANNING', 'I0-SYN-04:S5_FULL',
         'I0-SYN-06:S5_FULL', 'I0-SYN-07:S4_EVIDENCE_PLANNING', 'I0-SYN-11:S5_FULL']
ARCHIVES = {
    'RQ3_REBUILD_I2_SYNTHETIC_PILOT_EXECUTION_REVIEW_2026-09-07.zip':
        'b9506c17b67640b7868e9d9c4016f22f83d47934a844779e7a108987db3175f0',
    'RQ3_REBUILD_I3_PLANNER_DIAGNOSIS_REVIEW_2026-09-07.zip':
        '6acc9e442388fad598a4be186fadbc48b4a6ede1a3bcb9f3dd016865354c98af',
    PACKET.name: 'daaae946905fee8fbeb8df0f15a47ce3fb81246fe54d7adeaa3a06d9b5121e03'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def require(condition, code):
    if not condition:
        raise ValueError(code)


def file_binding(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'SOURCE_MISSING_OR_SYMLINK:' + str(path))
    return dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path.read_bytes()))


def check_files(rows):
    for row in rows:
        require(file_binding(row['path']) == row, 'SOURCE_DRIFT:' + row['path'])


def repair_module():
    # Use the exact committed I3 renderer, never an integration patch.
    import importlib.util
    spec = importlib.util.spec_from_file_location('i4_bound_i3_repair', I3 / 'repair_v1.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def settings():
    original = load(I1 / 'PILOT_CONFIGURATION_PROPOSED.json')
    return dict(version='I4_LIMITED_CONFIG_V1', slots=SLOTS,
        generation_roles=original['generation_roles'], sdk_max_retries=0,
        timeout_seconds=30, minimum_start_interval_seconds=2.0,
        max_request_input_byte_units=36256, estimated_budget_cap_usd=0.25,
        uncached_usd_per_million=original['uncached_usd_per_million'],
        caps=dict(INITIAL=5, CORRECTION=5, FINAL=5, TOTAL=15),
        max_corrections_per_slot=1, max_finals_per_slot=1, final_retries=0,
        router_calls=0, retrieval_calls=0, memory_calls=0, embedding_calls=0,
        judge_calls=0, human_scores=0, resume=False,
        reservation_convention='I1: canonical UTF-8 request bytes + 256; reserve max output; charge max(reservation, known uncached usage estimate). NOT AN EXACT BILLING GUARANTEE.')


def load_slots():
    deps = load(I3 / 'MINIMAL_RETEST_DEPENDENCIES_NOT_AUTHORIZED.json')
    require([x['logical'] for x in deps['selected']] == SLOTS, 'FIVE_SLOT_ORDER_MISMATCH')
    return deps['selected']


def prepared(row):
    path, pointer = row['frozen_input_source'].split('#')
    require(pointer == '/output/prepared', 'PREPARED_POINTER_MISMATCH')
    value = load(I3 / path)['output']['prepared']
    # I3 audit_saved.py:206 defines this value as sha(bridge), although its
    # source pointer names the parent prepared object. Preserve that definition.
    require(sha(value['planner']['bridge']) == row['frozen_input_sha256'], 'BRIDGE_SNAPSHOT_HASH_MISMATCH')
    return value
