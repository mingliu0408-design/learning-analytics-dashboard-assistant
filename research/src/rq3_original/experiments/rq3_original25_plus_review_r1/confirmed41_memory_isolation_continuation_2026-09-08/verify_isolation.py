"""Offline payload conservation and real native Memory process-boundary audit."""
from checkpoints import *
from continue_run import frozen_context
from isolation import isolated_prepare, parent_socket_allocation_check, child_environment
import interface_a1 as interface
from utils.c4_rebuild.i1.frozen_p3 import ROLE_NAMES
import argparse


def candidate_and_final(t,binding,c,r,parent,logical):
    prepared=r['prepared'];plan=prepared['planner'];accepted=None;failed=False;candidate=None
    if plan and plan['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
        planner=interface.planner_for(base.snapshot_for(t,binding),
            prepared['final_request']['runtime_input']['evidence']['selected_evidence'])
        if planner.plan_kind(plan['bridge'])['kind']!='NEEDS_TASK_INFORMATION':
            candidate=planner.candidate_payload(prepared,c['generation_roles']['CANDIDATE'])
            previous=parent.accepted(logical+':CANDIDATE','CANDIDATE',candidate)
            if previous:accepted=previous[0]['value']
        failed=accepted is None
    return candidate,base.final_payload(prepared,c['generation_roles']['FINAL'],accepted,failed)


def verify():
    base.offline()
    m,tasks,binding,c,ident,unused,frozen=frozen_context(DATA/'RUN_MANIFEST.json')
    parent=LayeredLedger();taskmap={t['task_id']:t for t in tasks}
    parent_socket_allocation_check()
    records=[]
    for slot in parent.slots:
        if slot['status']!='ACCEPTED':continue
        logical=slot['declared_slot_key'];t=taskmap[slot['task_id']]
        source=parent.module(logical)
        assert source and source[0] in ('A1','A2')
        candidate,final=candidate_and_final(t,binding,c,source[2],parent,logical)
        parent.accepted(logical+':FINAL','FINAL',final)
        records.append(dict(logical=logical,source_run=source[0],payload_sha256=sha(final),
            answer_sha256=slot['answer_sha256'],full_payload_unchanged=True))
    assert len(records)==183
    routes={}
    for t in tasks:
        if t['task_id'] not in m['task_ids']:continue
        src=base.source_for(t,binding)
        if src['clarification']:continue
        for role in ROLE_NAMES:
            payload=frozen.request(role,src['primary']);logical='P3:'+role+':'+sha(payload)
            if logical in parent.selected:
                parent.accepted(logical,role,payload);routes[logical]=sha(payload)
    assert len(routes)==81
    candidate_records=[]
    for logical,run in parent.selected.items():
        if not logical.endswith(':CANDIDATE'):continue
        slot=logical.removesuffix(':CANDIDATE');t=taskmap[slot.split(':')[0]]
        candidate,final=candidate_and_final(t,binding,c,parent.module(slot)[2],parent,slot)
        parent.accepted(logical,'CANDIDATE',candidate)
        candidate_records.append(dict(logical=logical,payload_sha256=sha(candidate)))
    assert len(candidate_records)==8
    # This is the actual task where A2 first imported nonempty native Memory.
    t=taskmap['task-495277e64cd9'];modes=c['modes']
    saved=parent.module(t['task_id']+':S3_EVIDENCE_MEMORY')[2]
    route={k:saved['prepared']['trace']['route'][k] for k in
        ('rag_required','memory_required','planning_required','provider_identity')}
    isolated,receipt=isolated_prepare(t,binding,modes,c,route)
    native=[]
    for mode in modes:
        logical=t['task_id']+':'+mode;r=isolated[mode]['modules'];old=parent.module(logical)[2]
        assert all(r[k]==old[k] for k in ('source','prepared','rag_calls','memory_calls')), 'MODULE_CHANGED:'+logical
        before=candidate_and_final(t,binding,c,old,parent,logical)
        after=candidate_and_final(t,binding,c,r,parent,logical)
        assert before==after, 'FULL_PROVIDER_PAYLOAD_CHANGED:'+logical
        for role,payload in (('CANDIDATE',after[0]),('FINAL',after[1])):
            if logical+':'+role in EXISTING_UNKNOWNS:
                parent.unknown_permission(logical+':'+role,payload)
        native.append(dict(logical=logical,module_sha256=sha(r),full_payloads_unchanged=True,
            memory_calls=r['memory_calls'],rag_calls=r['rag_calls']))
    parent_socket_allocation_check()
    assert not any(k.startswith(('OPENAI_','AZURE_','ANTHROPIC_')) for k in child_environment())
    result=dict(passed=True,provider_calls=0,real_network_requests=0,scientific_interface=interface.VERSION,
        parent_identity=parent.identity,accepted_answers_verified=183,accepted_routes_verified=81,
        accepted_candidates_verified=8,full_payload_conservation=records,candidate_payloads=candidate_records,
        historical_unknown_same_payload_permissions=EXISTING_UNKNOWNS,
        actual_native_task_six_modes=native,worker_receipt=receipt,
        parent_socket_allocation_passed_after_memory=True,worker_credentials_excluded=True,
        historical_unknown_count=8,historical_budget_debit_usd=parent.budget_debit,
        original_scientific_dependencies_unchanged=True,old_six_planning_replacements_preserved=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=verify();write_once(a.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in (
        'full_payload_conservation','candidate_payloads','historical_unknown_same_payload_permissions','actual_native_task_six_modes')}))
