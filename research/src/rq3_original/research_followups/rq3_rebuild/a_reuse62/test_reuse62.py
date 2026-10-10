"""Offline regression checks; handwritten fixtures, never generated task answers."""
from copy import deepcopy
from dataclasses import replace,asdict
from pathlib import Path
import csv
import json
import socket
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT))
from build_materials import loadlines,digest,EXPECTED
from interfaces import ReplayService,resolve_intent,typed_planner,final_payload,final_issues,freeze_answer,validate_bridge,replay_source_check,bridge_api
from utils.c4_rebuild.contracts import Mode
from research_followups.rq3_rebuild.i0_human_integration.fixtures import snapshot,request,SyntheticRouter,END,START,rag_source
from runtime import Worker,readiness

def denied(*a,**kw):raise AssertionError('NETWORK_FORBIDDEN_DURING_OFFLINE_TEST')
socket.create_connection=denied;socket.socket.connect=denied

class Checks(unittest.TestCase):
    def prepared(self,planning=False,query='What should I do next?'):
        return ReplayService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(False,False,planning)).prepare(
            request(Mode.S4_EVIDENCE_PLANNING if planning else Mode.S1_CROSS_PAGE_EVIDENCE,query=query,as_of=END,future_policy='WARN_SNAPSHOT_ONLY'))

    def test_original62_and_original25(self):
        p=HERE/'originals/unified_benchmark_scenarios.jsonl';self.assertEqual(digest(p.read_bytes()),EXPECTED)
        rows=loadlines(p);tasks=loadlines(HERE/'runtime/TASKS_62.jsonl')
        self.assertEqual(len(rows),62);self.assertEqual(len(tasks),62)
        for a,b in zip(rows,tasks):self.assertEqual(a['student_query'],b['query']);self.assertEqual(a['page'],b['page'])
        self.assertEqual([r['source_scenario_id'] for r in rows[:25]],[f'S{i:03}' for i in range(1,26)])

    def test_runtime_no_sidecars(self):
        for t in loadlines(HERE/'runtime/TASKS_62.jsonl'):
            self.assertEqual(set(t),{'task_id','query','page','history'})
            self.assertTrue(all(set(h)=={'role','content'} for h in t['history']))
        p=self.prepared();wire=final_payload(p,dict(model='HANDWRITTEN_FIXTURE',temperature=0,max_output_tokens=2048))
        body=json.loads(wire['messages'][1]['content'])
        self.assertNotIn('task_id',body);self.assertNotIn('gold',body);self.assertNotIn('plan_fields',wire['response_format']['json_schema']['schema']['properties'])

    def test_history_not_relocated(self):
        changes=json.loads((HERE/'INPUT_DIFFERENCES_62.json').read_text())
        self.assertEqual(sum(c['old_9_session_move_reversed'] for c in changes),9)
        for row in changes:
            self.assertEqual(len(row['original_history']),len(row['new_visible_history']))
            for a,b in zip(row['original_history'],row['new_visible_history']):
                self.assertEqual(a['role'],b['role']);self.assertTrue(b['content'].endswith(a['content']))

    def test_blank_human_all_modes_common(self):
        with (HERE/'human/BLANK_RATINGS_2976.csv').open(encoding='utf-8-sig') as f:ratings=list(csv.DictReader(f))
        with (HERE/'human/COMMON_APPLICABILITY_496.csv').open(encoding='utf-8-sig') as f:apps=list(csv.DictReader(f))
        self.assertEqual(len(ratings),2976);self.assertEqual(len(apps),496)
        self.assertTrue(all(not r[k] for r in ratings for k in ['score','rationale','rater','signature','response_id']))
        self.assertTrue(all(not r[k] for r in apps for k in ['applicable','reason','reviewer','signature']))
        for i in range(1,63):
            sets=[{r['criterion'] for r in ratings if r['case_id']==f'U{i:03}' and r['mode']==m.value} for m in Mode]
            self.assertTrue(all(s==sets[0] and len(s)==8 for s in sets))

    def test_final_plan_app_owned(self):
        plan={'opaque_fixture_plan':'HANDWRITTEN_PLAN_NO_PROVIDER'}
        out={'answer':'Handwritten schema fixture.','cited_evidence_ids':[]}
        frozen=freeze_answer(out,[],plan);plan['opaque_fixture_plan']='mutated'
        self.assertEqual(frozen['accepted_plan']['opaque_fixture_plan'],'HANDWRITTEN_PLAN_NO_PROVIDER')
        self.assertTrue(final_issues(dict(out,plan_fields={}),[]))
        self.assertTrue(final_issues(dict(out,cited_evidence_ids=['current-request']),[]))
        self.assertTrue(final_issues(dict(out,cited_evidence_ids=['missing']),['known']))
        self.assertFalse(final_issues(out,[]))

    def test_page_only_preserved_and_evidence_differs(self):
        q='How do lecture videos connect to debate preparation?';snap=snapshot()
        pairs=[]
        for mode in [Mode.S0_PAGE_ONLY,Mode.S1_CROSS_PAGE_EVIDENCE]:
            p=ReplayService(enabled=True,snapshot=snap).prepare(request(mode,query=q,as_of=END))
            pairs.append(p['final_request']['runtime_input']['evidence']['selected_evidence'])
        self.assertEqual(pairs[0][0],pairs[1][0]);self.assertEqual(len(pairs[0]),1)
        self.assertGreater(len(pairs[1]),len(pairs[0]))
        self.assertNotIn('Debate',pairs[0][0]['content']['activity'])

    def test_overview_existing_crosspage_not_removed(self):
        p=ReplayService(enabled=True,snapshot=snapshot()).prepare(request(Mode.S0_PAGE_ONLY,query='Summarise recorded activity.',page='Overview',as_of=END))
        self.assertEqual(set(p['final_request']['runtime_input']['evidence']['selected_evidence'][0]['content']['activity']),{'Lecture','Resources','Debate','Reflection'})

    def test_completed_window_endpoint_without_date_shift(self):
        p=self.prepared();self.assertEqual(p['final_request']['runtime_input']['scope']['as_of'],END)
        with self.assertRaisesRegex(Exception,'COMPLETE_REPLAY_WINDOW'):
            ReplayService(enabled=True,snapshot=snapshot()).prepare(request(query='Summarise recorded activity.'))

    def test_ordinary_action_no_invented_calendar(self):
        for q in ['What should I do next?','How can I improve in this activity?','How should I do item 1?']:
            self.assertEqual(resolve_intent(q)['mode'],'ORDINARY_ACTION_ADVICE')
        self.assertNotEqual(resolve_intent('Schedule my tasks')['mode'],'ORDINARY_ACTION_ADVICE')
        p=self.prepared(planning=True)
        self.assertEqual(p['planner']['status'],'CANDIDATE_PENDING_DISABLED_TRANSPORT')
        tool=typed_planner();self.assertEqual(tool.plan_kind(p['planner']['bridge'])['kind'],'ORDINARY_ACTION_ADVICE')
        wire=tool.candidate_payload(p,dict(model='HANDWRITTEN_FIXTURE',temperature=0,max_output_tokens=2048))
        self.assertEqual(wire['response_format']['json_schema']['schema']['properties']['actions']['items']['properties']['schedule']['type'],'null')
        self.assertIsNone(p['planner']['bridge']['planner_input']['scope']['timezone'])

    def test_current_request_point_does_not_bypass_scope_or_tamper(self):
        p=self.prepared(planning=True);bridge=p['planner']['bridge'];self.assertEqual(validate_bridge(bridge)['outcome'],'PASSED_ENCODED_CHECKS')
        bad=deepcopy(bridge);bad['planner_input']['facts'][0]['source_ref']['course_id']='WRONG'
        self.assertNotEqual(validate_bridge(bad)['outcome'],'PASSED_ENCODED_CHECKS')

    def test_point_extension_preserves_access_version_and_future_failures(self):
        bridge=self.prepared(planning=True)['planner']['bridge'];inp=bridge['planner_input']
        for field,value,code in [('access','DENIED','SOURCE_ACCESS_DENIED'),('version','wrong','SOURCE_VERSION_STALE'),
            ('course_id','other','SOURCE_SCOPE_MISMATCH'),('observed_at','2026-09-20T00:00:00+02:00','SOURCE_FROM_FUTURE')]:
            changed=deepcopy(inp);ref=changed['facts'][0]['source_ref'];ref[field]=value
            report=bridge_api.p1v.p0.Report();replay_source_check(bridge)(ref,'$.facts[0].source_ref',changed,report)
            self.assertIn(code,[i['code'] for i in report.issues])

    def test_other_fact_cannot_claim_current_request_point(self):
        bridge=self.prepared(planning=True)['planner']['bridge'];inp=deepcopy(bridge['planner_input'])
        fact=inp['facts'][0];fact['fact_id']='different';fact['fact_type']='UNRELATED_SOURCE'
        report=bridge_api.p1v.p0.Report();replay_source_check(bridge)(fact['source_ref'],'$.facts[0].source_ref',inp,report)
        self.assertIn('SOURCE_VALIDITY_ORDER',[i['code'] for i in report.issues])

    def test_rag_upstream_gate_once(self):
        retriever=rag_source();p=ReplayService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(True,False,False),retriever=retriever).prepare(
            request(Mode.S2_EVIDENCE_RAG,query='What about a blue bicycle?',as_of=END))
        self.assertEqual(retriever.calls,1);self.assertIn('RAG_SINGLE_GATE_SCORER',p['trace']['ordered_events'])

    def test_no_authorization_no_transport(self):
        result=subprocess.run([sys.executable,'-B',str(HERE/'run_batch.py'),'--execute'],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(result.returncode,2);self.assertIn('NO_PROVIDER_AUTHORIZATION',result.stderr)

    def test_actual_source_readiness_does_not_infer_permission(self):
        tasks=loadlines(HERE/'runtime/TASKS_62.jsonl');b=json.loads((HERE/'runtime/SOURCE_BINDINGS.json').read_text())
        rows=readiness(tasks,b);self.assertEqual(len(rows),62);self.assertEqual(sum(r['ready'] for r in rows),0)

    def test_actual_worker_source_rebuild_and_native_empty_state_clones(self):
        # A disposable fixture exercises the actual loader/worker. It is not added to the 62 roster.
        snap=snapshot();req=request(query='Summarise recorded activity.',as_of=END)
        with tempfile.TemporaryDirectory(prefix='reused62-contract-') as td:
            td=Path(td);entries={}
            for name,records in snap.tables.items():
                f=td/(name+'.csv');cols=list(snap.specs[name].columns)
                with f.open('w',newline='') as out:
                    w=csv.DictWriter(out,fieldnames=cols);w.writeheader();w.writerows(records)
                spec=asdict(snap.specs[name]);entries[name]=dict(path=str(f),sha256=digest(f.read_bytes()),spec=spec)
            rs=rag_source();cf=td/'chunks.jsonl'
            cf.write_text(''.join(json.dumps(asdict(c))+'\n' for c in rs.scorer.chunks))
            b=dict(schema_version='REUSED62_SOURCE_BINDINGS_V1',snapshot=dict(version=snap.version,origin='SYNTHETIC',tables=entries),
                source_permission_ref='EXPLICIT_DISPOSABLE_CONTRACT_FIXTURE',course_id=req.scope.course_id,
                roster={k:list(v) for k,v in snap.roster.items()},
                calendars={k:dict(version=v.version,timezone=v.timezone,weeks=dict(v.weeks)) for k,v in snap.calendars.items()},
                rag=dict(path=str(cf),sha256=digest(cf.read_bytes()),version=req.source_version,corpus_sha256=rs.scorer.corpus_hash,validity_interval=[START,END]),
                memory_policy='CANONICAL_SAME_SESSION_NO_INFERRED_PERSISTENT_PRELOAD',
                tasks={'FIXTURE':dict(learner_id=req.scope.learner_id,scope=req.scope.internal(),as_of=END,
                    permission_ref='EXPLICIT_DISPOSABLE_CONTRACT_FIXTURE',future_policy='WARN_SNAPSHOT_ONLY',memory=None)})
            bf=td/'bindings.json';bf.write_text(json.dumps(b))
            task=dict(task_id='FIXTURE',query=req.query,page=req.page,history=list(req.history))
            common=dict(task=task,bindings_path=str(bf),bindings_digest=digest(b))
            worker=Worker();source=worker.call(dict(common,op='source'))
            traces=[]
            for mode in ['S3_EVIDENCE_MEMORY','S5_FULL']:
                result=worker.call(dict(common,op='prepare',mode=mode,primary_sha256=source['primary_sha256'],
                    config=dict(evidence_budget=12000,request_budget=50000),
                    route=dict(rag_required=False,memory_required=True,planning_required=False,provider_identity='SYNTHETIC_DISPOSABLE_CONTRACT_ROUTE')))
                traces.append(result['prepared']['trace']['memory_diagnostics'])
                self.assertEqual(result['memory_calls'],1)
                self.assertEqual(result['prepared']['trace']['memory_returned_ids'],[])
            self.assertEqual(traces[0]['native_state_sha256'],traces[1]['native_state_sha256'])
            self.assertTrue(all(t['readonly_state_unchanged'] for t in traces))

if __name__=='__main__':unittest.main(verbosity=2)
