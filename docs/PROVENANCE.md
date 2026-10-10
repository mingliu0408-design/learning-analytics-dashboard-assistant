> Historical v0.1.0 snapshot. Current G0-R1 recovery/publication: [PROJECT_MAP](PROJECT_MAP.md), [RECOVERY](RECOVERY.md), [VALIDATION_G0_R1](VALIDATION_G0_R1.md).

# 来源与贡献边界

本仓库面向技术演示，将可运行的公开界面与已发表的研究复现代码分开。

| 层级 | 来源 | 本次处理 |
| --- | --- | --- |
| `research/` | `mingliu0408-design/lad-assistant-reproducibility`，main 提交 `2d5ed307397b0f58f777fd2c054bc96a3c145e7d` | 从公开 GitHub 仓库复制，排除其 `.git`，保留原文件与许可说明；原快照校验器继续适用 |
| 原学习仪表盘 | 本地历史基线及原应用版本 | 原项目在既有仪表盘上新增/集成问答能力；未复制 Firebase、学生输入、会话或课程文档到演示入口 |
| `demo/` 与 `app.py` | 2026-10-10 新公开包装适配 | 原创合成数据、新界面、可选生成及模块集成；不能写成论文评估时已经运行的网页 |
| `docs/index.html` | 新浏览器导览 | 只显示合成数据和离线预生成示例；不把静态示例称为实时大模型服务 |

原聊天绑定目录 `rq3-rebuild-i1-pilot-launch` 在本次工作时已不在原路径。原 Git common 仓库仍包含研究提交 `fdd9848b2a92b5f50675d193a4765e02dfa9ebb8`；本次公开材料以已经发布的复现快照为输入，未恢复、推送或改写私有研究历史。

项目适合描述为“在已有学习分析仪表盘上开发并集成智能问答助手”。仓库归属与提交作者不证明全部代码独立原创；本仓库不替代个人职责证明或正式作者贡献声明。

研究快照的来源映射、哈希、配置和限定分别位于 `research/metadata/`、`research/docs/`、`research/LICENSING.md`。原论文的路由、数据范围与模型配置保持独立。公开演示的新规则路由、合成候选计划和 UI 不能替代原 P3/RQ3 实验身份。
