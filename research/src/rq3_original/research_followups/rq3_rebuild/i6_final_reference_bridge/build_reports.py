"""Preserve completed/stopped live outputs and create unscored reading material."""
from copy import deepcopy
from decimal import Decimal
import difflib
import json
import shutil
from i6_common import *
import run_i6 as run
from final_reference_v1 import preservation_receipt

def main():
    require((OUTPUT/'RUN_SUMMARY.json').is_file(), 'TERMINAL_SUMMARY_REQUIRED')
    check_files(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files'])
    seal=load(HERE/'PRECALL_IDENTITY_SEAL.json')
    check_files(seal['binding']['files'])
    summary=load(OUTPUT/'RUN_SUMMARY.json'); live=HERE/'live'
    require(not live.exists(), 'NO_REPORT_OVERWRITE')
    captures=[]
    for p in sorted(OUTPUT.rglob('*')):
        if not p.is_file():continue
        require(not p.is_symlink() and p.suffix in ('.json','.jsonl'), 'UNEXPECTED_LIVE_FILE')
        target=live/p.relative_to(OUTPUT);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(p.read_bytes())
        require(target.read_bytes()==p.read_bytes(),'LIVE_READBACK')
        captures.append(dict(path=str(target.relative_to(HERE)),source=file_binding(p),bytes=target.stat().st_size,sha256=sha(target.read_bytes())))
    write_once(HERE/'ACTUAL_OUTPUT_SOURCE_MANIFEST.json',dict(files=captures,copy_readback='PASS'))
    starts=[load(p) for p in sorted((live/'attempts').glob('*.start.json'))]
    outcomes=[load(p) for p in sorted((live/'attempts').glob('*.outcome.json'))]
    timings=[load(p) for p in sorted((live/'attempts').glob('*.timing.json'))]
    reserved=sum((Decimal(s['reserved_estimate_usd']) for s in starts),Decimal(0))
    charged=Decimal(0);known=Decimal(0);usage_missing=0
    for s in starts:
        o=next((x for x in outcomes if x['attempt_id']==s['attempt_id']),{})
        estimate=run.usage_estimate(o.get('usage'),settings())
        if estimate is None:usage_missing+=1
        else:known+=estimate
        charged+=max(Decimal(s['reserved_estimate_usd']),estimate or Decimal(0))
    ordered=sorted(timings,key=lambda x:x['monotonic_start'])
    intervals=[b['monotonic_start']-a['monotonic_start'] for a,b in zip(ordered,ordered[1:])]
    physical={phase:sum(x['phase']==phase for x in starts) for phase in ('INITIAL','CORRECTION','FINAL')}
    require(physical==summary['phase_counts'] and len(starts)==summary['total_physical_calls'],'LIVE_CALL_COUNT_RECONCILIATION')
    require(all(physical[k]<=settings()['caps'][k] for k in physical) and len(starts)<=13,'CALL_CAP_READBACK')
    require(all(x>=2 for x in intervals),'PACING_READBACK')
    unknown=sum(x.get('completion')=='UNKNOWN' for x in outcomes)+sum(not any(o['attempt_id']==s['attempt_id'] for o in outcomes) for s in starts)
    budget=dict(phase_counts=physical,total_new_calls=len(starts),reused_candidates=summary.get('reused_accepted_candidates',0),
        new_accepted_candidates=summary.get('new_accepted_candidates',0),unknown_completions=unknown,
        reserved_estimate_usd=str(reserved),conservative_charged_estimate_usd=str(charged),
        known_usage_uncached_estimate_usd=str(known),usage_missing_attempts=usage_missing,ceiling_usd='0.25',
        minimum_observed_start_interval_seconds=min(intervals) if intervals else None,
        start_intervals_seconds=intervals,serial=all(a['monotonic_end']<=b['monotonic_start'] for a,b in zip(ordered,ordered[1:])),
        invoice_guarantee=False,reservation_convention=settings()['reservation_convention'],
        available_usage=[dict(attempt_id=o['attempt_id'],usage=o.get('usage')) for o in outcomes])
    write_once(HERE/'CALL_USAGE_BUDGET_PACING.json',budget)
    reading=['# I6 exposed synthetic DEV reading copy\n\nActual I6 outputs and the source-bound reused I5 candidate. '
             'Developer material, not an independent blind evaluation package. No human ratings.\n']
    checklist=[];preserved=[];slot_rows=[]
    for index,row in enumerate(summary['slots'],1):
        logical=row['logical'];p=prepared(load_slots()[index-1]);reading.append(f'\n## {index}. {logical}\n')
        material=load(HERE/f'inputs/{index:02}/supplied_material.json')
        reading.append('\n### Supplied material (verbatim JSON file)\n\n```json\n'+(HERE/f'inputs/{index:02}/supplied_material.json').read_text()+'```\n')
        relevant=[x for x in outcomes if x['logical']==logical]
        if index==1 and summary.get('reused_accepted_candidates'):
            content=load(HERE/'historical_i5/live/attempts/01_initial.raw.json')['choices'][0]['message']['content']
            reading.append('\n### Reused I5:01_initial content (verbatim)\n\n```json\n'+content+'\n```\n')
        for o in relevant:
            raw_path=live/'attempts'/(o['attempt_id']+'.raw.json');raw=load(raw_path)
            content=raw.get('choices',[{}])[0].get('message',{}).get('content') if raw.get('choices') else None
            if isinstance(content,str):
                text_path=HERE/'verbatim'/(o['attempt_id']+'.content.txt');text_path.parent.mkdir(parents=True,exist_ok=True)
                with text_path.open('x') as f:f.write(content)
                reading.append(f'\n### New I6 {o["attempt_id"]} — {o["status"]} (verbatim)\n\n```json\n'+content+'\n```\n')
            if o['role']=='FINAL' and isinstance(o.get('value'),dict):
                answer=o['value'].get('answer')
                if isinstance(answer,str):
                    with (HERE/'verbatim'/(o['attempt_id']+'.answer.txt')).open('x') as f:f.write(answer)
                accepted=load(live/'attempts'/(o['attempt_id']+'.start.json'))['request']
                plan=json.loads(accepted['messages'][1]['content'])['accepted_plan']
                preserved.append(dict(logical=logical,plan_fields_equal=o['value'].get('plan_fields')==plan,
                    **preservation_receipt(p,settings()['generation_roles']['FINAL'],plan)))
        checklist.append(dict(logical=logical,rating='',reason='',source_support_rating='',source_support_reason='',
            duration_uncertainty_rating='',duration_uncertainty_reason='',unseen_document_rating='',unseen_document_reason='',
            unsupported_guarantee_rating='',unsupported_guarantee_reason='',reviewer='',reviewed_at=''))
        status='FINAL_ACCEPTED' if row.get('final_status')=='ACCEPTED' else 'UNKNOWN' if 'UNKNOWN_COMPLETION' in (row.get('candidate_status'),row.get('final_status')) else 'UNTESTED' if not row.get('attempt_ids') else 'FAILED'
        slot_rows.append(dict(**row,slot_status=status))
    write_once(HERE/'FIVE_SLOT_OUTCOMES.json',slot_rows)
    write_once(HERE/'LIVE_FINAL_INPUT_PRESERVATION.json',preserved)
    write_once(HERE/'HUMAN_DEV_CHECKLIST_BLANK.json',dict(status='UNSCORED',slots=checklist,human_scores=0))
    (HERE/'DEVELOPMENT_READING_COPY_VERBATIM.md').write_text(''.join(reading),encoding='utf-8')
    observations=('Developer observations only; no human scores and no teaching-effectiveness inference.\n\n'
        'All five slots are exposed synthetic DEV. Original I5 FINAL remains rejected for current-request. '
        'I6 retains the accepted plans and source facts; its citation enum constrains identity, not entailment. '
        'Model durations remain uncertain estimates and cannot establish actual feasibility. '
        'Observation dates do not establish availability. Worksheet text is absent from the first S4 snapshot, '
        'so its contents cannot be claimed as read. Plan guarantees may remain inside exact plan_fields; '
        'human review must distinguish these from the final prose. No ratings or reasons have been filled.\n')
    (HERE/'DEVELOPER_OBSERVATIONS.md').write_text(observations,encoding='utf-8')
    tests=load(HERE/'OFFLINE_TEST_SUMMARY.json')
    report=f'''# I6 completion report

{summary['status']}

Stop reason: {summary.get('stop_reason') or 'None'}.

| Slot | Candidate origin | Candidate | FINAL | State |
|---|---|---|---|---|
'''
    for r in slot_rows:report+=f"| {r['logical']} | {r.get('candidate_origin','UNTESTED')} | {r.get('candidate_status','NOT_ATTEMPTED')} | {r.get('final_status','NOT_ATTEMPTED')} | {r['slot_status']} |\n"
    report+=f'''
Reused accepted candidates: {summary.get('reused_accepted_candidates',0)}. New accepted candidates: {summary.get('new_accepted_candidates',0)}.
New Provider calls: INITIAL {physical['INITIAL']}, CORRECTION {physical['CORRECTION']}, FINAL {physical['FINAL']}; total {len(starts)}, ceiling 13.
Unknown completions: {unknown}. Final accepted: {sum(r.get('final_status')=='ACCEPTED' for r in slot_rows)}.
Offline tests: {tests['passed']}/{tests['tests_run']} passed; failures {tests['failures']}, errors {tests['errors']}, skipped {tests['skipped']}.
Frozen-convention reserved estimate USD {reserved}; conservative charged estimate USD {charged}; known usage estimate USD {known}; ceiling USD 0.25. These are not invoice guarantees.
P3/router, retrieval/RAG, Memory, embedding and Judge calls: all 0. Human scores: 0.

Starting HEAD: {START}. Actual ending HEAD and Git change receipt are included in the review ZIP as GIT_VERSION.json after the one original commit.
Only new I6 files were added; all original source identities were rechecked after execution. No FINAL retries or automatic continuation.

The actual original I5 failure was replayed before worktree edits and remains CITATION_ID_NOT_RETAINED. I6 supplies a versioned source-only citation contract derived from actual rendered source_facts and the retained trace; it does not enlarge the factual whitelist with the request. All five I5 initial requests are byte-identical, including the reused first request. Internal plan references, source facts, query/history and accepted plans remain intact.

See DEVELOPMENT_READING_COPY_VERBATIM.md, verbatim/*.answer.txt and live/attempts/*.raw.json for unedited response access. Human DEV rating and reason fields remain blank. Encoded acceptance is not semantic entailment or teaching effectiveness. Model durations are estimates, and absent worksheet text has not been read.

Remaining scope: manually review actual source support, uncertain durations, unsupported guarantees and unavailable document contents. Any further generation after completion or stop needs new explicit authorization; real-source readiness and human evaluation remain separate work.
'''
    (HERE/'I6_COMPLETION_REPORT.md').write_text(report,encoding='utf-8')
    (HERE/'START_HERE.md').write_text('# I6 review entry\n\nRead I6_COMPLETION_REPORT.md, FIVE_SLOT_OUTCOMES.json and DEVELOPMENT_READING_COPY_VERBATIM.md. '
        'Contract and code: FINAL_REFERENCE_CONTRACT_V1.md, final_reference_v1.py, run_i6.py and CODE_ONLY_CHANGE.patch. '
        'Identity: OLD_FAILURE_REPLAY.json, CANDIDATE_REUSE_RECEIPT.json, SOURCE_PRESERVATION_MANIFEST.json, PRECALL_IDENTITY_SEAL.json. '
        'Tests: OFFLINE_TEST_SUMMARY.json and offline_runs/. All human rating/reason fields are blank. '
        'This is exposed synthetic DEV, not effectiveness evidence or a blind evaluation package. Do not run live entrypoints again.\n',encoding='utf-8')
    write_once(HERE/'POSTRUN_SOURCE_PRESERVATION.json',dict(status='PASS',checked_original_files=len(load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['files']),
        checked_precall_files=len(seal['binding']['files']),tracked_diff=git('diff','--name-only'),starting_head=START,current_head=git('rev-parse','HEAD'),utc=utc()))
    write_once(HERE/'FINAL_QA.json',dict(status='PASS',original_sources_unchanged=True,precall_files_unchanged=True,
        caps_respected=True,serial_pacing=True,source_plan_input_preserved=all(x['plan_fields_equal'] and all(y['canonical_bytes_unchanged'] for y in x['fields'].values()) for x in preserved),
        no_human_scores=True,unknown_completions=unknown,actual_phase_counts=physical))
    print(canonical(dict(status='REPORTS_CREATED',calls=physical,unknown=unknown)).decode())

if __name__=='__main__':main()
