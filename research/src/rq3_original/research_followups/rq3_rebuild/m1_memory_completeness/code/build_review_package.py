"""Commit-only exact allowlist export; generated receipts live in ignored M1 packaging."""
import json
import subprocess
import zipfile
import stat
from pathlib import Path
from m1_common import OWNED,REPO,START,utc,write_json
from verify_review_package import PREFIX,MANIFEST,verify
import hashlib

SUBTREE=OWNED.relative_to(REPO).as_posix()
DESTINATION=Path('/Users/liuming/Downloads/'+PREFIX+'.zip')


def git(*args):
    return subprocess.check_output(['git','-C',str(REPO),*args])

def serial(value):return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()

def build():
    assert git('branch','--show-current').decode().strip()=='research/rq3-rebuild-m1-memory-completeness'
    end=git('rev-parse','HEAD').decode().strip()
    assert git('rev-parse','HEAD^').decode().strip()==START
    assert git('rev-list','--count',START+'..HEAD').decode().strip()=='1'
    assert not git('status','--porcelain=v1').strip(), 'WORKTREE_NOT_CLEAN'
    changed=git('diff','--name-only',START,'HEAD').decode().splitlines()
    assert changed and all(p.startswith(SUBTREE+'/') for p in changed)
    assert git('log','-1','--format=%s').decode().strip()=='RQ3-REBUILD-M1: prototype source-linked memory recovery and isolate semantic runtime'
    tracked=git('ls-tree','-r','--name-only','HEAD','--',SUBTREE).decode().splitlines()
    payload={}
    for p in tracked:
        relative=Path(p).relative_to(SUBTREE).as_posix()
        assert not any(x in Path(relative).parts for x in ('.runtime','packaging','__pycache__','.venv'))
        assert Path(relative).suffix not in ('.sqlite','.db','.bin','.safetensors','.zip','.pyc')
        mode=git('ls-tree','HEAD','--',p).split()[0]
        assert mode==b'100644', 'NONREGULAR_TRACKED_FILE'
        payload[PREFIX+'/'+relative]=git('show','HEAD:'+p)
    receipt={'generated_utc':utc(),'cwd':str(REPO),'branch':git('branch','--show-current').decode().strip(),
        'starting_head':START,'ending_head':end,'parent_head':START,'new_commit_count':1,
        'commit_subject':git('log','-1','--format=%s').decode().strip(),
        'owned_tree':git('rev-parse','HEAD:'+SUBTREE).decode().strip(),
        'post_commit_tracked_untracked_status':'CLEAN_EMPTY','changed_paths':changed,
        'scope_check':'ALL_CHANGES_UNDER_M1_ONLY','protected_workspaces':'E1/R1 not accessed or modified'}
    payload[PREFIX+'/packaging/GIT_RECEIPT.json']=serial(receipt)
    payload[PREFIX+'/packaging/CHANGED_CODE.diff']=git('diff','--no-ext-diff',START,'HEAD','--',SUBTREE+'/code',SUBTREE+'/tests',SUBTREE+'/RELATION_SCHEMA_V1.json')
    manifest={'generated_utc':utc(),'kind':'EXACT_REVIEW_ARCHIVE_MEMBER_MANIFEST',
        'self_reference_exclusions':[MANIFEST],
        'external_exclusions':['ZIP_READBACK_RECEIPT.json (contains final ZIP hash, stored outside ZIP)'],
        'payload_scope':'All committed M1 files plus generated Git receipt and code/test/schema diff.',
        'private_exclusions':['databases','model weights','environments','credentials','raw real/student/course data',
          'original human/Judge scores','unrelated/parallel task outputs'],
        'members':[{'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in sorted(payload.items())]}
    payload[MANIFEST]=serial(manifest)
    local=OWNED/'.runtime'/DESTINATION.name
    if local.exists():raise FileExistsError(local)
    with zipfile.ZipFile(local,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(payload.items()):
            i=zipfile.ZipInfo(name);i.create_system=3;i.external_attr=(stat.S_IFREG|0o644)<<16
            i.compress_type=zipfile.ZIP_DEFLATED;z.writestr(i,data)
    result=verify(local,payload)
    write_json(OWNED/'packaging/LOCAL_ZIP_READBACK_RECEIPT.json',result)
    write_json(OWNED/'packaging/GIT_RECEIPT.json',receipt)
    print(json.dumps({k:v for k,v in result.items() if k!='members'},indent=2))


def export():
    local=OWNED/'.runtime'/DESTINATION.name
    source_receipt=json.loads((OWNED/'packaging/LOCAL_ZIP_READBACK_RECEIPT.json').read_text())
    observed=verify(local)
    assert observed['sha256']==source_receipt['sha256']
    with DESTINATION.open('xb') as f:f.write(local.read_bytes())
    result=verify(DESTINATION)
    assert result['sha256']==source_receipt['sha256'] and result['members']==source_receipt['members']
    result['checks']['expected_committed_and_generated_bytes']='PASS_VIA_IDENTICAL_VERIFIED_ARCHIVE_SHA256_AND_ALL_MEMBER_HASHES'
    write_json(OWNED/'packaging/ZIP_READBACK_RECEIPT.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='members'},indent=2))

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--export-to-downloads',action='store_true');args=ap.parse_args()
    export() if args.export_to_downloads else build()
