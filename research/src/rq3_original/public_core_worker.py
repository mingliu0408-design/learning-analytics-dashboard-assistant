"""Public JSON boundary for the recovered original LAD core.

All original M1 imports and its process-wide network guard stay in this child.
Only allowlisted source roots are used; no evaluator, Gold or credentials enter.
"""
from pathlib import Path
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import sys
import tempfile

CORE = Path(__file__).resolve().parent
PROJECT = CORE.parents[2]
DATA = PROJECT / 'data'
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE / 'experiments/rq3_original25_plus_review_r1'))
import adapter as original
from utils.c4_rebuild.contracts import Request, Access, Mode, POLICIES, reject_sidecars
from utils.c4_dashboard_scoped.scope import instant, digest
from utils.c4_memory.c4_memory_store import C4MemoryStore
from utils.c4_memory.c4_memory_writer import C4MemoryWriter, StructuredMemoryCandidate
from utils.c4_rebuild.memory import clone_native_states, m1_dependencies
from utils.c4_rebuild.i1.memory import I1NativeM1
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from utils.c4_rebuild.i1.schemas import errors
from utils.c4_rebuild.i1.renderer import material
from utils.course_material_retriever import CourseChunk

ROLE_CONFIG = dict(model='gpt-4o-mini-2024-07-18',temperature=0,max_output_tokens=2048)

def load(path):
    return json.loads(Path(path).read_text())

def public_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('PUBLIC_SOURCE_PATH_BOUNDARY')
    return path

def task_for(message):
    if message['task_id'].startswith('dashboard-'):
        sys.path.insert(0,str(PROJECT))
        from public_runtime.dashboard import validate_context, source_selection
        context=validate_context(message.get('dashboard_context'),message['task_id'])
        selected=source_selection(context)
        s=selected['scope']
        task=dict(task_id=message['task_id'],query=message.get('query','Inspect the selected dashboard'),
            page=message.get('page','Overview'),visible_history=deepcopy(message.get('history',[])),
            query_time=message.get('request_time',__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()),
            scope=dict(student_id=s['learner_id'],course_id=s['course_id'],window_start=s['start'],window_end=s['end']),
            source_bindings=dict(course_corpus_id='PUBLIC_AUTHORIZED_COURSE',context_id=context['task_id']))
        original.source_guard(task)
        task['_dashboard_selection']=selected
        return task
    if message.get('dashboard_context') is not None:raise ValueError('DASHBOARD_CONTEXT_ON_RESEARCH_TASK')
    rows = [json.loads(x) for x in (DATA/'replay/runtime_tasks.jsonl').read_text().splitlines()]
    task = deepcopy(next(t for t in rows if t['task_id']==message['task_id']))
    if message.get('query') is not None:
        task['query'] = message['query']
        task['page'] = message.get('page',task['page'])
        task['visible_history'] = deepcopy(message.get('history', []))
        task['query_time'] = message['request_time']
    original.source_guard(task)
    return task

