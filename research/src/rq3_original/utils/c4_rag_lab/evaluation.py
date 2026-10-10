"""Retrieval engineering metrics, kept outside all candidate implementations."""
from .common import digest
from .chunking import ntokens
from .neural import serialise_v0

def reference_id_metrics(ranked_ids, reference_ids, document_by_id):
    gold=set(reference_ids)
    if not gold:
        return {'reference_count':0,'recall_at_1':None,'recall_at_3':None,'recall_at_5':None,
                'mrr_at_5':None,'document_hit_at_5':None,'empty_reference_nonempty_proxy':bool(ranked_ids[:5])}
    first=next((n for n,i in enumerate(ranked_ids[:5],1) if i in gold),None)
    docs={document_by_id[i] for i in gold}
    return {'reference_count':len(gold),**{f'recall_at_{k}':len(set(ranked_ids[:k])&gold)/len(gold) for k in (1,3,5)},
            'mrr_at_5':1/first if first else 0,'document_hit_at_5':bool({document_by_id[i] for i in ranked_ids[:5]}&docs),
            'empty_reference_nonempty_proxy':None}

def reviewed_span_metrics(retrieved, reference):
    """Only independently reviewed source spans/facts can produce support metrics.

    Spans are tuples (document_id, source_hash, start, end), half-open Unicode offsets.
    Each fact is conjunctive over its required spans. Coverage is not a semantic judge.
    """
    if not reference or reference.get('review_status')!='INDEPENDENTLY_REVIEWED':
        return {'span_recall':None,'required_fact_coverage':None,'unsupported_result':None,
                'reason':'INDEPENDENT_SOURCE_SPAN_AND_FACT_REFERENCES_MISSING'}
    def covered(span):
        doc,h,a,b=span
        intervals=sorted((max(a,x),min(b,y)) for d,s,x,y in retrieved if d==doc and s==h and x<b and y>a)
        end=a
        for x,y in intervals:
            if x>end:return False
            end=max(end,y)
        return end>=b
    spans=reference.get('spans',[]); facts=reference.get('facts',[])
    fact_values=[all(covered(s) for s in f['required_spans']) for f in facts if f.get('required_spans')]
    return {'span_recall':sum(covered(s) for s in spans)/len(spans) if spans else None,
        'required_fact_coverage':sum(fact_values)/len(fact_values) if fact_values else None,
        'unsupported_result':bool(retrieved) if reference.get('answerability')=='unanswerable' else None}

def assemble_v0(ids, by_id, tokenizer, budget):
    """Common local diagnostic context only; does not generate or declare support."""
    kept=[]; dropped=[]; provenance={}; used=0
    for ident in ids:
        c=by_id[ident]; fp=digest(c.text.encode())
        if fp in provenance:
            provenance[fp].append(ident)
            continue
        tokens=ntokens(tokenizer,serialise_v0(c),True)
        if used+tokens>budget:
            dropped.append({'id':ident,'reason':'WHOLE_CHUNK_EXCEEDS_REMAINING_CONTEXT_BUDGET','tokens':tokens})
            continue
        provenance[fp]=[ident]; kept.append(ident);used+=tokens
    return {'kept_ids':kept,'dropped':dropped,'tokens':used,'duplicate_provenance':provenance,
        'retrieved_duplicate_rate':1-len({digest(by_id[i].text.encode()) for i in ids})/len(ids) if ids else 0,
        'assembled_duplicate_rate':0,'body_truncation':0,'context_kind':'LOCAL_DIAGNOSTIC_NOT_GENERATION_REQUEST'}
