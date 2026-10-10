"""Read-only parent results and a thin DurableRunner continuation boundary."""
from a1_common import *
from collections import Counter
from copy import deepcopy
from utils.c4_rebuild.i1.durable import DurableRunner,StopRun


def debit(starts,directory,rates):
    total=0.0
    for s in starts:
        p=directory/'attempts'/f"{s['attempt_id']}.outcome.json"
        usage=load(p).get('usage') if p.exists() else None
        observed=0.0
        if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens')):
            observed=(usage['prompt_tokens']*rates['input']+usage['completion_tokens']*rates['output'])/1e6
        total+=max(s['reserved_usd_upper_bound'],observed)
    return total


class ParentLedger:
    def __init__(self,root=PARENT_RUN,verify=True):
        self.root=Path(root);self.policy=policy();self.binding=load(self.root/'RUN_BINDING.json')
        if verify:
            assert sha((self.root/'RUN_BINDING.json').read_bytes())==self.policy['parent_binding_sha256']
            assert self.binding['git_head']==self.policy['parent_execution_head'] and self.binding['transport_kind']=='LIVE'
            manifest=load(PARENT/'GENERATION_HANDOFF_MANIFEST.json')
            covered={}
            for e in manifest['result_files']:
                if e['path'].startswith('run/'):
                    p=self.root/e['path'][4:];assert sha(p.read_bytes())==e['sha256'] and p.stat().st_size==e['bytes'];covered[str(p.relative_to(self.root))]=e['sha256']
            actual={str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file() and p.name!='RUN.lock'}
            assert actual==set(covered)
            self.identity=sha(covered)
        else:self.identity='ENGINEERING_FIXTURE_ONLY'
        self.starts={}
        for p in (self.root/'attempts').glob('*.start.json'):
            s=load(p);self.starts.setdefault(s['logical'],[]).append(s)
        for v in self.starts.values():v.sort(key=lambda r:r['attempt'])
        self.terminals={load(p)['logical']:(p,load(p)) for p in (self.root/'terminals').glob('*.json')}
        self.stages={(s['logical'],s['stage']):(p,s) for p,s in [(p,load(p)) for p in (self.root/'stages').glob('*.json')]}
        self.budget_debit=max(self.policy['historical_minimum_budget_debit_usd'],debit([s for v in self.starts.values() for s in v],self.root,self.policy['uncached_usd_per_million']))
        if verify:
            assert sum(map(len,self.starts.values()))==256
            statuses=Counter(load(self.root/'attempts'/f"{s['attempt_id']}.outcome.json")['status'] for v in self.starts.values() for s in v)
            assert statuses=={'ACCEPTED':255,'UNKNOWN_COMPLETION':1}

    def accepted(self,logical,role,payload):
        if logical not in self.terminals:return None
        path,t=self.terminals[logical];s=next(s for s in self.starts[logical] if s['attempt_id']==t['attempt_id'])
        assert s['role']==role and payload==s['request'] and sha(payload)==s['request_sha256']==t['initial_request_sha256']
        op=self.root/'attempts'/f"{s['attempt_id']}.outcome.json";rp=self.root/'attempts'/f"{s['attempt_id']}.raw.json"
        outcome=load(op);assert outcome==t['result'] and sha(op.read_bytes())==t['outcome_sha256']
        assert outcome['status']=='ACCEPTED' and sha(rp.read_bytes())==outcome['raw_sha256']
        receipt=dict(parent_run_binding_sha256=sha((self.root/'RUN_BINDING.json').read_bytes()),parent_ledger_sha256=self.identity,
            logical=logical,role=role,payload_sha256=sha(payload),parent_attempt_id=s['attempt_id'],
            files=[file_entry(p,self.root) for p in (path,op,rp,self.root/'attempts'/f"{s['attempt_id']}.start.json")],
            reuse_basis='COMPLETE_PROVIDER_PAYLOAD_EQUAL_AND_PARENT_ACCEPTED_RECEIPTS_VERIFIED',new_provider_calls=0)
        return deepcopy(outcome),receipt

    def unknown_permission(self,logical,payload):
        matches=[u for u in self.policy['parent_unknown_authorizations'] if u['logical']==logical]
        if len(matches)!=1:raise StopRun('PARENT_UNKNOWN_NOT_AUTHORIZED')
        u=matches[0];ss=self.starts.get(logical,[])
        if len(ss)!=1:raise StopRun('PARENT_UNKNOWN_ATTEMPT_COUNT')
        s=ss[0];o=load(self.root/'attempts'/f"{s['attempt_id']}.outcome.json")
        if (s['attempt_id']!=u['attempt_id'] or o['status']!='UNKNOWN_COMPLETION' or s['request']!=payload
                or sha(payload)!=u['request_sha256'] or logical in self.terminals):raise StopRun('PARENT_UNKNOWN_IDENTITY_MISMATCH')
        return dict(parent_run_binding_sha256=sha((self.root/'RUN_BINDING.json').read_bytes()),parent_attempt_id=s['attempt_id'],
            parent_status='UNKNOWN_COMPLETION',parent_reserved_usd=s['reserved_usd_upper_bound'],new_run_attempt_allowance=1,
            cumulative_slot_attempt=2,parent_unknown_may_have_completed_or_been_billed=True,payload_sha256=sha(payload))