class DashboardPages:
    """Use the original scoped raw aggregator; no frozen task projection."""
    origin='LIVE'
    def __init__(self,task):
        from utils.c4_dashboard_scoped.scope import Snapshot, SourceSpec, Calendar, Scope
        from utils.c4_dashboard_scoped.aggregate import aggregate
        selected=task['_dashboard_selection']
        self.task=task
        self.scope=Scope(**selected['scope'])
        self.raw_snapshot=Snapshot(self.scope.snapshot,
            tables={k:tuple(v) for k,v in selected['tables'].items()},
            specs={k:SourceSpec(**v) for k,v in selected['specs'].items()},
            roster=selected['roster'],calendars={self.scope.course_id:Calendar(**selected['calendar'])},origin='LIVE')
        self.bundle=aggregate(self.raw_snapshot,self.scope)
        self.accepted_pointers=[f'source://dashboard/{table}/row/{n}'
            for table,slice_ in self.bundle.slices.items() for n,_ in slice_.rows]
        self.excluded_pointers=['OTHER_LEARNER_COURSE_OR_OUT_OF_WINDOW_ROWS_EXCLUDED_BEFORE_AGGREGATION']
    def validate_query(self,scope,query,now):
        if scope!=self.scope:raise ValueError('DASHBOARD_SCOPE_CHANGED')
        self.raw_snapshot.validate_query(scope,query,now)
    def chart_context(self,value):
        value=deepcopy(value)
        chosen=self.task['_dashboard_selection']['context']
        if 'Reflection' in value.get('activity',{}):
            value.update(deepcopy(self.task['_dashboard_selection']['chart_contexts']['Reflection']))
        value['chart_controls']=dict(
            observation_buckets=[f'Week {w}' for w in range(chosen['week_start'],chosen['week_end']+1)],
            item_selection='Explicitly selected recording item: '+chosen['lecture_item_id'] if chosen['lecture_item_id'] else 'No item selected.',
            temporal_basis='Historical observation week buckets, not current learner availability.')
        return value
    def context(self,domains):
        return self.chart_context(self.bundle.visible(domains[0]) if len(domains)==1 else self.bundle.context(domains))
    def overview(self):return self.chart_context(self.bundle.context(original.DOMAINS))
    def visible(self,page):return self.chart_context(self.bundle.visible(page))


def snapshot_for(task):
    if '_dashboard_selection' in task:return DashboardPages(task)
    tid = task['task_id']
    if tid.startswith('original-'):
        snapshot = object.__new__(original.ReplayPages)
        snapshot.task = deepcopy(task)
        snapshot.pages = load(DATA/'replay/source_materials/original25/PAGE_SOURCES.json')['pages']
        original.source_guard(snapshot.pages)
        snapshot.accepted_pointers=['/pages/'+d for d in original.DOMAINS]
        snapshot.excluded_pointers=[]
        return snapshot
    catalog = load(DATA/'replay/source_materials/catalog.json')
    entry = catalog['contexts'][task['source_bindings']['context_id']]
    path = public_path(DATA/'replay',entry['page_state_path'])
    raw = load(path)
    # Current request time filters historical events; their timestamps/windows
    # are preserved. This is a read-time projection, never a changed source file.
    raw['source_snapshot_as_of'] = raw['as_of']
    raw['as_of'] = task['query_time']
    initialize = original.clone_function(original.Pages.__init__, {'read':lambda p:deepcopy(raw)})
    snapshot = object.__new__(original.Pages)
    initialize(snapshot,task,{'page_state_path':str(path)})
    return snapshot

def request_for(task, message):
    s = task['scope']
    corpus = DATA/'course/corpus.jsonl'
    options = message.get('controls') or {}
    if '_dashboard_selection' in task:
        from utils.c4_dashboard_scoped.scope import Scope
        scope=Scope(**task['_dashboard_selection']['scope'])
    else:scope=original.TaskScope(s['student_id'],s['course_id'],s['window_start'],s['window_end'],timezone='UTC' if s['window_start'] else None)
    return Request(scope=scope,
        query=task['query'],page=task['page'],as_of=task['query_time'],session_id=message['session_id'],mode=Mode(message.get('mode','S5_FULL')),
        history=tuple(task['visible_history']),future_policy='WARN_SNAPSHOT_ONLY',
        access=Access(True,True,True,'EXPLICIT_PUBLIC_VISITOR_REQUEST'),
        source_version=hashlib.sha256(corpus.read_bytes()).hexdigest(),memory_state_version='SESSION_LOCAL_NATIVE_STATE',
        task_intent=options.get('task_intent'),memory_purpose=options.get('memory_purpose'),
        visible_controls='PUBLIC_EXPLICIT_CONTROLS' if options else None,
        schedule_timezone=options.get('schedule_timezone'),allowed_windows=tuple(options.get('allowed_windows') or ()),schedule_horizon=options.get('schedule_horizon'))

