"""Local-only identities, output helpers, and fail-closed execution guard."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import hashlib
import importlib.abc
import importlib.machinery
import json
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'research_followups/rq3_rebuild/r1_retrieval_lab'
LOCAL = OUT / 'local_artifacts'
BASE = '4765e066bd512611cd7157098aa50a86d25e7ea8'
BRANCH = 'research/rq3-rebuild-r1-retrieval-lab'
V0 = 'daaba43aebeda730db2bd7aef4583729610242a1af44060615c3f4c235e67ede'
CE_REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
CE_ROOT = LOCAL / 'models/ms-marco-MiniLM-L6-v2' / CE_REVISION
COURSE = 'GOVERNED_DUTE_COURSE_SIX_SOURCE_V0'

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(value).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n')

@contextmanager
def offline_guard():
    counts = {'network_attempts': 0, 'forbidden_import_attempts': 0}
    blocked = {'openai', 'anthropic', 'utils.c_full_service', 'utils.c4_real_service'}
    class DenyLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            counts['forbidden_import_attempts'] += 1
            raise RuntimeError('GENERATOR_OR_SERVICE_IMPORT_FORBIDDEN')
    class Deny(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == x or fullname.startswith(x + '.') for x in blocked):
                # Transformers probes package availability using find_spec. Block
                # execution rather than harmless discovery of installed metadata.
                return importlib.machinery.ModuleSpec(fullname, DenyLoader())
    def deny(*args, **kwargs):
        counts['network_attempts'] += 1
        raise RuntimeError('NETWORK_FORBIDDEN_DURING_LOCAL_LAB')
    finder = Deny()
    sys.meta_path.insert(0, finder)
    try:
        with patch.object(socket.socket, 'connect', deny), patch.object(socket.socket, 'connect_ex', deny), \
             patch.object(socket.socket, 'sendto', deny), patch.object(socket, 'create_connection', deny), \
             patch.object(socket, 'getaddrinfo', deny):
            yield counts
    finally:
        sys.meta_path.remove(finder)
