"""Explicitly authored development inputs. No retrieval, scores or expected-ID lookup for links."""
import json
import copy
import hashlib
from m1_common import OWNED, M0, FLAGS, utc, object_sha, write_json, sha
from relations import assertion_text, POLICY, TYPES, PURPOSES


def seal(event):
    event['source_sha256']=object_sha({k:v for k,v in event.items() if k!='source_sha256'})
    return event


def add_link(case,kind,left,right,*,status='ACTIVE'):
    ops={o['fact_id']:o for o in case['setup_operations'] if o.get('fact_id')}
    a,b=ops[left],ops[right]
    content=assertion_text(kind,a['content'],b['content'])
    event={'event_id':'relation-'+str(len(case['relation_events'])+1), 'version':1,
        'learner_id':a['learner_id'],'course_id':a['course_id'],
        'timestamp':'2026-08-19T12:00:00+00:00','role':'USER',
        'confirmation':'EXPLICIT_LEARNER_LINK','status':status,'consent_status':'GRANTED',
        'valid_from':'2026-08-19T12:00:00+00:00','valid_to':None,'supersedes_event_id':None,
        'content':content,'annotation':{'relation_type':kind,'from_fact':left,'to_fact':right,
                                     'span_chars':[0,len(content)]}}
    case['relation_events'].append(seal(event))
    return event


def add_fact(case,alias,kind,content,*,learner=None,course=None,operation='ADD',prior=None,
             valid_to=None,at='2026-08-16T09:00:00+00:00',valid_from=None):
    learner=learner or case['target']['learner_id'];course=course or case['target']['course_id']
    tid='new-source-'+str(len(case['source_turns'])+1)
    role='SYSTEM' if kind=='ACTIVE_PLAN' else 'USER'
    basis='VERIFIED_SYSTEM_EVENT' if role=='SYSTEM' else 'EXPLICIT_USER_STATEMENT'
    case['source_turns'].append({'turn_id':tid,'session_id':'new-setup-session',
        'learner_id':learner,'course_id':course,'timestamp':at,'role':role,'content':content,
        'provenance':'MODEL_AUTHORED_SYNTHETIC_SOURCE_TURN'})
    case['setup_operations'].append({'fact_id':alias,'source_turn_id':tid,'learner_id':learner,
        'course_id':course,'operation':operation,'memory_type':kind,'content':content,
        'target_fact_id':prior,'claim_basis':basis,'confidence':1.0,'consent_status':'GRANTED',
        'valid_from':valid_from or at,'valid_to':valid_to,'evidence_span':content,
        'source_span_chars':[0,len(content)]})


def variant(case,name):
    c=copy.deepcopy(case);c['case_id']=name;c['family_id']=name
    return c


def opaque_variant(case,name):
    c=variant(case,name)
    ids=set()
    def collect(v,k=''):
        if isinstance(v,dict):
            for key,x in v.items():collect(x,key)
        elif isinstance(v,list):
            for x in v:collect(x,k)
        elif isinstance(v,str) and (k.endswith('_id') or k in ('from_fact','to_fact')):ids.add(v)
    collect(c)
    mapping={s:'opaque-'+hashlib.sha256(('M1-ID-SWAP:'+s).encode()).hexdigest()[:18] for s in ids}
    def swap(v,k=''):
        if isinstance(v,dict):return {key:swap(x,key) for key,x in v.items()}
        if isinstance(v,list):return [swap(x,k) for x in v]
        if isinstance(v,str) and v in mapping and (k.endswith('_id') or k in ('from_fact','to_fact')):return mapping[v]
        return v
    c=swap(c);c['case_id']=name;c['family_id']=name
    c['relation_events'].reverse()
    for e in c['relation_events']:seal(e)
    return c,mapping


