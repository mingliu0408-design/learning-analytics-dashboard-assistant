"""Resume the completed artificial pipeline and require zero new mock sends."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,load,sha,write_once
from utils.c4_rebuild.i1.durable import DurableRunner
from utils.c4_rebuild.i1.orchestrator import Orchestrator
from utils.c4_rebuild.i1.worker import OfflineWorker
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from research_followups.rq3_rebuild.i1_pilot_launch.mock_transport import MockTransport,MockClock


def main(directory='mock_final_02', receipt_name='FULL_RESUME_CHECK.json'):
    config=load(HOME/'PILOT_CONFIGURATION_PROPOSED.json');manifest=load(HOME/'TASK_MANIFEST.json')
    binding=dict(config_sha256=sha(config),manifest_sha256=sha(manifest),source_manifest_sha256='MOCK_BUILD_BEFORE_FINAL_SOURCE_LOCK')
    t=MockTransport();clock=MockClock()
    runner=DurableRunner(HOME/'receipts'/directory,config,binding,t,resume=True,clock=clock,sleep=clock.sleep)
    try:result=Orchestrator(runner,FrozenP3(),OfflineWorker()).run(manifest)
    finally:runner.close()
    assert len(result)==72 and not t.requests
    write_once(HOME/'receipts'/receipt_name,dict(status='PASS',restored_final_slots=72,
        new_transport_attempts=0,source_rebuilt_and_checked=True,provider_calls=0))
    print('PASS: restored 72 artificial terminals with zero new sends')


if __name__=='__main__':main()
