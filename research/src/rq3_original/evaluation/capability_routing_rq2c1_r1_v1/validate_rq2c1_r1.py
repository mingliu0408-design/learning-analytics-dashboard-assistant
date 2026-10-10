"""RQ2-C1-R1 identity, safety, isolation, output, and package validators."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable
import zipfile

from . import (
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    LOCAL_ROOT,
    RESULT_BRANCH,
    ROOT,
    SAFE_JSON_FILENAMES,
    STARTING_HEAD,
    sha256_file,
)
from .c1_identity import (
    assert_partition_access_allowed,
    verify_original_c1_identity,
    verify_starting_preflight,
)
from .finalise_rq2c1_r1 import (
    CHECKSUM_NAME,
    expected_review_members,
    parse_output_checksums,
)


def validate_python_ast() -> dict[str, Any]:
    paths = sorted(HERE.glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"status": "PASS", "python_file_count": len(paths)}


def validate_temporal_imports() -> dict[str, Any]:
    violations: list[str] = []
    forbidden_names = {"temporal_validity", "_timestamp"}
    for path in sorted(HERE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "rq2c0_r2" in (node.module or ""):
                if any(alias.name in forbidden_names for alias in node.names):
                    violations.append(path.name)
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in forbidden_names:
                    violations.append(path.name)
    if violations:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_TEMPORAL_CONTRACT")
    return {
        "status": "PASS",
        "forbidden_reference_count": 0,
        "required_api": "temporal_validity_aware_v1_1",
    }


def validate_output_checksums() -> dict[str, Any]:
    values = parse_output_checksums()
    failed = [
        relative
        for relative, digest in values.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != digest
    ]
    if failed:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_TEST_FAILURE")
    return {"status": "PASS", "checksum_count": len(values), "failure_count": 0}


def validate_safe_outputs() -> dict[str, Any]:
    missing = [name for name in SAFE_JSON_FILENAMES if not (HERE / name).is_file()]
    missing.extend(name for name in DOC_FILENAMES if not (DOC_ROOT / name).is_file())
    if missing:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_TEST_FAILURE")
    safety = json.loads(
        (HERE / "rq2c1_r1_runtime_safety_results_v1.json").read_text()
    )
    isolation = json.loads(
        (HERE / "rq2c1_r1_rag_condition_isolation_v1.json").read_text()
    )
    validation = json.loads(
        (HERE / "rq2c1_r1_validation_report_v1.json").read_text()
    )
    if (
        safety["status"] != "PASS"
        or safety["hard_failure_count"] != 0
        or safety["successful_violation_count"] != 0
        or isolation["status"] != "PASS"
        or isolation["disabled_condition_actual_call_count"] != 0
        or validation["status"] != "PASS"
    ):
        raise RuntimeError("BLOCKED_RQ2_C1_R1_SAFETY_INSTRUMENTATION")
    forbidden_keys = {
        "current_query",
        "necessary_conversation_history",
        "canonical_text",
        "raw_content",
        "payload_text",
        "student_scope_id",
    }
    for name in SAFE_JSON_FILENAMES:
        value = json.loads((HERE / name).read_text(encoding="utf-8"))
        stack: list[Any] = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if set(item) & forbidden_keys:
                    raise RuntimeError("BLOCKED_RQ2_C1_R1_EVALUATION")
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return {
        "status": "PASS",
        "safe_json_count": len(SAFE_JSON_FILENAMES),
        "document_count": len(DOC_FILENAMES),
    }


def _governed_strings() -> tuple[str, ...]:
    strings: set[str] = set()
    fixture = ROOT / (
        "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
        "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl"
    )
    for line in fixture.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        value = row.get("input_event_or_query") or {}
        if isinstance(value.get("text"), str):
            strings.add(value["text"])
        for item in row.get("initial_store_state") or ():
            if isinstance(item.get("raw_content"), str):
                strings.add(item["raw_content"])
    for relative in (
        "evaluation/capability_routing_v1_r2b/local_gold/authentic_codebook_calibration_gold_v1.jsonl",
        "evaluation/capability_routing_v1_r2b/local_gold/synthetic_coverage_stress_gold_v1.jsonl",
        "evaluation/capability_routing_v1_r2b/local_gold/authentic_context_missing_qualitative_registry_v1.jsonl",
    ):
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if isinstance(row.get("current_query"), str):
                strings.add(row["current_query"])
            for turn in row.get("necessary_conversation_history") or ():
                if isinstance(turn, dict) and isinstance(turn.get("content"), str):
                    strings.add(turn["content"])
    return tuple(sorted(value for value in strings if len(value) >= 12))


def governed_text_leak_scan(paths: Iterable[Path] | None = None) -> dict[str, Any]:
    values = (
        list(paths)
        if paths is not None
        else [ROOT / relative for relative in parse_output_checksums()]
        + [HERE / CHECKSUM_NAME]
    )
    governed = _governed_strings()
    leaks: list[str] = []
    for path in values:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(value in text for value in governed):
            leaks.append(path.relative_to(ROOT).as_posix())
    if leaks:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_EVALUATION")
    return {
        "status": "PASS",
        "governed_string_count": len(governed),
        "leak_count": 0,
    }


def protected_source_comparison() -> dict[str, Any]:
    original = verify_original_c1_identity()
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", STARTING_HEAD, "--"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    invalid = [
        path
        for path in changed
        if path != ".gitignore"
        and not path.startswith("evaluation/capability_routing_rq2c1_r1_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2C1_R1_")
    ]
    if invalid:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_PROTECTED_SOURCE_MUTATED")
    return {
        "status": "PASS",
        "original_c1": original,
        "invalid_changed_file_count": 0,
    }


def validate_local_artifacts_ignored() -> dict[str, Any]:
    relative = str(LOCAL_ROOT.relative_to(ROOT))
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", relative + "/probe"],
        cwd=ROOT,
        check=False,
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", relative], cwd=ROOT, text=True
    ).strip()
    if ignored.returncode != 0 or tracked:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_TEST_FAILURE")
    return {"status": "PASS", "ignored": True, "tracked_file_count": 0}


def staged_allowlist() -> dict[str, Any]:
    staged = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True
    ).splitlines()
    invalid = [
        path
        for path in staged
        if path != ".gitignore"
        and not path.startswith("evaluation/capability_routing_rq2c1_r1_v1/")
        and not path.startswith("docs/thesis_mainline/rq2/RQ2C1_R1_")
    ]
    if invalid or any("local_artifacts/" in path for path in staged):
        raise RuntimeError("BLOCKED_RQ2_C1_R1_GIT_FAILURE")
    return {"status": "PASS", "staged_count": len(staged), "invalid_count": 0}


def validate_git_state(*, require_commit: bool = False) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    branch = git("branch", "--show-current")
    count = int(git("rev-list", "--count", f"{STARTING_HEAD}..HEAD"))
    expected = {1} if require_commit else {0, 1}
    if branch != RESULT_BRANCH or count not in expected or git("remote") or git("tag", "--list"):
        raise RuntimeError("BLOCKED_RQ2_C1_R1_GIT_FAILURE")
    return {
        "status": "PASS",
        "branch": branch,
        "relative_commit_count": count,
        "remote_count": 0,
        "tag_count": 0,
    }


def validate_review_zip(path: Path) -> dict[str, Any]:
    expected = set(expected_review_members())
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if archive.testzip() is not None or names != expected:
            raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
        if not set(parse_output_checksums()) <= names:
            raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
        lines = archive.read("REVIEW/REVIEW_CHECKSUMS.sha256").decode().splitlines()
        for line in lines:
            digest, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "status": "PASS",
        "member_count": len(expected),
        "referenced_output_count": len(parse_output_checksums()),
    }


def _partition_rejected(partition: str) -> bool:
    try:
        assert_partition_access_allowed(partition)
    except PermissionError:
        return True
    return False


def validate_all() -> dict[str, Any]:
    return {
        "starting_preflight": verify_starting_preflight()["status"],
        "python_ast": validate_python_ast(),
        "temporal_imports": validate_temporal_imports(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "local_artifacts": validate_local_artifacts_ignored(),
        "staged_allowlist": staged_allowlist(),
        "git": validate_git_state(),
        "track_a_rejected": _partition_rejected("TRACK_A"),
        "track_b_rejected": _partition_rejected("TRACK_B"),
        "status": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(validate_all(), indent=2, sort_keys=True))
