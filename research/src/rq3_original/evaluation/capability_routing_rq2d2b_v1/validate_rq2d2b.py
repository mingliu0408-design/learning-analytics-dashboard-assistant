"""RQ2-D2B validation, privacy scans, checksums, and review ZIP gates."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import zipfile
from typing import Any, Iterable

from . import (
    CANONICAL_ADJUDICATION_RELATIVE,
    COMPLETED_ADJUDICATION_SHA256,
    D2A_CANONICAL_A_RELATIVE,
    D2A_CANONICAL_B_RELATIVE,
    FULL_GOLD_RELATIVE,
    FULL_GOLD_SHA256,
    HERE,
    LABEL_GOLD_RELATIVE,
    LABEL_GOLD_SHA256,
    ORIGINAL_ADJUDICATION_RELATIVE,
    REVIEW_ZIP_NAME,
    ROOT,
    START_HEAD,
    TARGET_BRANCH,
    canonical_json_bytes,
    csv_rows,
    fallback_input_path,
    primary_input_path,
    sha256_bytes,
    sha256_file,
)
from .gold_bundle_manifest import build_gold_bundle_documents
from .gold_composition_validator import validate_gold_composition
from .human_decision_precedence import resolve_human_decisions
from .source_blinded_gold_builder import build_gold_bytes
from .starting_state import git, validate_starting_state
from .validate_completed_adjudication import validate_completed_adjudication


PYTHON_FILES = (
    "__init__.py",
    "starting_state.py",
    "adjudication_input_authority.py",
    "adjudication_canonicalisation.py",
    "validate_completed_adjudication.py",
    "human_adjudicator_attestation.py",
    "human_decision_precedence.py",
    "source_blinded_gold_builder.py",
    "gold_composition_validator.py",
    "gold_bundle_manifest.py",
    "finalise_rq2d2b.py",
    "validate_rq2d2b.py",
    "test_rq2d2b_unittest.py",
)
DOCUMENT_FILES = (
    "RQ2D2B_HUMAN_ADJUDICATION_CLOSURE.md",
    "RQ2D2B_SOURCE_BLINDED_CAPABILITY_GOLD_FREEZE.md",
    "RQ2D2B_GOLD_DISTRIBUTION_AND_LIMITATIONS.md",
    "RQ2D2B_GOVERNANCE_AND_NEXT_STAGE.md",
)
SAFE_JSON_FILES = (
    "rq2d2b_preflight_report_v1.json",
    "track_b_human_adjudicator_independence_attestation_v1.json",
    "track_b_adjudication_packet_authority_v1.json",
    "track_b_adjudication_canonicalisation_manifest_v1.json",
    "track_b_completed_adjudication_validation_v1.json",
    "track_b_human_decision_precedence_v1.json",
    "track_b_capability_gold_summary_v1.json",
    "track_b_capability_gold_manifest_v1.json",
    "track_b_capability_gold_freeze_receipt_v1.json",
    "rq2d2b_validation_report_v1.json",
)
CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2d2b_v1/rq2d2b_output_checksums_v1.sha256"
)
IGNORE_ADDITIONS = (
    "evaluation/capability_routing_rq2d2b_v1/local_adjudication/",
    "evaluation/capability_routing_rq2d2b_v1/local_gold/",
)
REVIEW_EXTRA_MEMBERS = (
    "review/GIT_STATE.txt",
    "review/DIFF_SUMMARY.txt",
    "review/GITIGNORE_DIFF.patch",
    "review/GITIGNORE_SHA256.txt",
    "review/REVIEW_CHECKSUMS.sha256",
)


class RQ2D2BValidationError(RuntimeError):
    pass


def _allowed_path(relative: str) -> bool:
    return (
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_rq2d2b_v1/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2D2B_")
    )


def assert_change_scope() -> None:
    for arguments in (
        ("status", "--porcelain=v1", "--untracked-files=all"),
        ("diff", "--name-only", START_HEAD),
        ("diff", "--cached", "--name-only", START_HEAD),
    ):
        for line in git(*arguments).stdout.decode().splitlines():
            relative = line[3:] if arguments[0] == "status" else line
            if " -> " in relative:
                relative = relative.split(" -> ", 1)[1]
            if relative and not _allowed_path(relative):
                raise RQ2D2BValidationError(
                    "BLOCKED_RQ2_D2B_PROTECTED_SOURCE_MUTATED"
                )


def assert_gitignore_contract() -> None:
    base = git("show", f"{START_HEAD}:.gitignore").stdout.decode("utf-8")
    expected = base.rstrip("\n") + "\n" + "\n".join(IGNORE_ADDITIONS) + "\n"
    if (ROOT / ".gitignore").read_text(encoding="utf-8") != expected:
        raise RQ2D2BValidationError(".gitignore differs from exact D2B additions")


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
    source_parts: list[str] = []
    for name in PYTHON_FILES:
        text = (HERE / name).read_text(encoding="utf-8")
        source_parts.append(text)
        tree = ast.parse(text)
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
            raise RQ2D2BValidationError(f"prohibited import in {name}")
    source = "\n".join(source_parts)
    prohibited_local_asset_names = (
        "raw_to_" + "blinded_mapping_v1",
        "track_b_hidden_" + "legacy_escrow",
        "TRACK_B_" + "BLIND_KEY",
    )
    if any(marker in source for marker in prohibited_local_asset_names):
        raise RQ2D2BValidationError("prohibited D1 local asset surface in D2B code")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def assert_safe_tracked_outputs() -> None:
    prohibited_keys = {
        "current_query",
        "current_page",
        "necessary_conversation_history",
        "capability_definition_reference",
        "reviewer_rationale",
        "adjudicator_rationale",
        "query",
        "history",
        "rationale",
        "raw_id",
        "legacy_label",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) & prohibited_keys:
                raise RQ2D2BValidationError("governed field in tracked-safe output")
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    absolute_marker = "/" + "Users" + "/"
    for name in SAFE_JSON_FILES:
        value = _json(HERE / name)
        text = json.dumps(value, ensure_ascii=False)
        if absolute_marker in text:
            raise RQ2D2BValidationError(f"absolute path in {name}")
        walk(value)
    for row in _jsonl(ROOT / LABEL_GOLD_RELATIVE):
        walk(row)
        if set(row) & prohibited_keys:
            raise RQ2D2BValidationError("governed text field in label-only Gold")


def _governed_values() -> list[str]:
    values: set[str] = set()
    for relative in (D2A_CANONICAL_A_RELATIVE, D2A_CANONICAL_B_RELATIVE):
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
    for row in csv_rows(ROOT / CANONICAL_ADJUDICATION_RELATIVE):
        value = row["adjudicator_rationale"].strip()
        if len(value) >= 16:
            values.add(value)
    return sorted(values)


def tracked_output_paths() -> list[Path]:
    return sorted(
        [
            *(HERE / name for name in PYTHON_FILES),
            *(ROOT / "docs/thesis_mainline/rq2" / name for name in DOCUMENT_FILES),
            *(HERE / name for name in SAFE_JSON_FILES),
            ROOT / LABEL_GOLD_RELATIVE,
        ],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    governed = _governed_values()
    scanned = list(paths) if paths is not None else tracked_output_paths()
    absolute_marker = "/" + "Users" + "/"
    leaks: list[str] = []
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        if absolute_marker in text or any(value in text for value in governed):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RQ2D2BValidationError("governed-text leak: " + ", ".join(leaks))
    return {
        "status": "PASS",
        "governed_value_count": len(governed),
        "scanned_file_count": len(scanned),
        "leak_count": 0,
    }


def assert_local_boundaries() -> None:
    for relative in (
        ORIGINAL_ADJUDICATION_RELATIVE,
        CANONICAL_ADJUDICATION_RELATIVE,
        FULL_GOLD_RELATIVE,
    ):
        if git("check-ignore", "-q", "--", relative.as_posix(), check=False).returncode:
            raise RQ2D2BValidationError(f"local artifact not ignored: {relative}")
        if not git("ls-files", "--error-unmatch", relative.as_posix(), check=False).returncode:
            raise RQ2D2BValidationError(f"local artifact is tracked: {relative}")


def assert_staged_allowlist() -> None:
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR").stdout.decode().splitlines()
    for relative in names:
        if not _allowed_path(relative) or "/local_adjudication/" in relative or "/local_gold/" in relative:
            raise RQ2D2BValidationError(f"unsafe staged path: {relative}")


def write_output_checksums() -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in tracked_output_paths()
    ]
    (ROOT / CHECKSUM_RELATIVE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_output_checksums() -> dict[str, Any]:
    expected = {path.relative_to(ROOT).as_posix() for path in tracked_output_paths()}
    observed: set[str] = set()
    for line in (ROOT / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        observed.add(relative)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2D2BValidationError(f"output checksum mismatch: {relative}")
    if observed != expected:
        raise RQ2D2BValidationError("output checksum path-set mismatch")
    return {"status": "PASS", "referenced_tracked_output_count": len(observed)}


def assert_generated_results() -> None:
    completed, reviewer_a, reviewer_b, completed_validation = validate_completed_adjudication(ROOT)
    if completed_validation != _json(HERE / "track_b_completed_adjudication_validation_v1.json"):
        raise RQ2D2BValidationError("completed adjudication validation not reproducible")
    decisions, precedence = resolve_human_decisions(reviewer_a, reviewer_b, completed)
    if precedence != _json(HERE / "track_b_human_decision_precedence_v1.json"):
        raise RQ2D2BValidationError("human decision precedence not reproducible")
    label_bytes, full_bytes, label_rows, _ = build_gold_bytes(decisions)
    if (
        sha256_bytes(label_bytes) != LABEL_GOLD_SHA256
        or label_bytes != (ROOT / LABEL_GOLD_RELATIVE).read_bytes()
        or sha256_bytes(full_bytes) != FULL_GOLD_SHA256
        or full_bytes != (ROOT / FULL_GOLD_RELATIVE).read_bytes()
    ):
        raise RQ2D2BValidationError("Gold bytes are not reproducible")
    summary = validate_gold_composition(label_rows)
    if summary != _json(HERE / "track_b_capability_gold_summary_v1.json"):
        raise RQ2D2BValidationError("Gold summary is not reproducible")
    attestation = HERE / "track_b_human_adjudicator_independence_attestation_v1.json"
    precedence_path = HERE / "track_b_human_decision_precedence_v1.json"
    summary_path = HERE / "track_b_capability_gold_summary_v1.json"
    manifest, receipt = build_gold_bundle_documents(
        attestation_sha256=sha256_file(attestation),
        decision_precedence_sha256=sha256_file(precedence_path),
        gold_summary_sha256=sha256_file(summary_path),
    )
    if (
        manifest != _json(HERE / "track_b_capability_gold_manifest_v1.json")
        or receipt != _json(HERE / "track_b_capability_gold_freeze_receipt_v1.json")
    ):
        raise RQ2D2BValidationError("Gold bundle documents are not reproducible")


def assert_protected_sources_unchanged() -> None:
    assert_change_scope()
    present = [path for path in (primary_input_path(), fallback_input_path()) if path.exists()]
    if not present or any(path.is_symlink() or not path.is_file() or sha256_file(path) != COMPLETED_ADJUDICATION_SHA256 for path in present):
        raise RQ2D2BValidationError("completed adjudication input changed")
    validate_starting_state()


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
        raise RQ2D2BValidationError("review ZIP requires clean committed D2B state")
    return {
        "review/GIT_STATE.txt": (
            f"branch={branch}\nhead={head}\nbase={START_HEAD}\nrelative_commits=1\n"
            "working_tree_clean=true\nindex_clean=true\nremote_count=0\ntag_count=0\n"
        ).encode("utf-8"),
        "review/DIFF_SUMMARY.txt": git("diff", "--stat", START_HEAD, "HEAD").stdout,
        "review/GITIGNORE_DIFF.patch": git("diff", START_HEAD, "HEAD", "--", ".gitignore").stdout,
        "review/GITIGNORE_SHA256.txt": (
            f"{sha256_file(ROOT / '.gitignore')}  .gitignore\n"
        ).encode("utf-8"),
    }


def create_review_zip() -> dict[str, Any]:
    validate_all(require_review_zip=False)
    core_paths = [ROOT / relative for relative in _checksum_member_paths()]
    core_paths.append(ROOT / CHECKSUM_RELATIVE)
    members = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in core_paths}
    members.update(_git_review_metadata())
    members["review/REVIEW_CHECKSUMS.sha256"] = (
        "\n".join(f"{sha256_bytes(value)}  {name}" for name, value in sorted(members.items()))
        + "\n"
    ).encode("utf-8")
    if set(members) != expected_review_members():
        raise RQ2D2BValidationError("BLOCKED_RQ2_D2B_REVIEW_PACKAGE_INCOMPLETE")
    destination = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    with zipfile.ZipFile(destination, "w") as archive:
        for name, value in sorted(members.items()):
            archive.writestr(_zip_info(name), value)
    result = validate_review_zip()
    result.update(
        {
            "review_zip_sha256": sha256_file(destination),
            "review_zip_size_bytes": destination.stat().st_size,
        }
    )
    return result


def validate_review_zip() -> dict[str, Any]:
    path = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    if path.is_symlink() or not path.is_file():
        raise RQ2D2BValidationError("review ZIP missing or not regular")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RQ2D2BValidationError("review ZIP integrity failure")
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_review_members():
            raise RQ2D2BValidationError("BLOCKED_RQ2_D2B_REVIEW_PACKAGE_INCOMPLETE")
        values = {name: archive.read(name) for name in names}
    current = {
        relative: (ROOT / relative).read_bytes()
        for relative in (*_checksum_member_paths(), CHECKSUM_RELATIVE.as_posix())
    }
    current.update(_git_review_metadata())
    if any(values[name] != value for name, value in current.items()):
        raise RQ2D2BValidationError("review ZIP does not match committed outputs")
    checked: set[str] = set()
    for line in values["review/REVIEW_CHECKSUMS.sha256"].decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name == "review/REVIEW_CHECKSUMS.sha256" or sha256_bytes(values[name]) != digest:
            raise RQ2D2BValidationError("review checksum mismatch")
        checked.add(name)
    if checked != set(values) - {"review/REVIEW_CHECKSUMS.sha256"}:
        raise RQ2D2BValidationError("review checksum coverage mismatch")
    governed = _governed_values()
    absolute_marker = "/" + "Users" + "/"
    for name, value in values.items():
        text = value.decode("utf-8")
        if absolute_marker in text or any(item in text for item in governed):
            raise RQ2D2BValidationError(f"governed text in review ZIP: {name}")
    referenced = set(_checksum_member_paths())
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
    assert_safe_tracked_outputs()
    assert_staged_allowlist()
    governed_text_leak_scan()
    validate_output_checksums()
    assert_protected_sources_unchanged()
    receipt = _json(HERE / "track_b_capability_gold_freeze_receipt_v1.json")
    if (
        receipt.get("state") != "TRACK_B_CAPABILITY_GOLD_FROZEN"
        or receipt.get("hidden_legacy_accessed") is not False
        or receipt.get("model_execution_count") != 0
        or receipt.get("final_evaluation_started") is not False
        or receipt.get("gold_frozen_before_legacy_unblinding") is not True
    ):
        raise RQ2D2BValidationError("Gold-before-unblinding invariant mismatch")
    if require_review_zip:
        validate_review_zip()


def main(argv: Iterable[str] | None = None) -> int:
    arguments = set(argv or [])
    require_review = "--require-review-zip" in arguments
    validate_all(require_review_zip=require_review)
    print(
        json.dumps(
            {
                "status": "PASS",
                "review_zip_required": require_review,
                "gold_state": "TRACK_B_CAPABILITY_GOLD_FROZEN",
                "gold_record_count": 48,
                "hidden_legacy_accessed": False,
                "raw_track_b_accessed": False,
                "model_execution_count": 0,
                "final_evaluation_started": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
