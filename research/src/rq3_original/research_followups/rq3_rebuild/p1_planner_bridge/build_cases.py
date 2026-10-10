"""New exposed synthetic bridge sources; no score tuning or independent-test status."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from p1bridge.contracts import VERSION,POLICY_ID,POLICY_SHA,canonical
from p1bridge.projection import classify_exact_request
from tools.build_fixtures import baseline as p0_baseline,window

ROOT=Path(__file__).resolve().parent
LABELS=['MODEL_AUTHORED','SYNTHETIC_DEVELOPMENT_FIXTURE','NOT_FOR_INDEPENDENT_TEST']


def fields(**changes):
    value=dict(goal=None,constraints=None,completed_task_ids=[],active_plan=None,review_permissions=[],duration_estimates=[])
    value.update(changes);return value


def memory(mid,value,origin='LEARNER_STATED_FACT',kind='STRUCTURED_BRIDGE_FIELDS',valid_to=None):
    content=canonical(value) if isinstance(value,dict) else value
    digest=sha256(content.encode()).hexdigest()
    pair={'LEARNER_STATED_FACT':('USER','EXPLICIT_USER_STATEMENT'),
        'SYSTEM_ORIGIN_PLAN':('SYSTEM','VERIFIED_SYSTEM_EVENT'),
        'EXPLICITLY_ACCEPTED_PLAN':('USER','EXPLICIT_ACCEPTANCE_EVENT'),
        'OBSERVED_COMPLETED_ACTION':('OBSERVER','VERIFIED_SYSTEM_EVENT'),
        'MODEL_INFERENCE':('MODEL','MODEL_OUTPUT'),'UNKNOWN':('UNKNOWN','UNKNOWN')}[origin]
    native=dict(memory_id=mid,memory_type=kind,content=content,
        timestamp_version=dict(created_at='2026-09-01T08:00:00+02:00',last_confirmed_at='2026-09-01T08:00:00+02:00',valid_from='2026-09-01T08:00:00+02:00',valid_to=valid_to,version=1,status='ACTIVE'),
        provenance=dict(source_session_id='synthetic-prior-session',source_turn_id=mid+'-turn',supersedes_memory_id=None,consent_status='GRANTED',content_sha256=digest),
        read_only_evidence=dict(representation='C4_READ_ONLY_MEMORY_EVIDENCE_V1',mutable=False,content=content,content_sha256=digest),
        relevance_components={**{k:0.0 for k in ('lexical','semantic','memory_type_alignment','recency','importance','confidence','fusion')},'lexical_supported':False,'semantic_supported':False})
    binding=dict(learner_id='learner-synthetic',course_id='course-synthetic',current_version='1',superseded_by=None,enabled=True,origin=origin,
        origin_basis=pair[1],source_role=pair[0],source_span=dict(text=content,start=0,end=len(content)),
        encoding='P1_EXPLICIT_FIELDS_JSON_V1' if isinstance(value,dict) else 'FREE_TEXT',validity_policy=dict(policy_id=POLICY_ID,source_sha256=POLICY_SHA))
    return dict(native=native,binding=binding)


def change_fields(mem,**changes):
    values=json.loads(mem['native']['content']);values.update(changes)
    content=canonical(values);digest=sha256(content.encode()).hexdigest()
    mem['native']['content']=content;mem['native']['provenance']['content_sha256']=digest
    mem['native']['read_only_evidence'].update(content=content,content_sha256=digest)
    mem['binding']['source_span']=dict(text=content,start=0,end=len(content))


def ordinary():
    base,plan=p0_baseline()
    base['scope'].update(timezone=None,horizon=None)
    base['context']['query']='Give me next steps without scheduling dates.'
    base['context']['visible_conversation']=['Synthetic source request: continue the explicit plan and respect my stated budget.']
    base['goals']=[];base['completed_tasks']=[];base['active_plan']=None
    base['facts']=[];base['soft_preferences']=[]
    base['hard_constraints']['budget']=dict(required=False,minutes=None)
    base['hard_constraints']['schedule']=dict(required=False,allowed_windows=None,excluded_windows=[],forbidden_weekdays=[],non_overlap=True)
    base['hard_constraints']['required_evidence_ids']=[]
    memories=[memory('mem-goal',fields(goal=dict(goal_id='goal-practice',text='Complete one synthetic practice exercise.'))),
        memory('mem-budget',fields(constraints=dict(budget=dict(required=True,minutes=30)))),
        memory('mem-plan',fields(active_plan=dict(plan_id='active-demo',goal_id='goal-practice',remaining_task_ids=['task-read','task-practice'],completed_task_ids=[])),origin='SYSTEM_ORIGIN_PLAN',kind='ACTIVE_PLAN'),
        memory('mem-done',fields(completed_task_ids=['task-read']),origin='OBSERVED_COMPLETED_ACTION',kind='COMPLETED_ACTION')]
    memories[-1]['native']['timestamp_version'].update(created_at='2026-09-05T08:00:00+02:00',last_confirmed_at='2026-09-05T08:00:00+02:00',valid_from='2026-09-05T08:00:00+02:00')
    source=dict(schema_version=VERSION,base_input=base,task_request=classify_exact_request(base['context']['query']),
        selected_memory=memories,memory_status='AVAILABLE',future_use_policy='RECONFIRM_FOR_SCHEDULE')
    plan['evidence_refs']=['mem-goal','mem-plan'];a=plan['actions'][0]
    a['schedule']=None;a['evidence_refs']=['mem-goal','mem-done'];a['estimated_duration'].update(origin='MODEL_ESTIMATE',uncertainty='Unquantified candidate estimate; actual learner duration unknown.')
    return source,plan


def scheduled(source,plan):
    base=source['base_input'];base['context']['query']='Schedule these tasks in the stated time windows.'
    source['task_request']=classify_exact_request(base['context']['query'])
    base['scope'].update(timezone='Europe/Oslo',horizon=window('2026-09-07T00:00:00+02:00','2026-09-08T00:00:00+02:00'))
    base['hard_constraints']['schedule'].update(required=True,allowed_windows=[window()])
    plan['actions'][0]['schedule']=window('2026-09-07T09:00:00+02:00','2026-09-07T09:20:00+02:00')


def make_cases():
    runtime=[]; mocks=[]; expected=[]
    def add(name,mutate=None,status='PASSED_ENCODED_CHECKS',codes=(),repairs=0,sequence=None):
        source,plan=ordinary()
        if mutate:mutate(source,plan)
        runtime.append(dict(case_id=name,labels=LABELS,source_lineage='NEW_P1_EXPLICIT_JSON_SOURCE_FIELDS; P0 shape reused as exposed regression scaffolding only.',runtime_input=source))
        mocks.append(dict(case_id=name,max_repairs=repairs,candidates=sequence(plan) if sequence else [plan]))
        expected.append(dict(case_id=name,expected_status=status,required_issue_codes=list(codes)))
    add('ordinary_open_plan_updated_completion')
    add('ordinary_no_budget',lambda s,p:s['selected_memory'].pop(1))
    add('bounded_schedule',lambda s,p:(scheduled(s,p),[m['native']['timestamp_version'].update(valid_to='2026-09-30T00:00:00+02:00') for m in s['selected_memory']]))
    add('open_schedule_requires_reconfirmation',scheduled,status='BOUNDED_REPAIR_EXHAUSTED',codes=['OPEN_ENDED_FUTURE_UNCONFIRMED'])
    add('open_schedule_warning_alternative',lambda s,p:(scheduled(s,p),s.update(future_use_policy='WARN_SNAPSHOT_ONLY')),codes=['OPEN_ENDED_FUTURE_UNCONFIRMED'])
    add('scheduled_missing_timezone',lambda s,p:(scheduled(s,p),s['base_input']['scope'].update(timezone=None)),status='NEEDS_INFORMATION',codes=['MISSING_TIMEZONE'])
    add('unknown_null_policy',lambda s,p:s['selected_memory'][0]['binding'].update(validity_policy=None),status='NEEDS_INFORMATION',codes=['MISSING_TIME'])
    add('unknown_policy_hash',lambda s,p:s['selected_memory'][0]['binding']['validity_policy'].update(source_sha256='unverified'),status='NEEDS_INFORMATION',codes=['MISSING_TIME'])
    add('expired_constraint',lambda s,p:s['selected_memory'][1]['native']['timestamp_version'].update(valid_to='2026-09-05T00:00:00+02:00'),status='INVALID_INPUT',codes=['SOURCE_OUTSIDE_VALIDITY'])
    add('future_open_valid_from',lambda s,p:s['selected_memory'][0]['native']['timestamp_version'].update(valid_from='2026-09-10T00:00:00+02:00'),status='INVALID_INPUT',codes=['SOURCE_OUTSIDE_VALIDITY'])
    add('revoked_memory',lambda s,p:s['selected_memory'][0]['native']['provenance'].update(consent_status='WITHDRAWN'),status='INVALID_INPUT',codes=['SOURCE_ACCESS_DENIED'])
    add('wrong_learner',lambda s,p:s['selected_memory'][0]['binding'].update(learner_id='other'),status='INVALID_INPUT',codes=['SOURCE_SCOPE_MISMATCH'])
    add('wrong_course',lambda s,p:s['selected_memory'][0]['binding'].update(course_id='other'),status='INVALID_INPUT',codes=['SOURCE_SCOPE_MISMATCH'])
    add('stale_version',lambda s,p:s['selected_memory'][0]['binding'].update(current_version='2'),status='INVALID_INPUT',codes=['SOURCE_VERSION_STALE'])
    add('future_observation',lambda s,p:s['selected_memory'][0]['native']['timestamp_version'].update(last_confirmed_at='2026-09-10T00:00:00+02:00'),status='INVALID_INPUT',codes=['SOURCE_FROM_FUTURE'])
    add('superseded_selected',lambda s,p:s['selected_memory'][0]['binding'].update(superseded_by='mem-replacement'),status='INVALID_INPUT',codes=['SOURCE_VERSION_STALE'])
    add('completed_repeat_rejected',lambda s,p:p['actions'][0].update(task_id='task-read'),status='BOUNDED_REPAIR_EXHAUSTED',codes=['COMPLETED_TASK_REPEATED'])
    def review(s,p):
        s['base_input']['hard_constraints']['continue_active_plan']=False
        s['selected_memory'].append(memory('mem-review',fields(review_permissions=[dict(task_id='task-read',rationale='I explicitly permit reviewing task-read.')])))
        p['actions'][0].update(task_id='task-read',kind='REVIEW')
    add('allowed_review',review)
    add('unpermitted_review',lambda s,p:(s['base_input']['hard_constraints'].update(continue_active_plan=False),p['actions'][0].update(task_id='task-read',kind='REVIEW')),status='BOUNDED_REPAIR_EXHAUSTED',codes=['REVIEW_NOT_AUTHORIZED'])
    add('ambiguous_plans',lambda s,p:s['selected_memory'].append(memory('mem-plan-b',fields(active_plan=dict(plan_id='other-plan',goal_id='goal-practice',remaining_task_ids=['other-task'],completed_task_ids=[])),origin='SYSTEM_ORIGIN_PLAN')),status='NEEDS_INFORMATION',codes=['AMBIGUOUS_ACTIVE_PLAN'])
    add('no_matching_memory',lambda s,p:(s.update(selected_memory=[],memory_status='NO_MATCH')),status='NEEDS_INFORMATION',codes=['GOAL_INFORMATION_MISSING'])
    add('partial_missing_goal',lambda s,p:s['selected_memory'].pop(0),status='NEEDS_INFORMATION',codes=['GOAL_INFORMATION_MISSING'])
    add('free_text_constraint_not_parsed',lambda s,p:s['selected_memory'].__setitem__(1,memory('mem-free','I have twenty minutes after work on weekdays.')),status='NEEDS_INFORMATION',codes=['UNSTRUCTURED_MEMORY'])
    add('model_inference_not_learner_goal',lambda s,p:s['selected_memory'].__setitem__(0,memory('mem-goal',fields(goal=dict(goal_id='goal-practice',text='An inferred learner goal.')),origin='MODEL_INFERENCE')),status='NEEDS_INFORMATION',codes=['ORIGIN_NOT_AUTHORITATIVE_FOR_STATE'])
    add('unknown_origin',lambda s,p:s['selected_memory'].__setitem__(0,memory('mem-goal',fields(goal=dict(goal_id='goal-practice',text='Unknown-origin goal.')),origin='UNKNOWN')),status='NEEDS_INFORMATION',codes=['MEMORY_ORIGIN_UNKNOWN'])
    add('system_advice_not_learner_goal',lambda s,p:s['selected_memory'].__setitem__(0,memory('mem-goal',fields(goal=dict(goal_id='goal-practice',text='Suggested system goal.')),origin='SYSTEM_ORIGIN_PLAN')),status='INVALID_INPUT',codes=['SYSTEM_ADVICE_NOT_LEARNER_FACT'])
    add('same_candidate_tighter_budget',lambda s,p:change_fields(s['selected_memory'][1],constraints=dict(budget=dict(required=True,minutes=10))),status='BOUNDED_REPAIR_EXHAUSTED',codes=['BUDGET_EXCEEDED'])
    add('unsupported_plus_40_claim',lambda s,p:p['actions'][0].update(action="This worksheet is guaranteed to raise the learner's final grade by 40 percent."))
    def invalid(p):q=deepcopy(p);q['actions'][0]['resource_ids']=['absent-resource'];return q
    def invalid_budget(p):q=deepcopy(p);q['actions'][0]['estimated_duration']['value']=80;return q
    add('zero_repair_exhausted',status='BOUNDED_REPAIR_EXHAUSTED',codes=['RESOURCE_NOT_PERMITTED'],sequence=lambda p:[invalid(p)])
    add('one_repair_success',repairs=1,sequence=lambda p:[invalid(p),p,invalid_budget(p)])
    add('two_repairs_success',repairs=2,sequence=lambda p:[invalid(p),invalid_budget(p),p])
    add('first_pass_stops',repairs=2,sequence=lambda p:[p,invalid(p),invalid_budget(p)])
    add('two_repairs_exhausted',repairs=2,status='BOUNDED_REPAIR_EXHAUSTED',codes=['BUDGET_EXCEEDED'],sequence=lambda p:[invalid(p),invalid(p),invalid_budget(p)])
    add('syntax_then_repair',repairs=1,sequence=lambda p:['{not valid json',p])
    add('schema_failure_retained',status='BOUNDED_REPAIR_EXHAUSTED',codes=['REQUIRED_FIELD'],sequence=lambda p:[{}])
    def source_estimate(s,p):
        s['selected_memory'].append(memory('mem-estimate',fields(duration_estimates=[dict(task_id='task-practice',value=20,uncertainty='Learner estimate, no measured range.')])) )
        p['actions'][0]['estimated_duration'].update(origin='LEARNER_ESTIMATE',evidence_refs=['mem-estimate'],uncertainty='Learner estimate, no measured range.')
    add('traceable_learner_duration',source_estimate)
    add('false_source_duration',lambda s,p:p['actions'][0]['estimated_duration'].update(origin='SOURCE_ESTIMATE',evidence_refs=['mem-goal']),status='BOUNDED_REPAIR_EXHAUSTED',codes=['ESTIMATE_SOURCE_VALUE_UNVERIFIED'])
    return runtime,mocks,expected


if __name__=='__main__':
    for name,rows in zip(('bridge_runtime.json','mock_sequences.json','expected_outcomes_sidecar.json'),make_cases()):
        (ROOT/'fixtures'/name).write_text(json.dumps(dict(labels=LABELS,cases=rows),indent=2)+'\n')
    print('Wrote 37 synthetic source/mock/sidecar cases separately.')
