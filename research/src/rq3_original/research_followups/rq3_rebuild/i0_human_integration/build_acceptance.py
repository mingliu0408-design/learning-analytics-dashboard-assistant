"""Prepare unscored synthetic tasks, common human shells, and actual envelope traces."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from fixtures import *
from utils.c4_dashboard_scoped.scope import digest
from utils.c4_rebuild.service import ResearchService, planner_base
from utils.c4_rebuild.planning import bridge_from_m1, validate_bridge, p1c, I0_INPUT
from utils.c4_rebuild.memory import MemoryBundle, clone_native_states
from utils.c4_rebuild.language import intent
from utils.c4_rebuild.generation import RESPONSE_SCHEMA, TELEMETRY_EVENTS, prepare_final_from_candidate
from test_integration import plan


def write(name, value):
    p=HERE/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


TASKS = [
    dict(id='I0-SYN-01',kind='CROSS_PAGE_WEEKLY_SUMMARY',query='Summarise my learning this week.',page='Lecture'),
    dict(id='I0-SYN-02',kind='LEGITIMATE_SINGLE_PAGE',query='Summarise resource views for this week.',page='Resources'),
    dict(id='I0-SYN-03',kind='OVERVIEW_NO_INCREMENT',query='Summarise my learning this week.',page='Overview'),
    dict(id='I0-SYN-04',kind='RAG_POSITIVE_INTERFACE',query='Suggest next steps using the week 1 lecture worksheet.',page='Lecture'),
    dict(id='I0-SYN-05',kind='RAG_GATE_OFF',query='Suggest next steps using the week 1 lecture worksheet.',page='Lecture',rag_bit=False),
    dict(id='I0-SYN-06',kind='SOURCE_DERIVED_NUMERIC_CONSTRAINT',query='Remind me of my goal and suggest next steps without dates.',page='Lecture',numeric=True),
    dict(id='I0-SYN-07',kind='COMPLETE_LINKED_MEMORY',query='Continue my plan and suggest next steps without dates.',page='Lecture',memory_index=12),
    dict(id='I0-SYN-08',kind='RAW_ADVICE_NO_DATES',query='Continue my plan and suggest useful next steps without dates.',page='Reflection',memory_index=32),
    dict(id='I0-SYN-09',kind='SCHEDULE_MISSING_TIMEZONE',query='Please schedule my tasks for the quadratic formula goal.',page='Lecture',explicit_purpose='GOAL_RECALL'),
    dict(id='I0-SYN-10',kind='AMBIGUOUS_NATIVE_PLAN',query='Continue my plan and suggest next steps without dates.',page='Lecture',memory_index=11),
    dict(id='I0-SYN-11',kind='MISSING_COURSE_EVIDENCE',query='Suggest next steps using the week 1 lecture worksheet.',page='Lecture',empty_course=True),
    dict(id='I0-SYN-12',kind='SUPERSEDED_COMPLETION',query='Continue my plan and suggest next steps without dates.',page='Lecture',memory_index=25),
]


def saved_envelopes():
    m1=HERE.parent/'m1_memory_completeness'
    path=m1/'PLANNER_ENVELOPE_SYNTHETIC_FIXTURES.json'
    saved=json.loads(path.read_text())
    runtime=json.loads((m1/'fixtures/linked_runtime_v1.json').read_text())
    indices={row['case_id']:i for i,row in enumerate(runtime)}
    reports=[]
    for row in saved['envelopes']:
        original=row['envelope'];source_case=runtime[indices[row['case_id']]]
        now=datetime.fromisoformat(original['scope']['as_of'])
        scoped=Scope(original['scope']['learner_id'],original['scope']['course_id'],
            'SYNTHETIC_SAVED_ENVELOPE_REPRODUCTION',(now-timedelta(days=1)).isoformat(),
            (now+timedelta(days=1)).isoformat(),'UTC')
        r=request(scope=scoped,as_of=now.isoformat(),query=source_case['target']['query'],
            page=source_case['target']['page'],session_id=original['scope']['session_id'])
        task=intent(r.query,explicit='ORDINARY_ACTION_ADVICE')
        base=planner_base(r,SimpleNamespace(content={'selected_evidence':[]}),task)
        unknown=bridge_from_m1(MemoryBundle(original,{},{}),base,task,r.future_policy)
        with tempfile.TemporaryDirectory(prefix='saved-m1-',dir=HERE/'.runtime') as td:
            adapter,setup=memory_source(indices[row['case_id']],td,target_as_of=original['scope']['as_of'])
            authority=adapter.authority_for(original)
            bound=bridge_from_m1(MemoryBundle(original,authority,{}),base,task,r.future_policy)
            native_matches=all(a.get('native_record') is not None for a in authority.values())
        report=dict(source_case_id=row['case_id'],condition=row['condition'],
            original_envelope_sha256=digest(original),source_file_sha256=sha256(path.read_bytes()).hexdigest(),
            actual_saved_envelope=original,without_runtime_authority=dict(bridge=unknown,validation=validate_bridge(unknown)),
            with_reproduced_synthetic_native_authority=dict(bridge=bound,validation=validate_bridge(bound)),
            all_saved_native_ids_present_in_reopened_source=native_matches,
            authority_boundary='New exact-source synthetic replay and read-only lookup; not original captured current-authority telemetry.',
            expected_sidecars_read=False,raw_text_unchanged=all(
                m['native']['content']==f['content'] for m,f in zip(bound['source_input']['selected_memory'],original['facts'])))
        reports.append(report)
    write('ACTUAL_M1_SAVED_ENVELOPE_PROJECTIONS.json',dict(flags=FLAGS,records=reports))
    return reports


def main():
    (HERE/'.runtime').mkdir(exist_ok=True)
    write('PILOT_TASKS.json',dict(flags=FLAGS,status='UNSCORED_PROPOSED_DEVELOPMENT_TASKS',tasks=TASKS,
        source_backed_real_tasks=[],real_task_reason='No new real-source permission/binding; no fake real tasks substituted.'))
    manifests=[];traces=[];shells=[];source_receipts=[];mock_handoffs=[]
    for task in TASKS:
        with tempfile.TemporaryDirectory(prefix='pilot-state-',dir=HERE/'.runtime') as td:
            adapter,setup=memory_source(task.get('memory_index',0),td,
                change=explicit_minutes_source if task.get('numeric') else None)
            source_receipts.append(dict(task_id=task['id'],setup_receipts=setup['setup_receipts'],
                source_runtime=setup['source_case'],relation_rejections=setup['relation_rejections']))
            learner=setup['source_case']['target']['learner_id'];course=setup['source_case']['target']['course_id']
            scoped_snapshot=snapshot(learner_id=learner,course_id=course)
            common={};rows=[]
            for mode in Mode:
                clones=clone_native_states(adapter.databases,Path(td)/mode.value)
                memory=NativeM1(clones,adapter.graph,adapter.source_events)
                r=request(mode,query=task['query'],page=task['page'])
                r=replace(r,scope=replace(r.scope,learner_id=learner,course_id=course),
                    memory_state_version=digest(setup['setup_receipts']))
                if task.get('explicit_purpose'):
                    r=replace(r,memory_purpose=task['explicit_purpose'],visible_controls='EXPLICIT_SYNTHETIC_UI_PURPOSE')
                service=ResearchService(enabled=True,snapshot=scoped_snapshot,
                    router=SyntheticRouter(task.get('rag_bit',True),True,True),
                    retriever=rag_source(task.get('empty_course',False),course_id=course),memory=memory)
                output=service.prepare(r)
                name=f"pilot_requests/{task['id']}_{mode.value}.json"
                write(name,output)
                candidate=bool(output['planner'] and output['planner']['request'])
                manifests.append(dict(task_id=task['id'],mode=mode.value,path=name,
                    sha256=sha256((HERE/name).read_bytes()).hexdigest(),final_response_present=False,
                    candidate_request_prepared=candidate,final_request_prepared=True,
                    clarification_required=output['final_request']['clarification_required']))
                traces.append(dict(task_id=task['id'],**output['trace']))
                rows.append(output)
                for item in output['final_request']['runtime_input']['evidence']['selected_evidence']:
                    common[digest(item)]=deepcopy(item)
                if task['id']=='I0-SYN-06' and candidate:
                    c=plan(output['planner']['bridge'])
                    final=prepare_final_from_candidate(output,c)
                    mock_handoffs.append(dict(task_id=task['id'],mode=mode.value,
                        source='SYNTHETIC_SUPPLIED_PLAN_NO_GENERATION',final_request=final,
                        final_answer=None,semantic_support='NOT_CHECKED'))
            if task['id']=='I0-SYN-01':
                assert len(rows[1]['trace']['e1_fact_trace'])>len(rows[0]['trace']['e1_fact_trace'])
            # One response-free common evidence shell per task, no condition-specific rating aid.
            shells.append(dict(task_id=task['id'],source_origin='SYNTHETIC_EXPOSED_DEVELOPMENT',
                current_query=task['query'],current_page=task['page'],visible_history=list(r.history),
                common_evidence=list(common.values()),applicability=None,responses=[],ratings=[],rater_identity=None,
                readiness='REFERENCE_SHELL_ONLY_H0_BINDING_AND_HUMAN_REVIEW_PENDING'))
    saved=saved_envelopes()
    write('PILOT_REQUEST_MANIFEST.json',dict(flags=FLAGS,requests=manifests,
        counts=dict(tasks=len(TASKS),final_request_blueprints=len(manifests),
                    candidate_request_blueprints=sum(x['candidate_request_prepared'] for x in manifests)),
        prospective_provider_calls=dict(final_upper_bound=len(manifests),candidate_upper_bound=2*len(TASKS),
            repair_upper_bound='24 * author_approved_repair_limit',
            route_decisions_without_reuse=4*len(TASKS),
            frozen_p3_roles=['RAG_SPECIALIST','MEMORY_SPECIALIST','B4_PLANNING'],
            route_provider_calls_with_one_frozen_route_per_scoped_task=3*len(TASKS),
            route_provider_calls_without_reuse=12*len(TASKS),
            route_invalid_output_repair_calls='SEPARATE_PENDING_BUDGET',
            executed_generation_or_rating_calls=0),
        no_sample_size_or_model_budget_approval=True))
    write('FACT_TO_FINAL_REQUEST_TRACE.json',dict(flags=FLAGS,traces=traces))
    write('COMMON_HUMAN_EVIDENCE_SHELLS.json',dict(flags=FLAGS,shells=shells,ratings_prefilled=False))
    write('SYNTHETIC_INPUT_SOURCE_RECEIPTS.json',dict(flags=FLAGS,task_sources=source_receipts))
    write('SYNTHETIC_PLAN_TO_FINAL_REQUEST.json',dict(flags=FLAGS,handoffs=mock_handoffs))
    write('schemas/I0_P1_INPUT_SCHEMA.json',I0_INPUT)
    write('schemas/STRUCTURED_PLAN_SCHEMA.json',p1c.CANDIDATE)
    write('schemas/FINAL_RESPONSE_SCHEMA.json',RESPONSE_SCHEMA)
    write('HUMAN_ONLY_EVALUATION_BOUNDARY.json',dict(version='I0_HUMAN_ONLY_V1',
        response_quality_evaluator='HUMAN_ONLY',llm_judge_created=False,llm_judge_calls=0,
        generation_calls=0,human_ratings_created=0,rating_rationales_created=0,
        supervisor_rubric_binding='H0_SEPARATE_TASK_NOT_IMPORTED_WHILE_ACTIVE',
        mechanical_checks='ENGINEERING_DIAGNOSTICS_NOT_RESPONSE_QUALITY',
        final_design_and_sample_size='PENDING_AUTHOR_DECISIONS',
        old_thesis_or_results_modified=False,transport_implementation='DISABLED',
        telemetry_events=TELEMETRY_EVENTS))
    print(json.dumps(dict(tasks=len(TASKS),final_request_blueprints=len(manifests),
        candidate_request_blueprints=sum(x['candidate_request_prepared'] for x in manifests),
        saved_m1_envelopes=len(saved),synthetic_mock_plan_handoffs=len(mock_handoffs),responses_generated=0)))


if __name__=='__main__':main()
