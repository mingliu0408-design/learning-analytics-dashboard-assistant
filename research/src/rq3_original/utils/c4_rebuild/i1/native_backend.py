"""Future local hybrid encoder bridge; one bounded worker, isolated temporary cache."""
import json
import os
import select
import subprocess
import time
from .common import ROOT, sha

import sys
PYTHON = os.environ.get('LAD_MODEL_PYTHON', sys.executable)


class I1LocalBackend:
    def __init__(self, output):
        from utils.c4_memory.c4_memory_retriever import MPNET_REVISION
        model = os.environ.get('LAD_MPNET_PATH', str(ROOT/'external_inputs/models/all-mpnet-base-v2'/MPNET_REVISION))
        worker = ROOT/'research_followups/rq3_rebuild/m1_memory_completeness/code/native_stage_worker.py'
        env = {k: os.environ[k] for k in ('PATH','TMPDIR','LANG','LC_CTYPE','LC_ALL') if k in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
            HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',
            OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',XDG_CACHE_HOME=str(output/'cache'),
            MPLCONFIGDIR=str(output/'matplotlib'))
        self.stderr = (output/'ENCODER_STDERR.txt').open('w')
        self.buffer=b'';self.inputs=[]
        self.process = subprocess.Popen([PYTHON,'-B',str(worker),'serve',model],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,env=env,cwd=ROOT)
        deadline=time.monotonic()+90
        try:
            while True:
                row=self.receive(deadline)
                if row.get('event')=='ENCODE_VERIFIED':
                    self.ready=row
                    break
        except BaseException:
            self.close()
            raise

    @property
    def identity(self):return self.ready['identity']

    def receive(self,deadline):
        while b'\n' not in self.buffer:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([self.process.stdout],[],[],remaining)[0]:
                raise TimeoutError('I1_LOCAL_ENCODER_TIMEOUT')
            block=os.read(self.process.stdout.fileno(),65536)
            if not block:
                raise RuntimeError('I1_LOCAL_ENCODER_EXIT')
            self.buffer+=block
        line,self.buffer=self.buffer.split(b'\n',1)
        return json.loads(line)

    def encode(self,texts):
        texts=list(texts)
        if any(not isinstance(t,str) or t!=t.strip() for t in texts):
            raise ValueError('ENCODER_SERIALIZATION_SCOPE')
        self.process.stdin.write(json.dumps({'texts':texts},ensure_ascii=False).encode()+b'\n')
        self.process.stdin.flush()
        row=self.receive(time.monotonic()+30)
        if row['input_sha256']!=sha(texts):
            raise ValueError('ENCODER_INPUT_RECEIPT')
        self.inputs.append(dict(input_sha256=sha(texts),count=len(texts)))
        return row['vectors']

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill();self.process.wait(timeout=5)
        self.process.stdout.close()
        if not self.process.stdin.closed:self.process.stdin.close()
        self.stderr.close()
