"""Zero-network recovery behavior tests. No scientific implementation mirrors."""
from recovery import *
import socket
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


def payload():
    return dict(model='gpt-4o-mini-2024-07-18',temperature=0,max_tokens=2048,stream=False,
        messages=[{'role':'user','content':'ENGINEERING MOCK ONLY'}],
        response_format={'type':'json_schema','json_schema':{'name':'fixture','strict':True,
            'schema':{'type':'object','properties':{'answer':{'type':'string'}},
                      'required':['answer'],'additionalProperties':False}}})


def ok(text='ENGINEERING MOCK ONLY'):
    return dict(model='gpt-4o-mini-2024-07-18',id='mock',usage={'prompt_tokens':1,'completion_tokens':1},
        choices=[{'finish_reason':'stop','message':{'content':json.dumps({'answer':text})}}])


def network():
    return dict(_transport_failure=True,category='UNKNOWN_COMPLETION',detail={'exception_chain':[
        {'class':'openai.APIConnectionError','errno':None},{'class':'builtins.ConnectionError','errno':54}]},
        network_recovery_eligible=True,model=None,usage=None)


class Mock:
    kind='MOCK'
    def __init__(self,values):self.values=list(values);self.calls=[];self.rebuilds=0
    def send(self,p):self.calls.append(deepcopy(p));return self.values.pop(0)
    def rebuild(self):self.rebuilds+=1
    def close(self):pass


