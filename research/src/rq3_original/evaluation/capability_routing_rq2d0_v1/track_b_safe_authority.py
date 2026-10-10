"""Verification and governed copying of the text-free Track-B schema package."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any
import zipfile

from . import (
    SAFE_AUTHORITY_COPY_ROOT,
    SCHEMA_AUTHORITY_MEMBER_SHA256,
    SCHEMA_AUTHORITY_ZIP,
    SCHEMA_AUTHORITY_ZIP_SHA256,
    TRACK_B_FILE_NAME,
    TRACK_B_RECORD_COUNT,
    TRACK_B_SHA256,
    sha256_bytes,
    sha256_file,
)


class SafeAuthorityError(RuntimeError):
    pass


def _parse_checksums(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise SafeAuthorityError("authority checksum manifest is not ASCII") from exc
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        if len(digest) != 64 or name in values:
            raise SafeAuthorityError("authority checksum manifest is malformed")
        values[name] = digest
    return values


def verify_safe_schema_package(
    path: Path = SCHEMA_AUTHORITY_ZIP,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if not path.is_file() or path.is_symlink() or sha256_file(path) != SCHEMA_AUTHORITY_ZIP_SHA256:
        raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or set(names) != set(SCHEMA_AUTHORITY_MEMBER_SHA256):
            raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
        if archive.testzip() is not None:
            raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
        for info in infos:
            pure = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or len(pure.parts) != 1
                or info.is_dir()
                or stat.S_ISLNK(mode)
            ):
                raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
        payloads = {name: archive.read(name) for name in names}
    if any(
        sha256_bytes(payloads[name]) != expected
        for name, expected in SCHEMA_AUTHORITY_MEMBER_SHA256.items()
    ):
        raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    internal = _parse_checksums(payloads["TRACK_B_SCHEMA_AUTHORITY_CHECKSUMS.sha256"])
    expected_internal = set(payloads) - {"TRACK_B_SCHEMA_AUTHORITY_CHECKSUMS.sha256"}
    if set(internal) != expected_internal or any(
        sha256_bytes(payloads[name]) != digest for name, digest in internal.items()
    ):
        raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    authority = json.loads(payloads["TRACK_B_SCHEMA_AUTHORITY_V1.json"])
    provenance = json.loads(payloads["TRACK_B_SCHEMA_AUTHORITY_PROVENANCE_V1.json"])
    source = authority.get("source_identity", {})
    safety = authority.get("privacy_and_distribution", {})
    if (
        source.get("file_name") != TRACK_B_FILE_NAME
        or source.get("sha256") != TRACK_B_SHA256
        or source.get("record_count") != TRACK_B_RECORD_COUNT
        or authority.get("status") != "EFFECTIVE_SAFE_SCHEMA_AUTHORITY"
        or safety.get("raw_track_b_in_package") is not False
        or safety.get("query_or_history_in_package") is not False
        or provenance.get("raw_asset_accessed_by_codex_or_repository_pipeline") is not False
        or provenance.get("raw_query_or_history_exported_in_package") is not False
    ):
        raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    prohibited_top_level = {"records", "rows", "queries", "conversation_histories"}
    for name, raw in payloads.items():
        if name.endswith(".json"):
            value = json.loads(raw)
            if prohibited_top_level & set(value):
                raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    return (
        {
            "schema_version": "track-b-safe-authority-contract-v1",
            "status": "PASS",
            "authority_alias": "TRACK_B_CONTEXTUAL_CAPABILITY_FINAL_SOURCE_V1",
            "package_sha256": SCHEMA_AUTHORITY_ZIP_SHA256,
            "member_count": len(payloads),
            "member_hash_match_count": len(payloads),
            "internal_checksum_match_count": len(internal),
            "zip_integrity": "PASS",
            "source_identity": source,
            "history_dependent": True,
            "track_b_is_capability_gold": False,
            "existing_intent_label_is_capability_gold": False,
            "threshold_selection_eligible": False,
            "policy_selection_eligible": False,
            "p1_modification_eligible": False,
            "authority_builder_access": "OUT_OF_BAND_SCHEMA_AUTHORITY_EXTRACTION",
            "authority_builder_must_not_review_or_adjudicate": True,
            "codex_raw_access": False,
            "repository_d0_raw_access": False,
            "raw_text_in_safe_package": False,
        },
        payloads,
    )


def install_governed_authority_copies(payloads: dict[str, bytes]) -> dict[str, Any]:
    SAFE_AUTHORITY_COPY_ROOT.mkdir(parents=True, exist_ok=True)
    for name in sorted(payloads):
        target = SAFE_AUTHORITY_COPY_ROOT / name
        target.write_bytes(payloads[name])
        if sha256_file(target) != SCHEMA_AUTHORITY_MEMBER_SHA256[name]:
            raise SafeAuthorityError("BLOCKED_RQ2_D0_TRACK_B_SCHEMA_AUTHORITY")
    return {
        "status": "PASS",
        "copy_count": len(payloads),
        "byte_identical_count": len(payloads),
    }
