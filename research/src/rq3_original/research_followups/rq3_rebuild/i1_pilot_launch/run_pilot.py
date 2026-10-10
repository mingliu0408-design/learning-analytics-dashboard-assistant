"""Default prepare-only; live mode requires the external I1 approval contract."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, sha, canonical, write_once, load
from utils.c4_rebuild.i1.policy import preflight
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from utils.c4_rebuild.i1.worker import OfflineWorker
from utils.c4_rebuild.i1.durable import DurableRunner
from utils.c4_rebuild.i1.orchestrator import Orchestrator


def main(argv=None, transport_factory=None):
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only',action='store_true')
    mode.add_argument('--execute',action='store_true')
    p.add_argument('--config',type=Path,default=HOME/'PILOT_CONFIGURATION_PROPOSED.json')
    p.add_argument('--manifest',type=Path,default=HOME/'TASK_MANIFEST.json')
    p.add_argument('--source-manifest',type=Path,default=HOME/'SOURCE_MANIFEST.json')
    p.add_argument('--approval',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--resume',action='store_true')
    a=p.parse_args(argv)
    config,manifest,binding,approval=preflight(a.config,a.manifest,a.source_manifest,
        execute=a.execute,approval_path=a.approval,output=a.output)
    frozen=FrozenP3()
    if frozen.identity!=config['frozen_p3_identity']:
        raise ValueError('FROZEN_ROLE_IDENTITY_CHANGED')
    if not a.execute:
        result=dict(status='PREPARE_ONLY_NO_NETWORK',binding=binding,role_caps=frozen.receipt()['roles'],
            proposed_final_slots=len(manifest['task_ids'])*len(manifest['modes']),provider_calls=0)
        if a.output:
            a.output.mkdir(parents=True,exist_ok=False)
            write_once(a.output/'PREPARATION_RECEIPT.json',result)
        print(canonical(result).decode())
        return result
    # Every schema/hash/scope/approval check above precedes SDK/client construction.
    if not a.output or (a.output.exists() and not a.resume):
        raise ValueError('NEW_OUTPUT_DIRECTORY_REQUIRED')
    if a.resume:
        expected=dict(binding,transport_kind='LIVE' if transport_factory is None else transport_factory.kind,role_contract_version=config['role_contract_version'])
        if load(a.output/'RUN_BINDING.json') != expected or (a.output/'STOP.json').exists():
            raise ValueError('RESUME_BINDING_OR_FATAL_STOP_REQUIRES_RESOLUTION')
    if transport_factory is None:
        from utils.c4_rebuild.i1.transport import OpenAITransport
        transport_factory=OpenAITransport
    transport=transport_factory(approved=True,timeout=config['transport_timeout_seconds'])
    runner=None
    try:
        runner=DurableRunner(a.output,config,binding,transport,resume=a.resume,
            unknown_authorizations=approval['resume_unknown_attempts'])
        approval_receipt=a.output/('AUTHOR_APPROVAL_'+sha(approval)+'.json')
        if not approval_receipt.exists():
            write_once(approval_receipt,dict(approval=approval,external_file_sha256=sha(a.approval.read_bytes()),authenticity='OPERATOR_SUPPLIED_AUTHOR_RECORD_NOT_CRYPTOGRAPHICALLY_AUTHENTICATED'))
        worker=OfflineWorker(timeout=config['offline_worker_timeout_seconds'])
        outcomes=Orchestrator(runner,frozen,worker).run(manifest)
        result=dict(status='TERMINAL_WITH_FAILURES' if any(x['result']['status']!='ACCEPTED' for x in outcomes) else 'RESPONSES_FROZEN_UNSCORED',
            slots=len(outcomes),accepted=sum(x['result']['status']=='ACCEPTED' for x in outcomes),human_scores=0)
        runner.stage('RUN','SUMMARY',binding,result)
        print(canonical(result).decode())
        return result
    finally:
        if runner: runner.close()
        transport.close()


if __name__=='__main__':
    main()
