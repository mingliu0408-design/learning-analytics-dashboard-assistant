"""Export committed R2 allowlist only; reopen, verify every byte, store SHA externally."""
from common import *
from pathlib import PurePosixPath
import stat
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ARCHIVE=Path('/Users/liuming/Downloads/RQ3_REBUILD_R2_CANDIDATE_REFERENCE_REVIEW_2026-09-06.zip')

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'

def verify_archive(path, expected):
    with ZipFile(path) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        assert z.testzip() is None, 'CRC_FAILURE'
        assert len(names)==len(set(names)), 'DUPLICATE_MEMBER'
        assert set(names)==set(expected), 'EXACT_MEMBER_SET_MISMATCH'
        for info in infos:
            p=PurePosixPath(info.filename)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in info.filename and not info.is_dir()
            assert stat.S_ISREG(info.external_attr >> 16) and not stat.S_ISLNK(info.external_attr >> 16)
            data=z.read(info.filename)
            assert len(data)==info.file_size==len(expected[info.filename])
            assert digest(data)==digest(expected[info.filename])
        manifest=json.loads(z.read('REVIEW_MANIFEST.json'))
        assert manifest['excluded_self']=='REVIEW_MANIFEST.json'
        assert {m['path'] for m in manifest['members']}==set(names)-{'REVIEW_MANIFEST.json'}
        for m in manifest['members']:
            data=z.read(m['path'])
            assert len(data)==m['bytes'] and digest(data)==m['sha256']
        assert json.loads(z.read('EXPORT_ALLOWLIST.json'))['members']==sorted(names)
    return {'crc_passed':True,'path_confinement_passed':True,'regular_files_only':True,
            'no_symlinks':True,'no_duplicate_names':True,'exact_member_set_passed':True,
            'member_lengths_and_sha256_passed':True,'members':len(expected)}

def main():
    assert not ARCHIVE.exists(), 'EXISTING_REVIEW_ZIP_NOT_OVERWRITTEN'
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()
    assert branch==BRANCH
    assert not subprocess.check_output(['git','status','--porcelain=v1'],text=True).strip(), 'CLEAN_DELIVERY_TREE_REQUIRED'
    commits=subprocess.check_output(['git','rev-list',BASE+'..'+head],text=True).splitlines()
    assert commits==[head]
    parents=subprocess.check_output(['git','rev-list','--parents','-n','1',head],text=True).strip().split()[1:]
    assert parents==[BASE], 'ONE_TASK_COMMIT_NO_INTEGRATION_CHERRY_PICKS'
    prefix=str(OUT.relative_to(ROOT))+'/'
    changed=subprocess.check_output(['git','diff','--name-status',BASE,head],text=True).splitlines()
    assert all(line.startswith('A\t'+prefix) for line in changed), 'ONLY_NEW_AUTHORIZED_TASK_FILES'
    paths=subprocess.check_output(['git','ls-files',str(OUT.relative_to(ROOT))],text=True).splitlines()
    payload={}
    for relative in paths:
        source=ROOT/relative;name=source.relative_to(OUT).as_posix()
        assert not source.is_symlink()
        assert not any(part in ('local_artifacts','__pycache__','.git','.venv','models') for part in PurePosixPath(name).parts)
        assert not source.suffix.lower() in ('.pdf','.doc','.docx','.bin','.safetensors','.npy','.npz','.sqlite','.db')
        b=subprocess.check_output(['git','show',f'{head}:{relative}'])
        assert digest(b)==file_hash(source)
        payload[name]=b
    outputs=json.loads(payload['OUTPUT_MANIFEST.json'])
    assert {m['path'] for m in outputs['members']}==set(payload)-{'OUTPUT_MANIFEST.json'}
    for m in outputs['members']:
        assert digest(payload[m['path']])==m['sha256'] and len(payload[m['path']])==m['bytes']
    assert json.loads(payload['DELIVERY_VALIDATION.json'])['passed']
    handoff={'task':'RQ3-REBUILD-R2_HUMAN_ALIGNED','cwd':str(ROOT),'branch':branch,
             'start_head':BASE,'end_head':head,'end_commit_parents':parents,'task_commit_count':1,
             'commit_subject':subprocess.check_output(['git','log','-1','--format=%s'],text=True).strip(),
             'tracked_tree_clean_before_export':True,'changed_files':changed,
             'inherited_sources_modified':False,'integration_cherry_picks':0,
             'status':'READY_FOR_RETRIEVER_DEV_SELECTION_WITH_HUMAN_REFERENCE_LIMITS',
             'receipt_created_after_commit':True}
    payload['GIT_HANDOFF.json']=encoded(handoff)
    payload['IMPLEMENTATION.diff']=subprocess.check_output(['git','diff','--no-ext-diff','--binary',BASE,head,'--',str(OUT.relative_to(ROOT))])
    members=sorted(set(payload)|{'EXPORT_ALLOWLIST.json','REVIEW_MANIFEST.json'})
    payload['EXPORT_ALLOWLIST.json']=encoded({'members':members,
        'excluded':['local raw query/passage text and reconstructable token arrays','models and environments',
                    'databases, secrets and private rows','complete copyrighted course materials',
                    'raw historical response ratings','whole repository and Git history'],
        'synthetic_fixtures':'Unit tests are synthetic; old 15-case references remain exposed development.'})
    payload['REVIEW_MANIFEST.json']=encoded({'excluded_self':'REVIEW_MANIFEST.json',
        'archive_sha256':'Stored externally in local_artifacts/ARCHIVE_RECEIPT.json; never self-hashed.',
        'members':[{'path':n,'bytes':len(b),'sha256':digest(b)} for n,b in sorted(payload.items())]})
    # Build in allowed ignored task-local storage, inspect it before the Downloads write.
    staged=LOCAL/'review_build.zip';LOCAL.mkdir(exist_ok=True)
    with ZipFile(staged,'x',compression=ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(payload.items()):
            info=ZipInfo(name,date_time=(2026,9,7,0,0,0));info.create_system=3
            info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=ZIP_DEFLATED
            z.writestr(info,data,compress_type=ZIP_DEFLATED,compresslevel=9)
    verify_archive(staged,payload)
    with staged.open('rb') as source,ARCHIVE.open('xb') as target:
        for b in iter(lambda:source.read(1024*1024),b''):target.write(b)
        target.flush();os.fsync(target.fileno())
    checked=verify_archive(ARCHIVE,payload)
    result={**checked,'path':str(ARCHIVE),'bytes':ARCHIVE.stat().st_size,'sha256':file_hash(ARCHIVE),
            'start_head':BASE,'end_head':head,'test_count':29,'artifact_check_count':23,
            'new_pair_scores':870,'human_scores':0,'judge_calls':0,'generation_calls':0,
            'readback_completed_utc':now(),'local_delivery_only':True}
    write_json(LOCAL/'ARCHIVE_RECEIPT.json',result,exclusive=True)
    write_json(LOCAL/'GIT_HANDOFF.json',handoff,exclusive=True)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
