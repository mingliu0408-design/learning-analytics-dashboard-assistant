"""Verify the actual I4 archive, then copy an explicit synthetic DEV allowlist."""
import stat
import zipfile
from pathlib import PurePosixPath
from i5_common import *
from typed_v1 import candidate_payload, plan_kind, schemas, ORDINARY, SCHEDULE
from utils.c4_rebuild.i1.renderer import final_payload


def verified_zip(path, expected=None):
    if expected:
        require(sha(path.read_bytes()) == expected, 'ARCHIVE_HASH_MISMATCH')
    z = zipfile.ZipFile(path)
    names = z.namelist()
    require(len(names) == len(set(names)) and z.testzip() is None, 'ARCHIVE_DUPLICATE_OR_CRC')
    for info in z.infolist():
        p = PurePosixPath(info.filename)
        require(not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename and
                not stat.S_ISLNK(info.external_attr >> 16), 'UNSAFE_ARCHIVE_MEMBER')
    name = 'OUTPUT_MANIFEST.json' if 'OUTPUT_MANIFEST.json' in names else 'MANIFEST.json'
    import json
    manifest = json.loads(z.read(name))
    require({r['path'] for r in manifest['members']} == set(names) - {name}, 'MANIFEST_MEMBER_SET')
    for row in manifest['members']:
        data = z.read(row['path'])
        require(len(data) == row['bytes'] and sha(data) == row['sha256'], 'MEMBER_HASH_MISMATCH')
    return z, manifest


