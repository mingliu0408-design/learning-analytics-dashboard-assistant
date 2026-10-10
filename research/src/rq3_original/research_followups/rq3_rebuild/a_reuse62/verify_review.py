"""Standalone ZIP allowlist, CRC, digest, roster and blank human-field verification."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
import csv
import io
import json
import sys
import zipfile

def verify(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        assert len(names)==len(set(names)), 'DUPLICATE_MEMBER'
        assert z.testzip() is None, 'CRC'
        assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and '\\' not in n for n in names),'UNSAFE_PATH'
        assert all((i.external_attr>>16)&0o170000!=0o120000 for i in z.infolist()),'SYMLINK_MEMBER'
        manifest=json.loads(z.read('PACKAGE_MANIFEST.json'))
        assert set(names)=={r['member'] for r in manifest['files']}|{'PACKAGE_MANIFEST.json'},'ALLOWLIST'
        for r in manifest['files']:
            b=z.read(r['member']);assert len(b)==r['bytes'] and sha256(b).hexdigest()==r['sha256'],r['member']
        original=z.read('originals/unified_benchmark_scenarios.jsonl')
        assert sha256(original).hexdigest()=='2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4'
        raw=[json.loads(l) for l in original.splitlines() if l.strip()]
        runtime=[json.loads(l) for l in z.read('runtime/TASKS_62.jsonl').splitlines() if l.strip()]
        assert len(raw)==len(runtime)==62 and [r['task_id'] for r in runtime]==[f'U{i:03}' for i in range(1,63)]
        for a,b in zip(raw,runtime):
            assert a['student_query']==b['query'] and a['page']==b['page']
            assert set(b)=={'task_id','query','page','history'}
            assert len(a['conversation_history'])==len(b['history'])
        for name,count,fields in [('human/BLANK_RATINGS_2976.csv',2976,['score','rationale','rater','signature','response_id']),
            ('human/COMMON_APPLICABILITY_496.csv',496,['applicable','reason','reviewer','signature'])]:
            rows=list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))))
            assert len(rows)==count and all(not r[k] for r in rows for k in fields),'FILLED_HUMAN_FIELDS'
        maps=list(csv.DictReader(io.StringIO(z.read('COVERAGE_INPUT_MAP_62.csv').decode('utf-8-sig'))))
        assert len(maps)==62 and all(r['latest_run_status']=='NOT_RUN' and r['actual_latest_decision']=='' for r in maps)
        assert not any('local_private/' in n or '/live/' in n or 'node_modules' in n or n.endswith(('.sqlite','.pkl','.env')) for n in names)
        receipt=json.loads(z.read('GIT_RECEIPT.json'))
    p=Path(path)
    return dict(path=str(p.resolve()),sha256=sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,members=len(names),
        crc='PASS',member_sha256='PASS',allowlist='PASS',roster62='PASS',blank_human_fields='PASS',
        git_start=receipt['start_head'],git_head=receipt['head'],provider_calls=0,readable_tasks=62,complete_source_bound_tasks=0)

if __name__=='__main__':print(json.dumps(verify(sys.argv[1]),ensure_ascii=False,indent=2))
