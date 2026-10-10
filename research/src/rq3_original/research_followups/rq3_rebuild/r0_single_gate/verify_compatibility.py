"""Read-only structural compatibility and synthetic service regression checks."""
import ast
from datetime import datetime, timezone
import io
import sys
import unittest
from offline_common import BASE, OUT, ROOT, PRODUCTION, digest, git, offline_guard, write_json

sys.path.insert(0, str(ROOT))
changes = {
    'utils/course_material_retriever.py': {'retrieve_course_chunks'},
    'utils/c4_rag/retrievers.py': {'C4RAGLegacyLexical.retrieve'},
    'utils/c4_rag/provider.py': {'C4CourseRAGProvider.retrieve'},
    'utils/c4_real_adapters.py': {'C4SelectedR0CourseRAGAdapter.retrieve'},
}


def symbols(data):
    values = {}
    for node in ast.parse(data).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            values[node.name] = ast.dump(node, include_attributes=False)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    values[node.name + '.' + member.name] = ast.dump(member, include_attributes=False)
    return values

checks = []
for path, allowed in changes.items():
    old = symbols(git('show', BASE + ':' + path))
    new = symbols((ROOT / path).read_bytes())
    modified = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
    assert modified == allowed, (path, modified)
    checks.append({'path': path, 'changed_functions': sorted(modified),
                   'other_functions_unchanged': len(old) - len(modified),
                   'before_sha256': digest(git('show', BASE + ':' + path)),
                   'after_sha256': digest((ROOT / path).read_bytes())})
tracked = git('diff', '--name-only', BASE).decode().splitlines()
assert set(tracked) == set(PRODUCTION)
assert not git('diff', '--check')
assert all(not str(p.relative_to(ROOT)).startswith(('thesis/', 'evaluation/')) for p in OUT.rglob('*'))

with offline_guard() as counters:
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_c4_real_service.py')
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'base_head': BASE,
          'structural_checks': checks, 'tracked_changes_are_exact_four_allowed_sources': True,
          'all_historical_artifacts_and_thesis_bytes_unchanged_in_worktree': True,
          'git_diff_check': 'PASS', 'service_test_source_sha256': digest((ROOT/'tests/test_c4_real_service.py').read_bytes()),
          'service_tests_run': result.testsRun, 'failures': len(result.failures),
          'errors': len(result.errors), 'skips': len(result.skipped), 'passed': result.wasSuccessful(),
          'guard_counters': counters, 'scope': 'Existing service tests use synthetic mock providers; no real course or saved input retrieval.',
          'test_output': stream.getvalue()}
write_json(OUT / 'COMPATIBILITY_CHECKS.json', report)
print(stream.getvalue())
print('Structural checks:',checks)
sys.exit(0 if result.wasSuccessful() else 1)
