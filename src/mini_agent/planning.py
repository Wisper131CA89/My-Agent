"""Small, public task-plan data structures used by the in-memory agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from .models import ToolResult
from .skills import SkillSpec
from .tools.base import Tool

_STATUSES = {"pending", "in_progress", "completed"}


@dataclass(frozen=True)
class PlanStep:
    """One intentionally short, user-visible implementation step."""

    description: str
    status: str = "pending"


class UpdatePlanTool(Tool):
    """Keep an in-memory public plan; it is never written to the workspace."""

    name = "update_plan"
    description = "Update the concise public implementation plan. Do not include private reasoning."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["description", "status"],
                    "properties": {
                        "description": {"type": "string", "minLength": 1, "maxLength": 160},
                        "status": {"type": "string", "enum": sorted(_STATUSES)},
                    },
                },
            }
        },
    }

    def __init__(self, workspace, on_update) -> None:  # type: ignore[no-untyped-def]
        super().__init__(workspace)
        self._on_update = on_update

    def skill_spec(self) -> SkillSpec:
        return SkillSpec(
            self.name,
            self.description,
            self.parameters,
            "A public plan update.",
            "read",
            30,
            "0.3",
            [],
            "builtin",
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raw_steps = arguments.get("steps")
        if not isinstance(raw_steps, list):
            return ToolResult(False, "Plan must contain steps.", "invalid_plan")
        steps: list[PlanStep] = []
        for raw in raw_steps:
            if not isinstance(raw, dict):
                return ToolResult(False, "Plan steps must be objects.", "invalid_plan")
            description, status = raw.get("description"), raw.get("status")
            if (
                not isinstance(description, str)
                or not description.strip()
                or len(description) > 160
            ):
                return ToolResult(False, "Plan step text is invalid.", "invalid_plan")
            if status not in _STATUSES:
                return ToolResult(False, "Plan step status is invalid.", "invalid_plan")
            steps.append(PlanStep(description.strip(), status))
        if sum(step.status == "in_progress" for step in steps) > 1:
            return ToolResult(False, "Only one plan step may be in progress.", "invalid_plan")
        self._on_update(steps)
        return ToolResult(True, "Public plan updated.")
