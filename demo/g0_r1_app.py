"""Restored LAD public UI; legacy synthetic UI is preserved in demo/legacy_app.py."""
from pathlib import Path
import json
import os
import uuid
import pandas as pd
import streamlit as st
from public_runtime.core import PublicAssistant, PAGES, MODES, PROFILES, tasks

st.set_page_config(page_title='LAD Assistant', page_icon='📊', layout='wide')
ROOT = Path(__file__).resolve().parent
LABELS = {'Overview':'总览','Resources':'课程资源','Lecture':'视频学习','Debate':'讨论互动','Reflection':'学习反思'}
if 'visitor_id' not in st.session_state:
    st.session_state.visitor_id = uuid.uuid4().hex
if 'engine' not in st.session_state:
    st.session_state.engine = PublicAssistant(st.session_state.visitor_id, storage_root=os.environ.get('LAD_SESSION_STORAGE'))
engine = st.session_state.engine
all_tasks = tasks()
with st.sidebar:
    st.markdown('### 📊 LAD Assistant')
    profile = st.selectbox('运行 profile', PROFILES)
    page = st.radio('学习页面', PAGES, format_func=lambda p: LABELS[p])
    candidates = [t for t in all_tasks if t['page'] == page] or all_tasks
    selected = st.selectbox('研究任务 / source context', [t['task_id'] for t in candidates], format_func=lambda x: x+' · '+next(t['query'][:58] for t in candidates if t['task_id']==x))
    task = next(t for t in all_tasks if t['task_id']==selected)
    if st.session_state.get('source_task') != selected:
        engine.select_task(selected)
        st.session_state.source_task=selected
        st.session_state.pop('last_result',None)
    st.caption('源课程：'+task['scope']['course_id'])
    st.caption('历史任务时间：'+task['query_time'])
    if profile == 'LIVE':
        engine.bind_key(st.text_input('访客 OpenAI API Key', type='password', key='visitor_api_key'))
        st.caption('仅点击实时发送时调用。问题、可见聊天及启用的学习/课程/Memory来源会发送至OpenAI；费用由访客承担。Key仅存在本session内存，不写数据库、日志或环境。')
        st.caption('P3要求Memory时完整Hybrid需要optional依赖与固定MPNet；资源缺失将明确报错。')
    else:
        engine.bind_key(None)
    if st.button('清空当前聊天'):
        engine.history.clear()
        st.session_state.pop('last_result',None)
        st.rerun()
    st.caption('可写Memory按session和任务独立。Cloud存储临时，重启会丢失；公开原seed只读。')
    st.markdown('[GitHub源码和研究数据](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant)')

st.title('Learning Analytics Dashboard Assistant')
st.write('查看四域学习来源，回放41题六模式的保存回答，执行原Evidence、R0、完整M1与typed Planner，或用自己的key发送完整实时请求。')
st.caption(f'当前 {profile} · {LABELS[page]} · 原核心 fdd9848 · 新公开UI适配；论文评分时的界面与历史结果独立保留。')
try:
    source = engine.call('source',task_id=selected)
except Exception as exc:
    st.error('来源读取失败：'+str(exc))
    st.stop()
view_tab, assistant_tab, memory_tab, course_tab = st.tabs(['学习仪表盘','问答与执行','学习Memory','课程来源'])
with view_tab:
    st.subheader(LABELS[page]+' · 保存的来源状态')
    st.caption('Original任务来自实际匿名仪表盘的历史投影；新增研究条件保留人工控制来源标签。缺失保持unknown；观察量不证明学习效果。')
    activity=source['overview'].get('activity',{})
    displayed=activity if page=='Overview' else {page:activity.get(page,{})}
    values=[]
    names={'resource_views':'资源访问','video_clicks':'视频点击','total_view_events':'播放事件','mean_percent_all_9_source_rows':'九行平均观看百分比','Total_chars':'字符编辑量','active_source_weeks':'有活动的源周数'}
    for domain,state in displayed.items():
        for metric,value in state.items():
            if metric in names and (value is None or type(value) in (int,float)):
                values.append((LABELS[domain]+' · '+names[metric],value))
        if 'event_observations' in state:
            values.append((LABELS[domain]+' · 所声明事件流的事件数',state['event_observations']['count']))
    if values:
        columns=st.columns(min(len(values),4))
        for i,(label,value) in enumerate(values):
            columns[i%len(columns)].metric(label,'unknown' if value is None else value)
    st.json(dict(source_origin=source['snapshot_origin'],scope=task['scope'],activity=displayed))
    with st.expander('浏览实际匿名学习活动CSV'):
        path=ROOT/'data/dashboard/input/features/features.csv'
        if path.exists():
            st.dataframe(pd.read_csv(path),hide_index=True,use_container_width=True)
        else:
            st.info('完整学习数据可从研究数据Release取得。')
        st.caption('原学习数据独立于受控实验条件。Total_chars/absStrCount表示字符编辑量。Overview是四域汇总，不增加第五域事件。')
