"""Exactly five saved-input DEV slots; no prepare/router/retrieval or resume path.

The only live client constructor is after validate_preflight, exclusive output
creation, and a flushed/fsynced preflight receipt. Tests inject a mock transport.
"""
from copy import deepcopy
import json
import os
import time
from decimal import Decimal
from i4_common import *
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.renderer import final_payload
from utils.c4_rebuild.i1.schemas import final_errors, strict_schema_check

REPAIR = repair_module()
CORRECTABLE = {'INVALID_JSON', 'SCHEMA', 'ENCODED_CHECK'}
FATAL = {'AUTH', 'BILLING', 'CONFIG', 'MODEL', 'RETURNED_MODEL_MISMATCH',
         'RATE_LIMIT', 'PERMISSION', 'TRANSPORT', 'UNKNOWN_COMPLETION', 'PROVIDER_ERROR'}


class StopRun(RuntimeError):
    pass


def estimate(payload, config):
    units = len(canonical(payload)) + 256
    rates = config['uncached_usd_per_million']
    amount = (Decimal(units) * Decimal(str(rates['input'])) +
              Decimal(payload['max_tokens']) * Decimal(str(rates['output']))) / Decimal(1000000)
    return units, amount


def usage_estimate(usage, config):
    if not isinstance(usage, dict) or not all(type(usage.get(k)) is int and usage[k] >= 0
            for k in ('prompt_tokens', 'completion_tokens')):
        return None
    r = config['uncached_usd_per_million']
    return (Decimal(usage['prompt_tokens']) * Decimal(str(r['input'])) +
            Decimal(usage['completion_tokens']) * Decimal(str(r['output']))) / Decimal(1000000)


def correction_payload(p, result, raw, config):
    """Feedback is constructed only from the new first response and its checker."""
    require(result['status'] in CORRECTABLE, 'NOT_AN_ORDINARY_CORRECTION')
    if result['value'] is not None:
        expected = REPAIR.candidate_issues(p['planner']['bridge'], result['value'])
        if sorted(canonical(x) for x in expected) == sorted(canonical(x) for x in result['issues']):
            return REPAIR.candidate_payload(p, config['generation_roles']['CANDIDATE'],
                previous=result['value'], issues=result['issues']), 'EXACT_I3_PARSED_FEEDBACK'
    # Explicitly tested branch for raw JSON/outer-schema failures. Never create a
    # pretend parsed candidate, or borrow any I3 second-request preview.
    payload = REPAIR.candidate_payload(p, config['generation_roles']['CANDIDATE'])
    choices = raw.get('choices')
    message = choices[0].get('message') if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) else None
    failed_text = message.get('content') if isinstance(message, dict) else None
    diagnostic = dict(status=result['status'], original_issues=deepcopy(result['issues']))
    if isinstance(failed_text, str):
        try:
            json.loads(failed_text)
        except json.JSONDecodeError as exc:
            diagnostic['parse_error'] = dict(type='JSONDecodeError', message=exc.msg,
                line=exc.lineno, column=exc.colno, position=exc.pos)
    body = json.loads(payload['messages'][1]['content'])
    body.update(raw_failed_response_text=failed_text,
        concrete_checker_issues=deepcopy(result['issues']),
        checker_feedback_details=[diagnostic],
        raw_correction_contract='Correct the raw failed response once using the same candidate contract. No parsed candidate is asserted for this branch. Preserve all supplied source facts and constraints.')
    payload['messages'][1]['content'] = canonical(body).decode()
    return payload, 'RAW_PARSE_OR_OUTER_SCHEMA_FEEDBACK'


