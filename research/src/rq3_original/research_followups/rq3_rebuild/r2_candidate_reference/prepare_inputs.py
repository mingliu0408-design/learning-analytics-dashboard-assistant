"""Freeze policies and sanitized ranking projections without opening references."""
from common import *
from policies import POLICIES, candidate_pool
import sys

def main():
    if (OUT / 'POLICY_FREEZE.json').exists():
        raise FileExistsError('POLICIES_ALREADY_FROZEN')
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
    assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == BRANCH
    config = inherited(R1 / 'RUN_CONFIG.json')
    compatibility = inherited(R1 / 'D_COMPATIBILITY_RETRY_MANIFEST.json')
    assert compatibility['dtype_override'] == 'float64' and compatibility['attention_override'] == 'eager'
    assert compatibility['same_model_revision'] == REVISION
    assert config['batch_size'] == 4 and config['rerank_depth'] == 30 and config['final_k'] == 5
    safe = []
    source_files = []
    for name in ('A_R0', 'C_HYBRID'):
        p = R1 / f'{name}_DIAGNOSTICS.json'
        # The inherited mixed report contains metric columns. They are dropped here;
        # the candidate constructor receives only exact ordered IDs in a separate file.
        rows = inherited(p)
        assert len(rows) == 15
        assert file_hash(p) == compatibility['saved_ABC_hashes'][name]
        source_files.append(source_receipt(p, 'SAVED_RANKING_PROJECTION_SOURCE'))
        safe.extend({'candidate': name, 'case_id': r['case_id'],
                     'query_sha256': r['query_sha256'], 'ranked_ids': r['ranked_ids']}
                    for r in rows)
    write_json(OUT / 'SAVED_RANKING_INPUTS.json', safe, exclusive=True)
    # No reference mapping, labels, historical ratings, or expected answers are loaded.
    rows = read_json(OUT / 'SAVED_RANKING_INPUTS.json')
    a = {r['case_id']: r for r in rows if r['candidate'] == 'A_R0'}
    c = {r['case_id']: r for r in rows if r['candidate'] == 'C_HYBRID'}
    assert len(a) == len(c) == 15 and set(a) == set(c)
    pools = []
    for policy in POLICIES:
        for sid, ar in a.items():
            assert ar['query_sha256'] == c[sid]['query_sha256']
            pool = candidate_pool(policy, ar['ranked_ids'], c[sid]['ranked_ids'])
            pools.append({'policy': policy, 'case_id': sid, 'query_sha256': ar['query_sha256'],
                          'candidate_ids': pool, 'candidate_count': len(pool),
                          'candidate_ids_sha256': digest(canonical(pool)),
                          'shortfall_from_cap': 30-len(pool)})
    write_json(OUT / 'CANDIDATE_POOLS.json', pools, exclusive=True)
    effective = {
        'model': 'cross-encoder/ms-marco-MiniLM-L6-v2', 'revision': REVISION,
        'dtype': 'float64', 'attention': 'eager', 'device': 'cpu',
        'threads': 1, 'batch_size': 4, 'deterministic_algorithms': True,
        'eval': True, 'inference_mode': True, 'use_safetensors': True,
        'trust_remote_code': False, 'local_files_only': True,
        'query_format': 'raw_strip_v1', 'query_cap': 64,
        'passage_format': 'unchanged utils.c4_rag.retrievers._embedding_text',
        'max_length': 512, 'padding': True, 'truncation': 'only_second',
        'output': 'raw logit, not probability', 'top_k': 5,
        'tie_break': 'descending logit, ascending exact chunk_id',
        'max_new_pair_scores': 900, 'actual_scheduled_pair_uses': sum(len(p['candidate_ids']) for p in pools),
        'cache': 'reuse only an identical complete ordered padded tensor batch plus model/config and query/passage byte hashes',
        'r1_cache': 'NOT_REUSED: saved length-only audit has no complete padded token tensor identity',
        'no_retry_on_nonfinite': True, 'threshold': None,
        'deployment_action': 'ABSTAIN_UNCALIBRATED', 'final_system_selected': False,
    }
    write_json(OUT / 'EFFECTIVE_CONFIG.json', effective, exclusive=True)
    policy_doc = {'E_R0_SEEDED': 'First 30 saved A_R0 IDs, preserving frozen order; fewer if unavailable.',
                  'F_FIXED_UNION': 'A rank1, C rank1, A rank2, C rank2, ...; skip exact duplicate IDs; stop at 30 unique or exhaustion.',
                  'reference_fields_allowed': [], 'rankings_refrozen': False,
                  'no_query_rewrite_corpus_chunk_or_threshold_change': True}
    write_json(OUT / 'POLICIES.json', policy_doc, exclusive=True)
    paths = [OUT/n for n in ('SAVED_RANKING_INPUTS.json', 'CANDIDATE_POOLS.json',
                            'EFFECTIVE_CONFIG.json', 'POLICIES.json', 'policies.py')]
    write_json(OUT / 'POLICY_FREEZE.json', {
        'frozen_utc': now(), 'start_head': BASE, 'new_pair_scores_before_freeze': 0,
        'coverage_audit_sha256': file_hash(OUT/'CANDIDATE_POOL_COVERAGE_AUDIT.json'),
        'files': {str(p.relative_to(OUT)): file_hash(p) for p in paths},
        'source_files': source_files, 'reference_mapping_loaded_by_constructor': False,
        'mixed_report_projection': 'Only four whitelisted fields retained; policy function has no query, score, label, or file argument.',
    }, exclusive=True)
    print(json.dumps({'pools':len(pools),'scheduled_pair_uses':effective['actual_scheduled_pair_uses'],
                      'short_pools':[{'policy':p['policy'],'case_id':p['case_id'],'count':p['candidate_count']} for p in pools if p['shortfall_from_cap']]}))

if __name__ == '__main__':
    main()
