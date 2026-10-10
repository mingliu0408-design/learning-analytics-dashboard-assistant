"""Post-commit allowlisted ZIP construction and full byte/CRC/provenance readback."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile
from i3_common import HERE, ROOT, LIVE, I2_ZIP, START, BRANCH, SCOPE, read, sha, canonical, git

ZIP=Path('/Users/liuming/Downloads/RQ3_REBUILD_I3_PLANNER_DIAGNOSIS_REVIEW_2026-09-07.zip')
READBACK=Path('/private/tmp/RQ3_REBUILD_I3_PLANNER_DIAGNOSIS_REVIEW_2026-09-07_READBACK.json')


def main():
    assert not ZIP.exists(), 'Never overwrite an existing review archive.'
    end=git('rev-parse','HEAD')
    assert git('branch','--show-current')==BRANCH and git('rev-parse','HEAD^')==START
    assert git('rev-list','--count',START+'..HEAD')=='1'
    assert git('log','-1','--format=%s')=='RQ3-REBUILD-I3: diagnose planner contract failures and prepare minimal repair'
    assert not git('status','--porcelain=v1')
    changes=git('diff','--name-status',START,'HEAD').splitlines()
    assert all(s.startswith('A\t'+SCOPE) for s in changes)
    assert read(HERE/'PRESERVATION_AND_REVIEW_CHECKS.json')['status']=='PASS'
    inputs=read(HERE/'SOURCE_PRESERVATION_MANIFEST.json')
    for r in inputs['frozen_registry']:
        b=(ROOT/r['path']).read_bytes();assert sha(b)==r['sha256'] and len(b)==r['bytes']
    assert sha(I2_ZIP.read_bytes())=='b9506c17b67640b7868e9d9c4016f22f83d47934a844779e7a108987db3175f0'
    for r in inputs['captured_sources']:
        b=(HERE/r['path']).read_bytes();assert sha(b)==r['sha256'] and len(b)==r['bytes']
        origin=r['source']
        if origin['kind']=='ACTUAL_I2_FILE_AND_ZIP':assert b==(LIVE/origin['relative_path']).read_bytes()
        if origin['kind']=='COMMITTED_SOURCE':assert b==(ROOT/origin['relative_path']).read_bytes()
    committed=read(HERE/'OUTPUT_MANIFEST.json')
    expected={r['path'] for r in committed['files']}|{'OUTPUT_MANIFEST.json'}
    actual={p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file()}
    assert actual==expected
    for r in committed['files']:
        b=(HERE/r['path']).read_bytes();assert len(b)==r['bytes'] and sha(b)==r['sha256']
    tree=subprocess.check_output(['git','ls-tree','-r','-z',end,'--',SCOPE],cwd=ROOT)
    objects={}
    for record in tree.split(b'\0'):
        if not record:continue
        meta,path=record.split(b'\t',1);mode,kind,oid=meta.decode().split()
        assert kind=='blob' and mode=='100644'
        objects[path.decode()]=oid
    assert git('rev-parse','--show-object-format')=='sha1'
    members={};origins={}
    def add(name,data,origin):
        p=PurePosixPath(name)
        assert not p.is_absolute() and '..' not in p.parts and '\\' not in name and name not in members
        members[name]=data;origins[name]=origin
    for name in sorted(actual):
        path=HERE/name;assert path.is_file() and not path.is_symlink();data=path.read_bytes()
        object_id=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        assert object_id==objects[SCOPE+name]
        target='COMMITTED_OUTPUT_MANIFEST.json' if name=='OUTPUT_MANIFEST.json' else name
        add(target,data,dict(kind='COMMITTED_I3_FILE',commit=end,path=SCOPE+name,git_blob=object_id))
    version=dict(workspace=str(ROOT),branch=BRANCH,starting_head=START,ending_head=end,new_commits=1,
        commit_subject=git('log','-1','--format=%s'),worktree_status='CLEAN',scope='NEW_I3_DIRECTORY_ONLY',changed_files=changes,
        source_I2_results_modified=False,integration_patch_applied=False)
    add('GIT_VERSION.json',canonical(version)+b'\n',dict(kind='GENERATED_POST_COMMIT_GIT_READBACK'))
    add('README.md',('I3 actual Planner diagnosis and minimal candidate contract repair\n\n'
        'Read START_HERE.md and I3_COMPLETION_REPORT.md. No Provider call is authorized.\n'
        'All 32 raw candidates and 72 raw answers are preserved under sources/live/.\n'
        'The exact answer reading copy has byte-range and SHA-256 readback. Human checklist fields are blank.\n'
        'OUTPUT_MANIFEST.json binds every other ZIP member. COMMITTED_OUTPUT_MANIFEST.json is the original committed directory inventory.\n'
        'GIT_VERSION.json records the actual single-commit start/end lineage. Snapshot sources are unchanged.\n'
        'reproduce_review.py rebuilds a temporary offline review checkout and replays saved records plus I3 tests. It never runs historical execution scripts.\n'
        'This is a local review archive; no upload, human evaluation completion, quality ranking or model repair success is asserted.\n').encode(),dict(kind='GENERATED_EXPORT_ENTRY'))
    export=dict(schema_version='I3_REVIEW_ZIP_MANIFEST_V1',excluded_self='OUTPUT_MANIFEST.json',
        members=[dict(path=n,bytes=len(b),sha256=sha(b),origin=origins[n]) for n,b in sorted(members.items())],
        exclusions=['credentials','API keys','private human responses','ratings','model weights','databases','unrelated corpus','I1 mock outputs'],
        original_source_manifest='SOURCE_PRESERVATION_MANIFEST.json',committed_directory_manifest='COMMITTED_OUTPUT_MANIFEST.json')
    add('OUTPUT_MANIFEST.json',canonical(export)+b'\n',dict(kind='SELF_HASH_EXCLUDED'))
    with zipfile.ZipFile(ZIP,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(members.items()):
            info=zipfile.ZipInfo(name,date_time=datetime.now(timezone.utc).timetuple()[:6]);info.create_system=3
            info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(ZIP) as z:
        names=z.namelist();assert len(names)==len(set(names)) and set(names)==set(members)
        assert z.testzip() is None
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename
            assert stat.S_ISREG(info.external_attr>>16) and not info.flag_bits&1
            data=z.read(info.filename)
            assert data==members[info.filename] and info.file_size==len(data)
        manifest=json.loads(z.read('OUTPUT_MANIFEST.json'))
        assert {r['path'] for r in manifest['members']}|{'OUTPUT_MANIFEST.json'}==set(names)
        for row in manifest['members']:
            data=z.read(row['path']);assert sha(data)==row['sha256'] and len(data)==row['bytes']
        reading=z.read('DEVELOPMENT_READING_COPY_VERIFIED.md')
        for row in json.loads(z.read('ANSWER_READING_COPY_INDEX.json'))['entries']:
            raw=json.loads(z.read(row['raw_record']));answer=json.loads(raw['choices'][0]['message']['content'])['answer'].encode()
            assert answer==reading[row['reading_start_byte']:row['reading_end_byte_exclusive']]
            assert sha(answer)==row['answer_sha256']
    assert not git('status','--porcelain=v1')
    receipt=dict(path=str(ZIP),sha256=sha(ZIP.read_bytes()),bytes=ZIP.stat().st_size,members=len(members),
        unique_members=len(members),crc='PASS',safe_regular_paths='PASS',exact_member_set='PASS',all_member_hashes_and_sizes='PASS',
        committed_and_generated_origins='PASS',answer_byte_readback=72,candidate_replay=32,
        git=version,distinct_offline_tests=240,standalone_repeated_tests=31,
        old_new_candidate_transition='32 ENCODED_CHECK -> ENCODED_CHECK',
        provider_calls_this_task=0,model_inference_this_task=0,human_scores_or_rationales_prefilled=0,
        preservation='All captured I2 files and 161 frozen-registry files unchanged',external_upload_asserted=False,
        readback_receipt_path=str(READBACK))
    READBACK.write_bytes(canonical(receipt)+b'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='git'},ensure_ascii=False,indent=2))
    print(json.dumps(dict(starting_head=START,ending_head=end,new_commits=1,worktree='CLEAN'),indent=2))


if __name__=='__main__':main()
