"""Reapply frozen heads to verified caches; never instantiate an encoder."""
import hashlib,json,os,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
from run_inference import guard,exact_definitions,sha
from collections.abc import Mapping,Sequence
from typing import Any

def main():
 guard()
 import numpy as np
 cfg=json.loads((BASE/'SOURCE_IDENTITY.json').read_text())
 for item in cfg['sources']:
  assert sha(BASE/item['packaged_path'])==item['sha256']
 ns={'np':np,'Mapping':Mapping,'Sequence':Sequence,'Any':Any}
 exact_definitions(BASE/'sources/track_h.py',['CAPABILITIES','prototype_scores','apply_thresholds','sigmoid','predict_ovr_probabilities','predict_from_b2_payload','predict_from_b3_payload'],ns)
 original=[json.loads(l) for l in (BASE/'predictions_b2_b3.jsonl').read_text().splitlines()]
 replay=[]
 for rep in ['test_labelled','dev_compact']:
  meta=json.loads((BASE/'embeddings'/f'{rep}.json').read_text());p=BASE/'embeddings'/f'{rep}.npy'
  texts=[json.loads(l) for l in (BASE/f'{rep}_serialized.jsonl').read_text().splitlines()]
  assert meta['annotation_case_ids']==[r['annotation_case_id'] for r in texts]
  assert hashlib.sha256('\n'.join(r['text'] for r in texts).encode()).hexdigest()==meta['text_sha256']
  assert meta['encoder_files']==cfg['encoder_files'] and sha(p)==meta['npy_sha256']
  X=np.load(p,allow_pickle=False);assert X.shape==(36,768)
  b2=json.loads((BASE/'sources/b2_frozen_model_v1.json').read_text());b3=json.loads((BASE/'sources/b3_frozen_model_v1.json').read_text())
  s2,p2=ns['predict_from_b2_payload'](X,b2);s3,p3=ns['predict_from_b3_payload'](X,b3)
  for j,i in enumerate(meta['annotation_case_ids']):replay.append({'annotation_case_id':i,'representation':rep,'B2':{'bits':p2[j].tolist(),'scores':s2[j].tolist()},'B3':{'bits':p3[j].tolist(),'probabilities':s3[j].tolist()}})
 assert replay==original
 (BASE/'CACHE_REPLAY_RECEIPT.json').write_text(json.dumps({'status':'PASS_EXACT_PREDICTION_OBJECT_EQUALITY','new_text_encodings':0,'cache_rows_reused':72,'frozen_head_row_evaluations':144,'model_loaded':False,'provider_calls':0,'training_calls':0,'prediction_rows_verified':72},indent=2)+'\n')
 print('PASS 72 cached rows reused; 144 frozen head row evaluations; zero text encoding; predictions exactly equal')
if __name__=='__main__':main()