def primary_for(task,snapshot,request):
    scoped=original.build_request(snapshot=snapshot,scope=request.scope,query=request.query,page=request.page,messages=request.history,session_id=request.session_id,now=instant(request.as_of))
    if isinstance(snapshot,DashboardPages):
        scoped=replace(scoped,dashboard_context=snapshot.visible(request.page))
    primary=scoped.primary_input.to_payload()
    result=dict(primary=primary,primary_sha256=digest(primary),clarification=original.FrozenClarificationGateAdapter().evaluate(scoped.primary_input).needs_clarification)
    if '_dashboard_selection' in task:
        result.update(dashboard_selection=task['_dashboard_selection']['context'],scope=task['_dashboard_selection']['scope'],
            source_hashes=task['_dashboard_selection']['source_hashes'],temporal_boundary=task['_dashboard_selection']['temporal_boundary'])
    return result

def workspace(message):
    path=Path(message['workspace']).resolve()
    if path.name != message['session_id'] or not message['session_id'].isalnum():
        raise ValueError('SESSION_WORKSPACE_IDENTITY')
    path.mkdir(parents=True,exist_ok=True)
    return path

def session_memory(task,message):
    """Clone the actual immutable seed into a separate task/session database."""
    import sqlite3
    root=workspace(message)/hashlib.sha256(task['task_id'].encode()).hexdigest()[:16]
    root.mkdir(exist_ok=True)
    db=root/'memory.sqlite'
    seed=DATA/'replay/native_initial'/task['task_id']
    dashboard='_dashboard_selection' in task
    if dashboard and not db.exists():
        with C4MemoryStore(db,clock=lambda:task['query_time']) as store:
            assert store.list_active_memories(task['scope']['student_id'])==[]
    if not db.exists():
        with sqlite3.connect((seed/'initial.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(db) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('SEED_INTEGRITY')
    graph_path=root/'visitor_graph.json'
    empty_graph=dict(version='M1_RELATIONS_V1',nodes={},source_events={},edges=[])
    empty_graph['sha256']=digest(empty_graph)
    graph=load(graph_path) if graph_path.exists() else (empty_graph if dashboard else load(seed/'graph.json'))
    events={} if dashboard else load(seed/'source_events.json')
    additions=root/'visitor_events.json'
    if additions.exists(): events.update(load(additions))
    return db,graph,events,additions

def atomic_json(path,value):
    import os
    temporary=path.with_name(path.name+'.new')
    temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False))
    os.replace(temporary,path)

def receipt_directory(message):
    directory=workspace(message)/'runtime_receipts'
    directory.mkdir(exist_ok=True)
    return directory


def receipt_binding(task,request,source):
    return dict(session_id=request.session_id,task_id=task['task_id'],
        learner_id=request.scope.learner_id,course_id=request.scope.course_id,
        scope=request.scope.internal(),primary_sha256=source['primary_sha256'])


def save_runtime_receipt(message,task,request,source,prepared):
    """Server-owned preparation; callers cannot replace it with another session's JSON."""
    import uuid
    token=uuid.uuid4().hex
    record=dict(version='PUBLIC_SERVER_PREPARATION_V1',binding=receipt_binding(task,request,source),
        prepared=deepcopy(prepared),prepared_sha256=digest(prepared))
    atomic_json(receipt_directory(message)/(token+'.json'),record)
    return token


def load_receipt(message,key,version):
    import re
    token=message.get(key)
    if not isinstance(token,str) or re.fullmatch(r'[0-9a-f]{32}',token) is None:
        raise ValueError('SESSION_RUNTIME_RECEIPT_REQUIRED')
    path=receipt_directory(message)/(token+'.json')
    if not path.is_file() or path.is_symlink():raise ValueError('SESSION_RUNTIME_RECEIPT_NOT_FOUND')
    record=load(path)
    if record.get('version')!=version:raise ValueError('SESSION_RUNTIME_RECEIPT_KIND_MISMATCH')
    return token,record


def verified_preparation(message,task,request,source):
    token,record=load_receipt(message,'runtime_receipt','PUBLIC_SERVER_PREPARATION_V1')
    if record['binding']!=receipt_binding(task,request,source):
        raise ValueError('SESSION_RUNTIME_RECEIPT_SCOPE_MISMATCH')
    prepared=record['prepared']
    if record['prepared_sha256']!=digest(prepared) or message.get('prepared')!=prepared:
        raise ValueError('SESSION_PREPARATION_CHANGED')
    return token,prepared


