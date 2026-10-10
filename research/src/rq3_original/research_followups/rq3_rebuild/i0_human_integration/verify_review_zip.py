"""Standalone read-only review ZIP verification; Python standard library only."""
from pathlib import PurePosixPath, Path
from hashlib import sha256
import json
import stat
import sys
from zipfile import ZipFile

MANIFEST='REVIEW_MANIFEST.json'


def verify(path):
    path=Path(path)
    with ZipFile(path) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        assert len(names)==len(set(names)), 'DUPLICATE_MEMBERS'
        assert len(names)<=4096 and sum(i.file_size for i in infos)<=256*1024*1024,'ARCHIVE_LIMIT'
        for i in infos:
            n=i.filename;p=PurePosixPath(n)
            assert not p.is_absolute() and not any(x in ('','..','.') for x in n.split('/')),'PATH_CONFINEMENT'
            assert '\\' not in n and ':' not in n and not i.is_dir(),'UNSAFE_MEMBER_PATH'
            assert not stat.S_ISLNK(i.external_attr>>16),'SYMLINK_MEMBER'
            assert stat.S_IFMT(i.external_attr>>16) in (0,stat.S_IFREG),'NONREGULAR_MEMBER'
            assert i.file_size<=64*1024*1024,'MEMBER_LIMIT'
        assert z.testzip() is None,'CRC_ERROR'
        m=json.loads(z.read(MANIFEST))
        assert m['excluded_self']==MANIFEST and m['archive_sha256_stored_externally'] is True
        expected={r['path']:r for r in m['members']}
        assert len(expected)==len(m['members']) and set(expected)|{MANIFEST}==set(names),'EXACT_MEMBER_SET'
        verified=[]
        for n,r in expected.items():
            data=z.read(n)
            assert len(data)==r['bytes'] and sha256(data).hexdigest()==r['sha256'], 'MEMBER_HASH_OR_LENGTH: '+n
            verified.append(dict(path=n,bytes=len(data),sha256=r['sha256']))
    return dict(path=str(path.resolve()),bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest(),
        members=len(names),manifest_covered_members=len(verified),CRC='PASS',path_confinement='PASS',
        symlinks=0,duplicate_names=0,exact_member_set='PASS',member_lengths_and_hashes='PASS',
        self_exclusion='REVIEW_MANIFEST.json excludes its own hash; archive hash is external.',
        verified_members=verified)


if __name__=='__main__':
    result=verify(sys.argv[1]);print(json.dumps({k:v for k,v in result.items() if k!='verified_members'},indent=2))
