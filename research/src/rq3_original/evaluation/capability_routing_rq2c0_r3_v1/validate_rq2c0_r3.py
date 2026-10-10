"""Deterministic builder, validator, and review ZIP gate for RQ2-C0-R3."""

from __future__ import annotations

import ast
import hashlib
import inspect
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
    EXPECTED_FIXTURE_BANK_SHA256,
    FIXTURE_BANK_PATH,
    HERE,
    RESULT_BRANCH,
    ROOT,
    SAFE_OUTPUT_FILENAMES,
    STARTING_HEAD,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .effective_contract import (
    candidate_ordering_amendment,
    effective_persistent_memory_contract,
    memory_safety_repair_authority,
    payload_scope_amendment,
    temporal_admission_amendment,
)
from .r2_identity import (
    protected_manifest,
    verify_fixture_identity,
    verify_r2_output_checksums,
    verify_r2_tracked_history,
    verify_starting_authority,
)
from .state_aware_eligibility import state_aware_eligible_records_v1_1


CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r3_v1/rq2c0_r3_output_checksums_v1.sha256"
)
ALLOWED_PACKAGE_PREFIX = "evaluation/capability_routing_rq2c0_r3_v1/"
ALLOWED_DOC_PREFIX = "docs/thesis_mainline/rq2/RQ2C0_R3_"
REVIEW_EXTRA_MEMBERS = frozenset(
    {
        "review_metadata/git_state.txt",
        "review_metadata/diff_summary.txt",
        "review_metadata/review_checksums.sha256",
        "review_metadata/review_scope.txt",
    }
)


class RQ2C0R3ValidationError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _preflight_report(starting: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2c0-r3-preflight-report-v1",
        "stage": "RQ2-C0-R3",
        "status": "PASS_MEMORY_SAFETY_CONTRACT_FREEZE",
        "starting_authority": dict(starting),
        "effective_primary_policy_id": "PMR_HYBRID_STATE_AWARE",
        "effective_state_aware_algorithm": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_admission_algorithm": "MEMORY_ADMISSION_V1_1",
        "effective_payload_scope": "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1",
        "r2_historical_files_changed": False,
        "fixture_changed": False,
        "fixture_membership_changed": False,
        "fixture_expected_decision_changed": False,
        "fixture_hash_changed": False,
        "P1_changed": False,
        "Capability_Gold_changed": False,
        "human_annotation_changed": False,
        "primary_policy_identity_changed": False,
        "retrieval_threshold_changed": False,
        "p2_implemented": False,
        "persistent_store_implemented": False,
        "actual_retrieval_executed": False,
        "production_routing_changed": False,
        "rag_memory_planner_behaviour_changed": False,
        "sealed_partition_access_count": 0,
        "model_training": False,
        "provider_calls": 0,
        "network_access": False,
        "expected_python_file_count": 9,
        "expected_safe_json_count": 6,
        "expected_document_count": 3,
        "expected_checksum_reference_count": 18,
    }


