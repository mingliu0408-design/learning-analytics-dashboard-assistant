"""One bounded offline run. No reference file is opened in this process."""
from common import *
from policies import POLICIES, admit_pairs, rank_scores
from contextlib import contextmanager
from types import SimpleNamespace
import fcntl
import importlib.metadata
import math
import re
import sys
import time

LOCK = Path('/private/tmp/rq3-rebuild-local-inference.lock')

def model_processes():
    """Inspect process metadata only; never read another worktree's files."""
    raw = subprocess.check_output(['ps','-axo','pid=,comm='],text=True)
    rows = []
    for line in raw.splitlines():
        pid_text, _, name = line.strip().partition(' ')
        pid = int(pid_text)
        if pid == os.getpid() or not re.search(r'python|ollama|llama|mlx',name,re.I):
            continue
        result = subprocess.run(['ps','-p',str(pid),'-o','args='],capture_output=True,text=True)
        args = result.stdout
        if not args.strip():
            continue  # process exited during snapshot
        role = ('SAVEIT_NON_MODEL' if 'Saveit.py' in args else
                'TELEGRAM_HARVESTER_NON_MODEL' if 'Telegram Image Harvester' in args and 'live_monitor.py' in args else
                'POTENTIAL_MODEL_OR_UNKNOWN_PYTHON')
        rows.append({'pid':pid, 'executable_name':Path(name.strip()).name, 'classification':role,
                     'blocks_inference':role == 'POTENTIAL_MODEL_OR_UNKNOWN_PYTHON'})
    return rows

