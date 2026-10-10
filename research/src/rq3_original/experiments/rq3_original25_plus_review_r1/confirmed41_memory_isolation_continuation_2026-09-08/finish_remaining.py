"""Explicit A3 isolated preparation entry. Frozen scientific functions; new run and matching approval."""
from checkpoints import *
from continue_run import frozen_context as a1_context
from contextlib import ExitStack
import argparse
import fcntl
import subprocess
import tempfile
import interface_a1 as interface
from utils.c4_rebuild.i1.frozen_p3 import ROLE_NAMES
from isolation import isolated_prepare, parent_socket_allocation_check


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()


def context():
    m,tasks,binding,c,old_ident,_,frozen=a1_context(DATA/'RUN_MANIFEST.json')
    parent=LayeredLedger();p=load(HERE/'RECOVERY_POLICY.json')
    c=deepcopy(c)
    c.update(initial_slot_ceilings=p['logical_caps'],aggregate_attempt_ceiling=p['aggregate_new_physical_cap'],
             retries=VERSION,proposed_money_ceiling_usd=10.0,uncached_usd_per_million={'input':.15,'output':.6})
    verification=load(HERE/'audit/ISOLATION_VERIFICATION.json')
    assert verification['passed'] is True
    ident=dict(old_ident,config_sha256=sha(c),code_sha256=sha(dict(inherited=old_ident['code_sha256'],
        recovery={p.name:sha(p.read_bytes()) for p in sorted(HERE.glob('*.py'))})),
        recovery_version=VERSION,recovery_policy_sha256=sha((HERE/'RECOVERY_POLICY.json').read_bytes()),
        layered_parent_identity=parent.identity,historical_budget_debit_usd=parent.budget_debit,
        historical_physical_calls=parent.physical_calls,
        user_authorization_sha256=sha((HERE/'USER_AUTHORIZATION.md').read_bytes()),
        starting_head=p['starting_head'],repair_protocol_sha256=sha((HERE/'REPAIR_PROTOCOL.md').read_bytes()),
        isolation_verification_sha256=sha((HERE/'audit/ISOLATION_VERIFICATION.json').read_bytes()))
    return m,tasks,binding,c,ident,parent,frozen


def blocked(runner,logical,reason,dependencies):
    runner.stage(logical,'DEPENDENCY_BLOCKED',{'reason':reason},
        dict(status='DEPENDENCY_BLOCKED',reason=reason,dependencies=dependencies,
             final_sent=False,human_scores=[]))


