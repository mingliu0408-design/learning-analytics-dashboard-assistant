"""Actual source loader and isolated E1/R0/M1/P1 worker for the fixed 62 roster."""
from pathlib import Path
from dataclasses import replace
from contextlib import ExitStack
import csv
import json
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT))
from build_materials import digest,loadlines
from interfaces import ReplayService
from utils.c4_dashboard_scoped.scope import Snapshot,SourceSpec,Coverage,Calendar,Scope,instant
from utils.c4_dashboard_scoped.integration import build_scoped_request
from utils.c4_rebuild.contracts import Request,Mode,Access,reject_sidecars
from utils.c4_real_adapters import FrozenClarificationGateAdapter
from utils.c4_real_contracts import P3CapabilityRoute

def checked_file(row):
    p=Path(row['path'])
    if p.is_symlink() or not p.is_file() or digest(p.read_bytes())!=row['sha256']:
        raise ValueError('SOURCE_FILE_HASH_OR_PATH:'+str(p))
    return p

def source_files(value):
    if isinstance(value,dict):
        if 'path' in value and 'sha256' in value:
            yield value
        for v in value.values():yield from source_files(v)
    elif isinstance(value,list):
        for v in value:yield from source_files(v)

def readiness(tasks,bindings):
    if bindings.get('schema_version')!='REUSED62_SOURCE_BINDINGS_V1':raise ValueError('BINDING_SCHEMA')
    if set(bindings['tasks'])!={r['task_id'] for r in tasks}:raise ValueError('BINDING_ROSTER')
    result=[]
    for task in tasks:
        b=bindings['tasks'][task['task_id']];gaps=[]
        for k in ['snapshot','source_permission_ref','course_id','roster','calendars','rag']:
            if not bindings.get(k):gaps.append(k.upper()+'_UNBOUND')
        for k in ['scope','as_of','permission_ref']:
            if not b.get(k):gaps.append(k.upper()+'_UNBOUND')
        if bindings.get('rag'):
            for k in ['validity_interval','source_permission_ref']:
                if not bindings['rag'].get(k):gaps.append('RAG_'+k.upper()+'_UNBOUND')
        if b.get('memory') and not b['memory'].get('source_permission_ref'):gaps.append('PERSISTENT_SOURCE_PERMISSION_UNBOUND')
        result.append(dict(task_id=task['task_id'],ready=not gaps,gaps=gaps))
    if not any(r['gaps'] for r in result):
        if bindings['snapshot'].get('origin','LIVE')!='LIVE':raise ValueError('REAL62_CANNOT_USE_SYNTHETIC_SNAPSHOT')
        for f in source_files(bindings):checked_file(f)
    return result

def make_snapshot(bindings):
    s=bindings['snapshot'];tables={};specs={}
    for name,entry in s['tables'].items():
        p=checked_file(entry)
        if p.suffix.lower()!='.csv':raise ValueError('ONLY_TRUSTED_SAFE_CSV_TABLES')
        with p.open() as f:
            reader=csv.DictReader(f);tables[name]=list(reader)
            spec=dict(entry['spec'])
            if list(spec['columns'])!=reader.fieldnames:raise ValueError('TABLE_HEADER_CHANGED')
        spec['coverage']=tuple(Coverage(**x) for x in spec.get('coverage',[]))
        spec['source_sha256']=entry['sha256'];specs[name]=SourceSpec(**spec)
    calendars={course:Calendar(**cal) for course,cal in bindings['calendars'].items()}
    return Snapshot(s['version'],tables,specs,bindings['roster'],calendars,s.get('origin','LIVE'))

def request_for(task,b,bindings,mode):
    if set(task)!={'task_id','query','page','history'}:raise ValueError('TASK_RUNTIME_ALLOWLIST')
    scope=Scope(**b['scope'])
    if scope.learner_id!=b['learner_id'] or scope.course_id!=bindings['course_id']:raise ValueError('TASK_SOURCE_IDENTITY')
    # No labels, expected routes, old target answers or session reconstruction are accepted.
    return Request(scope=scope,query=task['query'],page=task['page'],history=tuple(task['history']),
        as_of=b['as_of'],session_id='replay-'+digest(task)[:20],mode=mode,
        future_policy=b['future_policy'],access=Access(True,True,True,b['permission_ref']),
        memory_state_version=digest(b.get('memory')),source_version=bindings['rag']['version'])

class ReceiptRouter:
    def __init__(self,primary,route):self.primary,self.receipt=primary,route
    def route(self,primary):
        if primary.to_payload()!=self.primary:raise ValueError('P3_INPUT_CHANGED')
        return P3CapabilityRoute(**self.receipt) if self.receipt else None