def main():
    require(Path.cwd() == ROOT and git('branch', '--show-current') == BRANCH and git('rev-parse', 'HEAD') == START, 'START_MISMATCH')
    require(not git('diff', '--name-only') and not git('diff', '--cached', '--name-only'), 'TRACKED_DRIFT')
    require(not OUTPUT.exists() and not ZIP.exists(), 'EXCLUSIVE_OUTPUT_EXISTS')
    z, manifest = verified_zip(ARCHIVE, ARCHIVE_SHA)
    task, _ = verified_zip(PACKET)
    origins = {r['path']: r for r in manifest['members']}
    captures = []
    wanted = {'INPUT_BINDINGS.json', 'CONFIG.json', 'ACTUAL_MECHANICAL_REPLAY.json', 'FIVE_SLOT_OUTCOMES.json',
              'I4_COMPLETION_REPORT.md', 'FINAL_QA.json'}
    for name in z.namelist():
        if name.startswith('inputs/') or name.startswith('live/attempts/') or name in wanted:
            data = z.read(name)
            committed = I4 / name
            require(committed.read_bytes() == data, 'I4_ARCHIVE_COMMITTED_MISMATCH:' + name)
            rel = name if name.startswith('inputs/') else 'historical_i4/' + name
            target = HERE / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as f:
                f.write(data)
            captures.append(dict(path=rel, archive_member=name, bytes=len(data), sha256=sha(data),
                                 committed_source=str(committed), archive_origin=origins[name]['origin']))
    for name in task.namelist():
        target = HERE / 'task_spec' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(task.read(name))
    oldrows = load(HERE / 'historical_i4/INPUT_BINDINGS.json')
    require([r['logical'] for r in oldrows] == SLOTS, 'SLOT_ORDER')
    rows = []; decisions = []
    for index, old in enumerate(oldrows, 1):
        p = load(HERE / 'inputs' / f'{index:02}' / 'prepared.json')
        require(sha(p) == old['prepared_sha256'], 'SAVED_PREPARED_MISMATCH')
        require(sha(p['planner']['bridge']) == old['frozen_input_sha256'], 'SAVED_BRIDGE_MISMATCH')
        req = candidate_payload(p, settings()['generation_roles']['CANDIDATE'])
        prior_final = final_payload(p, settings()['generation_roles']['FINAL'], None, True)
        require(sha(prior_final) == old['prior_final_request_sha256'], 'FROZEN_FINAL_RENDERER_DRIFT')
        write_once(HERE / 'requests' / f'{index:02}_initial.json', req)
        row = dict(old)
        row.update(i4_initial_request_sha256=old['proposed_initial_request_sha256'],
                   proposed_initial_request_sha256=sha(req), directory=f'inputs/{index:02}',
                   typed_wire_schema_sha256=sha(req['response_format']['json_schema']['schema']))
        rows.append(row)
        decisions.append(dict(logical=old['logical'], prepared_file=f'inputs/{index:02}/prepared.json',
            prepared_file_sha256=sha((HERE / f'inputs/{index:02}/prepared.json').read_bytes()),
            decision=plan_kind(p['planner']['bridge']),
            preserved={k:sha(p['planner']['bridge']['planner_input'][k]) for k in
                       ('facts','scope','goals','hard_constraints','completed_tasks','active_plan','resources')},
            decision_not_based_on_logical_id=True))
    write_once(HERE / 'CONFIG.json', settings())
    write_once(HERE / 'INPUT_BINDINGS.json', rows)
    write_once(HERE / 'INPUT_DERIVED_PLAN_KIND_AUDIT.json', dict(status='PASS', slots=decisions,
        real_source_readiness='NOT_EVALUATED', semantic_support='NOT_CHECKED', human_judgments_read=0))
    for kind in (ORDINARY, SCHEDULE):
        local, wire = schemas(kind)
        write_once(HERE / 'schemas' / (kind + '.local.json'), local)
        write_once(HERE / 'schemas' / (kind + '.wire.json'), wire)
    paths = {ARCHIVE, PACKET, I3 / 'repair_v1.py', I1 / 'PILOT_CONFIGURATION_PROPOSED.json', I4 / 'CONFIG.json'}
    for folder in ('utils/c4_rebuild', 'utils/c4_dashboard_scoped',
        'research_followups/rq3_rebuild/p0_planner_prototype/p0planner',
        'research_followups/rq3_rebuild/p1_planner_bridge/p1bridge',
        'research_followups/rq3_rebuild/p1_planner_bridge/inherited_p0/p0planner'):
        paths.update((ROOT / folder).rglob('*.py'))
    for folder in ('research_followups/rq3_rebuild/p0_planner_prototype',
        'research_followups/rq3_rebuild/p1_planner_bridge',
        'research_followups/rq3_rebuild/p1_planner_bridge/inherited_p0',
        'research_followups/rq3_rebuild/i0_human_integration/schemas'):
        paths.update((ROOT / folder).glob('*SCHEMA*.json'))
    paths.add(ROOT / 'utils/c4_memory/c4_memory_store.py')
    paths.update(Path(x['committed_source']) for x in captures)
    paths.update(HERE / x['path'] for x in captures)
    write_once(HERE / 'SOURCE_PRESERVATION_MANIFEST.json', dict(version='I5_SOURCES_V1',
        files=[file_binding(p) for p in sorted(paths)], captures=captures,
        archive=file_binding(ARCHIVE), task_packet=file_binding(PACKET),
        snapshot_policy='Exact I4 archive member bytes; existing source files read only; no H2 judgments read.',
        unchanged_scope='All tracked pre-I5 files protected by Git diff guard; execution dependencies additionally hashed.'))
    write_once(HERE / 'GIT_START_RECEIPT.json', dict(cwd=str(ROOT), branch=BRANCH, starting_head=START,
        observed_initial_status='', starting_tracked_untracked_clean=True, utc=utc(),
        identity_checks='pwd, git branch --show-current, git rev-parse HEAD, git status --short --untracked-files=all'))
    print(canonical(dict(status='PASS', copied_i4_members=len(captures), selected_slots=5,
        kinds=[x['decision']['kind'] for x in decisions], source_files_bound=len(paths))).decode())


if __name__ == '__main__':
    main()
