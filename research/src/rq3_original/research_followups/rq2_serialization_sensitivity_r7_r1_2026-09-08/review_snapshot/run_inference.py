"""One bounded offline pass per representation. Gold is not read by this process."""
from __future__ import annotations
import argparse,ast,hashlib,json,os,socket,sys,time,traceback,typing,re,unicodedata
from pathlib import Path
BASE=Path(__file__).resolve().parent

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def jsonl(path,rows):path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
def exact_definitions(path,names,namespace):
 tree=ast.parse(path.read_text());selected=[];found=set()
 for node in tree.body:
  name=getattr(node,'name',None)
  if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):name=node.targets[0].id
  if name in names:selected.append(node);found.add(name)
 assert found==set(names),(path,set(names)-found)
 tree=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*selected],type_ignores=[])
 exec(compile(ast.fix_missing_locations(tree),str(path),'exec'),namespace)
 return [{'name':getattr(n,'name',getattr(n.targets[0],'id','')) if isinstance(n,ast.Assign) else n.name,'start_line':n.lineno,'end_line':n.end_lineno,'source_sha256':sha(path)} for n in selected]
def guard():
 def deny(*a,**k):raise RuntimeError('R7_OFFLINE_NETWORK_BLOCKED')
 socket.create_connection=deny;socket.getaddrinfo=deny;socket.socket.connect=deny;socket.socket.connect_ex=deny
 allowed=BASE.resolve()
 def audit(event,args):
  if event=='open':
   name,mode,flags=args
   writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
   if writing and isinstance(name,(str,bytes,os.PathLike)):
    p=Path(os.fsdecode(name)).resolve()
    if not p.is_relative_to(allowed):raise RuntimeError('R7_WRITE_OUTSIDE_SCOPE: '+str(p))
  if event in {'socket.connect','socket.getaddrinfo'}:raise RuntimeError('R7_OFFLINE_NETWORK_BLOCKED')
 sys.addaudithook(audit)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--encode-once',action='store_true');args=parser.parse_args()
 guard()
 cfg=json.loads((BASE/'SOURCE_IDENTITY.json').read_text())
 for e in cfg['sources']:assert sha(BASE/e['packaged_path'])==e['sha256']
 for e in cfg['encoder_files']:assert sha(Path(e['path']))==e['sha256']
 import numpy as np
 from collections.abc import Mapping,Sequence
 ns={'np':np,'json':json,'Any':typing.Any,'Mapping':Mapping,'Sequence':Sequence}
 names=['SEMANTIC_FIELDS','CAPABILITIES','ContractError','canonical_history','serialize_semantic_input','prototype_scores','apply_thresholds','sigmoid','predict_ovr_probabilities','predict_from_b2_payload','predict_from_b3_payload']
 source_audit=exact_definitions(BASE/'sources/track_h.py',names,ns)
 # Original exception type name is supplied as a local binding; successful serializers are unchanged ASTs.
 class CanonicalInputError(ValueError):pass
 cs={'Mapping':Mapping,'Sequence':Sequence,'Any':typing.Any,'re':re,'unicodedata':unicodedata,'CanonicalInputError':CanonicalInputError}
 names=['PRIMARY_FEATURE_FIELDS','NON_FEATURE_METADATA_FIELDS','MODEL_INPUT_FIELDS','CANONICAL_PAGES','RAG_CONTEXT_STATES','MEMORY_CONTEXT_STATES','_normalise_visible_text','validate_model_input','serialize_canonical_text']
 source_audit+=exact_definitions(BASE/'sources/canonical_text.py',names,cs)
 dump(BASE/'EXECUTED_DEFINITIONS.json',source_audit)
 rows=[json.loads(l) for l in (BASE/'sources/test_inputs.jsonl').read_text().splitlines()]
 ids=[r['annotation_case_id'] for r in rows];assert len(rows)==len(set(ids))==36
 semantics=[{k:r[k] for k in cfg['feature_fields']} for r in rows]
 texts={'test_labelled':[cs['serialize_canonical_text']({'model_input':s}) for s in semantics], 'dev_compact':[ns['serialize_semantic_input'](s) for s in semantics]}
 text_hashes={rep:hashlib.sha256('\n'.join(ts).encode()).hexdigest() for rep,ts in texts.items()}
 for rep in texts:
  jsonl(BASE/f'{rep}_serialized.jsonl',[{'annotation_case_id':i,'text':t,'utf8_sha256':hashlib.sha256(t.encode()).hexdigest()} for i,t in zip(ids,texts[rep],strict=True)])
 dump(BASE/'SERIALIZER_SUMMARY.json',{'row_count':36,'identical_text_pairs':sum(a==b for a,b in zip(*texts.values(),strict=True)),'text_hashes':text_hashes,'model_visible_fields':cfg['feature_fields'],'gold_model_visible':False})
 cache=BASE/'embeddings';cache.mkdir(exist_ok=True)
 identities={};matrices={};model=None
 import importlib.metadata as md
 versions={p:md.version(p) for p in ['numpy','torch','transformers','sentence-transformers','tokenizers','scikit-learn']}
 ledger={'schema':'R7_R1_BOUNDED_INFERENCE_V1','python':sys.version,'executable':sys.executable,'versions':versions,'new_text_encodings':0,'cache_rows_reused_this_invocation':0,'provider_calls':0,'llm_calls':0,'training_calls':0,'threshold_searches':0,'passes':[],'gold_files_read':0}
 dump(BASE/'runtime/invocation_started.json',ledger)
 for rep,ts in texts.items():
  npy=cache/f'{rep}.npy';meta=cache/f'{rep}.json';marker=cache/f'{rep}.attempt_started.json'
  if npy.exists() and meta.exists():
   identity=json.loads(meta.read_text());assert identity['text_sha256']==text_hashes[rep] and identity['annotation_case_ids']==ids and identity['encoder_files']==cfg['encoder_files'];assert sha(npy)==identity['npy_sha256']
   matrix=np.load(npy,allow_pickle=False);ledger['cache_rows_reused_this_invocation']+=36;origin='BOUND_INPUT_CACHE'
  else:
   if not args.encode_once:raise RuntimeError('No verified cache. Explicit --encode-once is required.')
   if marker.exists():raise RuntimeError('This representation already consumed its one attempt. Do not retry encoding.')
   dump(marker,{'representation':rep,'text_count':36,'text_sha256':text_hashes[rep],'started_at_unix':time.time(),'budget':'at most one encode call of these 36 texts'})
   if model is None:
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer(cfg['encoder_path'],device='cpu',local_files_only=True)
    assert model.get_sentence_embedding_dimension()==768
    dump(BASE/'RUNTIME_ENCODER_SETTINGS.json',{'max_seq_length':model.max_seq_length,'model_dtype':str(next(model.parameters()).dtype),'modules':str(model),'versions':versions,'device':'cpu','batch_size':16,'normalize_embeddings':True,'source_loader':'sources/execute_deterministic_test.py:132-146; same constructor and encode parameters, one shared model instance'})
   ledger['passes'].append({'representation':rep,'texts_submitted':36,'status':'STARTED'});dump(BASE/'runtime/invocation_started.json',ledger)
   matrix=model.encode(ts,batch_size=16,show_progress_bar=False,convert_to_numpy=True,normalize_embeddings=True)
   matrix=np.asarray(matrix,dtype=np.float32,order='C');np.save(npy,matrix,allow_pickle=False)
   ledger['new_text_encodings']+=36;ledger['passes'][-1]['status']='COMPLETED'
   identity={'representation':rep,'text_sha256':text_hashes[rep],'annotation_case_ids':ids,'encoder_files':cfg['encoder_files'],'npy_sha256':sha(npy),'matrix_sha256':hashlib.sha256(matrix.astype('<f4').tobytes()).hexdigest(),'shape':list(matrix.shape),'dtype':str(matrix.dtype),'normalization':'L2_UNIT','versions':versions};dump(meta,identity);origin='NEW_FROZEN_ENCODER_INFERENCE'
  assert matrix.shape==(36,768) and matrix.dtype==np.float32 and np.isfinite(matrix).all()
  assert np.allclose(np.linalg.norm(matrix.astype(np.float64),axis=1),1.,atol=2e-6,rtol=0)
  matrices[rep]=matrix;identities[rep]={'origin':origin,'shared_by':['B2','B3'],'cache_identity':identity}
 # Frozen heads are applied only after both text representations have been bound to their caches.
 result=[]
 for rep,matrix in matrices.items():
  b2=json.loads((BASE/'sources/b2_frozen_model_v1.json').read_text());b3=json.loads((BASE/'sources/b3_frozen_model_v1.json').read_text())
  scores2,pred2=ns['predict_from_b2_payload'](matrix,b2);scores3,pred3=ns['predict_from_b3_payload'](matrix,b3)
  for j,i in enumerate(ids):
   result.append({'annotation_case_id':i,'representation':rep,'B2':{'bits':pred2[j].tolist(),'scores':scores2[j].tolist()},'B3':{'bits':pred3[j].tolist(),'probabilities':scores3[j].tolist()}})
 jsonl(BASE/'predictions_b2_b3.jsonl',result)
 dump(BASE/'INFERENCE_RECEIPT.json',{**ledger,'status':'COMPLETE','representations':identities,'prediction_file_sha256':sha(BASE/'predictions_b2_b3.jsonl'),'head_applications':{'B2':72,'B3':72},'original_frozen_test_embedding_cache_rows_reused':0})
 print(json.dumps({'status':'COMPLETE','new_text_encodings':ledger['new_text_encodings'],'cache_rows_reused_this_invocation':ledger['cache_rows_reused_this_invocation'],'head_applications':144,'predictions_written':len(result)}))
if __name__=='__main__':
 try:main()
 except BaseException as e:
  dump(BASE/'runtime/inference_failure.json',{'error_type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc()});raise
