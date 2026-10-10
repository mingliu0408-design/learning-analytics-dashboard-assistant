PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS c4_schema_metadata (
    schema_name TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    architecture_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO c4_schema_metadata (
    schema_name,
    schema_version,
    architecture_id,
    created_at
) VALUES (
    'c4_memory_schema_v1',
    1,
    'C4_LEARNER_MEMORY_V1',
    '2026-09-01T00:00:00+00:00'
);

CREATE TABLE IF NOT EXISTS learner_memory_settings (
    student_id TEXT PRIMARY KEY,
    memory_enabled INTEGER NOT NULL DEFAULT 1 CHECK (memory_enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL UNIQUE,
    student_id TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (
        memory_type IN (
            'GOAL',
            'PREFERENCE',
            'CONSTRAINT',
            'DIFFICULTY',
            'COMPLETED_ACTION',
            'ACTIVE_PLAN',
            'PROGRESS_UPDATE',
            'CORRECTION'
        )
    ),
    content TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    source_turn_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    last_confirmed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'DELETED')),
    importance REAL NOT NULL CHECK (importance >= 0.0 AND importance <= 1.0),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    supersedes_memory_id TEXT REFERENCES memories(memory_id) ON DELETE CASCADE,
    consent_status TEXT NOT NULL CHECK (
        consent_status IN ('GRANTED', 'WITHDRAWN', 'NOT_REQUIRED')
    ),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    conflict_key TEXT,
    deletion_event_sha256 TEXT CHECK (
        deletion_event_sha256 IS NULL OR length(deletion_event_sha256) = 64
    ),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (memory_id <> COALESCE(supersedes_memory_id, ''))
);

CREATE INDEX IF NOT EXISTS idx_memories_student_status_time
    ON memories(student_id, status, valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_memories_student_type_status
    ON memories(student_id, memory_type, status);

CREATE INDEX IF NOT EXISTS idx_memories_conflict_key_status
    ON memories(student_id, conflict_key, status);

CREATE INDEX IF NOT EXISTS idx_memories_supersedes
    ON memories(supersedes_memory_id);

CREATE TABLE IF NOT EXISTS memory_events (
    event_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    memory_id TEXT,
    operation TEXT NOT NULL CHECK (
        operation IN ('ADD', 'UPDATE', 'SUPERSEDE', 'DELETE', 'NOOP', 'RESET', 'DISABLE', 'ENABLE')
    ),
    event_at TEXT NOT NULL,
    before_status TEXT,
    after_status TEXT,
    target_memory_id TEXT,
    reason_code TEXT NOT NULL,
    event_sha256 TEXT NOT NULL UNIQUE CHECK (length(event_sha256) = 64)
);

CREATE INDEX IF NOT EXISTS idx_memory_events_student_time
    ON memory_events(student_id, event_at, event_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    memory_type,
    content='memories',
    content_rowid='row_id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memory_fts(rowid, content, memory_type)
    VALUES (new.row_id, new.content, new.memory_type);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, memory_type)
    VALUES ('delete', old.row_id, old.content, old.memory_type);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content, memory_type)
    VALUES ('delete', old.row_id, old.content, old.memory_type);
    INSERT INTO memory_fts(rowid, content, memory_type)
    VALUES (new.row_id, new.content, new.memory_type);
END;
