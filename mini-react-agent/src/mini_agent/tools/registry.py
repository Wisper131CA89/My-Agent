from __future__ import annotations

import json
from typing import Any, Iterable

from ..models import ToolResult
from .base import Tool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool], max_output_chars: int = 20_000) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.max_output_chars = max_output_chars

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool: {name}")
        if not isinstance(arguments, dict) or "_invalid_json" in arguments:
            return ToolResult(False, "Tool arguments are not valid JSON object data")
        try:
            result = tool.execute(arguments)
        except Exception as exc:
            result = ToolResult(False, f"{type(exc).__name__}: {exc}")
        return ToolResult(result.success, result.content[: self.max_output_chars])

    @staticmethod
    def message_content(result: ToolResult) -> str:
        return json.dumps(
            {"success": result.success, "content": result.content},
            ensure_ascii=False,
        )

