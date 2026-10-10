"""Only authorised official immutable MiniLM files, <=300 MB, no user data."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import CE_ROOT, CE_REVISION, OUT, file_hash, write_json

REPO = 'cross-encoder/ms-marco-MiniLM-L6-v2'
NAMES = ('README.md', 'config.json', 'model.safetensors', 'special_tokens_map.json',
         'tokenizer.json', 'tokenizer_config.json', 'vocab.txt')
CAP = 300_000_000

def main():
    import psutil
    url = f'https://huggingface.co/api/models/{REPO}/revision/{CE_REVISION}?blobs=true'
    with urllib.request.urlopen(url, timeout=30) as r:
        meta = json.load(r)
    assert meta['sha'] == CE_REVISION
    files = {v['rfilename']: v for v in meta['siblings']}
    wanted = [files[n] for n in NAMES]
    total = sum(v['size'] for v in wanted)
    ram = dict(psutil.virtual_memory()._asdict())
    disk = shutil.disk_usage(OUT)
    assert total <= CAP and disk.free > total * 3 and ram['available'] > 400_000_000
    preflight = {'repo': REPO, 'revision': CE_REVISION, 'license': meta['cardData']['license'],
        'official_api': url, 'required_files': wanted, 'planned_bytes': total, 'cap_bytes': CAP,
        'ram_before': ram, 'free_disk_bytes_before': disk.free, 'trust_remote_code': False,
        'source_or_query_bytes_sent': 0, 'new_weight_formats': ['safetensors']}
    write_json(OUT / 'CROSS_ENCODER_DOWNLOAD_PREFLIGHT.json', preflight)
    CE_ROOT.mkdir(parents=True, exist_ok=True)
    received, receipt = 0, []
    for item in wanted:
        path = CE_ROOT / item['rfilename']
        if path.exists():
            raise FileExistsError('Refusing silent download repetition: ' + str(path))
        url = f'https://huggingface.co/{REPO}/resolve/{CE_REVISION}/{item["rfilename"]}'
        with urllib.request.urlopen(url, timeout=60) as response, path.open('xb') as f:
            written = 0
            while True:
                b = response.read(1024 * 1024)
                if not b:
                    break
                received += len(b)
                written += len(b)
                if received > CAP or written > item['size']:
                    raise RuntimeError('DOWNLOAD_BUDGET_OR_SIZE_EXCEEDED')
                f.write(b)
        assert path.stat().st_size == item['size']
        h = file_hash(path)
        if 'lfs' in item:
            assert h == item['lfs']['sha256']
        else:
            data = path.read_bytes()
            assert hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() == item['blobId']
        receipt.append({'name': item['rfilename'], 'bytes': path.stat().st_size, 'sha256': h})
        print(item['rfilename'], written, flush=True)
    write_json(OUT / 'CROSS_ENCODER_DOWNLOAD_RECEIPT.json',
               {**preflight, 'files': receipt, 'fetched_bytes': received, 'status': 'VERIFIED'})

if __name__ == '__main__':
    main()
