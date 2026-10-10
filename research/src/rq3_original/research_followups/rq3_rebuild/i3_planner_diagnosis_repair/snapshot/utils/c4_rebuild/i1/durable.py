"""Serial attempt journal with immutable raw receipts and bounded recovery."""
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import time
from .common import canonical, sha, load, utc, append, write_once, records
from .schemas import errors, strict_schema_check
from .transport import TransportFailure

FATAL = {'AUTH', 'BILLING', 'CONFIG', 'MODEL', 'RETURNED_MODEL_MISMATCH'}
RETRYABLE = {'INVALID_JSON', 'SCHEMA', 'TRUNCATED', 'ENCODED_CHECK', 'RATE_LIMIT'}


class StopRun(RuntimeError):
    pass


def parse_response(raw, payload, validator):
    if raw.get('model') != payload['model']:
        return 'RETURNED_MODEL_MISMATCH', None, ['Exact returned model snapshot required']
    choices = raw.get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return 'SCHEMA', None, ['ONE_RESPONSE_CHOICE_REQUIRED']
    choice = choices[0]
    message = choice.get('message') or {}
    if message.get('refusal'):
        return 'REFUSAL', None, [message['refusal']]
    if choice.get('finish_reason') == 'length':
        return 'TRUNCATED', None, ['OUTPUT_TRUNCATED']
    if choice.get('finish_reason') != 'stop' or message.get('tool_calls'):
        return 'SCHEMA', None, ['UNEXPECTED_FINISH_OR_TOOL_CALL']
    text = message.get('content')
    if not isinstance(text, str):
        return 'SCHEMA', None, ['MISSING_TEXT_CONTENT']
    def unique(pairs):
        value = {}
        for k,v in pairs:
            if k in value:
                raise ValueError('DUPLICATE_JSON_KEY')
            value[k] = v
        return value
    try:
        value = json.loads(text, object_pairs_hook=unique,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    except (ValueError, TypeError):
        return 'INVALID_JSON', None, ['JSON_PARSE_FAILED']
    problems = errors(value, payload['response_format']['json_schema']['schema'])
    if problems:
        return 'SCHEMA', value, problems
    problems = validator(value)
    return ('ENCODED_CHECK', value, problems) if problems else ('ACCEPTED', value, [])


class DurableRunner:
    def __init__(self, directory, config, binding, transport, *, resume=False,
                 unknown_authorizations=(), clock=time.monotonic, sleep=time.sleep):
        self.directory, self.config, self.binding = Path(directory), config, binding
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self.unknown_authorizations = set(unknown_authorizations)
        self.identity = dict(binding, transport_kind=transport.kind, role_contract_version=config['role_contract_version'])
        self.directory.mkdir(parents=True, exist_ok=resume)
        self.lock = (self.directory/'RUN.lock').open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if resume:
                if load(self.directory/'RUN_BINDING.json') != self.identity:
                    raise ValueError('RESUME_RUN_BINDING_MISMATCH')
            else:
                write_once(self.directory/'RUN_BINDING.json', self.identity)
            for name in ('attempts', 'terminals', 'stages'):
                (self.directory/name).mkdir(exist_ok=resume)
            if (self.directory/'STOP.json').exists():
                raise StopRun('FATAL_RUN_STOP_REQUIRES_EXTERNAL_RESOLUTION')
        except BaseException:
            self.close()
            raise
        self.last_start = None
        self.resume_cooldown = resume

    def close(self):
        if not self.lock.closed:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()

    def stage(self, logical, stage, inputs, output):
        key = sha([logical, stage, inputs])
        path = self.directory/'stages'/f'{key}.json'
        value = dict(logical=logical, stage=stage, input_sha256=sha(inputs),
                     output_sha256=sha(output), output=output)
        if path.exists():
            if load(path) != value:
                raise StopRun('STAGE_REPLAY_CHANGED')
        else:
            write_once(path, value)
        return output

    def reserve(self, logical, role, attempt, payload, initial_hash):
        starts = [load(p) for p in (self.directory/'attempts').glob('*.start.json')]
        group = 'ROUTE' if role in ('RAG', 'MEMORY', 'B4_PLANNING') else role
        ids = {r['logical'] for r in starts if r['group'] == group}
        if logical not in ids and len(ids) >= self.config['initial_slot_ceilings'][group]:
            raise StopRun('ROLE_LOGICAL_SLOT_CEILING')
        if len(starts) >= self.config['aggregate_attempt_ceiling']:
            raise StopRun('AGGREGATE_ATTEMPT_CEILING')
        units = len(canonical(payload)) + 256
        if units > self.config['max_request_input_byte_units']:
            raise StopRun('REQUEST_INPUT_BOUND_EXCEEDED')
        rates = self.config['uncached_usd_per_million']
        reserve = (units*rates['input'] + payload['max_tokens']*rates['output'])/1_000_000
        def charged(row):
            outcome_path = self.directory/'attempts'/f"{row['attempt_id']}.outcome.json"
            usage = load(outcome_path).get('usage') if outcome_path.exists() else None
            if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens')):
                observed = (usage['prompt_tokens']*rates['input'] + usage['completion_tokens']*rates['output'])/1_000_000
                return max(row['reserved_usd_upper_bound'], observed)
            return row['reserved_usd_upper_bound']
        if sum(charged(r) for r in starts) + reserve > self.config['proposed_money_ceiling_usd']:
            raise StopRun('MONEY_CEILING_NO_TRANSPORT')
        if self.last_start is None and self.resume_cooldown:
            self.sleep(self.config['minimum_start_interval_seconds'])
            self.resume_cooldown = False
        if self.last_start is not None:
            wait = self.config['minimum_start_interval_seconds'] - (self.clock()-self.last_start)
            if wait > 0:
                self.sleep(wait)
        at = self.clock()
        self.last_start = at
        aid = sha(logical)+f'.{attempt}'
        value = dict(attempt_id=aid, logical=logical, role=role, group=group, attempt=attempt,
            initial_request_sha256=initial_hash, request_sha256=sha(payload), request=payload,
            utc=utc(), monotonic_start=at, monotonic_clock_scope='CURRENT_PROCESS_ONLY',
            reserved_usd_upper_bound=reserve, completion='UNKNOWN', usage=None)
        write_once(self.directory/'attempts'/f'{aid}.start.json', value)
        append(self.directory/'JOURNAL.jsonl', dict(event='ATTEMPT_RESERVED_BEFORE_TRANSPORT', **value))
        return value

    def outcome(self, start, payload, validator):
        aid = start['attempt_id']
        base = self.directory/'attempts'
        raw_path = base/f'{aid}.raw.json'
        if not raw_path.exists():
            if aid not in self.unknown_authorizations:
                raise StopRun('UNKNOWN_IN_FLIGHT_REQUIRES_EXPLICIT_HANDLING:'+aid)
            result = dict(status='UNKNOWN_COMPLETION', value=None, issues=['EXPLICITLY_ACKNOWLEDGED_UNKNOWN_ATTEMPT'],
                raw_sha256=None, returned_model=None, request_id=None, usage=None)
        else:
            raw = load(raw_path)
            if raw.get('_transport_failure'):
                status, value, issues = raw['category'], None, [raw.get('detail')]
            else:
                status, value, issues = parse_response(raw, payload, validator)
            result = dict(status=status, value=value, issues=issues, raw_sha256=sha(raw_path.read_bytes()),
                returned_model=raw.get('model'), request_id=raw.get('_request_id') or raw.get('id'), usage=raw.get('usage'))
        result.update(attempt_id=aid, request_sha256=start['request_sha256'], utc=utc(),
                      monotonic_end=self.clock(), completion='UNKNOWN' if result['status']=='UNKNOWN_COMPLETION' else 'OBSERVED')
        write_once(base/f'{aid}.outcome.json', result)
        append(self.directory/'JOURNAL.jsonl', dict(event='ATTEMPT_OUTCOME', **result))
        if result['status'] in FATAL:
            write_once(self.directory/'STOP.json', dict(category=result['status'], attempt_id=aid, utc=utc()))
            raise StopRun(result['status'])
        if result['status'] == 'UNKNOWN_COMPLETION' and aid not in self.unknown_authorizations:
            raise StopRun('UNKNOWN_COMPLETION_REQUIRES_EXPLICIT_HANDLING:'+aid)
        return result

    def perform(self, logical, role, initial_payload, validator=lambda value: [], repair=None):
        if (self.directory/'STOP.json').exists():
            raise StopRun('FATAL_RUN_STOP_NO_FURTHER_CALLS')
        strict_schema_check(initial_payload['response_format']['json_schema']['schema'])
        initial_hash = sha(initial_payload)
        terminal_path = self.directory/'terminals'/f'{sha(logical)}.json'
        if terminal_path.exists():
            terminal = load(terminal_path)
            if terminal['initial_request_sha256'] != initial_hash or terminal['logical'] != logical:
                raise StopRun('TERMINAL_BINDING_MISMATCH')
            outcome_path = self.directory/'attempts'/f"{terminal['attempt_id']}.outcome.json"
            result = load(outcome_path)
            if sha(outcome_path.read_bytes()) != terminal['outcome_sha256'] or result != terminal['result']:
                raise StopRun('TERMINAL_RECEIPT_MISMATCH')
            raw_path = self.directory/'attempts'/f"{terminal['attempt_id']}.raw.json"
            if result['raw_sha256'] and sha(raw_path.read_bytes()) != result['raw_sha256']:
                raise StopRun('RAW_RECEIPT_MISMATCH')
            return terminal['result']
        payload = deepcopy(initial_payload)
        result = None
        for attempt in range(1, self.config['max_attempts_per_slot']+1):
            aid = sha(logical)+f'.{attempt}'
            base = self.directory/'attempts'
            start_path = base/f'{aid}.start.json'
            if start_path.exists():
                start = load(start_path)
                if start['initial_request_sha256'] != initial_hash or start['request_sha256'] != sha(payload):
                    raise StopRun('ATTEMPT_REQUEST_CHANGED')
                outcome_path = base/f'{aid}.outcome.json'
                result = load(outcome_path) if outcome_path.exists() else self.outcome(start, payload, validator)
                if result['raw_sha256'] and sha((base/f'{aid}.raw.json').read_bytes()) != result['raw_sha256']:
                    raise StopRun('RAW_RECEIPT_MISMATCH')
                if result['status'] == 'UNKNOWN_COMPLETION' and aid not in self.unknown_authorizations:
                    raise StopRun('UNKNOWN_COMPLETION_REQUIRES_EXPLICIT_HANDLING:'+aid)
            else:
                start = self.reserve(logical, role, attempt, payload, initial_hash)
                try:
                    raw = self.transport.send(payload)
                except TransportFailure as exc:
                    raw = dict(_transport_failure=True, category=exc.category, detail=exc.detail,
                               _request_id=exc.request_id, usage=None, model=None)
                # A crash or unexpected Python exception leaves the reservation in-flight.
                write_once(base/f'{aid}.raw.json', raw)
                result = self.outcome(start, payload, validator)
            if result['status'] in FATAL:
                raise StopRun(result['status'])
            if result['status'] == 'ACCEPTED' or result['status'] not in RETRYABLE | {'UNKNOWN_COMPLETION'}:
                break
            if attempt < self.config['max_attempts_per_slot'] and repair and result['status'] in ('SCHEMA','INVALID_JSON','ENCODED_CHECK'):
                payload = repair(result['value'], result['issues'])
        value = dict(logical=logical, initial_request_sha256=initial_hash, attempt_id=result['attempt_id'],
                     outcome_sha256=sha((base/f"{result['attempt_id']}.outcome.json").read_bytes()), result=result)
        write_once(terminal_path, value)
        append(self.directory/'JOURNAL.jsonl', dict(event='LOGICAL_TERMINAL', logical=logical, status=result['status']))
        return result