def execute(ctx,approval,output):
    m,tasks,binding,c,ident,parent,frozen=ctx
    if output.exists():
        raise StopRun('NEW_OUTPUT_DIRECTORY_REQUIRED')
    if git('status','--porcelain'):
        raise StopRun('FROZEN_CLEAN_EXECUTION_TREE_REQUIRED')
    ids,c=legacy.approve(approval,ident,m,c,output)
    assert ids==m['task_ids'] and c['proposed_money_ceiling_usd']==10
    assert c['generation_roles']==load(DATA/'CONFIG_PROPOSED.json')['generation_roles']
    # Exclusive generation lock is independent of B1 and local encoder locks.
    with open('/private/tmp/rq3-confirmed41-generation.lock','a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        transport=None;runner=None
        try:
            parent_socket_allocation_check()
            transport=RecoveryTransport(approved=True,timeout=c['transport_timeout_seconds'])
            runner=RecoveryRunner(output,c,dict(ident,approved_ids=ids,frozen_roles=frozen.identity),transport,parent)
            write_once(output/'RECOVERY_CONTROL.json',dict(policy=load(HERE/'RECOVERY_POLICY.json'),effective_config=c,
                historical_budget_debit_usd=parent.budget_debit,run_scoped_parent_bindings=parent.bindings,
                sdk_retries=0,tls_verification_disabled=False))
            write_once(output/'PARENT_INDEX.json',dict(identity=parent.identity,accepted=parent.index,
                historical_attempts=[dict(source_run=r,source_run_binding_sha256=parent.bindings[r],
                    attempt_id=a,logical=s['logical'],role=s['role'],request_sha256=s['request_sha256'],
                    reserved_usd_upper_bound=s['reserved_usd_upper_bound']) for (r,a),s in parent.starts.items()]))
            for t in tasks:
                tid=t['task_id']
                if tid not in ids:continue
                remaining=[mode for mode in c['modes'] if tid+':'+mode+':FINAL' not in parent.selected]
                if not remaining:continue
                src=base.source_for(t,binding);route=None;results={}
                runner.stage(tid,'SOURCE',{'task':sha(t),'binding':sha(binding)},src)
                if not src['clarification']:
                    for role in ROLE_NAMES:
                        payload=frozen.request(role,src['primary'])
                        results[role]=runner.perform('P3:'+role+':'+sha(payload),role,payload)
                    if all(r['status']=='ACCEPTED' for r in results.values()):
                        route=dict(rag_required=results['RAG']['value']['rag_required'],
                            memory_required=results['MEMORY']['value']['memory_required'],
                            planning_required=results['B4_PLANNING']['value']['planning_required'],
                            provider_identity='ACTUAL_FROZEN_P3')
                    runner.stage(tid,'ACTUAL_P3',{'primary':src['primary_sha256'],'frozen':frozen.identity},
                        dict(route=route,results=results))
                with ExitStack() as stack:
                    novel=[mode for mode in remaining if not parent.module(tid+':'+mode)
                           and (mode.startswith(('S0','S1')) or route is not None or src['clarification'])]
                    fresh={}
                    if novel:
                        fresh,worker_receipt=isolated_prepare(t,binding,novel,c,route)
                        runner.stage(tid,'OFFLINE_PREPARATION_WORKER',{'task':sha(t),'modes':novel,'route':sha(route)},worker_receipt)
                        # Every completed read is recorded before a later Provider stop.
                        for prepared_mode,entry in fresh.items():
                            origin=dict(source_run='A3',native_modules=True,offline_worker=True)
                            r=entry['modules']
                            runner.stage(tid+':'+prepared_mode,'MODULES',
                                {'source':src['primary_sha256'],'interface':interface.VERSION},
                                dict(r,module_checkpoint_origin=origin,actual_new_rag_calls=r['rag_calls'],
                                     actual_new_memory_calls=r['memory_calls']))
                            if entry['native_backend']:
                                runner.stage(tid,'NATIVE_BACKEND',{'binding':sha(binding['native'][tid])},entry['native_backend'])
                    for mode in remaining:
                        logical=tid+':'+mode
                        if mode.startswith(('S2','S3','S4','S5')) and not src['clarification'] and route is None:
                            blocked(runner,logical,'NO_ACCEPTED_P3',results)
                            continue
                        previous=parent.module(logical)
                        if previous:
                            run,path,r=previous
                            # Exact frozen A1 MODULES already carry the unchanged interface.
                            # No reconstructed memory or empty-library substitution.
                            assert run in ('A1','A2') and r['source']==src
                            origin=dict(source_run=run,path=str(path.relative_to(ROOT)),sha256=sha(path.read_bytes()))
                        else:
                            entry=fresh[mode];r=entry['modules']
                            if entry['native_backend']:
                                runner.stage(tid,'NATIVE_BACKEND',{'binding':sha(binding['native'][tid])},entry['native_backend'])
                            origin=dict(source_run='A3',native_modules=True,offline_worker=True)
                        runner.stage(logical,'MODULES',{'source':src['primary_sha256'],'interface':interface.VERSION},
                            dict(r,module_checkpoint_origin=origin,actual_new_rag_calls=0 if previous else r['rag_calls'],
                                 actual_new_memory_calls=0 if previous else r['memory_calls']))
                        prepared=r['prepared'];plan=prepared['planner'];accepted=None;failed=False
                        if plan and plan['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                            planner=interface.planner_for(base.snapshot_for(t,binding),
                                prepared['final_request']['runtime_input']['evidence']['selected_evidence'])
                            if planner.plan_kind(plan['bridge'])['kind']!='NEEDS_TASK_INFORMATION':
                                cfg=c['generation_roles']['CANDIDATE']
                                res=runner.perform(logical+':CANDIDATE','CANDIDATE',planner.candidate_payload(prepared,cfg),
                                    lambda v:planner.candidate_issues(plan['bridge'],v),
                                    lambda v,issues:planner.candidate_payload(prepared,cfg,previous=v,issues=issues))
                                if dependency_blocked(res):
                                    blocked(runner,logical,'NO_OBSERVED_CANDIDATE_RESPONSE',res)
                                    continue
                                accepted=res['value'] if res['status']=='ACCEPTED' else None
                            failed=accepted is None
                        payload=base.final_payload(prepared,c['generation_roles']['FINAL'],accepted,failed)
                        eids=prepared['trace']['retained_evidence_ids']
                        res=runner.perform(logical+':FINAL','FINAL',payload,lambda v:base.final_issues(v,eids))
                        answer=base.freeze_answer(res['value'],eids,accepted) if res['status']=='ACCEPTED' else None
                        runner.stage(logical,'RESPONSE',{'request':sha(payload),'plan':sha(accepted)},
                            dict(task_id=tid,mode=mode,result=res,response=answer,human_scores=[],result_origin='NEW_A3'))
                        print(json.dumps(dict(event='SLOT_FINISHED',logical=logical,status=res['status'])),flush=True)
            write_once(output/'EXECUTION_COMPLETE.json',dict(utc=utc(),all_task_loops_finished=True))
        except BaseException as exc:
            if runner:
                reason=str(exc) if isinstance(exc,StopRun) else 'UNEXPECTED_LOCAL_EXCEPTION'
                write_once(output/'PRESERVATION_STOP.json',dict(reason=reason,diagnostics=safe_exception(exc,'EXECUTE'),
                    utc=utc(),no_auto_resume=True))
            raise
        finally:
            if runner:runner.close()
            if transport:transport.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--preflight',action='store_true');p.add_argument('--execute',action='store_true')
    p.add_argument('--approval',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if not a.execute:base.offline()
    ctx=context()
    if not a.execute:
        print(json.dumps(dict(binding=ctx[4],parent_index_count=len(ctx[5].index),remaining_final_slots=63,
                             logical_caps=ctx[5] and load(HERE/'RECOVERY_POLICY.json')['logical_caps']),indent=2))
    else:
        if not a.approval or not a.output:raise StopRun('EXPLICIT_NEW_BINDING_REQUIRED')
        execute(ctx,load(a.approval),a.output)


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        print(json.dumps(dict(event='SAFE_PROCESS_FAILURE',reason=str(exc) if isinstance(exc,StopRun) else 'LOCAL_EXCEPTION',
                              diagnostics=safe_exception(exc,'PROCESS_ENTRY'))),file=sys.stderr)
        raise SystemExit(1)
