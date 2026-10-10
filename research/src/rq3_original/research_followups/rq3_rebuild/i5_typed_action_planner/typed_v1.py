"""Additive typed request contract; original P0/P1 validation stays unchanged.

No generation, mutation of candidate values, source projection or network access.
The existing P1 task_request is authoritative within its validated source binding.
This is not a general natural-language intent classifier.
"""
from copy import deepcopy
import importlib.util
import json
import re
from i5_common import I3, canonical, require
from utils.c4_rebuild.i1.schemas import LOCAL_CANDIDATE, errors, strict_subset, strict_schema_check
from utils.c4_rebuild.planning import validate_bridge

spec = importlib.util.spec_from_file_location('i5_frozen_i3_repair', I3 / 'repair_v1.py')
ORIGINAL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ORIGINAL)
VERSION = 'I5_TYPED_ACTION_PLAN_V1'
ORDINARY = 'ORDINARY_ACTION_ADVICE'
SCHEDULE = 'EXPLICIT_SCHEDULE'
NEEDS = 'NEEDS_TASK_INFORMATION'


def plan_kind(bridge):
    source = bridge['source_input']
    task = source['task_request']
    query = source['base_input']['context']['query']
    pi = bridge['planner_input']
    reasons = []
    # Never inspect scenario, condition, reviewer or expected-result identifiers.
    if not query.strip() or task['source_quote'] != query or task['basis'] == 'UNKNOWN':
        reasons.append('TASK_SOURCE_BINDING_UNCLEAR')
    if task['mode'] not in (ORDINARY, SCHEDULE):
        reasons.append('PLANNING_INTENT_UNKNOWN')
    requested = task['mode'] == SCHEDULE
    if pi['hard_constraints']['schedule']['required'] != requested:
        reasons.append('INTENT_SCHEDULE_CONFLICT')
    without_dates = bool(re.search(r'\bwithout (?:scheduling )?dates\b', query, re.I))
    residual = re.sub(r'\bwithout (?:scheduling )?dates\b', '', query, flags=re.I)
    calendar_cue = bool(re.search(r'\b(?:schedule|calendar|time[- ]slots?|dated|timetable)\b', residual, re.I))
    if task['mode'] == ORDINARY and calendar_cue:
        reasons.append('CURRENT_REQUEST_CALENDAR_CUE_CONFLICT')
    if requested and without_dates:
        reasons.append('CURRENT_REQUEST_NO_DATES_CONFLICT')
    if requested:
        for key, code in (('timezone', 'MISSING_TIMEZONE'), ('horizon', 'MISSING_HORIZON')):
            if pi['scope'][key] is None:
                reasons.append(code)
        if pi['hard_constraints']['schedule']['allowed_windows'] is None:
            reasons.append('MISSING_ALLOWED_WINDOWS')
    original = validate_bridge(bridge)
    if original['outcome'] != 'PASSED_ENCODED_CHECKS':
        reasons.extend(i['code'] for i in original['issues'] if i['severity'] in ORIGINAL.BLOCKING)
    return dict(version=VERSION, kind=NEEDS if reasons else task['mode'],
        recorded_mode=task['mode'], reasons=sorted(set(reasons)),
        task_request=deepcopy(task), legitimate_query=query,
        source_pointers=['/source_input/task_request', '/source_input/base_input/context/query',
                         '/planner_input/hard_constraints/schedule', '/planner_input/scope'],
        without_dates_explicit=without_dates, calendar_cue=calendar_cue,
        schedule_required=pi['hard_constraints']['schedule']['required'],
        budget_does_not_imply_calendar=True,
        evidence_time_is_not_availability=True,
        original_bridge_outcome=original['outcome'])


def schemas(kind):
    require(kind in (ORDINARY, SCHEDULE), 'NO_CANDIDATE_SCHEMA_FOR_NEEDS_INFORMATION')
    local = deepcopy(LOCAL_CANDIDATE)
    action = local['properties']['actions']['items']['properties']
    if kind == ORDINARY:
        action['schedule'] = {'type': 'null'}
        action['estimated_duration']['properties']['origin']['enum'] = ['MODEL_ESTIMATE', 'UNKNOWN']
    action['schedule']['description'] = ('Must be null: ordinary actions have no calendar.' if kind == ORDINARY else
        'Use the original calendar contract. Every action requires a supported schedule when scheduling is required; null never certifies successful scheduling.')
    descriptions = {
        'step_id': 'Unique local action identifier in THIS candidate, e.g. step_1. Distinct from task IDs, evidence IDs and resource IDs.',
        'task_id': 'Identity of the proposed task, e.g. proposed_task_1, or an exact supplied historical task ID when applicable. Never invent historical acceptance; preserve completion and prerequisite rules.',
        'dependencies': 'Only step_id values of earlier actions in THIS candidate. Never task_id, goal IDs or evidence IDs. No missing target, duplicate, self-loop, cycle or forward dependency.',
        'evidence_refs': 'Exact IDs from the supplied reference_catalog. An ID identifies evidence; it does not prove semantic support.',
        'resource_ids': 'Only exact IDs from encoded_planning_fields.resources. Evidence facts are not automatically resources. Empty when no resources are supplied.',
        'completion_check': 'A meaningful observable check for this proposed action. Do not claim unseen worksheet completion or unknown prior task state.',
    }
    for key, description in descriptions.items():
        action[key]['description'] = description
    action['estimated_duration']['description'] = ('Use MODEL_ESTIMATE with explicit uncertainty for your estimate, or UNKNOWN/null. Citations do not prove duration. UNKNOWN is not zero or budget compliance; original checks may block it.')
    local['properties']['evidence_refs']['description'] = descriptions['evidence_refs']
    local['properties']['continues_plan_id']['description'] = 'Null unless an actually adopted active plan is supplied; a non-null value must be its exact ID.'
    wire = strict_subset(local)
    def copy_descriptions(a, b):
        if 'description' in a:
            b['description'] = a['description']
        for key, child in a.get('properties', {}).items():
            copy_descriptions(child, b['properties'][key])
        if 'items' in a:
            copy_descriptions(a['items'], b['items'])
        for child, target in zip(a.get('anyOf', []), b.get('anyOf', [])):
            copy_descriptions(child, target)
    copy_descriptions(local, wire)
    strict_schema_check(wire)
    return local, wire


