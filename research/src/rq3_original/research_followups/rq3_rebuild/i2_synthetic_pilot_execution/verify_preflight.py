"""Read-only I1 validators; write new I2 receipts, never construct a client."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import hashlib
import json
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, sha, write_once
from utils.c4_rebuild.i1.policy import preflight, verify_external_resources, APPROVAL_SCHEMA
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3

HERE = Path(__file__).resolve().parent
START = '6352d5ef6846e6d4e6d436d840811643642ff24f'
DOWNLOADS = Path('/Users/liuming/Downloads')
EXPECTED = {
    'PILOT_CONFIGURATION_PROPOSED.json': '869908855de62e5167aa885b68e5537767f2899624650b2f6aed6637b947c278',
    'TASK_MANIFEST.json': '79fb50127c1b243ea0add1b641c9ee3818a29dcb5bd5a5818618ba70aa00dfce',
    'SOURCE_MANIFEST.json': '294cc66a1896dd777e6eb90d579942ee9dd3dd2b13d00daa74f7940ea261be93',
    'FROZEN_ROLE_REGISTRY.json': '2426c78cd5d8480f030c558674c3623dbf8745ab67c37d74cc9407190bef3bfc',
}

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()

def main():
    assert Path.cwd() == ROOT
    assert git('branch', '--show-current') == 'research/rq3-rebuild-i1-pilot-launch'
    assert git('rev-parse', 'HEAD') == START
    assert not git('diff', '--name-only', START)
    new = git('ls-files', '--others', '--exclude-standard').splitlines()
    assert all(p.startswith(str(HERE.relative_to(ROOT)) + '/') for p in new)
    for n in ('RQ3_REBUILD_I2_SYNTHETIC_PILOT_AUTHORIZATION_2026-09-07.json',
              'RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07',
              'RQ3_REBUILD_I2_SYNTHETIC_PILOT_EXECUTION_REVIEW_2026-09-07.zip'):
        assert not (DOWNLOADS / n).exists(), 'EXISTING_OUTPUT_REQUIRES_STOP:' + n
    hashes = {n: sha((HOME / n).read_bytes()) for n in EXPECTED}
    assert hashes == EXPECTED
    packet = DOWNLOADS / 'RQ3_REBUILD_I2_CODEX_TASK_PACKET_2026-09-07.zip'
    with zipfile.ZipFile(packet) as z:
        infos = z.infolist()
        names = z.namelist()
        assert len(names) == len(set(names)) and z.testzip() is None
        for item in infos:
            p = PurePosixPath(item.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in item.filename
            assert not stat.S_ISLNK(item.external_attr >> 16)
        manifest = json.loads(z.read('PACKAGE_MANIFEST.json'))
        assert set(names) == {r['path'] for r in manifest['members']} | {'PACKAGE_MANIFEST.json'}
        for row in manifest['members']:
            b = z.read(row['path'])
            assert sha(b) == row['sha256'] and len(b) == row['bytes']
        refs = {'APPROVAL_V1.json': 'schemas/APPROVAL_V1.json'}
        for name in names:
            if name.startswith('REFERENCE/') and not name.endswith('ASSISTANT_INDEPENDENT_REVIEW_CHECKS.json'):
                leaf = PurePosixPath(name).name
                assert z.read(name) == (HOME / refs.get(leaf, leaf)).read_bytes()
        (HERE / 'task_spec').mkdir(exist_ok=False)
        for name in ('CODEX_I2_SYNTHETIC_PILOT_EXECUTION.md', 'PACKAGE_MANIFEST.json'):
            with (HERE / 'task_spec' / name).open('xb') as f:
                f.write(z.read(name))
    old_zip = DOWNLOADS / 'RQ3_REBUILD_I1_PILOT_LAUNCH_REVIEW_2026-09-07.zip'
    assert sha(old_zip.read_bytes()) == 'b565c051e71b39e4e957ca8a0f0d84eb48d922fe00fdfeb5250d0ad9ac588397'
    config, manifest, binding, _ = preflight(HOME/'PILOT_CONFIGURATION_PROPOSED.json',
        HOME/'TASK_MANIFEST.json', HOME/'SOURCE_MANIFEST.json')
    assert load(HOME/'schemas/APPROVAL_V1.json') == APPROVAL_SCHEMA
    verify_external_resources()
    frozen = FrozenP3()
    assert frozen.identity == config['frozen_p3_identity']
    assert frozen.receipt() == load(HOME/'FROZEN_ROLE_REGISTRY.json')
    for row in manifest['sources']:
        assert sha(row['source']) == row['source_sha256']
        assert sha(row['source']['primary']) == row['primary_sha256']
    assert len(manifest['task_ids']) == 12 and len(manifest['modes']) == 6
    assert len({r['primary_sha256'] for r in manifest['sources']}) == 8
    result = dict(status='PASS', checked_at=datetime.now(timezone.utc).isoformat(),
        workspace=str(ROOT), branch=git('branch', '--show-current'), starting_head=START,
        initial_worktree='CLEAN_BEFORE_NEW_I2_AUDIT_FILES', tracked_changes=[],
        source_hashes=hashes, binding=binding, source_files_verified=len(load(HOME/'SOURCE_MANIFEST.json')['files']),
        frozen_role_identity=frozen.identity, external_runtime='ORIGINAL_VERIFY_EXTERNAL_RESOURCES_PASS',
        task_ids=manifest['task_ids'], modes=manifest['modes'], unique_four_field_inputs=8,
        configuration_approved_field=config['approved'], provider_calls=0, credentials_read=False,
        input_packet=dict(path=str(packet), sha256=sha(packet.read_bytes()), members=len(names),
            integrity='CRC_MEMBERS_HASH_SIZE_SAFE_PATH_NO_SYMLINK_PASS'),
        i1_review_zip=dict(path=str(old_zip), sha256=sha(old_zip.read_bytes())),
        official_reference=dict(url=config['price_reference'], verified_date='2026-09-07',
            method='OFFICIAL_PAGE_SEARCH_AND_OPEN_NO_PAID_PROBE', snapshot='gpt-4o-mini-2024-07-18',
            uncached_usd_per_million={'input': 0.15, 'output': 0.60}, endpoint='https://api.openai.com/v1/chat/completions',
            account_availability='NOT_TESTED', pricing_is_invoice=False))
    write_once(HERE/'PREFLIGHT_VERIFICATION.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'source_files_verified', 'unique_four_field_inputs', 'provider_calls')}))

if __name__ == '__main__':
    main()