def binding():
    # Approval explicitly binds code, copied inputs, original config, source registry and user message.
    names = ['i4_common.py', 'verify_sources.py', 'run_i4.py', 'run_tests.py',
             'tests/test_i4.py', 'CONFIG.json', 'INPUT_BINDINGS.json',
             'SOURCE_PRESERVATION_MANIFEST.json', 'DIRECT_USER_APPROVAL_MESSAGE.txt',
             'task_spec/START_HERE.md', 'task_spec/CODEX_I4_LIMITED_PLANNER_RETEST.md']
    return dict(starting_head=START, branch=BRANCH, cwd=str(ROOT), output=str(OUTPUT),
        slots=SLOTS, limits=load(HERE / 'CONFIG.json'),
        files=[file_binding(HERE / n) for n in names],
        repair=file_binding(I3 / 'repair_v1.py'),
        original_config=file_binding(I1 / 'PILOT_CONFIGURATION_PROPOSED.json'),
        source_manifest_sha256=sha((HERE / 'SOURCE_PRESERVATION_MANIFEST.json').read_bytes()),
        initial_request_hashes=[x['proposed_initial_request_sha256'] for x in load_slots()],
        source_kind='EXPOSED_SYNTHETIC_DEV_FAILURE_CATEGORY_SELECTED')


def validate_approval(record, expected):
    keys = {'version','authority','status','recorded_at','timestamp_basis','quotation_boundary',
            'signature_semantics','binding','binding_sha256'}
    require(set(record) == keys and record['version'] == 'I4_DIRECT_APPROVAL_V1', 'I4_APPROVAL_SCHEMA')
    require(record['authority'] == 'DIRECT_USER_MESSAGE_CURRENT_CONVERSATION' and
        record['status'] == 'AUTHORIZED', 'I4_APPROVAL_AUTHORITY')
    require(record['binding'] == expected and record['binding_sha256'] == sha(expected), 'I4_APPROVAL_BINDING')
    require(expected['limits'] == settings() and expected['slots'] == SLOTS, 'I4_CONFIG_CHANGED')


def validate_preflight():
    require(Path.cwd() == ROOT and git('branch','--show-current') == BRANCH and git('rev-parse','HEAD') == START,
        'GIT_SOURCE_IDENTITY_CHANGED')
    require(not git('diff','--name-only') and not git('diff','--cached','--name-only'), 'TRACKED_SOURCE_DRIFT')
    for p in git('ls-files','--others','--exclude-standard').splitlines():
        require(p.startswith(SCOPE), 'UNEXPECTED_UNTRACKED')
    require(not OUTPUT.exists() and not ZIP.exists(), 'EXCLUSIVE_OUTPUT_ALREADY_EXISTS')
    b = binding(); a = load(HERE / 'DIRECT_APPROVAL.json'); validate_approval(a, b)
    check_files(load(HERE / 'SOURCE_PRESERVATION_MANIFEST.json')['files'])
    tests = load(HERE / 'OFFLINE_TEST_SUMMARY.json')
    require(tests['status'] == 'PASS' and tests['failures'] == tests['errors'] == 0 and
        tests['code_binding_sha256'] == sha(b), 'OFFLINE_TESTS_OR_CODE_BINDING')
    require(tests['provider_calls'] == 0 and tests['sdk_client_constructions'] == 0, 'OFFLINE_TEST_BOUNDARY')
    require(all(r['status'] == 'PASS' for r in tests['suites']), 'REQUIRED_TEST_SUITE_FAILED')
    for row in load_slots():
        p = prepared(row)
        require(sha(REPAIR.candidate_payload(p, settings()['generation_roles']['CANDIDATE'])) ==
            row['proposed_initial_request_sha256'], 'INITIAL_REQUEST_DRIFT')
    return dict(status='PASS', utc=utc(), binding=b, approval_sha256=sha(a),
        tests_sha256=sha((HERE / 'OFFLINE_TEST_SUMMARY.json').read_bytes()),
        credentials_accessed=False, client_constructed=False,
        original_runner_invoked=False, source_files_checked=len(load(HERE / 'SOURCE_PRESERVATION_MANIFEST.json')['files']))


