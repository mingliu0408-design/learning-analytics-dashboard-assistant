"""Recalculate fixed-universe RQ1 metrics from saved sufficient counts.

No individual rankings or paired tests can be reconstructed from this starting
layer. Counts are read from data/, while independent comparison targets live in
results/reference/ and are never the source of calculated outputs.
"""
from fractions import Fraction
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def calculate(counts):
    results = {}
    for method, item in counts['methods'].items():
        labels = item['prediction_label_universe']
        matrix, ranks, n = item['confusion_matrix'], item['rank_distribution'], item['record_count']
        assert len(labels) == len(set(labels)) == 16
        assert set(matrix) == set(labels)
        assert all(set(row) == set(labels) for row in matrix.values())
        assert all(type(x) is int and x >= 0 for row in matrix.values() for x in row.values())
        assert all(type(x) is int and x >= 0 for x in ranks.values())
        assert sum(sum(row.values()) for row in matrix.values()) == sum(ranks.values()) == n == counts['record_count']
        correct = sum(matrix[label][label] for label in labels)
        assert correct == ranks.get('1', 0)
        rr = sum((Fraction(count, int(rank)) for rank, count in ranks.items() if rank != 'MISSING'), Fraction()) / n
        recall3 = Fraction(sum(count for rank, count in ranks.items() if rank != 'MISSING' and int(rank) <= 3), n)
        f1 = []
        for label in labels:
            tp = matrix[label][label]
            fp = sum(matrix[gold][label] for gold in labels if gold != label)
            fn = sum(matrix[label][pred] for pred in labels if pred != label)
            f1.append(Fraction(2 * tp, 2 * tp + fp + fn) if 2 * tp + fp + fn else Fraction())
        mean_rank = Fraction(sum((17 if rank == 'MISSING' else int(rank)) * count for rank, count in ranks.items()), n)
        results[method] = {'mrr': float(rr), 'top1_accuracy': correct/n, 'recall_at_3': float(recall3), 'macro_f1': float(sum(f1)/16), 'mean_gold_rank': float(mean_rank), 'top1_correct_count': correct}
    return results


def run(output_dir):
    counts = json.loads((ROOT/'data/reproduction/rq1/counts.json').read_text())
    calculated = calculate(counts)
    expected = json.loads((ROOT/'results/reference/rq1_metrics.json').read_text())
    assert calculated.keys() == expected.keys()
    for method, values in calculated.items():
        for metric, value in values.items():
            assert abs(value - expected[method][metric]) < 1e-14, (method, metric)
    result = {'status': 'PASS_AGGREGATE_START', 'layer': 'L1_SAVED_SUFFICIENT_COUNTS', 'record_count': counts['record_count'], 'methods': calculated, 'reference_comparison_passed': True, 'not_reproduced': ['Per-record rankings and Gold assignment', 'Paired bootstrap, randomisation and selection-gate inputs', 'Model encoding, training and historical checkpoint inference']}
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    (output/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
