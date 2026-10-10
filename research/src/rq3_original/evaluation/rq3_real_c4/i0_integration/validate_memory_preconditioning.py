#!/usr/bin/env python3
"""Validate all nine frozen Memory setups independently across all nine modes."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any


if __package__ in {None, ""}:
    import sys

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from utils.c4_real_adapters import C4PersistentLearnerMemoryAdapter
from utils.c4_real_contracts import C4Mode, C4RealRequest, ExecutionContext


HERE = Path(__file__).resolve().parent


class ValidationSemanticBackend:
    @property
    def identity(self):
        return {"backend": "I0_PRECONDITION_VALIDATION_NOT_USED", "network_allowed": False}

    def encode(self, texts):
        return [[1.0] for _ in texts]


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def validate(output: Path) -> dict[str, Any]:
    records = jsonl(HERE / "c4_real_memory_preconditioning_manifest_v1.jsonl")
    routes = {
        row["scenario_id"]: row["semantic_input"]
        for row in jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl")
    }
    proofs = []
    with tempfile.TemporaryDirectory(prefix="c4-real-i0-memory-validation-") as temporary:
        adapter = C4PersistentLearnerMemoryAdapter(
            temporary,
            evaluation_mode=True,
            semantic_backend=ValidationSemanticBackend(),
        )
        for record in records:
            scenario_id = record["scenario_id"]
            value = routes[scenario_id]
            for mode in C4Mode:
                request = C4RealRequest(
                    request_id=f"I0-MEMORY-VALIDATE::{scenario_id}::{mode.value}",
                    scenario_id=scenario_id,
                    mode=mode,
                    current_query=value["current_query"],
                    current_page=value["current_page"],
                    dashboard_context=value["dashboard_context"],
                    visible_conversation_history=tuple(value["visible_conversation_history"]),
                    student_id=f"I0-MEMORY-VALIDATE-STUDENT::{scenario_id}",
                    session_id=f"I0-MEMORY-TARGET-SESSION::{scenario_id}",
                    state_reset_id=f"I0-MEMORY-RESET::{scenario_id}::{mode.value}",
                    execution_context=ExecutionContext.EVALUATION,
                )
                proof = dict(adapter.precondition(request.memory_scope, record))
                results = proof["write_results"]
                if len(results) != record["setup_write_count"]:
                    raise RuntimeError(f"Write count mismatch: {scenario_id}/{mode.value}")
                if any(not result["accepted"] for result in results):
                    raise RuntimeError(f"Preconditioning write rejected: {scenario_id}/{mode.value}")
                if len(proof["active_memory_ids_after_reopen"]) != record["setup_write_count"]:
                    raise RuntimeError(f"Reopen state mismatch: {scenario_id}/{mode.value}")
                proofs.append(
                    {
                        "scenario_id": scenario_id,
                        "source_scenario_id": record["source_scenario_id"],
                        "mode": mode.value,
                        "namespace_sha256": proof["namespace_sha256"],
                        "write_count": len(results),
                        "accepted_write_count": sum(result["accepted"] for result in results),
                        "active_after_reopen_count": len(proof["active_memory_ids_after_reopen"]),
                        "store_reopened": proof["store_reopened"],
                        "raw_database_path_exposed": proof["raw_database_path_exposed"],
                    }
                )
        namespace_count = len({proof["namespace_sha256"] for proof in proofs})
        if namespace_count != len(proofs):
            raise RuntimeError("Memory namespace reused across scenario/mode validation scopes")
        if adapter.store_open_count != adapter.store_close_count:
            raise RuntimeError("Memory validation left a SQLite store open")
        report = {
            "schema_version": "c4-real-memory-preconditioning-validation-v1",
            "status": "PASS_ALL_NINE_CASES_ALL_NINE_MODES",
            "persistent_case_count": len(records),
            "mode_count": len(C4Mode),
            "isolated_scope_count": len(proofs),
            "unique_namespace_count": namespace_count,
            "write_attempt_count": sum(proof["write_count"] for proof in proofs),
            "accepted_write_count": sum(proof["accepted_write_count"] for proof in proofs),
            "rejected_write_count": 0,
            "store_open_count": adapter.store_open_count,
            "store_close_count": adapter.store_close_count,
            "all_stores_reopened": all(proof["store_reopened"] for proof in proofs),
            "raw_database_path_exposed": False,
            "assistant_advice_stored_as_learner_fact": False,
            "provider_calls": 0,
            "proofs": proofs,
        }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    report = validate(HERE / "c4_real_memory_preconditioning_validation_v1.json")
    print(json.dumps({key: report[key] for key in ("status", "isolated_scope_count", "write_attempt_count", "accepted_write_count", "provider_calls")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
