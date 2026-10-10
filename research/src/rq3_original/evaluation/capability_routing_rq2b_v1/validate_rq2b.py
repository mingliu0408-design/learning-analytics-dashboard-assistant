"""Fail-closed validation and review-package gates for RQ2-B."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
import zipfile

from . import DOC_FILENAMES, HERE, RESULT_BRANCH, ROOT, SAFE_OUTPUT_FILENAMES, STARTING_HEAD
from .gold_preflight import load_and_validate_gold


CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2b_v1/rq2b_output_checksums_v1.sha256"
)
ALLOWED_CHANGED_PREFIXES = (
    ".gitignore",
    "docs/thesis_mainline/rq2/RQ2B_",
    "evaluation/capability_routing_rq2b_v1/",
)
REVIEW_EXTRA_MEMBERS = frozenset(
    {
        "review_metadata/git_state.txt",
        "review_metadata/diff_summary.txt",
        "review_metadata/gitignore_diff.txt",
        "review_metadata/review_checksums.sha256",
    }
)


class RQ2BValidationError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def parse_output_checksums() -> dict[str, str]:
    path = ROOT / CHECKSUM_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise RQ2BValidationError("BLOCKED_RQ2_B_TEST_FAILURE: checksum missing")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2BValidationError("invalid output checksum line") from exc
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in result
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise RQ2BValidationError("invalid output checksum member")
        result[relative] = digest
    return result


def validate_output_checksums() -> dict[str, Any]:
    members = parse_output_checksums()
    failures: list[str] = []
    for relative, expected in members.items():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            failures.append(relative)
            continue
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != expected:
            failures.append(relative)
    if failures:
        raise RQ2BValidationError(
            "BLOCKED_RQ2_B_TEST_FAILURE: checksum mismatch " + ",".join(failures)
        )
    return {"status": "PASS", "referenced_tracked_output_path_count": len(members)}


def protected_source_comparison() -> dict[str, Any]:
    changed = [
        line
        for line in _git("diff", "--name-only", STARTING_HEAD, "--").splitlines()
        if line
    ]
    forbidden = [
        path
        for path in changed
        if not any(
            path == prefix or path.startswith(prefix)
            for prefix in ALLOWED_CHANGED_PREFIXES
        )
    ]
    if forbidden:
        raise RQ2BValidationError(
            "BLOCKED_RQ2_B_PROTECTED_SOURCE_MUTATED: " + ",".join(forbidden)
        )
    return {
        "status": "PASS",
        "changed_path_count": len(changed),
        "protected_existing_file_change_count": 0,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = [
        line
        for line in _git("diff", "--cached", "--name-only").splitlines()
        if line
    ]
    forbidden = [
        path
        for path in staged
        if (
            "/local_artifacts/" in path
            or path.endswith("/local_artifacts")
            or not any(
                path == prefix or path.startswith(prefix)
                for prefix in ALLOWED_CHANGED_PREFIXES
            )
        )
    ]
    if forbidden:
        raise RQ2BValidationError(
            "BLOCKED_RQ2_B_GIT_FAILURE: staged allowlist " + ",".join(forbidden)
        )
    return {"status": "PASS", "staged_path_count": len(staged)}


def validate_python_ast() -> dict[str, Any]:
    files = sorted(HERE.glob("*.py"))
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"status": "PASS", "python_file_count": len(files)}


def _governed_strings() -> list[str]:
    gold = load_and_validate_gold(ROOT)
    values: list[str] = []
    for example in (
        *gold.synthetic_gold,
        *gold.authentic_gold,
        *gold.authentic_context_missing_registry,
    ):
        values.append(example.router_input.current_query)
        for turn in example.router_input.conversation_history:
            content = str(turn.get("content") or "")
            if content:
                values.append(content)
    return sorted(set(value for value in values if len(value.strip()) >= 8))


def governed_text_leak_scan() -> dict[str, Any]:
    tracked_candidates = [
        *(HERE / name for name in SAFE_OUTPUT_FILENAMES),
        *(ROOT / "docs/thesis_mainline/rq2" / name for name in DOC_FILENAMES),
    ]
    governed = _governed_strings()
    leaks: list[str] = []
    for path in tracked_candidates:
        text = path.read_text(encoding="utf-8")
        if "/Users/" in text or re.search(r"(?:^|\s)/(?:private|var|tmp)/", text):
            leaks.append(f"absolute_path:{path.name}")
        for value in governed:
            if value in text:
                leaks.append(f"governed_text:{path.name}")
                break
    if leaks:
        raise RQ2BValidationError(
            "BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE: " + ",".join(leaks)
        )
    return {
        "status": "PASS",
        "governed_string_count": len(governed),
        "scanned_tracked_file_count": len(tracked_candidates),
        "leak_count": 0,
    }


def static_feature_access_audit() -> dict[str, Any]:
    path = HERE / "p1_capability_router.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    forbidden_imports = {
        "GoldExample",
        "CapabilityLabels",
        "SplitMetadata",
    }
    if imported & forbidden_imports:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE")
    route_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "route_p1_case"
    ]
    if len(route_functions) != 1:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE")
    parameters = [arg.arg for arg in route_functions[0].args.args]
    if parameters != ["case"]:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE")
    return {
        "status": "PASS",
        "router_input_type": "RoutingCaseInput",
        "gold_label_import_count": 0,
        "scenario_family_argument_count": 0,
        "source_role_argument_count": 0,
    }


def validate_safe_outputs() -> dict[str, Any]:
    values = {name: json.loads((HERE / name).read_text()) for name in SAFE_OUTPUT_FILENAMES}
    if any(not isinstance(value, dict) for value in values.values()):
        raise RQ2BValidationError("safe output schema mismatch")
    if values["rq2b_final_p1_policy_v1.json"].get("authentic_used_for_selection") is not False:
        raise RQ2BValidationError("BLOCKED_RQ2_B_AUTHENTIC_SELECTION_LEAKAGE")
    if values["rq2b_context_missing_diagnostic_v1.json"].get("included_in_authentic_aggregate") is not False:
        raise RQ2BValidationError("BLOCKED_RQ2_B_AUTHENTIC_SELECTION_LEAKAGE")
    if values["rq2b_validation_report_v1.json"].get("status") != "PASS":
        raise RQ2BValidationError("BLOCKED_RQ2_B_TEST_FAILURE")
    return {"status": "PASS", "safe_output_count": len(values)}


def expected_review_members() -> set[str]:
    return {
        *parse_output_checksums().keys(),
        CHECKSUM_RELATIVE.as_posix(),
        *REVIEW_EXTRA_MEMBERS,
    }


def validate_review_zip(
    zip_path: Path,
) -> dict[str, Any]:
    allowed = expected_review_members()
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        members = [info.filename for info in archive.infolist() if not info.is_dir()]
        if bad is not None or len(members) != len(set(members)) or set(members) != allowed:
            raise RQ2BValidationError("BLOCKED_RQ2_B_REVIEW_PACKAGE_INCOMPLETE")
        checksum_members = set(parse_output_checksums())
        if not checksum_members <= set(members):
            raise RQ2BValidationError("BLOCKED_RQ2_B_REVIEW_PACKAGE_INCOMPLETE")
        for relative, expected in parse_output_checksums().items():
            observed = hashlib.sha256(archive.read(relative)).hexdigest()
            if observed != expected:
                raise RQ2BValidationError("BLOCKED_RQ2_B_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "status": "PASS",
        "zip_member_count": len(members),
        "referenced_output_member_count": len(checksum_members),
        "referenced_outputs_present": True,
        "zip_integrity": "PASS",
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 26, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip(zip_path: Path) -> dict[str, Any]:
    """Build the exact safe review archive after the single RQ2-B commit."""

    if zip_path.exists():
        raise RQ2BValidationError("review ZIP target already exists")
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GIT_FAILURE")
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GIT_FAILURE: worktree not clean")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2BValidationError("BLOCKED_RQ2_B_GIT_FAILURE")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) != 1:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GIT_FAILURE")

    checksum_members = parse_output_checksums()
    payloads: dict[str, bytes] = {
        relative: (ROOT / relative).read_bytes() for relative in checksum_members
    }
    payloads[CHECKSUM_RELATIVE.as_posix()] = (ROOT / CHECKSUM_RELATIVE).read_bytes()
    git_state = "\n".join(
        [
            f"branch: {_git('branch', '--show-current')}",
            f"head: {_git('rev-parse', 'HEAD')}",
            f"parent: {_git('rev-parse', 'HEAD^')}",
            f"starting_head: {STARTING_HEAD}",
            f"relative_commits: {_git('rev-list', '--count', f'{STARTING_HEAD}..HEAD')}",
            f"remote_count: {len(_git('remote').splitlines()) if _git('remote') else 0}",
            f"tag_count: {len(_git('tag', '--list').splitlines()) if _git('tag', '--list') else 0}",
            "working_tree: clean",
            "index: clean",
            f"commit_subject: {_git('show', '-s', '--format=%s', 'HEAD')}",
        ]
    ) + "\n"
    diff_summary = (
        _git("diff", "--stat", STARTING_HEAD, "HEAD")
        + "\n\n"
        + _git("diff", "--name-status", STARTING_HEAD, "HEAD")
        + "\n"
    )
    gitignore_diff = _git("diff", STARTING_HEAD, "HEAD", "--", ".gitignore") + "\n"
    extras = {
        "review_metadata/git_state.txt": git_state.encode("utf-8"),
        "review_metadata/diff_summary.txt": diff_summary.encode("utf-8"),
        "review_metadata/gitignore_diff.txt": gitignore_diff.encode("utf-8"),
    }
    payloads.update(extras)
    review_checksums = "\n".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
        for name in sorted(payloads)
    ) + "\n"
    payloads["review_metadata/review_checksums.sha256"] = review_checksums.encode(
        "utf-8"
    )

    governed = _governed_strings()
    for name, payload in payloads.items():
        if name.endswith((".py", ".json", ".md", ".txt", ".sha256")):
            text = payload.decode("utf-8")
            if any(value in text for value in governed):
                raise RQ2BValidationError(
                    "BLOCKED_RQ2_B_GOLD_FEATURE_LEAKAGE: review ZIP"
                )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(_zip_info(name), payloads[name], compress_type=zipfile.ZIP_DEFLATED)
    if set(extras) | {"review_metadata/review_checksums.sha256"} != REVIEW_EXTRA_MEMBERS:
        raise RQ2BValidationError("BLOCKED_RQ2_B_REVIEW_PACKAGE_INCOMPLETE")
    verification = validate_review_zip(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        review_lines = archive.read(
            "review_metadata/review_checksums.sha256"
        ).decode("utf-8").splitlines()
        for line in review_lines:
            expected, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RQ2BValidationError(
                    "BLOCKED_RQ2_B_REVIEW_PACKAGE_INCOMPLETE"
                )
    return {
        **verification,
        "review_checksum_entries": len(review_lines),
        "governed_text_leak_scan": "PASS",
        "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "size_bytes": zip_path.stat().st_size,
        "path": str(zip_path),
    }


def validate_all() -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    if branch != RESULT_BRANCH:
        raise RQ2BValidationError("BLOCKED_RQ2_B_GIT_FAILURE")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        raise RQ2BValidationError("BLOCKED_RQ2_B_STARTING_STATE_MISMATCH")
    reports = {
        "python_ast": validate_python_ast(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "static_feature_access": static_feature_access_audit(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "staged_allowlist": staged_allowlist(),
    }
    return {"status": "PASS", "reports": reports}


def main() -> int:
    print(json.dumps(validate_all(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
