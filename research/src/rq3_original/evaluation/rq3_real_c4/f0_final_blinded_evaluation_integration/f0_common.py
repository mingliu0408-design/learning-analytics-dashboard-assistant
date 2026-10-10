"""Small offline primitives for the explicitly authorized F0 freeze."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "evaluation/rq3_real_c4"
PHASE_B = BASE / "j2d2_phase_b_evaluation_repair"
RESTRICTED = BASE / "i1_route_integration/restricted_internal"
DOWNLOADS = Path("/Users/liuming/Downloads")
CRITERIA = ("CLARITY", "PERSONALISATION", "ACTIONABILITY", "CONTEXT_AWARENESS",
            "MOTIVATION_AND_ENGAGEMENT", "RELIABILITY", "MULTI_PAGE_COHESIVENESS", "ERROR_HANDLING")
FIELDS = tuple(c.lower() for c in CRITERIA)
VISIBLE_FIELDS = ("student_query", "current_lad_page", "visible_conversation_history",
                  "condition_visible_dashboard_evidence", "condition_visible_course_evidence",
                  "condition_visible_learner_memory", "condition_visible_planning_support", "candidate_response")
RETAIN = "RETAIN_EXISTING_RESULT_UNCHANGED_APPLICABILITY"
KEEP = "UNCHANGED_APPLICABLE_KEEP_EXISTING_RATING"
KEEP_NA = "UNCHANGED_NOT_APPLICABLE_KEEP_NA"
TO_NA = "OLD_APPLICABLE_NEW_NOT_APPLICABLE_EXCLUDE_OLD_AND_SET_NA"
AMEND = "OLD_NOT_APPLICABLE_NEW_APPLICABLE_REQUIRES_BLIND_AMENDMENT"
MODEL = "gpt-4.1-2025-04-14"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def pretty(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def durable_write_once(path, raw, mode=0o644):
    path = Path(path)
    require(path.parent.is_dir(), "OUTPUT_PARENT_MISSING")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def jsonl_bytes(rows):
    return b"".join(canonical(row) + b"\n" for row in rows)


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: canonical(row[k]).decode() if isinstance(row[k], (dict, list, bool)) else row[k] for k in fields})
    return stream.getvalue().encode("utf-8")


def csv_rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))


def jsonl_rows(raw):
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def embedded_request(payload):
    text = payload["messages"][0]["content"]
    begin, end = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n", "\nEND_BLIND_JUDGE_REQUEST_JSON"
    require(text.count(begin) == text.count(end) == 1, "BLINDED_REQUEST_BOUNDARY_MISMATCH")
    raw = text.split(begin, 1)[1].rsplit(end, 1)[0]
    value = json.loads(raw)
    require(canonical(value).decode() == raw, "BLINDED_REQUEST_CANONICAL_BYTES_MISMATCH")
    return value
