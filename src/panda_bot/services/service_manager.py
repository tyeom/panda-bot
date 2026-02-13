"""Service lifecycle manager."""

from __future__ import annotations

from panda_bot.config import ServicesConfig
from panda_bot.log import get_logger
from panda_bot.services.browser import BrowserService
from panda_bot.services.scheduler import SchedulerService

logger = get_logger(__name__)


class ServiceManager:
    """Manages startup and shutdown of all services."""

    def __init__(self, config: ServicesConfig):
        self._browser = BrowserService(config.browser)
        self._scheduler = SchedulerService(config.scheduler)

    def get_browser(self) -> BrowserService:
        return self._browser

    def get_scheduler(self) -> SchedulerService:
        return self._scheduler

    async def start_all(self) -> None:
        """Start all services. Non-critical services log errors but don't block startup."""
        await self._scheduler.start()
        try:
            await self._browser.start()
        except Exception as e:
            logger.warning(
                "browser_service_unavailable",
                error=str(e),
                hint="Run 'python -m playwright install chromium' to install the browser",
            )
        logger.info("all_services_started")

    async def stop_all(self) -> None:
        """Stop all services gracefully."""
        await self._browser.stop()
        await self._scheduler.stop()
        logger.info("all_services_stopped")

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all services."""
        return {
            "browser": await self._browser.health_check(),
            "scheduler": await self._scheduler.health_check(),
        }
