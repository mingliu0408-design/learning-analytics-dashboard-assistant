"""Create one explicitly allowlisted review ZIP; no restricted data reads."""
import io
import json
import os
import stat
import zipfile

from f1_common import *
from finalize_f1_analysis import FINAL_STATUS

PACKAGE_ROOT = "RQ3_REAL_F1_FINAL_MODE_ANALYSIS_REVIEW_2026-09-03"
MANIFEST_NAME = "F1_REVIEW_PACKAGE_MANIFEST_V1.json"
AUDIT_NAME = "F1_REVIEW_PACKAGE_AUDIT_V1.json"
FORBIDDEN_MEMBER_PARTS = {"restricted_internal", ".git", "__pycache__", ".env"}


def validate_allowlist(allowlist):
    entries = allowlist["included_files"]
    assert len(entries) == len(set(entries))
    for name in entries:
        path = Path(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert not FORBIDDEN_MEMBER_PARTS.intersection(path.parts)
        assert path.suffix in {".md", ".txt", ".json", ".csv", ".py", ".pdf", ".svg", ".png", ".tiff"}
        assert not path.name.startswith("c4_real_f1_unblinded")
        assert "hmac_key" not in path.name and "frozen_pair_registry" not in path.name
        assert path.name != LEDGER.name
        assert path.name not in {MANIFEST_NAME, AUDIT_NAME}
    return entries


def main():
    assert not REVIEW_ZIP.exists(), "REVIEW_ZIP_ALREADY_EXISTS"
    assert git("branch", "--show-current") == EXPECTED_BRANCH
    assert git("rev-parse", "HEAD") == STARTING_HEAD
    receipt = read_json(FINAL_RECEIPT)
    assert receipt["status"] == FINAL_STATUS
    for name, digest in receipt["all_frozen_f1_file_hashes"].items():
        assert sha(HERE / name) == digest, "FINAL_FROZEN_ARTIFACT_CHANGED"
    allowlist = read_json(HERE / "F1_REVIEW_PACKAGE_ALLOWLIST_V1.json")
    entries = validate_allowlist(allowlist)
    data = {}
    for name in entries:
        path = HERE / name
        assert path.is_file() and not path.is_symlink()
        assert path.resolve().is_relative_to(HERE)
        data[name] = path.read_bytes()
    manifest = {"schema_version": "F1_REVIEW_PACKAGE_MANIFEST_V1", "package_root": PACKAGE_ROOT,
        "allowlist_sha256": sha(HERE / "F1_REVIEW_PACKAGE_ALLOWLIST_V1.json"),
        "final_analysis_receipt_sha256": sha(FINAL_RECEIPT),
        "members": [{"name": name, "bytes": len(content), "sha256": sha_bytes(content)} for name, content in sorted(data.items())],
        "manifest_self_hash_excluded_to_avoid_circularity": True,
        "restricted_raw_records_or_key_included": False,
        "ledger_content_excluded_metadata_only_included": True,
        "no_full_project_export": True}
    write_json(HERE / MANIFEST_NAME, manifest)
    data[MANIFEST_NAME] = (HERE / MANIFEST_NAME).read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(data.items()):
            info = zipfile.ZipInfo(PACKAGE_ROOT + "/" + name, date_time=(2026, 9, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, content)
    blob = buffer.getvalue()
    checks = []
    def check(name, valid):
        assert valid, name
        checks.append({"check": name, "status": "PASS"})
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        check("exact_explicit_allowlist_plus_manifest", set(names) == {PACKAGE_ROOT + "/" + n for n in data})
        check("no_duplicate_archive_members", len(names) == len(set(names)))
        check("crc_all_members", archive.testzip() is None)
        check("all_bytes_equal_authorized_files", all(archive.read(PACKAGE_ROOT + "/" + n) == v for n, v in data.items()))
        check("all_manifest_sha256_values", all(sha_bytes(archive.read(PACKAGE_ROOT + "/" + r["name"])) == r["sha256"] for r in manifest["members"]))
        check("no_key_or_restricted_member_paths", all(not FORBIDDEN_MEMBER_PARTS.intersection(Path(n).parts) and "hmac_key" not in Path(n).name for n in names))
        check("no_private_condition_or_pair_records", all("unblinded_condition_analysis_table" not in Path(n).name and "frozen_pair_registry" not in Path(n).name for n in names))
        check("no_raw_judge_or_human_rating_files", all(not Path(n).name.startswith(("c4_real_corrected_judge_results", "c4_real_corrected_human_ratings")) for n in names))
        check("ledger_metadata_only", PACKAGE_ROOT + "/F1_UNBLINDING_LEDGER_METADATA_V1.json" in names and PACKAGE_ROOT + "/" + LEDGER.name not in names)
        check("no_zip_path_traversal_or_absolute_paths", all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names))
        check("final_receipt_bytes_and_status", archive.read(PACKAGE_ROOT + "/" + FINAL_RECEIPT.name) == FINAL_RECEIPT.read_bytes() and receipt["status"] == FINAL_STATUS)
        check("no_full_repository_or_production_export", all(n.startswith(PACKAGE_ROOT + "/") for n in names) and allowlist["full_project_export"] is False)
    # The exact authorized pathname is the only output outside F1.
    fd = os.open(REVIEW_ZIP, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as output:
        output.write(blob); output.flush(); os.fsync(output.fileno())
    fsync_dir(REVIEW_ZIP.parent)
    check("written_zip_sha256_and_size", sha(REVIEW_ZIP) == sha_bytes(blob) and REVIEW_ZIP.stat().st_size == len(blob))
    with zipfile.ZipFile(REVIEW_ZIP) as archive:
        check("written_zip_crc", archive.testzip() is None)
    audit = {"schema_version": "F1_REVIEW_PACKAGE_AUDIT_V1", "status": "PASS", "checks": checks,
        "passed": len(checks), "failed": 0, "zip_path": str(REVIEW_ZIP), "zip_sha256": sha(REVIEW_ZIP),
        "zip_bytes": len(blob), "archive_member_count": len(data), "explicit_scientific_review_files": len(entries),
        "final_analysis_receipt_sha256": sha(FINAL_RECEIPT), "package_manifest_sha256": sha(HERE / MANIFEST_NAME),
        "raw_text_and_identity_privacy_preflight": "F1_TARGETED_TEST_REPORT_V1.json; archive is byte-identical to its allowlist inputs.",
        "created_once_with_O_EXCL": True, "f1_new_provider_calls": 0, "f1_new_network_calls": 0,
        "no_restricted_decoding_after_final_receipt": True}
    write_json(HERE / AUDIT_NAME, audit)
    print(json.dumps({k: audit[k] for k in ["status", "passed", "failed", "zip_path", "zip_sha256", "zip_bytes", "archive_member_count"]}, indent=2))


if __name__ == "__main__":
    main()
