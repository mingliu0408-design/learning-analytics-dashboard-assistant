"""Post-commit exact-member archive, reopened with CRC/size/hash readback."""
import zipfile
from pathlib import PurePosixPath
from i6_common import *

def main():
    head=git('rev-parse','HEAD')
    require(head!=START and git('rev-parse','HEAD^')==START,'ONE_ORIGINAL_COMMIT_REQUIRED')
    require(git('log','-1','--format=%s')=='RQ3-REBUILD-I6: align final citation contract and preserve bounded DEV continuation','COMMIT_SUBJECT')
    require(git('branch','--show-current')==BRANCH and not git('status','--porcelain=v1'),'CLEAN_END_GATE')
    changed=git('diff','--name-status',START,head).splitlines()
    require(all(x.startswith('A\t'+SCOPE) for x in changed),'ONLY_NEW_I6_FILES_ALLOWED')
    require(not ZIP.exists(),'NO_ZIP_OVERWRITE')
    tracked=git('ls-files',SCOPE).splitlines();members={}
    for name in tracked:
        p=ROOT/name;rel=str(p.relative_to(HERE))
        require(not p.is_symlink() and p.is_file(),'NO_SYMLINK_MEMBER')
        require(p.suffix in ('.py','.json','.jsonl','.md','.txt','.patch'),'UNEXPECTED_ARCHIVE_TYPE')
        require(not any(x in rel.lower() for x in ('h3_review','auth.json','.env','credentials','__pycache__')),'EXCLUDED_MEMBER')
        data=p.read_bytes()
        require(data==__import__('subprocess').check_output(['git','show',head+':'+name],cwd=ROOT),'COMMITTED_FILE_DRIFT')
        members[rel]=data
    versions=dict(starting_head=START,ending_head=head,branch=BRANCH,one_commit=True,changed_paths=changed,working_tree_clean=True,utc=utc())
    members['GIT_VERSION.json']=canonical(versions)+b'\n'
    manifest=dict(version='I6_ZIP_MANIFEST_V1',self_excluded='OUTPUT_MANIFEST.json',
        members=[dict(path=n,bytes=len(d),sha256=sha(d)) for n,d in sorted(members.items())],
        excluded=['credentials','authentication headers','human judgments','private real-person records','other worktrees','whole old archives','model weights'])
    members['OUTPUT_MANIFEST.json']=canonical(manifest)+b'\n'
    for name in members:
        p=PurePosixPath(name);require(not p.is_absolute() and '..' not in p.parts and '\\' not in name,'UNSAFE_ZIP_PATH')
    with zipfile.ZipFile(ZIP,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(members.items()):z.writestr(name,data)
    with zipfile.ZipFile(ZIP) as z:
        require(z.testzip() is None,'ZIP_CRC')
        require(len(z.namelist())==len(set(z.namelist())) and set(z.namelist())==set(members),'EXACT_ZIP_MEMBER_SET')
        for info in z.infolist():
            data=z.read(info.filename);require(info.file_size==len(members[info.filename]) and data==members[info.filename] and sha(data)==sha(members[info.filename]),'ZIP_READBACK')
    result=dict(path=str(ZIP),sha256=sha(ZIP.read_bytes()),bytes=ZIP.stat().st_size,members=len(members),
        crc='PASS',safe_paths='PASS',exact_file_set='PASS',lengths_and_sha256='PASS',starting_head=START,ending_head=head)
    write_once(OUTPUT/'REVIEW_ZIP_READBACK.json',result)
    print(canonical(result).decode())

if __name__=='__main__':main()
