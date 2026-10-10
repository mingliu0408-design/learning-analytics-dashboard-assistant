"""Export the single committed, allowlisted dataset revision and independently reopen its ZIP."""
from pathlib import Path, PurePosixPath
import subprocess
import json
import hashlib
import zipfile
import stat
import argparse

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
PREFIX='experiments/rq3_original25_plus/'
START='f3e12b21d162ab6beee8ed8aaa6224546d0779e5'
NAME='RQ3_ORIGINAL25_PLUS_NEW_CAPABILITY_DATASET_REVIEW_2026-09-07.zip'


def git(*args):
    return subprocess.check_output(['git','-C',str(REPO),*args])


def sha(data):return hashlib.sha256(data).hexdigest()


def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()


def verify(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        assert len(names)==len(set(names)),'duplicate ZIP members'
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
            assert not stat.S_ISLNK(info.external_attr>>16)
        assert z.testzip() is None,'CRC failure'
        manifest=json.loads(z.read('MANIFEST.json'))
        assert set(names)=={x['path'] for x in manifest['members']}|{'MANIFEST.json'}
        for item in manifest['members']:
            b=z.read(item['path']);assert len(b)==item['bytes'] and sha(b)==item['sha256'],item['path']
        counts=json.loads(z.read('audit/COUNTS.json'))
        assert (counts['original_queries'],counts['new_queries'],counts['families'])==(25,24,12)
        runtime=[json.loads(x) for x in z.read('runtime_tasks.jsonl').splitlines()]
        assert len(runtime)==49
        for x in names:
            if x.endswith('.json'):json.loads(z.read(x))
            elif x.endswith('.jsonl'):
                for line in z.read(x).splitlines():
                    if line:json.loads(line)
        assert z.read('TASKS_READABLE.md').decode().count('\n## ')==24
        assert z.read('ORIGINAL25_READABLE.md').decode().count('\n## ')==25
        lineage=json.loads(z.read('GIT_LINEAGE.json'))
        allow=json.loads(z.read('PACKAGE_ALLOWLIST.json'))['members']
        assert set(names)==set(allow)|{'GIT_LINEAGE.json','CHANGE_SUMMARY.md','MANIFEST.json'}
        return dict(zip_path=str(Path(path).resolve()),sha256=sha(Path(path).read_bytes()),
                    bytes=Path(path).stat().st_size,members=len(names),manifest_verified_members=len(manifest['members']),
                    crc='PASS',relative_paths='PASS',duplicates=0,symlinks=0,allowlist='PASS',hashes='PASS',
                    json_readback='PASS',readable_task_counts='PASS',git_start=lineage['start_head'],git_end=lineage['end_head'])


def build():
    end=git('rev-parse','HEAD').decode().strip()
    assert git('branch','--show-current').decode().strip()=='research/rq3-rebuild-i1-pilot-launch'
    assert git('rev-parse','HEAD^').decode().strip()==START,'expected one focused dataset commit'
    assert not git('status','--porcelain=v1').strip(),'worktree must be clean before export'
    changes=git('diff','--name-status',START,end).decode().splitlines()
    assert changes and all(row.startswith('A\t'+PREFIX) for row in changes),'existing path changed'
    paths=git('ls-tree','-rz','--name-only',end,'--',PREFIX).decode().rstrip('\x00').split('\x00')
    allow=json.loads((HERE/'PACKAGE_ALLOWLIST.json').read_text())['members']
    assert {p.removeprefix(PREFIX) for p in paths}==set(allow)
    payload={}
    for p in paths:
        relative=p.removeprefix(PREFIX)
        assert not (HERE/relative).is_symlink()
        b=git('show',end+':'+p)
        assert (HERE/relative).read_bytes()==b,'worktree/commit mismatch '+relative
        payload[relative]=b
    lineage=dict(start_head=START,end_head=end,branch='research/rq3-rebuild-i1-pilot-launch',
        repository_path=str(REPO),commit_count=1,commit_subject=git('show','-s','--format=%s',end).decode().strip(),
        changed_paths=len(changes),change_scope=PREFIX,all_changes_are_additions=True,
        existing_tracked_files_unchanged=not bool(git('diff','--name-only',START,end,'--','.',':(exclude)'+PREFIX+'**').strip()),
        raw_source_preservation='Raw source copies match SHA-256 recorded before task authoring; no original was modified.',
        commit_payload_readback='Every allowlisted member equals git show END:path',
        final_status='AI_ASSISTED_DRAFT_PENDING_SOURCE_REVIEW',
        note='GIT_LINEAGE/CHANGE_SUMMARY/MANIFEST are export metadata generated after the commit, so are not self-referential committed files.')
    assert lineage['existing_tracked_files_unchanged']
    payload['GIT_LINEAGE.json']=encoded(lineage)
    payload['CHANGE_SUMMARY.md']=(
        '# 本次数据提交\n\n'
        '新增原25名册、隔离原50消息、新24配对任务、实际课程/页面/会话来源、独立评价参考、可读材料及离线检查。\n\n'
        '原有生产工具、已完成修复、旧62题及结果均未改变。本提交只新增 '+str(len(changes))+' 个限定目录内文件。\n\n'
        '起始：`'+START+'`\n\n结束：`'+end+'`\n\n'
        '全部成员以MANIFEST中的SHA-256绑定；Git内容绑定详见GIT_LINEAGE.json。\n').encode()
    payload['MANIFEST.json']=encoded(dict(schema_version=1,self_excluded='MANIFEST.json',
        members=[dict(path=p,bytes=len(b),sha256=sha(b)) for p,b in sorted(payload.items())]))
    destination=HERE/'_delivery'/NAME;destination.parent.mkdir(exist_ok=True)
    if destination.exists():raise FileExistsError('Preserve existing archive: '+str(destination))
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p,b in sorted(payload.items()):
            info=zipfile.ZipInfo(p,date_time=(2026,9,7,0,0,0));info.external_attr=0o100644<<16
            info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,b)
    receipt=verify(destination)
    (destination.parent/'ZIP_READBACK.json').write_bytes(encoded(receipt))
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify');a=p.parse_args()
    if a.verify:print(json.dumps(verify(a.verify),ensure_ascii=False,indent=2))
    else:build()
