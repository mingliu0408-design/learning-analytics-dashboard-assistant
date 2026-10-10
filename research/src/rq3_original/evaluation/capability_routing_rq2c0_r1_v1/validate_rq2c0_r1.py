"""Deterministic builder, validator, and review-package gate for RQ2-C0-R1."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping
import zipfile

from . import (
    COMMIT_SUBJECT,
    DOC_FILENAMES,
    DOC_ROOT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_RQ2C0_CHECKSUM_COUNT,
    EXPECTED_RQ2C0_REVIEW_ZIP_SHA256,
    FIXTURE_ALIAS,
    FIXTURE_BANK_PATH,
    FIXTURE_ROLE,
    HERE,
    RESULT_BRANCH,
    ROOT,
    RQ2C0_CHECKSUM_RELATIVE,
    RQ2C0_REVIEW_ZIP,
    SAFE_OUTPUT_FILENAMES,
    STARTING_BRANCH,
    STARTING_HEAD,
    STARTING_PARENT,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .fixture_bank_builder import (
    build_fixture_manifest,
    build_fixture_summary,
    fixture_authority_contract,
    load_fixture_bank,
    normalise_local_fixture_bank,
)
from .fixture_coverage_validator import validate_fixture_coverage
from .literature_contract import architecture_contract
from .mechanism_metric_contract import metric_contract
from .memory_admission_policy import admission_conflict_contract
from .memory_retrieval_policy_family import policy_family_contract
from .memory_write_policy import write_update_contract
from .p2_condition_contract import condition_contract, validate_condition_isolation
from .persistent_memory_schema import schema_contract


CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r1_v1/rq2c0_r1_output_checksums_v1.sha256"
)
RQ2C0_IDENTITY_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_v1/rq2b_result_identity_v1.json"
)
PRODUCTION_MEMORY_RELATIVE = Path("utils/conversation_memory.py")
SUFFICIENCY_RELATIVE = Path("utils/retrieval_v2/sufficiency.py")
ALLOWED_DOC_PREFIX = "docs/thesis_mainline/rq2/RQ2C0_R1_"
ALLOWED_PACKAGE_PREFIX = "evaluation/capability_routing_rq2c0_r1_v1/"
REVIEW_EXTRA_MEMBERS = frozenset(
    {
        "review_metadata/git_state.txt",
        "review_metadata/diff_summary.txt",
        "review_metadata/gitignore_diff.txt",
        "review_metadata/review_checksums.sha256",
    }
)


class RQ2C0R1ValidationError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _parse_checksum_file(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise RQ2C0R1ValidationError("checksum manifest missing or unsafe")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2C0R1ValidationError("invalid checksum line") from exc
        relative_path = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise RQ2C0R1ValidationError("invalid checksum member")
        values[relative] = digest
    return values


def verify_rq2c0_output_checksums() -> int:
    values = _parse_checksum_file(ROOT / RQ2C0_CHECKSUM_RELATIVE)
    if len(values) != EXPECTED_RQ2C0_CHECKSUM_COUNT:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    failures = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if failures:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    return len(values)


def verify_starting_authority() -> dict[str, Any]:
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE")
    if _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    if (
        not RQ2C0_REVIEW_ZIP.is_file()
        or RQ2C0_REVIEW_ZIP.is_symlink()
        or sha256_file(RQ2C0_REVIEW_ZIP) != EXPECTED_RQ2C0_REVIEW_ZIP_SHA256
    ):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    checksum_count = verify_rq2c0_output_checksums()
    identity = json.loads((ROOT / RQ2C0_IDENTITY_RELATIVE).read_text(encoding="utf-8"))
    if (
        identity.get("p1_final_policy") != EXPECTED_P1_POLICY
        or identity.get("p1_policy_immutable") is not True
        or identity.get("gold_bundle_sha256") != EXPECTED_GOLD_BUNDLE_SHA256
    ):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "starting_branch": STARTING_BRANCH,
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "rq2c0_review_zip_sha256": EXPECTED_RQ2C0_REVIEW_ZIP_SHA256,
        "rq2c0_output_checksum_count": checksum_count,
        "p1_policy": identity["p1_final_policy"],
        "p1_policy_immutable": identity["p1_policy_immutable"],
        "gold_bundle_sha256": identity["gold_bundle_sha256"],
    }


def _scope_authority(starting: Mapping[str, Any]) -> dict[str, Any]:
    literature = architecture_contract()
    return {
        "schema_version": "rq2c0-r1-scope-authority-v1",
        "stage": "RQ2-C0-R1",
        "status": "FROZEN_CONTRACT_ONLY",
        "starting_authority": dict(starting),
        "result_branch": RESULT_BRANCH,
        "fixture_alias": FIXTURE_ALIAS,
        "fixture_role": FIXTURE_ROLE,
        "literature_evidence_basis": literature["evidence_basis"],
        "literature_invariant_count": len(literature["invariants"]),
        "memory_layers": literature["layers"],
        "production_memory_source_sha256": sha256_file(ROOT / PRODUCTION_MEMORY_RELATIVE),
        "retrieval_sufficiency_source_sha256": sha256_file(ROOT / SUFFICIENCY_RELATIVE),
        "p1_changed": False,
        "gold_changed": False,
        "human_annotation_changed": False,
        "persistent_memory_implemented": False,
        "p2_implemented": False,
        "production_routing_changed": False,
        "rag_behavior_changed": False,
        "memory_behavior_changed": False,
        "planner_behavior_changed": False,
        "track_a_access": False,
        "track_b_access": False,
        "model_training": False,
        "provider_calls": 0,
        "network_access": False,
    }


def _documents(outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    authority = outputs["rq2c0_r1_scope_authority_v1.json"]
    schema = outputs["persistent_learner_memory_schema_v1.json"]
    write = outputs["memory_write_update_contract_v1.json"]
    retrieval = outputs["persistent_memory_retrieval_policy_family_v1.json"]
    admission = outputs["memory_admission_conflict_contract_v1.json"]
    fixtures = outputs["controlled_mechanism_fixture_summary_v1.json"]
    coverage = outputs["mechanism_evaluability_repair_v1.json"]
    conditions = outputs["p2_condition_contract_v2.json"]

    literature_doc = f"""# RQ2-C0-R1 Memory Literature Synthesis

