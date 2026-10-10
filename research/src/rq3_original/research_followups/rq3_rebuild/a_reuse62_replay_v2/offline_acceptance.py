"""One bounded source/compiler/R0 acceptance run, no LLM or Memory repeat."""
from replay_common import *
from controlled_runtime import *
from interfaces import final_payload,freeze_answer,FINAL_SCHEMA

def run(resume_saved=False):
    path=HERE/'OFFLINE_ACCEPTANCE.json'
    if path.exists() and not resume_saved:raise FileExistsError('Acceptance already started; no automatic repeat.')
    tasks={t['task_id']:t for t in lines(HERE/'runtime/TASKS_62.jsonl')}
    b=read(HERE/'runtime/BINDINGS.json');cfg=read(HERE/'runtime/CONFIG_PROPOSED.json')
    report=dict(started_utc=utc(),compiler_preparations_started=0,compiler_preparations_completed=0,
        rag_diagnostic_limit=4,rag_queries_started=0,rag_queries_completed=0,memory_reads=0,
        p3_llm_calls=0,candidate_calls=0,final_calls=0,judge_calls=0,evidence_pairs=[],rag=[])
    if resume_saved:
        report=read(path)
        if report.get('ended_utc'):raise ValueError('ALREADY_FINISHED')
        report['reporting_interruption']='First R0 returned and was saved; summary used .status instead of .result_status. Resumed saved evidence and R0 without recomputation.'
        saved=read(HERE/'receipts/rag/U040.json')['result']
        assert report['rag_queries_started']==1 and not report['rag']
        report['rag_queries_completed']=1
        report['rag']=[dict(task_id='U040',status=saved['result_status'],ids=[s['source_id'] for s in saved['sources']])]
        p1=read(HERE/'receipts/evidence/U057_S1_CROSS_PAGE_EVIDENCE.json')['rebuilt']['prepared']
    write(path,report)
    for tid in (() if resume_saved else ('U054','U056','U057')):
        t=tasks[tid];source=source_for(t,b);pair={}
        for mode in ('S0_PAGE_ONLY','S1_CROSS_PAGE_EVIDENCE'):
            report['compiler_preparations_started']+=1;write(path,report)
            rebuilt=handle(dict(op='prepare',task=t,mode=mode,config=cfg,bindings_path=str(HERE/'runtime/BINDINGS.json'),
                bindings_digest=sha(b),primary_sha256=source['primary_sha256'],route=None))
            report['compiler_preparations_completed']+=1
            payload=final_payload(rebuilt['prepared'],cfg['generation_roles']['FINAL'])
            write(HERE/f'receipts/evidence/{tid}_{mode}.json',dict(rebuilt=rebuilt,unsent_final_wire=payload))
            pair[mode]=rebuilt['prepared']
        p0,p1=pair.values()
        e0=p0['final_request']['runtime_input']['evidence']['selected_evidence']
        e1=p1['final_request']['runtime_input']['evidence']['selected_evidence']
        assert e0[0]['content']==e1[0]['content'] and len(e0)==1
        added=[d for item in e1[1:] for d in item['content'].get('activity',{})]
        assert added==({'U054':['Lecture'],'U056':['Resources'],'U057':[]}[tid])
        report['evidence_pairs'].append(dict(task_id=tid,current_identical=True,current_sha256=sha(e0[0]['content']),
            additional_domains=added,extra_content_reached_downstream_input=bool(added),
            overview_current_already_contains_four_domains=tid=='U057',llm_sent=False))
        write(path,report)
    rag=rag_for(b)
    for tid in ('U040','U044','U047','U046'):
        if tid in {r['task_id'] for r in report['rag']}:continue
        request=request_for(tasks[tid],b,Mode.S2_EVIDENCE_RAG)
        report['rag_queries_started']+=1;write(path,report)
        result=rag.retrieve(request);report['rag_queries_completed']+=1
        from dataclasses import asdict
        receipt=dict(task_id=tid,query=request.query,history=list(request.history),diagnostic_gate='LOCAL_READ_DIAGNOSTIC_NOT_P3_OUTPUT',
            corpus_count=624,corpus_sha256=rag.scorer.corpus_hash,reference_ids_supplied=False,result=asdict(result))
        write(HERE/f'receipts/rag/{tid}.json',receipt)
        report['rag'].append(dict(task_id=tid,status=result.result_status,ids=[s.source_id for s in result.sources]))
        write(path,report)
    # Interface wiring only, not a generated answer or a scientific evaluation.
    sentinel={'actions':[],'test_only_sentinel':'APPLICATION_SLOT'}
    wire=final_payload(p1,cfg['generation_roles']['FINAL'],sentinel)
    body=json.loads(wire['messages'][1]['content'])
    assert body['accepted_plan']==sentinel and 'plan_fields' not in wire['response_format']['json_schema']['schema']['properties']
    assert set(FINAL_SCHEMA['properties'])=={'answer','cited_evidence_ids'}
    frozen=freeze_answer(dict(answer='INTERFACE_TEST_ONLY_NO_MODEL_RESPONSE',cited_evidence_ids=[]),[],sentinel)
    assert frozen['accepted_plan']==sentinel
    report['final_wire_check']=dict(two_field_schema=True,application_plan_slot_correct=True,source='interfaces.py reused unchanged',
        test_fixture_only=True,model_response_generated=False,human_fields_filled=False)
    report['ended_utc']=utc();write(path,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    offline()
    if sys.argv[1:] not in ([],['--resume-saved']):raise SystemExit('Use initial run or explicit --resume-saved reporting recovery.')
    run(resume_saved=bool(sys.argv[1:]))
