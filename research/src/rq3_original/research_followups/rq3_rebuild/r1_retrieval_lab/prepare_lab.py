"""Freeze inputs/config/probes before candidate rankings; no model inference."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import csv
import importlib.metadata
import json
import platform
import subprocess
import sys
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *

def main():
    assert Path.cwd().resolve()==ROOT
    assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==BRANCH
    assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==BASE
    assert not subprocess.check_output(['git','diff','--name-only',BASE],text=True).strip()
    if (OUT/'PRE_RANKING_FREEZE.json').exists():
        raise FileExistsError('PRE_RANKING_FREEZE_EXISTS')
    LOCAL.mkdir(exist_ok=True)
    with offline_guard() as guard:
        from utils.c4_rag.corpus import (load_legacy_chunks, legacy_chunk_corpus_hash, EXPECTED_SOURCE_HASHES,
            CANONICAL_CFULL_ROOT, CANONICAL_MPNET_ROOT, MPNET_REVISION)
        chunks=load_legacy_chunks()
        assert len(chunks)==624 and legacy_chunk_corpus_hash(chunks)==V0
        write_json(LOCAL/'v0_chunks.json',[asdict(c) for c in chunks])
        source_receipts=[]
        packet=Path('/Users/liuming/Downloads/RQ3_REBUILD_R1_CODEX_TASK_PACKET_2026-09-06.zip')
        with ZipFile(packet) as z:
            assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
            for n in z.namelist():
                assert not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
            manifest=json.loads(z.read('MANIFEST.json'))
            assert {m['path'] for m in manifest['members']}==set(z.namelist())-{'MANIFEST.json'}
            for item in manifest['members']:
                data=z.read(item['path'])
                assert len(data)==item['bytes'] and digest(data)==item['sha256']
            source_receipts.append({'path':str(packet),'sha256':file_hash(packet),'bytes':packet.stat().st_size,
                'role':'user-adopted task specification; REFERENCES read-only','verified_members':16})
        from utils.retrieval_v2.models import ManifestRecordV2
        from utils.retrieval_v2.ingestion import _extract_html,_extract_pdf,_extract_txt,_extract_python_metadata
        from utils.c4_rag_lab.chunking import Section
        sections=[]; profiles=[]; canonical_map=[]
        for line in (ROOT/'course_materials_v2/manifest.jsonl').read_text().splitlines():
            r=ManifestRecordV2.from_dict(json.loads(line))
            path=(ROOT if r.source_type=='python_metadata' else CANONICAL_CFULL_ROOT)/r.source_path
            assert file_hash(path)==EXPECTED_SOURCE_HASHES[r.source_path]
            source_receipts.append({'path':str(path),'sha256':file_hash(path),'bytes':path.stat().st_size,'role':'COURSE'})
            if r.source_type in ('html','legacy_doc'):
                d=_extract_html(path,r,'inherited_html')
            else:
                d={'pdf':_extract_pdf,'txt':_extract_txt,'python_metadata':_extract_python_metadata}[r.source_type](path,r)
            cursor=0; texts=[]
            for s in d.sections:
                sections.append(Section(d.document_id,d.source_hash,COURSE,'authorised_course_local_only',
                    s.text,cursor,tuple(s.section_path),s.week,s.assessment_part,d.material_type,s.source_url,s.page_number))
                texts.append(s.text); cursor+=len(s.text)
            text=''.join(texts)
            canonical_map.append({'document_id':d.document_id,'canonical_text_sha256':digest(text.encode()),
                'characters':len(text),'section_count':len(texts),'separator_policy':'concatenation; explicit section boundaries stored'})
            profiles.append({'document_id':d.document_id,'source_path':str(path),'source_sha256':d.source_hash,
                'source_bytes':path.stat().st_size,'format':r.source_type,'namespace':'COURSE','independent_document_count':1,
                'text_status':'AVAILABLE_BODY' if r.content_level=='full_text' and text else 'METADATA_ONLY' if text else 'MISSING_BODY',
                'extraction_completeness':'EXTRACTION_UNVERIFIED_AGAINST_RAW_LAYOUT',
                'content_level':r.content_level,'canonical_characters':len(text),'sections':len(texts),
                'heading_available':bool(d.sections),'url_count':text.count('http'),
                'language':'English-dominant; no language model used','permissions':'inherited six-source local-only; no linked-body crawl',
                'linked_body_status':'MISSING_BODY' if r.content_level!='full_text' else 'NOT_APPLICABLE',
                'structural_limits':'inherited parser normalises whitespace/deduplicates lines; PDF tables/reading bodies not reconstructed'})
        write_json(LOCAL/'canonical_sections.json',[asdict(s) for s in sections])
        with (OUT/'SOURCE_COVERAGE_AND_TEXT_MAP.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,lineterminator='\n',fieldnames=list(profiles[0]));w.writeheader();w.writerows(profiles)
        write_json(OUT/'CORPUS_REGISTRY.json',{'V0':{'sha256':V0,'chunks':624,'sources':6,
            'text_sha256_by_chunk':{c.chunk_id:digest(c.text.encode()) for c in chunks},
            'identity_serialisation':'utils.c4_rag.corpus.legacy_chunk_corpus_hash'},
            'V1a':{'canonical_documents':canonical_map,'extractor':'unchanged retrieval_v2 ingestion at starting HEAD',
                'scope':'same extracted text across both token sizes; NOT text-equivalent to legacy V0',
                'offset_unit':'Unicode character in per-document concatenation of inherited extracted sections'},
            'V1b':{'status':'NOT_RUN','definition':'repair extraction or recover raw source content; separate coverage intervention'},
            'V2':{'status':'SPEC_ONLY_NOT_AUTHORISED_FOR_INGESTION','definition':'additional independently authorised source bodies'}})
        # Read only exact historical files; references remain outside candidate inputs.
        prior=json.loads((ROOT/'evaluation/rq3_real_c4/track_r_rag/retrieval_comparison_v1.json').read_text())['evaluation_provenance']
        oldroot=CANONICAL_CFULL_ROOT/'evaluation'
        loaded={}
        for name,h in prior['input_hashes'].items():
            p=oldroot/name
            assert file_hash(p)==h, 'HISTORICAL_VERSION_MISMATCH'
            source_receipts.append({'path':str(p),'sha256':h,'bytes':p.stat().st_size,'role':'EXPOSED_DEV_REFERENCE_NOT_CORPUS'})
            if name in ('unified_benchmark_scenarios.jsonl','unified_reference_evidence_v1.jsonl'):
                loaded[name]=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        ids=prior['unified_selected_ids']; assert len(ids)==15 and len(set(ids))==15
        raw={r['scenario_id']:r for r in loaded['unified_benchmark_scenarios.jsonl']}
        ref={r['scenario_id']:r for r in loaded['unified_reference_evidence_v1.jsonl']}
        requests=[{'id':i,'query':raw[i]['student_query'],'page':raw[i]['page'], 'namespace':'EXPOSED_15_DEV',
                   'query_sha256':digest(raw[i]['student_query'].strip().encode())} for i in ids]
        labels=[]; by_id={c.chunk_id:c for c in chunks}; comparisons=[]
        for i in ids:
            row=ref[i]; gold=list(row.get('reference_chunk_ids') or [])
            assert set(gold)<=set(by_id), 'REFERENCE_ID_NOT_IN_V0'
            body_checks=[]
            for c in row.get('reference_course_evidence') or []:
                if c['chunk_id'] in by_id:
                    body_checks.append(str(c.get('text',''))==by_id[c['chunk_id']].text)
            labels.append({'id':i,'reference_ids':gold,'review_status_saved':row.get('review_status'),
                           'body_bytes_match_when_available':body_checks})
        write_json(LOCAL/'historical_requests.json',requests)
        write_json(LOCAL/'historical_labels.json',labels)
        write_json(OUT/'HISTORICAL_REFERENCE_VERIFICATION.json',{'status':'EXACT_FILE_HASHES_AND_IDS_VERIFIED',
            'source_inputs':prior['input_hashes'],'selected_ids':ids,'cases':labels,
            'limitation':'saved approved/revised fields do not prove independent human adjudication; reference-ID relevance only, not sufficiency'})
        # Source-anchored draft selection is deterministic and precedes any new ranking.
        def anchors(doc, week=None, part=None):
            eligible=[s for s in sections if s.document_id==doc and (week is None or s.week==week)
                      and (part is None or s.assessment_part==part)]
            return [{'document_id':s.document_id,'source_sha256':s.source_hash,'start':s.base_offset,
                'end':s.base_offset+len(s.text),'text_sha256':digest(s.text.encode()),'required_facts':[],
                'anchor_status':'DRAFT_LOCATION_ONLY_NOT_SUFFICIENCY_REFERENCE'} for s in eligible[:1]]
        probes=[]
        for ident,kind,q,doc,week,part in [
            ('DEV01','navigation_metadata','Where is the Week 4 lecture link?','module_weekly_pages','W4',None),
            ('DEV02','body_content','What requirements does Part A specify for reflective writing?','module_handbook',None,'Part A'),
            ('DEV03','multi_section','Compare the requirements of assessment Part A and Part B.','module_handbook',None,None),
            ('DEV04','ambiguous_followup','What about the second one?',None,None,None),
            ('DEV05','wrong_week_hard_negative','What is the Week 5 debate task, rather than the Week 4 task?','module_weekly_pages','W5',None),
            ('DEV06','title_only_insufficient','Explain the detailed empirical argument in the Week 4 reading.','module_reading_list',None,None),
            ('DEV07','corpus_unanswerable','What are the course visa sponsorship rules?',None,None,None),
            ('DEV08','no_rag_numeric_dashboard','How many times did I view the Dashboard this week?',None,None,None)]:
            a=anchors(doc,week,part) if doc else []
            if kind=='multi_section':a=anchors(doc,part='Part A')+anchors(doc,part='Part B')
            probes.append({'id':ident,'category':kind,'query':q,'draft_anchors':a,
                'authorship':'MACHINE_AUTHORED_DEVELOPMENT_PROBES','review_status':'HUMAN_REVIEW_PENDING',
                'candidate_rankings_viewed_before_draft':False,'independent_held_out':False,
                'expected_p3_control':False if kind=='no_rag_numeric_dashboard' else None,
                'required_fact_labels':None,'wrong_week_negative':'W4' if kind=='wrong_week_hard_negative' else None})
        write_json(OUT/'SOURCE_SPAN_REFERENCE_TEMPLATE.json',{'probes':probes,'schema':{
            'required_fact_id':'human assigns','acceptable_spans':'document/hash/start/end','support_type':'title_url|body|multi_section',
            'answerability':'answerable|partial|unanswerable|ambiguous','reviewer':'not supplied','review_date':'not supplied'},
            'use':'draft locations require human review; not a scored evaluation set'})
        config={'schema':'r1_lab_fixed_config_v1','lexical_depth':50,'dense_depth':50,'rrf_constant':60,
            'rrf_votes':[2,1],'rerank_depth':30,'final_k':5,'mpnet_cap':384,'ce_cap':512,'query_cap':64,
            'batch_size':4,'threads':1,'device':'cpu','dtype':'float32','context_budget':1200,
            'bm25':{'k1':1.5,'b':0.75,'field_weights':{'title':3.4,'section':2.8,'body':1.0,'metadata':3.6}},
            'chunk_windows':[256,384],'overlap_tokens':24,'neighbour_radius':1,
            'effective_query':'raw_strip_v1','history':False,'gold_query_type':False,'hard_week_filter':False,
            'candidate_thresholds':{'A_R0':'native best>=2.0','B_BM25':None,'C_HYBRID':None,'D_CROSS_ENCODER':None},
            'new_candidate_deployment_action':'ABSTAIN_UNCALIBRATED','diagnostic_mode':'retriever_only',
            'comparison_scope':'pipeline A vs B/C/D; B vs C controlled dense addition; C top30 vs D same pool',
            'normalisation_and_filters':'common course/source ACL only; R0 native page/query bonuses retained',
            'neural_serialization':'inherited _embedding_text; no V0 text repair or deduplication',
            'tie_break':'score descending then chunk_id ascending','selection':'one declared setting; no tuning/grid'}
        write_json(OUT/'RUN_CONFIG.json',config)
        model_identity=[]
        old_identity=json.loads((ROOT/'evaluation/rq3_real_c4/track_r_rag/c4_rag_r1_identity_v1.json').read_text())
        for path in sorted(CANONICAL_MPNET_ROOT.rglob('*')):
            if not path.is_file():continue
            rel=str(path.relative_to(CANONICAL_MPNET_ROOT)); h=file_hash(path)
            if rel in old_identity['model_file_hashes']: assert h==old_identity['model_file_hashes'][rel]
            model_identity.append({'file':rel,'bytes':path.stat().st_size,'sha256':h})
        write_json(OUT/'MODEL_RUNTIME_IDENTITY.json',{'python':platform.python_version(),'executable':sys.executable,
            'packages':{x:importlib.metadata.version(x) for x in ('torch','transformers','numpy','safetensors','tokenizers','psutil')},
            'mpnet':{'local_path':str(CANONICAL_MPNET_ROOT),'revision':MPNET_REVISION,'files':model_identity,
                'backend':'Transformers mean pooling + unit L2 normalization','status':'AVAILABLE_NOT_YET_EXECUTED'},
            'cross_encoder':{'local_path':str(CE_ROOT),'revision':CE_REVISION,'status':'DOWNLOADED_NOT_YET_EXECUTED',
                'receipt_sha256':file_hash(OUT/'CROSS_ENCODER_DOWNLOAD_RECEIPT.json')},
            'pdf_parser':'pure Python pypdf from existing base site-packages via inherited scoped import; no installs'})
        tracked=subprocess.check_output(['git','ls-files','-z']).decode().split('\0')
        inventory={p:file_hash(ROOT/p) for p in tracked if p and (ROOT/p).is_file()}
        write_json(LOCAL/'starting_tracked_hashes.json',inventory)
        write_json(OUT/'SOURCE_AND_CODE_MANIFEST.json',{'sources':source_receipts,
            'starting_tracked_tree_sha256':digest(canonical(inventory)),
            'inspected_code':{p:h for p,h in inventory.items() if p.startswith(('utils/c4_rag/','utils/retrieval_v2/'))
                or p in ('utils/course_material_retriever.py','course_materials_v2/manifest.jsonl')},
            'namespace_policy':{'COURSE':'exact six-source allowlist only','DEVELOPMENT_REFERENCE':'separate ignored label/query files',
                'LEARNER_EVIDENCE':'excluded; E0 map is locator/schema context only; raw learner rows never read'},
            'input_packet_does_not_contain_all_course_sources':True})
        freeze={'time_utc':datetime.now(timezone.utc).isoformat(),'base_head':BASE,'branch':BRANCH,'cwd':str(ROOT),
            'initial_status':'tracked and untracked clean observed before first edit','files':{
                str(p.relative_to(OUT)):file_hash(p) for p in (OUT/'RUN_CONFIG.json',OUT/'SOURCE_SPAN_REFERENCE_TEMPLATE.json',
                LOCAL/'historical_requests.json',LOCAL/'historical_labels.json',LOCAL/'canonical_sections.json')},
            'rankings_executed_before_freeze':0,'network_guard':guard}
        write_json(OUT/'PRE_RANKING_FREEZE.json',freeze)
    print('Frozen: V0 624 chunks; exact historical 15; 8 draft probes; 548 inherited sections')

if __name__=='__main__':main()
