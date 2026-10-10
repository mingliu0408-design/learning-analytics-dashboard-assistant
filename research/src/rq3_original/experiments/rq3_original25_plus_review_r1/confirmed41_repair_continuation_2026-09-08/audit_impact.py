"""Replay only saved A module inputs; no target retrieval, embedding or provider."""
from a1_common import *
base.offline()
from collections import Counter
from unittest.mock import patch
import interface_a1 as repair
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3,ROLE_NAMES


def differing(a,b,path='$'):
    if type(a)!=type(b):return [path]
    if isinstance(a,dict):
        return [p for k in sorted(a.keys()|b.keys()) for p in ([path+'.'+k] if k not in a or k not in b else differing(a[k],b[k],path+'.'+k))]
    if isinstance(a,list):
        if len(a)!=len(b):return [path]
        return [p for i,(x,y) in enumerate(zip(a,b)) for p in differing(x,y,path+f'[{i}]')]
    return [] if a==b else [path]


def main():
    m,tasks,binding,config=legacy.load_run(DATA/'RUN_MANIFEST.json')
    by_id={t['task_id']:t for t in tasks};pp=policy()
    stages={}
    for p in (PARENT_RUN/'stages').glob('*.json'):
        s=load(p);stages[(s['logical'],s['stage'])]=(p,s)
    results=[];six=[];route_rows=[];replayed={}
    starts={s['logical']:s for s in [load(p) for p in (PARENT_RUN/'attempts').glob('*.start.json')]}
    frozen=FrozenP3()
    with patch.object(base.R0OnExplicitCorpus,'__init__',side_effect=AssertionError('TARGET_RAG_FORBIDDEN')),patch.object(base.I1NativeM1,'__init__',side_effect=AssertionError('TARGET_MEMORY_FORBIDDEN')):
        for (logical,stage),(path,s) in sorted(stages.items()):
            if stage=='ACTUAL_P3':
                task=by_id[logical];src=base.source_for(task,binding)
                for role in ROLE_NAMES:
                    payload=frozen.request(role,src['primary']);key='P3:'+role+':'+sha(payload)
                    start=starts[key];assert payload==start['request']
                    old=load(PARENT_RUN/'attempts'/f"{start['attempt_id']}.outcome.json")
                    assert old['status']=='ACCEPTED' and sha((PARENT_RUN/'attempts'/f"{start['attempt_id']}.raw.json").read_bytes())==old['raw_sha256']
                    route_rows.append(dict(task_id=logical,role=role,logical=key,payload_sha256=sha(payload),parent_attempt_id=start['attempt_id']))
            if stage!='MODULES':continue
            tid,mode=logical.split(':',1);task=by_id[tid];old=s['output']
            before=repair.replay_saved(task,binding,mode,old,repaired=False)
            assert before==old,('OLD_REPLAY_DIFF',logical,differing(before,old))
            after=repair.replay_saved(task,binding,mode,old)
            original_start=starts[logical+':FINAL']
            old_payload=base.final_payload(before['prepared'],config['generation_roles']['FINAL'])
            new_payload=base.final_payload(after['prepared'],config['generation_roles']['FINAL'])
            assert old_payload==original_start['request']
            outcome=load(PARENT_RUN/'attempts'/f"{original_start['attempt_id']}.outcome.json")
            changed=old_payload!=new_payload
            if outcome['status']=='ACCEPTED' and changed and logical not in pp['replacement_slots']:
                raise RuntimeError('IMPACT_EXCEEDS_SIX_STOP:'+logical)
            if outcome['status']=='UNKNOWN_COMPLETION':
                assert not changed and original_start['request_sha256']==pp['parent_unknown_authorizations'][0]['request_sha256']
            row=dict(logical=logical,parent_status=outcome['status'],changed=changed,
                decision='REPLACEMENT_ELIGIBLE_INPUT_CHANGED' if changed else 'REUSE_ACCEPTED_PAYLOAD_EQUAL' if outcome['status']=='ACCEPTED' else 'ONE_AUTHORIZED_SAME_PAYLOAD_UNKNOWN_RESEND',
                parent_payload_sha256=sha(old_payload),new_precandidate_payload_sha256=sha(new_payload),
                old_module_sha256=sha(old),new_module_sha256=sha(after),module_file=file_entry(path,PARENT_RUN),
                changed_module_paths=differing(before,after),provider_payload_differing_fields=differing(old_payload,new_payload))
            results.append(row);replayed[logical]=after
            if logical in pp['replacement_slots']:
                p0=before['prepared']['planner'];p1=after['prepared']['planner']
                assert p0['status']=='NEEDS_INFORMATION'
                assert p1['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT'
                six.append(dict(logical=logical,before_status=p0['status'],after_status=p1['status'],
                    before_validation=p0['validation'],after_validation=p1['validation'],
                    original_validator_reproduced=True,old_source_input=p0['bridge']['source_input'],
                    new_source_input=p1['bridge']['source_input']))
    decisions=Counter(r['decision'] for r in results)
    assert decisions=={'REUSE_ACCEPTED_PAYLOAD_EQUAL':168,'REPLACEMENT_ELIGIBLE_INPUT_CHANGED':6,'ONE_AUTHORIZED_SAME_PAYLOAD_UNKNOWN_RESEND':1}
    assert len({r['parent_attempt_id'] for r in route_rows})==81 and len(route_rows)==90
    save(HERE/'audit/IMPACT_AUDIT.json',dict(passed=True,decisions=dict(decisions),records=results,
        generation_calls=0,target_retrieval_calls=0,target_embedding_calls=0,old_module_replay_exact=175,
        scope='Saved source/compiler/native module inputs only; no answer quality selection.'))
    save(HERE/'audit/SIX_PLANNER_REPLAY.json',six)
    save(HERE/'audit/P3_REUSE_AUDIT.json',dict(passed=True,logical_uses=90,unique_parent_attempts=81,records=route_rows))
    save(HERE/'audit/REPLAYED_INPUTS.json',replayed)
    print(json.dumps({'passed':True,'old_inputs_replayed':175,'six_repaired':len(six),'decisions':dict(decisions),'unique_routes_reusable':81}))


if __name__=='__main__':main()
