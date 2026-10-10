"""A3 control: preserved receipts, bounded continuation, fatal local guard errors."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import errno
import json
import os
import re
import ssl
import sys
import time

HERE = Path(__file__).resolve().parent
A1 = HERE.parent / 'confirmed41_repair_continuation_2026-09-08'
sys.dont_write_bytecode = True
sys.path.insert(0, str(A1))
from a1_common import ROOT, DATA, base, legacy, canonical, sha, load, write_once, append, utc, rows
from parent_ledger import debit
from utils.c4_rebuild.i1.durable import DurableRunner, StopRun, parse_response, FATAL, RETRYABLE
from utils.c4_rebuild.i1.schemas import strict_schema_check

VERSION = 'CONFIRMED41_MEMORY_PROCESS_ISOLATION_V1'
A2 = HERE.parent / 'confirmed41_remaining_generation_2026-09-08'
EXISTING_UNKNOWNS = load(HERE/'RECOVERY_POLICY.json')['existing_unknown_resends']


def safe_exception(exc, phase):
    """No repr, message, body, headers, request URL, or environment values."""
    chain, seen, current = [], set(), exc
    permanent = False
    local_code = None
    while current is not None and id(current) not in seen and len(chain) < 16:
        seen.add(id(current))
        cls = type(current)
        name = re.sub(r'[^a-zA-Z0-9_.]', '_', cls.__module__ + '.' + cls.__name__)[:160]
        eno = getattr(current, 'errno', None)
        if type(current) is RuntimeError and current.args == ('M0_NETWORK_DISABLED',):
            local_code = 'M0_NETWORK_DISABLED'
            permanent = True
        chain.append({'class': name, 'errno': eno if type(eno) is int else None})
        permanent |= isinstance(current, (ssl.SSLCertVerificationError, PermissionError))
        permanent |= isinstance(current, ssl.SSLError) and getattr(current, 'reason', None) in {
            'CERTIFICATE_VERIFY_FAILED', 'NO_PROTOCOLS_AVAILABLE', 'NO_CIPHERS_AVAILABLE'}
        permanent |= type(eno) is int and eno in (errno.EACCES, errno.EPERM)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    status = getattr(exc, 'status_code', None)
    return dict(exception_chain=chain, phase=phase, status_code=status if type(status) is int else None,
                response_present=getattr(exc, 'response', None) is not None,
                permanent_configuration_or_permission=bool(permanent),
                sensitive_fields_omitted=True, local_configuration_code=local_code)


class RecoveryTransport:
    kind = 'LIVE'

    def __init__(self, *, approved, timeout=30, factory=None):
        if approved is not True or timeout != 30:
            raise PermissionError('EXACT_APPROVED_TRANSPORT_REQUIRED')
        import logging
        from openai import OpenAI
        self.factory = factory or OpenAI
        # Avoid credential-bearing debug output, including inherited OPENAI_LOG.
        for name in ('openai', 'httpx', 'httpcore'):
            logging.getLogger(name).setLevel(logging.WARNING)
        self.kwargs = dict(max_retries=0, timeout=timeout, base_url='https://api.openai.com/v1')
        self.environment = {k: os.environ.get(k) for k in (
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy',
            'SSL_CERT_FILE','SSL_CERT_DIR')}
        self.client = self.factory(**self.kwargs)
        # Capture effective credentials privately so rebuilds cannot select a new account.
        for name in ('api_key', 'organization', 'project'):
            self.kwargs[name] = getattr(self.client, name)
        self.verify_client()

    def verify_client(self):
        if self.client.max_retries != 0 or str(self.client.base_url) != 'https://api.openai.com/v1/':
            raise StopRun('TRANSPORT_CONFIG_CHANGED')

    def rebuild(self):
        if any(os.environ.get(k) != v for k, v in self.environment.items()):
            raise StopRun('TRANSPORT_ENVIRONMENT_CHANGED')
        self.client.close()
        self.client = self.factory(**self.kwargs)
        self.verify_client()

    def send(self, payload):
        from openai import APIConnectionError, APITimeoutError
        began = time.monotonic()
        try:
            response = self.client.chat.completions.create(**payload)
            raw = response.model_dump(mode='json')
            raw['_request_id'] = getattr(response, '_request_id', None)
            return raw
        except Exception as exc:
            diag = safe_exception(exc, 'CHAT_COMPLETIONS_CREATE')
            diag['elapsed_seconds'] = time.monotonic() - began
            status = diag['status_code']
            body = getattr(exc, 'body', None)
            err = (body.get('error') or body) if isinstance(body, dict) else {}
            code = err.get('code') if isinstance(err, dict) else None
            billing = code in ('insufficient_quota', 'billing_hard_limit_reached')
            category = ('AUTH' if status in (401, 403) else 'BILLING' if billing else
                        'CONFIG' if diag['permanent_configuration_or_permission'] or status in (400, 422) else
                        'MODEL' if status == 404 else 'RATE_LIMIT' if status == 429 else
                        'UNKNOWN_COMPLETION' if status is None or status >= 500 else 'PROVIDER_ERROR')
            network = (isinstance(exc, (APIConnectionError, APITimeoutError)) and
                       not diag['response_present'] and category == 'UNKNOWN_COMPLETION')
            return dict(_transport_failure=True, category=category, detail=diag,
                        network_recovery_eligible=network, _request_id=None, usage=None, model=None)

    def close(self):
        self.client.close()


def dependency_blocked(result):
    # An unobserved provider response cannot masquerade as a rejected plan.
    return (result['status'] == 'UNKNOWN_COMPLETION' or result.get('completion') == 'UNKNOWN'
            or result.get('returned_model') is None)


class RecoveryRunner(DurableRunner):
    def __init__(self, directory, config, binding, transport, parent, **kwargs):
        self.parent = parent
        self.policy = load(HERE/'RECOVERY_POLICY.json')
        self.failure_streak = 0
        super().__init__(directory, config, binding, transport, **kwargs)
        if (self.directory/'PRESERVATION_STOP.json').exists():
            self.close()
            raise StopRun('PRESERVATION_STOP_NO_ORDINARY_RESUME')
        events = rows(self.directory/'LOGICAL_RECOVERY.jsonl') if (self.directory/'LOGICAL_RECOVERY.jsonl').exists() else []
        if events:
            self.failure_streak = events[-1]['consecutive_connection_exhaustions']

    def reserve(self, logical, role, attempt, payload, initial_hash):
        starts = [load(p) for p in (self.directory/'attempts').glob('*.start.json')]
        group = 'ROUTE' if role in ('RAG', 'MEMORY', 'B4_PLANNING') else role
        if sum(s['group'] == group for s in starts) >= self.policy['physical_caps'][group]:
            raise StopRun('ROLE_PHYSICAL_CEILING')
        if self.parent.physical_calls + len(starts) >= self.policy['cumulative_physical_cap']:
            raise StopRun('CUMULATIVE_PHYSICAL_CEILING')
        if sum(s['logical'] == logical for s in starts) >= (1 if logical in EXISTING_UNKNOWNS else 2):
            raise StopRun('SHARED_LOGICAL_ATTEMPT_CEILING')
        rates = self.config['uncached_usd_per_million']
        next_debit = ((len(canonical(payload))+256)*rates['input'] + payload['max_tokens']*rates['output'])/1e6
        if self.parent.budget_debit + debit(starts, self.directory, rates) + next_debit > 10:
            raise StopRun('CUMULATIVE_MONEY_CEILING_NO_TRANSPORT')
        return super().reserve(logical, role, attempt, payload, initial_hash)

    def outcome(self, start, payload, validator):
        aid = start['attempt_id']
        raw_path = self.directory/'attempts'/f'{aid}.raw.json'
        if not raw_path.exists():
            raise StopRun('UNKNOWN_IN_FLIGHT_NO_AUTOMATIC_CRASH_REPLAY')
        raw = load(raw_path)
        if raw.get('_transport_failure'):
            status, value, issues = raw['category'], None, [raw['detail']]
        else:
            status, value, issues = parse_response(raw, payload, validator)
        result = dict(status=status, value=value, issues=issues, raw_sha256=sha(raw_path.read_bytes()),
            returned_model=raw.get('model'), request_id=raw.get('_request_id') or raw.get('id'), usage=raw.get('usage'),
            attempt_id=aid, request_sha256=start['request_sha256'], utc=utc(), monotonic_end=self.clock(),
            completion='UNKNOWN' if status=='UNKNOWN_COMPLETION' else 'OBSERVED',
            network_recovery_eligible=raw.get('network_recovery_eligible', False))
        write_once(self.directory/'attempts'/f'{aid}.outcome.json', result)
        append(self.directory/'JOURNAL.jsonl', dict(event='ATTEMPT_OUTCOME', **result))
        return result

    def perform(self, logical, role, initial_payload, validator=lambda value: [], repair=None):
        if (self.directory/'STOP.json').exists() or (self.directory/'PRESERVATION_STOP.json').exists():
            raise StopRun('FATAL_RUN_STOP_NO_FURTHER_CALLS')
        reused = self.parent.accepted(logical, role, initial_payload)
        if reused:
            result, receipt = reused
            self.stage(logical, 'PARENT_REUSE', {'payload':sha(initial_payload)}, receipt)
            return result
        strict_schema_check(initial_payload['response_format']['json_schema']['schema'])
        initial_hash = sha(initial_payload)
        terminal_path = self.directory/'terminals'/f'{sha(logical)}.json'
        if terminal_path.exists():
            t = load(terminal_path)
            if t['logical'] != logical or t['initial_request_sha256'] != initial_hash:
                raise StopRun('TERMINAL_BINDING_MISMATCH')
            op = self.directory/'attempts'/f"{t['attempt_id']}.outcome.json"
            if sha(op.read_bytes()) != t['outcome_sha256'] or load(op) != t['result']:
                raise StopRun('TERMINAL_RECEIPT_MISMATCH')
            rp = self.directory/'attempts'/f"{t['attempt_id']}.raw.json"
            if sha(rp.read_bytes()) != t['result']['raw_sha256']:
                raise StopRun('RAW_RECEIPT_MISMATCH')
            return t['result']
        offset = 0
        if logical in EXISTING_UNKNOWNS:
            permission = self.parent.unknown_permission(logical, initial_payload)
            self.stage(logical, 'HISTORICAL_UNKNOWN_PERMISSION', {'payload':initial_hash}, permission)
            offset = 1
            append(self.directory/'RECOVERY_EVENTS.jsonl', dict(event='HISTORICAL_NETWORK_RETRY_WAIT_BEGIN',
                logical=logical,payload_sha256=initial_hash,utc=utc(),monotonic=self.clock(),wait_seconds=10))
            self.sleep(10)
            self.transport.rebuild()
            append(self.directory/'RECOVERY_EVENTS.jsonl', dict(event='CLIENT_REBUILT_SAME_CONFIGURATION',
                logical=logical,payload_sha256=initial_hash,utc=utc(),monotonic=self.clock(),sdk_retries=0))
        payload = deepcopy(initial_payload)
        all_connection = True
        actual_new_attempts = 0
        for attempt in range(1, 3-offset):
            aid = sha(logical)+f'.{attempt}'
            start_path = self.directory/'attempts'/f'{aid}.start.json'
            if start_path.exists():
                start = load(start_path)
                if start['initial_request_sha256'] != initial_hash or start['request_sha256'] != sha(payload):
                    raise StopRun('ATTEMPT_REQUEST_CHANGED')
                op = self.directory/'attempts'/f'{aid}.outcome.json'
                if not op.exists():
                    raise StopRun('UNKNOWN_IN_FLIGHT_NO_AUTOMATIC_CRASH_REPLAY')
                result = load(op)
                if sha((self.directory/'attempts'/f'{aid}.raw.json').read_bytes()) != result['raw_sha256']:
                    raise StopRun('RAW_RECEIPT_MISMATCH')
            else:
                start = self.reserve(logical, role, attempt, payload, initial_hash)
                actual_new_attempts += 1
                raw = self.transport.send(payload)
                write_once(self.directory/'attempts'/f'{aid}.raw.json', raw)
                result = self.outcome(start, payload, validator)
            network = result.get('network_recovery_eligible', False)
            all_connection = all_connection and network
            if not network and result['completion'] == 'OBSERVED':
                self.failure_streak = 0
            if result['status'] in FATAL or (result['status']=='UNKNOWN_COMPLETION' and not network):
                write_once(self.directory/'STOP.json', dict(category=result['status'], attempt_id=aid, utc=utc()))
                raise StopRun('UNRECOVERABLE_'+result['status'])
            if result['status']=='ACCEPTED' or result['status'] not in RETRYABLE | {'UNKNOWN_COMPLETION'}:
                break
            if attempt < 2-offset:
                if network:
                    append(self.directory/'RECOVERY_EVENTS.jsonl', dict(event='NETWORK_RETRY_WAIT_BEGIN',
                        logical=logical, failed_attempt_id=aid, payload_sha256=sha(payload), utc=utc(),
                        monotonic=self.clock(), wait_seconds=10, cumulative_next_attempt=attempt+offset+1))
                    self.sleep(10)
                    self.transport.rebuild()
                    append(self.directory/'RECOVERY_EVENTS.jsonl', dict(event='CLIENT_REBUILT_SAME_CONFIGURATION',
                        logical=logical, payload_sha256=sha(payload), utc=utc(), monotonic=self.clock(), sdk_retries=0))
                elif repair and result['status'] in ('SCHEMA','INVALID_JSON','ENCODED_CHECK'):
                    payload = repair(result['value'], result['issues'])
        terminal = dict(logical=logical, initial_request_sha256=initial_hash, attempt_id=result['attempt_id'],
            outcome_sha256=sha((self.directory/'attempts'/f"{result['attempt_id']}.outcome.json").read_bytes()), result=result)
        write_once(terminal_path, terminal)
        append(self.directory/'JOURNAL.jsonl', dict(event='LOGICAL_TERMINAL', logical=logical, status=result['status']))
        connection_exhausted = result.get('network_recovery_eligible', False)
        if connection_exhausted:
            self.failure_streak += 1
        else:
            self.failure_streak = 0
        append(self.directory/'LOGICAL_RECOVERY.jsonl', dict(logical=logical, status=result['status'],
            new_physical_attempts=actual_new_attempts, historical_attempt_offset=offset,
            connection_attempts_exhausted=connection_exhausted,all_attempts_connection_errors=all_connection,
            consecutive_connection_exhaustions=self.failure_streak, utc=utc()))
        if self.failure_streak >= 3:
            write_once(self.directory/'STOP.json', dict(category='THREE_CONSECUTIVE_CONNECTION_EXHAUSTIONS', utc=utc()))
            raise StopRun('THREE_CONSECUTIVE_CONNECTION_EXHAUSTIONS')
        return result
