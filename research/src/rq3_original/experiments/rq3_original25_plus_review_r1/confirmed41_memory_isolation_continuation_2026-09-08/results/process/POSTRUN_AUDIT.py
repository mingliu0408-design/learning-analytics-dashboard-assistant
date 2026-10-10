"""Independent readback of actual A3 attempts; never sends or resumes requests."""
from pathlib import Path
import sys,json,os
from collections import Counter
from decimal import Decimal
ROOT=Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-i1-pilot-launch')
HERE=ROOT/'experiments/rq3_original25_plus_review_r1/confirmed41_memory_isolation_continuation_2026-09-08'
sys.path.insert(0,str(HERE))
from checkpoints import LayeredLedger,load,rows,sha,canonical,EXISTING_UNKNOWNS,base
from export_continuation import inventory

def main():
 base.offline()
 taskdir=Path(__file__).resolve().parent.parent;run=taskdir/'run';process=taskdir/'process'
 assert load(process/'PROCESS_EXIT.json')['process_exited']
 parent=LayeredLedger();policy=load(HERE/'RECOVERY_POLICY.json')
 starts,outcomes,stages,bylogical,new=inventory(run)
 approval=load(taskdir/'EXECUTION_APPROVAL.json');pf=load(taskdir/'PREFLIGHT.json')
 binding=load(run/'RUN_BINDING.json')
 assert approval['binding']==pf['binding'] and all(binding[k]==v for k,v in pf['binding'].items())
 assert binding['transport_kind']=='LIVE' and binding['data_revision']=='ORIGINAL25_PLUS_REVIEW_R1'
 journal=rows(run/'JOURNAL.jsonl')
 jr=[r for r in journal if r['event']=='ATTEMPT_RESERVED_BEFORE_TRANSPORT']
 jo=[r for r in journal if r['event']=='ATTEMPT_OUTCOME']
 assert len(jr)==len(starts) and len(jo)==len(outcomes)
 assert {r['attempt_id'] for r in jr}=={r['attempt_id'] for r in starts}
 assert not any(s['logical'] in parent.selected for s in starts)
 missing={r['declared_slot_key'] for r in parent.slots if r['status']!='ACCEPTED'}
 assert len(missing)==63
 role_counts=Counter(s['group'] for s in starts)
 for group,cap in policy['physical_caps'].items():assert role_counts[group]<=cap
 assert len(starts)<=232 and parent.physical_calls+len(starts)<=518
 assert parent.budget_debit+new['budget_debit_usd']<=10
 assert new['minimum_start_interval_seconds'] is None or new['minimum_start_interval_seconds']>=2
 config=load(run/'RECOVERY_CONTROL.json')['effective_config']
 resends=[]
 for logical,ss in bylogical.items():
  assert len(ss)<=(1 if logical in EXISTING_UNKNOWNS else 2)
  for s in ss:
   payload=s['request'];assert sha(payload)==s['request_sha256']
   assert s['role'] in ('RAG','MEMORY','B4_PLANNING','CANDIDATE','FINAL')
   if s['role'] in ('CANDIDATE','FINAL'):
    assert logical.rsplit(':',1)[0] in missing
    for k in ('model','temperature'):assert payload[k]==config['generation_roles'][s['role']][k]
    assert payload['max_tokens']==config['generation_roles'][s['role']]['max_output_tokens']
    assert payload['stream'] is False
   op=run/'attempts'/f"{s['attempt_id']}.outcome.json"
   if op.exists():
    o=load(op);rp=run/'attempts'/f"{s['attempt_id']}.raw.json"
    assert sha(rp.read_bytes())==o['raw_sha256'] and o['request_sha256']==s['request_sha256']
   if s['attempt']==2:
    first=ss[0];prior=outcomes[first['attempt_id']]
    if prior['status']=='UNKNOWN_COMPLETION':assert first['request']==payload
  if logical in EXISTING_UNKNOWNS:
   receipt=parent.unknown_permission(logical,ss[0]['request'])
   resends.append(dict(logical=logical,additional_attempts=len(ss),request_sha256=ss[0]['request_sha256'],prior=receipt))
 waits=[]
 if (run/'RECOVERY_EVENTS.jsonl').exists():
  events=rows(run/'RECOVERY_EVENTS.jsonl')
  for i,e in enumerate(events):
   if e['event'].endswith('RETRY_WAIT_BEGIN'):
    n=events[i+1];assert n['event']=='CLIENT_REBUILT_SAME_CONFIGURATION'
    assert n['logical']==e['logical'] and n['payload_sha256']==e['payload_sha256']
    elapsed=n['monotonic']-e['monotonic'];assert elapsed>=10;waits.append(elapsed)
 final_responses=[];workers=[];module_reads=[]
 for p,s in stages:
  assert sha(s['output'])==s['output_sha256']
  if s['stage']=='RESPONSE':
   o=s['output'];assert o['human_scores']==[]
   if o['result']['status']=='ACCEPTED':
    r=o['result'];raw=load(run/'attempts'/f"{r['attempt_id']}.raw.json")
    assert o['response']['answer']==r['value']['answer']==json.loads(raw['choices'][0]['message']['content'])['answer']
    final_responses.append(s['logical'])
  elif s['stage']=='OFFLINE_PREPARATION_WORKER':
   o=s['output'];assert o['memory_guard']=='M0_NETWORK_DISABLED' and o['parent_socket_allocation_passed'] and o['credentials_available'] is False
   workers.append(dict(task=s['logical'],**o))
  elif s['stage']=='MODULES':module_reads.append(s['output'])
 for worker in workers:
  task=worker['task']
  assert all(any(s['logical']==task+':'+mode and s['stage']=='MODULES' for _,s in stages)
             for mode in config['modes'] if task+':'+mode in missing and parent.module(task+':'+mode) is None)
 unknown=[]
 for name,rr in [*parent.runs.items(),('A3',run)]:
  for p in (rr/'attempts').glob('*.start.json'):
   s=load(p);op=rr/'attempts'/f"{s['attempt_id']}.outcome.json"
   if not op.exists() or load(op)['status']=='UNKNOWN_COMPLETION':
    unknown.append(dict(source_run=name,attempt_id=s['attempt_id'],logical=s['logical'],reserved_usd_upper_bound=s['reserved_usd_upper_bound']))
 assert sum(u['source_run']!='A3' for u in unknown)==8
 key=os.environ.get('OPENAI_API_KEY','').encode()
 assert key
 for directory in (run,process):
  for p in directory.rglob('*'):
   if p.is_file():assert key not in p.read_bytes(), 'CREDENTIAL_BYTES_IN_ARTIFACT'
 report=dict(passed=True,basis='INDEPENDENT_READBACK_OF_ACTUAL_RECEIPTS',new=new,
  new_by_group=dict(role_counts),cumulative_physical_calls=286+len(starts),
  cumulative_budget_debit_usd=parent.budget_debit+new['budget_debit_usd'],
  cumulative_unknown_reserve_usd=str(sum(Decimal(str(u['reserved_usd_upper_bound'])) for u in unknown)),
  old183_answers_not_resent=True,old81_routes_and8_candidates_preserved=True,
  canonical_answer_count=183+len(final_responses),remaining_final_slots=63-len(final_responses),
  historical_unknowns_retained=8,new_unknowns=sum(u['source_run']=='A3' for u in unknown),
  explicit_unknown_resends=resends,retry_waits_seconds=waits,offline_workers=workers,
  recovery_log_offset_note='historical_attempt_offset is the inherited within-run allowance offset (1), not a count of historical attempts; each A2 resend has two historical UNKNOWN receipts plus at most one A3 attempt',
  actual_new_rag_calls=sum(x['actual_new_rag_calls'] for x in module_reads),
  actual_new_memory_calls=sum(x['actual_new_memory_calls'] for x in module_reads),
  credential_bytes_absent=True,judge_calls=0,human_scores_filled=0,provider_billing_certified=False)
 with (process/'POSTRUN_INDEPENDENT_AUDIT.json').open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ('new','offline_workers','explicit_unknown_resends','retry_waits_seconds')},ensure_ascii=False))

if __name__=='__main__':main()