## Evidence boundary

This synthesis uses only the literature identities and architectural summaries supplied in the authorised task. No network lookup was performed, no external citation was added, and no claim beyond those summaries is introduced.

## Frozen architecture

PersistentLearnerMemoryV1 separates Working Context, Session State, Persistent Episode, Profile/Preference, and Plan/Progress. Raw episodes remain append-only; a versioned projection derives active state. Keyword matching is one signal, not the architecture. Dense similarity is also one signal, not the architecture. Candidate retrieval must combine semantic relevance with entity or state links, memory type, temporal validity, and active status.

An LLM summary cannot replace the source episode as the sole fact. Writes require an explicit student statement or verified system event. Unconfirmed personality, mental-health, self-regulated-learning, or ability-deficit inferences are prohibited. The latest explicit correction wins; stale, superseded, cancelled, deleted, and cross-scope memories cannot enter generation.

This is a research contract, not a complete student model and not evidence of educational effectiveness.
"""

    architecture_doc = f"""# RQ2-C0-R1 Persistent Learner Memory Architecture

## Research-only schemas

The frozen namespace contains six contracts: MemoryEpisodeV1, MemoryStateProjectionV1, MemoryWriteDecisionV1, MemoryRetrievalPlanV1, MemoryCandidateV1, and MemoryAdmissionDecisionV1. Allowed episode types are {', '.join(schema['allowed_memory_types'])}. The raw episode is append-only; active goal, plan, constraints, preferences, corrections, completion state, and references are derived through a versioned projection.

The existing production memory source is preserved under SHA-256 `{authority['production_memory_source_sha256']}`. RQ2-C0-R1 creates no database, vector index, embedding retrieval runtime, production namespace, or P2 Router. Production encryption and durable persistence remain prerequisites for any future integration.

