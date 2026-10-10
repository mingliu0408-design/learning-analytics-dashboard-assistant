"""Post-freeze hidden-proposal diagnostics with enforced ordering."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from . import CAPABILITIES, ROOT, RQ2AR2BError, reject_prohibited_track_path, sha256_file


PRIMARY_PROPOSAL_RELATIVE = Path(
    "evaluation/capability_routing_v1/local_artifacts/"
    "capability_proposal_ledger_v1.jsonl"
)
SAFE_MANIFEST_RELATIVES = (
    Path("evaluation/capability_routing_v1/capability_review_packet_manifest_v1.json"),
    Path("evaluation/capability_routing_v1/rq2a_preflight_report_v1.json"),
    Path("evaluation/capability_routing_v1_r1b/reviewer_packet_manifest_v1_2.json"),
    Path("evaluation/capability_routing_v1_r1b/rq2a_r1b_preflight_report_v1.json"),
    Path("evaluation/capability_routing_v1_r1c/reviewer_packet_manifest_v1_3.json"),
    Path("evaluation/capability_routing_v1_r1c/rq2a_r1c_preflight_report_v1.json"),
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PostGoldDiagnosticError(RQ2AR2BError):
    pass


def verify_frozen_gold_members(
    root: Path, members: Mapping[str, Mapping[str, Any]]
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, metadata in members.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise PostGoldDiagnosticError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
        digest = sha256_file(path)
        if digest != metadata["sha256"]:
            raise PostGoldDiagnosticError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
        observed[relative] = digest
    return observed


def _proposal_references(value: Any) -> list[tuple[Path, str]]:
    references: list[tuple[Path, str]] = []
    if isinstance(value, dict):
        proposal_paths = [
            Path(item)
            for key, item in value.items()
            if isinstance(item, str)
            and "proposal" in key.lower()
            and item.lower().endswith(".jsonl")
        ]
        proposal_hashes = [
            item
            for key, item in value.items()
            if isinstance(item, str)
            and "proposal" in key.lower()
            and "sha256" in key.lower()
            and HEX64.fullmatch(item)
        ]
        if len(proposal_paths) == 1 and len(proposal_hashes) == 1:
            references.append((proposal_paths[0], proposal_hashes[0]))
        for child in value.values():
            references.extend(_proposal_references(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_proposal_references(child))
    return references


def _allowed_proposal_relative(relative: Path) -> bool:
    value = relative.as_posix()
    if relative == PRIMARY_PROPOSAL_RELATIVE:
        return True
    return (
        "proposal" in relative.name.lower()
        and (
            value.startswith("evaluation/capability_routing_v1_r1b/local_artifacts/")
            or value.startswith(
                "evaluation/capability_routing_v1_r1c/local_artifacts/"
            )
        )
    )


def governed_proposal_references(root: Path = ROOT) -> list[tuple[Path, str]]:
    references: set[tuple[Path, str]] = set()
    for relative in SAFE_MANIFEST_RELATIVES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        for candidate, digest in _proposal_references(value):
            reject_prohibited_track_path(candidate)
            if candidate.is_absolute() or not _allowed_proposal_relative(candidate):
                continue
            references.add((candidate, digest))
    return sorted(references, key=lambda item: (item[0].as_posix(), item[1]))


def _proposal_capabilities(row: Mapping[str, Any]) -> set[str]:
    for key in ("predicted_capabilities", "proposed_capabilities", "capability_proposal"):
        value = row.get(key)
        if isinstance(value, list):
            result = {str(item) for item in value}
            if result <= set(CAPABILITIES):
                return result
        if isinstance(value, dict):
            result = {
                capability
                for capability in CAPABILITIES
                if value.get(capability) in {True, "YES", 1}
            }
            return result
        if isinstance(value, str) and value.strip():
            result = {
                item.strip()
                for item in re.split(r"[;,]", value)
                if item.strip()
            }
            if result <= set(CAPABILITIES):
                return result
    if all(capability in row for capability in CAPABILITIES):
        return {
            capability
            for capability in CAPABILITIES
            if row[capability] in {True, "YES", 1}
        }
    raise PostGoldDiagnosticError("proposal ledger capability schema unavailable")


def _metrics(
    gold_rows: Iterable[Mapping[str, Any]],
    proposals: Mapping[str, set[str]],
) -> dict[str, Any]:
    rows = list(gold_rows)
    exact = 0
    tp = fp = fn = 0
    per_capability: dict[str, dict[str, int]] = {
        capability: {"tp": 0, "fp": 0, "fn": 0}
        for capability in CAPABILITIES
    }
    forbidden_violations = 0
    for row in rows:
        gold = {capability for capability in CAPABILITIES if row[capability] == "YES"}
        predicted = proposals[row["review_case_id"]]
        exact += predicted == gold
        tp += len(predicted & gold)
        fp += len(predicted - gold)
        fn += len(gold - predicted)
        forbidden_violations += bool(predicted & set(row["forbidden_capabilities"]))
        for capability in CAPABILITIES:
            if capability in predicted and capability in gold:
                per_capability[capability]["tp"] += 1
            elif capability in predicted:
                per_capability[capability]["fp"] += 1
            elif capability in gold:
                per_capability[capability]["fn"] += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    per_capability_metrics: dict[str, dict[str, Any]] = {}
    for capability, counts in per_capability.items():
        precision = ratio(counts["tp"], counts["tp"] + counts["fp"])
        recall = ratio(counts["tp"], counts["tp"] + counts["fn"])
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        per_capability_metrics[capability] = {
            **counts,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    return {
        "case_count": len(rows),
        "exact_set_accuracy": ratio(exact, len(rows)),
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        ),
        "per_capability": per_capability_metrics,
        "required_capability_recall": recall,
        "unnecessary_capability_rate": ratio(fp, tp + fp),
        "forbidden_capability_violation_rate": ratio(
            forbidden_violations, len(rows)
        ),
    }


def run_post_gold_diagnostic(
    *,
    root: Path,
    source_separated_gold_bundle_sha256: str,
    frozen_members: Mapping[str, Mapping[str, Any]],
    authentic_gold: list[Mapping[str, Any]],
    synthetic_gold: list[Mapping[str, Any]],
    authentic_registry: list[Mapping[str, Any]],
) -> dict[str, Any]:
    before = verify_frozen_gold_members(root, frozen_members)
    references = governed_proposal_references(root)
    base = {
        "schema_version": "post-gold-hidden-proposal-diagnostics-v1",
        "stage": "RQ2-A-R2B",
        "source_separated_gold_bundle_sha256": source_separated_gold_bundle_sha256,
        "gold_hashes_verified_before_unblinding": True,
        "gold_frozen_before_proposal_access": True,
        "proposal_used_to_form_gold": False,
        "threshold_tuning_performed": False,
        "overall_included_count": 57,
        "authentic_included_count": 22,
        "synthetic_included_count": 35,
        "authentic_context_missing_count": 3,
        "authentic_interpretation": [
            "DESCRIPTIVE_IN_SAMPLE_ONLY",
            "NOT_THRESHOLD_SELECTION",
        ],
        "synthetic_interpretation": "CONTROLLED_DEVELOPMENT_DIAGNOSTIC",
    }
    if len(references) != 1:
        after = verify_frozen_gold_members(root, frozen_members)
        if before != after:
            raise PostGoldDiagnosticError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
        return {
            **base,
            "status": "NOT_AVAILABLE_COMPLETE_PROPOSAL_LEDGER",
            "governed_complete_proposal_ledger_count": 0,
            "proposal_ledger_accessed": False,
            "metrics": None,
            "gold_hashes_unchanged_after_diagnostic": True,
        }

    relative, expected_sha256 = references[0]
    path = root / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or sha256_file(path) != expected_sha256
    ):
        after = verify_frozen_gold_members(root, frozen_members)
        if before != after:
            raise PostGoldDiagnosticError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
        return {
            **base,
            "status": "NOT_AVAILABLE_COMPLETE_PROPOSAL_LEDGER",
            "governed_complete_proposal_ledger_count": 0,
            "proposal_ledger_accessed": False,
            "metrics": None,
            "gold_hashes_unchanged_after_diagnostic": True,
        }

    ledger = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    all_gold = authentic_gold + synthetic_gold + authentic_registry
    expected_ids = {row["review_case_id"] for row in all_gold}
    proposal_by_id = {
        str(row.get("review_case_id") or ""): _proposal_capabilities(row)
        for row in ledger
    }
    if len(ledger) != 60 or set(proposal_by_id) != expected_ids or "" in proposal_by_id:
        after = verify_frozen_gold_members(root, frozen_members)
        if before != after:
            raise PostGoldDiagnosticError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
        return {
            **base,
            "status": "NOT_AVAILABLE_COMPLETE_PROPOSAL_LEDGER",
            "governed_complete_proposal_ledger_count": 0,
            "proposal_ledger_accessed": True,
            "candidate_ledger_sha256": expected_sha256,
            "candidate_record_count": len(ledger),
            "metrics": None,
            "gold_hashes_unchanged_after_diagnostic": True,
        }
    included = authentic_gold + synthetic_gold
    metrics = {
        "overall_included": _metrics(included, proposal_by_id),
        "authentic_included": _metrics(authentic_gold, proposal_by_id),
        "synthetic_included": _metrics(synthetic_gold, proposal_by_id),
        "authentic_context_missing": _metrics(
            authentic_registry, proposal_by_id
        ),
    }
    after = verify_frozen_gold_members(root, frozen_members)
    if before != after:
        raise PostGoldDiagnosticError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    return {
        **base,
        "status": "PASS",
        "governed_complete_proposal_ledger_count": 1,
        "proposal_ledger_accessed": True,
        "proposal_ledger_sha256": expected_sha256,
        "proposal_record_count": 60,
        "metrics": metrics,
        "gold_hashes_unchanged_after_diagnostic": True,
    }
