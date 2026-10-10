"""Render the integrated task/reference sidecar for human review; never score."""
from v2_common import *


def run():
    tasks = lines(HERE / 'runtime_tasks.jsonl')
    refs = lines(HERE / 'evaluation_reference.jsonl')
    ready = set(read(HERE / 'RUN_MANIFEST.json')['task_ids'])
    draft = {r['task_id']: r for r in read(HERE / 'applicability.json')['items']}
    language = {r['task_id']: r for r in read(HERE / 'LANGUAGE_ALIGNMENT.json')['pairs']}
    changes = read(HERE / 'QUERY_CHANGES.json')['changes']
    tests = read(HERE / 'audit/R1_TESTS.json')
    locators = read(HERE / 'audit/SOURCE_LOCATIONS.json')
    body = ['# R1逐题问题与独立评价参考', '',
        '本文件是评价sidecar，不进入P3、检索排名或生成输入。五份回传按原声明归档为待确认参考，正式纳入、适用性、署名及评分未代填。', '',
        '49题名册保留；41个来源可准备候选为17个原题受控回放与新24条件（12个family）。8个缺件原题保留。', '',
        '原问题用JSON字符串展示，末尾空格保留在引号内；runtime_tasks和original25_roster保留原25逐字文本。事实池不是要求逐项复述的唯一标准答案。', '']
    for index, (t, r) in enumerate(zip(tasks, refs), 1):
        tid = t['task_id']
        body += [f'## {index:02} · {tid}', '',
            f"页面：{t['page']}；来源可准备：{'是，正式纳入待定' if tid in ready else '否，缺件保留'}。",
            f"Family/条件（仅评价侧）：{r.get('family_id') or '原题受控回放'} / {r.get('condition') or '—'}。", '',
            '运行问题（精确字符串）：', '', '```json', json.dumps(t['query'], ensure_ascii=False), '```', '']
        if tid in language:
            body += ['保留中文草稿：' + language[tid]['chinese_query'], '']
        body += ['最低回答要求：', '']
        minimum = r.get('minimum_answer_requirements')
        if not minimum:
            minimum = [f['fact'] for f in r.get('required_for_minimal_answer', r['required_facts'])]
        body += ['- ' + s for s in minimum] + ['', '来源事实池（按所问选择相关事实，不要求全量复述）：', '']
        unique = set()
        for label, facts in [('事实池', r['required_facts']), ('可选补充', r.get('optional_support', []))]:
            for fact in facts:
                key = sha(fact)
                if key in unique:
                    continue
                unique.add(key)
                body += [f"**{label}：** {fact['fact']}", '']
                for e in fact['evidence']:
                    if e['kind'] == 'STRUCTURED_SOURCE':
                        body += [f"- `{e['path']}#{e['json_pointer']}`：`{canonical(e['value'])}`"]
                    elif e['kind'] == 'HISTORY_SPAN':
                        body += [f"- `{e['path']}#{e['json_pointer']}` 字符[{e['char_start']},{e['char_end']})；{e['role']}；{e['session_id']} / {e['message_id']}。", '  引文：' + e['quote']]
                    else:
                        body += [f"- `{e['path']}` / `{e['chunk_id']}` 字符[{e['char_start']},{e['char_end']})；`{e['readable_path']}` 字符[{e['document_char_start']},{e['document_char_end']})。", '  引文：' + e['quote']]
                body += ['']
        body += ['合理替代：', '']
        body += ['- ' + s for s in (r['acceptable_alternatives'] or ['只要内容受来源支持且回应问题，可使用合理的不同措辞和组织方式；不要求逐字匹配。'])]
        body += ['', '未知与解释边界：', ''] + ['- ' + s for s in r['unknowns']] + ['']
        if r.get('feasibility_witness'):
            w = r['feasibility_witness']
            body += [f"预算例证：{w['budget_minutes']}分钟；一个可行序列为 {' → '.join(w['one_feasible_sequence'])}，估计{w['estimated_minutes']}分钟。这不是唯一方案；部分方案与其他满足约束的方案均可。", '']
        body += ['回传适用性（仅draft，true/false/null原样投影）：', '', '```json', canonical(draft[tid]['draft']), '```', '',
                 'Confirmed applicability、正式纳入、reviewer_id、signature、score与评分理由均未填写。', '']
    (HERE / 'TASK_REVIEW_PACK.md').write_text('\n'.join(body))
    diff = ['# 九项已授权运行英文修订', '', '每项先断言旧query精确匹配；原25不改。中文草稿保留。没有依据P3、检索命中或生成回答选择措辞。', '']
    for c in changes:
        diff += [f"## {c['change_id']} · {c['task_id']}", '', '修改前：', '', c['before'], '', '修改后：', '', c['applied_after'], '']
    (HERE / 'QUERY_DIFF.md').write_text('\n'.join(diff))
    (HERE / 'CHANGES.md').write_text('''# 本轮限定合入

| 项目 | 实际修订 | 保留的边界 |
|---|---|---|
| C01/C02 | 实查23个原参考为空，其中15个可准备；补齐这15题来源事实、逐题最低要求、可选支持与合理替代 | original-13/23已有事实原对象保留；8题缺件不补造；original-01一项主要观察即可 |
| C03/C04/C05/C07/C08 | 9个新query按任务书精确更改；同步更新英文映射、49条来源输入和294条模式输入 | E01/E03/P01/P03成对同query；R01-B为自然改写；原25、中文草稿、family及实质对照保留 |
| C06 | R03 A/B同时说明Ryan书目、课程改编指南和论文全文缺失；增补指南改编出处与内容定位 | B仍不能回答原文实施步骤；没有联网补全文 |
| C09 | P03 A/B在原定位之外添加指定手册chunk[317,464)及文本[12133,12280) | 普通课程库完全未改 |
| C10–C12 | 分清新24构造情境和原25受控复用；记清快照/历史收据/本轮核对范围；Lecture采用中性称谓 | echo ID、Panopto旧定义均保留；平台映射、采集权限和外发权限不推断认证 |
| C13 | 原25逐字保留，original-12保持条件式术语解释 | 未把strings认证为累计字符编辑量 |
| C14/人工状态 | 五份原件逐字节归档；draft/confirmed适用性分离；69个待定位置聚合为4组 | 不填署名、正式纳入、最终适用性、分数或评分理由 |

继承的v2_common.py、adapter.py、run_batch.py逐字节复制；保持运行schema和现有批准schema。数据版本另以ORIGINAL25_PLUS_REVIEW_R1明确标识，并进入manifest身份。没有修改模型、P3、生成Prompt、检索阈值、Memory或Planner，保留FINAL计划保管修复。

9个primary身份、27个P3请求缓存键、54个模式状态键和54个FINAL输入预览哈希改变；其余40题输入身份完全一致。所有预览重新由现有builder生成；没有复制路由或回答缓存。native初态及历史setup收据按V2字节保留，不因query改写重造。
''')
    decisions = read(HERE / 'AUTHOR_DECISIONS.json')
    pending = ['# 有限剩余作者决定', '', '本轮资料限定合入已获用户直接授权。以下附件建议仍未获批准，所有author_decision字段保持null。', '',
        '| 适用性组 | 待定位置 | 作者待决定内容 |', '|---|---:|---|']
    for g in decisions['applicability_groups']:
        pending += [f"| {g['group']} | {g['count']} | {g['attachment_suggestion']} |"]
    pending += ['', '具体任务ID见AUTHOR_DECISIONS.json。41候选的draft计数仍为208 true、51 false、69 null；全部confirmed map留空。同一任务六模式最终使用同一map；配对条件的真实任务差异可以不同，但要预先写明。', '',
        '此外尚待统一确认：', '',
        '- 正式纳入范围：49题保留、41题仅来源可准备；8题缺件另列。final_inclusion和final_sample_size未填。',
        '- 来源说明与未来外发：确认echo/Panopto层级关系及本轮引用范围。未来实际模型执行还需真实直接批准R1数据身份、外发范围和预算。',
        '- 后续人评设计：评分者安排、原17受控回放与新12个family的分层报告、主汇总及多重比较范围。本轮未找到可据以填入的正式决定记录，继承配置中的比较名称只作proposal。', '',
        '17个共享回放背景与24个配对条件不能当成41个独立学生。回传资料未提供本轮身份/独立性认证，不借旧署名补填。未来回答评分及评分理由由人类独立填写。']
    (HERE / 'DECISIONS_FOR_AUTHOR.md').write_text('\n'.join(pending) + '\n')
    (HERE / 'COMMANDS.md').write_text('''# R1批量命令

在本项目根目录或审阅ZIP解压后的根目录执行，使用本机已有兼容Python。以下为离线命令，不需密钥、不安装依赖。

```sh
python3 -B experiments/rq3_original25_plus_review_r1/run_batch.py --manifest experiments/rq3_original25_plus_review_r1/RUN_MANIFEST.json --preflight
python3 -B experiments/rq3_original25_plus_review_r1/run_batch.py --manifest experiments/rq3_original25_plus_review_r1/RUN_MANIFEST.json --prepare --output /private/tmp/rq3-review-r1-fresh-prepare
python3 -B experiments/rq3_original25_plus_review_r1/verify_review.py
```

输出目录必须全新。prepare为49题生成294条来源输入预览，8题标明缺件；不运行目标P3、检索/embedding、候选、FINAL或Judge。admitted_by_manifest仅指来源可准备队列，不是人类正式纳入。受控mock FINAL用于验证既有接口，不是目标回答。

集成脚本integrate_review.py是此次一次性资料修订的可审查实现，要求本机完整V2和已完成intake，并拒绝覆盖R1；不是未来日常运行命令。验证器--prepare仅用于此次初次构建，不应在已有R1上重复使用。

后续若获用户实际直接批准，继续用现有EXECUTION_APPROVAL_TEMPLATE.json的schema，绑定R1的实际preflight身份、正式任务范围、外发权限、模型价格和总预算。模板保持PENDING，不能作批准。下面仅为未来命令说明，本轮未执行且不得执行：

```sh
python3 -B experiments/rq3_original25_plus_review_r1/run_batch.py --manifest experiments/rq3_original25_plus_review_r1/RUN_MANIFEST.json --execute --approval /absolute/path/approved-r1.json --output /absolute/path/new-r1-run
```

保留ORIGINAL25_PLUS_EN_V2运行/批准schema以兼容原runner；RUN_MANIFEST.data_revision=ORIGINAL25_PLUS_REVIEW_R1和全量绑定哈希区分新数据。旧批准、旧route/response缓存不能匹配R1。当前没有模型调用授权，也没有resume来源。
''')
    (HERE / 'START_HERE.md').write_text(f'''# RQ3本轮来源复核合入 R1

此次在原项目新增版本experiments/rq3_original25_plus_review_r1，保留V1/V2及五份回传原字节。起点为121788692aab6b4d4c53238789fbc2ecbf207d38；实际终点见ZIP根目录GIT_LINEAGE.json。

先看[精简修订表](CHANGES.md)、[九项英文前后对照](QUERY_DIFF.md)与[49题阅读版](TASK_REVIEW_PACK.md)。机器资料为runtime_tasks.jsonl和独立的evaluation_reference.jsonl；[四组待决定适用性及有限余项](DECISIONS_FOR_AUTHOR.md)另列，applicability.json保留draft/confirmed两层。

C01按实查23空/15可准备空处理；original-13/23旧事实保留。原25逐字不变；新24保持12个family。41仅是来源可准备候选，正式纳入、最终map、署名及评分未填。五份原回传见received_review，按DRAFT_PENDING_CONFIRMATION归档。

本轮最终核验：{tests['tests']}项检查通过；保留{locators['old_required_locator_occurrences_retained']}个旧required_facts定位，核对{locators['unique_task_locators']}个任务内唯一定位。6个预算例证验证通过，允许合理替代方案。较早核验脚本问题及失败记录保存在audit，未通过项修正后再验证，没有更改数据来适配断言。

已重建49条来源输入和294条模式输入。9/27/54/54分别为变化的primary、P3缓存键、模式状态键和FINAL输入预览；40题未改身份。评价sidecar与模型输入分离。详见INPUT_IDENTITY_CHANGES.json及audit/PREPARATION_ISOLATION.json。

Provider、P3模型、目标检索、embedding、候选、FINAL、Judge和人类评分均为0；没有读取API密钥。本包只用于本地审阅；不代表外发、模型执行、独立人评或科学结果认证。

[批量命令](COMMANDS.md)使用现有runner。模型、Prompt、检索、Memory和Planner不改；native初态及历史setup收据直接保留。源范围见source_materials/README.md。上游任务书与其建议见task_spec，其批准示例不是本轮执行授权。
''')
    (HERE / 'task_spec/README.md').write_text('''# 上游任务书与输入清单

此目录保留附件原任务书、建议及上游清单；只执行用户本轮直接批准的限定资料修订。DECISIONS_FOR_AUTHOR和QUERY_EDIT_PROPOSALS在上游的原状态不改写。实际应用记录见上一级QUERY_CHANGES.json。

PACKET_MANIFEST描述原13成员任务包，SOURCE_PACKET_MANIFEST描述原72成员来源包；它们不是本次交付ZIP清单。来源包已逐成员核验并与本机V2核对，输入哈希和66个字节一致路径见audit/INTAKE.json。本次交付不重复嵌套上游大ZIP，不导入旧答案或评分；最终成员以ZIP根目录MANIFEST.json为准。
''')
    receipt = read(HERE / 'source_materials/original25/RAW_AGGREGATION_RECEIPT.json')
    e = receipt['sources']['metric_contract']
    path = Path(e['path'])
    assert sha(path.read_bytes()) == e['sha256'] and path.stat().st_size == e['bytes']
    write(HERE / 'audit/SOURCE_SCOPE_CHECK.json', dict(
        inherited_receipt_processing_utc=receipt['processing_utc'], inherited_feature_cross_checks=receipt['feature_cross_checks'],
        current_metric_implementation_byte_identity_verified=dict(path=str(path.relative_to(ROOT)), sha256=e['sha256'], bytes=e['bytes']),
        original_csv_opened_this_round=False, original_raw_reaggregation_this_round=False,
        consent_or_external_permission_certified=False, platform_mapping_confirmed=None,
        lecture_neutral_label='所附录播观看记录', echo_source_id_preserved=True, panopto_definition_preserved=True,
        docx_review_scope='Five returned files archived byte-for-byte; no new DOCX layout or independent human certification.'))


if __name__ == '__main__':
    offline()
    run()