Per-student namespaces, source provenance, version history, deletion tombstones, and exclusion of sensitive inference are mandatory. Raw memory content remains local-only and is never placed in tracked outputs or the review package.
"""

    policy_doc = f"""# RQ2-C0-R1 Memory Write, Retrieval and Conflict Policy

## Write and update

Writes are limited to explicit student facts, preferences, constraints, goals and corrections, or verified plan/completion events. Model-only inference, unaccepted assistant suggestions, unverified dashboard interpretation, and sensitive profile inference are rejected. A correction appends a new episode, marks the old episode SUPERSEDED, retains the link, and does not erase history. Deletion creates a DELETED tombstone, blocks later retrieval, and retains only the deletion-event hash for audit.

## Candidate policies

The frozen, unselected family is {', '.join(retrieval['policy_ids'])}. PMR_KW_LEGACY is a keyword/rule baseline. PMR_DENSE_ONLY is a frozen local-dense candidate condition. PMR_HYBRID_TYPE_TEMPORAL combines dense, lexical/entity and explicit state links, then applies type and time. PMR_HYBRID_STATE_AWARE additionally rejects inactive, stale, superseded, cancelled, deleted, and cross-scope candidates and resolves explicit corrections.

No policy was run or selected. No learned retriever, cross-encoder, LLM memory Router, case-specific keyword, Gold feature, or source-role feature is authorised. Admission requires relevance, active status, temporal validity, current scope, and conflict safety. The rejection order is {', '.join(admission['rejection_priority'])}.
"""

    fixture_doc = f"""# RQ2-C0-R1 Controlled Mechanism Fixture Protocol

## Authority and role

`{FIXTURE_ALIAS}` is a user-authorised, contract-derived, white-box mechanism bank. It is synthetic and controlled; it is not student data, Capability Gold, authentic dialogue evidence, final evaluation, or educational-effectiveness evidence.

The bank contains {fixtures['total']} fixtures: {fixtures['rag']} RAG and {fixtures['persistent_memory']} Persistent Memory. RAG contains six candidate-gate and eight sufficiency-gate controls, including two each for SUPPORTED, AMBIGUOUS, UNSUPPORTED, and NO_RESULT. Persistent Memory contains four write/update, five retrieval, three freshness/conflict, and two privacy/control controls.

Full fixture inputs, initial memory state, and expected per-case decisions exist only in the ignored local JSONL committed by SHA-256 `{fixtures['fixture_bank_sha256']}`. Tracked files retain only hashes, counts, distributions, schemas, and gate outcomes. The local bank is excluded from Git and the review ZIP.

Coverage thresholds were applied unchanged. The resulting status is `{coverage['evaluability_status']}`. Fixture results are mechanism-development evidence only and cannot be reported as student outcomes.
"""

    condition_doc = f"""# RQ2-C0-R1 P2 Conditions and Evaluation Limits

## Frozen matrix

The five future offline conditions are {', '.join(conditions['conditions'])}. P1_BASE adds no mechanism. P2_RAG_ONLY isolates dual-gated RAG. P2_SESSION_STATE_ONLY isolates existing session state. P2_PERSISTENT_MEMORY_ONLY isolates additional persistent retrieval. P2_FULL includes all three mechanisms. C0, P1_D05_SIGNAL_UNION, production guards, the controlled fixture bank, Capability Gold, and ContextEnvelopeV1 remain fixed.