def save_candidate_receipt(message,task,request,source,preparation_token,candidate):
    import uuid
    token=uuid.uuid4().hex
    record=dict(version='PUBLIC_SERVER_CHECKED_CANDIDATE_V1',binding=receipt_binding(task,request,source),
        runtime_receipt=preparation_token,plan=deepcopy(candidate),plan_sha256=digest(candidate))
    atomic_json(receipt_directory(message)/(token+'.json'),record)
    return token


def verified_candidate(message,task,request,source,plan,preparation_token):
    _,record=load_receipt(message,'candidate_receipt','PUBLIC_SERVER_CHECKED_CANDIDATE_V1')
    if record['binding']!=receipt_binding(task,request,source) or record['runtime_receipt']!=preparation_token:
        raise ValueError('SESSION_CANDIDATE_RECEIPT_SCOPE_MISMATCH')
    if record['plan_sha256']!=digest(plan) or record['plan']!=plan:
        raise ValueError('SESSION_CHECKED_PLAN_CHANGED')
    return record


def native_fact(store,request,graph,events,content,memory_type,turn_suffix):
    """An explicit UI confirmation becomes USER source, never a SYSTEM event."""
    turn='visitor-'+digest(dict(session=request.session_id,time=request.as_of,content=content,type=memory_type,suffix=turn_suffix))[:24]
    candidate=StructuredMemoryCandidate.from_mapping(dict(operation='ADD',memory_type=memory_type,content=content,target_memory_id=None,confidence=1.0,evidence_span=content))
    result=C4MemoryWriter(store).apply_candidate(student_id=request.scope.learner_id,
        source_session_id=request.session_id,source_turn_id=turn,source_text=content,candidate=candidate,
        source_role='USER',claim_basis='EXPLICIT_USER_STATEMENT',consent_status='GRANTED',
        event_at=request.as_of,valid_from=request.as_of,valid_to=None).as_dict()
    if not result['accepted']:raise ValueError('NATIVE_WRITE_REJECTED:'+result['reason_code'])
    rec=result['record']
    events[turn]=dict(learner_id=request.scope.learner_id,course_id=request.scope.course_id,
        session_id=request.session_id,turn_id=turn,role='USER',content=rec['content'],timestamp=request.as_of)
    graph['nodes'][rec['memory_id']]=dict(native_id=rec['memory_id'],native_version=rec['version'],
        content_sha256=rec['content_sha256'],memory_type=rec['memory_type'],learner_id=rec['student_id'],
        course_id=request.scope.course_id,source_ref=dict(event_id=turn,source_version=1,session_id=request.session_id,
            event_sha256=digest(events[turn]),span_chars=[0,len(rec['content'])],observed_at=request.as_of,
            origin='USER',claim_basis='EXPLICIT_USER_STATEMENT',confirmation='LEARNER_STATED'))
    return rec

def confirmed_relation(graph,request,kind,left,right):
    """Use the exact original assertion/span/hash/role contract for new UI links."""
    m1_dependencies()
    from relations import assertion_text, object_sha
    content=assertion_text(kind,left['content'],right['content'])
    event=dict(event_id='relation-'+digest(dict(kind=kind,left=left['memory_id'],right=right['memory_id'],at=request.as_of))[:24],
        version=1,learner_id=request.scope.learner_id,course_id=request.scope.course_id,timestamp=request.as_of,
        role='USER',confirmation='EXPLICIT_LEARNER_LINK',status='ACTIVE',consent_status='GRANTED',
        valid_from=request.as_of,valid_to=None,supersedes_event_id=None,content=content,
        annotation=dict(relation_type=kind,from_fact=left['memory_id'],to_fact=right['memory_id'],span_chars=[0,len(content)]))
    event['source_sha256']=object_sha(event)
    graph['source_events'][event['event_id']]=event

