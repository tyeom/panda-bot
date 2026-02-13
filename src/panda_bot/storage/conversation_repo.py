"""Conversation repository with CRUD and FTS5 full-text search."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from panda_bot.log import get_logger
from panda_bot.storage.database import Database
from panda_bot.storage.models import ConversationRecord, SessionInfo

logger = get_logger(__name__)


class ConversationRepository:
    """CRUD + FTS5 search over conversation history."""

    def __init__(self, db: Database):
        self._db = db

    async def save_turn(self, record: ConversationRecord) -> int:
        """Save a conversation turn and return its ID."""
        cursor = await self._db.conn.execute(
            """INSERT INTO conversation_turns
               (bot_id, session_id, chat_id, role, content, model,
                token_input, token_output, tool_name, tool_call_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.bot_id,
                record.session_id,
                record.chat_id,
                record.role,
                record.content,
                record.model,
                record.token_input,
                record.token_output,
                record.tool_name,
                record.tool_call_id,
            ),
        )
        await self._db.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_session_history(
        self, bot_id: str, session_id: str, limit: int = 100
    ) -> list[ConversationRecord]:
        """Get conversation history for a session, ordered by time."""
        cursor = await self._db.conn.execute(
            """SELECT * FROM conversation_turns
               WHERE bot_id = ? AND session_id = ?
               ORDER BY created_at ASC
               LIMIT ?""",
            (bot_id, session_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def search(
        self, query: str, bot_id: Optional[str] = None, limit: int = 20
    ) -> list[ConversationRecord]:
        """Full-text search across conversation history."""
        if bot_id:
            cursor = await self._db.conn.execute(
                """SELECT t.* FROM conversation_turns t
                   JOIN conversation_fts f ON t.id = f.rowid
                   WHERE conversation_fts MATCH ? AND t.bot_id = ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, bot_id, limit),
            )
        else:
            cursor = await self._db.conn.execute(
                """SELECT t.* FROM conversation_turns t
                   JOIN conversation_fts f ON t.id = f.rowid
                   WHERE conversation_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            )
        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def delete_session(self, bot_id: str, session_id: str) -> int:
        """Delete all turns for a session. Returns number of deleted rows."""
        cursor = await self._db.conn.execute(
            "DELETE FROM conversation_turns WHERE bot_id = ? AND session_id = ?",
            (bot_id, session_id),
        )
        await self._db.conn.execute(
            "DELETE FROM sessions WHERE bot_id = ? AND session_id = ?",
            (bot_id, session_id),
        )
        await self._db.conn.commit()
        return cursor.rowcount

    async def list_sessions(self, bot_id: str) -> list[SessionInfo]:
        """List all sessions for a bot."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM sessions WHERE bot_id = ? ORDER BY last_active_at DESC",
            (bot_id,),
        )
        rows = await cursor.fetchall()
        return [
            SessionInfo(
                bot_id=row["bot_id"],
                session_id=row["session_id"],
                chat_id=row["chat_id"],
                platform=row["platform"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_active_at=datetime.fromisoformat(row["last_active_at"]),
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    async def upsert_session(
        self, bot_id: str, session_id: str, chat_id: str, platform: str
    ) -> None:
        """Create or update session metadata."""
        await self._db.conn.execute(
            """INSERT INTO sessions (bot_id, session_id, chat_id, platform)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(bot_id, session_id)
               DO UPDATE SET last_active_at = strftime('%Y-%m-%dT%H:%M:%f','now')""",
            (bot_id, session_id, chat_id, platform),
        )
        await self._db.conn.commit()

    @staticmethod
    def _row_to_record(row) -> ConversationRecord:
        return ConversationRecord(
            id=row["id"],
            bot_id=row["bot_id"],
            session_id=row["session_id"],
            chat_id=row["chat_id"],
            role=row["role"],
            content=row["content"],
            model=row["model"],
            token_input=row["token_input"],
            token_output=row["token_output"],
            tool_name=row["tool_name"],
            tool_call_id=row["tool_call_id"],
            timestamp=datetime.fromisoformat(row["created_at"]),
        )
