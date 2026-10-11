"""The author's Supervisor dashboard layout, connected to the recovered core.

Only released CSVs and session-local state are used. No historical Firebase,
legacy C_FULL service, hidden model opener, pickle or author key is imported.
"""
from pathlib import Path
import json
import os
import uuid

import pandas as pd
import streamlit as st

from public_runtime.core import PublicAssistant, PAGES, MODES, PROFILES, tasks
from public_runtime.dashboard_charts import load_dashboard_data, render_dashboard, chart_source_version

ROOT = Path(__file__).resolve().parents[1]
UI_PAGES = (*PAGES, 'Next Steps')
LABELS = {'Overview': '▦ Introduction / Overview', 'Resources': '▤ Resources',
          'Lecture': '▶ Lecture', 'Debate': '◉ Debate', 'Reflection': '✎ Reflection',
          'Next Steps': '⚑ Next Steps'}
MODE_LABELS = {'S0_PAGE_ONLY': 'S0 · Current page',
               'S1_CROSS_PAGE_EVIDENCE': 'S1 · Cross-page evidence',
               'S2_EVIDENCE_RAG': 'S2 · Evidence + RAG',
               'S3_EVIDENCE_MEMORY': 'S3 · Evidence + Memory',
               'S4_EVIDENCE_PLANNING': 'S4 · Evidence + Planning',
               'S5_FULL': 'S5 · Full system'}


def _result(result, engine, context):
    st.caption('结果身份：' + result.get('runtime_profile', 'UNKNOWN') + ' · '
               + result.get('generation', 'UNKNOWN'))
    mode = result.get('mode') or st.session_state.get('result_selection', {}).get('mode')
    if mode:
        st.caption('这次执行的研究模式：' + MODE_LABELS[mode])
    if result.get('answer'):
        st.markdown(result['answer'])
    plan = result.get('accepted_plan')
    if plan:
        st.markdown('#### Checked action proposal · 已检查的行动建议')
        st.write(plan['goal'])
        st.dataframe(pd.DataFrame([{'Step': action['step_id'], 'Action': action['action'],
                                   'Completion check': action['completion_check']}
                                  for action in plan['actions']]), hide_index=True, use_container_width=True)
        st.caption('编码约束检查通过；语义质量和最终回答对计划的忠实程度尚未验证。建议尚未成为你的 Memory。')
        if result.get('plan_registration', {}).get('registered'):
            with st.form('accept_checked_plan'):
                consent = st.checkbox('我选择采纳这个行动计划，并同意保存到当前学习者的会话 Memory')
                accept = st.form_submit_button('采纳已检查计划')
            if accept:
                try:
                    outcome = engine.memory_accept_plan(context['task_id'], plan, consent=consent)
                    if outcome['accepted']:
                        st.success('已按你的选择保存计划与原生行动记录。可在 Next Steps 报告完成。')
                    else:
                        st.warning('未采纳：' + outcome['reason_code'])
                except Exception as exc:
                    st.error('计划未采纳（' + type(exc).__name__ + '）。')
    core = result.get('core', result)
    prepared = core.get('prepared')
    if prepared:
        with st.expander('查看实际使用的证据、来源和检查'):
            st.json(prepared['final_request']['runtime_input']['evidence']['selected_evidence'])
            st.json({key: core[key] for key in ('rag_calls', 'memory_calls', 'memory_backend',
                                               'readonly_state_unchanged') if key in core})
            st.json(prepared['trace'])
            if prepared.get('planner'):
                st.json(prepared['planner'].get('validation', {}))
    with st.expander('完整执行记录'):
        st.json(result)


def _controls():
    intent = st.selectbox('显式任务类型', ['AUTO', 'ORDINARY_ACTION_ADVICE', 'EXPLICIT_SCHEDULE'])
    controls = {} if intent == 'AUTO' else {'task_intent': intent}
    if intent == 'EXPLICIT_SCHEDULE':
        st.caption('请明确填写可用日期、时区和时间窗口；未填写时原检查器会要求补充。')
        zone = st.text_input('计划时区', placeholder='Asia/Shanghai')
        start = st.text_input('计划开始时间（含时区）', placeholder='YYYY-MM-DDTHH:MM:SS+08:00')
        end = st.text_input('计划结束时间（含时区）', placeholder='YYYY-MM-DDTHH:MM:SS+08:00')
        available = st.checkbox('我确认这一整个时段可用于学习')
        if zone:
            controls['schedule_timezone'] = zone
        if start and end:
            controls['schedule_horizon'] = {'start': start, 'end': end}
            if available:
                controls['allowed_windows'] = [{'start': start, 'end': end}]
    with st.expander('Memory 使用目的'):
        use = st.selectbox('读取目的', ['AUTO', 'GOAL_RECALL', 'PLAN_CONTINUATION', 'COMPLETION_RECALL'])
        if use != 'AUTO':
            controls['memory_purpose'] = use
        st.caption('未知目的只读取相关种子，不擅自扩展目标、计划或完成关系。')
    return controls


