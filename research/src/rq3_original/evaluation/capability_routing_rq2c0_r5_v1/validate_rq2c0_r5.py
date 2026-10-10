"""Deterministic builder, validator, and review-ZIP gate for RQ2-C0-R5."""

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
from .effective_contract import safe_contract_outputs
from .r4_identity import (
    protected_manifest,
    verify_fixture_identity,
    verify_r2_output_checksums,
    verify_r2_tracked_history,
    verify_r3_output_checksums,
    verify_r3_tracked_history,
    verify_r4_output_checksums,
    verify_r4_tracked_history,
    verify_starting_authority,
)


CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_r5_v1/rq2c0_r5_output_checksums_v1.sha256"
)
ALLOWED_PACKAGE_PREFIX = "evaluation/capability_routing_rq2c0_r5_v1/"
ALLOWED_DOC_PREFIX = "docs/thesis_mainline/rq2/RQ2C0_R5_"
REVIEW_EXTRA_MEMBERS = frozenset(
    {
        "review_metadata/git_state.txt",
        "review_metadata/diff_summary.txt",
        "review_metadata/review_checksums.sha256",
        "review_metadata/review_scope.txt",
    }
)


class RQ2C0R5ValidationError(RuntimeError):
    """Fail-closed R5 build or validation error."""


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _preflight_report(starting: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2c0-r5-preflight-report-v1",
        "stage": "RQ2-C0-R5",
        "status": "PASS_VALIDATED_BUNDLE_TIME_INTEGRITY_FREEZE",
        "starting_authority": dict(starting),
        "effective_primary_policy_id": "PMR_HYBRID_STATE_AWARE",
        "effective_retrieval": "PMR_HYBRID_STATE_AWARE_V1_1",
        "effective_admission": "MEMORY_ADMISSION_V1_1",
        "effective_payload_scope": "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1",
        "effective_payload_binding": "PERSISTENT_MEMORY_PAYLOAD_BINDING_V1_3",
        "effective_validated_bundle": "PERSISTENT_MEMORY_VALIDATED_BUNDLE_V1_4",
        "effective_retrieval_plan": "VALIDATED_RETRIEVAL_PLAN_V1_2",
        "effective_interval_contract": "TIMEZONE_AWARE_RETRIEVAL_INTERVAL_V1_1",
        "r2_historical_files_changed": False,
        "r3_historical_files_changed": False,
        "r4_historical_files_changed": False,
        "fixture_text_changed": False,
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
        "expected_python_file_count": 12,
        "expected_safe_json_count": 10,
        "expected_document_count": 4,
        "expected_checksum_reference_count": 26,
    }


