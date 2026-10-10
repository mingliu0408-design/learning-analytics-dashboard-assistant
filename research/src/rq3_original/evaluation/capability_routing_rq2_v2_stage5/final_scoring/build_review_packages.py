"""Build and independently audit the authorized Stage 5E review ZIPs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Mapping
import zipfile

from .constants import (
    BINDING_PATH,
    FINAL_SCORING_DIR,
    INTERNAL_REVIEW_ZIP,
    PROJECT_ROOT,
    RQ3_HANDOFF_ZIP,
    STAGE4_ROOT,
)
from .scoring import canonical_json_bytes, sha256_bytes, sha256_file
from .validate_final_scoring import validate_outputs


FIXED_ZIP_TIME = (2026, 8, 31, 0, 0, 0)


def _zip_bytes(members: Mapping[str, bytes]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members, key=lambda value: value.encode("utf-8")):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)


def _audit(path: Path, members: Mapping[str, bytes]) -> dict[str, object]:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if names != sorted(members, key=lambda value: value.encode("utf-8")):
            raise RuntimeError(f"ZIP member order/allowlist differs: {path}")
        if archive.testzip() is not None:
            raise RuntimeError(f"ZIP CRC failed: {path}")
        for name, expected in members.items():
            if archive.read(name) != expected:
                raise RuntimeError(f"ZIP member bytes differ: {path} {name}")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "member_count": len(members),
        "crc_and_member_bytes_verified": True,
    }


def build_packages() -> dict[str, object]:
    validation = validate_outputs(recompute_bootstrap=True)
    if validation["status"] != "PASS":
        raise RuntimeError("Stage 5E outputs did not validate")
    if subprocess.check_output(
        ["git", "status", "--short"], cwd=PROJECT_ROOT, text=True
    ).strip():
        raise RuntimeError("review packages require the committed clean Stage 5E tree")
    if INTERNAL_REVIEW_ZIP.exists() or RQ3_HANDOFF_ZIP.exists():
        raise RuntimeError("one or both authorized review ZIP destinations already exist")

    internal: dict[str, bytes] = {}
    for path in sorted(FINAL_SCORING_DIR.rglob("*")):
        if not path.is_file() or path.suffix == ".pyc" or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(FINAL_SCORING_DIR).as_posix()
        internal[f"final_scoring/{relative}"] = path.read_bytes()
    internal["RQ2_FINAL_ROUTER_FOR_RQ3.json"] = BINDING_PATH.read_bytes()
    if any(name.endswith("RQ2_V2_TEST_ESCROW_2026-08-31.zip") for name in internal):
        raise RuntimeError("internal review ZIP attempted to nest the escrow archive")
    _write_new(INTERNAL_REVIEW_ZIP, _zip_bytes(internal))

    safe_sources = {
        "RQ2_FINAL_ROUTER_FOR_RQ3.json": BINDING_PATH.read_bytes(),
        "rq2_final_router_rq3_handoff_v1.json": (
            FINAL_SCORING_DIR / "rq2_final_router_rq3_handoff_v1.json"
        ).read_bytes(),
        "RQ2_FINAL_ROUTER_RQ3_HANDOFF.md": (
            FINAL_SCORING_DIR / "RQ2_FINAL_ROUTER_RQ3_HANDOFF.md"
        ).read_bytes(),
        "FINAL_ROUTER_SELECTION_DISCLOSURE.md": (
            STAGE4_ROOT / "final_router_selection/FINAL_ROUTER_SELECTION_DISCLOSURE.md"
        ).read_bytes(),
    }
    serialized = b"\n".join(safe_sources.values())
    if b"R2V2-ANN-" in serialized:
        raise RuntimeError("safe handoff contains a TEST annotation ID")
    manifest = {
        "schema_version": "rq2-v2-final-router-rq3-handoff-sha256-manifest-v1",
        "files": [
            {
                "name": name,
                "sha256": sha256_bytes(data),
                "size_bytes": len(data),
            }
            for name, data in sorted(safe_sources.items())
        ],
        "test_queries_included": False,
        "test_gold_included": False,
        "case_predictions_included": False,
        "test_annotation_ids_included": False,
        "error_registry_included": False,
        "restricted_family_mapping_included": False,
    }
    handoff = {**safe_sources, "SHA256_MANIFEST.json": canonical_json_bytes(manifest)}
    _write_new(RQ3_HANDOFF_ZIP, _zip_bytes(handoff))

    return {
        "status": "PASS",
        "internal_review_zip": _audit(INTERNAL_REVIEW_ZIP, internal),
        "rq3_safe_handoff_zip": _audit(RQ3_HANDOFF_ZIP, handoff),
    }


def main() -> int:
    print(json.dumps(build_packages(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
