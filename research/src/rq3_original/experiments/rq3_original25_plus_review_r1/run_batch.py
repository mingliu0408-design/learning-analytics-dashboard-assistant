"""Explicit-manifest batch entry. Defaults to offline source preflight."""
from v2_common import *
from copy import deepcopy
import argparse
import subprocess
from contextlib import ExitStack
import tempfile
from adapter import (Mode, prepare, source_for, snapshot_for, planner_for,
    final_payload, final_issues, freeze_answer)

def load_run(manifest):
    manifest=Path(manifest).resolve()
    if manifest.parent!=HERE or manifest.name!='RUN_MANIFEST.json':raise ValueError('EXPLICIT_V2_MANIFEST_REQUIRED')
    m=read(manifest)
    if m['version']!=VERSION or m['roster_count']!=49:raise ValueError('WRONG_ROSTER_MANIFEST')
    if sha((HERE/m['roster_path']).read_bytes())!=m['roster_sha256'] or sha((HERE/'BINDINGS.json').read_bytes())!=m['bindings_sha256']:
        raise ValueError('MANIFEST_BINDING_CHANGED')
    tasks=lines(HERE/m['roster_path']);binding=read(HERE/'BINDINGS.json');config=read(HERE/'CONFIG_PROPOSED.json')
    if len(tasks)!=49 or len({t['task_id'] for t in tasks})!=49 or config['task_ids']!=m['task_ids']:raise ValueError('ROSTER_MISMATCH')
    if config['generation_roles']['CANDIDATE']!=config['generation_roles']['FINAL'] or config['generation_roles']['FINAL']['model']!='gpt-4o-mini-2024-07-18':raise ValueError('MODEL_CHANGED')
    if config['modes']!=[mode.value for mode in Mode] or config['max_attempts_per_slot']!=2:raise ValueError('MODE_OR_RETRY_CHANGED')
    checked(binding['course'])
    for t in tasks:
        source_for(t,binding)
        nb=binding['native'][t['task_id']]
        for entry in [nb['database'],nb['graph'],nb['source_events'],*nb['mode_copies'].values()]:checked(entry)
    return m,tasks,binding,config

def identity(manifest,tasks,binding,config):
    paths=[p for p in HERE.glob('*.py')]
    # Version all executed local Python dependencies; no historical result files.
    paths.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m,'__file__',None) and str(Path(m.__file__).resolve()).startswith(str(ROOT)+'/') and str(m.__file__).endswith('.py'))
    git_result=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True)
    git_head=git_result.stdout.strip() if git_result.returncode==0 else read(ROOT/'GIT_LINEAGE.json')['ending_head']
    return dict(manifest_sha256=sha(manifest),tasks_sha256=sha(tasks),bindings_sha256=sha(binding),config_sha256=sha(config),
        code_sha256=sha({str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sorted(set(paths))}),
        git_head=git_head,git_basis='LIVE_GIT' if git_result.returncode==0 else 'ARCHIVE_LINEAGE_RECORD')

