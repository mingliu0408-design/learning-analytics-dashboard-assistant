#!/usr/bin/env python3
"""Offline L2 contracts on author implementation and invented fixtures, never study outputs."""
from pathlib import Path
import hashlib
import json
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/rq3_original'
sys.path.insert(0, str(SOURCE))
sys.dont_write_bytecode = True

def no_network(event, args):
    if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind','socket.sendto'}:
        raise RuntimeError('RELEASE_OFFLINE_CHECK_NETWORK_FORBIDDEN')
sys.addaudithook(no_network)

from utils.c4_dashboard_scoped import PAGES, DOMAINS
from utils.c4_dashboard_scoped.scope import Scope, Snapshot, SourceSpec, Coverage, ScopeError
from utils.c4_dashboard_scoped.aggregate import aggregate
from utils.c4_rebuild.contracts import Request, Access, Mode, POLICIES, reject_sidecars
from utils.c4_rebuild.service import ResearchService
from utils.c4_real_contracts import P3CapabilityRoute
from utils.c4_rebuild.rag import R0OnExplicitCorpus
from utils.course_material_retriever import CourseChunk
from utils.c4_memory.c4_memory_store import C4MemoryStore
from utils.c4_memory.c4_memory_writer import C4MemoryWriter
from utils.c4_memory.c4_memory_retriever import C4MemoryRetriever
from utils.c4_rebuild.memory import m1_dependencies
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3
from utils.c4_rebuild.i1.schemas import errors, strict_schema_check

FIXTURE = json.loads((ROOT/'examples/synthetic/rq3/fixture.json').read_text())

