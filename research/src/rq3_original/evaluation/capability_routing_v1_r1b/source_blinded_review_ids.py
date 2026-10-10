"""Create deterministic source-blinded reviewer IDs and a local-only mapping."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from . import (
    LOCAL_REVIEW_ID_MAPPING_RELATIVE,
    ROOT,
    canonical_jsonl_bytes,
    id_set_sha256,
    sha256_file,
)


FIXED_REVIEW_ID_SALT = "RQ2-A-R1B-V1.2-SOURCE-BLINDING-20260825"
REVIEW_ID_PATTERN = re.compile(r"^RQ2CAL-[0-9a-f]{12}$")


class SourceBlindingError(RuntimeError):
    pass


def review_case_id(canonical_case_id: str) -> str:
    digest = hashlib.sha256(
        f"{FIXED_REVIEW_ID_SALT}\x00{canonical_case_id}".encode("utf-8")
    ).hexdigest()[:12]
    value = f"RQ2CAL-{digest}"
    if not REVIEW_ID_PATTERN.fullmatch(value):
        raise SourceBlindingError("opaque review ID format failure")
    return value


def build_review_id_mapping(
    combined_rows: list[dict[str, Any]], root: Path = ROOT
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    mapping = [
        {
            "review_case_id": review_case_id(str(row["canonical_case_id"])),
            "canonical_case_id": str(row["canonical_case_id"]),
            "source_bank": str(row["source_bank"]),
        }
        for row in combined_rows
    ]
    review_ids = [row["review_case_id"] for row in mapping]
    if len(mapping) != 60 or len(set(review_ids)) != 60:
        raise SourceBlindingError("review ID collision or count mismatch")
    if any(
        token in review_id.upper()
        for review_id in review_ids
        for token in ("AUTH", "SYN", "SOURCE", "STUDENT")
    ):
        raise SourceBlindingError("review ID leaks source identity")
    path = root / LOCAL_REVIEW_ID_MAPPING_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_jsonl_bytes(mapping))
    summary = {
        "mapping_record_count": len(mapping),
        "review_case_id_set_sha256": id_set_sha256(review_ids),
        "mapping_sha256": sha256_file(path),
        "mapping_size_bytes": path.stat().st_size,
        "mapping_local_only": True,
        "mapping_tracked": False,
        "mapping_reviewer_visible": False,
        "source_identity_encoded_in_review_id": False,
        "fixed_salt_sha256": hashlib.sha256(
            FIXED_REVIEW_ID_SALT.encode("utf-8")
        ).hexdigest(),
    }
    return mapping, summary
