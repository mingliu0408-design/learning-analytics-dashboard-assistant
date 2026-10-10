"""Controlled replay paths and exact-byte receipts; no credential access."""
from pathlib import Path
import hashlib
import json
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = HERE.parent / 'a_reuse62'
LEGACY = Path('external_inputs/course_source')
START = '633851e3b832dc2c2a1724eb854c8c0ee3acc997'
VERSION = 'CONTROLLED_HISTORICAL_REPLAY_V2'
COURSE = 'research:reused62:module'
LEARNER = 'research:reused62:learner'
# Existing I1's QUERY_TIME, a controlled experimental clock, NOT a student observation.
CLOCK = '2026-09-01T12:00:00+00:00'
NINE = ('U026','U027','U029','U031','U033','U034','U035','U036','U037')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(OLD))
sys.dont_write_bytecode = True

def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False).encode()
    return hashlib.sha256(value).hexdigest()

def read(path): return json.loads(Path(path).read_text())
def lines(path): return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
def file_id(path):
    path = Path(path)
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=sha(path.read_bytes()))
def checked(entry):
    p=Path(entry['path'])
    if sha(p.read_bytes()) != entry['sha256']: raise ValueError('SOURCE_HASH_CHANGED:'+str(p))
    return p
def utc(): return datetime.now(timezone.utc).isoformat()
def offline():
    import socket
    def guard(event,args):
        if event.startswith('socket.') and event in ('socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind','socket.sendto'):
            raise RuntimeError('CONTROLLED_REPLAY_NO_NETWORK')
    sys.addaudithook(guard)
