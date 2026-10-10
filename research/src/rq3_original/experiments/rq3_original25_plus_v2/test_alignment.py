"""Offline contract tests, with target retrieval confined to an unrelated fixture."""
from v2_common import *
offline()
from copy import deepcopy
from unittest.mock import patch
import unittest
import tempfile
import sqlite3
import re
from adapter import (Mode,Pages,source_guard,prepare,source_for,SourceService,
    snapshot_for,request_for,ReceiptRouter,planner_for,final_payload)
from native_setup import map_fact
from utils.c4_rebuild.memory import m1_dependencies,clone_native_states
from utils.c4_memory.c4_memory_store import C4MemoryStore
from utils.c4_memory.c4_memory_writer import C4MemoryWriter

class AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks=lines(HERE/'runtime_tasks.jsonl');cls.by_id={t['task_id']:t for t in cls.tasks}
        cls.binding=read(HERE/'BINDINGS.json');cls.config=read(HERE/'CONFIG_PROPOSED.json')
        cls.rows=lines(HERE/'prepared_inputs/PREPARED_INPUTS_294.jsonl')
        cls.preview={(r['task_id'],r['mode']):r for r in cls.rows}
        cls.design=read(HERE/'family_design.json')['tasks']
        cls.pair={(r['family_id'],r['condition']):r['task_id'] for r in cls.design}
    def wire(self,family,condition,mode):return self.preview[(self.pair[family,condition],mode)]['final_wire_preview']
    def test_original_queries_and_50_messages_preserved(self):
        self.assertEqual([t['query'] for t in self.tasks[:25]],[t['query'] for t in lines(V1/'runtime_tasks.jsonl')[:25]])
        self.assertEqual((HERE/'legacy_only/source_messages_50.jsonl').read_bytes(),(V1/'legacy_only/source_messages_50.jsonl').read_bytes())
        self.assertEqual(len(lines(HERE/'legacy_only/source_messages_50.jsonl')),50)
    def test_v1_and_course_bytes_unchanged(self):
        for name,h in read(HERE/'audit/V1_PRESERVATION_BASELINE.json').items():
            if '_delivery' in Path(name).parts and not (ROOT/name).exists() and (ROOT/'GIT_LINEAGE.json').exists():continue
            self.assertEqual(sha((ROOT/name).read_bytes()),h,name)
        for p in (V1/'source_materials/course').rglob('*'):
            if p.is_file():self.assertEqual(p.read_bytes(),(HERE/'source_materials/course'/p.relative_to(V1/'source_materials/course')).read_bytes())
    def test_family_roster_unchanged(self):
        self.assertEqual(read(HERE/'family_design.json'),read(V1/'family_design.json'))
        self.assertEqual(len(self.design),24);self.assertEqual(len(set(r['family_id'] for r in self.design)),12)
        self.assertEqual(len(read(HERE/'RUN_MANIFEST.json')['task_ids']),41)
    def test_english_only_model_visible_natural_language(self):
        for r in self.rows:
            if r['task_id'].startswith('task-'):self.assertIsNone(re.search('[\u4e00-\u9fff]',canonical(r['final_wire_preview'])),r['task_id'])
        for p in (HERE/'source_materials/histories').glob('*.json'):
            for s in read(p)['sessions']:
                for m in s['messages']:self.assertIsNone(re.search('[\u4e00-\u9fff]',m['content']))
    def test_history_and_reference_spans(self):
        count=0
        for ref in lines(HERE/'evaluation_reference.jsonl'):
            for fact in ref['required_facts']+ref.get('optional_support',[]):
                for e in fact['evidence']:
                    if e['kind']=='HISTORY_SPAN':
                        v=pointer(read(HERE/e['path']),e['json_pointer']);self.assertEqual(v[e['char_start']:e['char_end']],e['quote']);count+=1
                    elif e['kind']=='STRUCTURED_SOURCE':self.assertEqual(pointer(read(HERE/e['path']),e['json_pointer']),e['value']);count+=1
                    elif e['kind']=='COURSE_SPAN':
                        chunk=next(x for x in lines(HERE/e['path']) if x['chunk_id']==e['chunk_id'])
                        self.assertEqual(chunk['text'][e['char_start']:e['char_end']],e['quote']);count+=1
        self.assertEqual(count,71)
    def test_native_reopen_and_clone_hashes(self):
        _,_,RO=m1_dependencies();from state_harness import snapshot
        for t in self.tasks:
            b=self.binding['native'][t['task_id']];paths=[b['database'],*b['mode_copies'].values()]
            self.assertEqual(len({checked(p).stat().st_ino for p in paths}),7)
            for entry in paths:
                p=checked(entry)
                with RO(p,clock=lambda:t['query_time']) as store:self.assertEqual(sha(snapshot(store)),b['logical_sha256'])
                with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as con:
                    with self.assertRaises(sqlite3.OperationalError):con.execute('CREATE TABLE forbidden(x)')
    def test_native_roles_versions_and_uncertainty(self):
        receipts=[read(HERE/'native_initial'/t['task_id']/'setup_receipt.json') for t in self.tasks]
        self.assertEqual(sum(r['operations'] for r in receipts),26)
        self.assertEqual(sum(r['accepted_writes'] for r in receipts),20)
        self.assertEqual(sum(r['unindexed_suggestions'] for r in receipts),6)
        for r in receipts:
            for op in r['receipts']:
                if op['source_operation']['source_role']=='assistant':self.assertFalse(op['writer_result']['accepted'])
        for cond in 'AB':
            rows=read(HERE/'native_initial'/self.pair['M01',cond]/'state_readable.json')['memories']
            historical=[r for r in rows if '18 minutes' in r['content']]
            self.assertEqual(len(historical),1);self.assertEqual(historical[0]['memory_type'],'PROGRESS_UPDATE')
        a=read(HERE/'native_initial'/self.pair['M02','A']/'state_readable.json')['memories']
        b=read(HERE/'native_initial'/self.pair['M02','B']/'state_readable.json')['memories']
        self.assertTrue(any('12 minutes' in r['content'] and r['status']=='ACTIVE' for r in a))
        prior=next(r for r in b if '12 minutes' in r['content']);current=next(r for r in b if '24 minutes' in r['content'])
        self.assertEqual(prior['status'],'SUPERSEDED');self.assertEqual(current['version'],2)
        self.assertEqual(current['supersedes_memory_id'],prior['memory_id']);self.assertNotIn('12',current['content'])
    def test_source_operations_literal_spans(self):
        for t in self.tasks:
            r=read(HERE/'native_initial'/t['task_id']/'setup_receipt.json')
            turns={s['turn_id']:s for s in r['source_runtime']['source_turns']}
            for op in r['source_runtime']['setup_operations']:
                a,b=op['source_span_chars'];self.assertEqual(turns[op['source_turn_id']]['content'][a:b],op['content'])
    def test_mode_visibility_and_no_hidden_histories(self):
        for t in self.tasks:
            primary=[]
            for mode in Mode:
                r=self.preview[t['task_id'],mode.value]
                primary.append(r['source']['primary'])
                self.assertEqual(r['rag_calls'],0);self.assertEqual(r['memory_calls'],0)
                rt=r['prepared']['final_request']['runtime_input'];self.assertEqual(rt['memory']['facts'],[])
                self.assertEqual(r['source']['primary']['visible_conversation_history'],t['visible_history'])
                facts=rt['evidence']['selected_evidence']
                if mode==Mode.S0_PAGE_ONLY:
                    self.assertEqual(len(facts),1)
                    self.assertEqual(set(facts[0]['content']['activity']),set(DOMAINS if t['page']=='Overview' else [t['page']]))
                self.assertNotIn('required_facts',canonical(r['final_wire_preview']))
            self.assertTrue(all(p==primary[0] for p in primary))
    def test_scope_perturbations_are_invariant(self):
        for f in ('E02','P03'):
            for m in Mode:self.assertEqual(self.wire(f,'A',m.value),self.wire(f,'B',m.value),(f,m))
        for m in Mode:
            a=self.preview[self.pair['M02','A'],m.value];b=self.preview[self.pair['M02','B'],m.value]
            self.assertEqual(a['source']['primary_sha256'],b['source']['primary_sha256'])
            self.assertNotEqual(a['prepared']['trace']['module_state_key'],b['prepared']['trace']['module_state_key'])
    def test_directional_page_change_and_zero_unknown(self):
        self.assertEqual(self.wire('E01','A','S0_PAGE_ONLY'),self.wire('E01','B','S0_PAGE_ONLY'))
        self.assertNotEqual(self.wire('E01','A','S1_CROSS_PAGE_EVIDENCE'),self.wire('E01','B','S1_CROSS_PAGE_EVIDENCE'))
        for cond,value in [('A',0),('B',None)]:
            t=self.by_id[self.pair['E03',cond]];p=snapshot_for(t,self.binding)
            self.assertEqual(p.pages['Reflection']['event_observations']['count'],value)
        t=self.by_id[self.pair['E02','B']];p=snapshot_for(t,self.binding)
        self.assertEqual(sum(v['event_observations']['count'] for v in p.pages.values()),5)
        self.assertEqual(len(p.excluded_pointers),3)
    def test_references_optional_and_humans_blank(self):
        for r in lines(HERE/'evaluation_reference.jsonl'):
            self.assertTrue(all(x is None for x in r['applicability_by_criterion'].values()))
            self.assertTrue(all(x is None for x in r['human_review'].values()))
            if r.get('family_id') in ('P01','P02'):
                self.assertNotIn('RAG',r['expected_capabilities_design_only'])
                self.assertTrue(r['optional_support']);self.assertEqual(r['required_for_minimal_answer'],r['required_facts'])
        for f in ('R03','M03','E03'):self.assertIn(self.pair[f,'B'],read(HERE/'RUN_MANIFEST.json')['task_ids'])
    def test_no_evaluation_read_and_injection_rejected(self):
        t=self.tasks[-1];expected=prepare(t,self.binding,'S0_PAGE_ONLY',self.config)
        old_read=Path.read_text
        def guarded(path,*args,**kwargs):
            if path.name in ('evaluation_reference.jsonl','family_design.json','translation_map.json') or 'human_review' in path.parts:
                raise AssertionError('EVALUATION_READ')
            return old_read(path,*args,**kwargs)
        with patch.object(Path,'read_text',guarded):self.assertEqual(prepare(t,self.binding,'S0_PAGE_ONLY',self.config),expected)
        for key in ('family_id','condition','required_facts','source_availability_truth','optional_support'):
            with self.assertRaises(ValueError):source_guard({'ordinary':{key:'poison'}})
    def test_new_target_activation_is_blocked(self):
        with self.assertRaises(PermissionError):prepare(self.tasks[-1],self.binding,'S5_FULL',self.config,route=dict(rag_required=True,memory_required=True,planning_required=True))
    def test_wire_contract_app_keeps_plan(self):
        from interfaces import FINAL_SCHEMA,freeze_answer
        self.assertEqual(set(FINAL_SCHEMA['properties']),{'answer','cited_evidence_ids'})
        plan={'engineering_fixture_only':True}
        self.assertEqual(freeze_answer({'answer':'Fixture answer','cited_evidence_ids':[]},[],plan)['accepted_plan'],plan)
    def test_planning_projection_on_independent_fixture(self):
        from adapter import TaskScope,build_request
        from utils.c4_rebuild.contracts import Request,Access
        from utils.c4_dashboard_scoped.scope import instant
        now='2026-08-31T12:00:00+00:00'
        scope=TaskScope('engineering-learner','engineering-course','2026-08-24T00:00:00+00:00','2026-08-31T00:00:00+00:00')
        class Fixture:
            origin='SYNTHETIC';accepted_pointers=['/records/0'];excluded_pointers=[]
            def validate_query(self,*args):pass
            def context(self,domains):
                return {'activity':{d:{'record_snapshots':{'records':[{'payload':{'available_minutes':23}}]}} for d in domains}}
            def overview(self):return self.context(DOMAINS)
        snap=Fixture();rows=[]
        for mode in Mode:
            req=Request(scope=scope,query='Suggest next steps for organising my study notes.',page='Resources',as_of=now,session_id='engineering-target',mode=mode,
                future_policy='WARN_SNAPSHOT_ONLY',access=Access(True,True,True,'ENGINEERING_FIXTURE'),source_version='engineering-v1')
            primary=build_request(snapshot=snap,scope=scope,query=req.query,page=req.page,now=instant(now),session_id=req.session_id).primary_input.to_payload()
            router=ReceiptRouter(primary,dict(rag_required=False,memory_required=False,planning_required=True,provider_identity='SYNTHETIC_ENGINEERING_FIXTURE'))
            p=SourceService(enabled=True,snapshot=snap,router=router).prepare(req)
            if mode in (Mode.S4_EVIDENCE_PLANNING,Mode.S5_FULL):
                self.assertTrue(p['trace']['activation']['planning'])
                self.assertEqual(p['planner']['bridge']['planner_input']['hard_constraints']['budget'],{'required':True,'minutes':23})
                self.assertEqual(p['planner']['status'],'CANDIDATE_PENDING_DISABLED_TRANSPORT')
                encoded=planner_for(snap).candidate_payload(p,self.config['generation_roles']['CANDIDATE'])
                self.assertEqual(encoded['model'],'gpt-4o-mini-2024-07-18')
            else:self.assertIsNone(p['planner'])
            rows.append(dict(mode=mode.value,activation=p['trace']['activation'],planner_status=p['planner']['status'] if p['planner'] else None))
        write(HERE/'audit/ENGINEERING_PLANNER.json',dict(fixture='independent-engineering-only',rows=rows,p3_model_calls=0,candidate_calls=0,final_calls=0))
    def test_native_retrieval_only_independent_engineering_fixture(self):
        from utils.c4_rebuild.i1.memory import I1NativeM1,GENERIC
        _,compile_graph,RO=m1_dependencies();from state_harness import snapshot
        now='2026-08-31T12:00:00+00:00';quote='I have 16 minutes available for study.'
        with tempfile.TemporaryDirectory(prefix='rq3-unrelated-native-fixture-') as td:
            db=Path(td)/'fixture.sqlite'
            op=dict(operation='ADD',memory_type='CONSTRAINT',content=quote,target_memory_id=None,confidence=1.0,evidence_span=quote)
            with C4MemoryStore(db,clock=lambda:now) as store:
                r=C4MemoryWriter(store).apply_candidate(student_id='engineering-learner',source_session_id='engineering-prior',source_turn_id='engineering-turn',source_text=quote,candidate=op,
                    consent_status='NOT_REQUIRED',event_at='2026-08-30T09:00:00+00:00',valid_from='2026-08-30T09:00:00+00:00')
                self.assertTrue(r.accepted);before=snapshot(store)
            turn=dict(turn_id='engineering-turn',session_id='engineering-prior',role='USER',content=quote,timestamp='2026-08-30T09:00:00+00:00',learner_id='engineering-learner',course_id='engineering-course')
            target=dict(learner_id='engineering-learner',course_id='engineering-course',session_id='engineering-target',as_of=now,horizon='fixture only',query='Recall my available study minutes.',page='Resources',visible_history=[],visibility_rule='Only supplied visible turns')
            setup=dict(source_turns=[turn],setup_operations=[dict(op,fact_id='fixture-fact',learner_id='engineering-learner',course_id='engineering-course',source_turn_id='engineering-turn',source_span_chars=[0,len(quote)],claim_basis='EXPLICIT_USER_STATEMENT')],relation_events=[],target=target)
            graph,rejects=compile_graph(setup,{'engineering-course':db},{'fixture-fact':r.memory_id});self.assertEqual(rejects,[])
            native=I1NativeM1({'engineering-course':db},graph,{'engineering-turn':turn},backend=None)
            env,trace=native.read_envelope(target,GENERIC)
            self.assertEqual([f['content'] for f in env.payload['facts']],[quote]);self.assertTrue(trace['readonly_state_unchanged'])
            with RO(db,clock=lambda:now) as store:self.assertEqual(snapshot(store),before)
            empty_target=dict(target,learner_id='different-engineering-learner')
            env2,_=native.read_envelope(empty_target,GENERIC);self.assertEqual(env2.payload['facts'],[])
            write(HERE/'audit/ENGINEERING_NATIVE_READ.json',dict(fixture='independent-engineering-only',queries=[target['query'],empty_target['query']],read_calls=2,
                lexical_only=True,target_dataset_queries=0,readonly_unchanged=True,cross_learner_excluded=True))

DOMAINS=('Resources','Lecture','Debate','Reflection')
if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(AlignmentTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    write(HERE/'audit/LOADED_TEST_CODE_DEPENDENCIES.json',{
        str(Path(mod.__file__).resolve().relative_to(ROOT)):sha(Path(mod.__file__).read_bytes())
        for mod in list(sys.modules.values()) if getattr(mod,'__file__',None)
        and str(Path(mod.__file__).resolve()).startswith(str(ROOT)+'/') and str(mod.__file__).endswith('.py')})
    write(HERE/'audit/V2_TESTS.json',dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        passed=result.wasSuccessful(),target_retrieval_calls=0,provider_calls=0,
        failure_details=[dict(test=str(t),traceback=s) for t,s in result.failures+result.errors]))
    raise SystemExit(0 if result.wasSuccessful() else 1)
