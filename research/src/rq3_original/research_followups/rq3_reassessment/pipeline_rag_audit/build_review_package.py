#!/usr/bin/env python3
"""Package only committed CODEX_B audit files and a new HEAD/hash receipt."""
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = "25373ba4bdd152634f0f8913ab38931cd17c1cde"
NAMES = [
    "EXECUTED_VS_LIVE_PIPELINE_AUDIT.md", "MEMORY_GATE_AND_INFORMATION_FLOW_AUDIT.md",
    "BASELINE_COMPILER_AND_PLANNER_AUDIT.md", "RAG_CORPUS_AND_R0_R1_AUDIT.md",
    "CANDIDATE_IMPROVEMENTS_AND_ATTRIBUTION_PLAN.md", "DIAGNOSTIC_CONDITION_MATRIX.csv",
    "OPEN_AUTHOR_DECISIONS.md", "SOURCE_MANIFEST.json", "OFFLINE_AUDIT_RESULTS.json",
    "MEMORY_CASE_EVIDENCE.csv", "audit_offline.py", "test_audit_offline.py", "STATUS.md",
    "TEST_RESULTS.md", "build_review_package.py",
]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if git("branch", "--show-current") != "research/rq3-explain-audit-b-pipeline":
        raise RuntimeError("WRONG_BRANCH_STOP")
    if git("rev-list", "--count", BASE + "..HEAD") != "1":
        raise RuntimeError("EXPECTED_EXACTLY_ONE_AUDIT_COMMIT")
    if git("status", "--porcelain"):
        raise RuntimeError("WORKTREE_MUST_BE_CLEAN_BEFORE_PACKAGING")
    scope = HERE.relative_to(ROOT).as_posix() + "/"
    changed = git("diff", "--name-only", BASE, "HEAD").splitlines()
    if not changed or any(not p.startswith(scope) for p in changed):
        raise RuntimeError("CHANGED_PATH_OUTSIDE_B_SCOPE")
    files = {}
    for name in NAMES:
        p = HERE / name
        if p.is_symlink():
            raise RuntimeError("SYMLINK_NOT_ALLOWED")
        files[name] = p.read_bytes()
        committed = subprocess.check_output(["git", "show", "HEAD:" + scope + name], cwd=ROOT)
        if committed != files[name]:
            raise RuntimeError("AUDIT_MEMBER_NOT_EQUAL_TO_COMMIT")
    receipt = {"status": "READY_FOR_JOINT_RQ3_REASSESSMENT_DECISIONS", "base_head": BASE,
               "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
               "commit_count_after_base": 1, "tracked_tree_clean_before_packaging": True,
               "contents": [{"path": k, "bytes": len(v), "sha256": sha(v)} for k, v in files.items()],
               "only_new_audit_outputs": True, "raw_sources_payloads_answers_ratings_or_keys_included": False}
    files["PACKAGE_RECEIPT.json"] = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    output = HERE / "RQ3_REASSESS_B_AUDIT_2026-09-06.zip"
    if output.exists():
        raise FileExistsError("REVIEW_PACKAGE_EXISTS_NO_OVERWRITE")
    temporary = output.with_suffix(output.suffix + ".tmp")
    with ZipFile(temporary, "x", ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = ZipInfo("RQ3_REASSESS_B_AUDIT/" + name, date_time=(2026, 9, 6, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    with ZipFile(temporary) as z:
        expected = {"RQ3_REASSESS_B_AUDIT/" + n for n in files}
        if set(z.namelist()) != expected or z.testzip() is not None:
            raise RuntimeError("PACKAGE_MEMBERS_OR_CRC_INVALID")
        for name, data in files.items():
            if z.read("RQ3_REASSESS_B_AUDIT/" + name) != data:
                raise RuntimeError("PACKAGE_MEMBER_BYTES_DIFFER")
    temporary.rename(output)
    print(json.dumps({"path": str(output), "sha256": sha(output.read_bytes()),
                      "head": receipt["head"], "member_count": len(files)}, indent=2))


if __name__ == "__main__":
    main()
