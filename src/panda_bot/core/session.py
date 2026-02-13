"""Session manager mapping (bot_id, chat_id) to session IDs."""

from __future__ import annotations

import uuid

from panda_bot.log import get_logger
from panda_bot.storage.conversation_repo import ConversationRepository

logger = get_logger(__name__)


class SessionManager:
    """Manages sessions per (bot_id, chat_id) pair."""

    def __init__(self, conversation_repo: ConversationRepository):
        self._repo = conversation_repo
        self._active_sessions: dict[tuple[str, str], str] = {}

    def get_session_id(self, bot_id: str, chat_id: str) -> str:
        """Get or create a session ID for a (bot_id, chat_id) pair."""
        key = (bot_id, chat_id)
        if key not in self._active_sessions:
            session_id = uuid.uuid4().hex[:12]
            self._active_sessions[key] = session_id
            logger.info("session_created", bot_id=bot_id, chat_id=chat_id, session_id=session_id)
        return self._active_sessions[key]

    def reset_session(self, bot_id: str, chat_id: str) -> str:
        """Force create a new session, returning the new session ID."""
        key = (bot_id, chat_id)
        session_id = uuid.uuid4().hex[:12]
        self._active_sessions[key] = session_id
        logger.info("session_reset", bot_id=bot_id, chat_id=chat_id, session_id=session_id)
        return session_id

    @property
    def repo(self) -> ConversationRepository:
        return self._repo
