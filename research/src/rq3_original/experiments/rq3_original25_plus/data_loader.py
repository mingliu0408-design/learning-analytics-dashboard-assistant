"""Read-only dataset projections. No provider, router, retrieval or production Memory imports."""
from pathlib import Path
from collections import Counter
from datetime import datetime
import json
import copy

ROOT = Path(__file__).resolve().parent
TASK_KEYS = {'task_id','query','page','visible_history','scope','query_time','source_bindings'}
PAGES = ['Resources','Lecture','Debate','Reflection']


def read_json(path):
    return json.loads((ROOT/path).read_text())


def read_jsonl(path):
    return [json.loads(line) for line in (ROOT/path).read_text().splitlines() if line]


def task(task_id):
    result = next(t for t in read_jsonl('runtime_tasks.jsonl') if t['task_id']==task_id)
    if set(result)!=TASK_KEYS:
        raise ValueError('Runtime row contains unexpected fields')
    return result


def context(task_id):
    t = task(task_id)
    cid = t['source_bindings']['context_id']
    if cid is None:
        return None
    return read_json('source_materials/catalog.json')['contexts'][cid]


def shared_course_corpus():
    """Always the same full ordinary corpus. Deliberately has no task_id argument."""
    path = read_json('source_materials/catalog.json')['course_corpora']['shared-course-v1']
    return read_jsonl(path)


def instant(value):
    return datetime.fromisoformat(value)


def _matches(row, sc, when, event=False):
    if row['student_id']!=sc['student_id'] or row['course_id']!=sc['course_id']:
        return False
    time = instant(row['occurred_at'] if event else row['updated_at'])
    if time>instant(when):
        return False
    if event:
        return instant(sc['window_start'])<=time<instant(sc['window_end'])
    return True


def page_observations(task_id, include_other_pages=False):
    t = task(task_id); binding=context(task_id)
    if binding is None:
        return dict(current_page=t['page'],page_data=None,
                    observation_note='Original page data, identity and observation window were not recovered.')
    s=read_json(binding['page_state_path']);sc=t['scope']
    summaries={}
    for page in PAGES:
        ev=[x for x in s['events'] if x['page']==page and _matches(x,sc,t['query_time'],True)]
        records=[x for x in s['records'] if x['page']==page and _matches(x,sc,t['query_time'])]
        coverage=s['coverage'][page]
        summaries[page]=dict(page=page,coverage=coverage,events=ev,records=records,
               event_count=len(ev) if coverage['status']=='COMPLETE' else None,
               event_type_counts=dict(Counter(x['event_type'] for x in ev)) if coverage['status']=='COMPLETE' else None)
    if t['page']=='Overview':
        # Overview is a view over four domains, never another event source.
        current=dict(page='Overview',domain_summaries=summaries)
    else:
        current=summaries[t['page']]
    return dict(current_page=t['page'],page_data=current,
                **({'other_pages':{k:v for k,v in summaries.items() if k!=t['page']}} if include_other_pages else {}))


def generator_input(task_id):
    """A current-page-only input inspection; never imports the evaluation sidecar."""
    t=task(task_id)
    return dict(query=t['query'],page=t['page'],visible_history=t['visible_history'],
                dashboard_context=page_observations(task_id))


def replay_preload(task_id):
    """Transparent Python record replay, NOT a native Memory retrieval/extraction test."""
    t=task(task_id);binding=context(task_id)
    if not binding or not binding['history_path']:
        return {}
    h=read_json(binding['history_path'])
    messages={m['message_id']:(s,m) for s in h['sessions'] for m in s['messages']}
    ops=read_jsonl(binding['memory_operations_path']); latest={}
    for op in sorted(ops,key=lambda o:instant(o['valid_from'])):
        s,m=messages[op['source_message_id']]
        if s['student_id']!=t['scope']['student_id'] or s['course_id']!=t['scope']['course_id']:
            raise ValueError('Preload source outside task scope')
        if op['source_session_id']!=s['session_id'] or op['source_role']!=m['role']:
            raise ValueError('Source role/session mismatch')
        if m['content'][op['source_char_start']:op['source_char_end']]!=op['source_quote']:
            raise ValueError('Source span mismatch')
        if op['valid_from']!=m['timestamp']:
            raise ValueError('Fact validity does not start at the source statement')
        if instant(op['valid_from'])>=instant(t['query_time']):
            raise ValueError('Preload source must precede new target session')
        if op['source_role']=='assistant' and op['record_type']!='ASSISTANT_SUGGESTION':
            raise ValueError('Unadopted assistant advice cannot be a user fact/active plan')
        prior=latest.get(op['memory_key'])
        if prior:
            if op['replaces_version']!=prior['version'] or op['version']!=prior['version']+1:
                raise ValueError('Invalid fact version chain')
        elif op['version']!=1 or op['replaces_version'] is not None:
            raise ValueError('Version chain lacks its origin')
        latest[op['memory_key']]=copy.deepcopy(op)
    return latest


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description='Offline source inspection only')
    p.add_argument('task_id');p.add_argument('--view',choices=['current','pages','preload'],default='current')
    a=p.parse_args()
    result=generator_input(a.task_id) if a.view=='current' else page_observations(a.task_id,True) if a.view=='pages' else replay_preload(a.task_id)
    print(json.dumps(result,ensure_ascii=False,indent=2))