@contextmanager
def compute_lease():
    with LOCK.open('a+') as f:
        try:
            fcntl.flock(f.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('DEFERRED_LOCAL_INFERENCE_LOCK_BUSY')
        try:
            observed = model_processes()
            record = {'time_utc':now(),'lock_path':str(LOCK),'pid':os.getpid(),
                      'lock_acquired':True,'processes':observed,
                      'unfinished_sibling_files_read':0,'processes_killed':0,
                      'limitation':'Advisory lock plus current process inspection; no attestation that I0 uses this new lock. Rechecked before each forward.'}
            write_json(OUT/'RESOURCE_CHECK.json',record)
            if any(p['blocks_inference'] for p in observed):
                raise RuntimeError('DEFERRED_LOCAL_INFERENCE_RESOURCE')
            f.seek(0);f.truncate();f.write(json.dumps({'task':'R2','pid':os.getpid(),'time_utc':now()}));f.flush()
            yield record
        finally:
            fcntl.flock(f.fileno(),fcntl.LOCK_UN)

def install_reference_firewall():
    counts = {'forbidden_data_open_attempts':0}
    def guard(event,args):
        if event != 'open' or not isinstance(args[0],(str,bytes,os.PathLike)):
            return
        p = os.fsdecode(args[0])
        banned = ('historical_labels.json','HISTORICAL_REFERENCE_VERIFICATION.json',
                  'EXPOSED_REFERENCE_ID_MAPPING.json','CANDIDATE_POOL_COVERAGE_AUDIT',
                  'DEV_RESULTS.json','DIAGNOSTICS.json')
        if any(x in p for x in banned) or str(ROOT/'evaluation')+'/' in p:
            counts['forbidden_data_open_attempts'] += 1
            raise PermissionError('REFERENCE_OR_EVALUATION_OPEN_FORBIDDEN_IN_INFERENCE')
    sys.addaudithook(guard)
    return counts

def main():
    if (OUT/'EXECUTION_RECEIPT.json').exists():
        raise FileExistsError('EXECUTION_EXISTS_NO_AUTOMATIC_REPEAT')
    freeze = read_json(OUT/'POLICY_FREEZE.json')
    for name,h in freeze['files'].items():
        assert file_hash(OUT/name) == h, 'POLICY_FREEZE_MISMATCH'
    config = read_json(OUT/'EFFECTIVE_CONFIG.json')
    pools = read_json(OUT/'CANDIDATE_POOLS.json')
    reference_guard = install_reference_firewall()
    requests_path = r1_local()/'historical_requests.json'
    chunks_path = r1_local()/'v0_chunks.json'
    pre = inherited(R1/'PRE_RANKING_FREEZE.json')
    if not requests_path.is_file() or not chunks_path.is_file():
        write_json(OUT/'EXECUTION_RECEIPT.json',{'status':'NOT_RUN_SOURCE_UNAVAILABLE','new_pair_scores':0},exclusive=True)
        return
    assert file_hash(requests_path) == pre['files']['local_artifacts/historical_requests.json']
    chunks = read_json(chunks_path)
    assert len(chunks) == 624 and digest(canonical(chunks)) == V0, 'V0_CORPUS_MISMATCH'
    reqs = {r['id']:r for r in read_json(requests_path)}
    assert len(reqs) == 15
    for p in pools:
        assert digest(reqs[p['case_id']]['query'].strip().encode()) == p['query_sha256']
    source = [source_receipt(requests_path,'GOLD_FREE_R1_REQUESTS_LOCAL_ONLY'),
              source_receipt(chunks_path,'EXACT_R1_V0_CHUNKS_LOCAL_ONLY')]
    model_root = Path(inherited(R1/'MODEL_RUNTIME_IDENTITY.json')['cross_encoder']['local_path'])
    downloads = inherited(R1/'CROSS_ENCODER_DOWNLOAD_RECEIPT.json')
    for r in downloads['files']:
        p = model_root/r['name']
        if not p.is_file():
            write_json(OUT/'EXECUTION_RECEIPT.json',{'status':'NOT_RUN_SOURCE_UNAVAILABLE','new_pair_scores':0,'missing':'existing_model_file'},exclusive=True)
            return
        assert p.stat().st_size == r['bytes'] and file_hash(p) == r['sha256'], 'MODEL_FILE_MISMATCH'
        source.append(source_receipt(p,'READ_ONLY_EXISTING_MODEL'))
    code_paths = ['utils/c4_rag_lab/neural.py','utils/c4_rag_lab/common.py',
                  'utils/c4_rag/retrievers.py','utils/c4_rag/corpus.py']
    for name in code_paths:
        p = ROOT/name
        b = subprocess.check_output(['git','show',f'{BASE}:{name}'])
        assert digest(b) == file_hash(p)
        source.append(source_receipt(p,'INHERITED_EXECUTABLE_CODE'))
    runtime = {n:importlib.metadata.version(n) for n in ('torch','transformers','numpy','tokenizers','safetensors')}
    assert runtime == {'torch':'2.10.0','transformers':'4.55.0','numpy':'2.4.2','tokenizers':'0.21.4','safetensors':'0.7.0'}, 'R1_RUNTIME_DRIFT'
    write_json(OUT/'INFERENCE_SOURCE_MANIFEST.json',{
        'sources':source,'config_sha256':file_hash(OUT/'EFFECTIVE_CONFIG.json'),
        'runtime':runtime,'python':sys.version,'executable':sys.executable,
        'model_downloads':0,'package_installs':0,'v0':V0,
    },exclusive=True)
    assert read_json(OUT/'TEST_RESULTS.json')['passed'], 'TESTS_REQUIRED_BEFORE_INFERENCE'
    LOCAL.mkdir(exist_ok=True)
    receipt = {'status':'NOT_STARTED','start_head':BASE,'new_pair_attempts':0,'new_pair_scores':0,
               'cache_reused_pair_uses':0,'accepted_policy_case_rankings':0,'generation_calls':0,
               'judge_calls':0,'human_scores_created':0,'model_downloads':0,'configuration_count':1,
               'max_new_pair_scores':900,'scheduled_pair_uses':sum(p['candidate_count'] for p in pools),
               'started_utc':None,'reference_guard':reference_guard}
    cache, rankings, pair_audits = {}, [], []
    try:
        with compute_lease():
            sys.path.insert(0,str(ROOT))
            from utils.c4_rag_lab.common import offline_guard
            with offline_guard() as network_guard:
                receipt['status']='STARTED_DO_NOT_REPEAT';receipt['started_utc']=now()
                receipt['code_sha256']={p.name:file_hash(p) for p in sorted(OUT.glob('*.py'))}
                write_json(OUT/'EXECUTION_RECEIPT.json',receipt,exclusive=True)
                from utils.c4_rag_lab.neural import LocalNeural, serialise_v0
                by_id = {r['chunk_id']:SimpleNamespace(**r) for r in chunks}
                start = time.perf_counter()
                model = LocalNeural(model_root,'cross_encoder',dtype='float64',attention='eager')
                receipt['model_load_ms']=(time.perf_counter()-start)*1000
                assert str(next(model.model.parameters()).dtype)=='torch.float64'
                assert model.model.config._attn_implementation == 'eager'
                model_identity = digest(canonical({'model_files':downloads['files'],'runtime':runtime,
                                                  'config':config,'inherited_neural_sha256':file_hash(ROOT/code_paths[0])}))
                for p in pools:
                    policy,sid,ids = p['policy'],p['case_id'],p['candidate_ids']
                    query = reqs[sid]['query'].strip()
                    passages = [serialise_v0(by_id[i]) for i in ids]
                    scores = {}; start=time.perf_counter();used_cache=0;new_pairs=0
                    for offset in range(0,len(ids),4):
                        batch_ids=ids[offset:offset+4];batch=passages[offset:offset+4]
                        tokenized = model.tokenizer([query]*len(batch),batch,padding=True,
                            truncation='only_second',max_length=512,return_tensors='pt')
                        tensors={k:v.tolist() for k,v in tokenized.items()}
                        lengths=[model.lengths(t,query) for t in batch]
                        raw_hashes=[{'query_sha256':digest(query.encode()),'passage_sha256':digest(t.encode())} for t in batch]
                        batch_key=batch_identity(model_identity,raw_hashes,tensors)
                        reused = batch_key in cache
                        batch_id=f'{policy}::{sid}::{offset:02d}'
                        # Full text + full padded tensors stay local, never in review ZIP/Git.
                        append_json(LOCAL/'EFFECTIVE_INPUTS.jsonl',{
                            'batch_id':batch_id,'identity':batch_key,'query':query,'passages':batch,
                            'chunk_ids':batch_ids,'tensors':tensors,'model_config_identity':model_identity})
                        if reused:
                            values,origin=cache[batch_key];used_cache+=len(batch)
                            receipt['cache_reused_pair_uses']+=len(batch)
                        else:
                            current=model_processes()
                            append_json(OUT/'RESOURCE_RECHECKS.jsonl',{'time_utc':now(),'batch_id':batch_id,'processes':current})
                            if any(x['blocks_inference'] for x in current):
                                raise RuntimeError('DEFERRED_LOCAL_INFERENCE_RESOURCE')
                            receipt['new_pair_attempts']=admit_pairs(receipt['new_pair_attempts'],len(batch))
                            append_json(OUT/'EXECUTION_JOURNAL.jsonl',{'state':'RESERVED_BEFORE_FORWARD',
                                'time_utc':now(),'batch_id':batch_id,'pairs':len(batch),'identity':batch_key,
                                'cumulative_attempted':receipt['new_pair_attempts']})
                            with model.torch.inference_mode():
                                values=model.model(**tokenized).logits.reshape(-1).tolist()
                            if len(values)!=len(batch) or any(not math.isfinite(s) for s in values):
                                append_json(OUT/'EXECUTION_JOURNAL.jsonl',{'state':'NONFINITE_STOP',
                                    'batch_id':batch_id,'finite_flags':[math.isfinite(s) for s in values]})
                                raise ValueError('NONFINITE_STOP_NO_RETRY')
                            origin=batch_id;cache[batch_key]=(values,origin)
                            receipt['new_pair_scores']+=len(batch);new_pairs+=len(batch)
                            append_json(OUT/'EXECUTION_JOURNAL.jsonl',{'state':'FINITE_SCORES_COMMITTED',
                                'time_utc':now(),'batch_id':batch_id,'identity':batch_key,
                                'chunk_ids':batch_ids,'scores':values})
                        for j,(ident,value) in enumerate(zip(batch_ids,values)):
                            scores[ident]=value
                            pair={'policy':policy,'case_id':sid,'chunk_id':ident,'score':value,
                                  'batch_id':batch_id,'batch_identity':batch_key,'batch_row':j,
                                  'effective_tensor_row_sha256':digest(canonical({k:v[j] for k,v in tensors.items()})),
                                  'padded_tokens':len(tensors['input_ids'][j]),**raw_hashes[j],**lengths[j],
                                  'cache_reused':reused,'score_origin_batch':origin}
                            pair_audits.append(pair)
                        append_json(OUT/'CACHE_RECEIPTS.jsonl',{'batch_id':batch_id,'identity':batch_key,
                            'cache_hit':reused,'origin':origin,'pairs':len(batch),
                            'identity_scope':'complete ordered padded tensor batch and model/config/raw query/passage hashes'})
                    ranked=rank_scores(ids,scores)
                    row={'policy':policy,'case_id':sid,'query_sha256':p['query_sha256'],
                         'candidate_ids':ids,'candidate_ids_sha256':p['candidate_ids_sha256'],
                         'ranked_ids':ranked,'scores':[scores[i] for i in ranked],'top5_ids':ranked[:5],
                         'new_pair_scores':new_pairs,'cache_reused_pair_uses':used_cache,
                         'scoring_and_audit_elapsed_ms':(time.perf_counter()-start)*1000,
                         'status':'UNVALIDATED_RETRIEVAL_ONLY' if ids else 'EMPTY_SAVED_R0_POOL',
                         'native_returned_ids':[],'source_sufficiency':None,'human_response_quality':None}
                    rankings.append(row);receipt['accepted_policy_case_rankings']+=1
                    write_json(OUT/f'{policy}_{sid}.json',row,exclusive=True)
                    write_json(OUT/'PAIR_SCORES_AND_TOKEN_AUDIT.json',pair_audits)
                    write_json(OUT/'EXECUTION_RECEIPT.json',receipt)
                    print(policy,sid,'pairs',len(ids),'new',new_pairs,'cache',used_cache,flush=True)
                write_json(OUT/'RANKINGS.json',rankings,exclusive=True)
                receipt.update(status='COMPLETED_BOUNDED_DIAGNOSTIC',finished_utc=now(),network_guard=network_guard,
                               local_effective_inputs=source_receipt(LOCAL/'EFFECTIVE_INPUTS.jsonl','PRIVATE_EXACT_INPUT_LEDGER_EXCLUDED_FROM_REVIEW'),
                               model_config_identity=model_identity)
                del model
    except Exception as exc:
        receipt.update(status='DEFERRED_COMPUTE' if 'DEFERRED_' in str(exc) else 'STOPPED_FAILURE_NO_RETRY',
                       error_type=type(exc).__name__,error=str(exc),finished_utc=now())
        write_json(OUT/'EXECUTION_RECEIPT.json',receipt)
        raise
    write_json(OUT/'EXECUTION_RECEIPT.json',receipt)
    print(json.dumps(receipt,indent=2))

if __name__ == '__main__':
    main()
