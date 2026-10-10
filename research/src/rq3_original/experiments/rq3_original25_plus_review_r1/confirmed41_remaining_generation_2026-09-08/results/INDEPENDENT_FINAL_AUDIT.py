"""Read-only run audit; derived reports never change runner receipts."""
import json,hashlib,os
from pathlib import Path
from collections import Counter
from decimal import Decimal
ROOT=Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-i1-pilot-launch')
OUT=ROOT/'experiments/rq3_original25_plus_review_r1/confirmed41_remaining_generation_2026-09-08/results'
RUN=OUT/'run'
def load(p):return json.loads(p.read_text())
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x]
def sha(b):return hashlib.sha256(b).hexdigest()
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
starts=sorted([load(p) for p in (RUN/'attempts').glob('*.start.json')],key=lambda x:x['monotonic_start'])
outcomes={s['attempt_id']:load(RUN/'attempts'/(s['attempt_id']+'.outcome.json')) for s in starts}
journal=rows(RUN/'JOURNAL.jsonl');jr=[r for r in journal if r['event']=='ATTEMPT_RESERVED_BEFORE_TRANSPORT'];jo=[r for r in journal if r['event']=='ATTEMPT_OUTCOME']
assert len(jr)==len(jo)==len(starts)==9
assert {r['attempt_id'] for r in jr}=={r['attempt_id'] for r in jo}==set(outcomes)
assert Counter(o['status'] for o in outcomes.values())=={'ACCEPTED':3,'UNKNOWN_COMPLETION':6}
index=load(RUN/'PARENT_INDEX.json');accepted={r['logical'] for r in index['accepted']}
assert len(accepted)==269 and not any(s['logical'] in accepted for s in starts)
for s in starts:
 assert sha(canon(s['request']))==s['request_sha256']
 assert s['request']['model']=='gpt-4o-mini-2024-07-18' and s['request']['temperature']==0 and s['request']['max_tokens']==2048 and s['request']['stream'] is False
 raw=RUN/'attempts'/(s['attempt_id']+'.raw.json');assert sha(raw.read_bytes())==outcomes[s['attempt_id']]['raw_sha256']
 if s['attempt']==2:
  earlier=next(a for a in starts if a['logical']==s['logical'] and a['attempt']==1)
  assert earlier['request']==s['request'] and earlier['request_sha256']==s['request_sha256']
waits=[];events=rows(RUN/'RECOVERY_EVENTS.jsonl')
for i,event in enumerate(events):
 if event['event'].endswith('RETRY_WAIT_BEGIN'):
  nxt=events[i+1];assert nxt['event']=='CLIENT_REBUILT_SAME_CONFIGURATION' and nxt['logical']==event['logical']
  assert nxt['payload_sha256']==event['payload_sha256']
  elapsed=nxt['monotonic']-event['monotonic'];assert elapsed>=10;waits.append(elapsed)
assert len(waits)==4
streak=rows(RUN/'LOGICAL_RECOVERY.jsonl')
assert [r['consecutive_connection_exhaustions'] for r in streak[-3:]]==[1,2,3]
assert load(RUN/'STOP.json')['category']=='THREE_CONSECUTIVE_CONNECTION_EXHAUSTIONS'
slots=rows(OUT/'RESPONSE_HANDOFF.jsonl');missing=[]
for s in slots:
 assert s['human_scores']==[]
 if s['status']=='ACCEPTED':continue
 logical=s['declared_slot_key'];cs=[x for x in starts if x['logical']==logical+':CANDIDATE'];fs=[x for x in starts if x['logical']==logical+':FINAL']
 if fs:kind='FINAL_UNKNOWN_AFTER_TWO_ATTEMPTS'
 elif cs and outcomes[cs[-1]['attempt_id']]['status']=='UNKNOWN_COMPLETION':kind='CANDIDATE_UNKNOWN_FINAL_DEPENDENCY_BLOCKED'
 else:kind='UNATTEMPTED_AFTER_GLOBAL_STOP'
 refs=[dict(path='run/attempts/'+x['attempt_id']+'.outcome.json',sha256=sha((RUN/'attempts'/(x['attempt_id']+'.outcome.json')).read_bytes())) for x in cs+fs]
 missing.append(dict(slot=logical,recorded_handoff_status=s['status'],derived_missing_reason=kind,source_outcomes=refs))
assert Counter(x['derived_missing_reason'] for x in missing)=={'FINAL_UNKNOWN_AFTER_TWO_ATTEMPTS':1,'CANDIDATE_UNKNOWN_FINAL_DEPENDENCY_BLOCKED':2,'UNATTEMPTED_AFTER_GLOBAL_STOP':60}
secret=os.environ.get('OPENAI_API_KEY','').encode();assert secret
for p in OUT.rglob('*'):
 if p.is_file():assert secret not in p.read_bytes(), 'CREDENTIAL_FOUND_IN_OUTPUT'
