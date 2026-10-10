"""Narrow I0 extension over frozen P1 function bodies, preserving native text.

I0 explicitly admits nullable metadata absent from M1 link-expanded facts. It
does not manufacture retrieval scores or dates. Original P1 remains unchanged.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import FunctionType
import sys
from utils.c4_dashboard_scoped.scope import canonical, digest, instant
from .contracts import reject_sidecars
from .language import numeric_constraint

ROOT = Path(__file__).resolve().parents[2]
P1 = ROOT/'research_followups/rq3_rebuild/p1_planner_bridge'
if str(P1) not in sys.path:
    sys.path.insert(0, str(P1))
from p1bridge import contracts as p1c, projection as p1p, checker as p1v

I0_INPUT = deepcopy(p1c.INPUT)
I0_INPUT['properties'].update(i0_envelope={'type': 'object'})
I0_INPUT['required'].append('i0_envelope')
n = I0_INPUT['properties']['selected_memory']['items']['properties']['native']['properties']
for key in ('created_at', 'last_confirmed_at'):
    n['timestamp_version']['properties'][key] = {'anyOf': [{'type': 'string'}, {'type': 'null'}]}
n['timestamp_version']['properties']['status'] = {'anyOf': [{'type': 'string'}, {'type': 'null'}]}
n['relevance_components'] = {'anyOf': [deepcopy(n['relevance_components']), {'type': 'null'}]}


def source_bindings(bundle):
    env, auth = bundle.envelope, bundle.authority
    selected = []
    policy_verified = sha256((ROOT/'utils/c4_memory/c4_memory_store.py').read_bytes()).hexdigest() == p1c.POLICY_SHA
    for f in env['facts']:
        mid, ref, validity = f['native_id'], f['source_ref'], f['validity']
        a = auth.get(mid, {})
        rec = a.get('native_record') or {}
        event = a.get('source_event')
        valid_event = bool(event and digest(event) == ref['event_sha256']
            and event.get('learner_id') == f['learner_id'] and event.get('course_id') == f['course_id']
            and event.get('role') == ref['origin'] and event.get('turn_id') == ref['event_id'])
        start, end = ref['span_chars']
        valid_event = bool(valid_event and event['content'][start:end] == f['content'])
        valid_rec = bool(rec and rec.get('memory_id') == mid and rec.get('student_id') == f['learner_id']
            and rec.get('content') == f['content'] and rec.get('version') == f['native_version']
            and rec.get('valid_from') == validity['valid_from'] and rec.get('valid_to') == validity['valid_to']
            and rec.get('consent_status') == f['consent_status']
            and rec.get('content_sha256') == sha256(f['content'].encode()).hexdigest()
            and a.get('current_as_of') == env['scope']['as_of'])
        native = dict(memory_id=mid, memory_type=f['memory_type'], content=f['content'],
            timestamp_version=dict(created_at=rec.get('created_at') if valid_rec else None,
                last_confirmed_at=rec.get('last_confirmed_at') if valid_rec else None,
                valid_from=validity['valid_from'], valid_to=validity['valid_to'],
                version=f['native_version'], status=rec.get('status') if valid_rec else None),
            provenance=dict(source_session_id=ref['session_id'], source_turn_id=ref['event_id'],
                supersedes_memory_id=f['supersedes_native_id'], consent_status=f['consent_status'],
                content_sha256=sha256(f['content'].encode()).hexdigest()),
            relevance_components=a.get('relevance_components'),
            read_only_evidence=dict(representation='I0_ACTUAL_M1_READ_ONLY_TEXT', mutable=False,
                content=f['content'], content_sha256=sha256(f['content'].encode()).hexdigest()))
        known_role = valid_event and ref['origin'] in ('USER', 'SYSTEM')
        origin = ('LEARNER_STATED_FACT' if ref['origin'] == 'USER' else 'SYSTEM_ORIGIN_PLAN') if known_role else 'UNKNOWN'
        source_policy = bool(policy_verified and valid_rec and
            validity['meaning'] == 'NO_DECLARED_EXPIRY_UNDER_NATIVE_ACTIVE_SQL' and
            validity['verified_at'] == env['scope']['as_of'])
        binding = dict(learner_id=f['learner_id'] if valid_event and valid_rec else None,
            course_id=f['course_id'] if valid_event and valid_rec else None,
            current_version=a.get('current_version') if valid_rec else None,
            superseded_by=None, enabled=a.get('enabled') if valid_rec else None,
            origin=origin, origin_basis=ref['claim_basis'] if known_role else 'UNKNOWN',
            source_role=ref['origin'] if known_role else 'UNKNOWN',
            # P1 receives a local view of the selected span only. Original event
            # offsets/hash remain verbatim in i0_envelope.source_ref; full turns
            # may contain unselected facts and must not enlarge provider input.
            source_span=dict(text=f['content'], start=0, end=len(f['content'])) if valid_event else None,
            encoding='FREE_TEXT', validity_policy=dict(policy_id=p1c.POLICY_ID, source_sha256=p1c.POLICY_SHA) if source_policy else None)
        selected.append(dict(native=native, binding=binding))
    return selected


def fields_for(source):
    """Only authoritative source types/whole sentences and retained exact-ID links."""
    env = source['i0_envelope']
    selected = {x['native']['memory_id']: x for x in source['selected_memory']}
    fields, parses = {}, []
    def empty():
        return dict(goal=None, constraints=None, completed_task_ids=[], active_plan=None,
                    review_permissions=[], duration_estimates=[])
    for mid, mem in selected.items():
        n, b = mem['native'], mem['binding']
        f = empty()
        if b['origin'] == 'LEARNER_STATED_FACT' and b['source_span'] is not None:
            if n['memory_type'] == 'GOAL':
                f['goal'] = dict(goal_id=mid, text=n['content'])
            if n['memory_type'] == 'CONSTRAINT':
                parsed = numeric_constraint(n['content'], mid)
                parses.append(parsed)
                if parsed['parsed_value'] is not None:
                    f['constraints'] = dict(budget=dict(required=True, minutes=parsed['parsed_value']))
        fields[mid] = f if any((f['goal'], f['constraints'])) else None
    # A native completion row ID is NOT an independent task ID. Only a retained
    # COMPLETION_OF_ACTION edge identifies an accepted action's immutable ID.
    edges = env['source_link_edges']
    for e in edges:
        if e['from_id'] not in selected or e['to_id'] not in selected:
            raise ValueError('M1 relation references a nonselected fact')
        for key, vkey in (('from_id', 'from_version'), ('to_id', 'to_version')):
            if selected[e[key]]['native']['timestamp_version']['version'] != e[vkey]:
                raise ValueError('Stale native edge version')
        if e['relation_type'] == 'COMPLETION_OF_ACTION':
            done, action = selected[e['from_id']], selected[e['to_id']]
            if (done['native']['memory_type'] == 'COMPLETED_ACTION' and
                action['native']['memory_type'] == 'PROGRESS_UPDATE' and
                action['native']['content'].startswith('I accept this action:') and
                all(x['binding']['origin'] == 'LEARNER_STATED_FACT' for x in (done, action))):
                f = fields[e['from_id']] or empty()
                f['completed_task_ids'].append(e['to_id'])
                fields[e['from_id']] = f
    return fields, parses


def project(source):
    reject_sidecars(source)
    fields, parses = fields_for(source)
    globals_ = dict(p1p.project.__globals__)
    globals_.update(INPUT=I0_INPUT, structured_fields=lambda n, b: deepcopy(fields[n['memory_id']]))
    inherited = FunctionType(p1p.project.__code__, globals_, 'i0_p1_project', p1p.project.__defaults__)
    result = inherited(source)
    ordinary = source['task_request']['mode'] == 'ORDINARY_ACTION_ADVICE'
    for item in result['projection_issues']:
        if ordinary and item['code'] == 'UNSTRUCTURED_MEMORY':
            item.update(severity='WARNING', message='Raw fact retained for ordinary advice; its unencoded state/constraints remain NOT_CHECKABLE.')
    if source['i0_envelope'].get('status') == 'AMBIGUOUS':
        result['projection_issues'].append(p1p.issue('AMBIGUOUS_ACTIVE_PLAN', '$.i0_envelope',
            'Several native plans remain; no inferred adoption or plan selection.'))
    for mid, f in fields.items():
        if f and f['constraints']:
            result['planner_input']['hard_constraints']['required_evidence_ids'].append(mid)
    result['i0_diagnostics'] = dict(version='I0_P1_NATIVE_TEXT_EXTENSION_V1', numeric_parses=parses,
        raw_state_checkability='NOT_CHECKABLE' if any(f is None for f in fields.values()) else 'ENCODED_FIELDS_ONLY',
        active_plan_adoption='NOT_ESTABLISHED', native_completion_ids_are_task_ids=False,
        semantic_support='NOT_CHECKED', inherited_p1_function_body_unchanged=True)
    return result


def validate_bridge(bridge):
    env = dict(p1v.validate_bridge.__globals__)
    env['project'] = project
    return FunctionType(p1v.validate_bridge.__code__, env, 'i0_validate_bridge')(bridge)


def validate_candidate(bridge, candidate):
    env = dict(p1v.validate_candidate.__globals__)
    env['validate_bridge'] = validate_bridge
    result = FunctionType(p1v.validate_candidate.__code__, env, 'i0_validate_candidate')(bridge, candidate)
    result['semantic_support'] = 'NOT_CHECKED'
    result['unencoded_constraint_support'] = bridge['i0_diagnostics']['raw_state_checkability']
    return result


def bridge_from_m1(bundle, base, task, future_policy):
    source = dict(schema_version=p1c.VERSION, base_input=deepcopy(base), task_request=deepcopy(task),
        selected_memory=source_bindings(bundle), memory_status='AVAILABLE' if bundle.envelope['facts'] else 'NO_MATCH',
        future_use_policy=future_policy, i0_envelope=deepcopy(bundle.envelope))
    return project(source)


def empty_envelope(request):
    return dict(version='M1_PLANNER_ENVELOPE_DRAFT_V1', read_only=True, facts=[],
        scope=dict(learner_id=request.scope.learner_id, course_id=request.scope.course_id,
                   session_id=request.session_id, as_of=request.as_of, horizon='current scoped request'),
        status='NOT_ACTIVATED', source_link_edges=[], structured_constraints=[],
        accepted_action_ids=[], completed_action_ids=[], active_plan_ids=[],
        chosen_active_plan_id=None, missing_information=[], semantic_support='NOT_CHECKED')
