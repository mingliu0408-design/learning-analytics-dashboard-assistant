"""Six-mode serial runner; default preflight cannot access a Provider or keys."""
from replay_common import *
import argparse
import subprocess
from controlled_runtime import Worker, source_for
from interfaces import final_payload, final_issues, freeze_answer, VERSION as WIRE_VERSION
from snapshot_planning import typed_planner

def code_identity():
    # Only executable dependencies, not historical Judge/Gold/research-output JSON.
    paths=subprocess.check_output(['git','ls-files','-z','utils','research_followups/rq3_rebuild'],cwd=ROOT).decode().split('\0')
    folders=('m0_memory_data/','m1_memory_completeness/','p0_planner_prototype/','p1_planner_bridge/',
        'i0_human_integration/','i1_pilot_launch/','i3_planner_diagnosis_repair/','i5_typed_action_planner/','a_reuse62/')
    paths=set(p for p in paths if p.endswith(('.py','.sql')) and (ROOT/p).is_file()
        and (p.startswith('utils/') or any('/'+folder in p for folder in folders)))
    paths.update(str(p.relative_to(ROOT)) for p in HERE.glob('*.py'))
    return sha({p:sha((ROOT/p).read_bytes()) for p in sorted(paths)})

def binding_identity(config,tasks,binding):
    memory=read(HERE/'runtime/MEMORY_BINDINGS.json')
    for mb in memory.values():
        for entry in [*mb['databases'].values(),mb['graph'],mb['source_events']]:checked(entry)
    return dict(config_sha256=sha(config),tasks_sha256=sha(tasks),sources_sha256=sha(binding),memory_sha256=sha(memory),
        code_sha256=code_identity(),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())