The metric contract separates write quality, retrieval Recall@1/Recall@3/MRR and abstention, admission safety, update/conflict accuracy, and end-to-end capability/clarification/token overhead. No condition was executed in RQ2-C0-R1. Track A and Track B were not accessed, P2 was not implemented, and no production Router was integrated.
"""
    return {
        DOC_FILENAMES[0]: literature_doc,
        DOC_FILENAMES[1]: architecture_doc,
        DOC_FILENAMES[2]: policy_doc,
        DOC_FILENAMES[3]: fixture_doc,
        DOC_FILENAMES[4]: condition_doc,
    }


def _preflight_report(
    starting: Mapping[str, Any],
    manifest: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rq2c0-r1-preflight-report-v1",
        "stage": "RQ2-C0-R1",
        "status": "PASS_CONTRACT_AND_FIXTURE_FREEZE",
        "starting_authority": dict(starting),
        "fixture_alias": FIXTURE_ALIAS,
        "fixture_bank_sha256": manifest["raw_bank_sha256"],
        "fixture_count": manifest["raw_record_count"],
        "mechanism_evaluability": coverage["evaluability_status"],
        "tracked_safe_output_count": len(SAFE_OUTPUT_FILENAMES),
        "expected_checksum_reference_count": 30,
        "local_fixture_text_tracked": False,
        "local_fixture_text_review_package_eligible": False,
        "p1_changed": False,
        "gold_changed": False,
        "human_annotation_changed": False,
        "persistent_memory_implemented": False,
        "p2_implemented": False,
        "production_behavior_changed": False,
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_a_access": False,
        "track_b_access": False,
    }


def build_all() -> dict[str, Any]:
    starting = verify_starting_authority()
    fixtures = load_fixture_bank()
    normalise_local_fixture_bank(fixtures)
    fixtures = load_fixture_bank()
    manifest = build_fixture_manifest(fixtures)
    summary = build_fixture_summary(fixtures, manifest)
    coverage = validate_fixture_coverage(fixtures)
    outputs: dict[str, dict[str, Any]] = {
        "rq2c0_r1_scope_authority_v1.json": _scope_authority(starting),
        "persistent_learner_memory_schema_v1.json": schema_contract(),
        "memory_write_update_contract_v1.json": write_update_contract(),
        "persistent_memory_retrieval_policy_family_v1.json": policy_family_contract(),
        "memory_admission_conflict_contract_v1.json": admission_conflict_contract(),
        "controlled_mechanism_fixture_authority_v1.json": fixture_authority_contract(),
        "controlled_mechanism_fixture_manifest_v1.json": manifest,
        "controlled_mechanism_fixture_summary_v1.json": summary,
        "p2_condition_contract_v2.json": condition_contract(),
        "persistent_memory_metric_contract_v1.json": metric_contract(),
        "mechanism_evaluability_repair_v1.json": coverage,
    }
    outputs["rq2c0_r1_preflight_report_v1.json"] = _preflight_report(
        starting, manifest, coverage
    )
    if set(outputs) != set(SAFE_OUTPUT_FILENAMES):
        raise RQ2C0R1ValidationError("RQ2-C0-R1 safe output set mismatch")
    for name, value in outputs.items():
        write_canonical_json(HERE / name, value)
    for name, value in _documents(outputs).items():
        path = DOC_ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    targets = _tracked_checksum_targets()
    manifest_text = "\n".join(
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in targets
    ) + "\n"
    (ROOT / CHECKSUM_RELATIVE).write_text(manifest_text, encoding="utf-8")
    commitments = {
        path.relative_to(ROOT).as_posix(): sha256_file(path) for path in targets
    }
    return {
        "status": "PASS_CONTRACT_AND_FIXTURE_FREEZE",
        "evaluability_status": coverage["evaluability_status"],
        "fixture_count": len(fixtures),
        "safe_output_count": len(outputs),
        "checksum_reference_count": len(targets),
        "build_commitment_sha256": sha256_bytes(canonical_json_bytes(commitments)),
    }


def _tracked_checksum_targets() -> list[Path]:
    python_files = sorted(HERE.glob("*.py"))
    json_files = [HERE / name for name in SAFE_OUTPUT_FILENAMES]
    docs = [DOC_ROOT / name for name in DOC_FILENAMES]
    targets = sorted(
        [*python_files, *json_files, *docs],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    if (
        len(python_files) != 13
        or len(targets) != 30
        or len(targets) != len(set(targets))
        or any(not path.is_file() or path.is_symlink() for path in targets)
    ):
        raise RQ2C0R1ValidationError("RQ2-C0-R1 checksum target set incomplete")
    return targets


def parse_output_checksums() -> dict[str, str]:
    return _parse_checksum_file(ROOT / CHECKSUM_RELATIVE)


def validate_output_checksums() -> dict[str, Any]:
    members = parse_output_checksums()
    failures = [
        relative
        for relative, expected in members.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != expected
    ]
    if failures or len(members) != 30:
        raise RQ2C0R1ValidationError(
            "BLOCKED_RQ2_C0_R1_TEST_FAILURE: output checksums"
        )
    return {"status": "PASS", "referenced_tracked_output_path_count": len(members)}


def validate_python_ast() -> dict[str, Any]:
    files = sorted(HERE.glob("*.py"))
    forbidden_imports = {"openai", "firebase_admin", "sentence_transformers", "faiss", "chromadb"}
    observed_forbidden: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed_forbidden.update(
                    item.name.split(".")[0] for item in node.names if item.name.split(".")[0] in forbidden_imports
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in forbidden_imports:
                    observed_forbidden.add(root)
    if len(files) != 13 or observed_forbidden:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_TEST_FAILURE: Python AST")
    return {"status": "PASS", "python_file_count": len(files), "forbidden_import_count": 0}


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_safe_outputs() -> dict[str, Any]:
    values = {
        name: json.loads((HERE / name).read_text(encoding="utf-8"))
        for name in SAFE_OUTPUT_FILENAMES
    }
    forbidden_raw_keys = {
        "initial_store_state",
        "input_event_or_query",
        "expected_retrieval_ids",
        "expected_admission_ids",
        "expected_rejection_reasons",
        "raw_content",
        "memory_text",
    }
    if any(forbidden_raw_keys & set(_walk_keys(value)) for value in values.values()):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_TEST_FAILURE: tracked raw text")
    if values["controlled_mechanism_fixture_summary_v1.json"].get("total") != 28:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK")
    if values["mechanism_evaluability_repair_v1.json"].get("all_gates_pass") is not True:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_FIXTURE_COVERAGE")
    if not validate_condition_isolation(values["p2_condition_contract_v2.json"]):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_TEST_FAILURE: conditions")
    return {"status": "PASS", "safe_output_count": len(values), "raw_text_key_count": 0}


def _fixture_natural_language_strings() -> list[str]:
    strings: set[str] = set()
    for fixture in load_fixture_bank():
        query_text = str(fixture.input_event_or_query.get("text") or "").strip()
        if len(query_text) >= 24:
            strings.add(query_text)
        for item in fixture.initial_store_state:
            raw_content = str(item.get("raw_content") or "").strip()
            if len(raw_content) >= 24:
                strings.add(raw_content)
    return sorted(strings)


def governed_text_leak_scan() -> dict[str, Any]:
    paths = [ROOT / relative for relative in parse_output_checksums()]
    governed = _fixture_natural_language_strings()
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if ("/" + "Users/") in text or re.search(r"(?:^|\s)/(?:private|var|tmp)/", text):
            leaks.append(f"absolute_path:{path.name}")
        if any(value in text for value in governed):
            leaks.append(f"fixture_text:{path.name}")
    if leaks:
        raise RQ2C0R1ValidationError(
            "BLOCKED_RQ2_C0_R1_TEST_FAILURE: governed text " + ",".join(leaks)
        )
    return {
        "status": "PASS",
        "governed_fixture_string_count": len(governed),
        "scanned_tracked_file_count": len(paths),
        "leak_count": 0,
    }


def _changed_paths() -> list[str]:
    tracked = {
        line for line in _git("diff", "--name-only", STARTING_HEAD, "--").splitlines() if line
    }
    untracked = {
        line
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line
    }
    return sorted(tracked | untracked)


def _path_allowed(path: str) -> bool:
    return (
        path == ".gitignore"
        or path.startswith(ALLOWED_DOC_PREFIX)
        or path.startswith(ALLOWED_PACKAGE_PREFIX)
    )


def protected_source_comparison() -> dict[str, Any]:
    changed = _changed_paths()
    forbidden = [path for path in changed if not _path_allowed(path)]
    changed_existing = [
        path
        for path in changed
        if path != ".gitignore"
        and subprocess.run(
            ["git", "cat-file", "-e", f"{STARTING_HEAD}:{path}"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    ]
    if forbidden or changed_existing:
        raise RQ2C0R1ValidationError(
            "BLOCKED_RQ2_C0_R1_PROTECTED_SOURCE_MUTATED: "
            + ",".join(forbidden + changed_existing)
        )
    return {
        "status": "PASS",
        "changed_path_count": len(changed),
        "protected_existing_file_change_count": 0,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = [
        line for line in _git("diff", "--cached", "--name-only").splitlines() if line
    ]
    forbidden = [
        path
        for path in staged
        if not _path_allowed(path) or "/local_fixture_bank/" in path
    ]
    if forbidden:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE: staged allowlist")
    return {"status": "PASS", "staged_path_count": len(staged)}


def assert_partition_access_allowed(partition: str) -> None:
    if str(partition).upper() in {"TRACK_A", "TRACK_B"}:
        raise PermissionError("sealed evaluation partition")


def validate_local_fixture_ignore() -> dict[str, Any]:
    probe = (
        "evaluation/capability_routing_rq2c0_r1_v1/"
        "local_fixture_bank/probe.jsonl"
    )
    if subprocess.run(
        ["git", "check-ignore", "-q", probe], cwd=ROOT, check=False
    ).returncode != 0:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE: ignore")
    tracked = _git("ls-files", ALLOWED_PACKAGE_PREFIX + "local_fixture_bank")
    if tracked or not FIXTURE_BANK_PATH.is_file() or FIXTURE_BANK_PATH.is_symlink():
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_FIXTURE_BANK")
    return {
        "status": "PASS",
        "tracked_local_fixture_count": 0,
        "local_fixture_record_count": len(load_fixture_bank()),
    }


def validate_no_implementation() -> dict[str, Any]:
    scope = json.loads((HERE / "rq2c0_r1_scope_authority_v1.json").read_text(encoding="utf-8"))
    if any(
        scope[key]
        for key in (
            "persistent_memory_implemented",
            "p2_implemented",
            "production_routing_changed",
            "rag_behavior_changed",
            "memory_behavior_changed",
            "planner_behavior_changed",
            "model_training",
            "network_access",
        )
    ) or scope["provider_calls"] != 0:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_TEST_FAILURE: implementation boundary")
    return {"status": "PASS", "implementation_count": 0}


def validate_review_package_contract() -> dict[str, Any]:
    expected = expected_review_members()
    forbidden = [name for name in expected if "/local_fixture_bank/" in name]
    if forbidden or not set(parse_output_checksums()).issubset(expected):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_TEST_FAILURE: review completeness")
    return {
        "status": "PASS",
        "referenced_output_member_count": len(parse_output_checksums()),
        "expected_review_member_count": len(expected),
        "local_fixture_member_count": 0,
    }


def validate_all() -> dict[str, Any]:
    reports = {
        "starting_authority": verify_starting_authority(),
        "python_ast": validate_python_ast(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "staged_allowlist": staged_allowlist(),
        "local_fixture_bank": validate_local_fixture_ignore(),
        "implementation_boundary": validate_no_implementation(),
        "review_package_contract": validate_review_package_contract(),
    }
    return {
        "status": "PASS_CONTRACT_AND_FIXTURE_FREEZE",
        "evaluability_status": json.loads(
            (HERE / "mechanism_evaluability_repair_v1.json").read_text(encoding="utf-8")
        )["evaluability_status"],
        "reports": reports,
    }


def expected_review_members() -> set[str]:
    return {
        *parse_output_checksums(),
        CHECKSUM_RELATIVE.as_posix(),
        *REVIEW_EXTRA_MEMBERS,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 26, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def validate_review_zip(zip_path: Path) -> dict[str, Any]:
    allowed = expected_review_members()
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
        if bad is not None or len(members) != len(set(members)) or set(members) != allowed:
            raise RQ2C0R1ValidationError(
                "BLOCKED_RQ2_C0_R1_TEST_FAILURE: review package"
            )
        for relative, expected in parse_output_checksums().items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != expected:
                raise RQ2C0R1ValidationError(
                    "BLOCKED_RQ2_C0_R1_TEST_FAILURE: review checksum"
                )
        if any("local_fixture_bank" in name for name in members):
            raise RQ2C0R1ValidationError(
                "BLOCKED_RQ2_C0_R1_TEST_FAILURE: local fixture in ZIP"
            )
    return {
        "status": "PASS",
        "zip_integrity": "PASS",
        "zip_member_count": len(members),
        "referenced_output_member_count": len(parse_output_checksums()),
        "referenced_outputs_present": True,
        "local_fixture_member_count": 0,
    }


def build_review_zip(zip_path: Path) -> dict[str, Any]:
    if zip_path.exists():
        raise RQ2C0R1ValidationError("review ZIP target already exists")
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE: worktree")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) != 1:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE: commit count")
    if _git("show", "-s", "--format=%s", "HEAD") != COMMIT_SUBJECT:
        raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_GIT_FAILURE: subject")

    payloads = {
        relative: (ROOT / relative).read_bytes() for relative in parse_output_checksums()
    }
    payloads[CHECKSUM_RELATIVE.as_posix()] = (ROOT / CHECKSUM_RELATIVE).read_bytes()
    payloads["review_metadata/git_state.txt"] = (
        "\n".join(
            (
                f"branch: {_git('branch', '--show-current')}",
                f"head: {_git('rev-parse', 'HEAD')}",
                f"parent: {_git('rev-parse', 'HEAD^')}",
                f"starting_head: {STARTING_HEAD}",
                f"relative_commits: {_git('rev-list', '--count', f'{STARTING_HEAD}..HEAD')}",
                "remote_count: 0",
                "tag_count: 0",
                "working_tree: clean",
                "index: clean",
                f"commit_subject: {_git('show', '-s', '--format=%s', 'HEAD')}",
            )
        )
        + "\n"
    ).encode("utf-8")
    payloads["review_metadata/diff_summary.txt"] = (
        _git("diff", "--stat", STARTING_HEAD, "HEAD")
        + "\n\n"
        + _git("diff", "--name-status", STARTING_HEAD, "HEAD")
        + "\n"
    ).encode("utf-8")
    payloads["review_metadata/gitignore_diff.txt"] = (
        _git("diff", STARTING_HEAD, "HEAD", "--", ".gitignore") + "\n"
    ).encode("utf-8")
    review_checksums = "\n".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
        for name in sorted(payloads)
    ) + "\n"
    payloads["review_metadata/review_checksums.sha256"] = review_checksums.encode("utf-8")

    governed = _fixture_natural_language_strings()
    for name, payload in payloads.items():
        if name.endswith((".py", ".json", ".md", ".txt", ".sha256")):
            text = payload.decode("utf-8")
            if ("/" + "Users/") in text or any(value in text for value in governed):
                raise RQ2C0R1ValidationError("BLOCKED_RQ2_C0_R1_TEST_FAILURE: ZIP leak")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(_zip_info(name), payloads[name])
    verification = validate_review_zip(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        lines = archive.read("review_metadata/review_checksums.sha256").decode("utf-8").splitlines()
        for line in lines:
            expected, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RQ2C0R1ValidationError(
                    "BLOCKED_RQ2_C0_R1_TEST_FAILURE: ZIP internal checksum"
                )
    return {
        **verification,
        "review_checksum_entries": len(lines),
        "governed_text_leak_scan": "PASS",
        "sha256": sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "path": str(zip_path),
    }


def main() -> int:
    build = build_all()
    print(json.dumps({"build": build, "validation": validate_all()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
