from __future__ import annotations

import difflib
import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from ..models import ToolResult
from .base import Tool
from .paths import (
    IGNORED_NAMES,
    _is_link,
    is_protected,
    is_sensitive,
    relative_display,
    resolve_workspace_path,
)

MAX_FILE_BYTES = 1_000_000
MAX_WRITE_CHARS = 1_000_000
MAX_LIST_ENTRIES = 500
MAX_LIST_CHARS = 60_000
MAX_WALK_ENTRIES = 5_000
MAX_DIFF_CHARS = 4_000


def _atomic_replace(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _atomic_create(path: Path, content: str) -> None:
    """Publish a completed temporary file with a no-clobber hard-link operation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        # link() fails atomically if path was created after validation; unlike
        # O_EXCL direct writing it never exposes a partially-written target.
        os.link(temporary, path)
    except FileExistsError:
        raise FileExistsError(
            "file already exists; use apply_patch or explicitly set overwrite=true"
        ) from None
    except BaseException:
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_text(path: Path) -> str:
    if not path.is_file() or _is_link(path):
        raise ValueError("path is not a regular file")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds the {MAX_FILE_BYTES} byte read limit")
    if b"\x00" in data[:4096]:
        raise ValueError("binary files are not supported")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8 text") from exc


def _safe_walk(root: Path):
    """Yield a bounded tree while never descending into protected/link nodes."""
    seen = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_directories = [
            name
            for name in sorted(directories)
            if name not in IGNORED_NAMES
            and not is_sensitive(current_path / name)
            and not is_protected(current_path / name)
            and not _is_link(current_path / name)
        ]
        directories[:] = safe_directories
        safe_files = [
            name
            for name in sorted(files)
            if not is_sensitive(current_path / name)
            and not is_protected(current_path / name)
            and not _is_link(current_path / name)
        ]
        seen += len(safe_directories) + len(safe_files)
        if seen > MAX_WALK_ENTRIES:
            yield current_path, [], [], True
            return
        # ``directories`` is the list used by os.walk; callers may prune it
        # (for example, to honor list_files max_depth).
        yield current_path, directories, safe_files, False


class ListFilesTool(Tool):
    name = "list_files"
    description = "List safe workspace files under a bounded recursion depth."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "max_depth": {"type": "integer", "minimum": 0, "maximum": 6, "default": 3},
        },
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        root = resolve_workspace_path(self.workspace, arguments.get("path", "."), must_exist=True)
        if not root.is_dir() or _is_link(root):
            raise ValueError("path is not a regular directory")
        depth_limit = int(arguments.get("max_depth", 3))
        if not 0 <= depth_limit <= 6:
            raise ValueError("max_depth must be between 0 and 6")
        output: list[str] = []
        output_chars = 0
        for current_path, directories, files, truncated in _safe_walk(root):
            if truncated:
                output.append("... traversal truncated after 5000 entries")
                break
            if len(current_path.relative_to(root).parts) >= depth_limit:
                directories[:] = []
            for name in files:
                line = relative_display(current_path / name, self.workspace)
                if len(output) >= MAX_LIST_ENTRIES or output_chars + len(line) + 1 > MAX_LIST_CHARS:
                    output.append("... output truncated")
                    return ToolResult(True, "\n".join(output))
                output.append(line)
                output_chars += len(line) + 1
        return ToolResult(True, "\n".join(output) or "(directory is empty)")


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a bounded UTF-8 text file by inclusive line range."
    parameters: ClassVar[dict[str, Any]] = {
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
        content = "\n".join(
            f"{number}: {line}" for number, line in enumerate(lines[start - 1 : end], start)
        )
        if len(content) > MAX_LIST_CHARS:
            content = content[:MAX_LIST_CHARS] + "\n... output truncated"
        return ToolResult(True, content or "(requested range is empty)")


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create a bounded UTF-8 text file. Existing files require overwrite=true."
    parameters: ClassVar[dict[str, Any]] = {
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
        content = arguments["content"]
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        if len(content) > MAX_WRITE_CHARS:
            raise ValueError(f"content exceeds the {MAX_WRITE_CHARS} character write limit")
        existed = path.exists()
        if existed:
            if _is_link(path):
                raise PermissionError("refusing to overwrite a link")
            if not arguments.get("overwrite", False):
                raise FileExistsError(
                    "file already exists; use apply_patch or explicitly set overwrite=true"
                )
            _atomic_replace(path, content)
        else:
            _atomic_create(path, content)
        verb = "Updated" if existed else "Created"
        return ToolResult(
            True, f"{verb} {relative_display(path, self.workspace)} ({len(content)} chars)"
        )


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = "Replace one exact, uniquely occurring text block in an existing UTF-8 file."
    parameters: ClassVar[dict[str, Any]] = {
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
        old_text, new_text = arguments["old_text"], arguments["new_text"]
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text must be a non-empty string")
        if not isinstance(new_text, str):
            raise TypeError("new_text must be a string")
        if len(old_text) + len(new_text) > MAX_WRITE_CHARS:
            raise ValueError("patch text exceeds the write limit")
        content = _read_text(path)
        occurrences = content.count(old_text)
        if occurrences != 1:
            raise ValueError(f"old_text must occur exactly once; found {occurrences}")
        updated = content.replace(old_text, new_text, 1)
        if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"patched file would exceed the {MAX_FILE_BYTES} byte write limit")
        _atomic_replace(path, updated)
        diff = "".join(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=relative_display(path, self.workspace),
                tofile=relative_display(path, self.workspace),
                n=2,
            )
        )
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + "\n... diff truncated\n"
        summary = f"Patched {relative_display(path, self.workspace)} (1 exact replacement)"
        return ToolResult(True, f"{summary}\n{diff}" if diff else summary)
