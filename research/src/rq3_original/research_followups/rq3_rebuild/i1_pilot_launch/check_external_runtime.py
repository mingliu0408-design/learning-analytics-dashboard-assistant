"""Read-only file hashes and interpreter identities; no model import/forward."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,sha,write_once
from utils.c4_memory.c4_memory_retriever import MPNET_REVISION,MPNET_REQUIRED_HASHES


def main():
    legacy=Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3')
    model=legacy/'semantic_runtime/models/all-mpnet-base-v2'/MPNET_REVISION
    rows=[]
    for name,expected in MPNET_REQUIRED_HASHES.items():
        p=model/name;data=p.read_bytes() if p.is_file() else None
        rows.append(dict(path=str(p),exists=data is not None,sha256=sha(data) if data else None,
            expected_sha256=expected,bytes=len(data) if data else None,
            status='PASS' if data and sha(data)==expected else 'UNAVAILABLE_OR_MISMATCH'))
    interpreters=[]
    for p in (Path(sys.executable),Path('/opt/anaconda3/bin/python3'),legacy/'.venv/bin/python'):
        real=p.resolve();out=subprocess.run([str(p),'-B','-c','import sys; print(sys.version)'],capture_output=True,text=True,timeout=10)
        interpreters.append(dict(path=str(p),resolved_path=str(real),sha256=sha(real.read_bytes()),
            version=out.stdout.strip(),returncode=out.returncode))
    result=dict(status='AVAILABLE_HASH_CHECKED' if all(x['status']=='PASS' for x in rows) else 'OPTIONAL_UNAVAILABLE',
        models=rows,interpreters=interpreters,model_forward_calls=0,provider_calls=0,
        environment_installs=0,downloads=0,native_hybrid_execution='NOT_RUN_IN_I1')
    write_once(HOME/'EXTERNAL_RUNTIME_RECEIPT.json',result)
    print(result['status'])


if __name__=='__main__':main()
