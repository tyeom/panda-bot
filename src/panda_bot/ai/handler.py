"""Message handler: receives incoming messages, calls Claude, sends responses."""

from __future__ import annotations

import json
import re
from typing import Any

from panda_bot.ai.client import AIClient
from panda_bot.ai.conversation import build_messages
from panda_bot.ai.tool_runner import run_tool_loop
from panda_bot.ai.tools.base import Tool
from panda_bot.ai.tools.registry import ToolRegistry
from panda_bot.config import BotConfig
from panda_bot.core.session import SessionManager
from panda_bot.log import get_logger
from panda_bot.messenger.base import MessengerAdapter
from panda_bot.messenger.models import IncomingMessage, OutgoingMessage
from panda_bot.storage.models import ConversationRecord

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 10
TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


def _build_tool_system_prompt(tools: list[Tool]) -> str:
    """Build a system prompt section that describes available tools for Claude Code CLI."""
    if not tools:
        return ""

    lines = [
        "\n\n--- Available Tools ---",
        "You have access to the following tools. To use a tool, output EXACTLY this format:",
        "<tool_call>",
        '{"tool": "tool_name", "input": {"param1": "value1"}}',
        "</tool_call>",
        "",
        "You can use multiple tool calls in one response. Wait for tool results before continuing.",
        "When you have the final answer, respond with plain text WITHOUT any <tool_call> tags.",
        "",
        "Tools:",
    ]
    for tool in tools:
        schema = tool.input_schema
        props = schema.get("properties", {})
        param_desc = ", ".join(
            f'{k}: {v.get("description", "")}'
            for k, v in props.items()
        )
        lines.append(f"\n### {tool.name}")
        lines.append(f"Description: {tool.description}")
        lines.append(f"Parameters: {param_desc}")
        required = schema.get("required", [])
        if required:
            lines.append(f"Required: {', '.join(required)}")

    return "\n".join(lines)


