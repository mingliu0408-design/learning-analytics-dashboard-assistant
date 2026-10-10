#!/usr/bin/env python3
"""Read-only continuation/completeness audit and offline artifact tests.

--audit prints the evidence audit. No Provider client is constructed and no
Runner execution/resume function is called. Canonical membership is determined
only by frozen identity, original order and authorized output source, never by
score value. Only individual-result applicability means are verified.
"""

from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import types
import unittest
from unittest.mock import patch
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
SOURCE_SHA = '5ad7494f179dfe0b817cdbc0b2152e0160fce87bd6bf84ee1eac59be70cf64bb'
PACKAGE_SHA = '2a4c0968208aa346cb799e51540dfc6af45f3c07113a1d79817bbbca52601e7c'
AUTH_SHA = 'a6b62bc9d2a1e9be783210d8c2a3da01f8e5de93423a37e2d94ad9070f06fc15'
ROW_SHA = '55954a66735d98b5247fa7159ce9390bdf73a0473be12ef63d51c2fe528c6090'
REQUEST_ID = 'C4J4-B56DBB266EAC9B4CD8557941'
RESULT_ID = 'R3B-C1E425465D569BD2B1C6'
PAYLOAD_SHA = '507b28fe2fa7f6f9fa63258192c55e290afea1c1ee5ce4925948321c26b3b472'
MODEL = 'gpt-4.1-2025-04-14'
RETRYABLE = ('INVALID_JSON', 'STRICT_SCHEMA_VALIDATION_FAILED', 'APPLICABILITY_CONTRACT_VIOLATION')
SECRET_RE = re.compile(rb'\bsk-[A-Za-z0-9_-]{16,}\b|Bearer\s+[A-Za-z0-9_.-]{16,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', re.I)
HIDDEN_KEYS = {'scenario_id', 'family_id', 'scenario_family_id', 'mode', 'mode_id', 'condition_id', 'condition_name', 'route_signature', 'gold', 'human_rating', 'expected_winner'}
HIDDEN_RE = re.compile(r'\bC[0-9]+_[A-Z][A-Z_]+\b|\bU[0-9]{3}\b')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_bytes())


def read_lines(path):
    raw = Path(path).read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('partial durable journal line')
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def no_network(*args, **kwargs):
    raise AssertionError('OFFLINE_TEST_NETWORK_PROHIBITED')


def network_guard():
    stack = ExitStack()
    for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'), (socket, 'create_connection')):
        stack.enter_context(patch.object(obj, name, no_network))
    return stack


def hidden(value):
    if isinstance(value, dict):
        return bool(set(value) & HIDDEN_KEYS) or any(hidden(v) for v in value.values())
    if isinstance(value, list):
        return any(hidden(v) for v in value)
    return isinstance(value, str) and bool(HIDDEN_RE.search(value))


def read_zip(path, expected_sha):
    if sha(Path(path).read_bytes()) != expected_sha:
        raise ValueError('frozen ZIP hash mismatch')
    with ZipFile(path) as archive:
        if len(archive.infolist()) != 13 or len(set(archive.namelist())) != 13 or archive.testzip() is not None:
            raise ValueError('ZIP member count/CRC mismatch')
        return {name: archive.read(name) for name in archive.namelist()}


def frozen_module(name, raw):
    module = types.ModuleType(name)
    module.__file__ = 'VERIFIED_FROZEN_ZIP::' + name + '.py'
    sys.modules[name] = module
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module


