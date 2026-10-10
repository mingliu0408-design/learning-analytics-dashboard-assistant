"""Optional fixed-model R7 encoder inference. Not part of offline reproduction.

This release wrapper reuses exact function ASTs from the frozen R7 code. It
requires explicit --encode-once, externally supplied semantic inputs, and an
already obtained local encoder. It never downloads weights, reads Gold, fits
heads, selects thresholds or calls a generative API.
"""
import argparse
import ast
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import typing
import unicodedata
ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT/'src/rq2_original/r7/sources'
SEMANTIC_FIELDS = ('current_query','current_page','dashboard_context','visible_conversation_history')
MODEL_HASHES = {
    'config.json':'d46a3e04ded82bba22528424480697d394eeda6a27484e08c5bb2bdf5906cfa0',
    'model.safetensors':'78c0197b6159d92658e319bc1d72e4c73a9a03dd03815e70e555c5ef05615658',
    'tokenizer.json':'b8be2c30ba5dd723a6d5ee26d013da103d5408d92ddcb23747622f9e48f1d842',
}


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def exact_definitions(path,names,namespace):
    """Same frozen AST selection mechanism as R7 run_inference.py."""
    selected=[];found=set()
    for node in ast.parse(path.read_text()).body:
        name=getattr(node,'name',None)
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):name=node.targets[0].id
        if name in names:selected.append(node);found.add(name)
    assert found==set(names),(path,set(names)-found)
    tree=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*selected],type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree),str(path),'exec'),namespace)


def algorithm_namespace(np):
    ns={'np':np,'json':json,'Any':typing.Any,'Mapping':Mapping,'Sequence':Sequence}
    exact_definitions(SOURCES/'track_h.py',['SEMANTIC_FIELDS','CAPABILITIES','ContractError','canonical_history','serialize_semantic_input','prototype_scores','apply_thresholds','sigmoid','predict_ovr_probabilities','predict_from_b2_payload','predict_from_b3_payload'],ns)
    class CanonicalInputError(ValueError):pass
    cs={'Mapping':Mapping,'Sequence':Sequence,'Any':typing.Any,'re':re,'unicodedata':unicodedata,'CanonicalInputError':CanonicalInputError}
    exact_definitions(SOURCES/'canonical_text.py',['PRIMARY_FEATURE_FIELDS','NON_FEATURE_METADATA_FIELDS','MODEL_INPUT_FIELDS','CANONICAL_PAGES','RAG_CONTEXT_STATES','MEMORY_CONTEXT_STATES','_normalise_visible_text','validate_model_input','serialize_canonical_text'],cs)
    return ns,cs


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encode-once',action='store_true',help='Explicitly permit a new 36-case pass for each representation')
    parser.add_argument('--inputs',type=Path,help='External JSONL: annotation_case_id and the four semantic fields; exactly 36 cases')
    parser.add_argument('--encoder',type=Path,help='Already obtained all-mpnet-base-v2 e8c3b32... local directory')
    parser.add_argument('--output',type=Path,help='New output directory; existing directory is refused')
    args=parser.parse_args(argv)
    if not args.encode_once:parser.error('Encoding was not requested. Use --encode-once only with supplied inputs and local model assets.')
    if any(x is None for x in [args.inputs,args.encoder,args.output]):parser.error('--inputs, --encoder and --output are required with --encode-once')
    if args.output.exists():parser.error('--output must be a new directory; no frozen outputs are overwritten')
    def deny(*a,**k):raise RuntimeError('R7_OFFLINE_NETWORK_BLOCKED')
    socket.create_connection=deny;socket.getaddrinfo=deny;socket.socket.connect=deny;socket.socket.connect_ex=deny
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    for name,expected in MODEL_HASHES.items():
        if sha(args.encoder/name)!=expected:raise ValueError('Frozen encoder file hash mismatch: '+name)
    rows=[json.loads(line) for line in args.inputs.read_text().splitlines() if line.strip()]
    ids=[r['annotation_case_id'] for r in rows]
    assert len(rows)==len(set(ids))==36
    assert all(set(row)=={'annotation_case_id',*SEMANTIC_FIELDS} for row in rows), 'No Gold or extra fields accepted'
    import numpy as np
    from sentence_transformers import SentenceTransformer
    ns,cs=algorithm_namespace(np)
    semantics=[{k:r[k] for k in SEMANTIC_FIELDS} for r in rows]
    texts={'test_labelled':[cs['serialize_canonical_text']({'model_input':s}) for s in semantics], 'dev_compact':[ns['serialize_semantic_input'](s) for s in semantics]}
    model=SentenceTransformer(str(args.encoder),device='cpu',local_files_only=True)
    assert model.get_sentence_embedding_dimension()==768
    assert model.max_seq_length==384, 'Historical R7 used max_seq_length=384'
    args.output.mkdir(parents=True)
    (args.output/'ATTEMPT_STARTED.json').write_text(json.dumps({'input_sha256':sha(args.inputs),'encoder_hashes':MODEL_HASHES,'training_calls':0,'threshold_searches':0,'provider_calls':0},indent=2)+'\n')
    result=[]
    for rep,ts in texts.items():
        matrix=model.encode(ts,batch_size=16,show_progress_bar=False,convert_to_numpy=True,normalize_embeddings=True)
        matrix=np.asarray(matrix,dtype=np.float32,order='C')
        assert matrix.shape==(36,768) and np.isfinite(matrix).all()
        assert np.allclose(np.linalg.norm(matrix.astype(np.float64),axis=1),1.,atol=2e-6,rtol=0)
        b2=json.loads((SOURCES/'b2_frozen_model_v1.json').read_text());b3=json.loads((SOURCES/'b3_frozen_model_v1.json').read_text())
        scores2,pred2=ns['predict_from_b2_payload'](matrix,b2);scores3,pred3=ns['predict_from_b3_payload'](matrix,b3)
        for j,i in enumerate(ids):result.append({'annotation_case_id':i,'representation':rep,'B2':{'bits':pred2[j].tolist(),'scores':scores2[j].tolist()},'B3':{'bits':pred3[j].tolist(),'probabilities':scores3[j].tolist()}})
    (args.output/'predictions_b2_b3.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in result))
    (args.output/'COMPLETE.json').write_text(json.dumps({'status':'COMPLETE','new_text_encodings':72,'head_applications':144,'inputs_sha256':sha(args.inputs),'predictions_sha256':sha(args.output/'predictions_b2_b3.jsonl')},indent=2)+'\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
