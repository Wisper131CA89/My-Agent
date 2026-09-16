from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, ClassVar

from ..models import ToolResult
from .base import Tool
from .filesystem import MAX_WALK_ENTRIES, _read_text, _safe_walk
from .paths import _is_link, is_protected, is_sensitive, relative_display, resolve_workspace_path

MAX_MATCHES = 200
MAX_OUTPUT_CHARS = 60_000
MAX_QUERY_CHARS = 1_000


class SearchTextTool(Tool):
    name = "search_text"
    description = "Search safe, bounded UTF-8 text files for a literal string."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "file_pattern": {"type": "string", "default": "*"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments["query"]
        if not isinstance(query, str) or not query:
            raise ValueError("query must be a non-empty string")
        if len(query) > MAX_QUERY_CHARS:
            raise ValueError(f"query exceeds the {MAX_QUERY_CHARS} character limit")
        root = resolve_workspace_path(self.workspace, arguments.get("path", "."), must_exist=True)
        pattern = arguments.get("file_pattern", "*")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("file_pattern must be a non-empty string")
        if root.is_file():
            candidates, traversal_limited = [root], False
        elif root.is_dir() and not _is_link(root):
            candidates = []
            traversal_limited = False
            for current, _, files, truncated in _safe_walk(root):
                if truncated:
                    traversal_limited = True
                    break
                candidates.extend(
                    Path(current) / name for name in files if fnmatch.fnmatch(name, pattern)
                )
        else:
            raise ValueError("path is not a regular file or directory")
        results: list[str] = []
        output_chars = 0
        for path in candidates:
            if _is_link(path) or is_sensitive(path) or is_protected(path):
                continue
            try:
                # Revalidate every enumerated candidate immediately before IO:
                # a file may have been replaced by a link during traversal.
                path = resolve_workspace_path(self.workspace, str(path), must_exist=True)
                text = _read_text(path)
            except (PermissionError, UnicodeDecodeError, OSError, ValueError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query not in line:
                    continue
                result = f"{relative_display(path, self.workspace)}:{number}:{line}"
                if len(results) >= MAX_MATCHES or output_chars + len(result) + 1 > MAX_OUTPUT_CHARS:
                    results.append("... output truncated")
                    return ToolResult(True, "\n".join(results))
                results.append(result)
                output_chars += len(result) + 1
        if traversal_limited:
            results.append(f"... traversal truncated after {MAX_WALK_ENTRIES} entries")
        return ToolResult(True, "\n".join(results) or "No matches found")
