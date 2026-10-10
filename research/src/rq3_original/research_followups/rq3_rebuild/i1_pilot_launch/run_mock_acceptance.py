"""Full finite pipeline with mock role transport and actual lexical native states."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, sha, write_once, canonical
from utils.c4_rebuild.i1.durable import DurableRunner
from utils.c4_rebuild.i1.orchestrator import Orchestrator
from utils.c4_rebuild.i1.worker import OfflineWorker
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from utils.c4_rebuild.i1.human import dossier, project
from research_followups.rq3_rebuild.i1_pilot_launch.mock_transport import MockTransport, MockClock


def main(output):
    output=Path(output)
    config=load(HOME/'PILOT_CONFIGURATION_PROPOSED.json')
    manifest=load(HOME/'TASK_MANIFEST.json')
    transport=MockTransport();clock=MockClock()
    binding=dict(config_sha256=sha(config),manifest_sha256=sha(manifest),source_manifest_sha256='MOCK_BUILD_BEFORE_FINAL_SOURCE_LOCK')
    runner=DurableRunner(output,config,binding,transport,clock=clock,sleep=clock.sleep)
    try:
        freezes=Orchestrator(runner,FrozenP3(),OfflineWorker()).run(manifest)
    finally:
        runner.close()
    registry=[dict(index=i,request_sha256=sha(x),payload=x,utf8_payload_bytes=len(canonical(x))) for i,x in enumerate(transport.requests)]
    write_once(output/'MOCK_REQUEST_REGISTRY.json',dict(origin='ARTIFICIAL_TRANSPORT_ONLY',requests=registry))
    write_once(output/'MOCK_RESPONSE_FREEZES.json',dict(origin='ARTIFICIAL_NOT_FOR_RATING',responses=freezes))
    all_packets=[];all_mappings=[]
    for entry in manifest['sources']:
        common=dossier(entry['source'],dict(source_review_approved=False,reference=None,source_ids=[],version='PENDING_SOURCE_REVIEW'))
        packet,mapping=project(common,manifest['modes'])
        all_packets.append(packet);all_mappings.extend(mapping)
    write_once(output/'NO_RESPONSE_HUMAN_PROJECTIONS.json',dict(packets=all_packets,real_response_count=0,ratings=[]))
    write_once(output/'RESTRICTED_TEST_MAPPING.json',all_mappings)
    sample=[x for x in freezes if x['task_id']==manifest['task_ids'][0]]
    common=dossier(manifest['sources'][0]['source'],dict(source_review_approved=False,
        reference={'test_only_sentinel':'EVALUATOR_ONLY_SENTINEL'},source_ids=[],version='ARTIFICIAL_TEST'))
    packet,mapping=project(common,manifest['modes'],sample,artificial=True)
    write_once(output/'ARTIFICIAL_PACKET_TEST.json',packet)
    assert 'EVALUATOR_ONLY_SENTINEL' not in canonical(registry).decode()
    result=dict(status='PASS' if all(x['result']['status']=='ACCEPTED' for x in freezes) else 'FAIL',
        final_slots=len(freezes),accepted_mock_finals=sum(x['result']['status']=='ACCEPTED' for x in freezes),
        physical_mock_attempts=len(transport.requests),provider_calls=0,real_generated_responses=0,
        human_ratings=0,judge_calls=0,route_mock_attempts=sum('required' in next(iter(p['response_format']['json_schema']['schema']['properties'])) for p in transport.requests),
        candidate_mock_attempts=sum('plan_id' in p['response_format']['json_schema']['schema']['properties'] for p in transport.requests),
        source_tasks=12,unique_four_field_inputs=8,blank_human_projected_slots=72,
        memory_backend='ACTUAL_RECREATED_SYNTHETIC_LEXICAL_NATIVE_STATES',native_hybrid_forward_calls=0)
    write_once(output/'MOCK_ACCEPTANCE_RESULT.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main(sys.argv[1])
