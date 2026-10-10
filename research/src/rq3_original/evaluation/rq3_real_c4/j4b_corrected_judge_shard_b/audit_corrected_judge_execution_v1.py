#!/usr/bin/env python3
"""Offline audit of one frozen Shard B run. No execution or resume entry point.

Reads the separately supplied B ZIP in memory and via zipimport, without another
extraction. Applicability decisions are consumed exactly as supplied. Only each
result's required local mean is checked; no cross-result score is calculated.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
ROOT = Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-real-j4b-corrected-judge-b')
PACKAGE = Path('/Users/liuming/Downloads/C4_REAL_CORRECTED_JUDGE_SHARD_B_EXECUTION_PACKAGE_R4_2026-09-02.zip')
BRANCH = 'research/rq3-real-c4-j4b-corrected-judge-b'
HEAD = '9d300c1efd1575005d4673c7cb6297a1bfd6a3ca'
PACKAGE_HASH = 'b133157f57a8546f503a8eba72520dd04fe54e5a803ec218bf55ef89fb28975b'
MANIFEST_HASH = '89be3ee0dc8b00795cd1770867b8fbd0094987fe013246312c99e29498998eba'
AUTH_HASH = '3bc01ece542bc0cfb77def8e602cdbb4ff394fd58f35ca968068c7f326a536e2'
PACKAGE_ID = 'C4_REAL_CORRECTED_JUDGE_SHARD_B_R4_20260902'
AUTH_ID = 'RQ3-REAL-C4-J4B-CORRECTED-JUDGE-20260902'
MODEL = 'gpt-4.1-2025-04-14'
COUNT = 38
LIMIT = 76
RETRYABLE = frozenset(('INVALID_JSON', 'STRICT_SCHEMA_VALIDATION_FAILED', 'APPLICABILITY_CONTRACT_VIOLATION'))
TOKENS = ('prompt_tokens', 'cached_input_tokens', 'completion_tokens', 'total_tokens')
DURABLE = frozenset(('JUDGE_ATTEMPT_JOURNAL.jsonl', 'JUDGE_TERMINAL_JOURNAL.jsonl',
    'JUDGE_ERROR_REGISTRY.jsonl', 'JUDGE_STATUS_JOURNAL.jsonl',
    'JUDGE_PREFLIGHT_START_RECEIPT.json', 'JUDGE_EXECUTION_STATUS.json'))
PROTOCOL_HASHES = {
    'JUDGE_CONFIGURATION.json': '41448c8a9fce7756079b4ff85a682285769a72238d0350ae0dcf703bd75acbff',
    'JUDGE_PROMPT.txt': '0d5efac2d764cfd9d8aeaa125071ec8f8ce61108cd8896bfd299dc68ddc8537e',
    'JUDGE_SCHEMA.json': '5193646806796034c2c9abe524006cfae04204284e2ddfe4f3add37eefc41a8a',
    'judge_result_parser_v3.py': '7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb',
    'judge_execution_runner_v3.py': '6fed067756d90cc8cddf82bab3cb0770423d200edabd3590a73b48c2b81fa6f2',
    'PRIMARY_RUBRIC.json': 'be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350',
    'APPLICABILITY_CONTRACT_V2.json': '9f7c9a19670ab2da7c99f5b4f19dcd73d7100792b30b9b60e6b9906bccc16557',
}
ENTRY_HASH = 'abf6fd158e68a406008bee838a74adc9d0cc3e87feef0ad649ea790c0feb44e4'
INCOMPLETE = 'CORRECTED_JUDGE_EXECUTION_INCOMPLETE_REQUIRES_NEW_DIRECT_AUTHORIZATION'


class AuditFailure(ValueError):
    pass


def need(value, label):
    if not value:
        raise AuditFailure(label)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_bytes())


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def network_guard():
    stack = ExitStack()
    for owner, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'), (socket, 'create_connection')):
        stack.enter_context(patch.object(owner, name, side_effect=AuditFailure('OFFLINE_AUDIT_NETWORK_PROHIBITED')))
    return stack


def load_context(package=PACKAGE):
    package = Path(package)
    need(digest(package.read_bytes()) == PACKAGE_HASH, 'selected ZIP hash')
    # zipimport reads module bytes without extraction or bytecode writes.
    sys.path.insert(0, str(package))
    parser = importlib.import_module('judge_result_parser_v3')
    validator = importlib.import_module('validate_package')
    members = validator.read_package_zip(package)
    validation = validator.validate_members(members, package_zip_sha256=PACKAGE_HASH)
    output = BASE / 'execution_output_v1'
    need({p.name for p in output.iterdir()} == DURABLE, 'durable output allowlist')
    need(all(p.is_file() and not p.is_symlink() for p in output.iterdir()), 'regular durable files')
    def jsonl(name):
        return [validator.strict_json(line) for line in (output / name).read_bytes().splitlines() if line.strip()]
    requests = [validator.strict_json(line) for line in members['BLINDED_JUDGE_REQUESTS.jsonl'].splitlines() if line.strip()]
    context = {
        'package_path': package, 'members': members, 'validation': validation,
        'parser': parser, 'validator': validator, 'output': output, 'requests': requests,
        'config': validator.strict_json(members['JUDGE_CONFIGURATION.json']),
        'contract': validator.strict_json(members['EXECUTION_CONTRACT.json']),
        'auth': read_json(BASE / 'judge_execution_authorization_v1.json'),
        'preflight': read_json(BASE / 'runtime_preflight_v1.json'),
        'gates': read_json(BASE / 'starting_gates_v1.json'),
        'package_validation': read_json(BASE / 'package_validation_v1.json'),
        'receipt': read_json(output / 'JUDGE_PREFLIGHT_START_RECEIPT.json'),
        'status': read_json(output / 'JUDGE_EXECUTION_STATUS.json'),
        'events': jsonl('JUDGE_ATTEMPT_JOURNAL.jsonl'),
        'terminals': jsonl('JUDGE_TERMINAL_JOURNAL.jsonl'),
        'errors': jsonl('JUDGE_ERROR_REGISTRY.jsonl'),
        'status_events': jsonl('JUDGE_STATUS_JOURNAL.jsonl'),
        'snapshot': read_json(BASE / 'execution_output_integrity_v1.json'),
        'invocation': read_json(BASE / 'runner_invocation_v1.json'),
    }
    context['started'] = [e for e in context['events'] if e['event'] == 'ATTEMPT_STARTED']
    context['returned'] = [e for e in context['events'] if e['event'] == 'ATTEMPT_RETURNED']
    context['by_id'] = {r['logical_judge_request_id']: r for r in requests}
    return context


def verify_sources(c):
    v, cfg, contract = c['validation'], c['config'], c['contract']
    need(v['status'] == 'PASS' and v['package_id'] == PACKAGE_ID and v['shard_id'] == 'B', 'selected package identity')
    need(v['request_count'] == COUNT and v['maximum_physical_attempts'] == LIMIT and v['estimated_input_tokens'] == 139203, 'frozen request counts')
    need(v['blinded_judge_manifest_sha256'] == MANIFEST_HASH and len(c['members']) == 13, 'manifest and member count')
    for name, expected in PROTOCOL_HASHES.items():
        need(digest(c['members'][name]) == expected, 'protocol commitment: ' + name)
    need(contract['phase_b_entry_receipt_sha256'] == ENTRY_HASH, 'Phase B receipt hash binding')
    need(cfg['model'] == MODEL and cfg['temperature'] == 0 and cfg['maximum_output_tokens'] == 2048, 'model sampling contract')
    need(cfg['stream'] is False and cfg['tools'] == 'NONE' and cfg['sdk_retries'] == 0, 'transport options')
    need(cfg['minimum_initial_start_interval_seconds'] == 15.0 and cfg['request_timeout_seconds'] == 120.0, 'timing contract')
    recorded = c['package_validation']
    need(recorded['extraction_count'] == 1 and recorded['no_bytecode_residue'] is True, 'one fresh extraction')
    need(recorded['zip_validation']['status'] == recorded['directory_validation']['status'] == 'PASS', 'required package validators')
    need(recorded['package_tests'] == {'exit_code': 0, 'tests_run': 22, 'failures': 0, 'errors': 0, 'provider_calls': 0}, '22 frozen offline tests')
    need(recorded['member_sha256'] == {n: digest(b) for n, b in c['members'].items()}, 'all 13 recorded member hashes')
    return {'package_member_count': 13, 'request_count': COUNT, 'package_tests_passed': 22}


def verify_authorization(c):
    a = c['auth']
    expected = {
        'schema_version': 'c4-real-corrected-judge-execution-authorization-r4-v1',
        'authorization_id': AUTH_ID, 'authorized_by': 'Ming Liu', 'package_id': PACKAGE_ID,
        'shard_id': 'B', 'request_count': COUNT, 'maximum_physical_attempts': LIMIT,
        'package_zip_sha256': PACKAGE_HASH, 'blinded_judge_manifest_sha256': MANIFEST_HASH,
        'status': 'AUTHORIZED',
    }
    need(set(a) == set(expected) | {'authorized_at_utc'}, 'exact eleven authorization fields')
    need(all(a[k] == v for k, v in expected.items()), 'authorization bindings')
    need(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', a['authorized_at_utc'])), 'authorization UTC format')
    need(digest((BASE / 'judge_execution_authorization_v1.json').read_bytes()) == AUTH_HASH, 'authorization immutable hash')
    need(utc(a['authorized_at_utc']) <= utc(c['receipt']['timestamp_utc']), 'authorization predates execution')
    g = c['gates']
    need(g['working_directory'] == str(ROOT) and g['branch'] == BRANCH and g['starting_head'] == HEAD, 'starting Git identity')
    need(g['initial_git_status_short'] == '' and g['tracked_worktree_clean'] and g['output_leaf_absent'], 'clean and fresh starting gates')
    i = c['invocation']
    need(i['real_runner_invocations'] == 1 and i['automatic_resume'] is False, 'one runner invocation')
    need(i['authorization_environment_value'] == 'AUTHORIZED_C4_REAL_CORRECTED_JUDGE_EXECUTION_R4', 'exact environment gate')
    need(i['package_zip_sha256'] == PACKAGE_HASH and i['authorization_sha256'] == AUTH_HASH, 'invocation source binding')
    return {'authorization_sha256': AUTH_HASH, 'real_runner_invocations': 1}


def verify_runtime(c):
    p = c['preflight']
    need(p['status'] == 'PASS' and p['python_executable'] == '/opt/anaconda3/bin/python3', 'Python executable')
    need(p['python_version'] == '3.13.5' and p['openai_sdk_version'] == '1.109.1', 'runtime versions')
    need(p['api_key_presence_checked_only'] and p['api_key_value_recorded'] is False, 'key presence only')
    need(p['provider_calls'] == p['network_attempts'] == p['dependency_changes'] == 0, 'zero-network preflight')
    need(p['client_closed_cleanly'] and p['official_openai_base_url_verified'], 'client close and endpoint')
    expected = dict.fromkeys(('connect', 'read', 'write', 'pool'), 120.0)
    need(p['client_max_retries'] == 0 and p['timeout_components_seconds'] == p['httpx_timeout_components_seconds'] == expected, 'preflight timeout components')
    events = c['status_events']
    need([e['status'] for e in events[:3]] == ['PREFLIGHT_STARTED', 'RUNTIME_VALIDATED', 'CLIENT_CONSTRUCTED_RETRIES_ZERO_TIMEOUT_120_VERIFIED'], 'runtime event order')
    need(all(e['judge_calls'] == 0 for e in events[:3]), 'runtime gates precede Provider')
    actual = events[1]['runtime']
    need(all(actual[k] == p[k] for k in ('python_executable', 'python_version', 'openai_sdk_version', 'api_key_presence_checked_only', 'api_key_value_recorded')), 'execution runtime matches preflight')
    transport = events[2]['client_configuration']
    need(transport['client_max_retries'] == 0 and transport['timeout_components_seconds'] == expected and transport['request_timeout_seconds'] == 120.0, 'execution client timeout')
    receipt = c['receipt']
    need(receipt['judge_calls_at_receipt_write'] == 0 and receipt['client_constructed_at_receipt_write'] is False and receipt['runtime_constructed_at_receipt_write'] is False, 'durable receipt before runtime')
    for k in ('authorization_id', 'authorized_by', 'authorized_at_utc', 'package_id', 'shard_id', 'request_count', 'maximum_physical_attempts', 'package_zip_sha256', 'blinded_judge_manifest_sha256'):
        need(receipt[k] == c['auth'][k], 'receipt binding: ' + k)
    return {'python_version': '3.13.5', 'openai_sdk_version': '1.109.1', 'timeout_components_seconds': expected, 'preflight_provider_calls': 0}


def verify_attempts(c):
    starts, returned = c['started'], c['returned']
    need(len(starts) <= LIMIT and len(returned) <= len(starts), 'physical attempt cap')
    need(all(e['event'] in ('ATTEMPT_STARTED', 'ATTEMPT_RETURNED') for e in c['events']), 'known journal events')
    seen, completed, last = {}, {}, None
    for e in c['events']:
        rid = e['logical_judge_request_id']
        need(rid in c['by_id'], 'only authorized opaque request IDs')
        request = c['by_id'][rid]
        for k in ('logical_order', 'judge_result_blind_id', 'provider_payload_sha256'):
            need(e[k] == request[k], 'request identity/payload commitment: ' + k)
        need(e['request_timeout_seconds'] == 120.0 and e['attempt_number'] in (1, 2), 'attempt contract')
        key = (rid, e['attempt_number'])
        if e['event'] == 'ATTEMPT_STARTED':
            need(key not in seen and (last is None or last in completed), 'no overlapping/duplicate starts')
            if e['attempt_number'] == 2:
                need((rid, 1) in completed and completed[(rid, 1)].get('failure_code') in RETRYABLE, 'retry only after admitted first failure')
                need(last == (rid, 1), 'retry immediately follows same logical request')
                need(e['provider_payload_sha256'] == completed[(rid, 1)]['provider_payload_sha256'], 'byte-identical retry commitment')
            elif last is not None:
                need(completed[last].get('failure_code') is None, 'no continuation after unresolved failure')
            seen[key] = e
            last = key
        else:
            need(key in seen and key not in completed and key == last, 'one return for its start')
            need(e['request_started_at_utc'] == seen[key]['request_started_at_utc'], 'return start timestamp')
            need(utc(e['response_finished_at_utc']) >= utc(e['request_started_at_utc']), 'nonnegative timing')
            completed[key] = e
    initial = [e for e in starts if e['attempt_number'] == 1]
    need([e['logical_order'] for e in initial] == list(range(1, len(initial) + 1)), 'frozen initial request order')
    need([e['judge_calls_started'] for e in starts] == list(range(1, len(starts) + 1)), 'physical call sequence')
    intervals = [(utc(b['request_started_at_utc']) - utc(a['request_started_at_utc'])).total_seconds() for a, b in zip(initial, initial[1:])]
    need(all(sum(e['logical_judge_request_id'] == r['logical_judge_request_id'] for e in starts) <= 2 for r in initial), 'at most two physical attempts per request')
    return {'logical_requests_started': len(initial), 'physical_attempts': len(starts), 'returned_attempts': len(returned),
        'retries': sum(e['attempt_number'] == 2 for e in starts), 'minimum_observed_initial_start_interval_seconds': min(intervals) if intervals else None,
        'invalid_output_counts': {code: sum(e.get('failure_code') == code for e in returned) for code in sorted(RETRYABLE)}}


def pacing_measurements(c):
    initial = [e for e in c['started'] if e['attempt_number'] == 1]
    intervals = [{'from_logical_order': a['logical_order'], 'to_logical_order': b['logical_order'],
        'utc_interval_seconds': (utc(b['request_started_at_utc']) - utc(a['request_started_at_utc'])).total_seconds()}
        for a, b in zip(initial, initial[1:])]
    return {'configured_minimum_seconds': 15.0,
        'minimum_recorded_utc_interval_seconds': min((v['utc_interval_seconds'] for v in intervals), default=None),
        'observed_interval_count': len(intervals),
        'recorded_utc_intervals_below_minimum': [v for v in intervals if v['utc_interval_seconds'] < 15.0],
        'measurement_limit': 'The frozen runner sets its monotonic pacing reference before payload preparation, then records request_started_at_utc after preparation. It records neither that pacing-reference timestamp nor the HTTP send timestamp. UTC gaps cannot certify exact monotonic or HTTP-start spacing. No tolerance has been introduced and the runner was not altered.'}


def verify_strict_recorded_pacing(c):
    measured = pacing_measurements(c)
    need(not measured['recorded_utc_intervals_below_minimum'],
        'STRICT_15_SECOND_PACING_NOT_CERTIFIED: recorded UTC minimum is ' +
        str(measured['minimum_recorded_utc_interval_seconds']) + ' seconds')
    return measured


def applicability(c, request_id):
    content = c['by_id'][request_id]['provider_payload']['messages'][0]['content']
    body = content.split(c['validator'].BEGIN, 1)[1].rsplit(c['validator'].END, 1)[0]
    return c['validator'].strict_json(body)['frozen_applicability_map']


def verify_results(c):
    parser = c['parser']
    valid_returns = {}
    for e in c['returned']:
        if e['returned_model'] != MODEL:
            need(c['status']['status'] == 'INCOMPLETE', 'model mismatch cannot complete')
            continue
        rid = e['logical_judge_request_id']
        frozen_map = applicability(c, rid)
        try:
            result = parser.parse_judge_result(e['raw_response_content'], frozen_map,
                expected_judge_result_blind_id=e['judge_result_blind_id'])
        except parser.JudgeResultError as exc:
            need(e.get('failure_code') == parser.retryable_failure_code(exc) and e.get('parsed_semantic_result') is None, 'invalid-output failure classification')
            continue
        need(e.get('failure_code') is None and result == e['parsed_semantic_result'], 'raw-to-parsed result equality')
        need(e['rationale_lengths'] == parser.rationale_lengths(e['raw_response_content']), 'rationale length diagnostics')
        need(rid not in valid_returns, 'never rerun a successful request')
        valid_returns[rid] = e
    terminals = c['terminals']
    need(len({t['logical_judge_request_id'] for t in terminals}) == len(terminals), 'terminal request uniqueness')
    need(len({t['judge_result_blind_id'] for t in terminals}) == len(terminals), 'terminal result uniqueness')
    need([t['logical_order'] for t in terminals] == list(range(1, len(terminals) + 1)), 'terminal frozen prefix order')
    need(set(valid_returns) == {t['logical_judge_request_id'] for t in terminals}, 'one terminal per valid return')
    for t in terminals:
        rid = t['logical_judge_request_id']
        need(rid in c['by_id'], 'terminal belongs to selected request manifest')
        request, returned = c['by_id'][rid], valid_returns[rid]
        need(t['terminal_status'] == 'VALID_JUDGE_RESULT', 'valid terminal status')
        for field in ('logical_order', 'judge_result_blind_id', 'provider_payload_sha256'):
            need(t[field] == request[field] == returned[field], 'terminal source binding: ' + field)
        for field in ('parsed_semantic_result', 'returned_model', 'provider_response_id', 'system_fingerprint', 'finish_reason', *TOKENS):
            need(t[field] == returned[field], 'terminal return equality: ' + field)
        need(t['physical_attempts'] == returned['attempt_number'] and t['terminal_at_utc'] == returned['response_finished_at_utc'], 'terminal attempt identity')
        need(t['request_timeout_seconds'] == 120.0, 'terminal timeout')
        frozen_map = applicability(c, rid)
        result = t['parsed_semantic_result']
        scores = []
        for criterion, field in parser.SCORE_FIELDS.items():
            if frozen_map['criteria'][criterion]:
                need(type(result[field]) is int and 1 <= result[field] <= 5, 'applicable numeric score')
                scores.append(result[field])
            else:
                need(result[field] == 'NA', 'inapplicable score is NA')
            need(isinstance(result['criterion_rationales'][field], str) and result['criterion_rationales'][field].strip(), 'non-empty rationale')
        need(len(scores) == frozen_map['applicable_primary_count'] and result['overall_applicable_mean'] == sum(scores) / len(scores), 'independent local applicable mean')
        need(type(result['evidence_faithfulness']) is int and 1 <= result['evidence_faithfulness'] <= 5, 'evidence faithfulness')
        need(type(result['unsupported_claim_count']) is int and result['unsupported_claim_count'] >= 0, 'nonnegative unsupported claim count')
        need(result['response_blind_id'] == t['judge_result_blind_id'], 'semantic result identity')
    return {'valid_terminals': len(terminals), 'parser_v3_passed': len(terminals), 'applicability_v2_consistent': len(terminals),
        'local_means_verified': len(terminals), 'nonempty_rationale_count': len(terminals) * 8,
        'missing_terminal_count': COUNT - len(terminals), 'duplicate_terminal_count': 0}


def verify_tokens(c):
    totals = dict.fromkeys(TOKENS, 0)
    for e in c['returned']:
        need(all(type(e[k]) is int and e[k] >= 0 for k in TOKENS), 'nonnegative integer token usage')
        need(e['total_tokens'] == e['prompt_tokens'] + e['completion_tokens'], 'token arithmetic')
        need(e['cached_input_tokens'] <= e['prompt_tokens'], 'cached tokens are a prompt subset')
        for k in TOKENS:
            totals[k] += e[k]
    need(totals['total_tokens'] == totals['prompt_tokens'] + totals['completion_tokens'], 'aggregate usage arithmetic')
    return {'basis': 'All returned physical attempts, including admitted invalid-output attempts; cached tokens are already included in prompt tokens.',
        **totals, 'attempts_with_recorded_usage': len(c['returned']), 'attempts_without_recorded_usage': len(c['started']) - len(c['returned'])}


def verify_completion_and_errors(c):
    status = c['status']
    need(status['status'] in ('COMPLETE', 'INCOMPLETE'), 'recognized frozen terminal status')
    need(status['package_id'] == PACKAGE_ID and status['shard_id'] == 'B' and status['request_count'] == COUNT, 'status identity')
    need(status['physical_attempts'] == status['judge_calls'] == len(c['started']), 'status physical counts')
    need(status['valid_terminal_count'] == len(c['terminals']), 'status valid count')
    need(status['request_timeout_seconds'] == 120.0 and status['automatic_resume'] is False, 'status timeout/no resume')
    need(c['status_events'][-1]['status'] == status['status'] and c['status_events'][-1]['judge_calls'] == len(c['started']), 'final status event')
    if status['status'] == 'COMPLETE':
        need(len(c['terminals']) == COUNT and len(c['returned']) == len(c['started']) and not c['errors'], 'complete coverage and no unresolved errors')
        need(status['corrected_execution_requires_new_direct_authorization'] is False, 'complete authorization status')
        need(c['invocation']['exit_code'] == 0, 'successful process exit')
        need(all(e['returned_model'] == MODEL for e in c['returned']), 'exact returned model')
    else:
        need(status['corrected_execution_requires_new_direct_authorization'] is True and c['errors'], 'incomplete fail-closed evidence')
        need(c['invocation']['exit_code'] != 0, 'incomplete process exit')
        first_failure_time = min(utc(e['timestamp_utc']) for e in c['errors'])
        need(all(utc(e['request_started_at_utc']) <= first_failure_time for e in c['started']), 'no starts after fatal failure')
        need(all(e['terminal_policy'] == 'STOP_ENTIRE_SHARD' for e in c['errors']), 'fatal stop policy')
    errors = Counter()
    for e in c['errors']:
        category, code = str(e.get('error_category', '')), str(e.get('error_code', ''))
        combined = (category + ' ' + code).lower()
        if category in RETRYABLE:
            errors['second_invalid_output'] += 1
        elif 'model' in combined:
            errors['model'] += 1
        elif 'timeout' in combined:
            errors['timeout'] += 1
        elif 'quota' in combined or 'billing' in combined:
            errors['billing'] += 1
        elif 'rate' in combined:
            errors['rate_limit'] += 1
        elif 'authentication' in combined or 'invalid_api_key' in combined:
            errors['authentication'] += 1
        elif 'permission' in combined:
            errors['permission'] += 1
        elif 'refusal' in combined:
            errors['refusal'] += 1
        elif 'connection' in combined or 'transport' in combined:
            errors['transport'] += 1
        else:
            errors['unclassified_fatal'] += 1
    result = {k: errors[k] for k in ('second_invalid_output', 'model', 'timeout', 'billing', 'rate_limit', 'authentication', 'permission', 'refusal', 'transport', 'unclassified_fatal')}
    return {'runner_status': status['status'], 'required_status': 'COMPLETE' if status['status'] == 'COMPLETE' else INCOMPLETE,
        'error_registry_count': len(c['errors']), 'error_counts': result,
        'returned_models': sorted({e['returned_model'] for e in c['returned']}),
        'note': 'Zero error registry entries establish zero failures. Incomplete sanitized errors that lack subtype remain unclassified, never inferred.'}


def verify_durability(c):
    actual = {name: digest((c['output'] / name).read_bytes()) for name in sorted(DURABLE)}
    need(actual == c['snapshot']['durable_file_sha256'], 'durable output unchanged since process exit')
    need(c['snapshot']['runner_has_exited'] is True and c['snapshot']['file_count'] == 6, 'post-exit integrity snapshot')
    need(not list(BASE.rglob('*.pyc')) and not list(BASE.rglob('__pycache__')), 'no artifact bytecode residue')
    return {'file_count': 6, 'durable_file_sha256': actual,
        'terminal_journal_sha256': actual['JUDGE_TERMINAL_JOURNAL.jsonl']}


def verify_blinding_and_secret_absence(c):
    # Inspect only selected blinded request/output structures. Never open a key,
    # restricted mapping, another package, or retained historical Judge output.
    for e in c['returned']:
        c['validator']._forbid_hidden_identity(e['raw_response_content'])
        if e.get('parsed_semantic_result') is not None:
            c['validator']._forbid_hidden_identity(e['parsed_semantic_result'])
    secret_patterns = (rb'\bsk-[A-Za-z0-9_-]{16,}', rb'(?i)bearer\s+[A-Za-z0-9._-]{20,}',
        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    scanned = 0
    for path in sorted(BASE.rglob('*')):
        need(not path.is_symlink(), 'no artifact symlink')
        if path.is_file():
            raw = path.read_bytes()
            need(not any(re.search(pattern, raw) for pattern in secret_patterns), 'credential-like material in artifact')
            scanned += 1
    return {'secret_pattern_matches': 0, 'files_scanned': scanned, 'hidden_identity_matches_in_blinded_outputs': 0,
        'api_key_value_read_for_scan': False,
        'scope_attestation': {'other_corrected_shards_accessed_or_executed': 0, 'old_judge_packages_used': 0,
            'retained_existing_judge_results_rerun': 0, 'condition_or_mode_unblinding': 0, 'system_comparisons': 0,
            'mode_level_scoring': 0, 'human_rating': 0, 'agreement_calculation': 0,
            'statistical_analysis': 0, 'response_generation': 0, 'component_execution': 0,
            'restricted_internal_access': 0, 'final_judge_integration': 0},
        'attestation_basis': 'Task action record, exact request-ID and payload allowlist, frozen runner, and artifact review; forbidden locations were not opened for this audit.'}


CHECKS = (
    ('frozen_package_and_member_hashes', verify_sources),
    ('authorization_and_starting_gates', verify_authorization),
    ('runtime_timeout_and_zero_network_preflight', verify_runtime),
    ('attempt_order_retry_and_identity', verify_attempts),
    ('strict_recorded_initial_start_spacing', verify_strict_recorded_pacing),
    ('parser_applicability_rationales_and_local_mean', verify_results),
    ('all_physical_attempt_token_arithmetic', verify_tokens),
    ('terminal_status_model_and_fail_closed_errors', verify_completion_and_errors),
    ('durable_output_immutability', verify_durability),
    ('blinding_and_secret_absence', verify_blinding_and_secret_absence),
)


def collect_audit(c):
    checks, details = {}, {}
    for name, verify in CHECKS:
        try:
            details[name] = verify(c)
            checks[name] = 'PASS'
        except (AuditFailure, ValueError, KeyError, TypeError) as exc:
            checks[name] = 'FAIL'
            details[name] = {'error_type': type(exc).__name__, 'reason': str(exc)}
    return {'schema_version': 'c4-real-j4b-corrected-judge-execution-audit-v1',
        'status': 'PASS' if all(v == 'PASS' for v in checks.values()) else 'FAIL',
        'audited_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'package_id': PACKAGE_ID, 'shard_id': 'B', 'checks': checks,
        'check_group_count': len(checks), 'passed_check_group_count': sum(v == 'PASS' for v in checks.values()),
        'details': details, 'offline_audit_provider_calls': 0,
        'parsed_result_set_serialization': 'One canonical UTF-8 JSON semantic result per LF-terminated line, in frozen logical request order; no cross-result scoring.',
        'parsed_result_set_sha256': digest(projection(c)),
        'terminal_journal_sha256': digest((c['output'] / 'JUDGE_TERMINAL_JOURNAL.jsonl').read_bytes()),
        'pacing_measurements': pacing_measurements(c)}


def projection(c):
    return b''.join(canonical(t['parsed_semantic_result']) + b'\n' for t in c['terminals'])


def create_artifacts(c):
    audit = collect_audit(c)
    source = {
        'schema_version': 'c4-real-j4b-corrected-judge-execution-source-manifest-v1',
        'package_id': PACKAGE_ID, 'shard_id': 'B', 'working_directory': str(ROOT),
        'branch': BRANCH, 'starting_head': HEAD,
        'package_zip_path': str(c['package_path']), 'package_zip_sha256': PACKAGE_HASH,
        'package_zip_size_bytes': c['package_path'].stat().st_size,
        'member_sha256': {name: digest(raw) for name, raw in sorted(c['members'].items())},
        'member_count': 13, 'extraction_count': 1, 'blinded_judge_manifest_sha256': MANIFEST_HASH,
        'authorization_sha256': AUTH_HASH, 'phase_b_entry_receipt_sha256_binding': ENTRY_HASH,
        'phase_b_original_receipt_accessed': False,
        'durable_file_sha256': c['snapshot']['durable_file_sha256'],
        'parsed_result_set_file': 'parsed_judge_results_v1.jsonl',
        'parsed_result_set_sha256': digest(projection(c)),
        'parsed_result_set_serialization': audit['parsed_result_set_serialization'],
        'support_artifact_sha256': {name: digest((BASE / name).read_bytes()) for name in (
            'starting_gates_v1.json', 'runtime_preflight_v1.json', 'package_validation_v1.json',
            'package_tests_v1.log', 'execution_output_integrity_v1.json', 'runner_invocation_v1.json',
            'audit_corrected_judge_execution_v1.py', 'test_corrected_judge_execution_v1.py')},
        'review_scope': 'Selected Shard B execution artifacts only. Original blinded input ZIP is supplied separately and is not duplicated into the review archive.'}
    for name, value in (('corrected_judge_execution_source_manifest_v1.json', source),
                        ('corrected_judge_execution_audit_v1.json', audit)):
        with (BASE / name).open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    with (BASE / 'parsed_judge_results_v1.jsonl').open('xb') as handle:
        handle.write(projection(c))
    print(json.dumps({'audit_status': audit['status'], 'check_groups': audit['check_group_count'],
        'passed_check_groups': audit['passed_check_group_count'], 'parsed_result_set_sha256': audit['parsed_result_set_sha256'],
        'terminal_journal_sha256': audit['terminal_journal_sha256']}, indent=2))
    return 0 if audit['status'] == 'PASS' else 1


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--package-zip', type=Path, default=PACKAGE)
    cli.add_argument('--check-only', action='store_true')
    args = cli.parse_args()
    with network_guard():
        context = load_context(args.package_zip)
        if args.check_only:
            result = collect_audit(context)
            print(json.dumps({'status': result['status'], 'checks': result['checks']}, indent=2))
            return 0 if result['status'] == 'PASS' else 1
        return create_artifacts(context)


if __name__ == '__main__':
    raise SystemExit(main())
