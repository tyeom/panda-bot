"""PC screen capture tool using mss."""

from __future__ import annotations

import io
from typing import Any

import mss

from panda_bot.ai.tools.base import Tool


class ScreenCaptureTool(Tool):
    """Capture the PC desktop screen."""

    @property
    def name(self) -> str:
        return "screen_capture"

    @property
    def description(self) -> str:
        return (
            "Capture the PC screen (desktop screenshot). "
            "Can capture all monitors or a specific monitor. "
            "Returns the screenshot as an image."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "monitor": {
                    "type": "integer",
                    "description": (
                        "Monitor number to capture. "
                        "0 = all monitors combined, "
                        "1 = primary monitor, "
                        "2 = second monitor, etc."
                    ),
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        monitor = kwargs.get("monitor", 1)

        try:
            with mss.mss() as sct:
                if monitor < 0 or monitor >= len(sct.monitors):
                    available = len(sct.monitors) - 1  # exclude index 0 (combined)
                    return (
                        f"Error: monitor {monitor} not found. "
                        f"Available: 0 (all), 1-{available}"
                    )

                screenshot = sct.grab(sct.monitors[monitor])

                buf = io.BytesIO()
                png_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)
                buf.write(png_bytes)
                png_data = buf.getvalue()

            self.add_pending_image(png_data, "image/png", "screenshot.png")
            return f"Screenshot taken ({len(png_data)} bytes). Image will be sent to user."

        except Exception as e:
            return f"Screen capture error: {e}"
