"""Preserve actual attempts, trace every slot and report mechanical limits only."""
from copy import deepcopy
from decimal import Decimal
import json
import shutil
from i5_common import *
from typed_v1 import ORIGINAL, candidate_issues, plan_kind
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.renderer import final_payload
from utils.c4_rebuild.i1.schemas import final_errors


def classification(status):
    if status == 'ACCEPTED': return 'ACCEPTED'
    if status == 'UNKNOWN_COMPLETION': return 'UNKNOWN'
    if status in ('NOT_ATTEMPTED',None) or status.startswith('NOT_CALLED'): return 'UNTESTED'
    return 'FAILED'


def counts(values):
    return {k:values.count(k) for k in ('ACCEPTED','FAILED','UNKNOWN','UNTESTED')}


def main():
    from run_i5 import binding, usage_estimate, estimate
    require(git('rev-parse','HEAD')==START and git('branch','--show-current')==BRANCH,'GIT_PRECOMMIT_IDENTITY')
    require(not git('diff','--name-only') and not git('diff','--cached','--name-only'),'PREEXISTING_TRACKED_DRIFT')
    check_files(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files'])
    if (HERE/'PRECALL_IDENTITY_SEAL.json').exists():
        require(load(HERE/'PRECALL_IDENTITY_SEAL.json')['preflight']['binding']==binding(),'POSTLIVE_CODE_CONFIG_DRIFT')
    if OUTPUT.exists():
        require(not (HERE/'live').exists(),'LIVE_ALREADY_CAPTURED')
        shutil.copytree(OUTPUT,HERE/'live',symlinks=False)
        for p in OUTPUT.rglob('*'):
            require(not p.is_symlink(),'LIVE_SYMLINK')
            if p.is_file():
                require(p.read_bytes()==(HERE/'live'/p.relative_to(OUTPUT)).read_bytes(),'LIVE_COPY_DRIFT')
    live=HERE/'live'
    summary=load(live/'RUN_SUMMARY.json') if (live/'RUN_SUMMARY.json').exists() else dict(
        status='NO_PROVIDER_EXECUTION',stop_reason='NOT_EXECUTED',total_physical_calls=0,
        phase_counts=dict(INITIAL=0,CORRECTION=0,FINAL=0),slots=[])
    starts=[load(p) for p in sorted((live/'attempts').glob('*.start.json'))]
    attempts=[load(p) for p in sorted((live/'attempts').glob('*.outcome.json'))]
    require(len(starts)==summary['total_physical_calls'],'CALL_RECONCILIATION')
    oldreplay=[]; newreplay=[]; rows=[]; reader=bytearray(); reading_index=[]
    for number,row in enumerate(load_slots(),1):
        p=prepared(row); b=p['planner']['bridge']; logical=row['logical']
        old=[]
        for phase in ('initial','correction'):
            aid=f'{number:02}_{phase}'; base=HERE/'historical_i4/live/attempts'
            s=load(base/(aid+'.start.json')); o=load(base/(aid+'.outcome.json')); raw=load(base/(aid+'.raw.json'))
            status,value,issues=parse_response(raw,s['request'],lambda v:ORIGINAL.candidate_issues(b,v))
            require(status==o['status'] and value==o['value'] and sorted(canonical(i) for i in issues)==sorted(canonical(i) for i in o['issues']), 'HISTORICAL_REPLAY_CHANGED')
            old.append(dict(attempt_id=aid,status=status,issues=issues,candidate_sha256=sha(value),
                            raw_record=f'historical_i4/live/attempts/{aid}.raw.json'))
            oldreplay.append(dict(attempt_id=aid,status=status,exact_value=True,exact_issue_set=True))
        new=[]
        slot_attempts=sorted((x for x in attempts if x['logical']==logical),key=lambda x:x['monotonic_start'])
        accepted=next((a['value'] for a in slot_attempts if a['role']=='CANDIDATE' and a['status']=='ACCEPTED'),None)
        for o in slot_attempts:
            aid=o['attempt_id']; s=load(live/'attempts'/(aid+'.start.json')); raw=load(live/'attempts'/(aid+'.raw.json'))
            if not raw.get('_transport_failure'):
                validator=(lambda v:candidate_issues(b,v)) if o['role']=='CANDIDATE' else (lambda v:final_errors(v,p['trace']['retained_evidence_ids'],accepted))
                status,value,issues=parse_response(raw,s['request'],validator)
                require(status==o['status'] and value==o['value'] and sorted(canonical(i) for i in issues)==sorted(canonical(i) for i in o['issues']),'ACTUAL_NEW_REPLAY_CHANGED')
                newreplay.append(dict(attempt_id=aid,status=status,exact_value=True,exact_issue_set=True))
            trace=dict(attempt_id=aid,role=o['role'],phase=o['phase'],status=o['status'],issues=o['issues'],
                       request_sha256=o['request_sha256'],raw_sha256=o['raw_sha256'],raw_record=f'live/attempts/{aid}.raw.json')
            c=o['value'] if o['role']=='CANDIDATE' and isinstance(o['value'],dict) else None
            if c and isinstance(c.get('actions'),list):
                trace['no_date_schedule']=all(a.get('schedule') is None for a in c['actions'])
                trace['action_trace']=[dict(step_id=a.get('step_id'),task_id=a.get('task_id'),dependencies=a.get('dependencies'),
                    schedule=a.get('schedule'),resource_ids=a.get('resource_ids'),evidence_refs=a.get('evidence_refs'),
                    estimated_duration=a.get('estimated_duration')) for a in c['actions']]
                trace['plan_evidence_refs']=c.get('evidence_refs')
                trace['continues_plan_id']=c.get('continues_plan_id')
                trace['original_checker_issues']=ORIGINAL.candidate_issues(b,c)
            if o['role']=='FINAL':
                expected=final_payload(p,settings()['generation_roles']['FINAL'],accepted,False)
                require(s['request']==expected,'FINAL_RENDERER_CHANGED')
                require(sha(expected)!=row['prior_final_request_sha256'],'FINAL_INPUT_UNCHANGED')
                trace['final_changed_from_i2_fallback']=True
            new.append(trace)
            choices=raw.get('choices'); msg=choices[0].get('message') if isinstance(choices,list) and len(choices)==1 else None
            text=msg.get('content') if isinstance(msg,dict) else None
            if isinstance(text,str):
                reader.extend(f'\n# {logical} / {aid} / {o["status"]}\n\nVerbatim new provider message.content; exposed synthetic DEV only.\n\n'.encode())
                start=len(reader); reader.extend(text.encode()); end=len(reader); reader.extend(b'\n')
                reading_index.append(dict(attempt_id=aid,raw_record=f'live/attempts/{aid}.raw.json',start_byte=start,
                    end_byte_exclusive=end,text_sha256=sha(text.encode()),raw_pointer='/choices/0/message/content'))
        cs=[a for a in slot_attempts if a['role']=='CANDIDATE']; fs=[a for a in slot_attempts if a['role']=='FINAL']
        candidate_status=cs[-1]['status'] if cs else 'NOT_ATTEMPTED'; final_status=fs[-1]['status'] if fs else 'NOT_ATTEMPTED'
        candidate_class=classification(candidate_status); final_class=classification(final_status)
        slot_class=('ACCEPTED' if candidate_class==final_class=='ACCEPTED' else 'UNKNOWN' if 'UNKNOWN' in (candidate_class,final_class)
                    else 'FAILED' if 'FAILED' in (candidate_class,final_class) else 'UNTESTED')
        rows.append(dict(logical=logical,plan_kind=plan_kind(b)['kind'],historical_i4=old,new_attempts=new,
            candidate_status=candidate_status,candidate_class=candidate_class,final_status=final_status,final_class=final_class,
            slot_class=slot_class,selected_attempt=next((a['attempt_id'] for a in cs if a['status']=='ACCEPTED'),None),
            prepared_sha256=sha(p),source_file=row['directory']+'/prepared.json',source_refs={f['fact_id']:dict(
                pointer=f'/planner/bridge/planner_input/facts/{i}',value_sha256=sha(f['value'].encode()),
                source_ref=f['source_ref']) for i,f in enumerate(b['planner_input']['facts'])},
            semantic_support='NOT_CHECKED',human_inspection='PENDING',human_scores=[]))
    write_once(HERE/'FIVE_SLOT_OUTCOMES.json',dict(slots=rows,historical_outputs_never_repaired=True))
    write_once(HERE/'ACTUAL_MECHANICAL_REPLAY.json',dict(status='PASS',historical=oldreplay,new=newreplay,provider_calls=0))
    with (HERE/'DEVELOPMENT_READING_COPY_VERBATIM.md').open('xb') as f:
        f.write(bytes(reader) or b'No new provider message.content exists. See preserved stop receipts.\n')
    write_once(HERE/'READING_COPY_INDEX.json',dict(entries=reading_index,includes_only='New I5 content; historical candidates remain separate under historical_i4.'))
    charges=[]; known=[]
    for s in starts:
        o=next((a for a in attempts if a['attempt_id']==s['attempt_id']),{})
        usage=usage_estimate(o.get('usage'),settings()); reservation=Decimal(s['reserved_estimate_usd'])
        charges.append(max(reservation,usage or Decimal(0)))
        if usage is not None:known.append(usage)
    times=sorted(x['monotonic_start'] for x in attempts); gaps=[b-a for a,b in zip(times,times[1:])]
    require(all(x>=2 for x in gaps),'PACING_VIOLATION')
    phase_counts={k:sum(s['phase']==k for s in starts) for k in ('INITIAL','CORRECTION','FINAL')}
    account=dict(phase_counts=phase_counts,total_physical_calls=len(starts),
        role_counts=dict(CANDIDATE=phase_counts['INITIAL']+phase_counts['CORRECTION'],FINAL=phase_counts['FINAL']),
        attempt_status_counts={k:sum(x['status']==k for x in attempts) for k in sorted({x['status'] for x in attempts})},
        reservation_total_usd=str(sum((Decimal(s['reserved_estimate_usd']) for s in starts),Decimal(0))),
        conservative_charged_estimate_usd=str(sum(charges,Decimal(0))),known_uncached_usage_estimate_usd=str(sum(known,Decimal(0))),
        usage_missing_attempts=sum(not isinstance(x.get('usage'),dict) for x in attempts),
        unknown_completions=sum(x['status']=='UNKNOWN_COMPLETION' for x in attempts),
        cap_usd=0.25,exact_invoice_guarantee=False,minimum_monotonic_start_gap_seconds=min(gaps) if gaps else None,
        start_gaps_seconds=gaps,router_calls=0,retrieval_calls=0,memory_calls=0,embedding_calls=0,judge_calls=0,human_scores=0,
        deferred_unreserved_capacity=15-len(starts),config=settings())
    write_once(HERE/'CALL_USAGE_BUDGET_PACING.json',account)
    complete=summary['status']=='BOUNDED_EXECUTION_COMPLETE' and all(r['slot_class']=='ACCEPTED' for r in rows)
    status='COMPLETE_DEV_RETEST_PENDING_HUMAN_INSPECTION' if complete else 'BLOCKED_WITH_PRESERVED_EVIDENCE'
    qa=dict(status=status,stop_reason=summary.get('stop_reason'),candidate_counts=counts([r['candidate_class'] for r in rows]),
        final_counts=counts([r['final_class'] for r in rows]),slot_counts=counts([r['slot_class'] for r in rows]),
        call_counts=phase_counts,total_physical_calls=len(starts),
        original_ten_rejected_with_exact_errors=True,old_outputs_changed=False,code_frozen_during_live=True,
        semantic_counterexample='SEMANTIC_SUPPORT_NOT_CHECKED: unsupported +40% statement can pass mechanical validation.',
        evidence_limits=['Legal evidence IDs do not establish semantic entailment.',
            'Worksheet contents and unknown exercise state are not supplied facts.',
            'No adopted active plan is established by these five snapshots.',
            'Relative-week memory goals apply to their historical source scope; current goal validity needs confirmation.',
            'Model duration arithmetic is uncertain and does not establish actual feasibility.',
            'Original FINAL prompt/fallback unchanged; remaining prose or fallback shortcomings need separate versioned work.'],
        human_judgments_read=0,human_scores=0,human_inspection='PENDING',learning_effectiveness='NOT_EVALUATED',
        readiness='DEV wrapper only; no production integration, deployment or six-mode effect estimate.')
    write_once(HERE/'FINAL_QA.json',qa)
    write_once(HERE/'DEFERRED_UNTESTED.json',dict(slots=[r['logical'] for r in rows if r['slot_class']=='UNTESTED'],
        other_eleven_slots='NOT_CALLED',future_integration='NOT_EXECUTED',human_inspection='PENDING',follow_on_experiment='NOT_AUTHORIZED'))
    checklist=[dict(logical=r['logical'],reviewer=None,score=None,rationale=None,signature=None,
                    source_fidelity=None,worksheet_limitations=None,goal_and_plan_state=None,duration_uncertainty=None,
                    pedagogical_usefulness=None) for r in rows]
    write_once(HERE/'HUMAN_DEV_CHECKLIST_BLANK.json',dict(status='BLANK_FOR_HUMAN',slots=checklist))
    table='| Slot | Candidate | FINAL | Slot status |\n|---|---|---|---|\n'+''.join(
        f'| {r["logical"]} | {r["candidate_status"]} | {r["final_status"]} | {r["slot_class"]} |\n' for r in rows)
    (HERE/'FIVE_SLOT_TABLE.md').write_text(table)
    (HERE/'HUMAN_DEV_CHECKLIST_BLANK.md').write_text('# Human DEV inspection — blank\n\n'+''.join(
        '\n## '+r['logical']+'\n\nReviewer: ______\n\nSource fidelity: ______\n\nMissing facts and state: ______\n\nDuration uncertainty: ______\n\nPedagogical usefulness: ______\n\nScore: ______\n\nRationale: ______\n\nSignature: ______\n' for r in rows))
    tests=load(HERE/'OFFLINE_TEST_SUMMARY.json') if (HERE/'OFFLINE_TEST_SUMMARY.json').exists() else {}
    (HERE/'I5_COMPLETION_REPORT.md').write_text(
        '# I5 completion report\n\n'+status+'\n\nStop reason: '+str(summary.get('stop_reason'))+'\n\n'+table+
        '\nCalls: '+json.dumps(account['phase_counts'])+'; total '+str(len(starts))+'.\n\n'+
        'Candidate counts: '+json.dumps(qa['candidate_counts'])+'. FINAL counts: '+json.dumps(qa['final_counts'])+'.\n\n'+
        'Offline tests: '+str(tests.get('passed',0))+'/'+str(tests.get('tests_run',0))+' passed; skipped '+str(tests.get('skipped',0))+'.\n\n'+
        'Conservative charged reservation estimate USD '+account['conservative_charged_estimate_usd']+' within the USD 0.25 convention; not an invoice guarantee.\n\n'+
        'Only new files under '+SCOPE+' were added. Code, selected schema, config and request identities were sealed before live execution; original P0/P1 checker, P3, RAG, Memory and FINAL prompt/fallback stay unchanged.\n\n'+
        'Direct-message failure-stop rule is stricter than the packet maximum: one new correction is allowed; an exhausted candidate or failed FINAL stops later slots. No third candidate, FINAL retry, model switch or implicit resume.\n\n'+
        'The five I4 inputs were selected for exposed development failure categories. They are not a formal study, a representative sample or a six-mode effect estimate. Mechanical acceptance does not validate learning benefit or semantic entailment. Human inspection remains pending.\n\n'+
        '\n'.join('- '+x for x in qa['evidence_limits'])+'\n\nGit start: '+START+'. The archive GIT_VERSION.json records the actual one-commit ending HEAD.\n')
    (HERE/'START_HERE.md').write_text('# I5 review\n\n'+status+'\n\nRead I5_COMPLETION_REPORT.md, FIVE_SLOT_TABLE.md and FINAL_QA.json first.\n\n'+
        'DEVELOPMENT_READING_COPY_VERBATIM.md contains every new raw message.content, with byte ranges in READING_COPY_INDEX.json. Live requests, raw responses and failures are under live/. Historical I4 candidates are separate under historical_i4/ and were never repaired.\n\n'+
        'INPUT_DERIVED_PLAN_KIND_AUDIT.json and TYPED_SCHEMA_CHANGE_REPORT.md explain the change. Tests and failed development runs are preserved in offline_runs/. PRECALL_IDENTITY_SEAL.json binds authorization and tested code. Human DEV checklists are blank.\n\n'+
        'This review package has no production deployment or pedagogical-effectiveness claim.\n')
    capture=[dict(path=str(p.relative_to(HERE)),actual_source=str(OUTPUT/p.relative_to(live)),
                  bytes=p.stat().st_size,sha256=sha(p.read_bytes())) for p in sorted(live.rglob('*')) if p.is_file()]
    write_once(HERE/'ACTUAL_OUTPUT_SOURCE_MANIFEST.json',dict(files=capture))
    write_once(HERE/'POSTRUN_SOURCE_PRESERVATION.json',dict(status='PASS',source_files_checked=len(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files']),
        original_ten_candidates_unchanged=True,preexisting_tracked_files_unchanged=True,postlive_execution_binding_sha256=sha(binding()),utc=utc()))
    print(canonical(dict(status=status,phase_counts=phase_counts,candidate_counts=qa['candidate_counts'],final_counts=qa['final_counts'],slots=qa['slot_counts'])).decode())


if __name__=='__main__':
    main()
