"""Build transparent source-first drafts. Standard library only; no system/model imports."""
from pathlib import Path
import csv
import io
import json
import hashlib
import copy

HERE = Path(__file__).resolve().parent
STATUS = 'AI_ASSISTED_DRAFT_PENDING_SOURCE_REVIEW'
START = '2026-08-24T00:00:00+00:00'
END = '2026-08-31T00:00:00+00:00'
NOW = '2026-08-31T12:00:00+00:00'
COURSE = 'dute-archived-materials-experiment-v1'
PAGES = ['Resources', 'Lecture', 'Debate', 'Reflection']
CRITERIA = [x['id'] for x in json.loads((HERE/'human_review/rubric.json').read_text())['criteria']]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def opaque(prefix, value):
    return prefix + digest(value.encode())[:12]


def write(path, data):
    p = HERE/path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def jsonl(path, rows):
    p = HERE/path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in rows))


def scope(family):
    return dict(student_id=opaque('synthetic-learner-', family), course_id=COURSE,
                window_start=START, window_end=END)


def state(family):
    return dict(provenance='SYNTHETIC_EXPERIMENT_STATE', draft_status=STATUS,
                scope=scope(family), as_of=NOW,
                coverage={p: dict(status='COMPLETE', window_start=START, window_end=END)
                          for p in PAGES}, events=[], records=[])


def event(s, eid, page, kind, day, payload=None, **overrides):
    row = dict(event_id=eid, student_id=s['scope']['student_id'], course_id=COURSE,
               page=page, event_type=kind, occurred_at=f'2026-08-{day:02}T10:00:00+00:00',
               payload=payload or {})
    row.update(overrides)
    s['events'].append(row)


def record(s, rid, page, payload):
    s['records'].append(dict(record_id=rid, student_id=s['scope']['student_id'],
                             course_id=COURSE, page=page,
                             updated_at='2026-08-30T12:00:00+00:00', payload=payload))


def session(family, name, day, messages):
    sid = opaque('session-', family+name)
    return dict(session_id=sid, student_id=scope(family)['student_id'], course_id=COURSE,
                provenance='SYNTHETIC_AUTHORED_DIALOGUE_NOT_OBSERVED_STUDENT_DATA',
                messages=[dict(message_id=sid+f'-m{i+1}', role=role, content=text,
                               timestamp=f'2026-08-{day:02}T09:{i:02}:00+00:00')
                          for i, (role, text) in enumerate(messages)])


def operation(sessions, si, mi, key, value, record_type='FACT', version=1, replaces=None):
    msg = sessions[si]['messages'][mi]
    return dict(operation='PUT_VERSION', memory_key=key, version=version,
                replaces_version=replaces, record_type=record_type, value=value,
                valid_from=msg['timestamp'], valid_until=None, source_role=msg['role'],
                source_session_id=sessions[si]['session_id'], source_message_id=msg['message_id'],
                source_char_start=0, source_char_end=len(msg['content']), source_quote=msg['content'],
                interpretation_status=STATUS,
                method='MANUALLY_SPECIFIED_TRANSPARENT_PRELOAD_NOT_AUTOMATIC_EXTRACTION')


def plan(pid, steps, adoption):
    return dict(plan_id=pid, origin='SYNTHETIC_STUDY_OPTIONS', adoption=adoption,
                duration_semantics='CONTROLLED_ESTIMATES_MINUTES_NOT_MEASURED_LEARNING_TIME',
                steps=[dict(step_id=sid, parent_plan_id=pid, action=action,
                            estimated_minutes=cost, depends_on=deps)
                       for sid, action, cost, deps in steps])


def common_page(family, page='Reflection'):
    s = state(family)
    record(s, 'workspace', page, {'workspace_title': '本次学习草稿', 'saved_draft': ''})
    return s


def noise(s):
    event(s, 'outside-learner', 'Debate', 'post_published', 27, {'post_id': 'other-post'},
          student_id='synthetic-other-learner')
    event(s, 'outside-course', 'Lecture', 'recording_play', 28, {'recording_id': 'other-recording'},
          course_id='synthetic-unrelated-course')
    event(s, 'outside-window', 'Reflection', 'document_edit', 23, {'document_id': 'old-note'})


