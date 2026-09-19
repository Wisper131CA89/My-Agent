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


@dataclass(frozen=True)
class ToolExecution:
    """Sanitized metadata for a tool call in the most recent turn."""

    name: str
    success: bool
    error_code: str | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class TurnReport:
    """Execution evidence, distinct from a model's final natural-language response."""

    final_response: str | None
    executed_success: bool
    tools: tuple[ToolExecution, ...]
    stop_reason: str = "completed"


class ModelClient(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelResponse:
        """Return text, tool calls, or both for the current conversation."""
