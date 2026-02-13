"""File system exploration tool."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from panda_bot.ai.tools.base import Tool


class FileSystemTool(Tool):
    """Tool for exploring the file system: listing directories, reading files, searching."""

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return (
            "Explore the file system. List directory contents, read file contents, "
            "get file info, or search for files by name pattern."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "read", "info", "search"],
                    "description": (
                        "'list' = list directory contents, "
                        "'read' = read file content, "
                        "'info' = get file/directory metadata, "
                        "'search' = search for files by name pattern"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path",
                },
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (glob, for 'search' action)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth for search (default: 3)",
                },
            },
            "required": ["action", "path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "list")
        path_str = kwargs.get("path", ".")

        try:
            path = Path(path_str).resolve()

            match action:
                case "list":
                    return self._list_dir(path)
                case "read":
                    return self._read_file(path)
                case "info":
                    return self._file_info(path)
                case "search":
                    pattern = kwargs.get("pattern", "*")
                    max_depth = kwargs.get("max_depth", 3)
                    return self._search(path, pattern, max_depth)
                case _:
                    return f"Error: unknown action '{action}'"
        except PermissionError:
            return f"Error: permission denied for '{path_str}'"
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _list_dir(path: Path) -> str:
        if not path.is_dir():
            return f"Error: '{path}' is not a directory"

        entries = []
        for entry in sorted(path.iterdir()):
            entry_type = "DIR" if entry.is_dir() else "FILE"
            size = ""
            if entry.is_file():
                size = f" ({_format_size(entry.stat().st_size)})"
            entries.append(f"  [{entry_type}] {entry.name}{size}")

        if not entries:
            return f"Directory '{path}' is empty."

        return f"Contents of {path}:\n" + "\n".join(entries)

    @staticmethod
    def _read_file(path: Path) -> str:
        if not path.is_file():
            return f"Error: '{path}' is not a file"

        size = path.stat().st_size
        if size > 500_000:
            return f"Error: file is too large ({_format_size(size)}). Max 500KB."

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: '{path}' is a binary file and cannot be read as text."

        return content

    @staticmethod
    def _file_info(path: Path) -> str:
        if not path.exists():
            return f"Error: '{path}' does not exist"

        stat = path.stat()
        info_lines = [
            f"Path: {path}",
            f"Type: {'directory' if path.is_dir() else 'file'}",
            f"Size: {_format_size(stat.st_size)}",
            f"Modified: {stat.st_mtime}",
            f"Permissions: {oct(stat.st_mode)}",
        ]
        return "\n".join(info_lines)

    @staticmethod
    def _search(path: Path, pattern: str, max_depth: int) -> str:
        if not path.is_dir():
            return f"Error: '{path}' is not a directory"

        results = []
        for root, dirs, files in os.walk(path):
            depth = Path(root).relative_to(path).parts
            if len(depth) >= max_depth:
                dirs.clear()
                continue

            root_path = Path(root)
            for f in files:
                if root_path.joinpath(f).match(pattern):
                    results.append(str(root_path / f))
                    if len(results) >= 50:
                        results.append("... (truncated at 50 results)")
                        return "\n".join(results)

        if not results:
            return f"No files matching '{pattern}' found in '{path}'."

        return "\n".join(results)


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024  # type: ignore[assignment]
    return f"{size:.1f}TB"
