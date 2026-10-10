#!/usr/bin/env python3
"""Post-commit, allowlisted ZIP builder. Writes only outside the repository."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = '595b949185ad1b97cdbb9b0fdaeb9804aff7c45c'
SCOPE = 'research_followups/rq3_rebuild/e0_crosspage_functional_check/'
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
destination = args.output.expanduser().absolute()
assert not destination.is_relative_to(ROOT), 'ZIP must be outside repository'


def git(*argv):
    return subprocess.check_output(['git', *argv], cwd=ROOT).decode().strip()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


ending = git('rev-parse', 'HEAD')
branch = git('branch', '--show-current')
assert branch == 'research/rq3-rebuild-e0-crosspage'
assert git('rev-parse', 'HEAD^') == BASE
assert git('rev-list', '--count', f'{BASE}..HEAD') == '1'
assert git('log', '-1', '--format=%s') == 'RQ3-REBUILD-E0: verify query-sensitive cross-page evidence path'
assert not git('status', '--porcelain=v1', '--untracked-files=all'), 'Working tree not clean'
assert not git('diff', '--check', BASE, ending), 'Committed diff whitespace check failed'
changed = git('diff', '--name-status', BASE, ending).splitlines()
assert all(line.startswith('A\t' + SCOPE) for line in changed), 'Changes must all be new E0 outputs'
members = sorted(git('ls-files', '--', SCOPE).splitlines())
disk = {p.relative_to(ROOT).as_posix() for p in HERE.rglob('*') if p.is_file()}
assert set(members) == disk, 'Disk/index allowlist mismatch'
stage = Path(tempfile.mkdtemp(prefix='rq3-e0-review-staging-', dir='/private/tmp'))
for rel in members:
    source = ROOT / rel
    assert not source.is_symlink()
    target = stage / source.relative_to(HERE)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

handoff = {'task': 'RQ3-REBUILD-E0', 'created_at_utc': datetime.now(timezone.utc).isoformat(), 'working_directory': str(ROOT), 'branch': branch, 'starting_head': BASE, 'ending_head': ending, 'commit_count': 1, 'commit_subject': git('log','-1','--format=%s'), 'change_summary': 'Output-only E0 functional audit; zero production/thesis/frozen experiment changes.', 'changed_files_name_status': changed, 'initial_tracked_tree_status': 'CLEAN', 'final_git_status_porcelain_v1': '', 'git_diff_check': {'command': ['git','diff','--check',BASE,ending], 'exit_code': 0, 'output': ''}, 'all_changes_confined_to_new_e0_outputs': True, 'receipt_generated_outside_repository_after_commit': True, 'not_a_deployment_or_experiment_authorisation': True}
(stage / 'GIT_HANDOFF.json').write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + '\n')
entries = []
for path in sorted(stage.rglob('*')):
    if path.is_file():
        raw = path.read_bytes()
        entries.append({'path': path.relative_to(stage).as_posix(), 'bytes': len(raw), 'sha256': sha(raw)})
manifest = {'task': 'RQ3-REBUILD-E0', 'manifest_self_excluded': True, 'members_excluding_manifest': entries, 'expected_total_file_members': len(entries) + 1, 'exclusions': ['credentials and environment files', 'raw learner/rater data', 'restricted identity maps and HMAC keys', 'candidate responses and ratings/rationales', 'complete course documents', 'models and environments', '.git', 'historical archives', 'unrelated artifacts']}
(stage / 'OUTPUT_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
if destination.exists():
    original = destination
    n = 2
    while destination.exists():
        destination = original.with_name(original.stem + f'_v{n}' + original.suffix)
        n += 1
destination.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for path in sorted(stage.rglob('*')):
        if path.is_file():
            z.write(path, path.relative_to(stage).as_posix())

# Reopen the newly created archive and verify archived bytes, not staging data.
with zipfile.ZipFile(destination, 'r') as z:
    assert z.testzip() is None
    names = z.namelist()
    assert len(names) == len(set(names))
    assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and '\\' not in n and not n.endswith('/') for n in names)
    archived_manifest = json.loads(z.read('OUTPUT_MANIFEST.json'))
    wanted = {r['path'] for r in archived_manifest['members_excluding_manifest']} | {'OUTPUT_MANIFEST.json'}
    assert set(names) == wanted, 'Missing or unexpected ZIP members'
    for r in archived_manifest['members_excluding_manifest']:
        raw = z.read(r['path'])
        assert len(raw) == r['bytes'] and sha(raw) == r['sha256'], r['path']
    assert json.loads(z.read('GIT_HANDOFF.json'))['ending_head'] == ending
    assert json.loads(z.read('TEST_RESULTS.json'))['diagnostic_suite_success']
    count = len(names)
receipt = {'actual_zip_path': str(destination), 'sha256': sha(destination.read_bytes()), 'bytes': destination.stat().st_size, 'file_members': count, 'manifest_hashed_members': count - 1, 'zip_crc_valid': True, 'safe_relative_paths': True, 'duplicate_members': 0, 'extra_members': 0, 'all_archived_member_hashes_verified': True, 'starting_head': BASE, 'ending_head': ending, 'final_git_status_porcelain_v1': git('status','--porcelain=v1','--untracked-files=all'), 'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'staging_directory': str(stage), 'local_delivery_only': True}
assert receipt['final_git_status_porcelain_v1'] == ''
receipt_path = destination.with_suffix('.verification.json')
with receipt_path.open('x') as f:
    json.dump(receipt,f,ensure_ascii=False,indent=2)
    f.write('\n')
print(json.dumps(receipt, ensure_ascii=False, indent=2))
