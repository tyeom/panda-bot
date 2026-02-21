"""Iterative tool execution loop for Claude tool use responses."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from panda_bot.ai.client import AnthropicClient
from panda_bot.ai.tools.base import Tool
from panda_bot.ai.tools.registry import ToolRegistry
from panda_bot.log import get_logger
from panda_bot.storage.conversation_repo import ConversationRepository
from panda_bot.storage.models import ConversationRecord

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 10


async def run_tool_loop(
    ai_client: AnthropicClient,
    tool_registry: ToolRegistry,
    conversation_repo: ConversationRepository,
    messages: list[dict[str, Any]],
    system: str,
    model: str,
    max_tokens: int,
    temperature: float,
    tools: list[Tool],
    bot_id: str,
    session_id: str,
    chat_id: str,
    cancel_event: asyncio.Event | None = None,
) -> str:
    """Execute the Claude tool-use loop until a final text response is produced.

    Returns the final assistant text response.
    """
    tool_defs = [t.to_api_dict() for t in tools]
    rounds = 0

    while rounds < MAX_TOOL_ROUNDS:
        if cancel_event and cancel_event.is_set():
            logger.info("tool_loop_cancelled", bot_id=bot_id, round=rounds)
            return "[작업이 중단되었습니다]"
        response = await ai_client.create_message(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tool_defs if tool_defs else None,
            temperature=temperature,
        )

        # Extract content blocks
        content_blocks = response.content
        tool_use_blocks = [b for b in content_blocks if b.type == "tool_use"]
        text_blocks = [b for b in content_blocks if b.type == "text"]

        # Save assistant tool_use records
        for block in tool_use_blocks:
            await conversation_repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="tool_use",
                    content=json.dumps(block.input),
                    model=model,
                    token_input=response.usage.input_tokens,
                    token_output=response.usage.output_tokens,
                    tool_name=block.name,
                    tool_call_id=block.id,
                )
            )

        # Build assistant message for conversation
        if tool_use_blocks:
            assistant_content: list[dict[str, Any]] = []
            for block in content_blocks:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
            messages.append({"role": "assistant", "content": assistant_content})
        else:
            # Text-only response
            final_text = "\n".join(b.text for b in text_blocks)
            messages.append({"role": "assistant", "content": final_text})

            # Save assistant text
            await conversation_repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="assistant",
                    content=final_text,
                    model=model,
                    token_input=response.usage.input_tokens,
                    token_output=response.usage.output_tokens,
                )
            )
            return final_text

        if not tool_use_blocks:
            break

        # Check for cancellation before executing tools
        if cancel_event and cancel_event.is_set():
            logger.info("tool_loop_cancelled_before_exec", bot_id=bot_id)
            return "[작업이 중단되었습니다]"

        # Execute tool calls concurrently
        async def _execute_one(block: Any) -> tuple[str, str]:
            if cancel_event and cancel_event.is_set():
                return block.id, "[Cancelled]"
            tool = tool_registry.get(block.name)
            if tool is None:
                return block.id, f"Error: unknown tool '{block.name}'"
            try:
                result = await tool.execute(**block.input)
                return block.id, result
            except asyncio.CancelledError:
                return block.id, "[Cancelled]"
            except Exception as e:
                logger.error("tool_execution_error", tool=block.name, error=str(e))
                return block.id, f"Error executing {block.name}: {e}"

        results = await asyncio.gather(*(_execute_one(b) for b in tool_use_blocks))

        # Save tool results and build message
        tool_result_content: list[dict[str, Any]] = []
        for tool_use_id, result_text in results:
            # Find matching tool_use block for metadata
            matching_block = next((b for b in tool_use_blocks if b.id == tool_use_id), None)
            tool_name = matching_block.name if matching_block else None

            await conversation_repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="tool_result",
                    content=result_text,
                    model=model,
                    tool_name=tool_name,
                    tool_call_id=tool_use_id,
                )
            )
            tool_result_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_text,
                }
            )

        messages.append({"role": "user", "content": tool_result_content})
        rounds += 1

    return "[Tool execution limit reached]"