new_debit=sum(Decimal(str(s['reserved_usd_upper_bound'])) for s in starts)
unknown=rows(OUT/'UNKNOWN_AND_FAILED_ATTEMPTS.jsonl')
assert len(unknown)==8
report=dict(basis='DERIVED_FROM_IMMUTABLE_RUN_RECEIPTS_NOT_NEW_RUNTIME_LOGS',new_attempts=9,new_accepted=3,new_unknown=6,cumulative_attempts=286,
 cumulative_budget_debit_usd=str(Decimal('.5533299')+new_debit),cumulative_unknown_reserved_usd=str(sum(Decimal(str(r['reserved_usd_upper_bound'])) for r in unknown)),
 accepted_canonical_slots=183,missing_slots=63,missing_reason_counts=dict(Counter(x['derived_missing_reason'] for x in missing)),
 missing_slot_details=missing,waits_before_rebuild_seconds=waits,minimum_start_interval_seconds=min(b['monotonic_start']-a['monotonic_start'] for a,b in zip(starts,starts[1:])),
 canonical_269_cached_results_not_resent=True,all_three_retry_payloads_identical=True,original_unknown_resend_payload_identical=True,
 six_planning_replacements_not_resent=True,consecutive_failure_stop_verified=True,credential_bytes_absent_from_artifacts=True,
 note='S5 candidate reached the third connection exhaustion and stopped the runner before the coordinator wrote a dependency stage. The original handoff records its FINAL as NOT_EXECUTED; this report derives the candidate dependency blocker from its two real UNKNOWN outcomes. No runner log or response was fabricated.')
with (OUT/'FINAL_DEPENDENCY_AND_ACCOUNTING_AUDIT.json').open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
text='''# 本轮停机诊断与缺失解释

本轮实际新增 9 次 Provider 尝试：FINAL 5（3 接受、2 未知），CANDIDATE 4（全部未知），ROUTE 0。
新增接受仅为 M01-B（task-495277e64cd9）的 S0/S1/S2。S0 是用户授权的唯一历史未知补发，payload 与旧未知完全相同；旧记录和预留未删除。
S3 FINAL、S4 CANDIDATE、S5 CANDIDATE 各遇到两次连接异常，连续逻辑故障序列为 1、2、3，触发全局停止。
每次网络补发前都实际等待至少 10 秒并重建相同配置客户端；重发 payload 完全一致。
全部六次新错误的安全类链为 openai.APIConnectionError → builtins.RuntimeError，errno 均为空，没有 HTTP 响应、request ID 或 usage。
测得单次日志区间约 0.0033–0.0095 秒，不能称作已经等待 30 秒超时，也不能作为独立 wire-send 测量。
本轮不保存异常消息、repr 或认证信息，因此仅凭这些记录不能进一步确认底层 RuntimeError 原因，更不能断言 DNS、代理、TLS 或服务端是根因。

246 槽最终保留 183 个规范回答，63 个缺失：1 个 FINAL 两次未知，2 个因候选未知没有 FINAL，另 60 个在全局停止后未执行。
S4 已有运行时 DEPENDENCY_BLOCKED 阶段；S5 的第三次逻辑故障触发停止，运行器尚未写入下游依赖阶段，原交接表将该 FINAL 记为 NOT_EXECUTED。
FINAL_DEPENDENCY_AND_ACCOUNTING_AUDIT.json 单独依据真实候选 outcome 解释 S5 的依赖缺失，不改写历史运行日志或伪造阶段。
原始状态计数仍是 183 ACCEPTED / 1 UNKNOWN_COMPLETION / 1 DEPENDENCY_BLOCKED / 61 NOT_EXECUTED。
累计 286 次尝试（278 接受、8 未知），预算借记约 $0.57506295，8 个未知总预留约 $0.01994340；这是保守控制账而非实际账单。
原180回答、81路由、8候选与上轮六个Planning替代保持不变；Judge和人评分数均为0。

初次启动曾被自动审批拒绝，尚未创建进程、run或发出调用。随后先核实剩余11题均为 SYNTHETIC_ENGLISH_ALIGNED、构造learner标识与原明确外发授权，再将同一启动操作重新提交审查并获准。
对应来源与授权证据保存于 process/EGRESS_AUTHORIZATION_EVIDENCE.json。没有绕过审批拒绝、没有增加目的地或外发范围。
'''
with (OUT/'NETWORK_STOP_DIAGNOSTICS.md').open('x') as f:f.write(text)
print(json.dumps({k:v for k,v in report.items() if k not in ('missing_slot_details','note')},ensure_ascii=False))
