# Learning Analytics Dashboard Assistant · LAD

学习分析仪表盘助手：使用作者确认的 Supervisor Streamlit 界面，匿名浏览已授权学习数据，回放真实研究回答，执行最新论文的原核心，并可使用访客自己的 key 实时问答。界面接入与验证：2026-10-11–12。

[界面与最新核心接入](docs/SUPERVISOR_UI_INTEGRATION.md) · [代码与研究材料地图](docs/PROJECT_MAP.md) · [来源及变换](docs/RECOVERY.md) · [架构](docs/ARCHITECTURE_G0_R1.md) · [研究入口](research/README.md) · [许可说明](docs/LICENSING_G0_R1.md)

![实际 Supervisor Resources 界面，2026-10-11](docs/screenshots/supervisor-resources.jpg)

![实际 Supervisor 有向 Debate 网络，2026-10-11](docs/screenshots/supervisor-debate.jpg)

这些截图来自本轮实际本地浏览器。Community Cloud登录与GitHub OAuth已完成；2026-10-12恢复部署表单时出现`Received no response from server / 1ST`，刷新后浏览器控制未能获得可操作的页面，尚没有经过验证的云应用地址。需在已连接的Streamlit账号中提交部署：本仓库、`main`、`app.py`、Python `3.13`，不配置作者key。原GitHub Pages只是历史静态导览。

## 安装和启动

使用 **Python 3.13**；本轮实测版本为3.13.0。默认安装无需模型下载或API key。

```bash
git clone https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant.git
cd learning-analytics-dashboard-assistant
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -m streamlit run app.py --browser.gatherUsageStats=false
```

Windows激活：`.venv\Scripts\activate`。从项目根目录启动，打开终端给出的localhost地址。完整锁定环境见`requirements-lock.txt`。Dockerfile使用Python3.13；Docker构建未在本轮实测。

## 六页和三种profile

保留作者指定的 Introduction / Overview、Resources、Lecture、Debate、Reflection、Next Steps 六页、原图表和聊天弹窗。侧栏的匿名学习者、观察周和可选视频条目绑定到真实 Evidence；回放使用单独标明的历史任务。Overview不新增第五域事件。`Total_chars`是字符编辑量；视频源为累计观看快照，无法按观看发生周筛选。unknown保持unknown；活动记录不证明理解或学习效果。

| Profile | 实际行为 | 资源及边界 |
|---|---|---|
| REPLAY | 读取41任务×6模式的246个保存回答，179个不同回答文本 | 无key；保留历史身份与回答hash，不生成新问题答案 |
| COMPONENTS | 原Evidence、单需求门控R0、完整M1、typed Planner输入与检查 | 无key；需求来自访客显式勾选，不冒称P3；Memory可选择LEXICAL或已配置的HYBRID；没有LLM候选时不编造自然语言答案 |
| LIVE | 原FrozenP3三个专项角色→R0/完整M1→P1+i5 candidate及单次修复→FINAL与引用检查 | 访客自备key；Memory需求需要固定MPNet及可选依赖；缺失资源明确失败。本轮仅精确mock验证，未进行真实付费推理 |

点击页面下方“🤖 Chat with GenAI Assistant!”展开助手；REPLAY可回放保存回答，COMPONENTS可执行真实R0/Memory。Next Steps保留反思和可编辑计划草稿；这些不会自动写入Memory。你可明确保存或更正学习信息，并在LIVE获得检查通过的行动建议后选择采纳、报告完成。计划采纳与完成关系使用原生Memory记录和关系检查；完成状态是你的自报。切换研究模式会清除旧结果；图表与助手快照哈希不一致时页面明确停止，要求重新读取。

实时调用只在点击发送时发生。问题、当前可见聊天与启用的学习/课程/Memory内容会发送至OpenAI，费用由访客账号承担。key仅保留在该session内存，不写环境、日志、数据库或公共缓存。Gold与评分参考公开于独立评价区，禁止进入生成输入或RAG。

## 完整研究数据

