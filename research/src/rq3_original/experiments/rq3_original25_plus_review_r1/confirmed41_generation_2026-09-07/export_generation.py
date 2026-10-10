"""Offline, write-once export of a stopped run. Never sends or resumes requests."""
import argparse
from collections import Counter, defaultdict
import csv
import fcntl
import hashlib
import html
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

STUDY = Path(__file__).resolve().parent
DATA = STUDY.parent
ROOT = DATA.parents[1]
START = 'abed9b54078d23b10d2c24eeb0f5e231d4b21270'


def read(p): return json.loads(Path(p).read_text())
def rows(p): return [json.loads(s) for s in Path(p).read_text().splitlines() if s]
def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(o): return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def blob(o): return (json.dumps(o, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
def git(*args): return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def put(p, b):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('xb') as f:
        f.write(b); f.flush(); os.fsync(f.fileno())


def entry(p, base):
    return dict(path=str(p.relative_to(base)), bytes=p.stat().st_size, sha256=sha(p.read_bytes()))


def study_check():
    d = read(STUDY/'CONFIRMED_RESEARCH_DECISIONS.json')
    m = read(DATA/'RUN_MANIFEST.json')
    assert d['included_task_ids'] == m['task_ids'] and len(m['task_ids']) == 41
    assert m['version'] == 'ORIGINAL25_PLUS_EN_V2' and m['data_revision'] == 'ORIGINAL25_PLUS_REVIEW_R1'
    old = {r['task_id']: r for r in read(DATA/'applicability.json')['items']}
    a = read(STUDY/'APPLICABILITY_CONFIRMED_41.json')['items']
    changes = {(r['task_id'], k) for r in a for k,v in r['applicability'].items() if old[r['task_id']]['draft'][k] is not v}
    expected = {(t,g['criterion']) for g in read(DATA/'AUTHOR_DECISIONS.json')['applicability_groups'] for t in g['task_ids']}
    assert changes == expected and len(changes) == 69
    for r in a:
        assert r['shared_across_modes'] == d['modes']
        for k,v in r['applicability'].items():
            assert type(v) is bool
            assert old[r['task_id']]['draft'][k] is v or (old[r['task_id']]['draft'][k] is None and v is False)
    assert Counter(str(v) for r in a for v in r['applicability'].values()) == {'True':208,'False':120}
    all49 = read(STUDY/'APPLICABILITY_ALL49.json')['items']
    assert len(all49) == 49 and sum(r['final_inclusion'] for r in all49) == 41
    for r in all49:
        assert r['reviewer_id'] is r['signature'] is r['scores'] is None
        if not r['final_inclusion']: assert r['applicability'] == old[r['task_id']]['draft']
    for name,h in read(STUDY/'BASELINE_FILES.json')['files'].items():
        if name != 'RUN_MANIFEST.json': assert sha((DATA/name).read_bytes()) == h, name
    prior = read(STUDY/'task_packet/source_snapshot/RUN_MANIFEST.json')
    assert {k:v for k,v in m.items() if k!='confirmed_study_sidecars'} == prior
    for e in m['confirmed_study_sidecars']:
        assert sha((DATA/e['path']).read_bytes()) == e['sha256'], e['path']
    return dict(passed=True, applicability_changes=69, included_true=208, included_false=120,
                included_null=0, preserved_baseline_files=len(read(STUDY/'BASELINE_FILES.json')['files'])-1)


def export(run, approval, preflight, process, output):
    study_check()
    receipt = read(process)
    assert receipt['process_exited'] is True and type(receipt['returncode']) is int
    a, pf = read(approval), read(preflight)
    assert a['binding'] == pf['binding'] and git('rev-parse','HEAD') == a['binding']['git_head']
    assert a['task_ids'] == read(DATA/'RUN_MANIFEST.json')['task_ids']
    assert Path(a['output_directory']).resolve() == run.resolve()
    lock = (run/'RUN.lock').open('r')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        binding = read(run/'RUN_BINDING.json')
        assert binding['transport_kind']=='LIVE' and all(binding[k]==v for k,v in pf['binding'].items())
        output.mkdir(parents=True, exist_ok=False)
        files = [run/'RUN_BINDING.json', run/'JOURNAL.jsonl']
        if (run/'STOP.json').exists(): files.append(run/'STOP.json')
        files += sorted(p for sub in ('attempts','terminals','stages') for p in (run/sub).glob('*.json'))
        files = [p for p in files if p.exists()]
        for p in files:
            assert not p.is_symlink()
            put(output/'run'/p.relative_to(run),p.read_bytes())
        for source,name in [(approval,'EXECUTION_APPROVAL.json'),(preflight,'PREFLIGHT.json'),(process,'PROCESS_EXIT.json')]:
            put(output/name, source.read_bytes())
        starts = sorted((read(p) for p in (run/'attempts').glob('*.start.json')), key=lambda r:r['monotonic_start'])
        outcomes = {p.name.removesuffix('.outcome.json'):read(p) for p in (run/'attempts').glob('*.outcome.json')}
        stages = [(p,read(p)) for p in (run/'stages').glob('*.json')]
        response = {r['logical']:(p,r) for p,r in stages if r['stage']=='RESPONSE'}
        active = defaultdict(list)
        stats = defaultdict(Counter)
        known_input=known_output=0; reserved=known_cost=0.0; unknown_usage=0
        for s in starts:
            aid=s['attempt_id']; active[s['logical']].append(s)
            assert sha(canonical(s['request']))==s['request_sha256']
            o=outcomes.get(aid)
            raw=run/'attempts'/f'{aid}.raw.json'
            if o and o.get('raw_sha256'): assert sha(raw.read_bytes())==o['raw_sha256']
            status=o['status'] if o else 'UNKNOWN_COMPLETION'
            st=stats[s['role']]; st['calls']+=1; st['retries']+=int(s['attempt']>1)
            st['success' if status=='ACCEPTED' else 'unknown' if status=='UNKNOWN_COMPLETION' else 'failed']+=1
            reserved+=s['reserved_usd_upper_bound']
            u=o.get('usage') if o else None
            if isinstance(u,dict) and all(type(u.get(k)) is int for k in ('prompt_tokens','completion_tokens')):
                known_input+=u['prompt_tokens']; known_output+=u['completion_tokens']
                known_cost+=(u['prompt_tokens']*.15+u['completion_tokens']*.60)/1e6
            else: unknown_usage+=1
        slots=[]
        d=read(STUDY/'CONFIRMED_RESEARCH_DECISIONS.json')
        for tid in d['included_task_ids']:
            for mode in d['modes']:
                logical=tid+':'+mode
                item=dict(task_id=tid,mode=mode,logical_id=None,status='NOT_EXECUTED',answer=None,answer_sha256=None,
                    origin=None,raw_response_path=None,raw_response_sha256=None,response_record_path=None,response_record_sha256=None,
                    declared_slot_key=logical,logical_id_basis='NO_RUNTIME_RECORD',human_scores=[])
                rr=response.get(logical); ss=active.get(logical+':FINAL',[])
                if rr:
                    p,r=rr; out=r['output']; res=out['result']
                    assert out['task_id']==tid and out['mode']==mode and out['human_scores']==[]
                    item.update(logical_id=r['logical'],logical_id_basis='RUNNER_RESPONSE_STAGE',status=res['status'],origin='LIVE',
                        response_record_path='run/'+str(p.relative_to(run)),response_record_sha256=sha(p.read_bytes()))
                    if res['status']=='ACCEPTED':
                        answer=out['response']['answer']
                        assert answer==res['value']['answer'] and out['response']['human_scores']==[]
                        item.update(answer=answer,answer_sha256=sha(answer.encode('utf-8')))
                    aid=res['attempt_id']
                elif ss:
                    s=ss[-1];aid=s['attempt_id'];o=outcomes.get(aid)
                    item.update(logical_id=s['logical'],logical_id_basis='RUNNER_FINAL_ATTEMPT_NO_RESPONSE_STAGE',
                        status=o['status'] if o else 'UNKNOWN_COMPLETION',origin='LIVE')
                else:
                    matches=[r for _,r in stages if r['logical']==logical]
                    if matches: item.update(logical_id=matches[0]['logical'],logical_id_basis='RUNNER_MODULE_STAGE_FINAL_NOT_EXECUTED')
                    slots.append(item);continue
                raw=run/'attempts'/f'{aid}.raw.json'
                if raw.exists():item.update(raw_response_path='run/'+str(raw.relative_to(run)),raw_response_sha256=sha(raw.read_bytes()))
                slots.append(item)
        assert len(slots)==246 and len({(r['task_id'],r['mode']) for r in slots})==246
        handoff=b''.join(canonical(r)+b'\n' for r in slots)
        put(output/'RESPONSE_HANDOFF.jsonl',handoff)
        fields=['task_id','mode','logical_id','logical_id_basis','status','origin','answer_sha256','raw_response_path','response_record_path']
        s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields);w.writeheader();w.writerows({k:r[k] for k in fields} for r in slots)
        put(output/'SLOT_STATUS_246.csv',s.getvalue().encode())
        interval=min((b['monotonic_start']-a['monotonic_start'] for a,b in zip(starts,starts[1:])),default=None)
        count=Counter(r['status'] for r in slots)
        modules=[r['output'] for _,r in stages if r['stage']=='MODULES']
        summary=dict(run_directory=str(run.resolve()),process_exit=receipt,answer_slots=246,
            slot_status_counts=dict(count),accepted_answers=sum(r['answer'] is not None for r in slots),
            role_calls={k:dict(v) for k,v in stats.items()},physical_calls=len(starts),retries=sum(s['attempt']>1 for s in starts),
            successful_calls=sum(o['status']=='ACCEPTED' for o in outcomes.values()),
            unknown_calls=sum(o['status']=='UNKNOWN_COMPLETION' for o in outcomes.values())+len(starts)-len(outcomes),
            failed_calls=sum(o['status'] not in ('ACCEPTED','UNKNOWN_COMPLETION') for o in outcomes.values()),
            route_task_stages=sum(r['stage']=='ACTUAL_P3' for _,r in stages),
            actual_rag_calls=sum(r.get('rag_calls',0) for r in modules),actual_memory_calls=sum(r.get('memory_calls',0) for r in modules),
            minimum_start_interval_seconds=interval,known_prompt_tokens=known_input,known_completion_tokens=known_output,
            known_usage_cost_usd=known_cost,reserved_usd=reserved,calls_without_usage=unknown_usage,
            pricing='0.15 input / 0.60 output USD per million; uncached snapshot; not an exact bill guarantee',
            stop=read(run/'STOP.json') if (run/'STOP.json').exists() else None,
            judge_calls=0,human_scores_filled=0,excluded_original_tasks=d['excluded'])
        assert len(starts)<=902 and (interval is None or interval>=2)
        assert all(len(v)<=2 for v in active.values()) and reserved<=10
        put(output/'EXECUTION_SUMMARY.json',blob(summary))
        tasks={r['task_id']:r for r in rows(DATA/'runtime_tasks.jsonl')}
        parts=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Frozen responses · internal researcher copy</title>',
            '<style>body{max-width:960px;margin:2rem auto;font:16px/1.6 system-ui;padding:0 1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:1rem}article{border-top:1px solid #aaa;margin-top:2rem}</style>',
            '<h1>Frozen responses · internal researcher copy</h1><p>Mode-visible; do not send this copy to raters. 所附录播观看记录。No human scores or generated replacements.</p>']
        md=['# 原样回答阅读版（研究者内部）','含模式，不直接给评分者。所附录播观看记录。回答正文逐字保留；失败及未执行不补写。','']
        for r in slots:
            label=r['task_id']+' / '+r['mode']+' / '+r['status'];q=tasks[r['task_id']]['query']
            text=r['answer'] if r['answer'] is not None else '[No accepted response; see preserved status and raw record.]'
            parts.append('<article><h2>'+html.escape(label)+'</h2><p>'+html.escape(q)+'</p><pre>'+html.escape(text)+'</pre></article>')
            md.extend(['## '+label,'',q,'','~~~~',text,'~~~~',''])
        parts.append('</html>');put(output/'READABLE_RESPONSES.html','\n'.join(parts).encode());put(output/'READABLE_RESPONSES.md','\n'.join(md).encode())
        source_names=['runtime_tasks.jsonl','BINDINGS.json','RUN_MANIFEST.json','CONFIG_PROPOSED.json','evaluation_reference.jsonl','family_design.json',
            'human_review/rubric.json','human_review/SUPERVISOR_RUBRIC_REFERENCE.md']
        source_names += [str(p.relative_to(DATA)) for p in (DATA/'source_materials').rglob('*') if p.is_file() and
                         'raw' not in p.relative_to(DATA/'source_materials').parts and p.suffix in ('.json','.jsonl','.md')]
        for name in sorted(set(source_names)):put(output/'study_materials'/name,(DATA/name).read_bytes())
        metadata=dict(audience='RESEARCHER_AND_FROZEN_HANDOFF_PACKAGER_ONLY',source_base='study_materials',
            tasks='study_materials/runtime_tasks.jsonl',common_references='study_materials/evaluation_reference.jsonl',
            applicability='../APPLICABILITY_CONFIRMED_41.json',family_map='../TASK_FAMILY_MAP.json',
            source_and_reference_files=[entry(p,output) for p in sorted((output/'study_materials').rglob('*')) if p.is_file()],
            no_condition_deduplication=True,no_actual_retrieval_as_common_reference=True,ratings_exist=False,
            next_step='B reads only this frozen handoff after completion; create separate opaque-item packages for two independent raters. Do not include mode, routing, internal plans, token counts or revision attempts.')
        put(output/'STUDY_METADATA.json',blob(metadata))
        manifest=dict(approval_binding=pf['binding'],run_binding=binding,actual_run_directory=str(run.resolve()),
            original_slot_roster=[dict(task_id=r['task_id'],mode=r['mode']) for r in slots],
            response_handoff=entry(output/'RESPONSE_HANDOFF.jsonl',output),coverage=summary,
            protocol=[entry(STUDY/e,STUDY) for e in ('CONFIRMED_RESEARCH_DECISIONS.json','APPLICABILITY_CONFIRMED_41.json','TASK_FAMILY_MAP.json','STUDY_PROTOCOL.md','USER_AUTHORIZATION.md')],
            result_files=[entry(p,output) for p in sorted(output.rglob('*')) if p.is_file()],
            frozen_after_process_exit=True)
        put(output/'GENERATION_HANDOFF_MANIFEST.json',blob(manifest))
        return summary
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN);lock.close()


