"""Candidate-request contract repair only; historical checker and outputs unchanged.

This module only constructs dictionaries. It cannot send requests. No source
facts, candidate values, constraints, model settings or retry limits are repaired.
"""
from copy import deepcopy
import json
import re

from utils.c4_rebuild.i1.common import canonical
from utils.c4_rebuild.i1.renderer import candidate_payload as original_payload
from utils.c4_rebuild.i1.schemas import LOCAL_CANDIDATE, errors
from utils.c4_rebuild.planning import validate_bridge, validate_candidate

VERSION = 'I3_CANDIDATE_CONTRACT_V1'
BLOCKING = ('ERROR', 'CONTRADICTION', 'NOT_CHECKABLE')
FINAL_ONLY_TEXT = ('The answer field contains the natural answer; citation IDs and plan_fields are administrative. '
                   'Set plan_fields to the supplied accepted plan, or null when none is supplied. ')


def candidate_issues(bridge, candidate):
    """Identical admission sequence to the saved I1 orchestrator, without a worker."""
    structural = errors(candidate, LOCAL_CANDIDATE)
    if structural:
        return structural
    checked = validate_candidate(bridge, candidate)
    return ([i for i in checked['issues'] if i['severity'] in BLOCKING]
            if checked['outcome'] != 'PASSED_ENCODED_CHECKS' else [])


def local_rules(schema=LOCAL_CANDIDATE, path='$'):
    """Transmit constraints omitted by the unchanged provider strict subset."""
    rows = []
    limits = {k: deepcopy(v) for k, v in schema.items()
              if k in ('minItems', 'maxItems', 'uniqueItems', 'minLength', 'minimum', 'maximum')}
    if limits:
        rows.append(dict(path=path, **limits))
    for key, child in schema.get('properties', {}).items():
        rows += local_rules(child, path+'.'+key)
    if 'items' in schema:
        rows += local_rules(schema['items'], path+'[*]')
    for child in schema.get('anyOf', []):
        rows += local_rules(child, path)
    return rows


def reference_catalog(bridge, body):
    """Bind exact checker IDs to already-rendered content; fail on any mismatch."""
    catalog = []
    facts = bridge['planner_input']['facts']
    if len({f['fact_id'] for f in facts}) != len(facts):
        raise ValueError('I3_DUPLICATE_FACT_ID')
    for fact in facts:
        if fact['fact_type'] == 'VERBATIM_CURRENT_TASK_REQUEST':
            value, pointer = body['current_query'], '/current_query'
            source_kind = 'CURRENT_TASK_REQUEST'
        else:
            matches = [(i, f) for i, f in enumerate(body['source_facts']) if f['id'] == fact['fact_id']]
            if len(matches) != 1:
                raise ValueError('I3_FACT_RENDER_BINDING_MISSING')
            i, rendered = matches[0]
            value = rendered['content']
            pointer, source_kind = f'/source_facts/{i}/content', rendered['kind']
            if source_kind != fact['kind']:
                raise ValueError('I3_FACT_KIND_CHANGED')
        exact = value if isinstance(value, str) else canonical(value).decode()
        if exact != fact['value']:
            raise ValueError('I3_FACT_CONTENT_CHANGED')
        catalog.append(dict(id=fact['fact_id'], source_kind=source_kind,
                            content_pointer=pointer, available=fact['available']))
    return catalog


def feedback_details(previous, issues):
    rules = {r['path']: r for r in local_rules()}
    out = []
    for issue in issues:
        if isinstance(issue, str):
            path, code = issue.rsplit(':', 1)
            pattern = re.sub(r'\[\d+\]', '[*]', path)
            detail = dict(original_issue=issue, path=path, code=code,
                          required_local_constraints=deepcopy(rules.get(pattern, {})))
            if code == 'ARRAY_LENGTH':
                parts = re.findall(r'([A-Za-z_][A-Za-z_0-9]*)|\[(\d+)\]', path[1:])
                value = previous
                for key, index in parts:
                    value = value[key] if key else value[int(index)]
                detail['observed_length'] = len(value)
                detail['instruction'] = ('Return the declared number of genuine supporting references. '
                    'Use exact catalog IDs; an ID only identifies a source and does not certify support. '
                    'Do not fabricate sources or pad references to satisfy a count.') if path.endswith('.evidence_refs') else 'Respect the supplied local array limits.'
            out.append(detail)
        else:
            # Preserve full original semantic/source/time feedback without paraphrasing it away.
            out.append(dict(original_issue=deepcopy(issue), **deepcopy(issue)))
    return out


def candidate_payload(prepared, role_config, previous=None, issues=()):
    bridge = prepared['planner']['bridge']
    if validate_bridge(bridge)['outcome'] != 'PASSED_ENCODED_CHECKS':
        raise ValueError('I3_INPUT_NOT_ADMITTED')
    if previous is None and issues:
        raise ValueError('I3_FEEDBACK_WITHOUT_PREVIOUS')
    if previous is not None:
        expected = candidate_issues(bridge, previous)
        # Original checker traverses a set of object keys; issue ordering is immaterial.
        if sorted(canonical(i) for i in expected) != sorted(canonical(i) for i in issues):
            raise ValueError('I3_FEEDBACK_NOT_EXACT_LOCAL_RESULT')
    result = original_payload(prepared, role_config, previous, issues)
    body = json.loads(result['messages'][1]['content'])
    body['candidate_contract'] = dict(version=VERSION, local_constraints=local_rules(),
        reference_catalog=reference_catalog(bridge, body),
        goal_binding='Retain the ID and verbatim text of one supplied encoded goal.',
        evidence_binding=('Plan and every action require nonempty evidence_refs under the local schema. '
            'Reference only exact catalog IDs. The current task request supports the requested intention; '
            'it does not establish missing worksheet content, completion, resources or learner facts.'),
        ordinary_advice=('Keep schedule null for ordinary advice without a supplied calendar. '
            'Do not infer a planning calendar from the dashboard activity window. '
            'A supplied schedule still requires all original time, permission and source checks.'),
        semantic_boundary='Valid IDs and estimate arithmetic do not establish semantic support or real feasibility.')
    if previous is not None:
        body['checker_feedback_details'] = feedback_details(previous, issues)
    system = result['messages'][0]['content']
    if system.count(FINAL_ONLY_TEXT) != 1:
        raise ValueError('I3_FROZEN_CANDIDATE_INSTRUCTION_DRIFT')
    result['messages'][0]['content'] = system.replace(FINAL_ONLY_TEXT, '') + (
        ' Return only the candidate fields in the response schema. '
        'Obey candidate_contract.local_constraints as well as the wire schema, and use its reference catalog. '
        'A correction must fix the concrete paths using checker_feedback_details without changing source facts.')
    result['messages'][1]['content'] = canonical(body).decode()
    result['response_format']['json_schema']['name'] = 'i3_candidate_contract_v1'
    return result
