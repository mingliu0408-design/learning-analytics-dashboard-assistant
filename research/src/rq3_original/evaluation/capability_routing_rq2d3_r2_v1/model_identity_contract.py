"""Frozen C0/B0/B1/P1 identities for future D4 execution."""

from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any

from . import ROOT, sha256_file


CANDIDATE_INDEX = Path("semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl")
CANDIDATE_INDEX_SHA256 = "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9"
CANDIDATE_EMBEDDINGS = Path("semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz")
CANDIDATE_EMBEDDINGS_SHA256 = "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8"
MPNET_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
P1_POLICY = Path("evaluation/capability_routing_rq2b_v1/rq2b_final_p1_policy_v1.json")
P1_POLICY_SHA256 = "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942"
B1_REPRODUCTION_LEDGER = Path("evaluation/capability_routing_rq2b_v1/local_artifacts/b1_predictions/b1_original35_reproduction_v1.jsonl")
B1_REPRODUCTION_SHA256 = "801efb2c4ab4b32445e6ec2e51a6bac9173d566cb8136070b557e35d62ca5e80"


def _regular_non_symlink(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except FileNotFoundError:
        return False


def build_model_identity_contract_v1() -> dict[str, Any]:
    index_path = ROOT / CANDIDATE_INDEX
    embeddings_path = ROOT / CANDIDATE_EMBEDDINGS
    policy_path = ROOT / P1_POLICY
    b1_ledger_path = ROOT / B1_REPRODUCTION_LEDGER
    fixed_hashes = {
        index_path: CANDIDATE_INDEX_SHA256,
        embeddings_path: CANDIDATE_EMBEDDINGS_SHA256,
        policy_path: P1_POLICY_SHA256,
        b1_ledger_path: B1_REPRODUCTION_SHA256,
    }
    if any(not _regular_non_symlink(path) or sha256_file(path) != expected for path, expected in fixed_hashes.items()):
        raise RuntimeError("BLOCKED_RQ2_D3_R2_MODEL_IDENTITY")
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    labels = {str(row["final_semantic_label"]) for row in index_rows}
    if len(index_rows) != 62 or len(labels) != 16:
        raise RuntimeError("BLOCKED_RQ2_D3_R2_MODEL_IDENTITY")
    model_path = ROOT / "semantic_runtime/models/all-mpnet-base-v2" / MPNET_REVISION
    if not model_path.is_dir() or model_path.is_symlink():
        raise RuntimeError("BLOCKED_RQ2_D3_R2_MODEL_IDENTITY")
    b0 = json.loads((ROOT / "evaluation/capability_routing_rq2b_v1/rq2b_b0_contract_v1.json").read_text(encoding="utf-8"))
    b1 = json.loads((ROOT / "evaluation/capability_routing_rq2b_v1/rq2b_b1_reproduction_v1.json").read_text(encoding="utf-8"))
    p1 = json.loads(policy_path.read_text(encoding="utf-8"))
    if (
        b0.get("baseline_identity") != "B0_ORIGINAL_QUERY_C0_TOP1_HARD_ROUTE_NO_CONTEXT_RESOLUTION"
        or b0.get("conversation_history_read_count") != 0
        or b0.get("prepare_mode_cm_context_call_count") != 0
        or b0.get("structured_memory_read_count") != 0
        or b1.get("baseline_identity") != "B1_CURRENT_PRODUCTION_CONTEXT_RESOLUTION_C0_TOP1_HARD_ROUTE"
        or b1.get("reproduced_ledger_sha256") != B1_REPRODUCTION_SHA256
        or p1.get("selected_policy_id") != "P1_D05_SIGNAL_UNION"
        or not p1.get("immutable_for_future_rq2c_and_track_b")
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R2_MODEL_IDENTITY")
    return {
        "schema_version": "track-b-final-model-identity-contract-v1",
        "stage": "RQ2-D3-R2",
        "status": "FROZEN",
        "c0": {
            "identity": "C0_COSINE",
            "candidate_index_relative_path": str(CANDIDATE_INDEX),
            "candidate_index_sha256": CANDIDATE_INDEX_SHA256,
            "candidate_record_count": 62,
            "label_count": 16,
            "candidate_embeddings_relative_path": str(CANDIDATE_EMBEDDINGS),
            "candidate_embeddings_sha256": CANDIDATE_EMBEDDINGS_SHA256,
            "mpnet_revision": MPNET_REVISION,
            "aggregation": "MAX",
        },
        "b0": {
            "identity": b0["baseline_identity"],
            "original_query_only": True,
            "history_read_count": 0,
            "structured_memory_read_count": 0,
            "context_resolver_call_count": 0,
            "context_resolution_prediction": False,
            "router": "C0_COSINE_TOP1_HARD_ROUTE",
        },
        "b1": {
            "identity": b1["baseline_identity"],
            "frozen_development_ledger_sha256": B1_REPRODUCTION_SHA256,
            "router": "C0_COSINE_TOP1_HARD_ROUTE",
        },
        "p1": {
            "identity": "P1_D05_SIGNAL_UNION",
            "policy_relative_path": str(P1_POLICY),
            "policy_sha256": P1_POLICY_SHA256,
            "intent_map_changed": False,
            "need_signals_changed": False,
            "threshold_changed": False,
            "weights_changed": False,
            "guards_changed": False,
        },
        "model_training_performed": False,
        "production_integration": False,
    }
