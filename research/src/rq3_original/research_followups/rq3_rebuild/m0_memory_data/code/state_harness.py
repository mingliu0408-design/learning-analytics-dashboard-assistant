"""Real inherited store, read-only targets, SQLite backup clones. Engineering only."""
from __future__ import annotations
from dataclasses import asdict
import sqlite3
from pathlib import Path
from common import disable_network, inherited_root, object_sha, utc, FLAGS

disable_network()
REPO = inherited_root()
from utils.c4_memory.c4_memory_store import C4MemoryStore, normalise_timestamp
from utils.c4_memory.c4_memory_writer import C4MemoryWriter, StructuredMemoryCandidate
from utils.c4_memory.c4_memory_provider import C4LearnerMemoryProvider
from utils.c4_memory.c4_memory_retriever import C4MemoryRetriever


class ReadOnlyStore(C4MemoryStore):
    """Only constructor changes. All selection/FTS/privacy SQL is inherited unchanged."""
    def __init__(self, path, *, clock):
        self.database_path = Path(path).resolve(strict=True)
        self._clock = clock
        self._connection = sqlite3.connect(self.database_path.as_uri() + "?mode=ro",
                                           uri=True, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA query_only = ON")
        row = self._connection.execute("SELECT schema_version, architecture_id FROM "
            "c4_schema_metadata WHERE schema_name='c4_memory_schema_v1'").fetchone()
        if tuple(row or ()) != (1, "C4_LEARNER_MEMORY_V1"):
            self.close()
            raise ValueError("SCHEMA_IDENTITY_MISMATCH")


def snapshot(store):
    """Diagnostic-only state digest, not retrieval input. Covers settings/events/records."""
    return {table: [dict(r) for r in store._connection.execute(
        f"SELECT * FROM {table} ORDER BY 1")]
        for table in ("c4_schema_metadata", "learner_memory_settings", "memories", "memory_events")}


def backup_closed(source, target):
    """Source caller has closed setup; API is safe even if a WAL later exists."""
    target = Path(target)
    if target.exists():
        raise FileExistsError(target)
    with sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def course_path(root, course_id):
    # Opaque course partition; learner ID never includes condition or session.
    return Path(root) / (object_sha({"course_id": course_id})[:24] + ".sqlite")


def setup_episode(runtime, destination):
    """No evaluation sidecar accepted. Writes only explicit synthetic source operations."""
    if runtime["flags"] != FLAGS:
        raise ValueError("SYNTHETIC_FLAGS_REQUIRED")
    dest = Path(destination)
    dest.mkdir(exist_ok=False)
    target = runtime["target"]
    courses = sorted({target["course_id"], *(o["course_id"] for o in runtime["setup_operations"])})
    turns = {t["turn_id"]: t for t in runtime["source_turns"]}
    aliases, receipts, databases = {}, [], {}
    for course in courses:
        path = course_path(dest, course)
        databases[course] = path
        with C4MemoryStore(path) as store:
            writer = C4MemoryWriter(store)
            for op in (o for o in runtime["setup_operations"] if o["course_id"] == course):
                turn = turns[op["source_turn_id"]]
                if normalise_timestamp(turn["timestamp"]) >= normalise_timestamp(target["as_of"]):
                    raise ValueError("SOURCE_EVENT_NOT_BEFORE_TARGET")
                if turn["course_id"] != course or turn["learner_id"] != op["learner_id"]:
                    raise ValueError("SOURCE_SCOPE_MISMATCH")
                if op["operation"] == "DISABLE":
                    if turn["role"] != "USER" or op["claim_basis"] != "EXPLICIT_USER_STATEMENT":
                        raise ValueError("UNAUTHORISED_CONTROL")
                    store.set_memory_enabled(op["learner_id"], False, event_at=turn["timestamp"])
                    outcome = {"accepted": True, "applied_operation": "DISABLE", "memory_id": None}
                else:
                    span = op["evidence_span"]
                    start, end = op["source_span_chars"]
                    if turn["content"][start:end] != span:
                        raise ValueError("SOURCE_SPAN_OFFSET_MISMATCH")
                    prior = op.get("target_fact_id")
                    candidate = StructuredMemoryCandidate.from_mapping({
                        "operation": op["operation"], "memory_type": op["memory_type"],
                        "content": op["content"], "target_memory_id": aliases[prior] if prior else None,
                        "confidence": op["confidence"], "evidence_span": span})
                    result = writer.apply_candidate(student_id=op["learner_id"],
                        source_session_id=turn["session_id"], source_turn_id=turn["turn_id"],
                        source_text=turn["content"], candidate=candidate,
                        source_role=turn["role"], claim_basis=op["claim_basis"],
                        consent_status=op["consent_status"], event_at=turn["timestamp"],
                        valid_from=op["valid_from"], valid_to=op["valid_to"])
                    outcome = result.as_dict()
                    if result.accepted and op["operation"] != "DELETE":
                        aliases[op["fact_id"]] = result.memory_id
                receipts.append({"event": "SETUP_WRITE_POLICY", "execution_utc": utc(),
                    "synthetic_event_at": turn["timestamp"], "course_id": course,
                    "fact_id": op.get("fact_id"), "source_role": turn["role"],
                    "claim_basis": op["claim_basis"], "outcome": outcome})
            before = snapshot(store)
        with ReadOnlyStore(path, clock=lambda: target["as_of"]) as reopened:
            after = snapshot(reopened)
            assert before == after
            check = reopened.integrity_check()
            assert check["integrity_check"] == "ok" and check["foreign_key_issue_count"] == 0
            receipts.append({"event": "CLOSED_AND_REOPENED_READ_ONLY", "execution_utc": utc(),
                "course_id": course, "logical_sha256": object_sha(after), "integrity": check,
                "memory_ids": [r["memory_id"] for r in after["memories"]],
                "settings": after["learner_memory_settings"], "same_state": True})
    return databases, aliases, receipts


class RecordingRetriever(C4MemoryRetriever):
    """Capture the public result once; no recomputation, parameter change, or reranking."""
    def retrieve(self, *args, **kwargs):
        self.calls += 1
        self.last = super().retrieve(*args, **kwargs)
        return self.last


def target_read(database, target, backend, *, gate):
    """Runtime accepts only legitimate target inputs; no setup aliases or expected facts."""
    allowed = {"learner_id", "course_id", "session_id", "as_of", "horizon", "query", "page",
               "visible_history", "visibility_rule"}
    if set(target) != allowed:
        raise ValueError("RUNTIME_TARGET_KEYS_MISMATCH")
    with ReadOnlyStore(database, clock=lambda: target["as_of"]) as store:
        before = object_sha(snapshot(store))
        provider = C4LearnerMemoryProvider(store, semantic_backend=backend, clock=lambda: target["as_of"])
        recorder = RecordingRetriever(store, semantic_backend=backend, clock=lambda: target["as_of"])
        recorder.calls, recorder.last = 0, None
        provider.retriever = recorder
        if gate == "FORCED_ENGINEERING_DIAGNOSTIC":
            envelope = provider.retrieve(target["learner_id"], target["query"], target["visible_history"])
        elif gate == "GATE_OFF_STUB":
            envelope = {"status": "NOT_ACTIVATED", "selected_memory_items": [],
                        "limitations": ["GATE_OFF_STUB_NO_P3_INVOCATION"]}
        else:
            raise ValueError("UNKNOWN_ENGINEERING_GATE")
        after = object_sha(snapshot(store))
        assert before == after
        return {"execution_utc": utc(), "gate": gate, "provider_entered": gate != "GATE_OFF_STUB",
            "retriever_calls": recorder.calls, "envelope": envelope,
            "public_retrieval_diagnostics": recorder.last.diagnostics() if recorder.last else "NOT_ENTERED",
            "nonselected_scores": "UNKNOWN_NOT_EXPOSED_BY_FROZEN_PUBLIC_RESULT",
            "before_logical_sha256": before, "after_logical_sha256": after, "target_state_writes": 0,
            "compiler_retention": "NOT_RUN", "planner_consumption": "NOT_RUN",
            "final_response_utility": "NOT_RUN"}


def availability(database, target, aliases):
    """Evaluation-only observation independent of retrieval and gate activation."""
    with ReadOnlyStore(database, clock=lambda: target["as_of"]) as store:
        records = snapshot(store)["memories"]
        active = store.list_active_memories(target["learner_id"], at=target["as_of"])
        enabled = store.is_memory_enabled(target["learner_id"])
        inverse = {v: k for k, v in aliases.items()}
        exclusions = {}
        at = normalise_timestamp(target["as_of"])
        for r in records:
            reasons = []
            if r["student_id"] != target["learner_id"]: reasons.append("OTHER_LEARNER")
            if r["status"] != "ACTIVE": reasons.append(r["status"])
            if r["consent_status"] not in ("GRANTED", "NOT_REQUIRED"): reasons.append("CONSENT_WITHDRAWN")
            if r["valid_from"] > at: reasons.append("FUTURE_VALIDITY")
            if r["valid_to"] and at >= r["valid_to"]: reasons.append("EXPIRED")
            if not enabled and r["student_id"] == target["learner_id"]: reasons.append("LEARNER_DISABLED")
            exclusions[inverse.get(r["memory_id"], r["memory_id"])] = reasons
        return {"stored_row_count": len(records), "stored_memory_ids": [r["memory_id"] for r in records],
            "active_sql_count": len(active), "memory_enabled": enabled,
            "active_authorized_count": len(active) if enabled else 0,
            "active_authorized_fact_ids": [inverse[r.memory_id] for r in active] if enabled else [],
            "exclusions": exclusions, "records": records}