class Contracts(unittest.TestCase):
    def snapshot(self):
        scope=Scope(**FIXTURE['scope'])
        rows=tuple(FIXTURE['rows'])
        spec=SourceSpec(columns=tuple(rows[0]), course_column='course', observation='timestamp', time_column='at',
            coverage=(Coverage((scope.learner_id,),scope.course_id,scope.start,scope.end,
                ('resource_views',),'SYNTHETIC_COMPLETE_OBSERVATION'),))
        snap=Snapshot(scope.snapshot,{'moodle':rows},{'moodle':spec},
            {scope.learner_id:(scope.course_id,)},origin='SYNTHETIC')
        return scope,snap

    def test_five_pages_scope_and_unknown(self):
        scope,snap=self.snapshot(); result=aggregate(snap,scope)
        facts={(f.domain,f.metric):f for f in result.facts}
        self.assertEqual(facts['Resources','resource_views'].value,1)
        self.assertEqual(facts['Resources','resource_views'].spans,(2,))
        self.assertIsNone(facts['Lecture','video_views'].value)
        self.assertEqual(facts['Lecture','video_views'].status,'SOURCE_UNAVAILABLE')
        for page in PAGES:
            view=result.visible(page)
            self.assertEqual(set(view['activity']),set(DOMAINS if page=='Overview' else (page,)))
        with self.assertRaises(ScopeError):
            snap.validate(Scope(**{**FIXTURE['scope'],'learner_id':'not-authorized-synthetic-learner'}))

    def test_runtime_rejects_evaluation_sidecars(self):
        for name in ('gold','ratings','expected_fact_ids','family_id'):
            with self.assertRaises(ValueError): reject_sidecars({'nested':[{name:None}]})

    def test_six_mode_gate_and_no_provider(self):
        scope,snap=self.snapshot()
        class FixedSyntheticRoute:
            calls=0
            def route(self, primary):
                self.calls+=1
                self.seen=primary.to_payload()
                return P3CapabilityRoute(False,False,True,provider_identity='SYNTHETIC_FIXED_TEST_ROUTE')
        for mode in Mode:
            router=FixedSyntheticRoute()
            req=Request(scope,'What should I do next to review these resources?','Resources',FIXTURE['as_of'],
                'synthetic-session',mode,'WARN_SNAPSHOT_ONLY',access=Access(False,False,True,'SYNTHETIC_TEST_ONLY'),
                task_intent='ORDINARY_ACTION_ADVICE',visible_controls='SYNTHETIC_VISIBLE_CONTROL')
            prepared=ResearchService(enabled=True,snapshot=snap,router=router).prepare(req)
            self.assertEqual(prepared['trace']['generation_calls'],0)
            self.assertEqual(router.calls,0 if mode.value.startswith(('S0','S1')) else 1)
            self.assertEqual(prepared['planner'] is not None, mode in (Mode.S4_EVIDENCE_PLANNING,Mode.S5_FULL))
            if router.calls:
                self.assertEqual(set(router.seen),{'current_query','current_page','dashboard_context','visible_conversation_history'})
            self.assertTrue(prepared['trace']['course_retention_complete'])

    def test_frozen_p3_payload_only(self):
        frozen=FrozenP3()
        primary=dict(current_query='Summarize my synthetic activity.',current_page='Overview',
                     dashboard_context='Synthetic activity example.',visible_conversation_history=[])
        for role in ('RAG','MEMORY','B4_PLANNING'):
            wire=frozen.request(role,primary)
            self.assertEqual(wire['model'],'gpt-4o-mini-2024-07-18')
            self.assertEqual(wire['temperature'],0)
            self.assertTrue(frozen.roles[role]['examples'])
        with self.assertRaises(ValueError): frozen.request('RAG',{**primary,'ratings':[]})

    def test_actual_r0_single_gate_and_explicit_corpus(self):
        chunk=CourseChunk(chunk_id='synthetic-course-span',source_file='synthetic-workshop.txt',
            source_type='weekly_page',title='Synthetic algebra workshop',text=FIXTURE['course_text'],week='1')
        scorer=R0OnExplicitCorpus([chunk])
        absent=scorer.retrieve('Week 1 algebra examples','Resources',[],retrieval_enabled=False,upstream_authorised=True)
        self.assertEqual(len(absent.selected_chunks),0)
        present=scorer.retrieve('Week 1 algebra examples','Resources',[],upstream_authorised=True)
        self.assertEqual(present.selected_chunks[0].chunk_id,'synthetic-course-span')
        self.assertEqual(present.implementation_id,'C4_RAG_R0_LEXICAL')
        self.assertIsNone(present.selected_chunks[0].dense_score)

    def test_memory_persistence_readonly_identity_visible_history(self):
        now=FIXTURE['as_of']; text=FIXTURE['memory_text']
        with tempfile.TemporaryDirectory(prefix='lad-rq3-synthetic-') as td:
            db=Path(td)/'memory.sqlite'
            with C4MemoryStore(db,clock=lambda:now) as store:
                writer=C4MemoryWriter(store)
                candidate=dict(operation='ADD',memory_type='GOAL',content=text,target_memory_id=None,
                    confidence=1.0,evidence_span=text)
                written=writer.apply_candidate(student_id='synthetic-learner',source_session_id='synthetic-session',
                    source_turn_id='synthetic-turn',source_text=text,candidate=candidate,event_at=now,valid_from=now)
                self.assertTrue(written.accepted)
                rejected=writer.apply_candidate(student_id='synthetic-learner',source_session_id='synthetic-session',
                    source_turn_id='synthetic-proposal',source_text=text,candidate=candidate,
                    source_role='ASSISTANT',claim_basis='ASSISTANT_ADVICE',event_at=now,valid_from=now)
                self.assertFalse(rejected.accepted)
            before=hashlib.sha256(db.read_bytes()).hexdigest()
            _,_,ReadOnlyStore=m1_dependencies()
            with ReadOnlyStore(db,clock=lambda:now) as store:
                retriever=C4MemoryRetriever(store,clock=lambda:now)
                selected=retriever.retrieve('synthetic-learner','synthetic algebra examples',[],at=now)
                self.assertTrue(selected.selected)
                self.assertEqual(len(retriever.retrieve('other-synthetic-learner','synthetic algebra',[],at=now).selected),0)
                repeated=retriever.retrieve('synthetic-learner','synthetic algebra',[{'role':'user','content':text}],at=now)
                self.assertEqual(len(repeated.selected),0)
            self.assertEqual(before,hashlib.sha256(db.read_bytes()).hexdigest())

    def test_typed_planner_schema_and_actual_final_citation_boundary(self):
        sys.path.insert(0,str(SOURCE/'experiments/rq3_original25_plus_review_r1'))
        import adapter
        adapter.interfaces.typed_planner()
        import typed_v1
        ordinary=typed_v1.schemas(typed_v1.ORDINARY)
        self.assertTrue(ordinary)
        self.assertTrue(adapter.interfaces.final_issues({'answer':'Synthetic answer.','cited_evidence_ids':['not-retained']},['retained']))
        self.assertFalse(adapter.interfaces.final_issues({'answer':'Synthetic answer.','cited_evidence_ids':[]},['retained']))
        self.assertEqual(adapter.interfaces.freeze_answer({'answer':'Synthetic answer.','cited_evidence_ids':[]},[],None)['semantic_support'],'NOT_CHECKED')

if __name__=='__main__':
    unittest.main(verbosity=2)
