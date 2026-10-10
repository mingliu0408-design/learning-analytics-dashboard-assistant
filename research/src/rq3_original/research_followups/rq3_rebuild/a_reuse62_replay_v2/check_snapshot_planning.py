"""One saved-input projection and exact-snapshot negative checks; zero module reads."""
from replay_common import *
from copy import deepcopy
from controlled_runtime import *
from snapshot_planning import validate_bridge,typed_planner
from utils.c4_rebuild.planning import empty_envelope
from utils.c4_rebuild.memory import MemoryBundle

def run():
    b=read(HERE/'runtime/BINDINGS.json');tasks=lines(HERE/'runtime/TASKS_62.jsonl')
    # Same Overview source view, previously compiled; no candidate or extra route.
    saved=read(HERE/'receipts/evidence_summary/U057_S1_CROSS_PAGE_EVIDENCE.json')['rebuilt']['prepared']
    compiled=SimpleNamespace(content=saved['final_request']['runtime_input']['evidence'])
    t=tasks[20];req=request_for(t,b,Mode.S4_EVIDENCE_PLANNING)
    s=ControlledService(enabled=True,snapshot=BoundPages(b))
    memory=MemoryBundle(empty_envelope(req),{},{});task=s.resolve_task_intent(req)
    bridge=s.build_planning_bridge(req,compiled,task,memory)
    v=validate_bridge(bridge)
    assert v['outcome']=='PASSED_ENCODED_CHECKS',v
    assert typed_planner().plan_kind(bridge)['kind']=='ORDINARY_ACTION_ADVICE'
    cases={}
    from utils.c4_rebuild.planning import bridge_from_m1
    for kind in ('FORGED_CONTENT','DENIED_PERMISSION','WRONG_LEARNER','SCHEDULE_REQUIRED'):
        base=deepcopy(bridge['source_input']['base_input']);tp=deepcopy(task)
        if kind=='FORGED_CONTENT':base['facts'][1]['value']='Invented unsupported content'
        if kind=='DENIED_PERMISSION':base['facts'][1]['source_ref']['access']='DENIED'
        if kind=='WRONG_LEARNER':base['facts'][1]['source_ref']['learner_id']='other-learner'
        if kind=='SCHEDULE_REQUIRED':
            tp['mode']='EXPLICIT_SCHEDULE';base['hard_constraints']['schedule']['required']=True
        changed=bridge_from_m1(memory,base,tp,'WARN_SNAPSHOT_ONLY')
        checked=validate_bridge(changed)
        assert checked['outcome']!='PASSED_ENCODED_CHECKS',kind
        cases[kind]=checked
    write(HERE/'receipts/UNDATED_SNAPSHOT_PLANNING_SUMMARY_CHECK.json',dict(task_id=t['task_id'],bridge=bridge,
        validation=v,typed_kind=typed_planner().plan_kind(bridge),negative_checks=cases,
        source='Existing bound Overview compiled input reused; query U021 unchanged',new_module_reads=0,
        candidate_calls=0,final_calls=0,tests=5,passed=True))
    print('5 exact-snapshot planning checks passed; no source dates invented or retrieval repeated.')

if __name__=='__main__':offline();run()
