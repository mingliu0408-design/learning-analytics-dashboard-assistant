"""Finite JSON worker. Recreates exposed sources, clones state, never imports SDK."""
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import canonical, sha
from utils.c4_rebuild.i1.memory import I1ResearchService, I1NativeM1
from utils.c4_rebuild.memory import clone_native_states, m1_dependencies
from utils.c4_rebuild.contracts import Mode
from utils.c4_dashboard_scoped.integration import build_scoped_request
from utils.c4_dashboard_scoped.scope import instant
from utils.c4_real_adapters import FrozenClarificationGateAdapter
from utils.c4_real_contracts import P3CapabilityRoute
from research_followups.rq3_rebuild.i0_human_integration.fixtures import (
    memory_source, request, snapshot, rag_source, explicit_minutes_source)

TASKS_FILE = ROOT/'research_followups/rq3_rebuild/i0_human_integration/PILOT_TASKS.json'


def task_source(slot):
    tasks = json.loads(TASKS_FILE.read_text())['tasks']
    task = next((t for t in tasks if t['id'] == slot), None)
    if task is None:
        raise ValueError('UNAPPROVED_TASK_SLOT')
    return task


class ReceiptRouter:
    def __init__(self, primary, route):
        self.primary, self.receipt = primary, route

    def route(self, incoming):
        if incoming.to_payload() != self.primary:
            raise ValueError('ROUTE_INPUT_CHANGED_AFTER_RECEIPT')
        if self.receipt is None:
            return None
        return P3CapabilityRoute(**self.receipt)


def handle(message):
    op = message['op']
    if op == 'check_candidate':
        from utils.c4_rebuild.planning import validate_candidate
        return validate_candidate(message['bridge'], message['candidate'])
    task = task_source(message['slot'])
    # Use source setup metadata only; no expected/reference areas are read.
    source = json.loads((TASKS_FILE.parent.parent/'m1_memory_completeness/fixtures/linked_runtime_v1.json').read_text())[task.get('memory_index', 0)]
    learner, course = source['target']['learner_id'], source['target']['course_id']
    snap = snapshot(learner_id=learner, course_id=course)
    r = request(Mode(message.get('mode', 'S5_FULL')), query=task['query'], page=task['page'])
    r = replace(r, scope=replace(r.scope, learner_id=learner, course_id=course))
    if task.get('explicit_purpose'):
        r = replace(r, memory_purpose=task['explicit_purpose'], visible_controls='EXPLICIT_SYNTHETIC_UI_PURPOSE')
    snap.validate_query(r.scope, r.query, instant(r.as_of))
    if not instant(r.scope.start) <= instant(r.as_of) < instant(r.scope.end):
        raise ValueError('AS_OF_OUTSIDE_REQUEST_WINDOW')
    primary = build_scoped_request(snapshot=snap, scope=r.scope, query=r.query, page=r.page,
        now=instant(r.as_of), messages=r.history, session_id=r.session_id).primary_input
    initial = dict(primary=primary.to_payload(), primary_sha256=sha(primary.to_payload()),
        clarification=FrozenClarificationGateAdapter().evaluate(primary).needs_clarification,
        scope=r.scope.internal(), origin='SYNTHETIC_MODEL_AUTHORED_EXPOSED',
        source_task_sha256=sha(task), source_state_recipe_sha256=sha(source))
    if op == 'source':
        return initial
    if op == 'dossier':
        from copy import deepcopy
        from utils.c4_dashboard_scoped.aggregate import aggregate
        from utils.c4_dashboard_scoped import DOMAINS
        raw = deepcopy(source)
        if task.get('numeric'):
            m1_dependencies()
            explicit_minutes_source(raw)
        turns = [t for t in raw['source_turns'] if t['learner_id']==learner and t['course_id']==course
                 and instant(t['timestamp']) < instant(r.as_of)]
        return dict(source_review_approved=False, version='I1_COMMON_SOURCE_DOSSIER_PROPOSED_V1',
            source_ids=[t['turn_id'] for t in turns],
            reference=dict(source_turns=turns, relation_source_events=raw['relation_events'],
                dashboard_aggregates=aggregate(snap,r.scope).context(DOMAINS),
                scope=initial['scope'], source_state_recipe_sha256=initial['source_state_recipe_sha256'],
                limitations=['Draft source review required; source events may be superseded or withdrawn. Author must freeze task truth/applicability before rating.',
                    'No candidate plan, generated support, mode-selected evidence union, or expected-answer sidecar supplies this dossier.']))
    if op != 'prepare' or initial['primary_sha256'] != message['primary_sha256']:
        raise ValueError('WORKER_OPERATION_OR_INPUT_BINDING')
    m1_dependencies()
    from contextlib import ExitStack
    with tempfile.TemporaryDirectory(prefix='i1-native-') as td, ExitStack() as stack:
        backend = None
        if (message.get('memory_backend') == 'M1_HYBRID_LINKS_DEV'
            and r.mode in (Mode.S3_EVIDENCE_MEMORY, Mode.S5_FULL)
            and (message.get('route') or {}).get('memory_required') is True
            and r.access.memory and not initial['clarification']):
            import fcntl
            lock = stack.enter_context(open('/private/tmp/rq3-rebuild-local-inference.lock', 'a+'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            from utils.c4_rebuild.i1.native_backend import I1LocalBackend
            backend = I1LocalBackend(Path(td))
            stack.callback(backend.close)
        native, setup = memory_source(task.get('memory_index', 0), td,
            change=explicit_minutes_source if task.get('numeric') else None, backend=backend)
        clones = clone_native_states(native.databases, Path(td)/'condition-clone')
        memory = I1NativeM1(clones, native.graph, native.source_events, backend=backend)
        r = replace(r, memory_state_version=sha(setup['source_case']))
        prepared = I1ResearchService(enabled=True, snapshot=snap,
            router=ReceiptRouter(primary.to_payload(), message.get('route')),
            retriever=rag_source(task.get('empty_course', False), course_id=course), memory=memory).prepare(r)
    return dict(source=initial, prepared=prepared, state_clone='NEW_PER_CONDITION',
                memory_backend=message.get('memory_backend', 'LEXICAL_NATIVE_DIAGNOSTIC'),
                source_role='EXPOSED_SYNTHETIC_RECIPE_NOT_PRIOR_I0_REQUEST')


if __name__ == '__main__':
    # Scope, E1 and source construction are also offline in this process.
    import socket
    def denied(*args, **kwargs):
        raise RuntimeError('I1_OFFLINE_WORKER_NO_NETWORK')
    socket.create_connection = denied
    socket.socket.connect = denied
    try:
        result = handle(json.load(sys.stdin))
        print(canonical({'ok': True, 'result': result}).decode())
    except Exception as exc:
        print(canonical({'ok': False, 'error': type(exc).__name__+':'+str(exc)}).decode())
        raise SystemExit(1)
