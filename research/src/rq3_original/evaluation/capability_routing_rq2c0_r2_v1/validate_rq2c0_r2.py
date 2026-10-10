"""Deterministic builder, validator, and review-package gate for RQ2-C0-R2."""

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
    AMENDMENT_CONTRACT_ID,
    COMMIT_SUBJECT,
    DOC_FILENAMES,
    DOC_ROOT,
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_R1_CHECKSUM_COUNT,
    EXPECTED_R1_REVIEW_ZIP_SHA256,
    HERE,
    R1_CHECKSUM_RELATIVE,
    R1_FIXTURE_BANK_PATH,
    R1_REVIEW_ZIP,
    R1_SCOPE_RELATIVE,
    RESULT_BRANCH,
    ROOT,
    SAFE_OUTPUT_FILENAMES,
    STARTING_BRANCH,
    STARTING_HEAD,
    STARTING_PARENT,
    canonical_json_bytes,
    canonical_json_line,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .condition_semantics import condition_semantics_contract, validate_condition_semantics
from .episode_schema_v1_1 import episode_schema_contract
from .event_type_compatibility import event_type_contract
from .executable_admission_contract import admission_contract
from .executable_retrieval_contract import executable_retrieval_contract
from .fixture_semantic_commitment import build_semantic_commitments
from .fixture_semantic_validator import (
    fixture_validation_amendment_authority,
    legacy_validation_alias,
    load_frozen_fixture_rows,
    mechanism_specific_field_semantics_contract,
    validate_all_fixture_semantics,
)
from .literature_evidence import literature_evidence_manifest
from .multi_hop_contract import multi_hop_contract
from .payload_schema import payload_boundary_contract
from .write_candidate_contract import write_candidate_boundary_contract


CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r2_v1/rq2c0_r2_output_checksums_v1.sha256"
)
ALLOWED_DOC_PREFIX = "docs/thesis_mainline/rq2/RQ2C0_R2_"
ALLOWED_PACKAGE_PREFIX = "evaluation/capability_routing_rq2c0_r2_v1/"
REVIEW_EXTRA_MEMBERS = frozenset(
    {
        "review_metadata/git_state.txt",
        "review_metadata/diff_summary.txt",
        "review_metadata/review_checksums.sha256",
        "review_metadata/review_scope.txt",
    }
)


class RQ2C0R2ValidationError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _parse_checksum_file(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise RQ2C0R2ValidationError("checksum manifest missing or unsafe")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2C0R2ValidationError("invalid checksum line") from exc
        relative_path = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise RQ2C0R2ValidationError("invalid checksum member")
        values[relative] = digest
    return values


def verify_r1_output_checksums() -> int:
    values = _parse_checksum_file(ROOT / R1_CHECKSUM_RELATIVE)
    failures = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if len(values) != EXPECTED_R1_CHECKSUM_COUNT or failures:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    return len(values)


def verify_starting_authority() -> dict[str, Any]:
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE")
    if _git("rev-parse", f"{STARTING_HEAD}^") != STARTING_PARENT:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    if (
        not R1_REVIEW_ZIP.is_file()
        or R1_REVIEW_ZIP.is_symlink()
        or sha256_file(R1_REVIEW_ZIP) != EXPECTED_R1_REVIEW_ZIP_SHA256
    ):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    checksum_count = verify_r1_output_checksums()
    if (
        sha256_file(R1_FIXTURE_BANK_PATH) != EXPECTED_FIXTURE_BANK_SHA256
        or R1_FIXTURE_BANK_PATH.stat().st_size != EXPECTED_FIXTURE_BANK_SIZE
        or len(load_frozen_fixture_rows()) != EXPECTED_FIXTURE_RECORD_COUNT
    ):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    scope = json.loads((ROOT / R1_SCOPE_RELATIVE).read_text(encoding="utf-8"))
    authority = scope.get("starting_authority") or {}
    if (
        authority.get("p1_policy") != EXPECTED_P1_POLICY
        or authority.get("p1_policy_immutable") is not True
        or authority.get("gold_bundle_sha256") != EXPECTED_GOLD_BUNDLE_SHA256
    ):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS",
        "starting_branch": STARTING_BRANCH,
        "starting_head": STARTING_HEAD,
        "starting_parent": STARTING_PARENT,
        "r1_review_zip_sha256": EXPECTED_R1_REVIEW_ZIP_SHA256,
        "r1_output_checksum_count": checksum_count,
        "fixture_bank_sha256": EXPECTED_FIXTURE_BANK_SHA256,
        "fixture_bank_size_bytes": EXPECTED_FIXTURE_BANK_SIZE,
        "fixture_record_count": EXPECTED_FIXTURE_RECORD_COUNT,
        "p1_policy": authority["p1_policy"],
        "p1_policy_immutable": authority["p1_policy_immutable"],
        "gold_bundle_sha256": authority["gold_bundle_sha256"],
    }


