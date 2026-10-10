"""Rechunk unchanged inherited canonical extraction. No retrieval or model inference."""
from pathlib import Path
from dataclasses import asdict
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *
from utils.c4_rag_lab.chunking import Section, chunk_section, coverage

def main():
    with offline_guard() as guard:
        from transformers import AutoTokenizer
        from utils.c4_rag.corpus import CANONICAL_MPNET_ROOT
        tok=AutoTokenizer.from_pretrained(str(CANONICAL_MPNET_ROOT),local_files_only=True,trust_remote_code=False)
        config=json.loads((OUT/'RUN_CONFIG.json').read_text())
        raw=json.loads((LOCAL/'canonical_sections.json').read_text())
        sections=[Section(**{**s,'ancestry':tuple(s['ancestry']),'blocks':()}) for s in raw]
        report={'identity':'V1a_INHERITED_CANONICAL_EXTRACTION','raw_source_completeness':'EXTRACTION_UNVERIFIED',
            'not_comparable_to_V0_as_chunk_size_only':True,'tokenizer':'actual all-mpnet-base-v2 immutable local tokenizer',
            'coverage_unit':'all canonical Unicode characters including whitespace','versions':{}}
        index_manifest={}
        for size in config['chunk_windows']:
            rows=[]; index=[]; errors=[]
            for n,s in enumerate(sections):
                try:
                    chunks=chunk_section(s,tok,size,config['overlap_tokens'])
                    rows.append({'section_index':n,'document_id':s.document_id,'base_offset':s.base_offset,
                                 **coverage(s,chunks)})
                    index.extend({'chunk_id':c.chunk_id,'parent_id':c.parent_id,'section_index':n,
                        'spans':c.spans,'absolute_spans':c.absolute_spans,'body_tokens':c.body_tokens,
                        'metadata_tokens':c.metadata_tokens,'model_tokens':c.model_tokens,
                        'previous_id':c.previous_id,'next_id':c.next_id,'text_sha256':digest(c.text.encode())} for c in chunks)
                except ValueError as exc:
                    errors.append({'section_index':n,'document_id':s.document_id,'error':str(exc),'characters':len(s.text)})
            path=LOCAL/f'v1a_{size}_index.json'
            write_json(path,index)
            totals={k:sum(r[k] for r in rows) for k in ('canonical_characters','covered_characters','missing_characters','overlap_characters','chunks')}
            totals['unprocessed_characters']=sum(e['characters'] for e in errors)
            report['versions'][str(size)]={'totals':totals,'sections':rows,'errors':errors,
                'actual_model_tokens_max':max((c['model_tokens'] for c in index),default=0),
                'body_truncation_tokens':0,'metadata_truncation_tokens':0}
            index_manifest[str(size)]={'index_sha256':file_hash(path),'chunks':len(index),
                'canonical_sections_sha256':file_hash(LOCAL/'canonical_sections.json'),'source_text_in_review_zip':False}
        report['network_guard']=guard
        write_json(OUT/'CHUNK_SOURCE_COVERAGE_AUDIT.json',report)
        write_json(OUT/'V1A_INDEX_MANIFEST.json',index_manifest)
        print(json.dumps({k:{'totals':v['totals'],'errors':len(v['errors']),'max_tokens':v['actual_model_tokens_max']} for k,v in report['versions'].items()},indent=2))
        if any(v['errors'] or v['totals']['missing_characters'] for v in report['versions'].values()):
            raise RuntimeError('CHUNK_COVERAGE_INCOMPLETE')

if __name__=='__main__':main()
