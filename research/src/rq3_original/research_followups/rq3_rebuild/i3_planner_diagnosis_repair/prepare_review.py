"""Build bounded reports, integration patch and unchanged runtime source snapshots."""
from collections import Counter
import difflib
import json
import subprocess
import sys
from i3_common import HERE, ROOT, START, SCOPE, read, write, jsonl, sha, canonical, live_records, reference

sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.renderer import candidate_payload
from utils.c4_rebuild.planning import validate_candidate
from utils.c4_rebuild.i1.schemas import LOCAL_CANDIDATE
from p1bridge.contracts import CANDIDATE as P1_CANDIDATE


def anchor(path, text):
    lines=(ROOT/path).read_text().splitlines()
    return f'snapshot/{path}:{next(i+1 for i,line in enumerate(lines) if text in line)}'


def main():
    assert LOCAL_CANDIDATE==P1_CANDIDATE
    manifest=read(HERE/'SOURCE_PRESERVATION_MANIFEST.json')
    existing={r['path'] for r in manifest['captured_sources']}
    names=set()
    for module in list(sys.modules.values()):
        value=getattr(module,'__file__',None)
        if value:
            p=__import__('pathlib').Path(value).resolve()
            if p.is_file() and p.is_relative_to(ROOT) and not p.is_relative_to(HERE):names.add(str(p.relative_to(ROOT)))
    lock='research_followups/rq3_rebuild/p1_planner_bridge/P0_DEPENDENCY_LOCK.json'
    names.add(lock)
    names.update('research_followups/rq3_rebuild/p0_planner_prototype/'+r['path'] for r in read(ROOT/lock)['files'])
    names.update(['utils/c4_rebuild/i1/orchestrator.py',
        'research_followups/rq3_rebuild/i0_human_integration/schemas/STRUCTURED_PLAN_SCHEMA.json',
        'research_followups/rq3_rebuild/i1_pilot_launch/PILOT_CONFIGURATION_PROPOSED.json',
        'research_followups/rq3_rebuild/i1_pilot_launch/tests/test_i1.py',
        'research_followups/rq3_rebuild/p0_planner_prototype/tests/test_offline_planner.py',
        'research_followups/rq3_rebuild/p1_planner_bridge/tests/test_bridge.py',
        'research_followups/rq3_rebuild/p1_planner_bridge/tests/test_archive.py'])
    for rel in sorted(names):
        name='snapshot/'+rel;data=(ROOT/rel).read_bytes()
        assert data==subprocess.check_output(['git','show',START+':'+rel],cwd=ROOT)
        target=HERE/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():assert target.read_bytes()==data
        else:target.write_bytes(data)
        if name not in existing:
            manifest['captured_sources'].append(dict(path=name,bytes=len(data),sha256=sha(data),
                source=dict(kind='COMMITTED_SOURCE',commit=START,relative_path=rel)))
    write('SOURCE_PRESERVATION_MANIFEST.json',manifest)
    old=(ROOT/'utils/c4_rebuild/i1/orchestrator.py').read_text()
    new=old.replace('from .renderer import candidate_payload, final_payload',
        'from .renderer import final_payload\nfrom research_followups.rq3_rebuild.i3_planner_diagnosis_repair.repair_v1 import candidate_payload')
    assert old!=new
    patch=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
        fromfile='a/utils/c4_rebuild/i1/orchestrator.py',tofile='b/utils/c4_rebuild/i1/orchestrator.py'))
    (HERE/'INTEGRATION_PATCH_NOT_APPLIED.patch').write_text(patch)
    reconciliation=read(HERE/'I2_ACTUAL_ROLE_AND_MODULE_RECONCILIATION.json');counts=reconciliation['counts']
    matrix=[json.loads(l) for l in (HERE/'PLANNER_ATTEMPT_ERROR_MATRIX.jsonl').read_text().splitlines()]
    traces=[json.loads(l) for l in (HERE/'FINAL_FALLBACK_AND_INPUT_TRACE.jsonl').read_text().splitlines()]
    live,stages,attempts=live_records()
    memory_rows=[]
    for row in reconciliation['case_mode_rows']:
        if row['memory_diagnostics'].get('identity')!='M1_HYBRID_LINKS_DEV_CANDIDATE':continue
        logical=row['logical'];mp,stage=stages[logical,'C_MODULE_REBUILD'];prepared=stage['output']['prepared']
        rt=prepared['final_request']['runtime_input'];a=next(a for a in attempts if a['logical']==logical+':FINAL')
        body=json.loads(a['request']['messages'][1]['content']);links=[]
        for i,f in enumerate(rt['memory']['facts']):
            mid=f['native_id'];selected=next(e for e in rt['evidence']['selected_evidence'] if e['evidence_id']==mid)
            rendered=next(e for e in body['source_facts'] if e['id']==mid)
            assert f['content']==selected['content']==rendered['content']
            assert f['native_version']==selected['version']==rendered['version']
            links.append(dict(native_id=mid,version=f['native_version'],source_ref=f['source_ref'],
                content_sha256=sha(f['content'].encode()),raw_text_unchanged=True,version_unchanged=True,
                envelope_source=reference(mp,f'/output/prepared/final_request/runtime_input/memory/facts/{i}')))
        memory_rows.append(dict(logical=logical,identity=row['memory_diagnostics']['identity'],
            readonly_state_unchanged=row['memory_diagnostics']['readonly_state_unchanged'],bindings=links,
            exact_native_to_compiler_to_final_readback=True,
            limit='Saved receipt/content readback only. No store was reopened and no encoder inference repeated. Free-text parsing and semantic applicability are separate.'))
    jsonl('M1_TO_FINAL_PRESERVATION_AUDIT.jsonl',memory_rows)
    test_reports=[read(HERE/f'test_output/{s}.json') for s in ('p0','p1','i1','i3')]
    assert all(r['errors']==r['failures']==r['skipped']==0 for r in test_reports)
    tests=dict(suites=test_reports,distinct_tests_passed=sum(r['passed'] for r in test_reports),
        original_tests_passed=sum(r['passed'] for r in test_reports if r['suite']!='i3'),
        new_tests_passed=test_reports[-1]['passed'],network_or_provider_calls=0,
        earlier_harness_failure=dict(path='test_output/i1_initial_harness_error.txt',errors=9,
            cause='I3 helper named common shadowed historical M0 common in sys.modules. Renamed only the new helper to i3_common; original I1 tests then passed 54/54.',
            represents_planner_defect=False),
        exclusions='Eight test_runner_gates.py tests were not run because they invoke run_pilot.main. No execution script was auto-run.')
    write('OFFLINE_TEST_SUMMARY.json',tests)
    schema_anchor=anchor('utils/c4_rebuild/i1/schemas.py','def strict_subset')
    stop_anchor=anchor('utils/c4_rebuild/i1/orchestrator.py','structural = errors')
    checker_anchor=anchor('research_followups/rq3_rebuild/p0_planner_prototype/p0planner/validator.py','def validate_candidate')
    advice_anchor=anchor('research_followups/rq3_rebuild/p0_planner_prototype/p0planner/validator.py','Actions explicitly unscheduled')
    fallback_anchor=anchor('utils/c4_rebuild/i1/renderer.py',"'CANDIDATE_FAILED':")
    render_anchor=anchor('utils/c4_rebuild/i1/renderer.py','def candidate_payload')
    sample=next(r for r in matrix if r['logical']=='I0-SYN-06:S5_FULL' and r['attempt_number']==1)
    badref=next(r for r in matrix if r['logical']=='I0-SYN-07:S4_EVIDENCE_PLANNING' and r['attempt_number']==1)
    root=f'''# I3 Planner failure diagnosis — actual I2 evidence

Status: READY_FOR_LIMITED_PLANNER_RETEST_APPROVAL. This is an exposed synthetic DEV implementation diagnosis. No model, Provider, Judge or human-scoring call was made in I3. A proposed prompt repair is ready to test, not proven effective.

## Recovered facts and immediate cause

The actual I2 ZIP was read and verified at SHA-256 `b9506c17b67640b7868e9d9c4016f22f83d47934a844779e7a108987db3175f0`, 1,695,368 bytes, 791 unique members, CRC and every manifest hash passing. `PREFLIGHT.json` records this live verification. The review receipt was not used in place of payloads. There are 24 route attempts (8 per RAG/Memory/B4), 32 returned candidate attempts for 16 logical slots, and 72 FINAL attempts: 128 physical attempts. The B4 bit is not a candidate. See the 72 rows in `I2_ACTUAL_ROLE_AND_MODULE_RECONCILIATION.json` and `CASE_MODE_RECONCILIATION.md`.

All 32 actual candidate responses are syntactically valid JSON, finish with stop, match the saved model snapshot, and pass the saved Provider response schema. All then fail local array cardinality checks: top-level `evidence_refs=[]` in 32/32, plus empty action references, yielding **128 saved error occurrences**. Each array must have at least one item. These are legitimate violations of the existing reference contract, not proven false rejections. `PLANNER_ATTEMPT_ERROR_MATRIX.jsonl` contains every raw/request/input binding, original issue and replay result. Example: `{sample['raw_source']}`; input `{sample['exact_input_source']}`; the 15-minute budget and unscheduled state are present, but missing references cause rejection first.

The orchestrator returns early on these structural errors (`{stop_anchor}`). Therefore none of these attempts reached the later goal/source/time/budget semantic checking stage in the actual admission path. ENCODED_CHECK is an umbrella runner status, **not evidence that 32 plans were rejected for infeasible schedules**. The complete P1 checker reports in the matrix also stop at candidate schema. No old candidate was filled with invented references to force the later checks to run.

## Confirmed contract defects and their evidential limits

1. **Undisclosed local constraints.** The strict wire conversion drops minItems, maxItems, minLength and related constraints (`{schema_anchor}`). Retaining a stricter local validator is legitimate, but the I1 candidate prompt does not disclose those omitted limits. In particular both nonempty reference requirements disappear from the sent schema. The local I0 candidate schema equals the P1 candidate schema exactly; there is no evidence of an incompatible field-name projection. The defect is the incomplete candidate instruction contract, not an established Provider schema transport failure. A prompt fix may help; only fresh calls can show that.
2. **Correction feedback lacks the required bound.** All 16 correction requests contain the exact previous candidate and the original issue list. Nothing was silently dropped. But `$.evidence_refs:ARRAY_LENGTH` does not state minimum 1 or observed length 0; the correction still sees the same relaxed wire schema. All 16 corrections repeat the original issue set, and 11 return an identical parsed candidate. Feedback was present but underspecified; the model's counterfactual response to better feedback is unknown.
3. **Candidate prompt contains FINAL-only directions.** The system text sent for candidates talks about answer/cited fields and setting plan_fields, which are absent from the candidate response schema (`{render_anchor}`). The schema appears to have prevailed because returned candidates do not contain these fields. The inconsistency is confirmed; its causal contribution to the empty references is unproven. The repair removes this text only from the candidate instruction.
4. **Reference identification is insufficiently explicit.** Existing `source_facts` expose exact IDs, and encoded goals refer to current-request. The current-request fact is not listed among source_facts even though the checker accepts its exact ID for the current query. The repair adds a verified ID-to-existing-content-pointer catalog; it does not replace IDs or introduce new source facts. Ten actual attempts contain 29 occurrences of fabricated identifiers such as source:recording_rows, source:activity_patterns and source:activity. These are objectively absent from the permitted facts, but were masked by earlier schema rejection. See `{badref['raw_source']}` and the `secondary_inspection` field of every matrix row. Never label them as originally observed EVIDENCE_ID_MISSING errors.
5. **Fallback confounds internal failure with learner information gaps.** `{fallback_anchor}` converts any candidate failure into the same request for necessary information. All 16 failed slots send accepted_plan=null plus this summary; no rejected candidate is smuggled in as an approved plan. Four answers cite a need for a reliable schedule despite ordinary, no-date requests. The final renderer remains unchanged in I3; repairing its policy is a separate decision, not necessary to retest candidate references.

## Alternatives A–G

| Category | Evidence-based conclusion |
|---|---|
| A — impossible or underspecified request | Two I0-SYN-09 planning conditions legitimately stop before candidate generation. They request scheduling but lack an explicit learner timezone, horizon and precise availability. S5 additionally retains an unparsed compound time constraint. Prior-plan continuation cases also lack an accepted active-plan object; exact continuation cannot be certified even if generic advice is possible. |
| B — invalid candidate with usable input | All 32 have empty required reference arrays. Ten also contain fabricated source IDs. Current-query/selected fact IDs were available. This establishes candidate defects, not general model weakness. |
| C — schema/renderer/checker mismatch | Confirmed omitted local bounds and FINAL-only candidate instructions. I0/P1 local shapes match; no evidence of a lossful candidate output projection. |
| D — valid ordinary advice falsely rejected | Not established: every saved candidate violates nonempty references. The independent advice-without-calendar control passes the unchanged checker (`{advice_anchor}`). |
| E — unnecessary/unavailable calendar required | No saved candidate had a schedule and no saved rejection was a time requirement. Unnecessary calendar requests appear in fallback prose. The two actual scheduling gates are justified. |
| F — Memory/compiler/candidate information loss | All 14 saved hybrid conditions preserve native text/version through compiler to FINAL, verified in `M1_TO_FINAL_PRESERVATION_AUDIT.jsonl`; all admitted-candidate Memory text copies also match. Numeric 15 survives and is encoded. The compound twenty-minutes sentence in I0-SYN-09 survives as raw text but is intentionally unencoded. Missing active-plan/acceptance information cannot be invented from activity or native record IDs. No lost selected Memory text explains the 32 failures. |
| G — unresolved | Later semantic/source checks for old invalid candidates were not reached; the prompt fix has no live result; natural-language support, prior-plan adoption, relative-week validity, actual feasibility and all human quality judgments remain unresolved. |

## What was minimally repaired

`repair_v1.py` adds omitted local bounds, exact reference catalog pointers and original-error details (including observed/required lengths) to candidate requests. It validates each bridge and verifies every catalog ID/content against already-rendered input. It preserves the original previous candidate and all concrete issues. Its admission sequence still invokes the original schema and checker. `INTEGRATION_PATCH_NOT_APPLIED.patch` proposes one candidate-renderer import change; the historical orchestrator and all P0/P1/I0/I1/I2 files remain untouched. Model gpt-4o-mini-2024-07-18, temperature, token caps, retry budget, Provider wire schema, P3, RAG and Memory policy are unchanged. Only the candidate contract name/instructions/body supplement change.

The complete old/new table remains **32 ENCODED_CHECK → 32 ENCODED_CHECK**. This is POST-HOC OFFLINE DIAGNOSTIC ONLY, never a revised I2 result. No later/better candidate was selected. All budgets, source/scope permissions, validity, completed-task and scheduling checks remain in place. The +40% unsupported semantic claim with valid IDs still passes encoded checks and is explicitly retained as a **known unchecked semantic counterexample**, not repaired by a source-ID match.

## Actual FINAL reading and remaining decisions

All 72 raw answers were read as DEV material and copied without rewriting. `ANSWER_READING_COPY_INDEX.json` binds exact UTF-8 answer bytes to raw responses and reading-copy byte ranges. Student-facing text has no detected retained evidence ID or raw checker-code leaks; the phrase checked plan appears in failed outputs. FINAL independently writes steps in I0-SYN-06:S5_FULL, I0-SYN-07:S4_EVIDENCE_PLANNING and I0-SYN-10:S5_FULL even though their plan_fields and accepted_plan are null. This is distinct from Planner success.

Technical flags with exact source/answer spans are in `FINAL_FALLBACK_AND_INPUT_TRACE.jsonl`. Examples include the preserved 15-minute budget and quadratic-formula topic in I0-SYN-06:S5_FULL, worksheet intermediate-expression/substitution phrases when the chunk is actually present, and the specific missing-time questions in I0-SYN-09. Lexical preservation is not correctness or completeness. Potential concerns include six view events phrased as six videos, learner-goal inference from activity in I0-SYN-06:S0–S2, and an August this-week goal phrased as current in September. These need manual verification; no quality score, rationale in a human form, mode ranking or final-effect analysis has been produced. No explicit quantified budget overrun or invented dated interval was established in the 72 answers. Unsupported causal claims about missing information and calendar necessity are shown directly, rather than manufacturing a broader constraint-violation rate.

There are {tests['distinct_tests_passed']} passing distinct offline tests: P0 70, P1 85, I1 54 and I3 31. Eight I1 execution-entrypoint gate tests were deliberately excluded. An initial new-harness import collision caused nine I1 errors and was repaired solely by namespacing the I3 utility; its original error log is retained. See `OFFLINE_TEST_SUMMARY.json`. Read `MINIMAL_LIVE_RETEST_PLAN_NOT_AUTHORIZED.md` for the five selected candidate slots and exact dependency rules. No new call is authorized by this report.
'''
    (HERE/'PLANNER_FAILURE_ROOT_CAUSE.md').write_text(root)
    selected=[('I0-SYN-04:S4_EVIDENCE_PLANNING','Empty references with ordinary advice and dashboard-only context'),
              ('I0-SYN-04:S5_FULL','Empty references with actual worksheet chunk and selected Memory'),
              ('I0-SYN-06:S5_FULL','Explicit 15-minute encoded budget and native Memory ID retention'),
              ('I0-SYN-07:S4_EVIDENCE_PLANNING','Fabricated source IDs masked by empty arrays; absent active-plan object'),
              ('I0-SYN-11:S5_FULL','Requested worksheet absent from retained RAG facts; distinguish request intention from unavailable source content')]
    plan_rows=[]
    for logical,reason in selected:
        first=next(m for m in matrix if m['logical']==logical and m['attempt_number']==1)
        final=next(a for a in attempts if a['logical']==logical+':FINAL')
        plan_rows.append(dict(logical=logical,selection_reason=reason,initial_candidate_attempt_id=first['attempt_id'],
            frozen_input_sha256=first['input_snapshot_sha256'],frozen_input_source=first['exact_input_source'],
            proposed_initial_request=f"proposed_requests_not_authorized/{first['attempt_id']}.json",
            proposed_initial_request_sha256=sha(read(HERE/f"proposed_requests_not_authorized/{first['attempt_id']}.json")),
            dependent_final_logical=logical+':FINAL',prior_final_attempt_id=final['attempt_id'],prior_final_request_sha256=final['request_sha256']))
    write('MINIMAL_RETEST_DEPENDENCIES_NOT_AUTHORIZED.json',dict(selected=plan_rows,
        impacted_but_not_default_retest=[m['logical'] for m in matrix if m['attempt_number']==1 and m['logical'] not in dict(selected)],
        candidate_initial_calls=5,candidate_corrections_max=5,conditional_final_calls_max=5,
        routing_calls=0,retrieval_or_embedding_calls=0,provider_authorized=False,
        correction_rule='Fresh first result only, exact checker feedback, at most one correction; never replay the old proposed second-attempt body as a fresh repair.',
        ordinary_missing_source='Do not treat current-request as evidence for worksheet contents; uncertainty may remain even after schema validity.'))
    plan='''# Minimal future retest — NOT AUTHORIZED

No model calls may be made under I3. This document proposes a new, separately authorized, exposed synthetic DEV retest using the exact same generator snapshot, gpt-4o-mini-2024-07-18. It does not authorize student deployment, quality scoring or final mode comparisons.

Select five logical slots by observed failure category, with IDs and all hashes in `MINIMAL_RETEST_DEPENDENCIES_NOT_AUTHORIZED.json`:

| Candidate slot | Diagnostic reason | Dependent FINAL slot |
|---|---|---|
'''
    for logical,reason in selected:plan+=f'| {logical}:CANDIDATE | {reason} | {logical}:FINAL |\n'
    plan+='''
The five fresh initial candidates require new inference because a corrected request cannot alter old outputs. Permit at most one correction per failed initial candidate under the original budget; preserve the first accepted attempt mechanically, never select by subjective quality. Thus the proposal is 5 initial + at most 5 correction calls. The 32 JSON requests under `proposed_requests_not_authorized/` are offline request-diff artifacts; second-attempt files contain OLD failure history and must not be dispatched as future correction requests. Fresh correction requests must use the fresh first result and exact checker output.

Only if a newly accepted candidate changes accepted_plan from null to a validated object does the corresponding FINAL input need a fresh answer. There are at most five such dependent slots, and running them also needs direct authorization covering FINAL. Retain failed, no-plan FINAL inputs without pointless regeneration if their full payload hash is identical. All 16 historical candidate slots are affected by the common candidate-renderer change; eleven are deferred rather than silently declared successful. Do not rerun all 72 answers. FINAL's renderer is unchanged. A future change to common FINAL instructions would require recomputing every one of the 72 payload hashes and reevaluating every changed payload under a separate scope.

Keep I0-SYN-09:S4 and S5 as offline scheduling-gate controls: 0 candidate calls while timezone, horizon and windows are missing. Preserve wrong learner/course, revoked/expired source, impossible schedule, ambiguous plan, missing-ID, completed-task and +40% semantic controls offline. Do not alter user inputs to make these pass. I0-SYN-07 has no accepted active plan; passing references would not establish valid continuation. I0-SYN-11 lacks worksheet content; a request citation cannot stand in for it.

Before any approved retest, verify the original I2 ZIP hash, source-record bytes, 161 frozen-source registry entries, starting/end Git lineage, original four-field routing input, role prompts/schemas and model settings. For each selected slot compare the saved C_MODULE_REBUILD output hash, scope/learner/course/as_of, source and corpus versions, selected evidence/native IDs and versions, permissions/validity and compiler/planner bridge hash with the dependency manifest. Reuse only those exact frozen synthetic prepared snapshots. Do not reinterpret the old as_of as a current student snapshot. Any identity drift stops reuse; no silent re-retrieval, source filling, model download or Memory refresh.

Routing and retrieval calls proposed: 0. Reuse the 24 saved router attempts and matching module outputs as read-only frozen evidence after the above checks. Never call the original orchestrator's prepare path to regenerate M1/RAG for this limited replay. Freeze a new candidate-contract version, config/input manifest and reviewed harness that consumes only the saved prepared inputs and the new pure renderer. The proposed integration patch alone does not create an approved runtime or override frozen authorization gates.

Use a fresh versioned directory, for example `RQ3_REBUILD_I4_LIMITED_PLANNER_RETEST_OUTPUT_<RUN_DATE>`, after explicit authorization. Never resume I2's directory. Keep all previous candidates/answers and status records unchanged and separately labeled. Record every raw request/response/error, exact model, token/call caps and hashes. Stop on unknown completion or model/source drift; no extra canary, retry, model change or bulk rerun. No human scores, generated review rationales or effect comparisons are part of this plan. Present concrete payloads and ceilings in the future direct authorization request; elapsed time and I3 completion do not grant approval.
'''
    (HERE/'MINIMAL_LIVE_RETEST_PLAN_NOT_AUTHORIZED.md').write_text(plan)
    blank='''# Blank human DEV inspection checklist

Only the author/reviewer may fill this file. All observations, judgments and notes below are blank. This is exposed synthetic DEV material, not independent human evaluation completion and not a rating dataset. AI technical diagnostics live in separate files and must not be copied into human fields as human judgments. No scores or suggested rationales are provided.

Reviewer: __________  Date: __________  Reviewed source version: __________

- [ ] I read the unaltered answer and its authorized input before forming my own view.
- [ ] I checked source scope and time applicability.
- [ ] I distinguished requests, learner facts, system suggestions and completed actions.
- [ ] I checked whether clarification was necessary and specific.
- [ ] I inspected plans/constraints and any factual claims in the actual wording.
- [ ] I distinguished mechanical validation from answer quality.

| Case and mode | Human observation | Source/answer span | Needs follow-up | Reviewer initials |
|---|---|---|---|---|
'''
    for t in traces:blank+=f"| {t['logical']} | | | | |\n"
    blank+='\nAdditional human notes: __________\n'
    (HERE/'HUMAN_DEV_CHECKLIST_BLANK.md').write_text(blank)
    write('GIT_START_RECEIPT.json',dict(starting_head=START,branch='research/rq3-rebuild-i1-pilot-launch',
        initial_tracked_state='CLEAN',initial_untracked_files=[],authorized_new_scope=SCOPE,
        ending_receipt='Review ZIP root GIT_VERSION.json is generated from actual Git after the single commit; self-referential commit hashes are not fabricated.'))
    (HERE/'START_HERE.md').write_text('''# I3 Planner diagnosis review

Status: **READY_FOR_LIMITED_PLANNER_RETEST_APPROVAL**. No new model or Provider call is authorized.

Read I3_COMPLETION_REPORT.md, then PLANNER_FAILURE_ROOT_CAUSE.md. All 32 actual candidate attempts are in PLANNER_ATTEMPT_ERROR_MATRIX.jsonl; all 72 FINAL traces are in FINAL_FALLBACK_AND_INPUT_TRACE.jsonl. Read the unaltered answers in DEVELOPMENT_READING_COPY_VERIFIED.md; ANSWER_READING_COPY_INDEX.json verifies their exact bytes. HUMAN_DEV_CHECKLIST_BLANK.md is entirely unfilled.

repair_v1.py only improves candidate contract visibility. INTEGRATION_PATCH_NOT_APPLIED.patch has not changed historical runtime code. OFFLINE_OLD_NEW_CLASSIFICATION_AUDIT.json keeps all 32 old outputs rejected. proposed_requests_not_authorized/ contains offline request previews, not callable jobs or authorization.

sources/live/ is an exact byte copy of the allowlisted actual I2 requests/results/stages, cross-checked against the local I2 ZIP. snapshot/ holds unchanged committed checker/renderer dependencies and original test source for inspection. SOURCE_PRESERVATION_MANIFEST.json distinguishes every copied origin. No credentials, model weights, databases, unrelated corpus or private human answers are included.

In the original checkout, run `python3 -B research_followups/rq3_rebuild/i3_planner_diagnosis_repair/audit_saved.py` and `python3 -B research_followups/rq3_rebuild/i3_planner_diagnosis_repair/run_offline_tests.py i3` for the saved replay and 31 new checks. Run offline suites p0/p1/i1 with the same test wrapper. The wrapper never runs an execution entrypoint. An extracted review can reproduce the saved replay and I3 controls with reproduce_review.py in a fresh temporary directory; original P0/P1/I1 suite reproduction uses the original checkout.

The ZIP root OUTPUT_MANIFEST.json binds all other members; its own hash is explicitly excluded. GIT_VERSION.json records exact post-commit IDs. The external ZIP readback receipt binds the ZIP's SHA-256, byte size, member count and CRC; no archive hashes itself and no upload is claimed.
''')
    notes=Counter(n['kind'] for t in traces for n in t['technical_observations'])
    write('TECHNICAL_OBSERVATION_INDEX.json',dict(non_scoring=True,manual_verification_required=True,counts=dict(notes),
        answer_ID_or_checker_code_matches=sum(len(t['implementation_ID_or_checker_code_matches']) for t in traces),
        all_72_answers_read_as_DEV=True,no_numeric_quality_labels=True,no_human_dataset_written=True))
    print(dict(snapshot_files=len(names),tests=tests['distinct_tests_passed'],memory_conditions=len(memory_rows),notes=dict(notes)))


if __name__=='__main__':main()