def _preflight_report(
    starting: Mapping[str, Any], validation: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": "rq2c0-r2-preflight-report-v1",
        "stage": "RQ2-C0-R2",
        "status": "PASS_EXECUTABLE_CONTRACT_FREEZE",
        "starting_authority": dict(starting),
        "field_semantics_contract_id": AMENDMENT_CONTRACT_ID,
        "fixture_semantic_validation": validation["status"],
        "passed_fixture_count": validation["passed_fixture_count"],
        "failed_fixture_count": validation["failed_fixture_count"],
        "fixture_bank_sha_before": validation["fixture_bank_sha_before"],
        "fixture_bank_sha_after": validation["fixture_bank_sha_after"],
        "safe_output_count": len(SAFE_OUTPUT_FILENAMES),
        "expected_checksum_reference_count": 36,
        "fixture_text_changed": False,
        "fixture_membership_changed": False,
        "expected_decision_changed": False,
        "coverage_count_changed": False,
        "p1_changed": False,
        "gold_changed": False,
        "human_annotation_changed": False,
        "persistent_store_implemented": False,
        "p2_implemented": False,
        "retrieval_executed": False,
        "policy_selected_from_fixtures": False,
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


def _documents(outputs: Mapping[str, Any]) -> dict[str, str]:
    retrieval = outputs["executable_persistent_retrieval_contract_v1.json"]
    admission = outputs["memory_admission_contract_v1.json"]
    validation = outputs["controlled_mechanism_fixture_semantic_validation_v1_1.json"]
    literature = outputs["persistent_memory_literature_evidence_v1.json"]

    algorithm = f"""# RQ2-C0-R2 Executable Memory Algorithm

## Deterministic retrieval

All policies apply exact student-scope and non-DELETED hard guards before candidate generation. The frozen dense encoder is `sentence-transformers/all-mpnet-base-v2` at revision `{retrieval['dense_encoder']['revision']}`, local-only, normalised, CPU, without fallback or download. Dense top-k is five and ties resolve by score descending, event time descending, then memory ID ascending.

`PMR_KW_LEGACY` uses only the existing production trigger, explicit state links, and exact lexical/entity overlap. `PMR_DENSE_ONLY` uses dense top-five. `PMR_HYBRID_TYPE_TEMPORAL` unions dense, lexical/entity, and explicit-link candidates and applies the frozen seven-field lexicographic ranking. `PMR_HYBRID_STATE_AWARE` additionally rejects stale, superseded, cancelled, and non-targeted completed episodes, resolves conflict groups, and applies the latest explicit correction.

`PMR_HYBRID_STATE_AWARE` is predesignated as the P2 persistent-memory primary policy. It was not selected from fixtures. The algorithms operate only on supplied safe metadata and scores; no store, encoder, embedding retrieval, or P2 Router was executed.

## Admission and multi-hop

Retrieval and admission remain separate. At most {admission['maximum_admitted_memories']} memories may enter generation. Direct, structured, and dense support have explicit predicates; top-one retrieval alone never authorises admission. Missing required memory leads to clarification or a safe partial response with an explicit missing-evidence boundary.
"""

    payload_write = """# RQ2-C0-R2 Private Payload and Write Boundary

## Versioned payload boundary

PersistentLearnerMemoryV1 remains historical; PersistentLearnerMemoryV1_1 adds a tracked-safe MemoryPayloadRefV1 and a private MemoryPayloadV1. Episodes contain payload IDs and hashes, never raw content. Payload text and structured values may exist only in an ignored local, encrypted-at-rest store and are excluded from Git and the review ZIP. Episode raw-content hash, payload-reference content hash, and computed private-payload content hash must match.

Event time and ingestion time are distinct. The episode also freezes timezone, status reason, source kind, and projection eligibility.

## Structured writes

RQ2-C1 may receive only structured explicit assertions, verified plan events, verified completion events, or explicit confirmations. Free-form LLM inference, unconfirmed assistant suggestions, inferred personality/SRL/ability, and unverified dashboard interpretations are rejected. Exact event-to-type compatibility is mandatory; unknown events and mismatched types fail without automatic reclassification. Open-ended natural-language memory extraction is explicitly outside RQ2-C1 evaluation.
"""

    fixture_doc = f"""# RQ2-C0-R2 Fixture Semantic Validation

The unchanged controlled bank was validated from actual fields under `{AMENDMENT_CONTRACT_ID}`. All {validation['fixture_count']} fixtures passed: {validation['rag_candidate_gate_count']} Candidate Gate, {validation['rag_sufficiency_gate_count']} Sufficiency Gate, and {validation['persistent_fixture_count']} Persistent Memory.

Candidate Gate uses pre-retrieval temporal semantics; downstream RAG IDs are commitments, not pre-existing store items, and admission/sufficiency conclusions are prohibited. Sufficiency Gate retains strict retrieved-chunk ID existence and field-derived SUPPORTED/AMBIGUOUS/UNSUPPORTED/NO_RESULT validation. Persistent groups retain strict episode-ID, scope, status, supersession, multi-hop, and rejection-reason validation.

The bank SHA before and after was `{validation['fixture_bank_sha_after']}`. Fixture text, membership, expected decisions, and coverage tags changed zero times. The tracked JSONL contains only hashes, counts, enums, and validation commitments.
"""

    condition_doc = """# RQ2-C0-R2 P2 Condition Semantics

P1_BASE may use ContextEnvelopeV1 for capability routing but adds neither session-state evidence admission nor persistent retrieval. P2_SESSION_STATE_ONLY admits already-present, valid ContextEnvelope session state through relevance/freshness gates and never searches persistent storage. P2_PERSISTENT_MEMORY_ONLY adds PMR_HYBRID_STATE_AWARE persistent search and adds no session-state evidence admission. P2_RAG_ONLY adds only dual-gated RAG. P2_FULL independently enables dual-gated RAG, session-state evidence admission, and PMR_HYBRID_STATE_AWARE persistent retrieval.

The switches are independently controllable. No condition evaluation or implementation occurred in RQ2-C0-R2.
"""

    trace_rows = "\n".join(
        f"| {item['source_identity']} | {item['venue_year']} | "
        f"{', '.join(item['supported_design_principles'])} | "
        f"{', '.join(item['contract_fields'])} |"
        for item in literature["sources"]
    )
    literature_doc = f"""# RQ2-C0-R2 Literature-to-Architecture Traceability

This publication-safe mapping uses only the identities and summaries explicitly authorised by the task. It adds no experimental numbers, performs no network lookup, and treats each source as design support rather than causal proof.

| Source identity | Venue/year | Supported principle | Project contract field |
|---|---|---|---|
{trace_rows}

The mapping justifies traceability of design choices; it does not demonstrate mechanism performance, educational effectiveness, or real-student generalisation.
"""

    amendment_doc = f"""# RQ2-C0-R2 Fixture Semantic Validation Amendment

Candidate Gate and Sufficiency Gate describe different times. Candidate Gate asks whether retrieval should start, before any chunk exists; an empty pre-retrieval state is therefore valid, and expected RAG IDs commit to possible downstream outputs rather than pre-existing items. Sufficiency Gate begins after retrieved chunks have been preconstructed and therefore retains strict ID existence, sufficiency, and admission checks.

Persistent Memory fixtures also retain strict store semantics: retrieved and admitted IDs must identify real episodes, and scope, stale, superseded, cancelled/completed, deleted, multi-hop, and conflict outcomes must be supported by episode fields. The Candidate Gate exception is exact-group only and fails closed everywhere else.

FX-001 and FX-002 were independently verified as exact `RAG_CANDIDATE_GATE` records. Neither record was edited. The whole-bank SHA remains `{validation['fixture_bank_sha_after']}`; membership, expected decisions, coverage tags, and behaviour remain unchanged. This is a validation-meaning correction, not a performance improvement.
"""

    return {
        DOC_FILENAMES[0]: algorithm,
        DOC_FILENAMES[1]: payload_write,
        DOC_FILENAMES[2]: fixture_doc,
        DOC_FILENAMES[3]: condition_doc,
        DOC_FILENAMES[4]: literature_doc,
        DOC_FILENAMES[5]: amendment_doc,
    }


def build_all() -> dict[str, Any]:
    fixture_sha_before = sha256_file(R1_FIXTURE_BANK_PATH)
    starting = verify_starting_authority()
    semantic_validation = validate_all_fixture_semantics()
    commitments = build_semantic_commitments(semantic_validation)
    outputs: dict[str, Any] = {
        "persistent_learner_memory_schema_v1_1.json": episode_schema_contract(),
        "private_memory_payload_boundary_v1.json": payload_boundary_contract(),
        "structured_write_candidate_contract_v1.json": write_candidate_boundary_contract(),
        "event_memory_type_compatibility_v1.json": event_type_contract(),
        "executable_persistent_retrieval_contract_v1.json": executable_retrieval_contract(),
        "memory_admission_contract_v1.json": admission_contract(),
        "multi_hop_memory_contract_v1.json": multi_hop_contract(),
        "p2_condition_semantics_v2_1.json": condition_semantics_contract(),
        "controlled_mechanism_fixture_semantic_commitment_v1.jsonl": commitments,
        "controlled_mechanism_fixture_semantic_validation_v1.json": legacy_validation_alias(
            semantic_validation
        ),
        "controlled_mechanism_fixture_semantic_validation_v1_1.json": semantic_validation,
        "persistent_memory_literature_evidence_v1.json": literature_evidence_manifest(),
        "fixture_semantic_validation_amendment_v1.json": fixture_validation_amendment_authority(),
        "mechanism_specific_fixture_field_semantics_v1_1.json": mechanism_specific_field_semantics_contract(),
    }
    outputs["rq2c0_r2_preflight_report_v1.json"] = _preflight_report(
        starting, semantic_validation
    )
    if set(outputs) != set(SAFE_OUTPUT_FILENAMES):
        raise RQ2C0R2ValidationError("RQ2-C0-R2 safe output set mismatch")
    for name, value in outputs.items():
        path = HERE / name
        if name.endswith(".jsonl"):
            path.write_bytes(b"".join(canonical_json_line(item) for item in value))
        else:
            write_canonical_json(path, value)
    for name, value in _documents(outputs).items():
        path = DOC_ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    targets = _tracked_checksum_targets()
    manifest = "\n".join(
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in targets
    ) + "\n"
    (ROOT / CHECKSUM_RELATIVE).write_text(manifest, encoding="utf-8")
    fixture_sha_after = sha256_file(R1_FIXTURE_BANK_PATH)
    if fixture_sha_before != EXPECTED_FIXTURE_BANK_SHA256 or fixture_sha_after != fixture_sha_before:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_FIXTURE_BANK_MUTATED")
    commitment = {
        path.relative_to(ROOT).as_posix(): sha256_file(path) for path in targets
    }
    return {
        "status": "PASS_EXECUTABLE_CONTRACT_FREEZE",
        "fixture_semantic_status": semantic_validation["status"],
        "passed_fixture_count": semantic_validation["passed_fixture_count"],
        "safe_output_count": len(outputs),
        "checksum_reference_count": len(targets),
        "build_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
        "fixture_bank_sha256": fixture_sha_after,
    }


def _tracked_checksum_targets() -> list[Path]:
    python_files = sorted(HERE.glob("*.py"))
    safe_outputs = [HERE / name for name in SAFE_OUTPUT_FILENAMES]
    docs = [DOC_ROOT / name for name in DOC_FILENAMES]
    targets = sorted(
        [*python_files, *safe_outputs, *docs],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    if (
        len(python_files) != 15
        or len(targets) != 36
        or len(targets) != len(set(targets))
        or any(not path.is_file() or path.is_symlink() for path in targets)
    ):
        raise RQ2C0R2ValidationError("RQ2-C0-R2 checksum target set incomplete")
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
    if failures or len(members) != 36:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: checksums")
    return {"status": "PASS", "referenced_tracked_output_path_count": len(members)}


def validate_python_ast() -> dict[str, Any]:
    files = sorted(HERE.glob("*.py"))
    forbidden_imports = {"openai", "firebase_admin", "sentence_transformers", "faiss", "chromadb"}
    observed: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(
                    item.name.split(".")[0]
                    for item in node.names
                    if item.name.split(".")[0] in forbidden_imports
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in forbidden_imports:
                    observed.add(root)
    if len(files) != 15 or observed:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: Python AST")
    return {"status": "PASS", "python_file_count": len(files), "forbidden_import_count": 0}


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _load_safe_output(name: str) -> Any:
    path = HERE / name
    if name.endswith(".jsonl"):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return json.loads(path.read_text(encoding="utf-8"))


def validate_safe_outputs() -> dict[str, Any]:
    values = {name: _load_safe_output(name) for name in SAFE_OUTPUT_FILENAMES}
    forbidden_keys = {
        "initial_store_state",
        "input_event_or_query",
        "raw_content",
        "memory_content",
        "student_text",
    }
    if any(forbidden_keys & set(_walk_keys(value)) for value in values.values()):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: governed payload")
    commitments = values["controlled_mechanism_fixture_semantic_commitment_v1.jsonl"]
    validation = values["controlled_mechanism_fixture_semantic_validation_v1_1.json"]
    if len(commitments) != 28 or validation.get("passed_fixture_count") != 28:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_FIXTURE_SEMANTIC_MISMATCH")
    if validation.get("fixture_bank_sha_before") != validation.get("fixture_bank_sha_after"):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_FIXTURE_BANK_MUTATED")
    if not validate_condition_semantics(values["p2_condition_semantics_v2_1.json"]):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_CONDITION_AMBIGUITY")
    return {
        "status": "PASS",
        "safe_output_count": len(values),
        "semantic_commitment_count": len(commitments),
        "governed_raw_key_count": 0,
    }


def _fixture_governed_strings() -> list[str]:
    strings: set[str] = set()
    for fixture, _ in load_frozen_fixture_rows():
        query = str(fixture["input_event_or_query"].get("text") or "").strip()
        if len(query) >= 24:
            strings.add(query)
        for item in fixture["initial_store_state"]:
            raw = str(item.get("raw_content") or "").strip()
            if len(raw) >= 24:
                strings.add(raw)
    return sorted(strings)


def governed_text_leak_scan() -> dict[str, Any]:
    paths = [ROOT / relative for relative in parse_output_checksums()]
    governed = _fixture_governed_strings()
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if ("/" + "Users/") in text or re.search(r"(?:^|\s)/(?:private|var|tmp)/", text):
            leaks.append(f"absolute_path:{path.name}")
        if any(value in text for value in governed):
            leaks.append(f"fixture_text:{path.name}")
    if leaks:
        raise RQ2C0R2ValidationError(
            "BLOCKED_RQ2_C0_R2_TEST_FAILURE: governed text " + ",".join(leaks)
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
    return path.startswith(ALLOWED_DOC_PREFIX) or path.startswith(ALLOWED_PACKAGE_PREFIX)


def protected_source_comparison() -> dict[str, Any]:
    changed = _changed_paths()
    forbidden = [path for path in changed if not _path_allowed(path)]
    existing = [
        path
        for path in changed
        if subprocess.run(
            ["git", "cat-file", "-e", f"{STARTING_HEAD}:{path}"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    ]
    if forbidden or existing:
        raise RQ2C0R2ValidationError(
            "BLOCKED_RQ2_C0_R2_PROTECTED_SOURCE_MUTATED: "
            + ",".join(forbidden + existing)
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
    forbidden = [path for path in staged if not _path_allowed(path)]
    if forbidden:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE: staged allowlist")
    return {"status": "PASS", "staged_path_count": len(staged)}


def assert_partition_access_allowed(partition: str) -> None:
    if str(partition).upper() in {"TRACK_A", "TRACK_B"}:
        raise PermissionError("sealed evaluation partition")


def validate_no_implementation() -> dict[str, Any]:
    report = _load_safe_output("rq2c0_r2_preflight_report_v1.json")
    forbidden_true = (
        "persistent_store_implemented",
        "p2_implemented",
        "retrieval_executed",
        "policy_selected_from_fixtures",
        "production_routing_changed",
        "rag_behavior_changed",
        "memory_behavior_changed",
        "planner_behavior_changed",
        "track_a_access",
        "track_b_access",
        "model_training",
        "network_access",
    )
    if any(report[key] for key in forbidden_true) or report["provider_calls"] != 0:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: implementation boundary")
    return {"status": "PASS", "implementation_count": 0}


def expected_review_members() -> set[str]:
    return {*parse_output_checksums(), CHECKSUM_RELATIVE.as_posix(), *REVIEW_EXTRA_MEMBERS}


def validate_review_package_contract() -> dict[str, Any]:
    members = expected_review_members()
    if not set(parse_output_checksums()).issubset(members) or any(
        "local_fixture" in name for name in members
    ):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: review package")
    return {
        "status": "PASS",
        "referenced_output_member_count": len(parse_output_checksums()),
        "expected_review_member_count": len(members),
        "local_fixture_member_count": 0,
    }


def validate_all() -> dict[str, Any]:
    fixture_sha_before = sha256_file(R1_FIXTURE_BANK_PATH)
    reports = {
        "starting_authority": verify_starting_authority(),
        "python_ast": validate_python_ast(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "staged_allowlist": staged_allowlist(),
        "implementation_boundary": validate_no_implementation(),
        "review_package_contract": validate_review_package_contract(),
    }
    fixture_sha_after = sha256_file(R1_FIXTURE_BANK_PATH)
    if fixture_sha_before != EXPECTED_FIXTURE_BANK_SHA256 or fixture_sha_after != fixture_sha_before:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_FIXTURE_BANK_MUTATED")
    return {
        "status": "PASS_EXECUTABLE_CONTRACT_FREEZE",
        "fixture_bank_sha256": fixture_sha_after,
        "reports": reports,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 27, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def validate_review_zip(zip_path: Path) -> dict[str, Any]:
    allowed = expected_review_members()
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
        if bad is not None or len(members) != len(set(members)) or set(members) != allowed:
            raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: review ZIP")
        for relative, expected in parse_output_checksums().items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != expected:
                raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: ZIP checksum")
        if any("local_fixture" in name or "payload_store" in name for name in members):
            raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: private ZIP member")
    return {
        "status": "PASS",
        "zip_integrity": "PASS",
        "zip_member_count": len(members),
        "referenced_output_member_count": len(parse_output_checksums()),
        "local_private_member_count": 0,
    }


def build_review_zip(zip_path: Path) -> dict[str, Any]:
    if zip_path.exists():
        raise RQ2C0R2ValidationError("review ZIP target already exists")
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE: worktree")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) != 1:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE: commit count")
    if _git("show", "-s", "--format=%s", "HEAD") != COMMIT_SUBJECT:
        raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_GIT_FAILURE: subject")

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
    payloads["review_metadata/review_scope.txt"] = (
        "RQ2-C0-R2 contract-only review package\n"
        "Local fixture text excluded\nPrivate payload text excluded\n"
        "Track A and Track B excluded\nModels excluded\n"
    ).encode("utf-8")
    checksums = "\n".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
        for name in sorted(payloads)
    ) + "\n"
    payloads["review_metadata/review_checksums.sha256"] = checksums.encode("utf-8")

    governed = _fixture_governed_strings()
    for name, payload in payloads.items():
        if name.endswith((".py", ".json", ".jsonl", ".md", ".txt", ".sha256")):
            text = payload.decode("utf-8")
            if ("/" + "Users/") in text or any(value in text for value in governed):
                raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: ZIP leak")
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
                raise RQ2C0R2ValidationError("BLOCKED_RQ2_C0_R2_TEST_FAILURE: internal checksum")
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
