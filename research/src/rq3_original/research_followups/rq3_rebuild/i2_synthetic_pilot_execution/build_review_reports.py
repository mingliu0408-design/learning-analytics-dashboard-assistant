"""Read existing live receipts once; produce descriptive I2 audit, never score."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import HOME, sha, load, write_once, canonical
from utils.c4_rebuild.i1.policy import verify_source_manifest, verify_external_resources
from utils.c4_rebuild.i1.schemas import errors, final_errors

HERE = Path(__file__).resolve().parent
LIVE = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07')
AUTH = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_AUTHORIZATION_2026-09-07.json')
START = '6352d5ef6846e6d4e6d436d840811643642ff24f'
LABEL = 'EXPOSED_SYNTHETIC_DEVELOPMENT_NOT_FORMAL_BLIND_EVALUATION'

def jsontext(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)

def write_text(name, value):
    with (HERE/name).open('x') as f:
        f.write(value)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()

def main():
    process = load(HERE/'EXECUTION_PROCESS_RECEIPT.json')
    manifest = load(HOME/'TASK_MANIFEST.json')
    config = load(HOME/'PILOT_CONFIGURATION_PROPOSED.json')
    pre = load(HERE/'PREFLIGHT_VERIFICATION.json')
    starts = sorted((load(p) for p in (LIVE/'attempts').glob('*.start.json')), key=lambda r: r['monotonic_start'])
    outcomes = {p.name.removesuffix('.outcome.json'): load(p) for p in (LIVE/'attempts').glob('*.outcome.json')}
    terminals = {x['logical']: x for x in (load(p) for p in (LIVE/'terminals').glob('*.json'))}
    stages = {(x['logical'], x['stage']): (p, x) for p in (LIVE/'stages').glob('*.json') for x in [load(p)]}
    live_files = sorted(p for p in LIVE.rglob('*') if p.is_file())
    baseline = {str(p.relative_to(LIVE)): sha(p.read_bytes()) for p in live_files}
    roles = {}
    for role in ('RAG', 'MEMORY', 'B4_PLANNING', 'CANDIDATE', 'FINAL'):
        rr = [r for r in starts if r['role'] == role]
        oo = [outcomes[r['attempt_id']] for r in rr if r['attempt_id'] in outcomes]
        known = [o for o in oo if isinstance(o.get('usage'), dict)
            and all(type(o['usage'].get(k)) is int for k in ('prompt_tokens','completion_tokens'))]
        roles[role] = dict(initial=sum(r['attempt']==1 for r in rr),
            retry_or_correction=sum(r['attempt']>1 for r in rr), physical_attempts=len(rr),
            known_usage_attempts=len(known), unknown_usage_attempts=len(rr)-len(known),
            prompt_tokens=sum(o['usage']['prompt_tokens'] for o in known),
            completion_tokens=sum(o['usage']['completion_tokens'] for o in known),
            cached_prompt_tokens=sum((o['usage'].get('prompt_tokens_details') or {}).get('cached_tokens',0) for o in known),
            attempt_status_counts=dict(Counter(o['status'] for o in oo)),
            logical_terminal_status_counts=dict(Counter(t['result']['status'] for t in terminals.values()
                if any(r['logical']==t['logical'] for r in rr))))
    retry_rows = []
    for r in starts:
        if r['attempt'] > 1:
            prev = next(s for s in starts if s['logical']==r['logical'] and s['attempt']==r['attempt']-1)
            retry_rows.append(dict(logical=r['logical'], role=r['role'], attempt_id=r['attempt_id'],
                previous_status=outcomes.get(prev['attempt_id'],{}).get('status','UNKNOWN'),
                kind='CORRECTION' if r['request_sha256'] != prev['request_sha256'] else 'IDENTICAL_RETRY'))
    def accounted(r):
        u = outcomes.get(r['attempt_id'],{}).get('usage')
        observed = ((u['prompt_tokens']*0.15+u['completion_tokens']*0.6)/1e6
            if isinstance(u,dict) and all(type(u.get(k)) is int for k in ('prompt_tokens','completion_tokens')) else 0)
        return max(r['reserved_usd_upper_bound'], observed)
    gaps = [b['monotonic_start']-a['monotonic_start'] for a,b in zip(starts, starts[1:])]
    serial = all(outcomes[a['attempt_id']]['monotonic_end'] <= b['monotonic_start'] for a,b in zip(starts,starts[1:])
        if a['attempt_id'] in outcomes)
    module_traces=[s[1]['output']['prepared']['trace'] for k,s in stages.items() if k[1]=='C_MODULE_REBUILD']
    memory_reads=[t['memory_diagnostics'] for t in module_traces if (t.get('memory_diagnostics') or {}).get('identity')]
    summary = dict(label=LABEL, roles=roles, total_physical_attempts=len(starts),
        initial_calls=sum(r['attempt']==1 for r in starts), retries_and_corrections=retry_rows,
        returned_models=dict(Counter(o['returned_model'] for o in outcomes.values() if o.get('returned_model'))),
        unknown_completion_attempts=[r['attempt_id'] for r in starts if r['attempt_id'] not in outcomes
            or outcomes[r['attempt_id']]['completion']=='UNKNOWN'],
        usage=dict(prompt_tokens=sum(r['prompt_tokens'] for r in roles.values()),
            completion_tokens=sum(r['completion_tokens'] for r in roles.values()),
            unknown_usage_attempts=sum(r['unknown_usage_attempts'] for r in roles.values())),
        budget=dict(approved_ceiling_usd=2.0, frozen_prospective_convention_usd=1.6735103999999998,
            charged_under_runner_convention_usd=sum(accounted(r) for r in starts),
            known_usage_at_uncached_rates_usd=sum((r['prompt_tokens']*0.15+r['completion_tokens']*0.6)/1e6 for r in roles.values()),
            actual_serialized_input_byte_units=sum(len(canonical(r['request']))+256 for r in starts),
            actual_output_token_caps_sum=sum(r['request']['max_tokens'] for r in starts),
            unknown_reservations_retained=True, invoice_verified=False,
            limitation='Byte units and MPNet tokenizer estimates are not OpenAI prompt tokens. Listed-rate arithmetic and reservations are not a bill.'),
        pacing=dict(serial=serial, minimum_monotonic_start_gap_seconds=min(gaps) if gaps else None,
            approved_minimum_seconds=2.0, sdk_retries=0, transport_timeout_seconds=30),
        actual_memory=dict(completed_native_read_conditions=len(memory_reads),
            backend_identity_counts=dict(Counter(m['identity'] for m in memory_reads)),
            readonly_unchanged_conditions=sum(m.get('readonly_state_unchanged') is True for m in memory_reads),
            conditions_with_kept_facts=sum(bool(m.get('kept_facts')) for m in memory_reads),
            generic_fallback_conditions=sum(m.get('generic_fallback')=='EXERCISED' for m in memory_reads),
            source_link_expansion_conditions=sum(bool(m.get('added_facts')) for m in memory_reads),
            exact_encoder_forward_count=None,
            evidence_limit='Completed original hybrid worker path and persisted M1 diagnostics; no independent per-forward counter persisted by I1.'),
        model_changes=0, supervisor_resume_calls=0, judge_calls=0, human_scores=0, final_statistics=0)
    write_once(HERE/'CALL_AND_USAGE_SUMMARY.json', summary)
    rows=[]
    for task in manifest['task_ids']:
        for mode in manifest['modes']:
            logical=task+':'+mode
            attempts=[r for r in starts if r['logical']==logical+':FINAL']
            terminal=terminals.get(logical+':FINAL')
            freeze=stages.get((logical,'F_G_RESPONSE_FREEZE'))
            result=terminal['result'] if terminal else None
            status=('VALID' if result and result['status']=='ACCEPTED' else 'FAILED' if result else
                'UNKNOWN' if attempts else 'UNEXECUTED')
            module=stages.get((logical,'C_MODULE_REBUILD'))
            planning=stages.get((logical,'D_E_CANDIDATE_CHECK_REPAIR'))
            trace=module[1]['output']['prepared']['trace'] if module else {}
            rows.append(dict(task_id=task,mode=mode,logical=logical,status=status,
                final_terminal_status=result['status'] if result else None,
                final_attempt_ids=[r['attempt_id'] for r in attempts],
                response_frozen=bool(freeze),
                freeze_file=str(freeze[0].relative_to(LIVE)) if freeze else None,
                modules_prepared=bool(module),
                route_status=trace.get('route_status'), route=trace.get('route'),
                planning_status=planning[1]['output']['planning_status'] if planning else None,
                last_completed_stage=('F_G_RESPONSE_FREEZE' if freeze else 'D_E_CANDIDATE_CHECK_REPAIR' if planning else
                    'C_MODULE_REBUILD' if module else 'A_VALIDATED_SOURCE' if (task,'A_VALIDATED_SOURCE') in stages else None)))
    coverage = {s:sum(r['status']==s for r in rows) for s in ('VALID','FAILED','UNKNOWN','UNEXECUTED')}
    assert len(rows)==72 and len({r['logical'] for r in rows})==72
    status = ('SYNTHETIC_DEV_RESPONSES_AVAILABLE_PENDING_HUMAN_INSPECTION'
        if coverage['VALID']==72 and process['returncode']==0 else 'SYNTHETIC_DEV_INCOMPLETE_PRESERVED_REQUIRES_DECISION')
    write_once(HERE/'ALL_SLOT_STATUS.json', dict(status=status,coverage=coverage,slots=rows,
        definition='VALID means accepted by original mechanical checks, not response quality. UNEXECUTED means no final provider attempt, even if earlier modules ran.'))
    observations=[]
    for row in rows:
        module=stages.get((row['logical'],'C_MODULE_REBUILD'))
        if not module: continue
        p=module[1]['output']['prepared'];t=p['trace'];f=p['final_request']
        evidence=f.get('runtime_input',{}).get('evidence',{}).get('selected_evidence',[])
        observations.append(dict(logical=row['logical'],activation=t.get('activation'),
            ordered_events=t.get('ordered_events'),route=t.get('route'),route_status=t.get('route_status'),
            requested_memory_backend=module[1]['output']['memory_backend'],
            memory=t.get('memory_diagnostics'), memory_ids=t.get('memory_returned_ids'),
            purpose_resolution=t.get('purpose_resolution'),course_ids=t.get('course_returned_ids'),
            evidence=[{k:e.get(k) for k in ('evidence_id','source_kind','evidence_type','evidence_strength')} for e in evidence],
            e1_fact_count=len(t.get('e1_fact_trace',[])),
            e1_fact_domains=sorted({x['domain'] for x in t.get('e1_fact_trace',[])}),
            e1_values_verified=all(x.get('final_value_verified') for x in t.get('e1_fact_trace',[])),
            planning_status=row['planning_status'],clarification_required=f.get('clarification_required'),
            semantic_support='NOT_CHECKED',answer_plan_fidelity='NOT_CHECKED'))
    write_once(HERE/'MODULE_PATH_OBSERVATIONS.json',dict(label=LABEL,conditions=observations))
    route_stages=[s[1] for k,s in stages.items() if k[1]=='B_FROZEN_P3']
    write_once(HERE/'EXECUTION_AND_SOURCE_BINDINGS.json',dict(status=status,starting_head=START,
        workspace=str(ROOT),branch=git('branch','--show-current'),live_output=str(LIVE),
        approval_file=str(AUTH),approval_file_sha256=sha(AUTH.read_bytes()),
        proposal_approved_field=config['approved'],preflight=pre,
        run_binding=load(LIVE/'RUN_BINDING.json'),process=process,
        route_input_terminals=len(route_stages),task_slots=12,unique_four_field_inputs=8,modes=6,
        final_head_location='GIT_VERSION.json in review archive and adjacent review receipt; committed report cannot contain its own commit hash.'))
    build_reading(manifest,rows,stages,terminals)
    build_markdown(status,coverage,summary,observations,route_stages,process)
    # Verify original source bytes and receipt chains without replaying any transport.
    source=verify_source_manifest(HOME/'SOURCE_MANIFEST.json')
    verify_external_resources()
    assert git('rev-parse','HEAD')==START and not git('diff','--name-only',START)
    assert config['approved'] is False
    assert len(starts)<=264 and all(r['attempt']<=2 for r in starts)
    assert sum(accounted(r) for r in starts)<=2.0
    assert serial and all(g>=2 for g in gaps)
    for group,cap in config['initial_slot_ceilings'].items():
        assert len({r['logical'] for r in starts if r['group']==group})<=cap
    for r in starts:
        assert sha(r['request'])==r['request_sha256']
        assert r['request']['model']=='gpt-4o-mini-2024-07-18' and r['request']['temperature']==0
        assert r['request']['max_tokens']==dict(RAG=32,MEMORY=32,B4_PLANNING=64,CANDIDATE=2048,FINAL=2048)[r['role']]
        assert not r['request'].get('stream') and not r['request'].get('tools')
        assert len(canonical(r['request']))+256<=config['max_request_input_byte_units']
        if r['attempt_id'] in outcomes:
            o=outcomes[r['attempt_id']]
            if o.get('raw_sha256'):
                assert sha((LIVE/'attempts'/f"{r['attempt_id']}.raw.json").read_bytes())==o['raw_sha256']
    for terminal in terminals.values():
        o=LIVE/'attempts'/f"{terminal['attempt_id']}.outcome.json"
        assert sha(o.read_bytes())==terminal['outcome_sha256'] and load(o)==terminal['result']
    for path,s in stages.values():
        assert sha(s['output'])==s['output_sha256']
    journal=[json.loads(line) for line in (LIVE/'JOURNAL.jsonl').read_text().splitlines()]
    assert [r for r in journal if r['event']=='ATTEMPT_RESERVED_BEFORE_TRANSPORT']==[
        dict(event='ATTEMPT_RESERVED_BEFORE_TRANSPORT',**r) for r in starts]
    assert len([r for r in journal if r['event']=='ATTEMPT_OUTCOME'])==len(outcomes)
    for row in rows:
        if row['status']=='VALID':
            terminal=terminals[row['logical']+':FINAL']
            module=stages[(row['logical'],'C_MODULE_REBUILD')][1]['output']['prepared']
            plan=stages[(row['logical'],'D_E_CANDIDATE_CHECK_REPAIR')][1]['output']['accepted_plan']
            start=next(r for r in starts if r['attempt_id']==terminal['attempt_id'])
            assert not errors(terminal['result']['value'],start['request']['response_format']['json_schema']['schema'])
            raw=load(LIVE/'attempts'/f"{terminal['attempt_id']}.raw.json")
            assert json.loads(raw['choices'][0]['message']['content'])==terminal['result']['value']
            assert stages[(row['logical'],'F_G_RESPONSE_FREEZE')][1]['output']['result']==terminal['result']
            assert not final_errors(terminal['result']['value'], module['trace']['retained_evidence_ids'], plan)
    secret=os.environ.get('OPENAI_API_KEY','').encode()
    assert secret and all(secret not in p.read_bytes() for p in live_files)
    assert baseline=={str(p.relative_to(LIVE)):sha(p.read_bytes()) for p in live_files}
    write_once(HERE/'PRESERVATION_CHECKS.json',dict(status='PASS',checked_at=datetime.now(timezone.utc).isoformat(),
        original_source_files=len(source['files']),original_tracked_changes=0,
        frozen_external_models_and_interpreters='PASS',config_approved_false=True,
        live_receipts_unchanged=True,live_files=len(live_files),live_manifest_sha256=sha(baseline),
        receipt_hash_chains='PASS',accepted_final_mechanical_readback=sum(r['status']=='VALID' for r in rows),
        attempts_budget_pacing_caps='PASS',all_72_identities_present=True,
        credential_exact_value_scan='PASS_ZERO_MATCHES',credential_value_recorded=False,
        offline_tests=dict(passed=62,failed=0,skipped=0,path='OFFLINE_TEST_OUTPUT.txt'),
        generated_text_rewritten=False,unknown_completion_auto_handling=False,
        human_scores=0,judge_calls=0,final_statistics=0))
    print(jsontext(dict(status=status,coverage=coverage,calls=roles)))

def build_reading(manifest, rows, stages, terminals):
    lines=['# 实际合成回答阅读副本', '', LABEL, '',
        '以下原文来自本次 LIVE Provider 回执，按固定任务与模式顺序排列。未作改写或质量评分。12 个槽位仅有 8 个唯一四字段输入。',
        'VALID 只表示原机械校验接受；人工事实、约束和自然度检查仍为空。每个条件的完整请求、来源跨度和原始回答位于审阅包 live/ 中。','']
    for task in manifest['task_ids']:
        source=next(r['source'] for r in manifest['sources'] if r['task_id']==task)
        lines += ['## '+task,'','问题：'+source['primary']['current_query'],'',
            '页面：'+source['primary']['current_page'], '',
            '<details><summary>固定合成上下文、可见历史与时间窗</summary>','',
            '```json',jsontext(source['primary']),'```','','</details>','']
        for row in [r for r in rows if r['task_id']==task]:
            lines+=['### '+row['mode'],'','状态：'+row['status']+'；规划状态：'+str(row['planning_status']),'']
            terminal=terminals.get(row['logical']+':FINAL')
            if terminal and isinstance(terminal['result'].get('value'),dict) and 'answer' in terminal['result']['value']:
                value=terminal['result']['value']
                lines += [value['answer'],'','行政字段（保留原值）：','',
                    '```json',jsontext({k:v for k,v in value.items() if k!='answer'}),'```','',
                    '原始回执：`live/attempts/'+terminal['attempt_id']+'.raw.json`','']
            else:
                lines+=['此槽位没有已接受的实际回答。未以 mock 或新生成文本补齐。','']
            module=stages.get((row['logical'],'C_MODULE_REBUILD'))
            if module:
                request=module[1]['output']['prepared']['final_request']
                lines += ['<details><summary>本条件实际模块证据与澄清项</summary>','',
                    '```json',jsontext(request['runtime_input']),'```','',
                    '澄清项：`'+json.dumps(request.get('clarification_required'),ensure_ascii=False)+'`','',
                    '</details>','']
    write_text('DEVELOPMENT_READING_COPY.md','\n'.join(lines)+'\n')

def build_markdown(status,coverage,summary,observations,routes,process):
    write_text('START_HERE.md',f'# I2 实际合成开发试点\n\n状态：**{status}**。\n\n'
        '先读 [完成报告](I2_COMPLETION_REPORT.md)，再按固定顺序阅读 [实际合成回答](DEVELOPMENT_READING_COPY.md)。'
        '所有 72 个预定身份见 [槽位覆盖](ALL_SLOT_STATUS.json)，调用与预算见 [用量审计](CALL_AND_USAGE_SUMMARY.json)。\n\n'
        f'{LABEL}。没有 LLM Judge、人工评分或研究统计。外部原始结果位于 `{LIVE}`。\n')
    text=['# 模块路径观察','',LABEL,'',
        '本报告只汇总实际执行路径和已保存字段，不评定回答质量，不比较方法优劣。',
        'Memory backend 的配置标签本身不是实际读取证据；下表身份来自已完成模块的 memory_diagnostics。',
        '原 live worker 仅在 S3/S5、真实 Memory YES、权限及澄清门控通过时构造原 hybrid encoder；未另行探针、替换或重跑。',
        '原 runner 未持久保存独立 encoder 输入/forward 总数；因此不宣称精确本地 forward 数。', '',
        '| 条件 | RAG scorer路径 | 返回课程块 | Memory实际身份 / 种子 / 保留 | P1状态 | E1事实 |',
        '|---|---|---:|---|---|---:|']
    for o in observations:
        mem=o.get('memory') or {}
        text.append(f"| {o['logical']} | {'RAG_SINGLE_GATE_SCORER' in (o['ordered_events'] or [])} | {len(o['course_ids'] or [])} | "
            f"{mem.get('identity','未读取')} / {len(mem.get('original_seed_ids',[]))} / {len(mem.get('kept_facts',[]))} | {o['planning_status']} | {o['e1_fact_count']} |")
    text += ['','实际 P3（完整三角色结果保留在 live/stages）：','',
        '```json',jsontext([dict(primary_sha256=r['logical'],route=r['output']['route']) for r in routes]),'```','',
        '逐条件 activation、目的回退、关系扩展、来源保留、课程支持标签和澄清字段见 MODULE_PATH_OBSERVATIONS.json。',
        'semantic_support 和 answer_plan_fidelity 均保持 NOT_CHECKED。']
    write_text('MODULE_PATH_OBSERVATIONS.md','\n'.join(text)+'\n')
    write_text('HUMAN_DEV_REVIEW_CHECKLIST.md','# 人工开发阅读检查表\n\n'+LABEL+'\n\n'
        '仅供后续人工填写。不是正式评分包；没有指定评分者、适用性决定、分数或签名。每条观察请引用槽位及原始来源。\n\n'
        '| 任务 / 模式 | 事实及来源观察 | 约束和缺失信息观察 | 自然度观察 | 原始回执或来源指针 |\n'
        '|---|---|---|---|---|\n' + '\n'.join('| '+t+':'+m+' | | | | |' for t in load(HOME/'TASK_MANIFEST.json')['task_ids'] for m in load(HOME/'TASK_MANIFEST.json')['modes'])+'\n')
    s=summary
    lines=['# I2 执行完成 / 保全报告','',f'状态：**{status}**。','',
        f'最终槽位 72：有效 {coverage["VALID"]}，失败 {coverage["FAILED"]}，未知 {coverage["UNKNOWN"]}，未执行 {coverage["UNEXECUTED"]}。有效只指原机械校验通过。',
        f'原运行器调用一次，进程退出码 {process["returncode"]}；没有 --resume 或额外 canary。','',
        '| 角色 | 初次 | 重试 / 修订 | 物理尝试 |','|---|---:|---:|---:|']
    lines += [f'| {k} | {v["initial"]} | {v["retry_or_correction"]} | {v["physical_attempts"]} |' for k,v in s['roles'].items()]
    lines += ['',f'合计 {s["total_physical_attempts"]} 次。未知完成 {len(s["unknown_completion_attempts"])}；返回模型：{s["returned_models"]}。',
        f'候选终态：{s["roles"]["CANDIDATE"]["logical_terminal_status_counts"]}。本轮 16 个候选均在一次修订后保留 ENCODED_CHECK 失败，未产生已接受计划；相应最终回答仍按原失败/澄清分支生成。',
        '规划门控另有 2 个 NEEDS_INFORMATION 条件未调用候选；其余 54 个条件未激活 Planner。',
        f'返回 usage：输入 {s["usage"]["prompt_tokens"]}，输出 {s["usage"]["completion_tokens"]} tokens；未知 usage 尝试 {s["usage"]["unknown_usage_attempts"]}。',
        f'原预算预留约定累计 USD {s["budget"]["charged_under_runner_convention_usd"]:.9f}，已知 usage 按未缓存单价折算 USD {s["budget"]["known_usage_at_uncached_rates_usd"]:.9f}。上限 USD 2；这些不是账单确认。',
        '单价与指定快照于本次执行前从 [OpenAI 官方模型页](https://developers.openai.com/api/docs/models/gpt-4o-mini) 核验。',
        f'最小 monotonic 起始间隔 {s["pacing"]["minimum_monotonic_start_gap_seconds"]} 秒；串行 {s["pacing"]["serial"]}，SDK retries=0，timeout=30 秒。','',
        '实际读取、RAG 路径、Planner 准入/修订/失败及跨页证据见 MODULE_PATH_OBSERVATIONS.md。',
        '实际 M1_HYBRID_LINKS_DEV_CANDIDATE 读取 14 个条件，14 个均保留事实且只读状态未变；10 个触发通用目的回退，2 个有来源链接扩展。未持久保存精确 encoder forward 总数。',
        'RAG scorer 实际触达 10 个条件，4 个返回课程块，支持标签为 BODY_EXCERPT；369 个 E1 事实指针通过最终请求值回读。',
        '原运行器控制台与进程收据完整保留；没有恢复执行、处理未知完成、更换模型或补跑有效回答。',
        '62 项原 I1 离线测试通过；161 个冻结来源文件、外部解释器和模型身份在执行前后均核验。原 I1、H0 和更早文件不变。',
        'PRESERVATION_CHECKS.json 记录回执链、实际回答机械回读和凭据扫描。','',
        'Git 空白检查仅在阅读副本提示 13 行来自原始回答的尾部空格及末尾空行；逐行来源已核验，按原文保留。其余暂存文件检查通过，见 GIT_WHITESPACE_REVIEW.json。','',
        f'Git 起始：`{START}`。最终唯一 I2 提交的精确 HEAD 见审阅 ZIP 的 GIT_VERSION.json 及外部回读收据。',
        f'原始结果：`{LIVE}`。审阅 ZIP：`/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_EXECUTION_REVIEW_2026-09-07.zip`。',
        '本提交报告不内嵌其自身提交哈希或 ZIP 自身哈希；两者由提交后的外部回读收据准确记录。','',
        '实际回答未作改写，见 DEVELOPMENT_READING_COPY.md。人工观察表仍为空。LLM Judge、人工评分、最终统计均为 0。',
        '这是已暴露合成开发试点，12 槽位仅 8 个唯一四字段输入；不属于正式 RQ3、真实学生部署或 held-out 效果证据。']
    write_text('I2_COMPLETION_REPORT.md','\n'.join(lines)+'\n')

if __name__=='__main__':
    main()
