"""Write review-facing status and source-bound instructions from actual receipts."""
from pathlib import Path
from collections import Counter
import csv
import json
import subprocess
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
from build_materials import write,digest,START_HEAD

def main():
    with (HERE/'COVERAGE_INPUT_MAP_62.csv').open(encoding='utf-8-sig') as f:coverage=list(csv.DictReader(f))
    with (HERE/'SOURCE_IDENTITY_MAP.csv').open(encoding='utf-8-sig') as f:identities=list(csv.DictReader(f))
    counts=Counter(g for r in coverage for g in r['specific_gaps'].split(';'))
    inventory=json.loads((HERE/'sources/ACTUAL_SOURCE_INVENTORY.json').read_text())
    readme='''# A任务：复用原62题的本地审阅交付

本包落实本轮62题范围，替代25-only与新增B安排。完整恢复25＋12＋10＋15，无删题，无自动补题。
状态：`REUSED62_MATERIALS_PREPARED_WITH_REAL_SOURCE_BLOCKERS`。ZIP名称中的 EVALUATION_READY 按用户指定使用，不表示已获生成或评分授权。

**可读取回放题：62/62；完整真实来源绑定、可直接六模式生成：0/62。计划372条件；本轮新答案、Provider、P3 LLM、Judge、人评分数均为0。**

先读 `READABLE_REPLAY_62.md`。`SOURCE_IDENTITY_MAP.csv` 对应原62行号、原25 CSV行号及身份哈希。
`COVERAGE_INPUT_MAP_62.csv` 分开记录已有任务需求、文件存在、旧路由、旧模块执行与返回、本轮 NOT_RUN 和缺件。
`INPUT_DIFFERENCES_62.json` 逐题保存原/新历史及旧9例跨会话移动。不能根据 P3 触发与否或旧回答质量删题。

`evaluation_reference/READABLE_COMMON_REFERENCE_62.md` 和 `COMMON_REFERENCE_62.json` 是独立共同参照，沿用旧来源版本并保留本轮人工确认空白。
`human/BLANK_RATINGS_2976.csv` 是62×6×8的空白评分；`COMMON_APPLICABILITY_496.csv` 是62×8共同适用性空表。
Excel文件位于 `outputs/01a07cbd-de18-7632-90a8-6cf69fda116a/REUSED62_BLANK_HUMAN_RATINGS.xlsx`，三张工作表已渲染核验。
评分表保留模式名以便准备，尚非盲评包。新回答冻结后才填写response_id并制作盲评映射。不得使用旧Judge或旧人评。

`originals/` 保留原文件，其中含 Gold 与旧目标答案字段，仅用于溯源。运行器只读 `runtime/TASKS_62.jsonl` 的白名单字段，不读 originals、historical 或评价参考。
Raw输入表、全部课程文档、身份映射、密钥、模型、数据库和旧执行日志不在ZIP内。原本机来源未修改。实际624块普通R0语料已本地恢复；不按题选择课程片段。

当前缺件集中在来源与时间绑定，详见 `BLOCKERS_AND_COVERAGE.md`。无需先构建新数据集。
已有62题按同题修正条件重评。旧分数不是严格配对before/after，也不能证明系统改善或教学效果。

## 运行命令

在现有项目执行以下离线预检（不读密钥、不调用模型）：

```sh
cd /Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-i1-pilot-launch
python3 -B research_followups/rq3_rebuild/a_reuse62/run_batch.py --preflight
```

完整来源绑定、共同模型、价格与总预算一次批准后，整批命令如下。本轮未执行，示例审批文件尚不存在：

```sh
cd /Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-i1-pilot-launch
/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/.venv/bin/python -B research_followups/rq3_rebuild/a_reuse62/run_batch.py --execute --approval /Users/liuming/Downloads/RQ3_REUSED_62_EXECUTION_APPROVAL.json --output research_followups/rq3_rebuild/a_reuse62/live/reused62_run01
```

审批须绑定CONFIG_PROPOSED、TASKS_62、SOURCE_BINDINGS、代码哈希、实际Git HEAD与输出目录；模板在runtime/。
默认候选/FINAL方案继承 `gpt-4o-mini-2024-07-18`、temperature=0、每次2048输出token。它尚待确认，不宣称模型现时可用。
P3保留原冻结角色配置。最多682初始调用槽位，含一次结构重试最多1364物理调用。美元价格和总预算保持null，不使用未经更新的旧价格。
运行器按全部62题检查来源；缺件不悄悄缩减分母。重复启动必须使用原批准目录和 `--resume`；成功终态按完整请求哈希复用，未知完成状态停止，不能重复调用。

## 代码与核验

`METHOD.md` 说明六模式、历史、应用计划保管和评价边界。`SOURCE_BINDING_FORMAT.md` 给出真实CSV、R0与只读Memory绑定格式。
`TEST_REPORT.json`、`TEST_OUTPUT.txt`、`PRECHECK_62.json` 为实际离线记录。`GIT_RECEIPT.json`、`CODE_CHANGES.patch` 与 `PACKAGE_MANIFEST.json` 绑定代码和交付物。
代码使用现有项目的E1/R0/M1/P1/I5和冻结P3依赖；ZIP提供本次代码及所需已有代码快照和依赖哈希，不是包含模型和私有数据的独立安装包。
'''
    write('START_HERE.md',readme)
    lines=['# 具体缺件与覆盖边界\n\n62题和原25身份已完整恢复。下表是准备缺件，不是模型失败结果。\n',
        '| 缺件 | 受影响题数 |\n|---|---:|\n']
    lines += ['| '+k+' | '+str(v)+' |\n' for k,v in counts.items()]
    lines += ['''
当前 learner_id 来自原62，Moodle有313条同ID记录、Echo有9条、Features有1条。文件与同ID行存在不能给缺失的观察时间、课程日历、来源覆盖或外发授权赋值。
Moodle包含事件Time/Week及不同含义的Content_week；材料周不得当作观看周。Echo没有观看时间，缺观察窗口和稳定录制ID绑定。Features是无时间列累计值，不可当作周事件。Reflection的activities.pkl仅核验哈希，未反序列化，仍需要可信CSV导出。网络数据有week，需要课程日历和覆盖。逐题来源域及具体缺件见覆盖CSV。

原25 CSV没有会话ID、时间戳或角色间因果关联证明。U020与U022在canonical中无历史且有指代；完整保留，不把CSV邻接助手答案擅自补作历史。其余明确缺失或无关控制同样保留。

旧62保存的需求标签和原审阅状态属于历史证据，不是本轮新Gold。旧Full中RAG 41未激活、9 NO_RESULT、9 SUPPORTED、3 LIMITED_EVIDENCE；Memory 43未激活、17 NO_MATCH、2 AVAILABLE。这些数来自已保存逐题结果，仅用于接线核查。返回的具体ID与旧独立参考未返回ID均列出；重叠不是语义充分性。全部本轮P3及返回为NOT_RUN。

9例旧跨会话移动：U026、U027、U029、U031、U033、U034、U035、U036、U037。原62的合法可见历史恢复为同会话共同输入，不自动写成持久Memory。旧预置清单保存在historical/，供核对其过期、更正、歧义、无关和缺失控制，未直接用作新的M1输入。62题完整可读不等于原来的人为会话边界得到认证。

实际发现的能力覆盖限制：canonical主要提供同会话指代和已有计划上下文，未独立建立持久跨会话时间、用户采纳及撤销状态。建议作者如确需测该能力，可批准最多2个现有题的边界版本，例如一个更正/过期对照、一个无关/缺失对照，并给出原先来源时间与会话证据。此建议不新增题，不代替62题，不作为本次数据交付前置条件。没有证据支持再指定一套固定数量的新题。

普通检索遗漏、合理NO_MATCH、路由关闭及一般回答质量不作为删题或额外修复的门槛。本轮不评价修复收益。
''']
    write('BLOCKERS_AND_COVERAGE.md',''.join(lines))
    write('FIX_STATUS.md','''# 实际修复与未验证范围

起点为I6提交ea33ee9；没有假设I7/H5已完成。H4的已完成报告仅用于定位端点/请求事实接线问题，H4任务与人评未混入62题。

| 接口 | 本轮实际处理 | 核验边界 |
|---|---|---|
| FINAL改写内部计划 | 新FINAL wire只允许answer/cited_evidence_ids；应用保存已验计划和哈希 | 手写结构fixture通过，真实新答案尚未生成，语义忠实度待人工 |
| 引用与请求/计划角色 | source IDs白名单；current-request和计划不是事实来源 | 非法ID/plan_fields注入均拒绝 |
| 普通建议被日历限制 | 暴露语法识别明确“what should I do next/how can I improve”等；复用I5 ordinary schema | 无case_id/Gold查表；未知/矛盾语义保留未知 |
| 完整周端点 | opt-in ReplayService接受显式完整窗口，as_of不改动 | 原service默认行为不变；未完成窗口拒绝 |
| 当前query事实有效性 | verbatim current-request按as_of时点；无虚构到期日 | scope/version/access/tamper/future/resource约束保留 |
| E1与page-only | 同scope当前页事实完整保留，非当前页经E1选择 | Overview原有跨页内容保留；真实源未绑定 |
| P3后R0 | 复用upstream_authorised单门控与原阈值 | 无新真实P3或逐题RAG调用；本地已有624块语料可恢复 |
| Memory初态 | 原15组可见历史保持同会话；默认无虚构持久预置 | 实际native空库关闭/复制/重开测试通过；原非空M1恢复需要可追溯先前来源 |
| 人评 | 8项共同任务适用性＋空白评分 | 无代填适用性/评分/理由/签名 |

源绑定、实际路由、回答、人評与统计尚未完成；不能把此表当新实验结果。
''')
    write('SOURCE_BINDING_FORMAT.md','''# 运行绑定格式

`runtime/SOURCE_BINDINGS.json` 已填原62 learner IDs、明确的同会话历史策略及本地普通624块R0导出身份。未知的scope、as_of、日历、权限和语料适用区间保持null。不要以脚本构造的默认日期代替来源。

snapshot对象结构：version为来源快照版本；origin为LIVE；tables按moodle、echo、gdocs、reply_network、view_network等实际来源命名。每个table为 `{path, sha256, spec}`，path指可信CSV，spec使用已有SourceSpec字段：columns、learner_column、course_column或single_course/course_binding_evidence、observation、time_column或week_column、calendar_version、timestamp_timezone、item_column、event_id_column、coverage、metric_semantics。声明必须来自现有来源/作者，不从Gold反造。路径、SHA和表头由实际loader核验。

roster是 `{learner_id: [course_id]}`。calendars是 `{course_id: {version, timezone, weeks: {week_number: [start_inclusive, end_exclusive]}}}`。每题scope使用已有Scope：learner_id、course_id、snapshot、start、end、timezone、calendar_version和需要时的lecture_item_id。as_of为确证完整窗口已观察后的回顾性时间。相对本周等仍须与原题/原时点和日历一致；不满足即列缺件。

rag为 `{path, sha256, corpus_sha256, version, validity_interval, source_permission_ref}`。path指普通整库JSONL，每行是CourseChunk字段。当前624块文件在本机local_private，未收进审阅ZIP。需要恢复时运行 `python3 -B research_followups/rq3_rebuild/a_reuse62/prepare_corpus.py`；已有相同导出直接复用。R0仍检查课程、版本、corpus hash、权限、原阈值与空答案边界。

默认每题memory=null表示canonical未给先前session，不表示从Memory来源组删除该题。若另行批准有证据的跨会话派生条件，memory必须绑定 `source_permission_ref`、`databases: {course_id: {path,sha256}}`、`graph: {path,sha256}`、`source_events: {path,sha256}`，且在INPUT_DIFFERENCES中记录会话语义变更。数据库须来自可追溯原先来源，经native writer预置后关闭；运行器逐模式复制并只读重开。graph/source_events使用M1原生协议，保留版本、权限、角色、时间、来源跨度、更正及撤销，不把旧助手建议写成学生承诺。不接收旧预生成payload或从旧目标答案反造的历史。

所有数据恢复后先做--preflight；其实际source阶段失败逐题保留，全部62绑定完成后才能一次批准整批模型/预算。评级适用性保存在human/共同表，不属于运行绑定，不传给生成器。
''')
    write('SCOPE_REPLACEMENT.json',dict(status='ACTIVE_A_SCOPE_REUSED62',supersedes=['25_ONLY','NEW_B_DATASET_BUILD'],
        original_task_left_idle=True,new_project_created=False,new_questions_added=0,provider_authorized=False,
        entry_git_head=START_HEAD,source_policy='CANONICAL_QUERY_AND_HISTORY_WITH_EXPLICIT_PAGE_LABEL_PROJECTION'))
    print(json.dumps(dict(reports_written=5,blocker_counts=dict(counts)),ensure_ascii=False))

if __name__=='__main__':main()
