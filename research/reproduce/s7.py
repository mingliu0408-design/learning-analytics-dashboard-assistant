#!/usr/bin/env python3
"""S7-R1: exact frozen-score reconstruction and fixed exploratory calculations.

Run from repository root: python -m reproduce.s7 --output outputs/s7
Only the supplied SCORE_COMPONENTS and exact source fields determine scores.
No model, provider, identity, declaration or human-scoring operation is present.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
import sys
from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STATUS = 'POST_HOC_EXPLORATORY_CONDITIONAL_SUPPLEMENT'

def avg(values):
    values = list(values)
    if not values:
        raise ValueError('An empty mean is undefined')
    return sum(values, F(0)) / len(values)

def family_aggregate(conditions):
    """condition -> rater -> applicable criterion scores; preserve equal levels."""
    return avg(avg(avg(scores) for scores in condition) for condition in conditions)

def sign_flip(deltas):
    deltas = list(map(F, deltas))
    denominator = math.lcm(*(d.denominator for d in deltas))
    integers = [int(d * denominator) for d in deltas]
    observed = abs(sum(integers))
    extreme = sum(abs(sum(s * v for s, v in zip(signs, integers))) >= observed
                  for signs in itertools.product((-1, 1), repeat=len(integers)))
    total = 2 ** len(integers)
    return F(extreme, total), extreme, total, F(observed, denominator * len(integers))

def holm(pvalues):
    pvalues = list(map(F, pvalues))
    order = sorted(range(len(pvalues)), key=lambda i: (pvalues[i], i))
    adjusted = [F(0)] * len(pvalues)
    running = F(0)
    for rank, i in enumerate(order):
        running = max(running, (len(order) - rank) * pvalues[i])
        adjusted[i] = min(F(1), running)
    return adjusted

def paired_bootstrap(matrix, n_resamples, seed):
    """matrix: group x family x mode, rational values. Common indices for all modes.

    Sum in an integer common denominator before conversion to float64. The
    canonical RNG call and array layout are fixed in FREEZE_RECEIPT.json.
    """
    matrix = np.asarray(matrix, dtype=object)
    groups, families, modes = matrix.shape
    denominator = math.lcm(*(F(x).denominator for x in matrix.flat))
    integer_matrix = np.array([int(F(x) * denominator) for x in matrix.flat],
                              dtype=np.int64).reshape(matrix.shape)
    assert int(np.abs(integer_matrix).max()) * groups * families < np.iinfo(np.int64).max
    indices = np.random.default_rng(seed).integers(0, families,
                    size=(n_resamples, groups, families), dtype=np.int64)
    sampled = integer_matrix[np.arange(groups)[None, :, None], indices, :]
    sums = sampled.sum(axis=(1, 2), dtype=np.int64)
    return sums, denominator * groups * families, indices

def leave_one_new(deltas, groups):
    return {removed: avg(avg(deltas[f] for f in fs if f != removed)
                           for fs in groups.values())
            for removed in deltas}

def read_csv(name):
    base = ROOT / ('data/reproduction/rq3' if name == 'SCORE_COMPONENTS.csv' else 'results/reference/s7/inputs')
    with (base / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    rows = list(rows)
    assert rows
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def ffields(prefix, value):
    return {prefix: float(value), prefix + '_exact': str(value)}

def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    spec_bytes = (ROOT / 'data/reproduction/s7/EXPLORATORY_SPEC.json').read_bytes()
    spec = json.loads(spec_bytes)
    freeze = json.loads((ROOT / 'data/reproduction/s7/FREEZE_RECEIPT.json').read_text())
    assert hashlib.sha256(spec_bytes).hexdigest() == freeze['spec_sha256']
    assert freeze['frozen_at_utc'] < started
    assert spec['analysis_status'] == STATUS and spec['results_already_seen']
    assert spec['bootstrap']['n_resamples'] == 50000 and spec['bootstrap']['seed'] == 20260908
    assert spec['bootstrap']['quantile_method'] == 'linear'
    assert spec['multiplicity']['alpha'] == .05 and spec['sign_flip']['enumerate'] == 4096
    groups = spec['fixed_focus_groups']
    assert list(groups) == ['E', 'R', 'M', 'P'] and all(len(x) == 3 for x in groups.values())
    families = list(itertools.chain.from_iterable(groups.values()))
    contrasts = [(c['high_mode'], c['low_mode']) for c in spec['contrasts']]
    modes = sorted(set(itertools.chain.from_iterable(contrasts)))
    assert len(modes) == 6 and len(contrasts) == 15
    assert set(contrasts) == {(modes[h], modes[l]) for l in range(6) for h in range(l + 1, 6)}

    # Reconstruct from all 1,968 criterion positions without pooling denominators.
    positions = read_csv('SCORE_COMPONENTS.csv')
    assert len(positions) == 1968
    by_answer = defaultdict(list)
    keys = set()
    masks = {}
    task_info = {}
    n_numeric = n_na = 0
    for r in positions:
        key = (r['task_id'], r['mode'], r['criterion'])
        assert key not in keys
        keys.add(key)
        assert r['mode'] in modes and r['applicable'] in ('True', 'False')
        applicable = r['applicable'] == 'True'
        mask_key = (r['task_id'], r['criterion'])
        assert mask_key not in masks or masks[mask_key] == applicable
        masks[mask_key] = applicable
        for label in ('Rater1_score', 'Rater2_score'):
            if applicable:
                assert r[label] in ('1', '2', '3', '4', '5')
            else:
                assert r[label] == 'NA'
        n_numeric += applicable
        n_na += not applicable
        by_answer[r['task_id'], r['mode']].append(r)
        info = (r['stratum'], r['family_id'], r['condition'])
        assert r['task_id'] not in task_info or task_info[r['task_id']] == info
        task_info[r['task_id']] = info
    assert (n_numeric, n_na) == (1248, 720)
    assert (sum(masks.values()), len(masks)-sum(masks.values())) == (208, 120)
    assert len(task_info) == 41 and len(by_answer) == 246
    reconstructed = defaultdict(list)
    answers = []
    for (task, mode), rows in sorted(by_answer.items()):
        assert len(rows) == 8 and len({r['criterion'] for r in rows}) == 8
        applicable = [r for r in rows if r['applicable'] == 'True']
        r1 = avg(F(r['Rater1_score']) for r in applicable)
        r2 = avg(F(r['Rater2_score']) for r in applicable)
        paired = avg([r1, r2])
        stratum, family, condition = task_info[task]
        unit = task if stratum == 'original17' else family
        reconstructed[stratum, unit, mode].append((r1, r2, paired))
        answers.append(dict(stratum=stratum, task_id=task, family_id=family,
            condition=condition, mode=mode, applicable_criteria=len(applicable),
            **ffields('Rater1_mean', r1), **ffields('Rater2_mean', r2),
            **ffields('two_rater_mean', paired)))
    units = {}
    unit_rows = read_csv('UNIT_MODE_MEANS.csv')
    assert len(unit_rows) == 174
    for r in unit_rows:
        key = (r['stratum'], r['unit_id'], r['mode'])
        assert key not in units
        vals = tuple(F(r[c]) for c in ('Rater1_mean_exact','Rater2_mean_exact','two_record_mean_exact'))
        assert vals[2] == avg(vals[:2])
        components = reconstructed[key]
        assert len(components) == int(r['conditions']) == (1 if key[0]=='original17' else 2)
        assert vals == tuple(avg(row[i] for row in components) for i in range(3))
        # Computation flows from criterion scores; saved values serve only as checks.
        units[key] = tuple(avg(row[i] for row in components) for i in range(3))
    assert set(reconstructed) == set(units)
    ids = {st: sorted({u for s,u,m in units if s == st}) for st in ('original17','new12_families')}
    assert len(ids['original17']) == 17 and set(ids['new12_families']) == set(families)
    for family in families:
        conditions = [info[2] for info in task_info.values() if info[1] == family]
        assert sorted(conditions) == ['A', 'B']
    means = {(st,m): avg(units[st,u,m][2] for u in us) for st,us in ids.items() for m in modes}
    for r in read_csv('MODE_DESCRIPTIVE_SUMMARY.csv'):
        st,m = r['stratum'],r['mode']
        assert means[st,m] == F(r['mean_exact'])
        assert int(r['n_units']) == len(ids[st])
    for r in read_csv('CAPABILITY_FAMILY_MEANS.csv'):
        assert avg(units['new12_families',u,r['mode']][2]
                   for u in groups[r['family_prefix']]) == F(r['mean_exact'])
    deltas = {(st,u,h,l): tuple(units[st,u,h][i]-units[st,u,l][i] for i in range(3))
              for st,us in ids.items() for u in us for h,l in contrasts}
    delta_rows = read_csv('ALL_MODE_CONTRAST_UNIT_DELTAS.csv')
    assert len(delta_rows) == len(deltas) == 435
    seen = set()
    for r in delta_rows:
        key = (r['stratum'],r['unit_id'],r['high_mode'],r['low_mode'])
        assert key not in seen
        seen.add(key)
        assert deltas[key] == tuple(F(r[c]) for c in ('Rater1_delta_exact','Rater2_delta_exact','delta_exact'))
    for r in read_csv('ALL_MODE_CONTRASTS.csv'):
        ds = [deltas[r['stratum'],u,r['high_mode'],r['low_mode']][2] for u in ids[r['stratum']]]
        assert avg(ds) == F(r['mean_exact'])
        assert (sum(d>0 for d in ds),sum(d==0 for d in ds),sum(d<0 for d in ds)) == tuple(int(r[x]) for x in ('wins','ties','losses'))
    high,low = modes[5],modes[0]
    for r in read_csv('PRIMARY_FAMILY_DIFFERENCES.csv'):
        assert deltas['new12_families',r['unit_id'],high,low][2] == F(r['delta_exact'])
    assert means['original17',high]-means['original17',low] == F(271,4760)
    assert means['new12_families',high]-means['new12_families',low] == F(977,1440)

    write_csv(output/'ANSWER_MEANS_RECONSTRUCTED.csv', answers)
    write_csv(output/'MODE_MEANS_REPRODUCED.csv', (
        dict(stratum=st,mode=m,n_units=len(us),**ffields('mean',means[st,m]),
             **ffields('Rater1_mean',avg(units[st,u,m][0] for u in us)),
             **ffields('Rater2_mean',avg(units[st,u,m][1] for u in us)))
        for st,us in ids.items() for m in modes))
    matrix = [[[units['new12_families',u,m][2] for m in modes] for u in fs] for fs in groups.values()]
    sums, denominator, indices = paired_bootstrap(matrix,50000,20260908)
    np.save(output/'BOOTSTRAP_INDICES.npy', indices.astype(np.uint8), allow_pickle=False)
    distribution = np.column_stack([(sums[:,modes.index(h)] - sums[:,modes.index(l)]).astype(np.float64)/denominator for h,l in contrasts])
    np.save(output/'BOOTSTRAP_CONTRAST_DISTRIBUTION.npy', distribution, allow_pickle=False)
    limits = np.quantile(distribution,[.025,.975],axis=0,method='linear')
    flips = [sign_flip([deltas['new12_families',u,h,l][2] for u in families]) for h,l in contrasts]
    adjusted = holm([f[0] for f in flips])
    table = []
    for j,(h,l) in enumerate(contrasts):
        ds = [deltas['new12_families',u,h,l][2] for u in families]
        p,extreme,total,stat = flips[j]
        table.append(dict(contrast=h[:2]+'-'+l[:2],high_mode=h,low_mode=l,n_families=12,
            **ffields('mean_delta',avg(ds)), bootstrap_lower_95=float(limits[0,j]),
            bootstrap_upper_95=float(limits[1,j]), **ffields('absolute_mean_statistic',stat),
            extreme_sign_configurations=extreme,total_sign_configurations=total,
            **ffields('p_raw',p),**ffields('p_holm_15',adjusted[j]),
            holm_below_alpha_0_05=adjusted[j]<=F(1,20),n_positive=sum(d>0 for d in ds),
            n_zero=sum(d==0 for d in ds),n_negative=sum(d<0 for d in ds),
            n_bootstrap=50000,seed=20260908,interval_status='marginal_conditional_resampling_stability',
            test_status='hypothetical_joint_sign_flip_invariance_not_established',analysis_status=STATUS))
    write_csv(output/'ALL_15_NEW_CONTRASTS.csv',table)
    write_csv(output/'ALL_15_ORIGINAL_DESCRIPTIVE_CONTRASTS.csv',(
        dict(contrast=h[:2]+'-'+l[:2],high_mode=h,low_mode=l,n_questions=17,
            **ffields('mean_delta',avg(deltas['original17',u,h,l][2] for u in ids['original17'])),
            n_positive=sum(deltas['original17',u,h,l][2]>0 for u in ids['original17']),
            n_zero=sum(deltas['original17',u,h,l][2]==0 for u in ids['original17']),
            n_negative=sum(deltas['original17',u,h,l][2]<0 for u in ids['original17']),
            interpretation='descriptive_only_no_CI_or_p') for h,l in contrasts))
    write_csv(output/'ALL_UNIT_DELTAS_EXACT.csv',(
        dict(stratum=st,unit_id=u,contrast=h[:2]+'-'+l[:2],**ffields('delta',vals[2]),
             **ffields('Rater1_delta',vals[0]),**ffields('Rater2_delta',vals[1]))
        for (st,u,h,l),vals in deltas.items()))
    influence = []
    for st,us in ids.items():
        ds = {u:deltas[st,u,high,low][2] for u in us}
        full = avg(ds.values())
        deleted = leave_one_new(ds,groups) if st=='new12_families' else {u:avg(v for k,v in ds.items() if k!=u) for u in us}
        for u in us:
            influence.append(dict(stratum=st,removed_unit=u,focus=u[0] if st=='new12_families' else '',
                remaining_units=len(us)-1,**ffields('removed_delta',ds[u]),**ffields('full_delta',full),
                **ffields('leave_one_out_delta',deleted[u]),**ffields('change_from_full',deleted[u]-full),
                weighting='equal_0.25_per_focus_renormalized_within_focus' if st=='new12_families' else 'equal_1_over_16_remaining_questions',
                interpretation='deterministic_influence_not_CI'))
    write_csv(output/'S5_S0_LEAVE_ONE_OUT.csv',influence)
    rater_table=[]
    for st,us in ids.items():
        for i,label in enumerate(('Rater 1','Rater 2')):
            ds=[deltas[st,u,high,low][i] for u in us]
            rater_table.append(dict(stratum=st,rater=label,n_units=len(us),**ffields('S5_minus_S0',avg(ds)),
                n_positive=sum(d>0 for d in ds),n_zero=sum(d==0 for d in ds),n_negative=sum(d<0 for d in ds),
                interpretation='descriptive_fixed_rater_no_resampling_of_raters'))
    write_csv(output/'RATER_S5_S0_DESCRIPTIVE.csv',rater_table)
    receipt = dict(status='PASS',analysis_status=STATUS,started_at_utc=started,
        finished_at_utc=datetime.now(timezone.utc).isoformat(),spec_sha256=hashlib.sha256(spec_bytes).hexdigest(),
        runtime=dict(python=platform.python_version(),numpy=np.__version__,platform=platform.system()),
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        checks=dict(score_positions=len(positions),numeric_per_rater=n_numeric,fixed_NA_per_rater=n_na,
            task_applicability_true=sum(masks.values()),task_applicability_false=len(masks)-sum(masks.values()),
            reconstructed_answer_means=246,reproduced_exact_unit_mode_means=174,reproduced_exact_mode_means=12,
            reproduced_exact_category_means=24,reproduced_exact_unit_deltas=435,reproduced_exact_contrasts=30,
            preserved_zero_unit_deltas=sum(v[2]==0 for v in deltas.values()),
            preserved_negative_unit_deltas=sum(v[2]<0 for v in deltas.values()),
            new_contrasts=15,sign_configurations_per_contrast=4096,holm_family_size=15,
            new_influence_values=12,original_influence_values=17,source_score_changes=0),
        bootstrap=dict(index_shape=list(indices.shape),storage_dtype='uint8',rng_dtype='int64',
            group_order=list(groups),family_order=groups,contrast_order=[r['contrast'] for r in table],
            integer_sum_denominator=denominator,quantile='numpy.quantile(method=linear)',
            index_sha256=hashlib.sha256((output/'BOOTSTRAP_INDICES.npy').read_bytes()).hexdigest(),
            distribution_sha256=hashlib.sha256((output/'BOOTSTRAP_CONTRAST_DISTRIBUTION.npy').read_bytes()).hexdigest()),
        no_new_model_calls=True,no_new_scores=True,no_agreement_coefficients=True)
    references = json.loads((ROOT/'results/reference/s7/REFERENCE_OUTPUT_HASHES.json').read_text())
    verified = {}
    for name, expected in references.items():
        actual = hashlib.sha256((output/name).read_bytes()).hexdigest()
        if actual != expected:
            raise AssertionError(f'Frozen output hash mismatch: {name}: {actual} != {expected}')
        verified[name] = actual
    receipt['reference_output_sha256_verified'] = verified
    (output/'COMPUTATION_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/s7')
    args=parser.parse_args()
    receipt = run(args.output.resolve())
    print(json.dumps(receipt, indent=2))
