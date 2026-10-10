"""Recover the existing generic R0 corpus locally; no query, retriever call or model."""
from pathlib import Path
from dataclasses import asdict
import json
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from build_materials import digest

def main():
    receipt=HERE/'sources/R0_CORPUS_EXPORT_RECEIPT.json'
    if receipt.exists():
        r=json.loads(receipt.read_text())
        if digest(Path(r['path']).read_bytes())!=r['sha256']:raise ValueError('EXISTING_CORPUS_EXPORT_CHANGED')
        print(json.dumps(dict(status='EXISTING_EXPORT_REUSED',count=r['count'],sha256=r['sha256'])));return
    from utils.c4_rag.corpus import load_legacy_chunks,legacy_chunk_corpus_hash
    chunks=load_legacy_chunks();out=HERE/'local_private/VERIFIED_R0_CORPUS.jsonl'
    out.parent.mkdir(exist_ok=True)
    data=''.join(json.dumps(asdict(c),ensure_ascii=False)+'\n' for c in chunks).encode()
    with out.open('xb') as f:f.write(data)
    r=dict(path=str(out),sha256=digest(data),bytes=len(data),count=len(chunks),corpus_sha256=legacy_chunk_corpus_hash(chunks),
        source_role='ACTUAL_EXISTING_COURSE_CORPUS_GENERIC_NOT_CASE_SELECTED',provider_calls=0,model_downloads=0)
    receipt.parent.mkdir(exist_ok=True);receipt.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))

if __name__=='__main__':main()
