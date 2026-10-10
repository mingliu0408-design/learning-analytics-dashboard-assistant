"""One temporary engineering fixture; no transport, target retrieval or scoring."""
import json
from pathlib import Path
import tempfile
import export_generation as e


def main():
    d=e.read(e.STUDY/'CONFIRMED_RESEARCH_DECISIONS.json')
    with tempfile.TemporaryDirectory(prefix='rq3-handoff-fixture-') as td:
        base=Path(td);run=base/'fixture_run';run.mkdir()
        for folder in ('attempts','stages','terminals'):(run/folder).mkdir()
        (run/'RUN.lock').touch();(run/'JOURNAL.jsonl').touch()
        ident={'git_head':e.git('rev-parse','HEAD')}
        e.put(base/'preflight.json',e.blob({'binding':ident}))
        e.put(base/'approval.json',e.blob({'binding':ident,'task_ids':d['included_task_ids'],'output_directory':str(run)}))
        e.put(base/'process.json',e.blob({'process_exited':True,'returncode':1,'engineering_fixture_only':True,'provider_calls':0}))
        # LIVE is a fixture of the preserved transport marker, never a real run.
        e.put(run/'RUN_BINDING.json',e.blob(dict(ident,transport_kind='LIVE',engineering_fixture_only=True)))
        answer='  Verbatim fixture: <>&\n第二行。\n'
        tid=d['included_task_ids'][0]
        for i,status in enumerate(('ACCEPTED','ENCODED_CHECK','UNKNOWN_COMPLETION')):
            logical=tid+':'+d['modes'][i];aid='fixture-'+str(i)
            request={'fixture_only':True}
            start={'attempt_id':aid,'logical':logical+':FINAL','role':'FINAL','group':'FINAL','attempt':1,
                'request':request,'request_sha256':e.sha(e.canonical(request)),
                'monotonic_start':10+i*2,'reserved_usd_upper_bound':.01}
            e.put(run/'attempts'/f'{aid}.start.json',e.blob(start))
            if status=='UNKNOWN_COMPLETION':continue
            raw=e.blob({'fixture_only':True,'value':answer if i==0 else 'invalid'})
            e.put(run/'attempts'/f'{aid}.raw.json',raw)
            out={'attempt_id':aid,'status':status,'raw_sha256':e.sha(raw),'value':{'answer':answer} if i==0 else None,'usage':None}
            e.put(run/'attempts'/f'{aid}.outcome.json',e.blob(out))
            if status=='ACCEPTED':
                stage={'logical':logical,'stage':'RESPONSE','output':{'task_id':tid,'mode':d['modes'][i],'result':out,
                    'response':{'answer':answer,'human_scores':[]},'human_scores':[]}}
                e.put(run/'stages'/'fixture.json',e.blob(stage))
        summary=e.export(run,base/'approval.json',base/'preflight.json',base/'process.json',base/'export')
        rows=e.rows(base/'export/RESPONSE_HANDOFF.jsonl')
        assert summary['slot_status_counts']=={'ACCEPTED':1,'ENCODED_CHECK':1,'UNKNOWN_COMPLETION':1,'NOT_EXECUTED':243}
        assert rows[0]['answer']==answer and rows[0]['answer_sha256']==e.sha(answer.encode())
        assert all(r['answer'] is None for r in rows[1:])
        assert all(r['origin'] is None and r['logical_id'] is None for r in rows[3:])
        assert summary['physical_calls']==3 and summary['unknown_calls']==1 and summary['failed_calls']==1
        assert (base/'export/READABLE_RESPONSES.html').read_text().count('<article>')==246
    receipt={'passed':True,'engineering_fixture_only':True,'checks':['246 exact slots','four distinct terminal categories',
        'UTF-8 answer bytes preserved','unexecuted origin and logical ID not fabricated','unknown reservation preserved','readable HTML covers all slots'],
        'provider_calls':0,'target_retrieval_calls':0,'human_scores_filled':0}
    e.put(e.STUDY/'EXPORT_TEST.json',e.blob(receipt))
    print(json.dumps(receipt))


if __name__=='__main__':main()
