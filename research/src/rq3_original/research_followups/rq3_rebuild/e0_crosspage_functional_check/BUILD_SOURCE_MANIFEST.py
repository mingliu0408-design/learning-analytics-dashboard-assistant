#!/usr/bin/env python3
"""Hash exact code/metadata inputs and copy only the offline import closure.

Raw learner sources are hashed as bytes; CSVs are read for their header only.
Pickle and XLSX sources are never deserialised. No private rows are exported.
"""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = '595b949185ad1b97cdbb9b0fdaeb9804aff7c45c'
LEGACY = Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3')
PACKET = Path('/Users/liuming/Downloads/RQ3_REBUILD_E0_CODEX_TASK_PACKET_2026-09-06.zip')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def git(*args, root=ROOT):
    return subprocess.check_output(['git', *args], cwd=root)


assert git('rev-parse', 'HEAD').decode().strip() == BASE
assert git('branch', '--show-current').decode().strip() == 'research/rq3-rebuild-e0-crosspage'
assert not git('diff', '--name-only', 'HEAD').strip(), 'Pre-existing tracked files changed'
closure = json.loads((HERE / 'RUNTIME_SOURCE_CLOSURE.json').read_text())['imported_python_files']
runtime_metadata = [
    'evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_candidate_configs_v1.json',
    'evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate_frozen_v1.json',
    'evaluation/rq3_real_c4/i0_integration/c4_real_generation_prompt_frozen_v1.txt',
    'evaluation/rq3_real_c4/i1_route_integration/c4_real_generation_schema_v2_provider_compatible.json',
]
static = [
    'pages/1 - 👨🏼‍💻 Individual Feedback.py', 'utils/helper.py', 'utils/const.py',
    'utils/c4_real_factory.py', 'evaluation/packaged_dashboard_fixture.py',
    'evaluation/rq3_real_c4/i1_route_integration/build_i1_artifacts.py',
    'research_followups/rq3_reassessment/pipeline_rag_audit/BASELINE_COMPILER_AND_PLANNER_AUDIT.md',
    'research_followups/rq3_reassessment/pipeline_rag_audit/EXECUTED_VS_LIVE_PIPELINE_AUDIT.md',
    'research_followups/rq3_reassessment/pipeline_rag_audit/STATUS.md',
]
records = []
for rel in sorted(set(closure + runtime_metadata + static)):
    path = ROOT / rel
    frozen = git('show', f'{BASE}:{rel}')
    assert path.read_bytes() == frozen, f'Source differs from base: {rel}'
    record = {'path': str(path), 'repo_relative_path': rel, 'commit': BASE, 'bytes': path.stat().st_size, 'sha256': sha(path), 'matches_committed_blob': True, 'use': 'runtime import closure' if rel in closure else ('deterministic runtime metadata' if rel in runtime_metadata else 'static audit reference')}
    # Byte-identical execution closure only; no provider outputs or raw inputs.
    if rel in closure + runtime_metadata:
        dest = HERE / 'runtime_snapshot' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        record['review_snapshot'] = dest.relative_to(HERE).as_posix()
    records.append(record)

input_members = []
with zipfile.ZipFile(PACKET) as z:
    assert z.testzip() is None
    prefix = 'RQ3_REBUILD_E0_CODEX_TASK_PACKET_2026-09-06/'
    manifest = json.loads(z.read(prefix + 'MANIFEST.json'))
    for member in manifest['members_excluding_manifest']:
        raw = z.read(prefix + member['path'])
        assert len(raw) == member['bytes']
        assert hashlib.sha256(raw).hexdigest() == member['sha256']
        input_members.append({**member, 'verified': True})