def _invoke(engine, profile, query, context, page, mode, controls, demands):
    try:
        if profile == 'COMPONENTS':
            result = engine.components(query, context=context, page=page, mode=mode,
                                       controls=controls, **demands)
        else:
            with st.spinner('Reading sources and checking the full research pipeline…'):
                result = engine.live(query, context=context, page=page, mode=mode, controls=controls)
        st.session_state.last_result = result
        st.session_state.result_selection = dict(context=context, page=page, mode=mode)
        return result
    except Exception as exc:
        if 'LIVE_MEMORY_REQUIRES_PINNED_MPNET' in str(exc):
            st.error('完整 Hybrid Memory 需要已校验的 MPNet 模型和可选依赖；本次完整请求未完成。')
        else:
            st.error(('组件未完成' if profile == 'COMPONENTS' else '实时请求未完成')
                     + '（' + type(exc).__name__ + '）。请检查输入、模型权限和所需资源。')
        return None


def _assistant(engine, profile, context, page, historical_task):
    st.markdown('#### 🤖 GenAI Assistant')
    if profile == 'REPLAY':
        st.caption('研究回答回放与上方匿名学习者的仪表盘分别标识。回放不会为当前学习者生成回答。')
        st.write(historical_task['query'])
        st.caption('历史任务：' + historical_task['task_id'] + ' · ' + historical_task['query_time'])
        mode = st.selectbox('保存的研究模式', MODES, format_func=lambda x: MODE_LABELS[x])
        if st.session_state.get('last_result', {}).get('mode') not in (None, mode):
            st.session_state.pop('last_result', None)
        if st.button('回放保存回答', type='primary'):
            st.session_state.last_result = engine.replay(historical_task['task_id'], mode)
    else:
        mode = st.selectbox('系统能力模式', MODES, index=5, format_func=lambda x: MODE_LABELS[x])
        if st.session_state.get('result_selection', {}).get('mode') not in (None, mode):
            st.session_state.pop('last_result', None)
        st.caption('回答使用当前学习者、当前页面和观察范围。观察数据不证明学习效果。')
        if profile == 'COMPONENTS':
            st.caption('本地组件：显式需求勾选，原 R0 / 完整 M1 / typed Planner；没有 P3 模型推断或模板答案。')
            c1, c2, c3 = st.columns(3)
            demands = dict(rag=c1.checkbox('执行 R0 RAG', value=True),
                           memory=c2.checkbox('执行完整 M1 Memory', value=True),
                           planning=c3.checkbox('执行 typed Planner', value=False))
            demands['memory_backend'] = st.selectbox('Memory 检索', ['LEXICAL', 'HYBRID'])
            st.caption('LEXICAL 使用原词法读取；HYBRID 使用固定 MPNet 编码及原混合检索，需要可选本地模型资源。')
        else:
            demands = {}
            st.caption('完整实时：冻结 P3 → 单需求门控 R0 / 隔离 M1 → P1+i5 → FINAL / 引用检查。S0/S1 和澄清请求绕过 P3。')
        controls = _controls()
        question = st.text_area('当前问题', value='Help me understand my learning activity and suggest next steps without dates.',
                                max_chars=2000, key='runtime_question_' + context['task_id'] + '_' + page)
        with st.container(height=220, border=True):
            for message in engine.history:
                with st.chat_message(message['role']):
                    st.markdown(message['content'])
        prompt = st.chat_input('Type your message', key='chat_' + context['task_id'] + '_' + page)
        clicked = st.button('执行本地组件' if profile == 'COMPONENTS' else '实时发送到 OpenAI', type='primary')
        if clicked or prompt:
            _invoke(engine, profile, prompt or question, context, page, mode, controls, demands)
    result = st.session_state.get('last_result')
    if result:
        _result(result, engine, context)


