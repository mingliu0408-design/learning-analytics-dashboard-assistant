"""Verified A/A1 indexes; canonical selection never falls back to old versions."""
from recovery import *
from parent_ledger import ParentLedger
import zipfile

PARENT_RESULTS = A1/'results'
PARENT_ARCHIVE = Path('/Users/liuming/Downloads/RQ3_CONFIRMED41_REPAIR_CONTINUATION_REVIEW_2026-09-08.zip')


class LayeredLedger:
    def __init__(self):
        policy = load(HERE/'RECOVERY_POLICY.json')
        if sha(PARENT_ARCHIVE.read_bytes()) != policy['parent_archive_sha256']:
            raise StopRun('PARENT_ARCHIVE_CHANGED')
        self.files = {}
        with zipfile.ZipFile(PARENT_ARCHIVE) as z:
            if z.testzip() is not None:
                raise StopRun('PARENT_ARCHIVE_CRC')
            manifest = json.loads(z.read('MANIFEST.json'))
            prefix = str(A1.relative_to(ROOT))+'/'
            for e in manifest['members']:
                if e['path'].startswith(prefix):
                    p = ROOT/e['path']
                    if p.is_symlink() or p.stat().st_size != e['bytes'] or sha(p.read_bytes()) != e['sha256']:
                        raise StopRun('PARENT_FILE_IDENTITY_CHANGED:'+e['path'])
                    self.files[e['path']] = dict(e)
        self.a = ParentLedger()
        self.runs = {'A':self.a.root, 'A1':PARENT_RESULTS/'run'}
        self.bindings = {run:sha((root/'RUN_BINDING.json').read_bytes()) for run,root in self.runs.items()}
        self.terminals, self.starts, self.stages = {}, {}, {}
        for run, root in self.runs.items():
            for p in (root/'attempts').glob('*.start.json'):
                s = load(p)
                self.starts[(run,s['attempt_id'])] = s
            for p in (root/'terminals').glob('*.json'):
                t = load(p)
                self.terminals[(run,t['logical'])] = (p,t)
            for p in (root/'stages').glob('*.json'):
                s = load(p)
                self.stages[(run,s['logical'],s['stage'])] = (p,s)
        self.physical_calls = len(self.starts)
        self.budget_debit = max(.5533299, sum(debit([s for (r,a),s in self.starts.items() if r==run],root,
            {'input':.15,'output':.6}) for run,root in self.runs.items()))
        self.slots = rows(PARENT_RESULTS/'RESPONSE_HANDOFF.jsonl')
        lineage = {r['declared_slot_key']:r for r in rows(PARENT_RESULTS/'RESULT_LINEAGE_246.jsonl')}
        self.selected = {}
        self.index = []
        if len(self.slots)!=246 or len(lineage)!=246 or self.physical_calls!=277:
            raise StopRun('PARENT_COUNTS_CHANGED')
        for r in self.slots:
            assert r['status']==lineage[r['declared_slot_key']]['current_status']
            assert r['answer_sha256']==lineage[r['declared_slot_key']]['selected_answer_sha256']
            for k in ('raw_response','response_record'):
                if r[k+'_path']:
                    assert sha((PARENT_RESULTS/r[k+'_path']).read_bytes())==r[k+'_sha256']
            assert r['human_scores']==[]
            if r['status']=='ACCEPTED':
                run = 'A' if r['selected_run']=='PARENT' else 'A1'
                logical = r['declared_slot_key']+':FINAL'
                self.selected[logical] = run
                payload = self.payload(run,logical)
                result,receipt = self.verify(run,logical,'FINAL',payload)
                assert r['answer']==result['value']['answer']
                raw = load(self.runs[run]/'attempts'/f"{result['attempt_id']}.raw.json")
                assert json.loads(raw['choices'][0]['message']['content'])['answer']==r['answer']
                assert sha(r['answer'].encode())==r['answer_sha256']
                self.index.append(receipt)
        for (run,logical),(p,t) in self.terminals.items():
            role = self.starts[(run,t['attempt_id'])]['role']
            if role != 'FINAL' and t['result']['status']=='ACCEPTED':
                assert logical not in self.selected
                self.selected[logical]=run
                _,receipt=self.verify(run,logical,role,self.payload(run,logical))
                self.index.append(receipt)
        counts=Counter(x['role'] if x['role'] in ('FINAL','CANDIDATE') else 'ROUTE' for x in self.index)
        if counts!={'FINAL':180,'CANDIDATE':8,'ROUTE':81}:
            raise StopRun('CANONICAL_PARENT_SELECTION_CHANGED')
        statuses=Counter(load(self.runs[run]/'attempts'/f'{aid}.outcome.json')['status'] for run,aid in self.starts)
        assert statuses=={'ACCEPTED':275,'UNKNOWN_COMPLETION':2}
        self.identity=sha(dict(files=self.files,run_bindings=self.bindings,selection=self.selected))
        self.unknown_permission(CURRENT_UNKNOWN, self.starts[('A1',sha(CURRENT_UNKNOWN)+'.1')]['request'])

    def payload(self,run,logical):
        t=self.terminals[(run,logical)][1]
        return self.starts[(run,t['attempt_id'])]['request']

    def verify(self,run,logical,role,payload):
        root=self.runs[run];tp,t=self.terminals[(run,logical)]
        s=self.starts[(run,t['attempt_id'])]
        assert s['logical']==logical and s['role']==role and s['request']==payload
        assert sha(payload)==s['request_sha256']==t['initial_request_sha256']
        op=root/'attempts'/f"{s['attempt_id']}.outcome.json"
        rp=root/'attempts'/f"{s['attempt_id']}.raw.json"
        o=load(op)
        assert o==t['result'] and o['status']=='ACCEPTED'
        assert sha(op.read_bytes())==t['outcome_sha256'] and sha(rp.read_bytes())==o['raw_sha256']
        receipt=dict(source_run=run,source_run_binding_sha256=self.bindings[run],logical=logical,role=role,
            attempt_id=s['attempt_id'],attempt_identity=[self.bindings[run],s['attempt_id']],
            payload_sha256=sha(payload),reuse_basis='EXACT_PAYLOAD_ACCEPTED_RECEIPTS_CANONICAL_SELECTION',
            files=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p.read_bytes()),bytes=p.stat().st_size)
                for p in (tp,op,rp,root/'attempts'/f"{s['attempt_id']}.start.json")])
        return deepcopy(o),receipt

    def accepted(self,logical,role,payload):
        if logical not in self.selected:
            return None
        run=self.selected[logical]
        if self.payload(run,logical)!=payload:
            raise StopRun('ACCEPTED_PAYLOAD_CHANGED_RESEND_FORBIDDEN:'+logical)
        return self.verify(run,logical,role,payload)

    def module(self,logical):
        for run in ('A1','A'):
            found=self.stages.get((run,logical,'MODULES'))
            if found:
                return run,found[0],deepcopy(found[1]['output'])
        return None

    def unknown_permission(self,logical,payload):
        aid=sha(CURRENT_UNKNOWN)+'.1'
        assert logical==CURRENT_UNKNOWN and logical not in self.selected
        s=self.starts[('A1',aid)]
        op=self.runs['A1']/'attempts'/f'{aid}.outcome.json'
        assert load(op)['status']=='UNKNOWN_COMPLETION'
        assert sha(payload)==CURRENT_UNKNOWN_HASH and payload==s['request']
        return dict(source_run='A1',source_run_binding_sha256=self.bindings['A1'],attempt_id=aid,
            source_attempt_identity=[self.bindings['A1'],aid],request_sha256=CURRENT_UNKNOWN_HASH,
            historical_reserved_usd=s['reserved_usd_upper_bound'],historical_status='UNKNOWN_COMPLETION',
            additional_physical_attempts_allowed=1,possible_duplicate_completion_and_billing_accepted=True)