def main():
    out=OWNED/'fixtures'
    assert not (out/'linked_runtime_v1.json').exists()
    original=json.loads((M0/'fixtures/synthetic_runtime.json').read_text())
    cases=[];purposes={}
    for old in original:
        c=variant(old,old['case_id'].replace('SYN-M0','SYN-M1-LINKED'))
        c['fixture_version']='M1_LINKED_SOURCE_V1';c['relation_events']=[]
        c['purpose']='GOAL_RECALL' if old['case_id']=='SYN-M0-01' else 'PLAN_CONTINUATION'
        cases.append(c)
    add_link(cases[0],'CONSTRAINT_APPLIES_TO_GOAL','f01-time','f01-goal')
    add_link(cases[2],'COMPLETION_BELONGS_TO_PLAN','f03-done','f03-plan')
    add_link(cases[12],'PLAN_PURSUES_GOAL','f13-plan','f13-goal')
    add_link(cases[12],'CONSTRAINT_APPLIES_TO_GOAL','f13-bound','f13-goal')
    # Expectations below are test-only outputs, never used by add_link or runtime.
    old_eval=json.loads((M0/'fixtures/synthetic_evaluation_only.json').read_text())
    evaluation=[]
    for e,c in zip(old_eval,cases):
        evaluation.append({'case_id':c['case_id'],'required':e['required_memory_fact_ids'],
            'acceptable_extra':[], 'source_class':e['source_class'],
            'ambiguous':e['source_class']=='AMBIGUOUS_SOURCE',
            'original_case_id':e['case_id'],'flags':FLAGS})
    def add(c,required,category,*,extra=None,ambiguous=False):
        cases.append(c);evaluation.append({'case_id':c['case_id'],'required':required,
            'acceptable_extra':extra or [],'source_class':category,'ambiguous':ambiguous,'flags':FLAGS})
    c=variant(cases[0],'SYN-M1-UNRELATED-GOAL')
    add_fact(c,'unrelated-goal','GOAL','I want to bake a sourdough loaf.')
    add(c,['f01-goal','f01-time'],'UNRELATED_SAME_LEARNER_GOAL')
    c=variant(cases[12],'SYN-M1-AMBIGUOUS-PLANS')
    add_fact(c,'second-plan','ACTIVE_PLAN','My other current plan is to label the geometry diagrams.')
    add(c,[],'AMBIGUOUS_SOURCE',ambiguous=True)
    c=variant(cases[0],'SYN-M1-CROSS-COURSE')
    add_fact(c,'foreign-goal','GOAL','I want to measure pendulum oscillations.',course='synthetic-course-physics')
    add_link(c,'CONSTRAINT_APPLIES_TO_GOAL','f01-time','foreign-goal')
    add(c,['f01-goal','f01-time'],'CROSS_COURSE_LINK')
    c=variant(cases[0],'SYN-M1-CROSS-LEARNER')
    add_fact(c,'foreign-goal','GOAL','I want to identify leaf species.',learner='synthetic-other-learner')
    add_link(c,'CONSTRAINT_APPLIES_TO_GOAL','f01-time','foreign-goal')
    add(c,['f01-goal','f01-time'],'CROSS_LEARNER_LINK')
    c=variant(cases[0],'SYN-M1-EXPIRED-NODE')
    c['setup_operations'][0]['valid_to']='2026-08-20T00:00:00+00:00'
    add(c,['f01-time'],'EXPIRED_LINKED_NODE')
    c=variant(cases[0],'SYN-M1-DELETED-NODE')
    add_fact(c,None,None,'Delete my saved goal.',operation='DELETE',prior='f01-goal',at='2026-08-19T13:00:00+00:00')
    add(c,['f01-time'],'DELETED_LINKED_NODE')
    c=variant(cases[0],'SYN-M1-VISIBLE-NODE')
    c['target']['visible_history']=[{'role':'user','content':c['setup_operations'][0]['content']}]
    add(c,['f01-time'],'VISIBLE_DUPLICATE')
    c=variant(cases[0],'SYN-M1-NO-SEED')
    c['target']['query']='Which zephyr remains?'
    add(c,[],'NO_SEED_UNSUPPORTED_QUERY')
    c=variant(cases[0],'SYN-M1-SOURCE-MISSING')
    c['setup_operations']=c['setup_operations'][1:];c['source_turns']=c['source_turns'][1:]
    add(c,['f01-time'],'MISSING_ENDPOINT_SOURCE')
    c=variant(cases[2],'SYN-M1-COMPLETION-CORRECTION')
    add_fact(c,'corrected-progress','CORRECTION','Correction: I only opened the worked example and have not finished it.',
             operation='SUPERSEDE',prior='f03-done',at='2026-08-18T09:00:00+00:00')
    add(c,['f03-plan','corrected-progress'],'COMPLETION_CORRECTION')
    c=variant(cases[0],'SYN-M1-WITHDRAWN-EDGE')
    c['relation_events'][0]['status']='WITHDRAWN';seal(c['relation_events'][0])
    add(c,['f01-goal','f01-time'],'WITHDRAWN_RELATION_SOURCE')
    c=variant(cases[0],'SYN-M1-UNSUPPORTED-LINK')
    e=c['relation_events'][0];e['content']='There is no declared relationship between the two facts.';e['annotation']['span_chars']=[0,len(e['content'])];seal(e)
    add(c,['f01-goal','f01-time'],'UNSUPPORTED_RELATION_STATEMENT')
    c=variant(cases[2],'SYN-M1-ACCEPTED-ACTION-CHAIN')
    c['relation_events']=[]
    add_fact(c,'accepted-action','PROGRESS_UPDATE','I accept this action: review the worked example.',at='2026-08-12T09:00:00+00:00')
    add_link(c,'ACCEPTED_ACTION_BELONGS_TO_PLAN','accepted-action','f03-plan')
    add_link(c,'COMPLETION_OF_ACTION','f03-done','accepted-action')
    add(c,['f03-plan','accepted-action','f03-done'],'EXPLICIT_ACCEPTED_ACTION_CHAIN')
    # Budget fixture intentionally has more supported constraints than the fixed cap.
    c=variant(cases[12],'SYN-M1-BUDGET-OMISSION')
    for i,text in enumerate(['I cannot use headphones.','I cannot access a printer.','I need large diagrams.',
                            'I cannot use coloured ink.','I need a quiet room.','I cannot stand for long.']):
        alias='limit-'+str(i);add_fact(c,alias,'CONSTRAINT',text)
        add_link(c,'CONSTRAINT_APPLIES_TO_GOAL',alias,'f13-goal')
    add(c,['f13-plan','f13-goal','f13-bound']+['limit-'+str(i) for i in range(6)],'BUDGET_PRESSURE')
    metamorphic=[]
    for i in (0,2,12):
        c,mapping=opaque_variant(cases[i], 'SYN-M1-OPAQUE-'+str(i+1))
        e=evaluation[i]
        add(c,[mapping[x] for x in e['required']],'OPAQUE_GRAPH_EQUIVALENCE')
        metamorphic.append({'original':cases[i]['case_id'],'variant':c['case_id'],'alias_mapping':mapping})
    write_json(out/'linked_runtime_v1.json',cases)
    write_json(out/'test_only_expectations_v1.json',evaluation)
    write_json(out/'test_only_metamorphic_pairs.json',metamorphic)
    changes=[]
    for old,c in zip(original,cases[:16]):
        changes.append({'original_case_id':old['case_id'],'linked_case_id':c['case_id'],
            'query_unchanged':old['target']==c['target'],
            'source_turns_unchanged':old['source_turns']==c['source_turns'],
            'setup_operations_unchanged':old['setup_operations']==c['setup_operations'],
            'added_relation_events':c['relation_events'],'new_task_purpose':c['purpose']})
    write_json(out/'SOURCE_ENRICHMENT_LOG.json',changes)
    write_json(out/'FIXTURE_FREEZE.json',{'execution_utc':utc(),'stage':'BEFORE_LINKED_RETRIEVAL',
        'flags':FLAGS,'case_count':len(cases),'policy':POLICY,
        'files':[{'path':n,'sha256':sha(out/n)} for n in ('linked_runtime_v1.json',
          'test_only_expectations_v1.json','test_only_metamorphic_pairs.json','SOURCE_ENRICHMENT_LOG.json')],
        'policy_document_sha256':sha(OWNED/'LINK_PROVENANCE_AND_EXPANSION_POLICY.md'),
        'not_a_held_out_test':True,'no_query_or_threshold_selection_using_retrieval':True})
    write_json(OWNED/'RELATION_SCHEMA_V1.json',{'version':'M1_RELATIONS_V1','format':'Executable strict validator: code/relations.py',
       'relation_types_native_endpoint_types':TYPES,'purpose_link_types':PURPOSES,'policy':POLICY,
       'edge_required':['edge_id','relation_type','from_id','to_id','from_version','to_version',
           'learner_id','course_id','source_event_id','source_version','source_sha256','span_chars'],
       'event_status':['ACTIVE','WITHDRAWN','SUPERSEDED'],
       'origin_and_confirmation':{'USER':'EXPLICIT_LEARNER_LINK','SYSTEM':'VERIFIED_SYSTEM_LINK_ACCEPTANCE_UNKNOWN'},
       'no_implicit_relations':True,'accepted_action_native_mapping':'PROGRESS_UPDATE with explicit learner acceptance statement; role preserved',
       'native_store_schema_changed':False})
    print('Frozen linked synthetic development cases:',len(cases))

if __name__=='__main__':main()
