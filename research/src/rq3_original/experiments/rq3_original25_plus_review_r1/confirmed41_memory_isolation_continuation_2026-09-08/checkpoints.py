"""Verified A/A1 indexes; canonical selection never falls back to old versions."""
from recovery import *
from parent_ledger import ParentLedger
import zipfile

PARENT_RESULTS = A2/'results'
PARENT_ARCHIVE = Path('external_inputs/historical_archives/RQ3_CONFIRMED41_REMAINING_GENERATION_REVIEW_2026-09-08.zip')


class LayeredLedger:
    def __init__(self):
        policy = load(HERE/'RECOVERY_POLICY.json')
        if sha(PARENT_ARCHIVE.read_bytes()) != policy['parent_archive_sha256']:
            raise StopRun('PARENT_ARCHIVE_CHANGED')
        self.files = {}
        archives = [
            (Path('external_inputs/historical_archives/RQ3_CONFIRMED41_REPAIR_CONTINUATION_REVIEW_2026-09-08.zip'),
             'c485f191b9869fbd0ca4ff20e2a9cf5e0aa077cdce019e67e18139a9dd4f3a93', None),
            (PARENT_ARCHIVE, policy['parent_archive_sha256'], A2)]
        for archive, expected, local_root in archives:
            assert sha(archive.read_bytes()) == expected
            with zipfile.ZipFile(archive) as z:
                assert z.testzip() is None and len(z.namelist()) == len(set(z.namelist()))
                manifest = json.loads(z.read('MANIFEST.json'))
                for e in manifest['members']:
                    from pathlib import PurePosixPath
                    rel = PurePosixPath(e['path'])
                    assert not rel.is_absolute() and '..' not in rel.parts
                    raw=z.read(e['path'])
                    assert len(raw)==e['bytes'] and sha(raw)==e['sha256']
                    if local_root is None:
                        if not e['path'].startswith(str(A1.relative_to(ROOT))+'/'):continue
                        p=ROOT/e['path']
                    else:
                        if e['path'] in ('README.md','GIT_LINEAGE.json','CONTROL_PATCH.diff'):continue
                        p=local_root/e['path']
                    if p.is_symlink() or not p.is_file() or p.read_bytes()!=raw:
                        raise StopRun('PARENT_FILE_IDENTITY_CHANGED:'+str(p.relative_to(ROOT)))
                    self.files[str(p.relative_to(ROOT))]=dict(bytes=len(raw),sha256=sha(raw))
        self.a = ParentLedger()
        self.runs = {'A':self.a.root, 'A1':A1/'results/run', 'A2':PARENT_RESULTS/'run'}
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
        self.budget_debit = max(policy['historical_budget_debit_usd'], sum(debit([s for (r,a),s in self.starts.items() if r==run],root,
            {'input':.15,'output':.6}) for run,root in self.runs.items()))
        self.slots = rows(PARENT_RESULTS/'RESPONSE_HANDOFF.jsonl')
        lineage = {r['declared_slot_key']:r for r in rows(PARENT_RESULTS/'RESULT_LINEAGE_246.jsonl')}
        self.selected = {}
        self.index = []
        if len(self.slots)!=246 or len(lineage)!=246 or self.physical_calls!=286:
            raise StopRun('PARENT_COUNTS_CHANGED')
        for r in self.slots:
            assert r['status']==lineage[r['declared_slot_key']]['status']
            assert r['answer_sha256']==lineage[r['declared_slot_key']]['answer_sha256']
            for k in ('raw_response','response_record'):
                if r[k+'_path']:
                    assert sha((PARENT_RESULTS/r[k+'_path']).read_bytes())==r[k+'_sha256']
            assert r['human_scores']==[]
            if r['status']=='ACCEPTED':
                run = r['selected_run']
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
        if counts!={'FINAL':183,'CANDIDATE':8,'ROUTE':81}:
            raise StopRun('CANONICAL_PARENT_SELECTION_CHANGED')
        statuses=Counter(load(self.runs[run]/'attempts'/f'{aid}.outcome.json')['status'] for run,aid in self.starts)
        assert statuses=={'ACCEPTED':278,'UNKNOWN_COMPLETION':8}
        self.identity=sha(dict(files=self.files,run_bindings=self.bindings,selection=self.selected))
        for logical,e in EXISTING_UNKNOWNS.items():
            self.unknown_permission(logical,self.starts[('A2',e['prior_attempt_ids'][0])]['request'])

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
        for run in ('A2','A1','A'):
            found=self.stages.get((run,logical,'MODULES'))
            if found:
                return run,found[0],deepcopy(found[1]['output'])
        return None

    def unknown_permission(self,logical,payload):
        e=EXISTING_UNKNOWNS[logical]
        assert logical not in self.selected and sha(payload)==e['request_sha256']
        receipts=[]
        for aid in e['prior_attempt_ids']:
            s=self.starts[('A2',aid)]
            op=self.runs['A2']/'attempts'/f'{aid}.outcome.json'
            assert s['logical']==logical and s['role']==e['role'] and s['request']==payload
            assert load(op)['status']=='UNKNOWN_COMPLETION'
            receipts.append(dict(attempt_id=aid,status='UNKNOWN_COMPLETION',
                reserved_usd_upper_bound=s['reserved_usd_upper_bound'],outcome_sha256=sha(op.read_bytes())))
        return dict(source_run='A2',source_run_binding_sha256=self.bindings['A2'],prior_attempts=receipts,
            request_sha256=sha(payload),additional_physical_attempts_allowed=1,
            authorization='DIRECT_USER_REPAIR_AND_CONTINUE_AFTER_DIAGNOSIS',
            historical_status_and_reservations_preserved=True,possible_duplicate_completion_and_billing=True)
