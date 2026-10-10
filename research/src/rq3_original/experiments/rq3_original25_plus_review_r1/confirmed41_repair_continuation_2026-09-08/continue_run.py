"""Explicit fresh-directory A1 entry; old approvals and ordinary resume rejected."""
from a1_common import *
from copy import deepcopy
from contextlib import ExitStack
import argparse
import fcntl
import subprocess
import tempfile
import interface_a1 as repair
from parent_ledger import ParentLedger,ContinuationRunner
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3,ROLE_NAMES
from utils.c4_rebuild.i1.transport import OpenAITransport
from utils.c4_rebuild.i1.native_backend import I1LocalBackend


def frozen_context(manifest):
    m,tasks,binding,c=legacy.load_run(manifest)
    pp=policy();parent=ParentLedger()
    impact=load(HERE/'audit/IMPACT_AUDIT.json')
    if impact.get('passed') is not True or impact['decisions']!={'REUSE_ACCEPTED_PAYLOAD_EQUAL':168,'REPLACEMENT_ELIGIBLE_INPUT_CHANGED':6,'ONE_AUTHORIZED_SAME_PAYLOAD_UNKNOWN_RESEND':1}:
        raise ValueError('IMPACT_AUDIT_NOT_ACCEPTED')
    c=deepcopy(c);c.update(initial_slot_ceilings=pp['new_initial_slot_ceilings'],aggregate_attempt_ceiling=pp['new_physical_ceiling'])
    names={str(p.relative_to(ROOT)) for p in DATA.glob('*.py')}|{str(p.relative_to(ROOT)) for p in HERE.glob('*.py')}
    for e in load(DATA/'DEPENDENCIES.json')['files']:
        p=ROOT/e['path']
        if sha(p.read_bytes())!=e['sha256']:raise ValueError('INHERITED_DEPENDENCY_CHANGED:'+e['path'])
        names.add(e['path'])
    old_study=DATA/'confirmed41_generation_2026-09-07'
    for name,h in load(old_study/'BASELINE_FILES.json')['files'].items():
        if name!='RUN_MANIFEST.json' and sha((DATA/name).read_bytes())!=h:raise ValueError('R1_DATA_OR_HISTORY_CHANGED:'+name)
    for e in m['confirmed_study_sidecars']:
        if sha((DATA/e['path']).read_bytes())!=e['sha256']:raise ValueError('PARENT_PROTOCOL_CHANGED')
    frozen=FrozenP3()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='research/rq3-rebuild-i1-pilot-launch':raise ValueError('WRONG_BRANCH')
    ident=dict(manifest_sha256=sha(m),tasks_sha256=sha(tasks),bindings_sha256=sha(binding),config_sha256=sha(c),
        code_sha256=sha({n:sha((ROOT/n).read_bytes()) for n in sorted(names)}),git_head=head,git_basis='LIVE_GIT',
        continuation_policy_sha256=sha((HERE/'CONTINUATION_POLICY.json').read_bytes()),
        interface_version=repair.VERSION,parent_run_binding_sha256=sha((PARENT_RUN/'RUN_BINDING.json').read_bytes()),
        parent_ledger_sha256=parent.identity,parent_archive_sha256=pp['parent_archive_sha256'],
        impact_audit_sha256=sha((HERE/'audit/IMPACT_AUDIT.json').read_bytes()),
        study_protocol_sha256=sha((HERE/'REPAIR_PROTOCOL.md').read_bytes()),
        user_authorization_sha256=sha((HERE/'USER_AUTHORIZATION.md').read_bytes()),
        historical_budget_debit_usd=parent.budget_debit,frozen_p3_identity=frozen.identity,
        data_revision=m['data_revision'])
    return m,tasks,binding,c,ident,parent,frozen


