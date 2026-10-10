"""Reproduce descriptive metrics from saved predictions, with no model imports."""
from __future__ import annotations
import ast,copy,hashlib,json,typing
from pathlib import Path
from collections import Counter,defaultdict
BASE=Path(__file__).resolve().parent
REPO=BASE.parents[1]
FS=REPO/'evaluation/capability_routing_rq2_v2_stage5/final_scoring'
CAPS=['RAG','Memory','Planning'];BITS=['rag_required','memory_required','planning_required']
MIDS={'B2':'R2V2-B2_PROTOTYPE','B3':'R2V2-B3_OVR','P1':'R2V2-P1_HYBRID'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(name,obj):(BASE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def load(name):return json.loads((BASE/name).read_text())
def jl(name):return [json.loads(l) for l in (BASE/name).read_text().splitlines()]
def writejl(name,rows):(BASE/name).write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
def sig(v):return tuple(bool(v[k]) for k in BITS)
def txt(v):return ''.join(str(int(k)) for k in v)
def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+''.join('| '+' | '.join(str(v) for v in r)+' |\n' for r in rows)
def metric_namespace():
 ns={}
 tree=ast.parse((BASE/'sources/constants.py').read_text())
 sel=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CAPABILITY_KEYS' for t in n.targets)]
 exec(compile(ast.Module(body=sel,type_ignores=[]),'frozen constants','exec'),ns)
 tree=ast.parse((BASE/'sources/metrics.py').read_text())
 tree.body=[n for n in tree.body if not (isinstance(n,ast.ImportFrom) and n.level) and not (isinstance(n,ast.FunctionDef) and n.name in ['bootstrap_analysis','percentile'])]
 exec(compile(tree,str(BASE/'sources/metrics.py'),'exec'),ns)
 return ns

def p1_frozen(b0,b2,b3,b4):
 ns={'direct':{'R2V2-B0_RULE':b0,'R2V2-B2_PROTOTYPE':b2,'R2V2-B3_OVR':b3},'b4_signature':b4}
 tree=ast.parse((BASE/'sources/compositions.py').read_text())
 fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='compose_case')
 wanted={'unanimous','p1_triggered','p1'}
 nodes=[n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in wanted for t in n.targets)]
 assert len(nodes)==3
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'original P1 assignments','exec'),ns)
 return tuple(ns['p1']),bool(ns['p1_triggered'])

def flatten(x,p=''):
 out={}
 if isinstance(x,dict):
  for k,v in x.items():out.update(flatten(v,p+'.'+k if p else k))
 elif isinstance(x,list):
  for i,v in enumerate(x):out.update(flatten(v,p+f'[{i}]'))
 else:out[p]=x
 return out

def direction(key):
 if any(t in key for t in ['distribution','predicted_capability','population_count','family_count','eligible_contrast','coverage','core_executed','predicted_clarify']):return None
 last=key.rsplit('.',1)[-1]
 if last in ['fp','fn','hamming_loss','under_routing_count','under_routing_rate','over_routing_count','over_routing_rate']:return -1
 if any(t in last for t in ['f1','precision','recall','specificity','accuracy','exact','jaccard','correct','consisten','matched','pattern_match']) or last in ['tp','tn','rate']:return 1
 return None

