"""Abstract tool interface for Claude tool use."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from panda_bot.messenger.models import Attachment


class Tool(ABC):
    """Base class for all Claude-callable tools."""

    def __init__(self) -> None:
        self._pending_images: list[Attachment] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name sent to the Anthropic API."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for Claude."""
        ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema dict describing accepted parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Run the tool and return a text result for Claude."""
        ...

    def add_pending_image(self, data: bytes, media_type: str, filename: str) -> None:
        """Queue an image to be sent to the user after this tool round."""
        from panda_bot.messenger.models import Attachment

        self._pending_images.append(Attachment(data=data, media_type=media_type, filename=filename))

    def take_pending_images(self) -> list[Attachment]:
        """Return and clear all pending images."""
        images = self._pending_images
        self._pending_images = []
        return images

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize to the Anthropic API tool definition format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
