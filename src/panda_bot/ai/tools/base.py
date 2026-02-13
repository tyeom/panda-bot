"""Abstract tool interface for Claude tool use."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class for all Claude-callable tools."""

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

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize to the Anthropic API tool definition format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