def _memory(engine, context):
    task_id = context['task_id']
    st.subheader('Learning Memory · 学习者独立会话')
    st.caption('只有你明确声明并同意保存的信息写入原生 Memory。模型建议不自动变成你的目标或已完成事项。')
    try:
        records = engine.memory_list(task_id)
    except Exception as exc:
        records = []
        st.error('Memory 读取未完成（' + type(exc).__name__ + '）。')
    options = {'新增': None, **{r['memory_id'] + ' · ' + r['content'][:40]: r['memory_id'] for r in records}}
    with st.form('visitor_memory'):
        choice = st.selectbox('新增或更新', list(options))
        kind = st.selectbox('Memory类型', ['GOAL', 'PREFERENCE', 'CONSTRAINT', 'DIFFICULTY'])
        content = st.text_area('你明确声明的内容', max_chars=1000)
        consent = st.checkbox('同意在当前session保存这条学习信息')
        save = st.form_submit_button('保存原生Memory')
    if save:
        try:
            outcome = engine.memory_write(task_id, content, kind, consent=consent,
                                          target_memory_id=options[choice])
            if outcome['accepted']:
                st.success('已保存')
            else:
                st.warning('未保存：' + outcome['reason_code'])
            records = engine.memory_list(task_id)
        except Exception as exc:
            st.error('Memory 未保存（' + type(exc).__name__ + '）。')
    if records:
        st.dataframe(pd.DataFrame([{'Type': r['memory_type'], 'Your statement': r['content'],
                                    'Version': r['version']} for r in records]), hide_index=True,
                     use_container_width=True)
    else:
        st.info('当前学习者尚未在这个会话声明学习 Memory。')
    with st.popover('原生 Memory 记录与来源'):
        st.json(records)
    try:
        state = engine.memory_task_state(task_id)
        adopted = state['plans']
    except Exception as exc:
        adopted = []
        st.error('已采纳计划读取未完成（' + type(exc).__name__ + '）。')
    if adopted:
        st.markdown('#### Adopted plans · 你已采纳的计划')
        st.caption('助手可以回顾你采纳的计划与自报完成关系；原 Planner 暂不自动恢复完整旧计划结构。')
        actions = [dict(**action, goal=plan['plan']['goal']) for plan in adopted for action in plan['actions']]
        st.dataframe(pd.DataFrame([{'Goal': action['goal'], 'Action': action['action'],
                                   'Status': 'Completed (your report)' if action['completed'] else 'Accepted'}
                                  for action in actions]), hide_index=True, use_container_width=True)
        unfinished = {action['action_memory_id']: action['action'] for action in actions if not action['completed']}
        if unfinished:
            with st.form('complete_accepted_action'):
                action_id = st.selectbox('已采纳的原生行动', list(unfinished), format_func=lambda value: unfinished[value])
                consent = st.checkbox('我确认已完成所选行动，并同意保存这条自报完成记录')
                complete = st.form_submit_button('报告行动完成')
            if complete:
                try:
                    outcome = engine.memory_complete_action(task_id, action_id, consent=consent)
                    if outcome['accepted']:
                        st.success('已保存你的完成报告与原生行动关系。完成由你自报，未经外部验证。')
                        st.rerun()
                    else:
                        st.warning('未保存：' + outcome['reason_code'])
                except Exception as exc:
                    st.error('完成报告未保存（' + type(exc).__name__ + '）。')
        with st.popover('计划、原生行动 ID 和完成依据'):
            st.json(state)


