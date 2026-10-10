"""Post-commit allowlisted review packaging, patch reconstruction and ZIP readback.

Writes only temporary staging and a new version-preserving Downloads archive
plus hash/verification sidecars. Never edits the repository or reruns retrieval.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from offline_common import BASE, BRANCH, OUT, ROOT, PRODUCTION, digest, git

TASK_FILES = (
    'START_HERE.md', 'COMPLETION_REPORT.md', 'STATUS.md',
    'CHANGE_AND_COMPATIBILITY_REPORT.md', 'P3_SINGLE_GATE_TEST_REPORT.md',
    'FIXED_CORPUS_RETRIEVER_COMPARISON_SPEC.md', 'SOURCE_MANIFEST.json',
    'SYNTHETIC_TEST_ATTEMPT_01.json', 'SYNTHETIC_TEST_ATTEMPT_02.json', 'COMPATIBILITY_CHECKS.json',
    'EXPOSED_21_CASE_GATE_DIAGNOSTIC.csv', 'EXPOSED_21_CASE_SOURCE_DETAILS.json',
    'EXPOSED_21_CASE_DIAGNOSTIC_SUMMARY.json', 'EXPOSED_DIAGNOSTIC_EXECUTION.json',
    'offline_common.py', 'test_p3_single_gate.py', 'run_synthetic_tests.py',
    'run_exposed_diagnostic.py', 'verify_compatibility.py', 'build_review_package.py',
)
CONTEXT = ('utils/c4_real_service.py', 'utils/c4_real_contracts.py', 'utils/c4_rag/corpus.py',
           'utils/c4_rag/models.py', 'tests/test_c4_real_service.py')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def safe(name):
    p = PurePosixPath(name)
    return not p.is_absolute() and '..' not in p.parts and '\\' not in name and str(p) == name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    assert Path.cwd().resolve() == ROOT
    assert git('branch', '--show-current').decode().strip() == BRANCH
    end = git('rev-parse', 'HEAD').decode().strip()
    assert git('rev-list', '--count', BASE + '..' + end).strip() == b'1'
    assert git('rev-parse', end+'^').decode().strip() == BASE
    assert git('log', '-1', '--format=%s').decode().strip() == 'RQ3-REBUILD-R0: use P3 as sole semantic course-retrieval gate'
    assert not git('status', '--porcelain=v1'), 'WORKTREE_NOT_CLEAN'
    task_rel = OUT.relative_to(ROOT).as_posix()
    expected_changes = set(PRODUCTION) | {task_rel + '/' + x for x in TASK_FILES}
    observed_changes = set(git('diff', '--name-only', BASE, end).decode().splitlines())
    assert observed_changes == expected_changes, (observed_changes ^ expected_changes)
    assert not git('diff', '--check', BASE, end)
    summary = json.loads((OUT/'EXPOSED_21_CASE_DIAGNOSTIC_SUMMARY.json').read_text())
    assert summary['status'] == 'COMPLETED_ONE_PAIRED_DIAGNOSTIC' and summary['paired_passes'] == 1
    assert summary['all_21_old_results_match_frozen'] and summary['admitted_cases_ranking_unchanged']
    assert json.loads((OUT/'SYNTHETIC_TEST_ATTEMPT_02.json').read_text())['passed']
    assert json.loads((OUT/'COMPATIBILITY_CHECKS.json').read_text())['passed']
    source_manifest = json.loads((OUT/'SOURCE_MANIFEST.json').read_text())
    rechecked = 0
    for item in source_manifest['files']:
        if '::' in item['path']:
            continue
        data = git('show', item['version'] + ':' + str(Path(item['path']).relative_to(ROOT))) if item.get('version') else Path(item['path']).read_bytes()
        assert digest(data) == item['sha256'], 'SOURCE_CHANGED_AFTER_EXECUTION'
        rechecked += 1
    patch_bytes = git('diff', '--binary', '--full-index', BASE, end, '--')
    code_patch = git('diff', '--binary', '--full-index', BASE, end, '--', *PRODUCTION)
    with tempfile.TemporaryDirectory(prefix='rq3-r0-review-') as temporary:
        tmp = Path(temporary)
        reconstruction = tmp / 'reconstruction'
        reconstruction.mkdir()
        for rel in PRODUCTION:
            path = reconstruction / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(git('show', BASE + ':' + rel))
        for options in (('--check',), ()):
            subprocess.run(['git', 'apply', *options, '-'], input=patch_bytes, cwd=reconstruction, check=True, capture_output=True)
        reconstructed = []
        for rel in sorted(expected_changes):
            actual = (reconstruction / rel).read_bytes()
            expected = git('show', end + ':' + rel)
            assert actual == expected, 'PATCH_RECONSTRUCTION_MISMATCH'
            reconstructed.append({'path': rel, 'sha256': digest(actual), 'bytes': len(actual)})
        files = {name: git('show', end + ':' + task_rel + '/' + name) for name in TASK_FILES}
        for rel in PRODUCTION:
            files['code/' + rel] = git('show', end + ':' + rel)
        for rel in CONTEXT:
            assert git('show', BASE + ':' + rel) == git('show', end + ':' + rel)
            files['context/' + rel] = git('show', end + ':' + rel)
        files['CHANGES.patch'] = patch_bytes
        files['CODE_ONLY.patch'] = code_patch
        files['PATCH_VERIFICATION.json'] = encoded({'status': 'PASS', 'starting_head': BASE, 'ending_head': end,
            'git_apply_check': True, 'applied_in_fresh_temp_directory': True,
            'all_reconstructed_files_match_end_commit': True, 'files': reconstructed,
            'source_entries_rechecked_after_execution': rechecked})
        files['GIT_HANDOFF.json'] = encoded({'task': 'RQ3-REBUILD-R0', 'status': 'COMPLETED_WITH_LIMITATIONS',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'working_directory': str(ROOT), 'branch': BRANCH,
            'starting_head': BASE, 'ending_head': end, 'parent_is_starting_head': True, 'commit_count': 1,
            'commit_subject': git('log', '-1', '--format=%s').decode().strip(),
            'commit_time': git('log', '-1', '--format=%cI').decode().strip(),
            'tracked_tree_status': 'CLEAN', 'untracked_tree_status': 'CLEAN',
            'git_status_porcelain': '', 'git_diff_check': 'PASS',
            'changed_functions': ['utils.course_material_retriever.retrieve_course_chunks',
                'utils.c4_rag.retrievers.C4RAGLegacyLexical.retrieve',
                'utils.c4_rag.provider.C4CourseRAGProvider.retrieve',
                'utils.c4_real_adapters.C4SelectedR0CourseRAGAdapter.retrieve'],
            'other_changed_symbol': 'C4SelectedR0CourseRAGAdapter.identity',
            'modified_source_paths': list(PRODUCTION), 'added_task_paths': sorted(expected_changes-set(PRODUCTION)),
            'outside_scope_changes': [], 'historical_artifacts_and_thesis_unchanged': True,
            'post_commit_generated_files': ['GIT_HANDOFF.json', 'PATCH_VERIFICATION.json', 'CHANGES.patch', 'CODE_ONLY.patch', 'OUTPUT_MANIFEST.json'],
            'no_extra_commit_for_receipt': True, 'merge_deploy_upload_performed': False})
        prefix = 'RQ3_REBUILD_R0_P3_SINGLE_GATE_REVIEW_2026-09-06/'
        members = {prefix + k: v for k, v in files.items()}
        assert all(safe(name) for name in members)
        manifest_name = prefix + 'OUTPUT_MANIFEST.json'
        members[manifest_name] = encoded({'schema': 'review-output-manifest-v1',
            'scope': 'Exact review allowlist; this manifest excludes its own hash.',
            'members_excluding_manifest': [{'path': k, 'bytes': len(v), 'sha256': digest(v)} for k, v in sorted(members.items())]})
        candidate = tmp/'review.zip'
        with ZipFile(candidate, 'x', compression=ZIP_DEFLATED, compresslevel=9) as z:
            for name, content in sorted(members.items()):
                info = ZipInfo(name, (2026, 9, 6, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                z.writestr(info, content)
        target = Path(args.output).resolve()
        assert target.parent == Path('/Users/liuming/Downloads')
        assert target.name.startswith('RQ3_REBUILD_R0_P3_SINGLE_GATE_REVIEW_2026-09-06') and target.suffix == '.zip'
        original = target
        suffix = 2
        while target.exists() or Path(str(target)+'.verification.json').exists() or Path(str(target)+'.sha256').exists():
            target = original.with_name(original.stem + f'_v{suffix}' + original.suffix)
            suffix += 1
        with target.open('xb') as dst, candidate.open('rb') as src:
            shutil.copyfileobj(src, dst)
        with ZipFile(target) as z:
            assert z.testzip() is None
            names = z.namelist()
            assert len(names) == len(set(names))
            assert set(names) == set(members)
            assert all(safe(name) and not name.endswith('/') for name in names)
            manifest = json.loads(z.read(manifest_name))
            assert {r['path'] for r in manifest['members_excluding_manifest']} | {manifest_name} == set(names)
            for row in manifest['members_excluding_manifest']:
                b = z.read(row['path'])
                assert len(b) == row['bytes'] and digest(b) == row['sha256']
            assert all(z.read(k) == v for k, v in members.items())
        receipt = {'archive_path': str(target), 'sha256': digest(target.read_bytes()), 'bytes': target.stat().st_size,
            'file_count': len(members), 'manifest_listed_files': len(members)-1, 'crc_integrity': 'PASS',
            'safe_relative_member_paths': 'PASS', 'all_member_hashes_match': True, 'extra_members': [],
            'archive_manifest_bytes_match_staging': True, 'patch_reconstruction': 'PASS',
            'starting_head': BASE, 'ending_head': end, 'one_commit': True, 'worktree_clean': not bool(git('status','--porcelain=v1')),
            'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'prior_archive_preserved': target != original,
            'uploaded': False}
        with Path(str(target)+'.verification.json').open('xb') as f:
            f.write(encoded(receipt))
        with Path(str(target)+'.sha256').open('x') as f:
            f.write(receipt['sha256']+'  '+target.name+'\n')
        print(json.dumps(receipt, indent=2))

if __name__ == '__main__':
    main()
