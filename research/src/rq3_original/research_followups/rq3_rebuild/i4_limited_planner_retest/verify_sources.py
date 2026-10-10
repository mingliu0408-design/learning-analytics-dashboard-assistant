"""Read-only frozen-source verification and one-time I4 input capture."""
import json
import stat
import zipfile
from pathlib import PurePosixPath
from i4_common import *
from utils.c4_rebuild.i1.renderer import final_payload, material
from utils.c4_rebuild.planning import validate_bridge


def check_archive(path, expected):
    require(sha(path.read_bytes()) == expected, 'ARCHIVE_HASH_MISMATCH:' + path.name)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        require(len(names) == len(set(names)), 'ARCHIVE_DUPLICATE')
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            require(not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
                and not stat.S_ISLNK(info.external_attr >> 16), 'ARCHIVE_UNSAFE_PATH')
        require(z.testzip() is None, 'ARCHIVE_CRC')
        mname = 'OUTPUT_MANIFEST.json' if 'OUTPUT_MANIFEST.json' in names else 'MANIFEST.json'
        manifest = json.loads(z.read(mname))
        members = manifest['members']
        require(set(names) == {r['path'] for r in members} | {mname}, 'ARCHIVE_ALLOWLIST')
        for row in members:
            data = z.read(row['path'])
            require(len(data) == row['bytes'] and sha(data) == row['sha256'], 'ARCHIVE_MEMBER_HASH')
    return dict(**file_binding(path), members=len(names), crc='PASS', member_hashes='PASS')


