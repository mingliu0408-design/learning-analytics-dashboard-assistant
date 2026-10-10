import copy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, sha, load, write_once, canonical
from utils.c4_rebuild.i1.schemas import CANDIDATE, FINAL, LOCAL_CANDIDATE, errors, strict_schema_check, final_errors
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3, ROLE_NAMES
from utils.c4_rebuild.i1.renderer import final_payload, candidate_payload
from utils.c4_rebuild.i1.durable import DurableRunner, StopRun, parse_response
from utils.c4_rebuild.i1.transport import TransportFailure, OpenAITransport
from utils.c4_rebuild.i1.policy import APPROVAL_SCHEMA, APPROVAL_VERSION, preflight
from utils.c4_rebuild.i1.worker import OfflineWorker
from utils.c4_rebuild.i1.memory import I1NativeM1, I1ResearchService, GENERIC
from utils.c4_rebuild.memory import MemoryBundle, m1_dependencies
from utils.c4_rebuild.language import purpose
from utils.c4_rebuild.planning import empty_envelope
from utils.c4_rebuild.service import ResearchService
from utils.c4_rebuild.contracts import Mode, Access
from research_followups.rq3_rebuild.i0_human_integration.fixtures import request, snapshot, memory_source, rag_source, SyntheticRouter
from research_followups.rq3_rebuild.i1_pilot_launch.mock_transport import MockTransport, MockClock, candidate
from utils.c4_rebuild.i1.human import project, dossier

CONFIG=load(HOME/'PILOT_CONFIGURATION_PROPOSED.json')
MANIFEST=load(HOME/'TASK_MANIFEST.json')