def _next_steps(engine, context):
    left, right = st.columns([2, .5], vertical_alignment='center')
    with left:
        st.subheader('What should you do next?')
        st.write('Review your activity, reflect on what it means to you, and choose a learning goal. '
                 'A reflection or goal below is your own declaration; accepting it is optional.')
    with right:
        st.image(str(ROOT / 'data/dashboard/input/images/srl.png'), width=180)
    scope = context['task_id']
    reflections_key = 'reflections_' + scope
    st.session_state.setdefault(reflections_key, [])
    with st.form('new_reflection'):
        reflection = st.text_area('Reflection', placeholder='What would you like to change next week?')
        if st.form_submit_button('Save reflection'):
            if reflection.strip():
                st.session_state[reflections_key].append({'Date': pd.Timestamp.now().isoformat(),
                                                         'Reflection': reflection.strip()})
                st.success('Reflection saved in this session.')
    if st.session_state[reflections_key]:
        st.dataframe(pd.DataFrame(st.session_state[reflections_key]), hide_index=True, use_container_width=True)
    st.caption('反思表只保留在当前 session；不会自动加入长期学习 Memory。需要引用时请在下面明确保存。')
    goals_key = 'goal_drafts_' + scope
    if goals_key not in st.session_state:
        st.session_state[goals_key] = pd.DataFrame(columns=['Goal', 'Due', 'Status', 'Progress', 'Notes'])
    st.markdown('#### My plans')
    edited = st.data_editor(st.session_state[goals_key], num_rows='dynamic', hide_index=True,
                            use_container_width=True, key='goal_editor_' + scope,
                            column_config={'Status': st.column_config.SelectboxColumn(
                                'Status', options=['Not started', 'In progress', 'Completed'])})
    st.session_state[goals_key] = edited.copy()
    st.caption('这是你的可编辑计划草稿；日期、状态和进度不自动进入研究后端。'
               '需让助手记住的目标或约束，请明确声明并同意保存。')
    _memory(engine, context)


def _course_browser():
    with st.expander('Course materials · 课程来源'):
        corpus = [json.loads(x) for x in (ROOT / 'data/course/corpus.jsonl').read_text().splitlines() if x.strip()]
        term = st.text_input('浏览课程文本', placeholder='learning analytics')
        matched = [c for c in corpus if not term or term.casefold() in (c['text'] + ' ' + c.get('title', '')).casefold()]
        st.caption(f'{len(matched)} / {len(corpus)} chunks。浏览筛选不是 RAG 评分；Gold 和评价参考不属于语料。')
        for row in matched[:8]:
            st.markdown('**' + row.get('title', row['chunk_id']) + '**')
            st.write(row['text'])
            st.caption(row['chunk_id'] + ' · ' + row['source_file'] + ' · W' + str(row.get('week')))


