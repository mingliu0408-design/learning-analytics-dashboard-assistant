"""Package the committed R1 revision with an explicit dependency allowlist.

Reuses the V2 Git/ZIP verification pattern, excludes old datasets and responses.
No model execution, retrieval, credential lookup or untracked file export.
"""
from v2_common import *
offline()
import argparse
from datetime import datetime, timezone
import os
import stat
import subprocess
import zipfile


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def collect():
    files = {}
    for p in HERE.rglob('*'):
        if p.is_symlink():
            raise ValueError('NO_SYMLINK:' + str(p))
        if p.is_file() and '__pycache__' not in p.parts and p.name != '.DS_Store':
            files[str(p.relative_to(ROOT))] = p
    for entry in read(HERE / 'DEPENDENCIES.json')['files']:
        p = ROOT / entry['path']
        if sha(p.read_bytes()) != entry['sha256'] or p.stat().st_size != entry['bytes']:
            raise ValueError('DEPENDENCY_CHANGED:' + entry['path'])
        files[entry['path']] = p
    for name, p in files.items():
        parts = Path(name).parts
        if p.is_symlink() or Path(name).is_absolute() or '..' in parts:
            raise ValueError('UNSAFE_MEMBER:' + name)
        if set(parts) & {'.git', '.env', 'node_modules', 'models', 'checkpoints', 'legacy_only'}:
            raise ValueError('EXCLUDED_MEMBER:' + name)
        if p.suffix.lower() in ('.bin', '.pt', '.pth', '.safetensors', '.pkl', '.zip'):
            raise ValueError('EXCLUDED_BINARY:' + name)
        if name.startswith(('experiments/rq3_original25_plus/', 'experiments/rq3_original25_plus_v2/',
                            'research_followups/rq3_rebuild/a_reuse62/runtime/',
                            'research_followups/rq3_rebuild/a_reuse62_replay_v2/runtime/')):
            raise ValueError('OLD_DATASET_EXCLUDED:' + name)
    return files


