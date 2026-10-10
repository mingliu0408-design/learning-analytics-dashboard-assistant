"""Recover exactly the hash-identified legacy 62. No inference or network imports."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import csv
import json
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.contracts import Mode
from utils.c4_dashboard_scoped.select import select_domains

LEGACY = Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3')
EXPECTED = '2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4'
START_HEAD = 'ea33ee9feb7412a8ecad73f0a4ce71fe1870d14b'
GROUPS = {'main_benchmark':'原25问题','memory_diagnostic':'Memory扩展12',
          'rag_diagnostic':'RAG扩展10','handwritten_unified':'其他情景15'}
CRITERIA = ['Clarity','Personalisation','Actionability','Context Awareness',
            'Motivation and Engagement','Reliability','Multi-page Cohesiveness','Error Handling']

def digest(value):
    return sha256(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def loadlines(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]

def write(path, value):
    path = HERE/path
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.name in {'CONFIG_PROPOSED.json','SOURCE_BINDINGS.json','APPROVAL_TEMPLATE.json'} and path.exists():
        existing=json.loads(path.read_text())
        if existing.get('approved') or existing.get('status') in ('READY','AUTHORIZED'):
            raise ValueError('PRESERVE_EXISTING_APPROVED_MATERIAL:'+str(path))
    path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def csvout(path, rows):
    path=HERE/path;path.parent.mkdir(parents=True,exist_ok=True)
    if path.parent.name=='human' and path.exists():
        with path.open(encoding='utf-8-sig') as f:existing=list(csv.DictReader(f))
        if any(r.get(k) for r in existing for k in ['score','rationale','rater','signature','applicable','reason','reviewer','response_id']):
            raise ValueError('PRESERVE_EXISTING_HUMAN_ENTRIES')
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    if branch!='research/rq3-rebuild-i1-pilot-launch':raise ValueError('WRONG_BRANCH')
    original=LEGACY/'evaluation/unified_benchmark_scenarios.jsonl'
    if digest(original.read_bytes())!=EXPECTED:raise ValueError('WRONG_62_SOURCE_HASH')
    rows=loadlines(original)
    assert [r['scenario_id'] for r in rows]==[f'U{i:03}' for i in range(1,63)]
    assert Counter(r['source_dataset'] for r in rows)==Counter(main_benchmark=25,memory_diagnostic=12,rag_diagnostic=10,handwritten_unified=15)
    source25=LEGACY/'evaluation/scenarios.jsonl';old25=loadlines(source25)
    with (LEGACY/'System Data/Example Conversation Data.csv').open() as f:csv50=list(csv.DictReader(f))
    users=[(i+2,r) for i,r in enumerate(csv50) if r['role']=='user']
    assert len(users)==25 and len(csv50)==50
    for i,r in enumerate(rows[:25]):
        assert r['student_query']==old25[i]['student_query']==users[i][1]['message'].strip()
        assert r['page']==old25[i]['page']==users[i][1]['graph']
        assert r['conversation_history']==old25[i].get('conversation_history',[])
    manifest=[]
    def remember(p,role,copy_to=None):
        p=Path(p);rec=dict(path=str(p),role=role,exists=p.is_file())
        if p.is_file():rec.update(sha256=digest(p.read_bytes()),bytes=p.stat().st_size)
        if copy_to and p.is_file():
            dst=HERE/copy_to;dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.exists() and dst.read_bytes()!=p.read_bytes():raise ValueError('IMMUTABLE_COPY_CHANGED')
            shutil.copyfile(p,dst);rec['package_path']=copy_to
        manifest.append(rec);return rec
    remember(original,'IMMUTABLE_ORIGINAL_CONTAINS_GOLD_NEVER_RUNTIME','originals/unified_benchmark_scenarios.jsonl')
    remember(source25,'IMMUTABLE_ORIGINAL_25_CONTAINS_OLD_TARGET_ANSWERS_NEVER_RUNTIME','originals/scenarios_25.jsonl')
    remember(LEGACY/'System Data/Example Conversation Data.csv','50_MESSAGE_SOURCE_TARGET_ANSWERS_EXCLUDED_FROM_PACKAGE')
    for name in ['multiturn_scenarios.jsonl','rag_scenarios.jsonl']:
        remember(LEGACY/'evaluation'/name,'IDENTITY_CROSSCHECK')
    refpath=LEGACY/'evaluation/unified_reference_evidence_v1.jsonl'
    remember(refpath,'LEGACY_REFERENCE_ONLY_NOT_NEW_HUMAN_APPROVAL','evaluation_reference/legacy_reference_62.jsonl')
    refs={r['scenario_id']:r for r in loadlines(refpath)}
    track=ROOT/'evaluation/rq3_real_c4/track_d_dataset'
    for n in ['final_62_scenario_identity_v1.json','original_25_subset_identity_v1.json','dataset_lineage_registry_v1.json','memory_scenario_registry_v1.csv']:
        remember(track/n,'HISTORICAL_IDENTITY_NOT_RUNTIME','historical/'+n)
    historical=ROOT/'evaluation/rq3_real_c4'
    def hist(n):
        p=historical/n;remember(p,'HISTORICAL_MECHANISM_EVIDENCE_NOT_NEW_RESULT');return loadlines(p)
    routes={r['scenario_id']:r for r in hist('i1_route_integration/c4_real_p3_routes_frozen_v1.jsonl')}
    traces={(r['scenario_id'],r['mode']):r for r in hist('i1_route_integration/c4_real_condition_execution_traces_frozen_v1.jsonl')}
    rags={(r['scenario_id'],r['mode']):r for r in hist('i1_route_integration/c4_real_condition_rag_results_frozen_v1.jsonl')}
    mems={(r['scenario_id'],r['mode']):r for r in hist('i1_route_integration/c4_real_condition_memory_results_frozen_v1.jsonl')}
    seeds={r['scenario_id']:r for r in hist('i0_integration/c4_real_memory_preconditioning_manifest_v1.jsonl')}
    write('historical/previous_9_session_moves.json',list(seeds.values()))
    write('historical/p3_routes_62.json',list(routes.values()))
    metadata=ROOT/'research_followups/rq3_rebuild/i0_human_integration/receipts/REAL_SOURCE_METADATA.json'
    remember(metadata,'PREVIOUS_SOURCE_INVENTORY_REFRESHED_BELOW')
    inventory=[]
    for s in json.loads(metadata.read_text())['sources']:
        if not s.get('locator'):
            inventory.append(dict(source_id=s['source_id'],path=None,exists=False,sha256=None,
                status='SOURCE_BINDING_UNKNOWN',reason=s.get('reason')))
            continue
        p=Path(s['locator']);fresh=remember(p,'RAW_SOURCE_METADATA_ONLY_NO_ROWS_EXPORTED')
        row=dict(source_id=s['source_id'],path=str(p),exists=fresh['exists'],sha256=fresh.get('sha256'),
            bytes=fresh.get('bytes'),matches_previous=fresh.get('sha256')==s.get('sha256'),
            headers=None,rows_with_legacy_learner_id=None,permission_for_new_external_generation='NOT_AUTHORIZED',
            observation_window=None,timezone=None,course_binding=None,safe_export=None)
        if p.suffix=='.csv' and p.exists():
            with p.open() as f:
                reader=csv.DictReader(f);row['headers']=reader.fieldnames
                if 'ID' in (reader.fieldnames or []):row['rows_with_legacy_learner_id']=sum(str(x['ID'])==str(rows[0]['student_id']) for x in reader)
        if p.suffix=='.pkl':row['read_status']='HASH_ONLY_NOT_DESERIALIZED'
        inventory.append(row)
    write('sources/ACTUAL_SOURCE_INVENTORY.json',inventory)
    packet=Path('/Users/liuming/Downloads/RQ3_REUSE_PREVIOUS_62_A_SCOPE_CODEX_TASK_PACKET_2026-09-07.zip')
    remember(packet,'USER_AUTHORIZED_SCOPE_REVISION')
    with zipfile.ZipFile(packet) as z:
        assert z.testzip() is None
        for n in ['START_HERE.md','CODEX_A_REUSE_PREVIOUS_62.md','SOURCE_NOTES.md','MANIFEST.json']:
            write('task_packet/'+n,z.read(n).decode())
    # Discover only existing course files, no web, model assets, credentials, or private identity mappings.
    for rel in ['System Data/Module','input/references.txt','input/moodle_links.pdf']:
        p=LEGACY/rel
        for f in sorted(p.rglob('*')) if p.is_dir() else [p]:
            if f.is_file() and f.suffix.lower() in ('.pdf','.txt','.csv','.json','.docx','.doc','.html','.md'):
                remember(f,'COURSE_SOURCE_PRESENT_CONTENT_USE_BINDING_PENDING')
    runtime=[];mapping=[];coverage=[];differences=[];reference=[];readable=['# 复用上一版论文的62题\n\n已暴露历史基准的开发后重评。原始25题及其余37题全部保留。此文件不含目标旧助手回答。\n']
    global_gaps=['COURSE_AND_LEARNER_BINDING_NOT_CONFIRMED','OBSERVATION_WINDOW_AND_AS_OF_UNKNOWN',
                 'SOURCE_TIMEZONE_AND_CALENDAR_UNKNOWN','SOURCE_USE_DECLARATION_PENDING']
    for i,r in enumerate(rows):
        cid=r['scenario_id'];old=r['conversation_history'];clean=[]
        for turn in old:
            content=turn['content']
            if turn.get('page'):content='[Prior page: '+turn['page']+']\n'+content
            clean.append(dict(role=turn['role'],content=content))
        runtime.append(dict(task_id=cid,query=r['student_query'],page=r['page'],history=clean))
        selected,_=select_domains(r['student_query'],r['page'])
        page_domains=['Lecture','Resources','Debate','Reflection'] if r['page']=='Overview' else [r['page']]
        gaps=list(global_gaps)
        needed=set(page_domains)|set(selected)
        if 'Lecture' in needed:gaps+=['ECHO_OBSERVATION_WINDOW_OR_EVENT_EXPORT_MISSING','RECORDING_ID_BINDING_MISSING']
        if 'Reflection' in needed:gaps+=['REFLECTION_TRUSTED_CSV_EXPORT_MISSING']
        if 'Debate' in needed:gaps+=['NETWORK_WEEK_CALENDAR_AND_COVERAGE_UNCONFIRMED']
        if re_relative(r['student_query']):gaps+=['RELATIVE_WEEK_OR_REFERENT_TIME_UNRESOLVED']
        if cid in ('U020','U022'):gaps+=['CANONICAL_HISTORY_EMPTY_ANTECEDENT_UNRESOLVED_NO_CSV_SESSION_PROOF']
        if 'course_material_retrieval' in r['required_capabilities']:gaps+=['COURSE_CORPUS_USE_VERSION_INTERVAL_BINDING_PENDING']
        route=routes[cid];trace=traces[(cid,'C5_FULL_C4')];rag=rags[(cid,'C5_FULL_C4')];mem=mems[(cid,'C5_FULL_C4')]
        cov=dict(case_id=cid,source_group=r['source_dataset'],current_page=r['page'],
            task_required_capabilities=';'.join(r['required_capabilities']),
            requirement_basis='Original62.required_capabilities; existing reviewed labels retained, no new Gold',
            source_files_exist='SEE sources/ACTUAL_SOURCE_INVENTORY.json; legal runtime binding incomplete',
            authorized_sources_ready=False,original_history_turns=len(old),new_history_turns=len(clean),
            old_persistent_setup_turns=len(seeds.get(cid,{}).get('earlier_session_setup',[])),
            new_history_policy='CANONICAL_SAME_SESSION; page labels retained explicitly; no inferred persistent session',
            historical_P3_version=route['method_id'],historical_P3_decision_id=route['decision_id'],
            historical_P3_input_sha256=route['semantic_input_sha256'],
            historical_RAG=route['rag_required'],historical_Memory=route['memory_required'],historical_Planning=route['planning_required'],
            historical_modules_called=';'.join(trace['modules_actually_called']),
            historical_rag_return=rag['status'],historical_memory_return=mem['status'],
            historical_rag_item_count=len(trace['course_source_ids']),historical_memory_item_count=len(trace['memory_ids']),
            historical_rag_returned_ids=';'.join(trace['course_source_ids']),
            historical_memory_returned_ids=';'.join(trace['memory_ids']),
            legacy_reference_course_ids=';'.join(refs[cid]['reference_chunk_ids']),
            legacy_reference_ids_not_returned=';'.join(sorted(set(refs[cid]['reference_chunk_ids'])-set(trace['course_source_ids']))),
            historical_return_completeness='NOT_INFERRED_FROM_AVAILABLE; inspect source IDs and independent reference',
            actual_latest_decision='',latest_run_status='NOT_RUN',latest_modules_executed='NOT_RUN',
            latest_return_completeness='NOT_RUN',ready_for_complete_six_mode_replay=False,specific_gaps=';'.join(gaps))
        coverage.append(cov)
        differences.append(dict(case_id=cid,original_query_sha256=digest(r['student_query'].encode()),
            original_history_sha256=digest(old),runtime_history_sha256=digest(clean),
            query_unchanged=True,history_role_content_unchanged=old==clean,
            prior_page_metadata_rendered=any(t.get('page') for t in old),
            canonical_same_session_preserved=True,old_9_session_move_reversed=cid in seeds,
            semantics='Same question under corrected conditions; no strict old/new paired-score claim',
            old_target_history=seeds[cid]['target_session_visible_history'] if cid in seeds else old,
            original_history=old,new_visible_history=clean))
        mapping.append(dict(case_id=cid,source_group=r['source_dataset'],source_case_id=r['source_scenario_id'],
            source_line=i+1,source_row_sha256=digest(r),original25_csv_line=users[i][0] if i<25 else '',
            original25_csv_query_match=('EXACT' if r['student_query']==users[i][1]['message'] else 'LEGACY_TRAILING_SPACE_TRIM_ALREADY_PRESENT') if i<25 else '',
            original25_id=r['source_scenario_id'] if i<25 else '',current_page=r['page'],
            question_sha256=digest(r['student_query'].encode()),family_key='QUERY_'+digest(r['student_query'].encode())[:16],
            session_family='UNKNOWN_FOR_CSV25' if i<25 else r['source_scenario_id'],
            family_note='Exact duplicate query grouping only; shared learner/source prevents independent-student interpretation'))
        rr=refs[cid]
        assert rr['reference_student_query']==r['student_query'] and rr['reference_page']==r['page']
        reference.append(dict(case_id=cid,current_query=r['student_query'],current_page=r['page'],
            common_visible_history=clean,common_reference=rr,reference_source='Legacy independently stored reference; no candidate/selected-mode union',
            fresh_source_confirmation='',applicability={c:'' for c in CRITERIA},human_rationale='',reviewer='',signature=''))
        readable += ['\n## '+cid+' · '+r['source_scenario_id']+' · '+GROUPS[r['source_dataset']]+'\n',
            '\n页面：'+r['page']+'。原62 JSONL 第 '+str(i+1)+' 行。\n\n问题：\n\n> '+r['student_query']+'\n',
            '\n原始合法历史：\n']
        readable += ['\n（空；不根据 CSV 行顺序补造会话。）\n'] if not old else ['\n```json\n'+json.dumps(old,ensure_ascii=False,indent=2)+'\n```\n']
        readable += ['\n已有需求标签：'+', '.join(r['required_capabilities'])+'。标签不是本轮人评。\n',
            '\n缺件：'+', '.join(gaps)+'。\n']
    assert len(runtime)==62 and len(mapping[:25])==25 and len(seeds)==9
    write('runtime/TASKS_62.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in runtime))
    write('READABLE_REPLAY_62.md',''.join(readable))
    csvout('SOURCE_IDENTITY_MAP.csv',mapping);csvout('COVERAGE_INPUT_MAP_62.csv',coverage)
    write('INPUT_DIFFERENCES_62.json',differences)
    write('evaluation_reference/COMMON_REFERENCE_62.json',reference)
    refmd=['# 共同独立评价参考\n\n仅供评价。旧来源参考保留其原版本，新来源确认和适用性均待人工。不得导入生成器。\n']
    for rr in reference:
        v=rr['common_reference'];refmd+=['\n## '+rr['case_id']+'\n\n'+rr['current_query']+'\n\n```json\n'+json.dumps({k:v[k] for k in ['reference_dashboard_evidence','reference_course_evidence','reference_source_restrictions','reference_evidence_notes','reference_chunk_ids']},ensure_ascii=False,indent=2)+'\n```\n']
    write('evaluation_reference/READABLE_COMMON_REFERENCE_62.md',''.join(refmd))
    ratings=[];apps=[]
    for r in runtime:
        for c in CRITERIA:apps.append(dict(case_id=r['task_id'],criterion=c,applicable='',reason='',reviewer='',signature=''))
        for mode in Mode:
            for c in CRITERIA:ratings.append(dict(case_id=r['task_id'],mode=mode.value,response_id='',criterion=c,score='',rationale='',rater='',signature=''))
    csvout('human/BLANK_RATINGS_2976.csv',ratings);csvout('human/COMMON_APPLICABILITY_496.csv',apps)
    write('human/WORKBOOK_INPUT.json',dict(ratings=ratings,applicability=apps,criteria=CRITERIA))
    rub=ROOT/'research_followups/rq3_rebuild/h0_human_evaluation/rubric.json';remember(rub,'EXISTING_SUPERVISOR_RUBRIC','human/rubric.json')
    for n in ['HUMAN_RUBRIC_GUIDE_DRAFT.md','SUPERVISOR_RUBRIC_SOURCE_AUDIT.md']:
        remember(rub.parent/n,'EXISTING_RUBRIC_NO_NEW_SCALE','human/'+n)
    config=dict(schema_version='REUSED62_CONFIG_V1',approved=False,role_contract_version='REUSED62_REPLAY_INTERFACE_V1',
        task_ids=[r['task_id'] for r in runtime],modes=[m.value for m in Mode],
        generation_roles={r:dict(model='gpt-4o-mini-2024-07-18',temperature=0,max_output_tokens=2048) for r in ['CANDIDATE','FINAL']},
        initial_slot_ceilings=dict(ROUTE=186,CANDIDATE=124,FINAL=372),aggregate_attempt_ceiling=1364,max_attempts_per_slot=2,
        minimum_start_interval_seconds=2,max_request_input_byte_units=250000,
        uncached_usd_per_million=None,proposed_money_ceiling_usd=None,transport_timeout_seconds=30,
        model_status='INHERITED_PROPOSAL_PENDING_AUTHOR_APPROVAL_AND_LIVE_AVAILABILITY',
        evidence_budget=12000,request_budget=50000,memory_backend='M1_HYBRID_LINKS_DEV_CANDIDATE',
        retries='AT_MOST_ONE_EXPLICIT_STRUCTURAL_RETRY;UNKNOWN_COMPLETION_NEVER_AUTO_RETRY',
        comparison='PRIMARY_S5_MINUS_S0;COMPONENT_CONTRASTS_PREDECLARED',evaluation='FRESH_HUMAN_ONLY')
    write('runtime/CONFIG_PROPOSED.json',config)
    bindings=dict(schema_version='REUSED62_SOURCE_BINDINGS_V1',status='INCOMPLETE',
        snapshot=None,source_permission_ref=None,course_id=None,roster=None,calendars=None,
        source_root=str(LEGACY),source_inventory='sources/ACTUAL_SOURCE_INVENTORY.json',
        rag=None,memory_policy='CANONICAL_SAME_SESSION_NO_INFERRED_PERSISTENT_PRELOAD',
        tasks={r['scenario_id']:dict(learner_id=r['student_id'],scope=None,as_of=None,
            future_policy='WARN_SNAPSHOT_ONLY',permission_ref=None,memory=None) for r in rows})
    corpus_receipt=HERE/'sources/R0_CORPUS_EXPORT_RECEIPT.json'
    if corpus_receipt.exists():
        cr=json.loads(corpus_receipt.read_text())
        assert digest(Path(cr['path']).read_bytes())==cr['sha256']
        bindings['rag']={k:cr[k] for k in ['path','sha256','corpus_sha256']}
        bindings['rag'].update(version='LEGACY_R0_'+cr['corpus_sha256'][:16],validity_interval=None,source_permission_ref=None)
        remember(corpus_receipt,'ACTUAL_GENERIC_624_CHUNK_EXPORT_NOT_NEW_RETRIEVAL')
    write('runtime/SOURCE_BINDINGS.json',bindings)
    write('runtime/APPROVAL_TEMPLATE.json',dict(status='NOT_AUTHORIZED',authorized_by='',authorized_at='',signature='',
        scope='REUSED62_SIX_MODES_372_FRESH_RESPONSES_HUMAN_ONLY',config_sha256=None,tasks_sha256=digest((HERE/'runtime/TASKS_62.jsonl').read_bytes()),
        sources_sha256=None,code_sha256=None,git_head=None,output_directory=None,max_physical_calls=1364))
    write('SOURCE_MANIFEST.json',dict(start_head=START_HEAD,branch=branch,files=manifest))
    write('RECOVERY_COUNTS.json',dict(total=62,original25=25,memory_extension=12,rag_extension=10,other=15,
        original25_verified_against_csv_and_scenarios=True,original_visible_history_nonempty=sum(bool(r['conversation_history']) for r in rows),
        historical_session_moves=9,recovered_loadable_tasks=62,complete_real_source_bound_tasks=0,planned_conditions=372,
        generated_responses=0,provider_calls=0,p3_llm_calls=0,judge_calls=0,human_scores_filled=0,
        original_sha256=EXPECTED,scope_supersedes='Previous 25-only and new B arrangement'))
    print(json.dumps(json.loads((HERE/'RECOVERY_COUNTS.json').read_text()),ensure_ascii=False))

def re_relative(q):
    import re
    return bool(re.search(r'\b(?:this week|today|next week|week\s*\d+)\b',q,re.I))

if __name__=='__main__':main()
