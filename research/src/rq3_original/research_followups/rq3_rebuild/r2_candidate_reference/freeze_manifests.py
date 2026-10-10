"""Freeze source/output manifests after all authorized task artifacts are complete."""
from common import *

def main():
    names=['A_R0_DIAGNOSTICS.json','C_HYBRID_DIAGNOSTICS.json','D_CROSS_ENCODER_DIAGNOSTICS.json',
           'RUN_CONFIG.json','PRE_RANKING_FREEZE.json','D_COMPATIBILITY_RETRY_MANIFEST.json',
           'MODEL_RUNTIME_IDENTITY.json','CROSS_ENCODER_DOWNLOAD_RECEIPT.json','CROSS_ENCODER_TOKEN_AUDIT.json',
           'HISTORICAL_REFERENCE_VERIFICATION.json','QUERY_IDENTITY_MAP.json',
           'SOURCE_COVERAGE_AND_TEXT_MAP.csv','V1A_INDEX_MANIFEST.json']
    sources=[]
    for n in names:
        p=R1/n
        b=subprocess.check_output(['git','show',f'{BASE}:{p.relative_to(ROOT)}'])
        assert digest(b)==file_hash(p)
        sources.append(source_receipt(p,'INHERITED_R1_READ_ONLY_NO_RAW_RATINGS_EXPORTED'))
    sources.append(source_receipt(ROOT/'course_materials_v2/manifest.jsonl','UNCHANGED_SIX_SOURCE_ALLOWLIST'))
    sources.append(source_receipt(Path(read_json(OUT/'START_GATE_RECEIPT.json')['input_zip']),'USER_ADOPTED_UPDATED_TASK_PACKET'))
    sources.extend(read_json(OUT/'INFERENCE_SOURCE_MANIFEST.json')['sources'])
    sources.append(read_json(OUT/'SOURCE_READINESS_AUDIT.json')['canonical_sections_file'])
    sources.extend({k:r[k] for k in ('path','bytes','sha256','role')} for r in read_json(OUT/'SOURCE_READINESS_AUDIT.json')['sources'])
    unique={r['path']:r for r in sources}
    write_json(OUT/'SOURCE_INPUT_MANIFEST.json',{
        'start_head':BASE,'start_tree':subprocess.check_output(['git','rev-parse',BASE+'^{tree}'],text=True).strip(),
        'source_count':len(unique),'sources':list(unique.values()),
        'scope':'Only named completed R1 artifacts, adopted task packet, exact existing local model/requests/corpus and six-source identities. No unfinished I0/H0 files.',
        'private_local_inputs_excluded_from_Git_and_review':True},exclusive=True)
    files=[]
    for p in sorted(OUT.rglob('*')):
        rel=p.relative_to(OUT)
        if any(part in ('local_artifacts','__pycache__') for part in rel.parts) or rel.as_posix()=='OUTPUT_MANIFEST.json':continue
        if p.is_symlink():raise RuntimeError('SYMLINK_IN_TASK_OUTPUT')
        if p.is_file():files.append({'path':rel.as_posix(),'bytes':p.stat().st_size,'sha256':file_hash(p)})
    write_json(OUT/'OUTPUT_MANIFEST.json',{'members':files,'excluded_self':'OUTPUT_MANIFEST.json',
        'excluded_directories':['local_artifacts/','__pycache__/'],
        'post_commit_receipts':'Archive GIT_HANDOFF/IMPLEMENTATION.diff/EXPORT_ALLOWLIST/REVIEW_MANIFEST are generated afterward; the external archive receipt is not included recursively.'},exclusive=True)
    print(json.dumps({'sources':len(unique),'output_manifest_covered_files':len(files),'self_excluded':True}))

if __name__=='__main__':
    main()
