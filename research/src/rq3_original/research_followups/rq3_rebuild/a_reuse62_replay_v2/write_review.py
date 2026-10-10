"""Small readable review materials from actual saved results; no scoring."""
from replay_common import *
from collections import Counter
import shutil
import csv

PY="'/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/.venv/bin/python'"
REL='research_followups/rq3_rebuild/a_reuse62_replay_v2'

def main():
    tasks=lines(HERE/'runtime/TASKS_62.jsonl');rows=read(HERE/'PREPARATION_RESULTS_62.json');memory=read(HERE/'MEMORY_RESULTS.json')
    oldroutes={r['scenario_id']:r for r in read(OLD/'historical/p3_routes_62.json')}
    gating=[]
    for r in rows:
        route=oldroutes[r['task_id']]
        gating.append(dict(task_id=r['task_id'],current_deterministic_clarification=r['gate_needs_clarification'],
            historical_only_p3={k:route[k] for k in ('rag_required','memory_required','planning_required')},
            historical_primary_sha256=route['semantic_input_sha256'],current_primary_sha256=r['primary_sha256'],
            current_p3='NOT_RUN_OLD_BITS_NOT_REUSED',memory_diagnostic=r['memory_diagnostic']))
    write(HERE/'GATING_AND_READOUT_62.json',gating)
    counts=read(HERE/'PREPARATION_COUNTS.json');acceptance=read(HERE/'OFFLINE_ACCEPTANCE.json')
    test=read(HERE/'TEST_REPORT.json');extra=read(HERE/'receipts/UNDATED_SNAPSHOT_PLANNING_SUMMARY_CHECK.json')
    write(HERE/'ACTUAL_RUN_COUNTS.json',dict(safe_source_aggregation=dict(moodle_rows=313,echo_rows=9,features_rows=1,passes=1),
        roster_entries=62,source_readiness_full_passes=5,source_readiness_row_checks=310,
        native_memory_setup_cases=9,native_writer_operations=20,closed_mode_clones=54,
        native_memory_diagnostic_reads=9,native_memory_read_retries=0,encoder_startups=1,
        encoder_batches=len(memory['encoder_batches']),encoder_warmup_batches=1,
        rag_shared_corpus_count=624,rag_diagnostic_queries=4,rag_repeated_queries=0,
        compiler_preparations=12,compiler_preparations_basis='6 initial S0/S1 + 4 all-NO mode checks + 2 final Overview-summary checks; no retrieval repeated',
        saved_planning_bridge_diagnostics=3,planning_validation_checks=11,
        tests_passed=test['tests']+extra['tests'],new_tests=12,additional_exact_snapshot_checks=5,
        snapshot_check_executions=10,snapshot_check_repetition_reason='Rechecked five cases after narrowing Overview to summaries; no module reads',
        provider_calls=0,p3_llm_calls=0,candidate_generation_calls=0,final_generation_calls=0,judge_calls=0,
        human_values_filled=0,live_outputs=0,reused_old_judge_scores=0,
        reporting_recovery='First R0 result was read from its saved receipt after a reporting field-name error; no query repeated.',
        unchanged_frozen_interfaces=['a_reuse62/interfaces.py','P3 frozen policies','native M1','FINAL two-field schema']))
    text=['# 原 62 题可读受控回放集','',
        'query/page 与 canonical 一致；仅九例目标历史按已批准条件隐藏。来源需求和准备状态是评审记录，不进入生成器。','']
    for t,r in zip(tasks,rows):
        text += [f"## {t['task_id']} · {r['source_dataset']} / {r['source_scenario_id']} · {t['page']}",'',t['query'],'',
            f"准备：{r['preparation_status']}。需求：{r['task_requirement']}。",
            f"当前页：{', '.join(r['current_domains'])}；S1 可增加：{', '.join(r['additional_domains']) or '无'}。",
            '缺件：'+('; '.join(r['important_missing']) or '无阻塞性事实缺件；仍受来源边界限制。'),
            'Memory：'+r['memory_setup']+'；本轮诊断：'+r['memory_diagnostic']+'。','',
            '目标共同可见历史：','',json.dumps(t['history'],ensure_ascii=False,indent=2),'']
        if t['task_id'] in NINE:
            text+=['隐藏 setup 来源见 runtime/memory_sources/'+t['task_id']+'.json；原同会话版本见 audit/HISTORY_CHANGES.json。','']
    (HERE/'READABLE_REPLAY_62.md').write_text('\n'.join(text))
    pairs='\n'.join(f"| {t} | {s['accepted_writes']} | {s['read_status']} | {len(s['read']['native_ids'])} | {'YES' if oldroutes[t]['memory_required'] else 'NO'} |" for t,s in memory['tasks'].items())
    (HERE/'MEMORY_SUMMARY.md').write_text('# 九例 Memory 预置与读取\n\n| 题号 | 原生写入数 | 一次本地诊断 | 返回条数 | 旧 P3 Memory 位（仅历史） |\n|---|---:|---|---:|---|\n'+pairs+'\n\n共 20 次写入、9 个新初态、54 个六模式克隆、9 次只读诊断；数据库均保持原校验值。4 例 AVAILABLE、3 例 AMBIGUOUS、2 例无匹配。AVAILABLE 只代表返回来源项，并非完整恢复目标、约束和计划。原清单没有有出处的关系断言，不能凭 Gold 补关联；本轮未强制开启 P3。旧 P3 的 NO 仍是历史结果，当前 P3 尚未运行。\n\nU026/U027/U029 的原生检索记录为 PLAN_ANTECEDENT_UNRESOLVED；不能把分拆存储的建议项强行宣布为已选定计划。U031 原无编号计划；U036 的讨论来源与当前资源指标无关。U033/U034 返回 SYSTEM 建议，不能忽略当前自述/更正或据此推定采纳。U037 未召回其 today 限制，不能当作无限时间。\n')
    (HERE/'INPUT_CHANGES.md').write_text('''# 输入变化记录

原 canonical 和 a_reuse62 同会话投影均未修改。62 个 query/page 完全相同；九例跨会话干预是作者公开批准的控制设置，不是源 CSV 已证明的真实会话边界。其他六个非空同会话历史保留；全部模式共享目标历史，隐藏 setup 不提前给 S0/S1/P3。

旧页面输入的追溯链显示它来自 reference_dashboard_evidence，本版本不予运行复用。新输入由 Moodle/Echo/features 安全表和系统指标定义形成；Snapshot-only 与 raw 聚合分别注明，因此不能声称相对旧实验是纯算法隔离或完全相同输入。S0 的当前页不注入其他页。Overview 最终只提供四域汇总；早期详细投影诊断仍保留在 receipts/evidence/U057_*，最终版本证据在 receipts/evidence_summary/ 和 OVERVIEW_SUMMARY_ACCEPTANCE.json，禁止将早期较宽输入用于正式批次。

Moodle 只按提供的事件记录及源 Week/weekday 聚合，没有构造绝对学期日历或时区。Echo 内容周不是观看周，技术行号不是独立视频；W3 “No Lecture Video” 不当漏看。反思保留 45093 累计 Total_chars，周级编辑轨迹、正文与反馈均未知，不能推回旧参考中的周级总结。

Memory 源角色、原文和 setup 时间保留；研究 learner/course 只提供隔离命名空间。旧 QUERY_TIME 用于受控 Memory age/validity，不解释现实今天/本周。U033/U034 目标自述/更正未写库。未构造关系断言、系统建议采纳或历史完成事实。

旧 FINAL 两字段和请求点时间修复不变。新的无日期快照例外仅对 hash-bound 普通建议的事实引用生效；权限、身份、伪造内容和排程反例仍失败，不给未知来源补日期。旧参考需人工重新确认；新人评表全部空白。
''')
    (HERE/'REMAINING_DECISIONS.md').write_text('''# 真正影响事实或外发的问题

1. U002：assessment views 的采集/事件映射定义未恢复；不能自动等同 Resources_views。
2. U004：十天的起点、真实可用时间和待完成任务/截止日未绑定；可提示需要的信息，不能生成已验证日程。
3. U009/U018：反馈或反思正文缺失；字符活动量不能支撑质量/强弱项判断。U014：当前按时提交只是用户自述，核实差异需要提交回执/截止记录。
4. U022：具体编号计划 2/3 前文缺失；不按 CSV 邻接拼接。U039/U059：当前课程周及该周任务未确定。
5. 一次外发/模型/总预算决定：是否把这个版本的页面聚合、合法可见历史、实际检索的课程片段和（被 P3 启用时的）受控 Memory 片段送至所选 Provider；统一 candidate/FINAL 模型、实时价格及总预算仍未批准。没有必要为全部题补真实选课、设备身份或生产日历。

来源准备不等于检索或规划成功：九例 Memory 为部分召回/歧义/缺失，真实 P3 仍未运行。未来保留全部 62 或预声明子集，以及重要缺件题是否保留为需澄清/说明局限的题，均须在看新输出前确定。当前未建议新增题，也未删题。
''')
    command=f"cd {ROOT}\n{PY} -B {REL}/run_batch.py --preflight"
    (HERE/'COMMANDS.md').write_text(f'''# 运行命令与一次批准

当前可以运行无网络、无密钥的 preflight：

```sh
{command}
```

已完成的一次 Memory/R0 验收不要重复调用；收据见 MEMORY_RESULTS.json 和 OFFLINE_ACCEPTANCE.json。

正式全批或预声明子集在一次批准后执行。将 CONFIG_PROPOSED.json 中模型/价格/总预算确认，preflight 取得当前 binding；将 APPROVAL_TEMPLATE.json 另存 APPROVAL_AUTHORIZED.json，填写真实用户决定、同一 binding、批准题号、外发范围和目标输出目录。不要把模板的空白当授权。

```sh
{PY} -B {REL}/run_batch.py --execute \\
  --approval {REL}/runtime/APPROVAL_AUTHORIZED.json \\
  --output {REL}/local_private/approved_generation
```

完整 62×6=372 个 FINAL 槽位；最多 186 个 P3 初始槽位、124 个 candidate 初始槽位。每槽最多两次，最高 1364 次物理调用；实际按 P3/校验结果减少。预算与最新模型可用性未确认，本轮没有查价格或调用 Provider。默认仍建议沿用待批准的 gpt-4o-mini-2024-07-18（candidate/FINAL 相同，temperature=0，2048 输出上限），不构成模型可用性承诺。

恢复已获准批次时使用同一命令加 --resume；DurableRunner 的绑定/锁/UNKNOWN_COMPLETION 门槛保留。不可修改已开始批次来掩盖失败。所有条件重新生成、重新人工评价，不混合旧 Judge 得分。
''')
    (HERE/'START_HERE.md').write_text('''# RQ3 A · 原 62 题受控历史回放

已保留并绑定 62/62 个问题输入（25+12+10+15）；其中 54 题来源足以支持有边界回放，8 题存在重要事实缺件。逐题表是 PREPARATION_RESULTS_62.csv/JSON，可读题目与目标历史是 READABLE_REPLAY_62.md。此结果不是 62/62 可正确作答或真实学生在线数据完备。

原 a_reuse62 和 canonical 未变；九个作者批准的跨会话设置已由 20 个原操作重建、关闭重开并复制 54 个模式初态。9 次本地只读诊断：4 AVAILABLE、3 AMBIGUOUS、2 无匹配。全部保留，详见 MEMORY_SUMMARY.md。

来源来自原 Moodle/Echo/features 安全表与系统指标代码。旧 reference-derived 页面快照未进入新生成输入；R0 使用共享 624 块语料。三组 S0/S1 实测保持当前页相等并正确添加相关非当前域；四次 R0 检索为三次 SUPPORTED、一次 NO_RESULT。12 项回归加 5 项无日期快照规划检查通过。FINAL 和请求点时间修复沿用旧版，新例外不放开权限或日程校验。

本轮 Provider/P3 LLM/candidate/FINAL/Judge 均为 0，人评仍空白。六模式薄脚本默认 preflight。正式生成仍需一次外发范围、模型、预算和预声明题目处理决定，命令见 COMMANDS.md。事实缺件集中在 assessment 定义、真实日程/待办、反思/反馈或提交回执、编号前文、当前周任务，详见 REMAINING_DECISIONS.md；不要求为其他题补无关生产元数据。

human/ 复用原空白表；evaluation_reference/ 只供人评参考重新确认，运行器不读取它。此为已暴露 62 题的受控历史回放/探索性评价，非新独立 TEST。ZIP 不含私有数据库、完整课程库、模型或真实身份映射；完整本地运行依赖本项目和原本地来源，包不是独立部署包。
''')
    for folder,names in {'human':['BLANK_RATINGS_2976.csv','COMMON_APPLICABILITY_496.csv','rubric.json'],
        'evaluation_reference':['COMMON_REFERENCE_62.json','READABLE_COMMON_REFERENCE_62.md']}.items():
        for n in names:
            p=HERE/folder/n;p.parent.mkdir(exist_ok=True)
            if not p.exists():shutil.copyfile(OLD/folder/n,p)
            assert p.read_bytes()==(OLD/folder/n).read_bytes()
    workbook=next((OLD/'outputs').rglob('REUSED62_BLANK_HUMAN_RATINGS.xlsx'))
    out=HERE/'human/REUSED62_BLANK_HUMAN_RATINGS.xlsx'
    if not out.exists():shutil.copyfile(workbook,out)
    assert out.read_bytes()==workbook.read_bytes()
    (HERE/'evaluation_reference/READ_FIRST.md').write_text('# 评价专用，待人工重新确认\n\n原参考原字节保留，不是新 runtime Evidence。会话、来源层级或观察窗口变化后，对原 required propositions/预期事实/适用性需重新确认。不会据此给生成器答案、强制 P3 或自动填人评。不要把同目录参考交给运行器。\n')
    for n,fields in [('BLANK_RATINGS_2976.csv',['response_id','score','rationale','rater','signature']),('COMMON_APPLICABILITY_496.csv',['applicable','reason','reviewer','signature'])]:
        rr=list(csv.DictReader((HERE/'human'/n).open(encoding='utf-8-sig')))
        assert all(not r[k] for r in rr for k in fields)
    write(HERE/'HUMAN_BLANK_VERIFICATION.json',dict(rating_rows=2976,applicability_rows=496,all_human_fields_blank=True,
        reference_status='PENDING_RECONFIRMATION',workbook_reused_byte_identical=True,workbook=file_id(out)))
    print('Readable 62, source/gate map, Memory summary, unchanged blank human materials and commands written.')

if __name__=='__main__':main()
