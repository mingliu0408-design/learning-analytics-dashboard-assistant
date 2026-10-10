"""Hash-bound, write-ahead F0 access; restricted values are projected as bytes.

No Provider client is constructed. Network and shell subprocess use are denied
inside controlled integration/test processes. The access ledger is sealed by the
final completion receipt and contains metadata only.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import sys
from pathlib import Path

from f0_common import HERE, ROOT, canonical, digest, require, utc_now
from f0_entry_binding import ENTRY_SHA256

ENTRY = HERE / "F0_BLINDED_EVALUATION_ENTRY_RECEIPT_V1.json"
LEDGER = HERE / "F0_CONTROLLED_ACCESS_LEDGER.jsonl"
COMPLETION = HERE / "C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT.json"
CATALOG = HERE / "F0_AUTHORIZED_SOURCE_CATALOG_V1.json"
PROJECTIONS = {
    "c4_real_condition_to_corrected_judge_request_mapping_r4_v1.csv": (
        "replay_record_id", "corrected_logical_judge_request_id", "corrected_judge_result_blind_id",
        "corrected_provider_payload_sha256", "corrected_applicability_sha256"),
    "c4_real_corrected_human_item_to_condition_mapping_v2.jsonl": (
        "original_rating_item_id", "corrected_rating_item_id", "corrected_visible_payload_sha256", "replay_record_id"),
    "c4_real_human_applicability_amendment_to_condition_mapping_r1.jsonl": (
        "amendment_item_id", "corrected_rating_item_id", "criterion", "original_rating_item_id", "replay_record_id"),
}
PERMITTED_USES = frozenset({"source_structure_and_identity", "canonical_result_validation",
                          "human_base_and_amendment_intake", "blinded_identity_projection",
                          "historical_usage_accounting", "frozen_protocol_loading",
                          "targeted_offline_test", "generated_artifact_verification"})
NETWORK_DENIALS = []


def install_offline_guard():
    def hook(event, args):
        if event.startswith("socket.") or event in {"urllib.Request", "http.client.connect", "subprocess.Popen", "os.system", "os.posix_spawn"}:
            NETWORK_DENIALS.append(event)
            raise RuntimeError("F0_OFFLINE_OPERATION_DENIED: " + event)
    sys.addaudithook(hook)


def verify_entry():
    raw = ENTRY.read_bytes()
    require(digest(raw) == ENTRY_SHA256, "F0_ENTRY_RECEIPT_HASH_MISMATCH")
    entry = json.loads(raw)
    require(entry["write_count"] == 1 and entry["overwrite_permitted"] is False, "ENTRY_NOT_WRITE_ONCE")
    require(all(entry[k] == 0 for k in ("score_bearing_sources_read_before_receipt", "human_rating_sources_read_before_receipt", "mode_mapping_opened_before_receipt")), "PRE_RECEIPT_CONTENT_EXPOSURE")
    for filename, field in (
        ("C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json", "source_selection_policy_sha256"),
        ("C4_REAL_CORRECTED_JUDGE_PACING_EVIDENCE_RESOLUTION_V1.json", "pacing_evidence_policy_sha256"),
        ("F0_PRE_SCORE_AGREEMENT_SCOPE_V1.json", "agreement_scope_policy_sha256"),
    ):
        require(digest((HERE / filename).read_bytes()) == entry[field], "PRE_SCORE_POLICY_CHANGED")
    for name, expected in entry["phase_a_and_b_authority_hashes"].items():
        require(digest((ROOT / name).read_bytes()) == expected, "F0_AUTHORITY_HASH_MISMATCH")
    require(digest(CATALOG.read_bytes()) == entry["source_catalog_sha256"], "F0_SOURCE_CATALOG_CHANGED")
    return entry


def _append_before_open(path, expected, role, use, projection):
    entry = verify_entry()
    require(not COMPLETION.exists(), "F0_CONTROLLED_ACCESS_SEALED")
    require(use in PERMITTED_USES, "UNKNOWN_ACCESS_USE")
    record = {
        "schema_version": "F0_CONTROLLED_ACCESS_V1", "event": "READ_AUTHORIZED_BEFORE_SOURCE_OPEN",
        "timestamp_utc": utc_now(), "entry_receipt_sha256": ENTRY_SHA256,
        "source_role": role, "source_path": str(path), "source_sha256": expected,
        "permitted_use": use, "projected_field_names": list(projection),
        "content_values_recorded": False, "mode_values_decoded": 0,
    }
    fd = os.open(LEDGER, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
    with os.fdopen(fd, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        lines = handle.read().splitlines()
        record["sequence"] = len(lines) + 1
        record["previous_record_sha256"] = digest(lines[-1]) if lines else None
        handle.write(canonical(record) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    fd = os.open(HERE, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    require(record["timestamp_utc"] >= entry["frozen_at_utc"], "ACCESS_PRECEDES_ENTRY")


def source_record(path):
    verify_entry()
    path = Path(path).resolve(strict=True)
    catalog = json.loads(CATALOG.read_bytes())
    records = [r for r in catalog["sources"] if r["path"] == str(path)]
    require(len(records) == 1, "SOURCE_NOT_EXACTLY_ALLOWLISTED: " + path.name)
    return records[0]


def _read_catalogued(path, use, projection=()):
    source = source_record(path)
    path = Path(source["path"])
    if source["source_role"] == "restricted_identity_projection":
        require(tuple(projection) == PROJECTIONS.get(path.name), "UNBLINDED_MAPPING_ACCESS_DENIED")
    else:
        require(not projection, "PROJECTION_NOT_DECLARED_FOR_SOURCE")
    _append_before_open(path, source["sha256"], source["source_role"], use, projection)
    raw = path.read_bytes()
    require(digest(raw) == source["sha256"], "CONTROLLED_SOURCE_HASH_MISMATCH: " + path.name)
    return raw


def read_source(path, use):
    return _read_catalogued(path, use)


def read_generated(path, expected_sha256, source_role):
    path = Path(path).resolve(strict=True)
    require(path.parent == HERE or path.parent == ROOT / "evaluation/rq3_real_c4/i1_route_integration/restricted_internal", "GENERATED_SOURCE_OUTSIDE_SCOPE")
    require(source_role in {"frozen_judge_result", "corrected_human_rating", "restricted_condition_result_projection", "human_transition_source_audit"}, "INVALID_GENERATED_SOURCE_ROLE")
    _append_before_open(path, expected_sha256, source_role, "generated_artifact_verification", ())
    raw = path.read_bytes()
    require(digest(raw) == expected_sha256, "GENERATED_ARTIFACT_HASH_MISMATCH")
    return raw


def verify_hash_only(path, expected_sha256):
    """Log and stream immutable-source bytes into SHA-256 without decoding them."""
    path = Path(path).resolve(strict=True)
    verify_entry()
    allowed = {r["path"]: r["sha256"] for r in json.loads(CATALOG.read_bytes())["sources"]}
    start = json.loads((HERE / "F0_STARTING_GATES_V1.json").read_bytes())
    allowed.update({str(ROOT / r["path"]): r["sha256"] for r in start["retained_untracked_files"]})
    restricted = ROOT / "evaluation/rq3_real_c4/i1_route_integration/restricted_internal"
    allowed.update({str(restricted / name): value for name, value in start["restricted_preservation_hashes"].items()})
    original = json.loads((HERE / "F0_ORIGINAL_JUDGE_COMMIT_SOURCE_MANIFEST_V1.json").read_bytes())
    allowed.update({str(ROOT / r["path"]): r["sha256"] for source in original for r in source["files"]})
    require(allowed.get(str(path)) == expected_sha256, "HASH_ONLY_SOURCE_NOT_FROZEN")
    _append_before_open(path, expected_sha256, "immutable_source_hash_only", "targeted_offline_test", ())
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    require(hasher.hexdigest() == expected_sha256, "PRESERVED_SOURCE_HASH_CHANGED: " + path.name)
    return True


def _string_end(raw, start):
    require(raw[start] == 34, "JSON_STRING_EXPECTED")
    i = start + 1
    while i < len(raw):
        if raw[i] == 92:
            i += 2
        elif raw[i] == 34:
            return i + 1
        else:
            i += 1
    raise RuntimeError("JSON_STRING_UNTERMINATED")


def _value_end(raw, start):
    if raw[start] == 34:
        return _string_end(raw, start)
    if raw[start] in (91, 123):
        stack = [raw[start]]
        i = start + 1
        while i < len(raw) and stack:
            c = raw[i]
            if c == 34:
                i = _string_end(raw, i)
                continue
            if c in (91, 123):
                stack.append(c)
            elif c in (93, 125):
                require(stack.pop() == (91 if c == 93 else 123), "JSON_NESTING_MISMATCH")
            i += 1
        require(not stack, "JSON_VALUE_UNTERMINATED")
        return i
    i = start
    while i < len(raw) and raw[i] not in b",}\r\n\t ":
        i += 1
    require(i > start, "JSON_VALUE_EMPTY")
    return i


def project_json_object(raw, allowed, require_all=True):
    """Decode only allowlisted top-level values; skip other value byte spans."""
    raw = raw.strip()
    require(raw.startswith(b"{") and raw.endswith(b"}"), "JSON_OBJECT_REQUIRED")
    allowed = set(allowed)
    result, seen = {}, set()
    i = 1
    while i < len(raw) - 1:
        while raw[i] in b" \r\n\t":
            i += 1
        end = _string_end(raw, i)
        key = json.loads(raw[i:end])  # Column names, never hidden values.
        require(key not in seen, "DUPLICATE_PROJECTION_FIELD")
        seen.add(key)
        i = end
        while raw[i] in b" \r\n\t":
            i += 1
        require(raw[i] == 58, "JSON_COLON_REQUIRED")
        i += 1
        while raw[i] in b" \r\n\t":
            i += 1
        end = _value_end(raw, i)
        if key in allowed:
            result[key] = json.loads(raw[i:end])
        i = end
        while i < len(raw) and raw[i] in b" \r\n\t":
            i += 1
        if raw[i] == 125:
            break
        require(raw[i] == 44, "JSON_COMMA_REQUIRED")
        i += 1
    require(not require_all or set(result) == allowed, "REQUIRED_PROJECTED_FIELDS_MISSING")
    return result


def project_csv(raw, allowed):
    """Parse CSV framing while only buffering/decoding selected value columns."""
    raw = raw.removeprefix(b"\xef\xbb\xbf")
    header, body = raw.split(b"\n", 1)
    names = next(csv.reader(io.StringIO(header.decode("utf-8"))))
    require(len(names) == len(set(names)) and set(allowed) <= set(names), "CSV_PROJECTION_HEADER_MISMATCH")
    selected = {names.index(name): name for name in allowed}
    rows, row, buf = [], {}, bytearray()
    index = 0
    quoted = False
    at_start = True
    after_quote = False
    i = 0

    def finish_field():
        nonlocal index, buf, at_start, after_quote
        if index in selected:
            row[selected[index]] = bytes(buf).decode("utf-8")
        buf = bytearray()
        index += 1
        at_start = True
        after_quote = False

    while i < len(body):
        c = body[i]
        if quoted:
            if c == 34:
                if i + 1 < len(body) and body[i + 1] == 34:
                    if index in selected:
                        buf.append(34)
                    i += 2
                    continue
                quoted, after_quote = False, True
            elif index in selected:
                buf.append(c)
        elif c == 34 and at_start:
            quoted = True
            at_start = False
        elif c == 44:
            finish_field()
        elif c in (10, 13):
            finish_field()
            require(index == len(names) and set(row) == set(allowed), "CSV_ROW_WIDTH_MISMATCH")
            rows.append(row)
            row, index = {}, 0
            if c == 13 and i + 1 < len(body) and body[i + 1] == 10:
                i += 1
        else:
            require(not after_quote, "CSV_TRAILING_QUOTED_VALUE_CONTENT")
            if index in selected:
                buf.append(c)
            at_start = False
        i += 1
    require(not quoted, "CSV_UNTERMINATED_QUOTE")
    if index or buf or row or not at_start:
        finish_field()
        require(index == len(names) and set(row) == set(allowed), "CSV_FINAL_ROW_WIDTH_MISMATCH")
        rows.append(row)
    return rows


def read_projection(path):
    path = Path(path)
    allowed = PROJECTIONS.get(path.name)
    require(allowed is not None, "MAPPING_PROJECTION_NOT_ALLOWLISTED")
    raw = _read_catalogued(path, "blinded_identity_projection", allowed)
    if path.suffix == ".csv":
        return project_csv(raw, allowed)
    return [project_json_object(line, allowed) for line in raw.splitlines() if line.strip()]
