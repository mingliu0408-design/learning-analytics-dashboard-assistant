"""Validate the external authority package and exact local authentic CSV."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
import stat
from typing import Any
import zipfile

from . import (
    AUTHENTIC_ASSISTANT_TURN_COUNT,
    AUTHENTIC_BANK_ALIAS,
    AUTHENTIC_COLUMNS,
    AUTHENTIC_PAGE_DISTRIBUTION,
    AUTHENTIC_RECORD_COUNT,
    AUTHENTIC_SOURCE_SHA256,
    AUTHENTIC_SOURCE_SIZE_BYTES,
    AUTHENTIC_USER_TURN_COUNT,
    AUTHORITY_MANIFEST_SHA256,
    AUTHORITY_MEMBERS,
    AUTHORITY_ZIP_NAME,
    AUTHORITY_ZIP_SHA256,
    FALLBACK_AUTHENTIC_SOURCE_NAME,
    HERE,
    HIGH_CONFIDENCE_CONTEXT_CASE_IDS,
    PREFERRED_AUTHENTIC_SOURCE_RELATIVE,
    ROOT,
    SYNTHETIC_STRESS_BANK_ALIAS,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)


class AuthorityPackageError(RuntimeError):
    pass


class AuthenticSourceError(RuntimeError):
    pass


def _downloads_file(name: str) -> Path:
    return Path.home() / "Downloads" / name


def validate_authority_package() -> dict[str, Any]:
    path = _downloads_file(AUTHORITY_ZIP_NAME)
    if not path.is_file() or path.is_symlink():
        raise AuthorityPackageError("BLOCKED_RQ2_A_R1B_INVALID_AUTHORITY_PACKAGE")
    if sha256_file(path) != AUTHORITY_ZIP_SHA256:
        raise AuthorityPackageError("BLOCKED_RQ2_A_R1B_INVALID_AUTHORITY_PACKAGE")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if tuple(sorted(names)) != tuple(sorted(AUTHORITY_MEMBERS)):
            raise AuthorityPackageError("authority ZIP member mismatch")
        if archive.testzip() is not None:
            raise AuthorityPackageError("authority ZIP CRC failure")
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or info.is_dir():
                raise AuthorityPackageError("authority ZIP contains non-regular member")
        payloads = {name: archive.read(name) for name in names}
    manifest_bytes = payloads["RQ2_AUTHENTIC_DIALOGUE_CALIBRATION_AUTHORITY_V1.json"]
    if sha256_bytes(manifest_bytes) != AUTHORITY_MANIFEST_SHA256:
        raise AuthorityPackageError("authority manifest hash mismatch")
    checksum_lines = payloads[
        "RQ2_AUTHENTIC_DIALOGUE_AUTHORITY_CHECKSUMS.sha256"
    ].decode("utf-8").splitlines()
    checked: set[str] = set()
    for line in checksum_lines:
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        if name not in payloads or name.endswith("CHECKSUMS.sha256"):
            raise AuthorityPackageError("authority internal checksum member mismatch")
        if sha256_bytes(payloads[name]) != digest:
            raise AuthorityPackageError("authority internal checksum failure")
        checked.add(name)
    if checked != {
        "RQ2_AUTHENTIC_DIALOGUE_CALIBRATION_AUTHORITY_V1.json",
        "RQ2_AUTHENTIC_DIALOGUE_INTEGRATION_REPORT.md",
    }:
        raise AuthorityPackageError("authority internal checksum coverage mismatch")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    csv_identity = manifest["source_identity"]["csv"]
    required = {
        "sha256": AUTHENTIC_SOURCE_SHA256,
        "size_bytes": AUTHENTIC_SOURCE_SIZE_BYTES,
        "row_count": AUTHENTIC_RECORD_COUNT,
        "student_user_turn_count": AUTHENTIC_USER_TURN_COUNT,
        "assistant_turn_count": AUTHENTIC_ASSISTANT_TURN_COUNT,
    }
    if any(csv_identity.get(key) != value for key, value in required.items()):
        raise AuthorityPackageError("authority CSV identity mismatch")
    if tuple(csv_identity.get("columns") or ()) != AUTHENTIC_COLUMNS:
        raise AuthorityPackageError("authority CSV schema mismatch")
    if csv_identity.get("student_page_distribution") != AUTHENTIC_PAGE_DISTRIBUTION:
        raise AuthorityPackageError("authority page distribution mismatch")
    return {
        "zip_sha256": AUTHORITY_ZIP_SHA256,
        "zip_member_count": len(names),
        "zip_integrity": "PASS",
        "exact_member_list": True,
        "internal_checksum_entry_count": len(checked),
        "internal_checksums_pass": True,
        "manifest_sha256": AUTHORITY_MANIFEST_SHA256,
        "manifest": manifest,
        "raw_dialogue_text_present": False,
        "student_or_session_identifiers_present": False,
        "track_a_asset_present": False,
        "track_b_asset_present": False,
    }


def _source_matches(path: Path) -> bool:
    return (
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == AUTHENTIC_SOURCE_SIZE_BYTES
        and sha256_file(path) == AUTHENTIC_SOURCE_SHA256
    )


def resolve_authentic_source(root: Path = ROOT) -> tuple[Path, dict[str, Any]]:
    preferred = root / PREFERRED_AUTHENTIC_SOURCE_RELATIVE
    if _source_matches(preferred):
        return preferred, {
            "canonical_local_source": "PROJECT_LOCAL_ONLY_SOURCE",
            "preferred_source_used": True,
            "fallback_source_checked": False,
            "third_raw_copy_created": False,
        }
    fallback = _downloads_file(FALLBACK_AUTHENTIC_SOURCE_NAME)
    if not _source_matches(fallback):
        raise AuthenticSourceError("BLOCKED_RQ2_A_R1B_AUTHENTIC_SOURCE_MISMATCH")
    return fallback, {
        "canonical_local_source": "DOWNLOADS_LOCAL_ONLY_FALLBACK",
        "preferred_source_used": False,
        "fallback_source_checked": True,
        "third_raw_copy_created": False,
    }


def load_authentic_rows(root: Path = ROOT) -> tuple[list[dict[str, str]], dict[str, Any]]:
    path, resolution = resolve_authentic_source(root)
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        raise AuthenticSourceError("authentic source unexpectedly contains UTF-8 BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthenticSourceError("authentic source is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != AUTHENTIC_COLUMNS:
        raise AuthenticSourceError("authentic source columns mismatch")
    rows = list(reader)
    roles = Counter(row["role"] for row in rows)
    pages = Counter(row["graph"] for row in rows if row["role"] == "user")
    if len(rows) != AUTHENTIC_RECORD_COUNT:
        raise AuthenticSourceError("authentic source record count mismatch")
    if roles != Counter(
        {"user": AUTHENTIC_USER_TURN_COUNT, "assistant": AUTHENTIC_ASSISTANT_TURN_COUNT}
    ):
        raise AuthenticSourceError("authentic source role distribution mismatch")
    if dict(sorted(pages.items())) != AUTHENTIC_PAGE_DISTRIBUTION:
        raise AuthenticSourceError("authentic source page distribution mismatch")
    if any(not row["message"].strip() for row in rows):
        raise AuthenticSourceError("authentic source contains an empty message")
    return rows, {
        **resolution,
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
        "encoding": "UTF-8_WITHOUT_BOM",
        "columns": list(AUTHENTIC_COLUMNS),
        "record_count": len(rows),
        "user_turn_count": roles["user"],
        "assistant_turn_count": roles["assistant"],
        "user_page_distribution": dict(sorted(pages.items())),
    }


def build_authentic_source_authority(root: Path = ROOT) -> dict[str, Any]:
    package = validate_authority_package()
    _, source = load_authentic_rows(root)
    paper = package["manifest"]["source_identity"]["paper"]
    return {
        "schema_version": "authentic-dialogue-source-authority-v1",
        "stage": "RQ2-A-R1B",
        "status": "AUTHORISED_FOR_RQ2_DEVELOPMENT_INTEGRATION",
        "authority_package": {
            key: value for key, value in package.items() if key != "manifest"
        },
        "source_identity": {
            "alias": "DUTE_AUTHENTIC_EXAMPLE_DIALOGUE_SUBSET_V1",
            **source,
            "raw_source_local_only": True,
            "raw_source_tracked": False,
            "raw_source_redistribution_authorised": False,
        },
        "paper_provenance": {
            "alias": paper["alias"],
            "title": paper["title"],
            "authors": paper["authors"],
            "pdf_sha256": paper["sha256"],
            "reported_complete_study_query_count": 168,
            "reported_participating_chatbot_users": 22,
            "reported_study_duration_weeks": 10,
            "pdf_body_read_in_rq2_a_r1b": False,
        },
        "research_role": {
            "bank_alias": AUTHENTIC_BANK_ALIAS,
            "student_user_turns": "AUTHENTIC_STUDENT_LANGUAGE_CODEBOOK_CALIBRATION",
            "assistant_turns": "AI_GENERATED_CONTEXT_CANDIDATES_ONLY",
            "complete_study_dataset": False,
            "session_lineage_present": False,
            "paper_theme_labels_present": False,
            "eligible_for_threshold_selection": False,
            "eligible_for_independent_performance_evaluation": False,
            "eligible_for_educational_effectiveness_claim": False,
            "eligible_for_broad_student_language_generalisation": False,
            "synthetic_bank_alias": SYNTHETIC_STRESS_BANK_ALIAS,
        },
        "context_link_contract": {
            "high_confidence_candidate_case_ids": list(
                HIGH_CONFIDENCE_CONTEXT_CASE_IDS
            ),
            "candidate_count": len(HIGH_CONFIDENCE_CONTEXT_CASE_IDS),
            "human_confirmation_required": True,
            "adjacency_proves_shared_session": False,
            "other_cases_have_no_candidate_history": True,
        },
        "invariants": {
            "production_changes": False,
            "model_training": False,
            "provider_calls": 0,
            "network_access": False,
            "track_a_access": False,
            "track_b_access": False,
        },
    }


def write_authentic_source_authority(root: Path = ROOT) -> dict[str, Any]:
    value = build_authentic_source_authority(root)
    (HERE / "authentic_dialogue_source_authority_v1.json").write_bytes(
        canonical_json_bytes(value)
    )
    return value
