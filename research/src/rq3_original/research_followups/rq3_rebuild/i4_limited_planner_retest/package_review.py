"""Commit-bound allowlisted ZIP and external readback; no inference entrypoint."""
import argparse
import json
import re
import stat
import subprocess
import zipfile
from pathlib import PurePosixPath
from i4_common import *


def safe(name, data):
    p=PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and '\\' not in name,'UNSAFE_ARCHIVE_PATH')
    require(not p.name.startswith('.env') and p.suffix.lower() not in ('.db','.sqlite','.sqlite3','.pem','.key','.zip'),'EXCLUDED_FILE_TYPE')
    require(not re.search(rb'sk-[A-Za-z0-9_-]{20,}',data),'POSSIBLE_CREDENTIAL')


def manifest():
    rows=[]
    require(not (HERE/'OUTPUT_MANIFEST.json').exists(),'COMMITTED_MANIFEST_ALREADY_EXISTS')
    for p in sorted(HERE.rglob('*')):
        require(not p.is_symlink(),'SYMLINK_IN_I4')
        if p.is_file():
            name=str(p.relative_to(HERE));data=p.read_bytes();safe(name,data)
            rows.append(dict(path=name,bytes=len(data),sha256=sha(data)))
    write_once(HERE/'OUTPUT_MANIFEST.json',dict(version='I4_COMMITTED_OUTPUT_MANIFEST_V1',members=rows,
        self_excluded='OUTPUT_MANIFEST.json',source_scope=SCOPE,
        excluded=['credentials','headers','human judgments','personal identities','unrelated corpus','weights','databases','full old archives']))
    print(canonical(dict(committed_manifest_members=len(rows),status='PASS')).decode())


def package():
    end=git('rev-parse','HEAD')
    require(git('branch','--show-current')==BRANCH and git('rev-list','--count',START+'..HEAD')=='1','EXACT_ONE_RESULT_COMMIT_REQUIRED')
    require(git('rev-parse','HEAD^')==START,'START_PARENT_MISMATCH')
    require(not git('status','--porcelain=v1','--untracked-files=all'),'WORKTREE_NOT_CLEAN')
    changed=git('diff','--name-only',START,end).splitlines()
    require(changed and all(p.startswith(SCOPE) for p in changed),'GIT_SCOPE_ESCAPE')
    manifest=load(HERE/'OUTPUT_MANIFEST.json')
    for row in manifest['members']:
        data=(HERE/row['path']).read_bytes()
        require(len(data)==row['bytes'] and sha(data)==row['sha256'],'COMMITTED_OUTPUT_DRIFT')
    check_files(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files'])
    require(not ZIP.exists() and not ZIP.with_suffix('.READBACK.json').exists(),'ARCHIVE_OR_READBACK_ALREADY_EXISTS')
    entries={};origins={}
    for name in git('ls-files','--',SCOPE).splitlines():
        path=ROOT/name;rel=str(path.relative_to(HERE));data=path.read_bytes();safe(rel,data)
        archive_name='COMMITTED_OUTPUT_MANIFEST.json' if rel=='OUTPUT_MANIFEST.json' else rel
        require(not path.is_symlink() and archive_name not in entries,'DUPLICATE_OR_SYMLINK')
        blob=git('rev-parse',end+':'+name)
        require(subprocess.check_output(['git','cat-file','blob',blob],cwd=ROOT)==data,'GIT_BLOB_READBACK_MISMATCH')
        entries[archive_name]=data
        origins[archive_name]=dict(kind='COMMITTED_I4_FILE',commit=end,git_blob=blob,path=name)
    git_receipt=dict(branch=BRANCH,cwd=str(ROOT),starting_head=START,ending_head=end,
        starting_tree=git('rev-parse',START+'^{tree}'),ending_tree=git('rev-parse','HEAD^{tree}'),
        ending_parent=git('rev-parse','HEAD^'),new_commit_count=1,changed_paths=changed,
        commit_subject=git('log','-1','--format=%s'),tracked_untracked_clean=True,
        historical_72_answers_and_32_candidates_byte_identical=True,utc=utc())
    entries['GIT_VERSION.json']=canonical(git_receipt)+b'\n'
    entries['GIT_CHANGE.patch']=subprocess.check_output(['git','diff','--binary',START,end,'--',SCOPE],cwd=ROOT)
    origins['GIT_VERSION.json']=dict(kind='POST_COMMIT_GIT_RECEIPT')
    origins['GIT_CHANGE.patch']=dict(kind='ACTUAL_GIT_DIFF',start=START,end=end)
    zipmanifest=dict(version='I4_REVIEW_OUTPUT_MANIFEST_V1',self_excluded='OUTPUT_MANIFEST.json',
        committed_manifest='COMMITTED_OUTPUT_MANIFEST.json',
        members=[dict(path=n,bytes=len(data),sha256=sha(data),origin=origins[n]) for n,data in sorted(entries.items())],
        exclusions=manifest['excluded'])
    entries['OUTPUT_MANIFEST.json']=canonical(zipmanifest)+b'\n'
    for n,data in entries.items():safe(n,data)
    with zipfile.ZipFile(ZIP,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for n,data in sorted(entries.items()):
            info=zipfile.ZipInfo(n);info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
            z.writestr(info,data)
    with zipfile.ZipFile(ZIP) as z:
        names=z.namelist();require(len(names)==len(set(names)) and set(names)==set(entries),'ZIP_EXACT_ALLOWLIST')
        require(z.testzip() is None,'ZIP_CRC_FAILURE')
        for info in z.infolist():
            require(not stat.S_ISLNK(info.external_attr>>16),'ZIP_SYMLINK')
            data=z.read(info.filename);safe(info.filename,data)
            require(data==entries[info.filename],'ZIP_MEMBER_READBACK_MISMATCH')
        readbackmanifest=json.loads(z.read('OUTPUT_MANIFEST.json'))
        for row in readbackmanifest['members']:
            data=z.read(row['path']);require(len(data)==row['bytes'] and sha(data)==row['sha256'],'ZIP_MANIFEST_HASH')
        reader=z.read('DEVELOPMENT_READING_COPY_VERBATIM.md')
        for x in json.loads(z.read('READING_COPY_INDEX.json'))['entries']:
            require(sha(reader[x['start_byte']:x['end_byte_exclusive']])==x['text_sha256'],'ZIP_READER_HASH')
        account=json.loads(z.read('CALL_USAGE_BUDGET_PACING.json'))
    receipt=dict(status='VERIFIED',zip_path=str(ZIP),sha256=sha(ZIP.read_bytes()),bytes=ZIP.stat().st_size,
        members=len(entries),crc='PASS',paths='SAFE',duplicates=0,symlinks=0,exact_allowlist='PASS',
        member_sizes_hashes='PASS',verbatim_reader='PASS',manifest_self_excluded=True,
        starting_head=START,ending_head=end,phase_counts=account['phase_counts'],total_physical_calls=account['total_physical_calls'],
        local_creation_only=True,uploaded=False,utc=utc())
    write_once(ZIP.with_suffix('.READBACK.json'),receipt)
    require(load(ZIP.with_suffix('.READBACK.json'))==receipt,'EXTERNAL_RECEIPT_READBACK')
    print(canonical(receipt).decode())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['manifest','package']);a=p.parse_args()
    manifest() if a.action=='manifest' else package()
