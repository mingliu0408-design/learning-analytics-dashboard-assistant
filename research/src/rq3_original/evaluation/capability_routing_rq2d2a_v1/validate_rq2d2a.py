"""RQ2-D2A validation, leak scanning, checksums, and review ZIP gates."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from typing import Any, Iterable

from . import (
    ADJUDICATION_PACKET_RELATIVE,
    CANONICAL_A_RELATIVE,
    CANONICAL_B_RELATIVE,
    COMPLETED_A_NAME,
    COMPLETED_A_SHA256,
    COMPLETED_B_NAME,
    COMPLETED_B_SHA256,
    HERE,
    ORIGINAL_A_RELATIVE,
    ORIGINAL_B_RELATIVE,
    REVIEW_ZIP_NAME,
    ROOT,
    START_HEAD,
    TARGET_BRANCH,
    csv_rows,
    downloads_path,
    sha256_bytes,
    sha256_file,
)
from .adjudication_packet_builder import ADJUDICATION_FIELDS, PACKET_FIELDS
from .disagreement_manifest import build_disagreement_manifest
from .starting_state import git, validate_starting_state
from .track_b_agreement import calculate_agreement, validate_expected_agreement
from .validate_completed_packets import validate_completed_packets


PYTHON_FILES = (
    "__init__.py",
    "starting_state.py",
    "completed_packet_authority.py",
    "crossed_packet_lineage.py",
    "canonicalize_track_b_review_packets.py",
    "validate_completed_packets.py",
    "track_b_agreement.py",
    "disagreement_manifest.py",
    "adjudication_packet_builder.py",
    "finalise_rq2d2a.py",
    "validate_rq2d2a.py",
    "test_rq2d2a_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2D2A_COMPLETED_PACKET_AUTHORITY_AND_CANONICALISATION.md",
    "RQ2D2A_INTER_REVIEWER_AGREEMENT.md",
    "RQ2D2A_HUMAN_ADJUDICATION_HANDOFF.md",
    "RQ2D2A_GOVERNANCE_AND_LIMITATIONS.md",
)
SAFE_JSON_FILES = (
    "rq2d2a_preflight_report_v1.json",
    "track_b_completed_packet_authority_v1.json",
    "track_b_crossed_packet_assignment_attestation_v1.json",
    "track_b_packet_canonicalisation_manifest_v1.json",
    "track_b_completed_packet_validation_v1.json",
    "track_b_inter_reviewer_agreement_v1.json",
    "track_b_disagreement_manifest_v1.json",
    "track_b_adjudication_packet_manifest_v1.json",
    "rq2d2a_validation_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2a_v1/rq2d2a_output_checksums_v1.sha256"
)
IGNORE_ADDITIONS = (
    "evaluation/capability_routing_rq2d2a_v1/local_review/",
    "evaluation/capability_routing_rq2d2a_v1/local_adjudication/",
)
REVIEW_EXTRA_MEMBERS = (
    "review/GIT_STATE.txt",
    "review/DIFF_SUMMARY.txt",
    "review/GITIGNORE_DIFF.patch",
    "review/GITIGNORE_SHA256.txt",
    "review/REVIEW_CHECKSUMS.sha256",
)


class RQ2D2AValidationError(RuntimeError):
    pass


def _allowed_path(relative: str) -> bool:
    return (
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_rq2d2a_v1/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2D2A_")
    )


def assert_change_scope() -> None:
    for arguments in (
        ("status", "--porcelain=v1", "--untracked-files=all"),
        ("diff", "--name-only", START_HEAD),
        ("diff", "--cached", "--name-only", START_HEAD),
    ):
        lines = git(*arguments).stdout.decode().splitlines()
        for line in lines:
            relative = line[3:] if arguments[0] == "status" else line
            if " -> " in relative:
                relative = relative.split(" -> ", 1)[1]
            if relative and not _allowed_path(relative):
                raise RQ2D2AValidationError(
                    "BLOCKED_RQ2_D2A_PROTECTED_SOURCE_MUTATED"
                )


def assert_gitignore_contract() -> None:
    base = git("show", f"{START_HEAD}:.gitignore").stdout.decode("utf-8")
    expected = base.rstrip("\n") + "\n" + "\n".join(IGNORE_ADDITIONS) + "\n"
    if (ROOT / ".gitignore").read_text(encoding="utf-8") != expected:
        raise RQ2D2AValidationError(".gitignore differs from exact local additions")


def assert_all_python_ast() -> None:
    for name in PYTHON_FILES:
        path = HERE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def assert_no_provider_network_or_model_surface() -> None:
    prohibited_imports = {
        "openai",
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "socket",
        "firebase_admin",
        "torch",
        "transformers",
        "sentence_transformers",
    }
    for name in PYTHON_FILES:
        tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            str(node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        if imports & prohibited_imports:
            raise RQ2D2AValidationError(f"prohibited import in {name}")
    source = "\n".join((HERE / name).read_text(encoding="utf-8") for name in PYTHON_FILES)
    # Split the literals so the scanner does not match its own deny-list source.
    prohibited_local_asset_names = (
        "raw_to_" + "blinded_mapping_v1",
        "track_b_hidden_" + "legacy_escrow",
        "TRACK_B_" + "BLIND_KEY",
    )
    if any(marker in source for marker in prohibited_local_asset_names):
        raise RQ2D2AValidationError("prohibited D1 local asset surface in D2A code")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_safe_json() -> None:
    absolute_marker = "/" + "Users" + "/"
    prohibited_keys = {
        "current_query",
        "current_page",
        "necessary_conversation_history",
        "reviewer_rationale",
        "query",
        "history",
        "rationale",
        "raw_id",
        "legacy_label",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) & prohibited_keys:
                raise RQ2D2AValidationError("governed field found in safe JSON")
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for name in SAFE_JSON_FILES:
        value = _json(HERE / name)
        text = json.dumps(value, ensure_ascii=False)
        if absolute_marker in text:
            raise RQ2D2AValidationError(f"absolute local path in {name}")
        walk(value)


def _governed_values() -> list[str]:
    values: set[str] = set()
    for relative in (CANONICAL_A_RELATIVE, CANONICAL_B_RELATIVE):
        for row in csv_rows(ROOT / relative):
            for field in (
                "current_query",
                "current_page",
                "necessary_conversation_history",
                "reviewer_rationale",
            ):
                value = str(row.get(field) or "").strip()
                if len(value) >= 16:
                    values.add(value)
    return sorted(values)


def tracked_output_paths() -> list[Path]:
    return sorted(
        [
            *(HERE / name for name in PYTHON_FILES),
            *(ROOT / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
            *(HERE / name for name in SAFE_JSON_FILES),
        ],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    governed = _governed_values()
    scanned = list(paths) if paths is not None else tracked_output_paths()
    leaks: list[str] = []
    absolute_marker = "/" + "Users" + "/"
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if absolute_marker in text or any(value in text for value in governed):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RQ2D2AValidationError("governed-text leak: " + ", ".join(leaks))
    return {
        "status": "PASS",
        "governed_value_count": len(governed),
        "scanned_file_count": len(scanned),
        "leak_count": 0,
    }


def assert_local_boundaries() -> None:
    for relative in (
        ORIGINAL_A_RELATIVE,
        ORIGINAL_B_RELATIVE,
        CANONICAL_A_RELATIVE,
        CANONICAL_B_RELATIVE,
        ADJUDICATION_PACKET_RELATIVE,
    ):
        if git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2D2AValidationError(f"local artifact is not ignored: {relative}")
        if not git("ls-files", "--error-unmatch", relative.as_posix(), check=False).returncode:
            raise RQ2D2AValidationError(f"local artifact is tracked: {relative}")


def assert_staged_allowlist() -> None:
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode().splitlines()
    for relative in names:
        if not _allowed_path(relative) or "/local_review/" in relative or "/local_adjudication/" in relative:
            raise RQ2D2AValidationError(f"unsafe staged path: {relative}")


def assert_protected_sources_unchanged() -> None:
    assert_change_scope()
    identities = (
        (downloads_path(COMPLETED_A_NAME), COMPLETED_A_SHA256),
        (downloads_path(COMPLETED_B_NAME), COMPLETED_B_SHA256),
    )
    if any(path.is_symlink() or not path.is_file() or sha256_file(path) != digest for path, digest in identities):
        raise RQ2D2AValidationError("completed packet input changed")
    validate_starting_state()


def write_output_checksums() -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in tracked_output_paths()
    ]
    (ROOT / CHECKSUM_RELATIVE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_output_checksums() -> dict[str, Any]:
    expected = {path.relative_to(ROOT).as_posix() for path in tracked_output_paths()}
    observed: set[str] = set()
    manifest = ROOT / CHECKSUM_RELATIVE
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        observed.add(relative)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2D2AValidationError(f"output checksum mismatch: {relative}")
    if observed != expected:
        raise RQ2D2AValidationError("output checksum referenced-path set mismatch")
    return {"status": "PASS", "referenced_tracked_output_count": len(observed)}


def assert_generated_results() -> None:
    rows_a, rows_b, packet_validation = validate_completed_packets(ROOT)
    if packet_validation != _json(HERE / "track_b_completed_packet_validation_v1.json"):
        raise RQ2D2AValidationError("packet validation output is not reproducible")
    agreement = calculate_agreement(rows_a, rows_b)
    validate_expected_agreement(agreement)
    if agreement != _json(HERE / "track_b_inter_reviewer_agreement_v1.json"):
        raise RQ2D2AValidationError("agreement output is not reproducible")
    disagreement = build_disagreement_manifest(rows_a, rows_b)
    if disagreement != _json(HERE / "track_b_disagreement_manifest_v1.json"):
        raise RQ2D2AValidationError("disagreement manifest is not reproducible")
    packet_rows = csv_rows(ROOT / ADJUDICATION_PACKET_RELATIVE)
    if len(packet_rows) != 23 or tuple(packet_rows[0]) != PACKET_FIELDS:
        raise RQ2D2AValidationError("adjudication packet shape mismatch")
    if any(row[field] for row in packet_rows for field in ADJUDICATION_FIELDS):
        raise RQ2D2AValidationError("adjudication field was prefilled")


def _checksum_member_paths() -> list[str]:
    return [
        line.split("  ", 1)[1]
        for line in (ROOT / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines()
        if line
    ]


def expected_review_members() -> set[str]:
    return {
        *_checksum_member_paths(),
        CHECKSUM_RELATIVE.as_posix(),
        *REVIEW_EXTRA_MEMBERS,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _git_review_metadata() -> dict[str, bytes]:
    branch = git("branch", "--show-current").stdout.decode().strip()
    head = git("rev-parse", "HEAD").stdout.decode().strip()
    relative = int(git("rev-list", "--count", f"{START_HEAD}..HEAD").stdout.decode().strip())
    status = git("status", "--porcelain=v1", "--untracked-files=all").stdout.decode()
    if branch != TARGET_BRANCH or relative != 1 or status:
        raise RQ2D2AValidationError("review ZIP requires clean committed D2A state")
    git_state = (
        f"branch={branch}\nhead={head}\nbase={START_HEAD}\n"
        f"relative_commits={relative}\nworking_tree_clean=true\nindex_clean=true\n"
        f"remote_count=0\ntag_count=0\n"
    ).encode("utf-8")
    diff_summary = git("diff", "--stat", START_HEAD, "HEAD").stdout
    gitignore_diff = git("diff", START_HEAD, "HEAD", "--", ".gitignore").stdout
    gitignore_hash = f"{sha256_file(ROOT / '.gitignore')}  .gitignore\n".encode("utf-8")
    return {
        "review/GIT_STATE.txt": git_state,
        "review/DIFF_SUMMARY.txt": diff_summary,
        "review/GITIGNORE_DIFF.patch": gitignore_diff,
        "review/GITIGNORE_SHA256.txt": gitignore_hash,
    }


def create_review_zip() -> dict[str, Any]:
    validate_all(require_review_zip=False)
    core_paths = [ROOT / relative for relative in _checksum_member_paths()]
    core_paths.append(ROOT / CHECKSUM_RELATIVE)
    members: dict[str, bytes] = {
        path.relative_to(ROOT).as_posix(): path.read_bytes() for path in core_paths
    }
    members.update(_git_review_metadata())
    review_checksums = "\n".join(
        f"{sha256_bytes(value)}  {name}" for name, value in sorted(members.items())
    ) + "\n"
    members["review/REVIEW_CHECKSUMS.sha256"] = review_checksums.encode("utf-8")
    if set(members) != expected_review_members():
        raise RQ2D2AValidationError("BLOCKED_RQ2_D2A_REVIEW_PACKAGE_INCOMPLETE")
    destination = downloads_path(REVIEW_ZIP_NAME)
    with zipfile.ZipFile(destination, "w") as archive:
        for name, value in sorted(members.items()):
            archive.writestr(_zip_info(name), value)
    result = validate_review_zip()
    result["review_zip_sha256"] = sha256_file(destination)
    result["review_zip_size_bytes"] = destination.stat().st_size
    return result


def validate_review_zip() -> dict[str, Any]:
    path = downloads_path(REVIEW_ZIP_NAME)
    if path.is_symlink() or not path.is_file():
        raise RQ2D2AValidationError("review ZIP missing or not regular")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RQ2D2AValidationError("review ZIP integrity failure")
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_review_members():
            raise RQ2D2AValidationError("BLOCKED_RQ2_D2A_REVIEW_PACKAGE_INCOMPLETE")
        values = {name: archive.read(name) for name in names}
    current_members = {
        relative: (ROOT / relative).read_bytes()
        for relative in (*_checksum_member_paths(), CHECKSUM_RELATIVE.as_posix())
    }
    current_members.update(_git_review_metadata())
    if any(values[name] != value for name, value in current_members.items()):
        raise RQ2D2AValidationError("review ZIP does not match current committed outputs")
    checksum_lines = values["review/REVIEW_CHECKSUMS.sha256"].decode("utf-8").splitlines()
    checked: set[str] = set()
    for line in checksum_lines:
        digest, name = line.split("  ", 1)
        if name == "review/REVIEW_CHECKSUMS.sha256" or sha256_bytes(values[name]) != digest:
            raise RQ2D2AValidationError("review checksum mismatch")
        checked.add(name)
    if checked != set(values) - {"review/REVIEW_CHECKSUMS.sha256"}:
        raise RQ2D2AValidationError("review checksum coverage mismatch")
    governed = _governed_values()
    absolute_marker = "/" + "Users" + "/"
    for name, value in values.items():
        text = value.decode("utf-8")
        if absolute_marker in text or any(item in text for item in governed):
            raise RQ2D2AValidationError(f"governed text in review ZIP: {name}")
    referenced = set(_checksum_member_paths())
    if not referenced <= set(values):
        raise RQ2D2AValidationError("output-checksum reference missing from review ZIP")
    return {
        "zip_integrity": "PASS",
        "exact_allowlist": "PASS",
        "internal_checksums": "PASS",
        "governed_text_leak_scan": "PASS",
        "member_count": len(values),
        "referenced_tracked_output_count": len(referenced),
        "referenced_output_member_count": len(referenced & set(values)),
    }


def validate_all(*, require_review_zip: bool = False) -> None:
    validate_starting_state()
    assert_change_scope()
    assert_gitignore_contract()
    assert_all_python_ast()
    assert_no_provider_network_or_model_surface()
    assert_local_boundaries()
    assert_generated_results()
    assert_safe_json()
    assert_staged_allowlist()
    governed_text_leak_scan()
    validate_output_checksums()
    assert_protected_sources_unchanged()
    preflight = _json(HERE / "rq2d2a_preflight_report_v1.json")
    if (
        preflight.get("hidden_legacy_access_guard") != "DENIED"
        or preflight.get("hidden_legacy_accessed") is not False
        or preflight.get("raw_track_b_accessed") is not False
        or preflight.get("model_execution_count") != 0
        or preflight.get("adjudication_decision_count") != 0
        or preflight.get("capability_gold_frozen") is not False
    ):
        raise RQ2D2AValidationError("research boundary invariant mismatch")
    if require_review_zip:
        validate_review_zip()


def main(argv: Iterable[str] | None = None) -> int:
    require_review = "--require-review-zip" in set(argv or [])
    validate_all(require_review_zip=require_review)
    print(
        json.dumps(
            {
                "status": "PASS",
                "review_zip_required": require_review,
                "disagreement_case_count": 23,
                "adjudication_decision_count": 0,
                "capability_gold_frozen": False,
                "hidden_legacy_accessed": False,
                "raw_track_b_accessed": False,
                "model_execution_count": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
