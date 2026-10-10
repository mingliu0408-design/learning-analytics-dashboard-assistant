"""Validate the Stage 4J-0 freeze without loading or scoring DEV records."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .p1_protocol import (
    DIAGNOSTIC_POLICY_ID,
    ELIGIBLE_POLICY_IDS,
    OUTER_FOLDS,
    POLICY_SIMPLICITY_ORDER,
)


TRACK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRACK_DIR.parents[2]


class ValidationError(RuntimeError):
    """Raised when a frozen Stage 4J-0 contract check fails."""


def _load_json(name: str) -> dict[str, Any]:
    with (TRACK_DIR / name).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must contain one JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, label: str, passed: list[str]) -> None:
    if not condition:
        raise ValidationError(label)
    passed.append(label)


def run_checks() -> list[str]:
    """Return passed check labels or fail closed on the first mismatch."""

    passed: list[str] = []
    candidates = _load_json("p1_candidate_policies_frozen_v1.json")
    nested = _load_json("p1_nested_selection_protocol_v1.json")
    inputs = _load_json("p1_input_contract_v1.json")
    outputs = _load_json("p1_output_contract_v1.json")

    candidate_ids = tuple(
        policy["policy_id"] for policy in candidates["eligible_policies"]
    )
    _require(candidate_ids == ELIGIBLE_POLICY_IDS, "exact eligible policy IDs", passed)
    _require(
        candidates["eligible_policy_count"] == 9 == len(candidate_ids),
        "exact eligible policy count",
        passed,
    )
    _require(
        [policy["simplicity_order"] for policy in candidates["eligible_policies"]]
        == list(range(9))
        and all(
            POLICY_SIMPLICITY_ORDER[policy["policy_id"]]
            == policy["simplicity_order"]
            for policy in candidates["eligible_policies"]
        ),
        "frozen simplicity order",
        passed,
    )
    diagnostics = candidates["diagnostic_policies"]
    _require(
        candidates["diagnostic_policy_count"] == 1
        and len(diagnostics) == 1
        and diagnostics[0]["policy_id"] == DIAGNOSTIC_POLICY_ID
        and diagnostics[0]["eligible"] is False,
        "one non-eligible all-B4 diagnostic",
        passed,
    )
    _require(
        candidates["architecture"]["case_level_switch_only"] is True
        and candidates["architecture"]["label_level_mixing_prohibited"] is True,
        "case-level complete-route architecture",
        passed,
    )
    _require(
        candidates["architecture"]["triggered_invalid_b4_status"]
        == "FALLBACK_FAILED_USED_B3",
        "B4 failure fallback status",
        passed,
    )

    _require(
        tuple(nested["population"]["outer_fold_ids"]) == OUTER_FOLDS,
        "four frozen outer folds",
        passed,
    )
    expected_tie_break = [
        ("macro_f1", "HIGHER"),
        ("exact_capability_set_match", "HIGHER"),
        ("jaccard", "HIGHER"),
        ("under_routing_rate", "LOWER"),
        ("over_routing_rate", "LOWER"),
        ("fallback_rate", "LOWER"),
        ("policy_simplicity_order", "LOWER"),
        ("policy_id", "UTF8_BYTEWISE_ASCENDING"),
    ]
    actual_tie_break = [
        (rule["metric"], rule["direction"])
        for rule in nested["selection_tie_break"]["ordered_rules"]
    ]
    _require(actual_tie_break == expected_tie_break, "frozen tie-break order", passed)
    _require(
        nested["cross_fitted_meta_policy_evaluation"][
            "outer_validation_label_isolation"
        ]["outer_validation_gold_available_to_policy_selection"]
        is False,
        "outer-validation Gold excluded from selection",
        passed,
    )
    _require(
        nested["final_full_dev_policy_freeze"]["input"]
        == "ALL_64_CROSS_FITTED_DEV_OOF_RECORDS"
        and nested["final_full_dev_policy_freeze"]["test_performance_used"]
        is False,
        "final full-DEV procedure excludes TEST",
        passed,
    )

    bound_artifacts = inputs["bound_artifacts"]
    _require(len(bound_artifacts) == 14, "exact bound artifact inventory", passed)
    for artifact in bound_artifacts:
        relative_path = str(artifact["path"])
        path = REPO_ROOT / relative_path
        _require(path.is_file(), f"bound artifact exists: {relative_path}", passed)
        _require(
            _sha256(path) == artifact["sha256"],
            f"bound artifact hash: {relative_path}",
            passed,
        )
        _require(
            re.search(r"(?:^|[-_/])TEST(?:$|[-_/])", relative_path.upper()) is None,
            f"no TEST identifier in bound path: {relative_path}",
            passed,
        )

    b4_binding = inputs["b4_result_binding"]
    _require(
        b4_binding["result_artifact_path"] is None
        and b4_binding["result_artifact_sha256"] is None
        and b4_binding["terminal_outcome_artifact_path"] is None
        and b4_binding["terminal_outcome_artifact_sha256"] is None,
        "B4 execution result remains unbound",
        passed,
    )
    _require(
        inputs["execution_gate"]["stage4j0_p1_scoring_authorized"] is False
        and inputs["execution_gate"]["stage4j0_provider_calls_authorized"] is False
        and inputs["execution_gate"]["stage4j0_test_access_authorized"] is False,
        "Stage 4J-0 execution gates closed",
        passed,
    )
    _require(
        outputs["current_stage_execution"]
        == {
            "p1_case_outputs_created": False,
            "p1_scores_created": False,
            "provider_calls": 0,
            "test_records_accessed": 0,
        },
        "zero current-stage execution outputs",
        passed,
    )

    source = (TRACK_DIR / "p1_protocol.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    allowed_imports = {
        "__future__",
        "dataclasses",
        "decimal",
        "math",
        "re",
        "typing",
    }
    _require(
        imported_roots <= allowed_imports,
        "reference semantics use standard-library pure imports only",
        passed,
    )

    status_text = (TRACK_DIR / "STATUS.md").read_text(encoding="utf-8")
    _require(
        "READY_FOR_STAGE_4J_AFTER_VALID_B4_DEV_RESULTS" in status_text,
        "required readiness status",
        passed,
    )
    return passed


def main() -> int:
    passed = run_checks()
    for index, label in enumerate(passed, start=1):
        print(f"PASS {index:02d}: {label}")
    print(f"RESULT: {len(passed)}/{len(passed)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