def validate_confirmed_graph(graph,events,database,request):
    """Recompile using original native records and source-event checks, without Gold."""
    from datetime import timedelta
    _,compile_sidecar,_=m1_dependencies()
    operations=[];aliases={}
    with C4MemoryStore(database,clock=lambda:request.as_of) as store:
        for mid,node in graph['nodes'].items():
            record=store.get_memory(request.scope.learner_id,mid)
            if record is None:continue
            operations.append(dict(operation='ADD',fact_id=mid,source_turn_id=node['source_ref']['event_id'],
                course_id=request.scope.course_id,learner_id=request.scope.learner_id,
                source_span_chars=node['source_ref']['span_chars'],claim_basis=node['source_ref']['claim_basis'],content=record.content))
            aliases[mid]=mid
    target_time=(instant(request.as_of)+timedelta(microseconds=1)).isoformat()
    runtime=dict(source_turns=list(events.values()),setup_operations=operations,
        relation_events=list(graph['source_events'].values()),target=dict(as_of=target_time))
    compiled,rejected=compile_sidecar(runtime,{request.scope.course_id:database},aliases)
    if rejected:raise ValueError('CONFIRMED_RELATION_REJECTED:'+','.join(x['reason'] for x in rejected))
    return compiled

def plan_operation(message,task,request,snapshot,source):
    """Public session adapter for checked proposal -> explicit adoption -> self-report.

    It reuses the original Writer and relationship compiler. Publication seeds,
    research materials, accepted plans and model output are never edited here.
    """
    import sqlite3
    from contextlib import closing
    op=message['op']
    if '_dashboard_selection' not in task:raise ValueError('PLAN_STATE_REQUIRES_DASHBOARD_SESSION')
    db,graph,events,event_path=session_memory(task,message)
    registry_path=db.parent/'checked_plan_proposals.json'
    state_path=db.parent/'adopted_plans.json'
    proposals=load(registry_path) if registry_path.exists() else {}
    state=load(state_path) if state_path.exists() else {}
    if op=='register_plan':
        plan=message['plan']
        preparation_token,prepared=verified_preparation(message,task,request,source)
        verified_candidate(message,task,request,source,plan,preparation_token)
        original.source_guard(plan)
        bound=prepared['final_request']['runtime_input']['scope']
        if any(bound[k]!=v for k,v in dict(learner_id=request.scope.learner_id,course_id=request.scope.course_id,session_id=request.session_id).items()):
            raise ValueError('PROPOSAL_SCOPE_MISMATCH')
        issues=original.planner_for(snapshot).candidate_issues(prepared['planner']['bridge'],plan)
        if issues:raise ValueError('PROPOSAL_NOT_CHECKED_ACCEPTED')
        key=digest(plan)
        proposals[key]=dict(plan=deepcopy(plan),plan_sha256=key,task_id=task['task_id'],
            session_id=request.session_id,learner_id=request.scope.learner_id,course_id=request.scope.course_id,
            status='CHECKED_PROPOSAL_NOT_ADOPTED',registered_at=request.as_of)
        atomic_json(registry_path,proposals)
        return dict(registered=True,plan_sha256=key,status='CHECKED_PROPOSAL_NOT_ADOPTED',memory_written=False)
    if op=='memory_task_state':
        result=[]
        with C4MemoryStore(db,clock=lambda:request.as_of) as store:
            for key,adopted in state.items():
                record=store.get_memory(request.scope.learner_id,adopted['plan_memory_id'])
                if record is None or record.status!='ACTIVE':continue
                actions=[]
                for action in adopted['actions']:
                    rec=store.get_memory(request.scope.learner_id,action['action_memory_id'])
                    if rec is None or rec.status!='ACTIVE':continue
                    completion=action.get('completion_memory_id')
                    done=store.get_memory(request.scope.learner_id,completion) if completion else None
                    actions.append(dict(**action,completed=bool(done and done.status=='ACTIVE'),completion_basis='EXPLICIT_USER_SELF_REPORT' if done else None))
                result.append(dict(plan_sha256=key,plan_memory_id=record.memory_id,plan=deepcopy(adopted['plan']),actions=actions,origin='USER',adoption_basis='EXPLICIT_UI_CONSENT'))
        return dict(plans=result,learner_id=request.scope.learner_id,course_id=request.scope.course_id)
    if message.get('consent') is not True:return dict(accepted=False,reason_code='EXPLICIT_UI_CONSENT_REQUIRED')
    if op=='memory_accept_plan':
        plan=message['plan'];key=digest(plan);proposal=proposals.get(key)
        if not proposal or proposal['plan']!=plan or proposal['session_id']!=request.session_id or proposal['learner_id']!=request.scope.learner_id or proposal['task_id']!=task['task_id']:
            raise ValueError('PLAN_NOT_CHECKED_IN_THIS_LEARNER_SESSION')
        if key in state:return dict(accepted=True,already_adopted=True,**state[key])
        if not 0<len(plan['actions'])<=20:raise ValueError('PUBLIC_PLAN_ACTION_LIMIT')
        contents=['I adopt this plan: '+plan['plan_id']+'. Goal as displayed: '+plan['goal']+'. Checked proposal sha256: '+key]
        contents += ['I accept this action: ['+plan['plan_id']+'/'+a['step_id']+'] '+a['action'] for a in plan['actions']]
        if any(len(x)>4000 for x in contents):raise ValueError('NATIVE_CONFIRMATION_TEXT_LIMIT')
    elif op=='memory_complete_action':
        aid=message['action_memory_id']
        found=[(key,adopted,a) for key,adopted in state.items() for a in adopted['actions'] if a['action_memory_id']==aid]
        if len(found)!=1:raise ValueError('ACTIVE_ACCEPTED_ACTION_REQUIRED')
        key,adopted,action=found[0]
        if action.get('completion_memory_id'):return dict(accepted=True,already_completed=True,**action)
    else:raise ValueError('UNKNOWN_PLAN_OPERATION')
    # Original Writer commits each call. Stage a native copy so any policy or
    # relation rejection leaves the user's real store/graph/source events intact.
    with tempfile.TemporaryDirectory(prefix='plan-write-',dir=db.parent) as temporary:
        staged=Path(temporary)/'native.sqlite'
        with closing(sqlite3.connect(db)) as src,closing(sqlite3.connect(staged)) as dst:src.backup(dst)
        proposed_graph=deepcopy(graph);proposed_events=deepcopy(events)
        with C4MemoryStore(staged,clock=lambda:request.as_of) as store:
            if op=='memory_accept_plan':
                active=native_fact(store,request,proposed_graph,proposed_events,contents[0],'ACTIVE_PLAN',key)
                saved_actions=[]
                for i,a in enumerate(plan['actions'],1):
                    accepted=native_fact(store,request,proposed_graph,proposed_events,contents[i],'PROGRESS_UPDATE',key+'/'+a['step_id'])
                    confirmed_relation(proposed_graph,request,'ACCEPTED_ACTION_BELONGS_TO_PLAN',accepted,active)
                    saved_actions.append(dict(step_id=a['step_id'],action=a['action'],action_memory_id=accepted['memory_id'],completion_memory_id=None))
                state[key]=dict(plan_sha256=key,plan_memory_id=active['memory_id'],plan=deepcopy(plan),actions=saved_actions,adopted_at=request.as_of)
                result=dict(accepted=True,already_adopted=False,**state[key])
            else:
                accepted=store.get_memory(request.scope.learner_id,aid)
                active=store.get_memory(request.scope.learner_id,adopted['plan_memory_id'])
                if not accepted or not active or accepted.status!='ACTIVE' or active.status!='ACTIVE' or accepted.memory_type!='PROGRESS_UPDATE' or not accepted.content.startswith('I accept this action:'):
                    raise ValueError('ACTIVE_ACCEPTED_ACTION_REQUIRED')
                done=native_fact(store,request,proposed_graph,proposed_events,
                    'I report that I have completed this action: ['+aid+'] '+action['action'],'COMPLETED_ACTION',aid)
                confirmed_relation(proposed_graph,request,'COMPLETION_BELONGS_TO_PLAN',done,active.as_dict())
                confirmed_relation(proposed_graph,request,'COMPLETION_OF_ACTION',done,accepted.as_dict())
                action['completion_memory_id']=done['memory_id']
                result=dict(accepted=True,already_completed=False,completion_memory_id=done['memory_id'],action_memory_id=aid,completion_basis='EXPLICIT_USER_SELF_REPORT')
        compiled=validate_confirmed_graph(proposed_graph,proposed_events,staged,request)
        with closing(sqlite3.connect(staged)) as src,closing(sqlite3.connect(db)) as dst:src.backup(dst)
        atomic_json(event_path.parent/'visitor_graph.json',compiled)
        atomic_json(event_path,proposed_events)
        atomic_json(state_path,state)
    return result


