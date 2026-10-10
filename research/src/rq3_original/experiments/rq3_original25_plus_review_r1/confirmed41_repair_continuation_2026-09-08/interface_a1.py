"""Versioned Planning-only intent and declared-source temporal interpretation.

No task/family IDs, evaluation inputs, routing changes, retrieval changes or
model prompt changes. Nonactivated Planning retains the exact R1 request.
"""
from a1_common import base,DATA,load
from copy import deepcopy
from itertools import combinations
from types import SimpleNamespace
import re
from utils.c4_rebuild import planning as api
from utils.c4_rebuild.memory import MemoryBundle
from utils.c4_dashboard_scoped.scope import canonical,digest,instant

VERSION='A1_PLANNING_INTENT_DECLARED_SOURCE_TIME_V1'
SOURCE_TYPES={'SOURCE_CURRENT_PROJECTION','SOURCE_NONCURRENT_PROJECTION'}


def resolve_intent(query,explicit=None):
    old=base.interfaces.resolve_intent(query,explicit)
    if explicit is not None or old['mode']!='UNKNOWN':return old
    calendar=re.search(r'\b(?:schedule|calendar|timetable|time[- ]slots?|dated)\b|\bat\s+\d{1,2}(?::\d{2}|\s*[ap]m)\b|\b(?:this|next)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',query,re.I)
    ordinary=re.search(r'\bwhat\s+(?:(?:step|action)\s+)?(?:can|could|should|would)\s+i\s+(?:do|try|start|begin)\b|\bhow\s+(?:can|could|should)\s+i\s+(?:(?:best|better)\s+)?(?:manage|organize|organise|prioriti[sz]e|approach|begin|start|improve|structure)\b',query,re.I)
    if ordinary and not calendar:
        return dict(mode='ORDINARY_ACTION_ADVICE',basis='EXPLICIT_TASK_REQUEST_FIELD',source_quote=query)
    return old


