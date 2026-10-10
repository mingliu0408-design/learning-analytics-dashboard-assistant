"""Postcommit, allowlisted review export and mandatory readback; never full repo."""
from pathlib import Path
from hashlib import sha256
import json
import stat
import subprocess
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from verify_review_zip import verify

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PREFIX='research_followups/rq3_rebuild/i0_human_integration/'
START='a15155b687264f235980836912f2e351bf428c9c'
TARGET=Path('/Users/liuming/Downloads/RQ3_REBUILD_I0_HUMAN_INTEGRATION_REVIEW_2026-09-06.zip')


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()


def main():
    assert str(ROOT)=='/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-i0-human-integration'
    assert git('branch','--show-current')=='research/rq3-rebuild-i0-human-integration'
    assert git('status','--porcelain=v1')=='','DIRTY_WORKTREE'
    end=git('rev-parse','HEAD');commits=git('rev-list','--reverse',START+'..HEAD').splitlines()
    assert len(commits)==6 and commits[-1]==end
    assert git('show','-s','--format=%s',end)=='RQ3-REBUILD-I0: integrate corrected modules for human-rated RQ3'
    lineage=json.loads((HERE/'receipts/SOURCE_INTEGRATION_LINEAGE.json').read_text())
    assert [r['cherry_pick_commit'] for r in lineage['integrations']]==commits[:5]
    changed=git('diff-tree','--no-commit-id','--name-status','-r',end).splitlines()
    assert all(r.startswith('A\t'+PREFIX) or r.startswith('A\tutils/c4_rebuild/') for r in changed)
    if TARGET.exists():raise FileExistsError('Existing requested review ZIP will not be overwritten')
    delivery=HERE/'delivery';delivery.mkdir(exist_ok=True)
    receipt=dict(starting_head=START,ending_head=end,branch=git('branch','--show-current'),
        commit_count_after_start=6,integration_commits=commits[:5],i0_task_commit=commits[-1],
        exact_i0_subject=git('show','-s','--format=%s',end),final_worktree='CLEAN',
        i0_added_files=len(changed),inherited_sources_unchanged=True,
        final_commit_own_hash_exclusion='Commit receipt produced after commit; stored in ignored delivery and review ZIP.')
    data={}
    tracked=git('ls-tree','-r','--name-only',end,'--',PREFIX,'utils/c4_rebuild').splitlines()
    for rel in tracked:
        p=ROOT/rel
        assert p.is_file() and not p.is_symlink()
        if rel.startswith(PREFIX):
            name=rel[len(PREFIX):]
            assert not any(part in ('.runtime','local_private','delivery','__pycache__') for part in Path(name).parts)
        else:name='implementation/'+rel
        assert name not in data
        assert p.suffix.lower() not in ('.sqlite','.db','.pkl','.xlsx','.safetensors','.zip')
        data[name]=p.read_bytes()
    data['GIT_COMMIT_RECEIPT.json']=(json.dumps(receipt,indent=2)+'\n').encode()
    codepaths=[r.split('\t',1)[1] for r in changed if r.endswith('.py') or r.endswith('/.gitignore')]
    patch=subprocess.check_output(['git','diff','--binary',commits[-2],end,'--',*codepaths],cwd=ROOT)
    data['implementation/CHANGED_CODE.patch']=patch
    manifest=dict(format='RQ3_REBUILD_I0_REVIEW_MANIFEST_V1',excluded_self='REVIEW_MANIFEST.json',
        archive_sha256_stored_externally=True,source_start=START,source_end=end,
        export_policy='Only I0 new source, synthetic fixtures/requests, source hashes, task packet, unscored outputs and receipts. No raw private rows, models, venvs, DBs, secrets, full course corpus or historical ratings.',
        members=[dict(path=n,bytes=len(b),sha256=sha256(b).hexdigest()) for n,b in sorted(data.items())])
    data['REVIEW_MANIFEST.json']=(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode()
    staging=delivery/'REVIEW_STAGING.zip'
    with ZipFile(staging,'w',compression=ZIP_DEFLATED,compresslevel=9) as z:
        for n,b in sorted(data.items()):
            i=ZipInfo(n,date_time=(2026,9,6,0,0,0));i.create_system=3
            i.external_attr=(stat.S_IFREG|0o644)<<16;i.compress_type=ZIP_DEFLATED
            z.writestr(i,b)
    first=verify(staging)
    with TARGET.open('xb') as f:f.write(staging.read_bytes())
    result=verify(TARGET)
    assert result['sha256']==first['sha256']
    result.update(starting_head=START,ending_head=end,final_worktree=git('status','--porcelain=v1') or 'CLEAN')
    (delivery/'GIT_COMMIT_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (delivery/'ZIP_VERIFICATION.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    TARGET.with_suffix('.zip.verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    TARGET.with_suffix('.zip.sha256').write_text(result['sha256']+'  '+TARGET.name+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='verified_members'},indent=2,ensure_ascii=False))


if __name__=='__main__':main()