def _documents(outputs: Mapping[str, Any]) -> dict[str, str]:
    effective = outputs["effective_persistent_memory_contract_v1_2.json"]
    ordering = outputs["state_aware_candidate_ordering_amendment_v1.json"]
    admission = outputs["temporal_admission_safety_amendment_v1.json"]
    payload = outputs["text_only_payload_scope_amendment_v1.json"]

    ordering_doc = f"""# RQ2-C0-R3 State-Aware Candidate Ordering

RQ2-C0-R3 corrects a pre-implementation ordering defect without changing the policy family or primary identity. The effective primary remains `{effective['effective_primary_policy_id']}` and now uses `{effective['effective_state_aware_algorithm']}`.

Scope, deletion, temporal validity, stale/superseded/cancelled state, non-targeted completion, inactive state, active explicit-correction supersession, and conflict-group projection are resolved before dense Top-5. Dense ranking then operates only on eligible records. Invalid records therefore receive no dense rank and consume neither candidate-union nor final result slots.

The dense encoder, Top-k of {effective['unchanged']['dense_top_k']}, maximum results of {effective['unchanged']['maximum_retrieval_results']}, and seven-field R2 ranking tuple remain unchanged. The three non-state-aware policies retain exact R2 behaviour. This is a research-only effective contract; no store, encoder, persistent retrieval, P2 condition, or production route was executed.

Authority: `{ordering['authority_basis']}` on `{ordering['authorisation_date']}`. The correction was not selected from fixtures or model output.
"""

    admission_doc = f"""# RQ2-C0-R3 Temporal Admission Safety

`{admission['effective_algorithm']}` separates potential relevance signals from hard eligibility and effective support. Direct, structured, and dense relevance may be audited before guards, but none can override scope, deletion, temporal, state, or completion guards.

A temporally invalid candidate always has `guard_eligible = false`, `TEMPORALLY_INVALID`, no post-guard relevance support, and an empty admission basis, including when an explicit state link is present. Guard-eligible candidates retain the R2 definitions of DIRECT_SUPPORT, STRUCTURED_SUPPORT, and DENSE_SUPPORT. Maximum admission remains three; Top-1 is never admitted automatically. With no admitted memory, memory-required work clarifies and optional-memory work continues without memory.

The contract changes no production RAG, Memory, Planner, Source Scope, prompt, or routing behaviour. It defines the future offline RQ2-C1 implementation boundary only.
"""

    payload_doc = f"""# RQ2-C0-R3 Payload Scope and Effective Contract

The effective RQ2-C1 payload scope is `{effective['effective_payload_scope']}`. `structured_value` is compatibility-only and must be null or an empty mapping. Any non-empty mapping fails closed. Canonical text is the sole content used for the frozen R2-normalised hash, embedding text, retrieval text, and payload length. Typed state remains governed episode/index metadata and is not duplicated into the payload body.

General structured JSON canonicalisation and structured-payload hashing are future work; RQ2-C1 must not claim arbitrary structured payload support. Private content remains local-only, excluded from Git and the review ZIP, and no persistent store was created.

Future RQ2-C1 must import the R3 state-aware, admission, and payload validators recorded in `rq2c1_import_contract`; the superseded R2 state-aware ordering and admission guard sequence are not effective imports. R2 remains historical and byte-identical.

Authority: `{payload['authority_basis']}` on `{payload['authorisation_date']}`.
"""
    return {
        DOC_FILENAMES[0]: ordering_doc,
        DOC_FILENAMES[1]: admission_doc,
        DOC_FILENAMES[2]: payload_doc,
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
        len(python_files) != 9
        or len(safe_outputs) != 6
        or len(docs) != 3
        or len(targets) != 18
        or len(targets) != len(set(targets))
        or any(not path.is_file() or path.is_symlink() for path in targets)
    ):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: output set")
    return targets


def build_all() -> dict[str, Any]:
    fixture_before = sha256_file(FIXTURE_BANK_PATH)
    r2_before = verify_r2_tracked_history()["tracked_manifest_sha256"]
    starting = verify_starting_authority()
    outputs: dict[str, Any] = {
        "memory_safety_repair_authority_v1.json": memory_safety_repair_authority(),
        "state_aware_candidate_ordering_amendment_v1.json": candidate_ordering_amendment(),
        "temporal_admission_safety_amendment_v1.json": temporal_admission_amendment(),
        "text_only_payload_scope_amendment_v1.json": payload_scope_amendment(),
        "effective_persistent_memory_contract_v1_2.json": effective_persistent_memory_contract(),
    }
    outputs["rq2c0_r3_preflight_report_v1.json"] = _preflight_report(starting)
    if set(outputs) != set(SAFE_OUTPUT_FILENAMES):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: safe outputs")
    for name, value in outputs.items():
        write_canonical_json(HERE / name, value)
    for name, value in _documents(outputs).items():
        path = DOC_ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    targets = _tracked_checksum_targets()
    manifest = "\n".join(
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in targets
    ) + "\n"
    (ROOT / CHECKSUM_RELATIVE).write_text(manifest, encoding="utf-8")

    fixture_after = sha256_file(FIXTURE_BANK_PATH)
    r2_after = verify_r2_tracked_history()["tracked_manifest_sha256"]
    protected_manifest()
    if fixture_before != EXPECTED_FIXTURE_BANK_SHA256 or fixture_after != fixture_before:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    if r2_before != r2_after:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_R2_HISTORY_MUTATED")
    commitment = {
        path.relative_to(ROOT).as_posix(): sha256_file(path) for path in targets
    }
    return {
        "status": "PASS_MEMORY_SAFETY_CONTRACT_FREEZE",
        "safe_output_count": len(outputs),
        "checksum_reference_count": len(targets),
        "build_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
        "fixture_bank_sha256": fixture_after,
        "r2_tracked_manifest_sha256": r2_after,
    }


def parse_output_checksums() -> dict[str, str]:
    path = ROOT / CHECKSUM_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: checksums")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2C0R3ValidationError(
                "BLOCKED_RQ2_C0_R3_TEST_FAILURE: checksums"
            ) from exc
        rel = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: checksums")
        values[relative] = digest
    return values


