"""AI client abstraction with Anthropic API and Claude Code CLI backends."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from panda_bot.config import AnthropicConfig, ClaudeCodeConfig
from panda_bot.log import get_logger

logger = get_logger(__name__)


@dataclass
class AIResponse:
    """Unified response from any AI backend."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = None  # Backend-specific raw response


class AIClient(ABC):
    """Abstract base class for AI backends."""

    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> AIResponse:
        """Send a conversation to the AI and return a response.

        For backends that handle tools internally (e.g. Claude Code CLI),
        the tools parameter may be ignored.
        """
        ...

    @property
    @abstractmethod
    def supports_tool_loop(self) -> bool:
        """Whether this backend requires the caller to run a tool execution loop.

        - True: Anthropic API style - returns tool_use blocks, caller must execute and re-send.
        - False: Claude Code CLI style - handles tools internally, returns final text.
        """
        ...


class AnthropicClient(AIClient):
    """Anthropic API backend using the official SDK."""

    def __init__(self, config: AnthropicConfig):
        import anthropic

        self._client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=config.max_retries,
            timeout=config.timeout,
        )

    @property
    def supports_tool_loop(self) -> bool:
        return True

    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> AIResponse:
        """Send messages to the Anthropic API. Returns raw Message for tool_runner."""
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        logger.debug("api_request", model=model, message_count=len(messages))
        response = await self._client.messages.create(**kwargs)
        logger.debug(
            "api_response",
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
        )
        return AIResponse(
            text="",  # Text extracted by tool_runner from raw response
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw=response,
        )

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> Any:
        """Legacy method used by tool_runner. Returns the raw Anthropic Message."""
        response = await self.chat(
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        )
        return response.raw


class ClaudeCodeClient(AIClient):
    """Claude Code CLI backend using subprocess."""

    def __init__(self, config: ClaudeCodeConfig):
        self._cli_path = self._resolve_cli_path(config.cli_path)
        self._timeout = config.timeout
        self._allowed_tools = config.allowed_tools

    @staticmethod
    def _resolve_cli_path(cli_path: str) -> str:
        """Resolve the claude CLI path, checking common install locations."""
        # If it's an absolute path, use as-is
        if os.path.isabs(cli_path) and os.path.exists(cli_path):
            return cli_path

        # Try shutil.which first (searches PATH)
        found = shutil.which(cli_path)
        if found:
            return found

        # On Windows, check common npm global locations
        if platform.system() == "Windows":
            candidates = []
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                candidates.append(os.path.join(appdata, "npm", "claude.cmd"))
                candidates.append(os.path.join(appdata, "npm", "claude"))
            # Also check LOCALAPPDATA for newer npm versions
            localappdata = os.environ.get("LOCALAPPDATA", "")
            if localappdata:
                candidates.append(os.path.join(localappdata, "npm", "claude.cmd"))
            for candidate in candidates:
                if os.path.exists(candidate):
                    return candidate

        # Return original path as fallback
        return cli_path

    @property
    def supports_tool_loop(self) -> bool:
        return False

    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> AIResponse:
        """Send a conversation to Claude Code CLI and return the final response."""
        # Build the prompt from conversation history
        prompt = self._build_prompt(system, messages)

        # Build command - pipe prompt via stdin to avoid Windows encoding issues
        cmd = [self._cli_path, "-p", "--output-format", "json"]

        # Add allowed tools
        if self._allowed_tools:
            for tool_name in self._allowed_tools:
                cmd.extend(["--allowedTools", tool_name])

        logger.info("claude_code_request", cli_path=self._cli_path, prompt_length=len(prompt))

        try:
            # Remove ANTHROPIC_API_KEY from subprocess env so CLI uses subscription auth
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode("utf-8")),
                timeout=self._timeout,
            )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                # Show both stdout and stderr for debugging
                error_detail = stderr_text or stdout_text or "(no output)"
                logger.error(
                    "claude_code_error",
                    returncode=process.returncode,
                    stderr=stderr_text,
                    stdout=stdout_text[:500],
                )
                return AIResponse(text=f"Claude Code error (exit {process.returncode}): {error_detail}")

            return self._parse_response(stdout_text)

        except asyncio.TimeoutError:
            logger.error("claude_code_timeout", timeout=self._timeout)
            return AIResponse(text=f"Claude Code timed out after {self._timeout} seconds.")
        except FileNotFoundError:
            logger.error("claude_code_not_found", cli_path=self._cli_path)
            return AIResponse(
                text=f"Claude Code CLI not found at '{self._cli_path}'. "
                "Install it with: npm install -g @anthropic-ai/claude-code"
            )

    def _build_prompt(self, system: str, messages: list[dict[str, Any]]) -> str:
        """Convert system prompt and message history into a single prompt string."""
        parts: list[str] = []

        if system:
            parts.append(f"[System Instructions]\n{system}\n")

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if isinstance(content, str):
                if role == "user":
                    parts.append(f"[User]\n{content}")
                elif role == "assistant":
                    parts.append(f"[Assistant]\n{content}")
            elif isinstance(content, list):
                # Handle structured content blocks (tool_use results etc.)
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(f"[{role.title()}]\n{block['text']}")
                        elif block.get("type") == "tool_result":
                            parts.append(f"[Tool Result]\n{block.get('content', '')}")

        return "\n\n".join(parts)

    def _parse_response(self, output: str) -> AIResponse:
        """Parse Claude Code CLI JSON output."""
        try:
            data = json.loads(output)

            # Claude Code JSON output format: {"result": "...", "cost_usd": ..., ...}
            if isinstance(data, dict):
                text = data.get("result", "")
                # Try to extract token usage if available
                input_tokens = data.get("input_tokens", 0)
                output_tokens = data.get("output_tokens", 0)
                return AIResponse(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    raw=data,
                )
            # If it's a list (stream format), concatenate text results
            elif isinstance(data, list):
                texts = []
                for item in data:
                    if isinstance(item, dict) and item.get("type") == "result":
                        texts.append(item.get("result", ""))
                return AIResponse(text="\n".join(texts) if texts else str(data))

        except json.JSONDecodeError:
            # Plain text output
            pass

        return AIResponse(text=output)
