"""RQ3-REBUILD-R0 audit helpers; no model/provider or private-data output."""
from __future__ import annotations
import hashlib
import importlib.abc
import json
from pathlib import Path
import socket
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import patch

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
BASE = '595b949185ad1b97cdbb9b0fdaeb9804aff7c45c'
BRANCH = 'research/rq3-rebuild-r0-single-gate'
I0 = ROOT / 'evaluation/rq3_real_c4/i0_integration'
I1 = ROOT / 'evaluation/rq3_real_c4/i1_route_integration'
PRODUCTION = ('utils/course_material_retriever.py', 'utils/c4_rag/retrievers.py',
              'utils/c4_rag/provider.py', 'utils/c4_real_adapters.py')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


@contextmanager
def offline_guard():
    counts = {'network_attempts': 0, 'model_or_provider_import_attempts': 0}
    blocked = {'openai', 'anthropic', 'torch', 'transformers', 'sentence_transformers',
               'huggingface_hub', 'requests', 'httpx'}
    if blocked.intersection(sys.modules):
        raise RuntimeError('FORBIDDEN_MODULE_ALREADY_LOADED')
    class DenyImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in blocked:
                counts['model_or_provider_import_attempts'] += 1
                raise RuntimeError('MODEL_OR_PROVIDER_IMPORT_BLOCKED')
    def deny_network(*args, **kwargs):
        counts['network_attempts'] += 1
        raise RuntimeError('NETWORK_BLOCKED')
    finder = DenyImports()
    sys.meta_path.insert(0, finder)
    try:
        with patch.object(socket.socket, 'connect', deny_network), \
             patch.object(socket.socket, 'connect_ex', deny_network), \
             patch.object(socket.socket, 'sendto', deny_network), \
             patch.object(socket, 'create_connection', deny_network), \
             patch.object(socket, 'getaddrinfo', deny_network):
            yield counts
    finally:
        sys.meta_path.remove(finder)


def diagnostic_exit(*, mode_allowed=True, p3_required=True, access_blocked=False,
                    ranking=False, status=None, corpus_available=True):
    """Normalize existing typed/trace exits for reports; never control retrieval."""
    if not mode_allowed:
        return 'MODE_DISABLED'
    if not p3_required:
        return 'P3_NOT_REQUIRED'
    if access_blocked:
        return 'ACCESS_BLOCKED'
    if not corpus_available:
        return 'CORPUS_UNAVAILABLE'
    if not ranking:
        return 'LEGACY_SEMANTIC_GATE_REJECTED'
    if status == 'NO_RESULT':
        return 'RETRIEVAL_NO_RELEVANT_RESULT'
    if status in ('LIMITED_EVIDENCE', 'WEAK_MATCH'):
        return status
    return 'RETRIEVAL_AVAILABLE'