小型运行数据已经在`data/`，clone即可回放。完整学习原文件发布副本、课程、历史/Memory、最终41、匿名评分、40锚点、S7/R7/D9及实际W9论文和补充材料通过本仓库新Release资产发布。[v0.2.0-g0-r1数据资产](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant/releases/download/v0.2.0-g0-r1/LAD_ASSISTANT_G0_R1_RESEARCH_DATA_2026-10-10.zip)已上传，并通过匿名公开下载、整包及逐成员哈希回读。大小67,328,343字节，17,704成员，SHA-256 `cb690dc0adbf361ea437a72e8beae319fdee3ca25b5311403cb497ffc7843612`。完整机器记录见`data/manifest.json`。

```bash
python scripts/download_research_data.py --destination research/released_data
```

下载脚本无需GitHub认证，校验SHA、CRC、每文件hash及安全路径，拒绝重复/穿越/符号链接/异常大小或覆盖不同的已有文件；重复运行不写相同文件。发布副本保留匿名关系、时间、原回答和评分；移除身份和认证信息，变换及前后hash有明确记录。原研究文件与论文未修改。

最终246身份与legacy62×9、DEV历史版本分开。八个未运行原题没有新增回答；183个继承slot的内部完整checkpoint及八次历史unknown completion仍缺少完整证据，不根据均值或后续回答补造。找回的真实RQ1 final128 CSV与冻结记录hash一致，位于`research/data/evaluation/rq1/`。

## 可选完整实时资源

```bash
python -m pip install -r requirements-live.txt
python scripts/download_model.py
export LAD_MPNET_PATH="$PWD/.local/models/e8c3b32edf5434bc2275fc9bab85f82640a19130"
python -m streamlit run app.py --browser.gatherUsageStats=false
```

MPNet身份为`sentence-transformers/all-mpnet-base-v2`，固定revision和三个原始文件hash由获取脚本校验。本轮已在独立干净环境安装可选依赖并实际运行原Hybrid检索、768维CPU编码、只读检查和完整mock链路；见`docs/SUPERVISOR_UI_INTEGRATION.md`。依赖清单为`requirements-live-lock.txt`。模型仅匿名下载，不使用缓存的作者token；若Xet传输失败，可按官方支持设置`HF_HUB_DISABLE_XET=1`后重试同一命令。默认Cloud不会自动安装可选依赖或下载该模型；未配置资源时明确失败。真实付费provider推理未实测，冻结P3模型的未来服务可用性由provider决定。

完整M1读取及其断网保护依赖全部在无provider凭据worker里导入；主UI/API进程保留正常网络调用。当前仪表盘的Memory从空库开始，按session和匿名学习者独立；只读研究seed仅用于对应历史任务，不能冒充当前学习者历史。聊天同时区分观察范围和视频条目。默认目录为系统临时目录；Community Cloud重启可能丢失。设置`LAD_SESSION_STORAGE=/path`可使用本地持久目录，但重开同一记忆还需保留同一session ID；没有登录、跨设备同步或永久云数据库。当前session按串行操作适配，不承诺跨进程并发写入事务。

## 实际验证与代码入口

```bash
python -m unittest discover -s tests -v
python scripts/security_scan.py --repo .
cd research
python -m unittest discover -s checks -p 'test_*.py' -v
python checks/check_snapshot.py
python checks/check_rq3.py
```

2026-10-12最终本地回归79项全部通过（166.113秒），包含16项Supervisor UI检查；保留的20项研究测试、7项RQ3契约及315文件快照哈希检查也全部通过。安全扫描2,149个拟发布文件零发现；测试前后24个相关代码/依赖文件及8份数据hash一致。检查逐值验证图表、当前学习者/周范围绑定、计划采纳/完成和session隔离；localhost HTTP mock在完整M1读取前后完成5个provider POST。无key CI在Ubuntu/Python3.13运行同一套回归，实际远端结果见GitHub Actions。可选原MPNet/Hybrid另有真实本地实测，付费推理0次。这些检查没有重跑研究回答、重评或修改统计。

