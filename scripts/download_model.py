"""Download only the pinned official MPNet model, then verify original hashes.

Run outside the network-disabled Memory worker. No provider key is used.
Optional dependency: pip install -r requirements-live.txt
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'research/src/rq3_original/utils/c4_memory/c4_memory_retriever.py'
NAMES={'MPNET_REPO_ID','MPNET_REVISION','MPNET_REQUIRED_HASHES'}
constants={}
for node in ast.parse(SOURCE.read_text()).body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in NAMES:
        constants[node.targets[0].id]=ast.literal_eval(node.value)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT/'.local/models')
    args=parser.parse_args()
    target=args.root.resolve()/constants['MPNET_REVISION']
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=constants['MPNET_REPO_ID'],revision=constants['MPNET_REVISION'],local_dir=target,
        allow_patterns=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','modules.json','sentence_bert_config.json','config_sentence_transformers.json','1_Pooling/config.json','README.md','.gitattributes'])
    for name,expected in constants['MPNET_REQUIRED_HASHES'].items():
        observed=hashlib.sha256((target/name).read_bytes()).hexdigest()
        if observed!=expected:raise ValueError('PINNED_MODEL_HASH_MISMATCH:'+name)
    print(json.dumps({'repo_id':constants['MPNET_REPO_ID'],'revision':constants['MPNET_REVISION'],'path':str(target),'verified_sha256':constants['MPNET_REQUIRED_HASHES']},indent=2))
if __name__=='__main__':main()
