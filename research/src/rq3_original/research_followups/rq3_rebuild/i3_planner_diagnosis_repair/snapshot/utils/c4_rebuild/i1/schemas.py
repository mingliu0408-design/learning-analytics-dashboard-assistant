"""Explicit strict provider schemas plus unchanged local P1 semantic validation."""
from copy import deepcopy
from .common import ROOT, canonical
import json

VERSION = 'I1_ROLE_CONTRACT_V1'
LOCAL_CANDIDATE = json.loads((ROOT/'research_followups/rq3_rebuild/i0_human_integration/schemas/STRUCTURED_PLAN_SCHEMA.json').read_text())


def strict_subset(node):
    # Shapes/meaning are unchanged. Nonportable constraints stay in local checks.
    allowed = {'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'enum'}
    result = {}
    for key, value in node.items():
        if key == 'const':
            result['enum'] = [deepcopy(value)]
        elif key == 'properties':
            result[key] = {k: strict_subset(v) for k, v in value.items()}
        elif key in ('items',):
            result[key] = strict_subset(value)
        elif key == 'anyOf':
            result[key] = [strict_subset(v) for v in value]
        elif key in allowed:
            result[key] = deepcopy(value)
    return result


CANDIDATE = strict_subset(LOCAL_CANDIDATE)
FINAL = {'type': 'object', 'additionalProperties': False,
         'properties': {'answer': {'type': 'string'},
                        'cited_evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
                        'plan_fields': {'anyOf': [deepcopy(CANDIDATE), {'type': 'null'}]}},
         'required': ['answer', 'cited_evidence_ids', 'plan_fields']}


def strict_schema_check(node, root=True):
    if root and node.get('type') != 'object':
        raise ValueError('STRICT_ROOT_OBJECT_REQUIRED')
    if node.get('type') == 'object':
        if node.get('additionalProperties') is not False or set(node.get('required', [])) != set(node.get('properties', {})):
            raise ValueError('STRICT_OBJECT_FIELDS_REQUIRED_CLOSED')
        for item in node['properties'].values():
            strict_schema_check(item, False)
    if 'items' in node:
        strict_schema_check(node['items'], False)
    for item in node.get('anyOf', []):
        strict_schema_check(item, False)
    if set(node) - {'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'enum', 'description', 'title'}:
        raise ValueError('UNREVIEWED_STRICT_SCHEMA_KEYWORD')


def errors(value, schema, path='$'):
    if 'anyOf' in schema:
        return [] if any(not errors(value, s, path) for s in schema['anyOf']) else [path+':ANY_OF']
    t = schema.get('type')
    checks = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
              'string': lambda: isinstance(value, str), 'boolean': lambda: type(value) is bool,
              'integer': lambda: type(value) is int, 'number': lambda: type(value) in (int, float),
              'null': lambda: value is None}
    if t and not checks[t]():
        return [path+':TYPE']
    out = []
    if 'enum' in schema and value not in schema['enum']:
        out.append(path+':ENUM')
    if 'const' in schema and value != schema['const']:
        out.append(path+':CONST')
    if t == 'object':
        props = schema.get('properties', {})
        if set(schema.get('required', [])) - set(value) or (schema.get('additionalProperties') is False and set(value)-set(props)):
            out.append(path+':FIELD_SET')
        for key in value.keys() & props.keys():
            out += errors(value[key], props[key], path+'.'+key)
    if t == 'array':
        for i, v in enumerate(value):
            out += errors(v, schema['items'], path+f'[{i}]')
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
            out.append(path+':ARRAY_LENGTH')
        if schema.get('uniqueItems') and len({canonical(v) for v in value}) != len(value):
            out.append(path+':DUPLICATES')
    if t == 'string' and len(value) < schema.get('minLength', 0):
        out.append(path+':STRING_LENGTH')
    if t in ('number', 'integer') and not schema.get('minimum', -float('inf')) <= value <= schema.get('maximum', float('inf')):
        out.append(path+':NUMBER_BOUND')
    return out


def final_errors(value, evidence_ids, accepted_plan):
    out = errors(value, FINAL)
    if out:
        return out
    if not value['answer'].strip():
        out.append('ANSWER_EMPTY')
    ids = value['cited_evidence_ids']
    if len(ids) != len(set(ids)) or not set(ids) <= set(evidence_ids):
        out.append('CITATION_ID_NOT_RETAINED')
    if value['plan_fields'] != accepted_plan:
        out.append('FINAL_ADMIN_PLAN_CHANGED')
    return out
