"""Allowlisted post-commit review ZIP, exclusive creation and independent readback."""
from pathlib import Path,PurePosixPath
import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,sha,canonical,load,write_once

DEFAULT=Path('/Users/liuming/Downloads/RQ3_REBUILD_I1_PILOT_LAUNCH_REVIEW_2026-09-07.zip')
START='517c2097ceb454a0273b41ad790e5c498fd39985'
INTEGRATION='44bc6745a8a37176ad39d3890c5390f5d64221ac'


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def archive_allowlist():
    tracked=git('ls-files','-z').decode().split('\0')
    paths=[]
    prefix=str(HOME.relative_to(ROOT))+'/'
    h0='research_followups/rq3_rebuild/h0_human_evaluation/'
    r2='research_followups/rq3_rebuild/r2_candidate_reference/'
    h0docs={'START_HERE.md','COMPLETION_REPORT.md','AUTHOR_DECISIONS_NEEDED.md','COMMON_REFERENCE_AND_APPLICABILITY_PROTOCOL_DRAFT.md',
        'HUMAN_RUBRIC_GUIDE_DRAFT.md','HUMAN_ANALYSIS_PLAN_DRAFT.md','SUPERVISOR_RUBRIC_SOURCE_AUDIT.md','SOURCE_LINEAGE.json','rubric.json'}
    r2docs={'README.md','COMPLETION_REPORT.md','I0_RETRIEVER_INTERFACE_RECOMMENDATION.md','R0_SEEDED_RERANKING_DEV_RESULTS.md','UNRESOLVED_DECISIONS.json'}
    for name in tracked:
        if not name:continue
        include=(name.startswith(prefix) or name.startswith('utils/c4_rebuild/i1/') or
            name in ('utils/c4_rebuild/service.py','utils/c4_rebuild/memory.py') or
            name.startswith(h0) and (name[len(h0):] in h0docs or name[len(h0):].startswith(('schemas/','ui/','templates/'))) or
            name.startswith(r2) and name[len(r2):] in r2docs)
        if not include:continue
        p=ROOT/name
        if p.is_symlink() or p.suffix in ('.sqlite','.db','.safetensors','.pyc','.zip') or '.delivery' in p.parts or p.name=='RUN.lock':
            raise ValueError('NONREVIEW_OR_UNSAFE_FILE:'+name)
        paths.append(name)
    return sorted(paths)


def verify(path,expected=None):
    path=Path(path)
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        assert len(names)==len(set(names)), 'DUPLICATE_MEMBERS'
        assert z.testzip() is None, 'CRC_ERROR'
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            assert not p.is_absolute() and '..' not in p.parts and '.' not in p.parts and '\\' not in info.filename
            assert str(p)==info.filename and not stat.S_ISLNK(info.external_attr>>16) and not info.is_dir()
        declared=json.loads(z.read('EXPORT_ALLOWLIST.json'))['members']
        assert set(names)==set(declared) and len(declared)==len(set(declared)), 'ALLOWLIST_MISMATCH'
        if expected is not None:assert set(names)==set(expected), 'EXTERNAL_ALLOWLIST_MISMATCH'
        manifest=json.loads(z.read('OUTPUT_MANIFEST.json'))
        rows=manifest['members'];assert {r['path'] for r in rows}|{'OUTPUT_MANIFEST.json'}==set(names)
        assert len(rows)==len(names)-1
        for row in rows:
            data=z.read(row['path'])
            assert len(data)==row['bytes'] and sha(data)==row['sha256'], 'MEMBER_HASH_LENGTH:'+row['path']
    return dict(path=str(path),status='PASS',sha256=sha(path.read_bytes()),bytes=path.stat().st_size,
        members=len(names),crc='PASS',safe_paths='PASS',symlinks=0,duplicate_members=0,
        exact_allowlist='PASS',member_hashes_and_lengths='PASS',verified_manifest_members=len(rows))


def build(path=DEFAULT):
    assert not Path(path).exists(), 'OUTPUT_EXISTS_NO_OVERWRITE'
    assert git('branch','--show-current').decode().strip()=='research/rq3-rebuild-i1-pilot-launch'
    assert git('status','--porcelain=v1').strip()==b'', 'TRACKED_OR_UNTRACKED_WORKTREE_NOT_CLEAN'
    head=git('rev-parse','HEAD').decode().strip()
    assert git('log','-1','--format=%s').decode().strip()=='RQ3-REBUILD-I1: prepare bounded live pilot and human evaluation bridge'
    assert int(git('rev-list','--count',INTEGRATION+'..'+head))==1
    from utils.c4_rebuild.i1.policy import verify_source_manifest
    verify_source_manifest(HOME/'SOURCE_MANIFEST.json')
    validation=load(HOME/'VALIDATION_RESULTS.json');assert validation['status']=='PASS'
    selected=archive_allowlist();data={name:(ROOT/name).read_bytes() for name in selected}
    code=[p for p in selected if p.startswith('utils/c4_rebuild/') or
          p.startswith(str(HOME.relative_to(ROOT))+'/') and ('/task_spec/' not in p) and (p.endswith('.py') or '/schemas/' in p or p.endswith('/PILOT_CONFIGURATION_PROPOSED.json'))]
    patch=git('diff','--binary',INTEGRATION,head,'--',*code)
    receipt=dict(starting_head=START,branch='research/rq3-rebuild-i1-pilot-launch',
        handoffs=[{k:r[k] for k in ('label','original_commit','cherry_picked_commit','file_count','status')} for r in validation['handoffs']],
        after_handoffs_head=INTEGRATION,ending_head=head,original_i1_commits_after_handoffs=1,
        git_status='CLEAN',new_original_task_commit_message=git('log','-1','--format=%s').decode().strip(),
        source_manifest_sha256=sha((HOME/'SOURCE_MANIFEST.json').read_bytes()),
        implementation_patch_sha256=sha(patch),i1_changed_paths=git('diff','--name-only',INTEGRATION,head).decode().splitlines())
    data['GIT_VERSION.json']=canonical(receipt)+b'\n'
    data['IMPLEMENTATION.patch']=patch
    entry='research_followups/rq3_rebuild/i1_pilot_launch/START_HERE.md'
    data['START_HERE.md']=(
        '# I1 review archive\n\nOpen ['+entry+']('+entry+').\n\n'
        'Preparation only. Provider/real generation/Judge/Human scores: 0. '
        'Latest full mock: 72 accepted artificial responses; 173 focused tests passed. '
        'Configuration and human design remain pending author approval.\n\n'
        'GIT_VERSION.json binds the starting, integrated and final commits. '
        'IMPLEMENTATION.patch contains the I1 code/schema/policy changes. '
        'OUTPUT_MANIFEST.json binds every other member. '
        'This allowlisted archive is not the full project; use the recorded original checkout for execution. '
        'Mock strings and source-review drafts must never be presented as real responses or rating truth.\n').encode()
    names=sorted([*data,'EXPORT_ALLOWLIST.json','OUTPUT_MANIFEST.json'])
    data['EXPORT_ALLOWLIST.json']=canonical(dict(scope='I1_REVIEW_ONLY',members=names))+b'\n'
    manifest=dict(schema_version='I1_REVIEW_OUTPUT_MANIFEST_V1',excluded_self='OUTPUT_MANIFEST.json',
        ending_head=head,members=[dict(path=n,bytes=len(b),sha256=sha(b)) for n,b in sorted(data.items())])
    data['OUTPUT_MANIFEST.json']=canonical(manifest)+b'\n'
    delivery=HOME/'.delivery';delivery.mkdir(exist_ok=True)
    write_once(delivery/'GIT_VERSION.json',receipt)
    write_once(delivery/'OUTPUT_MANIFEST.json',manifest)
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,body in sorted(data.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,9,7,0,0,0));info.create_system=3
            info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,body)
    with Path(path).open('rb') as f:os.fsync(f.fileno())
    report=verify(path,names)
    write_once(delivery/'ZIP_READBACK_VERIFICATION.json',report)
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--verify':
        print(json.dumps(verify(sys.argv[2]),indent=2))
    else:build(Path(sys.argv[1]) if len(sys.argv)>1 else DEFAULT)