def execute(context,approval,output):
    m,tasks,binding,config,ident,parent,frozen=context
    if output.exists():raise PermissionError('NEW_OUTPUT_DIRECTORY_REQUIRED_NO_RESUME')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():raise PermissionError('FROZEN_CLEAN_EXECUTION_TREE_REQUIRED')
    ids,c=legacy.approve(approval,ident,m,config,output)
    pp=policy()
    if ids!=m['task_ids'] or c['proposed_money_ceiling_usd']!=10.0 or c['uncached_usd_per_million']!=pp['uncached_usd_per_million']:
        raise PermissionError('A1_EXACT_SCOPE_AND_CUMULATIVE_BUDGET_REQUIRED')
    impact={r['logical']:r for r in load(HERE/'audit/IMPACT_AUDIT.json')['records']}
    transport=OpenAITransport(approved=True,timeout=c['transport_timeout_seconds']);runner=None
    try:
        runner=ContinuationRunner(output,c,dict(ident,approved_ids=ids,frozen_roles=frozen.identity),transport,parent)
        write_once(output/'CONTINUATION_CONTROL.json',dict(policy=pp,effective_config=c,parent_budget_debit_usd=parent.budget_debit,
            budget_is_cumulative=True,parent_unknown_permissions_are_parent_run_scoped=True,new_unknown_whitelist=[]))
        for t in tasks:
            if t['task_id'] not in ids:continue
            tid=t['task_id'];src=base.source_for(t,binding);route=None
            runner.stage(tid,'SOURCE',dict(task=sha(t),binding=sha(binding)),src)
            if not src['clarification']:
                results={}
                for role in ROLE_NAMES:
                    payload=frozen.request(role,src['primary'])
                    results[role]=runner.perform('P3:'+role+':'+sha(payload),role,payload)
                if all(r['status']=='ACCEPTED' for r in results.values()):
                    route=dict(rag_required=results['RAG']['value']['rag_required'],memory_required=results['MEMORY']['value']['memory_required'],
                        planning_required=results['B4_PLANNING']['value']['planning_required'],provider_identity='ACTUAL_FROZEN_P3')
                runner.stage(tid,'ACTUAL_P3',dict(primary=src['primary_sha256'],frozen=frozen.identity),dict(route=route,results=results))
            with ExitStack() as stack:
                backend=None
                need_native=any((tid+':'+mode,'MODULES') not in parent.stages for mode in c['modes'])
                if need_native and route and route['memory_required'] and load(DATA/'native_initial'/tid/'state_readable.json')['memories']:
                    lock=stack.enter_context(open('/private/tmp/rq3-rebuild-local-inference.lock','a+'))
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    td=stack.enter_context(tempfile.TemporaryDirectory(prefix='rq3-a1-native-backend-'))
                    backend=I1LocalBackend(Path(td));stack.callback(backend.close)
                    runner.stage(tid,'NATIVE_BACKEND',dict(data_binding=sha(binding['native'][tid])),dict(identity=backend.identity,ready=backend.ready))
                for mode in c['modes']:
                    logical=tid+':'+mode
                    previous=parent.stages.get((logical,'MODULES'))
                    if previous:
                        r=repair.replay_saved(t,binding,mode,previous[1]['output'])
                        if sha(r)!=impact[logical]['new_module_sha256']:raise ValueError('FROZEN_REPLAY_CHANGED:'+logical)
                        module_origin='PARENT_FROZEN_MODULE_INPUT'
                    else:
                        r=repair.prepare(t,binding,mode,c,route=route if mode.startswith(('S2','S3','S4','S5')) else None,
                                         allow_target_reads=True,backend=backend)
                        module_origin='CURRENT_NATIVE_MODULES'
                    runner.stage(logical,'MODULES',dict(source=src['primary_sha256'],interface=repair.VERSION),
                        dict(r,module_inputs_origin=module_origin,actual_new_rag_calls=r['rag_calls'] if not previous else 0,
                             actual_new_memory_calls=r['memory_calls'] if not previous else 0))
                    prepared=r['prepared'];plan=prepared['planner'];accepted=None;failed=False
                    if plan and plan['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                        planner=repair.planner_for(base.snapshot_for(t,binding),prepared['final_request']['runtime_input']['evidence']['selected_evidence'])
                        if planner.plan_kind(plan['bridge'])['kind']!='NEEDS_TASK_INFORMATION':
                            cfg=c['generation_roles']['CANDIDATE']
                            res=runner.perform(logical+':CANDIDATE','CANDIDATE',planner.candidate_payload(prepared,cfg),
                                lambda v:planner.candidate_issues(plan['bridge'],v),
                                lambda v,issues:planner.candidate_payload(prepared,cfg,previous=v,issues=issues))
                            accepted=res['value'] if res['status']=='ACCEPTED' else None
                        failed=accepted is None
                    payload=base.final_payload(prepared,c['generation_roles']['FINAL'],accepted,failed)
                    if logical in impact and impact[logical]['decision']=='REUSE_ACCEPTED_PAYLOAD_EQUAL':
                        if sha(payload)!=impact[logical]['parent_payload_sha256']:raise ValueError('IMPACT_EXCEEDS_SIX_STOP:'+logical)
                    eids=prepared['trace']['retained_evidence_ids']
                    res=runner.perform(logical+':FINAL','FINAL',payload,lambda v:base.final_issues(v,eids))
                    answer=base.freeze_answer(res['value'],eids,accepted) if res['status']=='ACCEPTED' else None
                    inherited=logical+':FINAL' in parent.terminals and parent.starts[logical+':FINAL'][-1]['request']==payload
                    runner.stage(logical,'RESPONSE',dict(request=sha(payload),plan=sha(accepted)),
                        dict(task_id=tid,mode=mode,result=res,response=answer,human_scores=[],
                            result_origin='PARENT_REUSED_UNCHANGED' if inherited else 'NEW_A1',
                            replaces_parent=logical in pp['replacement_slots'] and not inherited))
        write_once(output/'EXECUTION_COMPLETE.json',dict(completed_utc=utc(),all_task_loops_finished=True))
    except BaseException as exc:
        if runner:write_once(output/'PRESERVATION_STOP.json',dict(exception_type=type(exc).__name__,reason=str(exc),utc=utc(),no_auto_resume=True))
        raise
    finally:
        if runner:runner.close()
        transport.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--preflight',action='store_true');g.add_argument('--execute',action='store_true')
    p.add_argument('--approval',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if not a.execute:base.offline()
    context=frozen_context(a.manifest)
    if a.preflight:print(json.dumps(dict(binding=context[4],new_physical_ceiling=282,historical_physical=256,cumulative_budget_ceiling_usd=10.0,provider_authorized=False),indent=2))
    else:
        if not a.approval or not a.output:raise PermissionError('EXPLICIT_A1_APPROVAL_AND_NEW_OUTPUT_REQUIRED')
        execute(context,load(a.approval),a.output)


if __name__=='__main__':main()
