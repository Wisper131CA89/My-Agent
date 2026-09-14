from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from ..models import ToolResult
from .base import Tool
from .paths import IGNORED_NAMES, relative_display, resolve_workspace_path


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError("path is not a file")
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ValueError("binary files are not supported")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8 text") from exc


class ListFilesTool(Tool):
    name = "list_files"
    description = "List files under a workspace directory with a bounded recursion depth."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "max_depth": {"type": "integer", "minimum": 0, "maximum": 6, "default": 3},
        },
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        root = resolve_workspace_path(self.workspace, arguments.get("path", "."), must_exist=True)
        if not root.is_dir():
            raise ValueError("path is not a directory")
        depth_limit = int(arguments.get("max_depth", 3))
        if not 0 <= depth_limit <= 6:
            raise ValueError("max_depth must be between 0 and 6")

        output: list[str] = []
        for current, directories, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.relative_to(root).parts)
            directories[:] = sorted(name for name in directories if name not in IGNORED_NAMES)
            if depth >= depth_limit:
                directories[:] = []
            for name in sorted(files):
                output.append(relative_display(current_path / name, self.workspace))
                if len(output) >= 500:
                    output.append("... output truncated after 500 files")
                    return ToolResult(True, "\n".join(output))
        return ToolResult(True, "\n".join(output) or "(directory is empty)")


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file by inclusive line range."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = resolve_workspace_path(self.workspace, arguments["path"], must_exist=True)
        lines = _read_text(path).splitlines()
        start = int(arguments.get("start_line", 1))
        end = int(arguments.get("end_line", min(start + 399, max(len(lines), 1))))
        if start < 1 or end < start or end - start + 1 > 400:
            raise ValueError("request an inclusive range of at most 400 lines")
        selected = lines[start - 1 : end]
        content = "\n".join(f"{number}: {line}" for number, line in enumerate(selected, start))
        return ToolResult(True, content or "(requested range is empty)")


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create a UTF-8 text file. Existing files require overwrite=true."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = resolve_workspace_path(self.workspace, arguments["path"], must_exist=False)
        existed = path.exists()
        if existed and not arguments.get("overwrite", False):
            raise FileExistsError("file already exists; use apply_patch or explicitly set overwrite=true")
        content = arguments["content"]
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        _atomic_write(path, content)
        verb = "Updated" if existed else "Created"
        return ToolResult(True, f"{verb} {relative_display(path, self.workspace)} ({len(content)} chars)")


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = "Replace one exact, uniquely occurring text block in an existing UTF-8 file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = resolve_workspace_path(self.workspace, arguments["path"], must_exist=True)
        old_text = arguments["old_text"]
        new_text = arguments["new_text"]
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a non-empty string")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string")
        content = _read_text(path)
        occurrences = content.count(old_text)
        if occurrences != 1:
            raise ValueError(f"old_text must occur exactly once; found {occurrences}")
        _atomic_write(path, content.replace(old_text, new_text, 1))
        return ToolResult(True, f"Patched {relative_display(path, self.workspace)}")