class Parent:
    identity='MOCK_PARENT'
    physical_calls=277
    budget_debit=.5533299
    def accepted(self,*args):return None
    def unknown_permission(self,logical,p):return {'historical_unknown_retained':True,'one_more_attempt':True}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.out=Path(self.tmp.name)/'run';self.now=0.;self.waits=[];self.parent=Parent()
        self.config=load(DATA/'CONFIG_PROPOSED.json')
        self.config.update(initial_slot_ceilings={'ROUTE':33,'CANDIDATE':22,'FINAL':66},aggregate_attempt_ceiling=241,
            proposed_money_ceiling_usd=10.,uncached_usd_per_million={'input':.15,'output':.6})
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('MOCK_NETWORK_FORBIDDEN'))
        self.guard.start();self.addCleanup(self.guard.stop)
    def sleep(self,n):self.waits.append(n);self.now+=n
    def runner(self,values,resume=False):
        self.mock=Mock(values)
        r=RecoveryRunner(self.out,self.config,{'test':'ENGINEERING_ONLY'},self.mock,self.parent,
            clock=lambda:self.now,sleep=self.sleep,resume=resume)
        self.addCleanup(r.close);return r
    def test_connection_then_success_same_payload_wait_and_rebuild(self):
        r=self.runner([network(),ok()]);v=r.perform('f','FINAL',payload())
        self.assertEqual(v['status'],'ACCEPTED');self.assertEqual(self.mock.calls,[payload(),payload()])
        self.assertEqual(self.waits,[10]);self.assertEqual(self.mock.rebuilds,1)
        self.assertEqual(load(self.out/'attempts'/f'{sha("f")}.1.outcome.json')['status'],'UNKNOWN_COMPLETION')
    def test_exhausted_missing_then_independent_success(self):
        r=self.runner([network(),network(),ok()]);v=r.perform('f','FINAL',payload())
        self.assertEqual(v['status'],'UNKNOWN_COMPLETION')
        self.assertEqual(r.perform('g','FINAL',payload())['status'],'ACCEPTED')
        self.assertEqual(len(self.mock.calls),3);self.assertEqual(r.failure_streak,0)
    def test_historical_unknown_has_only_one_attempt_even_if_invalid(self):
        bad=ok();bad['choices'][0]['message']['content']='invalid'
        r=self.runner([bad]);v=r.perform(CURRENT_UNKNOWN,'FINAL',payload())
        self.assertEqual(v['status'],'INVALID_JSON');self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(self.waits,[10]);self.assertEqual(self.mock.rebuilds,1)
    def test_three_consecutive_logical_connection_exhaustions_stop(self):
        r=self.runner([network() for _ in range(6)])
        for logical in ('f','g'):r.perform(logical,'FINAL',payload())
        with self.assertRaisesRegex(StopRun,'THREE_CONSECUTIVE'):r.perform('h','FINAL',payload())
        with self.assertRaisesRegex(StopRun,'FATAL_RUN_STOP'):r.perform('i','FINAL',payload())
        self.assertEqual(len(self.mock.calls),6)
    def test_accepted_restart_adds_no_calls(self):
        r=self.runner([ok()]);first=r.perform('f','FINAL',payload());r.close()
        r=self.runner([],resume=True);self.assertEqual(r.perform('f','FINAL',payload()),first)
        self.assertEqual(self.mock.calls,[])
    def test_same_attempt_name_in_two_runs_is_not_permission(self):
        r=self.runner([network(),network()]);r.perform(CURRENT_UNKNOWN,'FINAL',payload())
        self.assertEqual(len(self.mock.calls),1)
        self.assertEqual(load(self.out/'attempts'/f'{sha(CURRENT_UNKNOWN)}.1.outcome.json')['status'],'UNKNOWN_COMPLETION')
        self.assertEqual(r.perform(CURRENT_UNKNOWN,'FINAL',payload())['status'],'UNKNOWN_COMPLETION')
        self.assertEqual(len(self.mock.calls),1)
    def test_network_then_invalid_output_no_third_format_attempt(self):
        bad=ok();bad['choices'][0]['message']['content']='bad json'
        r=self.runner([network(),bad]);repair=unittest.mock.Mock(return_value=payload())
        self.assertEqual(r.perform('c','CANDIDATE',payload(),repair=repair)['status'],'INVALID_JSON')
        self.assertEqual(len(self.mock.calls),2);repair.assert_not_called()
    def test_candidate_repair_then_connection_no_third_network_attempt(self):
        bad=ok();bad['choices'][0]['message']['content']='bad json'
        r=self.runner([bad,network()]);fixed=payload();fixed['messages'][0]['content']='FROZEN REPAIR FIXTURE'
        res=r.perform('c','CANDIDATE',payload(),repair=lambda v,i:fixed)
        self.assertTrue(dependency_blocked(res));self.assertEqual(len(self.mock.calls),2)
        self.assertEqual(self.mock.calls[1],fixed);self.assertEqual(self.mock.rebuilds,0)
    def test_unknown_candidate_and_rate_limit_block_dependencies(self):
        for status in ('UNKNOWN_COMPLETION','RATE_LIMIT'):
            self.assertTrue(dependency_blocked({'status':status,'completion':'UNKNOWN' if status=='UNKNOWN_COMPLETION' else 'OBSERVED','returned_model':None}))
        self.assertFalse(dependency_blocked({'status':'ENCODED_CHECK','completion':'OBSERVED','returned_model':'gpt-4o-mini-2024-07-18'}))
    def test_budget_counts_history_and_unknown_reservations(self):
        r=self.runner([network(),ok()]);p=payload()
        one=((len(canonical(p))+256)*.15+2048*.6)/1e6
        self.parent.budget_debit=10-one*1.5
        with self.assertRaisesRegex(StopRun,'CUMULATIVE_MONEY'):r.perform('f','FINAL',p)
        self.assertEqual(len(self.mock.calls),1)
        self.assertGreater(debit([load(x) for x in (self.out/'attempts').glob('*.start.json')],self.out,{'input':.15,'output':.6}),0)
    def test_role_physical_and_logical_caps(self):
        r=self.runner([]);r.policy=deepcopy(r.policy);r.policy['physical_caps']['FINAL']=0
        with self.assertRaisesRegex(StopRun,'ROLE_PHYSICAL'):r.perform('f','FINAL',payload())
        self.assertEqual(self.mock.calls,[])
        r.policy['physical_caps']['FINAL']=131;r.config['initial_slot_ceilings']['FINAL']=0
        with self.assertRaisesRegex(StopRun,'ROLE_LOGICAL'):r.perform('f','FINAL',payload())
    def test_auth_and_nonnetwork_unknown_stop_immediately(self):
        raw=network();raw.update(category='AUTH',network_recovery_eligible=False)
        r=self.runner([raw])
        with self.assertRaisesRegex(StopRun,'UNRECOVERABLE_AUTH'):r.perform('f','FINAL',payload())
        self.assertEqual(self.mock.rebuilds,0);self.assertEqual(len(self.mock.calls),1)
    def test_safe_exception_chain_keeps_errno_without_credentials(self):
        from openai import APIConnectionError
        import httpx
        cause=OSError(54,'SECRET sk-FAKE https://u:password@proxy.invalid')
        exc=APIConnectionError(request=httpx.Request('POST','https://u:password@api.invalid'))
        exc.__cause__=cause
        s=safe_exception(exc,'TEST');encoded=json.dumps(s)
        self.assertEqual(s['exception_chain'][-1]['errno'],54)
        for secret in ('SECRET','password','sk-FAKE','proxy.invalid','api.invalid'):self.assertNotIn(secret,encoded)
    def test_permanent_certificate_and_permission_errors(self):
        for exc in (ssl.SSLCertVerificationError(1,'SECRET'),PermissionError(errno.EACCES,'SECRET')):
            self.assertTrue(safe_exception(exc,'TEST')['permanent_configuration_or_permission'])
    def test_transport_rebuild_exact_settings_and_safe_failure(self):
        from openai import APIConnectionError
        import httpx
        calls=[]
        class Client:
            def __init__(self,**kw):
                calls.append(kw);self.api_key=kw.get('api_key','sk-PRIVATE_FIXTURE');self.organization='org-fixture';self.project='proj-fixture'
                self.max_retries=kw['max_retries'];self.base_url='https://api.openai.com/v1/'
                self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.fail))
            def close(self):pass
            def fail(self,**kw):
                exc=APIConnectionError(request=httpx.Request('POST','https://api.openai.com/v1/chat/completions'))
                exc.__cause__=OSError(54,'sk-PRIVATE_FIXTURE')
                raise exc
        t=RecoveryTransport(approved=True,factory=Client)
        raw=t.send(payload());self.assertTrue(raw['network_recovery_eligible'])
        self.assertNotIn('sk-PRIVATE_FIXTURE',json.dumps(raw));t.rebuild()
        for name in ('max_retries','timeout','base_url'):self.assertEqual(calls[0][name],calls[1][name])
        self.assertEqual(calls[1]['api_key'],'sk-PRIVATE_FIXTURE')
    def test_actual_parent_two_layers_preserve_canonical_180_routes_candidates(self):
        from checkpoints import LayeredLedger
        p=LayeredLedger()
        self.assertEqual(len(p.index),269);self.assertEqual(p.physical_calls,277)
        self.assertAlmostEqual(p.budget_debit,.5533299)
        for logical in load(A1/'CONTINUATION_POLICY.json')['replacement_slots']:
            self.assertEqual(p.selected[logical+':FINAL'],'A1')
        old=p.payload('A1','original-06:S4_EVIDENCE_PLANNING:FINAL');changed=deepcopy(old);changed['max_tokens']+=1
        with self.assertRaisesRegex(StopRun,'ACCEPTED_PAYLOAD_CHANGED'):p.accepted('original-06:S4_EVIDENCE_PLANNING:FINAL','FINAL',changed)

    def pipeline(self,values,modes,candidate=False):
        import finish_remaining as entry
        from contextlib import ExitStack
        parent=Parent();parent.selected={};parent.index=[];parent.starts={};parent.bindings={}
        parent.module=lambda logical:None
        c=deepcopy(self.config);c['modes']=modes
        source={'primary':'mock source','primary_sha256':sha('mock source'),'clarification':False}
        route_values={'RAG':{'rag_required':False},'MEMORY':{'memory_required':False},'B4_PLANNING':{'planning_required':True}}
        def route_payload(role,primary):
            p=payload();key=next(iter(route_values[role]))
            p['response_format']['json_schema']['schema']={'type':'object','properties':{key:{'type':'boolean'}},'required':[key],'additionalProperties':False}
            return p
        prepared_modes=[]
        def prepare(t,b,mode,config,**kw):
            prepared_modes.append(mode)
            return dict(source=source,rag_calls=0,memory_calls=0,prepared=dict(
                planner={'status':'CANDIDATE_PENDING_DISABLED_TRANSPORT','bridge':{}} if candidate else None,
                final_request={'runtime_input':{'evidence':{'selected_evidence':[]}}},trace={'retained_evidence_ids':[]}))
        planner=SimpleNamespace(plan_kind=lambda bridge:{'kind':'ACTION'},candidate_payload=lambda *a,**kw:payload(),candidate_issues=lambda *a:[])
        transport=Mock(values)
        def make_runner(out,config,binding,transport,parent):
            r=RecoveryRunner(out,config,binding,transport,parent,clock=lambda:self.now,sleep=self.sleep)
            return r
        with ExitStack() as stack:
            for obj,name,value in [(entry,'git',lambda *a:''),(entry.legacy,'approve',lambda *a:(['fixture'],c)),
                (entry,'RecoveryTransport',lambda **kw:transport),(entry,'RecoveryRunner',make_runner),
                (entry.base,'source_for',lambda *a:source),(entry.interface,'prepare',prepare),
                (entry.interface,'planner_for',lambda *a:planner),(entry.base,'snapshot_for',lambda *a:None),
                (entry.base,'final_payload',lambda *a:payload()),(entry.base,'final_issues',lambda *a:[]),
                (entry.base,'freeze_answer',lambda value,*a:dict(answer=value['answer'],human_scores=[]))]:
                stack.enter_context(patch.object(obj,name,value))
            entry.execute(({'task_ids':['fixture']},[{'task_id':'fixture'}],{},c,{},parent,
                           SimpleNamespace(request=route_payload,identity='MOCK')),{},self.out)
        stages=[load(p) for p in (self.out/'stages').glob('*.json')]
        return prepared_modes,stages,transport
    def test_pipeline_failed_p3_skips_dependent_modes_runs_s0_s1(self):
        def route_ok(value):
            raw=ok();raw['choices'][0]['message']['content']=json.dumps(value);return raw
        values=[network(),network(),route_ok({'memory_required':False}),route_ok({'planning_required':True}),ok(),ok()]
        modes=['S0_PAGE_ONLY','S1_CROSS_PAGE_EVIDENCE','S2_EVIDENCE_RAG','S3_EVIDENCE_MEMORY','S4_EVIDENCE_PLANNING','S5_FULL']
        prepared,stages,t=self.pipeline(values,modes)
        self.assertEqual(prepared,modes[:2]);self.assertEqual(len(t.calls),6)
        self.assertEqual(sum(s['stage']=='DEPENDENCY_BLOCKED' for s in stages),4)
        self.assertEqual(sum(s['stage']=='RESPONSE' for s in stages),2)
    def test_pipeline_unknown_candidate_never_generates_fallback_final(self):
        def route_ok(value):
            raw=ok();raw['choices'][0]['message']['content']=json.dumps(value);return raw
        values=[route_ok({'rag_required':False}),route_ok({'memory_required':False}),route_ok({'planning_required':True}),
                network(),network(),ok(),ok()]
        prepared,stages,t=self.pipeline(values,['S4_EVIDENCE_PLANNING','S5_FULL'],candidate=True)
        self.assertEqual(len(t.calls),7)
        blocked=[s for s in stages if s['stage']=='DEPENDENCY_BLOCKED']
        responses=[s for s in stages if s['stage']=='RESPONSE']
        self.assertEqual([s['logical'] for s in blocked],['fixture:S4_EVIDENCE_PLANNING'])
        self.assertEqual([s['logical'] for s in responses],['fixture:S5_FULL'])


if __name__=='__main__':unittest.main(verbosity=2)
