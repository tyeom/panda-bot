"""Playwright browser service for web automation and scraping."""

from __future__ import annotations

import asyncio
from typing import Optional

from panda_bot.config import BrowserServiceConfig
from panda_bot.log import get_logger
from panda_bot.services.base import Service

logger = get_logger(__name__)


class BrowserService(Service):
    """Manages a Playwright browser instance for web automation."""

    def __init__(self, config: BrowserServiceConfig):
        self._config = config
        self._playwright: Optional[object] = None
        self._browser: Optional[object] = None
        self._lock = asyncio.Lock()

    @property
    def service_name(self) -> str:
        return "browser"

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self._config.browser_type)
        self._browser = await launcher.launch(headless=self._config.headless)
        logger.info(
            "browser_started",
            browser_type=self._config.browser_type,
            headless=self._config.headless,
        )

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()  # type: ignore[union-attr]
            self._browser = None
        if self._playwright:
            await self._playwright.stop()  # type: ignore[union-attr]
            self._playwright = None
        logger.info("browser_stopped")

    async def health_check(self) -> bool:
        return self._browser is not None and self._browser.is_connected()  # type: ignore[union-attr]

    async def open_page(self, url: str, wait_until: str = "domcontentloaded") -> str:
        """Open a URL and return the page text content."""
        async with self._lock:
            page = await self._browser.new_page()  # type: ignore[union-attr]
            try:
                await page.goto(
                    url,
                    wait_until=wait_until,
                    timeout=self._config.timeout_ms,
                )
                content = await page.inner_text("body")
                return content[:50000]  # Limit content size
            finally:
                await page.close()

    async def screenshot(self, url: str, full_page: bool = False) -> bytes:
        """Take a screenshot of a URL and return PNG bytes."""
        async with self._lock:
            page = await self._browser.new_page()  # type: ignore[union-attr]
            try:
                await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self._config.timeout_ms,
                )
                return await page.screenshot(full_page=full_page)
            finally:
                await page.close()

    async def get_html(self, url: str) -> str:
        """Get the full HTML content of a URL."""
        async with self._lock:
            page = await self._browser.new_page()  # type: ignore[union-attr]
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
                html = await page.content()
                return html[:100000]
            finally:
                await page.close()

    async def evaluate_script(self, url: str, script: str) -> str:
        """Navigate to a URL and evaluate JavaScript on the page."""
        async with self._lock:
            page = await self._browser.new_page()  # type: ignore[union-attr]
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
                result = await page.evaluate(script)
                return str(result)
            finally:
                await page.close()

    async def click_and_extract(
        self, url: str, selector: str, extract_selector: str | None = None
    ) -> str:
        """Navigate to URL, click an element, and extract content."""
        async with self._lock:
            page = await self._browser.new_page()  # type: ignore[union-attr]
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
                await page.click(selector, timeout=self._config.timeout_ms)
                await page.wait_for_load_state("domcontentloaded")

                target = extract_selector or "body"
                content = await page.inner_text(target)
                return content[:50000]
            finally:
                await page.close()
