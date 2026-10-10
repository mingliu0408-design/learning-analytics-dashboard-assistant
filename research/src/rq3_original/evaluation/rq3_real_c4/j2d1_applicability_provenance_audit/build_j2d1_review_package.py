#!/usr/bin/env python3
"""Build the strict allowlisted RQ3-REAL-C4-J2D1 review ZIP."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from validate_j2d1_artifacts import HMAC_KEY, PACKAGE_FILES, run_checks


TARGET = Path(
    "/Users/liuming/Downloads/"
    "RQ3_REAL_J2D1_APPLICABILITY_PROVENANCE_REVIEW_2026-09-02.zip"
)
ROOT_NAME = "RQ3_REAL_J2D1_APPLICABILITY_PROVENANCE_REVIEW_2026-09-02"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if TARGET.exists():
        raise RuntimeError(f"refusing to overwrite existing review ZIP: {TARGET}")
    preflight = run_checks()
    if any(row["status"] != "PASS" for row in preflight):
        raise RuntimeError("artifact preflight did not pass")
    missing = sorted(name for name in PACKAGE_FILES if not (HERE / name).is_file())
    if missing:
        raise RuntimeError(f"missing allowlisted package files: {missing}")

    descriptor = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name in sorted(PACKAGE_FILES):
                    payload = (HERE / name).read_bytes()
                    info = zipfile.ZipInfo(f"{ROOT_NAME}/{name}", (2026, 9, 2, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    info.create_system = 3
                    archive.writestr(info, payload)
    except BaseException:
        if TARGET.exists():
            TARGET.unlink()
        raise

    postflight = run_checks(TARGET)
    if any(row["status"] != "PASS" for row in postflight):
        raise RuntimeError("review ZIP postflight did not pass")
    key = HMAC_KEY.read_bytes()
    if key in TARGET.read_bytes():
        raise RuntimeError("raw HMAC key bytes found in review ZIP")
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": str(TARGET),
                "sha256": sha256_file(TARGET),
                "byte_count": TARGET.stat().st_size,
                "member_count": len(PACKAGE_FILES),
                "postflight_checks_passed": len(postflight),
                "postflight_checks_failed": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
