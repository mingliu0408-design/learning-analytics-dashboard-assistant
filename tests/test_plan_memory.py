"""Explicit UI consent -> original native Writer and M1/P1 relationships.

Only the provider is mocked. All scope, SQLite, role, relation compilation,
read-only M1 retrieval and P1 projection execute the recovered original core.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from public_runtime.core import PublicAssistant, CoreFailure
from tests.test_runtime import ExactMock


class SensitiveActionMock(ExactMock):
    def send(self, payload):
        result = super().send(payload)
        value = json.loads(result['choices'][0]['message']['content'])
        if 'actions' in value:
            value['actions'][0]['action'] = 'Record my email address before reviewing analytics.'
            result['choices'][0]['message']['content'] = json.dumps(value)
        return result


class PlanMemoryRuntime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lad-plan-memory-tests-')
        self.engine = PublicAssistant(uuid.uuid4().hex, storage_root=self.temp.name)
        self.engine.bind_dashboard('301101', 1, 3)

    def tearDown(self):
        self.temp.cleanup()

    def proposal(self, provider=None):
        result = self.engine.live(
            'Give me an action plan without dates to study learning analytics',
            transport=provider or ExactMock(), memory_backend='LEXICAL',
            controls={'task_intent': 'ORDINARY_ACTION_ADVICE'})
        return result['accepted_plan'], result

    def persisted(self):
        return {str(p.relative_to(self.engine.workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.engine.workspace.rglob('*')
                if p.is_file() and p.name in ('memory.sqlite', 'visitor_graph.json',
                                             'visitor_events.json', 'adopted_plans.json')}

    def test_checked_proposal_is_not_memory_and_consent_requires_literal_true(self):
        plan, result = self.proposal()
        self.assertEqual(result['plan_registration']['status'], 'CHECKED_PROPOSAL_NOT_ADOPTED')
        self.assertFalse(result['plan_registration']['memory_written'])
        self.assertEqual(self.engine.memory_list(), [])
        self.assertEqual(self.engine.memory_task_state()['plans'], [])
        before = self.persisted()
        for consent in (False, 'true', 1, None):
            answer = self.engine.memory_accept_plan('dashboard-301101', plan, consent=consent)
            self.assertFalse(answer['accepted'])
            self.assertEqual(answer['reason_code'], 'EXPLICIT_UI_CONSENT_REQUIRED')
            self.assertEqual(self.persisted(), before)
        self.assertFalse(self.engine.memory_accept_plan('dashboard-301101', plan)['accepted'])

    def test_forged_other_learner_and_other_session_plan_is_rejected(self):
        plan, _ = self.proposal()
        forged = deepcopy(plan)
        forged['actions'][0]['action'] = 'Perform a different action that was not accepted by P1.'
        with self.assertRaisesRegex(CoreFailure, 'PLAN_NOT_CHECKED_IN_THIS_LEARNER_SESSION'):
            self.engine.memory_accept_plan('dashboard-301101', forged, consent=True)
        self.engine.bind_dashboard('301102', 1, 3)
        with self.assertRaisesRegex(CoreFailure, 'PLAN_NOT_CHECKED_IN_THIS_LEARNER_SESSION'):
            self.engine.memory_accept_plan('dashboard-301102', plan, consent=True)
        self.assertEqual(self.engine.memory_list(), [])
        other = PublicAssistant(uuid.uuid4().hex, storage_root=self.temp.name)
        other.bind_dashboard('301101', 1, 3)
        with self.assertRaisesRegex(CoreFailure, 'PLAN_NOT_CHECKED_IN_THIS_LEARNER_SESSION'):
            other.memory_accept_plan('dashboard-301101', plan, consent=True)
        self.assertEqual(other.memory_list(), [])

    def test_direct_registration_rejects_forged_preparation_and_cross_session_receipts(self):
        plan, result = self.proposal()
        other = PublicAssistant(uuid.uuid4().hex, storage_root=self.temp.name)
        other.bind_dashboard('301101', 1, 3)
        forged = json.loads(json.dumps(result['core']['prepared']).replace(
            self.engine.session_id, other.session_id))
        query = 'I did not run a candidate or FINAL.'
        for extra in ({}, {'runtime_receipt': result['core']['runtime_receipt']},
                      {'runtime_receipt': '../runtime_receipts/not-an-identity'}):
            with self.assertRaisesRegex(CoreFailure, 'SESSION_RUNTIME_RECEIPT'):
                other.call('register_plan', query=query, plan=plan, prepared=forged, **extra)
        self.assertEqual(other.memory_list(), [])
        self.assertEqual(other.memory_task_state()['plans'], [])
        legitimate = other.components(
            'Give me an action plan without dates to study learning analytics',
            rag=True, memory=True, planning=True,
            controls={'task_intent': 'ORDINARY_ACTION_ADVICE'})
        args = dict(query='Give me an action plan without dates to study learning analytics',
                    controls={'task_intent': 'ORDINARY_ACTION_ADVICE'},
                    runtime_receipt=legitimate['runtime_receipt'])
        with self.assertRaisesRegex(CoreFailure, 'SESSION_PREPARATION_CHANGED'):
            other.call('check_candidate', prepared=forged, candidate=plan, **args)
        checked_files = [p for p in (self.engine.workspace / 'runtime_receipts').glob('*.json')
                         if json.loads(p.read_text()).get('version') == 'PUBLIC_SERVER_CHECKED_CANDIDATE_V1']
        self.assertEqual(len(checked_files), 1)
        for extra in ({}, {'candidate_receipt': checked_files[0].stem}):
            with self.assertRaisesRegex(CoreFailure, 'SESSION_RUNTIME_RECEIPT'):
                other.call('register_plan', prepared=legitimate['prepared'], plan=plan,
                           **args, **extra)
        self.assertEqual(other.memory_list(), [])
        # A genuine local checker pass must still match the exact plan bytes.
        checked = other.call('check_candidate', prepared=legitimate['prepared'], candidate=plan, **args)
        self.assertEqual(checked['issues'], [])
        mutated = deepcopy(plan)
        mutated['actions'][0]['action'] = 'A different unchecked proposal.'
        with self.assertRaisesRegex(CoreFailure, 'SESSION_CHECKED_PLAN_CHANGED'):
            other.call('register_plan', prepared=legitimate['prepared'], plan=mutated,
                       candidate_receipt=checked['candidate_receipt'], **args)
        self.assertEqual(other.memory_list(), [])

    def test_native_user_adoption_completion_relations_and_p1_read_only_projection(self):
        plan, _ = self.proposal()
        adopted = self.engine.memory_accept_plan('dashboard-301101', plan, consent=True)
        aid = adopted['actions'][0]['action_memory_id']
        self.assertEqual({r['memory_type'] for r in self.engine.memory_list()},
                         {'ACTIVE_PLAN', 'PROGRESS_UPDATE'})
        before = self.persisted()
        self.assertFalse(self.engine.memory_complete_action('dashboard-301101', aid)['accepted'])
        self.assertEqual(self.persisted(), before)
        done = self.engine.memory_complete_action('dashboard-301101', aid, consent=True)
        self.assertEqual(done['completion_basis'], 'EXPLICIT_USER_SELF_REPORT')
        self.engine.bind_dashboard('301101', 4, 4)
        state = self.engine.memory_task_state()
        action = state['plans'][0]['actions'][0]
        self.assertTrue(action['completed'])
        self.assertEqual(action['completion_memory_id'], done['completion_memory_id'])
        before = self.persisted()
        for purpose, query in (('PLAN_CONTINUATION', 'Continue the plan I adopted.'),
                               ('COMPLETION_RECALL', 'What have I completed?')):
            local = self.engine.components(query, rag=False, memory=True, planning=True,
                controls={'memory_purpose': purpose, 'task_intent': 'ORDINARY_ACTION_ADVICE'})
            envelope = local['prepared']['final_request']['runtime_input']['memory']
            self.assertEqual({f['memory_type'] for f in envelope['facts']},
                             {'ACTIVE_PLAN', 'PROGRESS_UPDATE', 'COMPLETED_ACTION'})
            self.assertEqual({e['relation_type'] for e in envelope['source_link_edges']},
                             {'ACCEPTED_ACTION_BELONGS_TO_PLAN', 'COMPLETION_BELONGS_TO_PLAN',
                              'COMPLETION_OF_ACTION'})
            self.assertEqual(envelope['accepted_action_ids'], [aid])
            self.assertEqual(envelope['chosen_active_plan_id'], adopted['plan_memory_id'])
            self.assertTrue(local['readonly_state_unchanged'])
            self.assertTrue(envelope['read_only'])
            for fact in envelope['facts']:
                self.assertEqual(fact['source_ref']['origin'], 'USER')
                self.assertEqual(fact['source_ref']['claim_basis'], 'EXPLICIT_USER_STATEMENT')
                self.assertEqual(fact['source_ref']['session_id'], self.engine.session_id)
            bridge = local['prepared']['planner']['bridge']
            completed = bridge['planner_input']['completed_tasks']
            self.assertIn(aid, [t['task_id'] for t in completed])
            self.assertNotIn(done['completion_memory_id'], [t['task_id'] for t in completed])
            self.assertEqual(self.persisted(), before)
        self.engine.bind_dashboard('301102', 4, 4)
        self.assertEqual(self.engine.memory_task_state()['plans'], [])
        with self.assertRaisesRegex(CoreFailure, 'ACTIVE_ACCEPTED_ACTION_REQUIRED'):
            self.engine.memory_complete_action('dashboard-301102', aid, consent=True)

    def test_adoption_and_completion_are_idempotent_and_reopenable(self):
        plan, _ = self.proposal()
        first = self.engine.memory_accept_plan('dashboard-301101', plan, consent=True)
        before = self.persisted()
        second = self.engine.memory_accept_plan('dashboard-301101', plan, consent=True)
        self.assertTrue(second['already_adopted'])
        self.assertEqual(first['plan_memory_id'], second['plan_memory_id'])
        self.assertEqual(before, self.persisted())
        aid = first['actions'][0]['action_memory_id']
        first_done = self.engine.memory_complete_action('dashboard-301101', aid, consent=True)
        before = self.persisted()
        second_done = self.engine.memory_complete_action('dashboard-301101', aid, consent=True)
        self.assertTrue(second_done['already_completed'])
        self.assertEqual(first_done['completion_memory_id'], second_done['completion_memory_id'])
        self.assertEqual(before, self.persisted())
        reopened = PublicAssistant(self.engine.session_id, storage_root=self.temp.name)
        reopened.bind_dashboard('301101', 5, 5)
        self.assertEqual(len(reopened.memory_list()), 3)
        self.assertTrue(reopened.memory_task_state()['plans'][0]['actions'][0]['completed'])
        other = PublicAssistant(uuid.uuid4().hex, storage_root=self.temp.name)
        other.bind_dashboard('301101', 5, 5)
        self.assertEqual(other.memory_task_state()['plans'], [])
        with self.assertRaisesRegex(CoreFailure, 'ACTIVE_ACCEPTED_ACTION_REQUIRED'):
            other.memory_complete_action('dashboard-301101', aid, consent=True)

    def test_native_policy_rejection_preserves_real_store_and_sidecars(self):
        plan, _ = self.proposal(SensitiveActionMock())
        self.assertIsNotNone(plan)  # The structural checker is not a semantic safety oracle.
        before = self.persisted()
        with self.assertRaisesRegex(CoreFailure, 'NATIVE_WRITE_REJECTED:UNRELATED_SENSITIVE_INFORMATION'):
            self.engine.memory_accept_plan('dashboard-301101', plan, consent=True)
        self.assertEqual(self.persisted(), before)
        self.assertEqual(self.engine.memory_list(), [])
        self.assertEqual(self.engine.memory_task_state()['plans'], [])

    def test_hybrid_option_is_gated_and_invalid_backend_rejected(self):
        for bad in ('FAKE', '', None):
            with self.assertRaisesRegex(ValueError, 'UNKNOWN_MEMORY_BACKEND'):
                self.engine.components('Recall my plan', memory_backend=bad)
        with patch.dict(os.environ, {}, clear=True):
            local = self.engine.components('Explain activity', rag=False, memory=False,
                                           memory_backend='HYBRID')
            self.assertEqual(local['memory_calls'], 0)
            with self.assertRaisesRegex(CoreFailure, 'REQUIRES_PINNED_MPNET_PATH'):
                self.engine.components('Recall my plan', rag=False, memory=True,
                                       memory_backend='HYBRID')


if __name__ == '__main__':
    unittest.main()
