"""Browser tool for web page navigation and scraping."""

from __future__ import annotations

from typing import Any

from panda_bot.ai.tools.base import Tool
from panda_bot.services.browser import BrowserService


class BrowserTool(Tool):
    """Tool that allows Claude to browse the web, extract content, and take screenshots."""

    def __init__(self, browser_service: BrowserService):
        self._browser = browser_service

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Browse the web by opening URLs, extracting text content, getting HTML, "
            "taking screenshots, evaluating JavaScript, or clicking elements. "
            "Use this to look up information, scrape web pages, or interact with websites."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["open", "html", "screenshot", "evaluate", "click"],
                    "description": (
                        "Action to perform: "
                        "'open' = get text content, "
                        "'html' = get raw HTML, "
                        "'screenshot' = take a screenshot, "
                        "'evaluate' = run JavaScript, "
                        "'click' = click an element and extract content"
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to",
                },
                "script": {
                    "type": "string",
                    "description": "JavaScript code to evaluate (for 'evaluate' action)",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click target (for 'click' action)",
                },
                "extract_selector": {
                    "type": "string",
                    "description": "CSS selector for content extraction after click (optional)",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Whether to capture full page screenshot (default: false)",
                },
            },
            "required": ["action", "url"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "open")
        url = kwargs.get("url", "")

        if not url:
            return "Error: url is required"

        try:
            match action:
                case "open":
                    return await self._browser.open_page(url)
                case "html":
                    return await self._browser.get_html(url)
                case "screenshot":
                    full_page = kwargs.get("full_page", False)
                    screenshot_bytes = await self._browser.screenshot(url, full_page=full_page)
                    return f"Screenshot taken ({len(screenshot_bytes)} bytes). Image saved."
                case "evaluate":
                    script = kwargs.get("script", "")
                    if not script:
                        return "Error: script is required for evaluate action"
                    return await self._browser.evaluate_script(url, script)
                case "click":
                    selector = kwargs.get("selector", "")
                    if not selector:
                        return "Error: selector is required for click action"
                    extract_selector = kwargs.get("extract_selector")
                    return await self._browser.click_and_extract(
                        url, selector, extract_selector
                    )
                case _:
                    return f"Error: unknown action '{action}'"
        except Exception as e:
            return f"Browser error: {e}"
