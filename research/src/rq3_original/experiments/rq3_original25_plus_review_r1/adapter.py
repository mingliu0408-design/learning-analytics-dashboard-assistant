"""Thin source projection into the actual C4 compiler/service and native M1.

Target route/retrieval is disabled unless the approved execution caller opts in.
This module never imports evaluation references, task-family designs or ratings.
"""
from v2_common import *
from copy import deepcopy
from collections import Counter
from dataclasses import dataclass, replace
from types import SimpleNamespace
from itertools import combinations
from contextlib import ExitStack
import tempfile

for folder in ('a_reuse62','a_reuse62_replay_v2'):
    sys.path.insert(0,str(ROOT/'research_followups/rq3_rebuild'/folder))
from interfaces import ReplayService, clone_function, final_payload, final_issues, freeze_answer
import interfaces
from controlled_runtime import BoundPages
from utils.c4_dashboard_scoped.scope import instant, digest, canonical
from utils.c4_dashboard_scoped.select import select_domains
from utils.c4_dashboard_scoped.integration import ScopedC4Request
from utils.c4_real_contracts import EvidenceItem, EvidenceSynthesisResult, P3CapabilityRoute, C4Mode
from utils.c4_rebuild.contracts import Mode, Request, Access, POLICIES, reject_sidecars
from utils.c4_rebuild.service import ResearchService
from utils.c4_rebuild.rag import R0OnExplicitCorpus, ProvisionalR0
from utils.c4_rebuild.memory import m1_dependencies, clone_native_states
from utils.c4_rebuild.i1.memory import I1NativeM1
from utils.c4_real_adapters import FrozenClarificationGateAdapter
from utils.course_material_retriever import CourseChunk

DOMAINS=('Resources','Lecture','Debate','Reflection')
TASK_KEYS={'task_id','query','page','visible_history','scope','query_time','source_bindings'}

def source_guard(value):
    reject_sidecars(value)
    if isinstance(value,dict):
        banned={'condition','required_facts','required_for_minimal_answer','optional_support','source_availability_truth','feasibility_witness','human_review'}
        if set(value)&banned: raise ValueError('EVALUATION_FIELD_IN_SOURCE')
        for v in value.values(): source_guard(v)
    elif isinstance(value,list):
        for v in value: source_guard(v)

@dataclass(frozen=True)
class TaskScope:
    learner_id:str
    course_id:str
    start:object
    end:object
    snapshot:str=VERSION
    timezone:object='UTC'
    def public_window(self):
        return dict(start_inclusive=self.start,end_exclusive=self.end,timezone=self.timezone,
            time_basis='EXPLICIT_SOURCE_EVENT_WINDOW' if self.start else 'AS_SUPPLIED_HISTORICAL_SOURCES')
    def internal(self): return dict(self.__dict__)

class Pages:
    origin='SYNTHETIC'
    def __init__(self,task,binding):
        self.task=deepcopy(task)
        for entry in binding.get('files',{}).values():checked(entry)
        self.raw=read(HERE/binding['page_state_path'])
        source_guard(self.raw)
        self.accepted_pointers=[]; self.excluded_pointers=[]
        sc=task['scope']; now=instant(task['query_time'])
        if self.raw['scope']!=sc or self.raw['as_of']!=task['query_time']: raise ValueError('PAGE_SCOPE_BINDING')
        summaries={}
        for page in DOMAINS:
            events=[]; records=[]
            for kind in ('events','records'):
                for i,row in enumerate(self.raw[kind]):
                    if row['page']!=page: continue
                    at=instant(row['occurred_at' if kind=='events' else 'updated_at'])
                    ok=(row['student_id']==sc['student_id'] and row['course_id']==sc['course_id'] and at<=now)
                    if kind=='events': ok=ok and instant(sc['window_start'])<=at<instant(sc['window_end'])
                    ptr=f'/{kind}/{i}'
                    (self.accepted_pointers if ok else self.excluded_pointers).append(ptr)
                    if ok: (events if kind=='events' else records).append(deepcopy(row))
            # A structured snapshot uses its latest known record, not an event sum.
            latest={}
            for row in records:
                prior=latest.get(row['record_id'])
                if prior is None or instant(row['updated_at'])>instant(prior['updated_at']): latest[row['record_id']]=row
            cov=deepcopy(self.raw['coverage'][page])
            complete=(cov['status']=='COMPLETE' and instant(cov['window_start'])<=instant(sc['window_start']) and instant(cov['window_end'])>=instant(sc['window_end']))
            if not complete: cov['status']='UNKNOWN'
            summaries[page]=dict(coverage=cov,event_observations=dict(projection='COUNT_SCOPED_SOURCE_EVENTS',
                count=len(events) if complete else None,observed_rows=len(events),
                by_type=dict(Counter(e['event_type'] for e in events)) if complete else None,events=events),
                record_snapshots=dict(projection='STRUCTURED_SOURCE_STATE_NOT_EVENT_COUNTS',records=list(latest.values())))
        self.pages=summaries
    def validate_query(self,scope,query,now):
        t=self.task
        if (scope.learner_id,scope.course_id,scope.start,scope.end)!=(t['scope']['student_id'],t['scope']['course_id'],t['scope']['window_start'],t['scope']['window_end']): raise ValueError('SOURCE_SCOPE_CHANGED')
        if now!=instant(t['query_time']) or not query.strip(): raise ValueError('SOURCE_TIME_CHANGED')
    def context(self,domains):
        return dict(activity={d:deepcopy(self.pages[d]) for d in domains},
            interpretation='Activity records are not equivalent measures of effort, understanding or learning quality. Source estimates are not measured durations.')
    def overview(self): return self.context(DOMAINS)

