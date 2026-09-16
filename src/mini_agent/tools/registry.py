from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from jsonschema import Draft202012Validator

from ..models import ToolResult
from .base import Tool


class ToolRegistry:
    """Expose and execute only tools permitted by the configured capability set."""

    def __init__(
        self,
        tools: Iterable[Tool],
        max_output_chars: int = 20_000,
        allowed_tools: Iterable[str] | None = None,
    ) -> None:
        candidates = {tool.name: tool for tool in tools}
        self._allowed = set(allowed_tools) if allowed_tools is not None else set(candidates)
        self._tools = {name: tool for name, tool in candidates.items() if name in self._allowed}
        self.max_output_chars = max_output_chars

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if not isinstance(name, str) or name not in self._allowed:
            return ToolResult(
                False, "This tool is not permitted in the selected mode.", "tool_not_permitted"
            )
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, f"Unknown tool: {name}", "unknown_tool")
        if not isinstance(arguments, dict) or "_invalid_json" in arguments:
            return ToolResult(
                False, "Tool arguments must be a valid JSON object.", "invalid_arguments"
            )
        error = next(iter(Draft202012Validator(tool.parameters).iter_errors(arguments)), None)
        if error:
            # Do not echo model supplied values: schema libraries can include them in messages.
            return ToolResult(
                False, "Tool arguments do not match the required schema.", "invalid_arguments"
            )
        try:
            result = tool.execute(arguments)
        except FileNotFoundError:
            result = ToolResult(False, "Requested file was not found.", "file_not_found")
        except (PermissionError, ValueError, FileExistsError) as exc:
            result = ToolResult(False, str(exc), "tool_rejected")
        except Exception:  # noqa: BLE001 - tools are third-party/untrusted execution boundaries.
            # Arbitrary exception details can contain private paths or secrets.
            result = ToolResult(
                False, "Tool execution failed unexpectedly.", "tool_execution_failed", True
            )
        return ToolResult(
            result.success,
            result.content[: self.max_output_chars],
            result.error_code,
            result.retryable,
        )

    @staticmethod
    def message_content(result: ToolResult) -> str:
        return json.dumps(
            {
                "success": result.success,
                "content": result.content,
                "error_code": result.error_code,
                "retryable": result.retryable,
            },
            ensure_ascii=False,
        )
