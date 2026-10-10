"""Frozen scientific starting-state and input-identity validation."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from . import (
    C0_EMBEDDINGS_RELATIVE,
    C0_EMBEDDINGS_SHA256,
    C0_INDEX_RELATIVE,
    C0_INDEX_SHA256,
    COMBINED_SOURCE_RELATIVE,
    COMBINED_SOURCE_SHA256,
    GOLD_BUNDLE_SHA256,
    GROUPING_RELATIVE,
    GROUPING_SHA256,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    METRIC_IMPLEMENTATION_RELATIVE,
    METRIC_IMPLEMENTATION_SHA256,
    MPNET_REVISION,
    MODEL_RELATIVE,
    P1_POLICY_ID,
    P1_POLICY_RELATIVE,
    P1_POLICY_SHA256,
    ROOT,
    START_HEAD,
    STATISTICAL_CONTRACT_RELATIVE,
    STATISTICAL_CONTRACT_SHA256,
    TARGET_BRANCH,
    jsonl_rows_from_bytes,
    regular_non_symlink,
    sha256_file,
)


GOLD_MANIFEST_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/"
    "track_b_capability_gold_manifest_v1.json"
)
CONFIG_RELATIVE = Path("semantic_runtime/config/semantic_routing_config.json")


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


def _verified(path: Path, expected_sha256: str) -> dict[str, Any]:
    target = ROOT / path
    if not regular_non_symlink(target):
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    observed = sha256_file(target)
    if observed != expected_sha256:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    return {
        "relative_path": str(path),
        "sha256": observed,
        "size_bytes": os.lstat(target).st_size,
        "regular_non_symlink": True,
    }


def verify_starting_state_and_inputs() -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    if branch != TARGET_BRANCH or head != START_HEAD:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    if _git("remote") or _git("tag", "--list"):
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")

    identities = {
        "label_only_gold": _verified(LABEL_GOLD_RELATIVE, LABEL_GOLD_SHA256),
        "combined_source": _verified(COMBINED_SOURCE_RELATIVE, COMBINED_SOURCE_SHA256),
        "grouping": _verified(GROUPING_RELATIVE, GROUPING_SHA256),
        "statistical_contract": _verified(
            STATISTICAL_CONTRACT_RELATIVE, STATISTICAL_CONTRACT_SHA256
        ),
        "metric_implementation": _verified(
            METRIC_IMPLEMENTATION_RELATIVE, METRIC_IMPLEMENTATION_SHA256
        ),
        "c0_index": _verified(C0_INDEX_RELATIVE, C0_INDEX_SHA256),
        "c0_embeddings": _verified(C0_EMBEDDINGS_RELATIVE, C0_EMBEDDINGS_SHA256),
        "p1_policy": _verified(P1_POLICY_RELATIVE, P1_POLICY_SHA256),
    }

    label_rows = jsonl_rows_from_bytes((ROOT / LABEL_GOLD_RELATIVE).read_bytes())
    combined_rows = jsonl_rows_from_bytes((ROOT / COMBINED_SOURCE_RELATIVE).read_bytes())
    grouping_rows = jsonl_rows_from_bytes((ROOT / GROUPING_RELATIVE).read_bytes())
    index_rows = jsonl_rows_from_bytes((ROOT / C0_INDEX_RELATIVE).read_bytes())
    if not all(len(rows) == 48 for rows in (label_rows, combined_rows, grouping_rows)):
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    case_sets = [
        {str(row["review_case_id"]) for row in rows}
        for rows in (label_rows, combined_rows, grouping_rows)
    ]
    if any(len(values) != 48 for values in case_sets) or not (
        case_sets[0] == case_sets[1] == case_sets[2]
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    groups = Counter(str(row["contrast_group_id"]) for row in grouping_rows)
    if len(groups) != 24 or set(groups.values()) != {2}:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")
    if len(index_rows) != 62 or len({row["final_semantic_label"] for row in index_rows}) != 16:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")

    with np.load(ROOT / C0_EMBEDDINGS_RELATIVE, allow_pickle=False) as archive:
        shape = [int(value) for value in archive["embeddings"].shape]
        model_revision = str(archive["model_revision"].item())
    if shape != [62, 768] or model_revision != MPNET_REVISION:
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")

    manifest = json.loads((ROOT / GOLD_MANIFEST_RELATIVE).read_text(encoding="utf-8"))
    policy = json.loads((ROOT / P1_POLICY_RELATIVE).read_text(encoding="utf-8"))
    config = json.loads((ROOT / CONFIG_RELATIVE).read_text(encoding="utf-8"))
    if (
        manifest.get("gold_bundle_sha256") != GOLD_BUNDLE_SHA256
        or policy.get("selected_policy_id") != P1_POLICY_ID
        or config.get("aggregation") != "max"
        or config.get("model", {}).get("revision") != MPNET_REVISION
        or not (ROOT / MODEL_RELATIVE).is_dir()
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_FROZEN_INPUT_MISMATCH")

    from evaluation.capability_routing_rq2d3_r2_v1.fixed_statistical_execution import (
        verify_frozen_statistical_sources_v1,
    )

    statistical_sources = verify_frozen_statistical_sources_v1()
    return {
        "schema_version": "rq2d4-starting-state-v1",
        "status": "PASS",
        "starting_branch": branch,
        "starting_head": head,
        "remote_count": 0,
        "tag_count": 0,
        "gold_bundle_sha256": GOLD_BUNDLE_SHA256,
        "identities": identities,
        "label_record_count": 48,
        "combined_record_count": 48,
        "grouping_record_count": 48,
        "contrast_group_count": 24,
        "cases_per_group": 2,
        "c0_candidate_records": 62,
        "c0_label_count": 16,
        "c0_embedding_shape": shape,
        "c0_aggregation": "MAX",
        "mpnet_revision": MPNET_REVISION,
        "p1_policy": P1_POLICY_ID,
        "statistical_source_identities": statistical_sources,
    }


def main() -> int:
    print(json.dumps(verify_starting_state_and_inputs(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