def capture():
    require(Path.cwd() == ROOT and git('branch', '--show-current') == BRANCH and git('rev-parse', 'HEAD') == START,
        'WORKTREE_IDENTITY_MISMATCH')
    require(not git('diff', '--name-only') and not git('diff', '--cached', '--name-only'), 'TRACKED_DRIFT')
    for line in git('ls-files', '--others', '--exclude-standard').splitlines():
        require(line.startswith(SCOPE), 'UNEXPECTED_UNTRACKED:' + line)
    require(not OUTPUT.exists() and not ZIP.exists(), 'EXCLUSIVE_OUTPUT_ALREADY_EXISTS')
    archives = [check_archive(PACKET.parent / n, h) for n, h in ARCHIVES.items()]
    z2 = zipfile.ZipFile(PACKET.parent / list(ARCHIVES)[0])
    z3 = zipfile.ZipFile(PACKET.parent / list(ARCHIVES)[1])
    task = zipfile.ZipFile(PACKET)
    preservation = load(I3 / 'SOURCE_PRESERVATION_MANIFEST.json')
    all_files = {}
    def bind(path):
        row = file_binding(path); all_files[str(path)] = row
        return row
    for n in ARCHIVES:
        bind(PACKET.parent / n)
    # I3's actual committed files are bound to the immutable, verified I3 archive.
    for name in git('ls-files', '--', str(I3.relative_to(ROOT))).splitlines():
        path = ROOT / name
        rel = str(path.relative_to(I3))
        member = 'COMMITTED_OUTPUT_MANIFEST.json' if rel == 'OUTPUT_MANIFEST.json' else rel
        require(path.read_bytes() == z3.read(member), 'I3_COMMITTED_ARCHIVE_MISMATCH:' + rel)
        bind(path)
    for row in preservation['captured_sources']:
        data = (I3 / row['path']).read_bytes()
        require(sha(data) == row['sha256'] and len(data) == row['bytes'], 'I3_CAPTURE_MISMATCH')
        src = row['source']
        if src['kind'] == 'ACTUAL_I2_FILE_AND_ZIP':
            path = OLD / src['relative_path']
            require(path.read_bytes() == data == z2.read(src['zip_member']), 'ACTUAL_I2_SOURCE_MISMATCH')
            bind(path)
        elif src['kind'] == 'COMMITTED_SOURCE':
            path = ROOT / src['relative_path']
            require(path.read_bytes() == data, 'FROZEN_COMMITTED_SOURCE_MISMATCH')
            bind(path)
        elif src['kind'] == 'I2_ZIP_MEMBER':
            require(z2.read(src['member']) == data, 'I2_RECEIPT_MISMATCH')
    for row in preservation['frozen_registry']:
        actual = bind(ROOT / row['path'])
        require(actual['sha256'] == row['sha256'] and actual['bytes'] == row['bytes'], 'FROZEN_REGISTRY_MISMATCH')
    for name in task.namelist():
        if not name.startswith('REFERENCES/'):
            continue
        leaf = name.split('/')[-1]
        data = z3.read('GIT_VERSION.json') if leaf == 'GIT_VERSION.json' else (
            (I1 / 'PILOT_CONFIGURATION_PROPOSED.json').read_bytes() if leaf.startswith('I1_PILOT_') else (I3 / leaf).read_bytes())
        require(task.read(name) == data, 'TASK_REFERENCE_MISMATCH:' + name)
    stages = {(s['logical'], s['stage']): (p, s) for p in (I3 / 'sources/live/stages').glob('*.json') for s in [load(p)]}
    config = settings(); repair = repair_module(); selected = []
    for i, row in enumerate(load_slots(), 1):
        p = prepared(row); path = I3 / row['frozen_input_source'].split('#')[0]; stage = load(path)
        require(stage['logical'] == row['logical'] and sha(stage['output']) == stage['output_sha256'], 'STAGE_HASH_MISMATCH')
        source = stage['output']['source']; rt = p['final_request']['runtime_input']
        require(source['origin'] == 'SYNTHETIC_MODEL_AUTHORED_EXPOSED', 'SOURCE_KIND_MISMATCH')
        require(set(source['primary']) == {'current_query','current_page','visible_conversation_history','dashboard_context'}, 'P3_FOUR_FIELDS')
        require(sha(source['primary']) == source['primary_sha256'], 'PRIMARY_HASH_MISMATCH')
        route_path, route = stages[source['primary_sha256'], 'B_FROZEN_P3']
        require(sha(route['output']) == route['output_sha256'] and route['output']['route']['provider_identity'] == 'ACTUAL_FROZEN_P3', 'ACTUAL_ROUTE_MISMATCH')
        require(all(v['status'] == 'ACCEPTED' and v['completion'] == 'OBSERVED' for v in route['output']['roles'].values()), 'OLD_ROUTE_INCOMPLETE')
        require(validate_bridge(p['planner']['bridge'])['outcome'] == 'PASSED_ENCODED_CHECKS', 'BRIDGE_NOT_ADMITTED')
        initial = repair.candidate_payload(p, config['generation_roles']['CANDIDATE'])
        require(sha(initial) == row['proposed_initial_request_sha256'] and initial == load(I3 / row['proposed_initial_request']), 'PROPOSED_INITIAL_HASH_MISMATCH')
        old_final_path = I3 / 'sources/live/attempts' / (row['prior_final_attempt_id'] + '.start.json')
        old_final = load(old_final_path)
        require(old_final['logical'] == row['dependent_final_logical'] and sha(old_final['request']) == row['prior_final_request_sha256'], 'OLD_FINAL_BINDING')
        require(final_payload(p, config['generation_roles']['FINAL'], None, True) == old_final['request'], 'ORIGINAL_FINAL_RENDERER_MISMATCH')
        folder = HERE / 'inputs' / f'{i:02}'
        folder.mkdir(parents=True, exist_ok=False)
        # Original full saved stage retains provenance; canonical prepared file is explicitly labelled an extraction.
        (folder / 'old_i2_stage.json').write_bytes(path.read_bytes())
        (folder / 'old_i2_route_stage.json').write_bytes(route_path.read_bytes())
        write_once(folder / 'prepared.json', p)
        write_once(folder / 'initial_request.json', initial)
        write_once(folder / 'supplied_material.json', material(p))
        for attempt in (row['initial_candidate_attempt_id'], row['initial_candidate_attempt_id'][:-1] + '2', row['prior_final_attempt_id']):
            for suffix in ('start','raw','outcome'):
                name = f'{attempt}.{suffix}.json'
                (folder / name).write_bytes((I3 / 'sources/live/attempts' / name).read_bytes())
        selected.append(dict(**row, directory=str(folder.relative_to(HERE)),
            input_unit_bytes=len(canonical(initial)) + 256, source_sha256=sha(source), scope=rt['scope'],
            prepared_sha256=sha(p), saved_stage_file_sha256=sha(path.read_bytes()),
            i3_frozen_input_hash_definition='sha(prepared.planner.bridge); I3 audit_saved.py:206 and prepare_review.py:157',
            current_query_sha256=sha(rt['context']['current_query'].encode()),
            visible_history_sha256=sha(rt['context']['visible_conversation_history']),
            runtime_input_sha256=sha(rt), compiler_evidence_sha256=sha(rt['evidence']),
            trace_sha256=sha(p['trace']), bridge_sha256=sha(p['planner']['bridge']),
            route_stage_sha256=sha(route), native_memory_sha256=sha(rt['memory']),
            retained_ids=p['trace']['retained_evidence_ids'],
            fact_scope_and_validity='UNCHANGED_BRIDGE_VALIDATION_PASSED; ALL_SAVED_BYTES_MATCH_I2_AND_I3',
            source_semantic_support='NOT_CHECKED'))
    for path in sorted((HERE / 'inputs').rglob('*')):
        if path.is_file(): bind(path)
    write_once(HERE / 'CONFIG.json', config)
    write_once(HERE / 'INPUT_BINDINGS.json', selected)
    write_once(HERE / 'SOURCE_PRESERVATION_MANIFEST.json', dict(version='I4_SOURCE_PRESERVATION_V1',
        files=list(all_files.values()), i3_captured_sources_verified=len(preservation['captured_sources']),
        frozen_registry_verified=len(preservation['frozen_registry']), archives=archives,
        historical_candidates_preserved=32, historical_answers_preserved=72,
        selected=selected, known_ignored_paths_preserved=load(HERE / 'GIT_START_RECEIPT.json')['ignored_paths'],
        excludes=['credentials', 'human scores', 'Gold', 'model weights', 'unrelated corpus']))
    print(canonical(dict(status='PASS', slots=len(selected), initial_hashes_match=5,
        input_units=[x['input_unit_bytes'] for x in selected], captured=len(preservation['captured_sources']),
        frozen=len(preservation['frozen_registry']), source_files_bound=len(all_files))).decode())


if __name__ == '__main__':
    capture()