def prepare_batch(m,tasks,binding,config,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    sources=[];prepared=[]
    for t in tasks:
        src=source_for(t,binding)
        sources.append(dict(task_id=t['task_id'],**src))
        for mode in config['modes']:
            result=prepare(t,binding,mode,config)
            wire=final_payload(result['prepared'],config['generation_roles']['FINAL'])
            prepared.append(dict(task_id=t['task_id'],mode=mode,admitted_by_manifest=t['task_id'] in m['task_ids'],
                status='DETERMINISTIC_INPUT_ONLY_ACTUAL_P3_PENDING',source=result['source'],prepared=result['prepared'],
                final_wire_preview=wire,rag_calls=result['rag_calls'],memory_calls=result['memory_calls']))
    jsonl(output/'SOURCE_INPUTS_49.jsonl',sources)
    jsonl(output/'PREPARED_INPUTS_294.jsonl',prepared)
    from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
    write(output/'FROZEN_ROLE_RECEIPT.json',FrozenP3().receipt())
    write(output/'PREPARE_COUNTS.json',dict(roster=49,prepared_source_previews=49,mode_input_previews=len(prepared),
        preparable=m['preparable_count'],provider_calls=0,p3_calls=0,target_retrieval_calls=0,candidate_calls=0,final_calls=0,judge_calls=0,
        note='S2-S5 optional modules remain pending actual P3; these previews are not routed/model responses.'))
    dependencies={str(Path(mod.__file__).resolve().relative_to(ROOT)):sha(Path(mod.__file__).read_bytes())
        for mod in list(sys.modules.values()) if getattr(mod,'__file__',None)
        and str(Path(mod.__file__).resolve()).startswith(str(ROOT)+'/') and str(mod.__file__).endswith('.py')}
    write(output/'LOADED_CODE_DEPENDENCIES.json',dependencies)
    print(canonical(read(output/'PREPARE_COUNTS.json')))

def approve(a,ident,m,config,output):
    # Reuses the existing consolidated replay approval vocabulary. No approval
    # is inferred from READY/prepared status or from elapsed time.
    if a.get('status')!='AUTHORIZED' or a.get('scope')!='ORIGINAL25_PLUS_EN_V2_FRESH_SIX_MODES_HUMAN_ONLY':raise PermissionError('NO_PROVIDER_AUTHORIZATION_THIS_ROUND')
    if a.get('binding')!=ident or not a.get('user_decision') or not a.get('external_source_scope_confirmed'):
        raise PermissionError('ONE_CONSOLIDATED_TASK_SOURCE_MODEL_BUDGET_DECISION_REQUIRED')
    if Path(a.get('output_directory','')).resolve()!=Path(output).resolve():raise PermissionError('OUTPUT_NOT_AUTHORIZED')
    ids=a.get('task_ids')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<=set(m['task_ids']):raise PermissionError('PREDECLARED_PREPARABLE_ROSTER_REQUIRED')
    if a.get('selection_basis')!='PREDECLARED_BEFORE_NEW_OUTPUTS':raise PermissionError('PERFORMANCE_SELECTION_FORBIDDEN')
    groups={}
    for row in read(HERE/'family_design.json')['tasks']:groups.setdefault(row['family_id'],set()).add(row['task_id'])
    if any(set(ids)&g and not g<=set(ids) for g in groups.values()):raise PermissionError('PAIR_MUST_STAY_TOGETHER')
    money=a.get('proposed_money_ceiling_usd');rates=a.get('uncached_usd_per_million')
    if type(money) not in (float,int) or money<=0 or not isinstance(rates,dict) or any(type(rates.get(k)) not in (float,int) or rates[k]<=0 for k in ('input','output')):raise PermissionError('AGGREGATE_MONEY_BUDGET_AND_PRICES_PENDING')
    c=deepcopy(config);c.update(approved=True,proposed_money_ceiling_usd=money,uncached_usd_per_million=rates)
    return ids,c

def execute(ids,tasks,binding,config,ident,output,resume):
    # This entire branch is reached only after approve; never entered this round.
    from utils.c4_rebuild.i1.frozen_p3 import FrozenP3,ROLE_NAMES
    from utils.c4_rebuild.i1.durable import DurableRunner
    from utils.c4_rebuild.i1.transport import OpenAITransport
    frozen=FrozenP3();transport=OpenAITransport(approved=True,timeout=config['transport_timeout_seconds']);runner=None
    try:
        runner=DurableRunner(output,config,dict(ident,approved_ids=ids,frozen_roles=frozen.identity),transport,resume=resume)
        for t in tasks:
            if t['task_id'] not in ids:continue
            tid=t['task_id'];src=source_for(t,binding);route=None
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
                if route and route['memory_required'] and read(HERE/'native_initial'/tid/'state_readable.json')['memories']:
                    import fcntl
                    from utils.c4_rebuild.i1.native_backend import I1LocalBackend
                    lock=stack.enter_context(open('/private/tmp/rq3-rebuild-local-inference.lock','a+'))
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    td=stack.enter_context(tempfile.TemporaryDirectory(prefix='rq3-v2-native-backend-'))
                    backend=I1LocalBackend(Path(td));stack.callback(backend.close)
                for mode in config['modes']:
                    logical=tid+':'+mode
                    r=prepare(t,binding,mode,config,route=route if mode.startswith(('S2','S3','S4','S5')) else None,
                              allow_target_reads=True,backend=backend)
                    runner.stage(logical,'MODULES',dict(primary=src['primary_sha256'],module_state=r['prepared']['trace']['module_state_key']),r)
                    p=r['prepared'];plan=p['planner'];accepted=None;failed=False
                    if plan and plan['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                        planner=planner_for(snapshot_for(t,binding))
                        if planner.plan_kind(plan['bridge'])['kind']!='NEEDS_TASK_INFORMATION':
                            cfg=config['generation_roles']['CANDIDATE']
                            res=runner.perform(logical+':CANDIDATE','CANDIDATE',planner.candidate_payload(p,cfg),
                                lambda v:planner.candidate_issues(plan['bridge'],v),
                                lambda v,issues:planner.candidate_payload(p,cfg,previous=v,issues=issues))
                            accepted=res['value'] if res['status']=='ACCEPTED' else None
                        failed=accepted is None
                    payload=final_payload(p,config['generation_roles']['FINAL'],accepted,failed);eids=p['trace']['retained_evidence_ids']
                    res=runner.perform(logical+':FINAL','FINAL',payload,lambda v:final_issues(v,eids))
                    answer=freeze_answer(res['value'],eids,accepted) if res['status']=='ACCEPTED' else None
                    runner.stage(logical,'RESPONSE',dict(request=sha(payload),plan=sha(accepted)),dict(task_id=tid,mode=mode,result=res,response=answer,human_scores=[]))
    finally:
        if runner:runner.close()
        transport.close()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    group=p.add_mutually_exclusive_group();group.add_argument('--preflight',action='store_true');group.add_argument('--prepare',action='store_true');group.add_argument('--execute',action='store_true')
    p.add_argument('--approval',type=Path);p.add_argument('--output',type=Path);p.add_argument('--resume',action='store_true')
    a=p.parse_args(argv)
    if a.execute and not a.approval:raise PermissionError('NO_PROVIDER_AUTHORIZATION_THIS_ROUND')
    if not a.execute:offline()
    m,tasks,binding,config=load_run(a.manifest);ident=identity(m,tasks,binding,config)
    if a.execute:
        if not a.output:raise ValueError('OUTPUT_REQUIRED')
        ids,c=approve(read(a.approval),ident,m,config,a.output)
        execute(ids,tasks,binding,c,ident,a.output,a.resume)
    elif a.prepare:
        if not a.output:raise ValueError('NEW_OUTPUT_DIRECTORY_REQUIRED')
        prepare_batch(m,tasks,binding,config,a.output)
    else:print(json.dumps(dict(binding=ident,counts=read(HERE/'audit/COUNTS.json'),source_missing=m['excluded_pending_source'],provider_authorized=False),ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (PermissionError,ValueError) as exc:print(str(exc),file=sys.stderr);raise SystemExit(2)
