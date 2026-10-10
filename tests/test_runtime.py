"""Publication adapter integration tests; no paid provider call or research rerun."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import subprocess
import unittest
import uuid
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from copy import deepcopy
from public_runtime.core import PublicAssistant, CoreFailure, tasks, responses, ROOT

class ExactMock:
    def __init__(self,*,planning=True,memory=True,bad_candidate=False,bad_citation=False):
        self.payloads=[]
        self.planning,self.memory,self.bad_candidate,self.bad_citation=planning,memory,bad_candidate,bad_citation
    def send(self,payload):
        self.payloads.append(deepcopy(payload))
        props=payload['response_format']['json_schema']['schema']['properties']
        if set(props)=={'rag_required'}:value={'rag_required':True}
        elif set(props)=={'memory_required'}:value={'memory_required':self.memory}
        elif set(props)=={'rag_required','memory_required','planning_required'}:value={'rag_required':False,'memory_required':False,'planning_required':self.planning}
        elif 'actions' in props:
            body=json.loads(payload['messages'][1]['content'])
            goal=body['encoded_planning_fields']['goals'][0]
            ids=[x['id'] for x in body['candidate_contract']['reference_catalog']]
            value={'plan_id':'new-plan','goal_id':goal['goal_id'],'goal':goal['text'],'actions':[{'step_id':'step_1','task_id':'proposed_task_1','kind':'TASK','action':'Review the learning analytics topic and write one question.','estimated_duration':{'value':5,'unit':'minutes','origin':'MODEL_ESTIMATE','evidence_refs':[],'uncertainty':'This is a model estimate, not measured duration.'},'resource_ids':[],'dependencies':['missing-step'] if self.bad_candidate else [],'schedule':None,'completion_check':'Write one question after review.','evidence_refs':ids[:1],'brief_rationale':'Supports the current requested action.'}],'evidence_refs':ids[:1],'continues_plan_id':None,'brief_rationale':'Ordinary advice without invented calendar dates.'}
        else:
            body=json.loads(payload['messages'][1]['content'])
            ids=body['citation_contract']['allowed_source_ids']
            value={'answer':'This is a mock transport integration result, not a newly generated research answer.','cited_evidence_ids':['not-retained'] if self.bad_citation else ids[:1]}
        return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value),'role':'assistant'}}]}

class RuntimeIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='lad-tests-')
        self.engine=PublicAssistant(uuid.uuid4().hex,storage_root=self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_replay_identifiers_hashes_and_no_fabrication(self):
        rows=responses()
        self.assertEqual(len(rows),246)
        self.assertEqual(len({(r['task_id'],r['mode']) for r in rows}),246)
        self.assertEqual(len({r['answer'] for r in rows}),179)
        for row in rows:self.assertEqual(hashlib.sha256(row['answer'].encode()).hexdigest(),row['answer_sha256'])
        self.assertEqual(self.engine.replay('original-01','S0_PAGE_ONLY')['generation'],'SAVED_HISTORICAL_ANSWER_NO_NEW_MODEL_CALL')
        with self.assertRaises(ValueError):self.engine.replay('new-question','S0_PAGE_ONLY')
    def test_actual_local_single_rag_gate_and_full_worker(self):
        connection=socket.socket.connect
        os.environ['OPENAI_API_KEY']='TEST_ONLY_NOT_REAL'
        try:self.assertFalse(self.engine.call('ping')['provider_credentials_present'])
        finally:os.environ.pop('OPENAI_API_KEY')
        result=self.engine.components('Explain learning analytics in the course',memory=True,rag=True)
        self.assertEqual(result['rag_calls'],1)
        self.assertEqual(result['memory_calls'],1)
        self.assertEqual(socket.socket.connect,connection)
        self.assertFalse(any(k.endswith('m1_common') or k.endswith('state_harness') for k in sys.modules))
        self.assertIn('RAG_SINGLE_GATE_SCORER',result['prepared']['trace']['ordered_events'])
        self.assertEqual(result['generation'],'NO_LLM_NO_NATURAL_ANSWER_GENERATION')
    def test_memory_write_reopen_correction_readonly_and_session_isolation(self):
        seed=ROOT/'data/replay/native_initial/original-01/initial.sqlite'
        before=hashlib.sha256(seed.read_bytes()).hexdigest()
        first=self.engine.memory_write('original-01','My learning goal is understanding analytics','GOAL',consent=True)
        self.assertTrue(first['accepted'])
        mid=first['memory_id']
        second=self.engine.memory_write('original-01','My learning goal is understanding course analytics','GOAL',consent=True,target_memory_id=mid)
        self.assertTrue(second['accepted'])
        reopened=PublicAssistant(self.engine.session_id,storage_root=self.tmp.name)
        records=reopened.memory_list('original-01')
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['content'],'My learning goal is understanding course analytics')
        result=reopened.components('What learning goal did I state?',rag=False,memory=True)
        facts=result['prepared']['final_request']['runtime_input']['memory']['facts']
        self.assertEqual(facts[0]['content'],records[0]['content'])
        self.assertTrue(result['readonly_state_unchanged'])
        other=PublicAssistant(uuid.uuid4().hex,storage_root=self.tmp.name)
        self.assertEqual(other.memory_list('original-01'),[])
        self.engine.bind_key('TEST_VISITOR_PLACEHOLDER')
        self.assertIsNone(other._api_key)
        self.assertEqual(other.history,[])
        self.engine.history.append({'role':'user','content':'source-bound history'})
        self.engine.select_task('task-013459503624')
        self.assertEqual(self.engine.history,[])
        self.engine.select_task('original-01')
        self.assertEqual(self.engine.history[-1]['content'],'source-bound history')
        self.assertEqual(hashlib.sha256(seed.read_bytes()).hexdigest(),before)
        self.assertFalse(any('TEST_VISITOR_PLACEHOLDER' in p.read_text(errors='ignore') for p in Path(self.tmp.name).rglob('*') if p.is_file()))
    def test_exact_p3_mock_full_candidate_final_chain(self):
        provider=ExactMock()
        result=self.engine.live('Give me an action plan without dates to study learning analytics',transport=provider,memory_backend='LEXICAL',controls={'task_intent':'ORDINARY_ACTION_ADVICE'})
        self.assertEqual([r['role'] for r in result['provider_trace']],['RAG','MEMORY','B4_PLANNING','CANDIDATE','FINAL'])
        self.assertIsNotNone(result['accepted_plan'])
        self.assertEqual(result['generation'],'MOCK_EXACT_CORE_NO_PAID_CALL')
        self.assertFalse(result['live_model_call'])
        self.assertEqual(result['frozen_p3']['identity'],'a3dfeb5a87884eda62ebe0b6a7c9df439994be85d8547ec2d90b9ad276a2a4a1')
        for payload in provider.payloads[:3]:
            self.assertEqual(payload['model'],'gpt-4o-mini-2024-07-18')
            self.assertEqual(payload['temperature'],0)
            body=json.loads(payload['messages'][-1]['content'])
            self.assertFalse('gold' in json.dumps(body).lower())
        self.assertNotIn('current-request',result['cited_evidence_ids'])
    def test_negative_planner_repair_and_citation_block(self):
        provider=ExactMock(bad_candidate=True)
        result=self.engine.live('Give me an action plan without dates',transport=provider,memory_backend='LEXICAL',controls={'task_intent':'ORDINARY_ACTION_ADVICE'})
        self.assertIsNone(result['accepted_plan'])
        self.assertTrue(result['candidate_issues'])
        self.assertIn('CANDIDATE_REPAIR',[r['role'] for r in result['provider_trace']])
        with self.assertRaises(CoreFailure):self.engine.live('Explain learning analytics',transport=ExactMock(planning=False,memory=False,bad_citation=True))
    def test_live_memory_missing_resource_is_explicit(self):
        if os.environ.get('LAD_MPNET_PATH'):self.skipTest('Optional local model configured')
        with self.assertRaisesRegex(CoreFailure,'LIVE_MEMORY_REQUIRES_PINNED_MPNET'):
            self.engine.live('What goal did I state?',transport=ExactMock(planning=False),memory_backend='HYBRID')
    def test_scope_course_dedup_unknown_zero_and_time_boundary(self):
        fixture=(ROOT/'tests/scope_fixture.py').read_text()
        result=subprocess.run([sys.executable,'-c',fixture],cwd=ROOT/'research/src/rq3_original',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('unknown/0 checks passed',result.stdout)
    def test_http_provider_mock_remains_callable_after_complete_m1(self):
        mock=ExactMock()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                body=json.dumps(mock.send(payload)).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url='http://127.0.0.1:'+str(server.server_address[1])+'/v1/chat/completions'
        class HTTPTransport:
            def send(self,payload):
                request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=5) as response:return json.loads(response.read())
        try:
            result=self.engine.live('Give me an action plan without dates',transport=HTTPTransport(),memory_backend='LEXICAL',controls={'task_intent':'ORDINARY_ACTION_ADVICE'})
            self.assertEqual(result['core']['memory_calls'],1)
            self.assertEqual([r['role'] for r in result['provider_trace']],['RAG','MEMORY','B4_PLANNING','CANDIDATE','FINAL'])
            self.assertEqual(len(mock.payloads),5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    def test_gold_and_evaluation_sidecars_rejected(self):
        with self.assertRaises(CoreFailure):
            self.engine.call('prepare',query='Explain learning analytics',history=[{'role':'user','content':'question','gold':'forbidden'}])
    def test_task_source_projection_all_five_pages(self):
        seen=set()
        for task in tasks():
            if task['page'] in seen:continue
            source=self.engine.call('source',task_id=task['task_id'])
            self.assertEqual(set(source['primary']),{'current_query','current_page','dashboard_context','visible_conversation_history'})
            seen.add(task['page'])
        self.assertEqual(seen,{'Overview','Resources','Lecture','Debate','Reflection'})

if __name__=='__main__':unittest.main()
