"""Public Streamlit adapter. All dashboard/course inputs are synthetic."""
from pathlib import Path
import os
import uuid

import pandas as pd
import plotly.express as px
import streamlit as st

from demo.core import DemoAssistant
from demo.data import PAGES, SAMPLE_QUESTIONS, COURSE_MATERIALS

st.set_page_config(page_title="Learning Analytics Assistant", page_icon="📊", layout="wide")
st.markdown("""<style>
.block-container{padding-top:2.2rem;max-width:1280px}
[data-testid=stMetric]{background:white;border:1px solid #e3e8f3;border-radius:14px;padding:18px}
h1{letter-spacing:-1px} .stCaption{color:#63718a}
</style>""", unsafe_allow_html=True)

ROOT = Path(__file__).resolve().parent
MEMORY_ROOT = Path(os.environ.get("DEMO_MEMORY_ROOT", str(ROOT / ".local" / "memory"))).expanduser()
LABELS = {"Overview":"总览", "Resources":"课程资源", "Lecture":"视频学习", "Debate":"讨论互动", "Reflection":"学习反思"}
METRICS = {"resource_views":"资源访问", "video_minutes":"视频学习分钟", "video_completion":"视频完成", "debate_posts":"讨论发帖", "debate_replies":"讨论回复", "reflection_words":"反思字数"}

if "workspace_id" not in st.session_state:
    st.session_state.workspace_id = uuid.uuid4().hex
if "messages" not in st.session_state:
    st.session_state.messages = []
MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
database = MEMORY_ROOT / (st.session_state.workspace_id + ".sqlite")
engine = DemoAssistant(database, session_id=st.session_state.workspace_id)
st.session_state.demo_engine = engine

with st.sidebar:
    st.markdown("### 📊 LAD Assistant")
    st.caption("硕士项目 · 公开演示")
    page = st.radio("学习页面", PAGES, format_func=lambda p: LABELS[p])
    st.divider()
    online = st.checkbox("开启 OpenAI 在线生成", value=False)
    api_key = None
    if online:
        api_key = st.text_input("你的 OpenAI API Key", type="password")
        st.caption("点击发送才调用模型；问题、当前可见历史和所选证据会发给 OpenAI。费用由你的账号承担。Key 不写入数据库。")
    else:
        st.caption("当前为确定性离线演示：真实检索、记忆与校验；回答由模板组织。")
    if st.button("清空本次对话", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.caption("独立访客工作区。数据库保存在服务本地；刷新页面可能进入新工作区。")
    st.markdown("[源码与运行说明](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant)")

st.caption("SYNTHETIC DATA / 合成数据 · 非真实学生记录")
st.title("Learning Analytics Dashboard Assistant")
st.write("把学习活动转成可追溯的问答：查看数据、检索课程材料、记录明确偏好、生成并校验行动计划。")
st.caption("在已有学习分析仪表盘上开发智能问答的研究项目。本界面是新整理的公开演示适配；论文实现与结果独立保存在 research/。")

snapshot = engine.snapshot(page)
metrics = snapshot["metrics"]
columns = st.columns(min(len(metrics), 4))
for index, (name, value) in enumerate(metrics.items()):
    columns[index % len(columns)].metric(METRICS.get(name, name), value)

dashboard_tab, assistant_tab, memory_tab, materials_tab = st.tabs(["学习仪表盘", "智能问答", "持久化记忆", "课程证据"])
with dashboard_tab:
    st.subheader(LABELS[page] + " · 四周学习活动")
    frame = pd.DataFrame(snapshot["weekly"])
    candidates = [name for name in metrics if name in frame.columns]
    selected = st.selectbox("查看趋势", candidates, format_func=lambda k: METRICS[k])
    fig = px.bar(frame, x="week", y=selected, labels={"week":"教学周", selected:METRICS[selected]}, color_discrete_sequence=["#4665e9"])
    fig.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(dtick=1))
    st.plotly_chart(fig, use_container_width=True)
    with st.expander("查看数据与范围"):
        st.dataframe(frame, hide_index=True, use_container_width=True)
        st.json(snapshot["scope"])
    st.caption("数据由 demo/data.py 中的原创合成样例生成。这里的行为统计不证明学习效果或真实学生表现。")

