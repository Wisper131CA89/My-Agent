from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models import ToolResult


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve(strict=True)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

