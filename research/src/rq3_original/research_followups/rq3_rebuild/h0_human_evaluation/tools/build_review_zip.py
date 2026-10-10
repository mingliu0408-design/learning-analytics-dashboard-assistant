"""Export this committed H0 task only; create post-commit receipt without self-hash."""
import argparse
import datetime
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path
from h0 import ROOT, canonical_bytes, digest, read_json, write_json
from validate import artifacts
from verify_review_zip import verify

START='a15155b687264f235980836912f2e351bf428c9c'
BRANCH='research/rq3-rebuild-h0-human-evaluation'
PREFIX='research_followups/rq3_rebuild/h0_human_evaluation/'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT.parents[2])


def build(output):
    output=Path(output)
    if output.exists():raise ValueError('refuse to overwrite existing review ZIP')
    end=git('rev-parse','HEAD').decode().strip()
    if git('branch','--show-current').decode().strip()!=BRANCH:raise ValueError('branch mismatch')
    if git('rev-parse','HEAD^').decode().strip()!=START:raise ValueError('single task-specific commit must directly follow starting HEAD')
    if git('status','--porcelain=v1').strip():raise ValueError('working tree must be clean before export')
    changes=git('diff','--name-status',START,end).decode().splitlines()
    if not changes or any(not line.startswith('A\t'+PREFIX) for line in changes):raise ValueError('changed-file scope not new H0 files only')
    errors=artifacts()
    if errors:raise ValueError('; '.join(errors))
    tracked=git('ls-tree','-r','--name-only',end,'--',PREFIX).decode().splitlines()
    allowed_dirs={'input','evidence','templates','schemas','tools','tests','ui','test_results','blank_packet'}
    files={}
    for name in tracked:
        if not name.startswith(PREFIX):raise ValueError('tracked file outside H0 prefix')
        rel=name[len(PREFIX):];path=ROOT/rel
        if '/' in rel and rel.split('/')[0] not in allowed_dirs:raise ValueError('unapproved export directory '+rel)
        if path.is_symlink() or not path.is_file():raise ValueError('nonregular source file')
        if any(x in Path(rel).parts for x in ('__pycache__','.venv','node_modules','private_data','models')):raise ValueError('forbidden export component')
        files[rel]=path.read_bytes()
    if not files or 'START_HERE.md' not in files:raise ValueError('empty or incorrect tracked export set')
    metadata=ROOT/'delivery_metadata';metadata.mkdir(exist_ok=True)
    receipt={'task':'RQ3-REBUILD-H0','status':'READY_FOR_HUMAN_PROTOCOL_AND_NEW_TASK_APPROVAL','start_head':START,'end_head':end,'branch':BRANCH,'commit_subject':git('log','-1','--format=%s').decode().strip(),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope_check':'only new files under '+PREFIX,'working_tree_clean_at_export':True,'commit_count':1,'commit_self_hash_policy':'receipt created after commit and intentionally not committed; no self hash required','source_packet_sha256':read_json(ROOT/'PREFLIGHT.json')['packet_sha256'],'generation_calls':0,'rating_calls':0,'actual_human_ratings':0,'historical_ratings_copied':False,'archive_hash_policy':'stored outside ZIP after archive creation'}
    write_json(metadata/'COMMIT_RECEIPT.json',receipt)
    files['COMMIT_RECEIPT.json']=(metadata/'COMMIT_RECEIPT.json').read_bytes()
    # Text implementation delta; original PDF/image bytes already supplied by their manifest entries.
    paths=[PREFIX+rel for rel in files if rel.split('/')[0] in {'tools','ui','tests','schemas','templates'} or ('/' not in rel and rel.endswith('.md'))]
    patch=git('diff','--no-ext-diff',START,end,'--',*paths)
    (metadata/'IMPLEMENTATION.patch').write_bytes(patch);files['IMPLEMENTATION.patch']=patch
    names=sorted([*files,'EXPORT_ALLOWLIST.json','OUTPUT_MANIFEST.json'])
    allow={'members':names,'basis':'explicit committed H0 file set plus named post-commit metadata','excluded':'whole repository, models, environments, databases, private source rows, secrets, full course materials, historical ratings','synthetic_fixture_policy':'tests/ contains clearly marked artificial program fixtures; human packet contains no responses or ratings','self_reference_policy':'allowlist includes its own name only, never its own hash'}
    files['EXPORT_ALLOWLIST.json']=(json.dumps(allow,ensure_ascii=False,indent=2)+'\n').encode()
    manifest={'excluded_self':'OUTPUT_MANIFEST.json','archive_sha256':'stored externally, not in this manifest','members':[{'path':name,'bytes':len(data),'sha256':digest(data)} for name,data in sorted(files.items())]}
    files['OUTPUT_MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    write_json(metadata/'OUTPUT_MANIFEST.json',manifest)
    # Exclusive creation: do not replace an existing delivery.
    try:
        with output.open('xb') as f:
            with zipfile.ZipFile(f,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                for name,data in sorted(files.items()):
                    info=zipfile.ZipInfo(name, date_time=(2026,9,6,0,0,0));info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16;info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
        result=verify(output)
    except Exception:
        # Preserve failed artifact; do not silently repair or overwrite it.
        raise
    result.update(start_head=START,end_head=end,commit_count=1)
    write_json(metadata/'ARCHIVE_VERIFICATION.json',result)
    (metadata/'ARCHIVE_SHA256.txt').write_text(result['sha256']+'  '+str(output)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(build(a.output),indent=2))
