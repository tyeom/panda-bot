"""Abstract messenger adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from panda_bot.messenger.models import IncomingMessage, OutgoingMessage


class MessengerAdapter(ABC):
    """Base class for all messenger platform adapters.

    To add a new messenger, subclass this and implement all abstract methods.
    """

    def __init__(self, bot_id: str, config: dict):
        self.bot_id = bot_id
        self.config = config
        self._message_callback: Callable[[IncomingMessage], Awaitable[None]] | None = None

    @abstractmethod
    async def start(self) -> None:
        """Connect to the platform and begin receiving messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnect."""
        ...

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a message to a specific chat/channel."""
        ...

    @abstractmethod
    async def send_typing_indicator(self, chat_id: str) -> None:
        """Show typing/processing indicator."""
        ...

    def on_message(self, callback: Callable[[IncomingMessage], Awaitable[None]]) -> None:
        """Register the callback invoked for every incoming message."""
        self._message_callback = callback

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return platform identifier string."""
        ...