def authored_situations():
    """Fix all situations before target questions/reference are assembled below."""
    cases = {}
    s = state('E01')
    s['coverage']['Debate']['status'] = 'UNKNOWN'
    event(s, 'lecture-play', 'Lecture', 'recording_play', 25, {'recording_id': 'discussion-preparation'})
    record(s, 'discussion-work', 'Debate', {'topic': '学习分析应如何保留学生选择权',
                                         'post_status': 'DRAFT', 'draft_saved': True})
    cases['E01'] = [(s, [], []), (copy.deepcopy(s), [], [])]
    cases['E01'][1][0]['records'][0]['payload']['post_status'] = 'PUBLISHED'

    s = state('E02')
    event(s, 'resource-a', 'Resources', 'resource_view', 24, {'resource': 'module-guide'})
    event(s, 'resource-b', 'Resources', 'resource_view', 25, {'resource': 'reading-list'})
    event(s, 'lecture-a', 'Lecture', 'recording_play', 26, {'recording_id': 'analytics-notes'})
    event(s, 'debate-a', 'Debate', 'post_published', 27, {'post_id': 'claim-and-evidence'})
    event(s, 'reflection-a', 'Reflection', 'document_edit', 28, {'document_id': 'weekly-note'})
    cases['E02'] = [(s, [], []), (copy.deepcopy(s), [], [])]
    noise(cases['E02'][1][0])

    s = state('E03')
    event(s, 'lecture-a', 'Lecture', 'recording_play', 25, {'recording_id': 'reflection-preparation'})
    cases['E03'] = [(s, [], []), (copy.deepcopy(s), [], [])]
    cases['E03'][1][0]['coverage']['Reflection']['status'] = 'UNKNOWN'

    for f in ['R01', 'R02', 'R03']:
        s = common_page(f, 'Resources')
        cases[f] = [(s, [], []), (copy.deepcopy(s), [], [])]

    f = 'M01'; s = common_page(f)
    hist = [session(f, 'goal', 20, [('user', '下一次整理反思时，我想把一次小组分歧和一种学习理论联系起来，而不是只写事情经过。'),
                                   ('assistant', '也可以直接尝试写一篇完整长文；这只是我的建议。')]),
            session(f, 'preference', 22, [('user', '我更容易从两栏对照表开始，左栏放经历，右栏放理论解释。暂时不要推荐视频。')]),
            session(f, 'limit', 25, [('user', '这次整理反思我只有18分钟；先做一个能接着改的短提纲。')])]
    ops = [operation(hist, 0, 0, 'reflection-goal', {'goal': 'connect group disagreement with learning theory'}),
           operation(hist, 0, 1, 'long-essay-suggestion', {'suggestion': 'write a complete long essay', 'student_adopted': False}, 'ASSISTANT_SUGGESTION'),
           operation(hist, 1, 0, 'working-preference', {'format': 'two-column comparison', 'avoid': 'video'}),
           operation(hist, 2, 0, 'reflection-budget', {'minutes': 18, 'deliverable': 'short outline'})]
    bh = copy.deepcopy(hist)+[session(f, 'irrelevant', 29, [('user', '我刚给书桌换了一个绿色文件夹，里面只装旅行收据。')])]
    bo = copy.deepcopy(ops)+[operation(bh, 3, 0, 'folder-colour', {'colour': 'green', 'use': 'travel receipts'})]
    cases[f] = [(s, hist, ops), (copy.deepcopy(s), bh, bo)]

    f = 'M02'; s = common_page(f, 'Debate')
    hist = [session(f, 'goal', 20, [('user', '讨论准备先处理我论点中的一个反例，不急着润色措辞。')]),
            session(f, 'budget', 23, [('user', '下次讨论准备我能留出12分钟。'),
                                     ('assistant', '如果方便，我建议留30分钟；目前这只是建议。')])]
    ops = [operation(hist, 0, 0, 'debate-priority', {'priority': 'one counterexample before wording polish'}),
           operation(hist, 1, 0, 'debate-budget', {'minutes': 12}),
           operation(hist, 1, 1, 'suggested-budget', {'minutes': 30, 'student_adopted': False}, 'ASSISTANT_SUGGESTION')]
    bh = copy.deepcopy(hist)+[session(f, 'correction', 29, [('user', '更正之前的12分钟：下次讨论准备改为24分钟，原先的时间安排被替换；优先处理反例不变。')])]
    bo = copy.deepcopy(ops)+[operation(bh, 2, 0, 'debate-budget', {'minutes': 24}, version=2, replaces=1)]
    cases[f] = [(s, hist, ops), (copy.deepcopy(s), bh, bo)]

    f = 'M03'; s = common_page(f, 'Resources')
    hist = [session(f, 'choice', 21, [('user', '我确定以允许学生退出的学习分析仪表板作为设计评析对象，关注点是学生能否理解并拒绝数据使用。')]),
            session(f, 'workflow', 25, [('user', '下次先提醒我已作出的选择；先别替我扩写整篇文章。')])]
    ops = [operation(hist, 0, 0, 'critique-choice', {'object': 'learning analytics dashboard with student opt-out', 'focus': 'understand and refuse data use'}),
           operation(hist, 1, 0, 'workflow', {'request': 'recall previous choice before drafting'})]
    bh = copy.deepcopy(hist)
    bh[0]['messages'][0]['content'] = '设计评析对象和关注点我还没有确定，等我想好再告诉你。'
    bo = [operation(bh, 0, 0, 'choice-state', {'state': 'not yet chosen'}),
          operation(bh, 1, 0, 'workflow', {'request': 'recall previous choice before drafting'})]
    cases[f] = [(s, hist, ops), (copy.deepcopy(s), bh, bo)]

    f = 'P01'; s = common_page(f)
    record(s, 'study-options', 'Reflection', plan('outline-plan', [
        ('read', '读课程反思写作指南', 6, []),
        ('outline', '把一个个人经历与理论连成短提纲', 9, ['read']),
        ('revise', '按提纲修改一段反思并核对依据', 12, ['outline'])], 'USER_SELF_DECLARED_ORDER'))
    record(s, 'study-budget', 'Reflection', {'available_minutes': 35,
                                            'origin': 'SYNTHETIC_USER_SELF_REPORT'})
    cases[f] = [(s, [], []), (copy.deepcopy(s), [], [])]
    cases[f][1][0]['records'][2]['payload']['available_minutes'] = 15

    f = 'P02'; s = common_page(f)
    record(s, 'adopted-study-plan', 'Reflection', plan('example-plan', [
        ('read', '阅读课程关于反思与引用的说明', 8, []),
        ('choose', '选出一个小组讨论例子并标明是谁提出', 7, ['read']),
        ('outline', '写出该例子与课程概念相连的短提纲', 10, ['choose'])], 'USER_SELF_DECLARED_ORDER'))
    record(s, 'study-budget', 'Reflection', {'available_minutes': 25,
                                            'origin': 'SYNTHETIC_USER_SELF_REPORT'})
    record(s, 'resource-progress', 'Resources', {'plan_id': 'example-plan',
                                               'step_id': 'read', 'completed': False,
                                               'origin': 'SYNTHETIC_USER_CHECKLIST'})
    cases[f] = [(s, [], []), (copy.deepcopy(s), [], [])]
    cases[f][1][0]['records'][3]['payload']['completed'] = True

    f = 'P03'; s = common_page(f)
    s['records'][0]['payload']['saved_draft'] = '这个教育聊天助手能很快回复学生，所以我觉得它有教育价值。'
    record(s, 'work-options', 'Reflection', plan('critique-plan', [
        ('read', '读Part B评析问题说明', 5, []),
        ('compare', '对照学习者观点下的一个主张与支持它的证据', 7, ['read']),
        ('revise', '修改一段并写出尚需核实的证据问题', 8, ['compare'])], 'OPTIONS_NOT_A_UNIQUE_REQUIRED_PLAN'))
    record(s, 'resource-progress', 'Resources', {'plan_id': 'critique-plan',
                                               'step_id': 'read', 'completed': True,
                                               'origin': 'SYNTHETIC_USER_CHECKLIST'})
    hist = [session(f, 'goal', 21, [('user', '我选Part B的技术评析，打算从学习者视角评析一个教育聊天助手。别把回复速度直接当成学习效果。')]),
            session(f, 'constraints', 24, [('user', '下次继续这份评析时，我想先用两栏表对照主张和证据，不看视频；最多22分钟。在我更正前先按这个安排。'),
                                          ('assistant', '可以再找同学讨论；这只是可选建议，尚未安排。')])]
    ops = [operation(hist, 0, 0, 'critique-goal', {'option': 'Part B technology critique', 'object': 'educational chatbot', 'perspective': 'learner', 'distinction': 'response speed is not learning effectiveness'}),
           operation(hist, 1, 0, 'critique-constraints', {'format': 'two-column claim/evidence table', 'avoid': 'video', 'minutes': 22}),
           operation(hist, 1, 1, 'peer-suggestion', {'suggestion': 'ask a peer', 'scheduled': False, 'student_adopted': False}, 'ASSISTANT_SUGGESTION')]
    cases[f] = [(s, hist, ops), (copy.deepcopy(s), copy.deepcopy(hist), copy.deepcopy(ops))]
    noise(cases[f][1][0])
    return cases