def assemble():
    start = read(HERE / 'audit/INTAKE.json')['starting_head']
    head = git('rev-parse', 'HEAD')
    branch = git('branch', '--show-current')
    if branch != 'research/rq3-rebuild-i1-pilot-launch' or git('status', '--porcelain'):
        raise ValueError('CLEAN_EXPECTED_BRANCH_REQUIRED')
    git('merge-base', '--is-ancestor', start, head)
    # NUL-delimited names preserve the returned Chinese filenames exactly,
    # independently of Git's core.quotePath display setting.
    changes = subprocess.check_output(['git', 'diff', '--name-only', '-z', start, head],
                                      cwd=ROOT).decode().rstrip('\0').split('\0')
    prefix = str(HERE.relative_to(ROOT)) + '/'
    if not changes or any(not n.startswith(prefix) for n in changes):
        raise ValueError('OUT_OF_SCOPE_GIT_CHANGE')
    payload = {name: p.read_bytes() for name, p in collect().items()}
    requests = ''.join(head + ':' + n + '\n' for n in payload).encode()
    batch = subprocess.run(['git', 'cat-file', '--batch'], cwd=ROOT, input=requests,
                           capture_output=True, check=True).stdout
    pos = 0
    for name, data in payload.items():
        end = batch.index(b'\n', pos)
        header = batch[pos:end].split(); pos = end + 1
        if len(header) != 3 or header[1] != b'blob':
            raise ValueError('UNBOUND_GIT_MEMBER:' + name)
        size = int(header[2]); blob = batch[pos:pos + size]; pos += size + 1
        if blob != data:
            raise ValueError('GIT_BYTE_MISMATCH:' + name)
    if pos != len(batch):
        raise ValueError('GIT_BATCH_LENGTH')
    preserved = read(HERE / 'audit/INTAKE.json')['preserved_files']
    for name, digest in preserved.items():
        if sha((ROOT / name).read_bytes()) != digest:
            raise ValueError('V1_OR_V2_CHANGED:' + name)
    lineage = dict(starting_head=start, ending_head=head, branch=branch,
        starting_worktree_clean=True, ending_worktree_clean=True,
        git_blob_verified_members=len(payload), preserved_v1_v2_files=len(preserved),
        changed_paths=changes, commits=git('log', '--format=%H %s', start + '..' + head).splitlines())
    payload['GIT_LINEAGE.json'] = (json.dumps(lineage, ensure_ascii=False, indent=2) + '\n').encode()
    payload['SOURCE_PATCH.diff'] = subprocess.check_output(['git', 'diff', '--no-ext-diff', start, head,
        '--', prefix + '*.py'], cwd=ROOT)
    command = [sys.executable, '-B', str(HERE / 'run_batch.py'), '--manifest', str(HERE / 'RUN_MANIFEST.json'), '--preflight']
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
    preflight = json.loads(result.stdout)
    if preflight['binding']['git_head'] != head:
        raise ValueError('FINAL_PREFLIGHT_GIT_MISMATCH')
    payload['PREFLIGHT_BINDING.json'] = (json.dumps(preflight, ensure_ascii=False, indent=2) + '\n').encode()
    payload['START_HERE.md'] = (f'''# RQ3 ORIGINAL25 PLUS 来源复核合入 R1

请从[阅读入口]({prefix}START_HERE.md)开始。此包为原项目本次限定资料修订，未运行模型、目标检索/embedding或Judge，也未填人类分数。

- [具体修订]({prefix}CHANGES.md)
- [49题问题与独立评价参考]({prefix}TASK_REVIEW_PACK.md)
- [九项英文前后对照]({prefix}QUERY_DIFF.md)
- [四组待决定适用性及有限余项]({prefix}DECISIONS_FOR_AUTHOR.md)
- [新版本批量命令]({prefix}COMMANDS.md)
- [本轮最终检查]({prefix}audit/R1_TESTS.json)

49题名册、原25逐字问题与12个family保留；41题是来源可准备候选，正式纳入尚待决定。五份回传在received_review原样归档，按其声明为待确认参考。

此ZIP按仓库相对路径组织，命令从解压根目录执行；依赖源码与普通来源已包含，不含模型权重、API凭据、原始身份文件、旧目标回答或不必要的上游大ZIP。现有Python库仍由本机提供。

MANIFEST.json覆盖除自身外的全部成员；GIT_LINEAGE.json给出真实起止版本，SOURCE_PATCH.diff仅为此次Python源文件补丁。PREFLIGHT_BINDING.json来自提交后的本机实际preflight；解压版git_basis会标为ARCHIVE_LINEAGE_RECORD，其他绑定字段应一致。此前历史测试记录不计入本轮最终检查数。

本轮仅授权资料合入；本包与批准模板均不授权未来模型调用。
''').encode()
    manifest = dict(data_revision='ORIGINAL25_PLUS_REVIEW_R1', self_excluded='MANIFEST.json',
        git=lineage, created_utc=datetime.now(timezone.utc).isoformat(),
        members=[dict(path=n, bytes=len(v), sha256=sha(v)) for n, v in sorted(payload.items())],
        exclusions=['credentials', 'API keys', 'model weights', 'raw identity files',
                    'old target responses and scores', 'old datasets except minimal before-data snapshots', 'nested upstream ZIPs'],
        authorization='LOCAL_LIMITED_DATA_REFERENCE_INTEGRATION_ONLY')
    payload['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    return payload


def verify(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist(); names = z.namelist()
        if len(names) != len(set(names)) or z.testzip() is not None:
            raise ValueError('CRC_OR_DUPLICATE_FAILURE')
        for i in infos:
            p = Path(i.filename)
            if p.is_absolute() or '..' in p.parts or stat.S_ISLNK(i.external_attr >> 16):
                raise ValueError('UNSAFE_ZIP_PATH')
        manifest = json.loads(z.read('MANIFEST.json'))
        if {e['path'] for e in manifest['members']} | {'MANIFEST.json'} != set(names):
            raise ValueError('MANIFEST_MEMBER_SET')
        for e in manifest['members']:
            raw = z.read(e['path'])
            if len(raw) != e['bytes'] or sha(raw) != e['sha256'] or z.getinfo(e['path']).file_size != e['bytes']:
                raise ValueError('READBACK_BYTES_OR_HASH:' + e['path'])
    return dict(path=str(path.resolve()), sha256=sha(path.read_bytes()), bytes=path.stat().st_size,
        members=len(names), manifest_covered_members=len(manifest['members']), crc_ok=True,
        safe_paths=True, duplicate_members=0, all_member_sizes_and_hashes_verified=True,
        starting_head=manifest['git']['starting_head'], ending_head=manifest['git']['ending_head'],
        branch=manifest['git']['branch'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args()
    if not a.verify_only:
        payload = assemble()
        with a.output.open('xb') as f:
            with zipfile.ZipFile(f, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for name, data in sorted(payload.items()):
                    info = zipfile.ZipInfo(name, (2026, 9, 7, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (0o100444 if name.endswith('.sqlite') else 0o100644) << 16
                    z.writestr(info, data)
            f.flush(); os.fsync(f.fileno())
    print(json.dumps(verify(a.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