def handle(message):
    op=message['op']
    if op=='ping': return {'core':'RECOVERED_FDD9848_ORIGINAL','provider_credentials_present':any(k for k in __import__('os').environ if k.upper().endswith('API_KEY') or k.upper() in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY'))}
    task=task_for(message)
    snapshot=snapshot_for(task)
    request=request_for(task,message)
    source=primary_for(task,snapshot,request)
    if op=='source': return dict(source=source,**source,overview=snapshot.overview(),snapshot_origin=snapshot.origin,source_time=task['query_time'])
    if op in ('register_plan','memory_accept_plan','memory_complete_action','memory_task_state'):
        return plan_operation(message,task,request,snapshot,source)
    if op=='p3_requests':
        frozen=FrozenP3()
        return dict(source=source,requests={r:frozen.request(r,source['primary']) for r in original.ROLE_NAMES} if hasattr(original,'ROLE_NAMES') else {r:frozen.request(r,source['primary']) for r in ('RAG','MEMORY','B4_PLANNING')},receipt=frozen.receipt())
    if op in ('memory_list','memory_write'):
        db,graph,events,event_path=session_memory(task,message)
        with C4MemoryStore(db,clock=lambda:request.as_of) as store:
            if op=='memory_list':return [r.as_dict() for r in store.list_active_memories(request.scope.learner_id)]
            content=message['content']
            target=message.get('target_memory_id')
            turn='visitor-'+digest(dict(session=request.session_id,content=content,time=request.as_of))[:24]
            candidate=StructuredMemoryCandidate.from_mapping(dict(operation='UPDATE' if target else 'ADD',memory_type=message['memory_type'],content=content,target_memory_id=target,confidence=1.0,evidence_span=content))
            result=C4MemoryWriter(store).apply_candidate(student_id=request.scope.learner_id,source_session_id=request.session_id,source_turn_id=turn,source_text=content,candidate=candidate,source_role='USER',claim_basis='EXPLICIT_USER_STATEMENT',consent_status='GRANTED' if message['consent'] else 'DENIED',event_at=request.as_of,valid_from=request.as_of,valid_to=None).as_dict()
            if result['accepted']:
                events[turn]=dict(learner_id=request.scope.learner_id,course_id=request.scope.course_id,session_id=request.session_id,turn_id=turn,role='USER',content=result['record']['content'],timestamp=request.as_of)
                rec=result['record']
                graph['nodes'][rec['memory_id']]=dict(native_id=rec['memory_id'],native_version=rec['version'],content_sha256=rec['content_sha256'],memory_type=rec['memory_type'],learner_id=rec['student_id'],course_id=request.scope.course_id,source_ref=dict(event_id=turn,source_version=1,session_id=request.session_id,event_sha256=digest(events[turn]),span_chars=[0,len(rec['content'])],observed_at=request.as_of,origin='USER',claim_basis='EXPLICIT_USER_STATEMENT',confirmation='LEARNER_STATED'))
                graph.pop('sha256',None)
                graph['sha256']=digest(graph)
                (event_path.parent/'visitor_graph.json').write_text(json.dumps(graph,ensure_ascii=False))
                event_path.write_text(json.dumps(events,ensure_ascii=False))
            return result
    if op in ('check_candidate','candidate_payload'):
        preparation_token,prepared=verified_preparation(message,task,request,source)
        planner=original.planner_for(snapshot)
        if op=='check_candidate':
            issues=planner.candidate_issues(prepared['planner']['bridge'],message['candidate'])
            return dict(issues=issues,candidate_receipt=None if issues else save_candidate_receipt(
                message,task,request,source,preparation_token,message['candidate']))
        return planner.candidate_payload(prepared,ROLE_CONFIG,previous=message.get('previous'),issues=message.get('issues',()))
    if op=='final_payload':
        preparation_token,prepared=verified_preparation(message,task,request,source)
        accepted=message.get('accepted_plan')
        if accepted is not None:verified_candidate(message,task,request,source,accepted,preparation_token)
        return original.final_payload(prepared,ROLE_CONFIG,accepted,message.get('candidate_failed',False))
    if op=='check_final':
        _,prepared=verified_preparation(message,task,request,source)
        ids=prepared['trace']['retained_evidence_ids']
        if message.get('evidence_ids')!=ids:raise ValueError('SESSION_FINAL_EVIDENCE_CHANGED')
        return {'issues':original.final_issues(message['value'],ids)}
    if op!='prepare':raise ValueError('UNKNOWN_PUBLIC_OPERATION')
    route=message.get('route')
    rag=memory=backend=None
    if route and route['rag_required'] and POLICIES[request.mode][1]:
        scorer=original.R0OnExplicitCorpus([CourseChunk(**json.loads(x)) for x in (DATA/'course/corpus.jsonl').read_text().splitlines() if x.strip()])
        rag=original.UndatedR0(scorer,course_id=request.scope.course_id,source_version=request.source_version,expected_corpus_sha256=scorer.corpus_hash)
    with tempfile.TemporaryDirectory(prefix='lad-readonly-') as td:
        if route and route['memory_required'] and POLICIES[request.mode][2]:
            # ALL M1 imports happen in this worker, before reading any M1 state.
            m1_dependencies()
            db,graph,events,_=session_memory(task,message)
            if message.get('memory_backend')=='HYBRID':
                import os
                if not os.environ.get('LAD_MPNET_PATH'):raise ValueError('LIVE_MEMORY_REQUIRES_PINNED_MPNET_PATH_OPTIONAL_REQUIREMENTS')
                from utils.c4_rebuild.i1.native_backend import I1LocalBackend
                backend=I1LocalBackend(Path(td))
            clones=clone_native_states({request.scope.course_id:db},Path(td)/'readonly')
            memory=I1NativeM1(clones,graph,events,backend=backend)
        try:
            service=original.SourceService(enabled=True,snapshot=snapshot,router=original.ReceiptRouter(source['primary'],route),retriever=rag,memory=memory,evidence_budget=12000,request_budget=50000)
            prepared=service.prepare(request)
        finally:
            if backend is not None:backend.close()
    if isinstance(snapshot,DashboardPages):
        prepared['trace']['dashboard_raw_fact_trace']=[f.trace() for f in snapshot.bundle.facts]
        prepared['trace']['dashboard_source_hashes']=task['_dashboard_selection']['source_hashes']
        prepared['trace']['dashboard_temporal_boundary']=task['_dashboard_selection']['temporal_boundary']
    receipt=save_runtime_receipt(message,task,request,source,prepared)
    return dict(source=source,prepared=prepared,runtime_receipt=receipt,rag_calls=rag.calls if rag else 0,memory_calls=memory.calls if memory else 0,
        memory_backend=memory.identity if memory else 'NOT_ACTIVATED',readonly_state_unchanged=memory is None or prepared['trace'].get('memory_diagnostics',{}).get('readonly_state_unchanged',memory.calls==0))

if __name__=='__main__':
    import socket
    def denied(*args,**kwargs):raise RuntimeError('PUBLIC_CORE_WORKER_NO_NETWORK')
    socket.create_connection=denied
    socket.socket.connect=denied
    try:
        value=handle(json.load(sys.stdin))
        print(json.dumps({'ok':True,'result':value},ensure_ascii=False,allow_nan=False))
    except Exception as exc:
        print(json.dumps({'ok':False,'error':type(exc).__name__+':'+str(exc)},ensure_ascii=False))
        raise SystemExit(1)
