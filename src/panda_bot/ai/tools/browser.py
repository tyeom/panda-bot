"""Browser tool for web page navigation and scraping."""

from __future__ import annotations

from typing import Any

from panda_bot.ai.tools.base import Tool
from panda_bot.services.browser import BrowserService


class BrowserTool(Tool):
    """Tool that allows Claude to browse the web, extract content, and take screenshots.

    The browser maintains a persistent session across calls, so cookies,
    localStorage, and sessionStorage are preserved between actions.
    """

    def __init__(self, browser_service: BrowserService):
        super().__init__()
        self._browser = browser_service

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Browse the web with a persistent browser session. "
            "Cookies and login state are maintained across calls. "
            "Actions: open a page, get HTML, take screenshots, evaluate JavaScript, "
            "click elements, fill form fields, or clear the session. "
            "If url is omitted, the action runs on the current page."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["open", "html", "screenshot", "evaluate", "click", "fill", "clear_session"],
                    "description": (
                        "Action to perform: "
                        "'open' = get text content, "
                        "'html' = get raw HTML, "
                        "'screenshot' = take a screenshot, "
                        "'evaluate' = run JavaScript, "
                        "'click' = click an element and extract content, "
                        "'fill' = fill a form field (input/textarea), "
                        "'clear_session' = clear cookies and session data"
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to. Optional — if omitted, operates on the current page.",
                },
                "script": {
                    "type": "string",
                    "description": "JavaScript code to evaluate (for 'evaluate' action)",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the target element (for 'click' and 'fill' actions)",
                },
                "value": {
                    "type": "string",
                    "description": "Value to fill into the form field (for 'fill' action)",
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
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "open")
        url = kwargs.get("url") or None

        try:
            match action:
                case "open":
                    return await self._browser.open_page(url)
                case "html":
                    return await self._browser.get_html(url)
                case "screenshot":
                    full_page = kwargs.get("full_page", False)
                    screenshot_bytes = await self._browser.screenshot(url, full_page=full_page)
                    self.add_pending_image(screenshot_bytes, "image/png", "screenshot.png")
                    return f"Screenshot taken ({len(screenshot_bytes)} bytes). Image will be sent to user."
                case "evaluate":
                    script = kwargs.get("script", "")
                    if not script:
                        return "Error: script is required for evaluate action"
                    return await self._browser.evaluate_script(script, url)
                case "click":
                    selector = kwargs.get("selector", "")
                    if not selector:
                        return "Error: selector is required for click action"
                    extract_selector = kwargs.get("extract_selector")
                    return await self._browser.click_and_extract(
                        selector, url, extract_selector
                    )
                case "fill":
                    selector = kwargs.get("selector", "")
                    value = kwargs.get("value", "")
                    if not selector:
                        return "Error: selector is required for fill action"
                    if not value:
                        return "Error: value is required for fill action"
                    return await self._browser.fill(selector, value, url)
                case "clear_session":
                    return await self._browser.clear_session()
                case _:
                    return f"Error: unknown action '{action}'"
        except Exception as e:
            return f"Browser error: {e}"
