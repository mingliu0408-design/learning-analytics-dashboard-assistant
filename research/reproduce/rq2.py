"""Use original dependency-free metrics on all released saved RQ2 predictions."""
import json
from pathlib import Path
from src.rq2_original.evaluation.capability_routing_rq2_v2_stage5.final_scoring import metrics
ROOT = Path(__file__).resolve().parents[1]
BITS = ('rag_required','memory_required','planning_required')


def load_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_inputs():
    base = ROOT/'data/reproduction/rq2'
    rows = load_rows(base/'evaluation_sidecar.jsonl')
    ids = [r['annotation_case_id'] for r in rows]
    assert len(ids) == len(set(ids)) == 36
    answer = [r for r in rows if r['gold_dialogue_action'] == 'ANSWER']
    assert len(answer) == 32
    assert len({r['canonical_scenario_family_id'] for r in answer}) == 16
    for row in rows:
        if row['gold_dialogue_action'] == 'CLARIFY':
            assert all(row['gold_'+k] is None for k in BITS)
        else:
            assert all(type(row['gold_'+k]) is bool for k in BITS)
    saved = load_rows(base/'complete_predictions.jsonl')
    methods = {}
    for row in saved:
        assert all(type(row[k]) is bool for k in BITS)
        method = methods.setdefault(row['method_id'], {})
        assert row['annotation_case_id'] not in method
        method[row['annotation_case_id']] = tuple(row[k] for k in BITS)
    assert len(methods) == 11
    assert all(set(predictions) == set(ids) for predictions in methods.values())
    return rows, answer, methods


def run(output_dir):
    rows, answer, methods = load_inputs()
    gates = {r['annotation_case_id']:r['frozen_clarification_prediction'] for r in rows}
    expected_core = json.loads((ROOT/'results/reference/rq2_final_test_core_method_metrics_v1.json').read_text())['methods']
    expected_full = json.loads((ROOT/'results/reference/rq2_final_test_end_to_end_metrics_v1.json').read_text())['methods']
    result = {}
    for method, predictions in methods.items():
        routes = {i: 'CLARIFY' if gates[i]=='CLARIFY' else metrics.signature_text(value) for i,value in predictions.items()}
        core = metrics.core_metrics(answer, predictions)
        full = metrics.end_to_end_metrics(rows, gates, routes)
        assert core == expected_core[method], (method, 'core32')
        assert full == expected_full[method], (method, 'complete36')
        result[method] = {'core_answer32':core, 'complete36':full}
    output = Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    (output/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    return {'status':'PASS', 'layer':'L1_SAVED_ANONYMOUS_PREDICTIONS_GOLD', 'case_count':36,'core_count':32,'method_count':len(methods),'all_metric_objects_exact':True,'P3_macro_f1':result['R2V2-P3_RAG_MEMORY_SPECIALISTS']['core_answer32']['macro_f1']}
