"""SQLite database connection manager with schema migration."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from panda_bot.log import get_logger

logger = get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          TEXT    NOT NULL,
    session_id      TEXT    NOT NULL,
    chat_id         TEXT    NOT NULL,
    role            TEXT    NOT NULL CHECK(role IN ('user','assistant','tool_use','tool_result')),
    content         TEXT    NOT NULL,
    model           TEXT    NOT NULL DEFAULT '',
    token_input     INTEGER NOT NULL DEFAULT 0,
    token_output    INTEGER NOT NULL DEFAULT 0,
    tool_name       TEXT,
    tool_call_id    TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_turns_session
    ON conversation_turns(bot_id, session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_turns_chat
    ON conversation_turns(bot_id, chat_id);

CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
    content,
    content='conversation_turns',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_fts_insert AFTER INSERT ON conversation_turns BEGIN
    INSERT INTO conversation_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_fts_delete AFTER DELETE ON conversation_turns BEGIN
    INSERT INTO conversation_fts(conversation_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TABLE IF NOT EXISTS sessions (
    bot_id          TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    chat_id         TEXT NOT NULL,
    platform        TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    last_active_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (bot_id, session_id)
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              TEXT PRIMARY KEY,
    bot_id          TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    cron_expr       TEXT,
    run_at          TEXT,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    enabled         INTEGER NOT NULL DEFAULT 1
);
"""


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open connection and run migrations."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        logger.info("database_initialized", path=self._db_path)

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("database_closed")
