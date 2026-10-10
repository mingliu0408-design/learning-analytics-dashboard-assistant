"""Post-authoring overlap inventory. Reads only query/history/source text projections, never scores."""
from pathlib import Path
from difflib import SequenceMatcher
import re
import json
import hashlib
from data_loader import ROOT,read_json,read_jsonl


def normal(text):
    return re.sub(r'\s+',' ',text).strip().casefold()


def text_values(obj):
    if isinstance(obj,str):return [obj]
    if isinstance(obj,list):return [t for x in obj for t in text_values(x)]
    if isinstance(obj,dict):
        return [t for k,v in obj.items() if k in {'content','text','query','student_query','visible_context','visible_history','conversation_history','messages','source_turns','sources'} for t in text_values(v)]
    return []


def main():
    old=[];sources=[]
    p=Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/evaluation/unified_benchmark_scenarios.jsonl')
    data=p.read_bytes();rows=[json.loads(x) for x in data.splitlines()]
    sources.append(dict(path=str(p),sha256=hashlib.sha256(data).hexdigest(),used_fields=['scenario_id','student_query','conversation_history'],excluded='All labels, predicted routes, expected sources, scores, Gold and answers'))
    for r in rows[25:]:
        old.append(dict(origin='old37',id=r['scenario_id'],query=r['student_query'],history=text_values(r['conversation_history'])))
    h3=Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-h3-dev-task-build/research_followups/rq3_rebuild/h3_dev_task_build/runtime_visible')
    for p in sorted(h3.glob('*.json')):
        data=p.read_bytes();r=json.loads(data)
        sources.append(dict(path=str(p),sha256=hashlib.sha256(data).hexdigest(),used_fields=['query','visible_context']))
        old.append(dict(origin='H3',id=p.stem,query=r['query'],history=text_values(r.get('visible_context',[]))))
    p=Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-h1-task-source-packs/research_followups/rq3_rebuild/h1_task_source_packs/DEV_EXAMPLES/SYNTHETIC_SOURCE_TURNS.json')
    data=p.read_bytes();r=json.loads(data)
    sources.append(dict(path=str(p),sha256=hashlib.sha256(data).hexdigest(),used_fields=['sources/source_id','sources/source_turns/content']))
    for s in r['sources']:
        old.append(dict(origin='H1 source history',id=s['source_id'],query='',history=[t['content'] for t in s['source_turns']]))
    tasks={t['task_id']:t for t in read_jsonl('runtime_tasks.jsonl')};out=[]
    old_texts=[normal(x) for o in old for x in [o['query']]+o['history'] if x]
    new_history=[]
    for p in (ROOT/'source_materials/histories').glob('*.json'):
        for s in json.loads(p.read_text())['sessions']:
            new_history += [normal(m['content']) for m in s['messages']]
    for d in read_json('family_design.json')['tasks']:
        t=tasks[d['task_id']];q=normal(t['query'])
        ranked=sorted([(SequenceMatcher(None,q,normal(o['query'])).ratio(),o['origin'],o['id']) for o in old if o['query']],reverse=True)
        out.append(dict(task_id=t['task_id'],family_id=d['family_id'],exact_query_matches=[dict(origin=o['origin'],id=o['id']) for o in old if q==normal(o['query'])],
                        highest_literal_similarity=dict(ratio=round(ranked[0][0],4),origin=ranked[0][1],id=ranked[0][2])))
    report=dict(status='COMPLETED_OFFLINE_AFTER_DRAFTING',new_queries=len(out),old37_queries=37,h3_queries=7,
        h1_source_episodes=sum(o['origin']=='H1 source history' for o in old),
        exact_query_overlaps=sum(bool(x['exact_query_matches']) for x in out),
        exact_historical_utterance_overlaps=sum(x in old_texts for x in set(new_history)),
        new_task_id_overlaps=sorted(set(tasks)&{o['id'] for o in old}),
        method='Unicode casefold/whitespace-normalised exact match and literal SequenceMatcher; source identities retained, no ranking or model output used.',
        semantic_limit='Chinese new drafts and English old queries limit literal similarity. Zero lexical matches is not independent semantic novelty certification. Final human semantic review is blank.',
        resolved_during_authoring=[dict(family='R02',finding='Initial general reflection-to-analysis question was semantically close to H3 R01.',resolution='Replaced with attribution of a peer explanation, paired with direct-book-quotation requirements from a second handbook section. No target output observed.'),
            dict(family='R03',finding='Article sample-size question shared the old H3 R03 form.',resolution='Final request concerns reconstructing an article-specific teaching procedure versus its bibliographic identity; no participants/results-number question retained. Same boundary design primitive is disclosed.')],
        related_patterns_not_claimed_novel=['E01 cross-page lecture/debate connection resembles an old capability focus, but publication status pair and event state are new.',
            'R01 uses previously exposed handbook but asks about equivalent versus literal word limits.',
            'R02/R03 use exposed source domain and familiar citation/provenance boundaries.',
            'Memory and Planning use familiar goals/budgets/dependencies, but no old maths episode, historical wording or old source operation was copied.'],
        human_semantic_review=None,sources=sources,items=out)
    (ROOT/'audit/OVERLAP_REVIEW.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k in ['new_queries','old37_queries','h3_queries','h1_source_episodes','exact_query_overlaps','exact_historical_utterance_overlaps','new_task_id_overlaps']},ensure_ascii=False))


if __name__=='__main__':main()
