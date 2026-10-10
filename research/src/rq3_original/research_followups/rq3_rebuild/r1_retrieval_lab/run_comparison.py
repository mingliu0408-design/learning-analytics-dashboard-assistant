"""One fixed V0 comparison; outputs are exposed development diagnostics only."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
import csv
import gc
import json
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *
from utils.c4_rag_lab.retrieval import RetrievalLab,SearchInput
from utils.c4_rag_lab.neural import LocalNeural,serialise_v0
from utils.c4_rag_lab.evaluation import reference_id_metrics,reviewed_span_metrics,assemble_v0

def main():
    config=json.loads((OUT/'RUN_CONFIG.json').read_text())
    freeze=json.loads((OUT/'PRE_RANKING_FREEZE.json').read_text())
    for name,h in freeze['files'].items():assert file_hash(OUT/name)==h
    latest=sorted(OUT.glob('TEST_ATTEMPT_*.json'))[-1]
    assert json.loads(latest.read_text())['passed']
    with (OUT/'COMPARISON_EXECUTION.json').open('x') as f:
        json.dump({'status':'STARTED_DO_NOT_REPEAT','started_utc':datetime.now(timezone.utc).isoformat(),
            'config_sha256':file_hash(OUT/'RUN_CONFIG.json'),'input_freeze_sha256':file_hash(OUT/'PRE_RANKING_FREEZE.json'),
            'code_sha256':{str(p.relative_to(ROOT)):file_hash(p) for p in sorted((ROOT/'utils/c4_rag_lab').glob('*.py'))}},f,indent=2)
    with offline_guard() as guard:
        from utils.c4_rag.corpus import load_legacy_chunks,legacy_chunk_corpus_hash,CANONICAL_MPNET_ROOT
        from transformers import AutoTokenizer
        import numpy as np
        chunks=load_legacy_chunks();assert legacy_chunk_corpus_hash(chunks)==V0
        lab=RetrievalLab(chunks,config); allowed=frozenset(c.source_file for c in chunks)
        requests=json.loads((LOCAL/'historical_requests.json').read_text())
        labels={r['id']:r for r in json.loads((LOCAL/'historical_labels.json').read_text())}
        reqs={r['id']:SearchInput(r['query'],r['page'],COURSE,allowed,mode='retriever_only') for r in requests}
        docs={c.chunk_id:c.source_file for c in chunks}
        tokenizer=AutoTokenizer.from_pretrained(str(CANONICAL_MPNET_ROOT),local_files_only=True,trust_remote_code=False)
        rows=[]; results={}; cost={}
        def record(sid,result,extra_ms=0):
            ids=[i for i,_ in result.ranked]
            metrics=reference_id_metrics(ids,labels[sid]['reference_ids'],docs)
            row={'case_id':sid,'candidate':result.candidate,'searched':result.searched,'scored_chunks':result.scored_chunks,
                'query_sha256':digest(reqs[sid].effective_query.encode()),'input_identity':result.input_identity,
                'namespace':'EXPOSED_15_DEVELOPMENT','status':result.status,'latency_ms':result.latency_ms+extra_ms,
                'ranked_ids':ids,'scores':[s for _,s in result.ranked],'pool_sha256':digest(canonical(result.candidate_pool)),
                'pool_count':len(result.candidate_pool),'native_returned_ids':result.native_returned,**metrics,
                'context':assemble_v0(ids[:5],lab.by_id,tokenizer,config['context_budget']),
                'support_metrics':reviewed_span_metrics([],None),
                'score_semantics':{'A_R0':'native weighted lexical','B_BM25':'weighted BM25','C_HYBRID':'weighted RRF',
                    'D_CROSS_ENCODER':'raw pair logit, not support probability'}[result.candidate]}
            rows.append(row);results[(sid,result.candidate)]=result
        for candidate in ('A_R0','B_BM25'):
            for sid,req in reqs.items():record(sid,lab.search(candidate,req))
            write_json(OUT/f'{candidate}_DIAGNOSTICS.json',[r for r in rows if r['candidate']==candidate])
            print(candidate,'15 cases complete',flush=True)
        # Neural phases run serially. Corpus and query vectors persist only in ignored lab storage.
        start=time.perf_counter(); model=LocalNeural(CANONICAL_MPNET_ROOT,'mpnet')
        cost['mpnet_load_ms']=(time.perf_counter()-start)*1000
        start=time.perf_counter()
        matrix=model.encode([serialise_v0(c) for c in chunks],[c.chunk_id for c in chunks])
        cost['mpnet_corpus_encode_ms']=(time.perf_counter()-start)*1000
        assert matrix.shape==(624,768) and np.isfinite(matrix).all()
        assert np.allclose(np.linalg.norm(matrix,axis=1),1,atol=1e-5)
        np.save(LOCAL/'mpnet_v0_vectors.npy',matrix,allow_pickle=False)
        vectors={}
        for sid,req in reqs.items():
            start=time.perf_counter();q=model.encode([req.effective_query],[sid])[0]
            dense=matrix@q; elapsed=(time.perf_counter()-start)*1000
            vectors[sid]=q
            c=lab.search('C_HYBRID',req,dense_scores=dict(zip((x.chunk_id for x in chunks),dense.tolist())))
            record(sid,c,elapsed)
        np.savez(LOCAL/'mpnet_query_vectors.npz',**vectors)
        mpnet_audit=model.audit
        for r in mpnet_audit:
            if r['id'] in lab.by_id:
                c=lab.by_id[r['id']]
                r['body_tokens']=len(model.tokenizer(c.text,add_special_tokens=False)['input_ids'])
                r['metadata_tokens']=len(model.tokenizer(serialise_v0(c)[:-len(c.text)] if c.text else serialise_v0(c),add_special_tokens=False)['input_ids'])
        write_json(OUT/'MPNET_TOKEN_AUDIT.json',mpnet_audit)
        write_json(OUT/'C_HYBRID_DIAGNOSTICS.json',[r for r in rows if r['candidate']=='C_HYBRID'])
        write_json(OUT/'DENSE_INDEX_MANIFEST.json',{'V0':V0,'shape':list(matrix.shape),'dtype':str(matrix.dtype),
            'vector_sha256':file_hash(LOCAL/'mpnet_v0_vectors.npy'),'row_ids_sha256':digest(canonical([c.chunk_id for c in chunks])),
            'unit_norm_verified':True,'model_identity_sha256':file_hash(OUT/'MODEL_RUNTIME_IDENTITY.json'),
            'normalisation':'mean pooling, unit L2','serialized_input_sha256':digest(canonical([serialise_v0(c) for c in chunks]))})
        del model; gc.collect()
        print('C_HYBRID real MPNet: corpus + 15 queries complete; model released',flush=True)
        start=time.perf_counter();model=LocalNeural(CE_ROOT,'cross_encoder')
        cost['cross_encoder_load_ms']=(time.perf_counter()-start)*1000
        for sid,req in reqs.items():
            c=results[(sid,'C_HYBRID')];pool=[i for i,_ in c.ranked[:config['rerank_depth']]]
            start=time.perf_counter()
            scores=model.score_pairs(req.effective_query,[serialise_v0(lab.by_id[i]) for i in pool],
                                     [sid+'::'+i for i in pool])
            # Stable case+chunk audit IDs; candidate interface receives original IDs.
            scores={i:scores[sid+'::'+i] for i in pool}
            elapsed=(time.perf_counter()-start)*1000
            d=lab.search('D_CROSS_ENCODER',req,hybrid=c,cross_scores=scores)
            assert set(d.candidate_pool)==set(pool) and len(d.ranked)==len(pool)
            record(sid,d,elapsed+next(r['latency_ms'] for r in rows if r['case_id']==sid and r['candidate']=='C_HYBRID'))
        write_json(OUT/'CROSS_ENCODER_TOKEN_AUDIT.json',model.audit)
        write_json(OUT/'D_CROSS_ENCODER_DIAGNOSTICS.json',[r for r in rows if r['candidate']=='D_CROSS_ENCODER'])
        del model;gc.collect()
        print('D_CROSS_ENCODER: 450 real query/passage pairs complete',flush=True)
        # Corrected baseline parity against saved R0 21-case diagnostic, no P3 execution.
        csvpath=ROOT/'research_followups/rq3_rebuild/r0_single_gate/EXPOSED_21_CASE_GATE_DIAGNOSTIC.csv'
        saved=list(csv.DictReader(csvpath.open()))
        inp=ROOT/'evaluation/rq3_real_c4/i0_integration/c4_real_p3_route_input_manifest_v1.jsonl'
        prior=json.loads((ROOT/'research_followups/rq3_rebuild/r0_single_gate/SOURCE_MANIFEST.json').read_text())
        expected=[r['sha256'] for r in prior['files'] if r['path'].endswith('/'+str(inp.relative_to(ROOT)))]
        assert len(expected)==1 and file_hash(inp)==expected[0]
        data={r['scenario_id']:r for r in map(json.loads,inp.read_text().splitlines())}
        parity=[]
        for old in saved:
            sid=old['scenario_id'];v=data[sid]['semantic_input']
            req=SearchInput(v['current_query'],v['current_page'],COURSE,allowed,mode='deployment',p3_required=True)
            assert digest(req.effective_query.encode())==old['raw_query_sha256']
            r=lab.search('A_R0',req)
            old_ids=old['new_source_ids'].split('|') if old['new_source_ids'] else []
            parity.append({'case_id':sid,'same_ids':r.native_returned==old_ids,'same_status':r.status==old['new_status'],
                'searched':r.searched,'status':r.status,'selected_ids':r.native_returned})
        write_json(OUT/'R0_21_BASELINE_REPRODUCTION.json',{'cases':parity,'saved_table_sha256':file_hash(csvpath),
            'input_sha256':file_hash(inp),'p3_rerun':False,'all_match':all(r['same_ids'] and r['same_status'] for r in parity)})
        # P3 numeric controls exercise the shared gate with no search/model calls.
        controls=[]
        for candidate in ('A_R0','B_BM25','C_HYBRID','D_CROSS_ENCODER'):
            r=lab.search(candidate,SearchInput('How many Dashboard views did I make?','overview',COURSE,allowed))
            assert not r.searched and r.scored_chunks==0
            controls.append({'candidate':candidate,'searched':r.searched,'status':r.status})
        summary={}
        for candidate in ('A_R0','B_BM25','C_HYBRID','D_CROSS_ENCODER'):
            rr=[r for r in rows if r['candidate']==candidate];positive=[r for r in rr if r['reference_count']]
            summary[candidate]={'status':'ACTUALLY_RUN','cases':len(rr),'reference_positive_cases':len(positive),
                **{k:statistics.mean(r[k] for r in positive) for k in ('recall_at_1','recall_at_3','recall_at_5','mrr_at_5','document_hit_at_5')},
                'empty_reference_nonempty_proxy':sum(r['empty_reference_nonempty_proxy'] is True for r in rr),
                'latency_ms_median':statistics.median(r['latency_ms'] for r in rr),
                'native_status_counts':dict(Counter(r['status'] for r in rr)),
                'semantic_sufficiency_metric':None,'deployment_ready':False}
        changes=[]
        for sid in reqs:
            base=next(r for r in rows if r['case_id']==sid and r['candidate']=='A_R0')
            for c in ('B_BM25','C_HYBRID','D_CROSS_ENCODER'):
                r=next(r for r in rows if r['case_id']==sid and r['candidate']==c)
                delta=None if base['recall_at_5'] is None else r['recall_at_5']-base['recall_at_5']
                changes.append({'case_id':sid,'candidate':c,'reference_id_recall5_delta_vs_A':delta,
                    'taxonomy':'EMPTY_REFERENCE_REQUIRES_REVIEW' if delta is None else 'GAIN' if delta>0 else 'REGRESSION' if delta<0 else 'TIE',
                    'sufficiency':'NOT_ESTABLISHED','reference_version':'EXACT_HASH_MATCH'})
        with (OUT/'EXPOSED_CASE_ERROR_TAXONOMY.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,lineterminator='\n',fieldnames=list(changes[0]));w.writeheader();w.writerows(changes)
        write_json(OUT/'FIXED_CORPUS_DIAGNOSTIC_SUMMARY.json',{'corpus':V0,'candidates':summary,
            'costs':cost,'p3_false_controls':controls,'network_guard':guard,'history_input':False,'gold_input':False,
            'definition':'macro reference-ID recall/MRR@5 on 13 nonempty historical reference cases BEFORE abstention',
            'empty_reference_note':'2 empty historical reference cases; nonempty retrieval is a proxy, not a verified false-positive label',
            'latency_note':'CPU warm query/ranking timing; D includes C query cost; corpus encode/model load reported separately; no service SLA',
            'support_metrics':reviewed_span_metrics([],None),'models_executed_serially':True,
            'real_pair_count':450,'no_generator_or_judge_calls':True})
        execution=json.loads((OUT/'COMPARISON_EXECUTION.json').read_text())
        execution.update(status='COMPLETED',finished_utc=datetime.now(timezone.utc).isoformat(),network_guard=guard)
        write_json(OUT/'COMPARISON_EXECUTION.json',execution)
        print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