def validate_output_checksums() -> dict[str, Any]:
    values = parse_output_checksums()
    failures = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if len(values) != 18 or failures:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: checksums")
    return {"status": "PASS", "referenced_output_count": len(values)}


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    forbidden_imports = {
        "openai",
        "firebase_admin",
        "sentence_transformers",
        "faiss",
        "chromadb",
    }
    observed: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    root = item.name.split(".")[0]
                    if root in forbidden_imports:
                        observed.add(root)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in forbidden_imports:
                    observed.add(root)
    if len(paths) != 9 or observed:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: Python AST")
    return {"status": "PASS", "python_file_count": len(paths), "forbidden_imports": 0}


def validate_feature_isolation() -> dict[str, Any]:
    source = inspect.getsource(state_aware_eligible_records_v1_1).lower()
    forbidden = ("gold", "fixture_category", "source_role", "expected_ids", "expected_")
    found = [token for token in forbidden if token in source]
    if found:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_STATE_AWARE_ORDERING")
    return {"status": "PASS", "forbidden_feature_reference_count": 0}


def _load_safe_output(name: str) -> Any:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_safe_outputs() -> dict[str, Any]:
    values = {name: _load_safe_output(name) for name in SAFE_OUTPUT_FILENAMES}
    forbidden_keys = {
        "query",
        "history",
        "fixture_text",
        "memory_text",
        "canonical_text",
        "structured_value",
        "student_data",
    }
    if any(forbidden_keys & set(_walk_keys(value)) for value in values.values()):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: unsafe output")
    effective = values["effective_persistent_memory_contract_v1_2.json"]
    if (
        effective["effective_primary_policy_id"] != "PMR_HYBRID_STATE_AWARE"
        or effective["effective_state_aware_algorithm"]
        != "PMR_HYBRID_STATE_AWARE_V1_1"
        or effective["effective_admission_algorithm"] != "MEMORY_ADMISSION_V1_1"
        or effective["effective_payload_scope"] != "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1"
    ):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_EFFECTIVE_CONTRACT")
    return {"status": "PASS", "safe_output_count": len(values), "unsafe_key_count": 0}


def _fixture_governed_strings() -> list[str]:
    strings: set[str] = set()
    for raw in FIXTURE_BANK_PATH.read_bytes().splitlines():
        fixture = json.loads(raw)
        query = str(fixture["input_event_or_query"].get("text") or "").strip()
        if len(query) >= 24:
            strings.add(query)
        for item in fixture["initial_store_state"]:
            value = str(item.get("raw_content") or "").strip()
            if len(value) >= 24:
                strings.add(value)
    return sorted(strings)


def governed_text_leak_scan() -> dict[str, Any]:
    paths = [ROOT / relative for relative in parse_output_checksums()]
    governed = _fixture_governed_strings()
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if ("/" + "Users/") in text or re.search(r"(?:^|\s)/(?:private|var|tmp)/", text):
            leaks.append("ABSOLUTE_PATH")
        if any(value in text for value in governed):
            leaks.append("GOVERNED_FIXTURE_TEXT")
    if leaks:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: governed text")
    return {
        "status": "PASS",
        "scanned_file_count": len(paths),
        "governed_string_count": len(governed),
        "leak_count": 0,
    }


def _zlist(command: list[str]) -> list[str]:
    return [
        item.decode("utf-8")
        for item in subprocess.check_output(command, cwd=ROOT).split(b"\0")
        if item
    ]


def _changed_paths() -> list[str]:
    tracked = set(
        _zlist(["git", "diff", "--name-only", "-z", STARTING_HEAD, "--"])
    )
    untracked = set(
        _zlist(["git", "ls-files", "--others", "--exclude-standard", "-z"])
    )
    return sorted(tracked | untracked)


def _path_allowed(relative: str) -> bool:
    return relative.startswith(ALLOWED_PACKAGE_PREFIX) or relative.startswith(
        ALLOWED_DOC_PREFIX
    )