def main():
 assert (BASE/'evaluation_sidecar.jsonl').is_file(), 'Supply the released numerical sidecar'
 rows=jl('evaluation_sidecar.jsonl');ids=[r['annotation_case_id'] for r in rows];byid={r['annotation_case_id']:r for r in rows}
 assert len(rows)==len(set(ids))==36
 answer=[r for r in rows if r['gold_dialogue_action']=='ANSWER'];assert len(answer)==32
 assert len({r['canonical_scenario_family_id'] for r in answer})==16
 for r in rows:
  if r['gold_dialogue_action']=='CLARIFY':assert all(r['gold_'+k] is None for k in BITS)
 orig={r['annotation_case_id']:r['method_predictions'] for r in jl('sources/original_deterministic.jsonl')}
 complete=jl('sources/final_test_complete_method_predictions_v1.jsonl')
 originals={m:{r['annotation_case_id']:sig(r) for r in complete if r['method_id']==mid} for m,mid in MIDS.items()}
 original_b0={r['annotation_case_id']:sig(r) for r in complete if r['method_id']=='R2V2-B0_RULE'}
 original_b4={r['annotation_case_id']:sig(r) for r in complete if r['method_id']=='R2V2-B4_JOINT_LLM'}
 b4_terminal=jl('sources/original_b4.jsonl')
 # The frozen complete B0 and B4 values are checked against their original terminals below.
 assert all(original_b0[i]==sig(orig[i]['R2V2-B0_RULE']) for i in ids)
 def locate_b4(row):
  if isinstance(row,dict):
   if all(k in row for k in BITS) and all(type(row[k]) is bool for k in BITS):return sig(row)
   for v in row.values():
    res=locate_b4(v)
    if res is not None:return res
  return None
 b4_check={r['annotation_case_id']:locate_b4(r) for r in b4_terminal}
 assert b4_check==original_b4
 predrows=jl('predictions_b2_b3.jsonl');reps=['original_frozen','test_labelled','dev_compact']
 predictions={'original_frozen':originals};p1_policy={}
 for rep in reps[1:]:
  part=[r for r in predrows if r['representation']==rep];assert {r['annotation_case_id'] for r in part}==set(ids)
  predictions[rep]={m:{r['annotation_case_id']:tuple(bool(v) for v in r[m]['bits']) for r in part} for m in ['B2','B3']}
 for rep in reps:
  computed={};triggers={}
  for i in ids:computed[i],triggers[i]=p1_frozen(original_b0[i],predictions[rep]['B2'][i],predictions[rep]['B3'][i],original_b4[i])
  if rep=='original_frozen':assert computed==originals['P1']
  predictions[rep]['P1']=computed;p1_policy[rep]=triggers
 proof={}
 for m,key in [('B2','scores'),('B3','probabilities')]:
  part=[r for r in predrows if r['representation']=='test_labelled']
  differences=[abs(r[m][key][j]-orig[r['annotation_case_id']][MIDS[m]][key][cap]) for r in part for j,cap in enumerate(CAPS)]
  proof[m]={'case_signature_mismatches':sum(predictions['test_labelled'][m][i]!=originals[m][i] for i in ids),'bit_mismatches':sum(a!=b for i in ids for a,b in zip(predictions['test_labelled'][m][i],originals[m][i],strict=True)),'max_absolute_score_or_probability_difference':max(differences),'all_108_scores_numerically_exact':not any(differences)}
 ns=metric_namespace();gates={r['annotation_case_id']:r['frozen_clarification_prediction'] for r in rows}
 metrics={};old_core=load('sources/final_test_core_method_metrics_v1.json')['methods'];old_e2e=load('sources/final_test_end_to_end_metrics_v1.json')['methods']
 routes={};allpred=[]
 for rep in reps:
  metrics[rep]={};routes[rep]={}
  for m in MIDS:
   pred=predictions[rep][m];route={i:'CLARIFY' if gates[i]=='CLARIFY' else txt(pred[i]) for i in ids};routes[rep][m]=route
   core=ns['core_metrics'](answer,pred);e2e=ns['end_to_end_metrics'](rows,gates,route)
   if rep=='original_frozen':
    assert core==old_core[MIDS[m]],m
    assert e2e==old_e2e[MIDS[m]],m
   metrics[rep][m]={'core_answer32':core,'complete36':e2e}
   for i in ids:allpred.append({'representation':rep,'method':m,'annotation_case_id':i,'bits':list(map(int,pred[i])),'frozen_gate':gates[i],'route':route[i],'p1_triggered':p1_policy[rep][i] if m=='P1' else None,'p1_source':('B4' if p1_policy[rep][i] else 'B3') if m=='P1' else None})
 proof['P1']={'original_composition_exact':True,'test_labelled_case_signature_mismatches':sum(predictions['test_labelled']['P1'][i]!=originals['P1'][i] for i in ids)}
 proof['all_original_core_and_full_metric_objects_exact']=True
 proof['all_test_labelled_metric_objects_exact']=metrics['test_labelled']==metrics['original_frozen']
 dump('BASELINE_REPRODUCTION.json',proof);dump('METRICS_ALL.json',metrics);writejl('predictions_all_versions.jsonl',allpred)
 case_rows=[];bit_rows=[];summary={}
 for m in MIDS:
  counts=Counter({k:0 for k in ['IMPROVED','UNCHANGED_ERROR_COUNT','WORSENED']});counts_bits=Counter({k:0 for k in ['IMPROVED','UNCHANGED','WORSENED']});counts_exact=Counter({k:0 for k in ['WRONG_TO_CORRECT','CORRECT_TO_WRONG','BOTH_CORRECT','BOTH_WRONG']});changed36=0
  for i in ids:
   r=byid[i];old=originals[m][i];new=predictions['dev_compact'][m][i];changed=old!=new;changed36+=changed
   gold=tuple(r['gold_'+k] for k in BITS) if r['gold_dialogue_action']=='ANSWER' else None
   oe=sum(a!=g for a,g in zip(old,gold,strict=True)) if gold is not None else None;ne=sum(a!=g for a,g in zip(new,gold,strict=True)) if gold is not None else None
   outcome=('IMPROVED' if ne<oe else 'WORSENED' if ne>oe else 'UNCHANGED_ERROR_COUNT') if gold is not None else 'NOT_APPLICABLE_CLARIFY'
   exact_transition=('WRONG_TO_CORRECT' if oe>0 and ne==0 else 'CORRECT_TO_WRONG' if oe==0 and ne>0 else 'BOTH_CORRECT' if oe==ne==0 else 'BOTH_WRONG') if gold is not None else 'NOT_APPLICABLE_CLARIFY'
   if gold is not None:counts[outcome]+=1;counts_exact[exact_transition]+=1
   case_rows.append({'method':m,'annotation_case_id':i,'family':r['canonical_scenario_family_id'],'gold_action':r['gold_dialogue_action'],'gold_bits':list(map(int,gold)) if gold is not None else None,'old_bits':txt(old),'new_bits':txt(new),'changed_bits':sum(a!=b for a,b in zip(old,new,strict=True)),'old_errors':oe,'new_errors':ne,'error_count_outcome':outcome,'exact_transition':exact_transition,'old_route':routes['original_frozen'][m][i],'new_route':routes['dev_compact'][m][i]})
   for j,cap in enumerate(CAPS):
    status=('IMPROVED' if old[j]!=gold[j] and new[j]==gold[j] else 'WORSENED' if old[j]==gold[j] and new[j]!=gold[j] else 'UNCHANGED') if gold is not None else 'NOT_APPLICABLE_CLARIFY'
    if gold is not None:counts_bits[status]+=1
    bit_rows.append({'method':m,'annotation_case_id':i,'family':r['canonical_scenario_family_id'],'gold_action':r['gold_dialogue_action'],'capability':cap,'old':int(old[j]),'new':int(new[j]),'gold':int(gold[j]) if gold is not None else None,'changed':old[j]!=new[j],'outcome':status})
  summary[m]={'case_signatures_changed_36':changed36,'case_signatures_changed_answer32':sum(c['method']==m and c['gold_action']=='ANSWER' and c['old_bits']!=c['new_bits'] for c in case_rows),'bits_changed_108':sum(b['method']==m and b['changed'] for b in bit_rows),'full_routes_changed_36':sum(routes['original_frozen'][m][i]!=routes['dev_compact'][m][i] for i in ids),'answer_case_error_count_outcomes':dict(counts),'answer_bit_outcomes':dict(counts_bits),'answer_exact_transitions':dict(counts_exact)}
 summary['P1']['b4_fallback_count_36']={rep:sum(p1_policy[rep].values()) for rep in reps}
 summary['P1']['fallback_decision_changes']=[i for i in ids if p1_policy['original_frozen'][i]!=p1_policy['dev_compact'][i]]
 dump('CHANGE_SUMMARY.json',summary);writejl('CASE_COMPARISON.jsonl',case_rows);writejl('BIT_COMPARISON.jsonl',bit_rows)
 (BASE/'ALL_CASE_CHANGES.md').write_text('# All case comparisons\n\nBits are ordered RAG, Memory, Planning. Error outcomes use Gold ANSWER only. CLARIFY latent bits are retained without invented capability Gold.\n\n'+table(['Method','ID','Family','Action','Old','New','Old errors','New errors','Outcome','Exact transition'],[[c[k] for k in ['method','annotation_case_id','family','gold_action','old_bits','new_bits','old_errors','new_errors','error_count_outcome','exact_transition']] for c in case_rows]))
 (BASE/'ALL_BIT_CHANGES.md').write_text('# All bit comparisons\n\nAll 324 method/case/bit positions are retained, including unchanged positions. CLARIFY Gold is null.\n\n'+table(['Method','ID','Capability','Old','New','Gold','Changed','Outcome'],[[r[k] for k in ['method','annotation_case_id','capability','old','new','gold','changed','outcome']] for r in bit_rows]))
 deltas=[]
 for m in MIDS:
  old=flatten(metrics['original_frozen'][m]);new=flatten(metrics['dev_compact'][m])
  for k in sorted(old.keys() | new.keys()):
   if k not in old or k not in new: assert 'prediction_signature_distribution.' in k
   a=old.get(k,0);b=new.get(k,0)
   if type(a) in [int,float] and type(b) in [int,float]:
    d=b-a;sign=direction(k);outcome='UNCHANGED' if d==0 else ('IMPROVED' if d*sign>0 else 'WORSENED') if sign else 'CHANGED_DESCRIPTIVE'
    deltas.append({'method':m,'metric':k,'original':a,'dev_compact':b,'delta':d,'direction':sign,'outcome':outcome})
 dump('ALL_METRIC_DELTAS.json',deltas)
 (BASE/'ALL_METRIC_DELTAS.md').write_text('# Complete scalar metric comparisons\n\nAll numeric fields from the original metric objects are included. Delta is compact minus original. Distribution/count changes without a quality direction are marked CHANGED_DESCRIPTIVE. No inferential tests or p values are added.\n\n'+table(['Method','Metric','Original','Compact','Delta','Outcome'],[[d['method'],d['metric'],f"{d['original']:.9g}",f"{d['dev_compact']:.9g}",f"{d['delta']:+.9g}",d['outcome']] for d in deltas]))
 selected=[]
 for m in MIDS:
  for rep in ['original_frozen','dev_compact']:
   c=metrics[rep][m]['core_answer32'];e=metrics[rep][m]['complete36']
   selected.append([m,rep,f"{c['macro_f1']:.9f}",f"{c['exact_correct_case_count']}/32",f"{c['under_routing_count']}/32",f"{c['over_routing_count']}/32",f"{c['hamming_loss']:.9f}",f"{e['full_route_signature_exact_count']}/36"])
 (BASE/'RESULT_TABLE.md').write_text('# Frozen-model serializer sensitivity\n\n'+table(['Method','Representation','Macro-F1','Exact set','Under','Over','Hamming','Full route exact'],selected))
 print(json.dumps({'baseline':proof,'changes':summary,'results':selected},indent=2))
if __name__=='__main__':main()
