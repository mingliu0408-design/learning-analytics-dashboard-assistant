#!/usr/bin/env python3
"""Read-only, zero-network audit of the directly authorized corrected shard C.

The frozen package is read in memory, never extracted or executed as a runner.
Only its hash-pinned offline validator and Parser V3 are loaded. No aggregate
quality score, identity mapping, human rating, or integration is produced.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import socket
import stat
import types
from unittest.mock import patch
import zipfile

PACKAGE = Path('/Users/liuming/Downloads/C4_REAL_CORRECTED_JUDGE_SHARD_C_EXECUTION_PACKAGE_R4_2026-09-02.zip')
PACKAGE_SHA256 = '16727bb41f11ae067a59ab70b48216db97692ae21f6ca334f63c095956ace2b9'
MANIFEST_SHA256 = 'fe4547a0b2ce05a78a7cefb65d8a4acb2b71c7152e5dd45aa290796152457bc5'
AUTHORIZATION_SHA256 = '5733a8041471949a7d36474074d4ba2b22a82366a17cb2c935e4978a5c616c78'
STARTING_HEAD = '9d300c1efd1575005d4673c7cb6297a1bfd6a3ca'
BRANCH = 'research/rq3-real-c4-j4c-corrected-judge-c'
WORKTREE = '/Users/liuming/Downloads/rq2_v2_parallel/rq3-real-j4c-corrected-judge-c'
PACKAGE_ID = 'C4_REAL_CORRECTED_JUDGE_SHARD_C_R4_20260902'
MODEL = 'gpt-4.1-2025-04-14'
INCOMPLETE = 'CORRECTED_JUDGE_EXECUTION_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION'
PINS = {
    'APPLICABILITY_CONTRACT_V2.json': '9f7c9a19670ab2da7c99f5b4f19dcd73d7100792b30b9b60e6b9906bccc16557',
    'BLINDED_JUDGE_REQUESTS.jsonl': MANIFEST_SHA256,
    'EXECUTION_CONTRACT.json': '37b10025401c588da90900abfc5fc39b0ba93e307387117ae5d7af1e2c004ab3',
    'JUDGE_CONFIGURATION.json': '110081cedd251cff81e6de9b2271a8d470d5aeb2ebe8f47e299c0f2079611329',
    'JUDGE_PROMPT.txt': '0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e',
    'JUDGE_SCHEMA.json': '5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a',
    'PACKAGE_SOURCE_HASHES.json': '0c03a480f15812b348ba20608702cc8d7737802a7d42898028f5ee4246832621',
    'PRIMARY_RUBRIC.json': 'be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350',
    'README.md': '90dffbd2c94568a579beeef0ad8b0eef06d221353bea41b0634b71c22b0481e7',
    'judge_execution_runner_v3.py': '6fed067756d90cc8cddf82bab3cb0770423d200edabd3590a73b48c2b81fa6f2',
    'judge_result_parser_v3.py': '7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb',
    'test_package.py': 'f8323623a855ceac83c4a26d94aaab83a4c4c3b560d0e5113368299ca5d34323',
    'validate_package.py': '12ac29b84e390860d3f030887f013925c0355be8bad2a0cc3c81b3254208c377',
}
OUTPUT_FILES = {
    'JUDGE_ATTEMPT_JOURNAL.jsonl', 'JUDGE_TERMINAL_JOURNAL.jsonl',
    'JUDGE_ERROR_REGISTRY.jsonl', 'JUDGE_STATUS_JOURNAL.jsonl',
    'JUDGE_PREFLIGHT_START_RECEIPT.json', 'JUDGE_EXECUTION_STATUS.json',
}
RETRYABLE = {'INVALID_JSON', 'STRICT_SCHEMA_VALIDATION_FAILED', 'APPLICABILITY_CONTRACT_VIOLATION'}
FORBIDDEN_IDENTITY_KEYS = {
    'scenario_id', 'family_id', 'scenario_family_id', 'mode', 'mode_id',
    'condition_id', 'condition_name', 'route', 'route_signature', 'gold',
    'expected_winner', 'human_rating', 'judge_score', 'prior_rating', 'prior_rationale',
}
TOKEN_FIELDS = ('prompt_tokens', 'cached_input_tokens', 'completion_tokens', 'total_tokens')


class AuditError(ValueError):
    pass


def require(value, label):
    if not value:
        raise AuditError(label)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def strict_json(raw):
    def reject_constant(_):
        raise AuditError('non-finite JSON constant')
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise AuditError('strict JSON decode failed') from exc


def jsonl(raw):
    require(not raw or raw.endswith(b'\n'), 'unterminated JSONL record')
    return [strict_json(line) for line in raw.splitlines() if line.strip()]


def scan_secrets(raw):
    patterns = (
        rb'\bsk-[A-Za-z0-9_-]{16,}',
        rb'(?im)^\s*authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9_./+=-]{8,}',
        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        rb'(?i)["\x27](?:api_key|access_token|refresh_token|client_secret)["\x27]\s*:\s*["\x27][^"\x27\s]{8,}',
    )
    require(not any(re.search(pattern, raw) for pattern in patterns), 'credential-like value detected')


def scan_identity(value, key=None):
    if isinstance(value, dict):
        require(not (set(value) & FORBIDDEN_IDENTITY_KEYS), 'hidden identity or prior rating field')
        for name, item in value.items():
            scan_identity(item, name)
    elif isinstance(value, list):
        for item in value:
            scan_identity(item)
    elif isinstance(value, str) and key != 'package_id':
        require(not re.search(r'\bC[0-9]+_[A-Z][A-Z_]+\b|\bU[0-9]{3}\b', value), 'hidden identity label')


def offline_module(name, raw):
    module = types.ModuleType(name)
    module.__file__ = '<hash-pinned-package>/' + name + '.py'
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module


def load_package(path):
    require(sha(path.read_bytes()) == PACKAGE_SHA256, 'external package SHA-256 mismatch')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) == 13 and set(names) == set(PINS), 'package allowlist')
        require(archive.testzip() is None, 'package CRC')
        require(all(not x.is_dir() and not stat.S_ISLNK(x.external_attr >> 16) for x in archive.infolist()), 'package nonregular file')
        return {name: archive.read(name) for name in names}


def load_snapshot(artifact, package_zip=PACKAGE):
    output = artifact / 'execution_output_v1'
    require(output.is_dir() and not output.is_symlink(), 'durable output directory missing')
    require({p.name for p in output.iterdir()} == OUTPUT_FILES, 'durable output inventory')
    require(all(p.is_file() and not p.is_symlink() for p in output.iterdir()), 'durable output nonregular file')
    return {
        'members': load_package(package_zip),
        'authorization': (artifact / 'judge_execution_authorization_v1.json').read_bytes(),
        'runtime': (artifact / 'corrected_judge_runtime_preflight_v1.json').read_bytes(),
        'entry': (artifact / 'corrected_judge_execution_entry_gates_v1.json').read_bytes(),
        'output': {p.name: p.read_bytes() for p in output.iterdir()},
        'console': (artifact / 'runner_process_console_v1.log').read_bytes(),
    }


def audit_snapshot(snapshot):
    members = snapshot['members']
    require(set(members) == set(PINS), 'package member inventory')
    require(all(sha(members[name]) == digest for name, digest in PINS.items()), 'package member hash')
    validator = offline_module('validate_package', members['validate_package.py'])
    parser = offline_module('judge_result_parser_v3', members['judge_result_parser_v3.py'])
    package_validation = validator.validate_members(members, package_zip_sha256=PACKAGE_SHA256)
    require(package_validation['request_count'] == 39 and package_validation['shard_id'] == 'C', 'selected shard binding')
    rows = jsonl(members['BLINDED_JUDGE_REQUESTS.jsonl'])
    requests = {row['logical_judge_request_id']: row for row in rows}
    require(len(rows) == len(requests) == 39, 'frozen request uniqueness')
    require(len({row['judge_result_blind_id'] for row in rows}) == 39, 'frozen result uniqueness')

    authorization = strict_json(snapshot['authorization'])
    contract = strict_json(members['EXECUTION_CONTRACT.json'])
    require(set(authorization) == set(contract['authorization_record_exact_fields']) and len(authorization) == 11, 'authorization exact fields')
    require(sha(snapshot['authorization']) == AUTHORIZATION_SHA256, 'authorization bytes')
    bindings = {
        'schema_version': 'c4-real-corrected-judge-execution-authorization-r4-v1',
        'authorization_id': 'RQ3-REAL-C4-J4C-CORRECTED-JUDGE-20260902',
        'authorized_by': 'Ming Liu', 'package_id': PACKAGE_ID, 'shard_id': 'C',
        'request_count': 39, 'maximum_physical_attempts': 78,
        'package_zip_sha256': PACKAGE_SHA256, 'blinded_judge_manifest_sha256': MANIFEST_SHA256,
        'status': 'AUTHORIZED',
    }
    require(all(authorization[k] == v for k, v in bindings.items()), 'authorization binding')
    require(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', authorization['authorized_at_utc'])), 'authorization timestamp')

    entry = strict_json(snapshot['entry'])
    require(entry['working_directory'] == WORKTREE and entry['branch'] == BRANCH and entry['starting_head'] == STARTING_HEAD, 'starting Git gates')
    require(entry['initial_git_status_short'] == entry['preexecution_tracked_status_short'] == '', 'clean tracked entry')
    require(entry['extraction_count'] == 1 and entry['output_leaf_absent'] is True, 'fresh extraction and output gates')
    require(entry['zip_validation'] == entry['directory_validation'] == 'PASS', 'initial package validation')
    require(entry['package_tests']['tests_run'] == 22 and entry['package_tests']['failures'] == entry['package_tests']['errors'] == 0, '22 package tests')
    require(entry['member_sha256'] == PINS and entry['package_zip_sha256'] == PACKAGE_SHA256, 'entry package hashes')
    require(entry['authorization_sha256'] == AUTHORIZATION_SHA256 and entry['runtime_preflight_sha256'] == sha(snapshot['runtime']), 'entry evidence hashes')
    require(entry['no_old_output_or_score_result_in_package'] is True and entry['no_bytecode_residue'] is True, 'clean package evidence')
    require(entry['phase_b_entry_receipt_sha256'] == 'abf6fd158e68a406008bee838a74adc9d0cc3e87feef0ad649ea790c0feb44e4', 'Phase-B receipt binding')
    runtime = strict_json(snapshot['runtime'])
    require(runtime['status'] == 'PASS' and runtime['python_executable'] == '/opt/anaconda3/bin/python3', 'preflight executable')
    require(runtime['python_version'] == '3.13.5' and runtime['openai_sdk_version'] == '1.109.1', 'preflight runtime versions')
    require(runtime['client_max_retries'] == 0 and runtime['request_timeout_seconds'] == 120.0, 'preflight retries and timeout')
    for name in ('sdk_timeout_components_seconds', 'http_client_timeout_components_seconds'):
        require(runtime[name] == dict.fromkeys(('connect', 'read', 'write', 'pool'), 120.0), 'preflight timeout components')
    require(runtime['network_attempts'] == runtime['provider_calls'] == runtime['dependency_installations_or_modifications'] == 0, 'zero-network preflight')
    require(runtime['api_key_present'] is True and runtime['api_key_value_recorded'] is False and runtime['client_closed_cleanly'] is True, 'preflight key and close')
    require(runtime['official_openai_base_url_verified'] is True, 'official endpoint')

    output = snapshot['output']
    require(set(output) == OUTPUT_FILES, 'durable output file set')
    attempts = jsonl(output['JUDGE_ATTEMPT_JOURNAL.jsonl'])
    terminals = jsonl(output['JUDGE_TERMINAL_JOURNAL.jsonl'])
    errors = jsonl(output['JUDGE_ERROR_REGISTRY.jsonl'])
    events = jsonl(output['JUDGE_STATUS_JOURNAL.jsonl'])
    preflight = strict_json(output['JUDGE_PREFLIGHT_START_RECEIPT.json'])
    final = strict_json(output['JUDGE_EXECUTION_STATUS.json'])
    for raw in [*output.values(), snapshot['authorization'], snapshot['runtime'], snapshot['entry'], snapshot['console']]:
        scan_secrets(raw)
    for value in (attempts, terminals, errors, events, preflight, final):
        scan_identity(value)
    for key in ('authorization_id', 'authorized_by', 'authorized_at_utc', 'package_id', 'shard_id', 'request_count', 'maximum_physical_attempts', 'package_zip_sha256', 'blinded_judge_manifest_sha256'):
        require(preflight[key] == authorization[key], 'runner preflight authorization binding')
    require(preflight['judge_calls_at_receipt_write'] == 0 and preflight['automatic_resume'] is False, 'runner initial call and resume gate')
    require(preflight['runtime_constructed_at_receipt_write'] is False and preflight['client_constructed_at_receipt_write'] is False, 'receipt ordering')
    require(preflight['request_timeout_seconds'] == 120.0, 'runner receipt timeout')
    require(final['status'] in ('COMPLETE', 'INCOMPLETE'), 'runner final status')
    require(final['package_id'] == PACKAGE_ID and final['shard_id'] == 'C' and final['request_count'] == 39, 'runner status bindings')
    require(final['automatic_resume'] is False and final['request_timeout_seconds'] == 120.0, 'runner final transport contract')
    require(events[0]['status'] == 'PREFLIGHT_STARTED' and events[-1]['status'] == final['status'], 'status journal endpoints')

    starts, returns, last_attempt = {}, {}, {}
    active = None
    initial_starts = []
    invalid = Counter({name: 0 for name in sorted(RETRYABLE)})
    totals = Counter({name: 0 for name in TOKEN_FIELDS})
    parsed_by_key = {}
    for event in attempts:
        require(event['logical_judge_request_id'] in requests, 'unknown attempted request')
        request = requests[event['logical_judge_request_id']]
        for name in ('logical_order', 'judge_result_blind_id', 'provider_payload_sha256'):
            require(event[name] == request[name], 'attempt request binding')
        require(event['request_timeout_seconds'] == 120.0, 'attempt timeout')
        number = event['attempt_number']
        require(type(number) is int and number in (1, 2), 'attempt number limit')
        key = (event['logical_judge_request_id'], number)
        if event['event'] == 'ATTEMPT_STARTED':
            require(active is None and key not in starts, 'duplicate or overlapping attempt')
            require(event['judge_calls_started'] == len(starts) + 1, 'physical attempt journal sequence')
            if number == 1:
                require(event['logical_order'] == len(initial_starts) + 1, 'frozen initial request order')
                if initial_starts:
                    previous_key = last_attempt[initial_starts[-1]['logical_judge_request_id']]
                    require(previous_key in returns and returns[previous_key].get('failure_code') is None, 'advanced after failed request')
                initial_starts.append(event)
            else:
                prior = (key[0], 1)
                require(prior in returns and returns[prior].get('failure_code') in RETRYABLE, 'nonretryable attempt repeated')
                require(initial_starts[-1]['logical_judge_request_id'] == key[0], 'out-of-order retry')
                require(returns[prior]['provider_payload_sha256'] == event['provider_payload_sha256'], 'retry payload mismatch')
            starts[key] = event
            last_attempt[key[0]] = key
            active = key
        elif event['event'] == 'ATTEMPT_RETURNED':
            require(active == key and key not in returns, 'return without unique matching start')
            require(event['request_started_at_utc'] == starts[key]['request_started_at_utc'], 'return start timestamp')
            require(datetime.fromisoformat(event['response_finished_at_utc']) >= datetime.fromisoformat(event['request_started_at_utc']), 'return timestamp order')
            require(event['latency_ms'] >= 0, 'negative latency')
            require(event['returned_model'] == MODEL or final['status'] == 'INCOMPLETE', 'returned model mismatch')
            for field in TOKEN_FIELDS:
                require(type(event[field]) is int and event[field] >= 0, 'nonnegative integer token usage')
                totals[field] += event[field]
            require(event['prompt_tokens'] + event['completion_tokens'] == event['total_tokens'], 'token arithmetic')
            require(event['cached_input_tokens'] <= event['prompt_tokens'], 'cached token bound')
            content = request['provider_payload']['messages'][0]['content']
            blind = strict_json(content.split(validator.BEGIN, 1)[1].rsplit(validator.END, 1)[0])
            applicability = blind['frozen_applicability_map']
            try:
                parsed = parser.parse_judge_result(event['raw_response_content'], applicability, expected_judge_result_blind_id=request['judge_result_blind_id'])
                failure = None
            except parser.JudgeResultError as exc:
                parsed = None
                failure = parser.retryable_failure_code(exc)
                require(failure in RETRYABLE, 'unrecognized parser failure')
            if event['returned_model'] == MODEL:
                require(event.get('failure_code') == failure and event.get('parsed_semantic_result') == parsed, 'Parser-V3 journal replay mismatch')
            if failure:
                invalid[failure] += 1
            else:
                require(parsed is not None, 'valid result missing')
                applicable_scores = []
                for criterion, field in parser.SCORE_FIELDS.items():
                    if applicability['criteria'][criterion]:
                        require(type(parsed[field]) is int and 1 <= parsed[field] <= 5, 'applicable score range')
                        applicable_scores.append(parsed[field])
                    else:
                        require(parsed[field] == 'NA', 'inapplicable dimension must be NA')
                    require(parsed['criterion_rationales'][field].strip(), 'empty rationale')
                require(parsed['overall_applicable_mean'] == sum(applicable_scores) / len(applicable_scores), 'local per-result mean')
                require(type(parsed['evidence_faithfulness']) is int and 1 <= parsed['evidence_faithfulness'] <= 5, 'evidence faithfulness')
                require(type(parsed['unsupported_claim_count']) is int and parsed['unsupported_claim_count'] >= 0, 'unsupported claim count')
                require(event['rationale_lengths'] == parser.rationale_lengths(event['raw_response_content']), 'rationale length metadata')
                if event['returned_model'] == MODEL:
                    parsed_by_key[key] = parsed
            returns[key] = event
            active = None
        else:
            raise AuditError('unknown attempt journal event')

    require(len(starts) <= 78 and len(initial_starts) <= 39, 'authorization attempt ceiling')
    require(final['physical_attempts'] == final['judge_calls'] == len(starts), 'status physical count')
    require(final['valid_terminal_count'] == len(terminals), 'status terminal count')
    gaps = [(datetime.fromisoformat(b['request_started_at_utc']) - datetime.fromisoformat(a['request_started_at_utc'])).total_seconds() for a, b in zip(initial_starts, initial_starts[1:])]
    require(all(gap > 0 for gap in gaps), 'initial request timestamp order')
    below_fifteen = [
        {'earlier_logical_order': a['logical_order'], 'later_logical_order': b['logical_order'], 'observed_utc_interval_seconds': gap}
        for a, b, gap in zip(initial_starts, initial_starts[1:], gaps) if gap < 15.0
    ]
    if starts:
        runtime_events = [e for e in events if e['status'] == 'RUNTIME_VALIDATED']
        client_events = [e for e in events if e['status'] == 'CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED']
        require(len(runtime_events) == len(client_events) == 1, 'runtime and client events')
        actual_runtime = runtime_events[0]['runtime']
        require(all(actual_runtime[name] == runtime[name] for name in ('python_executable', 'python_version', 'openai_sdk_version')), 'executed runtime identity')
        require(actual_runtime['api_key_presence_checked_only'] is True and actual_runtime['api_key_value_recorded'] is False, 'executed key handling')
        client = client_events[0]['client_configuration']
        require(client['client_max_retries'] == 0 and client['request_timeout_seconds'] == 120.0, 'executed retry and timeout configuration')
        require(client['timeout_components_seconds'] == dict.fromkeys(('connect', 'read', 'write', 'pool'), 120.0), 'executed timeout components')
        require(client['transport_configuration_verified_before_provider_call'] is True and client_events[0]['judge_calls'] == 0, 'client verified before provider')

    terminal_ids, result_ids, accepted_keys = set(), set(), set()
    parsed_results = []
    for position, terminal in enumerate(terminals, 1):
        logical_id = terminal['logical_judge_request_id']
        require(logical_id in requests and logical_id not in terminal_ids, 'terminal logical ID uniqueness')
        request = requests[logical_id]
        require(terminal['logical_order'] == position, 'terminal order and missing prefix')
        require(terminal['judge_result_blind_id'] not in result_ids, 'terminal result ID uniqueness')
        require(terminal['terminal_status'] == 'VALID_JUDGE_RESULT', 'invalid terminal status')
        for field in ('logical_order', 'judge_result_blind_id', 'provider_payload_sha256'):
            require(terminal[field] == request[field], 'terminal request binding')
        key = (logical_id, terminal['physical_attempts'])
        require(key in parsed_by_key and returns[key]['failure_code'] is None, 'terminal without accepted return')
        accepted = returns[key]
        require(terminal['parsed_semantic_result'] == parsed_by_key[key], 'terminal semantic identity')
        require(terminal['returned_model'] == MODEL and terminal['request_timeout_seconds'] == 120.0, 'terminal model and timeout')
        require(terminal['terminal_at_utc'] == accepted['response_finished_at_utc'], 'terminal timestamp')
        for field in (*TOKEN_FIELDS, 'provider_response_id', 'returned_model', 'system_fingerprint', 'finish_reason'):
            require(terminal[field] == accepted[field], 'terminal metadata identity')
        terminal_ids.add(logical_id)
        result_ids.add(terminal['judge_result_blind_id'])
        accepted_keys.add(key)
        parsed_results.append(terminal['parsed_semantic_result'])
    require(accepted_keys == set(parsed_by_key), 'valid return missing terminal')
    complete = final['status'] == 'COMPLETE'
    if complete:
        require(len(initial_starts) == len(terminals) == 39 and set(requests) == terminal_ids, 'complete coverage')
        require(len(starts) == len(returns) and not errors and active is None, 'complete unresolved errors')
        require(final['corrected_execution_requires_new_direct_authorization'] is False, 'complete final gate')
    else:
        require(errors and final['corrected_execution_requires_new_direct_authorization'] is True, 'incomplete new-authorization gate')
        require(all(error['terminal_policy'] == 'STOP_ENTIRE_SHARD' for error in errors), 'incomplete fail-closed policy')
    require(events[-1]['judge_calls'] == len(starts) and events[-1]['valid_terminal_count'] == len(terminals), 'final status journal counts')
    require(totals['prompt_tokens'] + totals['completion_tokens'] == totals['total_tokens'], 'total token arithmetic')

    categories = Counter(error['error_category'] for error in errors)
    error_text = canonical(errors).decode().lower()
    error_counts = {
        'unresolved_error_records': len(errors),
        'provider_errors': sum(error.get('phase') == 'PROVIDER_CALL' for error in errors),
        'refusal_errors': int(b'PROVIDER_REFUSAL_NON_RETRYABLE' in snapshot['console']),
        'returned_model_errors': categories['RETURNED_MODEL_MISMATCH'],
        'model_errors': categories['RETURNED_MODEL_MISMATCH'] + int('model_not_found' in error_text),
        'timeout_errors': sum(n for name, n in categories.items() if 'timeout' in name.lower()),
        'billing_errors': sum(error.get('error_code') in ('insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active') for error in errors),
        'rate_limit_errors': categories['RateLimitError'],
        'authentication_errors': categories['AuthenticationError'],
        'permission_errors': categories['PermissionDeniedError'],
        'transport_errors': categories['APIConnectionError'],
    }
    parsed_bytes = b''.join(canonical(row) + b'\n' for row in parsed_results)
    commitments = [{key: row[key] for key in ('logical_order', 'logical_judge_request_id', 'judge_result_blind_id', 'provider_payload_sha256')} for row in rows]
    facts = {
        'schema_version': 'c4-real-corrected-judge-execution-audit-v1',
        'audit_status': 'QUALIFIED_PACING_EVIDENCE_LIMITATION' if below_fifteen else 'PASS',
        'result_integrity_status': 'PASS', 'runner_status': final['status'],
        'execution_status': 'COMPLETE' if complete else INCOMPLETE,
        'package_id': PACKAGE_ID, 'shard_id': 'C',
        'logical_requests_authorized': 39, 'logical_requests_started': len(initial_starts),
        'physical_attempts': len(starts), 'maximum_physical_attempts': 78,
        'returned_attempts': len(returns), 'valid_terminals': len(terminals),
        'retry_attempts': sum(key[1] == 2 for key in starts),
        'missing_results': 39 - len(terminals), 'duplicate_results': 0,
        'invalid_output_counts': dict(invalid), 'error_counts': error_counts,
        'returned_models': sorted({event['returned_model'] for event in returns.values()}),
        'token_usage_all_returned_attempts': dict(totals),
        'token_usage_available_for_all_physical_attempts': len(starts) == len(returns),
        'minimum_observed_initial_start_interval_seconds': min(gaps) if gaps else None,
        'initial_start_intervals_checked': len(gaps),
        'pacing_evidence': {
            'required_interval_seconds': 15.0,
            'frozen_runner_hash_and_package_pacing_test': 'PASS',
            'journal_utc_intervals_all_at_least_15_seconds': not below_fifteen,
            'journal_utc_intervals_below_15_seconds': below_fifteen,
            'monotonic_gate_timestamps_recorded_by_frozen_runner': False,
            'actual_transport_start_intervals_independently_verified': False,
            'no_tolerance_added_to_15_second_requirement': True,
            'observation': 'The frozen runner samples previous_initial_start using monotonic time before payload preparation, then samples request_started_at_utc later. These are different measurement points. Logged UTC differences cannot independently certify the monotonic gate or actual wire-send spacing. Sub-15 observations are retained without rounding or accepting a new tolerance; no clock correction is inferred.',
        },
        'package_validation': package_validation, 'package_member_hashes_verified': 13,
        'authorization_sha256': sha(snapshot['authorization']),
        'runtime_preflight_sha256': sha(snapshot['runtime']),
        'entry_gates_sha256': sha(snapshot['entry']),
        'terminal_journal_sha256': sha(output['JUDGE_TERMINAL_JOURNAL.jsonl']),
        'parsed_result_set_sha256': sha(parsed_bytes),
        'parsed_result_set_serialization': 'one unchanged parsed_semantic_result per terminal, logical order, canonical UTF-8 JSON plus LF',
        'request_commitments_sha256': sha(canonical(commitments)),
        'output_file_sha256': {name: sha(raw) for name, raw in sorted(output.items())},
        'runner_console_sha256': sha(snapshot['console']),
        'parser_v3_replayed_return_count': len(returns),
        'applicability_verified_terminal_count': len(terminals),
        'locally_recomputed_per_result_mean_count': len(terminals),
        'package_tests_passed': 22,
        'credential_scan': 'PASS_PATTERN_SCAN', 'hidden_identity_scan': 'PASS',
        'offline_audit_provider_calls': 0,
        'scope_attestation': {
            'runner_invocations': 1, 'other_shard_package_accesses': 0,
            'retained_result_reruns': 0, 'old_judge_package_accesses': 0,
            'unblinding': 0, 'mode_level_scoring': 0, 'system_comparisons': 0,
            'human_rating': 0, 'agreement_calculation': 0, 'statistical_analysis': 0,
            'response_generation': 0, 'downstream_component_execution': 0,
            'final_judge_integration': 0, 'restricted_internal_accesses': 0,
        },
    }
    return facts, parsed_bytes, commitments


def deny_network(*args, **kwargs):
    raise AuditError('network forbidden in offline audit')


def network_guard():
    stack = ExitStack()
    for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'), (socket, 'create_connection'), (socket, 'getaddrinfo')):
        stack.enter_context(patch.object(obj, name, deny_network))
    return stack


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--artifact-dir', type=Path, default=Path(__file__).resolve().parent)
    cli.add_argument('--package-zip', type=Path, default=PACKAGE)
    args = cli.parse_args()
    with network_guard():
        facts, _, _ = audit_snapshot(load_snapshot(args.artifact_dir, args.package_zip))
    print(json.dumps(facts, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
