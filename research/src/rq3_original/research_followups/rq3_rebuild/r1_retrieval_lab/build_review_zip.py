"""Commit-bound allowlist ZIP with full readback; no full texts, models, or databases."""
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
import json
import stat
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *

DEST=Path('/Users/liuming/Downloads/RQ3_REBUILD_R1_RETRIEVAL_LAB_REVIEW_2026-09-06.zip')

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)

def main():
    head=git('rev-parse','HEAD').decode().strip()
    assert head!=BASE and git('rev-list','--count',BASE+'..HEAD').decode().strip()=='1'
    assert git('branch','--show-current').decode().strip()==BRANCH
    assert not git('status','--porcelain=v1').strip(),'WORKTREE_NOT_CLEAN'
    assert git('log','-1','--format=%s').decode().strip()=='RQ3-REBUILD-R1: add controlled retrieval and source-span chunking lab'
    diff=git('diff','--name-status',BASE,head).decode().splitlines()
    paths=[]
    for line in diff:
        status,path=line.split('\t',1)
        assert status=='A' and path.startswith(('utils/c4_rag_lab/','research_followups/rq3_rebuild/r1_retrieval_lab/'))
        assert 'local_artifacts' not in Path(path).parts
        assert not (ROOT/path).is_symlink()
        paths.append(path)
    verified=json.loads((OUT/'DELIVERY_VERIFICATION.json').read_text());assert verified['status']=='PASS'
    initial=json.loads((LOCAL/'starting_tracked_hashes.json').read_text())
    assert all(file_hash(ROOT/p)==h for p,h in initial.items())
    payload={p:(ROOT/p).read_bytes() for p in paths}
    payload['START_HERE.md']=(OUT/'START_HERE.md').read_bytes()
    codepaths=[p for p in paths if p.endswith('.py')]
    payload['CODE_ONLY.patch']=git('diff','--binary',BASE,head,'--',*codepaths)
    handoff={'task':'RQ3-REBUILD-R1','cwd':str(ROOT),'branch':BRANCH,'start_head':BASE,'end_head':head,
        'commit_count':1,'commit_subject':git('log','-1','--format=%s').decode().strip(),'worktree_clean':True,
        'all_changes_are_new_scoped_files':True,'changed_paths':paths,
        'existing_tracked_files_unchanged':len(initial),'verify_delivery_sha256':file_hash(OUT/'DELIVERY_VERIFICATION.json'),
        'no_merge_or_deploy':True,'source_root_and_scope':'exact governed six-source course allowlist',
        'post_commit_receipt_note':'Generated in the review archive to avoid self-referential Git hashes.'}
    payload['GIT_HANDOFF.json']=json.dumps(handoff,indent=2,sort_keys=True).encode()+b'\n'
    manifest={'task':'RQ3-REBUILD-R1','created_utc':datetime.now(timezone.utc).isoformat(),
        'self_excluded':True,'members':[{'path':p,'bytes':len(b),'sha256':digest(b)} for p,b in sorted(payload.items())],
        'allowlist_basis':'only added, committed files in two authorised directories plus entry, code patch and Git receipt',
        'exclusions':['local_artifacts','course and learner full text','weights','databases','credentials',
            'raw learner identifiers','candidate responses','ratings or Judge rationales','historical journals']}
    payload['REVIEW_MANIFEST.json']=json.dumps(manifest,indent=2,sort_keys=True).encode()+b'\n'
    for name in payload:
        p=PurePosixPath(name)
        assert not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
    with ZipFile(DEST,'x',compression=ZIP_DEFLATED,compresslevel=9) as z:
        for name,b in sorted(payload.items()):z.writestr(name,b)
    with ZipFile(DEST) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(set(z.namelist()))==len(payload)
        assert set(z.namelist())==set(payload)
        for info in z.infolist():
            name=info.filename;p=PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in name
            assert stat.S_IFMT(info.external_attr>>16)!=stat.S_IFLNK
            assert z.read(name)==payload[name]
        reread=json.loads(z.read('REVIEW_MANIFEST.json'))
        for item in reread['members']:
            b=z.read(item['path']);assert len(b)==item['bytes'] and digest(b)==item['sha256']
        assert json.loads(z.read('GIT_HANDOFF.json'))['end_head']==head
    receipt={'path':str(DEST),'sha256':file_hash(DEST),'bytes':DEST.stat().st_size,'members':len(payload),
        'hashed_members_excluding_manifest':len(payload)-1,'CRC':'PASS','safe_paths':'PASS',
        'all_member_hashes':'PASS','manifest_self_bytes_readback':'PASS','start_head':BASE,'end_head':head,
        'clean_after_packaging':not git('status','--porcelain=v1').strip()}
    write_json(LOCAL/'FINAL_ZIP_RECEIPT.json',receipt)
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