```text
app.py                          # Supervisor六页公开入口
public_runtime/supervisor_ui.py # 原界面布局、匿名浏览、聊天与明确用户操作
public_runtime/dashboard_charts.py # 原图表与agraph有向网络
public_runtime/dashboard.py    # allowlisted实际学习者/周范围与source hash绑定
public_runtime/core.py          # session隔离、回放、显式provider调用
research/src/rq3_original/public_core_worker.py  # 完整原研究核心隔离worker
data/course/, data/replay/       # 实际课程和历史输入/回答/只读Memory seeds
data/dashboard/                 # 匿名学习源副本
research/data/evaluation/       # 独立Gold与参考，不进入应用生成
research/src/rq1_original/, rq2_original/, rq3_original/ # 恢复的研究代码
scripts/download_research_data.py, download_model.py, security_scan.py
tests/                          # 无key集成/正负/隔离测试
```

## 研究、许可和限制

246表示回答条件，不是246名学生、独立问题或不同文本。历史研究数值及方法限制保留在`research/`；新公开UI不能追称为论文评分时已经运行的界面。原版权与第三方NOTICE保留，本轮没有统一赋予MIT/CC0。公开授权不改第三方权利；文件没有明确复用许可时应联系权利人。见[本次许可补充](docs/LICENSING_G0_R1.md)。

完整实时模型质量、Docker构建、生产并发及永久托管不由本轮mock验证建立。真实可选MPNet安装与Hybrid执行已有本地实测；云部署与代码/数据发布分别报告。M1可回顾已采纳计划和自报完成关系；原P1保留`active_plan_adoption=NOT_ESTABLISHED`，不宣称可自动恢复任意旧计划的完整typed结构。RQ1学习排序与RQ2路由比较保留为独立研究入口；最终应用采用冻结P3，不把早期实验变体拼成新系统。

---

## English

This public LAD application uses the author-confirmed Supervisor interface with six views: Introduction / Overview, Resources, Lecture, Debate, Reflection and Next Steps. It preserves the original charts, directed interactive network and chat popover. Anonymous learner, observation window and optional lecture selection are bound to the real scoped Evidence. **REPLAY** reads 246 saved answer identities from 41 tasks and six modes, separately labelled from the displayed learner; **COMPONENTS** executes the original Evidence, single-gated R0, isolated complete M1 and typed planning checks without a model; **LIVE** connects the original three-role FrozenP3, source modules, P1/i5 candidate/repair and FINAL/citation checks using the visitor's key. S0/S1 and genuine clarification bypass P3.

Use Python3.13 and the installation commands above from the repository root. The included small real, anonymized datasets allow no-key startup; obtain the full research archive with `python scripts/download_research_data.py`. Download identity and public availability are recorded in `data/manifest.json`. The downloader validates archive and member hashes and refuses unsafe paths or changes to existing user files.

API keys, chat histories and writable Memory are session-specific. Dashboard Memory starts empty for each visitor and learner. A checked model plan is only a proposal until explicit adoption; completion is an explicit user self-report linked to the native accepted action. Reflections and editable goal drafts do not silently become Memory. Full M1 is imported only in a credential-free child process; evaluation Gold never enters generation or retrieval. Optional Hybrid Memory requires the pinned MPNet resource, which was installed and actually exercised locally in this update; missing resources cause an explicit error. Community Cloud storage is temporary and the default install omits optional model dependencies. The live integration was tested with exact request/response and localhost HTTP mocks, with no paid inference and no regenerated research answers or ratings. RQ1/RQ2 experimental models remain independent research entrypoints rather than being added to the frozen final P3 pipeline. The original P1 projector does not automatically reconstruct arbitrary adopted text plans into its full typed active-plan structure.

The original files, frozen results, notices and licensing boundaries are preserved. Publication copies record identity/path/authentication transformations. Latest W9 manuscript and supplement, ratings, anchors, analyses and separate historical datasets are included in the Release archive. Missing historical execution checkpoints remain unknown. The public adaptation does not establish real-student learning outcomes, production scale or ownership beyond documented contributions.

The final local update passed 79 application tests (including 16 Supervisor UI checks), 20 preserved research tests, seven RQ3 contracts and 315 snapshot hashes. The publication scan found no issues in 2,149 candidate files. Tests left all 24 tracked runtime/dependency identities and eight dashboard input hashes unchanged. Remote CI results are available under GitHub Actions; no verified Community Cloud URL is currently available.
