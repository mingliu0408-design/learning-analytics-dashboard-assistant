"""Bind only original U001-U025 ordinary sources and the fixed new 24."""
from v2_common import *
from copy import deepcopy
import shutil
from native_setup import build_state

# Preparation limitations, based on literal questions and available ordinary
# sources. Never read by the Evidence, Memory, P3 or generation adapters.
MISSING = {
    2:['ASSESSMENT_VIEWS_DEFINITION_NOT_RECOVERED'],
    4:['TEN_DAY_START_AND_AVAILABILITY_UNKNOWN','REQUIRED_TASKS_AND_DEADLINES_NOT_BOUND'],
    5:['THIS_REFERS_TO_PRIOR_PLAN_OR_ADVICE_NOT_RECOVERED'],
    7:['THIS_REFERS_TO_PRIOR_ADVICE_NOT_RECOVERED'],
    9:['FEEDBACK_OR_REFLECTION_TEXT_NOT_RECOVERED'],
    14:['W4_SUBMISSION_RECEIPT_AND_DEADLINE_NOT_RECOVERED'],
    18:['REFLECTION_TEXT_FOR_STRENGTH_WEAKNESS_JUDGMENT_NOT_RECOVERED'],
    22:['NUMBERED_ITEMS_2_AND_3_ANTECEDENT_NOT_RECOVERED'],
}