def collect_audit():
    meta = read_json(HERE / 'order39_continuation_package_metadata_v1.json')
    preservation = read_json(HERE / 'historical_a_preservation_manifest_v1.json')
    original = read_zip(meta['original_package_zip_path'], SOURCE_SHA)
    members = read_zip(meta['package_zip_path'], PACKAGE_SHA)
    assert {name: sha(raw) for name, raw in original.items()} == meta['original_member_sha256']
    assert {name: sha(raw) for name, raw in members.items()} == meta['member_sha256']
    original_validator = frozen_module('original_a_offline_validator', original['validate_package.py'])
    original_validation = original_validator.validate_members(original, package_zip_sha256=SOURCE_SHA)
    validator = frozen_module('validate_package', members['validate_package.py'])
    parser = frozen_module('judge_result_parser_v3', members['judge_result_parser_v3.py'])
    runner = frozen_module('judge_execution_runner_v3', members['judge_execution_runner_v3.py'])
    validation = validator.validate_members(members, package_zip_sha256=PACKAGE_SHA)
    source_lines = original['BLINDED_JUDGE_REQUESTS.jsonl'].splitlines(keepends=True)
    source_rows = [json.loads(raw) for raw in source_lines]
    source_by_id = {row['logical_judge_request_id']: row for row in source_rows}
    row = json.loads(members['BLINDED_JUDGE_REQUESTS.jsonl'])
    authorization = validator.strict_json((HERE / 'judge_execution_authorization_v2.json').read_bytes())
    runner._validate_authorization_record(authorization, package_validation=validation, package_zip_sha256=PACKAGE_SHA)
    preflight = meta['runtime_preflight']
    out1, out2 = HERE / 'execution_output_v1', HERE / 'execution_output_v2'
    old_attempts = read_lines(out1 / 'JUDGE_ATTEMPT_JOURNAL.jsonl')
    old_returns = [e for e in old_attempts if e['event'] == 'ATTEMPT_RETURNED']
    old_starts = [e for e in old_attempts if e['event'] == 'ATTEMPT_STARTED']
    old_terminals = read_lines(out1 / 'JUDGE_TERMINAL_JOURNAL.jsonl')
    old_errors = read_lines(out1 / 'JUDGE_ERROR_REGISTRY.jsonl')
    attempts = read_lines(out2 / 'JUDGE_ATTEMPT_JOURNAL.jsonl')
    starts = [e for e in attempts if e['event'] == 'ATTEMPT_STARTED']
    returns = [e for e in attempts if e['event'] == 'ATTEMPT_RETURNED']
    terminals = read_lines(out2 / 'JUDGE_TERMINAL_JOURNAL.jsonl')
    errors = read_lines(out2 / 'JUDGE_ERROR_REGISTRY.jsonl')
    status_events = read_lines(out2 / 'JUDGE_STATUS_JOURNAL.jsonl')
    receipt = read_json(out2 / 'JUDGE_PREFLIGHT_START_RECEIPT.json')
    status = read_json(out2 / 'JUDGE_EXECUTION_STATUS.json')
    checks = {}

    def check(name, value):
        assert name not in checks
        checks[name] = bool(value)

    check('original_and_r5_packages_valid', original_validation['status'] == validation['status'] == 'PASS')
    check('original_manifest_hash', sha(original['BLINDED_JUDGE_REQUESTS.jsonl']) == '8c6bd146cdc20b2ea8dcc14b41967e256afda36ee605c39c4522f9386d4a2fc3')
    check('source_row_complete_byte_identity', len(source_lines) == 39 and members['BLINDED_JUDGE_REQUESTS.jsonl'] == source_lines[38] and sha(source_lines[38]) == ROW_SHA)
    check('source_order_and_opaque_ids', row['logical_order'] == 39 and row['logical_judge_request_id'] == REQUEST_ID and row['judge_result_blind_id'] == RESULT_ID)
    check('provider_payload_byte_identity', canonical(row['provider_payload']) == canonical(source_rows[38]['provider_payload']) and sha(canonical(row['provider_payload'])) == row['provider_payload_sha256'] == PAYLOAD_SHA)
    check('six_frozen_files_byte_identical', all(members[name] == original[name] for name in validator.FROZEN_MEMBER_SHA256))
    check('r5_package_identity_and_count', validation['package_id'] == 'C4_REAL_CORRECTED_JUDGE_SHARD_A_ORDER39_CONTINUATION_R5_20260902' and validation['shard_id'] == 'A_ORDER39_CONTINUATION' and validation['request_count'] == 1 and validation['maximum_physical_attempts'] == 2)
    check('authorization_exact_eleven_fields', len(authorization) == 11 and set(authorization) == runner.AUTHORIZATION_FIELDS)
    check('authorization_schema_r4_amendment', authorization['schema_version'] == runner.AUTHORIZATION_SCHEMA_VERSION == 'c4-real-corrected-judge-execution-authorization-r4-v1')
    check('authorization_identity_status_and_hash', authorization['authorization_id'] == 'RQ3-REAL-C4-J4A-R1-ORDER39-CONTINUATION-20260902' and authorization['authorized_by'] == 'Ming Liu' and authorization['status'] == 'AUTHORIZED' and sha((HERE / 'judge_execution_authorization_v2.json').read_bytes()) == AUTH_SHA)
    check('exact_r4_environment_gate', meta['execution_contract']['authorization_environment_value'] == runner.AUTHORIZATION_ENVIRONMENT_VALUE == 'AUTHORIZED_C4_REAL_CORRECTED_JUDGE_EXECUTION_R4')
    check('historical_all_eighteen_preserved', len(preservation['before_sha256']) == 18 and preservation['before_sha256'] == preservation['after_sha256'] and all(sha((HERE / name).read_bytes()) == value for name, value in preservation['before_sha256'].items()))
    check('historical_attempt_terminal_hashes', sha((out1 / 'JUDGE_ATTEMPT_JOURNAL.jsonl').read_bytes()) == '51010df4ddf956e3c7d5bf49d9671ae0edc8e84e0ed876fc997c2d15536f8853' and sha((out1 / 'JUDGE_TERMINAL_JOURNAL.jsonl').read_bytes()) == 'fa7c803828fe77fa8cd8f2b95ca24406bfc1081a8df69b2cac2c10f16b527fed')
    historical_parsed_sha = sha(canonical([t['parsed_semantic_result'] for t in old_terminals]))
    check('historical_parsed_set_hash', historical_parsed_sha == '01fef268d5a884ddd2dbec24dc2499aa8e1de95bd4d06d10494f4e6d690554c5')
    check('historical_39_attempts_38_returns_38_terminals', len(old_starts) == 39 and len(old_returns) == len(old_terminals) == 38 and all(e['attempt_number'] == 1 for e in old_starts))
    check('historical_interrupted_attempt_not_a_result', old_starts[-1]['logical_judge_request_id'] == REQUEST_ID and not any(e['logical_judge_request_id'] == REQUEST_ID for e in old_returns + old_terminals) and len(old_errors) == 1 and old_errors[0]['error_category'] == 'KeyboardInterrupt' and old_errors[0]['phase'] == 'PROVIDER_CALL')
    check('historical_status_remains_incomplete', read_json(out1 / 'JUDGE_EXECUTION_STATUS.json')['status'] == 'INCOMPLETE')
    check('historical_pacing_qualified_not_rewritten', meta['historical_pacing_disposition'] == preservation['pacing_disposition'] == 'QUALIFIED_PACING_EVIDENCE_LIMITATION' and preservation['historical_report_rewritten'] is False)
    check('single_request_pacing_not_applicable', meta['continuation_pacing_disposition'] == 'NOT_APPLICABLE_SINGLE_LOGICAL_REQUEST' and sum(e['attempt_number'] == 1 for e in starts) == 1)
    check('runtime_exact', all(preflight['runtime'][k] == v for k, v in {'python_executable': '/opt/anaconda3/bin/python3', 'python_version': '3.13.5', 'openai_sdk_version': '1.109.1'}.items()))
    check('preflight_zero_network_and_client_closed', preflight['provider_calls'] == preflight['network_attempts'] == 0 and preflight['client_closed_cleanly'] is True)
    check('api_key_presence_only_no_dependency_change', preflight['runtime']['api_key_presence_checked_only'] is True and preflight['runtime']['api_key_value_recorded'] is False and preflight['dependency_changes'] == 0)
    check('sdk_retries_zero_all_timeouts_120', preflight['client_configuration']['client_max_retries'] == 0 and preflight['client_configuration']['timeout_components_seconds'] == preflight['httpx_timeout_components_seconds'] == {k: 120.0 for k in ('connect', 'read', 'write', 'pool')})
    check('runner_invoked_once_new_output_only', preservation['continuation_runner_invocations'] == 1 and preservation['continuation_process_exit_code'] == 0 and preflight['output_v2_absent'] is True and meta['execution_invocation_limit'] == 1)
    check('output_bytes_unchanged_since_completion', {p.name: sha(p.read_bytes()) for p in out2.iterdir()} == preservation['continuation_output_sha256_at_completion'])
    check('receipt_binds_authorization', all(receipt[k] == authorization[k] for k in ('authorization_id', 'authorized_by', 'authorized_at_utc', 'package_id', 'shard_id', 'request_count', 'maximum_physical_attempts', 'package_zip_sha256', 'blinded_judge_manifest_sha256')))
    check('receipt_precedes_provider_calls', receipt['judge_calls_at_receipt_write'] == 0 and receipt['client_constructed_at_receipt_write'] is False and receipt['runtime_constructed_at_receipt_write'] is False)
    check('runner_status_sequence', [s['status'] for s in status_events] == ['PREFLIGHT_STARTED', 'RUNTIME_VALIDATED', 'CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED', 'COMPLETE'])
    check('runner_runtime_and_client_match_preflight', status_events[1]['runtime'] == preflight['runtime'] and status_events[2]['client_configuration'] == preflight['client_configuration'])
    check('continuation_complete_within_call_ceiling', status['status'] == 'COMPLETE' and status['request_count'] == status['valid_terminal_count'] == 1 and status['physical_attempts'] == status['judge_calls'] == len(starts) == len(returns) and 1 <= len(starts) <= 2)
    check('continuation_no_automatic_resume', status['automatic_resume'] is False and meta['execution_contract']['automatic_resume_permitted'] is False)
    identity_fields = ('logical_order', 'logical_judge_request_id', 'judge_result_blind_id', 'provider_payload_sha256')
    check('all_new_events_exact_authorized_identity', all(all(event[k] == row[k] for k in identity_fields) for event in attempts + terminals))
    check('all_new_events_timeout_120', all(event['request_timeout_seconds'] == 120.0 for event in attempts + terminals) and status['request_timeout_seconds'] == 120)
    check('paired_attempt_events_in_order', [event['event'] for event in attempts] == ['ATTEMPT_STARTED', 'ATTEMPT_RETURNED'] * len(starts) and [e['attempt_number'] for e in starts] == list(range(1, len(starts) + 1)) and [e['attempt_number'] for e in returns] == list(range(1, len(returns) + 1)) and all(a['request_started_at_utc'] == b['request_started_at_utc'] for a, b in zip(starts, returns)))
    check('retry_contract_exact', tuple(meta['execution_contract']['retryable_failure_codes']) == RETRYABLE and meta['execution_contract']['maximum_byte_identical_invalid_output_retries'] == 1 and meta['execution_contract']['all_other_failures_non_retryable'] is True)
    check('retry_only_after_eligible_invalid_output', all(e['failure_code'] in RETRYABLE for e in returns[:-1]) and returns[-1]['failure_code'] is None and len(returns[:-1]) <= 1 and all(e['provider_payload_sha256'] == PAYLOAD_SHA for e in starts + returns))
    check('zero_new_error_registry_entries', len(errors) == 0)
    check('one_new_valid_terminal', len(terminals) == 1 and terminals[0]['terminal_status'] == 'VALID_JUDGE_RESULT' and terminals[0]['physical_attempts'] == len(starts))
    check('model_and_finish_reason_exact', all(e['returned_model'] == MODEL and e['finish_reason'] == 'stop' for e in returns + terminals))
    check('old_canonical_orders_one_through_38', [e['logical_order'] for e in old_terminals] == list(range(1, 39)))
    check('only_new_canonical_order_39', [e['logical_order'] for e in terminals] == [39])

    canonical_terminals = old_terminals + terminals
    request_counts = Counter(e['logical_judge_request_id'] for e in canonical_terminals)
    result_counts = Counter(e['judge_result_blind_id'] for e in canonical_terminals)
    missing = sorted(set(source_by_id) - set(request_counts))
    unexpected = sorted(set(request_counts) - set(source_by_id))
    duplicate_requests = sorted(k for k, count in request_counts.items() if count != 1)
    duplicate_results = sorted(k for k, count in result_counts.items() if count != 1)
    check('final_39_unique_request_and_result_ids', len(canonical_terminals) == len(request_counts) == len(result_counts) == 39 and not duplicate_requests and not duplicate_results)
    check('no_missing_or_unexpected_request', not missing and not unexpected)
    check('canonical_identity_matches_original_manifest', all(all(e[k] == source_by_id[e['logical_judge_request_id']][k] for k in identity_fields) for e in canonical_terminals))

    all_returns = old_returns + returns
    returns_by_attempt = {(e['logical_judge_request_id'], e['attempt_number']): e for e in all_returns}
    check('no_duplicate_returned_attempt_identity', len(returns_by_attempt) == len(all_returns))
    parser_passes, parser_failures, lineage = [], [], []
    parsed_link_ok = applicability_ok = rationales_ok = means_ok = auxiliary_ok = models_ok = True
    for terminal in canonical_terminals:
        request_id = terminal['logical_judge_request_id']
        frozen_row = source_by_id[request_id]
        attempt = returns_by_attempt[(request_id, terminal['physical_attempts'])]
        applicability = runner._extract_applicability(frozen_row['provider_payload'])
        source_output = 'execution_output_v1' if terminal['logical_order'] <= 38 else 'execution_output_v2'
        lineage.append({**{k: terminal[k] for k in identity_fields}, 'source_output': source_output})
        try:
            parsed = parser.parse_judge_result(attempt['raw_response_content'], applicability, expected_judge_result_blind_id=frozen_row['judge_result_blind_id'])
        except parser.JudgeResultError as exc:
            parser_failures.append({'logical_judge_request_id': request_id, 'failure_code': parser.retryable_failure_code(exc)})
            continue
        parser_passes.append(request_id)
        parsed_link_ok &= parsed == attempt['parsed_semantic_result'] == terminal['parsed_semantic_result'] and attempt['failure_code'] is None
        parsed_link_ok &= all(attempt[k] == terminal[k] for k in identity_fields)
        parsed_link_ok &= attempt['provider_response_id'] == terminal['provider_response_id'] and attempt['response_finished_at_utc'] == terminal['terminal_at_utc']
        for criterion, field in parser.SCORE_FIELDS.items():
            value = parsed[field]
            applicability_ok &= (type(value) is int and 1 <= value <= 5) if applicability['criteria'][criterion] else value == 'NA'
        rationales_ok &= set(parsed['criterion_rationales']) == set(parser.SCORE_FIELDS.values()) and all(isinstance(v, str) and v.strip() for v in parsed['criterion_rationales'].values())
        rationales_ok &= attempt['rationale_lengths'] == parser.rationale_lengths(attempt['raw_response_content'])
        means_ok &= parsed['overall_applicable_mean'] == parser.recompute_overall_applicable_mean(parsed, applicability)
        auxiliary_ok &= type(parsed['evidence_faithfulness']) is int and 1 <= parsed['evidence_faithfulness'] <= 5 and type(parsed['unsupported_claim_count']) is int and parsed['unsupported_claim_count'] >= 0
        models_ok &= attempt['returned_model'] == terminal['returned_model'] == MODEL
    check('all_39_reparse_with_frozen_parser_v3', len(parser_passes) == 39 and not parser_failures)
    check('raw_return_parsed_terminal_identity_link', parsed_link_ok)
    check('all_39_applicability_maps_respected', applicability_ok)
    check('all_required_rationales_nonempty_unmodified', rationales_ok)
    check('all_individual_means_recomputed_only', means_ok)
    check('auxiliary_fields_schema_valid', auxiliary_ok)
    check('all_canonical_returned_models_exact', models_ok)
    retry_parser_ok = True
    for attempt in returns[:-1]:
        try:
            parser.parse_judge_result(attempt['raw_response_content'], runner._extract_applicability(row['provider_payload']), expected_judge_result_blind_id=RESULT_ID)
        except parser.JudgeResultError as exc:
            retry_parser_ok &= parser.retryable_failure_code(exc) == attempt['failure_code']
        else:
            retry_parser_ok = False
    check('any_retry_failure_independently_reparsed', retry_parser_ok)

    token_fields = ('prompt_tokens', 'cached_input_tokens', 'completion_tokens', 'total_tokens')
    tokens = {k: sum(e[k] for e in returns) for k in token_fields}
    check('new_usage_nonnegative_integer_arithmetic', all(all(type(e[k]) is int and e[k] >= 0 for k in token_fields) and e['cached_input_tokens'] <= e['prompt_tokens'] and e['total_tokens'] == e['prompt_tokens'] + e['completion_tokens'] for e in returns))
    check('terminal_usage_matches_successful_return', all(terminals[0][k] == returns[-1][k] for k in token_fields))
    check('no_hidden_identifiers_in_returned_content', all(not hidden(json.loads(e['raw_response_content'])) and not hidden(e['parsed_semantic_result']) for e in old_returns + returns if e['failure_code'] is None))
    scoped_paths = [p for p in HERE.rglob('*') if p.is_file()]
    check('no_credentials_in_new_artifacts', all(not SECRET_RE.search(p.read_bytes()) for p in scoped_paths if p.relative_to(HERE).as_posix() not in preservation['before_sha256']))
    check('no_bytecode_or_symlink_residue', all(not p.is_symlink() and p.name != '__pycache__' and p.suffix not in ('.pyc', '.pyo') for p in HERE.rglob('*')))
    check('all_package_tests_recorded_pass', meta['original_package_test_count'] == 22 and meta['continuation_package_test_count'] == 36 and all(r['exit_code'] == 0 for r in meta['original_validation_records'] + meta['continuation_directory_and_test_records']))
    check('no_other_shard_or_restricted_mapping_access_attested', meta['no_other_corrected_shard_access'] is True and meta['no_restricted_mapping_access'] is True)

    terminal_sha = sha((out2 / 'JUDGE_TERMINAL_JOURNAL.jsonl').read_bytes())
    parsed_sha = sha(canonical([t['parsed_semantic_result'] for t in terminals]))
    check('new_terminal_journal_frozen_sha', terminal_sha == '8df896d0bb7c6638388cea673f42c1e3cd084f4a36284d01e2ad0862267cefb0')
    check('new_parsed_result_set_frozen_sha', parsed_sha == '295af913807993c69924c22aaf0ac55d465104470de3dc26c23d170e552ee223')
    failures = sorted(k for k, passed in checks.items() if not passed)
    return {
        'schema_version': 'c4-real-corrected-judge-a-final-completeness-audit-v1',
        'audit_timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'status': 'COMPLETE' if not failures else 'AUDIT_FAILED',
        'audit_passed': not failures,
        'starting_head': meta['starting_head'],
        'working_directory': meta['working_directory'],
        'branch': meta['branch'],
        'historical_canonical_count': len(old_terminals),
        'continuation_canonical_count': len(terminals),
        'total_corrected_a_results': len(canonical_terminals),
        'unique_logical_judge_request_ids': len(request_counts),
        'unique_result_blind_ids': len(result_counts),
        'missing_request_ids': missing,
        'unexpected_request_ids': unexpected,
        'duplicate_request_ids': duplicate_requests,
        'duplicate_terminal_result_ids': duplicate_results,
        'parser_v3_pass_count': len(parser_passes),
        'parser_v3_failures': parser_failures,
        'canonical_selection_policy': 'ORIGINAL_A_ORDERS_1_TO_38_FROM_V1_AND_ONLY_ORDER_39_FROM_AUTHORIZED_V2_BY_IDENTITY',
        'selection_uses_score_value': False,
        'canonical_sources': lineage,
        'historical_files_preserved_count': len(preservation['before_sha256']),
        'historical_output_status_unchanged': 'INCOMPLETE',
        'historical_interrupted_order39_is_judge_result': False,
        'historical_interrupted_order39_provider_outcome_and_billing': 'UNKNOWN_NOT_INFERRED',
        'historical_pacing_disposition': 'QUALIFIED_PACING_EVIDENCE_LIMITATION',
        'historical_pacing_limitation': 'ATTEMPT_STARTED UTC values do not establish the Runner monotonic initial-start reference or actual wire-send timing; preserved historical valid results are not invalidated.',
        'continuation_pacing_disposition': 'NOT_APPLICABLE_SINGLE_LOGICAL_REQUEST',
        'continuation_counts': {'logical_requests': 1, 'physical_attempts': len(starts), 'judge_calls': status['judge_calls'], 'valid_terminals': len(terminals), 'byte_identical_invalid_output_retries': len(starts) - 1, 'unresolved_errors': len(errors)},
        'continuation_errors': {'invalid_json': sum(e['failure_code'] == RETRYABLE[0] for e in returns), 'strict_schema': sum(e['failure_code'] == RETRYABLE[1] for e in returns), 'applicability_contract': sum(e['failure_code'] == RETRYABLE[2] for e in returns), 'provider': sum(e.get('phase') == 'PROVIDER_CALL' for e in errors), 'returned_model_mismatch': sum(e.get('error_category') == 'RETURNED_MODEL_MISMATCH' for e in errors), 'unresolved': len(errors)},
        'continuation_returned_models': sorted({e['returned_model'] for e in returns}),
        'continuation_token_usage': tokens,
        'token_usage_scope': 'Only the captured continuation return; historical interrupted order39 usage and billing remain unknown.',
        'package_zip_sha256': PACKAGE_SHA,
        'authorization_v2_sha256': AUTH_SHA,
        'one_request_manifest_sha256': ROW_SHA,
        'continuation_terminal_journal_sha256': terminal_sha,
        'continuation_parsed_result_set_sha256': parsed_sha,
        'historical_parsed_result_set_sha256_unchanged': historical_parsed_sha,
        'parsed_result_set_hash_definition': 'SHA256 of UTF-8 JSON array of terminal parsed_semantic_result objects, in journal order, ensure_ascii=False, sort_keys=True, separators=(comma,colon), allow_nan=False, without a trailing newline.',
        'runtime_preflight_provider_calls': 0,
        'offline_audit_provider_calls': 0,
        'scope_attestations': {'unblinding': 0, 'score_comparisons': 0, 'human_rating_access_or_intake': 0, 'agreement_calculation': 0, 'final_statistics': 0, 'final_integration': 0, 'other_shard_provider_calls': 0, 'generation_calls': 0, 'restricted_mapping_access': 0, 'scope': 'This single-request continuation and its offline completion audit only.'},
        'package_test_results': {'original_a': {'passed': 22, 'failed': 0}, 'continuation_r5': {'passed': 36, 'failed': 0}},
        'checks': checks,
        'check_count': len(checks),
        'passed_check_count': len(checks) - len(failures),
        'failed_check_count': len(failures),
        'failed_checks': failures,
    }


class ContinuationArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = network_guard()
        cls.addClassCleanup(cls.guard.close)
        cls.before = {p.relative_to(HERE).as_posix(): sha(p.read_bytes()) for p in HERE.rglob('*') if p.is_file()}
        cls.audit = collect_audit()

    def assert_checks(self, *names):
        for name in names:
            with self.subTest(check=name):
                self.assertTrue(self.audit['checks'][name])

    def test_01_all_audit_checks_pass(self):
        self.assertEqual(self.audit['failed_checks'], [])
        self.assertEqual(self.audit['status'], 'COMPLETE')

    def test_02_original_and_r5_frozen_packages(self):
        self.assert_checks('original_and_r5_packages_valid', 'original_manifest_hash', 'r5_package_identity_and_count')

    def test_03_original_order39_exact_bytes_and_identity(self):
        self.assert_checks('source_row_complete_byte_identity', 'source_order_and_opaque_ids', 'provider_payload_byte_identity')

    def test_04_six_frozen_support_members(self):
        self.assert_checks('six_frozen_files_byte_identical')

    def test_05_exact_eleven_field_r4_authorization(self):
        self.assert_checks('authorization_exact_eleven_fields', 'authorization_schema_r4_amendment')

    def test_06_authorization_binding_and_gate(self):
        self.assert_checks('authorization_identity_status_and_hash', 'exact_r4_environment_gate', 'receipt_binds_authorization')

    def test_07_all_historical_files_byte_preserved(self):
        self.assert_checks('historical_all_eighteen_preserved')

    def test_08_historical_journals_and_parsed_set(self):
        self.assert_checks('historical_attempt_terminal_hashes', 'historical_parsed_set_hash', 'historical_39_attempts_38_returns_38_terminals')

    def test_09_historical_interruption_not_a_result(self):
        self.assert_checks('historical_interrupted_attempt_not_a_result', 'historical_status_remains_incomplete')
        self.assertFalse(self.audit['historical_interrupted_order39_is_judge_result'])

    def test_10_pacing_qualified_and_single_request_na(self):
        self.assert_checks('historical_pacing_qualified_not_rewritten', 'single_request_pacing_not_applicable')

    def test_11_runtime_and_zero_network_preflight(self):
        self.assert_checks('runtime_exact', 'preflight_zero_network_and_client_closed', 'api_key_presence_only_no_dependency_change')

    def test_12_client_transport_retries_and_timeout(self):
        self.assert_checks('sdk_retries_zero_all_timeouts_120', 'runner_runtime_and_client_match_preflight', 'all_new_events_timeout_120')

    def test_13_single_runner_invocation_and_receipt(self):
        self.assert_checks('runner_invoked_once_new_output_only', 'receipt_precedes_provider_calls', 'runner_status_sequence', 'continuation_no_automatic_resume')

    def test_14_one_complete_request_and_paired_events(self):
        self.assert_checks('continuation_complete_within_call_ceiling', 'all_new_events_exact_authorized_identity', 'paired_attempt_events_in_order', 'one_new_valid_terminal')

    def test_15_retry_policy_without_replay(self):
        self.assert_checks('retry_contract_exact', 'retry_only_after_eligible_invalid_output', 'any_retry_failure_independently_reparsed', 'zero_new_error_registry_entries')

    def test_16_exact_returned_model(self):
        self.assert_checks('model_and_finish_reason_exact', 'all_canonical_returned_models_exact')

    def test_17_final_39_unique_identities(self):
        self.assert_checks('final_39_unique_request_and_result_ids', 'no_missing_or_unexpected_request', 'canonical_identity_matches_original_manifest', 'no_duplicate_returned_attempt_identity')

    def test_18_canonical_sources_not_score_based(self):
        self.assert_checks('old_canonical_orders_one_through_38', 'only_new_canonical_order_39')
        self.assertFalse(self.audit['selection_uses_score_value'])
        self.assertEqual(Counter(e['source_output'] for e in self.audit['canonical_sources']), {'execution_output_v1': 38, 'execution_output_v2': 1})

    def test_19_all_39_pass_parser_and_applicability(self):
        self.assert_checks('all_39_reparse_with_frozen_parser_v3', 'raw_return_parsed_terminal_identity_link', 'all_39_applicability_maps_respected')

    def test_20_rationales_individual_means_and_auxiliary_fields(self):
        self.assert_checks('all_required_rationales_nonempty_unmodified', 'all_individual_means_recomputed_only', 'auxiliary_fields_schema_valid')

    def test_21_token_usage_and_frozen_output_hashes(self):
        self.assert_checks('new_usage_nonnegative_integer_arithmetic', 'terminal_usage_matches_successful_return', 'new_terminal_journal_frozen_sha', 'new_parsed_result_set_frozen_sha', 'output_bytes_unchanged_since_completion')

    def test_22_no_hidden_content_credentials_or_residue(self):
        self.assert_checks('no_hidden_identifiers_in_returned_content', 'no_credentials_in_new_artifacts', 'no_bytecode_or_symlink_residue', 'no_other_shard_or_restricted_mapping_access_attested')

    def test_23_package_tests_and_written_audit_match(self):
        self.assert_checks('all_package_tests_recorded_pass')
        recorded = read_json(HERE / 'corrected_judge_a_final_completeness_audit_v1.json')
        current = dict(self.audit)
        recorded.pop('audit_timestamp_utc')
        current.pop('audit_timestamp_utc')
        self.assertEqual(recorded, current)

    def test_24_audit_is_read_only_and_network_blocked(self):
        with self.assertRaisesRegex(AssertionError, 'OFFLINE_TEST_NETWORK_PROHIBITED'):
            socket.create_connection(('127.0.0.1', 9))
        self.assertEqual(self.before, {p.relative_to(HERE).as_posix(): sha(p.read_bytes()) for p in HERE.rglob('*') if p.is_file()})


if __name__ == '__main__':
    if sys.argv[1:] == ['--audit']:
        with network_guard():
            audit = collect_audit()
        print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        raise SystemExit(0 if audit['audit_passed'] else 1)
    unittest.main(verbosity=2)
