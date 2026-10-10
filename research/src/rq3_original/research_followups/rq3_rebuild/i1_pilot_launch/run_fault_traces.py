"""Saved mock traces for route/final structural retry and finite candidate repair."""
from pathlib import Path
import copy
import json
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, sha, write_once
from utils.c4_rebuild.i1.durable import DurableRunner
from utils.c4_rebuild.i1.orchestrator import Orchestrator
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from utils.c4_rebuild.i1.worker import OfflineWorker
from research_followups.rq3_rebuild.i1_pilot_launch.mock_transport import MockTransport,MockClock


def run(output, always_bad=False):
    config=load(HOME/'PILOT_CONFIGURATION_PROPOSED.json');full=load(HOME/'TASK_MANIFEST.json')
    manifest=dict(full,task_ids=['I0-SYN-06'],modes=['S5_FULL'])
    seen={}
    def faults(payload,raw,n):
        name=payload['response_format']['json_schema']['name']
        seen[name]=seen.get(name,0)+1
        if name=='i1_candidate_v1':
            if always_bad or seen[name]==1:
                v=json.loads(raw['choices'][0]['message']['content'])
                v['actions'][0]['estimated_duration']['value']=999
                raw['choices'][0]['message']['content']=json.dumps(v)
        elif not always_bad and seen[name]==1 and name in ('i1_final_v1','c4_real_p3_rag_specialist_v1'):
            raw['choices'][0]['message']['content']='{}'
        return raw
    transport=MockTransport(faults);clock=MockClock()
    runner=DurableRunner(output,config,{'mock_fault_case':always_bad},transport,clock=clock,sleep=clock.sleep)
    try:outcomes=Orchestrator(runner,FrozenP3(),OfflineWorker()).run(manifest)
    finally:runner.close()
    assert outcomes[0]['result']['status']=='ACCEPTED'
    assert outcomes[0]['planning_failed']==always_bad
    if always_bad:
        body=json.loads(transport.requests[-1]['messages'][-1]['content'])
        assert body['accepted_plan'] is None and any('could not be prepared' in s for s in body['information_needed'])
    result=dict(status='PASS',artificial_only=True,provider_calls=0,roles=seen,final=outcomes[0],
        candidate_failure_preserved=always_bad,final_not_claimed_successful_planning=always_bad)
    write_once(Path(output)/'FAULT_TRACE_RESULT.json',result)
    print({'path':str(output),'role_attempts':seen,'status':'PASS'})


if __name__=='__main__':
    run(HOME/'receipts/mock_repair_trace')
    run(HOME/'receipts/mock_candidate_failure_trace',True)
