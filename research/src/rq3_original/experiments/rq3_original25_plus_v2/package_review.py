"""Explicit allowlist, Git-bound repository-shaped review ZIP and full readback."""
from v2_common import *
import argparse
import zipfile
import subprocess
from datetime import datetime,timezone
import stat
import os

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def collect():
    files={}
    for folder in (V1,HERE):
        for p in folder.rglob('*'):
            if p.is_symlink():raise ValueError('NO_SYMLINK:'+str(p))
            if p.is_file() and '__pycache__' not in p.parts and '_delivery' not in p.parts and p.name!='.DS_Store':
                files[str(p.relative_to(ROOT))]=p
    for record in (HERE/'prepared_inputs/LOADED_CODE_DEPENDENCIES.json',HERE/'audit/LOADED_TEST_CODE_DEPENDENCIES.json',HERE/'audit/RUNTIME_OPEN_DEPENDENCIES.json'):
        for name in read(record):
            p=ROOT/name
            if p.is_file():files[name]=p
    # Lazy live execution dependencies, included as code only, never run here.
    for p in (ROOT/'utils/c4_rebuild/i1').glob('*.py'):files[str(p.relative_to(ROOT))]=p
    sql=ROOT/'utils/c4_memory/c4_memory_schema_v1.sql';files[str(sql.relative_to(ROOT))]=sql
    lock=ROOT/'research_followups/rq3_rebuild/p1_planner_bridge/P0_DEPENDENCY_LOCK.json'
    files[str(lock.relative_to(ROOT))]=lock
    for entry in read(lock)['files']:
        p=ROOT/'research_followups/rq3_rebuild/p0_planner_prototype'/entry['path']
        if sha(p.read_bytes())!=entry['sha256']:raise ValueError('P0_LOCK_DRIFT')
        files[str(p.relative_to(ROOT))]=p
    for p in (ROOT/'research_followups/rq3_rebuild/i0_human_integration/schemas').glob('*.json'):
        files[str(p.relative_to(ROOT))]=p
    p=ROOT/'research_followups/rq3_rebuild/m1_memory_completeness/code/native_stage_worker.py'
    files[str(p.relative_to(ROOT))]=p
    for entry in read(HERE/'prepared_inputs/FROZEN_ROLE_RECEIPT.json')['sources']:
        p=ROOT/entry['path']
        if sha(p.read_bytes())!=entry['sha256']:raise ValueError('FROZEN_ROLE_SOURCE_DRIFT')
        files[entry['path']]=p
    for name in files:
        parts=Path(name).parts
        if any(x in parts for x in ('.git','.env','node_modules','models','checkpoints')) or Path(name).suffix in ('.bin','.pt','.pth','.safetensors','.pkl'):
            raise ValueError('EXCLUDED_MEMBER:'+name)
        if name.startswith(('research_followups/rq3_rebuild/a_reuse62/runtime/','research_followups/rq3_rebuild/a_reuse62_replay_v2/runtime/')):
            raise ValueError('OLD_BATCH_RUNTIME_MUST_NOT_BE_PACKAGED')
    return files