with assistant_tab:
    if profile=='REPLAY':
        st.subheader('REPLAY · 历史研究回答')
        st.write(task['query'])
        mode=st.selectbox('保存的研究模式',MODES)
        if st.button('回放保存回答',type='primary'):
            try:
                st.session_state.last_result=engine.replay(selected,mode)
            except Exception as exc:
                st.error(str(exc))
        st.caption('只读取保存回答，不重新生成或评分。新问题没有历史匹配时切换组件或实时profile。')
    else:
        st.subheader('实际本地组件' if profile=='COMPONENTS' else '访客自备key · 完整实时核心')
        query=st.text_area('当前问题',value=task['query'],max_chars=2000,key='runtime_question_'+selected)
        intent=st.selectbox('显式任务类型',['AUTO','ORDINARY_ACTION_ADVICE','EXPLICIT_SCHEDULE'])
        controls={} if intent=='AUTO' else {'task_intent':intent}
        if intent=='EXPLICIT_SCHEDULE':
            st.caption('日历计划需要你明确填写时区、日期范围和可用窗口；留空时原检查器要求补充。')
            zone=st.text_input('计划时区',placeholder='Asia/Shanghai')
            start=st.text_input('计划开始时间（含时区）',placeholder='YYYY-MM-DDTHH:MM:SS+08:00')
            end=st.text_input('计划结束时间（含时区）',placeholder='YYYY-MM-DDTHH:MM:SS+08:00')
            available=st.checkbox('我确认这一整个时段可用于学习')
            if zone:controls['schedule_timezone']=zone
            if start and end:
                controls['schedule_horizon']={'start':start,'end':end}
                if available:controls['allowed_windows']=[{'start':start,'end':end}]
        if profile=='COMPONENTS':
            st.caption('需求来自下面显式勾选；此模式不执行P3推断、不生成模板答案。Memory明确是原生词法模式。')
            c1,c2,c3=st.columns(3)
            rag=c1.checkbox('执行 R0 RAG',value=True)
            memory=c2.checkbox('执行完整 M1 Memory',value=True)
            planning=c3.checkbox('执行 typed Planner',value=False)
            if st.button('执行本地组件',type='primary'):
                try:
                    st.session_state.last_result=engine.components(query,task_id=selected,page=page,rag=rag,memory=memory,planning=planning,controls=controls)
                except Exception as exc:
                    st.error('组件未完成：'+str(exc))
        else:
            st.caption('冻结三个P3角色 → 原R0/隔离M1 → P1+i5 candidate/检查/单次修复 → FINAL/引用检查。当前发布没有付费live实测。')
            if st.button('实时发送到 OpenAI',type='primary'):
                try:
                    with st.spinner('执行冻结角色与原核心…'):
                        st.session_state.last_result=engine.live(query,task_id=selected,page=page,controls=controls)
                except Exception as exc:
                    if 'LIVE_MEMORY_REQUIRES_PINNED_MPNET' in str(exc):
                        st.error('完整实时M1需要安装optional依赖并配置固定MPNet模型；当前未执行完整请求。')
                    else:
                        st.error('实时请求未完成（'+type(exc).__name__+'）。请检查key、模型权限和所需资源；异常详情不显示或记录。')
            for message in engine.history:
                with st.chat_message(message['role']):
                    st.write(message['content'])
    result=st.session_state.get('last_result')
    if result:
        st.caption('结果身份：'+result.get('runtime_profile','UNKNOWN')+' · '+result.get('generation','UNKNOWN'))
        if result.get('answer'):
            st.markdown(result['answer'])
        if 'prepared' in result:
            st.write('实际保留证据')
            st.json(result['prepared']['final_request']['runtime_input']['evidence']['selected_evidence'])
            st.json({k:result[k] for k in ('route','rag_calls','memory_calls','memory_backend') if k in result})
            st.json(result['prepared']['trace'])
            if result['prepared'].get('planner'):
                st.json(result['prepared']['planner']['validation'])
        with st.expander('完整执行记录与来源'):
            st.json(result)
with memory_tab:
    st.subheader('明确声明的学习Memory · session独立副本')
    st.caption('公开原seed只读；当前session按任务复制原生SQLite。writer保留角色、同意、版本和更正规则；助手建议不自动变成你的承诺。')
    try:
        records=engine.memory_list(selected)
    except Exception as exc:
        records=[]
        st.error(str(exc))
    options={'新增':None,**{r['memory_id']+' · '+r['content'][:40]:r['memory_id'] for r in records}}
    with st.form('visitor_memory'):
        choice=st.selectbox('新增或更新',list(options))
        kind=st.selectbox('Memory类型',['GOAL','PREFERENCE','CONSTRAINT','DIFFICULTY'])
        content=st.text_area('你明确声明的内容',max_chars=1000)
        consent=st.checkbox('同意在当前session保存这条学习信息')
        save=st.form_submit_button('保存原生Memory')
    if save:
        try:
            outcome=engine.memory_write(selected,content,kind,consent=consent,target_memory_id=options[choice])
            if outcome['accepted']:
                st.success('已保存')
            else:
                st.warning('未保存：'+outcome['reason_code'])
            records=engine.memory_list(selected)
        except Exception as exc:
            st.error(str(exc))
    st.json(records)
with course_tab:
    st.subheader('原课程语料 · 624 chunks')
    corpus=[json.loads(x) for x in (ROOT/'data/course/corpus.jsonl').read_text().splitlines() if x.strip()]
    term=st.text_input('浏览课程文本',placeholder='learning analytics')
    matched=[c for c in corpus if not term or term.casefold() in (c['text']+' '+c.get('title','')).casefold()]
    st.caption(f'匹配 {len(matched)} / {len(corpus)}；浏览筛选不是RAG评分。Gold和评价参考不属于此语料。')
    for item in matched[:20]:
        with st.expander(item['chunk_id']+' · '+item.get('title','')):
            st.write(item['text'])
            st.caption('来源：'+item['source_file']+' · 周：'+str(item.get('week')))
