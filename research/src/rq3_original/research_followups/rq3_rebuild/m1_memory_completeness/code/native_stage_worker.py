"""Fresh native probe. Fault tracing/network guard precede all numeric imports."""
import faulthandler
import resource
import json
import sys
import traceback
import platform
import importlib.metadata
from pathlib import Path
faulthandler.enable(all_threads=True)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
from m1_common import object_sha
from utils.c4_memory.c4_memory_retriever import FrozenLocalMPNetBackend, MEMORY_TYPE_DESCRIPTIONS

def emit(value):
    print(json.dumps(value), flush=True)

def main():
    stage, model = sys.argv[1], Path(sys.argv[2])
    emit({'event': 'STAGE_ENTER', 'stage': stage})
    if stage == 'metadata':
        packages = {}
        for name in ('numpy', 'torch', 'transformers', 'sentence-transformers', 'tokenizers', 'safetensors'):
            try: packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: packages[name] = 'NOT_INSTALLED'
        emit({'executable': sys.executable, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
              'python': sys.version, 'machine': platform.machine(), 'platform': platform.platform(),
              'packages': packages, 'requested_device': 'cpu', 'actual_device': 'NOT_LOADED'})
    elif stage in ('numpy', 'torch', 'tokenizers', 'transformers'):
        module = __import__(stage)
        emit({'module': stage, 'file': module.__file__, 'version': module.__version__})
    elif stage == 'tokenizer':
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True)
        encoded = tokenizer(['Synthetic revision goal.'], truncation=True, max_length=384)
        emit({'tokenizer_class': type(tokenizer).__name__, 'special_tokens': tokenizer.special_tokens_map,
              'synthetic_token_ids': encoded['input_ids']})
    else:
        import torch
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        backend = FrozenLocalMPNetBackend(model, verify_hashes=True)
        backend._load()
        identity = dict(backend.identity)
        device = str(next(backend._encoder.parameters()).device)
        emit({'event': 'MODEL_CONSTRUCTED', 'identity': identity, 'actual_device': device})
        if stage in ('encode', 'serve'):
            import math
            texts = ['Synthetic revision goal.', 'A learner has a short study period.']
            vectors = backend.encode(texts)
            norms = [math.sqrt(sum(v*v for v in row)) for row in vectors]
            assert len(vectors) == 2 and all(len(row) == 768 for row in vectors)
            assert all(math.isfinite(v) for row in vectors for v in row)
            assert all(abs(n-1.0) < 1e-5 for n in norms)
            configs = {n: json.loads((model/n).read_text()) for n in
                       ('modules.json', '1_Pooling/config.json', 'sentence_bert_config.json')}
            assert configs['1_Pooling/config.json']['pooling_mode_mean_tokens'] is True
            assert configs['sentence_bert_config.json']['max_seq_length'] == 384
            runtime_contract = {'implementation': identity['implementation']}
            if identity['implementation'].startswith('SENTENCE_TRANSFORMERS'):
                encoder = backend._encoder
                runtime_contract.update(max_seq_length=encoder.max_seq_length,
                    module_classes=[type(m).__name__ for m in encoder],
                    mean_pooling=encoder[1].pooling_mode == 'mean',
                    tokenizer_class=type(encoder[0].tokenizer).__name__,
                    do_lower_case=encoder[0].do_lower_case,
                    default_prompt_name=encoder.default_prompt_name,
                    parameter_dtype=str(next(encoder.parameters()).dtype))
                assert runtime_contract['max_seq_length']==384 and runtime_contract['mean_pooling']
                assert runtime_contract['module_classes']==['Transformer','Pooling','Normalize']
                assert runtime_contract['default_prompt_name'] is None
                assert not runtime_contract['do_lower_case']
                check_texts=texts+['synthetic '*500]
                effective=encoder[0].preprocess(check_texts)
                direct=encoder[0].tokenizer(check_texts,padding=True,truncation=True,max_length=384,return_tensors='pt')
                assert torch.equal(effective['input_ids'],direct['input_ids'])
                assert torch.equal(effective['attention_mask'],direct['attention_mask'])
                runtime_contract['effective_tokenization_matches_direct_local_tokenizer']=True
                runtime_contract['observed_truncated_length']=effective['input_ids'].shape[1]
            # Exact inherited implementation, not a model/pooling/serialization substitute.
            emit({'event': 'ENCODE_VERIFIED', 'identity': identity, 'actual_device': device,
                  'dimension': 768, 'norms': norms, 'configs': configs,
                  'input_sha256': object_sha(texts), 'max_length': 384,
                  'pooling': 'ATTENTION_MASK_MEAN', 'normalisation': 'L2',
                  'effective_input': 'str(text), query + eligible record.content + frozen type descriptions',
                  'type_descriptions_sha256': object_sha(MEMORY_TYPE_DESCRIPTIONS),
                  'loaded_runtime_contract': runtime_contract,
                  'difference_from_M0_attempt': 'Existing venv selects inherited SentenceTransformers branch; M0 base was eligible for Transformers fallback but never loaded.',
                  'implementation_difference_from_inherited': 'NONE'})
            if stage == 'serve':
                for line in sys.stdin:
                    message = json.loads(line)
                    assert set(message) == {'texts'} and isinstance(message['texts'], list)
                    emit({'vectors': backend.encode(message['texts']),
                          'input_sha256': object_sha(message['texts'])})
    emit({'event': 'STAGE_COMPLETE', 'stage': stage})

if __name__ == '__main__':
    try: main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
