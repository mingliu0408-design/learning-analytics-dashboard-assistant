"""Focused source/scope and actual receipt readback. No execution transport."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,load,sha,write_once
from utils.c4_rebuild.i1.policy import verify_source_manifest,validate_config
from utils.c4_rebuild.i1.schemas import CANDIDATE,FINAL,strict_schema_check

START='517c2097ceb454a0273b41ad790e5c498fd39985'
INTEGRATION='44bc6745a8a37176ad39d3890c5390f5d64221ac'
HANDOFFS=[('H0','099de69909327f6269989ebc0f528f299771acb1','f1dad979373393afa593adaba74c8e120fbeccf9',
           'research_followups/rq3_rebuild/h0_human_evaluation/'),
          ('R2','b7052410488f073965ba6ef577d9d420576a25e0',INTEGRATION,
           'research_followups/rq3_rebuild/r2_candidate_reference/')]


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()


def main():
    receipt=dict(status='PASS',checks={},provider_calls=0,api_keys_read=False,judge_calls=0,human_scores=0)
    checks=receipt['checks']
    assert Path.cwd()==ROOT
    assert git('branch','--show-current')=='research/rq3-rebuild-i1-pilot-launch'
    source=verify_source_manifest(HOME/'SOURCE_MANIFEST.json');checks['source_hashes']=len(source['files'])
    validate_config(load(HOME/'PILOT_CONFIGURATION_PROPOSED.json'))
    checks['configuration_unapproved']=True
    handoffs=[]
    for label,original,cherry,prefix in HANDOFFS:
        changed=git('diff-tree','--no-commit-id','--name-status','-r',original).splitlines()
        rows=[]
        for line in changed:
            status,path=line.split('\t');assert status=='A' and path.startswith(prefix)
            committed=subprocess.check_output(['git','show',original+':'+path],cwd=ROOT)
            current=(ROOT/path).read_bytes();assert current==committed
            rows.append(dict(path=path,bytes=len(current),sha256=sha(current)))
        handoffs.append(dict(label=label,original_commit=original,cherry_picked_commit=cherry,
                             status='EXACT_BYTES_PASS',file_count=len(rows),files=rows))
    receipt['handoffs']=handoffs;checks['handoff_byte_matches']=sum(r['file_count'] for r in handoffs)
    paths=git('diff','--name-only',START).splitlines()
    allowed=('research_followups/rq3_rebuild/i1_pilot_launch/','utils/c4_rebuild/',HANDOFFS[0][3],HANDOFFS[1][3])
    assert all(p.startswith(allowed) for p in paths)
    # The only modifications to pre-existing tracked sources are the two opt-in hooks.
    statuses=git('diff','--name-status',START).splitlines()
    assert all(line.startswith('A\t') or line.split('\t')[-1] in ('utils/c4_rebuild/memory.py','utils/c4_rebuild/service.py') for line in statuses)
    checks['protected_tracked_paths_modified']=0
    checks['new_working_paths_within_scope']=all(p.startswith(('research_followups/rq3_rebuild/i1_pilot_launch/','utils/c4_rebuild/i1/'))
        for p in git('ls-files','--others','--exclude-standard').splitlines())
    assert checks['new_working_paths_within_scope']
    subprocess.run(['git','diff','--check'],cwd=ROOT,check=True,capture_output=True)
    checks['git_diff_check']='PASS'
    tests={}
    for name,file,count in [('I1','TEST_FINAL.txt',62),('I0','I0_REGRESSION.txt',36),('H0_PYTHON','H0_PYTHON_REGRESSION.txt',60)]:
        text=(HOME/'receipts'/file).read_text();assert re.search(r'Ran '+str(count)+r' tests',text) and '\nOK\n' in text and not re.search(r'FAILED \(',text)
        tests[name]=dict(passed=count,failed=0,skipped=0,receipt_sha256=sha(text.encode()))
    ui=load(HOME/'receipts/H0_UI_REGRESSION.json');assert ui['status']=='PASS' and ui['passed']==15
    tests['H0_JS']=dict(passed=15,failed=0,skipped=0)
    receipt['tests']=tests;checks['focused_tests_passed']=sum(v['passed'] for v in tests.values())
    mock=load(HOME/'receipts/mock_final_02/MOCK_ACCEPTANCE_RESULT.json')
    assert mock['status']=='PASS' and mock['physical_mock_attempts']==117 and mock['accepted_mock_finals']==72
    checks['latest_mock']=mock
    resume=load(HOME/'receipts/FULL_RESUME_CHECK.json');assert resume['status']=='PASS' and resume['new_transport_attempts']==0
    checks['full_resume']=resume
    for f in ('mock_repair_trace','mock_candidate_failure_trace'):
        assert load(HOME/'receipts'/f/'FAULT_TRACE_RESULT.json')['status']=='PASS'
    checks['finite_repair_and_failed_plan_traces']='PASS'
    assert load(HOME/'receipts/GENERIC_MEMORY_NATIVE_CHECK.json')['status']=='PASS'
    checks['actual_synthetic_native_fallback']='PASS_LEXICAL_ONLY'
    strict_schema_check(CANDIDATE);strict_schema_check(FINAL);checks['strict_output_shapes']='PASS_LOCAL_NOT_PROVIDER_TESTED'
    for name,value in [('CANDIDATE_STRICT_V1.json',CANDIDATE),('FINAL_STRICT_V1.json',FINAL)]:
        assert load(HOME/'schemas'/name)==value
    blank=load(HOME/'human_preparation/h0_blank_ui/human/human_packet.json')
    assert blank['items']==[] and blank['item_template']['response'] is None
    assert all(r['score'] is None for r in load(HOME/'human_preparation/h0_blank_ui/human/ratings.json'))
    projected=load(HOME/'human_preparation/NO_RESPONSE_PROJECTIONS.json')
    assert projected['real_responses']==0 and projected['ratings']==[]
    for packet in projected['packets']:
        assert len({sha({k:v for k,v in i.items() if k not in ('item_id','response')}) for i in packet['items']})==1
        assert all(i['response'] is None for i in packet['items'])
    checks['common_dossier_six_mode_parity']='PASS_72_RESPONSE_FREE_SLOTS'
    budget=load(HOME/'PROSPECTIVE_BUDGET_FINAL.json');assert budget['conservative_prospective_usd']<2
    checks['prospective_budget']=dict(attempts=264,usd=budget['conservative_prospective_usd'],approved=False)
    write_once(HOME/'VALIDATION_RESULTS.json',receipt)
    print(json.dumps(dict(status='PASS',focused_tests=checks['focused_tests_passed'],
        handoff_files=checks['handoff_byte_matches'],source_files=checks['source_hashes'],provider_calls=0)))


if __name__=='__main__':main()
