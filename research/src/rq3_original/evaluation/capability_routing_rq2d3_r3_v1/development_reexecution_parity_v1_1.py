"""Actual B0/B1/P1 re-execution against the frozen RQ2 development ledgers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import CAPABILITIES, ROOT, sha256_file
from .frozen_capability_predictor_core_v1_1 import (
    CoreRoutingContentV1_1,
    FrozenCapabilityPredictorCoreV1_1,
    core_trace_hash_v1_1,
    trace_projection_v1_1,
)


DEVELOPMENT_INPUT_MANIFEST = ROOT / (
    "evaluation/capability_routing_v1_r2b/"
    "source_separated_capability_gold_manifest_v1.json"
)
DEVELOPMENT_INPUT_MANIFEST_SHA256 = (
    "1c41fd4f81d41fde15dcf10981b242ce7615071e1177ce555f7e1aebae85c831"
)
LEDGER_AUTHORITY_MANIFEST = ROOT / (
    "evaluation/capability_routing_rq2b_v1/rq2b_validation_report_v1.json"
)
LEDGER_AUTHORITY_MANIFEST_SHA256 = (
    "83bd1f3c26d866cdf449512b180a2e5e265bd86483634cea31870882843daca2"
)
LEDGER_ROLES = {
    "synthetic": {
        "B0": "evaluation/capability_routing_rq2b_v1/local_artifacts/b0_predictions/b0_synthetic_v1.jsonl",
        "B1": "evaluation/capability_routing_rq2b_v1/local_artifacts/b1_predictions/b1_synthetic_v1.jsonl",
        "P1": "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/synthetic_P1_D05_SIGNAL_UNION.jsonl",
    },
    "authentic": {
        "B0": "evaluation/capability_routing_rq2b_v1/local_artifacts/b0_predictions/b0_authentic_v1.jsonl",
        "B1": "evaluation/capability_routing_rq2b_v1/local_artifacts/b1_predictions/b1_authentic_v1.jsonl",
        "P1": "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/authentic_final_policy_v1.jsonl",
    },
    "context_missing": {
        "B0": "evaluation/capability_routing_rq2b_v1/local_artifacts/b0_predictions/b0_registry_v1.jsonl",
        "B1": "evaluation/capability_routing_rq2b_v1/local_artifacts/b1_predictions/b1_registry_v1.jsonl",
        "P1": "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/registry_final_policy_v1.jsonl",
    },
}
METRIC_JOIN_ROLE = (
    "evaluation/capability_routing_rq2b_v1/local_artifacts/"
    "error_ledgers/metric_join_rows_v1.json"
)


@dataclass(frozen=True)
class DevelopmentFeatureInputV1_1:
    case_id: str
    current_query: str
    current_page: str
    conversation_history: tuple[Mapping[str, Any], ...]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _manifest_relative_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    target = ROOT / path
    if not target.is_relative_to(ROOT) or not target.is_file() or target.is_symlink():
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    return target


def _load_development_feature_inputs() -> dict[str, tuple[DevelopmentFeatureInputV1_1, ...]]:
    if sha256_file(DEVELOPMENT_INPUT_MANIFEST) != DEVELOPMENT_INPUT_MANIFEST_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    manifest = json.loads(DEVELOPMENT_INPUT_MANIFEST.read_text(encoding="utf-8"))
    members = manifest.get("gold_members")
    if not isinstance(members, Mapping):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    selected: dict[int, tuple[str, Mapping[str, Any]]] = {}
    for relative, descriptor in members.items():
        if (
            isinstance(descriptor, Mapping)
            and descriptor.get("local_only") is True
            and descriptor.get("record_count") in {3, 22, 35}
        ):
            selected[int(descriptor["record_count"])] = (str(relative), descriptor)
    if set(selected) != {3, 22, 35}:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    dataset_for_count = {35: "synthetic", 22: "authentic", 3: "context_missing"}
    datasets: dict[str, tuple[DevelopmentFeatureInputV1_1, ...]] = {}
    for count, (relative, descriptor) in selected.items():
        path = _manifest_relative_path(relative)
        if sha256_file(path) != descriptor.get("sha256"):
            raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
        rows = _jsonl(path)
        if len(rows) != count:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
        projected = tuple(
            DevelopmentFeatureInputV1_1(
                case_id=str(row["review_case_id"]),
                current_query=str(row["current_query"]),
                current_page=str(row["current_page"]),
                conversation_history=tuple(
                    dict(item) for item in row["necessary_conversation_history"]
                ),
            )
            for row in rows
        )
        if len({row.case_id for row in projected}) != count:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
        datasets[dataset_for_count[count]] = projected
    return datasets


def _load_ledger_authority() -> Mapping[str, str]:
    if sha256_file(LEDGER_AUTHORITY_MANIFEST) != LEDGER_AUTHORITY_MANIFEST_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    document = json.loads(LEDGER_AUTHORITY_MANIFEST.read_text(encoding="utf-8"))
    authority = document.get("local_ledger_sha256")
    if not isinstance(authority, Mapping):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    required = {
        relative
        for methods in LEDGER_ROLES.values()
        for relative in methods.values()
    } | {METRIC_JOIN_ROLE}
    if not required <= set(authority):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    result = {relative: str(authority[relative]) for relative in required}
    for relative, expected in result.items():
        path = _manifest_relative_path(relative)
        if sha256_file(path) != expected:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    return result


def _expected_capabilities(method: str, row: Mapping[str, Any]) -> list[str]:
    if method in {"B0", "B1"}:
        projection = dict(row["capability_projection"])
        return [name for name in CAPABILITIES if bool(projection.get(name))]
    return [name for name in CAPABILITIES if name in set(row["predicted_capabilities"])]


def _metric_context_expectations(authority: Mapping[str, str]) -> dict[tuple[str, str, str], bool]:
    path = _manifest_relative_path(METRIC_JOIN_ROLE)
    if sha256_file(path) != authority[METRIC_JOIN_ROLE]:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
    document = json.loads(path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str, str], bool] = {}
    for dataset in ("synthetic", "authentic"):
        for method, rows in document[dataset].items():
            for row in rows:
                result[(dataset, method, str(row["review_case_id"]))] = bool(
                    row["predicted_context_resolution_required"]
                )
    return result


def require_prediction_level_authority_v1_1(row: Mapping[str, Any]) -> None:
    if not (
        ("capability_projection" in row or "predicted_capabilities" in row)
        and ("case_id" in row or "review_case_id" in row)
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")


def run_development_reexecution_parity_v1_1() -> dict[str, Any]:
    datasets = _load_development_feature_inputs()
    ledger_authority = _load_ledger_authority()
    context_expectations = _metric_context_expectations(ledger_authority)
    frozen: dict[tuple[str, str], tuple[Path, dict[str, dict[str, Any]]]] = {}
    p1_registry_context: dict[str, bool] = {}
    for dataset, methods in LEDGER_ROLES.items():
        for method, relative in methods.items():
            path = _manifest_relative_path(relative)
            if sha256_file(path) != ledger_authority[relative]:
                raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
            rows = _jsonl(path)
            for row in rows:
                require_prediction_level_authority_v1_1(row)
            keyed = {
                str(row.get("case_id") or row.get("review_case_id")): row for row in rows
            }
            if len(keyed) != len(rows):
                raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY_AUTHORITY")
            frozen[(dataset, method)] = (path, keyed)
            if dataset == "context_missing" and method == "P1":
                p1_registry_context = {
                    case_id: bool(row["context_resolution_required_prediction"])
                    for case_id, row in keyed.items()
                }
    safe_results: list[dict[str, Any]] = []
    with FrozenCapabilityPredictorCoreV1_1() as core:
        for dataset, examples in datasets.items():
            for method in ("B0", "B1", "P1"):
                path, expected_by_id = frozen[(dataset, method)]
                context_mismatch = capability_mismatch = trace_mismatch = id_mismatch = 0
                for case in examples:
                    expected = expected_by_id.get(case.case_id)
                    if expected is None:
                        id_mismatch += 1
                        continue
                    if dataset == "context_missing":
                        expected_context = (
                            False
                            if method == "B0"
                            else bool(p1_registry_context[case.case_id])
                        )
                    else:
                        expected_context = context_expectations[
                            (dataset, method, case.case_id)
                        ]
                    expected_caps = _expected_capabilities(method, expected)
                    expected_trace = core_trace_hash_v1_1(
                        trace_projection_v1_1(
                            method,
                            expected,
                            context_prediction=expected_context,
                            capabilities=expected_caps,
                        )
                    )
                    actual = core.predict(
                        method,
                        CoreRoutingContentV1_1(
                            current_query=case.current_query,
                            current_page=case.current_page,
                            necessary_conversation_history=case.conversation_history,
                        ),
                    )
                    context_mismatch += int(
                        bool(actual["context_resolution_required_prediction"])
                        != expected_context
                    )
                    capability_mismatch += int(
                        list(actual["predicted_capabilities"]) != expected_caps
                    )
                    trace_mismatch += int(
                        str(actual["core_prediction_trace_hash"]) != expected_trace
                    )
                expected_ids = set(expected_by_id)
                actual_ids = {case.case_id for case in examples}
                id_mismatch += len(expected_ids ^ actual_ids)
                status = (
                    "PASS"
                    if not (id_mismatch or context_mismatch or capability_mismatch or trace_mismatch)
                    else "FAIL"
                )
                safe_results.append(
                    {
                        "dataset": dataset,
                        "records": len(examples),
                        "method": method,
                        "expected_prediction_ledger_sha256": sha256_file(path),
                        "actual_case_count": len(examples),
                        "case_identity_mismatch_count": id_mismatch,
                        "context_mismatch_count": context_mismatch,
                        "capability_set_mismatch_count": capability_mismatch,
                        "core_trace_mismatch_count": trace_mismatch,
                        "status": status,
                    }
                )
    if any(row["status"] != "PASS" for row in safe_results):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_DEVELOPMENT_PARITY")
    return {
        "schema_version": "rq2d3-r3-development-reexecution-parity-v1",
        "stage": "RQ2-D3-R3",
        "status": "PASS",
        "actual_reexecution": True,
        "hash_only_parity": False,
        "datasets": safe_results,
        "dataset_record_counts": {"synthetic": 35, "authentic": 22, "context_missing": 3},
        "method_count": 3,
        "dataset_method_run_count": len(safe_results),
        "prediction_mismatch_count": 0,
        "context_mismatch_count": 0,
        "capability_set_mismatch_count": 0,
        "core_trace_mismatch_count": 0,
        "development_input_authority_manifest_sha256": DEVELOPMENT_INPUT_MANIFEST_SHA256,
        "prediction_ledger_authority_manifest_sha256": LEDGER_AUTHORITY_MANIFEST_SHA256,
        "mapping_access_count": 0,
        "canonical_case_bank_access_count": 0,
        "track_b_access_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }
