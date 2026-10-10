"""Narrow review export; read back every byte after the sole I2 commit."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import json
import os
import stat
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,load,sha,canonical,write_once
from utils.c4_rebuild.i1.policy import verify_source_manifest

HERE=Path(__file__).resolve().parent
LIVE=Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07')
AUTH=Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_AUTHORIZATION_2026-09-07.json')
ZIP=Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_EXECUTION_REVIEW_2026-09-07.zip')
START='6352d5ef6846e6d4e6d436d840811643642ff24f'

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()

def main():
    assert not ZIP.exists()
    assert load(HERE/'PRESERVATION_CHECKS.json')['status']=='PASS'
    assert git('rev-list','--count',START+'..HEAD')=='1'
    assert git('rev-parse','HEAD^')==START
    assert not git('status','--porcelain=v1')
    scope=str(HERE.relative_to(ROOT))+'/'
    changes=git('diff','--name-status',START,'HEAD').splitlines()
    assert all(s.startswith('A\t'+scope) for s in changes)
    verify_source_manifest(HOME/'SOURCE_MANIFEST.json')
    members={}
    provenance={}
    def add(name,data,origin):
        p=PurePosixPath(name)
        assert not p.is_absolute() and '..' not in p.parts and '\\' not in name
        assert name not in members
        members[name]=data
        provenance[name]=origin
    def add_file(name,path):
        assert path.is_file() and not path.is_symlink()
        add(name,path.read_bytes(),str(path))
    # This directory is entirely the new, reviewed I2 result commit.
    for p in sorted(HERE.rglob('*')):
        if p.is_file():
            assert p.suffix in ('.md','.json','.txt','.py')
            add_file('reports/'+str(p.relative_to(HERE)),p)
    source_allowlist=[
        'PILOT_CONFIGURATION_PROPOSED.json','TASK_MANIFEST.json','SOURCE_MANIFEST.json',
        'FROZEN_ROLE_REGISTRY.json','EXTERNAL_RUNTIME_RECEIPT.json','PROSPECTIVE_BUDGET_FINAL.json',
        'schemas/APPROVAL_V1.json','schemas/CANDIDATE_STRICT_V1.json','schemas/FINAL_STRICT_V1.json',
        'INTEGRATED_ROLE_EXECUTION_FLOW.md','run_pilot.py','offline_worker.py']
    for name in source_allowlist:
        add_file('source_reference/i1/'+name,HOME/name)
    mechanics=['common.py','policy.py','schemas.py','frozen_p3.py','renderer.py','durable.py',
        'orchestrator.py','transport.py','worker.py','memory.py','native_backend.py']
    for name in mechanics:
        add_file('mechanical_code/utils/c4_rebuild/i1/'+name,ROOT/'utils/c4_rebuild/i1'/name)
    for name in ('test_i1.py','test_runner_gates.py'):
        add_file('mechanical_code/tests/'+name,HOME/'tests'/name)
    add_file('authorization/EXTERNAL_APPROVAL.json',AUTH)
    live_inventory={}
    for p in sorted(LIVE.rglob('*')):
        if not p.is_file(): continue
        relative=str(p.relative_to(LIVE))
        if relative=='RUN.lock': continue
        assert p.suffix in ('.json','.jsonl')
        assert p.parent==LIVE or p.parent.name in ('attempts','terminals','stages')
        add_file('live/'+relative,p)
        live_inventory[relative]=sha(p.read_bytes())
    git_version=dict(workspace=str(ROOT),branch=git('branch','--show-current'),
        starting_head=START,ending_head=git('rev-parse','HEAD'),new_commits=1,
        commit_subject=git('log','-1','--format=%s'),worktree_status='CLEAN',
        scope='NEW_I2_DIRECTORY_ONLY',changed_files=changes)
    add('GIT_VERSION.json',canonical(git_version)+b'\n','POST_COMMIT_GIT_READBACK')
    approval_policy=dict(authorized_by='GENERIC_SESSION_USER_IDENTITY_NO_PERSONAL_SIGNATURE',
        signature='OPERATOR_RECORDED_EXPLICIT_USER_MESSAGE_APPROVAL',
        redaction_applied=False,reason='Record contains no personal signature or API secret; exact user-provided workspace paths retained for provenance.',
        exact_message='reports/DIRECT_USER_APPROVAL_MESSAGE.txt',
        credentials_included=False,databases_included=False,models_included=False,
        private_student_data_included=False,human_ratings_included=False,
        excluded_ephemeral_files=['live/RUN.lock'])
    add('EXPORT_BOUNDARIES.json',canonical(approval_policy)+b'\n','EXPORT_POLICY')
    readme=('I2 exposed synthetic development pilot review\n\n'
        'Start with reports/START_HERE.md and reports/I2_COMPLETION_REPORT.md.\n'
        'Actual generated answers: reports/DEVELOPMENT_READING_COPY.md.\n'
        'Raw synthetic provider requests, answers, routes, candidates and audit stages: live/.\n'
        'GIT_VERSION.json records the exact post-commit version. OUTPUT_MANIFEST.json binds all other members.\n'
        'Only the original checkout is executable; this narrow review export is not a standalone environment.\n'
        'No LLM Judge, human ratings or final research statistics. No external upload or review receipt is asserted.\n')
    add('README.md',readme.encode(),'EXPORT_ENTRY')
    secret=os.environ.get('OPENAI_API_KEY','').encode()
    assert secret and all(secret not in b for b in members.values())
    manifest=dict(schema_version='I2_REVIEW_EXPORT_MANIFEST_V1',excluded_self='OUTPUT_MANIFEST.json',
        members=[dict(path=n,bytes=len(b),sha256=sha(b),origin=provenance[n]) for n,b in sorted(members.items())])
    add('OUTPUT_MANIFEST.json',canonical(manifest)+b'\n','SELF_HASH_EXCLUDED')
    with zipfile.ZipFile(ZIP,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(members.items()):
            info=zipfile.ZipInfo(name,date_time=datetime.now().timetuple()[:6])
            info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3
            info.external_attr=(stat.S_IFREG|0o644)<<16
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(ZIP) as z:
        names=z.namelist()
        assert z.testzip() is None and len(names)==len(set(names))
        assert set(names)==set(members)
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
            assert not stat.S_ISLNK(info.external_attr>>16)
            assert z.read(info.filename)==members[info.filename]
        check=json.loads(z.read('OUTPUT_MANIFEST.json'))
        for row in check['members']:
            b=z.read(row['path'])
            assert sha(b)==row['sha256'] and len(b)==row['bytes']
    assert live_inventory=={n:sha((LIVE/n).read_bytes()) for n in live_inventory}
    receipt=dict(status='PASS',verified_at=datetime.now(timezone.utc).isoformat(),
        zip_path=str(ZIP),sha256=sha(ZIP.read_bytes()),bytes=ZIP.stat().st_size,members=len(members),
        manifest_members=len(manifest['members']),crc='PASS',exact_members='PASS',
        safe_paths='PASS',duplicates=0,symlinks=0,member_hashes_and_sizes='PASS',
        secret_exact_value_matches=0,live_outputs_unchanged=True,git=git_version,
        counts=load(HERE/'CALL_AND_USAGE_SUMMARY.json'),coverage=load(HERE/'ALL_SLOT_STATUS.json')['coverage'],
        output_directory=str(LIVE),external_upload_asserted=False)
    receipt_path=ZIP.with_suffix('.READBACK.json')
    write_once(receipt_path,receipt)
    print(json.dumps({k:receipt[k] for k in ('status','zip_path','sha256','bytes','members','coverage')},ensure_ascii=False))

if __name__=='__main__':
    main()
