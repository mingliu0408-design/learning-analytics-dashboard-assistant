"""Paired exposed synthetic diagnostics. Scoring happens after runtime returns."""
import argparse
import json
import csv
import tempfile
from collections import Counter
from pathlib import Path
from m1_common import OWNED, M0, object_sha, write_json, utc, sha, fresh_output
from state_harness import setup_episode, snapshot, ReadOnlyStore
from fixture_validation import assert_runtime_separation
from relations import compile_sidecar, read_bundle

def score(expected, got, ambiguous):
    required=set(expected['required']);got=set(got)
    missing=sorted(required-got);extra=sorted(got-required)
    unexpected=sorted(got-required-set(expected['acceptable_extra']))
    category=expected['source_class']
    if ambiguous or expected['ambiguous']:status='AMBIGUOUS'
    elif category in ('SOURCE_ABSENT','PRESENT_UNAUTHORISED'):status='NO_AUTHORIZED_SOURCE'
    elif not required:status='NOT_REQUIRED' if category in ('SESSION_ONLY','VISIBLE_ONLY') else ('NO_MATCH' if not got else 'WRONG_MATCH')
    elif not missing:status='FULL'
    elif required & got:status='PARTIAL'
    else:status='MISS'
    return {'coverage_status':status,'expected_fact_ids':sorted(required),'missing_fact_ids':missing,
            'extra_fact_ids':extra,'wrong_match_fact_ids':[] if expected['ambiguous'] else unexpected,
            'correct_facts':len(required&got),'required_facts':len(required)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=('lexical','hybrid'),required=True)
    ap.add_argument('--run-id',default='v1',choices=('v1','v2','v3'))
    args=ap.parse_args();out=fresh_output(OWNED/'diagnostics'/('linked_'+args.mode+'_'+args.run_id))
    write_json(out/'EXECUTION_CODE_HASHES.json',{'execution_utc':utc(),'files':[
        {'path':str(p.relative_to(OWNED)),'sha256':sha(p)} for p in sorted((OWNED/'code').glob('*.py'))]})
    fixture_dir=OWNED/'fixtures';freeze=json.loads((fixture_dir/'FIXTURE_FREEZE.json').read_text())
    for f in freeze['files']:assert sha(fixture_dir/f['path'])==f['sha256']
    assert sha(OWNED/'LINK_PROVENANCE_AND_EXPANSION_POLICY.md')==freeze['policy_document_sha256']
    cases=json.loads((fixture_dir/'linked_runtime_v1.json').read_text())
    expected={e['case_id']:e for e in json.loads((fixture_dir/'test_only_expectations_v1.json').read_text())}
    assert_runtime_separation(cases)
    backend=None;identity={'status':'NOT_RUN','reason':'EXPLICIT_LEXICAL_ONLY'}
    if args.mode=='hybrid':
        from local_backend import LocalBackend
        summary=json.loads((OWNED/'runtime_diagnostics/stages_v1/SUMMARY.json').read_text())
        if not summary['working_interpreters']:raise RuntimeError('NO_VERIFIED_LOCAL_ENCODER')
        try:backend=LocalBackend(summary['working_interpreters'][0],out)
        except Exception as exc:
            write_json(out/'STARTUP_FAILURE.json',{'status':'NOT_RUN','phase':'SERVICE_READINESS',
                'error':str(exc),'fixture_target_reads':0,'preserved_stderr':'WORKER_STDERR.txt'})
            raise
        identity={'status':'ENCODE_VERIFIED_BEFORE_DIAGNOSTICS','interpreter':summary['working_interpreters'][0],
                  'readiness':backend.ready}
    rows=[];traces=[];setup=[];graphs=[];envelopes=[];start=utc()
    try:
        for case in cases:
            with tempfile.TemporaryDirectory(prefix='m1-linked-',dir=OWNED/'.runtime') as td:
                dbs,aliases,receipts=setup_episode(case,Path(td)/'setup')
                graph,rejected=compile_sidecar(case,dbs,aliases)
                graphs.append({'case_id':case['case_id'],'graph':graph,'rejected_relations':rejected,
                               'source_events_frozen_before_retrieval':True})
                setup.append({'case_id':case['case_id'],'receipts':receipts,'relation_rejections':rejected})
                inverse={v:k for k,v in aliases.items()}
                state_before={course:sha(path) for course,path in dbs.items()}
                paired=[]
                for expand in (False,True):
                    calls_before=len(backend.inputs) if backend else 0
                    # No case labels, expectations or setup aliases cross the runtime API.
                    envelope,trace=read_bundle(dbs,graph,{'target':case['target'],'purpose':case['purpose']},
                                              expand=expand,backend=backend)
                    got=[inverse[m] for m in trace['kept_facts']]
                    with ReadOnlyStore(dbs[case['target']['course_id']],clock=lambda:case['target']['as_of']) as check:
                        authorized={r.memory_id for r in check.list_active_memories(case['target']['learner_id'],at=case['target']['as_of'])}
                        if not check.is_memory_enabled(case['target']['learner_id']):authorized=set()
                    violations=sorted(set(trace['kept_facts'])-authorized)
                    assert not violations, 'UNAUTHORIZED_SELECTED_FACT'
                    row={'case_id':case['case_id'],'source_class':expected[case['case_id']]['source_class'],
                         'mode':args.mode,'condition':trace['condition'],'retrieved_fact_ids':got,
                         'seed_fact_ids':[inverse[m] for m in trace['original_seed_ids']],
                         'added_fact_ids':[inverse[m] for m in trace['added_facts']],
                         'expansion_status':trace['expansion_status'],'exclusions':trace['exclusions'],
                         'omitted_facts':trace['omitted_facts'],'relation_rejections':rejected,
                         'same_state_sha256':object_sha(state_before),'semantic_executed':False,
                         'target_writes':0,'privacy_violations':violations}
                    row['encode_calls_during_read']=(len(backend.inputs)-calls_before) if backend else 0
                    row['semantic_executed']=row['encode_calls_during_read']>0
                    row.update(score(expected[case['case_id']],got,bool(trace['ambiguous_plan_ids'])))
                    rows.append(row);paired.append(trace)
                    traces.append({'case_id':case['case_id'],'trace':trace})
                    envelopes.append({'case_id':case['case_id'],'condition':trace['condition'],'envelope':envelope.payload})
                assert paired[0]['original_seed_items']==paired[1]['original_seed_items']
                assert state_before=={course:sha(path) for course,path in dbs.items()}
                print(case['case_id'],rows[-2]['coverage_status'],'->',rows[-1]['coverage_status'],
                      'extra',len(rows[-1]['extra_fact_ids']),flush=True)
    finally:
        if backend:
            backend.close();identity.update(status='EXECUTED',encode_calls=len(backend.inputs),
                                           input_receipts=backend.inputs,worker_exit_code=backend.process.returncode)
        write_json(out/'RUNTIME_IDENTITY.json',identity)
    for filename,values in [('PAIRED_RESULTS.json',rows),('TARGET_TRACES.json',traces),
                            ('SETUP_RECEIPTS.json',setup),('RELATION_PROVENANCE.json',graphs),
                            ('PLANNER_ENVELOPES.json',envelopes)]:write_json(out/filename,values)
    with (out/'PAIRED_RESULTS.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
    groups={}
    for condition in ('UNEXPANDED','EXPANDED'):
        subset=[r for r in rows if r['condition']==condition]
        groups[condition]={'cases':len(subset),'coverage':dict(Counter(r['coverage_status'] for r in subset)),
             'required_facts':sum(r['required_facts'] for r in subset),'correct_facts':sum(r['correct_facts'] for r in subset),
             'extra_facts':sum(len(r['extra_fact_ids']) for r in subset),
             'wrong_match_facts':sum(len(r['wrong_match_fact_ids']) for r in subset),
             'semantic_executed_rows':sum(r['semantic_executed'] for r in subset)}
    write_json(out/'SUMMARY.json',{'execution_start_utc':start,'execution_end_utc':utc(),'mode':args.mode,
         'groups':groups,'same_state_and_seed_rank_checks':len(cases),'target_writes':0,
         'llm_calls':0,'judge_calls':0,'p3_calls':0,'held_out_or_final_statistics':'NOT_RUN',
         'scope':'MODEL_AUTHORED_SYNTHETIC_DEVELOPMENT_NOT_FOR_INDEPENDENT_TEST',
         'db_files':'REMOVED_AFTER_RECEIPTS','policy':freeze['policy']})

if __name__=='__main__':main()
