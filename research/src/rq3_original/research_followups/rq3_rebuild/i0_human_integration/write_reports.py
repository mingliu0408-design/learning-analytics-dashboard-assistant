"""Generate review prose/receipts from observed artifacts, never new ratings."""
from pathlib import Path
from hashlib import sha256
import ast
import json
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
START='a15155b687264f235980836912f2e351bf428c9c'
SOURCES=['13d4bf9842f748e52777dd056ab17c17d6de86a4','8b22f73aab1930c2850b0301ceffe785a7599138',
 '6cc4e456e051d26520440282c099e45bd06bb87b','945c99563d3220ef4b8b7eb9eac06570d6173336','c96c3b143d1d29c92d4a892e39fb2f5095dfe531']


def write(name,value):
    p=HERE/name;p.parent.mkdir(exist_ok=True,parents=True)
    p.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n' if not isinstance(value,str) else value.strip()+'\n')


def main():
    integrations=subprocess.check_output(['git','rev-list','--reverse',START+'..HEAD'],cwd=ROOT,text=True).splitlines()
    assert len(integrations)==5,'Run report generation before the one I0 commit'
    lineage=[];files=[]
    for source,picked in zip(SOURCES,integrations):
        rows=subprocess.check_output(['git','diff-tree','--no-commit-id','--name-status','-r',source],cwd=ROOT,text=True).splitlines()
        assert all(r.startswith('A\t') for r in rows)
        for row in rows:
            path=row.split('\t',1)[1]
            original=subprocess.check_output(['git','show',source+':'+path],cwd=ROOT)
            local=(ROOT/path).read_bytes();assert original==local
            files.append(dict(path=path,source_commit=source,integrated_commit=picked,
                              bytes=len(local),sha256=sha256(local).hexdigest()))
        lineage.append(dict(source_commit=source,cherry_pick_commit=picked,files=len(rows),exact_bytes='PASS'))
    write('receipts/SOURCE_INTEGRATION_LINEAGE.json',dict(starting_head=START,
        integrations=lineage,source_files_verified=len(files),E1_R0_already_ancestors=True,
        no_R2_or_H0_commit_integrated=True))
    write('SOURCE_INPUT_MANIFEST.json',dict(source_files=files,exclusions='Content referenced by commit/hash; no inherited corpus, ratings, models or databases exported.',
        extra_code_dependencies=[dict(path=str(p.relative_to(ROOT)),sha256=sha256(p.read_bytes()).hexdigest())
            for p in sorted((ROOT/'utils/c4_dashboard_scoped').glob('*.py'))]+[
            dict(path=rel,sha256=sha256((ROOT/rel).read_bytes()).hexdigest()) for rel in (
                'utils/c4_memory/c4_memory_store.py','utils/c4_memory/c4_memory_retriever.py',
                'utils/c4_memory/c4_memory_provider.py','utils/c4_memory/c4_memory_writer.py',
                'utils/c4_real_adapters.py','utils/c4_real_contracts.py','utils/course_material_retriever.py')]))
    suites={}
    for suite in ('i0','p1','m1','r1'):
        reports=[(p,json.loads(p.read_text())) for p in (HERE/'receipts').glob(suite+'_*/TEST_REPORT.json')]
        p,value=max(reports,key=lambda pair:pair[1]['ended'])
        assert value['success']
        suites[suite]=dict(passed=value['passed'],tests_run=value['tests_run'],failures=value['failures'],
                          errors=value['errors'],skipped=value['skipped'],report=str(p.relative_to(HERE)))
    e1=json.loads((HERE/'receipts/e1/FUNCTIONAL_ACCEPTANCE_RESULTS.json').read_text())
    assert e1['counts']['FAIL']==0
    suites['e1']=dict(passed=e1['counts']['PASS'],tests_run=e1['tests_run'],failures=0,errors=0,skipped=e1['skips'],
                     report='receipts/e1/FUNCTIONAL_ACCEPTANCE_RESULTS.json')
    smokes=[(p,json.loads(p.read_text())) for p in (HERE/'receipts').glob('native_smoke_*/NATIVE_SMOKE_RECEIPT.json')]
    smoke_path,smoke=max(smokes,key=lambda pair:pair[1]['ended']);assert smoke['status']=='PASS'
    # The final smoke must correspond to the exact final integration source bytes.
    for rel,h in smoke['i0_source_hashes'].items():assert sha256((ROOT/rel).read_bytes()).hexdigest()==h
    test_summary=dict(status='PASS',suites=suites,passed=sum(s['passed'] for s in suites.values()),
        final_suite_tests=sum(s['tests_run'] for s in suites.values()),failures=0,errors=0,skipped=0,
        native_smoke_runs=len(smokes),final_native_smoke=str(smoke_path.relative_to(HERE)),
        native_encoding_calls_per_smoke=[r.get('encoding_calls_during_retrieval') for _,r in smokes],
        old_failed_attempts_retained=True,generation_calls=0,judge_calls=0,human_scores=0)
    write('receipts/TEST_SUMMARY.json',test_summary)
    constants={}
    for n in ast.parse((ROOT/'utils/c4_real_adapters.py').read_text()).body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            if n.targets[0].id in ('GENERATOR_MODEL','GENERATOR_ENDPOINT','GENERATOR_MAX_OUTPUT_TOKENS'):
                constants[n.targets[0].id]=ast.literal_eval(n.value)
    route_path='evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p3_rag_memory_specialists_frozen_v1.json'
    route=json.loads((ROOT/route_path).read_text())
    write('GENERATION_CONFIGURATION_PROPOSAL.json',dict(status='PENDING_AUTHOR_APPROVAL',
        historical_generator_reference=dict(**constants,temperature=0,stream=False,
            evidence='utils/c4_real_adapters.py::_build_request_payload; reference only, no parameters enabled'),
        frozen_p3_reference=dict(path=route_path,sha256=sha256((ROOT/route_path).read_bytes()).hexdigest(),
            composition=route['composition_rule'],models={k:v['model_snapshot'] for k,v in route['components'].items()}),
        live_settings={k:'PENDING_AUTHOR_APPROVAL' for k in ['provider','model_snapshot','candidate_model_role',
            'temperature','max_output_tokens','repair_limit','route_invalid_output_repair_limit',
            'total_call_budget','total_token_or_cost_budget','future_use_policy','task_scope']},
        live_transport='NOT_IMPLEMENTED_IN_PREPARATION_PACKAGE',secrets_read=False,SDK_clients_constructed=0))
    write('START_HERE.md',f'''# RQ3-REBUILD-I0-HUMAN 审阅入口

状态：READY_FOR_HUMAN_RATED_DEV_PILOT_DECISIONS。此状态仅表示合成开发链路可供审阅和决定；真实来源绑定为 PARTIAL，网络传输关闭。

本任务将 E1 → RAG/M1 → 共同证据编译器 → 可选 P1 → 最终回答请求连成一条可运行、可检查的路径，并吸收原 E2 来源准备。新 RQ3 的回答质量仅由人工评价。本阶段没有生成回答、评分或创建 LLM Judge。

先读 I0_COMPLETION_REPORT.md、REAL_SOURCE_BINDING_AND_READINESS.md、M1_P1_ACTUAL_ENVELOPE_BRIDGE_REPORT.md、GENERATION_PILOT_READYNESS_AND_OPEN_DECISIONS.md。接口见 INTEGRATED_SIX_MODE_INTERFACE.md；逐事实定位见 FACT_TO_FINAL_REQUEST_TRACE.json。

最终本地测试 {test_summary['passed']}/{test_summary['final_suite_tests']}；另有两次串行、各一个合成请求的本地 MPNet smoke：初次连接检查与最终源码版本复核。每次只有一次检索编码调用，启动探针另见原生收据；不是两组实验或新的模型效果统计。

本 ZIP 是审阅包，不是独立部署包。新实现位于 implementation/utils/c4_rebuild；依赖完整的指定起始仓库及五次整合提交，继承代码只按 SOURCE_INPUT_MANIFEST.json 的提交/哈希引用。工作树内诊断命令：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B research_followups/rq3_rebuild/i0_human_integration/run_checks.py --suite i0
PYTHONDONTWRITEBYTECODE=1 python3 -B research_followups/rq3_rebuild/i0_human_integration/verify_acceptance.py
```

这些诊断会在 I0 目录写新收据；不要把它们当成冻结包的只读校验。仅校验 ZIP 可用包内独立 verify_review_zip.py。Git 最终 HEAD 在提交后生成的 GIT_COMMIT_RECEIPT.json 中。REVIEW_MANIFEST.json 不包含自身哈希，ZIP 哈希写在外部 sidecar。
''')
    write('I0_COMPLETION_REPORT.md',f'''# I0 完成报告

交付状态 READY_FOR_HUMAN_RATED_DEV_PILOT_DECISIONS；真实数据准入 PARTIAL。起始 HEAD `{START}`，五次 cherry-pick 后 HEAD `{integrations[-1]}`；最终任务提交由独立提交收据记录。

已按顺序整合 R1、M0、M1、P0、P1，{len(files)} 个新增来源文件逐字节匹配原提交；没有冲突或历史来源改写。新增工作只位于 i0_human_integration 与 utils/c4_rebuild。E1/R0 不重复应用，R2/H0 未完成源码未读取或整合。无默认工厂/UI 开关改动。

一条 ResearchService.prepare 路径实现六种临时语义配置。E1 的同一可信 Snapshot/Scope 同时供应可见页和按问题选出的跨页事实；R0 用原生单门控 scorer；M1 通过真实持久状态和关联读取接入；P1 保持原函数体、在局部依赖映射中加入可空原生元数据和来源受限规范化。没有整体复制系统或改写模块全局。

12 个 SYNTHETIC/EXPOSED-DEVELOPMENT 任务产生 72 份最终请求草案、21 份可准备的候选计划请求、12 个无响应无评分的共同人工证据壳。3 个候选分支需要信息，保留其具体原因。两个合成计划字段包经过实际 P1 检查后进入同一个最终请求 builder；它们不是模型回答。369 个 E1 原子事实指针、144 个课程/记忆保留断言和全部请求文件已回读核验。

最终测试：I0 {suites['i0']['passed']}、E1 84、R1 29、M1 42、P1 85，共 {test_summary['passed']}/{test_summary['final_suite_tests']} 通过，未跳过。M1 是关联检索测试模块，不冒称重跑其全部 76 项发布测试。R1 为原 29 项测试，包含本地 tokenizer，不做模型前向推理。原始失败尝试均保留：跨页测试句只命中 Lecture、未来政策测试无检索种子、测试错误复制 immutable Snapshot；构建器首次缺少 digest 导入，其次拒绝不匹配的 opaque 来源身份。修正均发生于 I0 自身测试/构建，未改继承来源或补 Gold。

本地 MPNet 的最终有哈希收据 smoke 通过；两次均串行持锁、CPU、离线，合计两个微型请求，每次一次实际检索编码。最初进程列表因 sandbox 被拒；未将其写成成功，资源协调依靠 R2 释放确认和共享锁。未修改运行环境或模型。

没有真实 Provider 路由/候选/最终回答调用，没有 LLM Judge、人工分数、统计推断、最终方法选择、部署、论文/旧结果修改。人工评分指南和统计设计仍由 H0/作者后续冻结。精确阻塞事项见 readiness 文件；普通未结构化建议可作为带未知状态的开发任务，不能称已验证自由文本约束或生成质量。
''')
    write('REAL_SOURCE_BINDING_AND_READINESS.md','''# 真实来源绑定与准备状态

原 E2 范围已在 I0 完成限定位置检查、模板和就绪检查器，不另开 E2。receipts/REAL_SOURCE_METADATA.json 是本次实际回读：8 个 known legacy 文件仍存在、哈希均与 E1 一致；7 个可读表头已核实。I0 当前工作树没有对应输入文件。存在不等于新用途授权；PRIVATE_DATA_NOTICE.md 的本地工作说明不替代新研究/生成准入或 participant consent。

| 来源 | 状态 | 已知事实与最低补件 |
|---|---|---|
| student_info.xlsx | PARTIAL | 已有 ID/AppName 等列；需要认证后的明确 learner ID、课程名册绑定和权限依据，不能从 AppName/文件名赋权。 |
| Moodle | PARTIAL | Time 与活动 Week、Content_week 分列，无 course ID。提供真实课程/时区/日历及单课程来源绑定、指标覆盖声明；无需重问已有列。 |
| Echo | PARTIAL | Class、Content_week、Video Views、Video View %、ID；无观看时间。周活动需要事件或有真实观察窗的导出、稳定 recording ID。允许另行声明累计快照的采集截至时间、窗口和指标含义；材料周不能替代观看周。 |
| reply/view network | PARTIAL | From/To/count/week；提供课程日历、授权和覆盖。输出同学习者计数，不导出对端姓名。 |
| features | PARTIAL | 无时间列的累计值，不能覆盖每周事件；只有独立且明确同窗快照才能另行绑定。 |
| Reflection activities.pkl | UNKNOWN | 原哈希一致；没有可信创建/安全反序列化依据。提供带原文件哈希、字段、观察时间和可信导出过程的 CSV；本次未 unpickle。字符量不代表反思内容或质量。 |
| cohort ts | PARTIAL | day/previousCohorts/currentCohort，无个人 ID；不进入同学习者事实链，当前试点不必为它补件。 |
| goals/reflections 原文 | UNKNOWN | 无标准 loader 的真实来源绑定。若任务需要，再提供许可、身份、来源跨度和时间的安全导出。 |
| RAG 课程材料 | PARTIAL | R0/R1 固定语料和实现按已完成提交引用；实际新课程/访问授权与版本/适用区间仍须绑定。旧 corpus 身份不等于新用途许可。 |
| 真实 Memory | UNKNOWN | 本次只使用明确的合成 pre-target 来源操作；真实跨会话读写需提供 opt-in、当前版本/撤销权威和按课程隔离的状态。 |

真实来源 READY 数为 0。不要因表头/哈希通过而标记真实生成已获授权。REAL_SOURCE_MANIFEST_TEMPLATE.json 保留 null；utils/c4_rebuild/sources.py 检查路径、哈希、格式、绑定、许可、窗口、日历、coverage 与安全导出声明。这个 checker 验证声明完整性，不认证声明签署者。raw 输入只放 ignored local_private，review ZIP 不包含数据行。

作者若只批准现有合成开发任务，以上真实数据补件不会阻塞该合成试点；真正采用真实学生来源前才是必要条件。
''')
    write('INTEGRATED_SIX_MODE_INTERFACE.md','''# 六模式共同接口

| 临时 ID | 当前页 | E1 跨页 | RAG | Memory | P1 |
|---|---|---|---|---|---|
| S0_PAGE_ONLY | 保留 | 关 | 关 | 关 | 关 |
| S1_CROSS_PAGE_EVIDENCE | 保留 | 按问题 | 关 | 关 | 关 |
| S2_EVIDENCE_RAG | 保留 | 按问题 | 门控 | 关 | 关 |
| S3_EVIDENCE_MEMORY | 保留 | 按问题 | 关 | 门控 | 关 |
| S4_EVIDENCE_PLANNING | 保留 | 按问题 | 关 | 关 | 门控 |
| S5_FULL | 保留 | 按问题 | 门控 | 门控 | 门控 |

不是 RQ2 候选名或冻结统计设计。工厂 `ResearchService(enabled=True, snapshot=..., router=..., retriever=..., memory=...)` 只做 preparation；execute 始终拒绝，无 live client/transport 参数。默认应用路径没有接入此工厂。

顺序：可信 scope/current-page → 原 CG → S2–S5 的原四字段 P3 输入 → E1 选取 → RAG → M1 → 实际 C4 compiler → 可选 P1 → provider-neutral 最终请求。S0/S1 遵守继承的 zero-P3 合同。P3 只接 current_query/current_page/dashboard_context/visible_conversation_history，不接已检索事实、purpose、身份或标签。缺路由不等于 YES；无效合同拒绝。冻结 P3 是 RAG Specialist + Memory Specialist + B4 Planning，包含真实 LLM 调用，不能把 MPNet 检查称作 P3 推理。

可选能力准入是 mode allows AND P3 bit AND access.allowed；SyntheticRouter 仅可用于 SYNTHETIC Snapshot。R0OnExplicitCorpus 仅替换构造器的语料注入，调用继承 scorer 的 upstream_authorised=True；不再过第二道 semantic veto，仍检查课程/版本/corpus hash。Retriever Protocol 可替换；R0 是临时开发基线，不是 R2 的最终结论。

M1 的 backend 注入可选择 hybrid+links 开发候选，也保留 lexical/unexpanded 诊断。purpose 是独立工程字段：来自明确可见控件或版本化 query grammar，未知就不读 Memory；P3 不输出 purpose。source IDs、fixture 名和 expected sidecars 不参与选择。

所有模式用同一 compiler，默认 12000 个确定性 evidence-token 单位和 50000 个完整请求单位，均为离线工程预算，非 Provider tokenizer 或已批准 token 上限。当前页必须保留；可选事实整体 budget-omitted，并在最终请求、trace 和筛选后的 Memory view 中一致，不能从原包络重新引入。Overview 引用四域一次；没有强制每个对比都出现信息增量。

Direct 与计划分支使用完全相同的 common runtime_input，包括原文、来源绑定、显式规范化与可见历史；P1 projection 只派生这些来源已含的信息，当前任务目标逐字来自 current query。Planning OFF 不调用 projection/checker/candidate。Direct 可以自然安排步骤。最终缓存身份包括完整最终/候选请求、learner/course/snapshot/版本/状态和 session，以及模型角色合同；读取到的 native state digest 单独加入。这里不部署结果缓存。

最终回答 schema 有 answer、cited_evidence_ids、plan_fields；结构化计划是单独 P1 schema。prepare_final_from_candidate 对已准备证据/候选输入做完整性核验，经过实际 P1 检查后再交给同一 final builder。机械字段复制一致不证明回答原文保真或教育质量。
''')
    write('M1_P1_ACTUAL_ENVELOPE_BRIDGE_REPORT.md','''# 实际 M1 包络到 P1 的桥接

实际消费 M1 发布文件 PLANNER_ENVELOPE_SYNTHETIC_FIXTURES.json 的全部 4 份保存输出；它们不是重新制作的理想 P1 JSON。ACTUAL_M1_SAVED_ENVELOPE_PROJECTIONS.json 同时保留原包络哈希、无 authority 投影和按原合成来源重建/关闭/重开的 authority 投影。7 个保存事实条目的原 native IDs 在重开状态中全部找到，原文字节不变。

| 字段 | 当前映射 | 保留的界限 |
|---|---|---|
| native_id/version/type/content | P1 fact ID、版本、类型和逐字原文 | 版本不是自动获准的新用途授权。 |
| learner/course/session/as_of | 显式 scope 和按课程 DB 绑定 | 单独保存包络不构造当前运行权威。 |
| source_ref span/hash/role | 校验实际 source event 哈希、身份、角色、原始字符跨度 | P1 model-visible span 只含所选子串，局部范围归一为 0..len；原偏移在 M1 ref 保留，不把整段未选择源文塞进模型。 |
| created_at/last_confirmed/enabled/current_version | 从原生只读 store 复核 | 保存包络本身没有的字段，authority 缺失时为 null/UNKNOWN。 |
| relevance_components | seed 保留原值；关联扩展为 null/NOT_SCORED_LINK_EXPANSION | 不以 0 伪装未计算分数。原 P1 strict shape 的差异由 I0 局部 schema 扩展表达。 |
| valid_to=null | 仅在固定 native store 文件哈希匹配且当前 authority 验证后映为 NO_DECLARED_EXPIRY | authority/policy 缺失为 UNKNOWN；无 2099 假日期。未来仍显式选择 RECONFIRM_FOR_SCHEDULE 或 WARN_SNAPSHOT_ONLY。 |
| USER GOAL | 原文目标，native ID 作来源 ID | 不从系统建议制造 learner goal/adoption。 |
| raw constraints | 原文保留；小语法支持明确整句分钟/quarter-hour/有限数字词 | 每项带 span/value/unit/uncertainty/supported syntax；否定、换单位、模糊日期、未列数字词仍 NOT_CHECKABLE。 |
| active_plan IDs/links | 原关系和 chosen/ambiguous 状态进入共同证据 | 无稳定 task ID 和完整 task binding 时 P1 typed active_plan 保持 null；plan edge 不证明 learner acceptance。 |
| completed/accepted IDs | 原生事实 ID 保留；仅合法 COMPLETION_OF_ACTION 边可绑定到明确接受动作的 native ID | completion row ID 本身不是 task ID；更正/撤销不继承过时完成边；完成不是掌握程度。 |

无 authority 的 4 份保存输入均未获 encoded admission。按原始合成状态提供 authority 后：3 份可准备普通建议（保留 UNSTRUCTURED_MEMORY 警告与 NOT_CHECKABLE），1 份原生计划歧义仍 NEEDS_INFORMATION。没有把它们说成完整机器可检查排程。

普通建议允许模型看有来源的原文，但原文约束验证仍 NOT_CHECKABLE；不是要求作者把学生语言改写成 JSON。显式排期需要时区、区间、可用窗口及必要的 typed constraints，未知即澄清。原 M1 案例的复杂 'twenty minutes ... after work on weekdays' 不被小提取器错误泛化成本次总预算。

新合成 'I have 15 minutes.' 经真实 M1 写入、关闭、重开、检索，进入实际 P1 检查：10 分钟合成估计通过 encoded checks、20 分钟被 BUDGET_EXCEEDED 拒绝。两种开放有效期未来政策各有实测分支；没有选定最终科学政策。

`+40%` 保证可通过编码字段检查，明确标为 semantic_support=NOT_CHECKED；这正是自动 checker 的覆盖缺口，须人工审阅。之后若增加模型提取器，需要单独版本、成本和授权，不属于本次已解决的一般 NLP 能力。
''')
    write('RUNTIME_COMPATIBILITY_MATRIX.md',f'''# 本次实际运行兼容性

| 路径 | 本次结果 | 范围 |
|---|---|---|
| Python 3.13.0 stdlib + SQLite / E1 / I0 | PASS | E1 84、I0 {suites['i0']['passed']}；无 UI server、模型或 Provider。 |
| 原生 M1 linked lexical | PASS | M1 42 项关联测试，以及 I0 写入/重开/clone/read。不是替代 hybrid 的语义效果声明。 |
| P1/P0 frozen functions | PASS | P1 原 85 项回归；I0 private FunctionType 注入后原函数体/模块 globals 不变。 |
| existing legacy .venv Python 3.13.5 / R1 | PASS | 29 项原测试；tokenizer-only，长输入测试提示 1409>512，未送入神经网络。 |
| 同一 .venv / 原 MPNet CPU | PASS | 两次串行微型接口 smoke，最终收据 {str(smoke_path.relative_to(HERE))}；每次一个目标检索 encode，768 维启动探针，offline，原模型哈希可核。 |
| Base Anaconda torch | NOT_RERUN | 继承 M1 记载 SIGSEGV；本次未诊断原因或修复共享环境。 |
| R2 候选 reranker | NOT_RUN_IN_I0 | 只协调资源；不读取 R2 活动工作树或采纳其未授权提交/选择。 |
| 冻结 P3 新输入执行 | NOT_RUN | 合同为三个 LLM 角色。测试全是明确 SyntheticRouter stubs，非真实 P3 准确率。 |
| Provider generation / SDK / LLM Judge | NOT_RUN_BY_SCOPE | 没有客户端构造、secret 读取、请求发送、评分或 Judge 路径。 |
| 真实学生数据 / UI部署 | NOT_RUN | 来源绑定未齐备，默认应用保持原状。 |

R2 在 2026-09-06 23:12:43 UTC 已结束模型使用，并明确回复可安排授权范围内的 I0 smoke。I0 再获取共享 advisory lock；ps 被 sandbox 拒绝的事实独立记录，不伪称进程扫描通过。原生环境没有安装、下载、修复或修改。
''')
    write('GENERATION_PILOT_READYNESS_AND_OPEN_DECISIONS.md','''# 小规模生成的真实剩余事项

机械状态 READY_FOR_HUMAN_RATED_DEV_PILOT_DECISIONS；不等于授权运行。完成本阶段不需要填 Gold、重写论文或评分。

**启动现有合成开发任务前只需决定/绑定以下项目：**

1. 直接批准要运行的任务/模式与 Provider、model snapshot、候选/最终模型角色、temperature、max tokens、总调用/token/费用上限，以及各角色有限 repair/停止政策。GENERATION_CONFIGURATION_PROPOSAL.json 从历史代码读取 gpt-4o-mini-2024-07-18、OpenAI Chat Completions、temperature=0、final max_tokens=512；这些只是参考，全部新设置 PENDING_AUTHOR_APPROVAL。
2. 在单独获准执行阶段绑定 disabled transport，并准备与同一四字段输入对应的冻结 P3 决策。P3 包含 RAG Specialist、Memory Specialist、B4 Planning 三个 LLM 角色；MPNet 通过不能替代它。不能用 synthetic stub 冒充最终试点 P3。相同任务各模式应复用同一已完成决策；缺失/无效组件保留，不回退或填补。
3. 若纳入未来排期，明确 RECONFIRM_FOR_SCHEDULE 或 WARN_SNAPSHOT_ONLY；为对应任务补齐实际用户时间窗/时区/必要的 typed facts，或先只批准普通建议任务。未解析语言仍原文 NOT_CHECKABLE，不要求用户改写为 JSON。开放有效期不保证未来可用。

12 任务×6 模式有 72 份最终请求草案；当前 21 份可准备候选计划请求、3 份需信息。按每任务冻结一次 P3 的上界估算为 36 个路由角色调用 + 72 个最终调用 + 至多 24 个候选调用 = 132 次，另计路由 invalid-output、候选 repair 和 final repair。按当前 21 个候选分支是 129 次基础上界；实际 CG/准入会减少调用。若重复跑每模式 P3，路由部分会膨胀至 144 次，不是已批准方案。这些是请求数核算，非费用或样本量批准。

**仅在改用真实学生来源时还需要：** authenticated learner/course roster、按新用途的权限证据、课程日历/时区与 coverage；Echo 活动观察窗/稳定 recording ID（或明确累计快照合同）；可信 Reflection 安全导出；真实 Memory opt-in/撤销/当前版本与 RAG 课程授权。已知表头无需再问；不需要 cohort 数据也能开展当前个人任务。

**人工评价启动前：** 由作者/H0 冻结新任务样本、rater availability、共同参考、适用性、主终点及统计方案；当前只交付无响应/无评分壳。它们不阻塞独立的授权合成生成准备，也没有被 I0 擅自定稿。

非阻塞事项：完整 GUI 部署、另一轮一般审计、重跑旧论文实验、选择 R2 最终胜者、通用自然语言提取器。真正存在的模块限制已明确；不得把这些扩大成开始任何小规模合成试点都必须解决的新研究问题。
''')
    write('receipts/BUILD_AND_LIMITATION_NOTES.json',dict(
        build_attempt_01='NameError: digest import missing; no Provider or state mutation outside synthetic temp dirs.',
        build_attempt_02='KeyError on opaque source course; constructor now binds all six modes to source target learner/course, never inferred from filename.',
        i0_test_failures='Retained in I0_TEST_ATTEMPT_01.txt and per-run TEST_OUTPUT.txt; final source suite passes.',
        initial_native_smoke_source_versions='Intermediate interface smoke before final trace/provenance changes; retained separately.',
        final_native_smoke='Exact final utils/c4_rebuild source hashes verified.',
        ps_inventory='Sandbox denied ps; not represented as success. Shared lock and R2 release used.',
        source_read_scope='Exact E1/E0 legacy locators and source documents; no active sibling contents.'))
    print(json.dumps(dict(source_files_verified=len(files),tests=test_summary['passed'],reports='WRITTEN',final_smoke=smoke['status'])))


if __name__=='__main__':main()