QUERIES = {
 'E01': ['8月24日至30日，我看了讨论准备的讲座，讲座和讨论衔接到哪一步了？请结合记录指出接下来还可以做什么。']*2,
 'E02': ['只看这门课8月24日至30日，我在资源、讲座、讨论和反思各有多少条活动记录，合计多少？请说明这些次数能说明什么。']*2,
 'E03': ['8月24日至30日，我是不是完全没有修改反思？请结合反思和讲座记录，说明哪些事情能确定、哪些不能。']*2,
 'R01': ['课程手册里Part A算作2500词，是否意味着每周反思加起来不能超过2500词？Part B又怎么计算？',
         '交作业时，前半部分的反思合集有严格的两千五百词上限吗？后半篇文章的篇幅要求和它一样吗？'],
 'R02': ['我想在Part A中采用同组同学提出的一个解释。按课程手册，我应怎样区分同伴的观点和自己的反思？',
         '我想在Part A中采用同组同学提出的一个解释。按课程手册，我应怎样区分同伴的观点和自己的反思？如果还逐字引用一本书，引用形式需要增加哪些信息？'],
 'R03': ['课程反思写作指南列出的Ryan在2011年发表的那篇文章，题名、期刊和页码是什么？',
         '我想按课程反思写作指南列出的Ryan在2011年的那篇文章来练习。请仅根据本课程提供的材料，说明该论文具体如何组织反思写作训练，并列出原文的实施步骤。'],
 'M01': ['按我之前几次说的目标、做法偏好和时间限制，下次整理反思可以从哪一步开始？']*2,
 'M02': ['我下次准备讨论时，最后确认能用多长时间，优先处理哪件事？']*2,
 'M03': ['请提醒我上次已经确定的设计评析对象，以及我打算重点关注什么。']*2,
 'P01': ['我想按草稿里列出的顺序推进反思，用页面上的粗略用时和可用时间，建议我这次做到哪一步。']*2,
 'P02': ['我想继续页面里这份反思计划。请结合资源页的完成记录，说说这次从哪一步做起，时间是否够用。']*2,
 'P03': ['结合我先前选定的作业方向和做法偏好，以及现在的反思草稿和资源进度，建议我下一步怎样改。请用草稿中的用时估计。']*2,
}
PAGE = dict(E01='Lecture', E02='Resources', E03='Lecture', R01='Resources',
            R02='Resources', R03='Resources', M01='Reflection', M02='Debate',
            M03='Resources', P01='Reflection', P02='Reflection', P03='Reflection')