def planner_for(snapshot,evidence=()):
    """Only remove category errors for exact, scoped, retained source content.

    Dates, source roles, versions and values are never rewritten. Course text
    exemptions apply only to current ordinary advice, never scheduled use.
    """
    b=load(DATA/'BINDINGS.json');corpus=base.lines(base.checked(b['course']))
    chunks={r['chunk_id']:r for r in corpus}
    allowed={canonical(snapshot.overview())}|{canonical(snapshot.context(ds)) for n in range(1,5) for ds in combinations(base.DOMAINS,n)}
    declared={e['evidence_id']:e for e in evidence if e['source_kind']=='COURSE_RAG'}
    def course_fact(f,ref):
        item=declared.get(f['fact_id']);chunk=chunks.get(f['fact_id'])
        if not item or not chunk:return False
        p=item['provenance'];content=item['content']
        metadata=(content.get('week')==chunk.get('week') and content.get('page')==chunk.get('page')
                  and content.get('document_title')==item.get('document_title') and content.get('section')==item.get('section'))
        # Metadata-only and link-only evidence stays so labelled; no body promotion.
        bounded=(content.get('text')==chunk['text'] if 'text' in content else
                 content.get('boundary') in ('TITLE_AND_METADATA_ONLY','LINK_ONLY'))
        if content.get('boundary')=='LINK_ONLY':
            bounded=content.get('links')==re.findall(r'https?://[^\s)\]}>,]+',chunk['text'])[:3]
        return (metadata and bounded and f['kind']=='COURSE_RAG' and f['fact_type']=='COURSE_SOURCE'
            and f['value']==canonical(content) and p.get('time_basis')=='UNDATED_FIXED_COURSE_CORPUS'
            and p.get('source_version')==ref['version']==b['course']['sha256']
            and p.get('course_id')==ref['course_id']==snapshot.task['scope']['course_id']
            and ref['scope']=='COURSE' and ref['learner_id'] is None
            and ref['source_id']==ref['span_id']==f['fact_id']
            and all(ref[k] is None and p.get(k) is None for k in ('observed_at','valid_from','valid_to')))
    def source_check(bridge):
        inherited=api.p1v.source_extension(bridge)
        def check(ref,path,inp,report,at=None):
            local=api.p1v.p0.Report();inherited(ref,path,inp,local,at)
            fs=[f for f in inp['facts'] if f['source_ref']==ref]
            f=fs[0] if len(fs)==1 else None
            ordinary=(bridge['source_input']['task_request']['mode']=='ORDINARY_ACTION_ADVICE'
                and bridge['source_input']['future_use_policy']=='WARN_SNAPSHOT_ONLY' and at is None)
            point=bool(f and f['fact_id']=='current-request' and f['fact_type']=='VERBATIM_CURRENT_TASK_REQUEST'
                and f['value']==inp['context']['query'] and ref['source_id']=='current-request'
                and ref['observed_at']==ref['valid_from']==ref['valid_to']==inp['scope']['as_of'])
            page=bool(f and f['kind']=='DASHBOARD' and f['fact_type'] in SOURCE_TYPES and f['value'] in allowed
                and ref['version']==base.VERSION and ref['scope']=='LEARNER'
                and ref['source_id']==ref['span_id']==f['fact_id']
                and ref['learner_id']==snapshot.task['scope']['student_id']
                and ref['course_id']==snapshot.task['scope']['course_id'])
            undated=bool(page and snapshot.origin=='CONTROLLED_RECONTEXTUALISATION'
                and all(ref[k] is None for k in ('observed_at','valid_from','valid_to')))
            historical=bool(page and snapshot.origin=='SYNTHETIC'
                and ref['observed_at']==snapshot.task['query_time']==inp['scope']['as_of']
                and ref['valid_from']==snapshot.task['scope']['window_start']
                and ref['valid_to']==snapshot.task['scope']['window_end']
                and ref['valid_to'] is not None and instant(ref['valid_to'])<=instant(inp['scope']['as_of']))
            course=bool(f and course_fact(f,ref))
            for issue in local.issues:
                skip_point=point and issue['path']==path and issue['code'] in ('SOURCE_VALIDITY_ORDER','SOURCE_OUTSIDE_VALIDITY')
                skip_window=ordinary and historical and issue['path']==path and issue['code']=='SOURCE_OUTSIDE_VALIDITY'
                skip_missing=ordinary and (undated or course) and issue['code']=='MISSING_TIME' and issue['path'] in {path+'.'+k for k in ('observed_at','valid_from','valid_to')}
                if not (skip_point or skip_window or skip_missing):report.issues.append(issue)
            if ordinary and (historical or undated or course):
                report.add('A1_DECLARED_SOURCE_TIME_SEMANTICS',path,
                    'Bound archived course evidence; no present-policy or future-availability claim.' if course else
                    'Exact historical observation, not current availability or a future schedule.','WARNING')
        return check
    def validators(bridge):return base.clone_function(api.p1v.validators,{'source_extension':source_check})(bridge)
    def validate_bridge(bridge):return base.clone_function(api.p1v.validate_bridge,{'project':api.project,'validators':validators,'source_extension':source_check})(bridge)
    def validate_candidate(bridge,candidate):return base.clone_function(api.p1v.validate_candidate,{'validate_bridge':validate_bridge,'validators':validators,'source_extension':source_check})(bridge,candidate)
    inherited=base.interfaces.typed_planner();original=inherited.candidate_issues.__globals__['ORIGINAL']
    oi=base.clone_function(original.candidate_issues,{'validate_candidate':validate_candidate})
    op=base.clone_function(original.candidate_payload,{'validate_bridge':validate_bridge,'candidate_issues':oi})
    proxy=SimpleNamespace(**vars(original));proxy.candidate_issues=oi;proxy.candidate_payload=op
    kind=base.clone_function(inherited.plan_kind,{'validate_bridge':validate_bridge})
    issues=base.clone_function(inherited.candidate_issues,{'ORIGINAL':proxy,'plan_kind':kind})
    payload=base.clone_function(inherited.candidate_payload,{'ORIGINAL':proxy,'plan_kind':kind,'candidate_issues':issues})
    return SimpleNamespace(plan_kind=kind,candidate_issues=issues,candidate_payload=payload,validate_bridge=validate_bridge,
                           validate_candidate=validate_candidate,source_check=source_check)


