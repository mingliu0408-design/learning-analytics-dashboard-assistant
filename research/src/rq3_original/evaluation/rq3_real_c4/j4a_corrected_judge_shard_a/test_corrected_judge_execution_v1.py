#!/usr/bin/env python3
"""Offline artifact verification and synthetic Parser-V3 regressions.

Real candidate text is never changed. Synthetic parser fixtures are not Judge
ratings. Network entry points are blocked for the entire test class. These tests
never call execute_package, construct a client, or resume the frozen run.
"""

import copy
import json
import socket
import unittest
from unittest.mock import patch

import audit_corrected_judge_execution_v1 as audit


class CorrectedJudgeArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [patch.object(socket.socket, 'connect', audit.no_network),
                       patch.object(socket.socket, 'connect_ex', audit.no_network),
                       patch.object(socket, 'create_connection', audit.no_network)]
        for item in cls.patches:
            item.start()
        cls.output = audit.HERE / 'execution_output_v1'
        cls.before = {p.name: audit.digest(p.read_bytes()) for p in cls.output.iterdir()}
        cls.result = audit.collect_audit()
        cls.after = {p.name: audit.digest(p.read_bytes()) for p in cls.output.iterdir()}
        cls.members, cls.modules, _ = audit.load_frozen_support()
        cls.parser = cls.modules['judge_result_parser_v3']

    @classmethod
    def tearDownClass(cls):
        for item in reversed(cls.patches):
            item.stop()

    def verify_checks(self, *names):
        for name in names:
            with self.subTest(check=name):
                self.assertTrue(self.result['checks'][name], name)

    def fixture(self, applicability=None):
        flags = {name: True for name in self.parser.PRIMARY_CRITERIA}
        if applicability:
            flags.update(applicability)
        mapping = {'schema_version': self.parser.APPLICABILITY_SCHEMA_VERSION,
                   'freeze_status': 'FROZEN_BEFORE_CANDIDATE_SCORING',
                   'criteria': flags, 'applicable_primary_count': sum(flags.values()),
                   'applicability_sha256': audit.digest(audit.canonical(flags))}
        payload = {field: '3' if flags[name] else 'NA' for name, field in self.parser.SCORE_FIELDS.items()}
        payload.update({'schema_version': self.parser.TRANSPORT_SCHEMA_VERSION,
                        'evidence_faithfulness': '3', 'unsupported_claim_count': '0',
                        'criterion_rationales': {field: 'OFFLINE_SYNTHETIC_PARSER_FIXTURE' for field in self.parser.SCORE_FIELDS.values()}})
        return payload, mapping

    def parse(self, payload, mapping):
        return self.parser.parse_judge_result(payload, mapping, expected_judge_result_blind_id='R3B-00000000000000000001')

    def test_01_read_only_output_immutability(self):
        self.assertEqual(self.before, self.after)

    def test_02_known_contract_failure_remains_disclosed(self):
        self.assertEqual(self.result['audit_status'], 'FAIL')
        self.assertEqual(self.result['execution_status'], 'INCOMPLETE')
        self.assertEqual(self.result['failed_checks'], ['initial_start_intervals_at_least_15_seconds'])
        self.assertEqual(self.result['check_count'], self.result['passed_check_count'] + 1)

    def test_03_package_and_members(self):
        self.verify_checks('package_zip_hash', 'exact_13_pinned_member_hashes', 'frozen_package_validation')

    def test_04_frozen_manifest_and_identity(self):
        self.verify_checks('selected_shard_and_request_count', 'maximum_physical_attempts_contract', 'phase_b_entry_receipt_binding')

    def test_05_starting_gates_and_extraction(self):
        self.verify_checks('starting_directory_branch_head', 'starting_worktree_clean', 'fresh_extraction_exactly_once', 'zip_directory_tests_pass_before_execution')

    def test_06_authorization(self):
        self.verify_checks('authorization_exact_11_fields', 'authorization_identity_and_status', 'authorization_timestamp_format', 'authorization_sha256')

    def test_07_zero_network_runtime(self):
        self.verify_checks('preflight_runtime_identity', 'preflight_zero_network', 'preflight_client_closed', 'preflight_key_presence_only', 'no_dependency_changes')

    def test_08_transport_configuration(self):
        self.verify_checks('preflight_zero_sdk_retries', 'preflight_all_timeout_components_120', 'openai_chat_completions_endpoint', 'runner_client_transport_identity')

    def test_09_single_invocation_output_gate(self):
        self.verify_checks('runner_invoked_once', 'output_leaf_absent_and_runner_created', 'output_exact_durable_file_set')

    def test_10_receipt_and_runtime_order(self):
        self.verify_checks('runner_receipt_bindings', 'runner_receipt_before_transport', 'status_event_sequence', 'runner_runtime_identity')

    def test_11_provider_payload_hashes(self):
        self.verify_checks('all_journal_bindings_and_payload_hashes', 'all_payload_hashes_recomputed', 'frozen_provider_parameters')

    def test_12_request_order_and_uniqueness(self):
        self.verify_checks('initial_order_is_frozen_prefix', 'initial_ids_unique', 'attempt_keys_unique', 'attempts_one_initial_one_optional_retry')

    def test_13_durable_attempt_sequence(self):
        self.verify_checks('attempt_events_only_started_returned', 'returned_attempts_have_starts', 'durable_attempt_event_order')

    def test_14_attempt_counts_and_cap(self):
        self.verify_checks('physical_call_counters', 'physical_attempt_cap_78', 'runner_status_counts')

    def test_15_retry_contract(self):
        self.verify_checks('retry_only_after_eligible_failure', 'retry_hashes_byte_identical', 'no_retry_after_valid_result', 'no_automatic_resume')

    def test_16_pacing_and_timeout(self):
        self.verify_checks('all_attempt_timeouts_120', 'timestamps_ordered', 'pacing_incident_matches_observed_intervals')
        self.assertFalse(self.result['checks']['initial_start_intervals_at_least_15_seconds'])
        self.assertEqual([v['observed_interval_seconds'] for v in self.result['pacing_violations']], [14.98719, 14.996812])

    def test_17_terminal_ids_and_coverage(self):
        self.verify_checks('terminal_request_ids_unique', 'terminal_result_ids_unique', 'terminal_order_is_frozen_prefix', 'all_terminals_valid_status', 'complete_has_full_coverage_no_errors')

    def test_18_model_and_parser_v3(self):
        self.verify_checks('returned_model_exact', 'all_valid_results_reparse_with_frozen_parser_v3', 'invalid_output_labels_match_parser_v3', 'terminals_match_successful_returned_attempts')

    def test_19_applicability_and_rationales(self):
        self.verify_checks('score_na_values_match_frozen_applicability', 'rationales_nonempty_unchanged', 'evidence_faithfulness_valid', 'unsupported_claim_count_nonnegative')

    def test_20_local_mean_and_tokens(self):
        self.verify_checks('per_result_local_mean_exact', 'provider_tokens_nonnegative_integers', 'provider_token_arithmetic')

    def test_21_fail_closed_rules(self):
        self.verify_checks('status_complete_or_incomplete', 'incomplete_requires_new_authorization', 'error_policy_stops_entire_shard', 'second_invalid_stops_without_next_request', 'unreturned_provider_attempt_is_last_and_not_retried')

    def test_22_blinding_and_secrets(self):
        self.verify_checks('no_condition_mode_identity_in_results', 'secret_absence_artifact_scan', 'other_corrected_packages_not_accessed')

    def test_23_bytecode_and_source_immutability(self):
        self.verify_checks('no_bytecode_or_symlink_artifacts', 'fresh_extraction_members_remain_unchanged')

    def test_24_terminal_and_parsed_set_digests(self):
        rows = audit.read_jsonl(self.output / 'JUDGE_TERMINAL_JOURNAL.jsonl')
        self.assertEqual(audit.digest((self.output / 'JUDGE_TERMINAL_JOURNAL.jsonl').read_bytes()), self.result['terminal_journal_sha256'])
        self.assertEqual(audit.digest(audit.canonical([r['parsed_semantic_result'] for r in rows])), self.result['parsed_result_set_sha256'])

    def test_25_synthetic_valid_parser_and_local_mean(self):
        payload, mapping = self.fixture()
        original = copy.deepcopy(payload)
        result = self.parse(payload, mapping)
        self.assertEqual(payload, original)
        self.assertEqual(result['overall_applicable_mean'], 3.0)

    def test_26_synthetic_long_rationale_preserved(self):
        payload, mapping = self.fixture()
        payload['criterion_rationales']['clarity'] = 'OFFLINE_LONG_RATIONALE_' * 60
        self.assertEqual(self.parse(payload, mapping)['criterion_rationales']['clarity'], payload['criterion_rationales']['clarity'])

    def test_27_synthetic_duplicate_json_keys_rejected(self):
        _, mapping = self.fixture()
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'STRICT_SCHEMA_VALIDATION_FAILED'):
            self.parse('{"duplicate":1,"duplicate":2}', mapping)

    def test_28_synthetic_invalid_json_rejected(self):
        _, mapping = self.fixture()
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'INVALID_JSON'):
            self.parse('OFFLINE_INVALID_JSON', mapping)

    def test_29_synthetic_extra_field_rejected(self):
        payload, mapping = self.fixture()
        payload['OFFLINE_EXTRA_FIELD'] = True
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'STRICT_SCHEMA_VALIDATION_FAILED'):
            self.parse(payload, mapping)

    def test_30_synthetic_empty_rationale_rejected(self):
        payload, mapping = self.fixture()
        payload['criterion_rationales']['clarity'] = '  '
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'STRICT_SCHEMA_VALIDATION_FAILED'):
            self.parse(payload, mapping)

    def test_31_synthetic_evidence_and_unsupported_rejected(self):
        for field, value in (('evidence_faithfulness', 'NA'), ('unsupported_claim_count', '-1')):
            with self.subTest(field=field):
                payload, mapping = self.fixture()
                payload[field] = value
                with self.assertRaisesRegex(self.parser.JudgeResultError, 'STRICT_SCHEMA_VALIDATION_FAILED'):
                    self.parse(payload, mapping)

    def test_32_synthetic_applicable_na_rejected(self):
        payload, mapping = self.fixture()
        payload['clarity'] = 'NA'
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'APPLICABILITY_CONTRACT_VIOLATION'):
            self.parse(payload, mapping)

    def test_33_synthetic_inapplicable_score_rejected(self):
        payload, mapping = self.fixture({'ACTIONABILITY': False})
        payload['actionability'] = '3'
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'APPLICABILITY_CONTRACT_VIOLATION'):
            self.parse(payload, mapping)

    def test_34_synthetic_applicability_hash_rejected(self):
        payload, mapping = self.fixture()
        mapping['applicability_sha256'] = '0' * 64
        with self.assertRaisesRegex(self.parser.JudgeResultError, 'APPLICABILITY_CONTRACT_VIOLATION'):
            self.parse(payload, mapping)

    def test_35_synthetic_partial_applicability_local_mean(self):
        payload, mapping = self.fixture({'ACTIONABILITY': False, 'ERROR_HANDLING': False})
        result = self.parse(payload, mapping)
        self.assertEqual(result['actionability'], 'NA')
        self.assertEqual(result['error_handling'], 'NA')
        self.assertEqual(result['overall_applicable_mean'], 3.0)

    def test_36_zero_scope_confirmations(self):
        self.assertTrue(self.result['zero_scope_confirmations'])
        self.assertTrue(all(value == 0 for value in self.result['zero_scope_confirmations'].values()))
        self.verify_checks('durable_output_matches_immediate_stop_snapshot', 'agent_interrupt_transparently_disclosed', 'incomplete_usage_marked_unobserved')
        self.assertFalse(self.result['token_usage_complete_for_all_physical_attempts'])
        self.assertEqual(self.result['agent_interrupt_count'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
