#!/usr/bin/env python3
"""32 zero-network tests of actual durable evidence and in-memory tampering.

Never calls the runner, writes a journal, changes a request, or recomputes an
applicability decision. The eight negative tests change disposable copies only.
"""
from collections import Counter
import copy
import hashlib
import json
import unittest

import audit_corrected_judge_execution_v1 as audit


class CorrectedJudgeExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = audit.network_guard()
        cls.guard.__enter__()
        cls.addClassCleanup(cls.guard.__exit__, None, None, None)
        cls.c = audit.load_context()

    def test_01_selected_package_and_exact_13_members(self):
        self.assertEqual(audit.verify_sources(self.c)['package_member_count'], 13)
        self.assertEqual(hashlib.sha256(self.c['package_path'].read_bytes()).hexdigest(), audit.PACKAGE_HASH)

    def test_02_frozen_protocol_hashes_and_contract(self):
        for name, expected in audit.PROTOCOL_HASHES.items():
            self.assertEqual(hashlib.sha256(self.c['members'][name]).hexdigest(), expected)
        self.assertEqual(self.c['contract']['phase_b_entry_receipt_sha256'], audit.ENTRY_HASH)
        self.assertEqual(self.c['config']['model'], audit.MODEL)
        self.assertEqual(self.c['config']['maximum_output_tokens'], 2048)
        self.assertIs(self.c['config']['stream'], False)

    def test_03_38_request_identities_and_frozen_order(self):
        requests = self.c['requests']
        self.assertEqual(len(requests), 38)
        self.assertEqual([r['logical_order'] for r in requests], list(range(1, 39)))
        for key in ('logical_judge_request_id', 'judge_result_blind_id', 'provider_payload_sha256'):
            self.assertEqual(len({r[key] for r in requests}), 38)
        self.assertTrue(all(r['logical_judge_request_id'].startswith('C4J4-') for r in requests))

    def test_04_exact_authorization_and_immutable_hash(self):
        self.assertEqual(audit.verify_authorization(self.c)['authorization_sha256'], audit.AUTH_HASH)
        self.assertEqual(len(self.c['auth']), 11)

    def test_05_starting_git_gates(self):
        g = self.c['gates']
        self.assertEqual((g['working_directory'], g['branch'], g['starting_head']), (str(audit.ROOT), audit.BRANCH, audit.HEAD))
        self.assertEqual(g['initial_git_status_short'], '')
        self.assertTrue(g['output_leaf_absent'])
        self.assertTrue(g['tracked_worktree_clean'])

    def test_06_zero_network_preflight(self):
        p = self.c['preflight']
        self.assertEqual((p['provider_calls'], p['network_attempts'], p['dependency_changes']), (0, 0, 0))
        self.assertTrue(p['client_closed_cleanly'])
        self.assertTrue(p['api_key_presence_checked_only'])
        self.assertFalse(p['api_key_value_recorded'])

    def test_07_execution_runtime_and_four_timeout_components(self):
        result = audit.verify_runtime(self.c)
        self.assertEqual((result['python_version'], result['openai_sdk_version']), ('3.13.5', '1.109.1'))
        self.assertEqual(result['timeout_components_seconds'], dict.fromkeys(('connect', 'read', 'write', 'pool'), 120.0))

    def test_08_exactly_one_invocation_and_final_status(self):
        self.assertEqual(self.c['invocation']['real_runner_invocations'], 1)
        self.assertFalse(self.c['invocation']['automatic_resume'])
        audit.verify_completion_and_errors(self.c)

    def test_09_attempt_order_counts_and_maximum(self):
        value = audit.verify_attempts(self.c)
        self.assertEqual(value['physical_attempts'], self.c['status']['judge_calls'])
        self.assertLessEqual(value['physical_attempts'], 76)

    def test_10_only_admitted_byte_identical_retry(self):
        returns = {(e['logical_judge_request_id'], e['attempt_number']): e for e in self.c['returned']}
        for e in self.c['started']:
            if e['attempt_number'] == 2:
                previous = returns[(e['logical_judge_request_id'], 1)]
                self.assertIn(previous['failure_code'], audit.RETRYABLE)
                self.assertEqual(e['provider_payload_sha256'], previous['provider_payload_sha256'])

    def test_11_initial_request_spacing(self):
        initial = [e for e in self.c['started'] if e['attempt_number'] == 1]
        intervals = [(audit.utc(b['request_started_at_utc']) - audit.utc(a['request_started_at_utc'])).total_seconds() for a, b in zip(initial, initial[1:])]
        self.assertTrue(all(value >= 15.0 for value in intervals))

    def test_12_all_provider_payload_commitments(self):
        hashes = {r['logical_judge_request_id']: hashlib.sha256(audit.canonical(r['provider_payload'])).hexdigest() for r in self.c['requests']}
        for e in self.c['events'] + self.c['terminals']:
            self.assertEqual(e['provider_payload_sha256'], hashes[e['logical_judge_request_id']])

    def test_13_returned_model_identity(self):
        self.assertTrue(all(t['returned_model'] == audit.MODEL for t in self.c['terminals']))
        if self.c['status']['status'] == 'COMPLETE':
            self.assertEqual({e['returned_model'] for e in self.c['returned']}, {audit.MODEL})

    def test_14_valid_terminal_coverage(self):
        self.assertEqual(len(self.c['terminals']), self.c['status']['valid_terminal_count'])
        if self.c['status']['status'] == 'COMPLETE':
            self.assertEqual(len(self.c['terminals']), 38)
            self.assertEqual(len(self.c['errors']), 0)
        self.assertTrue(all(t['terminal_status'] == 'VALID_JUDGE_RESULT' for t in self.c['terminals']))

    def test_15_terminal_identities_unique(self):
        for name in ('logical_judge_request_id', 'judge_result_blind_id'):
            self.assertTrue(all(v == 1 for v in Counter(t[name] for t in self.c['terminals']).values()))
        self.assertEqual([t['logical_order'] for t in self.c['terminals']], list(range(1, len(self.c['terminals']) + 1)))

    def test_16_raw_response_parser_v3_replay(self):
        self.assertEqual(audit.verify_results(self.c)['parser_v3_passed'], len(self.c['terminals']))

    def test_17_numeric_scores_and_na_match_supplied_applicability(self):
        for t in self.c['terminals']:
            flags = audit.applicability(self.c, t['logical_judge_request_id'])['criteria']
            for criterion, field in self.c['parser'].SCORE_FIELDS.items():
                value = t['parsed_semantic_result'][field]
                if flags[criterion]:
                    self.assertIs(type(value), int)
                    self.assertIn(value, range(1, 6))
                else:
                    self.assertEqual(value, 'NA')

    def test_18_independent_local_mean(self):
        for t in self.c['terminals']:
            flags = audit.applicability(self.c, t['logical_judge_request_id'])['criteria']
            result = t['parsed_semantic_result']
            values = [result[field] for criterion, field in self.c['parser'].SCORE_FIELDS.items() if flags[criterion]]
            self.assertEqual(result['overall_applicable_mean'], sum(values) / len(values))

    def test_19_rationales_evidence_and_unsupported_count(self):
        for t in self.c['terminals']:
            result = t['parsed_semantic_result']
            self.assertEqual(len(result['criterion_rationales']), 8)
            self.assertTrue(all(isinstance(v, str) and v.strip() for v in result['criterion_rationales'].values()))
            self.assertIn(result['evidence_faithfulness'], range(1, 6))
            self.assertIs(type(result['unsupported_claim_count']), int)
            self.assertGreaterEqual(result['unsupported_claim_count'], 0)

    def test_20_each_returned_attempt_token_arithmetic(self):
        for e in self.c['returned']:
            self.assertEqual(e['total_tokens'], e['prompt_tokens'] + e['completion_tokens'])
            self.assertLessEqual(e['cached_input_tokens'], e['prompt_tokens'])
            self.assertTrue(all(type(e[k]) is int and e[k] >= 0 for k in audit.TOKENS))

    def test_21_all_physical_attempt_usage_totals(self):
        saved = audit.read_json(audit.BASE / 'corrected_judge_execution_audit_v1.json')['details']['all_physical_attempt_token_arithmetic']
        for key in audit.TOKENS:
            self.assertEqual(saved[key], sum(e[key] for e in self.c['returned']))
        self.assertEqual(saved, audit.verify_tokens(self.c))

    def test_22_durable_output_byte_preservation(self):
        self.assertEqual(audit.verify_durability(self.c)['file_count'], 6)

    def test_23_parsed_result_set_serialization_and_hash(self):
        raw = (audit.BASE / 'parsed_judge_results_v1.jsonl').read_bytes()
        self.assertEqual(raw, audit.projection(self.c))
        saved = audit.read_json(audit.BASE / 'corrected_judge_execution_audit_v1.json')
        self.assertEqual(hashlib.sha256(raw).hexdigest(), saved['parsed_result_set_sha256'])
        self.assertEqual(len(raw.splitlines()), len(self.c['terminals']))

    def test_24_source_commitments_blinding_and_secret_absence(self):
        source = audit.read_json(audit.BASE / 'corrected_judge_execution_source_manifest_v1.json')
        self.assertEqual(source['member_sha256'], {n: audit.digest(b) for n, b in self.c['members'].items()})
        self.assertEqual(source['durable_file_sha256'], self.c['snapshot']['durable_file_sha256'])
        for name, expected in source['support_artifact_sha256'].items():
            self.assertEqual(audit.digest((audit.BASE / name).read_bytes()), expected)
        audit.verify_blinding_and_secret_absence(self.c)

    def changed(self, key):
        c = dict(self.c)
        c[key] = copy.deepcopy(self.c[key])
        return c

    def test_25_reject_duplicate_terminal(self):
        c = self.changed('terminals')
        c['terminals'].append(copy.deepcopy(c['terminals'][0]))
        with self.assertRaises(audit.AuditFailure):
            audit.verify_results(c)

    def test_26_reject_unauthorized_request_id(self):
        c = self.changed('events')
        c['events'][0]['logical_judge_request_id'] = 'OFFLINE_UNAUTHORIZED_ID'
        with self.assertRaises(audit.AuditFailure):
            audit.verify_attempts(c)

    def test_27_reject_changed_provider_payload_hash(self):
        c = self.changed('events')
        c['events'][0]['provider_payload_sha256'] = '0' * 64
        with self.assertRaises(audit.AuditFailure):
            audit.verify_attempts(c)

    def test_28_reject_retry_after_valid_result(self):
        first = next(e for e in self.c['returned'] if e.get('failure_code') is None)
        started = next(e for e in self.c['started'] if e['logical_judge_request_id'] == first['logical_judge_request_id'] and e['attempt_number'] == first['attempt_number'])
        initial, valid, retry = copy.deepcopy(started), copy.deepcopy(first), copy.deepcopy(started)
        initial['attempt_number'] = valid['attempt_number'] = 1
        retry['attempt_number'] = 2
        c = dict(self.c, events=[initial, valid, retry], started=[initial, retry], returned=[valid])
        with self.assertRaises(audit.AuditFailure):
            audit.verify_attempts(c)

    def test_29_reject_bad_token_arithmetic(self):
        c = self.changed('returned')
        c['returned'][0]['total_tokens'] += 1
        with self.assertRaises(audit.AuditFailure):
            audit.verify_tokens(c)

    def test_30_reject_empty_rationale_in_disposable_copy(self):
        c = self.changed('returned')
        e = next(e for e in c['returned'] if e.get('failure_code') is None)
        raw = json.loads(e['raw_response_content'])
        raw['criterion_rationales']['clarity'] = ' '
        e['raw_response_content'] = json.dumps(raw)
        with self.assertRaises(audit.AuditFailure):
            audit.verify_results(c)

    def test_31_reject_changed_local_mean(self):
        c = self.changed('terminals')
        c['terminals'][0]['parsed_semantic_result']['overall_applicable_mean'] += 0.125
        with self.assertRaises(audit.AuditFailure):
            audit.verify_results(c)

    def test_32_reject_extra_authorization_field(self):
        c = self.changed('auth')
        c['auth']['OFFLINE_EXTRA_FIELD'] = True
        with self.assertRaises(audit.AuditFailure):
            audit.verify_authorization(c)


if __name__ == '__main__':
    unittest.main(verbosity=2)
