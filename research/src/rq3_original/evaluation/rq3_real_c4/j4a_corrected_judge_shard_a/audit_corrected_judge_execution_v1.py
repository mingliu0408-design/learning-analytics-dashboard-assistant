#!/usr/bin/env python3
"""Read-only audit of the one authorized corrected Judge R4 shard A.

No transport is constructed and no execution/resume API is invoked. The exact
selected external ZIP is read in memory, never extracted. The parsed-set digest
is SHA-256 of canonical JSON bytes of the ordered terminal semantic-result list.
Only per-result local means are verified; no cross-result score is computed.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import stat
import sys
import types
from unittest.mock import patch
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
WORKTREE = Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-real-j4a-corrected-judge-a')
BRANCH = 'research/rq3-real-c4-j4a-corrected-judge-a'
START_HEAD = '9d300c1efd1575005d4673c7cb6297a1bfd6a3ca'
PACKAGE_ZIP = Path('/Users/liuming/Downloads/C4_REAL_CORRECTED_JUDGE_SHARD_A_EXECUTION_PACKAGE_R4_2026-09-02.zip')
PACKAGE_SHA = '5ad7494f179dfe0b817cdbc0b2152e0160fce87bd6bf84ee1eac59be70cf64bb'
MANIFEST_SHA = '8c6bd146cdc20b2ea8dcc14b41967e256afda36ee605c39c4522f9386d4a2fc3'
AUTH_SHA = 'f159cbce6316aaa3c2efd46f93d4b3195ce322b7af23dad19003b7a85375b4f3'
PACKAGE_ID = 'C4_REAL_CORRECTED_JUDGE_SHARD_A_R4_20260902'
AUTH_ID = 'RQ3-REAL-C4-J4A-CORRECTED-JUDGE-20260902'
MODEL = 'gpt-4.1-2025-04-14'
RETRYABLE = ('INVALID_JSON', 'STRICT_SCHEMA_VALIDATION_FAILED', 'APPLICABILITY_CONTRACT_VIOLATION')
EXPECTED_RUNTIME = {'python_executable': '/opt/anaconda3/bin/python3', 'python_version': '3.13.5', 'openai_sdk_version': '1.109.1'}
PINNED_MEMBERS = {
    'APPLICABILITY_CONTRACT_V2.json': '9f7c9a19670ab2da7c99f5b4f19dcd73d7100792b30b9b60e6b9906bccc16557',
    'BLINDED_JUDGE_REQUESTS.jsonl': MANIFEST_SHA,
    'EXECUTION_CONTRACT.json': 'cfeb952291827acd06da1c35bdb9cbb3b16fdb6ac855e8049706bc3515ec11c5',
    'JUDGE_CONFIGURATION.json': '2ff37c67b4817b226f92c93d3d8bd910b2d9784289273f0a607ea09119c7eb7a',
    'JUDGE_PROMPT.txt': '0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e',
    'JUDGE_SCHEMA.json': '5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a',
    'PACKAGE_SOURCE_HASHES.json': 'af6d67acf7be6f97cf6efe7e624071089a1a3246e1dba4a4d7ced5d11f3b85ab',
    'PRIMARY_RUBRIC.json': 'be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350',
    'README.md': 'f0f292958e100eb7f999229265f712274486f171cac8b3a5a1b9130ddc81a419',
    'judge_execution_runner_v3.py': '6fed067756d90cc8cddf82bab3cb0770423d200edabd3590a73b48c2b81fa6f2',
    'judge_result_parser_v3.py': '7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb',
    'test_package.py': 'f8323623a855ceac83c4a26d94aaab83a4c4c3b560d0e5113368299ca5d34323',
    'validate_package.py': '12ac29b84e390860d3f030887f013925c0355be8bad2a0cc3c81b3254208c377',
}
OUTPUT_NAMES = {
    'JUDGE_ATTEMPT_JOURNAL.jsonl', 'JUDGE_TERMINAL_JOURNAL.jsonl',
    'JUDGE_ERROR_REGISTRY.jsonl', 'JUDGE_STATUS_JOURNAL.jsonl',
    'JUDGE_PREFLIGHT_START_RECEIPT.json', 'JUDGE_EXECUTION_STATUS.json',
}
HIDDEN_KEYS = {'condition_id', 'condition_name', 'mode', 'mode_id', 'scenario_id',
               'scenario_family_id', 'family_id', 'route', 'route_signature', 'gold',
               'expected_winner', 'human_rating', 'prior_rating', 'prior_rationale'}
SECRET_PATTERNS = (
    re.compile(rb'\bsk-[A-Za-z0-9_-]{16,}\b'),
    re.compile(rb'Bearer\s+[A-Za-z0-9_.-]{16,}', re.I),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
)
IDENTITY_RE = re.compile(r'\bC[0-9]+_[A-Z][A-Z_]+\b|\bU[0-9]{3}\b')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def read_jsonl(path):
    raw = Path(path).read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('incomplete durable JSONL line')
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def hidden_identity(value):
    if isinstance(value, dict):
        return bool(set(value) & HIDDEN_KEYS) or any(hidden_identity(v) for v in value.values())
    if isinstance(value, list):
        return any(hidden_identity(v) for v in value)
    return isinstance(value, str) and bool(IDENTITY_RE.search(value))


def load_frozen_support():
    if digest(PACKAGE_ZIP.read_bytes()) != PACKAGE_SHA:
        raise ValueError('selected package SHA-256 mismatch')
    with ZipFile(PACKAGE_ZIP) as archive:
        infos = archive.infolist()
        if len(infos) != 13 or {i.filename for i in infos} != set(PINNED_MEMBERS):
            raise ValueError('exact 13-member package allowlist mismatch')
        if any(i.is_dir() or stat.S_ISLNK(i.external_attr >> 16) for i in infos):
            raise ValueError('nonregular ZIP member')
        if archive.testzip() is not None:
            raise ValueError('package CRC mismatch')
        members = {i.filename: archive.read(i.filename) for i in infos}
    if {name: digest(raw) for name, raw in members.items()} != PINNED_MEMBERS:
        raise ValueError('pinned member hash mismatch')
    modules = {}
    for name in ('validate_package', 'judge_result_parser_v3', 'judge_execution_runner_v3'):
        module = types.ModuleType(name)
        module.__file__ = str(PACKAGE_ZIP) + '::' + name + '.py'
        sys.modules[name] = module
        exec(compile(members[name + '.py'], module.__file__, 'exec'), module.__dict__)
        modules[name] = module
    validation = modules['validate_package'].validate_members(members, package_zip_sha256=PACKAGE_SHA)
    return members, modules, validation


def no_network(*args, **kwargs):
    raise AssertionError('OFFLINE_AUDIT_NETWORK_PROHIBITED')


def collect_audit(artifact_dir=HERE):
    """Return evidence checks without altering any artifact or source member."""
    artifact_dir = Path(artifact_dir)
    members, modules, validation = load_frozen_support()
    validator = modules['validate_package']
    parser = modules['judge_result_parser_v3']
    runner = modules['judge_execution_runner_v3']
    rows = runner.load_jsonl_bytes(members['BLINDED_JUDGE_REQUESTS.jsonl'])
    config = json.loads(members['JUDGE_CONFIGURATION.json'])
    contract = json.loads(members['EXECUTION_CONTRACT.json'])
    auth_path = artifact_dir / 'judge_execution_authorization_v1.json'
    auth = validator.strict_json(auth_path.read_bytes())
    runner._validate_authorization_record(auth, package_validation=validation, package_zip_sha256=PACKAGE_SHA)
    gates = read_json(artifact_dir / 'starting_and_package_gates_v1.json')
    runtime = read_json(artifact_dir / 'runtime_preflight_v1.json')
    invocation = read_json(artifact_dir / 'execution_invocation_v1.json')
    output = artifact_dir / 'execution_output_v1'
    attempts = read_jsonl(output / 'JUDGE_ATTEMPT_JOURNAL.jsonl')
    terminals = read_jsonl(output / 'JUDGE_TERMINAL_JOURNAL.jsonl')
    errors = read_jsonl(output / 'JUDGE_ERROR_REGISTRY.jsonl')
    status_events = read_jsonl(output / 'JUDGE_STATUS_JOURNAL.jsonl')
    receipt = read_json(output / 'JUDGE_PREFLIGHT_START_RECEIPT.json')
    status = read_json(output / 'JUDGE_EXECUTION_STATUS.json')
    checks = {}

    def check(name, passed):
        if name in checks:
            raise ValueError('duplicate audit check name')
        checks[name] = bool(passed)

    check('package_zip_hash', digest(PACKAGE_ZIP.read_bytes()) == PACKAGE_SHA)
    check('exact_13_pinned_member_hashes', {k: digest(v) for k, v in members.items()} == PINNED_MEMBERS)
    check('frozen_package_validation', validation['status'] == 'PASS')
    check('selected_shard_and_request_count', validation['shard_id'] == 'A' and len(rows) == 39 and validation['request_count'] == 39)
    check('maximum_physical_attempts_contract', config['maximum_physical_attempts'] == contract['maximum_physical_attempts'] == 78)
    check('phase_b_entry_receipt_binding', contract['phase_b_entry_receipt_sha256'] == 'abf6fd158e68a406008bee838a74adc9d0cc3e87feef0ad649ea790c0feb44e4')
    check('starting_directory_branch_head', gates['working_directory'] == str(WORKTREE) and gates['branch'] == BRANCH and gates['starting_head'] == START_HEAD)
    check('starting_worktree_clean', gates['starting_git_status_short'] == gates['starting_git_status_porcelain_untracked_all'] == '')
    check('fresh_extraction_exactly_once', gates['selected_external_package_extractions'] == 1 and gates['fresh_extraction_directory'].startswith('/private/tmp/c4-real-j4a-r4.'))
    check('zip_directory_tests_pass_before_execution', len(gates['package_validation_records']) == 3 and all(v['exit_code'] == 0 for v in gates['package_validation_records']) and gates['package_test_count'] == 22)
    check('other_corrected_packages_not_accessed', gates['other_corrected_packages_accessed'] is False and invocation['additional_shards_dispatched'] == 0)
    check('authorization_exact_11_fields', set(auth) == runner.AUTHORIZATION_FIELDS and len(auth) == 11)
    check('authorization_identity_and_status', auth['authorization_id'] == AUTH_ID and auth['authorized_by'] == 'Ming Liu' and auth['status'] == 'AUTHORIZED')
    check('authorization_timestamp_format', bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', auth['authorized_at_utc'])))
    check('authorization_sha256', digest(auth_path.read_bytes()) == AUTH_SHA == runtime['authorization_sha256'])
    check('preflight_runtime_identity', all(runtime['runtime'].get(k) == v for k, v in EXPECTED_RUNTIME.items()))
    check('preflight_zero_network', runtime['status'] == 'PASS' and runtime['network_operations'] == runtime['provider_calls'] == 0)
    check('preflight_client_closed', runtime['client_closed_cleanly'] is True)
    check('preflight_key_presence_only', runtime['runtime']['api_key_presence_checked_only'] is True and runtime['runtime']['api_key_value_recorded'] is False)
    check('preflight_zero_sdk_retries', runtime['client_configuration']['client_max_retries'] == 0)
    check('preflight_all_timeout_components_120', runtime['client_configuration']['timeout_components_seconds'] == runtime['underlying_httpx_timeout_components_seconds'] == {k: 120.0 for k in ('connect', 'read', 'write', 'pool')})
    check('openai_chat_completions_endpoint', runtime['endpoint'] == 'https://api.openai.com/v1/chat/completions')
    check('no_dependency_changes', runtime['dependency_installations'] == runtime['dependency_modifications'] == 0)
    check('runner_invoked_once', invocation['runner_invocation_count'] == 1 and invocation['automatic_resume_permitted'] is False)
    check('output_leaf_absent_and_runner_created', gates['output_leaf_absent_before_authorization'] is True and runtime['output_leaf_absent'] is True and invocation['output_leaf_created_by'] == 'FROZEN_RUNNER_ONLY')
    check('output_exact_durable_file_set', {p.name for p in output.iterdir()} == OUTPUT_NAMES and all(p.is_file() and not p.is_symlink() for p in output.iterdir()))
    check('runner_receipt_bindings', all(receipt.get(k) == auth[k] for k in ('authorization_id', 'authorized_by', 'authorized_at_utc', 'package_id', 'shard_id', 'request_count', 'maximum_physical_attempts', 'package_zip_sha256', 'blinded_judge_manifest_sha256')))
    check('runner_receipt_before_transport', receipt['judge_calls_at_receipt_write'] == 0 and receipt['runtime_constructed_at_receipt_write'] is False and receipt['client_constructed_at_receipt_write'] is False)
    check('status_event_sequence', [x['status'] for x in status_events] == ['PREFLIGHT_STARTED', 'RUNTIME_VALIDATED', 'CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED', status['status']])
    runtime_events = [x for x in status_events if x['status'] == 'RUNTIME_VALIDATED']
    client_events = [x for x in status_events if x['status'] == 'CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED']
    check('runner_runtime_identity', len(runtime_events) == 1 and all(runtime_events[0]['runtime'].get(k) == v for k, v in EXPECTED_RUNTIME.items()))
    check('runner_client_transport_identity', len(client_events) == 1 and client_events[0]['client_configuration'] == runtime['client_configuration'] and client_events[0]['judge_calls'] == 0)
    starts = [x for x in attempts if x['event'] == 'ATTEMPT_STARTED']
    returned = [x for x in attempts if x['event'] == 'ATTEMPT_RETURNED']
    initial = [x for x in starts if x['attempt_number'] == 1]
    retried = [x for x in starts if x['attempt_number'] == 2]
    request_by_id = {r['logical_judge_request_id']: r for r in rows}
    key = lambda r: (r['logical_judge_request_id'], r.get('attempt_number', r.get('physical_attempts')))
    starts_by_key = {key(r): r for r in starts}
    returned_by_key = {key(r): r for r in returned}
    grouped = defaultdict(list)
    for event in starts:
        grouped[event['logical_judge_request_id']].append(event)
    bindings_ok = True
    for event in attempts + terminals:
        source = request_by_id.get(event['logical_judge_request_id'])
        bindings_ok &= source is not None and all(event.get(k) == source[k] for k in ('logical_order', 'logical_judge_request_id', 'judge_result_blind_id', 'provider_payload_sha256'))
    check('all_journal_bindings_and_payload_hashes', bindings_ok)
    check('all_payload_hashes_recomputed', all(digest(canonical(r['provider_payload'])) == r['provider_payload_sha256'] for r in rows))
    check('initial_order_is_frozen_prefix', [r['logical_judge_request_id'] for r in initial] == [r['logical_judge_request_id'] for r in rows[:len(initial)]])
    check('initial_ids_unique', len(initial) == len({r['logical_judge_request_id'] for r in initial}))
    check('attempt_keys_unique', len(starts_by_key) == len(starts) and len(returned_by_key) == len(returned))
    check('attempts_one_initial_one_optional_retry', all([x['attempt_number'] for x in events] in ([1], [1, 2]) for events in grouped.values()))
    check('attempt_events_only_started_returned', all(x['event'] in ('ATTEMPT_STARTED', 'ATTEMPT_RETURNED') for x in attempts))
    check('returned_attempts_have_starts', all(key(r) in starts_by_key and r['request_started_at_utc'] == starts_by_key[key(r)]['request_started_at_utc'] for r in returned))
    sequence_ok = True
    pending = None
    for event in attempts:
        if event['event'] == 'ATTEMPT_STARTED':
            sequence_ok &= pending is None
            pending = key(event)
        else:
            sequence_ok &= pending == key(event)
            pending = None
    check('durable_attempt_event_order', sequence_ok and (pending is None or status['status'] == 'INCOMPLETE'))
    check('physical_call_counters', status['physical_attempts'] == status['judge_calls'] == len(starts) and [r['judge_calls_started'] for r in starts] == list(range(1, len(starts) + 1)))
    check('physical_attempt_cap_78', len(starts) <= 78 and len(initial) <= 39)
    check('retry_only_after_eligible_failure', all(returned_by_key.get((r['logical_judge_request_id'], 1), {}).get('failure_code') in RETRYABLE for r in retried))
    check('retry_hashes_byte_identical', all(r['provider_payload_sha256'] == starts_by_key[(r['logical_judge_request_id'], 1)]['provider_payload_sha256'] for r in retried))
    check('no_retry_after_valid_result', all(returned_by_key.get((r['logical_judge_request_id'], 1), {}).get('parsed_semantic_result') is None for r in retried))
    intervals = [(utc(b['request_started_at_utc']) - utc(a['request_started_at_utc'])).total_seconds() for a, b in zip(initial, initial[1:])]
    check('initial_start_intervals_at_least_15_seconds', all(v >= 15.0 for v in intervals))
    check('all_attempt_timeouts_120', all(x['request_timeout_seconds'] == 120.0 for x in attempts + terminals) and status['request_timeout_seconds'] == receipt['request_timeout_seconds'] == 120.0)
    check('timestamps_ordered', all(utc(r['response_finished_at_utc']) >= utc(r['request_started_at_utc']) and r['latency_ms'] >= 0 for r in returned) and utc(auth['authorized_at_utc']) <= utc(runtime['timestamp_utc']) <= utc(receipt['timestamp_utc']) <= utc(status['timestamp_utc']))
    check('terminal_request_ids_unique', len(terminals) == len({x['logical_judge_request_id'] for x in terminals}))
    check('terminal_result_ids_unique', len(terminals) == len({x['judge_result_blind_id'] for x in terminals}))
    check('terminal_order_is_frozen_prefix', [x['logical_judge_request_id'] for x in terminals] == [r['logical_judge_request_id'] for r in rows[:len(terminals)]])
    check('all_terminals_valid_status', all(x['terminal_status'] == 'VALID_JUDGE_RESULT' for x in terminals))
    check('returned_model_exact', all(x['returned_model'] == MODEL for x in returned + terminals))
    check('frozen_provider_parameters', all(r['provider_payload']['model'] == MODEL and r['provider_payload']['temperature'] == 0 and r['provider_payload']['max_tokens'] == 2048 and r['provider_payload']['stream'] is False and 'tools' not in r['provider_payload'] for r in rows))
    parsed_ok = invalid_labels_ok = terminal_matches = applicability_ok = True
    rationales_ok = evidence_ok = unsupported_ok = local_means_ok = True
    for event in returned:
        source = request_by_id[event['logical_judge_request_id']]
        applicability = runner._extract_applicability(source['provider_payload'])
        try:
            reparsed = parser.parse_judge_result(event['raw_response_content'], applicability, expected_judge_result_blind_id=source['judge_result_blind_id'])
        except parser.JudgeResultError as exc:
            invalid_labels_ok &= parser.retryable_failure_code(exc) == event.get('failure_code') and event.get('parsed_semantic_result') is None
        else:
            parsed_ok &= event.get('failure_code') is None and event['parsed_semantic_result'] == reparsed
    for terminal in terminals:
        source = request_by_id[terminal['logical_judge_request_id']]
        event = returned_by_key.get(key(terminal))
        if event is None:
            terminal_matches = False
            continue
        terminal_matches &= event.get('failure_code') is None and event['parsed_semantic_result'] == terminal['parsed_semantic_result'] and terminal['terminal_at_utc'] == event['response_finished_at_utc']
        terminal_matches &= all(terminal[k] == event[k] for k in ('prompt_tokens', 'cached_input_tokens', 'completion_tokens', 'total_tokens', 'returned_model', 'provider_response_id', 'finish_reason', 'system_fingerprint'))
        applicability = runner._extract_applicability(source['provider_payload'])
        value = terminal['parsed_semantic_result']
        reparsed = parser.parse_judge_result(event['raw_response_content'], applicability, expected_judge_result_blind_id=source['judge_result_blind_id'])
        parsed_ok &= reparsed == value and value['response_blind_id'] == source['judge_result_blind_id']
        for criterion, field in parser.SCORE_FIELDS.items():
            score = value[field]
            applicability_ok &= (type(score) is int and 1 <= score <= 5) if applicability['criteria'][criterion] else score == 'NA'
        rationales_ok &= set(value['criterion_rationales']) == set(parser.SCORE_FIELDS.values()) and all(isinstance(v, str) and v.strip() for v in value['criterion_rationales'].values())
        evidence_ok &= type(value['evidence_faithfulness']) is int and 1 <= value['evidence_faithfulness'] <= 5
        unsupported_ok &= type(value['unsupported_claim_count']) is int and value['unsupported_claim_count'] >= 0
        local_means_ok &= value['overall_applicable_mean'] == parser.recompute_overall_applicable_mean(value, applicability)
    check('all_valid_results_reparse_with_frozen_parser_v3', parsed_ok)
    check('invalid_output_labels_match_parser_v3', invalid_labels_ok)
    check('terminals_match_successful_returned_attempts', terminal_matches)
    check('score_na_values_match_frozen_applicability', applicability_ok)
    check('rationales_nonempty_unchanged', rationales_ok)
    check('evidence_faithfulness_valid', evidence_ok)
    check('unsupported_claim_count_nonnegative', unsupported_ok)
    check('per_result_local_mean_exact', local_means_ok)
    check('provider_tokens_nonnegative_integers', all(type(r[k]) is int and r[k] >= 0 for r in returned for k in ('prompt_tokens', 'cached_input_tokens', 'completion_tokens', 'total_tokens')))
    check('provider_token_arithmetic', all(r['total_tokens'] == r['prompt_tokens'] + r['completion_tokens'] and r['cached_input_tokens'] <= r['prompt_tokens'] for r in returned))
    check('runner_status_counts', status['request_count'] == 39 and status['valid_terminal_count'] == len(terminals) and status['package_id'] == PACKAGE_ID and status['shard_id'] == 'A')
    complete = status['status'] == 'COMPLETE'
    check('status_complete_or_incomplete', status['status'] in ('COMPLETE', 'INCOMPLETE'))
    check('complete_has_full_coverage_no_errors', not complete or len(terminals) == len(initial) == 39 and len(starts) == len(returned) and not errors)
    check('incomplete_requires_new_authorization', complete or status['corrected_execution_requires_new_direct_authorization'] is True)
    check('no_automatic_resume', status['automatic_resume'] is False and receipt['automatic_resume'] is False)
    check('error_policy_stops_entire_shard', all(e['terminal_policy'] == 'STOP_ENTIRE_SHARD' for e in errors))
    second_invalid = [r for r in returned if r['attempt_number'] == 2 and r.get('failure_code') in RETRYABLE]
    check('second_invalid_stops_without_next_request', not second_invalid or not complete and key(starts[-1]) == key(second_invalid[-1]))
    check('unreturned_provider_attempt_is_last_and_not_retried', len(starts) == len(returned) or not complete and len(starts) == len(returned) + 1 and key(starts[-1]) not in returned_by_key)
    check('no_condition_mode_identity_in_results', not any(hidden_identity(r.get('parsed_semantic_result')) or hidden_identity(r['raw_response_content']) for r in returned))
    output_hashes = {name: digest((output / name).read_bytes()) for name in sorted(OUTPUT_NAMES)}
    parsed_values = [r['parsed_semantic_result'] for r in terminals]
    parsed_sha = digest(canonical(parsed_values))
    artifact_files = [p for p in artifact_dir.rglob('*') if p.is_file()]
    secret_files = [str(p.relative_to(artifact_dir)) for p in artifact_files if any(pattern.search(p.read_bytes()) for pattern in SECRET_PATTERNS)]
    check('secret_absence_artifact_scan', not secret_files)
    check('no_bytecode_or_symlink_artifacts', not any(p.suffix == '.pyc' or '__pycache__' in p.parts or p.is_symlink() for p in artifact_dir.rglob('*')))
    extracted = Path(gates['fresh_extraction_directory'])
    check('fresh_extraction_members_remain_unchanged', {p.name for p in extracted.iterdir()} == set(PINNED_MEMBERS) and all(digest((extracted / name).read_bytes()) == sha for name, sha in PINNED_MEMBERS.items()))
    invalid_counts = {code: sum(r.get('failure_code') == code for r in returned) for code in RETRYABLE}
    token_totals = {k: sum(r[k] for r in returned) for k in ('prompt_tokens', 'cached_input_tokens', 'completion_tokens', 'total_tokens')}
    error_categories = dict(Counter(str(e.get('error_category')) for e in errors))
    error_codes = dict(Counter(str(e.get('error_code')) for e in errors))
    nonparser_errors = [e for e in errors if e.get('error_category') not in RETRYABLE]
    interrupt_errors = [e for e in errors if e.get('error_category') == 'KeyboardInterrupt']
    provider_errors = [e for e in nonparser_errors if e.get('error_category') != 'KeyboardInterrupt']
    incident_path = artifact_dir / 'pacing_contract_incident_v1.json'
    incident = read_json(incident_path) if incident_path.exists() else None
    observed_violations = [{'previous_logical_order': a['logical_order'], 'next_logical_order': b['logical_order'],
                           'previous_started_at_utc': a['request_started_at_utc'], 'next_started_at_utc': b['request_started_at_utc'],
                           'observed_interval_seconds': interval, 'shortfall_seconds': round(15.0 - interval, 6)}
                          for a, b, interval in zip(initial, initial[1:], intervals) if interval < 15.0]
    if incident is not None:
        check('durable_output_matches_immediate_stop_snapshot', incident['durable_output_sha256'] == output_hashes)
        check('pacing_incident_matches_observed_intervals', incident['pacing_violations'] == observed_violations)
        check('agent_interrupt_transparently_disclosed', incident['stop_signal'] == 'SIGINT' and incident['interruption_initiated_by'] == 'EXECUTING_AGENT_FAIL_CLOSED' and len(interrupt_errors) == 1 and not complete)
        check('incomplete_usage_marked_unobserved', len(starts) == len(returned) + 1 and key(starts[-1]) not in returned_by_key and status['corrected_execution_requires_new_direct_authorization'] is True)
    failed_checks = [k for k, passed in checks.items() if not passed]
    return {
        'schema_version': 'c4-real-corrected-judge-execution-audit-v1',
        'audit_timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'audit_status': 'PASS' if not failed_checks else 'FAIL',
        'execution_status': status['status'],
        'workflow_status': 'CORRECTED_JUDGE_EXECUTION_COMPLETE' if complete else 'CORRECTED_JUDGE_EXECUTION_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION',
        'package_id': PACKAGE_ID, 'shard_id': 'A',
        'working_directory': str(WORKTREE), 'branch': BRANCH, 'starting_head': START_HEAD,
        'package_zip_path': str(PACKAGE_ZIP), 'package_zip_sha256': PACKAGE_SHA,
        'member_sha256': PINNED_MEMBERS, 'package_validation': validation,
        'authorization_sha256': AUTH_SHA,
        'runtime': runtime['runtime'], 'client_configuration': runtime['client_configuration'],
        'logical_requests_frozen': 39, 'logical_requests_started': len(initial),
        'physical_attempts': len(starts), 'returned_attempts': len(returned),
        'retries': len(retried), 'valid_terminal_count': len(terminals),
        'missing_valid_result_count': 39 - len(terminals),
        'duplicate_terminal_request_ids': len(terminals) - len({r['logical_judge_request_id'] for r in terminals}),
        'duplicate_terminal_result_ids': len(terminals) - len({r['judge_result_blind_id'] for r in terminals}),
        'invalid_output_counts': invalid_counts,
        'unresolved_error_count': len(errors), 'nonparser_error_count': len(nonparser_errors),
        'error_categories': error_categories, 'error_codes': error_codes,
        'agent_interrupt_count': len(interrupt_errors),
        'observed_provider_error_event_count': len(provider_errors),
        'observed_error_counts': {
            'provider': len(provider_errors),
            'refusal': sum('REFUSAL' in str(e.get('error_category', '')).upper() for e in errors),
            'returned_model_mismatch': sum(e.get('error_category') == 'RETURNED_MODEL_MISMATCH' for e in errors),
            'timeout': sum('TIMEOUT' in str(e.get('error_category', '')).upper() for e in errors),
            'billing': sum(e.get('error_code') in ('insufficient_quota', 'billing_hard_limit_reached') for e in errors),
            'rate_limit': sum(e.get('error_code') == 'rate_limit_exceeded' for e in errors),
            'authentication': sum(e.get('error_category') == 'AuthenticationError' for e in errors),
            'permission': sum(e.get('error_category') == 'PermissionDeniedError' for e in errors),
            'transport': sum(e.get('error_category') == 'APIConnectionError' for e in errors),
            'agent_interrupt': len(interrupt_errors),
        },
        'interrupted_request_provider_outcome': 'UNOBSERVED_NO_ADDITIONAL_PROVIDER_CALL_AUTHORIZED' if interrupt_errors else None,
        'error_subtype_observability': 'NO_ERRORS' if not errors else 'USE_DURABLE_CATEGORY_AND_CODE; DO_NOT_INFER_MISSING_EXCEPTION_DETAIL',
        'returned_models': sorted({r['returned_model'] for r in returned}),
        'token_totals_all_returned_attempts': token_totals,
        'token_usage_complete_for_all_physical_attempts': len(starts) == len(returned),
        'initial_start_intervals_seconds': intervals,
        'minimum_observed_initial_start_interval_seconds': min(intervals) if intervals else None,
        'pacing_violations': observed_violations,
        'terminal_journal_sha256': output_hashes['JUDGE_TERMINAL_JOURNAL.jsonl'],
        'parsed_result_set_sha256': parsed_sha,
        'parsed_result_set_hash_definition': 'SHA256(canonical UTF-8 JSON array of parsed_semantic_result objects in frozen logical terminal order; sorted keys; compact separators; no trailing newline)',
        'durable_output_sha256': output_hashes,
        'package_tests_passed_before_execution': 22,
        'secret_scan_flagged_files': secret_files,
        'zero_scope_confirmations': {
            'other_corrected_shard_execution': 0, 'old_package_execution': 0,
            'retained_existing_judge_result_reruns': 0, 'response_generation': 0,
            'human_rating': 0, 'condition_or_mode_unblinding': 0,
            'mode_level_scoring': 0, 'system_comparisons': 0, 'agreement_calculation': 0,
            'statistical_analysis': 0, 'final_judge_integration': 0,
            'rag_memory_planner_evidence_synthesis_p3_streamlit_rq2_execution': 0,
            'restricted_internal_access': 0, 'offline_audit_provider_calls': 0,
        },
        'check_count': len(checks), 'passed_check_count': sum(checks.values()),
        'failed_checks': failed_checks, 'checks': checks,
    }


def main():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument('--artifact-dir', type=Path, default=HERE)
    args = command.parse_args()
    with patch.object(socket.socket, 'connect', no_network), patch.object(socket.socket, 'connect_ex', no_network), patch.object(socket, 'create_connection', no_network):
        audit = collect_audit(args.artifact_dir)
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if audit['audit_status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
