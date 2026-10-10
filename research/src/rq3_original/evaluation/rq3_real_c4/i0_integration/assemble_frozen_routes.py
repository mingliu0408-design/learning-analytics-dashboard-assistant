#!/usr/bin/env python3
"""Future local-only merger for three successfully executed route journals.

This merger does not call a provider and is not run in I0. After separate
route-execution authority, it will consume the three terminal journals, take
only the RAG Specialist RAG bit, Memory Specialist Memory bit, and B4 Planning
bit, and emit the precomputed cache accepted by C4 REAL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
METHOD_ID = "R2V2-P3_RAG_MEMORY_SPECIALISTS"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} is not an object")
        rows.append(value)
    return rows


def successful_by_scenario(path: Path, expected_field: str) -> dict[str, dict[str, Any]]:
    rows = load_jsonl(path)
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("event") != "TERMINAL_SUCCESS":
            continue
        scenario_id = str(row.get("scenario_id") or "")
        result = row.get("output")
        if not scenario_id or not isinstance(result, Mapping):
            raise ValueError(f"Malformed success terminal in {path}")
        if expected_field not in result or type(result[expected_field]) is not bool:
            raise ValueError(f"Missing strict {expected_field} in {path}:{scenario_id}")
        if scenario_id in output:
            raise ValueError(f"Duplicate success terminal in {path}:{scenario_id}")
        output[scenario_id] = row
    return output


def assemble(
    *, rag_terminal: Path, memory_terminal: Path, b4_terminal: Path, output: Path
) -> dict[str, Any]:
    route_inputs = load_jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl")
    expected = {row["scenario_id"]: row for row in route_inputs if row["status"] == "READY_FOR_P3_ROUTE_EXECUTION"}
    rag = successful_by_scenario(rag_terminal, "rag_required")
    memory = successful_by_scenario(memory_terminal, "memory_required")
    b4 = successful_by_scenario(b4_terminal, "planning_required")
    if set(rag) != set(expected) or set(memory) != set(expected) or set(b4) != set(expected):
        raise ValueError("Terminal success populations do not equal the frozen Gate-ANSWER population")
    scenario_routes = []
    by_hash: dict[str, dict[str, bool]] = {}
    for scenario_id in sorted(expected):
        semantic_hash = expected[scenario_id]["semantic_input_sha256"]
        for terminal in (rag[scenario_id], memory[scenario_id], b4[scenario_id]):
            if terminal.get("semantic_input_sha256") != semantic_hash:
                raise ValueError(f"Semantic-input identity mismatch: {scenario_id}")
        bits = {
            "rag_required": rag[scenario_id]["output"]["rag_required"],
            "memory_required": memory[scenario_id]["output"]["memory_required"],
            "planning_required": b4[scenario_id]["output"]["planning_required"],
        }
        prior = by_hash.setdefault(semantic_hash, bits)
        if prior != bits:
            raise ValueError(f"Byte-identical semantic inputs received inconsistent routes: {semantic_hash}")
        scenario_routes.append(
            {
                "scenario_id": scenario_id,
                "semantic_input_sha256": semantic_hash,
                "method_id": METHOD_ID,
                **bits,
                "decision_id": "C4-P3-" + hashlib.sha256(
                    canonical_bytes({"semantic_input_sha256": semantic_hash, **bits})
                ).hexdigest()[:24],
                "source_bits": {
                    "rag": "RAG_SPECIALIST",
                    "memory": "MEMORY_SPECIALIST",
                    "planning": "B4_PLANNING_BIT_ONLY",
                },
            }
        )
    payload = {
        "schema_version": "c4-real-precomputed-p3-route-cache-v1",
        "method_id": METHOD_ID,
        "scenario_count": len(scenario_routes),
        "unique_semantic_input_count": len(by_hash),
        "scenario_routes": scenario_routes,
        "route_cache": {
            key: {**bits, "method_id": METHOD_ID, "provider_identity": "FROZEN_PARALLEL_ROUTE_JOURNALS"}
            for key, bits in sorted(by_hash.items())
        },
        "gold_used": False,
        "provider_calls_by_merger": 0,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"scenario_count": len(scenario_routes), "unique_semantic_input_count": len(by_hash), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag-terminal", type=Path, required=True)
    parser.add_argument("--memory-terminal", type=Path, required=True)
    parser.add_argument("--b4-terminal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(rag_terminal=args.rag_terminal, memory_terminal=args.memory_terminal, b4_terminal=args.b4_terminal, output=args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