def protected_source_comparison() -> dict[str, Any]:
    changed = _changed_paths()
    forbidden = [relative for relative in changed if not _path_allowed(relative)]
    existing = [
        relative
        for relative in changed
        if subprocess.run(
            ["git", "cat-file", "-e", f"{STARTING_HEAD}:{relative}"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ]
    if forbidden or existing:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_PROTECTED_SOURCE_MUTATED")
    protected = protected_manifest()
    return {
        "status": "PASS",
        "changed_path_count": len(changed),
        "protected_existing_change_count": 0,
        **protected,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = _zlist(["git", "diff", "--cached", "--name-only", "-z"])
    if any(not _path_allowed(relative) for relative in staged):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_GIT_FAILURE")
    return {"status": "PASS", "staged_path_count": len(staged)}


def assert_partition_access_allowed(partition: str) -> None:
    if str(partition).upper() in {"TRACK_A", "TRACK_B"}:
        raise PermissionError("sealed evaluation partition")


def validate_no_implementation() -> dict[str, Any]:
    report = _load_safe_output("rq2c0_r3_preflight_report_v1.json")
    forbidden_true = (
        "p2_implemented",
        "persistent_store_implemented",
        "actual_retrieval_executed",
        "production_routing_changed",
        "rag_memory_planner_behaviour_changed",
        "model_training",
        "network_access",
    )
    if (
        any(report[key] for key in forbidden_true)
        or report["provider_calls"] != 0
        or report["sealed_partition_access_count"] != 0
    ):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: implementation")
    return {"status": "PASS", "forbidden_implementation_count": 0}


def expected_review_members() -> set[str]:
    return {*parse_output_checksums(), CHECKSUM_RELATIVE.as_posix(), *REVIEW_EXTRA_MEMBERS}


def validate_review_package_contract() -> dict[str, Any]:
    members = expected_review_members()
    if len(parse_output_checksums()) != 18 or len(members) != 23:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: review package")
    if any(
        token in name.lower()
        for name in members
        for token in ("local_fixture", "payload_store", "model", "ledger")
    ):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: review package")
    return {
        "status": "PASS",
        "referenced_output_member_count": 18,
        "expected_review_member_count": 23,
    }


def validate_all() -> dict[str, Any]:
    fixture_before = sha256_file(FIXTURE_BANK_PATH)
    reports = {
        "starting_authority": verify_starting_authority(),
        "r2_output_checksums": verify_r2_output_checksums(),
        "r2_history": verify_r2_tracked_history(),
        "fixture_identity": verify_fixture_identity(),
        "python_ast": validate_python_ast(),
        "feature_isolation": validate_feature_isolation(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "staged_allowlist": staged_allowlist(),
        "implementation_boundary": validate_no_implementation(),
        "review_package": validate_review_package_contract(),
    }
    fixture_after = sha256_file(FIXTURE_BANK_PATH)
    if fixture_before != EXPECTED_FIXTURE_BANK_SHA256 or fixture_after != fixture_before:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_STARTING_STATE_MISMATCH")
    return {
        "status": "PASS_MEMORY_SAFETY_CONTRACT_FREEZE",
        "fixture_bank_sha256": fixture_after,
        "reports": reports,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 27, 15, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def validate_review_zip(zip_path: Path) -> dict[str, Any]:
    allowed = expected_review_members()
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
        if bad is not None or len(members) != len(set(members)) or set(members) != allowed:
            raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: review ZIP")
        for relative, digest in parse_output_checksums().items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != digest:
                raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: ZIP checksum")
        if any(
            token in name.lower()
            for name in members
            for token in ("local_fixture", "payload_store", "model", "ledger")
        ):
            raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: ZIP member")
    return {
        "status": "PASS",
        "zip_integrity": "PASS",
        "zip_member_count": len(members),
        "referenced_output_member_count": len(parse_output_checksums()),
    }


def build_review_zip(zip_path: Path) -> dict[str, Any]:
    if zip_path.exists():
        raise RQ2C0R3ValidationError("review ZIP target already exists")
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_GIT_FAILURE")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_GIT_FAILURE: worktree")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_GIT_FAILURE")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) != 1:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_GIT_FAILURE: commit count")
    if _git("show", "-s", "--format=%s", "HEAD") != COMMIT_SUBJECT:
        raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_GIT_FAILURE: commit subject")

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
        "RQ2-C0-R3 research-only memory-safety contract review package\n"
        "Fixtures, private payloads, sealed partitions, models, and ledgers excluded\n"
        "No persistent retrieval, P2 condition, or production route executed\n"
    ).encode("utf-8")
    review_checksums = "\n".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
        for name in sorted(payloads)
    ) + "\n"
    payloads["review_metadata/review_checksums.sha256"] = review_checksums.encode(
        "utf-8"
    )

    governed = _fixture_governed_strings()
    for name, payload in payloads.items():
        text = payload.decode("utf-8")
        if ("/" + "Users/") in text or any(value in text for value in governed):
            raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: ZIP leak")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(_zip_info(name), payloads[name])
    verification = validate_review_zip(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        lines = archive.read("review_metadata/review_checksums.sha256").decode().splitlines()
        for line in lines:
            digest, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RQ2C0R3ValidationError("BLOCKED_RQ2_C0_R3_TEST_FAILURE: internal checksum")
    return {
        **verification,
        "review_checksum_entries": len(lines),
        "governed_text_leak_scan": "PASS",
        "sha256": sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "path": str(zip_path),
    }


def main() -> int:
    print(json.dumps({"build": build_all(), "validation": validate_all()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