def plain_payload():
    return dict(model='gpt-4o-mini-2024-07-18',temperature=0,max_tokens=2048,stream=False,
        messages=[dict(role='user',content='{"accepted_plan":null}')],
        response_format=dict(type='json_schema',json_schema=dict(name='i1_final_v1',strict=True,schema=FINAL)))


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def native(self,index=0):
        m1_dependencies()
        m,s=memory_source(index,self.root)
        return I1NativeM1(m.databases,m.graph,m.source_events),s

    def spy_service(self,bit=True,access=True,cls=I1ResearchService):
        spy=SimpleNamespace(calls=[])
        def read(r,p):
            spy.calls.append((r.query,r.history,p))
            return MemoryBundle(empty_envelope(r),{}, {})
        spy.read=read
        r=request(Mode.S3_EVIDENCE_MEMORY,query='What preferences did I mention earlier?',
            access=Access(False,access,False,'explicit-test' if access else None))
        service=cls(enabled=True,snapshot=snapshot(),router=SyntheticRouter(False,bit,False),memory=spy)
        return r,service,spy

    def test_unknown_p3_yes_spy_preserves_query_history(self):
        r,s,m=self.spy_service();p=s.prepare(r)
        self.assertEqual(m.calls,[(r.query,r.history,GENERIC)])
        self.assertEqual(p['trace']['purpose_resolution']['original_purpose'],'UNKNOWN')

    def test_p3_no_never_reads(self):
        r,s,m=self.spy_service(bit=False);s.prepare(r);self.assertEqual(m.calls,[])

    def test_permission_no_never_reads(self):
        r,s,m=self.spy_service(access=False);s.prepare(r);self.assertEqual(m.calls,[])

    def test_i0_default_still_suppresses_unknown(self):
        r,s,m=self.spy_service(cls=ResearchService);s.prepare(r);self.assertEqual(m.calls,[])

    def test_s0_s1_never_route_or_read(self):
        for mode in (Mode.S0_PAGE_ONLY,Mode.S1_CROSS_PAGE_EVIDENCE):
            r,s,m=self.spy_service();s.prepare(replace(r,mode=mode));self.assertEqual(m.calls,[]);self.assertEqual(s.router.inputs,[])

    def test_unknown_native_relevant_seeds_no_links_readonly(self):
        m,_=self.native();r=request(query='What did I previously say about the quadratic formula?')
        self.assertEqual(purpose(r.query)['value'],'UNKNOWN')
        b=m.read(r,GENERIC)
        self.assertTrue(b.envelope['facts']);self.assertEqual(b.envelope['source_link_edges'],[])
        self.assertEqual(b.trace['added_facts'],[]);self.assertTrue(b.trace['readonly_state_unchanged'])
        self.assertEqual(b.trace['relation_expansion'],'UNSUPPORTED_PURPOSE')
        self.assertEqual(b.trace['generic_fallback'],'EXERCISED')

    def test_irrelevant_native_unknown_does_not_sweep(self):
        m,_=self.native();b=m.read(request(query='zzzxqv telescope galaxies'),GENERIC)
        self.assertEqual(b.envelope['facts'],[])
        self.assertEqual(b.trace['record_state'],'UNAVAILABLE_OR_NO_RELEVANT_SOURCE')

    def test_missing_source_binding_stays_unavailable(self):
        m,_=self.native();m.graph['nodes']={};m.graph['sha256']=sha({k:v for k,v in m.graph.items() if k!='sha256'})
        b=m.read(request(query='quadratic formula'),GENERIC)
        self.assertEqual(b.envelope['facts'],[])

    def test_stale_native_version_excluded(self):
        m,_=self.native()
        with sqlite3.connect(next(iter(m.databases.values()))) as db:
            db.execute('UPDATE memories SET version=version+1')
        self.assertEqual(m.read(request(query='quadratic formula study time'),GENERIC).envelope['facts'],[])

    def test_expired_native_excluded(self):
        m,_=self.native()
        with sqlite3.connect(next(iter(m.databases.values()))) as db:
            db.execute("UPDATE memories SET valid_to='2026-08-21T00:00:00.000000+00:00'")
        self.assertEqual(m.read(request(query='quadratic formula study time'),GENERIC).envelope['facts'],[])

    def test_consent_withdrawn_native_excluded(self):
        m,_=self.native()
        with sqlite3.connect(next(iter(m.databases.values()))) as db:
            db.execute("UPDATE memories SET consent_status='WITHDRAWN'")
        self.assertEqual(m.read(request(query='quadratic formula study time'),GENERIC).envelope['facts'],[])

    def test_ambiguous_plan_not_selected(self):
        m,_=self.native(11);b=m.read(request(query='What did my earlier plan say?'),GENERIC)
        self.assertEqual(b.trace['plan_state'],'AMBIGUOUS')
        self.assertIsNone(b.envelope['chosen_active_plan_id']);self.assertEqual(b.envelope['source_link_edges'],[])

    def test_known_purpose_original_body_equivalent(self):
        m,_=self.native();r=request(query='Remind me of my goal and suggest next steps without dates.')
        inherited=type(m).__mro__[1](m.databases,m.graph,m.source_events)
        self.assertEqual(m.read(r,'GOAL_RECALL').envelope,inherited.read(r,'GOAL_RECALL').envelope)
        from relations import PURPOSES
        self.assertNotIn(GENERIC,PURPOSES)

    def test_source_scope_invalid_before_router(self):
        r,s,m=self.spy_service()
        with self.assertRaises(ValueError):s.prepare(replace(r,scope=replace(r.scope,course_id='wrong-course')))
        self.assertEqual(s.router.inputs,[]);self.assertEqual(m.calls,[])


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)/'run'
        self.clock=MockClock()
        self.binding={'config':'test'}

    def runner(self,transport=None,config=None,resume=False,unknown=()):
        t=transport or MockTransport()
        r=DurableRunner(self.directory,config or CONFIG,self.binding,t,resume=resume,
            unknown_authorizations=unknown,clock=self.clock,sleep=self.clock.sleep)
        self.addCleanup(r.close)
        return r,t

    def test_reservation_exists_before_transport(self):
        def check(payload,raw,n):
            self.assertEqual(len(list((self.directory/'attempts').glob('*.start.json'))),n)
            return raw
        r,t=self.runner(MockTransport(check));self.assertEqual(r.perform('slot','FINAL',plain_payload())['status'],'ACCEPTED')

    def test_accepted_terminal_resume_never_repeats(self):
        r,t=self.runner();one=r.perform('slot','FINAL',plain_payload());r.close()
        r2,t2=self.runner(resume=True);self.assertEqual(r2.perform('slot','FINAL',plain_payload()),one)
        self.assertEqual(t2.requests,[])

    def test_schema_invalid_then_valid_two_attempts(self):
        def bad(payload,raw,n):
            if n==1:raw['choices'][0]['message']['content']='{}'
            return raw
        r,t=self.runner(MockTransport(bad));result=r.perform('slot','FINAL',plain_payload())
        self.assertEqual(result['status'],'ACCEPTED');self.assertEqual(len(t.requests),2)

    def test_permanent_schema_failure_terminal_preserved(self):
        def bad(payload,raw,n):raw['choices'][0]['message']['content']='{}';return raw
        r,t=self.runner(MockTransport(bad));result=r.perform('slot','FINAL',plain_payload())
        self.assertEqual(result['status'],'SCHEMA');self.assertEqual(len(t.requests),2)
        self.assertEqual(len(list((self.directory/'terminals').glob('*.json'))),1)

    def test_candidate_encoded_repair_two_total(self):
        worker=OfflineWorker();s=worker.call(dict(op='source',slot='I0-SYN-06'))
        p=worker.call(dict(op='prepare',slot='I0-SYN-06',mode='S5_FULL',primary_sha256=s['primary_sha256'],
            route=dict(rag_required=True,memory_required=True,planning_required=True,provider_identity='MOCK')))['prepared']
        def bad(payload,raw,n):
            if n==1:
                value=json.loads(raw['choices'][0]['message']['content']);value['actions'][0]['estimated_duration']['value']=999
                raw['choices'][0]['message']['content']=json.dumps(value)
            return raw
        def validate(v):
            x=worker.call(dict(op='check_candidate',bridge=p['planner']['bridge'],candidate=v))
            return x['issues'] if x['outcome']!='PASSED_ENCODED_CHECKS' else []
        c=CONFIG['generation_roles']['CANDIDATE'];r,t=self.runner(MockTransport(bad))
        result=r.perform('plan','CANDIDATE',candidate_payload(p,c),validate,
            lambda prev,issues:candidate_payload(p,c,prev,issues))
        self.assertEqual(result['status'],'ACCEPTED');self.assertEqual(len(t.requests),2)
        self.assertIn('concrete_checker_issues',t.requests[-1]['messages'][-1]['content'])

    def test_refusal_no_retry(self):
        def refusal(payload,raw,n):raw['choices'][0]['message']['refusal']='Mock refusal';return raw
        r,t=self.runner(MockTransport(refusal));self.assertEqual(r.perform('slot','FINAL',plain_payload())['status'],'REFUSAL')
        self.assertEqual(len(t.requests),1)

    def test_truncation_has_finite_retry(self):
        def trunc(payload,raw,n):raw['choices'][0]['finish_reason']='length';return raw
        r,t=self.runner(MockTransport(trunc));self.assertEqual(r.perform('slot','FINAL',plain_payload())['status'],'TRUNCATED')
        self.assertEqual(len(t.requests),2)

    def test_auth_billing_config_model_stop(self):
        for category in ('AUTH','BILLING','CONFIG','MODEL'):
            with self.subTest(category=category):
                self.directory=Path(self.tmp.name)/category
                class Failed(MockTransport):
                    def send(self,payload):self.requests.append(payload);raise TransportFailure(category,{'mock':True})
                r,t=self.runner(Failed())
                with self.assertRaises(StopRun):r.perform('slot','FINAL',plain_payload())
                self.assertEqual(len(t.requests),1);self.assertTrue((self.directory/'STOP.json').exists())
                with self.assertRaisesRegex(StopRun,'FATAL_RUN_STOP'):r.perform('another','FINAL',plain_payload())
                self.assertEqual(len(t.requests),1);r.close()

    def test_returned_model_mismatch_stops(self):
        def wrong(p,raw,n):raw['model']='wrong';return raw
        r,t=self.runner(MockTransport(wrong))
        with self.assertRaisesRegex(StopRun,'RETURNED_MODEL'):r.perform('slot','FINAL',plain_payload())
        self.assertEqual(len(t.requests),1)

    def test_unknown_completion_requires_explicit_resume(self):
        class Unknown(MockTransport):
            def send(self,payload):self.requests.append(payload);raise TransportFailure('UNKNOWN_COMPLETION')
        r,t=self.runner(Unknown())
        with self.assertRaisesRegex(StopRun,'UNKNOWN_COMPLETION'):r.perform('slot','FINAL',plain_payload())
        r.close();r2,t2=self.runner(resume=True)
        with self.assertRaisesRegex(StopRun,'UNKNOWN_COMPLETION'):r2.perform('slot','FINAL',plain_payload())
        self.assertEqual(t2.requests,[]);r2.close()
        aid=sha('slot')+'.1';r3,t3=self.runner(resume=True,unknown=(aid,))
        self.assertEqual(r3.perform('slot','FINAL',plain_payload())['status'],'ACCEPTED');self.assertEqual(len(t3.requests),1)
        old=load(self.directory/'attempts'/f'{aid}.outcome.json');self.assertIsNone(old['usage'])

    def test_raw_received_before_crash_recovered_without_send(self):
        r,t=self.runner();p=plain_payload();start=r.reserve('slot','FINAL',1,p,sha(p))
        write_once(self.directory/'attempts'/f"{start['attempt_id']}.raw.json",t.send(p));r.close()
        r2,t2=self.runner(resume=True);self.assertEqual(r2.perform('slot','FINAL',p)['status'],'ACCEPTED')
        self.assertEqual(t2.requests,[])

    def test_no_raw_inflight_never_repeated_automatically(self):
        r,t=self.runner();p=plain_payload();r.reserve('slot','FINAL',1,p,sha(p));r.close()
        r2,t2=self.runner(resume=True)
        with self.assertRaisesRegex(StopRun,'UNKNOWN_IN_FLIGHT'):r2.perform('slot','FINAL',p)
        self.assertEqual(t2.requests,[])

    def test_role_ceiling_before_transport(self):
        c=copy.deepcopy(CONFIG);c['initial_slot_ceilings']['FINAL']=1
        r,t=self.runner(config=c);r.perform('a','FINAL',plain_payload())
        with self.assertRaisesRegex(StopRun,'ROLE_LOGICAL'):r.perform('b','FINAL',plain_payload())
        self.assertEqual(len(t.requests),1)

    def test_total_ceiling_before_transport(self):
        c=copy.deepcopy(CONFIG);c['aggregate_attempt_ceiling']=0;r,t=self.runner(config=c)
        with self.assertRaisesRegex(StopRun,'AGGREGATE'):r.perform('a','FINAL',plain_payload())
        self.assertEqual(t.requests,[])

    def test_money_headroom_before_transport(self):
        c=copy.deepcopy(CONFIG);c['proposed_money_ceiling_usd']=0;r,t=self.runner(config=c)
        with self.assertRaisesRegex(StopRun,'MONEY'):r.perform('a','FINAL',plain_payload())
        self.assertEqual(t.requests,[])

    def test_input_bound_before_transport(self):
        c=copy.deepcopy(CONFIG);c['max_request_input_byte_units']=1;r,t=self.runner(config=c)
        with self.assertRaisesRegex(StopRun,'INPUT_BOUND'):r.perform('a','FINAL',plain_payload())
        self.assertEqual(t.requests,[])

    def test_monotonic_pacing_ignores_utc_artifact(self):
        r,t=self.runner()
        with patch('utils.c4_rebuild.i1.durable.utc',side_effect=['2026-09-07T00:00:00+00:00']*20):
            r.perform('a','FINAL',plain_payload());r.perform('b','FINAL',plain_payload())
        starts=[load(p) for p in (self.directory/'attempts').glob('*.start.json')]
        self.assertGreaterEqual(abs(starts[0]['monotonic_start']-starts[1]['monotonic_start']),2)
        self.assertEqual(len(list((self.directory/'terminals').glob('*.json'))),2)

    def test_terminal_tamper_detected(self):
        r,t=self.runner();r.perform('a','FINAL',plain_payload());raw=next((self.directory/'attempts').glob('*.raw.json'))
        raw.write_text('{}')
        with self.assertRaisesRegex(StopRun,'RAW_RECEIPT'):r.perform('a','FINAL',plain_payload())

    def test_cache_input_change_rejected(self):
        r,t=self.runner();p=plain_payload();r.perform('a','FINAL',p);p['messages'][0]['content']='changed'
        with self.assertRaisesRegex(StopRun,'BINDING'):r.perform('a','FINAL',p)
        self.assertEqual(len(t.requests),1)


