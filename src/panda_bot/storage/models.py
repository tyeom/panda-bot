"""Data models for storage layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ConversationRecord:
    bot_id: str
    session_id: str
    chat_id: str
    role: str  # "user" | "assistant" | "tool_use" | "tool_result"
    content: str
    model: str = ""
    token_input: int = 0
    token_output: int = 0
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    id: Optional[int] = None


@dataclass
class SessionInfo:
    bot_id: str
    session_id: str
    chat_id: str
    platform: str
    created_at: datetime
    last_active_at: datetime
    metadata: dict = field(default_factory=dict)