def approve(a,config,identity,output):
    if a.get('status')!='AUTHORIZED' or a.get('scope')!='CONTROLLED_REUSED62_FRESH_SIX_MODES_HUMAN_ONLY':
        raise PermissionError('NO_PROVIDER_AUTHORIZATION_THIS_ROUND')
    if not a.get('user_decision') or not a.get('external_source_scope_confirmed'):
        raise PermissionError('ONE_CONSOLIDATED_SOURCE_MODEL_BUDGET_DECISION_REQUIRED')
    if a.get('binding')!=identity:raise PermissionError('APPROVAL_BINDING_CHANGED')
    if config.get('approved') is not True:raise PermissionError('CONFIG_NOT_APPROVED')
    if not output or Path(a.get('output_directory','')).resolve()!=Path(output).resolve():raise PermissionError('OUTPUT_NOT_APPROVED')
    rates=config.get('uncached_usd_per_million');money=config.get('proposed_money_ceiling_usd')
    if not isinstance(rates,dict) or any(type(rates.get(k)) not in (int,float) or rates[k]<=0 for k in ('input','output')) or type(money) not in (int,float) or money<=0:
        raise PermissionError('MODEL_PRICE_AND_AGGREGATE_MONEY_BUDGET_PENDING')
    ids=a.get('task_ids')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(config['task_ids']):
        raise PermissionError('PREDECLARED_ROSTER_REQUIRED')
    if a.get('selection_basis')!='PREDECLARED_BEFORE_NEW_OUTPUTS':raise PermissionError('PERFORMANCE_SELECTION_FORBIDDEN')
    from preparation import CRITICAL
    if any(t in CRITICAL for t in ids) and a.get('include_declared_missing_fact_cases_as_limitations') is not True:
        raise PermissionError('MISSING_FACT_CASES_REQUIRE_EXPLICIT_PREDECLARED_TREATMENT')
    return ids

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preflight',action='store_true');p.add_argument('--execute',action='store_true')
    p.add_argument('--approval',type=Path);p.add_argument('--output',type=Path);p.add_argument('--resume',action='store_true')
    args=p.parse_args(argv)
    tasks=lines(HERE/'runtime/TASKS_62.jsonl');binding=read(HERE/'runtime/BINDINGS.json');config=read(HERE/'runtime/CONFIG_PROPOSED.json')
    from utils.c4_rebuild.contracts import Mode
    if [t['task_id'] for t in tasks]!=[f'U{i:03}' for i in range(1,63)] or config['task_ids']!=[t['task_id'] for t in tasks]:raise ValueError('ROSTER_CHANGED')
    if config['modes']!=[m.value for m in Mode] or config['role_contract_version']!=WIRE_VERSION:raise ValueError('MODE_WIRE_CONTRACT_CHANGED')
    if config['max_attempts_per_slot']!=2 or config['aggregate_attempt_ceiling']>1364:raise ValueError('CALL_BUDGET_EXPANSION')
    if config['generation_roles']['FINAL']!=config['generation_roles']['CANDIDATE']:raise ValueError('COMMON_GENERATION_MODEL_REQUIRED')
    identity=binding_identity(config,tasks,binding)
    if not args.execute:
        from preparation import assess
        rows=assess(tasks,binding)
        print(json.dumps(dict(binding=identity,total=62,input_bound=sum(r['input_binding_status']=='BOUND' for r in rows),
            source_sufficient=sum(r['source_sufficient_for_bounded_replay'] for r in rows),generation_authorized=0,
            provider_calls=0,tasks=rows),ensure_ascii=False,indent=2));return 0
    # No source preparation, transport construction, or credential read precedes this check.
    if not args.approval:raise PermissionError('NO_PROVIDER_AUTHORIZATION_THIS_ROUND')
    approved_ids=approve(read(args.approval),config,identity,args.output)
    tasks=[t for t in tasks if t['task_id'] in approved_ids]
    source_by_id={t['task_id']:source_for(t,binding) for t in tasks}
    from utils.c4_rebuild.i1.frozen_p3 import FrozenP3,ROLE_NAMES
    from utils.c4_rebuild.i1.durable import DurableRunner
    from utils.c4_rebuild.i1.transport import OpenAITransport
    frozen=FrozenP3();planner=typed_planner();worker=Worker()
    transport=OpenAITransport(approved=True,timeout=config['transport_timeout_seconds'])
    runner=None
    try:
        runner=DurableRunner(args.output,config,dict(identity,approved_ids=approved_ids),transport,resume=args.resume)
        for t in tasks:
            tid=t['task_id'];source=source_by_id[tid];route=None
            runner.stage(tid,'SOURCE',dict(task=sha(t),binding=sha(binding)),source)
            if not source['clarification']:
                result={}
                for role in ROLE_NAMES:
                    payload=frozen.request(role,source['primary'])
                    result[role]=runner.perform('P3:'+role+':'+sha(payload),role,payload)
                if all(r['status']=='ACCEPTED' for r in result.values()):
                    route=dict(rag_required=result['RAG']['value']['rag_required'],memory_required=result['MEMORY']['value']['memory_required'],
                        planning_required=result['B4_PLANNING']['value']['planning_required'],provider_identity='ACTUAL_FROZEN_P3')
                runner.stage(tid,'ACTUAL_P3',dict(primary=source['primary_sha256'],frozen=frozen.identity),dict(route=route,results=result))
            for mode in config['modes']:
                logical=tid+':'+mode
                rebuilt=worker.call(dict(op='prepare',task=t,mode=mode,config=config,bindings_path=str(HERE/'runtime/BINDINGS.json'),
                    bindings_digest=sha(binding),primary_sha256=source['primary_sha256'],route=route if mode.startswith(('S2','S3','S4','S5')) else None))
                runner.stage(logical,'MODULES',dict(source=sha(source),route=sha(route)),rebuilt)
                prepared=rebuilt['prepared'];plan=prepared['planner'];accepted=None;failed=False
                if plan and plan['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                    if planner.plan_kind(plan['bridge'])['kind']!='NEEDS_TASK_INFORMATION':
                        cfg=config['generation_roles']['CANDIDATE']
                        result=runner.perform(logical+':CANDIDATE','CANDIDATE',planner.candidate_payload(prepared,cfg),
                            lambda v:planner.candidate_issues(plan['bridge'],v),
                            lambda v,issues:planner.candidate_payload(prepared,cfg,previous=v,issues=issues))
                        accepted=result['value'] if result['status']=='ACCEPTED' else None
                    failed=accepted is None
                payload=final_payload(prepared,config['generation_roles']['FINAL'],accepted,failed)
                ids=prepared['trace']['retained_evidence_ids']
                result=runner.perform(logical+':FINAL','FINAL',payload,lambda v:final_issues(v,ids))
                response=freeze_answer(result['value'],ids,accepted) if result['status']=='ACCEPTED' else None
                runner.stage(logical,'RESPONSE',dict(request=sha(payload),plan=sha(accepted)),
                    dict(task_id=tid,mode=mode,result=result,response=response,human_scores=[]))
        print(json.dumps(dict(status='SEE_DURABLE_TERMINALS',output=str(args.output),conditions=len(tasks)*6)))
    finally:
        if runner:runner.close()
        transport.close()
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,PermissionError) as exc:print(str(exc),file=sys.stderr);raise SystemExit(2)
