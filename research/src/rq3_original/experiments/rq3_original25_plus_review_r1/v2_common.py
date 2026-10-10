"""Local, source-only helpers. No transport or credential discovery."""
from pathlib import Path
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V1 = HERE.with_name('rq3_original25_plus')
START_HEAD = 'd051906c55eadfebd2efcca5020fed43abf2871b'
VERSION = 'ORIGINAL25_PLUS_EN_V2'
sys.dont_write_bytecode = True
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def read(path): return json.loads(Path(path).read_text())
def lines(path): return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def sha(value): return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
def jsonl(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False)+'\n' for r in rows))
def file_id(path, base=HERE):
    path = Path(path)
    return dict(path=str(path.relative_to(base)), bytes=path.stat().st_size, sha256=sha(path.read_bytes()))
def checked(entry, base=HERE):
    p = (base/entry['path']).resolve()
    if not p.is_relative_to(base.resolve()) or p.is_symlink() or sha(p.read_bytes()) != entry['sha256']:
        raise ValueError('BOUND_SOURCE_CHANGED:'+str(p))
    return p
def pointer(obj, p):
    for k in p.strip('/').split('/'):
        k = k.replace('~1', '/').replace('~0', '~')
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj
def offline():
    def guard(event, args):
        if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.bind', 'socket.sendto'):
            raise RuntimeError('NO_NETWORK_THIS_PREPARATION')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            name = str(args[0]).lower()
            if Path(name).name in ('.env', 'auth.json', 'credentials.json') or 'api_key' in name or 'api-key' in name:
                raise RuntimeError('NO_CREDENTIAL_READ_THIS_PREPARATION')
    sys.addaudithook(guard)