def verify_zip(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
        for i in z.infolist():
            p=PurePosixPath(i.filename)
            assert not p.is_absolute() and '..' not in p.parts and not stat.S_ISLNK(i.external_attr>>16)
        m=json.loads(z.read('MANIFEST.json'))
        assert set(names)=={r['path'] for r in m['members']}|{'MANIFEST.json'}
        for r in m['members']:
            b=z.read(r['path']);assert len(b)==r['bytes'] and sha(b)==r['sha256']
        prefix=str(STUDY.relative_to(ROOT))+'/results/'
        rs=[json.loads(s) for s in z.read(prefix+'RESPONSE_HANDOFF.jsonl').splitlines()]
        assert len(rs)==246 and len({(r['task_id'],r['mode']) for r in rs})==246
        for r in rs:
            if r['answer'] is not None:assert sha(r['answer'].encode())==r['answer_sha256']
            for key in ('raw_response','response_record'):
                if r[key+'_path']:assert sha(z.read(prefix+r[key+'_path']))==r[key+'_sha256']
    return dict(path=str(path.resolve()),sha256=sha(path.read_bytes()),bytes=path.stat().st_size,members=len(names),crc_ok=True,
                exact_members=True,safe_paths=True,all_member_hashes=True,handoff_rows=246,git=m['git'])


def package(output):
    study_check()
    assert not git('status','--porcelain') and git('branch','--show-current')=='research/rq3-rebuild-i1-pilot-launch'
    head=git('rev-parse','HEAD');git('merge-base','--is-ancestor',START,head)
    files=[p for p in STUDY.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [DATA/'run_batch.py',DATA/'adapter.py',DATA/'v2_common.py']
    for e in read(DATA/'DEPENDENCIES.json')['files']:
        p=ROOT/e['path'];assert sha(p.read_bytes())==e['sha256'];files.append(p)
    payload={}
    key=os.environ.get('OPENAI_API_KEY','').encode()
    for p in sorted(set(files)):
        assert not p.is_symlink() and p.suffix not in ('.zip','.sqlite','.bin','.pkl','.safetensors')
        n=str(p.relative_to(ROOT));b=p.read_bytes()
        assert not re.search(rb'sk-(?:proj-)?[A-Za-z0-9_-]{24,}',b)
        assert not key or key not in b
        committed=subprocess.check_output(['git','show',head+':'+n],cwd=ROOT)
        assert b==committed,n
        payload[n]=b
    lineage=dict(starting_head=START,execution_head=read(STUDY/'results/PREFLIGHT.json')['binding']['git_head'],
                 ending_head=head,branch=git('branch','--show-current'),ending_clean=True,
                 changed_paths=git('diff','--name-only',START,head).splitlines(),commits=git('log','--format=%H %s',START+'..'+head).splitlines())
    prefix=str(STUDY.relative_to(ROOT))+'/'
    payload['GIT_LINEAGE.json']=blob(lineage)
    payload['START_HERE.md']=('# 41题限定生成结果与冻结交接\n\n此包是研究者内部包，含模式、运行记录及评价参考；不要直接给评分者。\n\n'
        f'- [执行报告]({prefix}results/EXECUTION_REPORT.md)\n- [原样回答阅读版]({prefix}results/READABLE_RESPONSES.html)\n'
        f'- [246槽交接]({prefix}results/RESPONSE_HANDOFF.jsonl)\n- [交接清单]({prefix}results/GENERATION_HANDOFF_MANIFEST.json)\n'
        f'- [研究协议]({prefix}STUDY_PROTOCOL.md)\n\n两名评分者的身份、签名、分数及理由仍为空；本包没有真实人评统计或LLM Judge。B后续只读取此冻结交接。\n').encode()
    manifest=dict(git=lineage,members=[dict(path=n,bytes=len(b),sha256=sha(b)) for n,b in sorted(payload.items())],
        self_excluded='MANIFEST.json',excluded=['credentials','HMAC keys','raw identity tables','complete personal logs','B active files','old answers and scores','model weights'])
    payload['MANIFEST.json']=blob(manifest)
    with output.open('xb') as f:
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for n,b in sorted(payload.items()):z.writestr(n,b)
        f.flush();os.fsync(f.fileno())
    return verify_zip(output)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['check','export','package','verify'])
    for name in ('run','approval','preflight','process','output'):p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    if a.command=='check':r=study_check()
    elif a.command=='export':r=export(a.run,a.approval,a.preflight,a.process,a.output)
    elif a.command=='package':r=package(a.output)
    else:r=verify_zip(a.output)
    print(json.dumps(r,ensure_ascii=False,indent=2))
