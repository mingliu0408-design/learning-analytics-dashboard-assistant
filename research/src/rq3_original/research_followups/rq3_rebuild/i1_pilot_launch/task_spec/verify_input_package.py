"""Read-only validation of this task ZIP. Uses Python standard library only."""
from pathlib import Path, PurePosixPath
import hashlib,json,stat,sys,zipfile

def verify(path: str) -> dict:
    p=Path(path)
    with zipfile.ZipFile(p) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):
            raise ValueError('Duplicate members')
        for item in z.infolist():
            n=PurePosixPath(item.filename)
            if n.is_absolute() or '..' in n.parts or '\\' in item.filename or stat.S_ISLNK(item.external_attr>>16):
                raise ValueError('Unsafe member: '+item.filename)
        bad=z.testzip()
        if bad is not None: raise ValueError('CRC: '+bad)
        manifest=json.loads(z.read('MANIFEST.json'))
        expected={x['path'] for x in manifest['members']} | {'MANIFEST.json'}
        if set(names)!=expected: raise ValueError('Member set mismatch')
        for x in manifest['members']:
            b=z.read(x['path'])
            if len(b)!=x['bytes'] or hashlib.sha256(b).hexdigest()!=x['sha256']:
                raise ValueError('Hash/size: '+x['path'])
    return dict(path=str(p),status='PASS',sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,members=len(names))

if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('Usage: python verify_input_package.py task.zip')
    print(json.dumps(verify(sys.argv[1]),indent=2))