class LimitedRunner:
    def __init__(self, directory, config, transport, source_guard=lambda: None,
                 clock=time.monotonic, sleep=time.sleep):
        self.directory, self.config, self.transport = Path(directory), deepcopy(config), transport
        require(self.config == settings(), 'I4_CONFIG_CHANGED')
        self.source_guard, self.clock, self.sleep = source_guard, clock, sleep
        self.starts, self.outcomes, self.last_send = [], [], None
        self.stopped = False

    def stop(self, category, attempt_id=None):
        self.stopped = True
        if not (self.directory / 'STOP.json').exists():
            write_once(self.directory / 'STOP.json', dict(category=category, attempt_id=attempt_id, utc=utc()))
        raise StopRun(category)

    def call(self, row, phase, payload, validator, correction_of=None, final_plan=None):
        if self.stopped or (self.directory / 'STOP.json').exists(): self.stop('STOPPED_NO_RESUME')
        try:
            self.source_guard()
        except Exception:
            self.stop('SOURCE_OR_HARNESS_DRIFT')
        logical = row['logical']
        if logical not in SLOTS or phase not in ('INITIAL','CORRECTION','FINAL'):
            self.stop('ROLE_OR_SLOT_NOT_AUTHORIZED')
        if row != load_slots()[SLOTS.index(logical)]: self.stop('SLOT_SOURCE_BINDING_CHANGED')
        starts = [x for x in self.starts if x['logical'] == logical]
        if any(x['phase'] == phase for x in starts): self.stop('SLOT_ATTEMPT_CEILING')
        if phase == 'INITIAL':
            if starts or sha(payload) != row['proposed_initial_request_sha256']: self.stop('INITIAL_REQUEST_MISMATCH')
        elif phase == 'CORRECTION':
            if len(starts) != 1 or starts[0]['phase'] != 'INITIAL' or not self.outcomes or correction_of != self.outcomes[-1]['attempt_id']:
                self.stop('CORRECTION_NOT_NEW_FIRST_RESULT')
            previous = self.outcomes[-1]
            if previous['status'] not in CORRECTABLE: self.stop('CORRECTION_NOT_ALLOWED')
            new_payload, _ = correction_payload(prepared(row), previous,
                load(self.directory / 'attempts' / (correction_of + '.raw.json')), self.config)
            if payload != new_payload: self.stop('FRESH_CORRECTION_HASH_MISMATCH')
        else:
            accepted = [x for x in self.outcomes if x['logical'] == logical and x['phase'] != 'FINAL' and x['status'] == 'ACCEPTED']
            if len(accepted) != 1 or accepted[0]['value'] != final_plan: self.stop('FINAL_NO_NEW_ACCEPTED_PLAN')
            if REPAIR.candidate_issues(prepared(row)['planner']['bridge'], final_plan): self.stop('FINAL_PLAN_CHECK_FAILED')
            expected = final_payload(prepared(row), self.config['generation_roles']['FINAL'], final_plan, False)
            if payload != expected or sha(payload) == row['prior_final_request_sha256']: self.stop('FINAL_INPUT_UNCHANGED_OR_RENDERER_DRIFT')
        if len(self.starts) >= self.config['caps']['TOTAL']: self.stop('TOTAL_PHYSICAL_CALL_CEILING')
        if sum(x['phase'] == phase for x in self.starts) >= self.config['caps'][phase]: self.stop('ROLE_CALL_CEILING')
        role = 'FINAL' if phase == 'FINAL' else 'CANDIDATE'
        cfg = self.config['generation_roles'][role]
        if (payload['model'] != cfg['model'] or payload['temperature'] != 0 or payload['max_tokens'] != 2048
                or payload['stream'] is not False or 'tools' in payload): self.stop('MODEL_OR_REQUEST_CONFIG_MISMATCH')
        strict_schema_check(payload['response_format']['json_schema']['schema'])
        units, reserved = estimate(payload, self.config)
        if units > self.config['max_request_input_byte_units']: self.stop('REQUEST_INPUT_BOUND_EXCEEDED')
        charges = []
        for start in self.starts:
            outcome = next((o for o in self.outcomes if o['attempt_id'] == start['attempt_id']), {})
            known = usage_estimate(outcome.get('usage'), self.config)
            charges.append(max(Decimal(start['reserved_estimate_usd']), known or Decimal(0)))
        if sum(charges, Decimal(0)) + reserved > Decimal(str(self.config['estimated_budget_cap_usd'])):
            self.stop('ESTIMATED_BUDGET_EXHAUSTED')
        # Pace actual transport dispatch starts. Reservations are fsynced first;
        # dispatch marks are also durable before the single send invocation.
        if self.last_send is not None:
            while self.clock() - self.last_send < 2.0:
                self.sleep(2.0 - (self.clock() - self.last_send))
        aid = f'{SLOTS.index(logical)+1:02}_{phase.lower()}'
        start = dict(attempt_id=aid, logical=logical, phase=phase, role=role,
            prepared_sha256=sha(prepared(row)), i3_bridge_sha256=row['frozen_input_sha256'],
            request=payload, request_sha256=sha(payload), utc=utc(), input_byte_units=units,
            reserved_estimate_usd=str(reserved), completion='UNKNOWN', usage=None,
            correction_of=correction_of, source_guard='PASS', transport_kind=self.transport.kind)
        write_once(self.directory / 'attempts' / (aid + '.start.json'), start)
        append(self.directory / 'JOURNAL.jsonl', dict(event='RESERVED_BEFORE_TRANSPORT', **start))
        self.starts.append(start)
        # If a prior dispatch is less than 2 seconds away, wait again after fsync.
        if self.last_send is not None:
            while self.clock() - self.last_send < 2.0:
                self.sleep(2.0 - (self.clock() - self.last_send))
        write_once(self.directory / 'attempts' / (aid + '.dispatch.json'),
            dict(attempt_id=aid, utc=utc(), monotonic_before_dispatch=self.clock()))
        actual_start = self.clock(); self.last_send = actual_start
        try:
            raw = self.transport.send(payload)
        except BaseException as exc:
            # Exception reprs and HTTP headers are intentionally never persisted.
            category = getattr(exc, 'category', 'UNKNOWN_COMPLETION')
            if category not in FATAL: category = 'UNKNOWN_COMPLETION'
            raw = dict(_transport_failure=True, category=category,
                exception_type=type(exc).__name__, request_id=getattr(exc, 'request_id', None), usage=None)
        actual_end = self.clock()
        write_once(self.directory / 'attempts' / (aid + '.timing.json'), dict(attempt_id=aid,
            monotonic_start=actual_start, monotonic_end=actual_end, utc_end=utc(), clock_scope='CURRENT_PROCESS'))
        write_once(self.directory / 'attempts' / (aid + '.raw.json'), raw)
        if raw.get('_transport_failure'):
            status, value, issues = raw['category'], None, [raw['category']]
        else:
            try:
                status, value, issues = parse_response(raw, payload, validator)
            except Exception as exc:
                status, value, issues = 'UNKNOWN_COMPLETION', None, ['UNEXPECTED_RESPONSE_OR_LOCAL_VALIDATION_EXCEPTION', type(exc).__name__]
        outcome = dict(attempt_id=aid, logical=logical, phase=phase, role=role, status=status,
            value=value, issues=issues, returned_model=raw.get('model'), usage=raw.get('usage'),
            raw_sha256=sha((self.directory / 'attempts' / (aid + '.raw.json')).read_bytes()),
            request_sha256=sha(payload), request_id=raw.get('_request_id') or raw.get('id') or raw.get('request_id'),
            completion='UNKNOWN' if status == 'UNKNOWN_COMPLETION' else 'OBSERVED',
            monotonic_start=actual_start, monotonic_end=actual_end, utc=utc(),
            semantic_support='NOT_CHECKED', human_scores=[])
        write_once(self.directory / 'attempts' / (aid + '.outcome.json'), outcome)
        append(self.directory / 'JOURNAL.jsonl', dict(event='ATTEMPT_OUTCOME', **outcome))
        self.outcomes.append(outcome)
        print(canonical(dict(event='ATTEMPT_OUTCOME', slot=logical, phase=phase, status=status)).decode(), flush=True)
        if status in FATAL: self.stop(status, aid)
        known = usage_estimate(outcome['usage'], self.config)
        if sum(charges, Decimal(0)) + max(reserved, known or Decimal(0)) > Decimal(str(self.config['estimated_budget_cap_usd'])):
            self.stop('OBSERVED_USAGE_EXCEEDS_ESTIMATED_BUDGET', aid)
        return outcome

    def execute(self):
        rows = [dict(logical=x, candidate_status='NOT_ATTEMPTED', selected_attempt=None,
                     accepted_plan_sha256=None, final_eligible=False, final_called=False,
                     final_status='NOT_ATTEMPTED', correction_branch=None) for x in SLOTS]
        reason = None
        try:
            for row, outcome in zip(load_slots(), rows):
                p = prepared(row); initial = REPAIR.candidate_payload(p, self.config['generation_roles']['CANDIDATE'])
                validator = lambda v: REPAIR.candidate_issues(p['planner']['bridge'], v)
                r = self.call(row, 'INITIAL', initial, validator)
                outcome['candidate_status'] = r['status']
                if r['status'] in CORRECTABLE:
                    raw = load(self.directory / 'attempts' / (r['attempt_id'] + '.raw.json'))
                    try:
                        corrected, branch = correction_payload(p, r, raw, self.config)
                    except Exception as exc:
                        outcome['candidate_status'] = 'FAILED_CORRECTION_UNAVAILABLE'
                        outcome['correction_error_type'] = type(exc).__name__
                    else:
                        outcome['correction_branch'] = branch
                        r = self.call(row, 'CORRECTION', corrected, validator, correction_of=r['attempt_id'])
                        outcome['candidate_status'] = r['status']
                if r['status'] == 'ACCEPTED':
                    accepted = r['value']
                    outcome.update(selected_attempt=r['attempt_id'], accepted_plan_sha256=sha(accepted))
                    final = final_payload(p, self.config['generation_roles']['FINAL'], accepted, False)
                    outcome['new_final_request_sha256'] = sha(final)
                    outcome['final_eligible'] = sha(final) != row['prior_final_request_sha256']
                    if outcome['final_eligible']:
                        f = self.call(row, 'FINAL', final,
                            lambda v: final_errors(v, p['trace']['retained_evidence_ids'], accepted), final_plan=accepted)
                        outcome.update(final_called=True, final_status=f['status'])
                    else:
                        outcome['final_status'] = 'NOT_CALLED_UNCHANGED_INPUT'
                else:
                    outcome['final_status'] = 'NOT_CALLED_NO_ACCEPTED_PLAN'
                write_once(self.directory / 'terminals' / (f'{SLOTS.index(row["logical"])+1:02}.json'), outcome)
                append(self.directory / 'JOURNAL.jsonl', dict(event='SLOT_TERMINAL', **outcome))
        except StopRun as exc:
            reason = str(exc)
        except BaseException as exc:
            reason = 'UNEXPECTED_LOCAL_STOP:' + type(exc).__name__
            if not (self.directory / 'STOP.json').exists():
                write_once(self.directory / 'STOP.json', dict(category=reason, utc=utc()))
        # Reconcile every begun slot from durable attempts even if stopped mid-slot.
        for row in rows:
            attempts = [x for x in self.outcomes if x['logical'] == row['logical']]
            cs = [x for x in attempts if x['role'] == 'CANDIDATE']
            fs = [x for x in attempts if x['role'] == 'FINAL']
            row['attempt_ids'] = [x['attempt_id'] for x in attempts]
            if cs: row['candidate_status'] = cs[-1]['status']
            if fs: row.update(final_called=True, final_status=fs[-1]['status'])
            if reason and not (self.directory / 'terminals' / f'{SLOTS.index(row["logical"])+1:02}.json').exists():
                row['execution_state'] = 'STOPPED_PARTIAL' if attempts else 'UNATTEMPTED_AFTER_STOP'
                write_once(self.directory / 'terminals' / f'{SLOTS.index(row["logical"])+1:02}.json', row)
                append(self.directory / 'JOURNAL.jsonl', dict(event='STOP_TERMINAL', **row))
            else:
                row['execution_state'] = 'BOUNDED_SLOT_COMPLETE'
        summary = dict(status='PRESERVED_EARLY_STOP' if reason else 'BOUNDED_EXECUTION_COMPLETE',
            stop_reason=reason, slots=rows, phase_counts={k:sum(s['phase']==k for s in self.starts) for k in ('INITIAL','CORRECTION','FINAL')},
            total_physical_calls=len(self.starts), semantic_support='NOT_CHECKED', human_scores=0,
            router_calls=0,retrieval_calls=0,memory_calls=0,embedding_calls=0,judge_calls=0,utc=utc())
        write_once(self.directory / 'RUN_SUMMARY.json', summary)
        return summary