contracts = [
    ('Lecture/Resources/Debate', 'moodle', 'input/moodle/moodle_logs.csv', 'ID; Event; Activity; Week; Content_week; Time; Day_of_week', '_student_rows: numeric ID equality; then Event/Activity filters', 'Week groups event occurrence; Content_week denotes material; Time is present but no range filter is applied', 'utils/evidence_synthesiser.py:768,787,895,1574,1637'),
    ('Lecture', 'echo', 'input/echo/echo_logs.csv', 'ID; Class; Content_week; Video Views; Video View %', '_student_rows: numeric ID equality', 'Content_week is material week; no observation timestamp or observation Week column in verified header', 'utils/evidence_synthesiser.py:787,820'),
    ('Reflection', 'gdocs', 'input/gdocs/activities.pkl', 'ID; Week; absStrCount; dayOfWeek (code contract, pickle not opened)', '_student_rows: numeric ID equality', 'Week groups editing volume; no requested interval filter', 'utils/evidence_synthesiser.py:929,1645'),
    ('All four pages', 'features', 'input/features/features.csv', 'ID; Resources_views; Video_views_sum; Video_clicks; Video_view%_avg; Debate_posts; Debate_replies; Debate_views; Total_chars; network unique counts', '_feature_row: first matching ID row; not a unique-ID validator', 'No time columns; feature totals override event-derived fallbacks; cannot safely relabel as weekly', 'utils/evidence_synthesiser.py:1581,1591'),
    ('Debate', 'reply_network', 'input/debate/reply_network.csv', 'From; To; count; week; From_person; To_person (names not copied)', '_network_rows: From==ID or To==ID; only counts returned', 'week used in summary; no request interval filter', 'utils/evidence_synthesiser.py:1129,1601'),
    ('Debate', 'view_network', 'input/debate/view_network.csv', 'From; To; count; week; From_person; To_person (names not copied)', '_network_rows: From==ID or To==ID; only counts returned', 'week used in summary; no request interval filter', 'utils/evidence_synthesiser.py:1129,1601'),
    ('Reflection', 'gdocs_ts', 'input/gdocs/ts_cohorts.csv', 'day; previousCohorts; currentCohort', 'Cohort context, not same-learner evidence; all supplied cohort rows summed', 'day present; current function does not apply a time filter', 'utils/evidence_synthesiser.py:1144'),
    ('Identity mapping', 'student_info', 'input/student_info.xlsx', 'AppName; ID (code contract only)', 'UI maps selected AppName to first matching ID; fallback returns selected display value', 'No course/time contract at this request boundary', 'pages/1 - 👨🏼‍💻 Individual Feedback.py:1826'),
]
raw = []
map_rows = []
legacy_head = git('rev-parse', 'HEAD', root=LEGACY).decode().strip()
for pages, field, rel, columns, student_filter, time_semantics, anchors in contracts:
    for label, root in [('current_checkout', ROOT), ('known_legacy', LEGACY)]:
        path = root / rel
        present = path.is_file()
        header = None
        if present and path.suffix == '.csv':
            with path.open(encoding='utf-8-sig', newline='') as f:
                header = next(csv.reader(f))
        r = {'path': str(path), 'location': label, 'exists': present, 'status': 'PRESENT_BYTES_HASHED_SCHEMA_ONLY' if present else 'SOURCE_DATA_UNAVAILABLE_AT_CURRENT_PATH', 'bytes': path.stat().st_size if present else None, 'sha256': sha(path) if present else None, 'csv_header_only': header, 'private_rows_parsed': False, 'source_commit_claim': 'NONE; raw-file byte hashes are authoritative, legacy checkout HEAD is contextual only'}
        raw.append(r)
        map_rows.append({'page': pages, 'binding_field': field, 'location': label, 'path': str(path), 'status': r['status'], 'fields': '; '.join(header) if header else columns, 'schema_authority': 'CSV header verified' if header else 'committed code contract only', 'learner_scope': student_filter, 'course_scope': 'No course field/filter in consumed schema; source-root course authorisation must be supplied externally', 'time_scope': time_semantics, 'code_anchors': anchors, 'actual_live_binding': 'UNKNOWN_LIVE_CONFIGURATION', 'rows_exported': 0})
for name, col in [('goals', 'Goal/goal'), ('reflections', 'Reflection/reflection/text')]:
    map_rows.append({'page': 'Reflection optional text', 'binding_field': name, 'location': 'optional_API_only', 'path': 'NO_SOURCE_BOUND_BY_load_dashboard_data', 'status': 'NOT_BOUND_BY_STANDARD_LOADER', 'fields': col, 'schema_authority': 'code contract only', 'learner_scope': 'UNFILTERED: _summarise_optional_text_table has no learner argument', 'course_scope': 'no course filter', 'time_scope': 'no time filter', 'code_anchors': 'utils/evidence_synthesiser.py:728,1693', 'actual_live_binding': 'UNKNOWN_LIVE_CONFIGURATION', 'rows_exported': 0})
with (HERE / 'RAW_DASHBOARD_SOURCE_MAP.csv').open('w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(map_rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(map_rows)
manifest = {'task': 'RQ3-REBUILD-E0', 'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'starting_head': BASE, 'input_packet': {'path': str(PACKET), 'bytes': PACKET.stat().st_size, 'sha256': sha(PACKET), 'zip_crc_valid': True, 'manifest_entries': input_members}, 'committed_sources': records, 'raw_source_metadata_only': raw, 'legacy_checkout_head_context_only': legacy_head, 'legacy_raw_data_executed': False, 'raw_real_data_copied': False, 'frozen_payload_audit_repeated': False, 'live_configuration_inspected': False, 'source_snapshot_note': 'Only Python import closure and four deterministic config/prompt/schema files. No datasets, model weights, credentials, course documents, response bodies, ratings or full project.'}
(HERE / 'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'source_files_verified': len(records), 'snapshot_files': len(set(closure + runtime_metadata)), 'raw_files_present': sum(x['exists'] for x in raw), 'raw_paths_missing': sum(not x['exists'] for x in raw), 'private_rows_parsed': 0}))
