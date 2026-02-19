"""Unified message models for all messenger platforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from panda_bot.core.types import Platform


@dataclass(frozen=True, slots=True)
class Attachment:
    """Binary attachment (image, file, etc.)."""

    data: bytes
    media_type: str  # e.g. "image/jpeg", "image/png"
    filename: str = "attachment"


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    platform: Platform
    bot_id: str
    chat_id: str
    user_id: str
    user_display_name: str
    text: str
    timestamp: datetime
    reply_to_message_id: Optional[str] = None
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    chat_id: str
    text: str
    parse_mode: Optional[str] = None  # "markdown", "html", None
    reply_to_message_id: Optional[str] = None
    attachments: list[Attachment] = field(default_factory=list)