def handle(message):
    task=message['task'];bindings=json.loads(Path(message['bindings_path']).read_text())
    if digest(bindings)!=message['bindings_digest']:raise ValueError('BINDINGS_CHANGED')
    b=bindings['tasks'][task['task_id']]
    snap=make_snapshot(bindings);request=request_for(task,b,bindings,Mode(message.get('mode','S5_FULL')))
    # Complete observation windows only. A missing/current half-window is not silently moved.
    if instant(request.as_of)<instant(request.scope.end):raise ValueError('COMPLETE_REPLAY_WINDOW_NOT_OBSERVED_AS_OF')
    scoped=build_scoped_request(snapshot=snap,scope=request.scope,query=request.query,page=request.page,
        messages=request.history,session_id=request.session_id,now=instant(request.as_of))
    primary=scoped.primary_input.to_payload()
    source=dict(primary=primary,primary_sha256=digest(primary),scope=request.scope.internal(),
        clarification=FrozenClarificationGateAdapter().evaluate(scoped.primary_input).needs_clarification,
        task_input_sha256=digest(task),source_binding_sha256=digest(bindings))
    if message['op']=='source':return source
    if message['op']!='prepare' or digest(primary)!=message['primary_sha256']:raise ValueError('SOURCE_STAGE_IDENTITY')
    from utils.c4_rebuild.rag import ProvisionalR0,R0OnExplicitCorpus
    from utils.course_material_retriever import CourseChunk
    rb=bindings['rag'];chunks=[CourseChunk(**v) for v in loadlines(checked_file(rb))]
    rag=ProvisionalR0(R0OnExplicitCorpus(chunks),course_id=bindings['course_id'],source_version=rb['version'],
        expected_corpus_sha256=rb['corpus_sha256'],source_window=rb['validity_interval'])
    from utils.c4_rebuild.memory import clone_native_states,m1_dependencies
    from utils.c4_rebuild.i1.memory import I1NativeM1
    m1_dependencies()
    with tempfile.TemporaryDirectory(prefix='reused62-state-') as td,ExitStack() as stack:
        td=Path(td);mb=b.get('memory')
        if mb:
            dbs={c:checked_file(v) for c,v in mb['databases'].items()}
            graph=json.loads(checked_file(mb['graph']).read_text())
            events=json.loads(checked_file(mb['source_events']).read_text())
        else:
            # Empty original persistent history stays empty. No old assistant proposal is written as user fact.
            from utils.c4_memory.c4_memory_store import C4MemoryStore
            db=td/'empty-origin.sqlite'
            store=C4MemoryStore(db,clock=lambda:request.as_of);store.close()
            dbs={request.scope.course_id:db}
            graph={'version':'M1_RELATIONS_V1','nodes':{},'edges':[],'source_events':{}}
            graph['sha256']=digest(graph);events={}
        clones=clone_native_states(dbs,td/'condition')
        backend=None
        if mb and request.mode in (Mode.S3_EVIDENCE_MEMORY,Mode.S5_FULL) and (message.get('route') or {}).get('memory_required'):
            from utils.c4_rebuild.i1.native_backend import I1LocalBackend
            import fcntl
            lock=stack.enter_context(open('/private/tmp/rq3-rebuild-local-inference.lock','a+'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            backend=I1LocalBackend(td);stack.callback(backend.close)
        memory=I1NativeM1(clones,graph,events,backend=backend)
        service=ReplayService(enabled=True,snapshot=snap,router=ReceiptRouter(primary,message.get('route')),
            retriever=rag,memory=memory,evidence_budget=message['config']['evidence_budget'],
            request_budget=message['config']['request_budget'])
        prepared=service.prepare(request)
    return dict(source=source,prepared=prepared,state_clone='FRESH_CLOSED_READONLY_CLONE_PER_MODE',
        source_history_policy=bindings['memory_policy'],rag_calls=rag.calls,memory_calls=memory.calls,
        native_backend='M1_HYBRID' if backend else 'NATIVE_EMPTY_STORE_NO_EMBEDDING' if not mb else 'NOT_ACTIVATED')

class Worker:
    def call(self,message):
        p=subprocess.run([sys.executable,'-B',str(Path(__file__))],input=json.dumps(message),text=True,
            capture_output=True,timeout=150,cwd=ROOT)
        if p.returncode:raise RuntimeError('REPLAY_WORKER:'+p.stdout[-1800:]+p.stderr[-800:])
        return json.loads(p.stdout)

if __name__=='__main__':
    import socket
    def denied(*a,**kw):raise RuntimeError('REUSED62_OFFLINE_WORKER_NO_NETWORK')
    socket.create_connection=denied;socket.socket.connect=denied
    try:print(json.dumps(handle(json.load(sys.stdin)),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps(dict(error=type(exc).__name__+':'+str(exc))));raise SystemExit(1)
