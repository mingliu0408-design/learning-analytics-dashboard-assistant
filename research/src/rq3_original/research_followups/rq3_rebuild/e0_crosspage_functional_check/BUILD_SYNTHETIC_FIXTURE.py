"""Create invented event rows, never a pre-synthesised evidence pack."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
A, B = 99000001, 99000002
tables = {k: [] for k in ('moodle', 'echo', 'gdocs', 'features', 'reply_network', 'view_network', 'gdocs_ts', 'goals', 'reflections')}
row_scope = {}


def add(table, row, week):
    rid = f"SYNTHETIC:{table}:{len(tables[table]) + 1:03d}"
    tables[table].append({'_fixture_row_id': rid, **row})
    row_scope[rid] = {'course': 'SYNTHETIC_COURSE_A', 'observation_window': f'W{week}'}


for sid, week, resources, posts, replies, views, video_clicks, chars in [
    (A, 1, 3, 2, 1, 4, 2, [100, 50]),
    (A, 2, 7, 5, 3, 6, 4, [900]),
    (B, 1, 11, 8, 6, 9, 8, [700]),
    (B, 2, 13, 9, 7, 10, 9, [800]),
]:
    for event, activity, count in [('Resources_views', 'Resources', resources), ('Debate_posts', 'Debate', posts), ('Debate_replies', 'Debate', replies), ('Debate_views', 'Debate', views), ('Video_views', 'Lecture', video_clicks)]:
        for n in range(count):
            add('moodle', {'ID': sid, 'Time': f'2026-08-{3 if week == 1 else 10:02d}T10:{n:02d}:00Z', 'Week': week, 'Day_of_week': 'Monday', 'Time_of_day': 'Morning', 'Activity': activity, 'Content_week': week, 'Activity_event': event, 'Event': event}, week)
    for count in chars:
        add('gdocs', {'ID': sid, 'Week': week, 'absStrCount': count, 'dayOfWeek': 'Monday'}, week)
    for table in ('reply_network', 'view_network'):
        add(table, {'From': sid, 'To': B if sid == A else A, 'count': week + (1 if sid == A else 3), 'week': week}, week)
    add('goals', {'ID': sid, 'Week': week, 'Goal': f'SYNTHETIC learner {"A" if sid == A else "B"} goal W{week}'}, week)
    add('reflections', {'ID': sid, 'Week': week, 'Reflection': f'SYNTHETIC learner {"A" if sid == A else "B"} reflection W{week}'}, week)

for sid, week, title, views, percent in [(A, 1, 'SYNTHETIC lecture A', 2, 40), (A, 1, 'SYNTHETIC lecture B', 4, 80), (A, 2, 'SYNTHETIC lecture C', 10, 100), (B, 1, 'SYNTHETIC lecture D', 30, 10), (B, 2, 'SYNTHETIC lecture E', 40, 20)]:
    add('echo', {'ID': sid, 'Class': title, 'Content_week': week, 'Video Views': views, 'Video View %': percent}, week)

fixture = {
    'data_classification': 'EXPLICITLY_SYNTHETIC_NO_REAL_LEARNER_RECORDS',
    'learner_aliases': {'A': A, 'B': B},
    'windows': {'W1': {'start_inclusive': '2026-08-03T00:00:00Z', 'end_exclusive': '2026-08-10T00:00:00Z'}, 'W2': {'start_inclusive': '2026-08-10T00:00:00Z', 'end_exclusive': '2026-08-17T00:00:00Z'}},
    'scope_note': 'row_scope is SYNTHETIC test metadata, not a field consumed by production. Echo Content_week denotes content week; it is NOT an event timestamp. The fixture assigns observation windows explicitly for test slicing only. Production lacks this contract.',
    'columns': {
        'moodle': ['Time', 'Week', 'Day_of_week', 'Time_of_day', 'Activity', 'Content_week', 'Activity_event', 'Event', 'ID'],
        'echo': ['Class', 'Content_week', 'Video Views', 'Video View %', 'ID'],
        'gdocs': ['ID', 'Week', 'absStrCount', 'dayOfWeek'],
        'features': ['ID', 'Resources_views', 'Video_views_sum', 'Video_clicks', 'Debate_posts', 'Debate_replies', 'Debate_views', 'Total_chars'],
        'reply_network': ['From', 'To', 'count', 'week'], 'view_network': ['From', 'To', 'count', 'week'],
        'gdocs_ts': ['day', 'previousCohorts', 'currentCohort'],
        'goals': ['ID', 'Week', 'Goal'], 'reflections': ['ID', 'Week', 'Reflection']},
    'tables': tables, 'row_scope': row_scope,
    'hand_expected': {
        'A_W1': {'resource_views': 3, 'debate_posts': 2, 'debate_replies': 1, 'debate_views': 4, 'lecture_video_views': 6, 'lecture_mean_percent': 60, 'lecture_video_clicks': 2, 'reflection_chars': 150},
        'A_W2': {'resource_views': 7, 'debate_posts': 5, 'debate_replies': 3, 'debate_views': 6, 'lecture_video_views': 10, 'lecture_mean_percent': 100, 'lecture_video_clicks': 4, 'reflection_chars': 900},
        'A_ALL': {'resource_views': 10, 'debate_posts': 7, 'debate_replies': 4, 'debate_views': 10, 'lecture_video_views': 16, 'lecture_mean_percent': 73.33, 'lecture_video_clicks': 6, 'reflection_chars': 1050},
        'B_W1': {'resource_views': 11, 'debate_posts': 8, 'debate_replies': 6, 'debate_views': 9, 'lecture_video_views': 30, 'lecture_mean_percent': 10, 'lecture_video_clicks': 8, 'reflection_chars': 700}}
}
(OUT / 'SYNTHETIC_FIXTURE.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + '\n')