class ExactOpenAITransport:
    kind = 'LIVE'

    def __init__(self):
        # Only called after the durable PREFLIGHT receipt. No probes or model list.
        from openai import OpenAI
        import httpx
        for key in ('OPENAI_BASE_URL','OPENAI_API_BASE'):
            if os.environ.get(key) and os.environ[key].rstrip('/') != 'https://api.openai.com/v1':
                raise ValueError('EXISTING_ENDPOINT_CONFIG_MISMATCH')
        self.http = httpx.Client(timeout=30, follow_redirects=False)
        self.client = OpenAI(max_retries=0, timeout=30, base_url='https://api.openai.com/v1', http_client=self.http)
        require(self.client.max_retries == 0 and str(self.client.base_url).rstrip('/') == 'https://api.openai.com/v1', 'CLIENT_CONFIG_MISMATCH')

    def send(self, payload):
        from utils.c4_rebuild.i1.transport import TransportFailure
        try:
            r = self.client.chat.completions.create(**payload)
            data = r.model_dump(mode='json'); data['_request_id'] = getattr(r, '_request_id', None)
            return data
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            body = getattr(exc, 'body', None)
            error = body.get('error', body) if isinstance(body, dict) else {}
            code = error.get('code') if isinstance(error, dict) else None
            category = ('AUTH' if status == 401 else 'PERMISSION' if status == 403 else
                'BILLING' if code in ('insufficient_quota','billing_hard_limit_reached') else
                'MODEL' if status == 404 else 'CONFIG' if status in (400,422) else
                'RATE_LIMIT' if status == 429 else 'UNKNOWN_COMPLETION')
            # No error body/message/headers are logged, as they may contain credentials.
            raise TransportFailure(category, request_id=getattr(exc, 'request_id', None)) from None

    def close(self):
        self.client.close()


