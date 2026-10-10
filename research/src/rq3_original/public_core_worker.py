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
from utils.c4_rebuild.contracts import Request, Access, Mode, reject_sidecars
from utils.c4_dashboard_scoped.scope import instant, digest
from utils.c4_memory.c4_memory_store import C4MemoryStore
from utils.c4_memory.c4_memory_writer import C4MemoryWriter, StructuredMemoryCandidate
from utils.c4_rebuild.memory import clone_native_states, m1_dependencies
from utils.c4_rebuild.i1.memory import I1NativeM1
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from utils.c4_rebuild.i1.schemas import errors
from utils.c4_rebuild.i1.renderer import material
from utils.course_material_retriever import CourseChunk

ROLE_CONFIG = dict(model='gpt-4o-mini-2024-07-18',temperature=0,max_output_tokens=3000)

def load(path):
    return json.loads(Path(path).read_text())

def public_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('PUBLIC_SOURCE_PATH_BOUNDARY')
    return path

def task_for(message):
    rows = [json.loads(x) for x in (DATA/'replay/runtime_tasks.jsonl').read_text().splitlines()]
    task = deepcopy(next(t for t in rows if t['task_id']==message['task_id']))
    if message.get('query') is not None:
        task['query'] = message['query']
        task['page'] = message.get('page',task['page'])
        task['visible_history'] = deepcopy(message.get('history', []))
        task['query_time'] = message['request_time']
    original.source_guard(task)
    return task

def snapshot_for(task):
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
    return Request(scope=original.TaskScope(s['student_id'],s['course_id'],s['window_start'],s['window_end'],timezone='UTC' if s['window_start'] else None),
        query=task['query'],page=task['page'],as_of=task['query_time'],session_id=message['session_id'],mode=Mode(message.get('mode','S5_FULL')),
        history=tuple(task['visible_history']),future_policy='WARN_SNAPSHOT_ONLY',
        access=Access(True,True,True,'EXPLICIT_PUBLIC_VISITOR_REQUEST'),
        source_version=hashlib.sha256(corpus.read_bytes()).hexdigest(),memory_state_version='SESSION_LOCAL_NATIVE_STATE',
        task_intent=options.get('task_intent'),memory_purpose=options.get('memory_purpose'),
        visible_controls='PUBLIC_EXPLICIT_CONTROLS' if options else None,
        schedule_timezone=options.get('schedule_timezone'),allowed_windows=tuple(options.get('allowed_windows') or ()),schedule_horizon=options.get('schedule_horizon'))

def primary_for(task,snapshot,request):
    scoped=original.build_request(snapshot=snapshot,scope=request.scope,query=request.query,page=request.page,messages=request.history,session_id=request.session_id,now=instant(request.as_of))
    primary=scoped.primary_input.to_payload()
    return dict(primary=primary,primary_sha256=digest(primary),clarification=original.FrozenClarificationGateAdapter().evaluate(scoped.primary_input).needs_clarification)

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
    if not db.exists():
        with sqlite3.connect((seed/'initial.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(db) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('SEED_INTEGRITY')
    graph_path=root/'visitor_graph.json'
    graph=load(graph_path) if graph_path.exists() else load(seed/'graph.json')
    events=load(seed/'source_events.json')
    additions=root/'visitor_events.json'
    if additions.exists(): events.update(load(additions))
    return db,graph,events,additions

def handle(message):
    op=message['op']
    if op=='ping': return {'core':'RECOVERED_FDD9848_ORIGINAL','provider_credentials_present':any(k for k in __import__('os').environ if k.upper().endswith('API_KEY') or k.upper() in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY'))}
    task=task_for(message)
    snapshot=snapshot_for(task)
    request=request_for(task,message)
    source=primary_for(task,snapshot,request)
    if op=='source': return dict(source,overview=snapshot.overview(),snapshot_origin=snapshot.origin,source_time=task['query_time'])
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
        planner=original.planner_for(snapshot)
        if op=='check_candidate':return {'issues':planner.candidate_issues(message['prepared']['planner']['bridge'],message['candidate'])}
        return planner.candidate_payload(message['prepared'],ROLE_CONFIG,previous=message.get('previous'),issues=message.get('issues',()))
    if op=='final_payload':return original.final_payload(message['prepared'],ROLE_CONFIG,message.get('accepted_plan'),message.get('candidate_failed',False))
    if op=='check_final':return {'issues':original.final_issues(message['value'],message['evidence_ids'])}
    if op!='prepare':raise ValueError('UNKNOWN_PUBLIC_OPERATION')
    route=message.get('route')
    rag=memory=backend=None
    if route and route['rag_required']:
        scorer=original.R0OnExplicitCorpus([CourseChunk(**json.loads(x)) for x in (DATA/'course/corpus.jsonl').read_text().splitlines() if x.strip()])
        rag=original.UndatedR0(scorer,course_id=request.scope.course_id,source_version=request.source_version,expected_corpus_sha256=scorer.corpus_hash)
    with tempfile.TemporaryDirectory(prefix='lad-readonly-') as td:
        if route and route['memory_required']:
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
    return dict(source=source,prepared=prepared,rag_calls=rag.calls if rag else 0,memory_calls=memory.calls if memory else 0,
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
