"""AST-verified revocation of all D3-R3 real-authority entry functions."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from . import ROOT, sha256_file
from .d3_r3_identity import AUTHORISED_LEGACY_FILES


SUPERSESSION = "SUPERSEDED_D3_R3_REAL_EXECUTION_ENTRY"


def _first_runtime_statement(function: ast.FunctionDef) -> ast.stmt | None:
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return body[0] if body else None


def legacy_entrypoint_inventory_document_v1() -> dict[str, Any]:
    entries = []
    for relative, metadata in sorted(AUTHORISED_LEGACY_FILES.items()):
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in metadata["function_names"]:
            function = functions.get(name)
            statement = _first_runtime_statement(function) if function else None
            if (
                not isinstance(statement, ast.Raise)
                or not isinstance(statement.exc, ast.Call)
                or not statement.exc.args
                or not isinstance(statement.exc.args[0], ast.Constant)
                or statement.exc.args[0].value != SUPERSESSION
            ):
                raise RuntimeError("BLOCKED_RQ2_D3_R4_LEGACY_ENTRY_REVOCATION")
        entries.append(
            {
                "relative_path": relative,
                "function_names": metadata["function_names"],
                "before_sha256": metadata["before_sha256"],
                "after_sha256": sha256_file(path),
                "entry_rejection": SUPERSESSION,
                "rejection_before_path_lock_import_open_or_directory_creation": True,
                "diff_summary": "one unconditional raise inserted at each listed function entry",
            }
        )
    return {
        "schema_version": "d3-r3-legacy-real-entrypoint-inventory-v1",
        "status": "PASS",
        "entry_count": sum(len(item["function_names"]) for item in entries),
        "file_count": len(entries),
        "entries": entries,
    }


def real_harness_supersession_document_v1() -> dict[str, Any]:
    inventory = legacy_entrypoint_inventory_document_v1()
    return {
        "schema_version": "d3-r3-real-harness-supersession-v1",
        "status": "FROZEN",
        "d3_r3_real_harness_status": "SUPERSEDED_UNAUTHORISED_FOR_REAL_EXECUTION",
        "entry_rejection": SUPERSESSION,
        "old_parent_blocked": True,
        "old_mutable_lock_updater_blocked": True,
        "old_feature_worker_blocked": True,
        "old_predictor_worker_blocked": True,
        "old_metric_worker_blocked": True,
        "old_credential_issuer_blocked": True,
        "historical_safe_outputs_changed": False,
        "historical_development_parity_changed": False,
        "inventory_file_count": inventory["file_count"],
    }
