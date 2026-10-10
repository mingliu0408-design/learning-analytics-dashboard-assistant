import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from m1_common import OWNED, M0, object_sha, sha
from relations import compile_sidecar, read_bundle, POLICY
from author_linked_fixtures import seal
from state_harness import setup_episode, ReadOnlyStore, C4MemoryStore


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.cases={c['case_id']:c for c in json.loads((OWNED/'fixtures/linked_runtime_v1.json').read_text())}
        self.tmp=tempfile.TemporaryDirectory(dir=OWNED/'.runtime');self.addCleanup(self.tmp.cleanup)
        self.counter=0
    def prepare(self, name='SYN-M1-LINKED-01', change=None):
        case=copy.deepcopy(self.cases[name])
        if change:change(case)
        self.counter+=1
        dbs,aliases,receipts=setup_episode(case,Path(self.tmp.name)/str(self.counter))
        graph,rejected=compile_sidecar(case,dbs,aliases)
        return case,dbs,aliases,graph,rejected
    def read(self,p,expand=True):
        c,dbs,a,g,rejected=p
        envelope,trace=read_bundle(dbs,g,{'target':c['target'],'purpose':c['purpose']},expand=expand)
        inverse={v:k for k,v in a.items()}
        return envelope,trace,[inverse[x] for x in trace['kept_facts']]
    def event_rejection(self, mutate, reason):
        def change(c):
            mutate(c['relation_events'][0]);seal(c['relation_events'][0])
        p=self.prepare(change=change)
        self.assertEqual(p[4][0]['reason'],reason)
        self.assertEqual(p[3]['edges'],[])
    def test_constraint_seed_can_restore_explicit_goal(self):
        p=self.prepare();_,t,got=self.read(p)
        self.assertEqual([p[2]['f01-time']],t['original_seed_ids'])
        self.assertEqual(got,['f01-time','f01-goal'])
    def test_goal_seed_can_restore_explicit_constraint(self):
        p=self.prepare(change=lambda c:c['target'].update(query='quadratic formula'))
        _,t,got=self.read(p)
        self.assertEqual(t['original_seed_ids'],[p[2]['f01-goal']])
        self.assertEqual(set(got),{'f01-goal','f01-time'})
    def test_plan_seed_and_two_hop_links(self):
        p=self.prepare('SYN-M1-LINKED-13');_,t,got=self.read(p)
        self.assertEqual(set(got),{'f13-plan','f13-goal','f13-bound'})
        self.assertEqual(max(x['depth'] for x in t['candidate_facts']),2)
    def test_completion_action_chain(self):
        p=self.prepare('SYN-M1-ACCEPTED-ACTION-CHAIN');e,t,got=self.read(p)
        self.assertIn('f03-done',got);self.assertIn('accepted-action',got)
        self.assertEqual(e.payload['accepted_action_ids'],[p[2]['accepted-action']])
    def test_unlinked_same_learner_goal_is_not_swept_in(self):
        self.assertNotIn('unrelated-goal',self.read(self.prepare('SYN-M1-UNRELATED-GOAL'))[2])
    def test_ambiguous_plans_are_not_selected_using_hidden_answer(self):
        e,t,got=self.read(self.prepare('SYN-M1-AMBIGUOUS-PLANS'))
        self.assertEqual(t['expansion_status'],'AMBIGUOUS');self.assertEqual(t['added_facts'],[])
        self.assertIsNone(e.payload['chosen_active_plan_id'])
    def test_cross_course_link_rejected(self):
        p=self.prepare('SYN-M1-CROSS-COURSE')
        self.assertEqual(p[4][0]['reason'],'CROSS_LEARNER_OR_COURSE')
        self.assertNotIn('foreign-goal',self.read(p)[2])
    def test_cross_learner_link_rejected(self):
        p=self.prepare('SYN-M1-CROSS-LEARNER')
        self.assertEqual(p[4][0]['reason'],'CROSS_LEARNER_OR_COURSE')
        self.assertNotIn('foreign-goal',self.read(p)[2])
    def test_expired_node_excluded(self):
        _,t,got=self.read(self.prepare('SYN-M1-EXPIRED-NODE'))
        self.assertEqual(got,['f01-time']);self.assertIn('EXPIRED',[e['reason'] for e in t['exclusions']])
    def test_deleted_node_not_reconstructed_from_provenance(self):
        e,t,got=self.read(self.prepare('SYN-M1-DELETED-NODE'))
        self.assertEqual(got,['f01-time'])
        self.assertNotIn('quadratic formula',e.canonical_json)
    def test_visible_linked_fact_not_duplicated(self):
        _,t,got=self.read(self.prepare('SYN-M1-VISIBLE-NODE'))
        self.assertEqual(got,['f01-time']);self.assertIn('VISIBLE_DUPLICATE',[x['reason'] for x in t['exclusions']])
    def test_no_seed_does_not_activate_history_walk(self):
        _,t,got=self.read(self.prepare('SYN-M1-NO-SEED'))
        self.assertEqual(got,[]);self.assertEqual(t['traversed_edges'],[])
    def test_missing_source_endpoint_rejected(self):
        p=self.prepare('SYN-M1-SOURCE-MISSING')
        self.assertEqual(p[4][0]['reason'],'MISSING_ENDPOINT')
        self.assertEqual(self.read(p)[2],['f01-time'])
    def test_completion_correction_never_revives_old_completion(self):
        e,t,got=self.read(self.prepare('SYN-M1-COMPLETION-CORRECTION'))
        self.assertNotIn('f03-done',got);self.assertEqual(e.payload['completed_action_ids'],[])
        self.assertIn('SUPERSEDED',[x['reason'] for x in t['exclusions']])
    def test_withdrawn_relation_not_followed(self):
        _,t,got=self.read(self.prepare('SYN-M1-WITHDRAWN-EDGE'))
        self.assertEqual(got,['f01-time'])
    def test_non_supporting_statement_does_not_authorize_edge(self):
        p=self.prepare('SYN-M1-UNSUPPORTED-LINK')
        self.assertEqual(p[4][0]['reason'],'RELATION_NOT_IN_SOURCE')
    def test_budget_leaves_reported_missing_facts(self):
        _,t,got=self.read(self.prepare('SYN-M1-BUDGET-OMISSION'))
        self.assertLessEqual(len(t['added_facts']),4);self.assertLessEqual(len(got),9)
        self.assertLess(len(got),9);self.assertTrue(t['omitted_facts'])
        self.assertLessEqual(len(t['traversed_edges']),12)
    def test_source_hash_mismatch_rejected(self):
        p=self.prepare(change=lambda c:c['relation_events'][0].update(content='tampered'))
        self.assertEqual(p[4][0]['reason'],'SOURCE_HASH_MISMATCH')
    def test_future_source_rejected(self):
        self.event_rejection(lambda e:e.update(timestamp='2026-08-21T00:00:00+00:00'),'RELATION_NOT_BEFORE_TARGET')
    def test_ambiguous_endpoint_rejected(self):
        self.event_rejection(lambda e:e['annotation'].update(to_fact=['f01-goal']),'AMBIGUOUS_ENDPOINT')
    def test_system_inference_not_accepted_as_relation(self):
        self.event_rejection(lambda e:e.update(role='ASSISTANT'),'UNSUPPORTED_RELATION_ORIGIN')
    def test_unknown_relation_fields_rejected(self):
        self.event_rejection(lambda e:e.update(arbitrary='extra'),'RELATION_EVENT_SCHEMA')
    def test_native_disable_after_graph_build_is_rechecked(self):
        p=self.prepare();c,dbs,a,g,_=p
        with C4MemoryStore(dbs[c['target']['course_id']]) as s:s.set_memory_enabled(c['target']['learner_id'],False)
        self.assertEqual(self.read(p)[2],[])
    def test_consent_withdrawal_after_graph_build_is_rechecked(self):
        p=self.prepare();c,dbs,a,g,_=p
        with C4MemoryStore(dbs[c['target']['course_id']]) as s:
            s._connection.execute("UPDATE memories SET consent_status='WITHDRAWN' WHERE memory_id=?",(a['f01-goal'],))
        self.assertEqual(self.read(p)[2],['f01-time'])
    def test_source_event_missing_after_setup_is_excluded(self):
        p=self.prepare();g=p[3];g['source_events']={};g['sha256']=object_sha({k:v for k,v in g.items() if k!='sha256'})
        _,t,got=self.read(p)
        self.assertEqual(got,['f01-time']);self.assertIn('RELATION_SOURCE_MISSING',[x['reason'] for x in t['exclusions']])
    def test_graph_integrity_rejects_unsealed_change(self):
        p=self.prepare();p[3]['edges']=[]
        with self.assertRaisesRegex(ValueError,'SIDECAR_INTEGRITY'):self.read(p)
    def test_gold_fields_never_enter_runtime(self):
        p=self.prepare();c,dbs,a,g,_=p
        bad=copy.deepcopy(c['target']);bad['expected_fact_ids']=['f01-goal']
        with self.assertRaises((AssertionError,ValueError)):
            read_bundle(dbs,g,{'target':bad,'purpose':c['purpose']},expand=True)
        with self.assertRaisesRegex(ValueError,'REQUEST_SCHEMA'):
            read_bundle(dbs,g,{'target':c['target'],'purpose':c['purpose'],'case_id':'SYN-M0-01'},expand=True)
    def test_original_rank_and_same_state_retained(self):
        p=self.prepare();e,a,_=self.read(p,False);f,b,_=self.read(p,True)
        self.assertEqual(a['original_seed_items'],b['original_seed_items'])
        self.assertEqual(a['original_read']['before_logical_sha256'],b['original_read']['after_logical_sha256'])
    def test_origin_null_validity_and_no_invented_constraints(self):
        e,t,got=self.read(self.prepare('SYN-M1-LINKED-13'))
        plan=next(f for f in e.payload['facts'] if f['memory_type']=='ACTIVE_PLAN')
        self.assertEqual(plan['source_ref']['origin'],'SYSTEM')
        self.assertEqual(plan['source_ref']['confirmation'],'SYSTEM_RECORDED_LEARNER_ACCEPTANCE_UNKNOWN')
        self.assertIsNone(plan['validity']['valid_to'])
        self.assertEqual(e.payload['structured_constraints'],[])
    def test_readonly_envelope_cannot_be_mutated_by_consumer(self):
        e,_,_=self.read(self.prepare());a=e.payload;a['facts'].clear()
        self.assertTrue(e.payload['facts'])
    def test_opaque_ids_and_reordered_edges_preserve_semantic_fact_sets(self):
        for pair in json.loads((OWNED/'fixtures/test_only_metamorphic_pairs.json').read_text()):
            p=self.prepare(pair['original']);q=self.prepare(pair['variant'])
            e,t,g=self.read(p);f,u,h=self.read(q)
            self.assertEqual({x['content'] for x in e.payload['facts']},{x['content'] for x in f.payload['facts']})
    def test_frozen_fixtures_and_original_inputs_unchanged(self):
        for directory in (M0/'fixtures',OWNED/'fixtures'):
            f=json.loads((directory/'FIXTURE_FREEZE.json').read_text())
            for x in f['files']:self.assertEqual(sha(directory/x['path']),x['sha256'])
        for row in json.loads((OWNED/'fixtures/SOURCE_ENRICHMENT_LOG.json').read_text()):
            self.assertTrue(row['query_unchanged'] and row['source_turns_unchanged'] and row['setup_operations_unchanged'])
    def test_deletion_after_graph_compilation_is_rechecked(self):
        p=self.prepare();c,dbs,a,g,_=p
        with C4MemoryStore(dbs[c['target']['course_id']]) as s:
            from utils.c4_memory.c4_memory_provider import C4LearnerMemoryProvider
            result=C4LearnerMemoryProvider(s).delete_memory(student_id=c['target']['learner_id'],
                target_memory_id=a['f01-goal'],source_session_id='late-control',source_turn_id='delete-after-bind',
                user_turn='Delete my goal.',evidence_span='Delete my goal.',event_at='2026-08-19T14:00:00+00:00')
            self.assertTrue(result.accepted)
        e,t,got=self.read(p);self.assertEqual(got,['f01-time'])
        self.assertNotIn('quadratic formula',e.canonical_json)
    def test_version_changed_after_binding_is_excluded(self):
        p=self.prepare();c,dbs,a,g,_=p
        with C4MemoryStore(dbs[c['target']['course_id']]) as s:
            s._connection.execute('UPDATE memories SET version=2 WHERE memory_id=?',(a['f01-goal'],))
        _,t,got=self.read(p);self.assertEqual(got,['f01-time'])
        self.assertIn('STALE_SOURCE_VERSION',[e['reason'] for e in t['exclusions']])
    def test_future_linked_node_rechecked(self):
        p=self.prepare(change=lambda c:c['setup_operations'][0].update(valid_from='2026-09-01T00:00:00+00:00'))
        _,t,got=self.read(p);self.assertEqual(got,['f01-time'])
        self.assertIn('FUTURE_VALIDITY',[e['reason'] for e in t['exclusions']])
    def test_goal_recall_does_not_follow_plan_completion_edges(self):
        p=self.prepare('SYN-M1-LINKED-03',change=lambda c:c.update(purpose='GOAL_RECALL'))
        _,t,got=self.read(p);self.assertNotIn('f03-done',got)
        self.assertIn('LINK_TYPE_OUTSIDE_TASK_PURPOSE',[e['reason'] for e in t['omitted_facts']])
    def test_native_sql_write_is_blocked_in_m1_read_connection(self):
        p=self.prepare();c,dbs,a,g,_=p
        with ReadOnlyStore(dbs[c['target']['course_id']],clock=lambda:c['target']['as_of']) as s:
            with self.assertRaises(sqlite3.OperationalError):s._connection.execute('DELETE FROM memories')