class ReplayPages(BoundPages):
    origin='CONTROLLED_RECONTEXTUALISATION'
    def __init__(self,task,binding):
        self.task=deepcopy(task);self.pages=read(checked(binding['page_source']))['pages']
        source_guard(self.pages)
        self.accepted_pointers=['/pages/'+d for d in DOMAINS];self.excluded_pointers=[]
    def validate_query(self,scope,query,now):
        if (scope.learner_id,scope.course_id)!=(self.task['scope']['student_id'],self.task['scope']['course_id']): raise ValueError('REPLAY_SOURCE_SCOPE')
        if now!=instant(self.task['query_time']) or not query.strip(): raise ValueError('REPLAY_TIME')

def aggregate_sources(snapshot,scope):
    return SimpleNamespace(facts=[],visible=lambda p:snapshot.overview() if p=='Overview' else snapshot.context((p,)))

def build_request(*,snapshot,scope,query,page,messages=(),session_id=None,now=None,**kwargs):
    snapshot.validate_query(scope,query,now)
    return ScopedC4Request(request_id='SOURCE_PROJECTION',scenario_id='RESEARCH_RUNTIME',mode=C4Mode.C1_EVIDENCE,
        current_query=query,current_page=page,dashboard_context=aggregate_sources(snapshot,scope).visible(page),
        visible_conversation_history=tuple(messages),student_id=scope.learner_id,session_id=session_id,
        state_reset_id=scope.snapshot,dashboard_scope=scope,trusted_now=now.isoformat())

class SourceEvidence:
    def __init__(self,snapshot): self.snapshot=snapshot
    def synthesise(self,*,request,primary_input):
        selected,reason=select_domains(primary_input.current_query,primary_input.current_page)
        current=DOMAINS if request.current_page=='Overview' else (request.current_page,)
        extra=tuple(d for d in selected if d not in current)
        content=self.snapshot.context(extra)
        items=() if not extra else (EvidenceItem('added:'+digest(content),'SOURCE_NONCURRENT_PROJECTION',content,
            evidence_strength='SOURCE_EVENTS_AND_RECORDS_AS_LABELLED',provenance=dict(adapter=VERSION,selection=reason,added_domains=extra)),)
        return EvidenceSynthesisResult(items,status='SOURCE_PROJECTION')

def current_item(evidence_id,evidence_type,content,**kwargs):
    return EvidenceItem(evidence_id,'SOURCE_CURRENT_PROJECTION',content,evidence_strength='SOURCE_EVENTS_AND_RECORDS_AS_LABELLED',provenance=dict(adapter=VERSION))

PREPARE=clone_function(ResearchService.prepare,dict(build_scoped_request=build_request,
    aggregate=aggregate_sources,ScopedEvidenceAdapter=SourceEvidence,EvidenceItem=current_item))

