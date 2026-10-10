"""Read-only old-reference engineering audit, separate from policy and inference."""
from common import *

def coverage_rows(rankings, refs):
    rows = []
    for r in rankings:
        ref = set(refs[r['case_id']])
        ids = r['ranked_ids']
        if len(ids) != len(set(ids)):
            raise ValueError('DUPLICATE_RANKED_ID')
        n = len(ref)
        hit_ids = [i for i in ids[:5] if i in ref]
        pool_ids = [i for i in ids if i in ref]
        rows.append({'case_id': r['case_id'], 'reference_count': n,
                     'candidate_count': len(ids), 'candidate_reference_ids': pool_ids,
                     'top5_reference_ids': hit_ids, 'candidate_reference_occurrences': len(pool_ids),
                     'top5_reference_occurrences': len(hit_ids),
                     'candidate_recall': len(pool_ids)/n if n else None,
                     'recall_at_5': len(hit_ids)/n if n else None,
                     'oracle_recall_at_5': min(5,len(pool_ids))/n if n else None,
                     'mrr_at_5': next((1/(k+1) for k,i in enumerate(ids[:5]) if i in ref),0) if n else None})
    return rows

def summarize(rows):
    positive = [r for r in rows if r['reference_count']]
    total = sum(r['reference_count'] for r in positive)
    pool = sum(r['candidate_reference_occurrences'] for r in positive)
    top5 = sum(r['top5_reference_occurrences'] for r in positive)
    return {'query_count':len(rows), 'reference_positive_queries':len(positive),
            'empty_reference_queries':len(rows)-len(positive),
            'reference_occurrences':total, 'pool_reference_occurrences':pool,
            'pool_micro_recall':pool/total if total else None,
            'pool_macro_query_recall':sum(r['candidate_recall'] for r in positive)/len(positive) if positive else None,
            'pool_any_hit_queries':sum(r['candidate_reference_occurrences']>0 for r in positive),
            'pool_no_hit_case_ids':[r['case_id'] for r in positive if not r['candidate_reference_occurrences']],
            'top5_reference_occurrences':top5,
            'top5_micro_recall':top5/total if total else None,
            'top5_macro_query_recall':sum(r['recall_at_5'] for r in positive)/len(positive) if positive else None,
            'top5_any_hit_queries':sum(r['top5_reference_occurrences']>0 for r in positive),
            'top5_mrr':sum(r['mrr_at_5'] for r in positive)/len(positive) if positive else None,
            'oracle_top5_macro_recall':sum(r['oracle_recall_at_5'] for r in positive)/len(positive) if positive else None}

def main():
    # Only the exposed reference-ID mapping is projected; no historical ratings exported.
    old = inherited(R1 / 'HISTORICAL_REFERENCE_VERIFICATION.json')
    refs = {r['id']:r['reference_ids'] for r in old['cases']}
    write_json(OUT/'EXPOSED_REFERENCE_ID_MAPPING.json', {
        'namespace':'EXPOSED_15_DEVELOPMENT_NOT_FRESH_TEST',
        'source_sha256':file_hash(R1/'HISTORICAL_REFERENCE_VERIFICATION.json'),
        'cases':[{'case_id':sid,'reference_ids':ids} for sid,ids in refs.items()],
        'human_independence_verified':False, 'source_relevance_or_sufficiency_verified':False,
        'historical_review_status_and_ratings_omitted':True}, exclusive=True)
    source = {n:inherited(R1/f'{n}_DIAGNOSTICS.json') for n in ('A_R0','C_HYBRID','D_CROSS_ENCODER')}
    for n, rr in source.items():
        assert {r['case_id'] for r in rr} == set(refs)
    c = {r['case_id']:r for r in source['C_HYBRID']}
    for r in source['D_CROSS_ENCODER']:
        assert r['candidate_pool_ids'] == c[r['case_id']]['ranked_ids'][:30]
        assert set(r['ranked_ids']) == set(r['candidate_pool_ids'])
    groups = {}
    for n, rr in source.items():
        groups[n+'_SAVED_FULL'] = coverage_rows(rr,refs)
        if n != 'D_CROSS_ENCODER':
            groups[n+'_TOP30'] = coverage_rows([{**r,'ranked_ids':r['ranked_ids'][:30]} for r in rr],refs)
    results = {'namespace':'EXPOSED_DEVELOPMENT_REFERENCE_ID_ONLY',
               'unique_reference_ids_across_cases':len(set(i for v in refs.values() for i in v)),
               'per_case':groups, 'summary':{n:summarize(rr) for n,rr in groups.items()},
               'D_pool_equals_C_top30_every_case':True,
               'count_definitions':'26 query-reference occurrences, including repeated IDs across queries; 13 positive queries each have two references; two empty-reference queries excluded from recall.',
               'oracle_assumptions':'Ranking-only oracle may move any old reference ID already in the fixed candidate pool into top5. Bound=sum(min(5,pool_hits_i)/reference_count_i)/13. It assumes these exact old IDs define relevance; no semantic alternatives, source sufficiency, thresholds, or context limits.',
               'source_sufficiency':None}
    write_json(OUT/'CANDIDATE_POOL_COVERAGE_AUDIT.json',results,exclusive=True)
    lines=['# Saved candidate-pool audit','',
           'Independently recomputed from R1 saved exact IDs; no models run. Historical exposed development identity is preserved.', '',
           '| Saved ranking/pool | Reference occurrences in pool | Pool hit queries /13 | Top5 occurrences /26 | Macro Recall@5 | Oracle macro Recall@5 |',
           '|---|---:|---:|---:|---:|---:|']
    for n,s in results['summary'].items():
        lines.append(f"| {n} | {s['pool_reference_occurrences']}/26 | {s['pool_any_hit_queries']}/13 | {s['top5_reference_occurrences']} | {s['top5_macro_query_recall']:.6f} | {s['oracle_top5_macro_recall']:.6f} |")
    lines += ['',results['count_definitions'], '',results['oracle_assumptions'], '',
              f"Unique reference IDs across all queries: {results['unique_reference_ids_across_cases']}. Macro recall equals micro recall numerically here only because all 13 nonempty cases have exactly two IDs. Query hit rate is a different statistic.", '',
              'C top30 no-hit queries: '+', '.join(results['summary']['C_HYBRID_TOP30']['pool_no_hit_case_ids'])+'.', '',
              'A saved full ranking excludes zero/nonpositive lexical tail entries in the inherited implementation; it is not a new rerun or a new R0 threshold. D is exactly a permutation of C top30. A missing old ID can be an acceptable semantic alternative; no source-judged semantic equivalence or required-proposition references are available. Empty old references are unlabelled, not confirmed unanswerable negatives. No response-quality or human scoring occurred.']
    (OUT/'CANDIDATE_POOL_COVERAGE_AUDIT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(results['summary'],indent=2))

if __name__ == '__main__':
    main()
