"""Offline evidence-integrity tests; all corruptions exist only in memory."""
import copy
from datetime import datetime, timedelta
from pathlib import Path
import unittest

import audit_corrected_judge_execution_v1 as audit


class CorrectedShardEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = audit.network_guard()
        cls.guard.__enter__()
        cls.artifact = Path(__file__).resolve().parent
        cls.snapshot = audit.load_snapshot(cls.artifact)

    @classmethod
    def tearDownClass(cls):
        cls.guard.__exit__(None, None, None)

    def corrupt(self):
        return copy.deepcopy(self.snapshot)

    def reject(self, snapshot):
        with self.assertRaises(audit.AuditError):
            audit.audit_snapshot(snapshot)

    @staticmethod
    def put_rows(snapshot, name, rows):
        snapshot['output'][name] = b''.join(audit.canonical(row) + b'\n' for row in rows)

    def attempt_rows(self, snapshot):
        return audit.jsonl(snapshot['output']['JUDGE_ATTEMPT_JOURNAL.jsonl'])

    def first_return(self, rows):
        matches = [row for row in rows if row['event'] == 'ATTEMPT_RETURNED']
        if not matches:
            self.skipTest('No returned result in preserved incomplete evidence')
        return matches[0]

    def terminal_rows(self, snapshot):
        rows = audit.jsonl(snapshot['output']['JUDGE_TERMINAL_JOURNAL.jsonl'])
        if not rows:
            self.skipTest('No valid terminal in preserved incomplete evidence')
        return rows

    def test_01_real_evidence_replays_under_frozen_parser(self):
        facts, parsed_bytes, _ = audit.audit_snapshot(self.snapshot)
        self.assertEqual(facts['result_integrity_status'], 'PASS')
        self.assertIn(facts['audit_status'], ('PASS', 'QUALIFIED_PACING_EVIDENCE_LIMITATION'))
        self.assertEqual(facts['shard_id'], 'C')
        self.assertEqual(facts['parsed_result_set_sha256'], audit.sha(parsed_bytes))
        self.assertEqual(facts['offline_audit_provider_calls'], 0)

    def test_02_all_thirteen_source_hashes_are_frozen(self):
        self.assertEqual({name: audit.sha(raw) for name, raw in self.snapshot['members'].items()}, audit.PINS)

    def test_03_extra_authorization_field_rejected(self):
        snapshot = self.corrupt()
        value = audit.strict_json(snapshot['authorization'])
        value['comment'] = 'synthetic mutation'
        snapshot['authorization'] = audit.canonical(value)
        self.reject(snapshot)

    def test_04_source_byte_mutation_rejected(self):
        snapshot = self.corrupt()
        snapshot['members']['JUDGE_PROMPT.txt'] += b'\n'
        self.reject(snapshot)

    def test_05_missing_terminal_rejected(self):
        snapshot = self.corrupt()
        rows = self.terminal_rows(snapshot)
        self.put_rows(snapshot, 'JUDGE_TERMINAL_JOURNAL.jsonl', rows[:-1])
        self.reject(snapshot)

    def test_06_duplicate_terminal_rejected(self):
        snapshot = self.corrupt()
        rows = self.terminal_rows(snapshot)
        if len(rows) < 2:
            self.skipTest('Fewer than two valid terminals')
        rows[1] = copy.deepcopy(rows[0])
        self.put_rows(snapshot, 'JUDGE_TERMINAL_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_07_returned_model_mutation_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        self.first_return(rows)['returned_model'] = 'synthetic-wrong-model'
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_08_payload_hash_mutation_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        rows[0]['provider_payload_sha256'] = '0' * 64
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_09_invalid_token_arithmetic_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        self.first_return(rows)['total_tokens'] += 1
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_10_retry_after_valid_return_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        accepted = self.first_return(rows)
        if accepted.get('failure_code') is not None:
            self.skipTest('First return is not valid')
        duplicate = copy.deepcopy(rows[0])
        duplicate['attempt_number'] = 2
        duplicate['judge_calls_started'] = 2
        rows.insert(rows.index(accepted) + 1, duplicate)
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_11_retry_without_invalid_return_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        duplicate = copy.deepcopy(rows[0])
        duplicate['attempt_number'] = 2
        duplicate['judge_calls_started'] = 2
        rows.insert(1, duplicate)
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_12_score_na_inconsistency_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        event = self.first_return(rows)
        raw = audit.strict_json(event['raw_response_content'])
        raw['clarity'] = 'NA'
        event['raw_response_content'] = audit.canonical(raw).decode()
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_13_local_mean_mutation_rejected(self):
        snapshot = self.corrupt()
        rows = self.terminal_rows(snapshot)
        rows[0]['parsed_semantic_result']['overall_applicable_mean'] += 0.125
        self.put_rows(snapshot, 'JUDGE_TERMINAL_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_14_empty_rationale_rejected(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        event = self.first_return(rows)
        raw = audit.strict_json(event['raw_response_content'])
        raw['criterion_rationales']['clarity'] = '  '
        event['raw_response_content'] = audit.canonical(raw).decode()
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_15_hidden_identity_field_rejected(self):
        snapshot = self.corrupt()
        rows = self.terminal_rows(snapshot)
        rows[0]['condition_id'] = 'synthetic-hidden-identity'
        self.put_rows(snapshot, 'JUDGE_TERMINAL_JOURNAL.jsonl', rows)
        self.reject(snapshot)

    def test_16_credential_like_value_rejected(self):
        with self.assertRaises(audit.AuditError):
            audit.scan_secrets(('s' + 'k-' + 'A' * 32).encode())

    def test_17_subfifteen_timestamp_is_disclosed_without_tolerance(self):
        snapshot = self.corrupt()
        rows = self.attempt_rows(snapshot)
        starts = [row for row in rows if row['event'] == 'ATTEMPT_STARTED' and row['attempt_number'] == 1]
        if len(starts) < 2:
            self.skipTest('Fewer than two initial requests')
        second_id = starts[1]['logical_judge_request_id']
        timestamp = (datetime.fromisoformat(starts[0]['request_started_at_utc']) + timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')
        for event in rows:
            if event['logical_judge_request_id'] == second_id and event['attempt_number'] == 1:
                event['request_started_at_utc'] = timestamp
        self.put_rows(snapshot, 'JUDGE_ATTEMPT_JOURNAL.jsonl', rows)
        facts, _, _ = audit.audit_snapshot(snapshot)
        self.assertEqual(facts['audit_status'], 'QUALIFIED_PACING_EVIDENCE_LIMITATION')
        self.assertFalse(facts['pacing_evidence']['journal_utc_intervals_all_at_least_15_seconds'])
        self.assertTrue(facts['pacing_evidence']['no_tolerance_added_to_15_second_requirement'])
        self.assertEqual(facts['pacing_evidence']['journal_utc_intervals_below_15_seconds'][0]['observed_utc_interval_seconds'], 1.0)

    def test_18_offline_audit_preserves_durable_output_bytes(self):
        before = {name: audit.sha(raw) for name, raw in self.snapshot['output'].items()}
        audit.audit_snapshot(self.snapshot)
        after = {p.name: audit.sha(p.read_bytes()) for p in (self.artifact / 'execution_output_v1').iterdir()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main(verbosity=2)
