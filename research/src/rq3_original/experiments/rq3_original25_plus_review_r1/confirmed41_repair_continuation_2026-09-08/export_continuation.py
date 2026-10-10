"""Offline immutable export, parent/new ledger separation, exact ZIP readback."""
from a1_common import *
from collections import Counter,defaultdict
from copy import deepcopy
import argparse
import csv
import fcntl
import html
import io
import os
from pathlib import PurePosixPath
import re
import stat
import subprocess
import zipfile
from parent_ledger import ParentLedger,debit

OLD_STUDY=PARENT.parent
PREFIX=str(HERE.relative_to(ROOT))+'/'

def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def blob(v):return (json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
def put(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())

def inventory(run):
    starts=sorted((load(p) for p in (run/'attempts').glob('*.start.json')),key=lambda s:s['monotonic_start'])
    outcomes={p.name.removesuffix('.outcome.json'):load(p) for p in (run/'attempts').glob('*.outcome.json')}
    stages=[(p,load(p)) for p in (run/'stages').glob('*.json')]
    bylogical=defaultdict(list);stats=defaultdict(Counter);known_in=known_out=missing=0
    for s in starts:
        bylogical[s['logical']].append(s);assert sha(s['request'])==s['request_sha256']
        o=outcomes.get(s['attempt_id']);status=o['status'] if o else 'UNKNOWN_COMPLETION'
        if o and o.get('raw_sha256'):assert sha((run/'attempts'/f"{s['attempt_id']}.raw.json").read_bytes())==o['raw_sha256']
        c=stats[s['role']];c['calls']+=1;c['success' if status=='ACCEPTED' else 'unknown' if status=='UNKNOWN_COMPLETION' else 'failed']+=1
        c['within_run_retries']+=s['attempt']>1
        u=o.get('usage') if o else None
        if isinstance(u,dict) and all(type(u.get(k)) is int and u[k]>=0 for k in ('prompt_tokens','completion_tokens')):
            known_in+=u['prompt_tokens'];known_out+=u['completion_tokens']
        else:missing+=1
    interval=min((b['monotonic_start']-a['monotonic_start'] for a,b in zip(starts,starts[1:])),default=None)
    summary=dict(physical_calls=len(starts),successful_calls=sum(c['success'] for c in stats.values()),failed_calls=sum(c['failed'] for c in stats.values()),
        unknown_calls=sum(c['unknown'] for c in stats.values()),role_calls={k:dict(v) for k,v in stats.items()},
        within_run_retries=sum(s['attempt']>1 for s in starts),minimum_start_interval_seconds=interval,
        known_prompt_tokens=known_in,known_completion_tokens=known_out,known_usage_cost_usd=(known_in*.15+known_out*.60)/1e6,
        calls_without_usage=missing,reserved_usd=sum(s['reserved_usd_upper_bound'] for s in starts),
        budget_debit_usd=debit(starts,run,policy()['uncached_usd_per_million']),
        statuses=dict(Counter(outcomes[s['attempt_id']]['status'] if s['attempt_id'] in outcomes else 'UNKNOWN_COMPLETION' for s in starts)))
    return starts,outcomes,stages,bylogical,summary

def merged_slots(parent,run):
    impact={r['logical']:r for r in load(HERE/'audit/IMPACT_AUDIT.json')['records']}
    starts,outcomes,stages,active,summary=inventory(run)
    responses={r['logical']:(p,r) for p,r in stages if r['stage']=='RESPONSE'}
    result=[]
    for old in rows(PARENT/'RESPONSE_HANDOFF.jsonl'):
        logical=old['declared_slot_key'];d=impact.get(logical);item=deepcopy(old)
        item.update(parent_status=old['status'],parent_answer_sha256=old['answer_sha256'],
                    parent_response_record_path='parent/'+old['response_record_path'] if old['response_record_path'] else None,
                    parent_raw_response_path='parent/'+old['raw_response_path'] if old['raw_response_path'] else None,
                    parent_run_binding_sha256=policy()['parent_binding_sha256'],selected_run=None,
                    replaces_parent=False,selection_basis='NO_ACCEPTED_RESPONSE')
        if d and d['decision']=='REUSE_ACCEPTED_PAYLOAD_EQUAL':
            payload=parent.starts[logical+':FINAL'][-1]['request']
            parent.accepted(logical+':FINAL','FINAL',payload)
            assert sha(payload)==d['parent_payload_sha256']
            item.update(selected_run='PARENT',selection_basis=d['decision'])
            for k in ('raw_response_path','response_record_path'):
                if item[k]:item[k]='parent/'+item[k]
            result.append(item);continue
        for k in ('answer','answer_sha256','raw_response_path','raw_response_sha256','response_record_path','response_record_sha256','origin','logical_id'):item[k]=None
        item.update(status='NOT_EXECUTED',logical_id_basis='NO_NEW_FINAL_RECORD')
        rr=responses.get(logical);ss=active.get(logical+':FINAL',[])
        if rr:
            p,r=rr;out=r['output'];res=out['result']
            assert out['task_id']==old['task_id'] and out['mode']==old['mode'] and out['human_scores']==[]
            item.update(logical_id=r['logical'],logical_id_basis='RUNNER_RESPONSE_STAGE',status=res['status'],
                response_record_path='run/'+str(p.relative_to(run)),response_record_sha256=sha(p.read_bytes()))
            # Six eligible slots with an actually identical final payload reuse.
            if out.get('result_origin')=='PARENT_REUSED_UNCHANGED':
                item.update(selected_run='PARENT',selection_basis='ACTUAL_FINAL_PAYLOAD_EQUAL_REUSE',answer=old['answer'],answer_sha256=old['answer_sha256'],
                    raw_response_path='parent/'+old['raw_response_path'],raw_response_sha256=old['raw_response_sha256'],origin='LIVE')
                result.append(item);continue
            if res['status']=='ACCEPTED':
                assert out['response']['answer']==res['value']['answer'] and out['response']['human_scores']==[]
                item.update(answer=out['response']['answer'],answer_sha256=sha(out['response']['answer'].encode()))
            aid=res['attempt_id']
        elif ss:
            s=ss[-1];aid=s['attempt_id'];res=outcomes.get(aid)
            item.update(logical_id=s['logical'],logical_id_basis='RUNNER_FINAL_ATTEMPT_NO_RESPONSE_STAGE',status=res['status'] if res else 'UNKNOWN_COMPLETION')
            if res and res['status']=='ACCEPTED':
                p=run/'attempts'/f'{aid}.outcome.json'
                item.update(answer=res['value']['answer'],answer_sha256=sha(res['value']['answer'].encode()),
                    response_record_path='run/'+str(p.relative_to(run)),response_record_sha256=sha(p.read_bytes()),logical_id_basis='RUNNER_ACCEPTED_FINAL_OUTCOME')
        else:
            if old['status']=='UNKNOWN_COMPLETION':
                item.update(logical_id=old['logical_id'],logical_id_basis=old['logical_id_basis'],status=old['status'],
                    raw_response_path=item['parent_raw_response_path'],raw_response_sha256=old['raw_response_sha256'],selection_basis='PARENT_UNKNOWN_PRESERVED_NO_NEW_FINAL')
            if logical in policy()['replacement_slots']:item['selection_basis']='REPLACEMENT_ELIGIBLE_NOT_EXECUTED_PARENT_HISTORICAL_ONLY'
            result.append(item);continue
        raw=run/'attempts'/f'{aid}.raw.json'
        if raw.exists():item.update(raw_response_path='run/'+str(raw.relative_to(run)),raw_response_sha256=sha(raw.read_bytes()))
        item.update(selected_run='A1',origin='LIVE' if item['status']!='UNKNOWN_COMPLETION' else None,
            replaces_parent=logical in policy()['replacement_slots'],selection_basis='NEW_FINAL_FOR_CHANGED_PLANNING_INPUT' if logical in policy()['replacement_slots'] else
            'ONE_AUTHORIZED_SAME_PAYLOAD_UNKNOWN_RESEND' if d else 'PREVIOUSLY_NOT_EXECUTED')
        result.append(item)
    assert len(result)==246 and len({(r['task_id'],r['mode']) for r in result})==246
    assert sum(r['selection_basis']=='REUSE_ACCEPTED_PAYLOAD_EQUAL' for r in result)==168
    return result,summary,stages,starts

def readables(output,slots):
    tasks={r['task_id']:r for r in rows(DATA/'runtime_tasks.jsonl')}
    parts=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>A1 原样回答</title>',
      '<style>body{max-width:960px;margin:2rem auto;font:16px/1.6 system-ui;padding:0 1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:1rem}article{border-top:1px solid #aaa;margin-top:2rem}</style>',
      '<h1>A1 原样回答阅读版（研究者内部）</h1><p>含模式与版本关系，不直接发给评分者。所附录播观看记录；回答正文逐字保留。旧174份回答另存 parent/。无真实人评分。</p>']
    md=['# A1 原样回答阅读版（研究者内部）','含模式与版本关系，不直接交给评分者。回答逐字保留，缺失不补写；旧174份保存在 parent/。','']
    for r in slots:
        label=' / '.join((r['task_id'],r['mode'],r['status'],r['selection_basis']));q=tasks[r['task_id']]['query']
        answer=r['answer'] if r['answer'] is not None else '[No accepted response; consult preserved status and receipts.]'
        parts.append('<article><h2>'+html.escape(label)+'</h2><p>'+html.escape(q)+'</p><pre>'+html.escape(answer)+'</pre></article>')
        fence='~'*max(4,max((len(x) for x in re.findall(r'~+',answer)),default=0)+1)
        md.extend(['## '+label,'',q,'',fence,answer,fence,''])
    parts.append('</html>');put(output/'READABLE_RESPONSES.html','\n'.join(parts).encode());put(output/'READABLE_RESPONSES.md','\n'.join(md).encode())