def begin_output(directory, receipt, approval):
    validate_approval(approval, receipt['binding'])
    require(receipt['status'] == 'PASS', 'PREFLIGHT_NOT_PASSED')
    Path(directory).mkdir(exist_ok=False)
    write_once(Path(directory) / 'PREFLIGHT.json', receipt)
    write_once(Path(directory) / 'DIRECT_APPROVAL.json', approval)


def main():
    receipt = validate_preflight()
    begin_output(OUTPUT, receipt, load(HERE / 'DIRECT_APPROVAL.json'))
    client = None
    try:
        client = ExactOpenAITransport()
        write_once(OUTPUT / 'CLIENT_CONFIGURATION.json', dict(utc=utc(), sdk_retries=0,timeout_seconds=30,
            automatic_redirects=False,endpoint='https://api.openai.com/v1',serial=True,credentials_logged=False))
        files = load(HERE / 'SOURCE_PRESERVATION_MANIFEST.json')['files'] + receipt['binding']['files']
        def guard():
            check_files(files)
            require(git('rev-parse','HEAD') == START and git('branch','--show-current') == BRANCH, 'GIT_DRIFT')
            require(not git('diff','--name-only') and not git('diff','--cached','--name-only'), 'TRACKED_DRIFT')
        runner = LimitedRunner(OUTPUT, settings(), client, guard)
        result = runner.execute()
        print(canonical(dict(status=result['status'],counts=result['phase_counts'],stop_reason=result['stop_reason'])).decode())
    except BaseException as exc:
        if not (OUTPUT / 'RUN_SUMMARY.json').exists():
            write_once(OUTPUT / 'STOP.json', dict(category='CLIENT_OR_PREFLIGHT_LOCAL_FAILURE', exception_type=type(exc).__name__, utc=utc()))
            write_once(OUTPUT / 'RUN_SUMMARY.json', dict(status='PRESERVED_EARLY_STOP',
                stop_reason='CLIENT_OR_PREFLIGHT_LOCAL_FAILURE:' + type(exc).__name__, total_physical_calls=0,
                phase_counts=dict(INITIAL=0,CORRECTION=0,FINAL=0),slots=[dict(logical=s,execution_state='UNATTEMPTED_AFTER_STOP') for s in SLOTS]))
        print('PRESERVED_EARLY_STOP_NO_AUTOMATIC_RETRY', flush=True)
    finally:
        if client: client.close()


if __name__ == '__main__':
    main()