def local_rules(schema, path='$', when=()):
    """Retain the applicability of every anyOf branch, including nullable scalars."""
    rows = []
    limits = {k: deepcopy(v) for k, v in schema.items()
              if k in ('minItems', 'maxItems', 'uniqueItems', 'minLength', 'minimum', 'maximum')}
    if limits:
        rows.append(dict(path=path, applies_when=list(when), **limits))
    for key, child in schema.get('properties', {}).items():
        rows += local_rules(child, path + '.' + key, when)
    if 'items' in schema:
        rows += local_rules(schema['items'], path + '[*]', when)
    for index, child in enumerate(schema.get('anyOf', [])):
        condition = dict(path=path, branch_index=index, type=child.get('type'), meaning='apply only when value matches this branch')
        rows += local_rules(child, path, (*when, condition))
    return rows


def candidate_issues(bridge, candidate):
    original = ORIGINAL.candidate_issues(bridge, candidate)
    decision = plan_kind(bridge)
    if decision['kind'] == NEEDS:
        return original + [dict(code=NEEDS, path='$', severity='NOT_CHECKABLE', message=','.join(decision['reasons']))]
    local, _ = schemas(decision['kind'])
    extra = errors(candidate, local)
    if not errors(candidate, LOCAL_CANDIDATE):
        pi = bridge['planner_input']
        other = ({a['task_id'] for a in candidate['actions']} | {f['fact_id'] for f in pi['facts']} |
                 {r['resource_id'] for r in pi['resources']} | {g['goal_id'] for g in pi['goals']})
        for i, a in enumerate(candidate['actions']):
            if a['step_id'] in other:
                extra.append(dict(code='STEP_NAMESPACE_COLLISION', path=f'$.actions[{i}].step_id', severity='ERROR',
                                  message='Local step ID must differ from task/evidence/resource/goal IDs.'))
    # Preserve original issue objects exactly; append only distinct new issues.
    return original + [x for x in extra if canonical(x) not in {canonical(i) for i in original}]


def feedback_details(previous, issues, kind):
    rows = local_rules(schemas(kind)[0])
    actions = previous.get('actions', []) if isinstance(previous, dict) else []
    existing = [a.get('step_id') for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []
    namespace = []
    if isinstance(actions, list):
        for i, a in enumerate(actions):
            if isinstance(a, dict) and isinstance(a.get('dependencies'), list):
                bad = [v for v in a['dependencies'] if v not in existing[:i]]
                if bad:
                    namespace.append(dict(path=f'$.actions[{i}].dependencies', offending_values=bad,
                                          allowed_earlier_step_ids=existing[:i]))
    return dict(original_issues=deepcopy(issues), existing_step_ids=existing,
        invalid_dependencies=namespace, conditional_local_constraints=rows,
        instruction='Revise the exact newly returned candidate once. Dependencies must use earlier local step IDs. Do not alter source facts or manufacture evidence, dates, adoption or completion.')


def candidate_payload(prepared, role_config, previous=None, issues=()):
    bridge = prepared['planner']['bridge']
    decision = plan_kind(bridge)
    require(decision['kind'] != NEEDS, 'NEEDS_TASK_INFORMATION:' + ','.join(decision['reasons']))
    require(previous is not None or not issues, 'FEEDBACK_WITHOUT_PREVIOUS')
    if previous is not None:
        require(sorted(canonical(x) for x in issues) == sorted(canonical(x) for x in candidate_issues(bridge, previous)),
                'I5_FEEDBACK_NOT_EXACT_NEW_RESULT')
    # Start from the untouched I3 initial builder; correction is bound to I5 checks.
    result = ORIGINAL.candidate_payload(prepared, role_config)
    body = json.loads(result['messages'][1]['content'])
    local, wire = schemas(decision['kind'])
    body['candidate_contract'].update(version=VERSION, plan_kind=decision['kind'],
        local_constraints=local_rules(local),
        identifier_namespaces={k: deepcopy(bridge['planner_input'][k]) for k in ('resources', 'completed_tasks', 'active_plan')},
        dependency_binding='dependencies reference earlier step_id values from this candidate only; task IDs, evidence IDs and goal IDs are different namespaces.',
        evidence_time='time_context.as_of and dashboard window are source observation times, not learner availability or permission to schedule.',
        substantive_limits='Current-request supports intention only. Missing worksheet content, unknown exercise state and missing adopted plan remain unknown. Historical relative-week statements do not establish a current goal beyond their scoped evidence time. Conditional suggestions must state missing facts; never assert unavailable content, prior adoption or completion.',
        duration_boundary='Model-supplied durations are MODEL_ESTIMATE with uncertainty or UNKNOWN, never proven by citations. Preserve any encoded budget; UNKNOWN cannot establish compliance.')
    if previous is not None:
        body.update(previous_candidate=deepcopy(previous), concrete_checker_issues=deepcopy(list(issues)),
                    checker_feedback_details=feedback_details(previous, issues, decision['kind']))
    result['messages'][1]['content'] = canonical(body).decode()
    result['response_format']['json_schema'].update(name='i5_' + decision['kind'].lower() + '_v1', schema=wire)
    return result
