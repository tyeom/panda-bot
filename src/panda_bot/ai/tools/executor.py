"""File/command execution tool."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any

from panda_bot.ai.tools.base import Tool


class ExecutorTool(Tool):
    """Tool for executing files and commands."""

    @property
    def name(self) -> str:
        return "executor"

    @property
    def description(self) -> str:
        return (
            "Execute a file or shell command. Can run scripts, programs, "
            "and shell commands. Returns stdout and stderr output."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command or file path to execute",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments to pass to the command",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for execution (default: current directory)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30, max: 300)",
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> str:
        command = kwargs.get("command", "")
        args = kwargs.get("args", [])
        cwd = kwargs.get("cwd")
        timeout = min(kwargs.get("timeout", 30), 300)

        if not command:
            return "Error: command is required"

        try:
            # Build the full command
            if args:
                full_cmd = f"{command} {' '.join(shlex.quote(a) for a in args)}"
            else:
                full_cmd = command

            process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return f"Error: command timed out after {timeout} seconds"

            output_parts = []
            if stdout:
                stdout_text = stdout.decode("utf-8", errors="replace")[:20000]
                output_parts.append(f"STDOUT:\n{stdout_text}")
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")[:5000]
                output_parts.append(f"STDERR:\n{stderr_text}")

            exit_info = f"Exit code: {process.returncode}"
            output_parts.append(exit_info)

            return "\n\n".join(output_parts) if output_parts else "Command completed with no output."

        except Exception as e:
            return f"Execution error: {e}"
