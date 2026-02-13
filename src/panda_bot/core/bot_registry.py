"""Registry of active bot (messenger adapter) instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from panda_bot.messenger.base import MessengerAdapter


class BotRegistry:
    """Tracks all active messenger adapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, MessengerAdapter] = {}

    def register(self, bot_id: str, adapter: MessengerAdapter) -> None:
        self._adapters[bot_id] = adapter

    def get(self, bot_id: str) -> MessengerAdapter | None:
        return self._adapters.get(bot_id)

    def all(self) -> list[MessengerAdapter]:
        return list(self._adapters.values())

    def ids(self) -> list[str]:
        return list(self._adapters.keys())