def _documents(outputs: Mapping[str, Any]) -> dict[str, str]:
    bundle = outputs["validated_memory_bundle_contract_v1_4.json"]
    fingerprint = outputs["bundle_fingerprint_contract_v1.json"]
    identifiers = outputs["opaque_identifier_contract_v1.json"]
    retrieval_time = outputs["retrieval_time_integrity_contract_v1_1.json"]
    plan = outputs["validated_retrieval_plan_contract_v1_2.json"]
    guard = outputs["downstream_bundle_guard_contract_v1_4.json"]
    effective = outputs["effective_persistent_memory_contract_v1_4.json"]

    bundle_doc = f"""# RQ2-C0-R5 Validated Bundle and Fingerprint Binding

RQ2-C0-R5 replaces transferable, free-standing validation receipts with `{bundle['bundle_schema']}`. The only creation path runs the R4 composite validator, validates every governed opaque identifier, validates the retrieval-validity interval, computes three domain-separated component fingerprints and then computes the composite input-binding fingerprint. A failed stage returns no bundle.

Canonical component bytes use dataclass field names, sorted mapping keys, preserved sequence order, exact strings, UTF-8 and compact sorted JSON. NaN and Infinity are rejected. Private canonical content participates only in the local payload fingerprint and is never written to tracked outputs or the review package. The fingerprint is an integrity binding, not a secret MAC, digital signature or caller-authentication mechanism.

Every downstream use reconstructs the expected bundle from the exact retained episode, reference and private payload, reruns R4 plus the R5 identifier and interval checks, and compares all component/composite fingerprints, validator IDs, the complete validation trace and contract hash. Mutation, transfer, stale reuse and fingerprint swapping therefore fail closed. A manually assembled bundle can pass only when its complete inputs and every recomputed value are genuinely valid; no caller-identity claim is made.
"""

    identifier_doc = f"""# RQ2-C0-R5 Opaque Identifier Integrity

`{identifiers['contract_id']}` applies independently to every episode, reference and payload occurrence of memory ID, payload ID, episode ID and source-turn ID. Each value must already be a non-empty NFC string, have no surrounding whitespace or NUL, and be at most {identifiers['rules']['maximum_utf8_bytes']} UTF-8 bytes. Values are never trimmed, casefolded, punctuation-stripped, normalised after receipt or replaced automatically.

R4 equality checks remain historical and unchanged, while R5 adds schema integrity before a validated bundle can exist. Consequently, equal empty identifiers no longer authorise provenance or downstream use. Store-wide uniqueness remains a mandatory RQ2-C1 store prerequisite and is not implemented in this contract-only stage.
"""

    time_doc = f"""# RQ2-C0-R5 Retrieval Time and Interval Contract

The effective interval contract is `{retrieval_time['contract_id']}`. `valid_from`, non-null `valid_until`, and retrieval `query_time` must be parseable timezone-aware ISO-8601 values and are converted to UTC instants. Episode `timezone` remains descriptive metadata and cannot repair a missing offset. The historical R2 naive-time helper is not an effective RQ2-C1 interface.

Non-null intervals must be strictly increasing. Retrieval validity is start-inclusive and end-exclusive: `valid_from_utc <= query_time_utc`, and either no end exists or `query_time_utc < valid_until_utc`. Equivalent offsets yield identical decisions.

The `{plan['future_rq2c1_required_schema']}` wrapper validates the pseudonymous scope and query time, stores the canonical UTC instant, binds target types, both query representations, resolver authorisation and memory-required state, and carries a deterministic fingerprint. Gold, source-role and fixture-expected fields are excluded. This stage does not run retrieval.
"""

    effective_doc = f"""# RQ2-C0-R5 Effective RQ2-C1 Entry Contract

The final pre-implementation contract is `{effective['schema_version']}`. It preserves R2 as the historical base, R3 candidate/admission safety, R4 payload integrity, `{effective['effective_retrieval']}` retrieval, `{effective['effective_admission']}` admission and `{effective['effective_payload_scope']}` payload scope. Primary identity remains `PMR_HYBRID_STATE_AWARE`; ranking, Top-k and thresholds are unchanged.

Future offline RQ2-C1 must use the five exact imports recorded in `rq2c1_import_contract`: create the validated bundle, fully revalidate it, guard every downstream interface, create a validated retrieval plan, and use aware-time interval validity. `{guard['accepted_authorisation_object']}` is the sole downstream authorisation object. The R4 standalone receipt/guard, raw R2 plan and R2 naive-time temporal helper are explicitly unauthorised.

This is a research-only contract freeze. It implements no persistent store, embedding retrieval, P2 condition, production route, RAG, Memory or Planner behaviour. Fixtures, P1, Capability Gold and all human decisions remain unchanged; Track A and Track B were not accessed.
"""
    return {
        DOC_FILENAMES[0]: bundle_doc,
        DOC_FILENAMES[1]: identifier_doc,
        DOC_FILENAMES[2]: time_doc,
        DOC_FILENAMES[3]: effective_doc,
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
        len(python_files) != 12
        or len(safe_outputs) != 10
        or len(docs) != 4
        or len(targets) != 26
        or len(targets) != len(set(targets))
        or any(not path.is_file() or path.is_symlink() for path in targets)
    ):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: output set")
    return targets


