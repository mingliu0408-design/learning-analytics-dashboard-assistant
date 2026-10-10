"""Versioned SQLite store for ``C4_LEARNER_MEMORY_V1``.

The store is local, learner-scoped, and experiment-only.  Every caller supplies
an explicit database path so separate tests and experiment runs never share a
database implicitly.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterator, Mapping, Sequence


ARCHITECTURE_ID = "C4_LEARNER_MEMORY_V1"
SCHEMA_VERSION = 1
MEMORY_TYPES = (
    "GOAL",
    "PREFERENCE",
    "CONSTRAINT",
    "DIFFICULTY",
    "COMPLETED_ACTION",
    "ACTIVE_PLAN",
    "PROGRESS_UPDATE",
    "CORRECTION",
)
MEMORY_STATUSES = ("ACTIVE", "SUPERSEDED", "DELETED")
CONSENT_STATUSES = ("GRANTED", "WITHDRAWN", "NOT_REQUIRED")
DELETED_CONTENT = "[DELETED]"
SCHEMA_PATH = Path(__file__).with_name("c4_memory_schema_v1.sql")
FTS_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "in", "is",
    "it", "me", "my", "of", "on", "or", "said", "say", "that", "the", "this", "to", "was",
    "were", "what", "when", "which", "with", "would", "you", "earlier", "before", "please",
}


class C4MemoryStoreError(RuntimeError):
    """Raised when a store invariant or state transition fails."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_object(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalise_timestamp(value: str | datetime | None) -> str:
    if value is None:
        return utc_now_iso()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise C4MemoryStoreError("INVALID_TIMESTAMP") from exc
    else:
        raise C4MemoryStoreError("INVALID_TIMESTAMP")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise C4MemoryStoreError("NAIVE_TIMESTAMP")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _strictly_after(start: str, proposed: str) -> str:
    start_dt = datetime.fromisoformat(start)
    proposed_dt = datetime.fromisoformat(proposed)
    if proposed_dt <= start_dt:
        proposed_dt = start_dt + timedelta(microseconds=1)
    return proposed_dt.isoformat(timespec="microseconds")


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    student_id: str
    memory_type: str
    content: str
    source_session_id: str
    source_turn_id: str
    created_at: str
    valid_from: str
    valid_to: str | None
    last_confirmed_at: str
    status: str
    importance: float
    confidence: float
    supersedes_memory_id: str | None
    consent_status: str
    content_sha256: str
    version: int
    conflict_key: str | None
    deletion_event_sha256: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any]) -> "MemoryRecord":
        values = dict(row)
        values.pop("row_id", None)
        return cls(**{name: values[name] for name in cls.__dataclass_fields__})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FTSMatch:
    record: MemoryRecord
    fts_rank: float
    rank_position: int


