"""Allowlisted ZIP, unique safe members, full hash/CRC readback. No external writes."""
from replay_common import *
import csv
import io
import subprocess
import zipfile
import stat

NAME='RQ3_REUSED_62_CONTROLLED_REPLAY_REVIEW_2026-09-07.zip'

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True)

def build():
    branch=git('branch','--show-current').strip();head=git('rev-parse','HEAD').strip()
    if branch!='research/rq3-rebuild-i1-pilot-launch':raise ValueError('BRANCH_CHANGED')
    if git('status','--porcelain'):raise ValueError('GIT_NOT_CLEAN')
    if git('merge-base',START,head).strip()!=START:raise ValueError('START_NOT_ANCESTOR')
    changed=git('diff','--name-only',START,head).splitlines()
    if not changed or any(not p.startswith(str(HERE.relative_to(ROOT))+'/') for p in changed):raise ValueError('CHANGE_SCOPE_EXPANDED')
    baseline=read(HERE/'audit/OLD_VERSION_BASELINE.json')
    assert all(file_id(OLD/n)==v for n,v in baseline.items())
    end=dict(branch=branch,start_head=START,end_head=head,clean=True,changed_files=changed,
        old_version_all_recorded_files_unchanged=True,original_dataset_sha256=sha((OLD/'originals/unified_benchmark_scenarios.jsonl').read_bytes()))
    write(HERE/'GIT_RECEIPT.json',end)
    (HERE/'CODE_CHANGES.patch').write_text(git('diff','--binary',START,head,'--',str(HERE.relative_to(ROOT)) ))
    import importlib.util
    spec=importlib.util.spec_from_file_location('controlled_package_runner',HERE/'run_batch.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    write(HERE/'BINDING_AT_DELIVERY.json',runner.binding_identity(read(HERE/'runtime/CONFIG_PROPOSED.json'),
        lines(HERE/'runtime/TASKS_62.jsonl'),read(HERE/'runtime/BINDINGS.json')))
    payload={}
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.py','.md','.json','.csv','.patch','.txt') and p.name not in ('ZIP_VERIFICATION.json','DELIVERY_RECEIPT.json'):
            payload[p.name]=p.read_bytes()
    for folder in ('runtime','sources','receipts','audit','human','evaluation_reference'):
        for p in (HERE/folder).rglob('*'):
            if p.is_file() and not p.is_symlink() and p.suffix in ('.json','.jsonl','.md','.csv','.xlsx'):
                payload[str(p.relative_to(HERE))]=p.read_bytes()
    # Reviewable inherited interfaces and source-operation dependencies, not full data or models.
    inherited=[OLD/'interfaces.py',ROOT/'utils/c4_rebuild/service.py',ROOT/'utils/c4_rebuild/contracts.py',
        ROOT/'utils/c4_rebuild/memory.py',ROOT/'utils/c4_rebuild/planning.py',ROOT/'utils/c4_rebuild/rag.py',
        ROOT/'utils/c4_rebuild/i1/memory.py',ROOT/'utils/c4_rebuild/i1/native_backend.py',
        ROOT/'utils/c4_rebuild/i1/durable.py',ROOT/'utils/c4_rebuild/i1/frozen_p3.py',
        ROOT/'utils/c4_rebuild/i1/renderer.py',ROOT/'utils/c4_rebuild/i1/schemas.py',
        ROOT/'research_followups/rq3_rebuild/m1_memory_completeness/code/relations.py',
        ROOT/'research_followups/rq3_rebuild/m0_memory_data/code/state_harness.py',
        ROOT/'utils/c4_memory/c4_memory_store.py',ROOT/'utils/c4_memory/c4_memory_writer.py',
        ROOT/'utils/c4_memory/c4_memory_retriever.py',ROOT/'utils/c4_dashboard_scoped/select.py']
    deps={str(p.relative_to(ROOT)):file_id(p) for p in inherited}
    write(HERE/'INHERITED_CODE_IDENTITIES.json',deps)
    payload['INHERITED_CODE_IDENTITIES.json']=(HERE/'INHERITED_CODE_IDENTITIES.json').read_bytes()
    for p in inherited:payload['inherited_code/'+str(p.relative_to(ROOT))]=p.read_bytes()
    manifest=dict(format='CONTROLLED_REPLAY_REVIEW_V2',git=end,members=[dict(path=n,bytes=len(data),sha256=sha(data)) for n,data in sorted(payload.items())],
        exclusions=['private SQLite/databases','full 624 course corpus','model weights','credentials','real identity mapping','old Judge scores','unrelated logs'],
        providers_called=0,ratings_filled=0,standalone_deployment=False)
    payload['MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    dest=HERE/'review_build'/NAME;dest.parent.mkdir(exist_ok=True)
    if dest.exists():raise FileExistsError(dest)
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for n,data in sorted(payload.items()):
            info=zipfile.ZipInfo(n,date_time=(2026,9,7,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(stat.S_IFREG|0o644)<<16;z.writestr(info,data)
    report=verify(dest)
    write(HERE/'ZIP_VERIFICATION.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))

def verify(path):
    p=Path(path)
    with zipfile.ZipFile(p) as z:
        assert z.testzip() is None
        names=z.namelist();assert len(names)==len(set(names))
        assert all(not n.startswith('/') and '..' not in Path(n).parts and '\\' not in n for n in names)
        assert all(not stat.S_ISLNK(i.external_attr>>16) for i in z.infolist())
        assert not any(Path(n).suffix.lower() in ('.sqlite','.db','.pkl','.safetensors','.bin') or 'local_private/' in n for n in names)
        manifest=json.loads(z.read('MANIFEST.json'))
        assert set(names)=={v['path'] for v in manifest['members']}|{'MANIFEST.json'}
        for v in manifest['members']:
            data=z.read(v['path']);assert sha(data)==v['sha256'] and len(data)==v['bytes']
        tasks=[json.loads(l) for l in z.read('runtime/TASKS_62.jsonl').decode().splitlines()]
        assert [t['task_id'] for t in tasks]==[f'U{i:03}' for i in range(1,63)]
        for n,fields,total in [('BLANK_RATINGS_2976.csv',['response_id','score','rationale','rater','signature'],2976),
                              ('COMMON_APPLICABILITY_496.csv',['applicable','reason','reviewer','signature'],496)]:
            rows=list(csv.DictReader(io.StringIO(z.read('human/'+n).decode('utf-8-sig'))))
            assert len(rows)==total and all(r[f]=='' for r in rows for f in fields)
        counts=json.loads(z.read('PREPARATION_COUNTS.json'))
        assert counts['bound_inputs']==62 and counts['source_sufficient_bounded_replay']==54 and counts['important_fact_missing']==8
        mem=json.loads(z.read('MEMORY_RESULTS.json'));assert mem['reads_completed']==9 and mem['target_writes']==0
    return dict(**file_id(p),members=len(names),manifest_hashed_members=len(names)-1,crc='PASS',paths='PASS',member_hashes='PASS',
        roster_62='PASS',blank_human_fields='PASS',private_database_and_models_excluded=True,git=manifest['git'])

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--verify':print(json.dumps(verify(sys.argv[2]),ensure_ascii=False,indent=2))
    elif len(sys.argv)==1:build()
    else:raise SystemExit('Usage: package_review.py [--verify ZIP]')
