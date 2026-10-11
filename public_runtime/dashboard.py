"""Trusted selection of the released, anonymous dashboard CSV sources.

No research task, evaluator, Gold, pickle or provider is read here. Course weeks
are observation buckets from the original UI, not claims about current learner
availability. The UTC dates serialize those buckets; the timezone of historical
naive source timestamps is not established and is never silently inferred.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/dashboard'
COURSE_ID = 'DUTE_LEGACY_COURSE'
CALENDAR_VERSION = 'DUTE_ORIGINAL_OBSERVATION_WEEKS_2025_V1'
SCHEMA = 'PUBLIC_DASHBOARD_SELECTION_V1'
FIRST_MONDAY = datetime(2025, 9, 29, tzinfo=timezone.utc)
MIN_WEEK, MAX_WEEK = 0, 10
SOURCES = {
    'roster': 'input/student_info.csv',
    'moodle': 'input/moodle/moodle_logs.csv',
    'echo': 'input/echo/echo_logs.csv',
    'gdocs': 'input/gdocs/activities.csv',
    'reply_network': 'input/debate/reply_network.csv',
    'view_network': 'input/debate/view_network.csv',
    'features': 'input/features/features.csv',
    'cohorts': 'input/gdocs/ts_cohorts.csv',
}
CONTEXT_KEYS = {'schema_version', 'kind', 'task_id', 'learner_id', 'course_id',
                'week_start', 'week_end', 'calendar_version', 'source_version',
                'lecture_item_id'}

def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def _path(relative):
    path = DATA / relative
    if path.is_symlink() or not path.resolve().is_relative_to(DATA.resolve()):
        raise ValueError('DASHBOARD_SOURCE_PATH_BOUNDARY')
    return path

def _rows(relative):
    with _path(relative).open(newline='', encoding='utf-8-sig') as source:
        return list(csv.DictReader(source))

def source_identity():
    values = {name: hashlib.sha256(_path(relative).read_bytes()).hexdigest()
              for name, relative in SOURCES.items()}
    return hashlib.sha256(_canonical(values).encode()).hexdigest(), values

def learners():
    return [{'id': row['ID'], 'label': row['AppName']}
            for row in _rows(SOURCES['roster'])]

def _id(value):
    value = str(value)
    if not value.isascii() or not value.isdigit() or str(int(value)) != value:
        raise ValueError('ANONYMOUS_DASHBOARD_ID_REQUIRED')
    if value not in {row['id'] for row in learners()}:
        raise ValueError('UNKNOWN_DASHBOARD_LEARNER')
    return value

def calendar():
    return {str(week): ((FIRST_MONDAY + timedelta(weeks=week-1)).isoformat(),
                        (FIRST_MONDAY + timedelta(weeks=week)).isoformat())
            for week in range(MIN_WEEK, MAX_WEEK + 1)}

def build_context(learner_id, *, week_start=MIN_WEEK, week_end=MAX_WEEK,
                  lecture_item_id=None):
    learner_id = _id(learner_id)
    if any(type(w) is not int for w in (week_start, week_end)) or not MIN_WEEK <= week_start <= week_end <= MAX_WEEK:
        raise ValueError('SELECT_CONTIGUOUS_OBSERVATION_WEEK_RANGE_0_TO_10')
    if lecture_item_id is not None:
        if not isinstance(lecture_item_id, str) or lecture_item_id not in {
                row['Class'] for row in _rows(SOURCES['echo']) if row['ID'] == learner_id}:
            raise ValueError('UNKNOWN_DASHBOARD_RECORDING')
    version, _ = source_identity()
    return dict(schema_version=SCHEMA, kind='DASHBOARD_CSV', task_id='dashboard-' + learner_id,
                learner_id=learner_id, course_id=COURSE_ID, week_start=week_start,
                week_end=week_end, calendar_version=CALENDAR_VERSION,
                source_version=version, lecture_item_id=lecture_item_id)

def validate_context(context, task_id=None):
    if not isinstance(context, dict) or set(context) != CONTEXT_KEYS:
        raise ValueError('DASHBOARD_CONTEXT_ALLOWLIST')
    expected = build_context(context['learner_id'], week_start=context['week_start'],
                             week_end=context['week_end'], lecture_item_id=context['lecture_item_id'])
    if context != expected or task_id is not None and task_id != expected['task_id']:
        raise ValueError('DASHBOARD_CONTEXT_IDENTITY_CHANGED')
    return expected

def source_selection(context):
    """Re-read only allowlisted source bytes; do not trust client-supplied rows."""
    selection = validate_context(context)
    tables = {name: _rows(relative) for name, relative in SOURCES.items() if name not in ('roster', 'cohorts')}
    cohort_rows = _rows(SOURCES['cohorts'])
    # Both Date and Week independently support the original Monday/week mapping.
    # Check dates without converting naive historical timestamps to UTC instants.
    for table, column in (('moodle', 'Time'), ('gdocs', 'Date')):
        for row in tables[table]:
            date = datetime.fromisoformat(row[column]).date()
            actual = (date - FIRST_MONDAY.date()).days // 7 + 1
            if actual != int(row['Week']):
                raise ValueError('ORIGINAL_OBSERVATION_WEEK_CALENDAR_MISMATCH')
    version, hashes = source_identity()
    if selection['source_version'] != version:
        raise ValueError('DASHBOARD_SOURCE_CHANGED_DURING_READ')
    specs = {}
    for name, rows in tables.items():
        if name in ('moodle', 'gdocs'):
            observation, week = 'week', 'Week'
        elif name in ('reply_network', 'view_network'):
            observation, week = 'week', 'week'
        elif name == 'echo':
            observation, week = 'content_week', None
        else:
            observation, week = 'cumulative', None
        specs[name] = dict(columns=list(rows[0]) if rows else [], single_course=COURSE_ID,
                           course_binding_evidence='USER_AUTHORIZED_SINGLE_PROJECT_DUTE_SOURCE_TREE:' + SOURCES[name],
                           observation=observation, week_column=week,
                           calendar_version=CALENDAR_VERSION if week else None,
                           learner_column='ID', item_column='Class' if name == 'echo' else None,
                           coverage=[], source_sha256=hashes[name])
    weeks = calendar()
    scope = dict(learner_id=selection['learner_id'], course_id=COURSE_ID, snapshot=version,
                 start=weeks[str(selection['week_start'])][0], end=weeks[str(selection['week_end'])][1],
                 timezone='UTC', calendar_version=CALENDAR_VERSION,
                 lecture_item_id=selection['lecture_item_id'])
    return dict(context=selection, scope=scope, tables=tables, specs=specs,
                calendar=dict(version=CALENDAR_VERSION, timezone='UTC', weeks=weeks),
                roster={row['id']: [COURSE_ID] for row in learners()},
                source_hashes=hashes,
                chart_contexts={'Reflection': {'cohort_comparison': reflection_cohort_context(selection, tables['gdocs'], cohort_rows, hashes['cohorts'])}},
                temporal_boundary='Source Week buckets validated against original Date/Time dates. UTC dates encode observation buckets only; naive source timestamp timezone is unknown. Echo Content_week is material week, not watching time. Coverage is not asserted complete; absent observations remain unknown.')


def _finite_number(value):
    if value in (None, '') or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def reflection_cohort_context(selection, gdocs_rows, cohort_rows, source_sha256):
    """Pure current-chart context; cohort curves are not personal activity facts.

    Source day→Week joins are derived from the provided activity records rather
    than inferred from a DataFrame index. The selected learner's actual rows are
    summed by day; absence stays unknown even when the renderer displays a zero
    for the count of recorded rows. No cohort population/coverage claim is added.
    """
    low, high = selection['week_start'], selection['week_end']
    identifier = selection['learner_id']
    day_weeks = {}
    edits = {}
    invalid_days = set()
    for row in gdocs_rows:
        day, week = _finite_number(row.get('day')), _finite_number(row.get('Week'))
        if day is None or week is None or not day.is_integer() or not week.is_integer():
            continue
        day, week = int(day), int(week)
        day_weeks.setdefault(day, set()).add(week)
        if row.get('ID') == identifier and low <= week <= high:
            value = _finite_number(row.get('absStrCount'))
            if value is None:
                invalid_days.add(day)
            else:
                edits[day] = edits.get(day, 0.0) + value
    values = []
    excluded = 0
    for row in cohort_rows:
        day = _finite_number(row.get('day'))
        if day is None or not day.is_integer():
            excluded += 1
            continue
        day = int(day)
        weeks = day_weeks.get(day, set())
        if len(weeks) != 1:
            excluded += 1
            continue
        week = next(iter(weeks))
        if not low <= week <= high:
            continue
        observed = day in edits and day not in invalid_days
        values.append(dict(day=day, observation_week=week,
            previous_cohort=_finite_number(row.get('previousCohorts')),
            current_cohort=_finite_number(row.get('currentCohort')),
            learner_recorded_edits=edits[day] if observed else None,
            learner_source_status='RECORDED_VALUE_PARTIAL_COVERAGE' if observed else 'NO_OBSERVATIONS_OR_INVALID_VALUE_COVERAGE_UNKNOWN',
            learner_chart_display_value=edits[day] if observed else (None if day in invalid_days else 0.0)))
    values.sort(key=lambda row: row['day'])
    return dict(source_kind='HISTORICAL_COHORT_CHART_CONTEXT', source_path=SOURCES['cohorts'],
        source_sha256=source_sha256, unit='character edits per source day',
        time_basis='Actual source day joined to observed Week; historical naive timestamp timezone is unknown.',
        observation_weeks=[low, high], records=values,
        unavailable_day_mapping_rows=excluded,
        population_basis='Saved previousCohorts/currentCohort series as supplied; population size, aggregation and complete coverage are not established by this CSV.',
        coverage_status='NOT_ASSERTED_COMPLETE',
        interpretation_limit='Cohort curves are descriptive page context, not individual learning facts, mastery or learning quality. A plotted zero for no recorded learner row does not establish no actual editing.')
