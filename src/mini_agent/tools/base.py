from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models import ToolResult
from ..skills import SkillSpec

_BUILTIN_SKILL_METADATA: dict[str, tuple[str, int, str]] = {
    "list_files": ("read", 30, "A bounded list of safe workspace files."),
    "read_file": ("read", 30, "The requested bounded UTF-8 text lines."),
    "search_text": ("read", 30, "Bounded matching workspace text lines."),
    "write_file": ("edit", 30, "A confirmation that the file was created or updated."),
    "apply_patch": ("edit", 30, "A patch confirmation and bounded unified diff."),
    "run_command": ("run", 120, "The command exit status and bounded output."),
}


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve(strict=True)

    def skill_spec(self) -> SkillSpec:
        """Return this tool's capability contract.

        Existing built-ins receive precise metadata here.  Unknown subclasses
        default to ``run`` as a fail-closed classification: a new capability is
        never silently exposed in read or edit mode.  Custom tools should
        override this method with their intended permission and metadata.
        """
        permission, timeout_seconds, returns = _BUILTIN_SKILL_METADATA.get(
            self.name,
            ("run", 30, "A tool-specific result."),
        )
        return SkillSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            returns=returns,
            permission=permission,  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
        )

    def schema(self) -> dict[str, Any]:
        spec = self.skill_spec()
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
