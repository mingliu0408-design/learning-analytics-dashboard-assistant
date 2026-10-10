"""Reopen and verify exact archive members, CRC, paths, modes, lengths and hashes."""
import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


def verify(path):
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive names')
        for i in infos:
            p = PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename or ':' in i.filename or '\x00' in i.filename or str(p) != i.filename or i.is_dir():
                raise ValueError('unsafe or noncanonical archive path')
            mode = i.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError('symlink or nonregular member')
        if z.testzip() is not None:
            raise ValueError('CRC failure')
        manifest = json.loads(z.read('OUTPUT_MANIFEST.json'))
        if manifest['excluded_self'] != 'OUTPUT_MANIFEST.json':
            raise ValueError('manifest self-exclusion must be explicit')
        entries = manifest['members']
        covered = [x['path'] for x in entries]
        if len(covered) != len(set(covered)) or 'OUTPUT_MANIFEST.json' in covered:
            raise ValueError('duplicate/self manifest record')
        if set(names) != set(covered) | {'OUTPUT_MANIFEST.json'}:
            raise ValueError('exact manifest member set mismatch')
        allowlist = json.loads(z.read('EXPORT_ALLOWLIST.json'))['members']
        if len(allowlist) != len(set(allowlist)) or set(allowlist) != set(names):
            raise ValueError('exact export allowlist mismatch')
        for row in entries:
            b = z.read(row['path'])
            if len(b) != row['bytes'] or z.getinfo(row['path']).file_size != row['bytes']:
                raise ValueError('member length mismatch: ' + row['path'])
            if hashlib.sha256(b).hexdigest() != row['sha256']:
                raise ValueError('member SHA-256 mismatch: ' + row['path'])
    return {'status':'PASS','path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'members':len(names),'manifest_members_verified':len(entries),'crc':'PASS','path_confinement':'PASS','symlinks':0,'duplicate_names':0,'exact_member_set':'PASS','all_member_lengths_and_sha256':'PASS','manifest_self_exclusion':'OUTPUT_MANIFEST.json','archive_hash_storage':'external receipt only'}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('zip');a=p.parse_args()
    try:
        print(json.dumps(verify(a.zip),indent=2))
    except (ValueError,KeyError,OSError,zipfile.BadZipFile) as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)}));raise SystemExit(1)
