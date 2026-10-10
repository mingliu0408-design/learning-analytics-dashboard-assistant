"""I6: one source-bound reused candidate plus four unchanged I5 initial requests.

Derived from the frozen I5 runner; this is a separate versioned run, not I5 resume.

The only live client constructor is after validate_preflight, exclusive output
creation, and a flushed/fsynced preflight receipt. Tests inject a mock transport.
"""
from copy import deepcopy
import json
import os
import time
from decimal import Decimal
from i6_common import *
from utils.c4_rebuild.i1.durable import parse_response
from final_reference_v1 import final_payload
from utils.c4_rebuild.i1.schemas import final_errors, strict_schema_check


CORRECTABLE = {'INVALID_JSON', 'SCHEMA', 'ENCODED_CHECK'}
FATAL = {'AUTH', 'BILLING', 'CONFIG', 'MODEL', 'RETURNED_MODEL_MISMATCH',
         'RATE_LIMIT', 'PERMISSION', 'TRANSPORT', 'UNKNOWN_COMPLETION', 'PROVIDER_ERROR', 'REFUSAL', 'TRUNCATED'}


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
                previous=result['value'], issues=result['issues']), 'EXACT_I5_PARSED_FEEDBACK'
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


def reused_candidate():
    """Validate actual I5 candidate anew without altering its bytes or plan."""
    row = load_slots()[0]; p = prepared(row)
    prefix = HERE / 'historical_i5/live/attempts'
    start = load(prefix / '01_initial.start.json')
    raw = load(prefix / '01_initial.raw.json')
    saved = load(prefix / '01_initial.outcome.json')
    for kind in ('start', 'raw', 'outcome'):
        path = f'live/attempts/01_initial.{kind}.json'
        require((HERE / 'historical_i5' / path).read_bytes() == (I5 / path).read_bytes(), 'REUSE_SOURCE_BYTES')
    require(start['logical'] == row['logical'] and start['prepared_sha256'] == row['prepared_sha256'], 'REUSE_PREPARED_BINDING')
    require(start['request'] == load(HERE / 'requests/01_initial.json') and
            start['request_sha256'] == row['proposed_initial_request_sha256'], 'REUSE_REQUEST_BINDING')
    require(start['i3_bridge_sha256'] == row['frozen_input_sha256'], 'REUSE_BRIDGE_BINDING')
    require(saved['raw_sha256'] == sha((prefix / '01_initial.raw.json').read_bytes()), 'REUSE_RAW_BINDING')
    status, value, issues = parse_response(raw, start['request'], lambda c: REPAIR.candidate_issues(p['planner']['bridge'], c))
    require(status == saved['status'] == 'ACCEPTED' and value == saved['value'] and issues == saved['issues'] == [], 'REUSE_ORIGINAL_VALIDATION')
    require(REPAIR.ORIGINAL.candidate_issues(p['planner']['bridge'], value) == [], 'REUSE_P0_P1_VALIDATION')
    return dict(version='I6_SOURCE_BOUND_I5_REUSE_V1', logical=row['logical'], candidate=value,
        candidate_sha256=sha(value), prepared_sha256=sha(p), bridge_sha256=sha(p['planner']['bridge']),
        raw_sha256=saved['raw_sha256'], source_start_sha256=sha((prefix / '01_initial.start.json').read_bytes()),
        source_outcome_sha256=sha((prefix / '01_initial.outcome.json').read_bytes()), original_request_sha256=sha(start['request']),
        i5_validation='ACCEPTED', original_validation_issues=[], new_candidate_calls=0,
        original_attempt='I5:01_initial', source_archive_sha256=ARCHIVE_SHA, source_head=START)