CAPS = {
 'E01':['Evidence','Planning'], 'E02':['Evidence'], 'E03':['Evidence'],
 'R01':['RAG'], 'R02':['RAG'], 'R03':['RAG'], 'M01':['Memory','Planning'],
 'M02':['Memory'], 'M03':['Memory'], 'P01':['Planning','RAG'],
 'P02':['Evidence','Planning','RAG'], 'P03':['Evidence','RAG','Memory','Planning']}
CHANGED = {
 'E01':'仅Debate快照的post_status从DRAFT变成PUBLISHED。',
 'E02':'仅增加三条范围外事件：另一学生、另一课程、窗口前一天。',
 'E03':'仅Reflection覆盖状态COMPLETE变为UNKNOWN；事件列表同为空。',
 'R01':'仅改变同义问题的表述；课程库、当前页与可见历史固定。',
 'R02':'仅在同伴观点归属问题上增加直接引用书籍的格式需求，增加另一段来源。',
 'R03':'同一引文由书目事实改问论文中的具体教学实施步骤；课程库固定。',
 'M01':'仅增加一个旅行文件夹会话及对应无关预置记录。',
 'M02':'仅增加目标前的明确更正会话及替代版本。',
 'M03':'仅把已确定对象与关注点的历史话语替换为尚未确定；相应预置事实改变。',
 'P01':'仅可用时间35变15分钟。',
 'P02':'仅资源页read步骤completed从false变true。',
 'P03':'仅增加三条范围外活动；课程、当前草稿、历史偏好和相关进度固定。'}


