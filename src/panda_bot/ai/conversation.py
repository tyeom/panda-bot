"""Convert conversation history to Anthropic API message format."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from panda_bot.storage.models import ConversationRecord

if TYPE_CHECKING:
    from panda_bot.messenger.models import Attachment

_TEXT_PREFIXES = ("text/",)
_TEXT_TYPES = frozenset({
    "application/json", "application/xml", "application/javascript",
    "application/x-yaml", "application/sql", "application/x-sh",
    "application/xhtml+xml", "application/csv",
})


def _is_text_media_type(media_type: str) -> bool:
    """Return True if the media type represents a human-readable text format."""
    return media_type.startswith(_TEXT_PREFIXES) or media_type in _TEXT_TYPES


def build_messages(
    history: list[ConversationRecord],
    current_attachments: list[Attachment] | None = None,
) -> list[dict[str, Any]]:
    """Convert stored conversation records into Anthropic API messages format.

    Groups consecutive tool_use and tool_result records into proper content blocks.
    If *current_attachments* are provided, the last user message is converted to
    a multimodal content list with image blocks appended.
    """
    messages: list[dict[str, Any]] = []
    i = 0

    while i < len(history):
        record = history[i]

        if record.role == "user":
            messages.append({"role": "user", "content": record.content})
            i += 1

        elif record.role == "assistant":
            messages.append({"role": "assistant", "content": record.content})
            i += 1

        elif record.role == "tool_use":
            # Collect consecutive tool_use blocks into one assistant message
            content_blocks: list[dict[str, Any]] = []
            while i < len(history) and history[i].role == "tool_use":
                import json

                try:
                    tool_input = json.loads(history[i].content)
                except (json.JSONDecodeError, TypeError):
                    tool_input = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": history[i].tool_call_id or f"tool_{i}",
                        "name": history[i].tool_name or "unknown",
                        "input": tool_input,
                    }
                )
                i += 1
            messages.append({"role": "assistant", "content": content_blocks})

        elif record.role == "tool_result":
            # Collect consecutive tool_result blocks into one user message
            result_blocks: list[dict[str, Any]] = []
            while i < len(history) and history[i].role == "tool_result":
                result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": history[i].tool_call_id or f"tool_{i}",
                        "content": history[i].content,
                    }
                )
                i += 1
            messages.append({"role": "user", "content": result_blocks})

        else:
            i += 1

    # Append attachment blocks to the last user message
    if current_attachments and messages:
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.get("role") != "user":
                continue
            content = msg["content"]
            # Convert plain string content to list format
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            # Append content blocks based on media type
            for att in current_attachments:
                if att.media_type.startswith("image/"):
                    # Image: base64 image block
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": att.media_type,
                                "data": base64.b64encode(att.data).decode(),
                            },
                        }
                    )
                elif _is_text_media_type(att.media_type):
                    # Text file: decode and include contents
                    try:
                        text_content = att.data.decode("utf-8")
                    except UnicodeDecodeError:
                        text_content = att.data.decode("utf-8", errors="replace")
                    content.append(
                        {
                            "type": "text",
                            "text": f"[File: {att.filename}]\n{text_content}",
                        }
                    )
                else:
                    # Binary file: include metadata only
                    size_kb = len(att.data) / 1024
                    content.append(
                        {
                            "type": "text",
                            "text": (
                                f"[File: {att.filename} "
                                f"({att.media_type}, {size_kb:.1f} KB) — binary file, content not shown]"
                            ),
                        }
                    )
            messages[idx]["content"] = content
            break

    return messages