def run():
    old = ROOT/'research_followups/rq3_rebuild/a_reuse62_replay_v2'
    b = read(old/'runtime/BINDINGS.json')
    source_entry = b['pages']; source_path = Path(source_entry['path'])
    if sha(source_path.read_bytes())!=source_entry['sha256']: raise ValueError('PRIOR_PAGE_SOURCE_CHANGED')
    dest = HERE/'source_materials/original25'; dest.mkdir(exist_ok=True)
    shutil.copyfile(source_path,dest/'PAGE_SOURCES.json')
    shutil.copyfile(old/'sources/RAW_AGGREGATION_RECEIPT.json',dest/'RAW_AGGREGATION_RECEIPT.json')
    # No old response, selected Gold evidence, statistics or extra 37 tasks.
    old_tasks = [t for t in lines(old/'runtime/TASKS_62.jsonl') if t['task_id'] in {f'U{i:03}' for i in range(1,26)}]
    old_tasks = {t['task_id']:t for t in old_tasks}
    tasks = lines(HERE/'runtime_tasks.jsonl'); reports = []; mappings = []
    catalog = read(HERE/'source_materials/catalog.json')
    native = {}; task_bindings = {}
    for i,t in enumerate(tasks):
        tid=t['task_id']
        if i<25:
            uid=f'U{i+1:03}'; prior=old_tasks[uid]
            # Existing replay trimmed some trailing spaces; new runtime retains V1 bytes.
            if t['query'].strip()!=prior['query'].strip() or t['page']!=prior['page'] or prior['history']!=[]:
                raise ValueError('ORIGINAL25_SOURCE_MAPPING_CHANGED:'+tid)
            t['scope']=dict(student_id=b['learner_id'],course_id=b['course_id'],window_start=None,window_end=None)
            t['query_time']=b['replay_clock']
            t['source_bindings']['context_id']='replay-'+tid
            tb=dict(kind='CONTROLLED_RECONTEXTUALISATION',page_source=file_id(dest/'PAGE_SOURCES.json'),
                    history_path=None,memory_operations_path=None)
            gaps=MISSING.get(i+1,[])
            mappings.append(dict(task_id=tid,original_id=f'S001-U{i+1:03}',prior_runtime_id=uid,
                original_query_verbatim=t['query'],prior_query_trailing_whitespace_only=(prior['query']!=t['query']),
                authenticity='CONTROLLED_RECONTEXTUALISATION',original_student_identity=None,original_full_session_recovered=False,
                original_query_time=None,experimental_clock=b['replay_clock'],page_source=file_id(dest/'PAGE_SOURCES.json'),
                source_scope_namespace=b['learner_id'],namespace_is_original_student=False,
                local_permission='USER_MESSAGE_CONTROLLED_LOCAL_REPLAY',missing=gaps,
                status='PENDING_RELEVANT_SOURCE' if gaps else 'PREPARABLE_CONTROLLED_REPLAY',
                nonblocking_limits=['No common observation interval','No real student clock or identity recovered','Activity is not learning quality'],
                source_time_policy='Retain source-local timestamps and undated cumulative snapshots; no invented present week.',
                external_permission=None))
        else:
            ctx=catalog['contexts'][t['source_bindings']['context_id']]
            tb=dict(kind='SYNTHETIC_ENGLISH_ALIGNED',**ctx)
            tb['files']={k:file_id(HERE/ctx[k]) for k in ('page_state_path','history_path','memory_operations_path') if ctx[k]}
            gaps=[]
        task_bindings[tid]=tb
        state,report=build_state(t,tb,HERE/'native_initial'/tid)
        native[tid]=state
        reports.append(dict(task_id=tid,mechanically_prepared=True,preparable=not gaps,missing=gaps,
            source_class=tb['kind'],native_rows=report['native_rows'],writes=report['accepted_writes'],
            source_operations=report['operations'],unindexed_suggestions=report['unindexed_suggestions'],
            closed_reopened=report['closed_reopened'],mode_copies=report['mode_copies'],target_reads=0,
            human_inclusion=None,external_authorization=None,generation_authorized=False))
    jsonl(HERE/'runtime_tasks.jsonl',tasks)
    jsonl(HERE/'original25_binding_status.jsonl',mappings)
    write(HERE/'BINDINGS.json',dict(version=VERSION,tasks=task_bindings,native=native,
        course=file_id(HERE/'source_materials/course/corpus.jsonl')))
    write(HERE/'audit/PREPARATION.json',reports)
    ready=[r['task_id'] for r in reports if r['preparable']]
    write(HERE/'RUN_MANIFEST.json',dict(version=VERSION,roster_path='runtime_tasks.jsonl',roster_sha256=sha((HERE/'runtime_tasks.jsonl').read_bytes()),
        task_ids=ready,bindings_sha256=sha((HERE/'BINDINGS.json').read_bytes()),
        roster_count=49,preparable_count=len(ready),original_count=25,new_count=24,new_families=12,
        excluded_pending_source=[dict(task_id=r['task_id'],missing=r['missing']) for r in reports if not r['preparable']],
        selection_basis='SOURCE_PREPARATION_BEFORE_NEW_OUTPUTS',provider_authorized=False))
    config=read(old/'runtime/CONFIG_PROPOSED.json')
    config.update(schema_version=VERSION,task_ids=ready,experiment_mode=VERSION,
        initial_slot_ceilings=dict(ROUTE=len(ready)*3,CANDIDATE=len(ready)*2,FINAL=len(ready)*6),
        aggregate_attempt_ceiling=len(ready)*22,language='English',human_review_pending=True)
    write(HERE/'CONFIG_PROPOSED.json',config)
    write(HERE/'audit/COUNTS.json',dict(roster=49,original_roster=25,new_conditions=24,new_families=12,
        input_previews=49,preparable=len(ready),preparable_original=sum(r['preparable'] for r in reports[:25]),preparable_new=24,
        pending_source_original=sum(not r['preparable'] for r in reports[:25]),source_operations=sum(r['source_operations'] for r in reports),
        native_writes=sum(r['writes'] for r in reports),native_rows=sum(r['native_rows'] for r in reports),
        unindexed_assistant_suggestions=sum(r['unindexed_suggestions'] for r in reports),native_initial_states=49,mode_clones=294,
        source_histories=8,target_retrieval_calls=0,p3_calls=0,candidate_calls=0,final_calls=0,judge_calls=0,human_decisions=0))
    print(canonical(read(HERE/'audit/COUNTS.json')))

if __name__=='__main__': offline(); run()
