#!/usr/bin/env python3
"""Strict offline validator for the frozen R3D0 artifact set."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CONTINUATION_PACKAGE = Path(
    "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_CONTINUATION_EXECUTION_PACKAGE_R3C1_2026-09-02.zip"
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    reclassification = load_json(HERE / "r3_existing_attempt_format_reclassification_summary_v2.json")
    checks["attempt_population_106"] = reclassification["attempt_count"] == 106
    checks["classification_changes_exactly_3"] = reclassification[
        "classification_changed_count"
    ] == 3
    checks["no_quality_assessment"] = reclassification["answer_quality_assessments"] == 0
    checks["blind_before_mapping_access"] = reclassification[
        "condition_mode_route_gold_or_expected_outcome_accesses"
    ] == 0
    canonical = load_jsonl(HERE / "c4_real_r3_existing_canonical_response_selection_v1.jsonl")
    checks["canonical_population_104"] = len(canonical) == 104
    checks["canonical_a_50"] = sum(row["shard"] == "A" for row in canonical) == 50
    checks["canonical_b_50"] = sum(row["shard"] == "B" for row in canonical) == 50
    checks["canonical_c_4"] = sum(row["shard"] == "C" for row in canonical) == 4
    checks["a40_attempt_1"] = next(
        row for row in canonical if row["shard"] == "A" and row["logical_order"] == 40
    )["selected_attempt_number"] == 1
    checks["c4_attempt_1"] = next(
        row for row in canonical if row["shard"] == "C" and row["logical_order"] == 4
    )["selected_attempt_number"] == 1
    remaining = load_jsonl(HERE / "c4_real_r3c_remaining_request_manifest_v1.jsonl")
    checks["remaining_population_43"] = len(remaining) == 43
    boundary = load_json(HERE / "c4_real_r3_primary_response_completion_boundary_v1.json")
    checks["exact_147_partition"] = boundary["status"] == "PASS_EXACT_147_REQUEST_PARTITION"
    checks["no_judge_request"] = boundary["judge_requests_created"] == 0
    source = load_json(HERE / "c4_real_r3c_continuation_source_audit_v1.json")
    checks["source_package_identity"] = source["source_package_sha256"] == (
        "16215b04bb875ec8b9b9627df7fb018eff14edf46f5a294049f0dd8442952699"
    )
    checks["source_manifest_identity"] = source["source_blinded_manifest_sha256"] == (
        "2bc12fbdf114cda1f52f3438820e2ec706bf60e1c8f0965c4ce610d9853f7ea1"
    )
    checks["source_orders_5_47"] = source["retained_original_logical_order_range"] == [5, 47]
    checks["source_rows_byte_identical"] = source["full_source_row_bytes_preserved"] is True
    package_audit = load_json(HERE / "c4_real_r3c_continuation_package_freeze_audit_v1.json")
    checks["continuation_package_exists"] = CONTINUATION_PACKAGE.is_file()
    checks["continuation_package_identity"] = sha256(CONTINUATION_PACKAGE) == package_audit[
        "package_sha256"
    ]
    checks["package_requests_43"] = package_audit["request_count"] == 43
    checks["package_maximum_attempts_86"] = package_audit["maximum_physical_attempts"] == 86
    checks["provider_payload_identity_all_43"] = package_audit[
        "provider_payload_byte_identity"
    ] == "PASS_ALL_43"
    checks["package_not_executed"] = package_audit["continuation_executed"] is False
    checks["zero_real_provider_calls"] = package_audit["real_provider_network_calls"] == 0
    checks["zero_generation_calls"] = package_audit["response_generation_calls"] == 0
    checks["zero_judge_calls"] = package_audit["judge_calls"] == 0
    checks["zero_scoring_calls"] = package_audit["scoring_calls"] == 0
    checks["zero_human_rating_actions"] = package_audit["human_rating_actions"] == 0
    checks["embedded_mocked_tests_11"] = package_audit["embedded_mocked_tests"][
        "tests_passed"
    ] == 11
    before = load_json(HERE / "c4_real_r3_source_preservation_manifest_before_v1.json")
    checks["preservation_baseline_pass"] = before["status"] == "PASS_BASELINE_FROZEN"
    after_path = HERE / "c4_real_r3_source_preservation_manifest_after_v1.json"
    if after_path.exists():
        after = load_json(after_path)
        checks["preservation_after_pass"] = after["status"] == (
            "PASS_ALL_ORIGINAL_R3_AND_RESTRICTED_IDENTITIES_UNCHANGED"
        )

    package_validator_path = HERE / "continuation_package_validator_v1.py"
    spec = importlib.util.spec_from_file_location("r3d0_package_validator", package_validator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import continuation package validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package_validation = dict(module.validate_zip(CONTINUATION_PACKAGE))
    checks["continuation_zip_validator_pass"] = package_validation["status"] == "PASS"
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValueError(f"R3D0 validation failures: {failed}")
    return {
        "schema_version": "c4-real-r3d0-validation-report-v1",
        "status": "PASS",
        "checks": checks,
        "check_summary": {"passed": len(checks), "failed": 0, "total": len(checks)},
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "human_rating_actions": 0,
    }


def main() -> int:
    report = validate()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if "--write-report" in sys.argv[1:]:
        (HERE / "c4_real_r3d0_validation_report_v1.json").write_text(
            rendered, encoding="utf-8"
        )
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
