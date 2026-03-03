"""File system exploration tool."""

from __future__ import annotations

import io
import mimetypes
import os
import zipfile
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
                    "enum": ["list", "read", "info", "search", "send_file", "compress"],
                    "description": (
                        "'list' = list directory contents, "
                        "'read' = read file content as text, "
                        "'info' = get file/directory metadata, "
                        "'search' = search for files by name pattern, "
                        "'send_file' = send a file to the user via messenger (supports any file type), "
                        "'compress' = compress file(s) or directory into a zip and send to user"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple file/directory paths (for 'compress' action). "
                                   "If provided, these are added to the zip archive.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (glob, for 'search' action). "
                                   "For 'compress', filters files in a directory by glob pattern.",
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
                case "send_file":
                    return self._send_file(path)
                case "compress":
                    paths = kwargs.get("paths")
                    pattern = kwargs.get("pattern")
                    return self._compress(path, extra_paths=paths, pattern=pattern)
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

    def _send_file(self, path: Path) -> str:
        """Read a file and queue it as an attachment to be sent to the user."""
        if not path.is_file():
            return f"Error: '{path}' is not a file"

        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"Error: file is too large ({_format_size(size)}). Max 50MB."

        try:
            data = path.read_bytes()
        except PermissionError:
            return f"Error: permission denied for '{path}'"

        media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        filename = path.name

        self.add_pending_image(data, media_type, filename)
        return f"File '{filename}' ({_format_size(size)}) queued for sending to user."

    def _compress(
        self,
        path: Path,
        extra_paths: list[str] | None = None,
        pattern: str | None = None,
    ) -> str:
        """Compress files/directories into a zip and queue for sending."""
        MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50MB

        # Collect all target paths
        targets: list[Path] = []
        if extra_paths:
            for p in extra_paths:
                targets.append(Path(p).resolve())
        else:
            targets.append(path)

        # Validate all targets exist
        for t in targets:
            if not t.exists():
                return f"Error: '{t}' does not exist"

        buf = io.BytesIO()
        file_count = 0
        try:
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for target in targets:
                    if target.is_file():
                        zf.write(target, target.name)
                        file_count += 1
                    elif target.is_dir():
                        for root, _dirs, files in os.walk(target):
                            for f in files:
                                fp = Path(root) / f
                                if pattern and not fp.match(pattern):
                                    continue
                                arcname = fp.relative_to(target.parent)
                                zf.write(fp, str(arcname))
                                file_count += 1
                    else:
                        return f"Error: '{target}' is not a file or directory"
        except PermissionError as e:
            return f"Error: permission denied - {e}"

        if file_count == 0:
            return "Error: no files matched for compression."

        zip_data = buf.getvalue()
        if len(zip_data) > MAX_ZIP_SIZE:
            return f"Error: resulting zip is too large ({_format_size(len(zip_data))}). Max 50MB."

        # Determine zip filename
        if len(targets) == 1:
            zip_name = targets[0].stem + ".zip"
        else:
            zip_name = "archive.zip"

        self.add_pending_image(zip_data, "application/zip", zip_name)
        return (
            f"Compressed {file_count} file(s) into '{zip_name}' "
            f"({_format_size(len(zip_data))}). Queued for sending to user."
        )

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
