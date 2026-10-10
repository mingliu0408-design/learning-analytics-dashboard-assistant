"""Safe validation for the persisted source-blinded grouping ledger."""

from __future__ import annotations

from collections import Counter
import json
from typing import Any

from . import HERE, sha256_file, utf8_key


def validate_persisted_grouping_v1() -> dict[str, Any]:
    ledger_path = HERE / "track_b_source_blinded_contrast_groups_v1.jsonl"
    manifest_path = HERE / "track_b_source_blinded_grouping_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = ledger_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ValueError("grouping ledger byte contract mismatch")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if len(rows) != 48 or any(set(row) != {"review_case_id", "contrast_group_id"} for row in rows):
        raise ValueError("grouping ledger schema mismatch")
    ids = [str(row["review_case_id"]) for row in rows]
    groups = [str(row["contrast_group_id"]) for row in rows]
    if ids != sorted(ids, key=utf8_key) or len(set(ids)) != 48:
        raise ValueError("grouping ledger order or identity mismatch")
    distribution = Counter(groups)
    if len(distribution) != 24 or set(distribution.values()) != {2}:
        raise ValueError("grouping ledger distribution mismatch")
    forbidden_fragments = ("raw_scenario", "raw_case", "contrast_set", "scenario_family", "query", "history", "rationale")
    if any(fragment in raw.decode("utf-8").lower() for fragment in forbidden_fragments):
        raise ValueError("forbidden grouping field leaked")
    if (
        manifest.get("status") != "PASS"
        or manifest["projection"].get("forbidden_field_value_access_count") != 0
        or manifest["ledger"].get("sha256") != sha256_file(ledger_path)
        or manifest["ledger"].get("size_bytes") != len(raw)
    ):
        raise ValueError("grouping manifest mismatch")
    return {
        "status": "PASS",
        "ledger_sha256": sha256_file(ledger_path),
        "ledger_size_bytes": len(raw),
        "record_count": 48,
        "group_count": 24,
        "records_per_group": 2,
        "forbidden_field_value_access_count": 0,
        "mapping_open_read": "1/1",
        "case_bank_open_read": "1/1",
    }
