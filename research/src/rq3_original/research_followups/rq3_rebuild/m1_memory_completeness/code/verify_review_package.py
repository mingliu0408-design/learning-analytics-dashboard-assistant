"""Standalone standard-library ZIP verifier. Does not load repo/runtime/private data."""
import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

PREFIX='RQ3_REBUILD_M1_MEMORY_COMPLETENESS_REVIEW_2026-09-06'
MANIFEST=PREFIX+'/packaging/REVIEW_MANIFEST.json'


def validate_info(info):
    name=info.filename;p=PurePosixPath(name)
    if not name.startswith(PREFIX+'/') or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('UNSAFE_PATH:'+name)
    if str(p)!=name or name.endswith('/') or any(x in ('','.') for x in name.split('/')):
        raise ValueError('NONCANONICAL_OR_DIRECTORY_MEMBER:'+name)
    kind=stat.S_IFMT(info.external_attr>>16)
    if kind not in (0,stat.S_IFREG):raise ValueError('NONREGULAR_MEMBER:'+name)
    if info.flag_bits & 1:raise ValueError('ENCRYPTED_MEMBER')


def verify(path, expected_bytes=None):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(set(names))!=len(names):raise ValueError('DUPLICATE_MEMBER')
        for i in infos:validate_info(i)
        if z.testzip() is not None:raise ValueError('CRC_FAILURE')
        manifest=json.loads(z.read(MANIFEST))
        entries=manifest['members'];listed=[e['path'] for e in entries]
        if len(set(listed))!=len(listed):raise ValueError('DUPLICATE_MANIFEST_MEMBER')
        if manifest['self_reference_exclusions'] != [MANIFEST]:raise ValueError('UNEXPECTED_SELF_EXCLUSION')
        if set(names)!=set(listed)|{MANIFEST}:raise ValueError('MISSING_OR_EXTRA_MEMBERS')
        for entry in entries:
            b=z.read(entry['path'])
            if len(b)!=entry['bytes'] or hashlib.sha256(b).hexdigest()!=entry['sha256']:
                raise ValueError('MEMBER_BYTES_OR_HASH_MISMATCH:'+entry['path'])
        if expected_bytes is not None:
            if set(expected_bytes)!=set(names):raise ValueError('EXPECTED_MEMBER_SET_MISMATCH')
            for name,b in expected_bytes.items():
                if z.read(name)!=b:raise ValueError('EXPECTED_BYTES_MISMATCH:'+name)
        members=[{'path':i.filename,'bytes':i.file_size,'sha256':hashlib.sha256(z.read(i)).hexdigest()} for i in infos]
    data=Path(path).read_bytes()
    return {'actual_path':str(Path(path).resolve()),'sha256':hashlib.sha256(data).hexdigest(),
        'bytes':len(data),'member_count':len(members),'checks':{
            'crc':'PASS','safe_paths':'PASS','regular_files_no_symlinks':'PASS','unique_names':'PASS',
            'exact_manifest_members':'PASS','sizes_and_hashes':'PASS',
            'expected_committed_and_generated_bytes':'PASS' if expected_bytes is not None else 'NOT_PROVIDED'},
        'members':members,'scope':'Local archive integrity only; no external receipt or research-validity assertion.'}

if __name__=='__main__':
    import sys
    print(json.dumps(verify(sys.argv[1]),indent=2))