def study_metadata(output):
    for p in sorted((PARENT/'study_materials').rglob('*')):
        if p.is_file():put(output/'study_materials'/p.relative_to(PARENT/'study_materials'),p.read_bytes())
    protocol_names={'decisions':'CONFIRMED_RESEARCH_DECISIONS.json','applicability':'APPLICABILITY_CONFIRMED_41.json','families':'TASK_FAMILY_MAP.json'}
    protocols={}
    for key,name in protocol_names.items():
        p=OLD_STUDY/name;put(output/'protocol'/name,p.read_bytes());protocols[key]=sha(p.read_bytes())
    rubric=output/'study_materials/human_review/rubric.json';protocols['rubric']=sha(rubric.read_bytes())
    metadata=load(PARENT/'STUDY_METADATA.json')
    metadata.update(data_kind='FROZEN_REAL_RESPONSES',protocol_sha256=protocols,applicability='protocol/APPLICABILITY_CONFIRMED_41.json',family_map='protocol/TASK_FAMILY_MAP.json',
        reference_basis='FIXED_COMMON_REFERENCE_NOT_RUN_RETRIEVAL',source_and_reference_files=[file_entry(p,output) for p in sorted((output/'study_materials').rglob('*')) if p.is_file()],
        ratings_exist=False,revision_exposure=policy()['exposure'],
        format_note='Preserves actual A data layout. B may adapt metadata field names from this frozen root only. This researcher package is not a blinded rater packet.',
        parent_decisions_actual_sha256=protocols['decisions'],
        b_task_packet_decisions_hash_is_not_substituted=True)
    put(output/'STUDY_METADATA.json',blob(metadata));return metadata,protocols

