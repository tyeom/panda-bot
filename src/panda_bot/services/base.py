"""Abstract service lifecycle interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Service(ABC):
    """Base class for background and foreground services."""

    @property
    @abstractmethod
    def service_name(self) -> str:
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...
