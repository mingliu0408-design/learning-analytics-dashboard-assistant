"""Research-only RQ2-A capability-routing contracts.

Nothing in this package is imported by the production application.  The
package measures the frozen production path and prepares blinded development
material; it does not implement a production capability router.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RQ1_C1_HEAD = "d54776424acde3a54f829cfc7ddb291e497489f6"
RQ1_C1_PARENT = "d020b5e982730ac66dc10d48e6622553d62d0dd2"
RQ1_ROUTER_MANIFEST_RELATIVE = Path(
    "evaluation/learned_intent_ranking/rq1c_final/"
    "rq1c1_router_selection_manifest_v1.json"
)
RQ1_ROUTER_MANIFEST_SHA256 = (
    "337dd3d78d8c3d47926759a4670606f6a9e1912bf2f98c265ba8467005a04c9a"
)
RQ1_EXECUTION_MANIFEST_RELATIVE = Path(
    "evaluation/learned_intent_ranking/rq1c_final/"
    "rq1c1_execution_manifest_v1.json"
)
RQ1_EXECUTION_MANIFEST_SHA256 = (
    "8285d1ee17a29bf9aa0ecea35e45813ae33bb88cab7ce32c3fa6e656aa315dfb"
)
RQ1_FINAL_ROUTER = "C0_COSINE"
RQ1_FINAL_SELECTION = "C0_REMAINS_SELECTED"

PREDICTED_CAPABILITIES = (
    "dashboard_evidence",
    "course_retrieval",
    "episodic_memory",
    "planning",
    "safe_direct_response",
    "clarification",
)

DETERMINISTIC_GUARDS = (
    "privacy",
    "student_identity",
    "data_ownership",
    "external_action_permission",
    "provider_capability",
    "explicit_source_restriction",
    "unsupported_operation",
    "course_source_authority",
    "evidence_sufficiency",
)

MAXIMUM_RECENT_TURNS = 4
LOCAL_SYNTHETIC_SOURCE_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "rq2a_contract_synthetic_source_v1.jsonl"
)
LOCAL_BANK_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "capability_development_bank_v1.jsonl"
)
LOCAL_LINEAGE_RELATIVE = Path(
    "evaluation/capability_routing_v1/raw_case_bank/"
    "capability_lineage_v1.jsonl"
)
LOCAL_PROPOSAL_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_artifacts/"
    "capability_proposal_ledger_v1.jsonl"
)
LOCAL_BASELINE_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_artifacts/"
    "legacy_hard_routing_baseline_v1.jsonl"
)
LOCAL_REVIEW_A_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_review/"
    "reviewer_a_capability_review_v1.csv"
)
LOCAL_REVIEW_B_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_review/"
    "reviewer_b_capability_review_v1.csv"
)


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes used by every tracked safe artifact."""

    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_frozen_rq1_router(root: Path = ROOT) -> dict[str, Any]:
    """Validate only the tracked safe RQ1 manifests; never inspect local gold."""

    router_path = root / RQ1_ROUTER_MANIFEST_RELATIVE
    execution_path = root / RQ1_EXECUTION_MANIFEST_RELATIVE
    if sha256_file(router_path) != RQ1_ROUTER_MANIFEST_SHA256:
        raise RuntimeError("RQ1 router selection manifest hash mismatch")
    if sha256_file(execution_path) != RQ1_EXECUTION_MANIFEST_SHA256:
        raise RuntimeError("RQ1 execution manifest hash mismatch")
    router = json.loads(router_path.read_text(encoding="utf-8"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    required_router = {
        "status": "ROUTER_FROZEN",
        "frozen_selection": RQ1_FINAL_SELECTION,
        "selected_router": RQ1_FINAL_ROUTER,
        "decision_immutable": True,
        "post_final_tuning_authorised": False,
    }
    for key, expected in required_router.items():
        if router.get(key) != expected:
            raise RuntimeError(f"RQ1 router field mismatch: {key}")
    required_execution = {
        "status": "COMPLETED",
        "final_execution_count": 1,
        "retry_permitted": False,
        "raw_asset_open_count": 1,
    }
    for key, expected in required_execution.items():
        if execution.get(key) != expected:
            raise RuntimeError(f"RQ1 execution field mismatch: {key}")
    return {
        "router": router,
        "execution": execution,
        "router_manifest_sha256": RQ1_ROUTER_MANIFEST_SHA256,
        "execution_manifest_sha256": RQ1_EXECUTION_MANIFEST_SHA256,
    }


def safe_count_distribution(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value
