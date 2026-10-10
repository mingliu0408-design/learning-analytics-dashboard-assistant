"""Standalone ZIP safety, CRC, allowlist, size and SHA-256 verification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

def digest(data):
    return hashlib.sha256(data).hexdigest()

def safe_members(z):
    infos = z.infolist()
    names = [i.filename for i in infos]
    assert len(names) == len(set(names)), "DUPLICATE_MEMBERS"
    for i in infos:
        p = PurePosixPath(i.filename)
        assert i.filename and not p.is_absolute() and ".." not in p.parts and "\\" not in i.filename
        assert i.filename == p.as_posix() and not i.is_dir(), "UNSAFE_OR_DIRECTORY_MEMBER"
        mode = i.external_attr >> 16
        assert not stat.S_ISLNK(mode), "SYMLINK_MEMBER"
        assert stat.S_IFMT(mode) in (0, stat.S_IFREG), "NON_REGULAR_MEMBER"
    assert z.testzip() is None, "CRC_FAILURE"
    return names

def verify(path):
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        names = safe_members(z)
        roots = {PurePosixPath(n).parts[0] for n in names}
        assert len(roots) == 1, "MULTIPLE_ROOTS"
        root = next(iter(roots))
        prefix = root + "/"
        manifest_name = prefix + "packaging/REVIEW_MANIFEST.json"
        receipt_name = prefix + "packaging/PACKAGING_VERIFICATION.json"
        manifest_bytes = z.read(manifest_name)
        manifest = json.loads(manifest_bytes)
        entries = manifest["members"]
        listed = {prefix + e["path"] for e in entries}
        assert len(listed) == len(entries), "DUPLICATE_MANIFEST_ENTRIES"
        assert set(names) == listed | {manifest_name, receipt_name}, "MISSING_OR_EXTRA_MEMBER"
        for e in entries:
            data = z.read(prefix + e["path"])
            assert len(data) == e["bytes"] and digest(data) == e["sha256"], e["path"]
        receipt = json.loads(z.read(receipt_name))
        assert receipt["review_manifest_sha256"] == digest(manifest_bytes)
        assert receipt["verification_status"] == "VERIFIED_BEFORE_RECEIPT_INSERTION"
        assert receipt["verified_member_count_before_receipt"] == len(names) - 1
        final_hashes = [{"path": n, "bytes": len(z.read(n)), "sha256": digest(z.read(n))} for n in names]
    return {"zip_path": str(path.resolve()), "zip_sha256": digest(path.read_bytes()),
        "zip_bytes": path.stat().st_size, "member_count": len(names), "crc": "PASS",
        "traversal_symlink_duplicate_check": "PASS", "missing_extra_members": "NONE",
        "payload_manifest_size_hashes": "PASS", "final_member_hashes": final_hashes}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()
    result = verify(args.zip)
    print(json.dumps({k: v for k, v in result.items() if k != "final_member_hashes"}, indent=2))