def build_all() -> dict[str, Any]:
    fixture_before = sha256_file(FIXTURE_BANK_PATH)
    histories_before = {
        "R2": verify_r2_tracked_history()["tracked_manifest_sha256"],
        "R3": verify_r3_tracked_history()["tracked_manifest_sha256"],
        "R4": verify_r4_tracked_history()["tracked_manifest_sha256"],
    }
    starting = verify_starting_authority()
    outputs = safe_contract_outputs()
    outputs["rq2c0_r5_preflight_report_v1.json"] = _preflight_report(starting)
    if set(outputs) != set(SAFE_OUTPUT_FILENAMES):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: safe outputs")
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
    histories_after = {
        "R2": verify_r2_tracked_history()["tracked_manifest_sha256"],
        "R3": verify_r3_tracked_history()["tracked_manifest_sha256"],
        "R4": verify_r4_tracked_history()["tracked_manifest_sha256"],
    }
    protected_manifest()
    if fixture_before != EXPECTED_FIXTURE_BANK_SHA256 or fixture_after != fixture_before:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    if histories_before != histories_after:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    commitment = {
        path.relative_to(ROOT).as_posix(): sha256_file(path) for path in targets
    }
    return {
        "status": "PASS_VALIDATED_BUNDLE_TIME_INTEGRITY_FREEZE",
        "safe_output_count": len(outputs),
        "checksum_reference_count": len(targets),
        "build_commitment_sha256": sha256_bytes(canonical_json_bytes(commitment)),
        "fixture_bank_sha256": fixture_after,
        "historical_manifest_sha256": histories_after,
    }


def parse_output_checksums() -> dict[str, str]:
    path = ROOT / CHECKSUM_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: checksums")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2C0R5ValidationError(
                "BLOCKED_RQ2_C0_R5_TEST_FAILURE: checksums"
            ) from exc
        rel = Path(relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in values
            or rel.is_absolute()
            or ".." in rel.parts
        ):
            raise RQ2C0R5ValidationError(
                "BLOCKED_RQ2_C0_R5_TEST_FAILURE: checksums"
            )
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
    if len(values) != 26 or failures:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: checksums")
    return {"status": "PASS", "referenced_output_count": len(values)}


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    forbidden_imports = {
        "openai",
        "firebase_admin",
        "sentence_transformers",
        "faiss",
        "chromadb",
        "requests",
        "httpx",
        "socket",
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
    if len(paths) != 12 or observed:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: Python AST")
    return {"status": "PASS", "python_file_count": len(paths), "forbidden_imports": 0}


def _load_safe_output(name: str) -> Any:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def validate_safe_outputs() -> dict[str, Any]:
    values = {name: _load_safe_output(name) for name in SAFE_OUTPUT_FILENAMES}
    if values["validated_bundle_time_integrity_authority_v1.json"] != values[
        "validation_time_integrity_authority_v1.json"
    ]:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: authority aliases")
    strings = [item for value in values.values() for item in _walk_strings(value)]
    if any(
        ("/" + "Users/") in item
        or re.search(r"(?:^|\s)/(?:private|var|tmp)/", item)
        or "@example." in item
        for item in strings
    ):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: unsafe output")
    effective = values["effective_persistent_memory_contract_v1_4.json"]
    if (
        effective["effective_validated_bundle"]
        != "PERSISTENT_MEMORY_VALIDATED_BUNDLE_V1_4"
        or effective["effective_retrieval_plan"] != "VALIDATED_RETRIEVAL_PLAN_V1_2"
        or effective["effective_interval_contract"]
        != "TIMEZONE_AWARE_RETRIEVAL_INTERVAL_V1_1"
        or effective["bundle_required_for_all_downstream_interfaces"] is not True
        or effective["free_standing_validation_receipt_authorised"] is not False
        or effective["episode_timezone_authoritative"] is not False
    ):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_EFFECTIVE_CONTRACT")
    return {"status": "PASS", "safe_output_count": len(values), "unsafe_value_count": 0}


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
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: governed text")
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
    tracked = set(_zlist(["git", "diff", "--name-only", "-z", STARTING_HEAD, "--"]))
    untracked = set(_zlist(["git", "ls-files", "--others", "--exclude-standard", "-z"]))
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
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "changed_path_count": len(changed),
        "protected_existing_change_count": 0,
        **protected_manifest(),
    }


def staged_allowlist() -> dict[str, Any]:
    staged = _zlist(["git", "diff", "--cached", "--name-only", "-z"])
    if any(not _path_allowed(relative) for relative in staged):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_GIT_FAILURE")
    return {"status": "PASS", "staged_path_count": len(staged)}


def assert_partition_access_allowed(partition: str) -> None:
    if str(partition).upper() in {"TRACK_A", "TRACK_B"}:
        raise PermissionError("sealed evaluation partition")