class MessageHandler:
    """Handles the full flow: message -> session -> history -> Claude -> tools -> response."""

    def __init__(
        self,
        adapter: MessengerAdapter,
        ai_client: AIClient,
        session_manager: SessionManager,
        tool_registry: ToolRegistry,
        bot_config: BotConfig,
    ):
        self._adapter = adapter
        self._ai_client = ai_client
        self._session_manager = session_manager
        self._tool_registry = tool_registry
        self._bot_config = bot_config

    async def handle(self, message: IncomingMessage) -> None:
        """Process an incoming message end-to-end."""
        bot_id = message.bot_id
        chat_id = message.chat_id
        text = message.text.strip()

        if not text:
            return

        # Handle special commands
        if text.lower() == "/reset":
            self._session_manager.reset_session(bot_id, chat_id)
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text="Session reset. Starting fresh.")
            )
            return

        if text.lower() == "/model":
            backend = self._bot_config.ai.backend
            model = self._ai_client.model_name
            tools = ", ".join(self._bot_config.ai.tools) or "(none)"
            info = (
                f"Bot: {bot_id}\n"
                f"Backend: {backend}\n"
                f"Model: {model}\n"
                f"Tools: {tools}"
            )
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text=info)
            )
            return

        if text.lower().startswith("/search "):
            query = text[8:].strip()
            results = await self._session_manager.repo.search(query, bot_id=bot_id, limit=5)
            if results:
                response_text = "Search results:\n\n" + "\n---\n".join(
                    f"[{r.role}] {r.content[:200]}" for r in results
                )
            else:
                response_text = "No results found."
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text=response_text)
            )
            return

        # Show typing indicator
        await self._adapter.send_typing_indicator(chat_id)

        # Get/create session
        session_id = self._session_manager.get_session_id(bot_id, chat_id)
        repo = self._session_manager.repo

        # Update session metadata
        await repo.upsert_session(
            bot_id=bot_id,
            session_id=session_id,
            chat_id=chat_id,
            platform=message.platform.value,
        )

        # Save user message
        await repo.save_turn(
            ConversationRecord(
                bot_id=bot_id,
                session_id=session_id,
                chat_id=chat_id,
                role="user",
                content=text,
            )
        )

        # Load conversation history
        history = await repo.get_session_history(bot_id, session_id)
        messages = build_messages(history)

        ai_config = self._bot_config.ai

        # Set conversation context on scheduler tool so it knows which chat to target
        scheduler_tool = self._tool_registry.get("scheduler")
        if scheduler_tool and hasattr(scheduler_tool, "set_context"):
            scheduler_tool.set_context(bot_id=bot_id, chat_id=chat_id)

        try:
            if self._ai_client.supports_tool_loop:
                # Anthropic API: use tool_runner loop
                tools = self._tool_registry.get_tools_by_names(ai_config.tools)
                response_text = await run_tool_loop(
                    ai_client=self._ai_client,
                    tool_registry=self._tool_registry,
                    conversation_repo=repo,
                    messages=messages,
                    system=ai_config.system_prompt,
                    model=ai_config.model,
                    max_tokens=ai_config.max_tokens,
                    temperature=ai_config.temperature,
                    tools=tools,
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                )
            else:
                # Claude Code CLI: use text-based tool loop with panda-bot tools
                tools = self._tool_registry.get_tools_by_names(ai_config.tools)
                response_text = await self._run_claude_code_tool_loop(
                    messages=messages,
                    system=ai_config.system_prompt,
                    tools=tools,
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                )

        except Exception as e:
            logger.error("ai_error", bot_id=bot_id, error=str(e))
            response_text = f"An error occurred: {e}"

        # Send response (split long messages)
        for chunk in _split_message(response_text, max_length=4000):
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text=chunk)
            )

    async def _run_claude_code_tool_loop(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        bot_id: str,
        session_id: str,
        chat_id: str,
    ) -> str:
        """Run a text-based tool loop for Claude Code CLI backend.

        Claude Code CLI doesn't natively support panda-bot's tools, so we:
        1. Add tool descriptions to the system prompt
        2. Ask Claude to output <tool_call> tags when it needs a tool
        3. Parse and execute tool calls
        4. Send results back and repeat until we get a plain text response
        """
        repo = self._session_manager.repo

        # Build system prompt with tool descriptions
        tool_prompt = _build_tool_system_prompt(tools) if tools else ""
        full_system = system + tool_prompt

        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            response = await self._ai_client.chat(
                system=full_system,
                messages=messages,
            )
            response_text = response.text

            # Check for tool calls in the response
            tool_calls = TOOL_CALL_PATTERN.findall(response_text)

            if not tool_calls:
                # No tool calls - this is the final response
                # Clean up any residual tags
                final_text = response_text.strip()

                await repo.save_turn(
                    ConversationRecord(
                        bot_id=bot_id,
                        session_id=session_id,
                        chat_id=chat_id,
                        role="assistant",
                        content=final_text,
                        token_input=response.input_tokens,
                        token_output=response.output_tokens,
                    )
                )
                return final_text

            # Process tool calls
            # Add assistant response to messages
            messages.append({"role": "assistant", "content": response_text})

            # Save assistant tool request
            await repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="tool_use",
                    content=response_text,
                )
            )

            # Execute each tool call and collect results
            tool_results: list[str] = []
            for call_json in tool_calls:
                try:
                    call_data = json.loads(call_json)
                    tool_name = call_data.get("tool", "")
                    tool_input = call_data.get("input", {})

                    tool = self._tool_registry.get(tool_name)
                    if tool is None:
                        result = f"Error: unknown tool '{tool_name}'"
                    else:
                        logger.info("tool_execute", tool=tool_name)
                        result = await tool.execute(**tool_input)

                    tool_results.append(f"[Tool Result: {tool_name}]\n{result}")
                except (json.JSONDecodeError, Exception) as e:
                    tool_results.append(f"[Tool Error]\n{e}")

            # Build tool results message
            results_text = "\n\n".join(tool_results)

            # Save tool results
            await repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="tool_result",
                    content=results_text,
                )
            )

            # Add tool results as user message for next round
            messages.append({"role": "user", "content": results_text})
            rounds += 1

        return "[Tool execution limit reached]"


def _split_message(text: str, max_length: int = 4000) -> list[str]:
    """Split a message into chunks that fit within platform limits."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Try to split at a newline
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    return chunks
