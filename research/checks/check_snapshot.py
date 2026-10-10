#!/usr/bin/env python3
"""Verify the explicit public-file manifest and numerical data/source identities."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "metadata/PUBLIC_FILE_MANIFEST.json").read_text())
    for row in manifest["files"]:
        path = ROOT / row["path"]
        assert not path.is_symlink(), row["path"]
        data = path.read_bytes()
        assert len(data) == row["bytes"], row["path"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]
    print(json.dumps({"verified_files": len(manifest["files"]), "status": "PASS"}))


if __name__ == "__main__":
    main()
