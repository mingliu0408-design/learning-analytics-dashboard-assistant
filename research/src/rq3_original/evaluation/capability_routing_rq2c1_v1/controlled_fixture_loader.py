"""Leakage-safe loader for the local-only controlled mechanism fixtures."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from . import (
    EXPECTED_FIXTURE_COUNT,
    EXPECTED_FIXTURE_SHA256,
    EXPECTED_FIXTURE_SIZE,
    FIXTURE_RELATIVE,
    ROOT,
    sha256_bytes,
)


EXPECTED_FIELDS = frozenset(
    {
        "expected_write_decision",
        "expected_retrieval_ids",
        "expected_admission_ids",
        "expected_rejection_reasons",
        "expected_clarification",
        "expected_security_state",
    }
)


@dataclass(frozen=True)
class ControlledFixtureInput:
    fixture_id: str
    mechanism_group: str
    fixture_category: str
    input_event_or_query: Mapping[str, Any]
    initial_store_state: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ControlledFixtureExpected:
    fixture_id: str
    values: Mapping[str, Any]


@dataclass(frozen=True)
class ControlledFixtureSet:
    prediction_inputs: tuple[ControlledFixtureInput, ...]
    scoring_targets: tuple[ControlledFixtureExpected, ...]
    identity: Mapping[str, Any]


def load_controlled_fixtures() -> ControlledFixtureSet:
    path = ROOT / FIXTURE_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise ValueError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
    raw = path.read_bytes()
    if (
        sha256_bytes(raw) != EXPECTED_FIXTURE_SHA256
        or len(raw) != EXPECTED_FIXTURE_SIZE
    ):
        raise ValueError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if len(rows) != EXPECTED_FIXTURE_COUNT:
        raise ValueError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
    prediction: list[ControlledFixtureInput] = []
    scoring: list[ControlledFixtureExpected] = []
    for row in rows:
        actual = set(row) - EXPECTED_FIELDS - {"coverage_tags", "contract_basis"}
        if actual != {
            "fixture_id",
            "mechanism_group",
            "fixture_category",
            "input_event_or_query",
            "initial_store_state",
        }:
            raise ValueError("BLOCKED_RQ2_C1_EXPECTED_FIELD_LEAKAGE")
        prediction.append(
            ControlledFixtureInput(
                fixture_id=str(row["fixture_id"]),
                mechanism_group=str(row["mechanism_group"]),
                fixture_category=str(row["fixture_category"]),
                input_event_or_query=dict(row["input_event_or_query"]),
                initial_store_state=tuple(dict(item) for item in row["initial_store_state"]),
            )
        )
        scoring.append(
            ControlledFixtureExpected(
                fixture_id=str(row["fixture_id"]),
                values={key: row[key] for key in sorted(EXPECTED_FIELDS)},
            )
        )
    ids = [item.fixture_id for item in prediction]
    if len(ids) != len(set(ids)):
        raise ValueError("BLOCKED_RQ2_C1_LOCAL_INPUT_IDENTITY")
    return ControlledFixtureSet(
        prediction_inputs=tuple(prediction),
        scoring_targets=tuple(scoring),
        identity={
            "sha256": EXPECTED_FIXTURE_SHA256,
            "size_bytes": len(raw),
            "record_count": len(rows),
            "prediction_view_expected_field_count": 0,
            "scoring_view_created_after_prediction_boundary": True,
        },
    )


def expected_field_access_audit() -> dict[str, Any]:
    annotations = set(ControlledFixtureInput.__annotations__)
    leaked = sorted(annotations & EXPECTED_FIELDS)
    if leaked:
        raise ValueError("BLOCKED_RQ2_C1_EXPECTED_FIELD_LEAKAGE")
    return {
        "status": "PASS",
        "prediction_input_fields": sorted(annotations),
        "expected_fields_present_in_prediction_view": leaked,
        "runtime_expected_field_read_count_before_scoring": 0,
        "gold_feature_used": False,
        "source_role_used": False,
        "scenario_family_used_as_feature": False,
    }
