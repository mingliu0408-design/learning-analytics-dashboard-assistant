"""Versioned source binding. Reuses the compiler, gates, M1 and FINAL/time fixes."""
from replay_common import *
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
import subprocess
import tempfile
from contextlib import ExitStack
from interfaces import ReplayService, clone_function
from utils.c4_rebuild.service import ResearchService
from utils.c4_rebuild.contracts import Mode, Request, Access
from utils.c4_dashboard_scoped.scope import instant, digest
from utils.c4_dashboard_scoped.select import select_domains
from utils.c4_dashboard_scoped.integration import ScopedC4Request
from utils.c4_real_contracts import EvidenceItem, EvidenceSynthesisResult, P3CapabilityRoute, C4Mode
from utils.c4_real_adapters import FrozenClarificationGateAdapter
from utils.c4_rebuild.rag import R0OnExplicitCorpus, ProvisionalR0
from utils.course_material_retriever import CourseChunk

DOMAINS=('Resources','Lecture','Debate','Reflection')

@dataclass(frozen=True)
class ReplayScope:
    learner_id:str=LEARNER
    course_id:str=COURSE
    snapshot:str=VERSION
    start:None=None
    end:None=None
    timezone:None=None
    def public_window(self):
        return dict(start=None,end=None,timezone=None,time_basis='AS_SUPPLIED_HISTORICAL_SOURCES',
            calendar_version=None,current_week=None,
            boundary='Source-local Moodle timestamps/week labels and cumulative snapshots; not a common observation window.')
    def internal(self):return dict(learner_id=self.learner_id,course_id=self.course_id,snapshot=self.snapshot,**self.public_window())

class BoundPages:
    origin='CONTROLLED_HISTORICAL_REPLAY'
    def __init__(self,binding):
        if binding['mode']!=self.origin or binding['course_id']!=COURSE or binding['learner_id']!=LEARNER:
            raise ValueError('CONTROLLED_SCOPE_MISMATCH')
        self.binding=binding;self.pages=read(checked(binding['pages']))['pages']
    def validate_query(self,scope,query,now):
        if (scope.learner_id,scope.course_id)!=(LEARNER,COURSE):raise ValueError('RESEARCH_SOURCE_SCOPE_MISMATCH')
        if not query.strip():raise ValueError('EMPTY_QUERY')
    def context(self,domains):
        return dict(activity={d:deepcopy(self.pages[d]) for d in domains},
            source_time_policy='No inferred current week, common observation window, timezone, or present availability. Unknown is not zero.')
    def overview(self):
        # Overview contains four-domain summaries, not each detailed page's rows.
        p=self.pages;r=p['Resources']['resource_events'];l=p['Lecture']['playback_snapshot']
        d=p['Debate'];f=p['Reflection']['writing_snapshot']
        summaries=dict(Resources=dict(resource_views=r['count'],active_source_weeks=len(r['by_source_week']),
            most_active_weekdays=r['most_active_weekdays'],level=r['level'],metrics=p['Resources']['metrics']),
            Lecture=dict(video_clicks=p['Lecture']['video_click_events']['count'],total_view_events=l['total_view_events'],
                mean_percent_all_9_source_rows=l['mean_percent_all_9_rows'],level=l['level'],observation_window=None,
                boundary='Includes the original No Lecture Video placeholder in this mean; not a distinct-video count.'),
            Debate=dict(counts={k:v['count'] for k,v in d['events'].items()},level='RAW_EVENT_AGGREGATION',
                collection_scope=deepcopy(d['collection_scope'])),
            Reflection=dict(Total_chars=f['Total_chars'],level=f['level'],observation_window=None,
                feedback_or_text=None,boundary=p['Reflection']['boundary']))
        for domain,s in summaries.items():
            s['source_versions']=deepcopy(p[domain]['source_versions']);s['claim_boundary']=p[domain]['claim_boundary']
        return dict(activity=summaries,source_time_policy=self.context(())['source_time_policy'],
            view_granularity='OVERVIEW_FOUR_DOMAIN_SUMMARIES_NOT_DETAILED_PAGE_ROWS')

def aggregate_bound(snapshot,scope):
    # The inherited fact tracer is for timestamp-filtered E1 atoms; this version
    # supplies its own exact content-to-compiler trace, without pretending E1 ran.
    return SimpleNamespace(facts=[],visible=lambda p:snapshot.overview() if p=='Overview' else snapshot.context((p,)))

def build_bound(*,snapshot,scope,query,page,messages=(),session_id=None,now=None,**kw):
    snapshot.validate_query(scope,query,now)
    return ScopedC4Request(request_id='CONTROLLED_SOURCE_VIEW',scenario_id='RESEARCH_RUNTIME',
        mode=C4Mode.C1_EVIDENCE,
        current_query=query,current_page=page,dashboard_context=aggregate_bound(snapshot,scope).visible(page),
        visible_conversation_history=tuple(messages),student_id=scope.learner_id,session_id=session_id,
        state_reset_id=scope.snapshot,dashboard_scope=scope,trusted_now=now.isoformat() if now else None)