def run():
    st.markdown('''<style>
      #MainMenu {visibility: hidden;} footer {visibility: hidden;}
      .block-container {padding-top: 2rem;}
      div[role="radiogroup"] {gap: 1rem; background: #f0f2f6; padding: .7rem; border-radius: .5rem;}
      div[data-testid="stPopoverBody"] {max-width: min(620px, 94vw);}
    </style>''', unsafe_allow_html=True)
    if 'visitor_id' not in st.session_state:
        st.session_state.visitor_id = uuid.uuid4().hex
    if 'engine' not in st.session_state:
        st.session_state.engine = PublicAssistant(st.session_state.visitor_id,
                                                 storage_root=os.environ.get('LAD_SESSION_STORAGE'))
    engine = st.session_state.engine
    data = load_dashboard_data()
    roster = data['student_info']
    ids = roster['ID'].astype(str).tolist()
    names = dict(zip(ids, roster['AppName']))
    with st.sidebar:
        st.markdown('### 👩‍💻 DUTE AI Assistant')
        st.caption('Supervisor dashboard · latest research core')
        profile = st.selectbox('运行 profile', PROFILES)
        learner = st.selectbox('匿名学习者', ids, format_func=lambda value: names[value])
        weeks = st.slider('观察周范围', min_value=0, max_value=10, value=(0, 10))
        st.caption('历史观察周：2025年课程。视频材料周和累计观看量不代表观看发生时间。')
        if profile == 'LIVE':
            engine.bind_key(st.text_input('访客 OpenAI API Key', type='password', key='visitor_api_key'))
            st.caption('仅发送时调用。问题、可见聊天及启用的来源发送到 OpenAI；费用由访客承担。Key只保留在本session内存。')
        else:
            engine.bind_key(None)
        st.caption('匿名浏览无需 Firebase。Cloud存储临时；当前学习者的可写 Memory 与其他访客独立。')
        st.markdown('[GitHub · Code and research data](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant)')
    st.header('Individual Engagement')
    page = st.radio('学习页面', UI_PAGES, format_func=lambda value: LABELS[value], horizontal=True,
                    label_visibility='collapsed', key='supervisor_page')
    core_page = page if page in PAGES else 'Overview'
    lecture_item = None
    if page == 'Lecture':
        items = data['echo'].loc[data['echo']['ID'].astype(str).eq(learner), 'Class'].drop_duplicates().tolist()
        lecture_item = st.selectbox('聚焦视频', [None, *items], format_func=lambda value: value or '全部累计录播记录')
    context = engine.bind_dashboard(learner, weeks[0], weeks[1], lecture_item_id=lecture_item)
    if chart_source_version(data) != context['source_version']:
        st.error('仪表盘来源在读取期间发生变化。请重新运行页面，以便图表和助手使用同一份来源。')
        st.stop()
    st.session_state.dashboard_context = context
    st.session_state.selected_learner = learner
    st.session_state.source_task = context['task_id']
    historical_task = None
    if profile == 'REPLAY':
        candidates = [t for t in tasks() if t['page'] == core_page] or tasks()
        with st.sidebar:
            selected = st.selectbox('研究任务 / source context', [t['task_id'] for t in candidates],
                                    format_func=lambda value: value + ' · ' + next(t['query'][:50] for t in candidates if t['task_id'] == value))
            historical_task = next(t for t in candidates if t['task_id'] == selected)
            st.caption('回放来源是这道历史研究任务，不是当前匿名学习者。')
    selection = (profile, learner, tuple(weeks), page, lecture_item,
                 historical_task['task_id'] if historical_task else None)
    if st.session_state.get('ui_selection') != selection:
        st.session_state.pop('last_result', None)
        st.session_state.ui_selection = selection
    with st.sidebar:
        if st.button('清空当前聊天'):
            engine.history.clear()
            st.session_state.pop('last_result', None)
            st.rerun()
        if engine.history:
            st.download_button('Download your chats with GenAI',
                               pd.DataFrame(engine.history).to_csv(index=False).encode(),
                               file_name='my-session-chat.csv', mime='text/csv')
    st.caption(names[learner] + f' · observation W{weeks[0]}–W{weeks[1]} · {profile}')
    data['_lecture_item_id'] = lecture_item
    if page == 'Next Steps':
        _next_steps(engine, context)
    else:
        render_dashboard(core_page, data, learner, weeks[0], weeks[1])
    # The scope is computed from the same trusted CSVs as the displayed graphs.
    try:
        source = engine.call('source', context=context, query='Explain this dashboard page.', page=core_page)
        st.session_state.latest_source = source
        with st.expander('当前仪表盘的来源与范围'):
            st.json(source.get('source', source))
    except Exception as exc:
        st.error('来源读取未完成（' + type(exc).__name__ + '）。')
    _, comments, assistant = st.columns([1, 2, 2])
    with comments:
        with st.form('feedback_' + page):
            st.markdown('#### We 🧡 your feedback!')
            rating = st.slider('How useful is this view?', 0, 5, 0)
            comment = st.text_input('What do you think about your feedback?')
            if st.form_submit_button('Save feedback in this session'):
                feedbacks = st.session_state.setdefault('visitor_feedbacks', {})
                feedbacks.setdefault(learner, []).append({'page': page, 'rating': rating, 'comment': comment})
                st.success('Thank you! Saved only in this visitor session.')
    with assistant:
        with st.popover('🤖 Chat with GenAI Assistant!', use_container_width=True):
            _assistant(engine, profile, context, core_page, historical_task)
    if page != 'Next Steps':
        with st.expander('Learning Memory · goals and corrections'):
            _memory(engine, context)
    _course_browser()
    with st.expander('论文技术与当前运行边界'):
        st.markdown('**Evidence / P3 / R0 / M1 / P1+i5 / FINAL** 使用恢复的原核心。'
                    'M1及断网保护只在无key子进程导入，生成进程保留网络能力。'
                    'RAG单门控、来源/时间、unknown/0、角色与更正、只读校验、编码计划与引用检查均保留。')
        st.markdown('**RQ1学习排序与RQ2路由比较** 保留为独立研究与分析入口；'
                    '最终应用采用论文的冻结P3，不把早期实验分类器串成新后端。'
                    'Gold、匿名评分和评价参考不会进入生成或RAG。')
        st.caption('COMPONENTS是无模型本地执行；LIVE需要自己的key与固定Hybrid资源。'
                   '本轮真实provider推理没有付费实测；精确mock不代表实时模型质量。')
