"""One-time byte-preserving capture of actual, exposed synthetic I2 evidence."""
from pathlib import PurePosixPath
import stat
import zipfile
from i3_common import HERE, ROOT, LIVE, I2_ZIP, PACKET, START, BRANCH, SCOPE, read, write, sha, git


def main():
    assert git('rev-parse', 'HEAD') == START
    assert git('branch', '--show-current') == BRANCH
    assert not git('diff', '--name-only') and not git('diff', '--cached', '--name-only')
    assert not (HERE/'SOURCE_PRESERVATION_MANIFEST.json').exists()
    unrelated = [p for p in git('ls-files', '--others', '--exclude-standard').splitlines() if not p.startswith(SCOPE)]
    assert unrelated == []
    origins = []

    def capture(destination, source, origin):
        assert source.is_file() and not source.is_symlink()
        data = source.read_bytes()
        target = HERE / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(data)
        origins.append(dict(path=destination, source=origin, bytes=len(data), sha256=sha(data)))

    frozen = read(ROOT/'research_followups/rq3_rebuild/i1_pilot_launch/SOURCE_MANIFEST.json')['files']
    for r in frozen:
        b = (ROOT/r['path']).read_bytes()
        assert len(b) == r['bytes'] and sha(b) == r['sha256'], r['path']
    with zipfile.ZipFile(I2_ZIP) as z:
        assert sha(I2_ZIP.read_bytes()) == 'b9506c17b67640b7868e9d9c4016f22f83d47934a844779e7a108987db3175f0'
        assert I2_ZIP.stat().st_size == 1695368 and len(z.infolist()) == 791
        assert len(set(z.namelist())) == 791 and z.testzip() is None
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
            assert not stat.S_ISLNK(info.external_attr >> 16) and not info.flag_bits & 1
        manifest = read_from_zip(z, 'OUTPUT_MANIFEST.json')
        assert set(z.namelist()) == {r['path'] for r in manifest['members']} | {'OUTPUT_MANIFEST.json'}
        for r in manifest['members']:
            b = z.read(r['path'])
            assert len(b) == r['bytes'] and sha(b) == r['sha256']
        for p in sorted(LIVE.rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(LIVE).as_posix()
            if p.parent.name not in ('attempts', 'stages', 'terminals') and rel not in ('JOURNAL.jsonl', 'RUN_BINDING.json'):
                continue
            assert z.read('live/'+rel) == p.read_bytes(), rel
            capture('sources/live/'+rel, p, dict(kind='ACTUAL_I2_FILE_AND_ZIP', relative_path=rel, zip_member='live/'+rel))
        for name in ('GIT_VERSION.json', 'OUTPUT_MANIFEST.json'):
            target = HERE/'sources/i2_review_receipts'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
            origins.append(dict(path=str(target.relative_to(HERE)), source=dict(kind='I2_ZIP_MEMBER', member=name),
                                bytes=target.stat().st_size, sha256=sha(target.read_bytes())))
    committed = ['research_followups/rq3_rebuild/i1_pilot_launch/'+n for n in
                 ('SOURCE_MANIFEST.json','TASK_MANIFEST.json','FROZEN_ROLE_REGISTRY.json','PILOT_CONFIGURATION_PROPOSED.json')]
    committed += ['research_followups/rq3_rebuild/i2_synthetic_pilot_execution/'+n for n in
                  ('EXECUTION_AND_SOURCE_BINDINGS.json','PRESERVATION_CHECKS.json','MODULE_PATH_OBSERVATIONS.json',
                   'CALL_AND_USAGE_SUMMARY.json','DEVELOPMENT_READING_COPY.md')]
    for rel in committed:
        b = (ROOT/rel).read_bytes()
        assert b == __import__('subprocess').check_output(['git','show',START+':'+rel],cwd=ROOT)
        capture('sources/committed/'+rel, ROOT/rel, dict(kind='COMMITTED_SOURCE', commit=START, relative_path=rel))
    with zipfile.ZipFile(PACKET) as z:
        for name in z.namelist():
            p = PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts
            target = HERE/'task_spec'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
            origins.append(dict(path=str(target.relative_to(HERE)), source=dict(kind='USER_TASK_PACKET', member=name),
                                bytes=target.stat().st_size, sha256=sha(target.read_bytes())))
    write('PREFLIGHT.json', dict(cwd=str(ROOT), branch=BRANCH, starting_head=START,
        initial_tracked_status='CLEAN', initial_untracked_files=[], recorded_unrelated_untracked=unrelated,
        task='Only START_HERE.md and CODEX_I3_PLANNER_DIAGNOSIS_AND_MINIMAL_REPAIR.md authorized by direct user request; other packet material is reference.',
        source_zip=dict(path=str(I2_ZIP),sha256=sha(I2_ZIP.read_bytes()),bytes=1695368,members=791,crc='PASS',all_manifest_members_verified=True),
        packet_sha256=sha(PACKET.read_bytes()), frozen_registry_files_verified=len(frozen), provider_authorization=False,
        no_environment_upgrade=True))
    write('SOURCE_PRESERVATION_MANIFEST.json', dict(version='I3_SOURCE_PRESERVATION_V1', starting_head=START,
        starting_tree=git('rev-parse',START+'^{tree}'), captured_sources=origins, frozen_registry=frozen,
        source_roots=dict(live=str(LIVE),i2_zip=str(I2_ZIP),repository=str(ROOT),task_packet=str(PACKET)),
        excluded=['credentials and keychain','historical authorization files','RUN.lock','models and databases',
                  'human responses, Gold and H1 returns','I1 mock outputs'], self_hash_excluded=True))
    print(dict(captured=len(origins), live_files=sum(r['path'].startswith('sources/live/') for r in origins), frozen_files=len(frozen)))


def read_from_zip(z, name):
    import json
    return json.loads(z.read(name))


if __name__ == '__main__':
    main()
