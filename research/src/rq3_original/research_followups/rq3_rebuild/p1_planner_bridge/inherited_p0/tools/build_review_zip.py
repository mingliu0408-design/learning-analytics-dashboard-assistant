"""Export exactly committed task bytes after the sole authorized commit.

Packaging metadata is explicitly post-commit. No git writes, archive overwrite,
network, private data discovery, or repository-wide tests are performed here.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from verify_review_zip import ARCHIVE_ROOT, MANIFEST, safe_name, verify

BASE = "595b949185ad1b97cdbb9b0fdaeb9804aff7c45c"
BRANCH = "research/rq3-rebuild-p0-planner-prototype"
SUBTREE = "research_followups/rq3_rebuild/p0_planner_prototype"
PROJECT = Path("/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-p0-planner-prototype")
DESTINATION = Path("/Users/liuming/Downloads/RQ3_REBUILD_P0_PLANNER_PROTOTYPE_REVIEW_2026-09-06.zip")
SUBJECT = "RQ3-REBUILD-P0: prototype evidence-grounded planning contracts and offline checks"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=PROJECT)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def archive_bytes(files):
    buf = io.BytesIO()
    now = datetime.now(timezone.utc)
    date = (now.year, now.month, now.day, now.hour, now.minute, now.second)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in sorted(files.items()):
            safe_name(name)
            info = zipfile.ZipInfo(name, date_time=date)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, raw)
    return buf.getvalue()


def main():
    destination = Path(sys.argv[1]) if len(sys.argv) == 2 else DESTINATION
    if destination != DESTINATION:
        raise SystemExit("This exporter is restricted to the user-authorized exact Downloads path.")
    receipt_path = destination.with_suffix(".verification.json")
    if destination.exists() or receipt_path.exists():
        raise SystemExit("Existing export/receipt detected; no overwrite. Inspect and report before proceeding.")
    assert git("rev-parse", "--show-toplevel").decode().strip() == str(PROJECT)
    assert git("branch", "--show-current").decode().strip() == BRANCH
    end = git("rev-parse", "HEAD").decode().strip()
    assert git("rev-parse", "HEAD^").decode().strip() == BASE
    assert git("rev-list", "--count", BASE + "..HEAD").decode().strip() == "1"
    assert git("log", "-1", "--format=%s").decode().strip() == SUBJECT
    assert not git("status", "--porcelain=v1", "--untracked-files=all").strip()
    changes = [line.split("\t") for line in git("diff", "--name-status", BASE, end).decode().splitlines()]
    assert changes and all(kind == "A" and path.startswith(SUBTREE + "/") for kind, path in changes)
    files, committed = {}, []
    for _, path in changes:
        raw = git("show", end + ":" + path)
        assert (PROJECT / path).read_bytes() == raw
        rel = path.removeprefix(SUBTREE + "/")
        name = ARCHIVE_ROOT + "/" + rel
        files[name] = raw
        committed.append(name)
    git_receipt = dict(kind="POST_COMMIT_PACKAGING_METADATA", generated_at_utc=datetime.now(timezone.utc).isoformat(),
                       starting_head=BASE, ending_head=end, branch=BRANCH, starting_status="CLEAN", ending_status="CLEAN",
                       task_commit_count=1, commit_subject=SUBJECT, commit_time_utc=datetime.fromisoformat(git("show", "-s", "--format=%cI", end).decode().strip()).astimezone(timezone.utc).isoformat(),
                       changed_files=[dict(change=k, path=p) for k,p in changes],
                       changed_path_scope=SUBTREE + "/", existing_tracked_files_modified=0,
                       committed_member_count=len(committed), committed_bytes_read_from="git show END:path, compared with clean working-tree bytes")
    files[ARCHIVE_ROOT + "/GIT_RECEIPT.json"] = encoded(git_receipt)
    files[ARCHIVE_ROOT + "/REVIEW_DIFF.patch"] = git("diff", "--no-ext-diff", "--no-textconv", "--binary", BASE, end, "--", SUBTREE)
    # A real zip readback of all payload members before metadata sealing.
    payload_zip = archive_bytes(files)
    with zipfile.ZipFile(io.BytesIO(payload_zip)) as z:
        assert z.testzip() is None and set(z.namelist()) == set(files)
        assert all(z.read(name) == raw for name,raw in files.items())
    files[ARCHIVE_ROOT + "/PACKAGING_VERIFICATION.json"] = encoded(dict(
        kind="POST_COMMIT_PACKAGING_METADATA", verified_at_utc=datetime.now(timezone.utc).isoformat(),
        payload_readback="PASS", payload_crc="PASS", payload_member_hashes="PASS",
        payload_verification_scope="All committed members plus GIT_RECEIPT.json and REVIEW_DIFF.patch read back from an in-memory ZIP before sealing packaging metadata.",
        payload_member_count=len(files), committed_bytes_match="PASS",
        final_zip_verification="Final on-disk archive is reopened and every manifest member is verified after writing. Results and whole-ZIP SHA-256 are in the adjacent .verification.json external receipt, to avoid circular hashes.",
        standalone_recheck="python3 -B tools/verify_review_zip.py /absolute/path/to/review.zip"))
    output_manifest = dict(kind="POST_COMMIT_PACKAGING_METADATA", task_id="RQ3-REBUILD-P0",
        hash_scope="Every member except OUTPUT_MANIFEST.json; archive bytes are hashed in the external receipt.",
        allowlist_source="Only added task paths in the sole BASE..END commit plus three named packaging metadata files.",
        members=[dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                      origin="EXACT_COMMITTED_BYTES" if name in committed else "POST_COMMIT_PACKAGING_METADATA") for name,raw in sorted(files.items())])
    files[MANIFEST] = encoded(output_manifest)
    final_bytes = archive_bytes(files)
    verify(io.BytesIO(final_bytes))
    with destination.open("xb") as f:
        f.write(final_bytes)
    verified = verify(destination)
    readback = destination.read_bytes()
    assert readback == final_bytes
    assert git("rev-parse", "HEAD").decode().strip() == end
    assert git("branch", "--show-current").decode().strip() == BRANCH
    receipt = dict(**verified, verified_at_utc=datetime.now(timezone.utc).isoformat(), actual_zip_path=str(destination),
                   sha256=hashlib.sha256(readback).hexdigest(), bytes=len(readback), starting_head=BASE, ending_head=end,
                   task_commit_count=1, git_status_after_export=git("status", "--porcelain=v1", "--untracked-files=all").decode(),
                   provenance="Unsigned locally generated verification receipt; no external upload or receipt claimed.")
    with receipt_path.open("xb") as f:
        f.write(encoded(receipt))
    print(json.dumps({**receipt, "external_verification_receipt":str(receipt_path)}, indent=2))


if __name__ == "__main__":
    main()
