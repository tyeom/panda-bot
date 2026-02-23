"""MCP (Model Context Protocol) server manager using Claude Code CLI.

Registers MCP servers via ``claude mcp add/remove -s user`` so the CLI
natively manages them.  A local JSON file tracks which servers were added
by panda-bot so they can be listed / cleaned up independently.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from panda_bot.log import get_logger

logger = get_logger(__name__)


class McpManager:
    """Manages external MCP server registrations through the Claude Code CLI.

    Workflow:
      1. ``add_server`` runs ``claude mcp add -s user ...`` to register globally.
      2. Server metadata is saved to a local JSON tracking file.
      3. ``remove_server`` runs ``claude mcp remove -s user ...`` and deletes
         the tracking entry.
      4. On startup the tracking file is loaded so ``list_servers`` works
         without shelling out.
    """

    def __init__(self, config_path: Path, cli_path: str = "claude") -> None:
        self._config_path = config_path
        self._cli_path = self._resolve_cli(cli_path)
        self._servers: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _resolve_cli(cli_path: str) -> str:
        found = shutil.which(cli_path)
        return found or cli_path

    # ── persistence ─────────────────────────────────────────────

    def _load(self) -> None:
        if self._config_path.exists():
            try:
                self._servers = json.loads(self._config_path.read_text(encoding="utf-8"))
                logger.info("mcp_config_loaded", count=len(self._servers))
            except (json.JSONDecodeError, OSError) as e:
                logger.error("mcp_config_load_error", error=str(e))
                self._servers = {}

    def _save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(self._servers, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── public API ──────────────────────────────────────────────

    async def add_server(
        self,
        name: str,
        package: str,
        env: dict[str, str] | None = None,
    ) -> str:
        """Register an MCP server via the Claude CLI and track it locally."""
        cmd = [self._cli_path, "mcp", "add", "-s", "user", name]
        if env:
            for key, val in env.items():
                cmd.extend(["-e", f"{key}={val}"])
        cmd.extend(["--", "npx", "-y", package])

        ok, output = await self._run(cmd)
        if not ok:
            return f"Failed to add MCP server '{name}': {output}"

        self._servers[name] = {"package": package}
        if env:
            self._servers[name]["env"] = env
        self._save()
        logger.info("mcp_server_added", name=name, package=package)
        return f"MCP server '{name}' added.\n{output}"

    async def remove_server(self, name: str) -> str:
        """Unregister an MCP server from the Claude CLI and remove tracking."""
        if name not in self._servers:
            return f"MCP server '{name}' not found."

        cmd = [self._cli_path, "mcp", "remove", "-s", "user", name]
        ok, output = await self._run(cmd)
        if not ok:
            return f"Failed to remove MCP server '{name}': {output}"

        del self._servers[name]
        self._save()
        logger.info("mcp_server_removed", name=name)
        return f"MCP server '{name}' removed."

    def list_servers(self) -> str:
        if not self._servers:
            return "No MCP servers configured."
        lines: list[str] = []
        for name, cfg in self._servers.items():
            pkg = cfg.get("package", "?")
            env_keys = ", ".join(cfg.get("env", {}).keys())
            env_info = f" (env: {env_keys})" if env_keys else ""
            lines.append(f"- {name}: {pkg}{env_info}")
        return "\n".join(lines)

    async def ensure_servers(self) -> None:
        """Re-register all tracked servers on startup (idempotent)."""
        if not self._servers:
            return
        for name, cfg in list(self._servers.items()):
            package = cfg.get("package", "")
            if not package:
                continue
            env = cfg.get("env")
            cmd = [self._cli_path, "mcp", "add", "-s", "user", name]
            if env:
                for key, val in env.items():
                    cmd.extend(["-e", f"{key}={val}"])
            cmd.extend(["--", "npx", "-y", package])
            ok, output = await self._run(cmd)
            if ok:
                logger.info("mcp_server_ensured", name=name)
            else:
                logger.warning("mcp_server_ensure_failed", name=name, output=output)

    # ── helpers ─────────────────────────────────────────────────

    async def _run(self, cmd: list[str]) -> tuple[bool, str]:
        """Run a CLI command and return (success, output)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = (stdout or b"").decode("utf-8", errors="replace").strip()
            err = (stderr or b"").decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                return False, err or out
            return True, out or err
        except asyncio.TimeoutError:
            return False, "Command timed out."
        except FileNotFoundError:
            return False, f"CLI not found: {self._cli_path}"
