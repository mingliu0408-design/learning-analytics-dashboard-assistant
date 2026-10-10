"""Exposed fixture replays and saved-native projection, without retrieval or model calls."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json,tempfile
from p1bridge.contracts import ROOT,canonical,schemas,schema_errors,OUTPUT
from p1bridge.projection import project,from_native_selected,classify_exact_request
from p1bridge.checker import validate_bridge
from p1bridge.mock import run_mock,ScriptedMock
from p1bridge.requests import candidate_request,direct_request,final_generator_request,deterministic_field_copy,PENDING_CONFIGURATION
from p0planner.offline_guard import install
from p0planner.controller import run_planner as p0_run
from p0planner.providers import MockProvider
from tools.build_fixtures import baseline


def main():
    install();started=datetime.now(timezone.utc).isoformat()
    out=Path(tempfile.mkdtemp(prefix='diagnostics_',dir=ROOT/'reports'))
    def write(name,value): (out/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    rows=json.loads((ROOT/'fixtures/bridge_runtime.json').read_text())['cases']
    mocks={r['case_id']:r for r in json.loads((ROOT/'fixtures/mock_sequences.json').read_text())['cases']}
    expected={r['case_id']:r for r in json.loads((ROOT/'fixtures/expected_outcomes_sidecar.json').read_text())['cases']}
    runs=[];parity=[];handoff=None
    for row in rows:
        m=mocks[row['case_id']];s=row['runtime_input'];mock=ScriptedMock(m['candidates'])
        result=run_mock(s,mock,max_repairs=m['max_repairs']);e=expected[row['case_id']]
        ok=result['status']==e['expected_status'] and set(e['required_issue_codes'])<={x['code'] for x in result['validation']['issues']}
        assert ok,(row['case_id'],result)
        assert not schema_errors(result,OUTPUT)
        b=project(s)
        runs.append(dict(case_id=row['case_id'],labels=row['labels'],bridge=b,result=result,sidecar_assertion_passed=ok))
        if validate_bridge(b)['outcome']=='PASSED_ENCODED_CHECKS':
            c=candidate_request(b);d=direct_request(b);assert c.payload['runtime_input']==d.payload['runtime_input']
            parity.append(dict(case_id=row['case_id'],runtime_sha256=sha256(canonical(c.payload['runtime_input']).encode()).hexdigest(),equal_runtime=True,
                candidate_request_sha256=c.sha256,direct_request_sha256=d.sha256))
        if row['case_id']=='ordinary_open_plan_updated_completion':
            handoff=dict(candidate_request=c.payload,direct_request=d.payload,
                final_generator_request=final_generator_request(b,result['plan']).payload,
                deterministic_field_copy=deterministic_field_copy(b,result['plan']),
                scope='No generated final answer or LLM paraphrase verification; direct generator may plan naturally.')
    (out/'MOCK_TRACE.jsonl').write_text(''.join(canonical(r)+'\n' for r in runs))
    write('DIRECT_PARITY_RESULTS.json',parity);write('REQUEST_AND_HANDOFF_EXAMPLE.json',handoff)
    old,plan=baseline();changed=deepcopy(old);changed['facts'][0]['source_ref']['valid_to']=None
    original_result=p0_run(old,MockProvider([plan]));null_result=p0_run(changed,MockProvider([plan]))
    assert original_result['status']=='PASSED_ENCODED_CHECKS' and null_result['status']=='NEEDS_INFORMATION'
    write('P0_NULL_VALIDITY_REPRODUCTION.json',dict(original_input=old,one_field_changed_input=changed,
        changed_path='$.facts[0].source_ref.valid_to',same_candidate=plan,original_result=original_result,null_result=null_result,
        boundary='Synthetic interface diagnostic only; not a live M0-to-P0 failure.'))
    # Read actual completed M0 outputs, never expected IDs or setup source facts.
    native=[]
    for row in json.loads((ROOT/'inherited_m0/selected_envelopes_exposed.json').read_text()):
        current,_=baseline();target=row['target']
        current['scope']=dict(learner_id=target['learner_id'],course_id=target['course_id'],session_id=target['session_id'],as_of=target['as_of'],timezone=None,horizon=None)
        current['context']=dict(query=target['query'],page=target['page'],visible_conversation=[canonical(t) for t in target['visible_history']])
        current.update(goals=[],facts=[],resources=[],source_versions=[],completed_tasks=[],review_permissions=[],active_plan=None,soft_preferences=[])
        current['hard_constraints']=dict(budget=dict(required=False,minutes=None),schedule=dict(required=False,allowed_windows=None,excluded_windows=[],forbidden_weekdays=[],non_overlap=True),
            forbid_completed_repeat=True,continue_active_plan=False,required_evidence_ids=[],task_prerequisites=[])
        s=from_native_selected(row['envelope'],current,classify_exact_request(target['query']),future_use_policy='RECONFIRM_FOR_SCHEDULE')
        b=project(s);result=validate_bridge(b)
        native.append(dict(case_id=row['case_id'],selected_ids=[m['native']['memory_id'] for m in s['selected_memory']],
            bridge=b,validation=result,source='Saved completed M0 envelope only; metadata not inferred; no retrieval or linkage added.'))
    write('M0_SAVED_NATIVE_PROJECTIONS.json',native)
    counts={status:sum(r['result']['status']==status for r in runs) for status in sorted({r['result']['status'] for r in runs})}
    summary=dict(started_at_utc=started,completed_at_utc=datetime.now(timezone.utc).isoformat(),cases=len(runs),all_sidecar_assertions_passed=True,
        status_counts=counts,eligible_request_parity_cases=len(parity),native_saved_envelopes=len(native),
        mock_candidate_calls=sum(r['result']['provider_calls']['candidate'] for r in runs),mock_repair_calls=sum(r['result']['provider_calls']['repair'] for r in runs),
        final_generation_calls=0,real_calls=0,judge_calls=0,
        call_count_scope='37 P1 case replays only; unit-test mocks and P0 reproduction/replays separate. P0 null reproduction adds one mock candidate and zero repairs.',
        no_retrieval_rerun=True,no_gold_or_model_scores=True,unsupported_plus_40_claim='PASSED_ENCODED_CHECKS with SEMANTIC_SUPPORT_NOT_CHECKED',
        native_projection='All retained as incomplete; no missing goal/completion/constraint reconstructed.',
        deployment_suitability='NOT_ESTABLISHED',configuration=PENDING_CONFIGURATION)
    write('DIAGNOSTIC_SUMMARY.json',summary)
    print(json.dumps(summary,indent=2));print('REPORT_DIRECTORY',out)
if __name__=='__main__':main()
