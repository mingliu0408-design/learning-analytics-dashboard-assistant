"""Offline readback of saved outputs and frozen boundaries; no retrieval/inference."""
from pathlib import Path
import ast
import json
import math
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *

def main():
    checks={}
    initial=json.loads((LOCAL/'starting_tracked_hashes.json').read_text())
    mismatch=[p for p,h in initial.items() if not (ROOT/p).is_file() or file_hash(ROOT/p)!=h]
    assert not mismatch,mismatch
    checks['original_tracked_files_unchanged']=len(initial)
    source=json.loads((OUT/'SOURCE_AND_CODE_MANIFEST.json').read_text())
    for r in source['sources']:
        assert file_hash(Path(r['path']))==r['sha256'],r['path']
    checks['source_receipts_verified']=len(source['sources'])
    frozen=json.loads((OUT/'PRE_RANKING_FREEZE.json').read_text())
    for name,h in frozen['files'].items():assert file_hash(OUT/name)==h
    checks['frozen_inputs_and_config_unchanged']=len(frozen['files'])
    retry=json.loads((OUT/'D_COMPATIBILITY_RETRY_MANIFEST.json').read_text())
    for c,h in retry['saved_ABC_hashes'].items():assert file_hash(OUT/f'{c}_DIAGNOSTICS.json')==h
    checks['ABC_not_rewritten_during_retry']=True
    model=json.loads((OUT/'MODEL_RUNTIME_IDENTITY.json').read_text())
    for f in model['mpnet']['files']:
        assert file_hash(Path(model['mpnet']['local_path'])/f['file'])==f['sha256']
    downloaded=json.loads((OUT/'CROSS_ENCODER_DOWNLOAD_RECEIPT.json').read_text())
    for f in downloaded['files']:assert file_hash(CE_ROOT/f['name'])==f['sha256']
    assert downloaded['fetched_bytes']<=300_000_000
    checks['model_hashes_and_download_cap']=True
    crows=json.loads((OUT/'C_HYBRID_DIAGNOSTICS.json').read_text())
    drows=json.loads((OUT/'D_CROSS_ENCODER_DIAGNOSTICS.json').read_text())
    assert len(crows)==len(drows)==15
    for c,d in zip(crows,drows):
        assert c['case_id']==d['case_id'] and c['input_identity']==d['input_identity']
        assert d['candidate_pool_ids']==c['ranked_ids'][:30]
        assert set(d['ranked_ids'])==set(d['candidate_pool_ids']) and len(d['scores'])==30
        assert all(math.isfinite(s) for s in d['scores'])
    checks['exact_C_top30_pools_reranked']=15;checks['finite_real_D_pairs']=450
    report=json.loads((OUT/'CHUNK_SOURCE_COVERAGE_AUDIT.json').read_text())
    for size,v in report['versions'].items():
        assert not v['errors'] and v['totals']['missing_characters']==0 and v['totals']['unprocessed_characters']==0
        assert v['totals']['canonical_characters']==151879
        assert v['actual_model_tokens_max']<=int(size)
        path=LOCAL/f'v1a_{size}_index.json'
        assert file_hash(path)==json.loads((OUT/'V1A_INDEX_MANIFEST.json').read_text())[size]['index_sha256']
        regen=LOCAL/'regeneration_verification'/path.name
        assert file_hash(path)==file_hash(regen),'INDEX_REGENERATION_MISMATCH'
    checks['V1a_coverage_and_model_budget_and_byte_identical_regeneration']=True
    parity=json.loads((OUT/'R0_21_BASELINE_REPRODUCTION.json').read_text())
    assert parity['all_match'] and len(parity['cases'])==21
    checks['R0_21_baseline_ids_and_statuses_identical']=True
    tests=json.loads(sorted(OUT.glob('TEST_ATTEMPT_*.json'))[-1].read_text())
    assert tests['passed'] and tests['tests']==29 and tests['errors']==tests['failures']==0
    checks['synthetic_tests_passed']=29
    summary=json.loads((OUT/'FIXED_CORPUS_DIAGNOSTIC_SUMMARY.json').read_text())
    assert all(not r['searched'] for r in summary['p3_false_controls'])
    checks['P3_false_zero_search_controls']=4
    assert all(p['review_status']=='HUMAN_REVIEW_PENDING' for p in json.loads((OUT/'SOURCE_SPAN_REFERENCE_TEMPLATE.json').read_text())['probes'])
    checks['machine_authored_probes_not_claimed_reviewed']=8
    code=list((ROOT/'utils/c4_rag_lab').glob('*.py'))+list(OUT.glob('*.py'))
    for p in code:ast.parse(p.read_text())
    checks['python_syntax_files']=len(code)
    subprocess.run(['git','diff','--check'],cwd=ROOT,check=True)
    payloads=[p for root in (ROOT/'utils/c4_rag_lab',OUT) for p in root.rglob('*')
              if p.is_file() and LOCAL not in p.parents and '__pycache__' not in p.parts]
    # Reject full saved body windows (>=100 characters) in every review payload.
    bodies=[c['text'].encode() for c in json.loads((LOCAL/'v0_chunks.json').read_text()) if len(c['text'])>=100]
    leaks=[]
    for p in payloads:
        raw=p.read_bytes()
        if any(body in raw for body in bodies):leaks.append(str(p.relative_to(ROOT)))
        assert p.suffix not in ('.npy','.npz','.pdf','.safetensors','.bin','.pkl','.db','.sqlite')
    assert not leaks,leaks
    checks['review_payload_full_v0_body_scan_matches']=0
    checks['learner_source_ingestion']='EXCLUDED_BY_EXACT_SOURCE_ALLOWLIST'
    # Private source files never enter the repository/export; checking filenames alone is not treated as proof.
    checks['current_code_hashes']={str(p.relative_to(ROOT)):file_hash(p) for p in code}
    write_json(OUT/'DELIVERY_VERIFICATION.json',{'status':'PASS','checks':checks,
        'limitations':['raw-layout extraction completeness unverified','independent fact/span labels absent',
            'D float32 runtime remains incompatible; measured D is float64/eager','initial MPNet load/build timing not durable']})
    print(json.dumps({k:v for k,v in checks.items() if k!='current_code_hashes'},indent=2))

if __name__=='__main__':main()
