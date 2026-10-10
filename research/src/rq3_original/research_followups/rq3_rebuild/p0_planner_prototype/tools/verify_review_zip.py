"""Standalone CRC, member allowlist, size/hash, path and symlink verification."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

ARCHIVE_ROOT = "RQ3_REBUILD_P0_PLANNER_PROTOTYPE_REVIEW_2026-09-06"
MANIFEST = ARCHIVE_ROOT + "/OUTPUT_MANIFEST.json"


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or "\\" in name or ":" in name or
            any(p in {"", ".", ".."} for p in name.split("/")) or
            path.parts[0] != ARCHIVE_ROOT):
        raise ValueError("Unsafe or out-of-root member: " + name)


def verify(path):
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP members")
        for info in z.infolist():
            safe_name(info.filename)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Directory/symlink members are not allowed")
        if z.testzip() is not None:
            raise ValueError("CRC mismatch")
        manifest = json.loads(z.read(MANIFEST))
        if manifest["hash_scope"] != "Every member except OUTPUT_MANIFEST.json; archive bytes are hashed in the external receipt.":
            raise ValueError("Unexpected manifest scope")
        members = manifest["members"]
        paths = [m["path"] for m in members]
        if len(paths) != len(set(paths)) or MANIFEST in paths:
            raise ValueError("Duplicate or self-referential manifest member")
        if set(names) != set(paths) | {MANIFEST}:
            raise ValueError("Missing/extra archive members")
        for member in members:
            raw = z.read(member["path"])
            if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
                raise ValueError("Size/hash mismatch: " + member["path"])
        return dict(status="PASS", crc="PASS", allowlist="PASS", traversal_and_symlinks="PASS",
                    member_sizes_and_sha256="PASS", file_count=len(names), hashed_member_count=len(members),
                    manifest_self_hash="EXCLUDED_BY_DECLARED_SCOPE")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 -B tools/verify_review_zip.py /absolute/path/to/review.zip")
    path = Path(sys.argv[1])
    print(json.dumps({**verify(path), "path": str(path.resolve()), "bytes": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, indent=2))
