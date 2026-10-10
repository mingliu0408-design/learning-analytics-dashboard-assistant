"""Recover exact tasks; deterministic original-CSV aggregation, no reference inputs."""
import ast
import csv
from collections import Counter
from copy import deepcopy
from replay_common import *

DOMAINS = ('Resources','Lecture','Debate','Reflection')

def constant(path, name):
    tree=ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)

def aggregate_sources():
    inventory={v['source_id']:v for v in read(OLD/'sources/ACTUAL_SOURCE_INVENTORY.json')}
    tables={};receipts={}
    for name in ('moodle','echo','features'):
        p=checked(inventory[name])
        with p.open() as f:
            reader=csv.DictReader(f)
            rows=[dict(row_index=i, values=r) for i,r in enumerate(reader,2) if r['ID']=='301127']
        tables[name]=rows
        receipts[name]=dict(**file_id(p),selected_rows=[r['row_index'] for r in rows],
            selection='Exact canonical source ID, local-only; names/identity mapping not read.',
            local_processing='USER_AUTHORIZED_CONTROLLED_REPLAY',external_disclosure='PENDING')
    assert [len(tables[k]) for k in ('moodle','echo','features')]==[313,9,1]
    code=ROOT/'utils/evidence_synthesiser.py'
    definitions=constant(code,'METRIC_DEFINITIONS')
    receipts['metric_contract']=dict(**file_id(code),source_kind='IMPLEMENTED_COLLECTION_AND_METRIC_CONTRACT',
        lines='METRIC_DEFINITIONS and DATA_PROVENANCE; not a generated answer/reference')
    def event(event_name):
        records=[r for r in tables['moodle'] if r['values']['Event']==event_name]
        weeks=Counter(r['values']['Week'] for r in records)
        days=Counter(r['values']['Day_of_week'] for r in records)
        times=[r['values']['Time'] for r in records]
        return dict(count=len(records),by_source_week=dict(sorted(weeks.items(),key=lambda x:int(x[0]))),
            by_source_weekday=dict(sorted(days.items())),row_indices=[r['row_index'] for r in records],
            timestamp_min=min(times) if times else None,timestamp_max=max(times) if times else None,
            timezone=None,source_id='moodle',calculation='COUNT_ROWS_FILTER_EVENT',level='RAW_EVENT_AGGREGATION',
            boundary='All supplied matching events; duplicate-looking rows retained. Source Week labels are not a current-week calendar.')
    resource=event('Resources_views')
    days=resource['by_source_weekday']; top=max(days.values())
    resource['most_active_weekdays']=[k for k,v in days.items() if v==top]
    lecture_rows=[dict(technical_row_index=r['row_index'],**{k:r['values'][k] for k in ('Class','Content_week','Video Views','Video View %')}) for r in tables['echo']]
    feature=tables['features'][0]
    pages={
        'Resources':dict(metrics=definitions['resources'],resource_events=resource),
        'Lecture':dict(metrics=definitions['lecture'],video_click_events=event('Video_views'),
            playback_snapshot=dict(rows=lecture_rows,total_view_events=sum(int(r['Video Views']) for r in lecture_rows),
                mean_percent_all_9_rows=sum(float(r['Video View %']) for r in lecture_rows)/9,
                source_id='echo',level='CUMULATIVE_TABLE_SNAPSHOT',observation_window=None,
                boundary='Content_week identifies material, not viewing date. Row index is a trace locator, not a unique recording ID. Week3 says No Lecture Video; its zero is not a missed lecture. No transcript or recording is supplied.')),
        'Debate':dict(metrics=definitions['debate'],events={e:event('Debate_'+e) for e in ('views','posts','replies')},
            collection_scope=dict(source_id='metric_contract',tracked='Moodle forum view/post/reply events',
                email_read_receipts='NOT_PRESENT_IN_SUPPLIED_TABLE_OR_IMPLEMENTED_METRIC',
                boundary='This replay cannot observe email reading. It does not claim that every deployed mail system lacks telemetry.'),
            interaction_snapshot=dict(source_id='features',row_index=feature['row_index'],level='CUMULATIVE_TABLE_SNAPSHOT',
                counts={k:int(v) for k,v in feature['values'].items() if k.startswith('Num_unique')},observation_window=None)),
        'Reflection':dict(metrics=definitions['reflection'],writing_snapshot=dict(source_id='features',row_index=feature['row_index'],
            Total_chars=int(feature['values']['Total_chars']),level='CUMULATIVE_TABLE_SNAPSHOT',observation_window=None),
            missing=dict(reflection_text=None,weekly_edit_events=None,submission_receipt=None,feedback_or_grade=None),
            boundary='Total_chars is cumulative edited-character activity, not an essay, a grade, or its current document length. Unsafe pickle was not loaded.')}
    for domain,p in pages.items():
        p['claim_boundary']='Activity traces do not establish mastery, quality, attention, adoption, or completion.'
        p['source_versions']={k:v['sha256'] for k,v in receipts.items() if k in {'metric_contract',*({'moodle'} if domain=='Resources' else {'moodle','echo'} if domain=='Lecture' else {'moodle','features'} if domain=='Debate' else {'features'})}}
    consistency={e:dict(raw_count=event(e)['count'],features_count=int(feature['values'][e]))
        for e in ('Resources_views','Debate_views','Debate_posts','Debate_replies')}
    assert all(v['raw_count']==v['features_count'] for v in consistency.values())
    write(HERE/'sources/RAW_AGGREGATION_RECEIPT.json',dict(sources=receipts,feature_cross_checks=consistency,
        observed_calendar=None,processing_utc=utc(),unsafe_pickle_loaded=False,legacy_snapshot_reused=False,
        rejected_snapshot_lineage='track_d_dataset/build_track_d_artifacts.py:1478 provider_input.dashboard_context = reference_dashboard_evidence'))
    write(HERE/'runtime/PAGE_SOURCES.json',dict(version=VERSION,pages=pages))
    return receipts