def binding():
    names = {str(p.relative_to(HERE)) for p in HERE.rglob('*.py')}
    for folder in ('inputs','requests','schemas','task_spec'):
        names.update(str(p.relative_to(HERE)) for p in (HERE/folder).rglob('*') if p.is_file())
    names.update(r['path'] for r in load(HERE/'SOURCE_PRESERVATION_MANIFEST.json')['captures'])
    names.update(['CONFIG.json','INPUT_BINDINGS.json','SOURCE_PRESERVATION_MANIFEST.json',
                  'DIRECT_USER_APPROVAL_MESSAGE.txt','APPROVAL_SCHEMA.json','CANDIDATE_REUSE_RECEIPT.json',
                  'FINAL_REFERENCE_CONTRACT_V1.md','FINAL_REFERENCE_CONTRACT_V1.json',
                  'CANDIDATE_REQUEST_VERIFICATION.json','ALLOWED_SOURCE_IDS.json','OLD_FAILURE_REPLAY.json'])
    return dict(version='I6_PRECALL_BINDING_V1', starting_head=START, branch=BRANCH,cwd=str(ROOT),output=str(OUTPUT),
        slots=SLOTS,limits=load(HERE/'CONFIG.json'),files=[file_binding(HERE/n) for n in sorted(names)],
        source_manifest_sha256=sha((HERE/'SOURCE_PRESERVATION_MANIFEST.json').read_bytes()),
        initial_request_hashes=[r['proposed_initial_request_sha256'] for r in load_slots()],
        reuse_sha256=sha(reused_candidate()),source_kind='EXPOSED_SYNTHETIC_DEV_ONLY')


def validate_approval(record, expected):
    from utils.c4_rebuild.i1.schemas import errors
    require(not errors(record, load(HERE / 'APPROVAL_SCHEMA.json')), 'I6_APPROVAL_SCHEMA')
    keys = {'version','authority','status','recorded_at','timestamp_basis','quotation_boundary',
            'signature_semantics','binding','binding_sha256'}
    require(set(record) == keys and record['version'] == 'I6_DIRECT_APPROVAL_V1', 'I6_APPROVAL_SCHEMA')
    require(record['authority'] == 'DIRECT_USER_MESSAGE_CURRENT_CONVERSATION' and
        record['status'] == 'AUTHORIZED', 'I6_APPROVAL_AUTHORITY')
    require(record['binding'] == expected and record['binding_sha256'] == sha(expected), 'I6_APPROVAL_BINDING')
    require(expected['limits'] == settings() and expected['slots'] == SLOTS, 'I6_CONFIG_CHANGED')


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
    require(tests['status'] == 'PASS' and tests['failures'] == tests['errors'] == tests['skipped'] == 0 and
        tests['code_binding_sha256'] == sha(b), 'OFFLINE_TESTS_OR_CODE_BINDING')
    require(tests['provider_calls'] == 0 and tests['sdk_client_constructions'] == 0, 'OFFLINE_TEST_BOUNDARY')
    require(all(r['status'] == 'PASS' for r in tests['suites']), 'REQUIRED_TEST_SUITE_FAILED')
    for row in load_slots():
        p = prepared(row)
        require(sha(REPAIR.candidate_payload(p, settings()['generation_roles']['CANDIDATE'])) ==
            row['proposed_initial_request_sha256'], 'INITIAL_REQUEST_DRIFT')
        require(load(HERE/'requests'/f'{SLOTS.index(row["logical"])+1:02}_initial.json') ==
                REPAIR.candidate_payload(p, settings()['generation_roles']['CANDIDATE']), 'SAVED_INITIAL_REQUEST_DRIFT')
        initial_path = HERE/'requests'/f'{SLOTS.index(row["logical"])+1:02}_initial.json'
        require(initial_path.read_bytes() == (I5/'requests'/initial_path.name).read_bytes(), 'INITIAL_RAW_BYTES_CHANGED')
    require(load(HERE/'CANDIDATE_REUSE_RECEIPT.json') == reused_candidate(), 'SAVED_REUSE_RECEIPT_MISMATCH')
    import importlib.metadata
    pinned = load(I5/'SDK_LOCAL_INSPECTION.json')
    for package in ('openai','httpx'):
        require(importlib.metadata.version(package) == pinned[package]['version'], 'SDK_VERSION_MISMATCH')
    return dict(status='PASS', utc=utc(), binding=b, approval_sha256=sha(a),
        tests_sha256=sha((HERE / 'OFFLINE_TEST_SUMMARY.json').read_bytes()),
        credentials_accessed=False, client_constructed=False,
        original_runner_invoked=False, source_files_checked=len(load(HERE / 'SOURCE_PRESERVATION_MANIFEST.json')['files']))


