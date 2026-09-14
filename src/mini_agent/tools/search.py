from __future__ import annotations

import fnmatch
import os
from typing import Any

from ..models import ToolResult
from .base import Tool
from .paths import IGNORED_NAMES, relative_display, resolve_workspace_path


class SearchTextTool(Tool):
    name = "search_text"
    description = "Search UTF-8 text files for a literal string."
    parameters = {
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
        root = resolve_workspace_path(self.workspace, arguments.get("path", "."), must_exist=True)
        pattern = arguments.get("file_pattern", "*")
        results: list[str] = []
        candidates = [root] if root.is_file() else []
        if root.is_dir():
            for current, directories, files in os.walk(root):
                directories[:] = [name for name in directories if name not in IGNORED_NAMES]
                candidates.extend(
                    type(root)(current) / name for name in files if fnmatch.fnmatch(name, pattern)
                )
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query in line:
                    results.append(f"{relative_display(path, self.workspace)}:{number}:{line}")
                    if len(results) >= 200:
                        results.append("... output truncated after 200 matches")
                        return ToolResult(True, "\n".join(results))
        return ToolResult(True, "\n".join(results) or "No matches found")

