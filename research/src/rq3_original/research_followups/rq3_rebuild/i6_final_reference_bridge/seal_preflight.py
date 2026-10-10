"""Create prospective identities once. Offline tests must follow before launch."""
import json
from i6_common import *
from final_reference_v1 import final_payload, preservation_receipt, VERSION, POLICY
import run_i6 as run

def main():
    require(not OUTPUT.exists(), 'NO_PREPARATION_AFTER_LIVE_START')
    reuse = run.reused_candidate()
    write_once(HERE/'CANDIDATE_REUSE_RECEIPT.json', reuse)
    ids=[]; candidates=[]; preservation=[]
    for index,row in enumerate(load_slots(),1):
        p=prepared(row); role=settings()['generation_roles']
        candidate=REPAIR.candidate_payload(p,role['CANDIDATE'])
        saved=HERE/'requests'/f'{index:02}_initial.json'
        require(load(saved)==candidate and sha(candidate)==row['proposed_initial_request_sha256'], 'I5_CANDIDATE_PAYLOAD_CHANGED')
        candidates.append(dict(logical=row['logical'],canonical_request_sha256=sha(candidate),
            file_sha256=sha(saved.read_bytes()),byte_identical_to_i5=saved.read_bytes()==(I5/'requests'/saved.name).read_bytes(),
            reference_catalog_unchanged=True,call_policy='REUSE_ONLY' if index==1 else 'AT_MOST_ONE_INITIAL'))
        plan=reuse['candidate'] if index==1 else None
        payload=final_payload(p,role['FINAL'],plan)
        body=json.loads(payload['messages'][1]['content'])
        ids.append(dict(logical=row['logical'],allowed_source_evidence_ids=body['final_citation_contract']['allowed_source_evidence_ids'],
            sources=[dict(id=x['id'],kind=x['kind'],content_sha256=sha(x['content'])) for x in body['source_facts']],
            trace_exact=True,prepared_sha256=sha(p)))
        preservation.append(dict(logical=row['logical'],**preservation_receipt(p,role['FINAL'],plan)))
        write_once(HERE/'schemas'/f'{index:02}_final.wire.json',payload['response_format']['json_schema']['schema'])
        if index==1: write_once(HERE/'requests/01_i6_final.json',payload)
    write_once(HERE/'CANDIDATE_REQUEST_VERIFICATION.json', candidates)
    write_once(HERE/'ALLOWED_SOURCE_IDS.json',ids)
    write_once(HERE/'FINAL_INPUT_PRESERVATION.json',preservation)
    write_once(HERE/'FINAL_REFERENCE_CONTRACT_V1.json',dict(version=VERSION,policy=POLICY,original_checker='utils/c4_rebuild/i1/schemas.py:final_errors',
        original_checker_sha256=sha((ROOT/'utils/c4_rebuild/i1/schemas.py').read_bytes()),
        no_source_wire_policy='String items without empty enum; mandatory [] in instructions and unchanged local subset validation.',
        source='Actual I1 renderer output and prepared retained-evidence trace only.'))
    (HERE/'FINAL_REFERENCE_CONTRACT_V1.md').write_text('# I6 FINAL reference contract v1\n\n'+POLICY+
        '\nThe source catalogue is derived only from retained rendered source_facts, in unchanged order. '
        'It adds no evidence. Nonempty catalogues constrain citation items with enum. '
        'An empty catalogue uses no empty enum or dummy ID; the original final_errors rejects every nonempty citation list. '
        'The original final_errors still checks source subset, duplicate citations, nonempty answer and exact accepted-plan equality. '
        'The original candidate-failure fallback remains unchanged and is ineligible for these live slots.\n\n'
        'Implementation reference: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). '
        'Uses the existing pinned strict-schema checker and enum subset. Budget rates remain the I5 frozen convention.\n',encoding='utf-8')
    b=run.binding()
    approval=dict(version='I6_DIRECT_APPROVAL_V1',authority='DIRECT_USER_MESSAGE_CURRENT_CONVERSATION',status='AUTHORIZED',
        recorded_at=utc(),timestamp_basis='Local receipt creation time; the user message has no asserted timestamp.',
        quotation_boundary='DIRECT_USER_APPROVAL_MESSAGE.txt preserves the current user request; task-document instructions are separately retained under task_spec.',
        signature_semantics='Direct user message authorization only; no signature or external approval fabricated.',binding=b,binding_sha256=sha(b))
    run.validate_approval(approval,b)
    write_once(HERE/'DIRECT_APPROVAL.json',approval)
    write_once(HERE/'PRECALL_IDENTITY_SEAL.json',dict(status='SEALED_AWAITING_OFFLINE_TESTS',binding=b,binding_sha256=sha(b),
        approval_sha256=sha(approval),utc=utc(),provider_calls=0,client_constructed=False))
    print(canonical(dict(status='SEALED',binding_sha256=sha(b),files=len(b['files']))).decode())

if __name__ == '__main__': main()
