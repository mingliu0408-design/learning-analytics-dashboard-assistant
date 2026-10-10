"""Regenerate ignored indexes in a new lab directory, never historical results."""
from pathlib import Path
from dataclasses import asdict
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *
from utils.c4_rag_lab.chunking import Section,chunk_section

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--destination',required=True,help='New directory below this lab local_artifacts')
    p.add_argument('--dense',action='store_true',help='Also run the existing local MPNet, one model at a time')
    args=p.parse_args();dest=Path(args.destination).resolve()
    if LOCAL.resolve() not in dest.parents or dest.exists():
        raise ValueError('New destination must be inside lab local_artifacts')
    with offline_guard() as guard:
        from utils.c4_rag.corpus import (load_legacy_chunks,legacy_chunk_corpus_hash,CANONICAL_CFULL_ROOT,CANONICAL_MPNET_ROOT)
        from utils.retrieval_v2.models import ManifestRecordV2
        from utils.retrieval_v2.ingestion import _extract_html,_extract_pdf,_extract_txt,_extract_python_metadata
        from transformers import AutoTokenizer
        cs=load_legacy_chunks();assert legacy_chunk_corpus_hash(cs)==V0
        sections=[]
        for line in (ROOT/'course_materials_v2/manifest.jsonl').read_text().splitlines():
            r=ManifestRecordV2.from_dict(json.loads(line))
            path=(ROOT if r.source_type=='python_metadata' else CANONICAL_CFULL_ROOT)/r.source_path
            d=_extract_html(path,r,'inherited_html') if r.source_type in ('html','legacy_doc') else \
                {'pdf':_extract_pdf,'txt':_extract_txt,'python_metadata':_extract_python_metadata}[r.source_type](path,r)
            offset=0
            for s in d.sections:
                sections.append(Section(d.document_id,d.source_hash,COURSE,'authorised_course_local_only',s.text,
                    offset,tuple(s.section_path),s.week,s.assessment_part,d.material_type,s.source_url,s.page_number))
                offset+=len(s.text)
        dest.mkdir(parents=True)
        write_json(dest/'v0_chunks.json',[asdict(c) for c in cs])
        write_json(dest/'canonical_sections.json',[asdict(s) for s in sections])
        frozen=json.loads((OUT/'PRE_RANKING_FREEZE.json').read_text())
        assert file_hash(dest/'canonical_sections.json')==frozen['files']['local_artifacts/canonical_sections.json']
        tok=AutoTokenizer.from_pretrained(str(CANONICAL_MPNET_ROOT),local_files_only=True,trust_remote_code=False)
        cfg=json.loads((OUT/'RUN_CONFIG.json').read_text())
        for size in cfg['chunk_windows']:
            index=[]
            for n,s in enumerate(sections):
                index.extend({'chunk_id':c.chunk_id,'section_index':n,'parent_id':c.parent_id,'spans':c.spans,
                    'absolute_spans':c.absolute_spans,'body_tokens':c.body_tokens,'metadata_tokens':c.metadata_tokens,
                    'previous_id':c.previous_id,'next_id':c.next_id,'model_tokens':c.model_tokens,'text_sha256':digest(c.text.encode())}
                    for c in chunk_section(s,tok,size,cfg['overlap_tokens']))
            write_json(dest/f'v1a_{size}_index.json',index)
        if args.dense:
            from utils.c4_rag_lab.neural import LocalNeural,serialise_v0
            import numpy as np
            model=LocalNeural(CANONICAL_MPNET_ROOT,'mpnet')
            matrix=model.encode([serialise_v0(c) for c in cs],[c.chunk_id for c in cs])
            np.save(dest/'mpnet_v0_vectors.npy',matrix,allow_pickle=False)
            write_json(dest/'mpnet_token_audit.json',model.audit)
            del model
        write_json(dest/'REGENERATION_MANIFEST.json',{'V0':V0,'dense_requested':args.dense,
            'files':{f.name:file_hash(f) for f in dest.iterdir() if f.is_file()},'network_guard':guard,
            'historical_diagnostics_rerun':False})
    print(str(dest))

if __name__=='__main__':main()
