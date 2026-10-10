"""Standard-library identities and durable, write-once records."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOME = ROOT / 'research_followups/rq3_rebuild/i1_pilot_launch'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError('DUPLICATE_JSON_KEY')
            d[k] = v
        return d
    return json.loads(Path(path).read_text(), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value) + b'\n'
    with path.open('xb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    sync_dir(path.parent)
    return sha(data)


def append(path, value):
    path = Path(path)
    with path.open('ab') as f:
        f.write(canonical(value) + b'\n')
        f.flush()
        os.fsync(f.fileno())
    sync_dir(path.parent)


def records(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]
