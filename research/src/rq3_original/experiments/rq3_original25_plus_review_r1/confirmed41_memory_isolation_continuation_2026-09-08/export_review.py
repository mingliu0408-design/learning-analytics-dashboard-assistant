"""Offline frozen handoff and independently reopened allowlisted archive."""
from checkpoints import *
from finish_remaining import context,git
from export_continuation import inventory,put,blob
from pathlib import PurePosixPath
import argparse
import fcntl
import html
import stat
import subprocess
import zipfile


def jsonl(path,records):
    put(path,b''.join(canonical(r)+b'\n' for r in records))


def export(run,approval,preflight,process):
    parent=LayeredLedger();a=load(approval);pf=load(preflight);exit_record=load(process/'PROCESS_EXIT.json')
    assert exit_record['process_exited'] and type(exit_record['returncode']) is int
    assert a['binding']==pf['binding']==context()[4]
    assert Path(a['output_directory']).resolve()==run.resolve()
    assert git('status','--porcelain')==''
    binding=load(run/'RUN_BINDING.json')
    assert binding['transport_kind']=='LIVE' and all(binding[k]==v for k,v in pf['binding'].items())
    output=HERE/'results';output.mkdir(exist_ok=False)
    with (run/'RUN.lock').open('r') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for p in sorted(run.rglob('*')):
            if p.is_file() and p.name!='RUN.lock':
                assert not p.is_symlink();put(output/'run'/p.relative_to(run),p.read_bytes())
    for p in process.iterdir():
        if p.is_file():put(output/'process'/p.name,p.read_bytes())
    for src,name in ((approval,'EXECUTION_APPROVAL.json'),(preflight,'PREFLIGHT.json')):
        put(output/name,src.read_bytes())
    copied={}
    def keep(p):
        p=Path(p)
        rel='parent_sources/'+str(p.relative_to(ROOT))
        if rel not in copied:
            assert not p.is_symlink();put(output/rel,p.read_bytes())
            copied[rel]=dict(path=rel,original_path=str(p),bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
        return rel
    for receipt in parent.index:
        for entry in receipt['files']:keep(ROOT/entry['path'])
    # Complete historical journals and stops; two UNKNOWN receipts never disappear.
    for run_name,root in parent.runs.items():
        for name in ('RUN_BINDING.json','JOURNAL.jsonl','STOP.json','PRESERVATION_STOP.json'):
            if (root/name).exists():keep(root/name)
    for name in ('RESPONSE_HANDOFF.jsonl','RESULT_LINEAGE_246.jsonl','EXECUTION_SUMMARY.json','GENERATION_HANDOFF_MANIFEST.json'):
        keep(PARENT_RESULTS/name)
    starts,outcomes,stages,bylogical,new=inventory(run)
    stage_map={(r['logical'],r['stage']):(p,r) for p,r in stages}
    slots=[];lineage=[]
    for old in parent.slots:
        item=deepcopy(old);logical=old['declared_slot_key'];final_logical=logical+':FINAL'
        item.update(previous_status=old['status'],previous_answer_sha256=old['answer_sha256'],human_scores=[])
        if item.get('dependency_record_path'):
            item['prior_dependency_record_path']=keep(PARENT_RESULTS/item.pop('dependency_record_path'))
        for k in ('raw_response','response_record'):
            if old[k+'_path']:
                item[k+'_path']=keep(PARENT_RESULTS/old[k+'_path'])
        for k in ('parent_raw_response_path','parent_response_record_path'):
            if old.get(k):item[k]=keep(PARENT_RESULTS/old[k])
        if old['status']=='ACCEPTED':
            item['selected_run']=parent.selected[final_logical]
            item['selection_basis']='PRESERVE_CANONICAL_A2_HANDOFF_BYTE_EXACT'
            assert final_logical not in bylogical
        elif final_logical in bylogical:
            ss=bylogical[final_logical];s=ss[-1];aid=s['attempt_id'];res=outcomes.get(aid)
            status=res['status'] if res else 'UNKNOWN_COMPLETION'
            item.update(status=status,selected_run='A3',answer=None,answer_sha256=None,
                selection_basis='AUTHORIZED_CURRENT_UNKNOWN_SINGLE_RESEND' if final_logical in EXISTING_UNKNOWNS else 'PREVIOUSLY_MISSING_SLOT',
                logical_id=final_logical,logical_id_basis='RUNNER_FINAL_OUTCOME',origin='LIVE' if res and res['completion']=='OBSERVED' else None,
                response_record_path=None,response_record_sha256=None,raw_response_path=None,raw_response_sha256=None)
            rp=run/'attempts'/f'{aid}.raw.json';op=run/'attempts'/f'{aid}.outcome.json'
            if rp.exists():item.update(raw_response_path='run/'+str(rp.relative_to(run)),raw_response_sha256=sha(rp.read_bytes()))
            if op.exists():item.update(response_record_path='run/'+str(op.relative_to(run)),response_record_sha256=sha(op.read_bytes()))
            if status=='ACCEPTED':
                raw=load(rp);answer=json.loads(raw['choices'][0]['message']['content'])['answer']
                assert res['value']['answer']==answer
                item.update(answer=answer,answer_sha256=sha(answer.encode()))
            rs=stage_map.get((logical,'RESPONSE'))
            if rs:
                p,r=rs
                assert r['output']['result']==res and r['output']['human_scores']==[]
                if status=='ACCEPTED':assert r['output']['response']['answer']==item['answer']
                item.update(response_record_path='run/'+str(p.relative_to(run)),response_record_sha256=sha(p.read_bytes()))
        elif (logical,'DEPENDENCY_BLOCKED') in stage_map:
            p,r=stage_map[(logical,'DEPENDENCY_BLOCKED')]
            item.update(status='DEPENDENCY_BLOCKED',selected_run=None,selection_basis=r['output']['reason'],
                        dependency_record_path='run/'+str(p.relative_to(run)))
        slots.append(item)
        historical=[dict(source_run=r,run_binding_sha256=parent.bindings[r],attempt_id=aid,
            request_sha256=s['request_sha256'],status=load(parent.runs[r]/'attempts'/f'{aid}.outcome.json')['status'])
            for (r,aid),s in parent.starts.items() if s['logical']==final_logical]
        current=[dict(source_run='A3',run_binding_sha256=sha((run/'RUN_BINDING.json').read_bytes()),
            attempt_id=s['attempt_id'],request_sha256=s['request_sha256'],
            status=outcomes.get(s['attempt_id'],{}).get('status','UNKNOWN_COMPLETION')) for s in bylogical.get(final_logical,[])]
        lineage.append(dict(declared_slot_key=logical,task_id=item['task_id'],mode=item['mode'],
            selected_run=item['selected_run'],status=item['status'],answer_sha256=item['answer_sha256'],
            prior_canonical_answer_sha256=old['answer_sha256'],prior_selection_basis=old['selection_basis'],
            new_selection_basis=item['selection_basis'],historical_attempts=historical,new_attempts=current,
            cumulative_physical_attempts=len(historical)+len(current)))
    assert len(slots)==246 and len({r['declared_slot_key'] for r in slots})==246
    assert sum(r['previous_status']=='ACCEPTED' for r in slots)==183
    jsonl(output/'RESPONSE_HANDOFF.jsonl',slots);jsonl(output/'RESULT_LINEAGE_246.jsonl',lineage)
    jsonl(output/'MISSING_AND_DEPENDENCY_BLOCKED.jsonl',[r for r in slots if r['status']!='ACCEPTED'])
    unknown=[]
    for run_name,root in [*parent.runs.items(),('A3',run)]:
        for p in (root/'attempts').glob('*.start.json'):
            s=load(p);aid=s['attempt_id'];op=root/'attempts'/f'{aid}.outcome.json'
            o=load(op) if op.exists() else {'status':'UNKNOWN_COMPLETION'}
            if o['status']!='ACCEPTED':
                paths=[]
                for suffix in ('start','raw','outcome'):
                    p=root/'attempts'/f'{aid}.{suffix}.json'
                    if p.exists():paths.append(keep(p) if run_name!='A3' else 'run/'+str(p.relative_to(run)))
                unknown.append(dict(source_run=run_name,run_binding_sha256=sha((root/'RUN_BINDING.json').read_bytes()),
                    attempt_id=aid,logical=s['logical'],role=s['role'],status=o['status'],
                    reserved_usd_upper_bound=s['reserved_usd_upper_bound'],files=paths,
                    final_slot_now_accepted=any(x['declared_slot_key']+':FINAL'==s['logical'] and x['status']=='ACCEPTED' for x in slots)))
    jsonl(output/'UNKNOWN_AND_FAILED_ATTEMPTS.jsonl',unknown)
    put(output/'PARENT_SOURCE_INDEX.json',blob(dict(parent_identity=parent.identity,
        parent_archive=str(PARENT_ARCHIVE),parent_archive_sha256=sha(PARENT_ARCHIVE.read_bytes()),
        selected_result_index=parent.index,included_files=list(copied.values()))))
    modules=[r['output'] for _,r in stages if r['stage']=='MODULES']
    new.update(actual_rag_calls=sum(r['actual_new_rag_calls'] for r in modules),
        actual_memory_calls=sum(r['actual_new_memory_calls'] for r in modules),
        logical_calls_by_group=dict(Counter(group for group in ('ROUTE','CANDIDATE','FINAL') for _ in
            {s['logical'] for s in starts if s['group']==group})),
        physical_calls_by_group=dict(Counter(s['group'] for s in starts)),
        network_recovery_waits=sum(1 for r in rows(run/'RECOVERY_EVENTS.jsonl') if r['event']=='NETWORK_RETRY_WAIT_BEGIN') if (run/'RECOVERY_EVENTS.jsonl').exists() else 0,
        historical_unknown_resends=sum(s['logical'] in EXISTING_UNKNOWNS for s in starts))
    old_summary=load(PARENT_RESULTS/'EXECUTION_SUMMARY.json')['cumulative']
    cumulative={k:old_summary[k]+new[k] for k in ('physical_calls','successful_calls','failed_calls','unknown_calls',
        'known_prompt_tokens','known_completion_tokens','known_usage_cost_usd','calls_without_usage','actual_rag_calls','actual_memory_calls')}
    cumulative['budget_debit_usd']=parent.budget_debit+new['budget_debit_usd']
    cumulative['physical_calls_by_group']={k:v+new['physical_calls_by_group'].get(k,0) for k,v in {'ROUTE':81,'CANDIDATE':12,'FINAL':193}.items()}
    counts=dict(Counter(r['status'] for r in slots))
    terminal='COMPLETE' if counts=={'ACCEPTED':246} else 'FINISHED_WITH_MISSING' if (run/'EXECUTION_COMPLETE.json').exists() else 'PRESERVATION_STOP'
    policy=load(HERE/'RECOVERY_POLICY.json')
    assert new['physical_calls']<=232 and cumulative['physical_calls']<=518 and cumulative['budget_debit_usd']<=10
    for group,cap in policy['physical_caps'].items():assert new['physical_calls_by_group'].get(group,0)<=cap
    for group,cap in policy['logical_caps'].items():assert new['logical_calls_by_group'].get(group,0)<=cap
    assert all(len(ss)<=(1 if logical in EXISTING_UNKNOWNS else 2) for logical,ss in bylogical.items())
    assert new['minimum_start_interval_seconds'] is None or new['minimum_start_interval_seconds']>=2
    assert sum(x['source_run'] in ('A','A1','A2') and x['status']=='UNKNOWN_COMPLETION' for x in unknown)==8
    summary=dict(terminal_state=terminal,new=new,historical=old_summary,cumulative=cumulative,
        slot_status_counts=counts,total_slots=246,canonical_183_preserved=True,old_six_planning_replacements_preserved=True,
        accepted_answers=counts.get('ACCEPTED',0),historical_unknowns_retained=8,
        current_missing_slots=246-counts.get('ACCEPTED',0),
        stop=load(run/'PRESERVATION_STOP.json') if (run/'PRESERVATION_STOP.json').exists() else None,
        execution_head=a['binding']['git_head'],starting_head=policy['starting_head'],
        provider_billing_certified=False,judge_calls=0,human_scores_filled=0,b1_activity_files_read=False)
    put(output/'EXECUTION_SUMMARY.json',blob(summary))
    for directory in ('study_materials','protocol'):
        for p in (PARENT_RESULTS/directory).rglob('*'):
            if p.is_file():put(output/directory/p.relative_to(PARENT_RESULTS/directory),p.read_bytes())
    metadata=load(PARENT_RESULTS/'STUDY_METADATA.json')
    metadata.update(ratings_exist=False,continuation_version=VERSION,
        continuation_note='Scientific inputs and evaluation unchanged; finite transport recovery after explicit authorization.')
    put(output/'STUDY_METADATA.json',blob(metadata))
    human='''# 冻结人评交接

这是冻结后的 A3 材料，可由 B1 在其原任务读取；本任务未访问 B1 活动文件，也未向其他任务发送消息。
从 GENERATION_HANDOFF_MANIFEST.json、RESPONSE_HANDOFF.jsonl、STUDY_METADATA.json 读取。
保留固定 41 题、八个缺件原题不运行、208 true / 120 false / 0 null、原 17 题与新 12 family 分层。
两人独立评分与原适用项平均规则不变。分数、理由、评分者身份、签名由本人填写，当前均未代填。
READABLE_RESPONSES 含模式，仅供研究者阅读，不直接交给评分者。缺失槽保持缺失；未知尝试不是质量 NA。
不存在 LLM Judge、人评比较统计或质量筛选。已知接受只是冻结机械校验通过。
'''
    put(output/'HUMAN_HANDOFF_README.md',human.encode())
    tasks={r['task_id']:r for r in rows(DATA/'runtime_tasks.jsonl')}
    md=['# A3 原样回答（研究者内部）','含模式；不直接交给评分者。正文逐字保留，缺失不补写。','']
    html_parts=['<!doctype html><meta charset="utf-8"><title>A3 原样回答</title><style>body{max-width:960px;margin:2rem auto;font:16px/1.6 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:1rem}</style><h1>A3 原样回答（研究者内部）</h1>']
    for r in slots:
        label=' / '.join((r['task_id'],r['mode'],r['status']));q=tasks[r['task_id']]['query']
        answer=r['answer'] if r['answer'] is not None else '[No accepted response; see retained status and receipts.]'
        fence='~'*max(4,max((len(x) for x in re.findall(r'~+',answer)),default=0)+1)
        md.extend(['## '+label,'',q,'',fence,answer,fence,''])
        html_parts.append('<article><h2>'+html.escape(label)+'</h2><p>'+html.escape(q)+'</p><pre>'+html.escape(answer)+'</pre></article>')
    put(output/'READABLE_RESPONSES.md','\n'.join(md).encode());put(output/'READABLE_RESPONSES.html','\n'.join(html_parts).encode())
    report=f'''# 剩余生成结果

终态：{terminal}。246 槽状态：{json.dumps(counts)}。183 份旧规范回答逐字保留；上轮六个 Planning 替代不变。

新增物理调用 {new['physical_calls']}；ROUTE/CANDIDATE/FINAL：{json.dumps(new['physical_calls_by_group'])}。
新增接受 {new['successful_calls']}、失败 {new['failed_calls']}、未知 {new['unknown_calls']}；累计调用 {cumulative['physical_calls']}。
历史 286 次尝试及八个 UNKNOWN 原记录保留；当前缺失 {summary['current_missing_slots']} 槽。
本轮未知的同 payload 补发 {new['historical_unknown_resends']} 次。额外网络等待与重建 {new['network_recovery_waits']} 次。
累计预算借记 ${cumulative['budget_debit_usd']:.8f} / $10，包括历史借记与全部未知预留；不是 Provider 账单认证。
新增真实 RAG {new['actual_rag_calls']}、Memory {new['actual_memory_calls']}；累计 {cumulative['actual_rag_calls']} / {cumulative['actual_memory_calls']}。

起始 HEAD {policy['starting_head']}；执行 HEAD {a['binding']['git_head']}。结果提交见 ZIP 根 GIT_LINEAGE.json。
模型、temperature 0、输出上限、30 秒 timeout、SDK retries 0、串行起始间隔至少 2 秒及原外发范围不变。
安全异常链只记录类、errno、阶段、响应存在状态和时间；不记录异常 repr、headers、环境或密钥，不关闭 TLS 校验。
恢复依据是用户直接授权。Memory 主进程禁网机制已离线复现；完整准备已隔离到无凭据的离线子进程。历史未知状态及预留不重分类。
官方错误分类参考：[OpenAI Error codes](https://developers.openai.com/api/docs/guides/error-codes)；实际行为同时核对本机 SDK 1.109.1。

RESPONSE_HANDOFF.jsonl 与 RESULT_LINEAGE_246.jsonl 保存全部槽，READABLE_RESPONSES 保存原样回答。
UNKNOWN_AND_FAILED_ATTEMPTS.jsonl 保留跨 run 的每条异常，MISSING_AND_DEPENDENCY_BLOCKED.jsonl 保留最终缺失。
冻结人评交接见 HUMAN_HANDOFF_README.md；Judge 0、人评分数 0，未读取 B1 活动文件。
'''
    put(output/'EXECUTION_REPORT.md',report.encode())
    verify=dict(parent_before_identity=parent.identity,parent_after_identity=LayeredLedger().identity,
        frozen_binding_matches=True,canonical_answers_preserved=183,slots=246,answer_bytes_match_raw=True,
        old_unknown_receipts_retained=8,scientific_files_unchanged=True,offline_preparation_isolated=True,minimum_start_interval_seconds=new['minimum_start_interval_seconds'])
    assert verify['parent_before_identity']==verify['parent_after_identity']
    put(output/'INDEPENDENT_CHECKS.json',blob(verify))
    entries=[dict(path=str(p.relative_to(output)),bytes=p.stat().st_size,sha256=sha(p.read_bytes())) for p in sorted(output.rglob('*')) if p.is_file()]
    handoff=dict(schema_version='RQ3_GENERATION_HANDOFF_V1',data_kind='FROZEN_REAL_RESPONSES',frozen=True,
        terminal_state=terminal,task_ids=load(DATA/'RUN_MANIFEST.json')['task_ids'],modes=load(DATA/'CONFIG_PROPOSED.json')['modes'],
        input_identity=binding,approval_binding=a['binding'],protocol_sha256=metadata['protocol_sha256'],
        responses={'path':'RESPONSE_HANDOFF.jsonl','sha256':sha((output/'RESPONSE_HANDOFF.jsonl').read_bytes())},
        study_metadata_sha256=sha((output/'STUDY_METADATA.json').read_bytes()),accepted_answer_statuses=['ACCEPTED'],
        coverage={'total_slots':246,'rateable_answers':summary['accepted_answers']},actual_call_count=cumulative['physical_calls'],
        answer_whitespace_preserved=True,result_files=entries)
    put(output/'GENERATION_HANDOFF_MANIFEST.json',blob(handoff))
    return summary


def verify_zip(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
        for i in z.infolist():
            p=PurePosixPath(i.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename and not stat.S_ISLNK(i.external_attr>>16)
        manifest=json.loads(z.read('MANIFEST.json'))
        assert set(names)=={e['path'] for e in manifest['members']}|{'MANIFEST.json'}
        for e in manifest['members']:
            b=z.read(e['path']);assert len(b)==e['bytes'] and sha(b)==e['sha256']
        slots=[json.loads(b) for b in z.read('results/RESPONSE_HANDOFF.jsonl').splitlines()]
        assert len(slots)==246 and len({r['declared_slot_key'] for r in slots})==246
        for r in slots:
            assert r['human_scores']==[]
            for k in ('raw_response','response_record'):
                if r[k+'_path']:assert sha(z.read('results/'+r[k+'_path']))==r[k+'_sha256']
            if r['answer'] is not None:
                assert r['status']=='ACCEPTED' and sha(r['answer'].encode())==r['answer_sha256']
                raw=json.loads(z.read('results/'+r['raw_response_path']))
                assert json.loads(raw['choices'][0]['message']['content'])['answer']==r['answer']
                if r['previous_status']=='ACCEPTED':assert r['answer_sha256']==r['previous_answer_sha256']
        h=json.loads(z.read('results/GENERATION_HANDOFF_MANIFEST.json'))
        for e in h['result_files']:
            b=z.read('results/'+e['path']);assert sha(b)==e['sha256'] and len(b)==e['bytes']
        assert sha(z.read('results/STUDY_METADATA.json'))==h['study_metadata_sha256']
        unknown=[json.loads(b) for b in z.read('results/UNKNOWN_AND_FAILED_ATTEMPTS.jsonl').splitlines()]
        assert sum(r['source_run'] in ('A','A1','A2') and r['status']=='UNKNOWN_COMPLETION' for r in unknown)==8
    return dict(path=str(path),sha256=sha(path.read_bytes()),bytes=path.stat().st_size,members=len(names),
        crc_ok=True,safe_paths=True,member_lengths_and_hashes_verified=True,all_246_slots_verified=True,
        raw_answer_text_verified=True,canonical_183_preserved=True,git=manifest['git'])


def package(path):
    assert not path.exists() and git('status','--porcelain')==''
    parent=LayeredLedger();starting=load(HERE/'RECOVERY_POLICY.json')['starting_head']
    paths=git('diff','--name-only',starting,'HEAD').splitlines()
    assert all(p.startswith(str(HERE.relative_to(ROOT))+'/') for p in paths)
    lineage=dict(starting_head=starting,execution_head=load(HERE/'results/EXECUTION_APPROVAL.json')['binding']['git_head'],
        ending_head=git('rev-parse','HEAD'),branch=git('branch','--show-current'),starting_clean=True,ending_clean=True,
        only_additive_recovery_directory_changed=True,commits=git('log','--format=%H %s',starting+'..HEAD').splitlines())
    files={}
    for p in HERE.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
            assert not p.is_symlink();files[str(p.relative_to(HERE))]=p.read_bytes()
    files['GIT_LINEAGE.json']=blob(lineage)
    controls=[str(p.relative_to(ROOT)) for p in HERE.glob('*.py')]+[str((HERE/'RECOVERY_POLICY.json').relative_to(ROOT))]
    files['CONTROL_PATCH.diff']=subprocess.check_output(['git','diff',starting,'HEAD','--',*controls],cwd=ROOT)
    files['README.md']=('''# RQ3 CONFIRMED41 A3 剩余生成审阅包

先读 results/EXECUTION_REPORT.md，再读 results/EXECUTION_SUMMARY.json 与 HUMAN_HANDOFF_README.md。
本包包含本轮实际请求与原始收据、246 槽选择和原样回答、跨 run 父来源索引、历史未知、冻结人评材料、mock 测试及恢复代码补丁。
父来源必要收据置于 results/parent_sources/；未重复复制无关旧资料。
完整父包位于 /Users/liuming/Downloads/RQ3_CONFIRMED41_REMAINING_GENERATION_REVIEW_2026-09-08.zip，
SHA-256 61487ebddbaecade38af12b6b8602bf6d7a1413e20e037bfd453c71da2d9ba97。
未改科学实现可定位于该父包、原工作区与 GIT_LINEAGE.json 指定起始提交。
复现代码时保留工作区相对目录；本 ZIP 不是独立安装包。
MANIFEST.json 对除自身外每个实际成员记录长度和 SHA-256；交付前已重新打开 ZIP 检查 CRC、安全路径及答案原文。
研究者阅读版含模式，不直接交给评分者。人评仍由本人完成。
排除密钥、.env、headers、完整环境、Git 对象、临时 native 模型缓存、B1 活动文件及未获准数据。
''').encode()
    manifest=dict(git=lineage,self_excluded='MANIFEST.json',members=[dict(path=n,bytes=len(b),sha256=sha(b)) for n,b in sorted(files.items())])
    files['MANIFEST.json']=blob(manifest)
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for n,b in sorted(files.items()):z.writestr(n,b)
    return verify_zip(path)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path);p.add_argument('--approval',type=Path)
    p.add_argument('--preflight',type=Path);p.add_argument('--process',type=Path);p.add_argument('--zip',type=Path)
    a=p.parse_args();base.offline()
    if a.zip:result=package(a.zip)
    else:result=export(a.run,a.approval,a.preflight,a.process)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
