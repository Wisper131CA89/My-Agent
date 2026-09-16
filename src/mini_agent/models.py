from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Kept separate so reasoning is never put in conversation/event logs.
    reasoning_content: str | None = None


@dataclass(frozen=True)
class ToolResult:
    success: bool
    content: str
    error_code: str | None = None
    retryable: bool | None = None


class ModelClient(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        """Return text, tool calls, or both for the current conversation."""
