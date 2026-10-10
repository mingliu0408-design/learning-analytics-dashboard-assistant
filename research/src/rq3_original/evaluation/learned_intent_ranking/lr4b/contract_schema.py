"""Frozen, standard-library-only schema constants for the RQ1-A contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


CONTRACT_VERSION = "lr4b-experiment-contract-v1"
QUERY_ONLY_V1 = "QUERY_ONLY_V1"
STRUCTURED_CONTEXT_V1 = "STRUCTURED_CONTEXT_V1"
CONTEXT_MODES = (QUERY_ONLY_V1, STRUCTURED_CONTEXT_V1)

MODEL_INPUT_FIELDS: Mapping[str, tuple[str, ...]] = {
    QUERY_ONLY_V1: ("query",),
    STRUCTURED_CONTEXT_V1: (
        "question_anchor_for_review",
        "previous_turns_for_review",
        "utterance_for_review",
    ),
}

FORBIDDEN_MODEL_INPUT_FIELDS = frozenset({
    "final_target_intent",
    "researcher_final_target_intent",
    "assistant_final_target_intent",
    "proposed_intent",
    "mapping_status",
    "review_decision",
    "review_rationale",
    "researcher_notes",
    "assistant_review_rationale",
    "secondary_dialogue_act",
    "annotation_status",
    "annotation_method",
    "gold_label_claim",
    "intended_use",
    "pairwise_activation_scenario",
})

LEDGER_FIELDS = (
    "record_id",
    "source_dataset_id",
    "intent_label",
    "context_mode",
    "query_source_sha256",
    "question_anchor_source_sha256",
    "previous_turns_source_sha256",
    "representation_sha256",
    "representation_character_count",
    "scenario_membership",
    "annotation_reliability",
)

BASELINE = {
    "starting_branch": "thesis/mainline",
    "starting_head": "8d3b6d6850bbf22c676371f613ad62e2389bd1e7",
    "source_pre_governance_fingerprint": "20fe1eb98d5b78f64bcb97f3c23f095eef26835eb2a4d3feecf6686e281f6f1a",
    "tracked_baseline_tree_fingerprint": "ccd20988d7112e9592d2826b454ba6030bdf16a8fa3aea1a3ac01aaed4871bf5",
    "protected_source_manifest_fingerprint": "f08d1feb9e7025621f5639d61abbc0d1ffbee1c4a1ab0f2cb279fc08fdc4e745",
}

EXPECTED_KEY_FILE_HASHES = {
    "Home.py": "3ba35aabb3bdd3fb8f08fd2926fac2ee189b13d66105b2153cd09682b41206be",
    "utils/c_full_service.py": "ceaad67997bd1104bb502641ca8f7339b3ecdffa484407774e7fc646c0e9728d",
    "pages/1 - 👨🏼‍💻 Individual Feedback.py": "8ea0772962971964afe40e14ec58e79b6b24aadc23091b6ec772628734acfe99",
}

EXPECTED_EEDI_HASHES = {
    "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_codebook_researcher_confirmed_v1.json": "74d9b5e8bf7822f7183dfe071651f7c3d5fc4bc965f3382fc0f70299796d5d51",
    "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_researcher_confirmed_300.csv": "3210566d015c87b896be9a7b6faa6a650b643a523da59f92a3c145a3cf1474c0",
    "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_confirmed_candidate_subset_256.csv": "5959b2bd343fd10ae180c641ddc72d5af0396956875ad69a2162ffeaeb25d9d3",
}

EXPECTED_COUNTS = {
    "full_researcher_confirmed": 300,
    "retained_secondary": 256,
    "excluded_secondary": 44,
    "direct_shared_intent": 72,
    "contextual_shared_intent": 184,
    "expanded_train": 318,
    "pairwise_capable": 316,
    "pairwise_labels": 14,
    "non_pairwise_singletons": 2,
    "query_only": 134,
    "structured_context": 184,
}
EXPECTED_SCENARIOS = {"V0": 58, "V1": 131, "V2": 154, "V3": 316}
FIVE_SEEDS = (20260813, 20260814, 20260815, 20260816, 20260817)

FINAL_GOLD_ROOT = PurePosixPath(
    "evaluation/learned_intent_ranking/lr1r/primary_v3_input"
)
LOCAL_LEDGER_PATH = PurePosixPath(
    "evaluation/learned_intent_ranking/lr4b/local_artifacts/"
    "lr4b_record_representation_ledger_v1.jsonl"
)

SAFE_JSON_FILENAMES = (
    "lr4b_experiment_contract_v1.json",
    "lr4b_input_inventory_summary_v1.json",
    "lr4b_data_scenario_summary_v1.json",
    "lr4b_context_representation_summary_v1.json",
    "lr4b_preflight_report_v1.json",
)

DOC_PATHS = (
    "docs/thesis_mainline/rq1/RQ1A_LR4B_EXPERIMENT_CONTRACT.md",
    "docs/thesis_mainline/rq1/RQ1A_CONTEXT_REPRESENTATION_CONTRACT.md",
    "docs/thesis_mainline/rq1/RQ1A_BASELINE_COMPARABILITY_CONTRACT.md",
)

PROTECTED_ROOTS = (
    "utils",
    "tests",
    "semantic_runtime/config",
    "semantic_runtime/artifacts",
    "evaluation/learned_intent_ranking/lr1",
    "evaluation/learned_intent_ranking/lr1r",
    "evaluation/learned_intent_ranking/lr2",
    "evaluation/learned_intent_ranking/lr2r",
    "evaluation/learned_intent_ranking/lr3",
    "evaluation/learned_intent_ranking/lr3r",
    "evaluation/learned_intent_ranking/lr3s",
    "evaluation/learned_intent_ranking/lr4a",
)


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic, human-reviewable JSON bytes."""

    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalised_relative_path(relative_path: str | PurePosixPath) -> PurePosixPath:
    raw = str(relative_path).replace("\\", "/")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("path must be a non-empty project-relative path")
    return candidate


