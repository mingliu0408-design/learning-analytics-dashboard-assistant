"""Reopen actual prepared artifacts; verify payload boundaries and trace pointers."""
import json
from hashlib import sha256
from pathlib import Path
from fixtures import HERE, FLAGS
from utils.c4_rebuild.contracts import reject_sidecars
from utils.c4_dashboard_scoped.scope import digest


def main():
    manifest=json.loads((HERE/'PILOT_REQUEST_MANIFEST.json').read_text())
    traces=json.loads((HERE/'FACT_TO_FINAL_REQUEST_TRACE.json').read_text())['traces']
    by_key={(r['task_id'],r['mode']):r for r in traces}
    facts=0;requests=0;candidates=0;retention_checks=0
    for row in manifest['requests']:
        p=HERE/row['path'];assert sha256(p.read_bytes()).hexdigest()==row['sha256']
        output=json.loads(p.read_text());final=output['final_request']
        reject_sidecars(final)
        assert final['execution_authorised'] is False and final['structured_plan'] is None
        assert digest(final)==output['trace']['final_request_sha256']
        assert output['trace']=={k:v for k,v in by_key[(row['task_id'],row['mode'])].items() if k!='task_id'}
        for fact in output['trace']['e1_fact_trace']:
            value=final
            for key in fact['final_json_pointer'].lstrip('/').split('/'):
                value=value[int(key)] if isinstance(value,list) else value[key]
            assert value['value']==fact['value']
            facts+=1
        assert output['trace']['memory_retention_complete'] and output['trace']['course_retention_complete']
        retention_checks+=2
        if output['planner'] and output['planner']['request']:
            candidate=output['planner']['request'];reject_sidecars(candidate)
            assert candidate['runtime_input']==final['runtime_input']
            candidates+=1
        requests+=1
    shells=json.loads((HERE/'COMMON_HUMAN_EVIDENCE_SHELLS.json').read_text())['shells']
    assert len(shells)==12 and all(not s['responses'] and not s['ratings'] and s['rater_identity'] is None for s in shells)
    saved=json.loads((HERE/'ACTUAL_M1_SAVED_ENVELOPE_PROJECTIONS.json').read_text())['records']
    assert len(saved)==4 and all(x['raw_text_unchanged'] and x['all_saved_native_ids_present_in_reopened_source'] for x in saved)
    for row in saved:
        assert digest(row['actual_saved_envelope'])==row['original_envelope_sha256']
        assert row['without_runtime_authority']['validation']['outcome']!='PASSED_ENCODED_CHECKS'
        assert row['with_reproduced_synthetic_native_authority']['bridge']['i0_diagnostics']['semantic_support']=='NOT_CHECKED'
    result=dict(status='PASS',prepared_requests_reopened=requests,candidate_requests_reopened=candidates,
        e1_fact_pointers_verified=facts,retention_assertions=retention_checks,human_shells_reopened=len(shells),
        actual_saved_m1_envelopes_verified=len(saved),responses_generated=0,ratings_created=0)
    (HERE/'receipts/ARTIFACT_READBACK.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
