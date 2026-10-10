"""Thin serial six-mode runner. Default preflight is source-only and network-free."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT))
from build_materials import loadlines,digest
from runtime import readiness,Worker,source_files,checked_file
from interfaces import final_payload,final_issues,freeze_answer,typed_planner,VERSION

def code_identity():
    # Bind all tracked application/research code, plus this opt-in implementation.
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    files={p:digest((ROOT/p).read_bytes()) for p in paths if p.endswith(('.py','.json','.sql')) and (ROOT/p).is_file()}
    files.update({str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in HERE.glob('*.py')})
    return digest(files)

def approve(a,config,binding,output):
    if a.get('status')!='AUTHORIZED' or a.get('scope')!='REUSED62_SIX_MODES_372_FRESH_RESPONSES_HUMAN_ONLY':raise PermissionError('NEW_REUSED62_APPROVAL_REQUIRED')
    if not all(a.get(k) for k in ['authorized_by','authorized_at','signature']):raise PermissionError('AUTHOR_APPROVAL_INCOMPLETE')
    if config.get('approved') is not True:raise PermissionError('CONFIG_NOT_APPROVED')
    if any(a.get(k)!=v for k,v in binding.items()):raise PermissionError('APPROVAL_HASH_OR_VERSION_CHANGED')
    if not output or Path(a['output_directory']).resolve()!=Path(output).resolve():raise PermissionError('OUTPUT_NOT_APPROVED')
    if a['max_physical_calls']!=config['aggregate_attempt_ceiling']:raise PermissionError('CALL_BUDGET_MISMATCH')
    if not isinstance(config.get('uncached_usd_per_million'),dict) or not isinstance(config.get('proposed_money_ceiling_usd'),(int,float)):
        raise PermissionError('PRICE_AND_TOTAL_BUDGET_PENDING')
    rates=config['uncached_usd_per_million']
    if any(not isinstance(rates.get(k),(int,float)) or rates[k]<=0 for k in ['input','output']) or config['proposed_money_ceiling_usd']<=0:
        raise PermissionError('INVALID_PRICE_OR_BUDGET')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks',type=Path,default=HERE/'runtime/TASKS_62.jsonl')
    p.add_argument('--bindings',type=Path,default=HERE/'runtime/SOURCE_BINDINGS.json')
    p.add_argument('--config',type=Path,default=HERE/'runtime/CONFIG_PROPOSED.json')
    p.add_argument('--preflight',action='store_true');p.add_argument('--execute',action='store_true')
    p.add_argument('--approval',type=Path);p.add_argument('--output',type=Path);p.add_argument('--resume',action='store_true')
    args=p.parse_args(argv)
    tasks=loadlines(args.tasks);bindings=json.loads(args.bindings.read_text());config=json.loads(args.config.read_text())
    if [t['task_id'] for t in tasks]!=[f'U{i:03}' for i in range(1,63)] or config['task_ids']!=[t['task_id'] for t in tasks]:raise ValueError('EXACT_62_REQUIRED_NO_SUBSET')
    from utils.c4_rebuild.contracts import Mode
    if config['modes']!=[m.value for m in Mode] or config['role_contract_version']!=VERSION:raise ValueError('SIX_MODE_OR_INTERFACE_CONTRACT')
    if config['max_attempts_per_slot']!=2 or config['aggregate_attempt_ceiling']>1364:raise ValueError('UNREVIEWED_RETRY_OR_CALL_EXPANSION')
    roles=config['generation_roles']
    if roles['CANDIDATE']!=roles['FINAL'] or roles['FINAL']!={'model':'gpt-4o-mini-2024-07-18','temperature':0,'max_output_tokens':2048}:
        raise ValueError('COMMON_MODEL_AND_BUDGET_CHANGED_REQUIRES_REVIEWED_CONFIG_VERSION')
    statuses=readiness(tasks,bindings)
    worker=Worker();source_by_id={}
    for task,status in zip(tasks,statuses):
        if status['ready']:
            try:
                source_by_id[task['task_id']]=worker.call(dict(op='source',task=task,bindings_path=str(args.bindings.resolve()),bindings_digest=digest(bindings)))
            except Exception as exc:
                status.update(ready=False,gaps=['SOURCE_PREPARATION_FAILED:'+str(exc)])
    ready=sum(r['ready'] for r in statuses)
    binding=dict(config_sha256=digest(args.config.read_bytes()),tasks_sha256=digest(args.tasks.read_bytes()),
        sources_sha256=digest(args.bindings.read_bytes()),code_sha256=code_identity(),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    report=dict(total_tasks=62,loadable_tasks=62,complete_source_bound_tasks=ready,planned_conditions=372,
        actual_provider_calls=0,actual_latest_routes='NOT_RUN',binding=binding,tasks=statuses)
    if not args.execute:
        print(json.dumps(report,ensure_ascii=False,indent=2));return 0
    # All source, approval and configuration checks occur before credential/SDK access.
    if not args.approval:raise PermissionError('NO_PROVIDER_AUTHORIZATION_THIS_ROUND')
    approve(json.loads(args.approval.read_text()),config,binding,args.output)
    if ready!=62:raise ValueError('FULL62_SOURCE_BINDINGS_INCOMPLETE; no calls made')
    from utils.c4_rebuild.i1.frozen_p3 import FrozenP3,ROLE_NAMES
    from utils.c4_rebuild.i1.durable import DurableRunner
    from utils.c4_rebuild.i1.transport import OpenAITransport
    frozen=FrozenP3();planner=typed_planner()
    transport=OpenAITransport(approved=True,timeout=config['transport_timeout_seconds'])
    runner=None
    try:
        runner=DurableRunner(args.output,config,binding,transport,resume=args.resume)
        for task in tasks:
            cid=task['task_id'];source=source_by_id[cid];route=None
            runner.stage(cid,'SOURCE',{'task':digest(task),'bindings':digest(bindings)},source)
            if not source['clarification']:
                results={}
                for role in ROLE_NAMES:
                    request=frozen.request(role,source['primary'])
                    results[role]=runner.perform('P3:'+role+':'+digest(request),role,request)
                if all(v['status']=='ACCEPTED' for v in results.values()):
                    route=dict(rag_required=results['RAG']['value']['rag_required'],memory_required=results['MEMORY']['value']['memory_required'],
                        planning_required=results['B4_PLANNING']['value']['planning_required'],provider_identity='ACTUAL_FROZEN_P3')
                runner.stage(cid,'ACTUAL_P3',{'primary':source['primary_sha256'],'frozen_roles':frozen.identity},dict(route=route,results=results))
            for mode in config['modes']:
                logical=cid+':'+mode
                rebuilt=worker.call(dict(op='prepare',task=task,mode=mode,config=config,bindings_path=str(args.bindings.resolve()),
                    bindings_digest=digest(bindings),primary_sha256=source['primary_sha256'],route=route if mode.startswith(('S2','S3','S4','S5')) else None))
                runner.stage(logical,'MODULES',{'source':digest(source),'route':digest(route)},rebuilt)
                prepared=rebuilt['prepared'];plan=prepared['planner'];accepted=None;failed=False
                if plan and plan['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                    kind=planner.plan_kind(plan['bridge'])
                    if kind['kind']!='NEEDS_TASK_INFORMATION':
                        cfg=config['generation_roles']['CANDIDATE']
                        result=runner.perform(logical+':CANDIDATE','CANDIDATE',planner.candidate_payload(prepared,cfg),
                            lambda v:planner.candidate_issues(plan['bridge'],v),
                            lambda v,issues:planner.candidate_payload(prepared,cfg,previous=v,issues=issues))
                        accepted=result['value'] if result['status']=='ACCEPTED' else None;failed=accepted is None
                    else:failed=True
                request=final_payload(prepared,config['generation_roles']['FINAL'],accepted,failed)
                ids=prepared['trace']['retained_evidence_ids']
                result=runner.perform(logical+':FINAL','FINAL',request,lambda v:final_issues(v,ids))
                answer=freeze_answer(result['value'],ids,accepted) if result['status']=='ACCEPTED' else None
                runner.stage(logical,'RESPONSE',{'request':digest(request),'plan':digest(accepted)},
                    dict(task_id=cid,mode=mode,result=result,response=answer,planning_failed=failed,human_scores=[]))
        print(json.dumps(dict(status='BATCH_FINISHED_SEE_TERMINALS',output=str(args.output),expected_conditions=372)))
    finally:
        if runner:runner.close()
        transport.close()
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,PermissionError) as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(2)