class C4MemoryStore:
    """SQLite-backed persistent Memory store for one test/experiment run."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        raw_path = str(database_path)
        if raw_path == ":memory:":
            raise C4MemoryStoreError("FILE_DATABASE_REQUIRED_PER_RUN")
        self.database_path = Path(database_path).expanduser().resolve()
        if self.database_path.exists() and self.database_path.is_dir():
            raise C4MemoryStoreError("DATABASE_PATH_IS_DIRECTORY")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or utc_now_iso
        self._connection = sqlite3.connect(
            str(self.database_path),
            isolation_level=None,
            timeout=10.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self._connection.execute("PRAGMA journal_mode = DELETE")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._initialise_schema()

    def _initialise_schema(self) -> None:
        if not SCHEMA_PATH.is_file():
            raise C4MemoryStoreError("SCHEMA_FILE_MISSING")
        self._connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        row = self._connection.execute(
            "SELECT schema_version, architecture_id FROM c4_schema_metadata "
            "WHERE schema_name = 'c4_memory_schema_v1'"
        ).fetchone()
        if not row or row["schema_version"] != SCHEMA_VERSION or row["architecture_id"] != ARCHITECTURE_ID:
            raise C4MemoryStoreError("SCHEMA_IDENTITY_MISMATCH")

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None  # type: ignore[assignment]

    def __enter__(self) -> "C4MemoryStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        if self._connection is None:
            raise C4MemoryStoreError("STORE_CLOSED")
        cursor = self._connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
        except Exception:
            cursor.execute("ROLLBACK")
            raise
        else:
            cursor.execute("COMMIT")
        finally:
            cursor.close()

    def _now(self, value: str | datetime | None = None) -> str:
        if value is None:
            value = self._clock()
        return normalise_timestamp(value)

    @staticmethod
    def _validate_identity(value: str, reason: str) -> str:
        value = str(value).strip()
        if not value or len(value) > 256 or any(ord(char) < 32 for char in value):
            raise C4MemoryStoreError(reason)
        return value

    @staticmethod
    def _row_to_record(row: sqlite3.Row | None) -> MemoryRecord | None:
        return MemoryRecord.from_row(row) if row is not None else None

    def get_memory(
        self,
        student_id: str,
        memory_id: str,
        *,
        include_inactive: bool = True,
    ) -> MemoryRecord | None:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        memory_id = self._validate_identity(memory_id, "INVALID_MEMORY_ID")
        sql = "SELECT * FROM memories WHERE student_id = ? AND memory_id = ?"
        params: list[Any] = [student_id, memory_id]
        if not include_inactive:
            sql += " AND status = 'ACTIVE'"
        return self._row_to_record(self._connection.execute(sql, params).fetchone())

    def list_memories(
        self,
        student_id: str,
        *,
        statuses: Sequence[str] | None = None,
    ) -> list[MemoryRecord]:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        sql = "SELECT * FROM memories WHERE student_id = ?"
        params: list[Any] = [student_id]
        if statuses is not None:
            clean = tuple(dict.fromkeys(str(value) for value in statuses))
            if not clean or any(value not in MEMORY_STATUSES for value in clean):
                raise C4MemoryStoreError("INVALID_MEMORY_STATUS_FILTER")
            sql += " AND status IN (" + ",".join("?" for _ in clean) + ")"
            params.extend(clean)
        sql += " ORDER BY created_at ASC, memory_id ASC"
        return [MemoryRecord.from_row(row) for row in self._connection.execute(sql, params)]

    def list_active_memories(
        self,
        student_id: str,
        *,
        at: str | datetime | None = None,
    ) -> list[MemoryRecord]:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        query_time = self._now(at)
        rows = self._connection.execute(
            "SELECT * FROM memories "
            "WHERE student_id = ? AND status = 'ACTIVE' "
            "AND consent_status IN ('GRANTED', 'NOT_REQUIRED') "
            "AND valid_from <= ? AND (valid_to IS NULL OR ? < valid_to) "
            "ORDER BY created_at DESC, memory_id ASC",
            (student_id, query_time, query_time),
        )
        return [MemoryRecord.from_row(row) for row in rows]

    def find_active_duplicate(
        self,
        student_id: str,
        memory_type: str,
        content_sha256: str,
        *,
        at: str | datetime | None = None,
    ) -> MemoryRecord | None:
        query_time = self._now(at)
        row = self._connection.execute(
            "SELECT * FROM memories WHERE student_id = ? AND memory_type = ? "
            "AND content_sha256 = ? AND status = 'ACTIVE' "
            "AND valid_from <= ? AND (valid_to IS NULL OR ? < valid_to) "
            "ORDER BY created_at DESC, memory_id ASC LIMIT 1",
            (student_id, memory_type, content_sha256, query_time, query_time),
        ).fetchone()
        return self._row_to_record(row)

    def _insert_event(
        self,
        cursor: sqlite3.Cursor,
        *,
        student_id: str,
        operation: str,
        event_at: str,
        reason_code: str,
        memory_id: str | None = None,
        before_status: str | None = None,
        after_status: str | None = None,
        target_memory_id: str | None = None,
    ) -> str:
        body = {
            "student_id": student_id,
            "memory_id": memory_id,
            "operation": operation,
            "event_at": event_at,
            "before_status": before_status,
            "after_status": after_status,
            "target_memory_id": target_memory_id,
            "reason_code": reason_code,
        }
        event_sha = sha256_object(body)
        event_id = "evt_" + event_sha[:24]
        cursor.execute(
            "INSERT OR IGNORE INTO memory_events ("
            "event_id, student_id, memory_id, operation, event_at, before_status, "
            "after_status, target_memory_id, reason_code, event_sha256"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                student_id,
                memory_id,
                operation,
                event_at,
                before_status,
                after_status,
                target_memory_id,
                reason_code,
                event_sha,
            ),
        )
        return event_id

    def record_noop(
        self,
        student_id: str,
        *,
        reason_code: str,
        event_at: str | datetime | None = None,
        memory_id: str | None = None,
        target_memory_id: str | None = None,
    ) -> str:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        observed_at = self._now(event_at)
        with self._transaction() as cursor:
            return self._insert_event(
                cursor,
                student_id=student_id,
                operation="NOOP",
                event_at=observed_at,
                reason_code=reason_code,
                memory_id=memory_id,
                target_memory_id=target_memory_id,
            )

    @staticmethod
    def _validate_record_fields(record: MemoryRecord) -> None:
        for value, reason in (
            (record.memory_id, "INVALID_MEMORY_ID"),
            (record.student_id, "INVALID_STUDENT_ID"),
            (record.source_session_id, "INVALID_SOURCE_SESSION_ID"),
            (record.source_turn_id, "INVALID_SOURCE_TURN_ID"),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 256
                or any(ord(char) < 32 for char in value)
            ):
                raise C4MemoryStoreError(reason)
        if record.supersedes_memory_id is not None and (
            not record.supersedes_memory_id.strip()
            or len(record.supersedes_memory_id) > 256
            or any(ord(char) < 32 for char in record.supersedes_memory_id)
        ):
            raise C4MemoryStoreError("INVALID_SUPERSEDES_MEMORY_ID")
        if record.memory_type not in MEMORY_TYPES:
            raise C4MemoryStoreError("INVALID_MEMORY_TYPE")
        if record.status not in MEMORY_STATUSES:
            raise C4MemoryStoreError("INVALID_MEMORY_STATUS")
        if record.consent_status not in CONSENT_STATUSES:
            raise C4MemoryStoreError("INVALID_CONSENT_STATUS")
        if not record.content.strip() or sha256_text(record.content) != record.content_sha256:
            raise C4MemoryStoreError("CONTENT_HASH_MISMATCH")
        if not 0.0 <= record.importance <= 1.0 or not 0.0 <= record.confidence <= 1.0:
            raise C4MemoryStoreError("INVALID_SCORE")
        start = normalise_timestamp(record.valid_from)
        if record.valid_to is not None and normalise_timestamp(record.valid_to) <= start:
            raise C4MemoryStoreError("INVALID_VALIDITY_INTERVAL")
        created = normalise_timestamp(record.created_at)
        confirmed = normalise_timestamp(record.last_confirmed_at)
        if confirmed < created:
            raise C4MemoryStoreError("LAST_CONFIRMED_PRECEDES_CREATION")

    @staticmethod
    def _record_values(record: MemoryRecord) -> tuple[Any, ...]:
        return (
            record.memory_id,
            record.student_id,
            record.memory_type,
            record.content,
            record.source_session_id,
            record.source_turn_id,
            record.created_at,
            record.valid_from,
            record.valid_to,
            record.last_confirmed_at,
            record.status,
            record.importance,
            record.confidence,
            record.supersedes_memory_id,
            record.consent_status,
            record.content_sha256,
            record.version,
            record.conflict_key,
            record.deletion_event_sha256,
        )

    @staticmethod
    def _insert_record(cursor: sqlite3.Cursor, record: MemoryRecord) -> None:
        cursor.execute(
            "INSERT INTO memories ("
            "memory_id, student_id, memory_type, content, source_session_id, "
            "source_turn_id, created_at, valid_from, valid_to, last_confirmed_at, "
            "status, importance, confidence, supersedes_memory_id, consent_status, "
            "content_sha256, version, conflict_key, deletion_event_sha256"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            C4MemoryStore._record_values(record),
        )

    def add_memory(
        self,
        record: MemoryRecord,
        *,
        operation: str = "ADD",
        reason_code: str = "WRITE_AUTHORISED",
    ) -> MemoryRecord:
        self._validate_record_fields(record)
        if operation != "ADD" or record.status != "ACTIVE" or record.supersedes_memory_id is not None:
            raise C4MemoryStoreError("INVALID_ADD_TRANSITION")
        with self._transaction() as cursor:
            self._insert_record(cursor, record)
            self._insert_event(
                cursor,
                student_id=record.student_id,
                operation=operation,
                event_at=record.created_at,
                reason_code=reason_code,
                memory_id=record.memory_id,
                after_status="ACTIVE",
            )
        return record

    def replace_memory(
        self,
        *,
        student_id: str,
        target_memory_id: str,
        replacement: MemoryRecord,
        operation: str,
        reason_code: str,
    ) -> tuple[MemoryRecord, MemoryRecord]:
        if operation not in {"UPDATE", "SUPERSEDE"}:
            raise C4MemoryStoreError("INVALID_REPLACEMENT_OPERATION")
        self._validate_record_fields(replacement)
        if replacement.student_id != student_id or replacement.supersedes_memory_id != target_memory_id:
            raise C4MemoryStoreError("REPLACEMENT_SCOPE_OR_LINK_MISMATCH")
        with self._transaction() as cursor:
            target_row = cursor.execute(
                "SELECT * FROM memories WHERE student_id = ? AND memory_id = ?",
                (student_id, target_memory_id),
            ).fetchone()
            if target_row is None:
                raise C4MemoryStoreError("TARGET_MEMORY_NOT_FOUND")
            target = MemoryRecord.from_row(target_row)
            if target.status != "ACTIVE":
                raise C4MemoryStoreError("TARGET_MEMORY_NOT_ACTIVE")
            if replacement.version != target.version + 1:
                raise C4MemoryStoreError("REPLACEMENT_VERSION_MISMATCH")
            closed_at = _strictly_after(target.valid_from, replacement.created_at)
            cursor.execute(
                "UPDATE memories SET status = 'SUPERSEDED', valid_to = ?, "
                "last_confirmed_at = ? WHERE memory_id = ? AND student_id = ?",
                (closed_at, replacement.created_at, target_memory_id, student_id),
            )
            self._insert_record(cursor, replacement)
            self._insert_event(
                cursor,
                student_id=student_id,
                operation=operation,
                event_at=replacement.created_at,
                reason_code=reason_code,
                memory_id=replacement.memory_id,
                before_status="ACTIVE",
                after_status="ACTIVE",
                target_memory_id=target_memory_id,
            )
        updated_target = self.get_memory(student_id, target_memory_id)
        if updated_target is None:
            raise C4MemoryStoreError("POST_REPLACEMENT_TARGET_MISSING")
        return updated_target, replacement

    def delete_memory(
        self,
        student_id: str,
        memory_id: str,
        *,
        event_at: str | datetime | None = None,
        reason_code: str = "EXPLICIT_DELETE",
    ) -> MemoryRecord:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        memory_id = self._validate_identity(memory_id, "INVALID_MEMORY_ID")
        observed_at = self._now(event_at)
        with self._transaction() as cursor:
            row = cursor.execute(
                "SELECT * FROM memories WHERE student_id = ? AND memory_id = ?",
                (student_id, memory_id),
            ).fetchone()
            if row is None:
                raise C4MemoryStoreError("TARGET_MEMORY_NOT_FOUND")
            target = MemoryRecord.from_row(row)
            if target.status == "DELETED":
                self._insert_event(
                    cursor,
                    student_id=student_id,
                    operation="NOOP",
                    event_at=observed_at,
                    reason_code="ALREADY_DELETED",
                    memory_id=memory_id,
                    target_memory_id=memory_id,
                )
                return target
            deletion_body = {
                "student_id": student_id,
                "memory_id": memory_id,
                "deleted_at": observed_at,
                "prior_content_sha256": target.content_sha256,
            }
            deletion_sha = sha256_object(deletion_body)
            valid_to = _strictly_after(target.valid_from, observed_at)
            cursor.execute(
                "UPDATE memories SET content = ?, status = 'DELETED', valid_to = ?, "
                "last_confirmed_at = ?, consent_status = 'WITHDRAWN', "
                "content_sha256 = ?, deletion_event_sha256 = ? "
                "WHERE student_id = ? AND memory_id = ?",
                (
                    DELETED_CONTENT,
                    valid_to,
                    observed_at,
                    sha256_text(DELETED_CONTENT),
                    deletion_sha,
                    student_id,
                    memory_id,
                ),
            )
            self._insert_event(
                cursor,
                student_id=student_id,
                operation="DELETE",
                event_at=observed_at,
                reason_code=reason_code,
                memory_id=memory_id,
                before_status=target.status,
                after_status="DELETED",
                target_memory_id=memory_id,
            )
        deleted = self.get_memory(student_id, memory_id)
        if deleted is None:
            raise C4MemoryStoreError("POST_DELETE_TARGET_MISSING")
        return deleted

    def is_memory_enabled(self, student_id: str) -> bool:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        row = self._connection.execute(
            "SELECT memory_enabled FROM learner_memory_settings WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        return True if row is None else bool(row["memory_enabled"])

    def set_memory_enabled(
        self,
        student_id: str,
        enabled: bool,
        *,
        event_at: str | datetime | None = None,
    ) -> None:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        observed_at = self._now(event_at)
        operation = "ENABLE" if enabled else "DISABLE"
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO learner_memory_settings (student_id, memory_enabled, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(student_id) DO UPDATE SET "
                "memory_enabled = excluded.memory_enabled, updated_at = excluded.updated_at",
                (student_id, int(bool(enabled)), observed_at),
            )
            self._insert_event(
                cursor,
                student_id=student_id,
                operation=operation,
                event_at=observed_at,
                reason_code="LEARNER_CONTROL",
            )

    def clear_experimental_learner_state(self, student_id: str) -> dict[str, int]:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        with self._transaction() as cursor:
            memory_count = cursor.execute(
                "SELECT count(*) AS count FROM memories WHERE student_id = ?",
                (student_id,),
            ).fetchone()["count"]
            event_count = cursor.execute(
                "SELECT count(*) AS count FROM memory_events WHERE student_id = ?",
                (student_id,),
            ).fetchone()["count"]
            cursor.execute("DELETE FROM memories WHERE student_id = ?", (student_id,))
            cursor.execute("DELETE FROM memory_events WHERE student_id = ?", (student_id,))
            cursor.execute("DELETE FROM learner_memory_settings WHERE student_id = ?", (student_id,))
        return {"memories_removed": int(memory_count), "events_removed": int(event_count)}

    @staticmethod
    def _fts_query(value: str) -> str:
        tokens = []
        for token in re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE):
            if len(token) >= 2 and token not in FTS_STOPWORDS and token not in tokens:
                tokens.append(token)
            if len(tokens) >= 24:
                break
        return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)

    def fts_search(
        self,
        student_id: str,
        query: str,
        *,
        at: str | datetime | None = None,
        limit: int = 25,
    ) -> list[FTSMatch]:
        if limit < 1 or limit > 100:
            raise C4MemoryStoreError("INVALID_FTS_LIMIT")
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        fts_query = self._fts_query(query)
        if not fts_query:
            return []
        query_time = self._now(at)
        rows = self._connection.execute(
            "SELECT m.*, bm25(memory_fts, 1.0, 0.1) AS fts_rank "
            "FROM memory_fts JOIN memories AS m ON m.row_id = memory_fts.rowid "
            "WHERE memory_fts MATCH ? AND m.student_id = ? AND m.status = 'ACTIVE' "
            "AND m.consent_status IN ('GRANTED', 'NOT_REQUIRED') "
            "AND m.valid_from <= ? AND (m.valid_to IS NULL OR ? < m.valid_to) "
            "ORDER BY fts_rank ASC, m.created_at DESC, m.memory_id ASC LIMIT ?",
            (fts_query, student_id, query_time, query_time, limit),
        ).fetchall()
        return [
            FTSMatch(
                record=MemoryRecord.from_row(row),
                fts_rank=float(row["fts_rank"]),
                rank_position=index,
            )
            for index, row in enumerate(rows, 1)
        ]

    def list_events(self, student_id: str) -> list[dict[str, Any]]:
        student_id = self._validate_identity(student_id, "INVALID_STUDENT_ID")
        rows = self._connection.execute(
            "SELECT * FROM memory_events WHERE student_id = ? "
            "ORDER BY event_at ASC, event_id ASC",
            (student_id,),
        )
        return [dict(row) for row in rows]

    def integrity_check(self) -> dict[str, Any]:
        integrity = self._connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = [dict(row) for row in self._connection.execute("PRAGMA foreign_key_check")]
        fts_count = self._connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0]
        memory_count = self._connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        return {
            "integrity_check": integrity,
            "foreign_key_issue_count": len(foreign_key_issues),
            "memory_row_count": int(memory_count),
            "fts_row_count": int(fts_count),
        }