class A1SourceService(base.SourceService):
    def resolve_task_intent(self,request):
        receipt=getattr(self.router,'receipt',None)
        active=bool(base.POLICIES[request.mode][3] and receipt and receipt.get('planning_required') and request.access.planning)
        return resolve_intent(request.query,request.task_intent) if active else super().resolve_task_intent(request)
    def build_planning_bridge(self,request,compiled,task,memory):
        self._a1_evidence=deepcopy(compiled.content['selected_evidence'])
        return super().build_planning_bridge(request,compiled,task,memory)
    def check_planning_bridge(self,bridge):
        return planner_for(self.snapshot,self._a1_evidence).validate_bridge(bridge)


prepare=base.clone_function(base.prepare,{'SourceService':A1SourceService})


def replay_saved(task,binding,mode,saved,*,repaired=True):
    """Replay actual saved module inputs through the same service function body.

    The compiler output and empty native envelope are frozen inputs here. This
    path cannot retrieve, embed or generate and rejects missing/omitted memory.
    """
    source=base.source_for(task,binding)
    assert source==saved['source']
    previous=saved['prepared'];rt=previous['final_request']['runtime_input'];trace=previous['trace']
    assert not rt['memory']['facts'] and not trace['memory_returned_ids']
    request=base.request_for(task,base.Mode(mode),binding);snapshot=base.snapshot_for(task,binding)
    route=trace['route']
    if route:route={k:route[k] for k in ('rag_required','memory_required','planning_required','provider_identity')}
    class SavedRag:
        calls=0
        def retrieve(self,request):
            self.calls+=1
            return SimpleNamespace(sources=tuple(SimpleNamespace(source_id=i) for i in trace['course_returned_ids']))
    class SavedMemory:
        calls=0
        def read(self,request,use):
            self.calls+=1
            return MemoryBundle(deepcopy(rt['memory']),{},deepcopy(trace['memory_diagnostics']))
    rag=SavedRag();memory=SavedMemory()
    service=(A1SourceService if repaired else base.SourceService)(enabled=True,snapshot=snapshot,
        router=base.ReceiptRouter(source['primary'],route),retriever=rag,memory=memory,
        evidence_budget=load(DATA/'CONFIG_PROPOSED.json')['evidence_budget'],request_budget=load(DATA/'CONFIG_PROPOSED.json')['request_budget'])
    real=service.compiler
    compiled_content=deepcopy(rt['evidence'])
    # Canonical journal JSON sorts object keys; original trace arrays preserve
    # the compiler's domain order. Restore that order without changing values.
    destinations={r['evidence_id']:r['domains'] for r in trace['source_fact_destinations']}
    for item in compiled_content['selected_evidence']:
        if item['evidence_id'] in destinations:
            activity=item['content']['activity'];order=destinations[item['evidence_id']]
            assert set(activity)==set(order)
            item['content']['activity']={k:activity[k] for k in order}
    frozen=SimpleNamespace(content=compiled_content,limitations=tuple(rt['evidence_limitations']),
        evidence_ids=tuple(trace['retained_evidence_ids']),compiled_evidence_sha256=trace['compiled_evidence_sha256'])
    service.compiler=SimpleNamespace(compile=lambda **kw:deepcopy(frozen),_tokens=real._tokens,token_budget=real.token_budget)
    prepared=service.prepare(request)
    prepared['trace']['module_state_key']=trace['module_state_key']
    return dict(source=source,prepared=prepared,rag_calls=rag.calls,memory_calls=memory.calls)
