"""Resume only failed D in verified float64 CPU runtime. Never reruns saved A/B/C."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import csv
import json
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *
from utils.c4_rag_lab.retrieval import RetrievalLab,SearchInput,SearchResult
from utils.c4_rag_lab.neural import LocalNeural,serialise_v0
from utils.c4_rag_lab.evaluation import reference_id_metrics,reviewed_span_metrics,assemble_v0

def main():
    freeze=json.loads((OUT/'PRE_RANKING_FREEZE.json').read_text())
    for name,h in freeze['files'].items():assert file_hash(OUT/name)==h
    config=json.loads((OUT/'RUN_CONFIG.json').read_text())
    rows=[]
    for c in ('A_R0','B_BM25','C_HYBRID'):
        data=json.loads((OUT/f'{c}_DIAGNOSTICS.json').read_text());assert len(data)==15
        rows+=data
    assert not (OUT/'D_CROSS_ENCODER_DIAGNOSTICS.json').exists()
    initial=json.loads((OUT/'COMPARISON_EXECUTION.json').read_text())
    with (OUT/'D_COMPATIBILITY_RETRY_MANIFEST.json').open('x') as f:
        json.dump({'status':'FROZEN_BEFORE_RETRY','time_utc':datetime.now(timezone.utc).isoformat(),
            'config_sha256':file_hash(OUT/'RUN_CONFIG.json'),'dtype_override':'float64','attention_override':'eager',
            'reason':'CPU float32 yields NaN in first query projection, including synthetic short input; weights finite. Float64 synthetic probe finite.',
            'selection_by_retrieval_success':False,'new_downloads':0,'model_or_weight_training':False,
            'same_model_revision':CE_REVISION,'same_queries_and_exact_C_top30':True,'ABC_rerun':False,
            'saved_ABC_hashes':{c:file_hash(OUT/f'{c}_DIAGNOSTICS.json') for c in ('A_R0','B_BM25','C_HYBRID')},
            'neural_code_sha256':file_hash(ROOT/'utils/c4_rag_lab/neural.py')},f,indent=2)
    with offline_guard() as guard:
        from utils.c4_rag.corpus import load_legacy_chunks,legacy_chunk_corpus_hash,CANONICAL_MPNET_ROOT
        from transformers import AutoTokenizer
        chunks=load_legacy_chunks();assert legacy_chunk_corpus_hash(chunks)==V0
        lab=RetrievalLab(chunks,config);allowed=frozenset(c.source_file for c in chunks)
        reqs={r['id']:SearchInput(r['query'],r['page'],COURSE,allowed,mode='retriever_only')
              for r in json.loads((LOCAL/'historical_requests.json').read_text())}
        labels={r['id']:r for r in json.loads((LOCAL/'historical_labels.json').read_text())}
        docs={c.chunk_id:c.source_file for c in chunks}
        tok=AutoTokenizer.from_pretrained(str(CANONICAL_MPNET_ROOT),local_files_only=True,trust_remote_code=False)
        start=time.perf_counter();model=LocalNeural(CE_ROOT,'cross_encoder',dtype='float64',attention='eager')
        cost={'cross_encoder_load_ms':(time.perf_counter()-start)*1000,
              'mpnet_corpus_encode_ms':None,'mpnet_load_ms':None,
              'missing_timing_reason':'initial process failed before persisting one-time build/load timings; saved C query timings preserved'}
        smoke=model.score_pairs('What color is the synthetic cube?',
            ['The synthetic cube is blue.','An unrelated train stops at the station.'],['SYNTHETIC_RELEVANT','SYNTHETIC_OTHER'])
        assert all(__import__('math').isfinite(v) for v in smoke.values()) and smoke['SYNTHETIC_RELEVANT']>smoke['SYNTHETIC_OTHER']
        write_json(OUT/'CROSS_ENCODER_FLOAT64_SMOKE.json',{'synthetic_only':True,'scores':smoke,'passed':True})
        model.audit=[]
        for sid,req in reqs.items():
            c=next(r for r in rows if r['case_id']==sid and r['candidate']=='C_HYBRID')
            assert c['input_identity']==req.identity
            pool=c['ranked_ids'][:config['rerank_depth']]
            hybrid=SearchResult('C_HYBRID',req.identity,ranked=list(zip(c['ranked_ids'],c['scores'])))
            start=time.perf_counter()
            scores=model.score_pairs(req.effective_query,[serialise_v0(lab.by_id[i]) for i in pool],[sid+'::'+i for i in pool])
            scores={i:scores[sid+'::'+i] for i in pool}
            ce_ms=(time.perf_counter()-start)*1000
            result=lab.search('D_CROSS_ENCODER',req,hybrid=hybrid,cross_scores=scores)
            ids=[i for i,_ in result.ranked]
            assert set(ids)==set(pool) and len(ids)==len(pool)
            row={'case_id':sid,'candidate':'D_CROSS_ENCODER','searched':True,'scored_chunks':len(pool),
                'query_sha256':digest(req.effective_query.encode()),'input_identity':req.identity,
                'namespace':'EXPOSED_15_DEVELOPMENT','status':result.status,
                'latency_ms':c['latency_ms']+ce_ms+result.latency_ms,'ce_pair_scoring_ms':ce_ms,
                'ranked_ids':ids,'scores':[s for _,s in result.ranked],'pool_sha256':digest(canonical(pool)),
                'pool_count':len(pool),'candidate_pool_ids':pool,'native_returned_ids':[],
                **reference_id_metrics(ids,labels[sid]['reference_ids'],docs),
                'context':assemble_v0(ids[:5],lab.by_id,tok,config['context_budget']),
                'support_metrics':reviewed_span_metrics([],None),'score_semantics':'float64 eager raw pair logit; not support probability'}
            write_json(OUT/f'D_CASE_{sid}.json',row);rows.append(row)
            print('D float64',sid,'finite pairs',len(pool),flush=True)
        write_json(OUT/'CROSS_ENCODER_TOKEN_AUDIT.json',model.audit)
        write_json(OUT/'D_CROSS_ENCODER_DIAGNOSTICS.json',[r for r in rows if r['candidate']=='D_CROSS_ENCODER'])
        del model
        import gc;gc.collect()
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
            assert digest(v['current_query'].encode())==old['raw_query_sha256']
            result=lab.search('A_R0',req)
            old_ids=old['new_source_ids'].split('|') if old['new_source_ids'] else []
            parity.append({'case_id':sid,'same_ids':result.native_returned==old_ids,'same_status':result.status==old['new_status'],
                'searched':result.searched,'status':result.status,'selected_ids':result.native_returned})
        write_json(OUT/'R0_21_BASELINE_REPRODUCTION.json',{'cases':parity,'saved_table_sha256':file_hash(csvpath),
            'input_sha256':file_hash(inp),'p3_rerun':False,'all_match':all(r['same_ids'] and r['same_status'] for r in parity)})
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
            for candidate in ('B_BM25','C_HYBRID','D_CROSS_ENCODER'):
                r=next(r for r in rows if r['case_id']==sid and r['candidate']==candidate)
                delta=None if base['recall_at_5'] is None else r['recall_at_5']-base['recall_at_5']
                changes.append({'case_id':sid,'candidate':candidate,'reference_id_recall5_delta_vs_A':delta,
                    'taxonomy':'EMPTY_REFERENCE_REQUIRES_REVIEW' if delta is None else 'GAIN' if delta>0 else 'REGRESSION' if delta<0 else 'TIE',
                    'sufficiency':'NOT_ESTABLISHED','reference_version':'EXACT_HASH_MATCH'})
        with (OUT/'EXPOSED_CASE_ERROR_TAXONOMY.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,lineterminator='\n',fieldnames=list(changes[0]));w.writeheader();w.writerows(changes)
        write_json(OUT/'FIXED_CORPUS_DIAGNOSTIC_SUMMARY.json',{'corpus':V0,'candidates':summary,
            'costs':cost,'p3_false_controls':controls,'network_guard_retry':guard,'history_input':False,'gold_input':False,
            'definition':'macro reference-ID recall/MRR@5 on 13 nonempty historical reference cases BEFORE abstention',
            'empty_reference_note':'2 empty historical reference cases; nonempty retrieval is a proxy, not a verified false-positive label',
            'latency_note':'CPU query/ranking timing; D includes C cost from saved ledger and new float64 rerank cost. No service SLA.',
            'support_metrics':reviewed_span_metrics([],None),'models_executed_serially':True,
            'accepted_real_pair_count':450,'failed_float32_pair_count':30,'no_generator_or_judge_calls':True,
            'precision_intervention':'D only: float64/eager compatibility repair frozen before successful retry; no model or query selection',
            'initial_guard':'offline_guard installed; failure interrupted final counter persistence; no network-capable inference path'})
        initial.update(status='COMPLETED_WITH_D_FLOAT64_COMPATIBILITY_RETRY',finished_utc=datetime.now(timezone.utc).isoformat(),
            continuation='finish_saved_comparison.py; original A/B/C outputs retained',retry_guard=guard)
        write_json(OUT/'COMPARISON_EXECUTION.json',initial)
        print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
