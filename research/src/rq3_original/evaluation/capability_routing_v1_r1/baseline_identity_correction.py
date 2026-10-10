"""Correct the descriptive identity of the already measured Legacy baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import HERE, ROOT, canonical_json_bytes, sha256_file


ORIGINAL_PROJECTION_RELATIVE = Path(
    "evaluation/capability_routing_v1/legacy_capability_projection_v1.json"
)
ORIGINAL_BASELINE_LABEL = "B0_FROZEN_C0_TOP1_HARD_ROUTE"
CURRENT_MEASURED_BASELINE = (
    "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE"
)
FUTURE_UNMEASURED_B0 = (
    "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION"
)
B0_MEASURED = False
INTERPRETIVE_FIELDS = {
    "baseline_identity",
    "context_resolution_enabled",
    "original_query_only",
    "supersedes_baseline_label",
}


class BaselineIdentityError(RuntimeError):
    pass


def build_corrected_projection(root: Path = ROOT) -> dict[str, Any]:
    original_path = root / ORIGINAL_PROJECTION_RELATIVE
    original = json.loads(original_path.read_text(encoding="utf-8"))
    if original.get("baseline_identity") != ORIGINAL_BASELINE_LABEL:
        raise BaselineIdentityError("unexpected original Legacy baseline label")
    calls = dict(original.get("production_function_call_counts") or {})
    if calls.get("prepare_mode_cm_context", 0) <= 0 or calls.get(
        "build_c_full_context", 0
    ) <= 0:
        raise BaselineIdentityError("measured baseline lacks production context resolution")
    corrected = dict(original)
    corrected.update(
        {
            "baseline_identity": CURRENT_MEASURED_BASELINE,
            "context_resolution_enabled": True,
            "original_query_only": False,
            "supersedes_baseline_label": ORIGINAL_BASELINE_LABEL,
        }
    )
    all_keys = set(original) | set(corrected)
    changed = {key for key in all_keys if original.get(key) != corrected.get(key)}
    if changed != INTERPRETIVE_FIELDS:
        raise BaselineIdentityError(
            f"corrected projection changed non-interpretive fields: {sorted(changed)}"
        )
    return corrected


def baseline_identity_contract() -> dict[str, Any]:
    return {
        "current_production_baseline": CURRENT_MEASURED_BASELINE,
        "current_production_context_resolution_enabled": True,
        "current_production_original_query_only": False,
        "future_b0_identity": FUTURE_UNMEASURED_B0,
        "future_b0_measured": B0_MEASURED,
        "future_b0_measurement_stage": "RQ2-B",
        "production_code_change_authorised_for_correction": False,
    }


def write_corrected_projection(root: Path = ROOT) -> dict[str, Any]:
    corrected = build_corrected_projection(root)
    (HERE / "legacy_capability_projection_v1_1.json").write_bytes(
        canonical_json_bytes(corrected)
    )
    return corrected


def assert_aggregate_identity(root: Path = ROOT) -> None:
    original = json.loads((root / ORIGINAL_PROJECTION_RELATIVE).read_text(encoding="utf-8"))
    corrected = build_corrected_projection(root)
    for key, value in original.items():
        if key == "baseline_identity":
            continue
        if corrected.get(key) != value:
            raise BaselineIdentityError(f"aggregate field changed: {key}")
    if corrected["ledger_sha256"] != original["ledger_sha256"]:
        raise BaselineIdentityError("Legacy per-case ledger identity changed")
    if sha256_file(root / ORIGINAL_PROJECTION_RELATIVE) == sha256_file(
        HERE / "legacy_capability_projection_v1_1.json"
    ):
        raise BaselineIdentityError("corrected projection was not versioned")


if __name__ == "__main__":
    value = write_corrected_projection()
    print(
        json.dumps(
            {
                "status": "PASS",
                "baseline_identity": value["baseline_identity"],
                "future_b0_measured": B0_MEASURED,
            },
            sort_keys=True,
        )
    )
