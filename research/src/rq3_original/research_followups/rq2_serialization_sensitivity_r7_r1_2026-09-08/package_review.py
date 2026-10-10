"""Export committed allowlisted artifacts and verify the ZIP by reopening it."""
from __future__ import annotations
import datetime,hashlib,json,stat,subprocess,zipfile
from pathlib import Path,PurePosixPath
BASE=Path(__file__).resolve().parent
REPO=BASE.parents[1]
DEST=Path('/Users/liuming/Downloads/THESIS_R7_R1_RQ2_SERIALIZER_SENSITIVITY_REVIEW_2026-09-08.zip')
def git(*args):return subprocess.check_output(['git',*args],cwd=REPO)
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 spec=json.loads((BASE/'PACKAGE_ALLOWLIST.json').read_text());files=spec['files'];assert len(files)==len(set(files))
 relative=BASE.relative_to(REPO).as_posix()
 head=git('rev-parse','HEAD').decode().strip();parent=git('rev-parse','HEAD^').decode().strip()
 assert parent=='1ddad9c9050565b56e15fe6cfb7982ce1d78cce0'
 changed=git('diff-tree','--no-commit-id','--name-only','-r','-z',head).decode().split('\0');changed=[p for p in changed if p]
 assert sorted(changed)==sorted(relative+'/'+p for p in files)
 assert not git('diff','--name-only','--',relative).strip()
 payload={}
 for name in files:
  p=BASE/name;assert p.is_file() and not p.is_symlink()
  committed=git('show',head+':'+relative+'/'+name);assert committed==p.read_bytes();payload[name]=committed
 receipt={'starting_head':parent,'delivery_commit':head,'branch':git('branch','--show-current').decode().strip(),'git_version':git('--version').decode().strip(),'commit_count':1,'committed_directory':relative,'committed_file_count':len(files),'staged_scope_exact':True,'pre_existing_outputs_preserved':True,'no_push_or_merge':True,'status_after_commit':git('status','--short').decode(),'package_only_members':['GIT_RECEIPT.json','MANIFEST.json']}
 payload['GIT_RECEIPT.json']=(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode()
 manifest={'format':'R7_R1_REVIEW_MANIFEST_V1','manifest_self_excluded':True,'self_exclusion_reason':'Avoid self-hash recursion; all other members are covered','files':[{'path':n,'size_bytes':len(v),'sha256':sha(v)} for n,v in sorted(payload.items())],'total_zip_member_count':len(payload)+1,'exclusions':['runtime temporary and dependency cache directories','unrelated experimental libraries','MPNet model weights','credentials and personal signatures','W7/S7 activity files']}
 payload['MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
 dest=DEST
 if dest.exists():
  suffix=datetime.datetime.now().strftime('%H%M%S');dest=DEST.with_name(DEST.stem+'_v'+suffix+DEST.suffix)
 with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for n,b in sorted(payload.items()):
   info=zipfile.ZipInfo(n,date_time=(2026,9,8,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(stat.S_IFREG|0o644)<<16;z.writestr(info,b)
 with zipfile.ZipFile(dest) as z:
  names=z.namelist();assert len(names)==len(set(names))==len(payload)
  assert z.testzip() is None
  for info in z.infolist():
   path=PurePosixPath(info.filename);assert not path.is_absolute() and '..' not in path.parts and '\\' not in info.filename
   assert stat.S_IFMT(info.external_attr>>16)!=stat.S_IFLNK
   raw=z.read(info);assert len(raw)==info.file_size==len(payload[info.filename]);assert sha(raw)==sha(payload[info.filename])
  reopened=json.loads(z.read('MANIFEST.json'));assert {x['path'] for x in reopened['files']}==set(names)-{'MANIFEST.json'}
  for e in reopened['files']:
   b=z.read(e['path']);assert len(b)==e['size_bytes'] and sha(b)==e['sha256']
 result={'path':str(dest),'sha256':sha(dest.read_bytes()),'size_bytes':dest.stat().st_size,'member_count':len(payload),'git':receipt,'verification':{'CRC':'PASS','safe_paths':'PASS','duplicates':'NONE','member_lengths':'PASS','all_member_hashes':'PASS','manifest_self_exclusion':'DECLARED','committed_bytes_readback':'PASS'}}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