class BoundEvidence:
    def __init__(self,snapshot):self.snapshot=snapshot
    def synthesise(self,*,request,primary_input):
        selected,reason=select_domains(primary_input.current_query,primary_input.current_page)
        current=DOMAINS if request.current_page=='Overview' else (request.current_page,)
        extra=tuple(d for d in selected if d not in current)
        content=self.snapshot.context(extra)
        items=() if not extra else (EvidenceItem('controlled-added:'+digest(content),
            'CONTROLLED_NONCURRENT_SOURCE_SYNTHESIS',content,evidence_strength='RAW_AND_CUMULATIVE_SNAPSHOT_AS_LABELLED',
            provenance=dict(adapter=VERSION,selection=reason,added_domains=extra,observed_at=None,valid_from=None,valid_to=None)),)
        return EvidenceSynthesisResult(items,status='CONTROLLED_SOURCE_SYNTHESIS')

def controlled_item(evidence_id,evidence_type,content,**kw):
    return EvidenceItem(evidence_id,'CONTROLLED_CURRENT_PAGE_VIEW',content,
        evidence_strength='RAW_AND_CUMULATIVE_SNAPSHOT_AS_LABELLED',
        provenance=dict(adapter=VERSION,observed_at=None,valid_from=None,valid_to=None))

PREPARE=clone_function(ResearchService.prepare,dict(build_scoped_request=build_bound,
    aggregate=aggregate_bound,ScopedEvidenceAdapter=BoundEvidence,EvidenceItem=controlled_item))

class ControlledService(ReplayService):
    def check_planning_bridge(self,bridge):
        from snapshot_planning import validate_bridge
        return validate_bridge(bridge)
    def validate_request_time(self,request):
        if request.as_of!=CLOCK:raise ValueError('UNDECLARED_EXPERIMENTAL_MEMORY_CLOCK')
    def build_planning_bridge(self,request,compiled,task,memory):
        # Reuse the fixed instantaneous current-request mapping exactly.
        bridge=super().build_planning_bridge(request,compiled,task,memory)
        # Unknown activity observation times must not acquire the Memory clock.
        base=deepcopy(bridge['source_input']['base_input'])
        for fact in base['facts']:
            if fact['fact_id']!='current-request' and fact['kind']=='DASHBOARD':
                fact['source_ref'].update(observed_at=None,valid_from=None,valid_to=None)
        from utils.c4_rebuild.planning import bridge_from_m1
        return bridge_from_m1(memory,base,task,request.future_policy)
    def prepare(self,request):
        result=PREPARE(self,request)
        if result['trace']['route_status']=='MISSING_ROUTE_NOT_YES':
            result['final_request']['clarification_required'].append('P3_ROUTE_UNAVAILABLE')
            result['final_request']['plan_status']='ROUTE_UNAVAILABLE'
        rt=result['final_request']['runtime_input']
        # Renderer time context is for the student's request, not native setup age.
        rt['scope']['as_of']=None
        trace=result['trace'];trace['integration_version']=VERSION
        trace['ordered_events']=[x.replace('E1_SCOPED_AGGREGATION','CONTROLLED_BOUND_SOURCE_SYNTHESIS').replace('SCOPE_AND_VISIBLE_PAGE','BOUND_RESEARCH_SCOPE_AND_VISIBLE_PAGE') for x in trace['ordered_events']]
        trace['experimental_memory_clock']=CLOCK;trace['actual_student_request_time']=None
        selected=rt['evidence']['selected_evidence']
        trace['source_fact_destinations']=[dict(evidence_id=e['evidence_id'],content_sha256=digest(e['content']),
            pointer=f'/runtime_input/evidence/selected_evidence/{i}/content',domains=list(e['content'].get('activity',{})))
            for i,e in enumerate(selected) if e['source_kind']=='DASHBOARD']
        trace['final_request_sha256']=digest(result['final_request'])
        return result

class ReceiptRouter:
    def __init__(self,primary,route):self.primary,self.receipt=primary,route
    def route(self,primary):
        if primary.to_payload()!=self.primary:raise ValueError('P3_INPUT_CHANGED')
        return P3CapabilityRoute(**self.receipt) if self.receipt else None

class BoundR0(ProvisionalR0):
    def retrieve(self,request):
        from dataclasses import replace
        result=super().retrieve(request)
        return replace(result,sources=tuple(replace(s,provenance=dict(s.provenance,observed_at=None,
            time_basis='UNDATED_LOCAL_COURSE_CORPUS',valid_from=None,valid_to=None)) for s in result.sources))

