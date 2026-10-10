"""Versioned provenance writer and bounded read-only relationship expansion."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from m1_common import object_sha
from fixture_validation import assert_runtime_separation
from state_harness import ReadOnlyStore, target_read, snapshot
from utils.c4_memory.c4_memory_store import normalise_timestamp
from utils.c4_memory.c4_memory_retriever import C4MemoryRetriever, _already_visible, _history_texts

VERSION = 'M1_RELATIONS_V1'
TYPES = {
    'PLAN_PURSUES_GOAL': ('ACTIVE_PLAN', 'GOAL'),
    'CONSTRAINT_APPLIES_TO_GOAL': ('CONSTRAINT', 'GOAL'),
    'CONSTRAINT_APPLIES_TO_PLAN': ('CONSTRAINT', 'ACTIVE_PLAN'),
    'COMPLETION_BELONGS_TO_PLAN': ('COMPLETED_ACTION', 'ACTIVE_PLAN'),
    'ACCEPTED_ACTION_BELONGS_TO_PLAN': ('PROGRESS_UPDATE', 'ACTIVE_PLAN'),
    'COMPLETION_OF_ACTION': ('COMPLETED_ACTION', 'PROGRESS_UPDATE'),
}
PURPOSES = {
    'GOAL_RECALL': ('CONSTRAINT_APPLIES_TO_GOAL',),
    'PLAN_CONTINUATION': tuple(TYPES),
    'COMPLETION_RECALL': ('COMPLETION_BELONGS_TO_PLAN','ACCEPTED_ACTION_BELONGS_TO_PLAN','COMPLETION_OF_ACTION'),
}
POLICY = {'version': 'M1_EXPANSION_V1', 'top_k': 5, 'max_added': 4,
          'max_final': 9, 'max_depth': 2, 'max_edges': 12}


def assertion_text(kind, left, right):
    templates = {
        'PLAN_PURSUES_GOAL': 'The plan {left} pursues the goal {right}.',
        'CONSTRAINT_APPLIES_TO_GOAL': 'The constraint {left} applies to the goal {right}.',
        'CONSTRAINT_APPLIES_TO_PLAN': 'The constraint {left} applies to the plan {right}.',
        'COMPLETION_BELONGS_TO_PLAN': 'The completion report {left} belongs to the plan {right}.',
        'ACCEPTED_ACTION_BELONGS_TO_PLAN': 'The explicitly accepted action {left} belongs to the plan {right}.',
        'COMPLETION_OF_ACTION': 'The completion report {left} completes the accepted action {right}.',
    }
    import json
    return templates[kind].format(left=json.dumps(left, ensure_ascii=False),
                                  right=json.dumps(right, ensure_ascii=False))


def exact_keys(value, keys, error):
    if not isinstance(value, dict) or set(value) != set(keys): raise ValueError(error)


def compile_sidecar(runtime, databases, aliases):
    """Legitimate setup only; evaluation labels/requirements are never accepted."""
    assert_runtime_separation(runtime)
    turns = {t['turn_id']: t for t in runtime['source_turns']}
    if len(turns) != len(runtime['source_turns']): raise ValueError('DUPLICATE_SOURCE_ID')
    nodes, by_alias = {}, {}
    for op in runtime['setup_operations']:
        if op['operation'] not in ('ADD','UPDATE','SUPERSEDE') or op['fact_id'] not in aliases: continue
        turn = turns[op['source_turn_id']]
        with ReadOnlyStore(databases[op['course_id']], clock=lambda: runtime['target']['as_of']) as store:
            rec = store.get_memory(op['learner_id'], aliases[op['fact_id']])
        if rec is None: continue
        # A rejected/no-op duplicate cannot overwrite the original source binding.
        if rec.source_turn_id != op['source_turn_id']: continue
        node = {'native_id': rec.memory_id, 'native_version': rec.version,
                'content_sha256': rec.content_sha256, 'memory_type': rec.memory_type,
                'learner_id': rec.student_id, 'course_id': op['course_id'],
                'source_ref': {'event_id': turn['turn_id'], 'source_version': 1,
                    'session_id': turn['session_id'], 'event_sha256': object_sha(turn),
                    'span_chars': op['source_span_chars'], 'observed_at': turn['timestamp'],
                    'origin': turn['role'], 'claim_basis': op['claim_basis'],
                    'confirmation': 'LEARNER_STATED' if turn['role']=='USER' else 'SYSTEM_RECORDED_LEARNER_ACCEPTANCE_UNKNOWN'}}
        nodes[rec.memory_id] = node
        by_alias[op['fact_id']] = (node, op['content'])
    events = {}
    edges, rejected = [], []
    for event in runtime['relation_events']:
        event_id = event.get('event_id')
        try:
            exact_keys(event, ('event_id','version','learner_id','course_id','timestamp','role',
                'confirmation','status','consent_status','valid_from','valid_to','supersedes_event_id',
                'content','annotation','source_sha256'), 'RELATION_EVENT_SCHEMA')
            if not isinstance(event_id,str) or not event_id or event_id in events: raise ValueError('DUPLICATE_OR_INVALID_EVENT_ID')
            payload = {k:v for k,v in event.items() if k != 'source_sha256'}
            if object_sha(payload) != event['source_sha256']: raise ValueError('SOURCE_HASH_MISMATCH')
            a = event['annotation']
            exact_keys(a, ('relation_type','from_fact','to_fact','span_chars'), 'RELATION_ANNOTATION_SCHEMA')
            if not isinstance(a['from_fact'],str) or not isinstance(a['to_fact'],str): raise ValueError('AMBIGUOUS_ENDPOINT')
            if a['from_fact'] not in by_alias or a['to_fact'] not in by_alias: raise ValueError('MISSING_ENDPOINT')
            left, right = by_alias[a['from_fact']], by_alias[a['to_fact']]
            kind = a['relation_type']
            if kind not in TYPES or (left[0]['memory_type'],right[0]['memory_type']) != TYPES[kind]: raise ValueError('RELATION_TYPE_MISMATCH')
            action = left if kind=='ACCEPTED_ACTION_BELONGS_TO_PLAN' else (right if kind=='COMPLETION_OF_ACTION' else None)
            if action and (action[0]['source_ref']['origin']!='USER' or not action[1].startswith('I accept this action:')):
                raise ValueError('ACTION_ACCEPTANCE_NOT_EXPLICIT')
            if left[0]['native_id']==right[0]['native_id']: raise ValueError('SELF_LINK')
            if any(n[0]['learner_id'] != event['learner_id'] or n[0]['course_id'] != event['course_id'] for n in (left,right)): raise ValueError('CROSS_LEARNER_OR_COURSE')
            if (event['role'],event['confirmation']) not in {
                ('USER','EXPLICIT_LEARNER_LINK'),('SYSTEM','VERIFIED_SYSTEM_LINK_ACCEPTANCE_UNKNOWN')}:
                raise ValueError('UNSUPPORTED_RELATION_ORIGIN')
            if type(event['version']) is not int or event['version']<1: raise ValueError('INVALID_SOURCE_VERSION')
            if event['status'] not in ('ACTIVE','WITHDRAWN','SUPERSEDED'): raise ValueError('INVALID_SOURCE_STATUS')
            if event['consent_status'] not in ('GRANTED','NOT_REQUIRED','WITHDRAWN'): raise ValueError('INVALID_SOURCE_CONSENT')
            at = normalise_timestamp(event['timestamp'])
            if at >= normalise_timestamp(runtime['target']['as_of']): raise ValueError('RELATION_NOT_BEFORE_TARGET')
            if any(at < normalise_timestamp(n[0]['source_ref']['observed_at']) for n in (left,right)): raise ValueError('RELATION_PRECEDES_FACT')
            start=normalise_timestamp(event['valid_from'])
            if event['valid_to'] is not None and normalise_timestamp(event['valid_to']) <= start: raise ValueError('INVALID_SOURCE_VALIDITY')
            span = a['span_chars']
            if not isinstance(span,list) or len(span)!=2 or any(type(n) is not int for n in span) or not 0<=span[0]<span[1]<=len(event['content']): raise ValueError('INVALID_RELATION_SPAN')
            if event['content'][span[0]:span[1]] != assertion_text(kind,left[1],right[1]): raise ValueError('RELATION_NOT_IN_SOURCE')
            events[event_id] = deepcopy(event)
            edges.append({'edge_id': object_sha({'event':event_id,'version':event['version'],'kind':kind}),
                'relation_type':kind, 'from_id':left[0]['native_id'],'to_id':right[0]['native_id'],
                'from_version':left[0]['native_version'],'to_version':right[0]['native_version'],
                'learner_id':event['learner_id'],'course_id':event['course_id'],
                'source_event_id':event_id,'source_version':event['version'],
                'source_sha256':event['source_sha256'],'span_chars':span})
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'event_id': event_id, 'reason': str(exc)})
    graph = {'version': VERSION, 'nodes': nodes, 'source_events':events,'edges':edges}
    graph['sha256'] = object_sha(graph)
    return graph, rejected


@dataclass(frozen=True)
class ReadOnlyEnvelope:
    canonical_json: str
    @property
    def payload(self):
        import json
        return json.loads(self.canonical_json)


def read_bundle(databases, graph, request, *, expand, backend=None):
    """No expected-ID or scenario argument. Only runtime scope/purpose + validated setup graph."""
    exact_keys(request, ('target','purpose'), 'REQUEST_SCHEMA')
    assert_runtime_separation(request)
    target, purpose = request['target'], request['purpose']
    if purpose not in PURPOSES: raise ValueError('UNKNOWN_TASK_PURPOSE')
    if graph['version'] != VERSION or object_sha({k:v for k,v in graph.items() if k!='sha256'}) != graph['sha256']: raise ValueError('SIDECAR_INTEGRITY')
    database = databases[target['course_id']]
    original = target_read(database,target,backend,gate='FORCED_ENGINEERING_DIAGNOSTIC')
    seed_items = original['envelope']['selected_memory_items']
    seed_ids = [v['memory_id'] for v in seed_items]
    trace = {'policy':POLICY, 'purpose':purpose, 'condition':'EXPANDED' if expand else 'UNEXPANDED',
             'original_seed_ids':seed_ids, 'original_seed_items':seed_items,
             'traversed_edges':[], 'candidate_facts':[], 'exclusions':[], 'omitted_facts':[],
             'kept_facts':[], 'graph_sha256':graph['sha256'], 'original_read':original}
    with ReadOnlyStore(database, clock=lambda:target['as_of']) as store:
        before=object_sha(snapshot(store))
        active=store.list_active_memories(target['learner_id'],at=target['as_of'])
        active,_=C4MemoryRetriever._resolve_active_conflicts(active)
        active_ids={r.memory_id for r in active}
        history=_history_texts(target['visible_history'])
        now=normalise_timestamp(target['as_of'])
        def eligible(mid):
            node=graph['nodes'].get(mid)
            if not node: return None,'MISSING_SOURCE_BINDING'
            if node['course_id']!=target['course_id'] or node['learner_id']!=target['learner_id']: return None,'CROSS_SCOPE'
            if not store.is_memory_enabled(target['learner_id']): return None,'LEARNER_DISABLED'
            rec=store.get_memory(target['learner_id'],mid)
            if rec is None: return None,'SOURCE_MISSING'
            if rec.status!='ACTIVE': return None,rec.status
            if rec.consent_status not in ('GRANTED','NOT_REQUIRED'): return None,'CONSENT_WITHDRAWN'
            if rec.valid_from>now: return None,'FUTURE_VALIDITY'
            if rec.valid_to is not None and now>=rec.valid_to: return None,'EXPIRED'
            if mid not in active_ids: return None,'ACTIVE_CONFLICT_EXCLUDED'
            if rec.version!=node['native_version'] or rec.content_sha256!=node['content_sha256']: return None,'STALE_SOURCE_VERSION'
            if normalise_timestamp(rec.created_at)>now or normalise_timestamp(node['source_ref']['observed_at'])>now: return None,'FUTURE_SOURCE'
            if _already_visible(rec.content,history): return None,'VISIBLE_DUPLICATE'
            return rec,None
        def edge_reason(edge):
            if edge['learner_id']!=target['learner_id'] or edge['course_id']!=target['course_id']: return 'CROSS_SCOPE'
            event=graph['source_events'].get(edge['source_event_id'])
            if not event: return 'RELATION_SOURCE_MISSING'
            if event['status']!='ACTIVE' or event['consent_status'] not in ('GRANTED','NOT_REQUIRED'): return 'RELATION_WITHDRAWN_OR_SUPERSEDED'
            if any(e['supersedes_event_id']==event['event_id'] and normalise_timestamp(e['timestamp'])<=now for e in graph['source_events'].values()): return 'RELATION_SUPERSEDED'
            if event['version']!=edge['source_version'] or event['source_sha256']!=edge['source_sha256']: return 'RELATION_VERSION_MISMATCH'
            if normalise_timestamp(event['timestamp'])>now or normalise_timestamp(event['valid_from'])>now: return 'RELATION_FUTURE'
            if event['valid_to'] is not None and now>=normalise_timestamp(event['valid_to']): return 'RELATION_EXPIRED'
            for key, vkey in [('from_id','from_version'),('to_id','to_version')]:
                rec,reason=eligible(edge[key])
                if reason: return reason
                if rec.version!=edge[vkey]: return 'STALE_EDGE_VERSION'
            return None
        records={}
        for mid in seed_ids:
            rec,reason=eligible(mid)
            if reason: trace['exclusions'].append({'native_id':mid,'stage':'SEED_RECHECK','reason':reason})
            else: records[mid]=rec
        plans=[r.memory_id for r in active if r.memory_type=='ACTIVE_PLAN' and eligible(r.memory_id)[1] is None]
        ambiguous=len(plans)>1
        trace['ambiguous_plan_ids']=plans if ambiguous else []
        queue=deque((mid,0) for mid in records)
        seen_edges=set(); added=0
        edges=sorted(graph['edges'],key=lambda e:(list(TYPES).index(e['relation_type']),
            graph['source_events'].get(e['source_event_id'],{}).get('timestamp',''),
            graph['nodes'].get(e['from_id'],{}).get('content_sha256',''),
            graph['nodes'].get(e['to_id'],{}).get('content_sha256','')))
        if expand and not ambiguous:
            while queue:
                current,depth=queue.popleft()
                for edge in edges:
                    if edge['edge_id'] in seen_edges or current not in (edge['from_id'],edge['to_id']): continue
                    other=edge['to_id'] if edge['from_id']==current else edge['from_id']
                    if edge['relation_type'] not in PURPOSES[purpose]:
                        trace['omitted_facts'].append({'native_id':other,'edge_id':edge['edge_id'],'reason':'LINK_TYPE_OUTSIDE_TASK_PURPOSE'})
                        continue
                    if depth>=POLICY['max_depth'] or len(seen_edges)>=POLICY['max_edges']:
                        trace['omitted_facts'].append({'native_id':other,'edge_id':edge['edge_id'],'reason':'DEPTH_OR_EDGE_BUDGET'})
                        continue
                    seen_edges.add(edge['edge_id'])
                    trace['candidate_facts'].append({'native_id':other,'via_edge':edge['edge_id'],'depth':depth+1})
                    reason=edge_reason(edge)
                    trace['traversed_edges'].append({'edge':edge,'from_seed_or_node':current,'candidate':other,'reason':reason or 'AUTHORIZED'})
                    if reason:
                        trace['exclusions'].append({'native_id':other,'edge_id':edge['edge_id'],'reason':reason})
                        continue
                    if other in records: continue
                    if added>=POLICY['max_added'] or len(records)>=POLICY['max_final']:
                        trace['omitted_facts'].append({'native_id':other,'edge_id':edge['edge_id'],'reason':'FACT_BUDGET'})
                        continue
                    records[other]=eligible(other)[0];added+=1;queue.append((other,depth+1))
        trace['kept_facts']=list(records)
        trace['added_facts']=[m for m in records if m not in seed_ids]
        trace['expansion_status']='AMBIGUOUS' if ambiguous else ('NO_SEED' if not seed_ids else ('EXECUTED' if expand else 'LINKS_IGNORED'))
        retained_edges=[e for e in edges if e['from_id'] in records and e['to_id'] in records and edge_reason(e) is None]
        facts=[]
        for mid,rec in records.items():
            facts.append({'native_id':mid,'memory_type':rec.memory_type,'content':rec.content,
                'learner_id':rec.student_id,'course_id':target['course_id'],'native_version':rec.version,
                'source_ref':graph['nodes'][mid]['source_ref'],
                'validity':{'valid_from':rec.valid_from,'valid_to':rec.valid_to,
                    'meaning':'NO_DECLARED_EXPIRY_UNDER_NATIVE_ACTIVE_SQL' if rec.valid_to is None else 'BOUNDED_INTERVAL',
                    'verified_at':target['as_of'],'future_availability':'UNKNOWN'},
                'consent_status':rec.consent_status,'supersedes_native_id':rec.supersedes_memory_id})
        missing=[]
        if ambiguous: missing.append('PLAN_ANTECEDENT_UNRESOLVED')
        if not records: missing.append('NO_AUTHORIZED_RELEVANCE_SEED_OR_SOURCE')
        if not retained_edges: missing.append('NO_RETAINED_SOURCE_GROUNDED_RELATIONS')
        if trace['exclusions'] or trace['omitted_facts']: missing.append('LINKED_INFORMATION_EXCLUDED_OR_BUDGET_OMITTED')
        missing.append('NATURAL_LANGUAGE_CONSTRAINT_VALUES_NOT_PARSED')
        body={'version':'M1_PLANNER_ENVELOPE_DRAFT_V1','read_only':True,
              'scope':{k:target[k] for k in ('learner_id','course_id','session_id','as_of','horizon')},
              'status':'AMBIGUOUS' if ambiguous else ('AVAILABLE' if facts else 'NO_AUTHORIZED_SOURCE_OR_MATCH'),
              'facts':facts,'source_link_edges':retained_edges,
              'active_plan_ids':[f['native_id'] for f in facts if f['memory_type']=='ACTIVE_PLAN'],
              'chosen_active_plan_id':None if ambiguous else next((f['native_id'] for f in facts if f['memory_type']=='ACTIVE_PLAN'),None),
              'completed_action_ids':[f['native_id'] for f in facts if f['memory_type']=='COMPLETED_ACTION'],
              'accepted_action_ids':[e['from_id'] for e in retained_edges if e['relation_type']=='ACCEPTED_ACTION_BELONGS_TO_PLAN'],
              'structured_constraints':[], 'missing_information':missing,
              'semantic_support':'NOT_CHECKED','planner_consumption':'NOT_RUN'}
        assert before==object_sha(snapshot(store))
        trace['readonly_state_unchanged']=True
    # Immutable canonical transport; callers receive fresh decoded copies.

    import json
    return ReadOnlyEnvelope(json.dumps(body,sort_keys=True,ensure_ascii=False)),trace