def memory_sources(tasks):
    old={r['scenario_id']:r for r in read(OLD/'historical/previous_9_session_moves.json')}
    assert set(old)==set(NINE)
    result={}
    for task in tasks:
        tid=task['task_id']
        if tid not in old:continue
        source=old[tid]
        turns=[];ops=[]
        for w in source['writes']:
            c=w['candidate'];text=w['source_text'];span=c['evidence_span']
            assert text.count(span)==1 and c['content']==span
            assert c['operation']=='ADD' and c['target_memory_id'] is None
            assert w['source_role'] in ('USER','SYSTEM')
            assert any(t['content']==text and t['role']==('user' if w['source_role']=='USER' else 'assistant') for t in source['earlier_session_setup'])
            a=text.index(span)
            turns.append(dict(turn_id=w['source_turn_id'],session_id=w['source_session_id'],
                learner_id=LEARNER,course_id=COURSE,timestamp=w['event_at'],role=w['source_role'],content=text))
            ops.append(dict(fact_id=w['alias'],source_turn_id=w['source_turn_id'],learner_id=LEARNER,course_id=COURSE,
                operation=c['operation'],memory_type=c['memory_type'],content=c['content'],confidence=c['confidence'],
                evidence_span=span,source_span_chars=[a,a+len(span)],target_fact_id=None,claim_basis=w['claim_basis'],
                consent_status='NOT_REQUIRED',valid_from=w['event_at'],valid_to=None))
        target=dict(learner_id=LEARNER,course_id=COURSE,session_id='CONTROLLED_TARGET_SESSION',as_of=CLOCK,
            horizon='HISTORICAL_REPLAY_NOT_CURRENT_AVAILABILITY',query=task['query'],page=task['page'],visible_history=[],
            visibility_rule='Historical approved hidden setup; same empty target history in all six modes.')
        runtime=dict(source_turns=turns,setup_operations=ops,relation_events=[],target=target)
        result[tid]=runtime
        write(HERE/f'runtime/memory_sources/{tid}.json',runtime)
    return result

