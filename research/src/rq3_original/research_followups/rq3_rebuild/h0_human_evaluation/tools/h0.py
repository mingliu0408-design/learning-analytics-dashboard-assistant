"""Offline H0 contracts. No provider, model, scoring or adjudication calls."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = (
    'CLARITY', 'PERSONALISATION', 'ACTIONABILITY', 'CONTEXT_AWARENESS',
    'MOTIVATION_AND_ENGAGEMENT', 'RELIABILITY', 'MULTI_PAGE_COHESIVENESS',
    'ERROR_HANDLING',
)
MODES = ('S0', 'S1', 'S2', 'S3', 'S4', 'S5')
VISIBLE_FIELDS = (
    'query', 'visible_context', 'evidence_dossier', 'response',
    'applicability', 'instructions', 'rubric_sha256', 'observability',
)
RATING_FIELDS = (
    'item_id', 'rater_id', 'criterion_id', 'score', 'note',
    'applicability_dispute', 'recorded_at',
)
FORBIDDEN_RUNTIME_FIELDS = {
    'expected_answer', 'missing_fact_labels', 'evaluator_reference',
    'evidence_dossier', 'score', 'rationale', 'expected_score',
    'p3_expected', 'expected_winner', 'applicability',
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value):
    # Preserve string bytes including whitespace, Unicode and line endings.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


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


def validate_task(task, ready=False):
    errors = schema_errors(task, read_json(ROOT / 'schemas/task.schema.json'))
    if errors:
        return errors
    ready = ready or task['status'] == 'FROZEN_PRE_ANSWER'
    p = task['provenance']
    legacy = bool(p['legacy_relations']) or p['exposure_status'] in {'LEGACY_62', 'M1_33', 'EXPOSED_DEVELOPMENT'}
    synthetic = p['provenance_class'] == 'MODEL_AUTHORED_SYNTHETIC_DEVELOPMENT_EXAMPLE'
    if task['split'] == 'HELD_OUT' and (legacy or synthetic):
        errors.append('held-out cannot contain legacy/exposed/model-authored development material')
    if p['human_author_id'] and p['human_author_id'] == p['independent_reviewer_id']:
        errors.append('writer and independent reviewer must be distinct')
    if not ready:
        return errors
    if task['status'] != 'FROZEN_PRE_ANSWER':
        errors.append('ready requires FROZEN_PRE_ANSWER; the validator never changes status')
    for key in ('task_id', 'family_id', 'episode_id', 'split'):
        if not task[key]:
            errors.append(f'{key}: unfilled')
    if not task['group_keys'] or any(not g['id'] for g in task['group_keys']):
        errors.append('group_keys: independent information-unit grouping required')
    if not any(g['kind'] == 'episode' and g['id'] == task['episode_id'] for g in task['group_keys']):
        errors.append('group_keys must include the exact episode identity')
    for key, val in p.items():
        if key != 'legacy_relations' and not val:
            errors.append(f'provenance.{key}: unfilled')
    if task['split'] == 'HELD_OUT' and p['exposure_status'] != 'NEW_PRE_RESPONSE_UNEXPOSED':
        errors.append('held-out requires explicit new pre-response exposure status')
    if p['provenance_class'] not in {'HUMAN_AUTHORED_SOURCE_GROUNDED', 'REAL_STUDENT_DATA', 'MODEL_AUTHORED_SYNTHETIC_DEVELOPMENT_EXAMPLE'}:
        errors.append('provenance_class: unknown source class')
    for key, val in task['task'].items():
        if not val:
            errors.append(f'task.{key}: unfilled')
    for key in ('text', 'scope', 'snapshot_version'):
        if not task['visible_context'][key]:
            errors.append(f'visible_context.{key}: unfilled (explicit no-context statement allowed)')
    ref = task['evaluator_reference']
    for key in ('evidence_dossier', 'acceptable_boundaries', 'scope', 'version'):
        if not ref[key]:
            errors.append(f'evaluator_reference.{key}: unfilled')
    if ref['scope'] != task['task']['scope'] or task['visible_context']['scope'] != task['task']['scope']:
        errors.append('common visible/reference/task scopes must agree')
    for key, a in task['applicability'].items():
        if type(a['applicable']) is not bool or not a['reason']:
            errors.append(f'applicability.{key}: unresolved task-level rule')
    if not any(a['applicable'] is True for a in task['applicability'].values()):
        errors.append('at least one original criterion must be applicable')
    eh_controls = {'MISSING', 'ABSENT', 'UNANSWERABLE', 'CONFLICTING', 'REVOKED', 'EXPIRED', 'WRONG_SCOPE', 'OOS'}
    if task['task']['source_condition'] in eh_controls and task['applicability']['ERROR_HANDLING']['applicable'] is not True:
        errors.append('task-inherent information problem requires Error Handling in all modes')
    ob = task['observability']
    if task['applicability']['MULTI_PAGE_COHESIVENESS']['applicable']:
        if ob['multi_page_design'] not in {'EPISODE_CROSS_PAGE', 'SINGLE_RESPONSE_ADAPTATION'} or not ob['context_reference']:
            errors.append('Multi-page Cohesiveness lacks observable cross-page material')
        if ob['multi_page_design'] == 'SINGLE_RESPONSE_ADAPTATION' and not ob['author_approval_reference']:
            errors.append('single-response adaptation requires explicit author approval reference')
    elif not ob['multi_page_design']:
        errors.append('record Multi-page observability limitation or exclusion design')
    for key, val in task['freeze'].items():
        if not val:
            errors.append(f'freeze.{key}: unfilled')
    if not re.fullmatch(r'[0-9a-f]{64}', task['freeze']['source_manifest_sha256']):
        errors.append('freeze.source_manifest_sha256: expected SHA-256')
    try:
        target = aware_time(task['task']['target_time'])
        frozen = aware_time(task['freeze']['frozen_at'])
        # Target time is the simulated/source observation time, not generation wall time.
        # Freeze may occur after target observation; it must precede future answer generation.
        _ = frozen
    except (ValueError, TypeError):
        errors.append('target/freeze times require explicit ISO timezone')
        target = None
    ids = [s['source_id'] for s in task['sources']]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        errors.append('source IDs must be nonempty and unique')
    if not set(ref['source_ids']).issubset(ids):
        errors.append('evaluator reference points to unknown source IDs')
    if not task['sources'] and not ref['absence_basis']:
        errors.append('no sources requires a documented absence/coverage basis')
    if task['task']['source_condition'] in {'PRESENT', 'ALREADY_VISIBLE', 'IRRELEVANT', 'CONFLICTING'} and not task['sources']:
        errors.append('source-present task requires versioned source spans')
    for source in task['sources']:
        for key in ('source_id', 'kind', 'document_or_session_id', 'version', 'exact_span', 'scope', 'permission_reference', 'pre_target_readiness_reference', 'state'):
            if not source[key]:
                errors.append(f'source.{key}: unfilled')
        if not re.fullmatch(r'[0-9a-f]{64}', source['sha256']):
            errors.append('source SHA-256 missing or invalid')
        if 'evaluation' not in source['permitted_use']:
            errors.append('evaluator source must have a stated evaluation permission')
        try:
            captured = aware_time(source['captured_at'])
            event = aware_time(source['event_time'])
            if target and (captured > target or event > target):
                errors.append('source unavailable before target observation time')
            start = aware_time(source['valid_from']) if source['valid_from'] else None
            end = aware_time(source['valid_to']) if source['valid_to'] else None
            if start and end and end < start:
                errors.append('source validity interval reversed')
            if 'generation' in source['permitted_use']:
                if source['state'] != 'ACTIVE' or source['scope'] != task['task']['scope']:
                    errors.append('generation source must be active and in scope')
                if target and ((start and start > target) or (end and end <= target)):
                    errors.append('generation source not valid at target time')
        except (ValueError, TypeError):
            errors.append('source times require ISO timezone')
    for a in task['source_annotations']:
        if a['source_id'] not in ids:
            errors.append('source annotation lacks source binding')
        if a['field'] in FORBIDDEN_RUNTIME_FIELDS:
            errors.append('evaluation label cannot be a source annotation')
        if not a['confirmed_by_reference']:
            errors.append('source annotation confirmation reference missing')
    return errors


def validate_collection(tasks, ready=False):
    if not isinstance(tasks, list):
        return ['task collection must be a list']
    errors = []
    for i, t in enumerate(tasks):
        errors.extend(f'task[{i}]: {e}' for e in validate_task(t, ready))
    if errors:
        return errors
    parent = list(range(len(tasks)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen, task_ids = {}, set()
    for i, t in enumerate(tasks):
        if t['task_id']:
            if t['task_id'] in task_ids:
                errors.append('duplicate task_id')
            task_ids.add(t['task_id'])
        keys = [('family', t['family_id'])] if t['family_id'] else []
        keys += [(g['kind'], g['id']) for g in t['group_keys'] if g['id']]
        for key in keys:
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    groups = {}
    for i, t in enumerate(tasks):
        groups.setdefault(find(i), []).append(t)
    for group in groups.values():
        splits = {t['split'] for t in group if t['split']}
        families = {t['family_id'] for t in group if t['family_id']}
        if len(splits) > 1:
            errors.append('related information unit crosses DEV/HELD_OUT')
        if len(families) > 1:
            errors.append('connected information units must share a family_id')
        if any(t['split'] == 'HELD_OUT' for t in group) and len(group) > 1:
            errors.append('current held-out design permits only one target per independent family')
    return errors


def project_runtime_capture(capture, approved_sources):
    """Pure projection only. No request sent; caller must verify real provenance later."""
    errors = schema_errors(capture, read_json(ROOT / 'schemas/runtime_capture.schema.json'))
    if errors:
        raise ValueError('; '.join(errors))
    target = aware_time(capture['target_time'])
    registry = {s['source_id']: s for s in approved_sources}
    if len(registry) != len(approved_sources):
        raise ValueError('duplicate approved source IDs')
    projected = []
    for a in capture['source_annotations']:
        source = registry.get(a['source_id'])
        if a['field'] in FORBIDDEN_RUNTIME_FIELDS:
            raise ValueError('evaluator-only annotation')
        if not source or 'generation' not in source['permitted_use'] or source['state'] != 'ACTIVE':
            raise ValueError('no active generation source authority')
        if source['scope'] != capture['visible_context']['scope']:
            raise ValueError('source scope mismatch')
        if a['available_pre_target'] is not True or a['permitted_runtime_use'] is not True or not a['confirmed_by_reference']:
            raise ValueError('annotation not confirmed for pre-target runtime use')
        if aware_time(a['captured_at']) > target or aware_time(source['captured_at']) > target:
            raise ValueError('future annotation/source')
        if (source['valid_from'] and aware_time(source['valid_from']) > target) or (source['valid_to'] and aware_time(source['valid_to']) <= target):
            raise ValueError('source outside validity window')
        projected.append({k: a[k] for k in ('source_id', 'field', 'value')})
    return {'query': capture['query'], 'visible_context': copy.deepcopy(capture['visible_context']), 'source_annotations': projected}


def visible_bytes(item):
    if set(item) != {'item_id', *VISIBLE_FIELDS}:
        raise ValueError('human item field set mismatch: hidden fields may not enter visible items')
    if not isinstance(item['response'], str) or not item['response']:
        raise ValueError('response-free slots cannot be deduplicated')
    return canonical_bytes({k: item[k] for k in VISIBLE_FIELDS})


def identical_visible_items(a, b):
    return visible_bytes(a) == visible_bytes(b)


def validate_condition_parity(items, mapping):
    """Coordinator-only check; restricted mode mappings never enter rater items."""
    errors = []
    lookup = {i['item_id']: i for i in items}
    mapped = [m.get('item_id') for m in mapping]
    if len(lookup) != len(items) or len(mapped) != len(set(mapped)) or set(mapped) != set(lookup):
        return ['condition mapping/item IDs must be an exact unique set']
    groups = {}
    for row in mapping:
        if set(row) != {'item_id', 'task_id', 'family_id', 'mode'}:
            return ['restricted mapping schema mismatch']
        groups.setdefault(row['task_id'], []).append(row)
    common_fields = [k for k in VISIBLE_FIELDS if k != 'response']
    for rows in groups.values():
        if sorted(r['mode'] for r in rows) != list(MODES):
            errors.append('task must map to exactly six main modes')
        if len({r['family_id'] for r in rows}) != 1:
            errors.append('same task cannot change family by mode')
        snapshots = [canonical_bytes({k: lookup[r['item_id']][k] for k in common_fields}) for r in rows]
        if len(set(snapshots)) != 1:
            errors.append('query/context/truth/applicability/instructions must be identical across six modes')
    return errors


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


def packet_errors(packet, preparation=True):
    keys = {'schema_version', 'stage', 'packet_id', 'protocol_approval_reference', 'rubric', 'items', 'item_template'}
    if not isinstance(packet, dict) or set(packet) != keys:
        return ['packet field set mismatch']
    errors = []
    if packet['schema_version'] != 'H0_HUMAN_PACKET_V1':
        errors.append('packet schema version mismatch')
    if preparation and (packet['stage'] != 'H0_RESPONSE_FREE_PREPARATION' or packet['protocol_approval_reference']):
        errors.append('H0 packet cannot assert future approval')
    if not preparation and (packet['stage'] != 'HUMAN_RATING_APPROVED' or not packet['protocol_approval_reference']):
        errors.append('future rating packet needs separately approved protocol reference')
    raw = read_json(ROOT / 'rubric.json')
    expected_rubric = {k: raw[k] for k in ('rubric_version', 'paper_title', 'source_version', 'source_pdf_sha256', 'scale', 'criteria')}
    if preparation and packet['rubric'] != expected_rubric:
        errors.append('H0 public rubric drift from verified source and labelled draft')
    r_hash = digest(canonical_bytes(packet['rubric']))
    seen = set()
    for item in [*packet['items'], packet['item_template']]:
        if not isinstance(item, dict) or set(item) != {'item_id', *VISIBLE_FIELDS}:
            errors.append('visible item fields mismatch / possible blinding leak')
            continue
        is_template = item is packet['item_template']
        if not is_template:
            if not re.fullmatch(r'[0-9a-f]{32}', item['item_id']) or item['item_id'] in seen:
                errors.append('opaque item ID missing or duplicate')
            seen.add(item['item_id'])
        if preparation or is_template:
            if item['response'] is not None:
                errors.append('H0/template must be response-free')
        elif not isinstance(item['response'], str) or not item['response']:
            errors.append('future rating item missing response')
        if item['rubric_sha256'] != r_hash:
            errors.append('rubric digest mismatch')
        task_props = read_json(ROOT / 'schemas/task.schema.json')['properties']
        for item_key, task_key in [('visible_context', 'visible_context'), ('evidence_dossier', 'evaluator_reference'), ('applicability', 'applicability'), ('observability', 'observability')]:
            errors.extend(schema_errors(item[item_key], task_props[task_key], item_key))
        if not isinstance(item['query'], str) or not isinstance(item['instructions'], str):
            errors.append('query/instructions must be strings')
    return errors
