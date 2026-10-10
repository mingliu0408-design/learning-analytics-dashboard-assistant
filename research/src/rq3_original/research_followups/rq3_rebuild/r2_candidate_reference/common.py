"""R2 identities and durable task-local receipts; no inference at import."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
R1 = ROOT / 'research_followups/rq3_rebuild/r1_retrieval_lab'
BASE = '13d4bf9842f748e52777dd056ab17c17d6de86a4'
BRANCH = 'research/rq3-rebuild-r2-candidate-reference'
V0 = 'daaba43aebeda730db2bd7aef4583729610242a1af44060615c3f4c235e67ede'
REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
LOCAL = OUT / 'local_artifacts'

def now():
    return datetime.now(timezone.utc).isoformat()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(value).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text())

def write_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if exclusive else 'w') as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                           allow_nan=False) + '\n')
        f.flush()
        os.fsync(f.fileno())

def append_json(path, value):
    with Path(path).open('a') as f:
        f.write(canonical(value).decode() + '\n')
        f.flush()
        os.fsync(f.fileno())

def inherited(path):
    """Verify a scoped tracked input against the authorized starting commit."""
    path = Path(path)
    data = subprocess.check_output(['git', 'show', f'{BASE}:{path.relative_to(ROOT)}'], cwd=ROOT)
    if file_hash(path) != digest(data):
        raise RuntimeError(f'INHERITED_INPUT_CHANGED: {path}')
    return read_json(path)

def r1_local():
    identity = inherited(R1 / 'MODEL_RUNTIME_IDENTITY.json')
    return Path(identity['cross_encoder']['local_path']).parents[2]

def source_receipt(path, role):
    path = Path(path)
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': file_hash(path), 'role': role}

def batch_identity(model_config_identity, raw_hashes, tensors):
    return digest(canonical({'model_config_identity':model_config_identity,
                             'ordered_raw_input_hashes':raw_hashes,'tensors':tensors}))
