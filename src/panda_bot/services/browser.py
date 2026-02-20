"""Playwright browser service for web automation and scraping."""

from __future__ import annotations

import asyncio
from typing import Optional

from panda_bot.config import BrowserServiceConfig
from panda_bot.log import get_logger
from panda_bot.services.base import Service

logger = get_logger(__name__)


class BrowserService(Service):
    """Manages a Playwright browser instance for web automation.

    Uses a persistent BrowserContext and reusable page so that cookies,
    localStorage, and sessionStorage survive across tool calls.
    """

    def __init__(self, config: BrowserServiceConfig):
        self._config = config
        self._playwright: Optional[object] = None
        self._browser: Optional[object] = None
        self._context: Optional[object] = None
        self._page: Optional[object] = None
        self._lock = asyncio.Lock()

    @property
    def service_name(self) -> str:
        return "browser"

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self._config.browser_type)
        self._browser = await launcher.launch(headless=self._config.headless)
        self._context = await self._browser.new_context()  # type: ignore[union-attr]
        self._page = None  # lazy creation via _ensure_page
        logger.info(
            "browser_started",
            browser_type=self._config.browser_type,
            headless=self._config.headless,
        )

    async def stop(self) -> None:
        if self._page and not self._page.is_closed():  # type: ignore[union-attr]
            await self._page.close()  # type: ignore[union-attr]
            self._page = None
        if self._context:
            await self._context.close()  # type: ignore[union-attr]
            self._context = None
        if self._browser:
            await self._browser.close()  # type: ignore[union-attr]
            self._browser = None
        if self._playwright:
            await self._playwright.stop()  # type: ignore[union-attr]
            self._playwright = None
        logger.info("browser_stopped")

    async def health_check(self) -> bool:
        return self._browser is not None and self._browser.is_connected()  # type: ignore[union-attr]

    async def _ensure_page(self):
        """Return the persistent page, creating one if needed."""
        if self._page is None or self._page.is_closed():  # type: ignore[union-attr]
            self._page = await self._context.new_page()  # type: ignore[union-attr]
        return self._page

    async def open_page(self, url: str | None = None, wait_until: str = "domcontentloaded") -> str:
        """Open a URL (or reuse current page) and return the page text content."""
        async with self._lock:
            page = await self._ensure_page()
            if url:
                await page.goto(
                    url,
                    wait_until=wait_until,
                    timeout=self._config.timeout_ms,
                )
            content = await page.inner_text("body")
            return content[:50000]

    async def screenshot(self, url: str | None = None, full_page: bool = False) -> bytes:
        """Take a screenshot and return PNG bytes. Navigates if url is provided."""
        async with self._lock:
            page = await self._ensure_page()
            if url:
                await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self._config.timeout_ms,
                )
            return await page.screenshot(full_page=full_page)

    async def get_html(self, url: str | None = None) -> str:
        """Get the full HTML content. Navigates if url is provided."""
        async with self._lock:
            page = await self._ensure_page()
            if url:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
            html = await page.content()
            return html[:100000]

    async def evaluate_script(self, script: str, url: str | None = None) -> str:
        """Evaluate JavaScript on the current page. Navigates first if url is provided."""
        async with self._lock:
            page = await self._ensure_page()
            if url:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
            result = await page.evaluate(script)
            return str(result)

    async def click_and_extract(
        self, selector: str, url: str | None = None, extract_selector: str | None = None
    ) -> str:
        """Click an element and extract content. Auto-detects and switches to popups."""
        async with self._lock:
            page = await self._ensure_page()
            if url:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )

            # Track pages before click for popup detection
            pages_before = list(self._context.pages)  # type: ignore[union-attr]

            await page.click(selector, timeout=self._config.timeout_ms)
            await page.wait_for_load_state("domcontentloaded")

            # Check for popup windows opened by the click
            popup_msg = ""
            await asyncio.sleep(0.5)
            new_pages = [
                p for p in self._context.pages  # type: ignore[union-attr]
                if p not in pages_before and not p.is_closed()
            ]
            if new_pages:
                self._page = new_pages[-1]
                try:
                    await self._page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                popup_msg = (
                    f"\n[Popup detected: auto-switched to '{self._page.url}'. "
                    "Use 'list_pages' to see all pages, 'switch_page' to switch.]"
                )
                page = self._page
                logger.info("popup_detected", url=self._page.url)

            target = extract_selector or "body"
            content = await page.inner_text(target)
            return content[:50000] + popup_msg

    async def fill(self, selector: str, value: str, url: str | None = None) -> str:
        """Fill a form field identified by CSS selector. Navigates first if url is provided."""
        async with self._lock:
            page = await self._ensure_page()
            if url:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._config.timeout_ms,
                )
            await page.fill(selector, value, timeout=self._config.timeout_ms)
            return f"Filled '{selector}' with value."

    async def clear_session(self) -> str:
        """Clear all session data by recreating the browser context."""
        async with self._lock:
            if self._page and not self._page.is_closed():  # type: ignore[union-attr]
                await self._page.close()  # type: ignore[union-attr]
            if self._context:
                await self._context.close()  # type: ignore[union-attr]
            self._context = await self._browser.new_context()  # type: ignore[union-attr]
            self._page = None
            logger.info("browser_session_cleared")
            return "Browser session cleared."

    async def list_pages(self) -> list[dict]:
        """List all open pages in the browser context."""
        async with self._lock:
            pages = self._context.pages  # type: ignore[union-attr]
            current = self._page
            result = []
            for i, page in enumerate(pages):
                result.append({
                    "index": i,
                    "url": page.url,
                    "title": await page.title(),
                    "active": page is current,
                })
            return result

    async def switch_page(self, index: int) -> str:
        """Switch the active page to the one at the given index."""
        async with self._lock:
            pages = self._context.pages  # type: ignore[union-attr]
            if index < 0 or index >= len(pages):
                return f"Error: invalid page index {index}. Open pages: {len(pages)}"
            self._page = pages[index]
            url = self._page.url
            logger.info("page_switched", index=index, url=url)
            return f"Switched to page {index}: {url}"

    async def close_page(self) -> str:
        """Close the current page and switch to another open page."""
        async with self._lock:
            if self._page is None:
                return "No page to close."
            pages = self._context.pages  # type: ignore[union-attr]
            if len(pages) <= 1:
                return "Cannot close the last remaining page. Use 'clear_session' instead."
            current = self._page
            remaining = [p for p in pages if p is not current]
            self._page = remaining[-1]
            await current.close()
            logger.info("page_closed", switched_to=self._page.url)
            return f"Page closed. Switched to: {self._page.url}"
