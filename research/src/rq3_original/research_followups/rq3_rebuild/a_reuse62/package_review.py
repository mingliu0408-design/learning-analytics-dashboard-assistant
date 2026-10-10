"""Create a bounded local review ZIP without private tables, models or run logs."""
from pathlib import Path
import json
import subprocess
import sys
import zipfile
from hashlib import sha256
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
from build_materials import START_HEAD,digest
from verify_review import verify

def main():
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    status=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    if status or branch!='research/rq3-rebuild-i1-pilot-launch':raise ValueError('PACKAGE_REQUIRES_RECORDED_CLEAN_BRANCH')
    receipt=dict(start_head=START_HEAD,head=head,branch=branch,tracked_status=status,
        original_task_scope='REUSED62_A',provider_calls_this_task=0)
    (HERE/'GIT_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    patch=subprocess.check_output(['git','diff','--binary',START_HEAD,head,'--','utils/c4_rebuild/service.py',str(HERE.relative_to(ROOT))],cwd=ROOT)
    (HERE/'CODE_CHANGES.patch').write_bytes(patch)
    preservation=[]
    for r in json.loads((HERE/'SOURCE_MANIFEST.json').read_text())['files']:
        if r['exists']:
            p=Path(r['path']);same=p.is_file() and digest(p.read_bytes())==r['sha256']
            preservation.append(dict(path=str(p),sha256=r['sha256'],unchanged=same))
    if not all(r['unchanged'] for r in preservation):raise ValueError('ORIGINAL_SOURCE_CHANGED')
    (HERE/'SOURCE_PRESERVATION.json').write_text(json.dumps(preservation,indent=2)+'\n')
    members={}
    roots=['START_HERE.md','METHOD.md','READABLE_REPLAY_62.md','SOURCE_IDENTITY_MAP.csv','COVERAGE_INPUT_MAP_62.csv',
        'INPUT_DIFFERENCES_62.json','SOURCE_MANIFEST.json','RECOVERY_COUNTS.json','SCOPE_REPLACEMENT.json',
        'BLOCKERS_AND_COVERAGE.md','FIX_STATUS.md','SOURCE_BINDING_FORMAT.md','TEST_REPORT.json','TEST_OUTPUT.txt',
        'PRECHECK_62.json','GIT_RECEIPT.json','CODE_CHANGES.patch','SOURCE_PRESERVATION.json','WORKBOOK_QA.json']
    for n in roots:members[n]=HERE/n
    for p in sorted(HERE.glob('*.py')):members[p.name]=p
    members['workbook.mjs']=HERE/'workbook.mjs'
    for folder in ['originals','runtime','historical','evaluation_reference','human','task_packet','sources']:
        for p in sorted((HERE/folder).rglob('*')):
            if p.is_file() and p.name!='WORKBOOK_INPUT.json':members[str(p.relative_to(HERE))]=p
    book=HERE/'outputs/01a07cbd-de18-7632-90a8-6cf69fda116a/REUSED62_BLANK_HUMAN_RATINGS.xlsx'
    members[str(book.relative_to(HERE))]=book
    # Dependencies already present in the same project: code snapshots only, not their old results.
    dirs=['utils/c4_rebuild','utils/c4_dashboard_scoped','utils/c4_memory','utils/c4_rag',
          'research_followups/rq3_rebuild/p0_planner_prototype/p0planner',
          'research_followups/rq3_rebuild/p1_planner_bridge/p1bridge',
          'research_followups/rq3_rebuild/m0_memory_data/code',
          'research_followups/rq3_rebuild/m1_memory_completeness/code']
    for rel in dirs:
        for p in sorted((ROOT/rel).rglob('*.py')):
            members['code/'+str(p.relative_to(ROOT))]=p
    for rel in ['utils/c4_real_adapters.py','utils/c4_real_contracts.py','utils/c4_real_streamlit.py',
                'utils/course_material_retriever.py','utils/course_metadata.py',
                'research_followups/rq3_rebuild/i5_typed_action_planner/typed_v1.py',
                'research_followups/rq3_rebuild/i5_typed_action_planner/i5_common.py',
                'research_followups/rq3_rebuild/i3_planner_diagnosis_repair/repair_v1.py']:
        members['code/'+rel]=ROOT/rel
    for rel in ['research_followups/rq3_rebuild/i0_human_integration/schemas',
                'research_followups/rq3_rebuild/p0_planner_prototype/schemas',
                'research_followups/rq3_rebuild/p1_planner_bridge/schemas']:
        for p in sorted((ROOT/rel).glob('*.json')):members['code/'+str(p.relative_to(ROOT))]=p
    for p in sorted((ROOT/'utils/c4_memory').rglob('*.sql')):members['code/'+str(p.relative_to(ROOT))]=p
    deps={n:digest(p.read_bytes()) for n,p in members.items() if n.startswith('code/')}
    (HERE/'CODE_DEPENDENCY_SNAPSHOT.json').write_text(json.dumps(deps,indent=2)+'\n')
    members['CODE_DEPENDENCY_SNAPSHOT.json']=HERE/'CODE_DEPENDENCY_SNAPSHOT.json'
    rows=[]
    for n,p in sorted(members.items()):
        if not p.is_file() or p.is_symlink():raise ValueError('ALLOWLIST_FILE_MISSING_OR_SYMLINK:'+str(p))
        rows.append(dict(member=n,bytes=p.stat().st_size,sha256=digest(p.read_bytes())))
    manifest=dict(schema_version='REUSED62_REVIEW_MANIFEST_V1',git=receipt,files=rows,
        exclusions=['API keys','raw student tables','complete course corpus','identity mappings','models','native DBs','old run logs','old Judge/human scores'],
        runtime_read_allowlist=['runtime/TASKS_62.jsonl','runtime/SOURCE_BINDINGS.json','runtime/CONFIG_PROPOSED.json'],
        reference_and_originals_never_generator=True)
    name='RQ3_REUSED_62_EVALUATION_READY_REVIEW_2026-09-07'
    out=HERE/(name+'.zip');v=2
    while out.exists():out=HERE/(name+f'_v{v}.zip');v+=1
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for n,p in sorted(members.items()):z.write(p,n)
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    result=verify(out);(HERE/'ZIP_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