def export(run,approval,preflight,process,output):
    parent=ParentLedger();a=load(approval);pf=load(preflight);receipt=load(process)
    assert receipt['process_exited'] is True and isinstance(receipt['returncode'],int)
    assert a['binding']==pf['binding'] and git('rev-parse','HEAD')==pf['binding']['git_head']
    assert Path(a['output_directory']).resolve()==run.resolve() and not output.exists()
    lock=(run/'RUN.lock').open('r');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        binding=load(run/'RUN_BINDING.json');assert binding['transport_kind']=='LIVE' and all(binding[k]==v for k,v in pf['binding'].items())
        output.mkdir(parents=True,exist_ok=False)
        for root,prefix in [(run,'run'),(PARENT_RUN,'parent/run')]:
            for p in sorted(root.rglob('*')):
                if p.is_file() and p.name!='RUN.lock':
                    assert not p.is_symlink();put(output/prefix/p.relative_to(root),p.read_bytes())
        for name in ('RESPONSE_HANDOFF.jsonl','READABLE_RESPONSES.html','READABLE_RESPONSES.md','EXECUTION_SUMMARY.json','EXECUTION_APPROVAL.json','PREFLIGHT.json','PROCESS_EXIT.json','GENERATION_HANDOFF_MANIFEST.json'):
            put(output/'parent'/name,(PARENT/name).read_bytes())
        for p,name in [(approval,'EXECUTION_APPROVAL.json'),(preflight,'PREFLIGHT.json'),(process,'PROCESS_EXIT.json')]:put(output/name,p.read_bytes())
        slots,new,stages,starts=merged_slots(parent,run)
        put(output/'RESPONSE_HANDOFF.jsonl',b''.join(canonical(r)+b'\n' for r in slots))
        fields=['task_id','mode','status','selected_run','selection_basis','replaces_parent','parent_status','answer_sha256','parent_answer_sha256','raw_response_path']
        s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in slots);put(output/'SLOT_STATUS_246.csv',s.getvalue().encode())
        pstats=inventory(PARENT_RUN)[4];cumulative={k:new[k]+pstats[k] for k in ('physical_calls','successful_calls','failed_calls','unknown_calls','known_prompt_tokens','known_completion_tokens','known_usage_cost_usd','calls_without_usage')}
        cumulative['budget_debit_usd']=parent.budget_debit+new['budget_debit_usd']
        cumulative['historical_unknown_retained']=True;cumulative['exact_bill_guarantee']=False
        modules=[r['output'] for _,r in stages if r['stage']=='MODULES']
        new['actual_rag_calls']=sum(m.get('actual_new_rag_calls',0) for m in modules)
        new['actual_memory_calls']=sum(m.get('actual_new_memory_calls',0) for m in modules)
        old_summary=load(PARENT/'EXECUTION_SUMMARY.json')
        cumulative.update(actual_rag_calls=old_summary['actual_rag_calls']+new['actual_rag_calls'],actual_memory_calls=old_summary['actual_memory_calls']+new['actual_memory_calls'])
        new['authorized_parent_unknown_resends']=sum(s['logical']==policy()['parent_unknown_authorizations'][0]['logical'] for s in starts)
        new['replacement_final_attempts']=sum(s['logical'].removesuffix(':FINAL') in policy()['replacement_slots'] and s['role']=='FINAL' for s in starts)
        terminal='COMPLETE' if (run/'EXECUTION_COMPLETE.json').exists() else 'PRESERVATION_STOP'
        summary=dict(terminal_state=terminal,new=new,parent=pstats,cumulative=cumulative,answer_slots=246,
            slot_status_counts=dict(Counter(r['status'] for r in slots)),accepted_answers=sum(r['answer'] is not None for r in slots),
            selected_parent_answers=sum(r['selected_run']=='PARENT' and r['answer'] is not None for r in slots),
            selected_new_answers=sum(r['selected_run']=='A1' and r['answer'] is not None for r in slots),
            parent_answers_historically_preserved=174,parent_routes_verified_reusable=81,
            actual_parent_reuse_unique_logicals=len({r['logical'] for r in rows(run/'PARENT_REUSE_RECEIPTS.jsonl')}) if (run/'PARENT_REUSE_RECEIPTS.jsonl').exists() else 0,
            selection_counts=dict(Counter(r['selection_basis'] for r in slots)),
            six_replacement_statuses=[{k:r[k] for k in ('declared_slot_key','status','selected_run','replaces_parent','answer_sha256','parent_answer_sha256')} for r in slots if r['declared_slot_key'] in policy()['replacement_slots']],
            native_backend_stages=[r['output'] for _,r in stages if r['stage']=='NATIVE_BACKEND'],
            stop=load(run/'PRESERVATION_STOP.json') if (run/'PRESERVATION_STOP.json').exists() else None,
            price_basis='USD per million input 0.15 / output 0.60; max(reservation, observed usage estimate), cumulative, not a bill guarantee',
            judge_calls=0,human_scores_filled=0,revision_exposure=policy()['exposure'])
        assert new['physical_calls']<=282 and cumulative['physical_calls']<=538 and cumulative['budget_debit_usd']<=10
        assert new['minimum_start_interval_seconds'] is None or new['minimum_start_interval_seconds']>=2
        assert new['authorized_parent_unknown_resends']<=1
        counts=Counter(s['logical'] for s in starts)
        assert all(n<=(1 if k in {x+':FINAL' for x in policy()['replacement_slots']}|{policy()['parent_unknown_authorizations'][0]['logical']} else 2) for k,n in counts.items())
        for group,cap in policy()['new_initial_slot_ceilings'].items():assert len({s['logical'] for s in starts if s['group']==group})<=cap
        assert all(r['human_scores']==[] and (r['answer'] is None or (r['status']=='ACCEPTED' and sha(r['answer'].encode())==r['answer_sha256'])) for r in slots)
        put(output/'EXECUTION_SUMMARY.json',blob(summary));readables(output,slots);metadata,protocols=study_metadata(output)
        manifest=dict(schema_version='RQ3_GENERATION_HANDOFF_V1',data_kind='FROZEN_REAL_RESPONSES',frozen=True,terminal_state=terminal,
            task_ids=load(DATA/'RUN_MANIFEST.json')['task_ids'],modes=load(DATA/'CONFIG_PROPOSED.json')['modes'],protocol_sha256=protocols,
            input_identity=binding,approval_binding=pf['binding'],actual_run_directory=str(run.resolve()),
            responses={'path':'RESPONSE_HANDOFF.jsonl','sha256':sha((output/'RESPONSE_HANDOFF.jsonl').read_bytes())},
            study_metadata_sha256=sha((output/'STUDY_METADATA.json').read_bytes()),accepted_answer_statuses=['ACCEPTED'],
            coverage=dict(total_slots=246,rateable_answers=summary['accepted_answers']),actual_call_count=cumulative['physical_calls'],
            parent_ledger_sha256=parent.identity,old_responses_preserved=174,answer_whitespace_preserved=True,
            result_files=[file_entry(p,output) for p in sorted(output.rglob('*')) if p.is_file()])
        put(output/'GENERATION_HANDOFF_MANIFEST.json',blob(manifest))
        return summary
    finally:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

