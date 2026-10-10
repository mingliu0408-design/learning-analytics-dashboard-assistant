"""Freeze safe authority metadata for the local synthetic calibration bank."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import (
    CALIBRATION_BANK_ALIAS,
    HERE,
    RAW_SYNTHETIC_SOURCE_RELATIVE,
    ROOT,
    canonical_json_bytes,
    require_exact_synthetic_source,
    sha256_bytes,
    sha256_file,
)


EXPECTED_RAW_SHA256 = (
    "b08f690547820945a503acf61cdcd9b0e2c305a28f0262afc16b76cd10668cff"
)
EXPECTED_RAW_SIZE_BYTES = 21786
EXPECTED_RAW_RECORD_COUNT = 36
EXPECTED_CANONICAL_CASE_COUNT = 35
EXPECTED_SOURCE_DATASET = "RQ2A_CONTRACT_SYNTHETIC"
EXPECTED_CONTENT_HASH_SET_SHA256 = (
    "167986c3a23117869054802f7994d7731c812fa8aeeb86954a4eb32370b5f04b"
)
REQUIRED_FIELDS = (
    "case_id",
    "source_dataset",
    "source_scenario_id",
    "turn_index",
    "current_query",
    "current_page",
    "conversation_history",
    "existing_expected_intent",
    "existing_required_capabilities",
    "scenario_category",
    "scenario_family",
    "provenance",
)


class SyntheticAuthorityError(RuntimeError):
    pass


def _canonical_record_hash(record: Mapping[str, Any]) -> str:
    serialised = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialised).hexdigest()


def build_synthetic_authority(root: Path = ROOT) -> dict[str, Any]:
    source = require_exact_synthetic_source(RAW_SYNTHETIC_SOURCE_RELATIVE)
    source_status = os.lstat(source)
    if not stat.S_ISREG(source_status.st_mode) or source.is_symlink():
        raise SyntheticAuthorityError("synthetic source must be regular and non-symlink")

    raw = source.read_bytes()
    if sha256_bytes(raw) != EXPECTED_RAW_SHA256 or len(raw) != EXPECTED_RAW_SIZE_BYTES:
        raise SyntheticAuthorityError("synthetic source byte identity mismatch")
    records = [
        json.loads(line)
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    ]
    if len(records) != EXPECTED_RAW_RECORD_COUNT:
        raise SyntheticAuthorityError("synthetic source record count mismatch")
    if any(not isinstance(record, Mapping) for record in records):
        raise SyntheticAuthorityError("synthetic source record is not an object")
    if any(not set(REQUIRED_FIELDS).issubset(record) for record in records):
        raise SyntheticAuthorityError("synthetic source schema mismatch")
    if {str(record["source_dataset"]) for record in records} != {
        EXPECTED_SOURCE_DATASET
    }:
        raise SyntheticAuthorityError("synthetic source_dataset mismatch")
    if not all(
        (record.get("provenance") or {}).get("synthetic") is True
        for record in records
    ):
        raise SyntheticAuthorityError("synthetic provenance flag mismatch")

    case_ids = [str(record["case_id"]) for record in records]
    if len(case_ids) != len(set(case_ids)):
        raise SyntheticAuthorityError("synthetic case IDs are not unique")
    content_hashes = [_canonical_record_hash(record) for record in records]
    content_hash_set_sha256 = sha256_bytes(
        ("\n".join(sorted(content_hashes)) + "\n").encode("utf-8")
    )
    if content_hash_set_sha256 != EXPECTED_CONTENT_HASH_SET_SHA256:
        raise SyntheticAuthorityError("synthetic content-hash set mismatch")

    original_summary_path = root / (
        "evaluation/capability_routing_v1/"
        "capability_development_bank_summary_v1.json"
    )
    original_summary = json.loads(original_summary_path.read_text(encoding="utf-8"))
    if original_summary.get("canonical_case_count") != EXPECTED_CANONICAL_CASE_COUNT:
        raise SyntheticAuthorityError("canonical case count mismatch")

    field_union = sorted({str(key) for record in records for key in record})
    category_counts = dict(
        sorted(Counter(str(record["scenario_category"]) for record in records).items())
    )
    family_counts = Counter(str(record["scenario_family"]) for record in records)
    return {
        "schema_version": "synthetic-calibration-bank-authority-v1",
        "stage": "RQ2-A-R1",
        "status": "AUTHORITY_FROZEN",
        "alias": CALIBRATION_BANK_ALIAS,
        "raw_source_relative_path": RAW_SYNTHETIC_SOURCE_RELATIVE.as_posix(),
        "raw_source_regular_file": True,
        "raw_source_symlink": False,
        "raw_source_sha256": EXPECTED_RAW_SHA256,
        "raw_source_size": EXPECTED_RAW_SIZE_BYTES,
        "raw_record_count": EXPECTED_RAW_RECORD_COUNT,
        "canonical_case_count": EXPECTED_CANONICAL_CASE_COUNT,
        "source_dataset": EXPECTED_SOURCE_DATASET,
        "synthetic": True,
        "authentic_student_voice": False,
        "external_student_data": False,
        "role": "DEVELOPMENT_CALIBRATION_ONLY",
        "eligible_for_threshold_development": True,
        "eligible_for_final_evaluation": False,
        "eligible_for_educational_effectiveness_claim": False,
        "eligible_for_student_language_generalisation_claim": False,
        "track_b_remains_future_held_out": True,
        "authoring_stage": "RQ2-A",
        "authoring_method": "CONTRACT_COVERAGE_SYNTHETIC_CASE_AUTHORING",
        "claimed_existing_student_benchmark_source": False,
        "schema_validation": "PASS",
        "required_fields": list(REQUIRED_FIELDS),
        "observed_field_union": field_union,
        "case_id_unique": True,
        "unique_case_id_count": len(set(case_ids)),
        "case_id_set_sha256": sha256_bytes(
            ("\n".join(sorted(case_ids)) + "\n").encode("utf-8")
        ),
        "content_hash_count": len(content_hashes),
        "unique_content_hash_count": len(set(content_hashes)),
        "content_hash_set_sha256": content_hash_set_sha256,
        "scenario_category_distribution": category_counts,
        "scenario_family_count": len(family_counts),
        "original_safe_summary_sha256": sha256_file(original_summary_path),
        "tracked_natural_language": False,
    }


def write_synthetic_authority(root: Path = ROOT) -> dict[str, Any]:
    authority = build_synthetic_authority(root)
    (HERE / "synthetic_calibration_bank_authority_v1.json").write_bytes(
        canonical_json_bytes(authority)
    )
    return authority


if __name__ == "__main__":
    value = write_synthetic_authority()
    print(
        json.dumps(
            {
                "status": value["status"],
                "raw_record_count": value["raw_record_count"],
                "canonical_case_count": value["canonical_case_count"],
                "synthetic": value["synthetic"],
            },
            sort_keys=True,
        )
    )