with assistant_tab:
    st.subheader("问一个与当前学习页面有关的问题")
    chosen = None
    for question in SAMPLE_QUESTIONS[page]:
        if st.button(question, key="sample_" + page + question):
            chosen = question
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    typed = st.chat_input("例如：根据我的资源学习情况，给我一个 30 分钟计划", max_chars=2000)
    question = chosen or typed
    if question:
        if online and not api_key:
            st.warning("请填写你的 API Key，或关闭在线生成后体验离线模式。")
        else:
            with st.chat_message("user"):
                st.write(question)
            with st.spinner("组装证据与校验约束…"):
                result = engine.answer(question, page=page, history=st.session_state.messages[-10:], online=online, api_key=api_key)
            result["request_page"] = page
            st.session_state.last_result = result
            if result.get("error"):
                st.error(result["error"])
                with st.chat_message("assistant"):
                    st.markdown(result["answer"])
            else:
                st.session_state.messages += [{"role":"user","content":question}, {"role":"assistant","content":result["answer"]}]
                with st.chat_message("assistant"):
                    st.markdown(result["answer"])
    if "last_result" in st.session_state:
        result = st.session_state.last_result
        st.caption("上一条回答页面：" + result.get("request_page", page) + " · 模式：" + result["mode"] + " · 启用能力：" + " / ".join(result["capabilities"]))
        with st.expander("回答依据与执行轨迹", expanded=True):
            for evidence in result["evidence"]:
                st.markdown("**[" + evidence["id"] + "] " + evidence.get("title", evidence.get("kind", "证据")) + "**")
                st.write(evidence.get("text", evidence.get("content", "")))
            st.json({"citations":result["citations"], "trace":result["trace"], "limitations":result["limitations"]})
        if result.get("plan"):
            with st.expander("结构化计划与校验结果"):
                st.json(result["plan"])

with memory_tab:
    st.subheader("只保存你明确填写的学习目标或约束")
    st.write("复用原项目的 SQLite + FTS5 写入与检索。聊天不会自动写入记忆；这里的记录与你当前对话历史分开。")
    records = engine.memory_list()
    choices = {"新增记录":None}
    choices.update({f"更新 {row.get('memory_id', row.get('id', ''))}: {row.get('content', '')[:35]}":row for row in records})
    with st.form("memory_form"):
        selection = st.selectbox("操作", list(choices))
        memory_type = st.selectbox("类型", ["GOAL","PREFERENCE","CONSTRAINT","DIFFICULTY"])
        content = st.text_area("学习内容", placeholder="例如：我希望优先练习碳排放核算，每次学习不超过 30 分钟。", max_chars=1000)
        consent = st.checkbox("我同意在当前演示工作区保存这条学习信息")
        save = st.form_submit_button("保存学习记忆")
    if save:
        previous = choices[selection]
        target_id = previous.get("memory_id", previous.get("id")) if previous else None
        try:
            result = engine.memory_write(content, memory_type, consent=consent, target_memory_id=target_id)
            if result.get("accepted"):
                st.success("已保存。更新会创建新版本并替代旧记录。")
            else:
                st.warning("未保存：" + str(result.get("reason_code", result.get("reason", "写入未通过"))))
        except ValueError:
            st.warning("未保存：请填写 1—1000 个字符的学习内容。")
    records = engine.memory_list()
    st.json(records)
    st.caption("请仅填写演示学习信息。数据库与 API Key 已从 Git/Docker 发布文件中排除；服务重启后数据库文件仍可被同路径的后端读取。")

with materials_tab:
    st.subheader("公开课程材料 · 原创合成内容")
    for item in COURSE_MATERIALS:
        with st.expander(item["id"] + " · " + item["title"]):
            st.write(item["text"])
            st.caption("来源：" + item["source"])
    st.caption("复用原 R0 加权词法评分；这里的演示语料不是论文的 6 份课程文档或 624 个文本块。MPNet 与原 P3 不在默认演示路径中执行。")
