#!/usr/bin/env python3
"""Post-commit allowlisted E1 review export and independent archive readback."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
START = "4765e066bd512611cd7157098aa50a86d25e7ea8"
ORIGINAL_E0 = "79c3cb27bb8f4f888aa661c7b731483223c4aaa8"
CHERRY = "fdc58a8ca672a2ddb9a5c381fd7f73a38a2e2924"
E1 = "research_followups/rq3_rebuild/e1_five_page/"
E0 = "research_followups/rq3_rebuild/e0_crosspage_functional_check/"
OUTPUT = Path("/Users/liuming/Downloads/RQ3_REBUILD_E1_FIVE_PAGE_REVIEW_2026-09-06.zip")
REPORTS = (
    "START_HERE.md", "README.md", "STATUS.json", "TEST_REPORT.md", "TEST_STDOUT.txt",
    "FUNCTIONAL_ACCEPTANCE_RESULTS.json", "SYNTHETIC_FIXTURE.json", "HAND_CALCULATED_EXPECTATIONS.json",
    "PAGE_FACT_TO_GENERATOR_TRACE.json", "FIVE_VIEW_DATA_PROVENANCE.csv", "ACTUAL_UI_METRIC_SOURCE_MAP.csv",
    "DATA_COVERAGE_PROFILE.json", "BEFORE_AFTER_E0_REQUIREMENTS.csv", "SCOPE_AND_CACHE_SAFETY_REPORT.md",
    "UI_WIRING_REPORT.md", "UNRESOLVED_ITEMS.md", "PREFLIGHT.json", "SOURCE_MANIFEST.json",
    "CHANGED_SYMBOLS.json", "RUNTIME_SOURCE_CLOSURE.json", "build_synthetic_fixture.py",
    "profile_sources.py", "test_scoped_evidence.py", "build_reports.py", "build_review_package.py",
)
METADATA = (
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_candidate_configs_v1.json",
    "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate_frozen_v1.json",
    "evaluation/rq3_real_c4/i0_integration/c4_real_generation_prompt_frozen_v1.txt",
    "evaluation/rq3_real_c4/i1_route_integration/c4_real_generation_schema_v2_provider_compatible.json",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    assert output == OUTPUT, "This receipt is scoped to the exact requested review filename"
    assert not output.exists(), "Requested output already exists; do not overwrite an existing review"
    assert not output.is_relative_to(ROOT)
    assert git("branch", "--show-current") == "research/rq3-rebuild-e1-five-page"
    end = git("rev-parse", "HEAD")
    assert git("rev-parse", "HEAD^") == CHERRY
    assert git("rev-parse", CHERRY + "^") == START
    assert git("rev-list", "--count", START + "..HEAD") == "2"
    assert git("log", "-1", "--format=%s") == "RQ3-REBUILD-E1: implement scoped five-view cross-page evidence"
    assert not git("status", "--porcelain=v1", "--untracked-files=all")
    assert not git("diff", "--check", START, end)
    e0_tree = git("rev-parse", ORIGINAL_E0 + ":" + E0.rstrip("/"))
    assert git("rev-parse", end + ":" + E0.rstrip("/")) == e0_tree
    changed = subprocess.check_output(["git", "diff", "--name-only", "-z", CHERRY, end], cwd=ROOT).decode().strip("\0").split("\0")
    page = next((ROOT / "pages").glob("1 - *Individual Feedback.py")).relative_to(ROOT).as_posix()
    assert all(p.startswith((E1, "utils/c4_dashboard_scoped/")) or p == page for p in changed)
    assert set(REPORTS) == {p.relative_to(HERE).as_posix() for p in HERE.rglob("*") if p.is_file()}
    stage = Path(tempfile.mkdtemp(prefix="rq3-e1-review-", dir="/private/tmp"))
    copied = []

    def copy(relative, destination):
        source = ROOT / relative
        assert source.is_file() and not source.is_symlink()
        data = source.read_bytes()
        committed = subprocess.check_output(["git", "show", end + ":" + relative], cwd=ROOT)
        assert data == committed
        target = stage / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        copied.append({"repo_path": relative, "archive_path": destination, "sha256": sha(data), "matches_ending_commit": True})

    for filename in REPORTS:
        copy(E1 + filename, filename)
    runtime = set(json.loads((HERE / "RUNTIME_SOURCE_CLOSURE.json").read_text())["imported_python_files"])
    runtime.update({"utils/c4_real_factory.py", page})
    runtime.update(METADATA)
    assert all(p.endswith(".py") or p in METADATA for p in runtime)
    for relative in sorted(runtime):
        copy(relative, "runtime_snapshot/" + relative)
    for filename in ("CROSS_PAGE_FUNCTIONAL_STATUS.md", "RAW_DASHBOARD_SOURCE_MAP.csv", "TEST_REPORT.md"):
        copy(E0 + filename, "REFERENCES/E0/" + filename)
    (stage / "patches").mkdir()
    focused = [p for p in changed if p.startswith("utils/") or p == page]
    for filename, paths in (("E1_IMPLEMENTATION.patch", focused), ("E1_FULL_COMMIT.patch", changed)):
        patch = subprocess.check_output(["git", "diff", "--binary", "--full-index", CHERRY, end, "--", *paths], cwd=ROOT)
        (stage / "patches" / filename).write_bytes(patch)
    write_json(stage / "GIT_HANDOFF.json", {"working_directory": str(ROOT), "branch": git("branch", "--show-current"),
        "starting_head": START, "original_E0_commit": ORIGINAL_E0, "cherry_picked_E0_commit": CHERRY,
        "ending_head": end, "commit_count_after_start": 2, "implementation_commit_count": 1,
        "original_and_final_E0_subtree": e0_tree, "E0_preserved": True,
        "changed_files_E1": changed, "protected_paths_unchanged": True, "final_git_status": "CLEAN",
        "git_diff_check": "PASS", "source_archive_mapping": copied,
        "receipt_location": "Generated outside repository after the implementation commit"})

    # New temporary runtime copy, independent output path. This reruns only E1
    # synthetics and cannot inspect original learner data or historical outputs.
    replay_out = Path(tempfile.mkdtemp(prefix="rq3-e1-portability-", dir="/private/tmp"))
    command = ["/opt/anaconda3/bin/python3", "-B", str(stage / "test_scoped_evidence.py"),
               "--source-root", str(stage / "runtime_snapshot"), "--output-dir", str(replay_out)]
    completed = subprocess.run(command, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                               text=True, capture_output=True, timeout=60)
    results = json.loads((replay_out / "FUNCTIONAL_ACCEPTANCE_RESULTS.json").read_text()) if completed.returncode == 0 else {}
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert results["counts"] == {"PASS": 84, "FAIL": 0, "UNKNOWN": 0} and not results["forbidden_attempts"]
    write_json(stage / "PORTABILITY_CHECK.json", {"status": "PASS", "source": "Byte-identical temporary runtime_snapshot",
        "tests": results["counts"], "skips": results["skips"], "transport_calls": results["transport_call_count"],
        "command": command, "exit_code": completed.returncode, "stdout_sha256": sha(completed.stdout.encode()),
        "forbidden_attempts": results["forbidden_attempts"], "only_E1_synthetic_tests_run": True})
    write_json(stage / "OUTPUT_MANIFEST.json", {"task": "RQ3-REBUILD-E1", "self_excluded": True,
        "ending_head": end, "members": [{"path": p.relative_to(stage).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
                                      for p in sorted(stage.rglob("*")) if p.is_file()],
        "excluded": ["Raw learner rows and private IDs/text", "Binary stores and identity spreadsheets", "Credentials",
                     "Raw course documents", "Models and environments", "Historical responses/scores/rationales", ".git", "M0/P0/R1 uncommitted work"]})
    stage_hashes = {p.relative_to(stage).as_posix(): sha(p.read_bytes()) for p in stage.rglob("*") if p.is_file()}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(stage_hashes):
            archive.write(stage / name, name)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts and "\\" not in n and not n.endswith("/") for n in names)
        assert all(not stat.S_ISLNK(i.external_attr >> 16) for i in archive.infolist())
        manifest = json.loads(archive.read("OUTPUT_MANIFEST.json"))
        assert {r["path"] for r in manifest["members"]} | {"OUTPUT_MANIFEST.json"} == set(names) == set(stage_hashes)
        for entry in manifest["members"]:
            data = archive.read(entry["path"])
            assert len(data) == entry["bytes"] and sha(data) == entry["sha256"]
        archived_hashes = {name: sha(archive.read(name)) for name in names}
        assert archived_hashes == stage_hashes  # Includes the manifest itself.
        assert json.loads(archive.read("GIT_HANDOFF.json"))["ending_head"] == end
    assert not git("status", "--porcelain=v1", "--untracked-files=all")
    receipt = {"path": str(output), "sha256": sha(output.read_bytes()), "bytes": output.stat().st_size,
               "file_count": len(names), "CRC": "PASS", "safe_paths": "PASS", "member_hashes": "PASS",
               "manifest_sha256": archived_hashes["OUTPUT_MANIFEST.json"], "all_member_sha256": archived_hashes,
               "starting_head": START, "cherry_picked_E0_commit": CHERRY, "ending_head": end,
               "synthetic_acceptance": results["counts"], "operational_UNKNOWN": 4, "portability": "PASS",
               "final_worktree": "CLEAN", "verified_utc": datetime.now(timezone.utc).isoformat(), "local_delivery_only": True}
    verification = output.with_suffix(".verification.json")
    with verification.open("x") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "all_member_sha256"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
