"""Validate and freeze the user-authorised local-only 28-case fixture bank."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import stat
from typing import Any, Iterable

from . import (
    FIXTURE_ALIAS,
    FIXTURE_AUTHORING_METHOD,
    FIXTURE_BANK_PATH,
    FIXTURE_ROLE,
    canonical_json_bytes,
    canonical_json_line,
    sha256_bytes,
    sha256_file,
)
from .fixture_schema import (
    ControlledMechanismFixtureV1,
    FIXTURE_CATEGORY_COUNTS,
    MECHANISM_GROUP_COUNTS,
    REQUIRED_FIXTURE_FIELDS,
)


class FixtureBankError(RuntimeError):
    pass


def _assert_regular_non_symlink(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise FixtureBankError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: missing") from exc
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise FixtureBankError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: unsafe file type")


def canonical_fixture_bank_bytes(
    fixtures: Iterable[ControlledMechanismFixtureV1],
) -> bytes:
    return b"".join(canonical_json_line(item.to_mapping()) for item in fixtures)


def load_fixture_bank(
    path: Path = FIXTURE_BANK_PATH,
) -> tuple[ControlledMechanismFixtureV1, ...]:
    _assert_regular_non_symlink(path)
    fixtures: list[ControlledMechanismFixtureV1] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise FixtureBankError(
                f"BLOCKED_RQ2_C0_R1_FIXTURE_BANK: blank line {line_number}"
            )
        try:
            value = json.loads(line)
            fixtures.append(ControlledMechanismFixtureV1.from_mapping(value))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise FixtureBankError(
                f"BLOCKED_RQ2_C0_R1_FIXTURE_BANK: record {line_number}"
            ) from exc
    ids = [item.fixture_id for item in fixtures]
    group_counts = Counter(item.mechanism_group for item in fixtures)
    category_counts = Counter(item.fixture_category for item in fixtures)
    if len(fixtures) != 28 or len(ids) != len(set(ids)):
        raise FixtureBankError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: identity")
    if dict(sorted(group_counts.items())) != dict(sorted(MECHANISM_GROUP_COUNTS.items())):
        raise FixtureBankError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: group counts")
    if dict(sorted(category_counts.items())) != dict(sorted(FIXTURE_CATEGORY_COUNTS.items())):
        raise FixtureBankError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK: category counts")
    return tuple(fixtures)


def normalise_local_fixture_bank(
    fixtures: tuple[ControlledMechanismFixtureV1, ...],
    path: Path = FIXTURE_BANK_PATH,
) -> None:
    payload = canonical_fixture_bank_bytes(fixtures)
    if path.read_bytes() != payload:
        path.write_bytes(payload)


def _sequence_commitment(values: Iterable[str]) -> str:
    return sha256_bytes(canonical_json_bytes(list(values)))


def fixture_authority_contract() -> dict[str, Any]:
    return {
        "schema_version": "controlled-mechanism-fixture-authority-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "alias": FIXTURE_ALIAS,
        "role": FIXTURE_ROLE,
        "authoring_method": FIXTURE_AUTHORING_METHOD,
        "user_authorised": True,
        "synthetic_controlled": True,
        "authentic_student_data": False,
        "human_capability_gold": False,
        "student_dataset": False,
        "final_evaluation": False,
        "authentic_dialogue_evidence": False,
        "educational_effectiveness_evidence": False,
        "threshold_selection_role": "MECHANISM_DEVELOPMENT_ONLY",
        "track_b_final_role_changed": False,
        "full_text_tracked": False,
        "full_text_review_package_eligible": False,
    }


def build_fixture_manifest(
    fixtures: tuple[ControlledMechanismFixtureV1, ...],
    path: Path = FIXTURE_BANK_PATH,
) -> dict[str, Any]:
    record_hashes = [sha256_bytes(canonical_json_line(item.to_mapping())) for item in fixtures]
    return {
        "schema_version": "controlled-mechanism-fixture-manifest-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "alias": FIXTURE_ALIAS,
        "role": FIXTURE_ROLE,
        "raw_bank_sha256": sha256_file(path),
        "raw_bank_size_bytes": path.stat().st_size,
        "raw_record_count": len(fixtures),
        "canonical_fixture_count": len(fixtures),
        "regular_file": True,
        "symlink": False,
        "ordered_fixture_id_commitment_sha256": _sequence_commitment(
            item.fixture_id for item in fixtures
        ),
        "ordered_record_hash_commitment_sha256": _sequence_commitment(record_hashes),
        "schema_field_commitment_sha256": _sequence_commitment(REQUIRED_FIXTURE_FIELDS),
        "record_hash_count": len(record_hashes),
        "natural_language_in_manifest": False,
        "local_only": True,
        "git_tracked": False,
    }


def build_fixture_summary(
    fixtures: tuple[ControlledMechanismFixtureV1, ...],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    group_counts = Counter(item.mechanism_group for item in fixtures)
    category_counts = Counter(item.fixture_category for item in fixtures)
    return {
        "schema_version": "controlled-mechanism-fixture-summary-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN",
        "alias": FIXTURE_ALIAS,
        "role": FIXTURE_ROLE,
        "fixture_bank_sha256": manifest["raw_bank_sha256"],
        "fixture_bank_size_bytes": manifest["raw_bank_size_bytes"],
        "total": len(fixtures),
        "rag": sum(count for key, count in group_counts.items() if key.startswith("RAG_")),
        "persistent_memory": sum(
            count for key, count in group_counts.items() if key.startswith("PERSISTENT_")
        ),
        "mechanism_group_counts": dict(sorted(group_counts.items())),
        "fixture_category_counts": dict(sorted(category_counts.items())),
        "full_text_included": False,
        "memory_text_included": False,
        "student_data_included": False,
    }