class LimitedRunner:
    def __init__(self, directory, config, transport, source_guard=lambda: None,
                 clock=time.monotonic, sleep=time.sleep):
        self.directory, self.config, self.transport = Path(directory), deepcopy(config), transport
        require(self.config == settings(), 'I6_CONFIG_CHANGED')
        self.source_guard, self.clock, self.sleep = source_guard, clock, sleep
        self.starts, self.outcomes, self.last_send = [], [], None
        if self.transport.kind == 'LIVE':
            receipt = load(self.directory / 'PREFLIGHT.json')
            validate_approval(load(self.directory / 'DIRECT_APPROVAL.json'), receipt['binding'])
            require(receipt['status'] == 'PASS' and receipt['binding'] == binding(), 'LIVE_RECEIPT_REQUIRED')
        self.stopped = False
        self.active_index = 0
        self.reused = None

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
        if self.active_index >= len(SLOTS) or logical != SLOTS[self.active_index]: self.stop('SERIAL_SLOT_ORDER')
        if logical == SLOTS[0] and phase != 'FINAL': self.stop('REUSED_SLOT_CANDIDATE_FORBIDDEN')
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
            if logical == SLOTS[0]:
                if self.reused != reused_candidate() or self.reused['candidate'] != final_plan: self.stop('REUSE_IDENTITY_CONFLICT')
            elif len(accepted) != 1 or accepted[0]['value'] != final_plan: self.stop('FINAL_NO_NEW_ACCEPTED_PLAN')
            if REPAIR.candidate_issues(prepared(row)['planner']['bridge'], final_plan): self.stop('FINAL_PLAN_CHECK_FAILED')
            if REPAIR.ORIGINAL.candidate_issues(prepared(row)['planner']['bridge'], final_plan): self.stop('ORIGINAL_FINAL_PLAN_CHECK_FAILED')
            expected = final_payload(prepared(row), self.config['generation_roles']['FINAL'], final_plan, False)
            if payload != expected or sha(payload) == row['prior_final_request_sha256']: self.stop('FINAL_INPUT_UNCHANGED_OR_RENDERER_DRIFT')
        if len(self.starts) >= self.config['caps']['TOTAL']: self.stop('TOTAL_PHYSICAL_CALL_CEILING')
        if sum(x['phase'] == phase for x in self.starts) >= self.config['caps'][phase]: self.stop('ROLE_CALL_CEILING')
        role = 'FINAL' if phase == 'FINAL' else 'CANDIDATE'
        cfg = self.config['generation_roles'][role]
        if (payload['model'] != cfg['model'] or payload['temperature'] != 0 or payload['max_tokens'] != 2048
                or payload['stream'] is not False or 'tools' in payload): self.stop('MODEL_OR_REQUEST_CONFIG_MISMATCH')
        if phase != 'FINAL':
            kind = REPAIR.plan_kind(prepared(row)['planner']['bridge'])['kind']
            if payload['response_format']['json_schema']['schema'] != REPAIR.schemas(kind)[1]:
                self.stop('TYPED_TRANSPORT_SCHEMA_MISMATCH')
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
            final_contract_version='I6_FINAL_REFERENCE_CONTRACT_V1' if phase == 'FINAL' else None,
            reused_candidate_sha256=self.reused['candidate_sha256'] if logical == SLOTS[0] else None,
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
                exception_type=type(exc).__name__, request_id=getattr(exc, 'request_id', None), usage=None,
                http_status=getattr(exc, 'http_status', None),
                provider_error_code=getattr(exc, 'provider_error_code', None),
                error_preservation='Safe error metadata only; no credential-bearing exception strings, HTTP headers or auth error bodies.')
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
            self.source_guard()
            self.reused = reused_candidate()
            write_once(self.directory/'CANDIDATE_REUSE_RECEIPT.json', self.reused)
            append(self.directory/'JOURNAL.jsonl',dict(event='I5_ACCEPTED_CANDIDATE_REUSED',**self.reused))
            for row, outcome in zip(load_slots(), rows):
                p = prepared(row); initial = REPAIR.candidate_payload(p, self.config['generation_roles']['CANDIDATE'])
                validator = lambda v: REPAIR.candidate_issues(p['planner']['bridge'], v)
                if self.active_index == 0:
                    r = dict(status='ACCEPTED', value=self.reused['candidate'],attempt_id='I5:01_initial')
                    outcome['candidate_origin'] = 'REUSED_I5_ACCEPTED'
                else:
                    outcome['candidate_origin'] = 'NEW_I6'
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
                        if f['status'] != 'ACCEPTED': self.stop('FINAL_FAILED_NO_RETRY', f['attempt_id'])
                    else:
                        outcome['final_status'] = 'NOT_CALLED_UNCHANGED_INPUT'
                else:
                    outcome['final_status'] = 'NOT_CALLED_NO_ACCEPTED_PLAN'
                    self.stop('CANDIDATE_FAILED_AFTER_ALLOWED_ATTEMPTS', r['attempt_id'])
                write_once(self.directory / 'terminals' / (f'{SLOTS.index(row["logical"])+1:02}.json'), outcome)
                append(self.directory / 'JOURNAL.jsonl', dict(event='SLOT_TERMINAL', **outcome))
                self.active_index += 1
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
            pending = [x for x in self.starts if x['logical'] == row['logical'] and not any(o['attempt_id']==x['attempt_id'] for o in attempts)]
            if pending:
                target = 'final_status' if pending[-1]['phase'] == 'FINAL' else 'candidate_status'
                row[target] = 'UNKNOWN_COMPLETION'
                if pending[-1]['phase'] == 'FINAL': row['final_called'] = True
                row['unresolved_attempt_ids'] = [x['attempt_id'] for x in pending]
            row['attempt_ids'] = [x['attempt_id'] for x in self.starts if x['logical'] == row['logical']]
            if cs: row['candidate_status'] = cs[-1]['status']
            if fs: row.update(final_called=True, final_status=fs[-1]['status'])
            if reason and not (self.directory / 'terminals' / f'{SLOTS.index(row["logical"])+1:02}.json').exists():
                row['execution_state'] = 'STOPPED_PARTIAL' if row['attempt_ids'] else 'UNATTEMPTED_AFTER_STOP'
                write_once(self.directory / 'terminals' / f'{SLOTS.index(row["logical"])+1:02}.json', row)
                append(self.directory / 'JOURNAL.jsonl', dict(event='STOP_TERMINAL', **row))
            else:
                row['execution_state'] = 'BOUNDED_SLOT_COMPLETE'
        summary = dict(status='PRESERVED_EARLY_STOP' if reason else 'BOUNDED_EXECUTION_COMPLETE',
            stop_reason=reason, slots=rows, phase_counts={k:sum(s['phase']==k for s in self.starts) for k in ('INITIAL','CORRECTION','FINAL')},
            total_physical_calls=len(self.starts), reused_accepted_candidates=int(self.reused is not None),
            new_accepted_candidates=sum(o['role']=='CANDIDATE' and o['status']=='ACCEPTED' for o in self.outcomes),
            semantic_support='NOT_CHECKED', human_scores=0,
            router_calls=0,retrieval_calls=0,memory_calls=0,embedding_calls=0,judge_calls=0,utc=utc())
        write_once(self.directory / 'RUN_SUMMARY.json', summary)
        return summary


class ExactOpenAITransport:
    kind = 'LIVE'

    def __init__(self):
        # Only called after the durable PREFLIGHT receipt. No probes or model list.
        receipt = load(OUTPUT / 'PREFLIGHT.json')
        validate_approval(load(OUTPUT / 'DIRECT_APPROVAL.json'), receipt['binding'])
        require(receipt['status'] == 'PASS' and receipt['binding'] == binding(), 'LIVE_RECEIPT_REQUIRED')
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
            failure = TransportFailure(category, request_id=getattr(exc, 'request_id', None))
            failure.http_status = status
            failure.provider_error_code = code if isinstance(code, str) and code.replace('_','').isalnum() and len(code)<100 else None
            raise failure from None

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
            validate_approval(load(HERE/'DIRECT_APPROVAL.json'), receipt['binding'])
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