def is_final_gold_path(relative_path: str | PurePosixPath) -> bool:
    candidate = _normalised_relative_path(relative_path)
    return candidate == FINAL_GOLD_ROOT or FINAL_GOLD_ROOT in candidate.parents


def authorised_project_path(
    project_root: str | Path,
    relative_path: str | PurePosixPath,
) -> Path:
    """Resolve a project-relative path lexically and reject final-gold scope."""

    candidate = _normalised_relative_path(relative_path)
    if is_final_gold_path(candidate):
        raise PermissionError("RQ1-A final-gold boundary rejected the requested path")
    root = Path(os.path.abspath(os.fspath(project_root)))
    return root.joinpath(*candidate.parts)


def validate_strict_scenarios(scenarios: Mapping[str, Iterable[str]]) -> bool:
    expected_order = ("V0", "V1", "V2", "V3")
    if tuple(sorted(scenarios)) != tuple(sorted(expected_order)):
        return False
    sets = [set(scenarios[name]) for name in expected_order]
    return sets[0] < sets[1] < sets[2] < sets[3]


def keyword_single_candidate_ranking(selected_candidate: str) -> tuple[str, ...]:
    """Return K0's degenerate ranking: exactly the production-selected intent."""

    candidate = str(selected_candidate).strip()
    if not candidate:
        raise ValueError("selected candidate must be non-empty")
    return (candidate,)


def keyword_single_candidate_reciprocal_rank(
    selected_candidate: str,
    gold_intent: str,
) -> float:
    """K0 MRR contribution; by contract it equals Top-1 correctness."""

    ranking = keyword_single_candidate_ranking(selected_candidate)
    gold = str(gold_intent).strip()
    if not gold:
        raise ValueError("gold intent must be non-empty")
    return 1.0 if ranking[0] == gold else 0.0