def main():
    corpus = [json.loads(x) for x in (HERE/'source_materials/course/corpus.jsonl').read_text().splitlines()]
    chunks = {x['chunk_id']: x for x in corpus}
    cm = json.loads((HERE/'source_materials/course/manifest.json').read_text())
    doc_by_source = {d['source_file_key']:d for d in cm['documents']}
    matrix = json.loads((HERE/'task_spec/FAMILY_MATRIX.json').read_text())
    families = {f['family_id']: f for f in matrix['families']}
    cases = authored_situations()
    runtime = []; refs = []; design = []; catalog = {}
    for family, variants in cases.items():
        for vi, (s, sessions, ops) in enumerate(variants):
            condition = 'AB'[vi]
            tid = opaque('task-', family+condition)
            cid = opaque('context-', family+condition)
            sp = f'source_materials/page_states/{cid}.json'
            hp = f'source_materials/histories/{cid}.json'
            op = f'source_materials/memory_operations/{cid}.jsonl'
            write(sp, s)
            if sessions:
                write(hp, dict(provenance='SYNTHETIC_AUTHORED_DIALOGUE', draft_status=STATUS,
                               student_id=s['scope']['student_id'], course_id=COURSE,
                               scope_policy='read-only prior sessions for this experimental learner and course',
                               target_session_id=opaque('new-session-', cid), target_time=NOW,
                               sessions=sessions))
                jsonl(op, ops)
            catalog[cid] = dict(page_state_path=sp, history_path=hp if sessions else None,
                                memory_operations_path=op if sessions else None)
            visible = []
            if family in ['P01','P02']:
                visible = [dict(role='user', content='页面草稿里的步骤顺序是我选定的，用时只是这次练习的估计。')]
            runtime.append(dict(task_id=tid, query=QUERIES[family][vi], page=PAGE[family],
                                visible_history=visible, scope=s['scope'], query_time=NOW,
                                source_bindings=dict(course_corpus_id='shared-course-v1', context_id=cid)))
            design.append(dict(task_id=tid, family_id=family, condition=condition,
                               primary_capability=families[family]['primary_capability'],
                               design_focus_bucket=family[0], test_type=families[family]['test_type'],
                               changed_factor=CHANGED[family], split='DRAFT_UNASSIGNED',
                               draft_status=STATUS, task_exposure='NEW_AUTHORING_NO_TARGET_OUTPUT_OBSERVED',
                               source_exposure='REUSED_EXPOSED_COURSE_DOMAIN',
                               not_claimed=['independent human authorship','held-out certification','new-document generalisation']))
            def struct(path, pointer, value):
                return dict(kind='STRUCTURED_SOURCE', path=path, json_pointer=pointer, value=value)
            def state_fact(text, pointer, value):
                return dict(fact=text, evidence=[struct(sp, pointer, value)])
            def memory_fact(text, si, mi):
                msg=sessions[si]['messages'][mi]
                return dict(fact=text, evidence=[dict(kind='HISTORY_SPAN',path=hp,
                     json_pointer=f'/sessions/{si}/messages/{mi}/content',
                     session_id=sessions[si]['session_id'], message_id=msg['message_id'],
                     role=msg['role'], char_start=0,char_end=len(msg['content']), quote=msg['content'])])
            def course_fact(text, chunk_id, quote):
                ch=chunks[chunk_id];start=ch['text'].index(quote);d=doc_by_source[ch['source_file']]
                interval=next(x for x in d['native_chunk_intervals'] if x['chunk_id']==chunk_id)
                return dict(fact=text,evidence=[dict(kind='COURSE_SPAN',path='source_materials/course/corpus.jsonl',
                    chunk_id=chunk_id,document_id=d['document_id'],document_version=d['raw_sha256'],
                    origin_raw_path=d['raw_path'],char_start=start,char_end=start+len(quote),quote=quote,
                    readable_path=d['extracted_path'],document_char_start=interval['char_start']+start,
                    document_char_end=interval['char_start']+start+len(quote),
                    offset_unit='Unicode codepoints; extracted text; end exclusive')])
            facts=[]; unknown=['记录和构造用时不证明学习质量、真实学习耗时或效果。']; alternatives=[]; feasibility=None
            availability='NECESSARY_SOURCE_PRESENT'; answerability='SUPPORTED_WITH_STATED_LIMITS'
            if family=='E01':
                facts=[state_fact('本周有一次讲座播放记录，不能据此断定完整观看或掌握。','/events/0',s['events'][0]),
                       state_fact('讨论草稿已保存；发布状态为'+s['records'][0]['payload']['post_status']+'。','/records/0/payload',s['records'][0]['payload'])]
                alternatives=['A可建议核对并发布草稿；B可建议阅读回应或检查论据。无需固定措辞或唯一步骤。']
                unknown+=['播放时长、理解程度、讨论内容质量和同伴回应均未知。']
            elif family=='E02':
                facts=[state_fact('范围内恰有2次资源访问、1次播放、1次发布、1次编辑，共5条不同类型活动。','/events',s['events']),
                       state_fact('汇总范围由student/course及半开时间窗口共同限定。','/scope',s['scope'])]
                alternatives=['可以分项陈述；不得把不同活动类型解释成可比较的投入或把Overview再计一次。']
            elif family=='E03':
                facts=[state_fact('讲座有一次播放。','/events/0',s['events'][0]),
                       state_fact('Reflection覆盖状态是'+s['coverage']['Reflection']['status']+'。','/coverage/Reflection',s['coverage']['Reflection']),
                       state_fact('所提供事件流中没有Reflection编辑事件。','/events',s['events'])]
                if vi:
                    availability='OBSERVATION_COVERAGE_UNKNOWN_BY_DESIGN';answerability='PARTIAL_UNKNOWN_REFLECTION_ACTIVITY'
                    unknown+=['Reflection窗口覆盖未知，不能把空列表补成实际零编辑。']
                else: alternatives=['可说在完整覆盖的构造记录窗口中编辑数为0；不把零编辑等同零思考。']
            elif family=='R01':
                facts=[course_fact('Part A按2500词等值计，反思实际总词数可以超过2500；Part B长度为2500词。','handbook_overview',
                    'Part A will be considered equivalent to 2500 words (not equal to, so your individual reflections can add up to more than 2500 words). Part B will be equal to 2500 words in length.'),
                    course_fact('手册对总作业规定5000词上下10%；不能把Part A等值偷换为其实际词数上限。','handbook_overview',
                    'Following the IOE policy, your assignment should be 5000 words +/- 10%.')]
                unknown+=['仅引用这份已存档手册，不外推为当前年度政策或另造Part A上限。']
            elif family=='R02':
                facts=[course_fact('讨论引发的反思应体现个人分析；若采用他人的评论或反思，须明确归属。',
                    'handbook_part_a_critical_analysis_and_reflection_portfolio',
                    'However, the reflection of these discussions in relation to how they advance digital learning design should be your own . If you include comments and reflections made by others in the group, you must reference them as such explicitly.')]
                if vi:
                    facts.append(course_fact('直接引文须加引号，正确给出作者、日期和页码。',
                     'handbook_referencing_plagiarism_1',
                     "All direct quotations from another author's work must be placed in quotation marks and cited correctly by providing the author name, date, and page number."))
                alternatives=['可用简短归属句说明是谁提出的观点，再清楚分开个人分析；不要求唯一引用句式。']
            elif family=='R03':
                facts=[course_fact('指南仅给出Ryan 2011的书目条目：Improving reflective writing in higher education: a social semiotic perspective；Teaching in Higher Education 16(1),99–111。',
                     'handbook_the_core_elements_of_academic_reflective_writing_3',
                     'Ryan, M., 2011. Improving reflective writing in higher education: a social semiotic perspective. Teaching in Higher Education, 16(1), 99-111.')]
                if vi:
                    availability='ASKED_FACT_ABSENT_FROM_FIXED_CORPUS';answerability='NO_ANSWER_FOR_REQUESTED_ARTICLE_PROCEDURE'
                    unknown+=['固定语料没有该论文全文或论文中的具体实施步骤；这是引文入口边界，不是检索失败。']
                    alternatives=['说明只给出引文及课程本身的写作指南，可提供明确标为课程指南的一般建议，不能声称是Ryan论文的具体操作步骤。']
            elif family=='M01':
                facts=[memory_fact('目标是把小组分歧联系到学习理论。',0,0),memory_fact('偏好两栏表且暂时不看视频。',1,0),
                       memory_fact('预算18分钟，先产出短提纲。',2,0),memory_fact('完整长文只是assistant建议，未被学生采纳。',0,1)]
                alternatives=['从选一个分歧、填两栏对应、提炼短提纲中提出有限步骤；不强制具体分钟拆分。']
            elif family=='M02':
                facts=[memory_fact('优先处理一个反例，而非润色。',0,0),
                       memory_fact('最后确认时间为'+('24' if vi else '12')+'分钟。',2 if vi else 1,0),
                       memory_fact('30分钟是assistant建议，不是学生确认预算。',1,1)]
                if vi: unknown+=['旧12分钟记录保留在来源中，但在更正后不能复活为当前预算。']
            elif family=='M03':
                facts=[memory_fact('历史中'+('尚未确定对象和关注点。' if vi else '已确定可退出的学习分析仪表板，关注理解和拒绝数据使用。'),0,0),
                       memory_fact('只要求提醒已作决定，不要扩写整篇。',1,0)]
                if vi:
                    availability='TARGET_FACT_NEVER_PROVIDED_IN_COMPLETE_HISTORY';answerability='CLARIFICATION_NEEDED'
                    unknown+=['仍需要读取历史核对；needs_memory=true不因事实未提供而改为false。']
                    alternatives=['指出所给完整历史尚无已确认对象/关注点，请学生补充。']
            elif family in ['P01','P02','P03']:
                pi=1
                p=s['records'][pi]['payload']
                facts=[state_fact('这些步骤及用时是受控情境中的估计，所有步骤属于同一个计划。',f'/records/{pi}/payload',p)]
                if family=='P01':
                    budget=s['records'][2]['payload']['available_minutes']; completed=[]
                    selected=['read','outline','revise'] if not vi else ['read','outline']
                    facts.append(state_fact('可用时间为'+str(budget)+'分钟。','/records/2/payload/available_minutes',budget))
                    facts.append(course_fact('反思写作需要分析、论证及经历/文献证据。','handbook_the_core_elements_of_academic_reflective_writing_1',
                      'Academic reflective writing requires critical and analytic thought, a clear line of argument, and the use of evidence through examples of personal experiences and thoughts and often also theoretical literature.'))
                    if vi: answerability='FULL_GOAL_INFEASIBLE_BUT_PARTIAL_PLAN_FEASIBLE'
                elif family=='P02':
                    budget=25;completed=['read'] if vi else [];selected=['choose','outline'] if vi else ['read','choose','outline']
                    facts += [state_fact('资源页read完成状态为'+str(bool(vi))+'。','/records/3/payload',s['records'][3]['payload']),
                              state_fact('可用时间25分钟。','/records/2/payload/available_minutes',25),
                              course_fact('小组观点须明确引用，个人分析仍应由本人完成。','handbook_part_a_critical_analysis_and_reflection_portfolio',
                                'If you include comments and reflections made by others in the group, you must reference them as such explicitly.')]
                else:
                    budget=22;completed=['read'];selected=['compare','revise']
                    facts += [state_fact('当前草稿把回复快作为教育价值理由，缺少学习效果证据。','/records/0/payload/saved_draft',s['records'][0]['payload']['saved_draft']),
                              state_fact('资源页标记说明阅读已完成。','/records/2/payload',s['records'][2]['payload']),
                              memory_fact('选定Part B技术评析及学习者视角；不能把速度等同学习效果。',0,0),
                              memory_fact('两栏主张/证据，不看视频，最多22分钟。',1,0),
                              memory_fact('与同学讨论只是未安排的assistant建议。',1,1),
                              course_fact('手册要求审视技术的理论基础、设计/评价证据及证据可信度。','handbook_part_b_design_case_extension_or_design_critique_3',
                                'What evidence is there of the educational value claimed? To what extent can we trust the evidence presented?')]
                steps={x['step_id']:x for x in p['steps']}
                total=sum(x['estimated_minutes'] for x in p['steps'] if x['step_id'] not in completed)
                used=sum(steps[x]['estimated_minutes'] for x in selected)
                feasibility=dict(plan_source_path=sp,plan_pointer=f'/records/{pi}/payload',
                     budget_minutes=budget,already_completed=completed,one_feasible_sequence=selected,
                     estimated_minutes=used,remaining_goal_minutes=total,
                     full_goal_fits_budget=total<=budget,slack_minutes=budget-used,
                     proof_scope='Arithmetic and dependencies under declared estimates only; not learning efficacy or unique correct prose.')
                alternatives=['任何遵守依赖、已完成状态、预算和已知偏好的合理部分或完整方案均可；参考序列不是唯一答案。']
            refs.append(dict(task_id=tid, draft_status=STATUS, family_id=family, condition=condition,
                 expected_capabilities_design_only=CAPS[family], source_availability_truth=availability,
                 source_material_file_status='PRESENT_AND_VALIDATED', retrieval_outcome='NOT_EXECUTED',
                 answerability_design=answerability, required_facts=facts, unknowns=unknown,
                 acceptable_alternatives=alternatives, feasibility_witness=feasibility,
                 pair_behavior=families[family]['expected_behavior_not_model_score'],
                 applicability_by_criterion={k:None for k in CRITERIA},
                 applicability_shared_across_modes=True,
                 human_review={k:None for k in ['source_sufficiency','question_naturalness','final_inclusion','reviewer_id','score','rationale','signature']}))
    # Original queries are parsed without stripping whitespace or manufacturing sessions.
    raw=(HERE/'legacy_only/Example Conversation Data(5).csv').read_bytes()
    original=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline='')))
    jsonl('legacy_only/source_messages_50.jsonl',[dict(source_record_number=i+1,**r) for i,r in enumerate(original)])
    jsonl('legacy_only/old_assistant_targets_NOT_GOLD.jsonl',[
        dict(source_record_number=i+1,**r) for i,r in enumerate(original) if r['role']=='assistant'])
    original_missing=[
      '该问题对应的原页面数值、学生绑定及观察窗口。',
      '原系统assessment views指标定义及适用事件口径。',
      '邮件订阅读取是否被该版本系统采集的来源契约。',
      '原始未完成任务清单、截止日期、未来10天可用时间及原提问日期。',
      'this所指建议与原学生数据；不得由上一行助手答案拼接。',
      '资源进度、已知用时和可用时间。',
      '原资源数据与this所指建议。',
      '原记录与录播/直播采集类型的确切绑定。',
      'it/feedback所指反馈、反思正文及评价依据。',
      '原Resources_views指标值、累计/分期范围和计算定义。',
      '原Resources_views计算定义及采集事件口径。',
      '原反思字符串/字数值、字段单位、正文与范围。',
      '原反思正文及其每周题目；课程写作指南可供通用建议。',
      '原week4提交凭证、原查询时间、页面更新时点；只保留学生当前自述。',
      '原讨论帖子内容、参与记录及活动要求。',
      '原资源页记录及所指具体活动。',
      'this aspect指代及原讨论记录/正文。',
      '原反思正文、评价标准与this aspect指代。',
      '原讨论数据采集契约及系统版本。',
      '邮件阅读可见性契约；无可靠前文session映射。',
      '原跨页活动事实、目标与限制。',
      '编号2和3所指原建议及真实会话映射。',
      '该反思的题目与正文；课程反思写作指南可提供一般结构依据。',
      '原课程/周次绑定及W4录播正文；现有元数据不等于全文。',
      'the full lecture所指录播身份、访问许可及可用全文。']
    roster=[]; qi=0
    for ri,row in enumerate(original):
        if row['role']!='user': continue
        qi+=1;tid=f'original-{qi:02}'
        current=dict(task_id=tid,query=row['message'],page=row['graph'],visible_history=[],
                     scope=dict(student_id=None,course_id=None,window_start=None,window_end=None),
                     query_time=None,source_bindings=dict(course_corpus_id='shared-course-v1',context_id=None))
        runtime.insert(qi-1,current)
        roster.append(dict(task_id=tid,source_record_number=ri+1,page=row['graph'],query=row['message'],
            query_utf8_sha256=digest(row['message'].encode()),query_utf8_bytes=len(row['message'].encode()),
            trailing_whitespace_characters=len(row['message'])-len(row['message'].rstrip()),
            source_csv_sha256=digest(raw),exposure='EXPOSED_LEGACY_ANCHOR',layer='LEGACY_ANCHOR_25',
            original_identity='UNKNOWN',original_session='UNKNOWN',original_timestamp='UNKNOWN',
            contextualisation='ORIGINAL_QUERY_ONLY_CONTEXT_NOT_RECOVERED',
            source_status='ORIGINAL_CONTEXT_MISSING',missing_material=original_missing[qi-1],
            available_material='Exact original question/page; archived shared course corpus for general guidance only, without original course linkage.',
            human_review=None))
        available=[]
        if qi in [13,23]:
            available=[course_fact('归档课程指南可支撑一般反思结构建议；不能认证为该学生原反思要求。',
               'handbook_the_core_elements_of_academic_reflective_writing_1',
               'Academic reflective writing requires critical and analytic thought, a clear line of argument, and the use of evidence through examples of personal experiences and thoughts and often also theoretical literature.')]
        refs.insert(qi-1,dict(task_id=tid,draft_status=STATUS,layer='LEGACY_ANCHOR_25',
            required_facts=available,source_availability_truth='ORIGINAL_CONTEXT_MISSING',
            source_material_file_status='ORIGINAL_QUERY_PRESENT_CONTEXT_NOT_RECOVERED',
            answerability_design='UNRESOLVED_ORIGINAL_CONTEXT',retrieval_outcome='NOT_EXECUTED',
            unknowns=[original_missing[qi-1]],acceptable_alternatives=['可说明缺失并请求具体上下文；不从旧目标答案制造事实。'],
            applicability_by_criterion={k:None for k in CRITERIA},applicability_shared_across_modes=True,
            human_review={k:None for k in ['source_sufficiency','question_naturalness','final_inclusion','reviewer_id','score','rationale','signature']}))
    jsonl('original25_roster.jsonl',roster)
    jsonl('runtime_tasks.jsonl',runtime)
    jsonl('evaluation_reference.jsonl',refs)
    write('family_design.json',dict(status=STATUS,final_sample_size=None,
        split_rule='Both conditions of a family stay together; DRAFT_UNASSIGNED is not held-out certification.',tasks=design))
    write('source_materials/catalog.json',dict(course_corpora={'shared-course-v1':'source_materials/course/corpus.jsonl'},contexts=catalog))
    write('human_review/task_review_blank.json',dict(status='NOT_REVIEWED',
        items=[dict(task_id=x['task_id'],source_review=None,naturalness_review=None,final_inclusion=None,
                    applicability={k:None for k in CRITERIA},reviewer_id=None,rationale=None,signature=None)
               for x in runtime],final_sample_size=None,multi_page_observation_design=None))
    write('audit/COUNTS.json',dict(original_queries=len(roster),original_messages=len(original),
        old_assistant_messages=sum(r['role']=='assistant' for r in original),new_queries=len(design),
        families=len(cases),runtime_tasks=len(runtime),course_source_documents=len(cm['documents']),
        ordinary_corpus_chunks=len(corpus),page_state_files=len(catalog),
        history_files=sum(bool(v['history_path']) for v in catalog.values()),
        stored_session_occurrences=sum(len(h) for vs in cases.values() for _,h,_ in vs),
        unique_historical_sessions=len({h['session_id'] for vs in cases.values() for _,hs,_ in vs for h in hs}),
        memory_operation_occurrences=sum(len(o) for vs in cases.values() for _,_,o in vs),
        feasibility_witnesses=sum(bool(r.get('feasibility_witness')) for r in refs),
        final_sample_size=None,provider_calls=0,p3_calls=0,candidate_final_calls=0,
        judge_calls=0,human_scores_filled=0,target_retriever_calls=0,native_memory_reads=0))
    print(json.dumps(json.loads((HERE/'audit/COUNTS.json').read_text()),ensure_ascii=False))


if __name__=='__main__':
    main()
