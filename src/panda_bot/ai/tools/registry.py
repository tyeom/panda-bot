"""Tool registry for discovering and managing available tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from panda_bot.ai.tools.base import Tool
from panda_bot.log import get_logger

if TYPE_CHECKING:
    from panda_bot.services.service_manager import ServiceManager

logger = get_logger(__name__)


class ToolRegistry:
    """Registry of all available tools."""

    def __init__(self, service_manager: ServiceManager):
        self._tools: dict[str, Tool] = {}
        self._service_manager = service_manager

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info("tool_registered", tool_name=tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools_by_names(self, names: list[str]) -> list[Tool]:
        """Get a subset of tools by name list."""
        return [self._tools[n] for n in names if n in self._tools]

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def discover_and_register(self) -> None:
        """Import and register all built-in tools."""
        from panda_bot.ai.tools.browser import BrowserTool
        from panda_bot.ai.tools.executor import ExecutorTool
        from panda_bot.ai.tools.filesystem import FileSystemTool
        from panda_bot.ai.tools.scheduler import SchedulerTool
        from panda_bot.ai.tools.screen_capture import ScreenCaptureTool

        browser_service = self._service_manager.get_browser()
        scheduler_service = self._service_manager.get_scheduler()

        self.register(BrowserTool(browser_service))
        self.register(FileSystemTool())
        self.register(ExecutorTool())
        self.register(SchedulerTool(scheduler_service))
        self.register(ScreenCaptureTool())
