"""I6 identities. Imports never construct clients or read credentials."""
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
I5 = ROOT / 'research_followups/rq3_rebuild/i5_typed_action_planner'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I5))
from i5_common import require, git, file_binding, check_files, SLOTS
from utils.c4_rebuild.i1.common import canonical, sha, load, write_once, append, utc
import i5_common
import typed_v1 as REPAIR

START = '5104bef72b38e8a1968599b94f6d5f0e8b9e2b73'
BRANCH = 'research/rq3-rebuild-i1-pilot-launch'
SCOPE = str(HERE.relative_to(ROOT)) + '/'
PACKET = Path('/Users/liuming/Downloads/RQ3_REBUILD_I6_CODEX_TASK_PACKET_2026-09-07.zip')
ARCHIVE = Path('/Users/liuming/Downloads/RQ3_REBUILD_I5_TYPED_ACTION_PLAN_REVIEW_2026-09-07.zip')
ARCHIVE_SHA = '7dfe73165b5dda13d8708ce235f0a6187c451971e559ba34888c49b82087b0a5'
OUTPUT = Path('/Users/liuming/Downloads/RQ3_REBUILD_I6_FINAL_REFERENCE_BRIDGE_OUTPUT_2026-09-07')
ZIP = Path('/Users/liuming/Downloads/RQ3_REBUILD_I6_FINAL_REFERENCE_BRIDGE_REVIEW_2026-09-07.zip')

def settings():
    config = i5_common.settings()
    require(config == load(I5 / 'CONFIG.json'), 'I5_CONFIG_IDENTITY')
    config.update(version='I6_FINAL_REFERENCE_CONFIG_V1',
                  caps=dict(INITIAL=4, CORRECTION=4, FINAL=5, TOTAL=13))
    return config

def load_slots():
    rows = load(HERE / 'INPUT_BINDINGS.json')
    require(rows == i5_common.load_slots(), 'I5_SLOT_REGISTRY_IDENTITY')
    return rows

def prepared(row):
    path = row['directory'] + '/prepared.json'
    require((HERE / path).read_bytes() == (I5 / path).read_bytes(), 'PREPARED_BYTES_CHANGED')
    p = load(HERE / path)
    require(sha(p) == row['prepared_sha256'], 'PREPARED_IDENTITY')
    require(sha(p['planner']['bridge']) == row['frozen_input_sha256'], 'BRIDGE_IDENTITY')
    return p
