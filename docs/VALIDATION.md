# 2026-10-10 公开演示验证

验证对象是本次新公开包装，不是原论文实验的重新执行。全部数据与课程材料为合成内容，模型接口仅使用 mock。

| 项目 | 实际记录 |
| --- | --- |
| 环境 | 独立 Python 3.12.14 虚拟环境；Streamlit 1.38.0、Pandas 2.2.3、Plotly 5.24.1、OpenAI SDK 1.109.1；完整版本见 `requirements-lock.txt` |
| 依赖一致性 | `python -m pip check` 通过 |
| 新演示测试 | `python -m unittest discover -s tests -v`，19/19 通过；禁 socket/DNS，不调用真实模型 |
| 覆盖 | 真实 R0 来源片段、SQLite/FTS5 写入与 reopen、来源/版本替代、学习者与课程隔离、中文目标/预算约束、P0 约束校验、最多一次纠错、JSON/引用 mock、Streamlit 空表单/问答/保存/访客隔离 |
| 原研究文件 | `python research/checks/check_snapshot.py` 校验 315 个文件，PASS；`research/` 保持公开源文件内容 |
| 原研究合成模块 | `python research/checks/check_rq3.py`，7/7 通过；包括作用域、模式门控、R0、持久化与规划/引用契约 |
| 实际浏览器 | 独立 Chrome 打开本机 Streamlit；仪表盘与离线30分钟计划成功；1 个图表、0 个 Streamlit exception、0 个页面脚本错误；截图见 `app-screenshot.png`、`assistant-screenshot.png` |
| 静态导览 | 五页、十个离线示例由 `scripts/build_preview.py` 实际生成，模型调用0；独立浏览器逐个点击检查；手机390px无横向溢出 |
| 发布边界 | 新包单独 Git 历史，研究来源已公开；本地数据库、虚拟环境、密钥、学生数据和课程原文排除；检查范围见 `PUBLICATION_CHECK.json` |

本机旧 Anaconda Python 3.13 的可选 readline 原生库曾崩溃。最终验证使用新的 Python 3.12 环境，没有修改原研究环境，也没有在正式测试中绕过原生模块。

未验证：真实在线模型回答质量或调用成本、原训练/完整论文模型运行、Docker镜像构建、生产服务或学生学习收益。本机 Docker daemon 未启动，因此 Dockerfile仅作为提供的运行方式，不宣称已构建成功。GitHub Pages 只承载静态导览，不能当成完整模型服务部署。

没有为简历新做模型实验、性能提升估算或论文指标重算。19项是本次公开适配的工程检查，不能替换原研究评估数字。
