"""Fail-closed RQ2-B result and local-ledger identity verification."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from evaluation.capability_routing_rq2b_v1.gold_preflight import load_and_validate_gold

from . import ROOT, STARTING_HEAD, STARTING_PARENT, sha256_file


RQ2B_REVIEW_ZIP = (
    Path.home()
    / "Downloads"
    / "RQ2_B_CAPABILITY_ROUTING_DEVELOPMENT_REVIEW_2026-08-26.zip"
)
EXPECTED_REVIEW_ZIP_SHA256 = (
    "00b27c9f5d496b2ec8111624e4d3497d2bbacde533d542fd15ac3d58214a540a"
)
EXPECTED_GOLD_BUNDLE_SHA256 = (
    "9957bbea0e723203718155f8974db5476c23d8a5239a4c66e76b2ade9a5ea18c"
)
RQ2B_CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/rq2b_output_checksums_v1.sha256"
)

EXPECTED_RESULT_HASHES: Mapping[str, str] = {
    "rq2b_final_p1_policy_v1.json": "74236e7166cfa2cc73447f873150812b9700dfcc14e5209e8b157be3c7210942",
    "rq2b_synthetic_comparison_v1.json": "7962889b3d7452ad304f6ee1614f8a0b7c14d8b55e3f0eff85466dc45506dfd6",
    "rq2b_authentic_descriptive_results_v1.json": "6c5ec8e7a3c227bf346872f4b52fb49b04ad9da1d80e1d7ae1299d1236464b75",
    "rq2b_context_missing_diagnostic_v1.json": "383f72ad84019aaefde6cab1b0a4869c31b6e9e29d9d676702b5c90b917a7a6a",
    "rq2b_error_analysis_v1.json": "1ecc8d1a67e3a7d6072096ea8de8917a09581718e6a21ca5b7ba36b9c58a15ab",
    "rq2b_development_uncertainty_v1.json": "f61f11159a5f525a8682565da69c6c08018e18b332dd9a86796e5b67f74fee8a",
    "rq2b_nested_oof_results_v1.json": "8d540a4e232a0ed99c1d4f68c546cd0631668beebeb118ff66dafd57a85b8933",
    "rq2b_validation_report_v1.json": "83bd1f3c26d866cdf449512b180a2e5e265bd86483634cea31870882843daca2",
}

EXPECTED_LOCAL_LEDGER_HASHES: Mapping[str, str] = {
    "evaluation/capability_routing_rq2b_v1/local_artifacts/b0_predictions/b0_synthetic_v1.jsonl": "390619788124421bdd2b5347d1644743bd0b0fd45acc487cf98fccda26e685ca",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/b1_predictions/b1_synthetic_v1.jsonl": "c56af19bf084d3e5c5d2cf7bb6323ea4eafe38bc3f2a138463864256eb5d2d02",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/synthetic_P1_D05_SIGNAL_UNION.jsonl": "75ab3d6c1ff4d58b652d5b089ff6f2b289ada756cfc4640cb1cc2df8040916ae",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/authentic_final_policy_v1.jsonl": "070c034bf8de35f6dd9465e1a858916c6fc39dfeffaecbfd16ceed10cff7951f",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/p1_predictions/registry_final_policy_v1.jsonl": "82a42f1b3a48c10efe8a193ad273560c5141fc6a3e542219f8a8efcfff453e4e",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/envelopes/context_envelopes_v1.jsonl": "63a458712cfd6cf16e60d114a601617168703919fd5e8cc5d2207ae9d860a6a0",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/c0_score_vectors/c0_full_score_vectors_v1.jsonl": "0f418a12c3a5f1a0fcbf473ae718022ab3d7a4efeca52acc739b240c36629342",
    "evaluation/capability_routing_rq2b_v1/local_artifacts/error_ledgers/metric_join_rows_v1.json": "497919bf72d32eb23666ca989de748b201a75aaf4f2c7ba2c8527fe7615bd1a9",
}


class RQ2C0IdentityError(RuntimeError):
    """Raised when an immutable RQ2-B input no longer matches."""


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    return value


def verify_starting_commit() -> dict[str, Any]:
    if _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT:
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    return {
        "approved_head": STARTING_HEAD,
        "approved_parent": STARTING_PARENT,
        "approved_head_is_ancestor": True,
    }


def verify_rq2b_output_checksums() -> int:
    manifest = ROOT / RQ2B_CHECKSUM_RELATIVE
    seen: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH") from exc
        path = ROOT / relative
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected)
            or relative in seen
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected
        ):
            raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
        seen.add(relative)
    if len(seen) != 36:
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    return len(seen)


def verify_result_hashes() -> dict[str, str]:
    base = ROOT / "evaluation/capability_routing_rq2b_v1"
    observed: dict[str, str] = {}
    for name, expected in EXPECTED_RESULT_HASHES.items():
        path = base / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
        observed[name] = expected
    policy = _load_json(base / "rq2b_final_p1_policy_v1.json")
    if (
        policy.get("selected_policy_id") != "P1_D05_SIGNAL_UNION"
        or policy.get("authentic_used_for_selection") is not False
        or policy.get("immutable_for_future_rq2c_and_track_b") is not True
        or policy.get("frozen_before_authentic_evaluation") is not True
    ):
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    return observed


def verify_local_ledgers() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in EXPECTED_LOCAL_LEDGER_HASHES.items():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise RQ2C0IdentityError("BLOCKED_RQ2_C0_LOCAL_LEDGER_IDENTITY")
        observed[relative] = expected
    return observed


def build_rq2b_identity() -> dict[str, Any]:
    start = verify_starting_commit()
    if not RQ2B_REVIEW_ZIP.is_file() or RQ2B_REVIEW_ZIP.is_symlink():
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    if sha256_file(RQ2B_REVIEW_ZIP) != EXPECTED_REVIEW_ZIP_SHA256:
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    result_hashes = verify_result_hashes()
    checksum_count = verify_rq2b_output_checksums()
    ledgers = verify_local_ledgers()
    gold = load_and_validate_gold(ROOT)
    if gold.identity.get("gold_bundle_sha256") != EXPECTED_GOLD_BUNDLE_SHA256:
        raise RQ2C0IdentityError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    return {
        "schema_version": "rq2c0-rq2b-result-identity-v1",
        "stage": "RQ2-C0",
        "status": "PASS",
        **start,
        "rq2b_review_zip_sha256": EXPECTED_REVIEW_ZIP_SHA256,
        "rq2b_output_checksum_count": checksum_count,
        "safe_result_sha256": dict(sorted(result_hashes.items())),
        "local_ledger_sha256": dict(sorted(ledgers.items())),
        "local_ledger_count": len(ledgers),
        "gold_bundle_sha256": EXPECTED_GOLD_BUNDLE_SHA256,
        "p1_final_policy": "P1_D05_SIGNAL_UNION",
        "p1_policy_immutable": True,
        "synthetic_selection_only": True,
        "authentic_descriptive_only": True,
        "track_b_unused": True,
        "rq2b_metrics_recomputed": False,
        "rq2b_results_modified": False,
    }
