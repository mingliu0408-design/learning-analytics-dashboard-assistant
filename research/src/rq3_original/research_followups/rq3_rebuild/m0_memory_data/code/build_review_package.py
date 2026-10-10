"""Package exact committed owned bytes; one task commit, post-commit metadata only."""
from __future__ import annotations
import io
import json
from pathlib import Path
import stat
import subprocess
import zipfile
from common import OWNED, BASE_HEAD, SUBTREE, object_sha, write_json, utc, sha
from verify_review_zip import verify, safe_members, digest

TITLE = "RQ3_REBUILD_M0_MEMORY_DATA_REVIEW_2026-09-06"
DESTINATION = Path("/Users/liuming/Downloads") / (TITLE + ".zip")

def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()

def write_archive(handle, files):
    with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(TITLE + "/" + name)
            # ZIP timestamps are packaging metadata, never synthetic event dates.
            from datetime import datetime, timezone
            info.date_time = datetime.now(timezone.utc).timetuple()[:6]
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)

def main():
    repo = OWNED.parents[2]
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])
    end = git("rev-parse", "HEAD").decode().strip()
    branch = git("branch", "--show-current").decode().strip()
    assert branch == "research/rq3-rebuild-m0-memory-data"
    assert git("status", "--porcelain=v1").decode() == "", "TREE_MUST_BE_CLEAN"
    assert git("rev-list", "--count", BASE_HEAD + ".." + end).decode().strip() == "1"
    assert git("rev-parse", end + "^").decode().strip() == BASE_HEAD
    assert git("log", "-1", "--format=%s").decode().strip() == "RQ3-REBUILD-M0: prepare memory episodes and isolated persistent-state harness"
    changed = git("diff", "--name-status", BASE_HEAD, end).decode().splitlines()
    assert changed and all(x.startswith("A\t" + SUBTREE + "/") for x in changed), "SCOPE_VIOLATION"
    owned = git("ls-tree", "-r", "--name-only", end, "--", SUBTREE).decode().splitlines()
    payload = {p[len(SUBTREE) + 1:]: git("show", end + ":" + p) for p in owned}
    forbidden = {".sqlite", ".db", ".zip", ".pyc", ".safetensors"}
    assert all(Path(p).suffix not in forbidden for p in payload)
    output = json.loads(payload["OUTPUT_MANIFEST.json"])
    assert {e["path"] for e in output["members"]} == set(payload) - {"OUTPUT_MANIFEST.json"}
    for entry in output["members"]:
        data = payload[entry["path"]]
        assert len(data) == entry["bytes"] and digest(data) == entry["sha256"]
    receipt = {"kind": "POST_COMMIT_PACKAGING_METADATA", "generated_utc": utc(),
        "repository": str(repo), "branch": branch, "starting_head": BASE_HEAD, "ending_head": end,
        "commit_count": 1, "commit_subject": git("log", "-1", "--format=%s").decode().strip(),
        "parent_head": git("rev-parse", end + "^").decode().strip(), "tree_status_before_packaging": "CLEAN",
        "changed_files": changed, "modified_existing_files": [], "committed_member_count": len(payload),
        "committed_bytes_source": "git show ending_head:repository_relative_path",
        "metadata_note": "This receipt, diff, review manifest and packaging verification were generated after the single commit. No ending-HEAD self-reference is embedded in that commit."}
    payload["packaging/GIT_RECEIPT.json"] = json_bytes(receipt)
    payload["packaging/REVIEW.diff"] = git("diff", "--no-ext-diff", "--no-renames", BASE_HEAD, end, "--", SUBTREE)
    manifest = {"kind": "POST_COMMIT_REVIEW_ALLOWLIST", "generated_utc": utc(), "root": TITLE,
        "scope": "All committed task files plus Git receipt/diff; excludes this manifest and PACKAGING_VERIFICATION.json to avoid self-reference. ZIP itself and external final ZIP_READBACK_RECEIPT.json are not members.",
        "members": [{"path": p, "bytes": len(b), "sha256": digest(b),
            "origin": "POST_COMMIT_METADATA" if p.startswith("packaging/") else "EXACT_COMMITTED_BYTES"}
            for p, b in sorted(payload.items())]}
    manifest_bytes = json_bytes(manifest)
    payload["packaging/REVIEW_MANIFEST.json"] = manifest_bytes
    # Actually create/reopen an archive for the scope recorded by its internal receipt.
    provisional = io.BytesIO()
    write_archive(provisional, payload)
    provisional.seek(0)
    with zipfile.ZipFile(provisional) as z:
        names = safe_members(z)
        assert set(names) == {TITLE + "/" + p for p in payload}
        for p, b in payload.items(): assert z.read(TITLE + "/" + p) == b
    verification = {"kind": "POST_COMMIT_PACKAGING_METADATA", "execution_utc": utc(),
        "verification_status": "VERIFIED_BEFORE_RECEIPT_INSERTION",
        "scope": "Reopened in-memory ZIP, all payload members and manifest, excluding this receipt itself. Final on-disk archive is then independently reopened and verified, including this receipt, in the external ZIP_READBACK_RECEIPT.json.",
        "verified_member_count_before_receipt": len(payload), "review_manifest_sha256": digest(manifest_bytes),
        "crc": "PASS", "member_bytes_vs_committed_or_generated_sources": "PASS",
        "allowlist_missing_extra_traversal_symlink_checks": "PASS"}
    payload["packaging/PACKAGING_VERIFICATION.json"] = json_bytes(verification)
    dest = DESTINATION
    version = 2
    while dest.exists():
        dest = DESTINATION.with_name(TITLE + f"_v{version}.zip"); version += 1
    with dest.open("xb") as handle: write_archive(handle, payload)
    final = verify(dest)
    with zipfile.ZipFile(dest) as z:
        for p, b in payload.items(): assert z.read(TITLE + "/" + p) == b
    final.update(execution_utc=utc(), committed_payload_matches_git="PASS",
                 all_final_member_bytes_vs_expected="PASS", starting_head=BASE_HEAD, ending_head=end)
    metadata = OWNED / "packaging"
    metadata.mkdir(exist_ok=False)
    for p, b in payload.items():
        if p.startswith("packaging/"): (metadata / Path(p).name).write_bytes(b)
    write_json(metadata / "ZIP_READBACK_RECEIPT.json", final)
    assert git("status", "--porcelain=v1").decode() == ""
    print(json.dumps({k: v for k, v in final.items() if k != "final_member_hashes"}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
