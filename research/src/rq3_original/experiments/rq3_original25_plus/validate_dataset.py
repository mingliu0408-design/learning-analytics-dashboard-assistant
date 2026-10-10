"""Semantic/source and leakage checks for the delivered draft, never model performance."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
import csv
import io
import json
import hashlib
import copy
import ast
from data_loader import (ROOT, TASK_KEYS, read_json, read_jsonl, task, context,
                         shared_course_corpus, page_observations, generator_input, replay_preload)

checks=[]


def check(name, condition, detail=None):
    checks.append(dict(name=name,passed=bool(condition),detail=detail))
    if not condition:
        raise AssertionError(name+': '+str(detail))


def ptr(obj,pointer):
    for part in pointer.lstrip('/').split('/'):
        part=part.replace('~1','/').replace('~0','~')
        obj=obj[int(part)] if isinstance(obj,list) else obj[part]
    return obj


def sha(b):
    return hashlib.sha256(b).hexdigest()


def differences(a,b,p=''):
    if type(a)!=type(b):return [p]
    if isinstance(a,dict):
        out=[]
        for k in sorted(set(a)|set(b)):
            if k not in a or k not in b:out.append(p+'/'+k)
            else:out+=differences(a[k],b[k],p+'/'+k)
        return out
    if isinstance(a,list):
        if len(a)!=len(b):return [p+'/length']
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in differences(x,y,p+'/'+str(i))]
    return [] if a==b else [p]


def validate():
    raw=(ROOT/'legacy_only/Example Conversation Data(5).csv').read_bytes()
    original=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline='')))
    check('original CSV exact supplied hash',sha(raw)=='6d91aa61b9a1011318dc1756747752d04c20c45cb4202dc4f06daa23580d3bc8')
    check('50 messages and exact 25/25 roles',len(original)==50 and Counter(x['role'] for x in original)=={'user':25,'assistant':25})
    preserved=read_jsonl('legacy_only/source_messages_50.jsonl')
    check('every original field including trailing whitespace preserved',all({k:v for k,v in r.items() if k!='source_record_number'}==o for r,o in zip(preserved,original)) and len(preserved)==50)
    users=[r for r in original if r['role']=='user']; roster=read_jsonl('original25_roster.jsonl')
    runtime=read_jsonl('runtime_tasks.jsonl'); refs=read_jsonl('evaluation_reference.jsonl')
    refmap={r['task_id']:r for r in refs}; design=read_json('family_design.json')['tasks']
    dm={r['task_id']:r for r in design}; families=defaultdict(list)
    for x in design:families[x['family_id']].append(x)
    check('25 exact original queries/pages in roster and runtime',len(roster)==25 and all(r['query']==u['message'] and r['page']==u['graph'] and runtime[i]['query']==u['message'] for i,(r,u) in enumerate(zip(roster,users))))
    check('original page counts',Counter(r['page'] for r in roster)==dict(Overview=10,Resources=3,Lecture=3,Debate=4,Reflection=5))
    check('legacy identity/session/time missing retained',all(r['original_identity']==r['original_session']==r['original_timestamp']=='UNKNOWN' for r in roster))
    check('no fabricated legacy conversation history',all(not r['visible_history'] and r['query_time'] is None and r['source_bindings']['context_id'] is None for r in runtime[:25]))
    check('49 unique task rows with exact reference alignment',len(runtime)==49 and len(set(r['task_id'] for r in runtime))==49 and set(refmap)=={r['task_id'] for r in runtime})
    check('12 paired families and 24 new drafts',len(design)==24 and len(families)==12 and all({x['condition'] for x in v}=={'A','B'} and len(v)==2 for v in families.values()))
    check('four design focuses each have six drafts',Counter(d['design_focus_bucket'] for d in design)=={'E':6,'R':6,'M':6,'P':6})
    check('family variants stay in one unassigned split',all({d['split'] for d in v}=={'DRAFT_UNASSIGNED'} for v in families.values()))
    check('no final sample size invented',read_json('family_design.json')['final_sample_size'] is None)
    check('runtime strict allowlist',all(set(r)==TASK_KEYS for r in runtime))
    forbidden=['required_facts','expected_capabilities','source_availability_truth','answerability_design','family_id','condition','feasibility_witness','human_review','selected_chunks','gold']
    check('runtime contains no evaluation/design/Gold fields',not any('"'+x+'"' in json.dumps(runtime).lower() for x in forbidden))
    loader=(ROOT/'data_loader.py').read_text()
    tree=ast.parse(loader)
    imports={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
    imports|={x.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import) for x in n.names}
    check('loader has only standard-library imports',imports <= {'pathlib','collections','datetime','json','copy','argparse'})
    check('loader does not import evaluation/legacy sidecar',not any(x in loader for x in ['evaluation_reference.jsonl','legacy_only/','family_design.json']))
    check('corpus API cannot accept a task-specific selector','def shared_course_corpus():' in loader)
    corpus=shared_course_corpus();cm=read_json('source_materials/course/manifest.json')
    check('entire ordinary 624-chunk corpus exact export',len(corpus)==624 and sha((ROOT/'source_materials/course/corpus.jsonl').read_bytes())==cm['corpus_sha256']=='89fe50ea0436c70e382629142742a774a2fc88727be09b85eb87af9ec3786a2e')
    chunks={c['chunk_id']:c for c in corpus}
    check('native course chunk IDs unique',len(chunks)==624)
    for d in cm['documents']:
        check('raw/extracted source hash '+d['document_id'],sha((ROOT/d['raw_path']).read_bytes())==d['raw_sha256'] and sha((ROOT/d['extracted_path']).read_bytes())==d['extracted_sha256'])
        txt=(ROOT/d['extracted_path']).read_text()
        check('all native source text intervals '+d['document_id'],all(txt[r['char_start']:r['char_end']]==chunks[r['chunk_id']]['text'] for r in d['native_chunk_intervals']))
    checked_spans=0
    for ref in refs:
        check('human fields blank '+ref['task_id'],all(v is None for v in ref['human_review'].values()) and all(v is None for v in ref['applicability_by_criterion'].values()))
        check('source availability separate from unexecuted retrieval '+ref['task_id'],ref['retrieval_outcome']=='NOT_EXECUTED' and bool(ref['source_availability_truth']))
        for fact in ref['required_facts']:
            check('reference fact has evidence '+ref['task_id'],bool(fact['evidence']))
            for e in fact['evidence']:
                if e['kind']=='COURSE_SPAN':
                    check('course source span '+ref['task_id'],chunks[e['chunk_id']]['text'][e['char_start']:e['char_end']]==e['quote'] and (ROOT/e['readable_path']).read_text()[e['document_char_start']:e['document_char_end']]==e['quote'] and sha((ROOT/e['origin_raw_path']).read_bytes())==e['document_version'])
                else:
                    value=ptr(read_json(e['path']),e['json_pointer'])
                    check('structured/history source span '+ref['task_id'],value==e['value'] if e['kind']=='STRUCTURED_SOURCE' else value[e['char_start']:e['char_end']]==e['quote'])
                checked_spans+=1
    assistant_targets=[r['message'] for r in original if r['role']=='assistant']
    source_text='\n'.join(p.read_text(errors='replace') for p in (ROOT/'source_materials').rglob('*') if p.is_file() and 'raw' not in p.parts)
    check('old assistant target text absent from runtime/source/reference',not any(t in json.dumps(runtime,ensure_ascii=False)+source_text+json.dumps(refs,ensure_ascii=False) for t in assistant_targets if t))
    pair_details={}; projections={}; replay_views={}
    for family, rows in families.items():
        rows=sorted(rows,key=lambda r:r['condition']);ta,tb=[task(x['task_id']) for x in rows]
        a,b=[read_json(context(t['task_id'])['page_state_path']) for t in [ta,tb]]
        diff=differences(a,b); pair_details[family]=dict(page_state_changed_paths=diff,declared_factor=rows[0]['changed_factor'])
        expected={'E01':['/records/0/payload/post_status'],'E02':['/events/length'],
                  'E03':['/coverage/Reflection/status'],'P01':['/records/2/payload/available_minutes'],
                  'P02':['/records/3/payload/completed'],'P03':['/events/length']}.get(family,[])
        check('only declared source factor differs '+family,diff==expected,dict(actual=diff,expected=expected))
        check('pair query differs only for RAG wording/composition/boundary '+family,(ta['query']!=tb['query'])==(family in ['R01','R02','R03']))
        check('pair scope/time/current history fixed '+family,all(ta[k]==tb[k] for k in ['scope','query_time','visible_history']))
        if family in ['M01','M02','M03','P03']:
            ha,hb=[read_json(context(t['task_id'])['history_path'])['sessions'] for t in [ta,tb]]
            hd=differences(ha,hb)
            if family in ['M01','M02']:
                check('pair adds exactly one source session '+family,len(hb)==len(ha)+1 and hb[:len(ha)]==ha)
            elif family=='M03':
                check('only declared choice utterance replaced',hd==['/0/messages/0/content'],hd)
            else:check('P03 history remains identical',ha==hb)
            pair_details[family]['history_changed_paths']=hd
        pa,pb=[page_observations(t['task_id'],True) for t in [ta,tb]]
        if family in ['E01','E02','E03','M01','M02','M03','P02','P03']:
            check('matched legal current page '+family,pa['page_data']==pb['page_data'])
        if family in ['E02','P03']:
            check('out-of-scope noise leaves scoped projections invariant '+family,pa==pb)
            check('noise consists of exactly three added events '+family,b['events'][:len(a['events'])]==a['events'] and len(b['events'])==len(a['events'])+3)
        if family=='E02':
            vals=[pa['page_data']['event_count']]+[v['event_count'] for v in pa['other_pages'].values()]
            check('five event total without Overview double-counting',vals==[2,1,1,1] and sum(vals)==5,vals)
        if family=='E03':
            check('zero versus unknown maintained',pa['other_pages']['Reflection']['event_count']==0 and pb['other_pages']['Reflection']['event_count'] is None)
        for t in [ta,tb]:
            cid=t['source_bindings']['context_id'];binding=context(t['task_id'])
            st=read_json(binding['page_state_path'])
            check('unique source event and record IDs '+t['task_id'],len({x['event_id'] for x in st['events']})==len(st['events']) and len({x['record_id'] for x in st['records']})==len(st['records']))
            check('completed observation window precedes query '+t['task_id'],datetime.fromisoformat(t['scope']['window_start'])<datetime.fromisoformat(t['scope']['window_end'])<=datetime.fromisoformat(t['query_time']))
            check('snapshot source times are not future '+t['task_id'],all(datetime.fromisoformat(x['updated_at'])<=datetime.fromisoformat(t['query_time']) for x in st['records']))
            projections[t['task_id']]=generator_input(t['task_id'])
            if binding['history_path']:
                h=read_json(binding['history_path']); ss=h['sessions']
                check('2-4 prior source sessions '+t['task_id'],2<=len(ss)<=4)
                times=[datetime.fromisoformat(m['timestamp']) for s in ss for m in s['messages']]
                check('all source turns chronological and before distinct target session '+t['task_id'],times==sorted(times) and max(times)<datetime.fromisoformat(t['query_time']) and h['target_session_id'] not in {s['session_id'] for s in ss})
                mem=replay_preload(t['task_id']); replay_views[t['task_id']]=mem
                check('preload bounded to scoped source messages '+t['task_id'],bool(mem))
                check('persistent history absent from current-visible history '+t['task_id'],not t['visible_history'])
                if family=='M01':check('unadopted essay stays assistant suggestion '+t['task_id'],mem['long-essay-suggestion']['source_role']=='assistant' and not mem['long-essay-suggestion']['value']['student_adopted'])
                if family=='M02':check('update reads latest student budget '+t['task_id'],mem['debate-budget']['value']['minutes']==(12 if t['task_id']==ta['task_id'] else 24) and mem['suggested-budget']['source_role']=='assistant')
                if family=='M03':check('unprovided choice remains absent '+t['task_id'],('critique-choice' in mem)==(t['task_id']==ta['task_id']))
            ref=refmap[t['task_id']];w=ref.get('feasibility_witness')
            if w:
                plan=ptr(read_json(w['plan_source_path']),w['plan_pointer']);steps={x['step_id']:x for x in plan['steps']}
                done=set(w['already_completed']);seen=set();cost=0
                check('all steps belong to one plan '+t['task_id'],all(s['parent_plan_id']==plan['plan_id'] for s in steps.values()) and len(steps)==len(plan['steps']))
                for step in w['one_feasible_sequence']:
                    check('plan dependency/order '+t['task_id']+'/'+step,step not in done and step not in seen and set(steps[step]['depends_on'])<=done|seen)
                    seen.add(step);cost+=steps[step]['estimated_minutes']
                needed=sum(s['estimated_minutes'] for k,s in steps.items() if k not in done)
                check('feasible plan arithmetic '+t['task_id'],cost==w['estimated_minutes']<=w['budget_minutes'] and needed==w['remaining_goal_minutes'] and w['full_goal_fits_budget']==(needed<=w['budget_minutes']) and w['slack_minutes']==w['budget_minutes']-cost)
    # Absence is about the whole fixed source inventory, not a query-specific retrieval result.
    matches=[c for c in corpus if 'Ryan' in c['text'] or 'Improving reflective writing in higher education' in c['text']]
    expected_id='handbook_the_core_elements_of_academic_reflective_writing_3'
    check('Ryan source is a bibliography entry in full fixed corpus',len(matches)==1 and matches[0]['chunk_id']==expected_id and '16(1), 99-111' in matches[0]['text'])
    absence=dict(corpus_sha256=cm['corpus_sha256'],inspected_chunks=624,method='Offline full-corpus identity and literal source-entry inventory; no ranking/retrieval engine',
                 matching_chunks=[m['chunk_id'] for m in matches],provided_article_full_text=False,
                 article_procedure_detail_status='NOT_IN_PROVIDED_SOURCE_INVENTORY',
                 limit='Not a claim that the article itself lacks a teaching procedure; independent human source-sufficiency review remains blank.')
    review=read_json('human_review/task_review_blank.json')
    check('H0 blank ratings copied without scores or identities',all(x['score'] is None and not x['rater_id'] and not x['note'] and not x['recorded_at'] for x in read_json('human_review/blank_ratings.json')))
    check('all final human review and applicability values blank',review['final_sample_size'] is None and review['multi_page_observation_design'] is None and all(all(v is None for v in x['applicability'].values()) and all(x[k] is None for k in ['source_review','naturalness_review','final_inclusion','reviewer_id','rationale','signature']) for x in review['items']))
    counts=read_json('audit/COUNTS.json')
    check('six planning feasibility witnesses',counts['feasibility_witnesses']==6)
    for path,value in [('audit/PAIR_CHECKS.json',pair_details),('audit/CURRENT_PAGE_PROJECTIONS.json',projections),
                       ('audit/PRELOAD_REPLAY_VIEWS.json',replay_views),('audit/FIXED_CORPUS_ABSENCE_CHECK.json',absence)]:
        (ROOT/path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return dict(status='PASS',checks=len(checks),failed=0,source_spans_checked=checked_spans,
                provider_calls=0,p3_calls=0,target_retriever_calls=0,native_memory_calls=0,
                candidate_final_calls=0,judge_calls=0,human_judgments_filled=0,details=checks)


if __name__=='__main__':
    try:
        report=validate()
    except Exception as exc:
        report=dict(status='FAIL',error=str(exc),details=checks)
        (ROOT/'audit/VALIDATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        raise
    (ROOT/'audit/VALIDATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False))
