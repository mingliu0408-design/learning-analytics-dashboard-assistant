"""Frozen H0 rating CSV and schema validators; no scoring or identity data included.

Selected dependency-closed definitions are verbatim from the frozen source.
This validates supplied records; it does not generate human ratings.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent

CRITERIA = (
    'CLARITY', 'PERSONALISATION', 'ACTIONABILITY', 'CONTEXT_AWARENESS',
    'MOTIVATION_AND_ENGAGEMENT', 'RELIABILITY', 'MULTI_PAGE_COHESIVENESS',
    'ERROR_HANDLING',
)


RATING_FIELDS = (
    'item_id', 'rater_id', 'criterion_id', 'score', 'note',
    'applicability_dispute', 'recorded_at',
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def schema_errors(value, schema, where='$'):
    """Validate the documented subset used by our closed JSON Schemas.

    Only type/enum/const/required/properties/additionalProperties/items are used.
    This is not a general implementation of JSON Schema draft 2020-12.
    """
    errors = []
    types = schema.get('type')
    if types:
        types = [types] if isinstance(types, str) else types
        matches = {
            'object': isinstance(value, dict), 'array': isinstance(value, list),
            'string': isinstance(value, str), 'integer': type(value) is int,
            'boolean': type(value) is bool, 'null': value is None,
        }
        if not any(matches.get(t, False) for t in types):
            return [f'{where}: expected {types}']
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        errors.append(f'{where}: incorrect constant')
    if 'enum' in schema and not any(type(value) is type(v) and value == v for v in schema['enum']):
        errors.append(f'{where}: value outside enum')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{where}.{key}: missing')
        if schema.get('additionalProperties') is False:
            for key in sorted(set(value) - set(props)):
                errors.append(f'{where}.{key}: forbidden extra field')
        for key, val in value.items():
            if key in props:
                errors.extend(schema_errors(val, props[key], f'{where}.{key}'))
    if isinstance(value, list) and 'items' in schema:
        for i, val in enumerate(value):
            errors.extend(schema_errors(val, schema['items'], f'{where}[{i}]'))
    return errors


def aware_time(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('timezone required')
    return t


def validate_ratings(rows, items, complete=False, blank_only=False):
    errors = schema_errors(rows, read_json(ROOT / 'schemas/ratings.schema.json'))
    if errors:
        return errors
    lookup = {i['item_id']: i for i in items}
    if len(lookup) != len(items):
        return ['duplicate item IDs']
    seen = set()
    raters = set()
    for row in rows:
        key = (row['item_id'], row['rater_id'], row['criterion_id'])
        if key in seen:
            errors.append('duplicate rater/item/criterion row')
        seen.add(key)
        item = lookup.get(row['item_id'])
        if item is None:
            errors.append('rating references unknown item')
            continue
        score = row['score']
        if blank_only and any(row[k] not in (None, '') for k in ('score', 'note', 'rater_id', 'applicability_dispute', 'recorded_at')):
            errors.append('H0 packet must contain only blank human entries')
        if score is None:
            if complete:
                errors.append('missing score; never silently omitted from denominator')
            continue
        if not isinstance(item['response'], str) or not item['response']:
            errors.append('cannot score a response-free item')
        if not row['rater_id'] or not row['recorded_at']:
            errors.append('filled human record requires rater ID and timestamp')
        else:
            try:
                aware_time(row['recorded_at'])
            except ValueError:
                errors.append('rating timestamp requires timezone')
        raters.add(row['rater_id'])
        applies = item['applicability'][row['criterion_id']]['applicable']
        if row['applicability_dispute']:
            if complete:
                errors.append('unresolved applicability dispute blocks final completeness')
        elif applies is True and score == 'NA':
            errors.append('applicable criterion cannot be NA')
        elif applies is False and score != 'NA':
            errors.append('inapplicable criterion requires human-entered NA')
        elif applies is None:
            errors.append('unresolved task applicability blocks rating')
    if complete:
        if not raters and items:
            errors.append('no completed rater identity')
        for item in items:
            for rater in raters:
                for criterion in CRITERIA:
                    if (item['item_id'], rater, criterion) not in seen:
                        errors.append('missing rater/item/criterion row')
    return errors


def load_ratings_csv(path):
    with Path(path).open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != list(RATING_FIELDS):
            raise ValueError('CSV header mismatch')
        rows = list(reader)
    for row in rows:
        v = row['score']
        if v == '':
            row['score'] = None
        elif v in {'1', '2', '3', '4', '5'}:
            row['score'] = int(v)
        elif v != 'NA':
            raise ValueError('CSV score must be blank, exact integer 1–5, or NA')
    return rows
