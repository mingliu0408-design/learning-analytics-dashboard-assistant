"""Gold-free deterministic policies. Only ordered chunk IDs are accepted."""
from itertools import zip_longest
import math

POLICIES = ('E_R0_SEEDED', 'F_FIXED_UNION')
CAP = 30

def checked_ids(ids):
    if not isinstance(ids, list) or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError('ORDERED_STRING_IDS_REQUIRED')
    if len(ids) != len(set(ids)):
        raise ValueError('SAVED_RANKING_HAS_DUPLICATE_IDS')
    return ids

def candidate_pool(policy, a_ids, c_ids):
    a_ids, c_ids = checked_ids(a_ids), checked_ids(c_ids)
    if policy == 'E_R0_SEEDED':
        return a_ids[:CAP]
    if policy != 'F_FIXED_UNION':
        raise ValueError('UNDECLARED_POLICY')
    result, seen = [], set()
    for a, c in zip_longest(a_ids, c_ids):
        for ident in (a, c):
            if ident is not None and ident not in seen:
                result.append(ident)
                seen.add(ident)
                if len(result) == CAP:
                    return result
    return result

def rank_scores(pool, scores):
    if set(pool) != set(scores) or len(pool) != len(scores):
        raise ValueError('SCORE_POOL_IDENTITY_MISMATCH')
    if any(not math.isfinite(value) for value in scores.values()):
        raise ValueError('NONFINITE_STOP_NO_RETRY')
    return sorted(pool, key=lambda ident: (-scores[ident], ident))

def admit_pairs(attempted, count, ceiling=900):
    if count < 0 or attempted < 0 or attempted + count > ceiling:
        raise ValueError('NEW_PAIR_CEILING_EXCEEDED')
    return attempted + count
