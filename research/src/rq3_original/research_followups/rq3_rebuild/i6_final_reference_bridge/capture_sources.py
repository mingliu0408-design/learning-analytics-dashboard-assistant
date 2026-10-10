"""One-time allowlisted capture after original failure replay; no generation."""
from copy import deepcopy
import json
import zipfile
from i6_common import *
from utils.c4_rebuild.i1.durable import parse_response
from utils.c4_rebuild.i1.schemas import final_errors

def copy_bytes(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'PRELIVE_CAPTURE_CONFLICT:' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(data)

def main():
    require(Path.cwd() == ROOT and git('branch', '--show-current') == BRANCH and git('rev-parse', 'HEAD') == START, 'START_GATE')
    require(not git('diff', '--name-only') and not git('diff', '--cached', '--name-only'), 'TRACKED_START_GATE')
    require(not OUTPUT.exists() and not ZIP.exists(), 'FRESH_OUTPUT_GATE')
    untracked = git('ls-files', '--others', '--exclude-standard').splitlines()
    require(all(p.startswith(SCOPE) for p in untracked), 'UNRELATED_UNTRACKED')
    replay = load('/tmp/I6_OLD_FAILURE_REPLAY_01a07bf5.json')
    require(replay['issues'] == ['CITATION_ID_NOT_RETAINED'] and replay['worktree_edits_before_replay'] == 0, 'REPLAY_FIRST_REQUIRED')
    copy_bytes(HERE / 'OLD_FAILURE_REPLAY.json', Path('/tmp/I6_OLD_FAILURE_REPLAY_01a07bf5.json').read_bytes())
    if not (HERE / 'GIT_START_RECEIPT.json').exists():
        write_once(HERE / 'GIT_START_RECEIPT.json', dict(cwd=str(ROOT), branch=BRANCH, head=START,
            tracked_clean=True, initial_untracked=[], observed_utc=utc(), observation_basis='Initial tool read before I6 edits; current untracked files are new I6 implementation only.'))
    require(sha(ARCHIVE.read_bytes()) == ARCHIVE_SHA, 'I5_ARCHIVE_HASH')
    paths = ['CONFIG.json', 'INPUT_BINDINGS.json', 'SDK_LOCAL_INSPECTION.json',
             'SOURCE_PRESERVATION_MANIFEST.json', 'PROVIDER_PAYLOAD_PROVENANCE_REVIEW.json',
             'I5_COMPLETION_REPORT.md', 'FINAL_FAILURE_TRACE.json', 'typed_v1.py', 'run_i5.py', 'i5_common.py']
    paths += [f'{folder}/{i:02}{suffix}' for i in range(1,6)
              for folder,suffix in [('requests','_initial.json'),('inputs','/prepared.json'),('inputs','/supplied_material.json')]]
    paths += [f'live/attempts/01_{phase}.{kind}.json' for phase in ('initial','final')
              for kind in ('raw','outcome','start','timing','dispatch')]
    captures=[]; preserved={}
    def track(path):
        preserved[str(path)] = file_binding(path)
    with zipfile.ZipFile(ARCHIVE) as z:
        require(z.testzip() is None, 'I5_ZIP_CRC')
        manifest = {r['path']:r for r in json.loads(z.read('OUTPUT_MANIFEST.json'))['members']}
        versions = json.loads(z.read('GIT_VERSION.json'))
        require(START in versions.values(), 'I5_END_HEAD_NOT_FOUND')
        for name in paths:
            data=z.read(name); original=I5/name; m=manifest[name]
            require(len(data)==m['bytes'] and sha(data)==m['sha256'], 'I5_MANIFEST_IDENTITY:'+name)
            require(original.read_bytes()==data, 'I5_CHECKOUT_ARCHIVE_MISMATCH:'+name)
            require(git('rev-parse', START+':'+str(original.relative_to(ROOT))) == m['origin']['git_blob'], 'I5_GIT_BLOB:'+name)
            target = name if name.startswith(('inputs/','requests/')) or name=='INPUT_BINDINGS.json' else 'historical_i5/'+name
            copy_bytes(HERE/target,data); track(original)
            captures.append(dict(path=target,archive_member=name,bytes=len(data),sha256=sha(data),origin=m['origin']))
    # Retain only the two expressly authorized task documents. Do not read H3.
    with zipfile.ZipFile(PACKET) as z:
        pm={r['path']:r for r in json.loads(z.read('PACKAGE_MANIFEST.json'))['files']}
        for name in ('START_HERE.md','CODEX_I6_FINAL_REFERENCE_BRIDGE_AND_CONTINUATION.md'):
            data=z.read(name)
            require(sha(data)==pm[name]['sha256'] and len(data)==pm[name]['bytes'], 'PACKET_IDENTITY')
            copy_bytes(HERE/'task_spec'/name,data)
        # Verify navigation aids against real archived sources, without reading H3.
        maps={'I5_CONFIG_PRESERVED.json':'CONFIG.json','I5_FINAL_ACTUAL_RAW.json':'live/attempts/01_final.raw.json',
              'I5_FIRST_ACCEPTED_CANDIDATE_RAW.json':'live/attempts/01_initial.raw.json',
              'I5_FIRST_ACCEPTED_CANDIDATE_OUTCOME.json':'live/attempts/01_initial.outcome.json',
              'I5_INPUT_BINDINGS.json':'INPUT_BINDINGS.json','I5_FINAL_FAILURE_TRACE.json':'FINAL_FAILURE_TRACE.json'}
        for aid,original in maps.items():
            require(z.read('REFERENCES/'+aid)==(I5/original).read_bytes(), 'PACKET_REFERENCE_MISMATCH:'+aid)
        require(z.read('REFERENCES/PRESERVED_I1_FINAL_CHECKER_SOURCE.py')==(ROOT/'utils/c4_rebuild/i1/schemas.py').read_bytes(), 'ORIGINAL_CHECKER_IDENTITY')
        oldstart=load(I5/'live/attempts/01_final.start.json')
        require(json.loads(z.read('REFERENCES/I5_FINAL_ACTUAL_REQUEST.json'))==oldstart,'PACKET_FINAL_START_ENVELOPE_MISMATCH')
    # Verify the inherited source chain by bytes; no source modules are executed.
    oldmanifest=load(I5/'SOURCE_PRESERVATION_MANIFEST.json')
    for row in oldmanifest['files']:
        path=Path(row['path'])
        if path.suffix in ('.py','.json') and (any(s in str(path) for s in ('/utils/c4_rebuild/','/p0planner/','/p1bridge/','/utils/c4_dashboard_scoped/','/schemas/')) or path.name in ('repair_v1.py','CONFIG.json','PILOT_CONFIGURATION_PROPOSED.json')):
            require(file_binding(path)==row,'ORIGINAL_SOURCE_DRIFT:'+str(path));track(path)
    provenance=load(I5/'PROVIDER_PAYLOAD_PROVENANCE_REVIEW.json')
    for row in provenance['source_proofs']:
        require(file_binding(row['path'])==row,'SYNTHETIC_SOURCE_PROOF_DRIFT');track(Path(row['path']))
    track(ARCHIVE);track(PACKET)
    for row in load(I5/'SDK_LOCAL_INSPECTION.json').values():
        if isinstance(row,dict) and 'path' in row:
            require(sha(Path(row['path']).read_bytes())==row['sha256'],'SDK_SOURCE_IDENTITY');track(Path(row['path']))
    for folder in (ROOT/'utils/c4_rebuild',):
        for path in folder.rglob('*.py'): track(path)
    write_once(HERE/'CONFIG.json',settings())
    approval_schema=load(I5/'APPROVAL_SCHEMA.json')
    approval_schema['properties']['version']['const']='I6_DIRECT_APPROVAL_V1'
    write_once(HERE/'APPROVAL_SCHEMA.json',approval_schema)
    write_once(HERE/'SOURCE_PRESERVATION_MANIFEST.json',dict(version='I6_SOURCE_MANIFEST_V1',archive=file_binding(ARCHIVE),
        task_packet=file_binding(PACKET),files=list(preserved.values()),captures=captures,
        evaluator_judgments_read=False,source_kind='EXPOSED_SYNTHETIC_DEV_ONLY'))
    print(canonical(dict(status='CAPTURED',captures=len(captures),preserved_files=len(preserved),provider_calls=0)).decode())

if __name__ == '__main__': main()
