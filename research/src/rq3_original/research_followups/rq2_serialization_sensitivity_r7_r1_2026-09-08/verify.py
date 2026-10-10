"""Independent descriptive checks plus provenance/preservation verification."""
from __future__ import annotations
import hashlib,json,math,subprocess
from pathlib import Path
from fractions import Fraction
BASE=Path(__file__).resolve().parent
REPO=BASE.parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def j(n):return json.loads((BASE/n).read_text())
def jl(n):return [json.loads(l) for l in (BASE/n).read_text().splitlines()]
def main():
 checks=[]
 def check(name,ok):
  assert ok,name;checks.append(name)
 cfg=j('SOURCE_IDENTITY.json')
 for e in cfg['sources']:check('packaged source '+e['packaged_path'],sha(BASE/e['packaged_path'])==e['sha256'])
 pred=jl('predictions_all_versions.jsonl');side=jl('evaluation_sidecar.jsonl');metrics=j('METRICS_ALL.json')
 check('36 identities',len(side)==len({r['annotation_case_id'] for r in side})==36)
 answers=[r for r in side if r['gold_dialogue_action']=='ANSWER'];check('32 ANSWER 16 families',len(answers)==32 and len({r['canonical_scenario_family_id'] for r in answers})==16)
 check('CLARIFY capability Gold null',all(all(r['gold_'+k+'_required'] is None for k in ['rag','memory','planning']) for r in side if r['gold_dialogue_action']=='CLARIFY'))
 for rep in metrics:
  for m in ['B2','B3','P1']:
   pp={r['annotation_case_id']:r for r in pred if r['representation']==rep and r['method']==m};check(rep+m+' complete population',len(pp)==36)
   f=[];wrong=exact=under=over=0
   for k in range(3):
    gk=['gold_rag_required','gold_memory_required','gold_planning_required'][k]
    tp=sum(r[gk] and pp[r['annotation_case_id']]['bits'][k] for r in answers)
    fp=sum(not r[gk] and pp[r['annotation_case_id']]['bits'][k] for r in answers)
    fn=sum(r[gk] and not pp[r['annotation_case_id']]['bits'][k] for r in answers)
    f.append(Fraction(2*tp,2*tp+fp+fn) if 2*tp+fp+fn else Fraction(0));wrong+=fp+fn
   for r in answers:
    gold=[int(r['gold_'+k+'_required']) for k in ['rag','memory','planning']];bits=pp[r['annotation_case_id']]['bits'];exact+=bits==gold;under+=any(g and not b for g,b in zip(gold,bits,strict=True));over+=any(b and not g for g,b in zip(gold,bits,strict=True))
   cm=metrics[rep][m]['core_answer32'];check(rep+m+' independent Fraction Macro-F1',math.isclose(cm['macro_f1'],float(sum(f)/3),abs_tol=1e-15,rel_tol=0));check(rep+m+' independent counts',cm['exact_correct_case_count']==exact and cm['under_routing_count']==under and cm['over_routing_count']==over and cm['hamming_loss']==wrong/96)
   correct=sum(pp[r['annotation_case_id']]['route']==('CLARIFY' if r['gold_dialogue_action']=='CLARIFY' else ''.join(str(int(r['gold_'+k+'_required'])) for k in ['rag','memory','planning'])) for r in side)
   check(rep+m+' full-route denominator',metrics[rep][m]['complete36']['full_route_signature_exact_count']==correct and metrics[rep][m]['complete36']['population_count']==36)
 check('all cases included',len(jl('CASE_COMPARISON.jsonl'))==108)
 check('all bits included',len(jl('BIT_COMPARISON.jsonl'))==324)
 check('baseline exact',j('BASELINE_REPRODUCTION.json')['all_test_labelled_metric_objects_exact'])
 check('72 encoded once',j('INFERENCE_RECEIPT.json')['new_text_encodings']==72 and len(j('INFERENCE_RECEIPT.json')['passes'])==2)
 for rep in ['test_labelled','dev_compact']:
  meta=j(f'embeddings/{rep}.json');check(rep+' cache bytes',sha(BASE/'embeddings'/f'{rep}.npy')==meta['npy_sha256'])
 check('P3 preserved',next(x for x in j('sources/final_test_method_results_v1.json')['methods'] if x['method_id']=='R2V2-P3_RAG_MEMORY_SPECIALISTS')['core_macro_f1_gold_answer_cases']==0.9310754604872252)
 preserved=[]
 if (REPO/'.git').exists() and (REPO/'evaluation').is_dir():
  initial=j('PREFLIGHT.json')
  for p,h in initial['preserved_files'].items():check('preserved '+p,sha(REPO/p)==h);preserved.append(p)
  for e in cfg['sources']:check('original source unchanged '+e['source_path'],sha(Path(e['source_path']))==e['sha256'])
  for e in cfg['encoder_files']:check('encoder unchanged '+e['relative_path'],sha(Path(e['path']))==e['sha256'])
  (BASE/'MODEL_UNCHANGED.json').write_text(json.dumps({'status':'PASS','original_sources':cfg['sources'],'encoder_files_before_and_after':cfg['encoder_files'],'fitted_weights_prototypes_thresholds_changed':False,'encoder_changed':False,'existing_untracked_file_count_preserved':len(preserved)},ensure_ascii=False,indent=2)+'\n')
 (BASE/'VERIFICATION.json').write_text(json.dumps({'status':'PASS','checks_passed':len(checks),'checks':checks,'independent_metrics':'Fraction count-based Macro-F1; direct set/routing counts; no original metric function used','posthoc_only':True},ensure_ascii=False,indent=2)+'\n')
 print('PASS',len(checks),'checks')
if __name__=='__main__':main()
