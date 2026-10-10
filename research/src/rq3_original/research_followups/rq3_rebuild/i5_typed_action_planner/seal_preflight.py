"""Record direct message authority, then bind the final offline-tested identity."""
import argparse
from i5_common import *


def approve():
    from run_i5 import binding, validate_approval
    b = binding()
    record = dict(version='I5_DIRECT_APPROVAL_V1',authority='DIRECT_USER_MESSAGE_CURRENT_CONVERSATION',
        status='AUTHORIZED',recorded_at=utc(),timestamp_basis='Local recording time, not a claimed user-send timestamp',
        quotation_boundary='DIRECT_USER_APPROVAL_MESSAGE.txt contains the complete supplied My request message in UTF-8, with a terminal LF. Markdown escapes are retained.',
        signature_semantics='Verbatim direct user authority; no fabricated signature or human rating.',
        binding=b,binding_sha256=sha(b))
    validate_approval(record,b)
    path=HERE/'DIRECT_APPROVAL.json'
    if path.exists():
        require(not OUTPUT.exists(),'NO_POSTLIVE_APPROVAL_REBIND')
        previous=path.read_bytes()
        folder=HERE/'offline_approval_history'; folder.mkdir(exist_ok=True)
        with (folder/(sha(previous)+'.json')).open('xb') as f:f.write(previous)
        path.unlink()
    write_once(path,record)
    print(canonical(dict(status='AUTHORIZED',binding_sha256=sha(b),message_sha256=sha((HERE/'DIRECT_USER_APPROVAL_MESSAGE.txt').read_bytes()))).decode())


def seal(run):
    from run_i5 import validate_preflight, binding, validate_approval
    require(not OUTPUT.exists(),'NO_POSTLIVE_SEAL')
    report=load(HERE/'offline_runs'/run/'SUMMARY.json')
    require(report['status']=='PASS' and report['code_binding_sha256']==sha(binding()),'TESTED_CODE_MISMATCH')
    validate_approval(load(HERE/'DIRECT_APPROVAL.json'),binding())
    write_once(HERE/'OFFLINE_TEST_SUMMARY.json',report)
    receipt=validate_preflight()
    write_once(HERE/'PRECALL_IDENTITY_SEAL.json',dict(status='SEALED',utc=utc(),preflight=receipt,
        actual_initial_requests=[file_binding(HERE/'requests'/f'{i:02}_initial.json') for i in range(1,6)],
        contingent_requests='Exact new output/error/accepted-plan dependent; builder code, typed schema and config hashes frozen. Per-call actual request hashes are fsynced before transport.',
        mutation_policy='No code/schema/prompt edits or automatic resume after first live call.'))
    print(canonical(dict(status='SEALED',binding_sha256=sha(binding()),tests=report['tests_run'])).decode())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['approve','seal']);p.add_argument('--run');a=p.parse_args()
    approve() if a.action=='approve' else seal(a.run)
