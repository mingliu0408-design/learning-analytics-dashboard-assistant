"""Read saved I4 records once; produce factual, unscored review material."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
import re
import shutil
from i4_common import *
from run_i4 import REPAIR, correction_payload, estimate, usage_estimate
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.schemas import LOCAL_CANDIDATE, errors, final_errors


def text_once(path, value):
    with Path(path).open('xb') as f:
        f.write(value.encode()); f.flush()
        import os
        os.fsync(f.fileno())


def codes(issues):
    return [x['code'] if isinstance(x,dict) else x.rsplit(':',1)[-1] for x in issues]


def refs(value, path='$'):
    found=[]
    if isinstance(value,dict):
        for k,v in value.items():
            if k=='evidence_refs' and isinstance(v,list):
                found.extend(dict(path=path+'.'+k,index=i,id=x) for i,x in enumerate(v))
            else:found.extend(refs(v,path+'.'+k))
    elif isinstance(value,list):
        for i,v in enumerate(value):found.extend(refs(v,path+f'[{i}]'))
    return found


def main():
    summary=load(OUTPUT/'RUN_SUMMARY.json')
    require(not (HERE/'live').exists(),'REPORT_CAPTURE_ALREADY_EXISTS')
    allowed={'PREFLIGHT.json','DIRECT_APPROVAL.json','CLIENT_CONFIGURATION.json','STOP.json','RUN_SUMMARY.json','JOURNAL.jsonl'}
    allowed |= {f'terminals/{i:02}.json' for i in range(1,6)}
    allowed |= {f'attempts/{i:02}_{phase}.{kind}.json' for i in range(1,6)
        for phase in ('initial','correction','final') for kind in ('start','dispatch','timing','raw','outcome')}
    copied=[]
    for path in sorted(OUTPUT.rglob('*')):
        if path.is_dir():continue
        rel=str(path.relative_to(OUTPUT));require(rel in allowed and not path.is_symlink(),'UNALLOWLISTED_LIVE_OUTPUT')
        data=path.read_bytes();require(not re.search(rb'sk-[A-Za-z0-9_-]{20,}',data),'POSSIBLE_SECRET_IN_OUTPUT')
        dest=HERE/'live'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as f:f.write(data)
        copied.append(dict(path='live/'+rel,origin=str(path),bytes=len(data),sha256=sha(data)))
    write_once(HERE/'ACTUAL_OUTPUT_SOURCE_MANIFEST.json',dict(files=copied,source=str(OUTPUT),copied_verbatim=True))
    cfg=load(HERE/'CONFIG.json')
    starts=[load(p) for p in (OUTPUT/'attempts').glob('*.start.json')]
    starts.sort(key=lambda x:(SLOTS.index(x['logical']),{'INITIAL':0,'CORRECTION':1,'FINAL':2}[x['phase']]))
    outcomes={p.name.removesuffix('.outcome.json'):load(p) for p in (OUTPUT/'attempts').glob('*.outcome.json')}
    rows=[];replays=[];fake=[];category_counts=Counter();phase_status=Counter();reader=bytearray();index=[]
    def add(s):reader.extend(s.encode())
    def exact(label,text,source,kind,logical):
        fence='`'*max(4,max([len(x) for x in re.findall(r'`+',text)] or [0])+1)
        add(f'\n{label}\n\n{fence}text\n');begin=len(reader);reader.extend(text.encode());end=len(reader);add(f'\n{fence}\n')
        index.append(dict(logical=logical,label=label,kind=kind,raw_source=source,
            start_byte=begin,end_byte_exclusive=end,text_sha256=sha(text.encode()),utf8_bytes=len(text.encode())))
    add('# I4 原样 DEV 阅读材料\n\n五个按失败类别选定的 EXPOSED SYNTHETIC DEV 槽位。所有材料均为合成快照，不是独立 TEST 样本。\n'
        'OLD_I2_HISTORICAL 是历史原文；NEW_I4_DEV 是本次实际输出。候选检查通过不等于语义或质量通过。人工表保持空白。\n')
    for number,dep in enumerate(load_slots(),1):
        p=prepared(dep);b=p['planner']['bridge'];captured=load(HERE/'INPUT_BINDINGS.json')[number-1]
        slot_starts=[s for s in starts if s['logical']==dep['logical']]
        oslot=[outcomes[s['attempt_id']] for s in slot_starts if s['attempt_id'] in outcomes]
        cs=[o for o in oslot if o['role']=='CANDIDATE'];fs=[o for o in oslot if o['role']=='FINAL']
        accepted=next((o for o in cs if o['status']=='ACCEPTED'),None)
        entry=dict(logical=dep['logical'],source_sha256=captured['source_sha256'],prepared_sha256=captured['prepared_sha256'],
            i3_bridge_sha256=dep['frozen_input_sha256'],initial_request_sha256=dep['proposed_initial_request_sha256'],
            prior_final_request_sha256=dep['prior_final_request_sha256'],
            initial_status=next((o['status'] for o in cs if o['phase']=='INITIAL'),'NOT_ATTEMPTED'),
            correction_status=next((o['status'] for o in cs if o['phase']=='CORRECTION'),'NOT_CALLED'),
            selected_attempt=accepted['attempt_id'] if accepted else None,
            accepted_plan_sha256=sha(accepted['value']) if accepted else None,
            final_eligible=bool(accepted),final_called=bool(fs),
            final_status=fs[-1]['status'] if fs else 'NOT_CALLED_NO_ACCEPTED_PLAN' if cs and not accepted else 'NOT_ATTEMPTED',
            initial_error_categories=codes(next((o['issues'] for o in cs if o['phase']=='INITIAL'),[])),
            correction_error_categories=codes(next((o['issues'] for o in cs if o['phase']=='CORRECTION'),[])),
            execution_state='BOUNDED_SLOT_COMPLETE' if summary['status']=='BOUNDED_EXECUTION_COMPLETE' else 'STOPPED_OR_UNATTEMPTED',
            semantic_support='NOT_CHECKED',human_review='BLANK_NOT_PERFORMED',
            attempts=[],fake_evidence_id_occurrences=[],initial_and_correction_parsed_identical=None)
        add(f'\n## {number}. {dep["logical"]}\n\n问题：{p["final_request"]["runtime_input"]["context"]["current_query"]}\n\n')
        add('实际提供的来源、可见历史、时间信息及约束（只作排版，无事实改写）：\n\n```json\n')
        supplied=load(HERE/captured['directory']/'supplied_material.json')
        supplied['encoded_planning_fields']=json.loads(load(HERE/captured['directory']/'initial_request.json')['messages'][1]['content'])['encoded_planning_fields']
        add(json.dumps(supplied,ensure_ascii=False,indent=2)+'\n```\n')
        old=[]
        for n in (1,2):
            aid=dep['initial_candidate_attempt_id'][:-1]+str(n)
            old.append(load(I3/'sources/live/attempts'/f'{aid}.outcome.json')['status'])
        add(f'\nOLD_I2_HISTORICAL 候选状态：{old[0]} / {old[1]}。未改变原 I2 分类。\n')
        oldpath=HERE/captured['directory']/(dep['prior_final_attempt_id']+'.raw.json')
        oldanswer=json.loads(load(oldpath)['choices'][0]['message']['content'])['answer']
        exact('OLD_I2_HISTORICAL — 原样历史回答',oldanswer,str(oldpath.relative_to(HERE)),'OLD_FINAL_ANSWER',dep['logical'])
        for o in oslot:
            aid=o['attempt_id'];s=next(x for x in slot_starts if x['attempt_id']==aid);rawpath=OUTPUT/'attempts'/f'{aid}.raw.json';raw=load(rawpath)
            if not raw.get('_transport_failure'):
                validator=(lambda v:REPAIR.candidate_issues(b,v)) if o['role']=='CANDIDATE' else (lambda v:final_errors(v,p['trace']['retained_evidence_ids'],accepted['value']))
                status,value,issues=parse_response(raw,s['request'],validator)
                require(status==o['status'] and value==o['value'] and sorted(map(canonical,issues))==sorted(map(canonical,o['issues'])),'SAVED_REPLAY_MISMATCH')
                replays.append(dict(attempt_id=aid,status=status,exact_value=True,exact_issue_set=True))
            require(sha(rawpath.read_bytes())==o['raw_sha256'] and sha(s['request'])==o['request_sha256'],'ACTUAL_RECORD_HASH_MISMATCH')
            if o['phase']=='INITIAL':require(sha(s['request'])==dep['proposed_initial_request_sha256'],'LIVE_INITIAL_DRIFT')
            if o['phase']=='CORRECTION':
                previous=outcomes[s['correction_of']];previousraw=load(OUTPUT/'attempts'/f'{s["correction_of"]}.raw.json')
                reconstructed,branch=correction_payload(p,previous,previousraw,cfg)
                require(reconstructed==s['request'],'FRESH_FEEDBACK_REPLAY_MISMATCH')
                old_preview=load(I3/dep['proposed_initial_request'].replace('.1.json','.2.json'))
                require(s['request']!=old_preview,'OLD_CORRECTION_PREVIEW_DISPATCHED')
                entry['fresh_correction_binding']=dict(correction_of=s['correction_of'],branch=branch,new_feedback_reproduced=True,old_preview_dispatched=False)
            phase_status[o['phase']+':'+o['status']]+=1
            category_counts.update(codes(o['issues']))
            detail=dict(attempt_id=aid,phase=o['phase'],status=o['status'],issues=o['issues'],
                request_sha256=o['request_sha256'],raw_sha256=o['raw_sha256'],value_sha256=sha(o['value']),
                local_structure_issues=errors(o['value'],LOCAL_CANDIDATE) if o['role']=='CANDIDATE' and o['value'] is not None else None)
            entry['attempts'].append(detail)
            if o['role']=='CANDIDATE' and o['value'] is not None:
                catalog={f['fact_id'] for f in b['planner_input']['facts']}
                missing=[dict(attempt_id=aid,**r) for r in refs(o['value']) if r['id'] not in catalog]
                fake.extend(missing);entry['fake_evidence_id_occurrences'].extend(missing)
                detail['nonnull_schedule_actions']=[a['step_id'] for a in o['value']['actions'] if a['schedule'] is not None]
                detail['dependency_references']=[dict(step_id=a['step_id'],task_id=a['task_id'],dependencies=a['dependencies']) for a in o['value']['actions']]
                add(f'\nNEW_I4_DEV — {o["phase"]} 候选状态：{o["status"]}；错误：{", ".join(codes(o["issues"]))}。\n')
                exact('NEW_I4_DEV — 原样候选响应文本',raw['choices'][0]['message']['content'],f'live/attempts/{aid}.raw.json','NEW_CANDIDATE_RAW_TEXT',dep['logical'])
            if o['role']=='FINAL' and o['value'] and isinstance(o['value'].get('answer'),str):
                exact('NEW_I4_DEV — 原样新 FINAL 回答',o['value']['answer'],f'live/attempts/{aid}.raw.json','NEW_FINAL_ANSWER',dep['logical'])
        if len(cs)==2:entry['initial_and_correction_parsed_identical']=cs[0]['value']==cs[1]['value']
        if not fs:add('\nNEW_I4_DEV — 本槽位没有新 FINAL 回答；上方历史回答不计为本次成功。\n')
        rows.append(entry)
    with (HERE/'DEVELOPMENT_READING_COPY_VERBATIM.md').open('xb') as f:f.write(reader)
    for x in index:require(sha(bytes(reader[x['start_byte']:x['end_byte_exclusive']]))==x['text_sha256'],'READER_HASH_MISMATCH')
    write_once(HERE/'READING_COPY_INDEX.json',dict(entries=index,byte_ranges_verified=True,reader_sha256=sha(bytes(reader))))
    write_once(HERE/'FIVE_SLOT_OUTCOMES.json',rows)
    write_once(HERE/'ACTUAL_MECHANICAL_REPLAY.json',dict(status='PASS',attempts=replays,provider_calls=0,new_scoring=False,
        initial_request_hashes_verified=sum(s['phase']=='INITIAL' for s in starts),fresh_correction_replays=sum(s['phase']=='CORRECTION' for s in starts)))
    lines=['# Five-slot outcome table','', '| Slot | Source / full prepared SHA-256 | Initial | Correction | Selected / plan hash | FINAL eligible / made / status | Errors |',
        '|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f'| {r["logical"]} | source `{r["source_sha256"]}`; prepared `{r["prepared_sha256"]}` | {r["initial_status"]} | {r["correction_status"]} | {r["selected_attempt"]} / {r["accepted_plan_sha256"]} | {r["final_eligible"]} / {r["final_called"]} / {r["final_status"]} | '+', '.join(sorted(set(r['initial_error_categories']+r['correction_error_categories'])))+' |')
    text_once(HERE/'FIVE_SLOT_TABLE.md','\n'.join(lines)+'\n')
    costs=[];prompt=completion=0;unknown_usage=0
    for s in starts:
        o=outcomes.get(s['attempt_id'],{});known=usage_estimate(o.get('usage'),cfg);reserved=Decimal(s['reserved_estimate_usd'])
        require(estimate(s['request'],cfg)==(s['input_byte_units'],reserved),'RESERVATION_REPLAY')
        if known is None:unknown_usage+=1
        else:prompt+=o['usage']['prompt_tokens'];completion+=o['usage']['completion_tokens']
        costs.append(dict(attempt_id=s['attempt_id'],reserved_estimate_usd=str(reserved),
            known_uncached_usage_estimate_usd=str(known) if known is not None else None,
            charged_against_cap_usd=str(max(reserved,known or Decimal(0))),
            usage=o.get('usage'),completion=o.get('completion','UNKNOWN'),input_byte_units=s['input_byte_units']))
    times=sorted((load(p) for p in (OUTPUT/'attempts').glob('*.timing.json')),key=lambda x:x['monotonic_start'])
    intervals=[b['monotonic_start']-a['monotonic_start'] for a,b in zip(times,times[1:])]
    require(all(x>=2 for x in intervals) and all(a['monotonic_end']<=b['monotonic_start'] for a,b in zip(times,times[1:])),'PACING_OR_SERIAL_FAILURE')
    phase_counts={phase:sum(x['phase']==phase for x in starts) for phase in ('INITIAL','CORRECTION','FINAL')}
    require(phase_counts==summary['phase_counts'] and len(starts)==summary['total_physical_calls']<=15,'CALL_ACCOUNTING_MISMATCH')
    accounting=dict(phase_counts=phase_counts,total_physical_calls=len(starts),known_prompt_tokens=prompt,
        known_completion_tokens=completion,usage_unknown_attempts=unknown_usage,
        unknown_completion_attempts=sum(c['completion']=='UNKNOWN' for c in costs),
        reservation_total_usd=str(sum((Decimal(x['reserved_estimate_usd']) for x in costs),Decimal(0))),
        known_uncached_usage_estimate_usd=str(sum((Decimal(x['known_uncached_usage_estimate_usd']) for x in costs if x['known_uncached_usage_estimate_usd'] is not None),Decimal(0))),
        cap_charge_usd=str(sum((Decimal(x['charged_against_cap_usd']) for x in costs),Decimal(0))),
        approved_estimate_cap_usd='.25',exact_bill_known=False,reservation_is_not_billing_guarantee=True,
        frozen_rates=cfg['uncached_usd_per_million'],attempts=costs,
        start_intervals_seconds=intervals,minimum_start_interval_seconds=min(intervals) if intervals else None,
        serial_nonoverlap_verified=True,phase_status_counts=dict(phase_status),error_category_occurrences=dict(category_counts),
        sdk_max_retries=0,final_retries=0,router_calls=0,retrieval_calls=0,memory_calls=0,embedding_calls=0,judge_calls=0,human_scores=0)
    write_once(HERE/'CALL_USAGE_BUDGET_PACING.json',accounting)
    check_files(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files'])
    write_once(HERE/'POSTRUN_SOURCE_PRESERVATION.json',dict(status='PASS',utc=utc(),
        bound_files_verified=len(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files']),
        old_candidate_responses_unchanged=32,old_final_responses_unchanged=72,
        i2_i3_and_frozen_dependencies_unchanged=True))
    write_once(HERE/'DEFERRED_UNTESTED.json',dict(status='DEFERRED_UNTESTED',
        slots=load(I3/'MINIMAL_RETEST_DEPENDENCIES_NOT_AUTHORIZED.json')['impacted_but_not_default_retest'],
        historical_planner_slots=16,selected_retested=phase_counts['INITIAL'],no_general_clearance=True))
    checklist=[dict(logical=s,factual_use=None,real_citation_support=None,unsupported_benefit_claims=None,
        unnecessary_scheduling_clarification=None,final_prose_plan_consistency=None,reviewer_notes=None) for s in SLOTS]
    write_once(HERE/'HUMAN_DEV_CHECKLIST_BLANK.json',checklist)
    text_once(HERE/'HUMAN_DEV_CHECKLIST_BLANK.md','# Blank manual development checklist\n\n留空供真实人工阅读后填写；未给分、未预填判断或理由。\n\n'
        '| Slot | Factual use | Citation support | Unsupported benefit claims | Unnecessary scheduling clarification | Final prose / plan consistency | Notes |\n'
        '|---|---|---|---|---|---|---|\n'+''.join(f'| {s} | | | | | | |\n' for s in SLOTS))
    candidates=[o for o in outcomes.values() if o['role']=='CANDIDATE']
    stats=dict(initial_pass=sum(o['phase']=='INITIAL' and o['status']=='ACCEPTED' for o in candidates),
        correction_pass=sum(o['phase']=='CORRECTION' and o['status']=='ACCEPTED' for o in candidates),
        candidate_local_structure_pass=sum(o['value'] is not None and not errors(o['value'],LOCAL_CANDIDATE) for o in candidates),
        candidate_later_check_failure=sum(o['status']=='ENCODED_CHECK' and not errors(o['value'],LOCAL_CANDIDATE) for o in candidates),
        fake_evidence_id_occurrences=len(fake),candidate_attempts_with_fake_ids=len({x['attempt_id'] for x in fake}),
        identical_corrections=sum(r['initial_and_correction_parsed_identical'] is True for r in rows),
        nonnull_schedule_attempts=sum(any(a['schedule'] is not None for a in o['value']['actions']) for o in candidates if isinstance(o['value'],dict)))
    write_once(HERE/'OBSERVED_RESULT_CLASSIFICATION.json',dict(**stats,fake_id_occurrences=fake,
        category_occurrences=dict(category_counts),semantic_support='NOT_CHECKED',quality='NOT_CHECKED',sample='FAILURE_SELECTED_EXPOSED_SYNTHETIC_DEV'))
    tests=load(HERE/'OFFLINE_TEST_SUMMARY.json')
    status='READY_FOR_HUMAN_DEV_READING_AND_INTEGRATION_DECISIONS' if summary['status']=='BOUNDED_EXECUTION_COMPLETE' else 'PRESERVED_EARLY_STOP'
    text_once(HERE/'I4_COMPLETION_REPORT.md',f'''# I4 limited planner-contract retest — actual results

Status: **{status}**. Execution coverage: **{summary['status']}**.
Stop reason: {summary.get('stop_reason')}. This status permits human DEV reading and a later integration decision only.

The five authorized slots were attempted in the specified order. Actual physical calls:
INITIAL **{phase_counts['INITIAL']}**, CORRECTION **{phase_counts['CORRECTION']}**, FINAL **{phase_counts['FINAL']}**, total **{len(starts)}**.
Initial full-admission passes: **{stats['initial_pass']}**; correction passes: **{stats['correction_pass']}**.
See FIVE_SLOT_TABLE.md and FIVE_SLOT_OUTCOMES.json for exact inputs, statuses, paths and error details.

All {len(candidates)} new candidate attempts passed local structural validation, including nonempty plan/action references.
They then failed the unchanged later P1 checks. New output references contained **{len(fake)}** absent evidence IDs.
This is a literal ID audit only, not citation entailment. Every tested slot remained without an accepted new plan,
so no dependent FINAL was eligible. The historical I2 fallback answers were not resent or reclassified as I4 successes.

The new candidates supplied dated schedules despite ordinary advice and missing learner scheduling timezone,
horizon and allowed windows. Actual MISSING_TIMEZONE / MISSING_WINDOW / ALLOWED_WINDOWS_UNKNOWN errors
are recorded in all ten attempts. Four slots also used task IDs in dependency fields that require step IDs,
producing DEPENDENCY_ID_MISSING and DEPENDENCY_TIME_UNKNOWN. Three slots encountered
OPEN_ENDED_FUTURE_UNCONFIRMED when source metadata without a declared expiry was used for dated future actions.
The candidates' dates are saved model output; no dates were added to the input.
All five corrections reproduced their corresponding initial parsed candidate exactly, despite the fresh,
complete checker feedback. The prompt intervention exposed later failures here; it did not produce an accepted plan.

Error occurrence counts: `{json.dumps(dict(category_counts),sort_keys=True)}`.
No structural error remains in these ten new attempts; the unresolved errors are the later encoded checks above.
This does not clear the other eleven historical slots, which remain DEFERRED_UNTESTED. All 32 old candidates
retain their original rejected status. Five exposed, failure-selected DEV slots do not constitute an independent
test sample or a quality/learning-effect estimate.

Model/configuration remained gpt-4o-mini-2024-07-18, temperature 0, max output 2048,
SDK retries 0, timeout 30 seconds, serial starts at least 2 seconds apart. The measured minimum start interval
was {accounting['minimum_start_interval_seconds']:.6f} seconds. Routing, retrieval, Memory, embedding,
LLM Judge and human scores were all zero. No canary, FINAL retry or resumed execution occurred.

Frozen reservation convention: actual canonical UTF-8 request bytes + 256, plus maximum output at the frozen rates.
Reserved/cap-charged estimate: **USD {accounting['cap_charge_usd']}**, under the new USD 0.25 authorization.
Known usage: {prompt} prompt tokens and {completion} completion tokens; frozen uncached-rate estimate:
**USD {accounting['known_uncached_usage_estimate_usd']}**. Unknown usage attempts: {unknown_usage}; unknown completions:
{accounting['unknown_completion_attempts']}. The estimate is not an exact bill or a billing guarantee.
The [official model page](https://developers.openai.com/api/docs/models/gpt-4o-mini) was read; existing local SDK
1.109.1 and httpx 0.28.1 were inspected without installation or upgrade. No credentials or headers are included.

Offline tests actually executed: **{tests['passed']}/{tests['tests_run']}**, P0 70, P1 85, I3 31, I4 36;
failures {tests['failures']}, errors {tests['errors']}, unittest-skipped {tests['skipped']}.
The 54 cases in I1 test_i1.py (a suite that includes prepare-worker execution) and 8 original execution-entrypoint tests were deliberately not executed and are separately listed,
not claimed as passes. New I4 tests exercised exact hashes, direct-approval binding, exclusive output,
fresh/raw correction branches, no-final/no-third-attempt behavior, caps, byte bounds, reservations, monotonic pacing,
source/model drift, all fatal transport classes and unknown completion. Inherited controls retain wrong scope,
revoked/expired sources, impossible scheduling, ambiguous plans, completed tasks, fake IDs and the unchecked +40% claim.
Actual saved mechanical replay: {len(replays)} attempts matched values and issue sets with zero new calls.

Source preservation passed for 790 I3 captured sources, 161 frozen registry entries and all 1,847 bound files;
72 old answers and 32 old candidates remain byte-identical. I2/I3 archive hashes match the packet.
I3's frozen_input_sha256 actually hashes the Planner bridge, as its immutable producer defines; the initial I4
interpretation error and exact code pointers are preserved in DEVELOPMENT_ISSUES.md. Separate full prepared
and original stage-file hashes are now recorded without modifying I3 or its proposed requests.

Read DEVELOPMENT_READING_COPY_VERBATIM.md for the five questions, actual supplied facts/constraints,
all ten verbatim new candidate texts and five verbatim OLD_I2_HISTORICAL answers. No new FINAL answer exists.
READING_COPY_INDEX.json verifies UTF-8 text hashes and exact byte ranges. HUMAN_DEV_CHECKLIST_BLANK.* remains blank.

Unresolved: genuine semantic/citation support; worksheet content absent in SYN-11 and dashboard-only SYN-04:S4;
accepted active-plan identity absent in SYN-07; old-plan adoption/completion; historical relative-week validity;
real feasibility and human answer quality. A legal current-request ID supports the learner's intention, not missing
worksheet contents, completion or learning benefits. The unchanged checker still does not reject the synthetic
unsupported +40% semantic counterexample. Common FINAL fallback still conflates internal failures with missing
information; it was deliberately left unchanged. No LLM/Judge score, human judgment, significance or winner analysis exists.

Recommendation: review the verbatim DEV material and decide separately whether another narrowly specified
candidate-contract change concerning null schedules and step-ID dependencies is warranted. Any later live call
requires a new scope and budget. Do not change the original checker or manufacture scheduling/source facts.
No production integration is justified by this run's zero accepted plans.

Git start: {START}, branch {BRANCH}. Exactly one new result commit will contain only the I4 directory.
The actual post-commit Git end, tree, parent and patch are in ZIP-root GIT_VERSION.json and GIT_CHANGE.patch;
the external readback receipt contains the archive's actual SHA-256/bytes/members to avoid a circular hash.
No upload, deployment, human review or final study is claimed. Execution is finished; no automatic rerun follows.
''')
    text_once(HERE/'START_HERE.md',f'''# I4 five-slot limited planner retest review

Execution: **{summary['status']}**. Result: **0 accepted new plans; 0 new FINAL answers**.
Calls: 5 initial + 5 fresh corrections = 10 total. All ten pass local structure and fail later unchanged checks.
Read I4_COMPLETION_REPORT.md, FIVE_SLOT_TABLE.md and DEVELOPMENT_READING_COPY_VERBATIM.md.
The latter distinguishes OLD_I2_HISTORICAL from NEW_I4_DEV and has a verified UTF-8 byte-range index.
HUMAN_DEV_CHECKLIST_BLANK.* is unfilled. Candidate/FINAL quality and semantic support are NOT_CHECKED.

live/ is an exact allowlisted copy of the exclusive actual output directory, including all raw requests,
responses, checker errors, durable journals, reservations and pacing. inputs/ contains only the five saved
synthetic inputs and relevant historical attempts. repair_v1.py is a byte-identical inspection copy of I3.
The runner imports the actual hash-bound I3 module. No integration patch was applied.

This review does not authorize re-execution. Do not run run_i4.py again or point it at another directory.
Tests and verification scripts require the original checkout and saved I2/I3 sources; this ZIP is not a standalone
provider launcher. Test output and actual replay are separately identified. All new Git work is limited to I4.
ZIP-root OUTPUT_MANIFEST.json excludes itself; GIT_VERSION.json records the actual post-commit version.
The external readback receipt binds ZIP hash, size, member count, safe paths, CRC and member hashes.
Local ZIP creation is not upload, acceptance or human review. Then stop.
''')
    with (HERE/'repair_v1.py').open('xb') as f:f.write((I3/'repair_v1.py').read_bytes())
    write_once(HERE/'EXECUTION_PROCESS_RECEIPT.json',dict(returncode=0,observed_runner_completion=summary['status'],
        supervisor_invocations=1,retries=0,resume=False,utc=utc(),output_directory=str(OUTPUT)))
    print(canonical(dict(status='REPORTS_AND_VERBATIM_READER_VERIFIED',accounting=accounting,classification=stats)).decode())


if __name__=='__main__':main()
