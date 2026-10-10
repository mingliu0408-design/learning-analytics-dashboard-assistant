"""Mechanical source metadata audit and BLANK human fields. No factual labels."""
from common import *
import csv

def main():
    metadata_path=R1/'SOURCE_COVERAGE_AND_TEXT_MAP.csv'
    before=subprocess.check_output(['git','show',f'{BASE}:{metadata_path.relative_to(ROOT)}'])
    assert digest(before)==file_hash(metadata_path)
    profiles=list(csv.DictReader(metadata_path.open()))
    allowlist=[json.loads(line) for line in (ROOT/'course_materials_v2/manifest.jsonl').read_text().splitlines()]
    by_doc={r['document_id']:r for r in allowlist}
    sections_path=r1_local()/'canonical_sections.json'
    assert file_hash(sections_path)==inherited(R1/'PRE_RANKING_FREEZE.json')['files']['local_artifacts/canonical_sections.json']
    sections=read_json(sections_path)
    canonical_by_doc={p['document_id']:''.join(s['text'] for s in sections if s['document_id']==p['document_id']) for p in profiles}
    actual=[]
    for p in profiles:
        source=Path(p['source_path'])
        if by_doc[p['document_id']]['source_path']=='utils/course_metadata.py':
            source=ROOT/'utils/course_metadata.py'
        entry={'document_id':p['document_id'],'source_path':str(source),
               'expected_sha256':p['source_sha256'],'exists':source.is_file(),
               'content_level_from_frozen_manifest':p['content_level'],
               'source_text_status_from_R1':p['text_status'],
               'original_extraction_completeness':'UNVERIFIED',
               'linked_bodies':'NOT_AVAILABLE_OR_NOT_AUTHORIZED' if p['linked_body_status']=='MISSING_BODY' else 'NOT_APPLICABLE',
               'no_crawl':True,'human_relevance_review':None}
        if source.is_file():
            entry.update(source_receipt(source,'SIX_SOURCE_METADATA_AND_HASH_CHECK'))
            entry['hash_match']=entry['sha256']==p['source_sha256']
            assert entry['hash_match'], 'SOURCE_HASH_CHANGED'
            with source.open('rb') as f:head=f.read(64)
            entry['signature']='PDF' if head.startswith(b'%PDF') else 'HTML_PREFIX' if b'html' in head.lower() or head.lstrip().startswith(b'<') else 'TEXT_OR_CODE'
        text=canonical_by_doc[p['document_id']]
        entry.update(canonical_characters=len(text),canonical_text_sha256=digest(text.encode()),
                     limited_canonical_excerpt=text[:96],excerpt_span=[0,min(96,len(text))],
                     excerpt_coordinate='canonical Unicode characters, NOT original bytes or PDF coordinates',
                     excerpt_purpose='human source identification only; no LLM correctness judgement')
        actual.append(entry)
    chunks=read_json(r1_local()/'v0_chunks.json')
    assert digest(canonical(chunks))==V0
    chunk_by_id={c['chunk_id']:c for c in chunks}
    doc_for_source={r['source_path']:r['document_id'] for r in allowlist}
    # V0 preserves absolute source-file identities, while the allowlist uses
    # relative paths. Admit only the exact hash-verified profile/manifest aliases.
    doc_for_source.update({r['source_path']:r['document_id'] for r in profiles})
    doc_for_source.update({r['source_path']:r['document_id'] for r in actual})
    original_by_doc={r['document_id']:r for r in actual}
    refs=read_json(OUT/'EXPOSED_REFERENCE_ID_MAPPING.json')['cases']
    rows=[]
    for case in refs:
        for ident in case['reference_ids']:
            chunk=chunk_by_id[ident];doc=doc_for_source[chunk['source_file']]
            text=canonical_by_doc[doc];body=chunk['text'];matches=[];cursor=0
            while body:
                pos=text.find(body,cursor)
                if pos<0:break
                matches.append({'start':pos,'end':pos+len(body),'coordinate':'R1_CANONICAL_UNICODE_CHARACTERS'})
                cursor=pos+1
            rows.append({'case_id':case['case_id'],'legacy_reference_id':ident,
                'reference_namespace':'EXPOSED_DEVELOPMENT_REFERENCE_ID_NOT_HUMAN_SUFFICIENCY_GOLD',
                'source_document_id':doc,'source_version_sha256':original_by_doc[doc]['expected_sha256'],
                'canonical_text_sha256':digest(text.encode()),'legacy_chunk_body_sha256':digest(body.encode()),
                'mechanical_canonical_exact_matches':matches,
                'mechanical_mapping_status':'EXACT_SUBSTRING_LOCATED_RELEVANCE_UNREVIEWED' if matches else 'NO_EXACT_V0_TO_CANONICAL_MATCH_ORIGINAL_REVIEW_NEEDED',
                'required_proposition':None,'original_document_locator':None,'original_span':None,
                'original_extraction_correct':None,'acceptable_alternative_evidence':[],
                'reviewed_chunk_spans':[],'sufficient_body_for_proposition':None,
                'wrong_week_or_version':None,'reviewer_id':None,'review_date':None,
                'review_status':None,'human_notes':None})
    write_json(OUT/'BLANK_SOURCE_FACT_REVIEW.json',{'status':'BLANK_HUMAN_REVIEW_REQUIRED',
        'human_fields_prefilled':False,'rows':rows,'response_ratings':None},exclusive=True)
    columns=['case_id','legacy_reference_id','source_document_id','source_version_sha256',
             'required_proposition','original_document_locator','original_span','acceptable_alternative_evidence',
             'reviewed_chunk_spans','original_extraction_correct','sufficient_body_for_proposition',
             'wrong_week_or_version','reviewer_id','review_date','review_status','human_notes']
    with (OUT/'BLANK_SOURCE_FACT_REVIEW.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');writer.writeheader()
        for r in rows:writer.writerow({k:r[k] if k in columns[:4] else '' for k in columns})
    prospective=[]
    for stratum in ('ANSWERABLE','UNANSWERABLE','WRONG_WEEK','INSUFFICIENT_BODY'):
        prospective.append({'planned_DEV_stratum':stratum,'case_id':None,'query':None,
                            'original_document_version':None,'required_propositions':[],
                            'acceptable_evidence_spans':[],'reference_judgement':None,
                            'human_reviewer':None,'adjudication':None,'frozen_before_candidate_output_review':None})
    write_json(OUT/'BLANK_PROSPECTIVE_DEV_REFERENCE.json',{
        'status':'TEMPLATE_NOT_A_NEW_BENCHMARK','strata_are_planning_categories_not_assigned_labels':True,
        'cases':prospective},exclusive=True)
    index_manifest=inherited(R1/'V1A_INDEX_MANIFEST.json')
    report={'sources':actual,'source_count':len(actual),
            'available_body_sources':sum(r['source_text_status_from_R1']=='AVAILABLE_BODY' for r in actual),
            'metadata_only_sources':sum(r['source_text_status_from_R1']=='METADATA_ONLY' for r in actual),
            'canonical_sections':len(sections),'canonical_characters':sum(len(t) for t in canonical_by_doc.values()),
            'source_manifest_sha256':file_hash(ROOT/'course_materials_v2/manifest.jsonl'),
            'canonical_sections_file':source_receipt(sections_path,'R1_CANONICAL_READ_ONLY'),
            'R1_chunk_counts_read_not_regenerated':{k:v['chunks'] for k,v in index_manifest.items()},
            'reference_occurrences':len(rows),'unique_legacy_reference_ids':len(set(r['legacy_reference_id'] for r in rows)),
            'occurrences_with_exact_canonical_match':sum(bool(r['mechanical_canonical_exact_matches']) for r in rows),
            'original_document_span_review_completed':0,'factual_correctness_labels_created':0,
            'rechunking_or_size_sweep_executed':False,'source_extraction_repaired':False,
            'limits':['Canonical character coverage is not original extraction fidelity.',
                      'Exact substring presence is not relevant or sufficient evidence.',
                      'No exact V0-to-canonical match does not prove original source loss.',
                      'Reading links, citation lists and lecture metadata are not target paper bodies or lecture transcripts.']}
    write_json(OUT/'SOURCE_READINESS_AUDIT.json',report,exclusive=True)
    (OUT/'SOURCE_REFERENCE_CHECKLIST.md').write_text('''# Source fact and chunk-readiness review

Use BLANK_SOURCE_FACT_REVIEW.json/CSV for the 26 old query-reference occurrences (some IDs repeat). The populated ID/hash fields are mechanical provenance. Every proposition, original span, correctness, sufficiency, alternative-evidence, reviewer and review-status field remains blank. No new human attestation is implied.

1. Confirm local permission, intended course/version, and availability of the original document. Do not treat a link as permission or body text.
2. Independently state each required proposition from the task and original source. Keep this review separate from candidate selection and new rank inspection.
3. Record the original HTML element/heading/URL or PDF page and span, with document SHA-256/version. Inspect omissions, tables and headings against the original; canonical offsets alone do not establish original-layout fidelity.
4. Identify all acceptable alternative evidence and explicit nonanswers (wrong week, wrong version, title-only, missing body). Do not require one old chunk ID if another source span supports the proposition.
5. Map reviewed original spans to canonical Unicode spans and then chunk spans; identify partial/multiple/missing mappings. The provided exact-substring locations are unreviewed mechanical hints, not final original spans.
6. Leave uncertainty explicit; record reviewer identity/date and adjudication only after real human work. Do not fill response ratings in these source templates.
7. Freeze prospective DEV references before calibration and an independent evaluation set before final use. Any extraction or rechunking comparison is a later separately authorized factor, with fixed references and corpus identity.

The six-source hash check and short identification excerpts do not certify extraction completeness. R1's 651/585 chunks mechanically cover its 151,879 canonical characters; R2 does not regenerate or compare these sizes. The ranking experiment retains the distinct 624-chunk V0 corpus.
''')
    print(json.dumps({k:v for k,v in report.items() if k not in ('sources','limits','canonical_sections_file')},indent=2))

if __name__=='__main__':
    main()