class ContinuationRunner(DurableRunner):
    def __init__(self,directory,config,binding,transport,parent,**kwargs):
        self.parent=parent;self.policy=policy();self.single_final={s+':FINAL' for s in self.policy['replacement_slots']}|{u['logical'] for u in self.policy['parent_unknown_authorizations']}
        # Empty inherited whitelist is essential: even a new unknown with the
        # same per-run attempt name must stop. Parent permission is run-scoped.
        super().__init__(directory,config,binding,transport,unknown_authorizations=(),**kwargs)

    def reserve(self,logical,role,attempt,payload,initial_hash):
        if logical in self.single_final and attempt>1:raise StopRun('A1_SINGLE_ATTEMPT_SLOT_CEILING')
        starts=[load(p) for p in (self.directory/'attempts').glob('*.start.json')]
        if self.policy['historical_physical_attempts']+len(starts)>=self.policy['cumulative_physical_ceiling']:
            raise StopRun('A1_CUMULATIVE_PHYSICAL_CEILING')
        rates=self.config['uncached_usd_per_million']
        next_debit=((len(canonical(payload))+256)*rates['input']+payload['max_tokens']*rates['output'])/1e6
        if self.parent.budget_debit+debit(starts,self.directory,rates)+next_debit>self.policy['cumulative_money_ceiling_usd']:
            raise StopRun('A1_CUMULATIVE_MONEY_CEILING_NO_TRANSPORT')
        return super().reserve(logical,role,attempt,payload,initial_hash)

    def reuse(self,logical,role,payload):
        found=self.parent.accepted(logical,role,payload)
        if not found:return None
        result,receipt=found
        self.stage(logical,'PARENT_REUSE',dict(new_binding=sha(self.identity),payload=sha(payload)),receipt)
        append(self.directory/'PARENT_REUSE_RECEIPTS.jsonl',receipt)
        return result,receipt

    def perform(self,logical,role,payload,validator=lambda x:[],repair=None):
        if logical in self.parent.terminals:
            parent_start=self.parent.starts[logical][-1]
            if payload==parent_start['request']:
                return self.reuse(logical,role,payload)[0]
            if role!='FINAL' or logical.removesuffix(':FINAL') not in self.policy['replacement_slots']:
                raise StopRun('ACCEPTED_PARENT_RESEND_FORBIDDEN')
            self.stage(logical,'REPLACEMENT_INPUT_DEPENDENCY',dict(new_payload=sha(payload)),
                dict(parent_payload_sha256=parent_start['request_sha256'],new_payload_sha256=sha(payload),
                     reason='FROZEN_PLANNING_INTERFACE_INPUT_CHANGED_NOT_OUTPUT_QUALITY',parent_preserved=True))
        elif logical in self.parent.starts:
            permission=self.parent.unknown_permission(logical,payload)
            self.stage(logical,'PARENT_UNKNOWN_AUTHORIZED_NEXT_ATTEMPT',dict(new_binding=sha(self.identity)),permission)
        # Per-slot limits are frozen policy, not extra retries granted by 282.
        previous=self.config
        if logical in self.single_final:self.config=dict(previous,max_attempts_per_slot=1)
        try:return super().perform(logical,role,payload,validator,repair)
        finally:self.config=previous
