"""Fail-closed loading of the frozen RQ1-B governed inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from . import (
    FINAL_GOLD_ROOT,
    ROOT,
    SCENARIO_COUNTS,
    SCENARIO_ORDER,
    STARTING_HEAD,
    STARTING_PARENT,
    TARGET_BRANCH,
)


LR3 = ROOT / "evaluation/learned_intent_ranking/lr3"
if str(LR3) not in sys.path:
    sys.path.insert(0, str(LR3))

from data_loader import (  # type: ignore[import-not-found]  # noqa: E402
    load_dev_views,
    load_frozen_candidate_artifacts,
    resolve_dev_records,
)

from evaluation.learned_intent_ranking.lr4b.build_lr4b_contract import (  # noqa: E402
    analyse_contract,
)
from evaluation.learned_intent_ranking.lr4b.context_representation import (  # noqa: E402
    build_query_only_representation,
    build_structured_context_representation,
    normalise_source_field,
    representation_sha256,
)


EXPECTED_INPUT_HASHES = {
    "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl":
        "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
    "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz":
        "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8",
    "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
    "ranker_expanded_train_manifest_candidate_v2.jsonl":
        "623bcdeaad62ae20559c616dc57aedfb22bd2d006f0beb6888da88d549c40805",
    "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
    "ranker_data_volume_scenarios_candidate_v2.json":
        "b5acd5320ec5e5096277c256df9fb9bb3c02446744baeef8d1236df4d556f6c1",
    "evaluation/learned_intent_ranking/lr1r/ranker_dev_manifest_candidate_v2.jsonl":
        "7765ffbbe48fcde543b60561f22a03cef596235af07eed58540aacb64334f09f",
    "evaluation/learned_intent_ranking/lr2r/ranker_dev_evaluation_views_v1.json":
        "e1a9a6c41a7509d1e52f31818c71db2e3628bdc02bc25786b03c6831a34c3986",
}

EXPANDED_TRAIN = PurePosixPath(
    "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
    "ranker_expanded_train_manifest_candidate_v2.jsonl"
)
SCENARIO_MEMBERSHIP = PurePosixPath(
    "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
    "ranker_data_volume_scenarios_candidate_v2.json"
)
APPROVED_INDEX = PurePosixPath(
    "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
)
RETAINED_EEDI = PurePosixPath(
    "evaluation/learned_intent_ranking/lr4a/training_data_input/"
    "eedi_stage_e4_confirmed_candidate_subset_256.csv"
)
DEV_MANIFEST = PurePosixPath(
    "evaluation/learned_intent_ranking/lr1r/ranker_dev_manifest_candidate_v2.jsonl"
)
NEGATIVE_POLICY = PurePosixPath(
    "evaluation/learned_intent_ranking/lr1r/"
    "ranker_negative_pair_policy_candidate_v1.json"
)
EFFECTIVE_CONTRACT = PurePosixPath(
    "evaluation/learned_intent_ranking/lr4b_r1/lr4b_experiment_contract_v1_1.json"
)

EXPECTED_LEDGER_FINGERPRINT = (
    "d33d9badd56edca675c48d865dbec5a0d19f2b9e6328e785243dd7cef3317007"
)


class RQ1BInputError(RuntimeError):
    """Raised without echoing governed source text."""


class FinalGoldBoundaryError(PermissionError):
    """Raised before any filesystem operation on the prohibited scope."""


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalised_relative(relative_path: str | PurePosixPath) -> PurePosixPath:
    raw = str(relative_path).replace("\\", "/")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("path must be a non-empty project-relative path")
    return candidate


def reject_final_gold_path(relative_path: str | PurePosixPath) -> PurePosixPath:
    """Lexically reject final gold before Path construction or filesystem access."""

    candidate = _normalised_relative(relative_path)
    if candidate == FINAL_GOLD_ROOT or FINAL_GOLD_ROOT in candidate.parents:
        raise FinalGoldBoundaryError("RQ1-B final-gold boundary rejected a path")
    return candidate


def authorised_path(relative_path: str | PurePosixPath) -> Path:
    candidate = reject_final_gold_path(relative_path)
    return ROOT.joinpath(*candidate.parts)


def read_json(relative_path: str | PurePosixPath) -> Any:
    return json.loads(authorised_path(relative_path).read_text(encoding="utf-8-sig"))


def read_jsonl(relative_path: str | PurePosixPath) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in authorised_path(relative_path)
        .read_text(encoding="utf-8-sig")
        .splitlines()
        if line
    ]


def read_csv(relative_path: str | PurePosixPath) -> list[dict[str, str]]:
    with authorised_path(relative_path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False
    )


def verify_git_starting_contract() -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", f"{STARTING_HEAD}^")
    remote = _git("remote")
    tags = _git("tag", "--list")
    ancestor = _git("merge-base", "--is-ancestor", STARTING_HEAD, "HEAD")
    if any(result.returncode for result in (branch, head, parent, remote, tags)):
        raise RQ1BInputError("Git starting-state command failed")
    current_branch = branch.stdout.decode("utf-8").strip()
    current_head = head.stdout.decode("ascii").strip()
    actual_parent = parent.stdout.decode("ascii").strip()
    remote_count = len(remote.stdout.splitlines())
    tag_count = len(tags.stdout.splitlines())
    if current_branch != TARGET_BRANCH or actual_parent != STARTING_PARENT:
        raise RQ1BInputError("Git branch or ancestry gate mismatch")
    if ancestor.returncode != 0 or remote_count or tag_count:
        raise RQ1BInputError("Git ancestry, remote, or tag gate mismatch")
    return {
        "starting_branch": "research/rq1-a-r1-contract-repair",
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "target_branch": TARGET_BRANCH,
        "current_head": current_head,
        "remote_count": remote_count,
        "tag_count": tag_count,
    }


def verify_frozen_inputs() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for relative, expected in sorted(EXPECTED_INPUT_HASHES.items()):
        path = authorised_path(relative)
        if not path.is_file() or path.is_symlink():
            raise RQ1BInputError("frozen input is missing or not a regular file")
        actual = sha256_file(path)
        if actual != expected:
            raise RQ1BInputError("frozen input hash mismatch")
        rows.append(
            {
                "relative_path": relative,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": True,
            }
        )
    contract = read_json(EFFECTIVE_CONTRACT)
    if (
        contract.get("schema_version") != "lr4b-experiment-contract-v1.1"
        or contract.get("status") != "EFFECTIVE_CONTRACT_FROZEN"
        or contract.get("rq1b_must_use_v1_1") is not True
    ):
        raise RQ1BInputError("effective RQ1-A-R1 contract mismatch")
    invariants = contract.get("invariants") or {}
    if invariants.get("final_gold_accessed") is not False:
        raise RQ1BInputError("upstream final-gold state is not false")
    return {
        "contract_schema": contract["schema_version"],
        "contract_status": contract["status"],
        "input_count": len(rows),
        "inputs": rows,
        "all_hashes_match": True,
    }


def _membership_fingerprint(values: Iterable[str]) -> str:
    projection = "".join(f"{value}\n" for value in sorted(values))
    return sha256_bytes(projection.encode("utf-8"))


def load_governed_bundle() -> dict[str, Any]:
    """Resolve all authorised TRAIN/DEV data while returning raw text only in memory."""

    git_gate = verify_git_starting_contract()
    input_gate = verify_frozen_inputs()
    contract_outputs, contract_ledger = analyse_contract(ROOT)
    summary = contract_outputs["lr4b_context_representation_summary_v1.json"]
    if summary["representation_ledger_fingerprint"] != EXPECTED_LEDGER_FINGERPRINT:
        raise RQ1BInputError("representation ledger fingerprint drift")

    expanded = read_jsonl(EXPANDED_TRAIN)
    scenarios_payload = read_json(SCENARIO_MEMBERSHIP)
    approved = read_jsonl(APPROVED_INDEX)
    retained = read_csv(RETAINED_EEDI)
    expanded_by_id = {str(row["record_id"]): row for row in expanded}
    approved_by_id = {str(row["example_id"]): row for row in approved}
    retained_by_id = {str(row["record_id"]): row for row in retained}
    ledger_by_id = {str(row["record_id"]): row for row in contract_ledger}
    scenario_ids: dict[str, list[str]] = {}
    for scenario in scenarios_payload["scenarios"]:
        scenario_id = str(scenario["scenario_id"])
        ids = [str(value) for value in scenario["record_ids"]]
        if len(ids) != SCENARIO_COUNTS.get(scenario_id) or len(set(ids)) != len(ids):
            raise RQ1BInputError("scenario membership count mismatch")
        scenario_ids[scenario_id] = ids
    if tuple(scenario_ids) != SCENARIO_ORDER:
        raise RQ1BInputError("scenario order mismatch")
    sets = [set(scenario_ids[name]) for name in SCENARIO_ORDER]
    if not (sets[0] < sets[1] < sets[2] < sets[3]):
        raise RQ1BInputError("scenario nesting mismatch")

    records: list[dict[str, Any]] = []
    projection_rows: list[str] = []
    for record_id in sorted(expanded_by_id):
        manifest = expanded_by_id[record_id]
        if record_id in approved_by_id:
            source = approved_by_id[record_id]
            representation = build_query_only_representation(str(source["query"]))
            context_mode = "QUERY_ONLY_V1"
        elif record_id in retained_by_id:
            source = retained_by_id[record_id]
            if source["final_mapping_status"] == "contextual_shared_intent":
                representation = build_structured_context_representation(
                    question_anchor_for_review=source["question_anchor_for_review"],
                    previous_turns_for_review=source["previous_turns_for_review"],
                    utterance_for_review=source["utterance_for_review"],
                )
                context_mode = "STRUCTURED_CONTEXT_V1"
            elif source["final_mapping_status"] == "direct_shared_intent":
                representation = build_query_only_representation(
                    source["utterance_for_review"]
                )
                context_mode = "QUERY_ONLY_V1"
            else:
                raise RQ1BInputError("authorised source mapping status mismatch")
        else:
            raise RQ1BInputError("expanded record does not resolve to an authorised source")
        digest = representation_sha256(representation)
        ledger_row = ledger_by_id.get(record_id)
        if (
            ledger_row is None
            or digest != ledger_row["representation_sha256"]
            or context_mode != ledger_row["context_mode"]
        ):
            raise RQ1BInputError("representation reconstruction mismatch")
        projection_rows.append(f"{record_id}\t{digest}\n")
        records.append(
            {
                **manifest,
                "representation": representation,
                "representation_sha256": digest,
                "context_mode": context_mode,
                "scenario_membership": tuple(ledger_row["scenario_membership"]),
            }
        )
    fingerprint = sha256_bytes("".join(projection_rows).encode("utf-8"))
    if fingerprint != EXPECTED_LEDGER_FINGERPRINT or len(records) != 318:
        raise RQ1BInputError("representation ledger count or fingerprint mismatch")

    frozen = load_frozen_candidate_artifacts()
    if (
        len(frozen["index_records"]) != 62
        or len(frozen["production_labels"]) != 16
        or frozen["config"].get("aggregation") != "max"
    ):
        raise RQ1BInputError("candidate universe drift")
    dev_records = resolve_dev_records(authorised_path(DEV_MANIFEST))
    view_ids = load_dev_views(dev_records)
    if {name: len(ids) for name, ids in view_ids.items()} != {
        "VIEW_A_PAIRWISE_SEEN": 79,
        "VIEW_B_SINGLETON_UNSEEN": 5,
        "VIEW_C_MIXED": 84,
    }:
        raise RQ1BInputError("DEV view drift")

    return {
        "git_gate": git_gate,
        "input_gate": input_gate,
        "records": records,
        "records_by_id": {row["record_id"]: row for row in records},
        "scenario_ids": scenario_ids,
        "scenario_membership_fingerprints": {
            name: _membership_fingerprint(ids) for name, ids in scenario_ids.items()
        },
        "approved_index": approved,
        "frozen": frozen,
        "dev_records": dev_records,
        "view_ids": view_ids,
        "representation_ledger_fingerprint": fingerprint,
        "negative_policy": read_json(NEGATIVE_POLICY),
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "final_gold_used": False,
        "final_gold_tuning": False,
    }


PROTECTED_PATHS = (
    "Home.py",
    "pages",
    "utils",
    "tests",
    "semantic_runtime/artifacts",
    "semantic_runtime/config",
    "evaluation/learned_intent_ranking/lr1",
    "evaluation/learned_intent_ranking/lr1r",
    "evaluation/learned_intent_ranking/lr2",
    "evaluation/learned_intent_ranking/lr2r",
    "evaluation/learned_intent_ranking/lr3",
    "evaluation/learned_intent_ranking/lr3r",
    "evaluation/learned_intent_ranking/lr3s",
    "evaluation/learned_intent_ranking/lr4a",
    "evaluation/learned_intent_ranking/lr4b",
    "evaluation/learned_intent_ranking/lr4b_r1",
    "docs/thesis_mainline/rq1/RQ1A_BASELINE_COMPARABILITY_CONTRACT.md",
    "docs/thesis_mainline/rq1/RQ1A_CONTEXT_REPRESENTATION_CONTRACT.md",
    "docs/thesis_mainline/rq1/RQ1A_LR4B_EXPERIMENT_CONTRACT.md",
    "docs/thesis_mainline/rq1/RQ1A_R1_CONTRACT_INTEGRITY_CORRECTION.md",
    "docs/thesis_mainline/rq1/RQ1A_R1_EFFECTIVE_EXPERIMENT_CONTRACT.md",
)


def verify_protected_sources_unchanged() -> dict[str, Any]:
    """Use tracked Git comparison only; never traverse the final-gold directory."""

    result = _git("diff", "--quiet", STARTING_HEAD, "--", *PROTECTED_PATHS)
    if result.returncode != 0:
        raise RQ1BInputError("protected source changed")
    return {
        "starting_head": STARTING_HEAD,
        "protected_path_count": len(PROTECTED_PATHS),
        "changed_existing_protected_file_count": 0,
        "protected_sources_unchanged": True,
        "comparison_method": "GIT_TRACKED_DIFF_WITH_FINAL_GOLD_NEVER_TRAVERSED",
    }


def governed_source_texts(bundle: Mapping[str, Any]) -> list[str]:
    """Return in-memory strings only for leak tests; callers must never print them."""

    values = [str(row["representation"]) for row in bundle["records"]]
    values.extend(str(row["query"]) for row in bundle["dev_records"])
    values.extend(str(row["query"]) for row in bundle["approved_index"])
    return values
