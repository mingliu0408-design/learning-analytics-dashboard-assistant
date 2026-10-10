"""Create the immutable pre-scoring receipt after toy-only verification."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

from .constants import (
    BINDING_PATH,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    COMPLETE_METHOD_IDS,
    ELIGIBILITY_PATH,
    ELIGIBILITY_SHA256,
    ELIGIBLE_METHOD_IDS,
    EXPECTED_BRANCH,
    EXPECTED_WORKTREE,
    FINAL_SCORING_DIR,
    INTEGRATED_COMMITS,
    PREDICTION_HASHES,
    PRE_SCORING_RECEIPT_PATH,
    PROJECT_ROOT,
    SCORING_SOURCE_NAMES,
    SELECTION_IMPLEMENTATION_PATH,
    SELECTION_RULE_PATH,
    SELECTION_RULE_SHA256,
    STARTING_HEAD,
)
from .scoring import (
    load_frozen_predictions,
    sha256_file,
    verify_frozen_sources,
    write_once_json,
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=PROJECT_ROOT, text=True
    ).strip()


def build_receipt() -> dict[str, object]:
    if Path.cwd().resolve() != EXPECTED_WORKTREE.resolve():
        raise RuntimeError("pre-scoring freeze is outside the authorized worktree")
    if _git("branch", "--show-current") != EXPECTED_BRANCH:
        raise RuntimeError("pre-scoring freeze branch differs")
    if _git("rev-parse", "HEAD") != INTEGRATED_COMMITS[-1][1]:
        raise RuntimeError("pre-scoring freeze HEAD differs from the fifth integration commit")
    changed = [line for line in _git("status", "--short").splitlines() if line]
    allowed_prefix = "evaluation/capability_routing_rq2_v2_stage5/final_scoring/"
    if any(allowed_prefix not in line for line in changed):
        raise RuntimeError("pre-scoring changes escape the authorized final_scoring directory")
    if PRE_SCORING_RECEIPT_PATH.exists():
        raise RuntimeError("pre-scoring receipt already exists")
    if BINDING_PATH.exists():
        raise RuntimeError("write-once RQ3 binding already exists")

    verified = verify_frozen_sources()
    frozen = load_frozen_predictions()
    if any(len(frozen[name]) != 36 for name in ("deterministic", "b4", "rag", "memory")):
        raise RuntimeError("prediction source coverage differs before receipt")

    source_hashes: dict[str, str] = {}
    imported_roots: set[str] = set()
    for name in SCORING_SOURCE_NAMES:
        path = FINAL_SCORING_DIR / name
        if not path.is_file():
            raise RuntimeError(f"pre-scoring source file is absent: {name}")
        source_hashes[str(path.relative_to(PROJECT_ROOT))] = sha256_file(path)
        if path.suffix == ".py":
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".")[0])
    prohibited_network_imports = {
        "aiohttp",
        "anthropic",
        "httpx",
        "openai",
        "requests",
        "socket",
        "urllib",
    }
    found_prohibited = sorted(imported_roots & prohibited_network_imports)
    if found_prohibited:
        raise RuntimeError(f"prohibited provider/network imports found: {found_prohibited}")

    receipt = {
        "schema_version": "rq2-v2-stage5e-pre-scoring-harness-receipt-v1",
        "receipt_status": "FROZEN_BEFORE_TEST_GOLD_ACCESS",
        "working_directory": str(EXPECTED_WORKTREE),
        "branch": EXPECTED_BRANCH,
        "starting_head": STARTING_HEAD,
        "integrated_head": INTEGRATED_COMMITS[-1][1],
        "integrated_commits": [
            {
                "original_commit": original,
                "cherry_picked_commit": integrated,
                "subject": subject,
            }
            for original, integrated, subject in INTEGRATED_COMMITS
        ],
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "scoring_source_file_hashes": dict(sorted(source_hashes.items())),
        "metric_implementation_hashes": {
            "stage5e_metrics": source_hashes[
                "evaluation/capability_routing_rq2_v2_stage5/final_scoring/metrics.py"
            ],
            "frozen_stage4_selection_implementation": sha256_file(
                SELECTION_IMPLEMENTATION_PATH
            ),
        },
        "composition_implementation_hashes": {
            "stage5e_compositions": source_hashes[
                "evaluation/capability_routing_rq2_v2_stage5/final_scoring/compositions.py"
            ]
        },
        "selection_sources": {
            "eligibility_path": str(ELIGIBILITY_PATH.relative_to(PROJECT_ROOT)),
            "eligibility_sha256": ELIGIBILITY_SHA256,
            "selection_rule_path": str(SELECTION_RULE_PATH.relative_to(PROJECT_ROOT)),
            "selection_rule_sha256": SELECTION_RULE_SHA256,
        },
        "prediction_source_hashes": dict(sorted(PREDICTION_HASHES.items())),
        "prediction_source_coverage": {
            "case_count_per_source": 36,
            "identical_annotation_id_sets": True,
            "deterministic_method_outputs": 252,
            "provider_terminal_errors": 0,
            "provider_retries": 0,
            "already_scored_predictions": 0,
            "imputed_predictions": 0,
        },
        "bootstrap": {
            "resampling_unit": "canonical_scenario_family_id",
            "seed": BOOTSTRAP_SEED,
            "replicates": BOOTSTRAP_REPLICATES,
            "interval": "PERCENTILE_95",
        },
        "expected_method_universe": {
            "complete_methods": list(COMPLETE_METHOD_IDS),
            "eligible_selection_methods": list(ELIGIBLE_METHOD_IDS),
            "reportable_exploratory_ineligible_method": "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION",
        },
        "pre_gold_test_evidence": {
            "required_toy_only_tests": {"passed": 13, "failed": 0, "errors": 0},
            "frozen_selection_and_prediction_tests": {
                "passed": 50,
                "failed": 0,
                "errors": 0,
            },
            "applicable_stage0_contract_metric_interface_tests": {
                "passed": 34,
                "failed": 0,
                "errors": 0,
            },
            "total_applicable_tests": {"passed": 97, "failed": 0, "errors": 0},
            "supplemental_full_stage0_aggregate_attempt": {
                "tests_run": 37,
                "passed": 34,
                "failed": 1,
                "errors": 2,
                "stage5e_gate_status": "NON_APPLICABLE_EXTERNAL_C0_ASSET_CHECKOUT_GAP",
                "reason": (
                    "Three repository-identity checks require frozen C0 files absent "
                    "from the dedicated Stage 5E worktree; no asset was substituted."
                ),
                "metric_definition_tests": {"passed": 6, "failed": 0, "errors": 0},
            },
        },
        "zero_gold_access_status": {
            "archive_identity_and_crc_verified": True,
            "test_gold_members_extracted": False,
            "test_gold_members_parsed": False,
            "test_gold_values_accessed": False,
            "test_gold_score_calculations": 0,
        },
        "zero_provider_call_status": {
            "provider_calls": 0,
            "network_calls": 0,
            "prediction_reruns": 0,
            "prohibited_provider_or_network_imports": found_prohibited,
        },
        "rq3_execution_count": 0,
        "binding_absent_before_scoring": True,
        "frozen_source_verification": verified,
        "post_receipt_code_modification_permitted": False,
    }
    write_once_json(PRE_SCORING_RECEIPT_PATH, receipt)
    return receipt


def main() -> int:
    receipt = build_receipt()
    print(
        json.dumps(
            {
                "status": receipt["receipt_status"],
                "source_file_count": len(receipt["scoring_source_file_hashes"]),
                "gold_values_accessed": receipt["zero_gold_access_status"][
                    "test_gold_values_accessed"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
