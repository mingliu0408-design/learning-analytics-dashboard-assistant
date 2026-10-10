"""Reproduce every saved attempt; derive evidence-bound, non-scoring DEV traces."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
import re
import sys
from i3_common import HERE, ROOT, read, write, jsonl, sha, canonical, live_records, reference

sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.renderer import candidate_payload as old_payload, final_payload
from utils.c4_rebuild.i1.schemas import errors, LOCAL_CANDIDATE, final_errors
from utils.c4_rebuild.planning import validate_candidate, validate_bridge
from repair_v1 import candidate_issues, candidate_payload, feedback_details, local_rules, reference_catalog

BLOCKING = ('ERROR', 'CONTRADICTION', 'NOT_CHECKABLE')


def same_issues(a, b):
    return sorted(canonical(i) for i in a) == sorted(canonical(i) for i in b)


def slot_name(logical):
    return logical.removesuffix(':CANDIDATE').removesuffix(':FINAL')


def claim_span(answer, quote):
    start = answer.find(quote)
    assert start >= 0, quote
    return dict(text=quote, start_char=start, end_char=start+len(quote), manual_verification_required=True)


def technical_notes(logical, answer, body, failed, bridge):
    """Literal trace anchors plus bounded technical observations, never human labels."""
    notes = []
    def add(kind, quote, detail, dependency):
        notes.append(dict(kind=kind, answer_span=claim_span(answer,quote), observation=detail, input_dependency=dependency))
    if failed:
        markers = ('Based on your current activity in the lecture, I can suggest some next steps:',
                   'here are some suggested next steps:')
        for marker in markers:
            if marker in answer:
                add('FINAL_WROTE_STEPS_WITHOUT_ACCEPTED_MODULE_PLAN', marker,
                    'FINAL independently wrote steps with accepted_plan=null; not a Planner success.', '/accepted_plan')
                break
        if 'checked plan' in answer:
            add('INTERNAL_FAILURE_CONCEPT_IN_PROSE', 'checked plan',
                'Student-facing prose mentions the internal checked-plan concept; no raw checker code is implied.', '/information_needed')
        if 'reliable schedule' in answer and bridge['source_input']['task_request']['mode']=='ORDINARY_ACTION_ADVICE':
            add('UNNECESSARY_CALENDAR_EXPLANATION', 'reliable schedule',
                'The input requests ordinary advice and the saved rejection was empty references, not a calendar failure.',
                'bridge/source_input/task_request; saved candidate outcome/issues')
        if 'lack of specific information' in answer:
            add('FALLBACK_CAUSAL_ATTRIBUTION_NOT_ESTABLISHED', 'lack of specific information',
                'The recorded cause is ARRAY_LENGTH. Input preconditions passed; this phrase is not an established cause of rejection.',
                'bridge validation and candidate outcome/issues')
        if 'lack of specific goals or actions outlined' in answer:
            add('FALLBACK_CAUSAL_ATTRIBUTION_NOT_ESTABLISHED', 'lack of specific goals or actions outlined',
                'The runtime includes the current-request goal; the checker did not reject a missing goal.',
                'bridge/planner_input/goals; candidate outcome/issues')
    if ':S' in logical and logical.startswith('I0-SYN-09:'):
        for token, pointer in [('timezone','/time_context/timezone'),('available','/time_context/allowed_windows'),('period','/time_context/horizon')]:
            if token in answer.lower():
                quote=answer[answer.lower().index(token):answer.lower().index(token)+len(token)]
                add('SCHEDULE_CLARIFICATION_WITH_MISSING_INPUT', quote,
                    'Explicit scheduling was requested; no learner scheduling timezone, precise windows or horizon was supplied. Dashboard timezone is a different field.', pointer)
    if 'Your current goal seems to be focused on engaging with the lecture materials effectively.' in answer:
        add('INFERRED_GOAL_WITHOUT_SUPPLIED_LEARNER_GOAL',
            'Your current goal seems to be focused on engaging with the lecture materials effectively.',
            'This wording infers a learner goal from activity; source_facts has no learner-goal record in this condition. Author should inspect against the no-invented-goals instruction.', '/source_facts')
    for i, f in enumerate(body['source_facts']):
        content=f['content']
        pointer=f'/source_facts/{i}/content'
        if isinstance(content,str) and 'I have 15 minutes.' == content and '15 minutes' in answer:
            add('TRACEABLE_BUDGET_MENTION', '15 minutes',
                'The declared budget survives in wording. No assertion that all proposed work fits the budget.', pointer)
        if isinstance(content,str) and 'twenty minutes' in content and 'twenty minutes' in answer:
            add('TRACEABLE_UNENCODED_BUDGET_MENTION', 'twenty minutes',
                'The original free-text constraint survives. The compound sentence is not parsed into an encoded budget.', pointer)
        if isinstance(content,str) and content.startswith('My goal this week'):
            if 'explain why the quadratic formula works' in answer:
                add('TRACEABLE_GOAL_TOPIC_MENTION','explain why the quadratic formula works',
                    'Topic is present in the supplied learner statement; this does not establish current-week applicability or achieved mastery.',pointer)
            if 'goal this week' in answer or 'goal for the week' in answer or 'goal for the week was' in answer:
                quote=next(q for q in ('goal this week','goal for the week') if q in answer)
                add('RELATIVE_WEEK_REQUIRES_AUTHOR_VERIFICATION',quote,
                    'Source was observed on 2026-08-10 while as_of is 2026-09-02. Active/no-declared-expiry metadata alone does not resolve the phrase this week.',f'/source_facts/{i}/source/observed_at; /time_context/as_of')
        if f['kind']=='COURSE_RAG':
            course_text=content if isinstance(content,str) else content['text']
            course_pointer=pointer if isinstance(content,str) else pointer+'/text'
            for phrase in ('intermediate expressions','substitution','worked example'):
                if phrase in answer and phrase in course_text:
                    add('TRACEABLE_WORKSHEET_PHRASE',phrase,
                        'The phrase occurs in supplied worksheet content and answer; lexical agreement is not a correctness/completeness metric.',course_pointer)
        if isinstance(content,dict):
            lecture=(content.get('activity') or {}).get('Lecture',{})
            if lecture and 'total of 6 videos' in answer:
                add('EVENT_COUNT_VERSUS_UNIQUE_VIDEO_AMBIGUITY','total of 6 videos',
                    'Input says video_views is a sum of view events and contains two recording rows. Wording may be read as six distinct videos; manual verification is required.',pointer+'/activity/Lecture/video_views; '+pointer+'/recording_rows')
            if lecture and '60%' in answer:
                add('TRACEABLE_MEAN_VIEW_PERCENT','60%',
                    'Input mean_view_percent.value is 60.0. This literal match certifies neither mastery nor the surrounding interpretation.',pointer+'/activity/Lecture/mean_view_percent')
            resource=(content.get('activity') or {}).get('Resources',{})
            if resource and '3 views' in answer:
                add('TRACEABLE_RESOURCE_VIEW_COUNT','3 views','Answer repeats a scoped resource-view count; not a learning-effect measure.',pointer+'/activity/Resources')
    return notes


def main():
    live, stages, attempts = live_records()
    for _,stage in stages.values():
        assert sha(stage['output'])==stage['output_sha256']
    terminals=[read(p) for p in (live/'terminals').glob('*.json')]
    for terminal in terminals:
        outcome_path=live/'attempts'/f"{terminal['attempt_id']}.outcome.json"
        outcome=read(outcome_path)
        assert terminal['result']==outcome and sha(outcome_path.read_bytes())==terminal['outcome_sha256']
        first=next(a for a in attempts if a['logical']==terminal['logical'] and a['attempt']==1)
        assert terminal['initial_request_sha256']==first['request_sha256']
    journal=[json.loads(line) for line in (live/'JOURNAL.jsonl').read_text().splitlines()]
    for a in attempts:
        entries=[j for j in journal if j.get('attempt_id')==a['attempt_id'] and j['event']=='ATTEMPT_RESERVED_BEFORE_TRANSPORT']
        assert len(entries)==1 and {k:v for k,v in entries[0].items() if k!='event'}==a
    write('SAVED_RECEIPT_CHAIN_VERIFICATION.json',dict(stages_verified=len(stages),terminal_outcome_bindings_verified=len(terminals),
        journal_reservations_verified=len(attempts),status='PASS',model_calls=0))
    config=read(ROOT/'research_followups/rq3_rebuild/i1_pilot_launch/PILOT_CONFIGURATION_PROPOSED.json')
    matrix=[]; transitions=[]; per_slot={}; bindings=[]; parser_counts=Counter(); role_counts=Counter()
    for start in attempts:
        aid=start['attempt_id']; role=start['role']; role_counts[role]+=1
        outcome_path=live/'attempts'/f'{aid}.outcome.json';raw_path=live/'attempts'/f'{aid}.raw.json'
        outcome=read(outcome_path); raw=read(raw_path)
        assert sha(start['request'])==start['request_sha256']==outcome['request_sha256']
        assert sha(raw_path.read_bytes())==outcome['raw_sha256']
        if role != 'CANDIDATE':
            if role=='FINAL':
                logical=slot_name(start['logical']);prepared=stages[logical,'C_MODULE_REBUILD'][1]['output']['prepared']
                plan=stages[logical,'D_E_CANDIDATE_CHECK_REPAIR'][1]['output']['accepted_plan']
                validator=lambda v:final_errors(v,prepared['trace']['retained_evidence_ids'],plan)
            else:
                validator=lambda v:[]
            status,value,issues=parse_response(raw,start['request'],validator)
            assert status==outcome['status'] and value==outcome['value'] and same_issues(issues,outcome['issues'])
            parser_counts[(role,status)]+=1
            continue
        body=json.loads(start['request']['messages'][1]['content'])
        logical=slot_name(start['logical']);module_path,module=stages[logical,'C_MODULE_REBUILD'];prepared=module['output']['prepared']
        bridge=prepared['planner']['bridge'];value=outcome['value'];pre=validate_bridge(bridge)
        old=lambda v:candidate_issues(bridge,v)
        status,parsed,replayed=parse_response(raw,start['request'],old)
        assert status==outcome['status'] and parsed==value and same_issues(replayed,outcome['issues'])
        assert pre['outcome']=='PASSED_ENCODED_CHECKS'
        parser_counts[(role,status)]+=1
        full=validate_candidate(bridge,value)
        structural=errors(value,LOCAL_CANDIDATE)
        wire_errors=errors(value,start['request']['response_format']['json_schema']['schema'])
        previous=None;received=[];previous_outcome=None
        if start['attempt']>1:
            previous_outcome=read(live/'attempts'/f"{aid.rsplit('.',1)[0]}.{start['attempt']-1}.outcome.json")
            previous=previous_outcome['value'];received=body['concrete_checker_issues']
            assert previous==body['previous_candidate'] and received==previous_outcome['issues']
        expected_old=old_payload(prepared,config['generation_roles']['CANDIDATE'],previous,received)
        assert expected_old==start['request']
        new=candidate_payload(prepared,config['generation_roles']['CANDIDATE'],previous,received)
        new_status,new_value,new_issues=parse_response(raw,new,old)
        assert new_value==value and same_issues(new_issues,replayed)
        write(f'proposed_requests_not_authorized/{aid}.json',new)
        facts=bridge['planner_input']['facts'];pids={f['fact_id'] for f in facts}
        refs=[]
        for i,a in enumerate(value['actions']):
            for j,fid in enumerate(a['evidence_refs']):
                refs.append(dict(path=f'$.actions[{i}].evidence_refs[{j}]',id=fid,in_permitted_facts=fid in pids))
            for j,fid in enumerate(a['estimated_duration']['evidence_refs']):
                refs.append(dict(path=f'$.actions[{i}].estimated_duration.evidence_refs[{j}]',id=fid,in_permitted_facts=fid in pids))
        for j,fid in enumerate(value['evidence_refs']):refs.append(dict(path=f'$.evidence_refs[{j}]',id=fid,in_permitted_facts=fid in pids))
        errors_detailed=[]
        for detail in feedback_details(value,outcome['issues']):
            detail.update(stage='LOCAL_STRUCTURAL_CONSTRAINT_BEFORE_P1_SEMANTIC_CHECK',
                classification=['B_INVALID_CANDIDATE_REFERENCE_ARRAY','C_UNDISCLOSED_LOCAL_SCHEMA_LIMIT'],
                source_dependencies=[reference(outcome_path,'/value'),
                    'snapshot/research_followups/rq3_rebuild/i0_human_integration/schemas/STRUCTURED_PLAN_SCHEMA.json',
                    reference(module_path,'/output/prepared/planner/bridge/planner_input/facts')],
                source_evidence='The returned array has length zero while the local schema requires minItems=1; wire schema omits this keyword.',
                observed_rejection=True)
            errors_detailed.append(detail)
        total=sum(Decimal(str(a['estimated_duration']['value'])) for a in value['actions'] if a['estimated_duration']['value'] is not None)
        budget=bridge['planner_input']['hard_constraints']['budget']
        goal=next((g for g in bridge['planner_input']['goals'] if g['goal_id']==value['goal_id']),None)
        secondary=dict(status='STATIC_INSPECTION_ONLY_NOT_ORIGINAL_CHECKER_REJECTIONS',nonempty_reference_checks=refs,
            invalid_nonempty_references=[r for r in refs if not r['in_permitted_facts']],
            goal_id_and_verbatim_text_match=bool(goal and goal['text']==value['goal']),
            declared_estimate_sum_minutes=str(total),encoded_budget=budget,
            exceeds_encoded_budget=bool(budget['minutes'] is not None and total>Decimal(str(budget['minutes']))),
            schedules_all_null=all(a['schedule'] is None for a in value['actions']),
            later_semantic_checks='NOT_REACHED_BY_ORIGINAL_ADMISSION; no fabricated references inserted to unmask them')
        memory=[]
        for i,m in enumerate(bridge['source_input']['selected_memory']):
            mid=m['native']['memory_id'];fact=next(f for f in facts if f['fact_id']==mid)
            rendered=next(f for f in body['source_facts'] if f['id']==mid)
            assert m['native']['content']==fact['value']==rendered['content']
            memory.append(dict(native_id=mid,native_version=m['native']['timestamp_version']['version'],
                source_span=m['binding']['source_span'],raw_text_sha256=sha(m['native']['content'].encode()),
                content_exact_native_to_checker_to_candidate=True,source=reference(module_path,f'/output/prepared/planner/bridge/source_input/selected_memory/{i}')))
        row=dict(logical=logical,attempt_id=aid,attempt_number=start['attempt'],request_sha256=start['request_sha256'],raw_sha256=outcome['raw_sha256'],
            raw_source=reference(raw_path),request_source=reference(live/'attempts'/f'{aid}.start.json'),outcome_source=reference(outcome_path),
            exact_input_source=reference(module_path,'/output/prepared'),input_snapshot_sha256=sha(bridge),
            provider_schema=start['request']['response_format']['json_schema'],provider_parser_status='VALID_JSON_STOP_EXACT_MODEL',
            provider_schema_errors=wire_errors,original_status=outcome['status'],replayed_status=status,all_saved_issues_reproduced=True,
            saved_issues=outcome['issues'],replayed_issues=replayed,errors=errors_detailed,
            original_local_report=full,input_precondition_report=pre,
            correction_received_specific_error=received if previous is not None else None,
            correction_feedback_equals_saved_original=True if previous is not None else None,
            repeated_error_paths_after_correction=same_issues(received,replayed) if previous is not None else None,
            returned_candidate_unchanged_after_correction=value==previous if previous is not None else None,
            secondary_inspection=secondary,memory_projection_readback=memory,
            input_ambiguity=dict(active_plan=bridge['planner_input']['active_plan'],intent=bridge['source_input']['task_request'],
                                 i0_diagnostics=bridge['i0_diagnostics']),
            later_checks_not_proven=['semantic entailment','ordinary-advice utility','full free-text constraints','actual time feasibility'])
        matrix.append(row);per_slot.setdefault(logical,[]).append(aid)
        transitions.append(dict(logical=logical,attempt_id=aid,old=status,new=new_status,
            old_issues=outcome['issues'],new_issues=new_issues,new_request_sha256=sha(new),
            unchanged_candidate_sha256=sha(value),classification='POST-HOC OFFLINE DIAGNOSTIC ONLY',
            new_provider_call=False,canonical_I2_result_changed=False))
        bindings.append(dict(logical=logical,attempt_id=aid,reference_catalog=reference_catalog(bridge,body),
            native_memory=memory,body_without_catalog_still_has_named_source_fact_ids=[f['id'] for f in body['source_facts']],
            current_request_ID_explicit_only_in_encoded_goal=True,final_only_instructions_in_candidate=True))
    jsonl('PLANNER_ATTEMPT_ERROR_MATRIX.jsonl',matrix)
    write('OFFLINE_OLD_NEW_CLASSIFICATION_AUDIT.json',dict(version='I3_OLD_NEW_V1',transitions=transitions,
        label='POST-HOC OFFLINE DIAGNOSTIC ONLY',canonical_results_modified=False,
        admission_rule_change='NONE: candidate-only rendering and explanatory feedback change',
        transitions_counts=dict(Counter(r['old']+' -> '+r['new'] for r in transitions)),
        prompt_effect_on_future_calls='UNTESTED; saved outputs cannot measure corrected prompt effectiveness'))
    jsonl('CANDIDATE_INPUT_BINDING_AUDIT.jsonl',bindings)
    case_rows=[];traces=[];answer_index=[];reading=bytearray();role_logicals={role:len({a['logical'] for a in attempts if a['role']==role}) for role in role_counts}
    reading.extend('# I3 actual I2 answer reading copy\n\nUnaltered decoded answer strings from 72 saved raw Provider responses. Synthetic DEV only; no human ratings. Administrative citation/plan fields remain in raw JSON. Each answer byte range is bound in ANSWER_READING_COPY_INDEX.json.\n'.encode())
    final_attempts={slot_name(a['logical']):a for a in attempts if a['role']=='FINAL'}
    for logical,start in sorted(final_attempts.items()):
        aid=start['attempt_id'];module_path,module=stages[logical,'C_MODULE_REBUILD'];prepared=module['output']['prepared']
        planner=prepared['planner'];rt=prepared['final_request']['runtime_input'];trace=prepared['trace']
        dpath,dstage=stages[logical,'D_E_CANDIDATE_CHECK_REPAIR'];d=dstage['output'];fpath,freeze=stages[logical,'F_G_RESPONSE_FREEZE']
        body=json.loads(start['request']['messages'][1]['content']);outcome=read(live/'attempts'/f'{aid}.outcome.json')
        raw=read(live/'attempts'/f'{aid}.raw.json');v=json.loads(raw['choices'][0]['message']['content']);answer=v['answer']
        assert v==outcome['value']==freeze['output']['result']['value']
        assert body['accepted_plan']==d['accepted_plan']==v['plan_fields']==None
        assert start['request']==final_payload(prepared,config['generation_roles']['FINAL'],d['accepted_plan'],d['planning_failed'])
        assert freeze['output']['final_request_sha256']==sha(start['request'])
        memory=trace.get('memory_diagnostics') or {}
        source_path,source=stages[logical.split(':')[0],'A_VALIDATED_SOURCE']
        primary=source['output']['primary_sha256'];route_pair=stages.get((primary,'B_FROZEN_P3'))
        case_rows.append(dict(logical=logical,scope=rt['scope'],primary_sha256=primary,
            shared_frozen_route=route_pair[1]['output']['route'] if route_pair else None,
            shared_route_stage=reference(route_pair[0]) if route_pair else None,
            effective_route=trace['route'],activation=trace['activation'],scope_source=reference(source_path),
            evidence_ids=trace['retained_evidence_ids'],course_returned_ids=trace['course_returned_ids'],
            memory_status=rt['memory']['status'],memory_diagnostics=memory,
            planning_requested_by_B4=bool((trace['route'] or {}).get('planning_required')),
            planning_precondition_report=planner['validation'] if planner else None,
            candidate_admitted=bool(planner and planner['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT'),
            raw_candidate_attempt_ids=per_slot.get(logical,[]),checker_terminal=d['result']['status'] if d['result'] else None,
            final_consumed_plan=body['accepted_plan'],final_failure_object=body['information_needed'],
            planning_stage=d,prepared_stage=reference(module_path),final_request=reference(live/'attempts'/f'{aid}.start.json')))
        bridge=planner['bridge'] if planner else None
        notes=technical_notes(logical,answer,body,d['planning_failed'],bridge)
        ids=trace['retained_evidence_ids']+per_slot.get(logical,[])
        leaks=[token for token in ids if token in answer]
        leaks += re.findall(r'ENCODED_CHECK|ARRAY_LENGTH|GOAL_BINDING_MISMATCH|I0-SYN-\d+|mem_[0-9a-f]+|page:[0-9a-f]+',answer)
        traces.append(dict(logical=logical,raw_answer_source=reference(live/'attempts'/f'{aid}.raw.json','/choices/0/message/content'),
            decoded_answer_sha256=sha(answer.encode()),final_payload_source=reference(live/'attempts'/f'{aid}.start.json','/request/messages/1/content'),
            prepared_stage=reference(module_path),planning_stage=reference(dpath),freeze_stage=reference(fpath),
            candidate_attempt_ids=per_slot.get(logical,[]),planning_status=d['planning_status'],
            failed_candidate_included_as_approved_plan=False,failed_candidate_raw_in_final_payload=False,
            failure_handling='FAILURE_SUMMARY_ONLY' if d['planning_failed'] else 'PRECONDITION_CLARIFICATION' if planner else 'NOT_ACTIVATED',
            accepted_plan=body['accepted_plan'],answer_plan_fields=v['plan_fields'],information_needed=body['information_needed'],
            implementation_ID_or_checker_code_matches=leaks,technical_observations=notes,
            raw_answers_rewritten=False,human_review_record_populated=False,
            review_limit='AI technical source/wording observations only; all semantic concerns require manual verification, no quality score or mode ranking.'))
        heading=f'\n## {logical}\n\nRaw record: `sources/live/attempts/{aid}.raw.json`\n\n<!-- BEGIN EXACT ANSWER {logical} -->\n'.encode()
        reading.extend(heading);begin=len(reading);encoded=answer.encode();reading.extend(encoded);end=len(reading)
        reading.extend(f'\n<!-- END EXACT ANSWER {logical} -->\n'.encode())
        answer_index.append(dict(logical=logical,raw_record=f'sources/live/attempts/{aid}.raw.json',answer_sha256=sha(encoded),bytes=len(encoded),
                                 reading_start_byte=begin,reading_end_byte_exclusive=end))
    (HERE/'DEVELOPMENT_READING_COPY_VERIFIED.md').write_bytes(reading)
    for r in answer_index:
        assert sha(bytes(reading[r['reading_start_byte']:r['reading_end_byte_exclusive']]))==r['answer_sha256']
    write('ANSWER_READING_COPY_INDEX.json',dict(entries=answer_index,count=len(answer_index),reading_copy_sha256=sha(bytes(reading)),all_answer_bytes_verified=True))
    jsonl('FINAL_FALLBACK_AND_INPUT_TRACE.jsonl',traces)
    counts=dict(actual_attempt_counts=dict(role_counts),logical_counts=role_logicals,
        total_physical_attempts=len(attempts),actual_candidate_attempts=len(matrix),actual_final_slots=len(traces),
        actual_candidate_terminal_counts=dict(Counter(c['checker_terminal'] for c in case_rows if c['raw_candidate_attempt_ids'])),
        actual_planning_status_counts=dict(Counter(c['planning_stage']['planning_status'] for c in case_rows)),
        hybrid_memory_conditions=sum(c['memory_diagnostics'].get('identity')=='M1_HYBRID_LINKS_DEV_CANDIDATE' for c in case_rows),
        hybrid_readonly_verified=sum(c['memory_diagnostics'].get('identity')=='M1_HYBRID_LINKS_DEV_CANDIDATE' and c['memory_diagnostics'].get('readonly_state_unchanged') is True for c in case_rows),
        repeated_issue_sets_after_correction=sum(m['repeated_error_paths_after_correction'] is True for m in matrix),
        identical_candidates_after_correction=sum(m['returned_candidate_unchanged_after_correction'] is True for m in matrix),
        saved_structural_error_occurrences=sum(len(m['saved_issues']) for m in matrix),
        attempts_with_nonempty_invalid_IDs=sum(bool(m['secondary_inspection']['invalid_nonempty_references']) for m in matrix),
        invalid_ID_occurrences=sum(len(m['secondary_inspection']['invalid_nonempty_references']) for m in matrix),
        parser_replay_counts={r+':'+s:n for (r,s),n in parser_counts.items()},
        actual_model_snapshots=sorted({read(live/'attempts'/f"{a['attempt_id']}.raw.json")['model'] for a in attempts}),
        missing_required_schedule_candidates=sum(c['planning_stage']['planning_status']=='NEEDS_INFORMATION' for c in case_rows),
        failure_final_independent_steps=[t['logical'] for t in traces if any(n['kind']=='FINAL_WROTE_STEPS_WITHOUT_ACCEPTED_MODULE_PLAN' for n in t['technical_observations'])])
    expected=dict(total_physical_attempts=128,actual_candidate_attempts=32,actual_final_slots=72,hybrid_memory_conditions=14)
    write('I2_ACTUAL_ROLE_AND_MODULE_RECONCILIATION.json',dict(counts=counts,case_mode_rows=case_rows,
        expected_receipt_counts=expected,discrepancies=[k for k,v in expected.items() if counts[k]!=v],
        roles_note='B4_PLANNING is a route bit, never an accepted structured plan. Source/module stages replayed from actual saved records without rerunning retrieval.'))
    lines=['# Actual case x mode reconciliation','', '| Case and mode | Effective B4 | Candidate gate | Attempts | Memory | RAG chunks | FINAL plan / state |','|---|---|---|---|---|---|---|']
    for c in case_rows:
        gate=(c['planning_precondition_report'] or {}).get('outcome','NOT_ACTIVATED')
        lines.append(f"| {c['logical']} | {c['planning_requested_by_B4']} | {gate} | {len(c['raw_candidate_attempt_ids'])} | {c['memory_status']} | {len(c['course_returned_ids'])} | null / {c['planning_stage']['planning_status']} |")
    (HERE/'CASE_MODE_RECONCILIATION.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(counts,ensure_ascii=False,indent=2))


if __name__=='__main__':
    import socket
    def denied(*args,**kwargs):
        raise RuntimeError('I3_OFFLINE_NO_NETWORK')
    socket.create_connection=denied
    socket.socket.connect=denied
    socket.getaddrinfo=denied
    main()
