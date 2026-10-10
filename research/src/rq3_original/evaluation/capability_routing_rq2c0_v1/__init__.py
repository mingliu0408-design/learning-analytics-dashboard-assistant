"""RQ2-C0 contract-only mechanism audit and evaluability freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DOC_ROOT = ROOT / "docs/thesis_mainline/rq2"

STARTING_BRANCH = "research/rq2-b-capability-routing-development"
STARTING_HEAD = "5463ec162c15b62b5c394f221b656f902a609d04"
STARTING_PARENT = "c1e630ef1a414bcc9de56cefaf58c8455bb93b3d"
RESULT_BRANCH = "research/rq2-c0-tool-gate-mechanism-contract"
COMMIT_SUBJECT = "rq2-c0: freeze P2 mechanism contract and reachability audit"

SAFE_OUTPUT_FILENAMES = (
    "rq2b_result_identity_v1.json",
    "b0_context_metric_interpretation_v1.json",
    "episodic_memory_reachability_audit_v1.json",
    "episodic_memory_semantics_contract_v1.json",
    "clarification_gate_reachability_audit_v1.json",
    "tool_gate_schema_v1.json",
    "dual_gated_rag_contract_v1.json",
    "selective_episodic_state_use_contract_v1.json",
    "p2_condition_contract_v1.json",
    "p2_metric_contract_v1.json",
    "p2_mechanism_evaluability_v1.json",
    "rq2c0_preflight_report_v1.json",
)

DOC_FILENAMES = (
    "RQ2C0_RQ2B_RESULT_FREEZE_AND_ENTRY_DECISION.md",
    "RQ2C0_EPISODIC_MEMORY_SEMANTICS_AND_REACHABILITY.md",
    "RQ2C0_DUAL_GATED_RAG_CONTRACT.md",
    "RQ2C0_P2_CONDITION_AND_ABLATION_PROTOCOL.md",
    "RQ2C0_MECHANISM_EVALUABILITY_AND_LIMITATIONS.md",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
