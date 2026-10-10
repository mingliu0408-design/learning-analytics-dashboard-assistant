"""Read-only, hash-only verification after the final receipt and local commit."""
import argparse
import json
import subprocess
import zipfile

from f1_common import *
from f1_controlled_unblinding_guard import controlled_bytes, verify_entry
from build_f1_review_package import PACKAGE_ROOT
from finalize_f1_analysis import FINAL_STATUS, verify_ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-committed", action="store_true")
    options = parser.parse_args()
    checks = []
    def check(name, ok):
        assert ok, name
        checks.append(name)
    entry, entry_digest = verify_entry()
    receipt = read_json(FINAL_RECEIPT)
    audit = read_json(HERE / "F1_REVIEW_PACKAGE_AUDIT_V1.json")
    check("final_status_and_single_write", receipt["status"] == FINAL_STATUS and receipt["write_count"] == 1 and not receipt["overwrite_permitted"])
    check("final_entry_binding", receipt["f1_pre_unblinding_receipt_sha256"] == entry_digest)
    check("all_frozen_f1_artifact_hashes", all(sha(HERE / p) == d for p, d in receipt["all_frozen_f1_file_hashes"].items()))
    check("closed_ledger_hash_and_metadata_chain", sha(LEDGER) == receipt["f1_unblinding_ledger_sha256"] and len(verify_ledger()[0]) == receipt["f1_unblinding_ledger_records"])
    closed = False
    try:
        controlled_bytes(RI / "c4_real_f1_unblinded_condition_analysis_table_v1.jsonl", "SOURCE_INTEGRITY_TEST", "verify_f1_final_freeze.py")
    except RuntimeError as error:
        closed = str(error) == "F1_ACCESS_CLOSED_BY_FINAL_FREEZE"
    check("guard_rejects_before_restricted_file_access", closed and sha(LEDGER) == receipt["f1_unblinding_ledger_sha256"])
    snapshot = read_json(HERE / "F1_SOURCE_PRESERVATION_SNAPSHOT_V1.json")["files"]
    check("all_preexisting_source_hashes_unchanged", all(sha(ROOT / p) == d for p, d in snapshot.items()))
    check("all_specified_authority_hashes_unchanged", all(sha(ROOT / p) == d for p, d in EXPECTED_HASHES.items()))
    check("restricted_output_hashes_and_0600_without_decoding", all(sha(RI / r["filename"]) == r["sha256"] and (RI / r["filename"]).stat().st_mode & 0o777 == 0o600 for r in receipt["restricted_analysis_files"]))
    check("review_zip_hash", sha(REVIEW_ZIP) == audit["zip_sha256"])
    check("package_manifest_binding", sha(HERE / "F1_REVIEW_PACKAGE_MANIFEST_V1.json") == audit["package_manifest_sha256"])
    manifest = read_json(HERE / "F1_REVIEW_PACKAGE_MANIFEST_V1.json")
    with zipfile.ZipFile(REVIEW_ZIP) as archive:
        check("review_zip_crc_and_member_hashes", archive.testzip() is None and all(sha_bytes(archive.read(PACKAGE_ROOT + "/" + r["name"])) == r["sha256"] for r in manifest["members"]))
        if options.require_committed:
            head = git("rev-parse", "HEAD")
            check("exactly_one_commit_from_starting_head", git("rev-list", "--count", STARTING_HEAD + "..HEAD") == "1" and git("rev-parse", "HEAD^") == STARTING_HEAD)
            check("exact_worktree_and_branch", str(ROOT) == EXPECTED_ROOT and git("branch", "--show-current") == EXPECTED_BRANCH)
            changed = git("diff", "--name-only", STARTING_HEAD, "HEAD").splitlines()
            check("commit_confined_to_f1", bool(changed) and all(p.startswith(str(HERE.relative_to(ROOT)) + "/") for p in changed))
            status = git("status", "--short", "--untracked-files=all").splitlines()
            check("only_three_retained_untracked_files", sorted(status) == sorted("?? " + p for p in RETAINED))
            check("all_f1_files_tracked_and_clean", set(git("ls-files", "--", str(HERE.relative_to(ROOT))).splitlines()) == {str(p.relative_to(ROOT)) for p in HERE.rglob("*") if p.is_file()} and not git("diff", "--name-only", "HEAD"))
            matched = True
            for info in archive.infolist():
                name = info.filename.removeprefix(PACKAGE_ROOT + "/")
                path = str((HERE / name).relative_to(ROOT))
                committed = subprocess.check_output(["git", "show", "HEAD:" + path], cwd=ROOT)
                matched = matched and committed == archive.read(info.filename)
            check("all_archive_bytes_equal_committed_files", matched)
    print(json.dumps({"status": "PASS", "passed": len(checks), "failed": 0, "checks": checks,
        "working_directory": str(ROOT), "branch": git("branch", "--show-current"),
        "starting_head": STARTING_HEAD, "ending_head": git("rev-parse", "HEAD"),
        "entry_receipt_sha256": entry_digest, "ledger_sha256": sha(LEDGER),
        "final_receipt_sha256": sha(FINAL_RECEIPT), "zip_path": str(REVIEW_ZIP), "zip_sha256": sha(REVIEW_ZIP),
        "restricted_record_decoding": 0, "prohibited_action_counts": PROHIBITED_ACTION_COUNTS}, indent=2))


if __name__ == "__main__":
    main()