class SourceService(ReplayService):
    def validate_request_time(self,request):
        if request.scope.end and instant(request.as_of)<instant(request.scope.end): raise ValueError('INCOMPLETE_REQUEST_WINDOW')
    def build_planning_bridge(self,request,compiled,task,memory):
        bridge=super().build_planning_bridge(request,compiled,task,memory)
        base=deepcopy(bridge['source_input']['base_input'])
        if self.snapshot.origin=='CONTROLLED_RECONTEXTUALISATION':
            for f in base['facts']:
                if f['kind']=='DASHBOARD' and f['fact_id']!='current-request':
                    f['source_ref'].update(observed_at=None,valid_from=None,valid_to=None)
        # Only structured fields actually retained by the common compiler can
        # supply a page budget. No evaluation witness or hidden history.
        budgets=[]
        for item in compiled.content['selected_evidence']:
            if item['source_kind']!='DASHBOARD':continue
            for domain in item['content'].get('activity',{}).values():
                for row in domain.get('record_snapshots',{}).get('records',[]):
                    value=row['payload']
                    if 'available_minutes' in value: budgets.append(value['available_minutes'])
        if len(set(budgets))==1:
            base['hard_constraints']['budget']=dict(required=True,minutes=budgets[0])
        elif len(set(budgets))>1: base['missing_information'].append('CONFLICTING_VISIBLE_PAGE_BUDGETS')
        from utils.c4_rebuild.planning import bridge_from_m1
        return bridge_from_m1(memory,base,task,request.future_policy)
    def check_planning_bridge(self,bridge): return planner_for(self.snapshot).validate_bridge(bridge)
    def prepare(self,request):
        result=PREPARE(self,request)
        if result['trace']['route_status']=='MISSING_ROUTE_NOT_YES':
            result['final_request']['clarification_required'].append('P3_ROUTE_UNAVAILABLE')
            result['final_request']['plan_status']='ROUTE_UNAVAILABLE'
        rt=result['final_request']['runtime_input']
        if self.snapshot.origin=='CONTROLLED_RECONTEXTUALISATION':rt['scope']['as_of']=None
        trace=result['trace'];trace['integration_version']=VERSION
        trace['ordered_events']=[s.replace('E1_SCOPED_AGGREGATION','SOURCE_EVENTS_AND_RECORD_PROJECTION') for s in trace['ordered_events']]
        trace['source_fact_destinations']=[dict(evidence_id=e['evidence_id'],content_sha256=digest(e['content']),
            pointer=f'/runtime_input/evidence/selected_evidence/{i}/content',domains=list(e['content'].get('activity',{})))
            for i,e in enumerate(rt['evidence']['selected_evidence']) if e['source_kind']=='DASHBOARD']
        trace['accepted_source_pointers']=self.snapshot.accepted_pointers
        trace['excluded_source_pointers']=self.snapshot.excluded_pointers
        trace['final_request_sha256']=digest(result['final_request'])
        return result

def planner_for(snapshot):
    """Reuse typed planner with a local, exact ordinary-snapshot validator."""
    from utils.c4_rebuild import planning as api
    allowed={canonical(snapshot.overview())}|{canonical(snapshot.context(ds)) for n in range(1,5) for ds in combinations(DOMAINS,n)}
    def source_check(bridge):
        inherited=interfaces.replay_source_check(bridge)
        def check(ref,path,inp,report,at=None):
            local=api.p1v.p0.Report();inherited(ref,path,inp,local,at)
            fs=[f for f in inp['facts'] if f['source_ref']==ref]
            exact=(snapshot.origin=='CONTROLLED_RECONTEXTUALISATION' and len(fs)==1 and fs[0]['kind']=='DASHBOARD'
                and fs[0]['fact_type'] in ('SOURCE_CURRENT_PROJECTION','SOURCE_NONCURRENT_PROJECTION')
                and fs[0]['value'] in allowed and ref['version']==VERSION
                and ref['learner_id']==snapshot.task['scope']['student_id'] and ref['course_id']==snapshot.task['scope']['course_id']
                and ref['observed_at'] is ref['valid_from'] is ref['valid_to'] is None
                and bridge['source_input']['task_request']['mode']=='ORDINARY_ACTION_ADVICE'
                and bridge['source_input']['future_use_policy']=='WARN_SNAPSHOT_ONLY' and at is None)
            for issue in local.issues:
                if not (exact and issue['code']=='MISSING_TIME' and issue['path'].startswith(path)):report.issues.append(issue)
            if exact:report.add('UNDATED_BOUND_SNAPSHOT_ORDINARY_ONLY',path,'Exact source snapshot; no current availability inferred.','WARNING')
        return check
    def validators(bridge):return clone_function(api.p1v.validators,{'source_extension':source_check})(bridge)
    def validate_bridge(bridge):return clone_function(api.p1v.validate_bridge,{'project':api.project,'validators':validators,'source_extension':source_check})(bridge)
    def validate_candidate(bridge,candidate):return clone_function(api.p1v.validate_candidate,{'validate_bridge':validate_bridge,'validators':validators,'source_extension':source_check})(bridge,candidate)
    inherited=interfaces.typed_planner();original=inherited.candidate_issues.__globals__['ORIGINAL']
    oi=clone_function(original.candidate_issues,{'validate_candidate':validate_candidate})
    op=clone_function(original.candidate_payload,{'validate_bridge':validate_bridge,'candidate_issues':oi})
    proxy=SimpleNamespace(**vars(original));proxy.candidate_issues=oi;proxy.candidate_payload=op
    kind=clone_function(inherited.plan_kind,{'validate_bridge':validate_bridge})
    issues=clone_function(inherited.candidate_issues,{'ORIGINAL':proxy,'plan_kind':kind})
    payload=clone_function(inherited.candidate_payload,{'ORIGINAL':proxy,'plan_kind':kind,'candidate_issues':issues})
    return SimpleNamespace(plan_kind=kind,candidate_issues=issues,candidate_payload=payload,validate_bridge=validate_bridge)