class ContractTests(unittest.TestCase):
    def test_strict_shapes_closed_required_nullable(self):
        strict_schema_check(CANDIDATE);strict_schema_check(FINAL)
        bad=copy.deepcopy(FINAL);bad['properties']['plan_fields']={'type':'object'}
        with self.assertRaises(ValueError):strict_schema_check(bad)

    def test_structural_equivalence_and_local_constraints(self):
        body={'current_query':'advice','encoded_planning_fields':{'hard_constraints':{'required_evidence_ids':[], 'budget':{'required':False,'minutes':None}}}}
        v=candidate(body);self.assertEqual(errors(v,CANDIDATE),[]);self.assertEqual(errors(v,LOCAL_CANDIDATE),[])
        v['actions'][0]['estimated_duration']['value']=-5
        self.assertEqual(errors(v,CANDIDATE),[]);self.assertTrue(errors(v,LOCAL_CANDIDATE))

    def test_json_duplicate_keys_rejected(self):
        p=plain_payload();r=MockTransport().send(p);r['choices'][0]['message']['content']='{"answer":"a","answer":"b"}'
        self.assertEqual(parse_response(r,p,lambda v:[])[0],'INVALID_JSON')

    def test_no_generic_evidence_prose_or_rationale_cap(self):
        v=dict(answer='Evidence: '+('context '*2000),cited_evidence_ids=[],plan_fields=None)
        self.assertEqual(final_errors(v,[],None),[])

    def test_no_provider_human_mean_field(self):
        self.assertEqual(set(FINAL['properties']),{'answer','cited_evidence_ids','plan_fields'})

    def test_final_plan_field_copy_not_semantic_proof(self):
        v=dict(answer='unsupported prose',cited_evidence_ids=[],plan_fields=None)
        self.assertEqual(final_errors(v,[],None),[])  # Explicitly no semantic certification.

    def test_frozen_role_caps_and_original_message_builder(self):
        f=FrozenP3();self.assertEqual([f.roles[r]['max_output_tokens'] for r in ROLE_NAMES],[32,32,64])
        p=MANIFEST['sources'][0]['source']['primary']
        for role in ROLE_NAMES:
            built=f.request(role,p)
            self.assertEqual(json.loads(built['messages'][-1]['content']),p)
            self.assertEqual(built['messages'][0]['content'],f.roles[role]['prompt'])
            self.assertEqual(len(built['messages']),2+len(f.roles[role]['examples'])*2)

    def test_same_input_stub_slots_not_forced_apart(self):
        groups=[g['task_ids'] for g in MANIFEST['same_input_groups']]
        self.assertIn(['I0-SYN-04','I0-SYN-05','I0-SYN-11'],groups)
        self.assertEqual(len(groups),8)

    def test_p3_no_sidecar_field(self):
        f=FrozenP3();p=copy.deepcopy(MANIFEST['sources'][0]['source']['primary']);p['expected']='sentinel'
        with self.assertRaises(ValueError):f.request('RAG',p)

    def test_recreated_native_state_has_stable_resume_identity(self):
        w=OfflineWorker();source=w.call(dict(op='source',slot='I0-SYN-06'))
        message=dict(op='prepare',slot='I0-SYN-06',mode='S5_FULL',primary_sha256=source['primary_sha256'],
            route=dict(rag_required=True,memory_required=True,planning_required=True,provider_identity='MOCK'))
        self.assertEqual(w.call(message),w.call(message))

    def test_hybrid_worker_not_constructed_when_mode_or_p3_denies(self):
        from research_followups.rq3_rebuild.i1_pilot_launch.offline_worker import handle
        source=handle(dict(op='source',slot='I0-SYN-06'))
        for mode,route in [('S0_PAGE_ONLY',None),('S3_EVIDENCE_MEMORY',dict(rag_required=False,memory_required=False,planning_required=False,provider_identity='MOCK'))]:
            with patch('utils.c4_rebuild.i1.native_backend.I1LocalBackend',side_effect=AssertionError('ENCODER')):
                handle(dict(op='prepare',slot='I0-SYN-06',mode=mode,primary_sha256=source['primary_sha256'],
                    route=route,memory_backend='M1_HYBRID_LINKS_DEV'))

    def test_local_hybrid_stdio_transport_mock_no_model_construction(self):
        import io
        from utils.c4_rebuild.i1.native_backend import I1LocalBackend
        process=SimpleNamespace(stdin=io.BytesIO(),stdout=io.BytesIO(),poll=lambda:0)
        texts=['synthetic source']
        with tempfile.TemporaryDirectory() as tmp:
            with patch('utils.c4_rebuild.i1.native_backend.subprocess.Popen',return_value=process) as popen:
                with patch.object(I1LocalBackend,'receive',side_effect=[
                    {'event':'ENCODE_VERIFIED','identity':{'implementation':'MOCK'}},
                    {'input_sha256':sha(texts),'vectors':[[1.0,0.0]]}]):
                    b=I1LocalBackend(Path(tmp));self.assertEqual(b.encode(texts),[[1.0,0.0]])
                    self.assertEqual(b.inputs,[{'input_sha256':sha(texts),'count':1}]);b.close()
                env=popen.call_args.kwargs['env']
                self.assertEqual(env['XDG_CACHE_HOME'],str(Path(tmp)/'cache'))
                self.assertNotIn('OPENAI_API_KEY',env)

    def test_worker_network_guard_isolated_from_parent(self):
        before=socket.socket.connect;OfflineWorker().call(dict(op='source',slot='I0-SYN-01'))
        self.assertIs(socket.socket.connect,before)

    def test_missing_route_is_failure_not_all_no(self):
        w=OfflineWorker();s=w.call(dict(op='source',slot='I0-SYN-06'))
        p=w.call(dict(op='prepare',slot='I0-SYN-06',mode='S5_FULL',primary_sha256=s['primary_sha256'],route=None))['prepared']
        self.assertIsNone(p['trace']['route']);self.assertIn('P3_ROUTE_UNAVAILABLE',p['final_request']['clarification_required'])
        self.assertIsNone(p['planner'])

    def test_missing_schedule_not_filled_from_gold(self):
        w=OfflineWorker();s=w.call(dict(op='source',slot='I0-SYN-09'))
        p=w.call(dict(op='prepare',slot='I0-SYN-09',mode='S5_FULL',primary_sha256=s['primary_sha256'],
            route=dict(rag_required=True,memory_required=True,planning_required=True,provider_identity='MOCK')))['prepared']
        self.assertEqual(p['planner']['status'],'NEEDS_INFORMATION');self.assertIsNone(p['planner']['request'])
        self.assertIn('MISSING_TIMEZONE',p['final_request']['clarification_required'])

    def test_renderer_excludes_admin_paths_and_sentinels(self):
        paths=list((HOME/'receipts/mock_attempt_01/stages').glob('*.json'))
        stage=next(load(p) for p in paths if load(p)['stage']=='C_MODULE_REBUILD')
        prepared=stage['output']['prepared'];prepared['final_request'].update(case_id='ADMIN_SENTINEL',phase='ADMIN_SENTINEL')
        prepared['trace']['source_path']='/private/secret-source'
        text=canonical(final_payload(prepared,CONFIG['generation_roles']['FINAL'])).decode()
        for forbidden in ('ADMIN_SENTINEL','/private/secret-source','execution_authorised','No plan has been generated','CANDIDATE_PENDING_DISABLED_TRANSPORT'):
            self.assertNotIn(forbidden,text)

    def test_human_identical_dossier_across_modes_and_no_answer(self):
        common=dossier(MANIFEST['sources'][0]['source'],dict(source_review_approved=False,reference='EVALUATOR_SENTINEL',source_ids=[],version='DRAFT'))
        packet,mapping=project(common,CONFIG['modes'])
        self.assertEqual(len({sha({k:v for k,v in x.items() if k not in ('item_id','response')}) for x in packet['items']}),1)
        self.assertTrue(all(x['response'] is None for x in packet['items']));self.assertEqual(packet['ratings'],[])
        self.assertNotIn('mode',packet['items'][0]);self.assertEqual(len(mapping),6)

    def test_artificial_freezes_cannot_be_real_rating_packet(self):
        f=load(HOME/'receipts/mock_attempt_01/MOCK_RESPONSE_FREEZES.json')['responses'][:6]
        common=dossier(MANIFEST['sources'][0]['source'],dict(source_review_approved=False,reference=None,source_ids=[],version='DRAFT'))
        with self.assertRaises(PermissionError):project(common,CONFIG['modes'],f)

    def test_openai_client_created_only_when_explicitly_approved(self):
        with patch.dict(sys.modules,{'openai':SimpleNamespace(OpenAI=lambda **kw: (_ for _ in ()).throw(AssertionError('CLIENT')))}):
            with self.assertRaises(PermissionError):OpenAITransport(approved=False,timeout=30)

    def test_mock_sdk_zero_retry_and_finite_timeout(self):
        seen=[];fake=SimpleNamespace(close=lambda:None)
        def factory(**kw):seen.append(kw);return fake
        with patch.dict(sys.modules,{'openai':SimpleNamespace(OpenAI=factory)}):
            t=OpenAITransport(approved=True,timeout=30);t.close()
        self.assertEqual(seen[0]['max_retries'],0);self.assertEqual(seen[0]['timeout'],30)

    def test_sdk_error_categories_without_network(self):
        class Error(Exception):
            def __init__(self,status,body=None):self.status_code=status;self.body=body;self.request_id='mock'
        for status,body,expected in [(401,None,'AUTH'),(403,None,'AUTH'),(400,None,'CONFIG'),(404,None,'MODEL'),
            (429,{'code':'insufficient_quota'},'BILLING'),(429,None,'RATE_LIMIT'),(500,None,'UNKNOWN_COMPLETION')]:
            def create(**kw):raise Error(status,body)
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with patch.dict(sys.modules,{'openai':SimpleNamespace(OpenAI=lambda **kw:client)}):
                transport=OpenAITransport(approved=True,timeout=30)
                with self.assertRaises(TransportFailure) as c:transport.send(plain_payload())
                self.assertEqual(c.exception.category,expected)


if __name__=='__main__':unittest.main(verbosity=2)
