"""Repository-global, non-overridable D4 path authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ROOT


OUTPUT_ROOT_RELATIVE = Path("evaluation/capability_routing_rq2d4_v1/local_one_shot")
CONTROL_ROOT_RELATIVE = Path("evaluation/capability_routing_rq2d4_v1/local_control")
GLOBAL_LOCK_NAME = "TRACK_B_FINAL_EVALUATION_GLOBAL_ACCESS_V1.json"


@dataclass(frozen=True)
class FixedD4PathsV1:
    output_root: Path
    control_root: Path
    global_lock: Path
    feature_view: Path
    b0_predictions: Path
    b1_predictions: Path
    p1_predictions: Path
    result: Path


def resolve_fixed_rq2d4_paths_v1() -> FixedD4PathsV1:
    output = ROOT / OUTPUT_ROOT_RELATIVE
    control = ROOT / CONTROL_ROOT_RELATIVE
    return FixedD4PathsV1(
        output_root=output,
        control_root=control,
        global_lock=control / GLOBAL_LOCK_NAME,
        feature_view=output / "track_b_feature_only_view_v1.jsonl",
        b0_predictions=output / "track_b_b0_predictions_v1.jsonl",
        b1_predictions=output / "track_b_b1_predictions_v1.jsonl",
        p1_predictions=output / "track_b_p1_predictions_v1.jsonl",
        result=output / "rq2d4_track_b_final_results_v1.json",
    )


def fixed_d4_path_contract_document_v1() -> dict[str, Any]:
    return {
        "schema_version": "track-b-d4-fixed-path-contract-v1",
        "status": "FROZEN",
        "output_root_relative": str(OUTPUT_ROOT_RELATIVE),
        "control_root_relative": str(CONTROL_ROOT_RELATIVE),
        "global_lock_relative": str(CONTROL_ROOT_RELATIVE / GLOBAL_LOCK_NAME),
        "entry_accepts_path_override": False,
        "all_real_paths_repository_fixed": True,
        "output_root_git_ignored_required": True,
        "control_root_git_ignored_required": True,
    }
