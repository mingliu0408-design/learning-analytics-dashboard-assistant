"""AST inventory and fail-closed verification for superseded D3-R2 real entries."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from . import ROOT, sha256_file


RELATIVE = Path(
    "evaluation/capability_routing_rq2d3_r2_v1/rq2d4_global_one_shot_contract.py"
)
BEFORE_SHA256 = "63f3fc261f7bb06d3def4d65c34e37a58c0e67bb3b5b1511caaa8167d5e61f65"
AFTER_SHA256 = "e0278a15ea37924ed2996ecadc351a63314dcbf7890415d5787d57d3a900eec3"
ENTRYPOINTS = (
    "execute_real_rq2d4_one_shot_v1",
    "_real_extractor_worker",
    "_real_predictor_worker",
    "_real_metric_worker",
    "_run_fixed_worker",
    "main",
)


def _first_executable(function: ast.FunctionDef) -> ast.stmt:
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body.pop(0)
    if not body:
        raise RuntimeError("empty legacy entry")
    return body[0]


def legacy_entrypoint_inventory_v1() -> dict[str, Any]:
    path = ROOT / RELATIVE
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    inventory = []
    for name in ENTRYPOINTS:
        node = functions.get(name)
        if node is None:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_LEGACY_ENTRY_REVOCATION")
        first = _first_executable(node)
        guarded = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Call)
            and isinstance(first.value.func, ast.Name)
            and first.value.func.id == "_raise_superseded_real_entry"
        )
        if not guarded:
            raise RuntimeError("BLOCKED_RQ2_D3_R3_LEGACY_ENTRY_REVOCATION")
        inventory.append(
            {
                "entrypoint": name,
                "relative_path": str(RELATIVE),
                "first_executable_statement": "_raise_superseded_real_entry()",
                "authorised_for_real_execution": False,
            }
        )
    observed = sha256_file(path)
    if observed != AFTER_SHA256:
        raise RuntimeError("BLOCKED_RQ2_D3_R3_LEGACY_ENTRY_REVOCATION")
    return {
        "schema_version": "d3-r2-legacy-real-entrypoint-inventory-v1",
        "status": "PASS",
        "entrypoints": inventory,
        "executed": False,
        "before_sha256": BEFORE_SHA256,
        "after_sha256": observed,
        "modified_file_count": 1,
    }


def supersession_document_v1() -> dict[str, Any]:
    inventory = legacy_entrypoint_inventory_v1()
    return {
        "schema_version": "d3-r2-real-harness-supersession-v1",
        "status": "SUPERSEDED_UNAUTHORISED_FOR_REAL_EXECUTION",
        "d3_r2_execution_contract_authorised": False,
        "d3_r2_result_schema_authorised": False,
        "d3_r2_worker_reports_authorised": False,
        "old_parent_entry_blocked": True,
        "old_extractor_entry_blocked": True,
        "old_predictor_entry_blocked": True,
        "old_metric_entry_blocked": True,
        "blocking_before_path_resolution": True,
        "blocking_before_restricted_open": True,
        "blocking_before_business_import": True,
        "d3_r2_synthetic_utilities_preserved": True,
        "grouping_ledger_unchanged": True,
        "before_sha256": inventory["before_sha256"],
        "after_sha256": inventory["after_sha256"],
        "effective_real_entry": "execute_real_rq2d4_one_shot_v1_1",
    }