def main():
    if (HERE/'runtime/BINDINGS.json').exists():raise FileExistsError('Binding build already exists; do not overwrite original build.')
    HERE.mkdir(exist_ok=True)
    original_files={str(p.relative_to(OLD)):file_id(p) for p in OLD.rglob('*') if p.is_file() and 'node_modules' not in p.parts and not p.is_symlink()}
    write(HERE/'audit/OLD_VERSION_BASELINE.json',original_files)
    canonical=lines(OLD/'originals/unified_benchmark_scenarios.jsonl')
    tasks=lines(OLD/'runtime/TASKS_62.jsonl')
    assert len(canonical)==len(tasks)==62
    for c,t in zip(canonical,tasks):
        assert c['scenario_id']==t['task_id'] and c['student_query']==t['query'] and c['page']==t['page']
    history_before=deepcopy(tasks)
    setups=memory_sources(tasks)
    for t in tasks:
        if t['task_id'] in NINE:t['history']=[]
    (HERE/'runtime/TASKS_62.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in tasks))
    write(HERE/'audit/HISTORY_CHANGES.json',[dict(task_id=a['task_id'],same_session_history=a['history'],controlled_target_history=b['history'],
        change='APPROVED_HISTORICAL_CROSS_SESSION_SETTING' if a['task_id'] in NINE else 'UNCHANGED') for a,b in zip(history_before,tasks)])
    write(HERE/'audit/ROSTER_IDENTITY.json',[dict(task_id=c['scenario_id'],source_dataset=c['source_dataset'],source_scenario_id=c['source_scenario_id']) for c in canonical])
    receipts=aggregate_sources()
    corpus=OLD/'local_private/VERIFIED_R0_CORPUS.jsonl'
    cr=read(OLD/'sources/R0_CORPUS_EXPORT_RECEIPT.json')
    assert len(lines(corpus))==624
    binding=dict(version=VERSION,mode='CONTROLLED_HISTORICAL_REPLAY',course_id=COURSE,learner_id=LEARNER,
        namespace_basis='One canonical local source identifier; research scope only, no authenticated enrolment claim.',
        replay_clock=CLOCK,replay_clock_basis='Existing i1_route_integration/build_i1_artifacts.py QUERY_TIME; experimental, not real student time.',
        real_current_week=None,local_permission='USER_MESSAGE_CONTROLLED_LOCAL_PROCESSING',external_permission=None,
        pages=file_id(HERE/'runtime/PAGE_SOURCES.json'),rag=dict(**file_id(corpus),count=624,
            version='VERIFIED_EXISTING_SHARED_R0_624',corpus_sha256='daaba43aebeda730db2bd7aef4583729610242a1af44060615c3f4c235e67ede'),
        memory_policy='NINE_APPROVED_HISTORICAL_SETUPS_OTHER_HISTORIES_UNCHANGED',
        tasks={t['task_id']:dict(memory_source=file_id(HERE/f"runtime/memory_sources/{t['task_id']}.json") if t['task_id'] in NINE else None) for t in tasks})
    write(HERE/'runtime/BINDINGS.json',binding)
    write(HERE/'audit/INPUT_IDENTITIES.json',dict(canonical=file_id(OLD/'originals/unified_benchmark_scenarios.jsonl'),
        original25=file_id(OLD/'originals/scenarios_25.jsonl'),same_session=file_id(OLD/'runtime/TASKS_62.jsonl'),
        moves=file_id(OLD/'historical/previous_9_session_moves.json'),corpus=file_id(corpus),raw=receipts,
        source_clock_code=file_id(ROOT/'evaluation/rq3_real_c4/i1_route_integration/build_i1_artifacts.py')))
    print('Recovered 62 unchanged queries/pages; whitelisted 9 setups; aggregated 313 Moodle + 9 Echo + 1 features rows.')

if __name__=='__main__':offline();main()