def verify_zip(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
        for i in z.infolist():
            p=PurePosixPath(i.filename);assert not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename and not stat.S_ISLNK(i.external_attr>>16)
        m=json.loads(z.read('MANIFEST.json'));assert set(names)=={e['path'] for e in m['members']}|{'MANIFEST.json'}
        for e in m['members']:
            b=z.read(e['path']);assert len(b)==e['bytes'] and sha(b)==e['sha256']
        prefix=PREFIX+'results/';rs=[json.loads(r) for r in z.read(prefix+'RESPONSE_HANDOFF.jsonl').splitlines()]
        assert len(rs)==246 and len({(r['task_id'],r['mode']) for r in rs})==246
        for r in rs:
            assert r['human_scores']==[]
            if r['answer'] is not None:assert r['status']=='ACCEPTED' and sha(r['answer'].encode())==r['answer_sha256']
            for key in ('raw_response','response_record'):
                if r[key+'_path']:assert sha(z.read(prefix+r[key+'_path']))==r[key+'_sha256']
        old=[json.loads(r) for r in z.read(prefix+'parent/RESPONSE_HANDOFF.jsonl').splitlines()];assert sum(r['answer'] is not None for r in old)==174
        for r in old:
            if r['answer'] is not None:assert sha(r['answer'].encode())==r['answer_sha256']
            for key in ('raw_response','response_record'):
                if r[key+'_path']:assert sha(z.read(prefix+'parent/'+r[key+'_path']))==r[key+'_sha256']
        h=json.loads(z.read(prefix+'GENERATION_HANDOFF_MANIFEST.json'));assert sha(z.read(prefix+h['responses']['path']))==h['responses']['sha256']
        assert sha(z.read(prefix+'STUDY_METADATA.json'))==h['study_metadata_sha256']
    return dict(path=str(path.resolve()),sha256=sha(path.read_bytes()),bytes=path.stat().st_size,members=len(names),crc_ok=True,
        exact_member_set=True,safe_paths=True,all_file_hashes_verified=True,handoff_slots=246,parent_answers_preserved=174,git=m['git'])

def package(output):
    ParentLedger();assert not git('status','--porcelain') and git('branch','--show-current')=='research/rq3-rebuild-i1-pilot-launch'
    head=git('rev-parse','HEAD');start=policy()['starting_head'];git('merge-base','--is-ancestor',start,head)
    changes=subprocess.check_output(['git','diff','--name-only','-z',start,head],cwd=ROOT).decode().rstrip('\0').split('\0')
    assert changes and all(n.startswith(PREFIX) for n in changes)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += list(DATA.glob('*.py'))+[DATA/'DEPENDENCIES.json']
    files += [ROOT/e['path'] for e in load(DATA/'DEPENDENCIES.json')['files']]
    payload={}
    key=os.environ.get('OPENAI_API_KEY','').encode()
    for p in sorted(set(files)):
        assert not p.is_symlink() and p.suffix not in ('.zip','.sqlite','.bin','.pkl','.safetensors')
        n=str(p.relative_to(ROOT));b=p.read_bytes()
        assert not re.search(rb'sk-(?:proj-)?[A-Za-z0-9_-]{24,}',b) and (not key or key not in b)
        payload[n]=b
    request=''.join(head+':'+n+'\n' for n in payload).encode()
    batch=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,input=request,capture_output=True,check=True).stdout;pos=0
    for n,b in payload.items():
        end=batch.index(b'\n',pos);header=batch[pos:end].split();pos=end+1;assert len(header)==3 and header[1]==b'blob'
        size=int(header[2]);assert batch[pos:pos+size]==b,n;pos+=size+1
    assert pos==len(batch)
    lineage=dict(starting_head=start,parent_execution_head=policy()['parent_execution_head'],execution_head=load(HERE/'results/PREFLIGHT.json')['binding']['git_head'],
        ending_head=head,branch=git('branch','--show-current'),starting_clean=True,ending_clean=True,changed_paths=changes,
        commits=git('log','--format=%H %s',start+'..'+head).splitlines(),git_blob_verified_members=len(payload))
    payload['GIT_LINEAGE.json']=blob(lineage)
    payload['SOURCE_PATCH.diff']=subprocess.check_output(['git','diff','--no-ext-diff',start,head,'--',PREFIX+'*.py'],cwd=ROOT)
    payload['START_HERE.md']=(f'# A1 限定接口修复与续跑冻结结果\n\n研究者内部包，含模式与评价参考，不直接发给评分者。\n\n'
        f'- [实际执行报告]({PREFIX}results/EXECUTION_REPORT.md)\n- [原样阅读版]({PREFIX}results/READABLE_RESPONSES.html)\n'
        f'- [246槽状态和复用关系]({PREFIX}results/SLOT_STATUS_246.csv)\n- [冻结人评交接]({PREFIX}results/GENERATION_HANDOFF_MANIFEST.json)\n'
        f'- [原174份历史回答]({PREFIX}results/parent/READABLE_RESPONSES.html)\n- [修订协议]({PREFIX}REPAIR_PROTOCOL.md)\n'
        f'- [完整payload影响核验]({PREFIX}audit/IMPACT_AUDIT.json)\n\n'
        '保留旧未知及费用预留。新结果按实际状态交接；没有LLM Judge或真实人评统计。后续由两名独立评分者的打包流程读取明确冻结文件；B活动文件未读取。\n').encode()
    payload['MANIFEST.json']=blob(dict(git=lineage,members=[dict(path=n,bytes=len(b),sha256=sha(b)) for n,b in sorted(payload.items())],self_excluded='MANIFEST.json',
        exclusions=['credentials and API keys','full personal logs','raw identity tables','model weights','B active files','unrelated historical experiments']))
    with output.open('xb') as f:
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for n,b in sorted(payload.items()):z.writestr(n,b)
        f.flush();os.fsync(f.fileno())
    return verify_zip(output)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['export','package','verify'])
    for name in ('run','approval','preflight','process','output'):p.add_argument('--'+name,type=Path)
    a=p.parse_args();base.offline()
    result=export(a.run,a.approval,a.preflight,a.process,a.output) if a.command=='export' else package(a.output) if a.command=='package' else verify_zip(a.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