class SavedM1Tests(unittest.TestCase):
    def test_actual_semantic_calls_match_eligible_rows_and_ipc_receipts(self):
        d=OWNED/'diagnostics/linked_hybrid_v3'
        rows=json.loads((d/'PAIRED_RESULTS.json').read_text())
        traces=json.loads((d/'TARGET_TRACES.json').read_text())
        runtime=json.loads((d/'RUNTIME_IDENTITY.json').read_text())
        self.assertEqual(sum(r['encode_calls_during_read'] for r in rows),len(runtime['input_receipts']))
        for r,t in zip(rows,traces):
            public=t['trace']['original_read']['public_retrieval_diagnostics']
            eligible=isinstance(public,dict) and public['active_candidate_count']>public['visible_history_excluded_count']
            self.assertEqual(r['semantic_executed'],eligible)
        self.assertEqual(runtime['worker_exit_code'],0)
    def test_saved_lexical_partial_and_ambiguity_remain_visible(self):
        d=OWNED/'diagnostics/linked_lexical_v2'
        rows={r['case_id']:r for r in json.loads((d/'PAIRED_RESULTS.json').read_text()) if r['condition']=='EXPANDED'}
        for name in ('SYN-M1-COMPLETION-CORRECTION','SYN-M1-WITHDRAWN-EDGE','SYN-M1-UNSUPPORTED-LINK','SYN-M1-BUDGET-OMISSION'):
            self.assertEqual(rows[name]['coverage_status'],'PARTIAL');self.assertTrue(rows[name]['missing_fact_ids'])
        self.assertEqual(rows['SYN-M1-AMBIGUOUS-PLANS']['coverage_status'],'AMBIGUOUS')
    def test_saved_target_reads_and_privacy_accounting(self):
        for folder in ('linked_lexical_v2','linked_hybrid_v3'):
            rows=json.loads((OWNED/'diagnostics'/folder/'PAIRED_RESULTS.json').read_text())
            self.assertEqual(len(rows),66)
            self.assertFalse(any(r['target_writes'] or r['privacy_violations'] for r in rows))
            for a,b in zip(rows[::2],rows[1::2]):
                self.assertEqual(a['same_state_sha256'],b['same_state_sha256'])
                self.assertEqual(a['seed_fact_ids'],b['seed_fact_ids'])
    def test_intermediate_failures_are_preserved(self):
        p=OWNED/'diagnostics'
        self.assertTrue((p/'linked_hybrid_v1/STARTUP_FAILURE.json').exists())
        self.assertTrue((p/'linked_hybrid_v2/ACCOUNTING_LIMITATION.json').exists())
        crash=json.loads((OWNED/'runtime_diagnostics/stages_v1/0_torch.json').read_text())
        self.assertEqual(crash['exit_code'],-11);self.assertIn('Segmentation fault',crash['stderr'])
    def test_semantic_rechecks_are_not_added_to_final_sample(self):
        a=json.loads((OWNED/'diagnostics/linked_hybrid_v2/PAIRED_RESULTS.json').read_text())
        b=json.loads((OWNED/'diagnostics/linked_hybrid_v3/PAIRED_RESULTS.json').read_text())
        self.assertEqual([(r['case_id'],r['condition'],r['retrieved_fact_ids']) for r in a],
                         [(r['case_id'],r['condition'],r['retrieved_fact_ids']) for r in b])
