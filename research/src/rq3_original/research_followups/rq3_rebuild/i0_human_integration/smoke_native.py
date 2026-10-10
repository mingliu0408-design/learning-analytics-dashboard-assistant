"""One coordinated local MPNet interface smoke. No dataset scoring or generation."""
from pathlib import Path
import fcntl
import json
import os
from hashlib import sha256
import tempfile
from datetime import datetime, timezone
from fixtures import *
from utils.c4_rebuild.service import ResearchService


def main():
    out=Path(tempfile.mkdtemp(prefix='native_smoke_',dir=HERE/'receipts'))
    receipt=dict(started=datetime.now(timezone.utc).isoformat(),scope='ONE_SYNTHETIC_I0_INTERFACE_SMOKE',
        coordination='R2 task 01a078f4-543d-75f1-ad3e-71fd3468a81d reported its model released; I0 advisory lock acquired before worker construction.',
        process_inventory='ps was denied by the filesystem sandbox; readiness used R2 release confirmation and the shared advisory lock, not an asserted process scan.',
        generation_calls=0,judge_calls=0,ratings=0,environment_changes=0,downloads=0)
    lock=open('/private/tmp/rq3-rebuild-local-inference.lock','a+')
    receipt['i0_source_hashes']={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT/'utils/c4_rebuild').glob('*.py'))}
    backend=None
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt['advisory_lock']='ACQUIRED'
        m1_dependencies()
        from local_backend import LocalBackend
        python='/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/.venv/bin/python'
        if not Path(python).is_file():raise RuntimeError('VERIFIED_INTERPRETER_UNAVAILABLE')
        backend=LocalBackend(python,out)
        with tempfile.TemporaryDirectory(prefix='i0-native-state-',dir=HERE/'.runtime') as td:
            m, setup=memory_source(0,td,backend=backend)
            s=ResearchService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(False,True,True),memory=m)
            prepared=s.prepare(request(query='Remind me of my goal and suggest next steps without dates.'))
        receipt.update(status='PASS',interpreter=python,worker_identity=backend.ready,
            encoding_calls_during_retrieval=len(backend.inputs),encoding_receipts=backend.inputs,
            m1_fact_count=len(prepared['final_request']['runtime_input']['memory']['facts']),
            planner_preparation=prepared['planner']['status'],request_sha256=prepared['trace']['final_request_sha256'],
            semantics='NOT_CHECKED_NO_ACCURACY_OR_SUPERIORITY_CLAIM')
        (out/'SYNTHETIC_PREPARED_REQUEST.json').write_text(json.dumps(prepared,indent=2)+'\n')
    except Exception as exc:
        receipt.update(status='UNAVAILABLE_OR_FAILED',error=type(exc).__name__+': '+str(exc))
    finally:
        if backend is not None:
            backend.close();receipt['worker_exit_code']=backend.process.returncode
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
        receipt['ended']=datetime.now(timezone.utc).isoformat()
        (out/'NATIVE_SMOKE_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(dict(status=receipt['status'],receipt_directory=str(out),
                         encoding_calls=receipt.get('encoding_calls_during_retrieval'),
                         error=receipt.get('error'))))


if __name__=='__main__':main()
