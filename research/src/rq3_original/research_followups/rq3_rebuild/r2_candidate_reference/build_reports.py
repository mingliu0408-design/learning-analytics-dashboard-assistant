"""Post-ranking old-ID metrics and human-reference-limited development report."""
from common import *
from audit_coverage import coverage_rows, summarize
import statistics

def main():
    refs={r['case_id']:r['reference_ids'] for r in read_json(OUT/'EXPOSED_REFERENCE_ID_MAPPING.json')['cases']}
    results={};per_case={};saved_inputs=[]
    for name in ('A_R0','C_HYBRID','D_CROSS_ENCODER'):
        raw=inherited(R1/f'{name}_DIAGNOSTICS.json')
        # Enough saved ranking data to recompute the audit, without old human fields.
        safe=[{k:r[k] for k in ('case_id','ranked_ids','scores','query_sha256','status','native_returned_ids')} for r in raw]
        saved_inputs.append({'candidate':name,'source_sha256':file_hash(R1/f'{name}_DIAGNOSTICS.json'),'rows':safe})
        per_case[name]=coverage_rows(safe,refs);results[name]=summarize(per_case[name])
        results[name]['execution']='SAVED_R1_NOT_RERUN'
    write_json(OUT/'SAVED_ACD_REVIEW_PROJECTION.json',saved_inputs,exclusive=True)
    rankings=read_json(OUT/'RANKINGS.json')
    audits=read_json(OUT/'PAIR_SCORES_AND_TOKEN_AUDIT.json')
    for name in ('E_R0_SEEDED','F_FIXED_UNION'):
        rows=[r for r in rankings if r['policy']==name]
        per_case[name]=coverage_rows(rows,refs);results[name]=summarize(per_case[name])
        results[name].update(execution='ACTUALLY_RUN_LOCAL_FIXED_MINILM',
            pair_scores=sum(r['new_pair_scores'] for r in rows),
            cache_reused_pair_uses=sum(r['cache_reused_pair_uses'] for r in rows),
            truncated_pairs=sum(r['truncated_tokens']>0 for r in audits if r['policy']==name),
            truncated_tokens=sum(r['truncated_tokens'] for r in audits if r['policy']==name),
            scoring_and_audit_elapsed_ms_median=statistics.median(r['scoring_and_audit_elapsed_ms'] for r in rows))
    changes=[]
    a={r['case_id']:r for r in per_case['A_R0']}
    for name in ('C_HYBRID','D_CROSS_ENCODER','E_R0_SEEDED','F_FIXED_UNION'):
        for r in per_case[name]:
            delta=None if r['recall_at_5'] is None else r['recall_at_5']-a[r['case_id']]['recall_at_5']
            changes.append({'case_id':r['case_id'],'candidate':name,'delta_recall5_vs_saved_A':delta,
                            'label':'EMPTY_OLD_REFERENCE_UNLABELLED' if delta is None else 'GAIN' if delta>0 else 'LOSS' if delta<0 else 'TIE'})
    ef_pools=read_json(OUT/'CANDIDATE_POOLS.json')
    e={p['case_id']:p['candidate_ids'] for p in ef_pools if p['policy']=='E_R0_SEEDED'}
    f={p['case_id']:p['candidate_ids'] for p in ef_pools if p['policy']=='F_FIXED_UNION'}
    overlap=sum(len(set(e[sid]) & set(f[sid])) for sid in e)
    report={'namespace':'EXPOSED_15_DEVELOPMENT_REFERENCE_ID_ONLY','candidates':results,
            'per_case':per_case,'changes_vs_A':changes,
            'E_F_same_case_shared_chunk_id_pair_uses':overlap,
            'cache_limit':'Same case/chunk ID is insufficient. Cache requires complete ordered padded input batch plus raw hashes and model/config identity. No such exact batches matched; 0 reused.',
            'fresh_test_claim':False,'significance_tests':0,'final_system_selected':False,
            'source_sufficiency_metric':None,'human_response_quality_metric':None}
    write_json(OUT/'DEV_RESULTS.json',report,exclusive=True)
    lines=['# R0-seeded reranking: exposed development results','',
           'Status: READY_FOR_RETRIEVER_DEV_SELECTION_WITH_HUMAN_REFERENCE_LIMITS. R0 remains the provisional integrated development baseline; no final system is selected.', '',
           '| Candidate | Evidence | Pool old-ID occurrences /26 | Top5 old-ID occurrences /26 | Macro Recall@5 (13) | Hit queries /13 | MRR@5 (13) |',
           '|---|---|---:|---:|---:|---:|---:|']
    for n,s in results.items():
        lines.append(f"| {n} | {s['execution']} | {s['pool_reference_occurrences']} | {s['top5_reference_occurrences']} | {s['top5_macro_query_recall']:.6f} | {s['top5_any_hit_queries']} | {s['top5_mrr']:.6f} |")
    lines += ['',
        'C pool in this table means its entire saved 50/50-fusion ranking, whereas D uses exactly C top30; see the separate candidate-pool audit for 22/26 versus 12/26. E uses A top30. F uses deterministic A/C alternation capped at 30. Both new pools contain all 26 old query-reference occurrences, so their old-ID oracle Recall@5 is 1.0; each positive query has two IDs.', '',
        'The denominator is 15 exposed development cases, of which 13 have nonempty references (two IDs each), two have empty references, and there are 17 unique IDs across cases. The 26 occurrences are not 26 independent tasks. Micro recall and macro query recall happen to coincide here; query any-hit rate and MRR are different measures.', '',
        'E top5 retains 17/26 and F 16/26, compared with saved A 25/26, C 6/26 and D 10/26. Candidate coverage alone therefore does not explain all ranking losses. These results do not measure acceptable semantic alternatives, source sufficiency, final answers, or independent human quality. They do not authorize a final winner or a production switch.', '',
        'Actual execution: 870 new finite pair logits (E 420, F 450), 30 policy-case outputs including empty E/U045, one MiniLM model/revision/config, no retries, 0 exact batch-cache reuse, 0 model downloads or package changes. A/C/D are saved outputs; MPNet, R0 retrieval and D were not rerun. There were no route, generation, Judge or human-scoring calls.', '',
        f'{overlap} same-case E/F candidate-ID overlaps are recorded, but ID overlap does not establish equal complete padded model inputs. R1 retained token lengths rather than complete padded tensors, so its 450 historical D scores were not admitted to the exact cache. The cap of 900 was not filled: U045 has no saved A ranking, so E stays empty.', '',
        'R1-compatible execution uses cross-encoder/ms-marco-MiniLM-L6-v2@233902d25c440f23af6f7d6e94d2946bac0bee0a, CPU float64/eager, batch 4, one torch thread, deterministic/eval inference, unchanged raw-strip query and inherited passage serialization, 512 total tokens and only-second truncation. E has 1 truncated pair/203 removed passage tokens; F has 2/405. The tokenizer length-audit warning concerns untruncated counting; actual input tensors are at most 512 tokens. No query exceeded 64 tokens.', '',
        'Complete query/passage text and padded tensor arrays are retained only in ignored local_artifacts/EFFECTIVE_INPUTS.jsonl (receipt with size/hash included). Review artifacts contain scores, complete candidate/ranking IDs, token counts, input hashes and cache/batch identities. This separation avoids exporting course bodies or reconstructable token arrays. Reproduction requires the authorized local sources.', '',
        'The model phase held an advisory /private/tmp/rq3-rebuild-local-inference.lock, inspected existing processes, and rechecked before each forward. No I0/model process was observed; Saveit and Telegram live-monitor processes were classified separately. No process was killed and no unfinished sibling files were read. The lock is advisory and no claim is made that I0 adopted it.', '',
        'Recorded policy timing includes tokenization, local identity writes and process checks as well as scoring; it is not a directly comparable R1 service latency or deployment SLA. Float64 CPU timing is not GPU/float32 performance. No significance testing, threshold transfer, TEST claim, calibration or final selection occurred.']
    (OUT/'R0_SEEDED_RERANKING_DEV_RESULTS.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__':
    main()
