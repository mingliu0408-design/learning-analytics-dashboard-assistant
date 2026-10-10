"""Readback invariants and tokenizer-only input replay. Never invokes a model."""
from common import *
from policies import candidate_pool, rank_scores
from types import SimpleNamespace
import csv
import math
import sys

def main():
    checks=[]
    def check(name,condition,detail=None):
        checks.append({'name':name,'passed':bool(condition),'detail':detail})
        if not condition:raise AssertionError(name)
    freeze=read_json(OUT/'POLICY_FREEZE.json')
    check('policy_freeze_unchanged',all(file_hash(OUT/n)==h for n,h in freeze['files'].items()))
    receipt=read_json(OUT/'EXECUTION_RECEIPT.json')
    check('successful_bounded_execution',receipt['status']=='COMPLETED_BOUNDED_DIAGNOSTIC' and receipt['new_pair_attempts']==receipt['new_pair_scores']==870<=900)
    code_names=('common.py','policies.py','prepare_inputs.py','run_inference.py')
    check('actual_inference_code_unchanged',all(file_hash(OUT/n)==receipt['code_sha256'][n] for n in code_names))
    check('zero_forbidden_calls',receipt['generation_calls']==receipt['judge_calls']==receipt['human_scores_created']==receipt['model_downloads']==0 and receipt['network_guard']['network_attempts']==receipt['network_guard']['forbidden_import_attempts']==receipt['reference_guard']['forbidden_data_open_attempts']==0)
    check('pre_inference_tests_passed',read_json(OUT/'TEST_RESULTS.json')['passed'] and read_json(OUT/'TEST_RESULTS.json')['tests_run']==29)
    source=read_json(OUT/'INFERENCE_SOURCE_MANIFEST.json')['sources']
    check('inference_inputs_model_code_hashes_unchanged',all(Path(p['path']).stat().st_size==p['bytes'] and file_hash(p['path'])==p['sha256'] for p in source),len(source))
    ledger_path=Path(receipt['local_effective_inputs']['path'])
    check('complete_local_input_ledger_hash',file_hash(ledger_path)==receipt['local_effective_inputs']['sha256'])
    ledger=[json.loads(line) for line in ledger_path.read_text().splitlines()]
    audits=read_json(OUT/'PAIR_SCORES_AND_TOKEN_AUDIT.json')
    audit_by_batch={}
    for r in audits:audit_by_batch.setdefault(r['batch_id'],[]).append(r)
    check('actual_pair_records_complete',len(audits)==870 and len({(r['policy'],r['case_id'],r['chunk_id']) for r in audits})==870)
    sys.path.insert(0,str(ROOT))
    from utils.c4_rag_lab.common import offline_guard
    with offline_guard() as network:
        from transformers import AutoTokenizer
        from utils.c4_rag_lab.neural import serialise_v0
        model_root=Path(read_json(R1/'MODEL_RUNTIME_IDENTITY.json')['cross_encoder']['local_path'])
        tokenizer=AutoTokenizer.from_pretrained(str(model_root),local_files_only=True,trust_remote_code=False)
        chunks=read_json(r1_local()/'v0_chunks.json');by_id={c['chunk_id']:SimpleNamespace(**c) for c in chunks}
        reqs={r['id']:r['query'].strip() for r in read_json(r1_local()/'historical_requests.json')}
        token_ok=True;identity_ok=True;serialization_ok=True;length_ok=True
        for batch in ledger:
            policy,sid,offset=batch['batch_id'].split('::')
            raw=[{'query_sha256':digest(batch['query'].encode()),'passage_sha256':digest(p.encode())} for p in batch['passages']]
            identity_ok &= batch['identity']==batch_identity(receipt['model_config_identity'],raw,batch['tensors'])
            serialization_ok &= batch['query']==reqs[sid] and batch['passages']==[serialise_v0(by_id[i]) for i in batch['chunk_ids']]
            replay=dict(tokenizer([batch['query']]*len(batch['passages']),batch['passages'],padding=True,truncation='only_second',max_length=512))
            token_ok &= replay==batch['tensors']
            for j,r in enumerate(audit_by_batch[batch['batch_id']]):
                tensor_row={k:v[j] for k,v in batch['tensors'].items()}
                identity_ok &= r['effective_tensor_row_sha256']==digest(canonical(tensor_row)) and r['batch_identity']==batch['identity'] and r['query_sha256']==raw[j]['query_sha256'] and r['passage_sha256']==raw[j]['passage_sha256']
                full=tokenizer(batch['query'],batch['passages'][j],truncation=False)['input_ids']
                length_ok &= r['untruncated_tokens']==len(full) and r['model_tokens']==sum(tensor_row['attention_mask']) and r['model_tokens']<=r['padded_tokens']<=512 and r['query_tokens']<=64 and r['truncated_tokens']==max(0,len(full)-512)
        check('exact_query_passage_serialization_replayed',serialization_ok)
        check('complete_tokenizer_tensors_replayed_without_model',token_ok,{'batches':len(ledger),'pairs':len(audits),'new_scores':0})
        check('batch_and_pair_input_identities',identity_ok)
        check('actual_token_truncation_limits',length_ok)
        check('validation_zero_network',network['network_attempts']==network['forbidden_import_attempts']==0)
    cache=[json.loads(line) for line in (OUT/'CACHE_RECEIPTS.jsonl').read_text().splitlines()]
    journal=[json.loads(line) for line in (OUT/'EXECUTION_JOURNAL.jsonl').read_text().splitlines()]
    reserved=[r for r in journal if r['state']=='RESERVED_BEFORE_FORWARD']
    committed=[r for r in journal if r['state']=='FINITE_SCORES_COMMITTED']
    check('durable_score_reservations_and_results',len(reserved)==len(committed)==len(ledger) and sum(r['pairs'] for r in reserved)==870 and all(math.isfinite(s) for r in committed for s in r['scores']))
    score_map={r['batch_id']:dict(zip(r['chunk_ids'],r['scores'])) for r in committed}
    check('pair_audit_matches_executed_logits',all(r['score']==score_map[r['batch_id']][r['chunk_id']] for r in audits))
    check('cache_claims_match_complete_batch_identities',len(cache)==len(ledger) and not any(r['cache_hit'] for r in cache) and len({r['identity'] for r in cache})==len(cache))
    resources=[json.loads(line) for line in (OUT/'RESOURCE_RECHECKS.jsonl').read_text().splitlines()]
    check('process_recheck_preceded_every_forward',len(resources)==len(reserved) and [r['batch_id'] for r in resources]==[r['batch_id'] for r in reserved] and not any(p['blocks_inference'] for r in resources for p in r['processes']))
    pools={(r['policy'],r['case_id']):r for r in read_json(OUT/'CANDIDATE_POOLS.json')}
    ranks=read_json(OUT/'RANKINGS.json');consistent=True
    for r in ranks:
        p=pools[(r['policy'],r['case_id'])]
        scores={a['chunk_id']:a['score'] for a in audits if a['case_id']==r['case_id'] and a['policy']==r['policy']}
        consistent &= r['candidate_ids']==p['candidate_ids'] and rank_scores(p['candidate_ids'],scores)==r['ranked_ids'] and r['top5_ids']==r['ranked_ids'][:5]
    check('all_thirty_rankings_derive_from_frozen_pools_and_logits',len(ranks)==30 and consistent)
    # Independent arithmetic, without the reporting helper.
    refs={r['case_id']:set(r['reference_ids']) for r in read_json(OUT/'EXPOSED_REFERENCE_ID_MAPPING.json')['cases']}
    recomputed={}
    for name in ('E_R0_SEEDED','F_FIXED_UNION'):
        rows=[r for r in ranks if r['policy']==name]
        hits=[len(set(r['ranked_ids'][:5]) & refs[r['case_id']]) for r in rows if refs[r['case_id']]]
        recomputed[name]={'hits':sum(hits),'macro':sum(h/2 for h in hits)/13}
    saved=read_json(OUT/'DEV_RESULTS.json')['candidates']
    check('E_F_metrics_independently_recomputed',all(v['hits']==saved[n]['top5_reference_occurrences'] and v['macro']==saved[n]['top5_macro_query_recall'] for n,v in recomputed.items()),recomputed)
    blank=read_json(OUT/'BLANK_SOURCE_FACT_REVIEW.json')['rows']
    fields=['required_proposition','original_document_locator','original_span','original_extraction_correct',
            'sufficient_body_for_proposition','wrong_week_or_version','reviewer_id','review_date','review_status','human_notes']
    csv_rows=list(csv.DictReader((OUT/'BLANK_SOURCE_FACT_REVIEW.csv').open()))
    check('human_fact_fields_actually_blank',len(blank)==26 and all(r[k] is None for r in blank for k in fields) and all(not r['acceptable_alternative_evidence'] and not r['reviewed_chunk_spans'] for r in blank) and len(csv_rows)==26 and all(r[k]=='' for r in csv_rows for k in fields))
    source_audit=read_json(OUT/'SOURCE_READINESS_AUDIT.json')
    check('six_original_source_hashes_verified',source_audit['source_count']==6 and all(r['exists'] and r['hash_match'] and file_hash(r['source_path'])==r['sha256'] for r in source_audit['sources']))
    changed=subprocess.check_output(['git','diff','--name-only',BASE],text=True).splitlines()
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],text=True).splitlines()
    prefix=str(OUT.relative_to(ROOT))+'/'
    check('only_authorized_new_task_paths',all(p.startswith(prefix) for p in changed+untracked))
    outside=subprocess.check_output(['git','diff',BASE,'--','.',f':(exclude){prefix}'],text=True)
    check('inherited_tracked_tree_preserved',not outside)
    write_json(OUT/'DELIVERY_VALIDATION.json',{'time_utc':now(),'passed':all(r['passed'] for r in checks),
        'check_count':len(checks),'checks':checks,'new_model_scores':0,'tokenizer_only_pairs_replayed':870,
        'scope':'Artifact, source/hash, tokenization and blank-field checks; not human source relevance or original extraction validation'})
    print(json.dumps({'passed':True,'checks':len(checks),'new_model_scores':0,'tokenizer_only_pairs_replayed':870}))

if __name__=='__main__':
    main()
