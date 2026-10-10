"""Generate human-readable review views from actual saved source files and sidecars."""
import json
from collections import Counter
from data_loader import ROOT,read_json,read_jsonl,context,page_observations


def pretty(x):return json.dumps(x,ensure_ascii=False,indent=2)


def main():
    roster=read_jsonl('original25_roster.jsonl');tasks={x['task_id']:x for x in read_jsonl('runtime_tasks.jsonl')}
    refs={x['task_id']:x for x in read_jsonl('evaluation_reference.jsonl')};design=read_json('family_design.json')['tasks']
    counts=read_json('audit/COUNTS.json');v=read_json('audit/VALIDATION.json')
    original=['# 导师原25题完整名册','',
      '原CSV 19,646 bytes，SHA-256 `6d91aa61b9a1011318dc1756747752d04c20c45cb4202dc4f06daa23580d3bc8`。50条消息中25条user和25条assistant。',
      '本文件仅展示目标问题；50条原消息和原CSV在legacy_only中原样隔离。原目标assistant答案不是Gold。相邻行不证明真实会话关系。',
      '页面计数：Overview 10 / Resources 3 / Lecture 3 / Debate 4 / Reflection 5。25题全部是EXPOSED_LEGACY_ANCHOR。身份、session和时间均UNKNOWN；没有将25题认作25位学生。','']
    for r in roster:
        original += [f"## {r['task_id']} · {r['page']}",'',f"CSV数据记录号：{r['source_record_number']}（不含表头）。尾部空白：{r['trailing_whitespace_characters']}字符。",'',
                     '```text',r['query'],'```','',
                     '需要补齐：'+r['missing_material'],'',
                     '可用材料：原问题、页面标签和共享归档课程库。课程库没有与该原问题对应的学生/学期绑定，不代表原实验条件。','']
        if refs[r['task_id']]['required_facts']:
            original += ['可供一般建议的来源：`handbook_the_core_elements_of_academic_reflective_writing_1`；仅提供通用反思结构依据。','']
    (ROOT/'ORIGINAL25_READABLE.md').write_text('\n'.join(original)+'\n')

    lines=['# 新功能任务逐题审阅','',
      '24个候选草稿，12个family各2个条件。状态均为AI_ASSISTED_DRAFT_PENDING_SOURCE_REVIEW。最终样本量、纳入、八项适用性及人工判断均未填写。',
      '这是评价者/作者视图，包含隐藏参考和完整历史，不能整体作为生成输入。运行输入仅见runtime_tasks.jsonl；普通来源见source_materials。',
      '新草稿采用中文提问与构造会话，课程原文为英文；原25保留原始英文。两层单独报告，不以混合均分掩盖语言与构造差异。所有新情境的日期是实验时钟，不代表2025课程在2026重新开课。','',
      '| family | 重点 | 条件差异 |', '|---|---|---|']
    for d in design[::2]:lines.append(f"| {d['family_id']} | {d['primary_capability']} | {d['changed_factor']} |")
    for d in design:
        t=tasks[d['task_id']];r=refs[t['task_id']];binding=context(t['task_id']);s=read_json(binding['page_state_path'])
        lines += ['',f"## {d['family_id']}-{d['condition']} · {d['primary_capability']}",'',
           f"运行ID：`{t['task_id']}`；当前页：{t['page']}；划分：DRAFT_UNASSIGNED。",'',
           '**问题**','',t['query'],'', '**配对因素**','',d['changed_factor'],'',
           '**实验范围与当前可见内容**','',
           f"学生：`{t['scope']['student_id']}`；课程实验ID：`{t['scope']['course_id']}`。活动窗口：[{t['scope']['window_start']}, {t['scope']['window_end']})。目标新会话时点：{t['query_time']}。",'',
           '当前可见历史：'+(pretty(t['visible_history']) if t['visible_history'] else '空；先前session不会直接提供给基线。'),'',
           '```json',pretty(page_observations(t['task_id'])),'```','',
           '**普通页面来源（含非当前页及原始范围外事件）**','',
           f"文件：[{binding['page_state_path']}]({binding['page_state_path']})。事件只计自身，不另计Overview。",'',
           '```json',pretty(s),'```','']
        if binding['history_path']:
            h=read_json(binding['history_path'])
            lines += ['**只读历史会话来源**','',
                      '这些对话是本次工具协助编写的构造话语，不是真实采集，不是被评估系统生成的目标答案。','',
                      f"来源：[{binding['history_path']}]({binding['history_path']})；操作映射：[{binding['memory_operations_path']}]({binding['memory_operations_path']})。",'']
            for sess in h['sessions']:
                lines += [f"会话 `{sess['session_id']}`：",'']
                for m in sess['messages']:lines += [f"- {m['timestamp']} · {m['role']}：{m['content']}"]
                lines+=['']
        else: lines+=['历史会话：此情境未预置跨会话记忆。','']
        lines += ['**评价参考（运行时不可见，待来源审核）**','',
            f"来源状态：`{r['source_availability_truth']}`；设计上的可回答性：`{r['answerability_design']}`；检索结果：`NOT_EXECUTED`。",'']
        for i,f in enumerate(r['required_facts'],1):
            lines += [f"{i}. {f['fact']}",'']
            for e in f['evidence']:
                if e['kind']=='COURSE_SPAN':
                    lines += [f"来源：[{e['readable_path']}]({e['readable_path']})；native chunk `{e['chunk_id']}`；片段内字符[{e['char_start']},{e['char_end']})；全文字符[{e['document_char_start']},{e['document_char_end']})。",'',
                              '> '+e['quote'],'']
                elif e['kind']=='HISTORY_SPAN':
                    lines += [f"来源：`{e['path']}` `{e['json_pointer']}`；角色{e['role']}；字符[{e['char_start']},{e['char_end']})。",'', '> '+e['quote'],'']
                else:lines += [f"来源：`{e['path']}` `{e['json_pointer']}`；值见上述实际页面文件。",'']
        lines += ['允许的替代做法：'+' '.join(r['acceptable_alternatives'] or ['可采用不同措辞；关键事实、范围和已知限制需一致。']),'',
                  '未知及限制：'+' '.join(r['unknowns']),'',
                  '配对观察：'+r['pair_behavior'],'']
        if r.get('feasibility_witness'):
            lines += ['一个可行性见证（只证明估计用时及依赖，不限定回答原文）：','',
                      '```json',pretty(r['feasibility_witness']),'```','']
        lines += ['人工来源核对：_____；自然性核对：_____；纳入决定：_____。',
                  '八项适用性/评分/理由/审核者/签名：全部空白，统一放在human_review目录。','']
    (ROOT/'TASKS_READABLE.md').write_text('\n'.join(lines).rstrip('\n')+'\n')

    overview=['# 24题快速总览','',
      '工具协助的未审核草稿。下表含评价侧事实，不能作为运行输入；逐字来源、当前页与历史全文见TASKS_READABLE.md。',
      '原25题完整名册及缺件另见ORIGINAL25_READABLE.md。','',
      '| 条件 | 当前页 | 实际问题 | 关键来源与边界 |', '|---|---|---|---|']
    for d in design:
        t=tasks[d['task_id']];r=refs[t['task_id']]
        fact=' '.join(x['fact'] for x in r['required_facts'])
        if r.get('feasibility_witness'):
            w=r['feasibility_witness'];fact+=f" 见证用时{w['estimated_minutes']}/{w['budget_minutes']}分钟；完成全部剩余目标需{w['remaining_goal_minutes']}分钟。"
        overview.append(f"| {d['family_id']}-{d['condition']} | {t['page']} | {t['query']} | {fact} 来源状态：{r['source_availability_truth']}。 |")
    (ROOT/'TASK_OVERVIEW.md').write_text('\n'.join(overview)+'\n')

    source_readme='''# 来源与字段说明

所有学生活动、页面状态与历史会话均为明确构造的实验情境，标为AI_ASSISTED_DRAFT_PENDING_SOURCE_REVIEW。没有复制真实学生行为记录，也没有从原CSV助手答案反造行为。课程材料则是已有普通语料的原文件与固定导出，不是为了答案新写的课程事实。

## 固定课程库

`course/corpus.jsonl`完整复制已有624条普通片段，SHA-256见course/manifest.json，所有任务共享同一库。六个原文件在course/raw，六份可读文本在course/*.txt。保留native chunk ID、原路径、原文件SHA-256和提取文本位置。提取文本区间使用Unicode字符、左闭右开；它不是原DOC/PDF的字节偏移。历史分块可能含重叠；不得把重复片段当独立证据。

文件包括课程手册、周页面、阅读清单、Moodle链接、dashboard参考入口和已有讲座元数据。元数据不是讲座全文，阅读清单/引文不是被引论文全文。归档课程材料的既有学期内容不改写为本次实验日期。材料在本次本地草稿中复用；没有新建真人授权、校方许可或向外部服务传输的许可声明。

## 页面数据

`catalog.json`用不含家族/条件含义的context ID绑定普通页面状态和历史文件。四个活动域为Resources/Lecture/Debate/Reflection。Overview是四域汇总视图，不生成额外事件。

每条event的event_id在该情境内唯一。student_id/course_id用于范围；occurred_at为带时区的实验时间。窗口是[start,end)，目标时点之后的记录也不允许进入当前状态。resource_view表示一次打开资源；recording_play仅表示一次播放；post_published表示发布；document_edit表示一次编辑。不同类型的次数是记录数，不是同质投入或学习质量，不合并成学生数量。

records为带更新时点的独立快照，例如讨论发布状态、个人草稿、学生自选步骤和完成清单。event覆盖COMPLETE仅指该实验事件流的完整覆盖；记录快照独立存在。E01的Debate事件覆盖特意设为UNKNOWN，两条件仍都有明确发布状态快照，不从事件空列表推断没有发布。

coverage.status=COMPLETE且范围内零事件才可计0。UNKNOWN时计数为null；文件存在且诚实记录覆盖未知，不是丢失研究文件。E03-B是这种观察来源不充分情境。数值0与null不可互换。无累计量被冒充为周级变化。学期状态、认知效果和因果关系未由这些记录推出。

## 历史与预置记忆

8份条件历史文件含20次session出现（11个配对共享的逻辑session槽位；M03同一逻辑槽位在两个条件中有不同话语）。它们不是20个独立学生/独立样本。必须按context隔离，不能跨条件合并同名session。每个Memory条件有2–4个有角色及时间的早期会话；目标在后续新session，当前visible_history为空。

26条PUT_VERSION操作逐条绑定原话、角色和字符区间。只有预声明替代才产生新版本；重放按源时间处理，M02-B更正12为24分钟，assistant的30分钟建议始终为未采纳建议。M03-B历史明确尚未确定，不伪造选题。valid_until=null是没有另设到期日，不保证无限有效；查询时仍受作用域、来源时点、替代版本和目标事项约束。

`data_loader.py`做可透明核对的字典重放，保存结果见audit/PRELOAD_REPLAY_VIEWS.json。它没有调用目标Memory、不做检索、不测试自动事实提取。先前assistant话语保持assistant角色；它们既不是学生承诺也不是ACTIVE_PLAN。页面中的一个plan包含多个step，所有step有相同parent_plan_id；不把每步生成为独立ACTIVE_PLAN。

## 可见性

`generator_input(task_id)`仅产生问题、页面、当前合法历史、当前页数据。先前会话与其他页只在其独立普通来源中，须由后续授权模式和实际路由决定读取。`shared_course_corpus()`没有task_id参数，不能按题返回参考片段。evaluation_reference、family_design、audit和human_review全部是sidecar；不能给P3、runtime top-k或生成器。原50消息隔离在legacy_only，不是runtime来源。
'''
    (ROOT/'source_materials/README.md').write_text(source_readme)
    start=f'''# 原25题＋新功能任务：本次实际完成

已交付原25题完整名册、50条原消息的原样隔离副本，以及24个有来源的新任务草稿，12个family各2个条件。最终样本量未冻结，人工审核没有代填。

请先读[24题快速总览](TASK_OVERVIEW.md)和[原25题及逐题缺件](ORIGINAL25_READABLE.md)，再逐题查看[完整可读草稿](TASKS_READABLE.md)。每题能看到问题、当前页、非当前页状态、历史会话、原文定位、未知项和允许替代方案。课程手册全文可直接读[source_materials/course/handbook.txt](source_materials/course/handbook.txt)。

数据严格分为runtime_tasks.jsonl、source_materials/、evaluation_reference.jsonl。family_design.json记录配对与暴露说明；human_review沿用H0八项标准及原空白评分模板，49个任务的来源审核、自然性、适用性、纳入、评分和签名全空。

已实际完成{v['checks']}项离线检查、{v['source_spans_checked']}处来源位置核验；6个规划条件均有预算和依赖验证。提供6个课程原文件、624个普通片段、24份页面状态、8份历史文件（20次session出现）、26条预置操作。Provider/P3/候选/FINAL/Judge/目标检索/目标Memory调用均为0。没有安装或搜索模型。

旧62已从新主evaluation方案中撤下，旧37不作为新题；本次没有启动任何旧批次，没有改写旧文件或已有系统修复。新文件仅位于experiments/rq3_original25_plus。起始HEAD是f3e12b21d162ab6beee8ed8aaa6224546d0779e5；最终提交和文件内容绑定见ZIP内GIT_LINEAGE.json。

原25的问题/页面已齐全，但原身份、session、时间和个人页面数据仍缺失；没有声称完整复现。R03-B的论文实施细节不在固定课程库，M03-B的个人选择从未提供，E03-B的Reflection覆盖未知，这些是明确设计边界。它们与尚未执行的检索失败分开记录。可执行检查通过不是最终来源充分性的人类认证。

最终只需核对[具体待确认项](AUTHOR_REVIEW_ITEMS.md)。本包停在数据草稿审阅，不包含新答案或分数，也不是独立held-out冻结。
'''
    (ROOT/'START_HERE.md').write_text(start)
    (ROOT/'AUTHOR_REVIEW_ITEMS.md').write_text('''# 需要作者核对的具体内容

1. 逐题核对TASKS_READABLE中24个问题的自然性和69处机器可回查的来源绑定（含原25的通用参照共71处）；尤其R01的词数等值解释、R02的同伴归属/直接引文组合、R03的引文入口边界。来源充分性的人类结论仍为空。
2. 确认明确构造的页面/会话/用时是否适合本研究；不需要补学校在线部署证明。本次实验学生与课程ID不是现实身份。
3. 原25若要复现原个体条件，需要该题对应的学生、session、原提问日期/窗口、原页面值/内容或数据采集契约；编号2和3、this/it等还缺指代。逐题清单见ORIGINAL25_READABLE。没有可靠映射时可保留问题并另行选择明确的受控背景，不把原助手答案当证据。本次未擅自构造这些原题背景。
4. 确认24草稿的最终纳入、语种和工作量。新题/历史为中文、归档课程为英文，原25保持英文；两层单独报告。每个family两个条件保持同一划分，24个条件不能算24个独立受试者。重复设计模式与课程源域已暴露，不认证为新文档泛化或独立人工编写。
5. 八项适用性在生成前按任务确认，对六模式一致。Multi-page Cohesiveness仍缺作者确认的观察方案：是跨页面多回答episode，还是批准单回答跨页整合的局部适配；本包不自动填true或NA。

若暂按49题和六模式计，是294个条件回答；两位评分者各294份，共588份；八项全适用时上限4704个单项评分。它是工作量算术，不是样本量充分性或统计功效结论。原25的历史缺件不撤销已经交付的新24草稿。

缺失论文实施细节、未提供的个人选题、观察覆盖未知都是预声明边界；不需要为了把它们变成正例而补造答案。后续实际P3漏触发、retrieval miss或模型回答失败应原样保留，不据此删题。
''')
    (ROOT/'INTEGRATION_NOTES.md').write_text('''# 数据加载与现有系统接线说明

本次只新增数据、只读加载器及离线检查脚本；生产模块、已有修复、原评分、预测、旧批次代码与结果均保留。没有调用目标模块来筛选新题。

数据可由data_loader.py实际读取：generator_input输出四字段当前页输入；page_observations可审阅范围过滤后的非当前页；shared_course_corpus始终返回完整624条普通语料；replay_preload输出逐条来源绑定的版本化预置视图。示例ID见family_design或TASKS_READABLE；这些函数不发送请求。

与原六模式runner之间还没有执行正式接线或生成：不要把自定义page_state结构冒充已经验收的生产DashboardData envelope，也不要把Python预置视图冒充native M1 SQLite数据库。未来接线须由数据加载/转换器使用普通来源、原许可范围和各模式初态，不导入评价sidecar，不增加生产重构。M1接线需要把PUT_VERSION映射到原生ADD/UPDATE记录并保持角色/版本、context隔离和只读初态；本包已提供全部来源话语和透明映射，但没有执行native writer、embedding或Memory检索。

旧a_reuse62_replay_v2来源回放与批次命令不适用于本数据清单；不会自动消费本目录或启动旧62。当前授权仅为草稿准备，旧批次未启动的请求已被本次直接指令取代。

核验命令（在本目录，用Python标准库，无网络）：

```sh
python -B validate_dataset.py
python -B data_loader.py <TASK_ID> --view current
python -B data_loader.py <TASK_ID> --view pages
python -B data_loader.py <TASK_ID> --view preload
```

validate_dataset会更新本目录audit验证视图。它不会改变来源、调用模型或填写人工项。审核ZIP中的MANIFEST绑定的是交付时文件字节；后续自行修改应另存版本并重建清单。
''')
    (ROOT/'COVERAGE_AND_EXPOSURE.md').write_text('''# 能力覆盖与已暴露材料

| 重点 | family | 条件数 | 具体观察 |
|---|---|---:|---|
| Evidence | E01–E03 | 6 | 非当前状态变化、跨scope扰动、零与覆盖未知 |
| RAG | R01–R03 | 6 | 课程特有词数约束的等义问法、两个段落的引用需求组合、引文与论文实施细节边界 |
| Memory | M01–M03 | 6 | 目标/偏好/预算联合、明确更新、需要查历史但选题尚未提供 |
| Planning | P01–P03 | 6 | 35/15分钟预算、先行步骤完成状态、课程＋历史＋跨页组合 |

primary只是设计重点，不是互斥路由标签。P03覆盖四类来源；M01也涉及普通行动建议，P02有非当前页进度。只声明预期行为，不声明Full应得更高分。

所有新任务先固定共享来源与构造情境，再形成问题、事实参照与检查。未使用P3输出、R0命中、候选/FINAL输出或任何旧评分决定保留。新题形成后做一次离线文本/ID重复检查，并在检查中替换了与H3 R01过近的通用反思题；R03最终不保留旧式论文样本量问法。详见audit/OVERLAP_REVIEW.json。

零字面重复不证明跨语言语义独立。课程文档、能力设计模式和系统均已暴露；新任务不认证为新文档泛化或独立人工TEST。未复制旧37的问法、编号计划、maths历史或旧DEV快照。新情境没有使用真实个体记录；原25仍单列EXPOSED_LEGACY_ANCHOR。

统计单元至少保留family依赖，两个条件不跨划分，当前全部DRAFT_UNASSIGNED。最终样本量/适用性/主指标/比较家族仍待作者确认；没有根据数据结果设置这些值。
''')
    print(json.dumps(dict(readable_originals=25,readable_new_tasks=24,task_document_bytes=(ROOT/'TASKS_READABLE.md').stat().st_size),ensure_ascii=False))


if __name__=='__main__':main()