def validate_no_implementation() -> dict[str, Any]:
    report = _load_safe_output("rq2c0_r5_preflight_report_v1.json")
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
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: implementation")
    return {"status": "PASS", "forbidden_implementation_count": 0}


def expected_review_members() -> set[str]:
    return {*parse_output_checksums(), CHECKSUM_RELATIVE.as_posix(), *REVIEW_EXTRA_MEMBERS}


def validate_review_package_contract() -> dict[str, Any]:
    members = expected_review_members()
    if len(parse_output_checksums()) != 26 or len(members) != 31:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: review package")
    prohibited = (
        "local_fixture",
        "payload_store",
        "local_artifact",
        "track_a",
        "track_b",
        "model",
        "ledger",
    )
    if any(token in name.lower() for name in members for token in prohibited):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: review package")
    return {
        "status": "PASS",
        "referenced_output_member_count": 26,
        "expected_review_member_count": 31,
    }


def validate_all() -> dict[str, Any]:
    fixture_before = sha256_file(FIXTURE_BANK_PATH)
    reports = {
        "starting_authority": verify_starting_authority(),
        "r2_output_checksums": verify_r2_output_checksums(),
        "r3_output_checksums": verify_r3_output_checksums(),
        "r4_output_checksums": verify_r4_output_checksums(),
        "r2_history": verify_r2_tracked_history(),
        "r3_history": verify_r3_tracked_history(),
        "r4_history": verify_r4_tracked_history(),
        "fixture_identity": verify_fixture_identity(),
        "python_ast": validate_python_ast(),
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
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_HISTORY_MUTATED")
    return {
        "status": "PASS_VALIDATED_BUNDLE_TIME_INTEGRITY_FREEZE",
        "fixture_bank_sha256": fixture_after,
        "reports": reports,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 27, 17, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def validate_review_zip(zip_path: Path) -> dict[str, Any]:
    allowed = expected_review_members()
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
        if bad is not None or len(members) != len(set(members)) or set(members) != allowed:
            raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: review ZIP")
        for relative, digest in parse_output_checksums().items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != digest:
                raise RQ2C0R5ValidationError(
                    "BLOCKED_RQ2_C0_R5_TEST_FAILURE: ZIP checksum"
                )
        review_lines = archive.read(
            "review_metadata/review_checksums.sha256"
        ).decode("utf-8").splitlines()
        for line in review_lines:
            digest, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RQ2C0R5ValidationError(
                    "BLOCKED_RQ2_C0_R5_TEST_FAILURE: internal checksum"
                )
    return {
        "status": "PASS",
        "zip_integrity": "PASS",
        "zip_member_count": len(members),
        "referenced_output_member_count": len(parse_output_checksums()),
        "review_checksum_entries": len(review_lines),
    }


def build_review_zip(zip_path: Path) -> dict[str, Any]:
    if zip_path.exists():
        raise RQ2C0R5ValidationError("review ZIP target already exists")
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_GIT_FAILURE")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_GIT_FAILURE: worktree")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_GIT_FAILURE")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) != 1:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_GIT_FAILURE: commit count")
    if _git("show", "-s", "--format=%s", "HEAD") != COMMIT_SUBJECT:
        raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_GIT_FAILURE: commit subject")

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
        "RQ2-C0-R5 research-only validated-bundle and retrieval-time contract review package\n"
        "Private payloads, raw scope values, queries, fixtures, sealed partitions, models, and ledgers excluded\n"
        "No persistent store, retrieval, P2 condition, or production route implemented\n"
    ).encode("utf-8")
    review_checksums = "\n".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
        for name in sorted(payloads)
    ) + "\n"
    payloads["review_metadata/review_checksums.sha256"] = review_checksums.encode(
        "utf-8"
    )

    governed = _fixture_governed_strings()
    for payload in payloads.values():
        text = payload.decode("utf-8")
        if ("/" + "Users/") in text or any(value in text for value in governed):
            raise RQ2C0R5ValidationError("BLOCKED_RQ2_C0_R5_TEST_FAILURE: ZIP leak")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(_zip_info(name), payloads[name])
    verification = validate_review_zip(zip_path)
    return {
        **verification,
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
