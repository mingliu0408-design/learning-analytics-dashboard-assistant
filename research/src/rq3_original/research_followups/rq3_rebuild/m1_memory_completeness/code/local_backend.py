"""CPU encoder in a bounded local stdio worker; no remote model/API provider."""
import json
import os
import select
import subprocess
from m1_common import OWNED, object_sha, utc
from probe_runtimes import MODEL, child_env

class LocalBackend:
    def __init__(self, python, output):
        self.events=[];self.buffer=b'';self.inputs=[]
        self.stderr=(output/'WORKER_STDERR.txt').open('w')
        self.process=subprocess.Popen([python,'-B',str(OWNED/'code/native_stage_worker.py'),'serve',str(MODEL)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,env=child_env(),cwd=OWNED)
        try:
            while True:
                row=self.receive();self.events.append(row)
                if row.get('event')=='ENCODE_VERIFIED':
                    self.ready=row;break
        except BaseException:
            self.close();raise
    def receive(self):
        while b'\n' not in self.buffer:
            if not select.select([self.process.stdout],[],[],90)[0]:
                raise TimeoutError('LOCAL_ENCODER_TIMEOUT')
            block=os.read(self.process.stdout.fileno(),65536)
            if not block: raise RuntimeError('LOCAL_ENCODER_EXIT:'+str(self.process.wait()))
            self.buffer+=block
        line,self.buffer=self.buffer.split(b'\n',1)
        return json.loads(line)
    @property
    def identity(self): return self.ready['identity']
    def encode(self,texts):
        texts=list(texts)
        # All authorized fixture strings are already stripped. No hidden prompts or IDs.
        if any(not isinstance(t,str) or t!=t.strip() for t in texts):
            raise ValueError('SERIALIZATION_BOUNDARY_REQUIRES_EXPLICIT_REVIEW')
        payload=json.dumps({'texts':texts},ensure_ascii=False).encode()+b'\n'
        self.process.stdin.write(payload);self.process.stdin.flush()
        row=self.receive()
        assert row['input_sha256']==object_sha(texts)
        self.inputs.append({'execution_utc':utc(),'texts_sha256':row['input_sha256'],
                            'text_count':len(texts),'vector_count':len(row['vectors'])})
        return row['vectors']
    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        if not self.process.stdout.closed:self.process.stdout.close()
        if not self.process.stdin.closed:self.process.stdin.close()
        if not self.stderr.closed:self.stderr.close()
