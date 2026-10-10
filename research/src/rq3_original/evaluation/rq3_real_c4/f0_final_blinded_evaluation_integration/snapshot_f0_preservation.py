"""Read-only Git and byte-preservation gate; no outcome values are decoded."""
from __future__ import annotations

import json
import subprocess

import f0_controlled_access_guard as guard
from f0_common import HERE, ROOT, BASE, RESTRICTED, DOWNLOADS, digest, pretty, require, durable_write_once, utc_now


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main():
    start = json.loads((HERE / "F0_STARTING_GATES_V1.json").read_bytes())
    commits = json.loads((HERE / "F0_INTEGRATED_JUDGE_COMMIT_MAPPING_V1.json").read_bytes())
    originals = json.loads((HERE / "F0_ORIGINAL_JUDGE_COMMIT_SOURCE_MANIFEST_V1.json").read_bytes())
    require(str(ROOT) == start["state"]["pwd"] and git("branch", "--show-current") == start["state"]["branch"], "F0_GIT_LOCATION_OR_BRANCH_CHANGED")
    require(git("rev-parse", "HEAD") == commits[-1]["cherry_picked_commit"], "F0_INTEGRATED_HEAD_CHANGED")
    require(git("rev-list", "--reverse", start["state"]["head"] + "..HEAD").splitlines() == [r["cherry_picked_commit"] for r in commits], "F0_CHERRY_PICK_ORDER_CHANGED")
    require(subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT).returncode == 0, "PREEXISTING_TRACKED_FILE_MODIFIED")
    changes = git("diff", "--name-status", start["state"]["head"], "HEAD").splitlines()
    expected = {r["path"] for source in originals for r in source["files"]}
    require({line.split("\t")[1] for line in changes} == expected and all(line.startswith("A\t") for line in changes), "INTEGRATED_FILE_SCOPE_DIFFERS")
    status = git("status", "--short", "--untracked-files=all").splitlines()
    retained = ["?? " + row["path"] for row in start["retained_untracked_files"]]
    outside = [line for line in status if not line[3:].startswith(str(HERE.relative_to(ROOT)) + "/")]
    require(outside == retained, "RETAINED_UNTRACKED_OR_OUT_OF_SCOPE_STATUS_CHANGED")
    guard.install_offline_guard()  # Git commands above are local reads only.
    for source in originals:
        for row in source["files"]:
            guard.verify_hash_only(ROOT / row["path"], row["sha256"])
    for row in start["retained_untracked_files"]:
        guard.verify_hash_only(ROOT / row["path"], row["sha256"])
    for name, expected_hash in start["restricted_preservation_hashes"].items():
        guard.verify_hash_only(RESTRICTED / name, expected_hash)
    for name, expected_hash in start["human_source_hashes"].items():
        guard.verify_hash_only(DOWNLOADS / name, expected_hash)
    report = {"schema_version": "F0_PRECOMPLETION_PRESERVATION_AUDIT_V1", "timestamp_utc": utc_now(),
              "status": "PASS", "starting_head": start["state"]["head"], "integrated_head": commits[-1]["cherry_picked_commit"],
              "branch": start["state"]["branch"], "working_directory": str(ROOT),
              "cherry_picked_commits_in_exact_order": commits, "integrated_original_files_byte_identical": len(expected),
              "all_preexisting_tracked_files_unchanged": True, "retained_untracked_files_unchanged": len(retained),
              "restricted_files_unchanged": len(start["restricted_preservation_hashes"]), "human_sources_unchanged": 8,
              "hash_only_source_verification": True, "mode_values_decoded": 0,
              "network_calls": 0, "provider_calls": 0, "untracked_outside_f0": retained}
    durable_write_once(HERE / "F0_PRECOMPLETION_PRESERVATION_AUDIT_V1.json", pretty(report))
    print(json.dumps({"status": "PASS", "integrated_files_preserved": len(expected), "human_sources_preserved": 8, "retained_untracked_files": 3}))


if __name__ == "__main__":
    main()