def assemble():
    files=collect();head=git('rev-parse','HEAD')
    if git('branch','--show-current')!='research/rq3-rebuild-i1-pilot-launch':raise ValueError('BRANCH_CHANGED')
    if git('status','--porcelain'):raise ValueError('COMMIT_REVIEW_INPUTS_FIRST')
    git('merge-base','--is-ancestor',START_HEAD,head)
    changes=git('diff','--name-only',START_HEAD,head).splitlines()
    if any(not p.startswith('experiments/rq3_original25_plus_v2/') for p in changes):raise ValueError('UNEXPECTED_OUT_OF_SCOPE_CHANGE')
    payload={name:p.read_bytes() for name,p in files.items()}
    verified=[]
    requests=''.join(head+':'+name+'\n' for name in payload).encode()
    batch=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,input=requests,capture_output=True,check=True).stdout
    pos=0
    for name,data in payload.items():
        end=batch.index(b'\n',pos);header=batch[pos:end].split();pos=end+1
        if len(header)!=3 or header[1]!=b'blob':raise ValueError('UNBOUND_GIT_MEMBER:'+name)
        size=int(header[2]);blob=batch[pos:pos+size];pos+=size+1
        if blob!=data:raise ValueError('MEMBER_NOT_BOUND_TO_ENDING_GIT:'+name)
        verified.append(name)
    if pos!=len(batch):raise ValueError('GIT_BATCH_READBACK_LENGTH')
    lineage=dict(starting_head=START_HEAD,ending_head=head,branch=git('branch','--show-current'),
        starting_worktree_clean=True,ending_worktree_clean=True,changed_paths=changes,
        git_blob_verified_members=len(verified),commits=git('log','--format=%H %s',START_HEAD+'..'+head).splitlines())
    payload['GIT_LINEAGE.json']=(json.dumps(lineage,ensure_ascii=False,indent=2)+'\n').encode()
    payload['START_HERE.md']=('''# RQ3 original 25 + new 24 runnable review

Open [the delivery guide](experiments/rq3_original25_plus_v2/START_HERE.md).
There are 49 roster entries and 41 source-qualified tasks awaiting human review
and a single subsequent execution approval: 17 controlled original replays + 24
new English conditions in 12 paired families. Eight originals have specific missing
inputs. No model answers or human scores were produced.

Read [task/source material](experiments/rq3_original25_plus_v2/TASK_REVIEW_PACK.md),
[batch commands](experiments/rq3_original25_plus_v2/COMMANDS.md),
[remaining limits](experiments/rq3_original25_plus_v2/FIX_STATUS.md), and
[test results](experiments/rq3_original25_plus_v2/audit/V2_TESTS.json).

The archive has repository-relative paths. Run commands from this extracted root.
The adjacent rq3_original25_plus directory retains V1 Chinese and original messages;
it is archival input and is never automatically executed. Dependencies are the
existing source code and the frozen role inputs, not a new platform or new model.
Local Python/library availability is required. Model files and credentials are
excluded. A ZIP copy uses GIT_LINEAGE.json for preflight provenance, not a fake Git
repository. The originating host separately verified every packed file against Git.

MANIFEST.json covers every other member with SHA-256 and size. The external readback
receipt verifies ZIP CRC, path safety, duplicates, exact membership and all hashes.
Passing these checks does not establish answer quality or educational benefit.
''').encode()
    manifest=dict(version=VERSION,self_excluded='MANIFEST.json',git=lineage,
        created_utc=datetime.now(timezone.utc).isoformat(),members=[dict(path=n,bytes=len(v),sha256=sha(v)) for n,v in sorted(payload.items())],
        exclusions=['credentials and API keys','model weights','old 37-task data','old answers/Gold selected evidence/statistics except the explicitly requested original 50 archival messages','unnecessary raw personal data','old large logs','previous untracked nested delivery ZIP and its delivery receipts'],
        scope='LOCAL_REVIEW_ONLY_EXTERNAL_SOURCE_PERMISSION_PENDING')
    payload['MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    return payload

def verify(path):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist();names=z.namelist()
        if len(names)!=len(set(names)) or z.testzip() is not None:raise ValueError('ZIP_CRC_OR_DUPLICATES')
        for i in infos:
            p=Path(i.filename)
            if p.is_absolute() or '..' in p.parts or stat.S_ISLNK(i.external_attr>>16):raise ValueError('UNSAFE_ZIP_MEMBER')
        manifest=json.loads(z.read('MANIFEST.json'))
        expected={r['path'] for r in manifest['members']}|{'MANIFEST.json'}
        if expected!=set(names):raise ValueError('ZIP_MEMBER_SET')
        for entry in manifest['members']:
            raw=z.read(entry['path'])
            if len(raw)!=entry['bytes'] or sha(raw)!=entry['sha256']:raise ValueError('ZIP_READBACK_HASH')
        counts=json.loads(z.read('experiments/rq3_original25_plus_v2/audit/COUNTS.json'))
    return dict(path=str(path.resolve()),sha256=sha(path.read_bytes()),bytes=path.stat().st_size,members=len(names),
        manifest_members=len(manifest['members']),crc=True,duplicate_names=0,path_safe=True,all_member_hashes_verified=True,
        git=manifest['git'],counts=counts)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--verify-only',action='store_true')
    a=p.parse_args()
    if not a.verify_only:
        payload=assemble()
        # Exclusive creation: no existing user archive is overwritten.
        with a.output.open('xb') as f:
            with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                for name,data in sorted(payload.items()):
                    i=zipfile.ZipInfo(name,(2026,9,7,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED
                    i.external_attr=(0o100444 if name.endswith('.sqlite') else 0o100644)<<16
                    z.writestr(i,data)
            f.flush();os.fsync(f.fileno())
    print(json.dumps(verify(a.output),ensure_ascii=False,indent=2))

if __name__=='__main__':offline();main()
