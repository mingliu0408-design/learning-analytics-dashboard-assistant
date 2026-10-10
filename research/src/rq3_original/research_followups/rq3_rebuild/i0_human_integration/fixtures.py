"""Explicit SYNTHETIC / EXPOSED DEVELOPMENT sources; no human or held-out data."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from utils.c4_dashboard_scoped.scope import Snapshot, SourceSpec, Coverage, Calendar, Scope
from utils.c4_rebuild.contracts import Request, Mode, Access
from utils.c4_real_contracts import P3CapabilityRoute
from utils.c4_rebuild.memory import NativeM1, m1_dependencies

FLAGS = ['SYNTHETIC_DEVELOPMENT_FIXTURE', 'MODEL_AUTHORED', 'NOT_FOR_INDEPENDENT_TEST']
START = '2026-08-31T00:00:00+02:00'
END = '2026-09-07T00:00:00+02:00'
NOW = '2026-09-02T12:00:00+02:00'
LEARNER = 'synthetic-learner-a'
COURSE = 'synthetic-course-maths'


def snapshot(tables=None, specs=None, learner_id=LEARNER, course_id=COURSE):
    fixture = json.loads((HERE.parent/'e1_five_page/SYNTHETIC_FIXTURE.json').read_text())
    mapping = {'SYN_A': learner_id, 'SYN_B': 'synthetic-learner-b', 'COURSE_A': course_id, 'COURSE_B': 'synthetic-course-other'}
    rows = {k: [{a: mapping.get(v, v) if isinstance(v, str) else v for a, v in row.items()} for row in values]
            for k, values in fixture['tables'].items()}
    from utils.c4_dashboard_scoped.aggregate import aggregate
    metrics = ('resource_views', 'video_clicks', 'video_views', 'mean_view_percent',
        'debate_posts', 'debate_replies', 'debate_views', 'edited_characters',
        'network_replies_sent', 'network_replies_received', 'network_replies_unique_sent', 'network_replies_unique_received',
        'network_views_sent', 'network_views_received', 'network_views_unique_sent', 'network_views_unique_received',
        'goals_record_count', 'reflections_record_count')
    specifications = {}
    for name, cols in fixture['columns'].items():
        specifications[name] = SourceSpec(tuple(cols), course_column='Course',
            observation='timestamp' if name=='moodle' else 'cumulative' if name=='features' else 'week',
            time_column='Time' if name=='moodle' else None,
            week_column='Observation_week' if name=='echo' else 'week' if 'network' in name else 'Week',
            calendar_version='I0_SYNTHETIC_CALENDAR', item_column='Item_ID' if name in ('echo', 'moodle') else None,
            event_id_column='Event_ID' if 'Event_ID' in cols else None,
            coverage=(Coverage((learner_id, 'synthetic-learner-b'), course_id, START,
                '2026-09-14T00:00:00+02:00', metrics, 'EXPLICIT_SYNTHETIC_COMPLETE_COLLECTION'),))
    specifications.update(specs or {})
    cal = Calendar('I0_SYNTHETIC_CALENDAR', 'Europe/Oslo', {1:(START, END), 2:(END, '2026-09-14T00:00:00+02:00')})
    return Snapshot('I0_SYNTHETIC_SNAPSHOT', rows if tables is None else tables, specifications,
        {learner_id:(course_id,), 'synthetic-learner-b':(course_id,)}, {course_id:cal}, 'SYNTHETIC')


def request(mode=Mode.S5_FULL, **kw):
    snap = snapshot()
    defaults = dict(scope=Scope(LEARNER, COURSE, snap.version, START, END, 'Europe/Oslo', 'I0_SYNTHETIC_CALENDAR'),
        query='Summarise my learning this week.', page='Lecture', as_of=NOW,
        session_id='I0_SYNTHETIC_VISIBLE_SESSION', mode=mode, future_policy='RECONFIRM_FOR_SCHEDULE',
        history=({'role':'user', 'content':'Use recorded counts carefully.'},),
        access=Access(True, True, True, 'EXPLICIT_SYNTHETIC_TEST_PERMISSION'),
        memory_state_version='I0_SYNTHETIC_NATIVE_STATE', source_version='I0_SYNTHETIC_CORPUS')
    defaults.update(kw)
    return Request(**defaults)


class SyntheticRouter:
    """Clearly named route stub. No observed P3 prediction or accuracy claim."""
    def __init__(self, rag=True, memory=True, planning=True):
        self.bits = (rag, memory, planning)
        self.inputs = []

    def route(self, primary_input):
        self.inputs.append(primary_input.to_payload())
        return P3CapabilityRoute(*self.bits, provider_identity='SYNTHETIC_ROUTE_STUB_NO_P3_INFERENCE')


def memory_source(index, directory, *, target_as_of=NOW, backend=None, expand=True, change=None):
    cases = json.loads((HERE.parent/'m1_memory_completeness/fixtures/linked_runtime_v1.json').read_text())
    case = deepcopy(cases[index])
    case['target']['as_of'] = target_as_of
    if change:
        change(case)
    _, compile_sidecar, _ = m1_dependencies()
    from state_harness import setup_episode
    dbs, aliases, receipts = setup_episode(case, Path(directory)/'setup')
    graph, rejections = compile_sidecar(case, dbs, aliases)
    adapter = NativeM1(dbs, graph, {x['turn_id']:x for x in case['source_turns']}, backend=backend, expand=expand)
    return adapter, dict(setup_receipts=receipts, relation_rejections=rejections, source_case=case)


def explicit_minutes_source(case):
    """New synthetic natural-language source event, not a hidden expected field."""
    text = 'I have 15 minutes.'
    op = next(x for x in case['setup_operations'] if x.get('memory_type')=='CONSTRAINT')
    op.update(content=text, evidence_span=text, source_span_chars=[0,len(text)])
    turn = next(x for x in case['source_turns'] if x['turn_id']==op['source_turn_id'])
    turn['content'] = text
    from relations import assertion_text
    from author_linked_fixtures import seal
    content = {x['fact_id']:x['content'] for x in case['setup_operations'] if 'content' in x}
    for e in case['relation_events']:
        a = e['annotation']
        e['content'] = assertion_text(a['relation_type'], content[a['from_fact']], content[a['to_fact']])
        a['span_chars'] = [0,len(e['content'])]
        seal(e)


def rag_source(empty=False,course_id=COURSE):
    from utils.c4_rebuild.rag import R0OnExplicitCorpus, ProvisionalR0
    from utils.course_material_retriever import CourseChunk
    # Runtime source text is newly invented instructional content.
    chunk = CourseChunk(chunk_id='I0_SYNTHETIC_COURSE_CHUNK', text='Synthetic lecture maths worksheet: compare the two quadratic solutions and check each solution by substitution. Write the intermediate expressions, explain the difference, and compare your reasoning with the worked example.',
        source_file='SYNTHETIC_LOCAL_SOURCE', source_type='weekly_page', title='Synthetic quadratic lecture maths worksheet',
        week='W1', task_type='lecture', metadata={'section_title':'Synthetic source paragraph 1'})
    scorer = R0OnExplicitCorpus([] if empty else [chunk])
    return ProvisionalR0(scorer, course_id=course_id, source_version='I0_SYNTHETIC_CORPUS',
                         expected_corpus_sha256=scorer.corpus_hash, source_window=(START, END))