def rag_for(binding):
    rb=binding['rag'];chunks=[CourseChunk(**v) for v in lines(checked(rb))]
    if len(chunks)!=624:raise ValueError('CORPUS_COUNT_CHANGED')
    return BoundR0(R0OnExplicitCorpus(chunks),course_id=COURSE,source_version=rb['version'],expected_corpus_sha256=rb['corpus_sha256'])

def request_for(task,binding,mode):
    if set(task)!={'task_id','query','page','history'}:raise ValueError('RUNTIME_TASK_ALLOWLIST')
    if task['task_id'] in NINE and task['history']!=[]:raise ValueError('HIDDEN_SETUP_LEAK')
    return Request(scope=ReplayScope(),query=task['query'],page=task['page'],as_of=CLOCK,
        session_id='CONTROLLED_TARGET_SESSION',mode=mode,history=tuple(task['history']),future_policy='WARN_SNAPSHOT_ONLY',
        access=Access(True,True,True,'USER_MESSAGE_LOCAL_CONTROLLED_REPLAY_ONLY'),
        memory_state_version=sha(binding['tasks'][task['task_id']]),source_version=binding['rag']['version'])

def source_for(task,binding):
    request=request_for(task,binding,Mode.S0_PAGE_ONLY);snapshot=BoundPages(binding)
    scoped=build_bound(snapshot=snapshot,scope=request.scope,query=request.query,page=request.page,
        messages=request.history,session_id=request.session_id,now=instant(CLOCK))
    primary=scoped.primary_input.to_payload()
    return dict(primary=primary,primary_sha256=digest(primary),task_sha256=sha(task),
        clarification=FrozenClarificationGateAdapter().evaluate(scoped.primary_input).needs_clarification,
        source_bound=True,current_observation_week=None)

def handle(message):
    binding=read(message['bindings_path'])
    if sha(binding)!=message['bindings_digest']:raise ValueError('BINDINGS_CHANGED')
    task=message['task'];source=source_for(task,binding)
    if message['op']=='source':return source
    if message['op']!='prepare' or source['primary_sha256']!=message['primary_sha256']:raise ValueError('SOURCE_STAGE_CHANGED')
    request=request_for(task,binding,Mode(message['mode']))
    rag=rag_for(binding);memory=None;backend=None
    with tempfile.TemporaryDirectory(prefix='reused62-controlled-') as td,ExitStack() as stack:
        td=Path(td)
        memory_wanted=request.mode in (Mode.S3_EVIDENCE_MEMORY,Mode.S5_FULL) and (message.get('route') or {}).get('memory_required') and not source['clarification']
        if memory_wanted:
            from utils.c4_rebuild.memory import clone_native_states,m1_dependencies
            from utils.c4_rebuild.i1.memory import I1NativeM1
            m1_dependencies()
            if task['task_id'] in NINE:
                mb=read(HERE/'runtime/MEMORY_BINDINGS.json')[task['task_id']]
                dbs={k:checked(v) for k,v in mb['databases'].items()}
                graph=read(checked(mb['graph']));events=read(checked(mb['source_events']))
                import fcntl
                from utils.c4_rebuild.i1.native_backend import I1LocalBackend
                lock=stack.enter_context(open('/private/tmp/rq3-rebuild-local-inference.lock','a+'))
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                backend=I1LocalBackend(td);stack.callback(backend.close)
            else:
                from utils.c4_memory.c4_memory_store import C4MemoryStore
                db=td/'empty.sqlite'
                with C4MemoryStore(db,clock=lambda:CLOCK):pass
                dbs={COURSE:db};graph=dict(version='M1_RELATIONS_V1',nodes={},edges=[],source_events={})
                graph['sha256']=digest(graph);events={}
            clones=clone_native_states(dbs,td/'condition')
            for p in clones.values():p.chmod(0o444)
            memory=I1NativeM1(clones,graph,events,backend=backend)
        service=ControlledService(enabled=True,snapshot=BoundPages(binding),router=ReceiptRouter(source['primary'],message.get('route')),
            retriever=rag,memory=memory,evidence_budget=message['config']['evidence_budget'],request_budget=message['config']['request_budget'])
        prepared=service.prepare(request)
    return dict(source=source,prepared=prepared,rag_calls=rag.calls,memory_calls=memory.calls if memory else 0,
        state_policy='FRESH_READONLY_CLONE_ONLY_IF_ACTUAL_GATE_ALLOWS',experimental_clock=CLOCK,real_time_unknown=True)

class Worker:
    def call(self,message):
        p=subprocess.run([sys.executable,'-B',str(Path(__file__))],input=json.dumps(message),text=True,capture_output=True,timeout=150,cwd=ROOT)
        if p.returncode:raise RuntimeError(p.stdout[-1200:]+p.stderr[-1000:])
        return json.loads(p.stdout)

if __name__=='__main__':
    offline()
    try:print(json.dumps(handle(json.load(sys.stdin)),ensure_ascii=False))
    except Exception as exc:print(json.dumps(dict(error=type(exc).__name__+':'+str(exc))));raise SystemExit(1)
