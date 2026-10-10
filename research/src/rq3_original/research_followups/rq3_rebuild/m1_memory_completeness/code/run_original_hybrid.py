"""Separate M0 exposed-fixture hybrid diagnostic with the verified existing runtime."""
import json
import sys
from pathlib import Path
from m1_common import OWNED, write_json, sha
import run_diagnostics as m0
from local_backend import LocalBackend
from probe_runtimes import snapshot

def main():
    out=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
    out.relative_to(OWNED)
    summary=json.loads((OWNED/'runtime_diagnostics/stages_v1/SUMMARY.json').read_text())
    python=summary['working_interpreters'][0]
    before=snapshot();backend=None
    def verified_backend():
        nonlocal backend
        backend=LocalBackend(python,out)
        return backend, {'status':'ENCODE_VERIFIED_BEFORE_RETRIEVAL','interpreter':python,
                         'readiness':backend.ready,'snapshot_files':before,
                         'worker_script_sha256':sha(OWNED/'code/native_stage_worker.py')}
    m0.OWNED=OWNED
    m0.runtime_backend=verified_backend
    try:m0.main()
    finally:
        if backend:
            backend.close()
            write_json(out/'ENCODING_RECEIPTS.json',{'encode_calls':backend.inputs,
                        'worker_exit_code':backend.process.returncode})
    # M0's summary writer adds unchanged_after_diagnostics to receipt dictionaries.
    after=snapshot()
    assert [{k:v for k,v in x.items() if k!='unchanged_after_diagnostics'} for x in before]==after

if __name__=='__main__':main()
