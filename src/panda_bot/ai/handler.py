"""Message handler: receives incoming messages, calls Claude, sends responses."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
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
from panda_bot.messenger.models import Attachment, IncomingMessage, OutgoingMessage
from panda_bot.services.mcp_manager import McpManager
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
        "",
        "=== CRITICAL: CUSTOM TOOL SYSTEM ===",
        "",
        "You have access to CUSTOM tools provided by the panda-bot platform.",
        "These tools give you capabilities like controlling a REAL browser (Playwright),",
        "scheduling tasks, and managing files.",
        "",
        "IMPORTANT RULES:",
        "1. For web browsing tasks (scraping, form filling, clicking, dynamic pages),",
        "   you MUST use the 'browser' tool below. It controls a real Playwright browser",
        "   that can handle JavaScript, dynamic content, and user interactions.",
        "   Do NOT use WebFetch for dynamic or interactive websites.",
        "2. For scheduling recurring tasks, you MUST use the 'scheduler' tool below.",
        "3. To use a tool, output EXACTLY this XML format in your response:",
        "",
        "<tool_call>",
        '{"tool": "tool_name", "input": {"param1": "value1"}}',
        "</tool_call>",
        "",
        "4. After outputting <tool_call> tags, STOP and wait. The system will execute",
        "   the tool and send you the results. Then you can continue.",
        "5. You can use multiple <tool_call> blocks in one response.",
        "6. When you have the final answer, respond with plain text (no <tool_call> tags).",
        "",
        "Available custom tools:",
    ]
    for tool in tools:
        schema = tool.input_schema
        props = schema.get("properties", {})
        lines.append(f"\n### {tool.name}")
        lines.append(f"Description: {tool.description}")
        lines.append("Parameters:")
        for k, v in props.items():
            desc = v.get("description", "")
            ptype = v.get("type", "string")
            enum = v.get("enum", [])
            enum_str = f" (values: {', '.join(enum)})" if enum else ""
            lines.append(f"  - {k} ({ptype}{enum_str}): {desc}")
        required = schema.get("required", [])
        if required:
            lines.append(f"Required: {', '.join(required)}")

    lines.extend([
        "",
        "=== BROWSER SESSION INFO ===",
        "The browser tool maintains a PERSISTENT SESSION across calls.",
        "Cookies, localStorage, and sessionStorage are preserved between actions.",
        "This means you can log in to a website and then access authenticated pages",
        "in subsequent calls without logging in again.",
        "If 'url' is omitted, the action operates on the current page.",
        "Use 'clear_session' to reset all session data when needed.",
        "",
        "=== EXAMPLES ===",
        "",
        "Example 1: Simple page read",
        "User: 'Show me the content of https://example.com'",
        "You should respond with:",
        '<tool_call>',
        '{"tool": "browser", "input": {"action": "open", "url": "https://example.com"}}',
        '</tool_call>',
        "",
        "Example 2: Login workflow (session is maintained across calls)",
        "User: 'Log in to example.com and get my dashboard info'",
        "Step 1 - open the login page:",
        '<tool_call>',
        '{"tool": "browser", "input": {"action": "open", "url": "https://example.com/login"}}',
        '</tool_call>',
        "Step 2 - fill username:",
        '<tool_call>',
        '{"tool": "browser", "input": {"action": "fill", "selector": "#username", "value": "user"}}',
        '</tool_call>',
        "Step 3 - fill password:",
        '<tool_call>',
        '{"tool": "browser", "input": {"action": "fill", "selector": "#password", "value": "pass"}}',
        '</tool_call>',
        "Step 4 - click login button:",
        '<tool_call>',
        '{"tool": "browser", "input": {"action": "click", "selector": "#login-btn"}}',
        '</tool_call>',
        "Step 5 - access authenticated page (session cookies are preserved):",
        '<tool_call>',
        '{"tool": "browser", "input": {"action": "open", "url": "https://example.com/dashboard"}}',
        '</tool_call>',
        "",
        "Example 3: Scheduling",
        "User: 'Check my email every 5 minutes'",
        "You should respond with:",
        '<tool_call>',
        '{"tool": "scheduler", "input": {"action": "add_cron", "cron_expr": "*/5 * * * *", "task_prompt": "Check email and summarize new messages"}}',
        '</tool_call>',
        "",
        "User: 'Send me a test alert in 5 minutes'",
        "You should respond with:",
        '<tool_call>',
        '{"tool": "scheduler", "input": {"action": "add_once", "run_at": "2025-01-15T14:35:00", "task_prompt": "Send: test alert!"}}',
        '</tool_call>',
        "=== END TOOL SYSTEM ===",
    ])

    return "\n".join(lines)


def _build_tool_reminder(tools: list[Tool]) -> str:
    """Build a short reminder about available tools to append to user messages."""
    if not tools:
        return ""
    names = ", ".join(t.name for t in tools)
    return (
        f"\n\n[SYSTEM OVERRIDE: You HAVE the following custom tools: {names}. "
        "You MUST use them when the user's request matches their capabilities. "
        "If you previously said you don't have these capabilities, that was WRONG - "
        "you DO have them now. "
        "For web browsing/scraping → use 'browser' tool. "
        "For scheduling/alarms/recurring tasks → use 'scheduler' tool. "
        "For file operations → use 'filesystem' tool. "
        "Output <tool_call> tags to invoke them. "
        "NEVER say you cannot schedule, browse, or use tools.]"
    )


class MessageHandler:
    """Handles the full flow: message -> session -> history -> Claude -> tools -> response."""

    def __init__(
        self,
        adapter: MessengerAdapter,
        ai_client: AIClient,
        session_manager: SessionManager,
        tool_registry: ToolRegistry,
        bot_config: BotConfig,
        mcp_manager: McpManager | None = None,
    ):
        self._adapter = adapter
        self._ai_client = ai_client
        self._session_manager = session_manager
        self._tool_registry = tool_registry
        self._bot_config = bot_config
        self._mcp_manager = mcp_manager
        self._running_tasks: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}

    async def handle(self, message: IncomingMessage) -> None:
        """Process an incoming message end-to-end."""
        bot_id = message.bot_id
        chat_id = message.chat_id
        text = message.text.strip()
        attachments = message.attachments

        if not text and not attachments:
            return

        # When image is sent without text, use placeholder
        if not text and attachments:
            text = "[Image]"

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

        if text.lower() == "/stop":
            task_info = self._running_tasks.get(chat_id)
            if task_info:
                task, cancel_event = task_info
                cancel_event.set()
                if not task.done():
                    task.cancel()
                await self._adapter.send_message(
                    OutgoingMessage(chat_id=chat_id, text="작업이 중단되었습니다.")
                )
            else:
                await self._adapter.send_message(
                    OutgoingMessage(chat_id=chat_id, text="진행 중인 작업이 없습니다.")
                )
            return

        if text.lower().startswith("/mcp"):
            await self._handle_mcp_command(chat_id, text)
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

        # Save user message (prefix with [Image] if attachment present)
        save_text = f"[Image] {text}" if attachments and not text.startswith("[Image]") else text
        await repo.save_turn(
            ConversationRecord(
                bot_id=bot_id,
                session_id=session_id,
                chat_id=chat_id,
                role="user",
                content=save_text,
            )
        )

        # Load conversation history
        history = await repo.get_session_history(bot_id, session_id)
        messages = build_messages(history, current_attachments=attachments or None)

        ai_config = self._bot_config.ai

        # Process AI and respond (fire-and-forget so /stop can execute immediately)
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            self._process_and_respond(
                bot_id, chat_id, session_id, messages, ai_config, attachments,
                cancel_event,
            )
        )
        self._running_tasks[chat_id] = (task, cancel_event)

        def _on_task_done(t: asyncio.Task) -> None:
            self._running_tasks.pop(chat_id, None)
            if t.cancelled():
                logger.info("task_cancelled_by_user", bot_id=bot_id, chat_id=chat_id)
            elif t.exception():
                logger.error("task_unhandled_error", bot_id=bot_id, error=str(t.exception()))

        task.add_done_callback(_on_task_done)

    async def _process_and_respond(
        self,
        bot_id: str,
        chat_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
        ai_config: Any,
        attachments: list[Attachment] | None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        """Run AI processing and send response. Supports cancellation via cancel_event."""
        repo = self._session_manager.repo

        # Set conversation context on scheduler tool so it knows which chat to target
        scheduler_tool = self._tool_registry.get("scheduler")
        if scheduler_tool and hasattr(scheduler_tool, "set_context"):
            scheduler_tool.set_context(bot_id=bot_id, chat_id=chat_id)

        response_text = ""
        try:
            if cancel_event and cancel_event.is_set():
                return

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
                    cancel_event=cancel_event,
                )
            else:
                # Claude Code CLI: use text-based tool loop with panda-bot tools
                # CLI doesn't support vision — save images as temp files and reference paths
                img_refs: list[str] = []
                if attachments:
                    import tempfile
                    import os

                    for att in attachments:
                        ext = att.media_type.split("/")[-1] if "/" in att.media_type else "bin"
                        tmp = tempfile.NamedTemporaryFile(
                            suffix=f".{ext}", prefix="panda_img_", delete=False
                        )
                        tmp.write(att.data)
                        tmp.close()
                        img_refs.append(tmp.name)

                    # Append file paths to last user message so CLI can reference them
                    paths_note = "\n[Attached images saved to: " + ", ".join(img_refs) + "]"
                    for m in reversed(messages):
                        if m.get("role") == "user" and isinstance(m.get("content"), str):
                            m["content"] += paths_note
                            break

                try:
                    tools = self._tool_registry.get_tools_by_names(ai_config.tools)
                    response_text = await self._run_claude_code_tool_loop(
                        messages=messages,
                        system=ai_config.system_prompt,
                        tools=tools,
                        bot_id=bot_id,
                        session_id=session_id,
                        chat_id=chat_id,
                        cancel_event=cancel_event,
                    )
                finally:
                    # Clean up temp files even on cancellation
                    for path in img_refs:
                        try:
                            import os
                            os.unlink(path)
                        except OSError:
                            pass

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("ai_error", bot_id=bot_id, error=str(e))
            response_text = f"An error occurred: {e}"

        # Collect pending images from tools
        pending_images: list[Attachment] = []
        for tool in self._tool_registry.get_tools_by_names(ai_config.tools):
            pending_images.extend(tool.take_pending_images())

        # Send response (split long messages)
        for chunk in _split_message(response_text, max_length=4000):
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text=chunk)
            )

        # Send pending images (e.g. screenshots) to user
        if pending_images:
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text="", attachments=pending_images)
            )

    async def _handle_mcp_command(self, chat_id: str, text: str) -> None:
        """Handle /mcp subcommands: list, add, remove."""
        if not self._mcp_manager:
            await self._adapter.send_message(
                OutgoingMessage(chat_id=chat_id, text="MCP manager is not configured.")
            )
            return

        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()
        sub = parts[1].lower() if len(parts) > 1 else ""

        if sub == "list":
            result = self._mcp_manager.list_servers()
        elif sub == "remove" and len(parts) > 2:
            result = await self._mcp_manager.remove_server(parts[2])
        elif sub == "add" and len(parts) > 3:
            # /mcp add <name> <package> [-e KEY=VAL ...]
            name = parts[2]
            package = parts[3]
            env = self._parse_mcp_env(parts[4:])
            result = await self._mcp_manager.add_server(
                name=name,
                package=package,
                env=env or None,
            )
        else:
            result = (
                "Usage:\n"
                "  /mcp list\n"
                "  /mcp add <name> <package> -e KEY=VAL\n"
                "  /mcp remove <name>\n"
                "\n"
                "Example (Notion MCP):\n"
                '  /mcp add notionApi @notionhq/notion-mcp-server -e OPENAPI_MCP_HEADERS=\'{"Authorization": "Bearer ntn_xxx", "Notion-Version": "2022-06-28"}\''
            )

        await self._adapter.send_message(
            OutgoingMessage(chat_id=chat_id, text=result)
        )

    @staticmethod
    def _parse_mcp_env(tokens: list[str]) -> dict[str, str]:
        """Parse -e KEY=VAL pairs from tokens (already split by shlex)."""
        env: dict[str, str] = {}
        i = 0
        while i < len(tokens):
            if tokens[i] == "-e" and i + 1 < len(tokens):
                i += 1
                kv = tokens[i]
                eq_idx = kv.find("=")
                if eq_idx > 0:
                    env[kv[:eq_idx]] = kv[eq_idx + 1:]
            i += 1
        return env

    async def _run_claude_code_tool_loop(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        bot_id: str,
        session_id: str,
        chat_id: str,
        cancel_event: asyncio.Event | None = None,
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
        tool_reminder = _build_tool_reminder(tools) if tools else ""
        logger.info(
            "claude_code_tool_loop",
            tool_count=len(tools),
            tool_names=[t.name for t in tools],
            system_length=len(full_system),
        )

        # Work on a copy to avoid mutating originals
        if tool_reminder and messages:
            messages = [m.copy() for m in messages]

            # Sanitize prior assistant messages that wrongly refused tool usage
            refusal_phrases = [
                "기능이 없", "할 수 없", "할 수가 없", "못 해", "못해",
                "지원하지 않", "불가능", "불가합니다",
                "I can't", "I cannot", "I don't have", "I'm not able",
                "no capability", "not supported",
            ]
            for i, msg in enumerate(messages):
                if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                    content = msg["content"]
                    if any(phrase in content for phrase in refusal_phrases):
                        messages[i]["content"] = (
                            "[Note: This previous response was incorrect. "
                            "Tools ARE available now. Ignore this response.]"
                        )

            # Append tool reminder to the last user message
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user" and isinstance(messages[i].get("content"), str):
                    messages[i]["content"] += tool_reminder
                    break

        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            # Check for cancellation at each iteration
            if cancel_event and cancel_event.is_set():
                logger.info("tool_loop_cancelled", bot_id=bot_id, round=rounds)
                return "[작업이 중단되었습니다]"

            response = await self._ai_client.chat(
                system=full_system,
                messages=messages,
            )

            # Check again after CLI call returns (cancel may have arrived during wait)
            if cancel_event and cancel_event.is_set():
                logger.info("tool_loop_cancelled_after_chat", bot_id=bot_id, round=rounds)
                return "[작업이 중단되었습니다]"

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

            # Save assistant tool request as regular assistant message
            # (tool_use/tool_result roles are for Anthropic API backend only)
            await repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="assistant",
                    content=response_text,
                )
            )

            # Execute each tool call and collect results
            tool_results: list[str] = []
            for call_json in tool_calls:
                # Check for cancellation before each tool execution
                if cancel_event and cancel_event.is_set():
                    logger.info("tool_execution_cancelled", bot_id=bot_id)
                    return "[작업이 중단되었습니다]"

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
                except asyncio.CancelledError:
                    logger.info("tool_execution_cancelled", bot_id=bot_id, tool=tool_name)
                    return "[작업이 중단되었습니다]"
                except (json.JSONDecodeError, Exception) as e:
                    tool_results.append(f"[Tool Error]\n{e}")

            # Build tool results message
            results_text = "\n\n".join(tool_results)

            # Save tool results as regular user message
            # (tool_use/tool_result roles are for Anthropic API backend only)
            await repo.save_turn(
                ConversationRecord(
                    bot_id=bot_id,
                    session_id=session_id,
                    chat_id=chat_id,
                    role="user",
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