class ReceiptRouter:
    def __init__(self,primary,route):self.primary,self.receipt=primary,route
    def route(self,primary):
        if primary.to_payload()!=self.primary: raise ValueError('ROUTER_VISIBLE_INPUT_CHANGED')
        return P3CapabilityRoute(**self.receipt) if self.receipt else None

def request_for(task,mode,binding):
    if set(task)!=TASK_KEYS:raise ValueError('RUNTIME_TASK_ALLOWLIST')
    source_guard(task);s=task['scope']
    return Request(scope=TaskScope(s['student_id'],s['course_id'],s['window_start'],s['window_end'],timezone='UTC' if s['window_start'] else None),
        query=task['query'],page=task['page'],as_of=task['query_time'],session_id='target-session',mode=mode,
        history=tuple(task['visible_history']),future_policy='WARN_SNAPSHOT_ONLY',access=Access(True,True,True,'USER_LOCAL_PREPARATION_SCOPE'),
        source_version=binding['course']['sha256'],memory_state_version=binding['native'][task['task_id']]['logical_sha256'])

def snapshot_for(task,binding):
    b=binding['tasks'][task['task_id']]
    return ReplayPages(task,b) if b['kind']=='CONTROLLED_RECONTEXTUALISATION' else Pages(task,b)

def source_for(task,binding):
    r=request_for(task,Mode.S0_PAGE_ONLY,binding);snap=snapshot_for(task,binding)
    scoped=build_request(snapshot=snap,scope=r.scope,query=r.query,page=r.page,messages=r.history,session_id=r.session_id,now=instant(r.as_of))
    primary=scoped.primary_input.to_payload()
    return dict(primary=primary,primary_sha256=digest(primary),clarification=FrozenClarificationGateAdapter().evaluate(scoped.primary_input).needs_clarification)

class UndatedR0(ProvisionalR0):
    def retrieve(self,request):
        r=super().retrieve(request)
        return replace(r,sources=tuple(replace(s,provenance=dict(s.provenance,observed_at=None,time_basis='UNDATED_FIXED_COURSE_CORPUS')) for s in r.sources))

def prepare(task,binding,mode,config,route=None,*,allow_target_reads=False,backend=None):
    source=source_for(task,binding);request=request_for(task,Mode(mode),binding);snap=snapshot_for(task,binding)
    active=route and any(route.get(k) for k in ('rag_required','memory_required','planning_required'))
    if active and not allow_target_reads:raise PermissionError('TARGET_ROUTE_AND_READS_NOT_AUTHORIZED_THIS_ROUND')
    rag=memory=None
    with tempfile.TemporaryDirectory(prefix='rq3-en-v2-readonly-') as td:
        if route and route.get('rag_required') and POLICIES[request.mode][1]:
            scorer=R0OnExplicitCorpus([CourseChunk(**v) for v in lines(checked(binding['course']))])
            rag=UndatedR0(scorer,course_id=request.scope.course_id,source_version=request.source_version,expected_corpus_sha256=scorer.corpus_hash)
        if route and route.get('memory_required') and POLICIES[request.mode][2]:
            nb=binding['native'][task['task_id']]
            copies=clone_native_states({request.scope.course_id:checked(nb['mode_copies'][request.mode.value])},Path(td)/'state')
            for p in copies.values():p.chmod(0o444)
            memory=I1NativeM1(copies,read(checked(nb['graph'])),read(checked(nb['source_events'])),backend=backend)
        service=SourceService(enabled=True,snapshot=snap,router=ReceiptRouter(source['primary'],route),retriever=rag,memory=memory,
            evidence_budget=config['evidence_budget'],request_budget=config['request_budget'])
        prepared=service.prepare(request)
    prepared['trace']['module_state_key']=sha(dict(source_primary=source['primary_sha256'],mode=mode,
        bound_sources=binding['tasks'][task['task_id']],native=binding['native'][task['task_id']]['logical_sha256'],route=route))
    return dict(source=source,prepared=prepared,rag_calls=rag.calls if rag else 0,memory_calls=memory.calls if memory else 0)
