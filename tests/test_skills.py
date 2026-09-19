from pathlib import Path
from typing import ClassVar

import pytest

from mini_agent.models import ToolResult
from mini_agent.skills import SkillSpec
from mini_agent.tools.base import Tool
from mini_agent.tools.filesystem import WriteFileTool
from mini_agent.tools.registry import ToolRegistry


class CustomTool(Tool):
    name = "custom"
    description = "A custom test tool."
    parameters: ClassVar[dict[str, object]] = {"type": "object", "additionalProperties": False}

    def execute(self, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(True, "x" * 100)


def test_skill_specs_are_mode_filtered_for_schema_and_execution(tmp_path: Path) -> None:
    registry = ToolRegistry([WriteFileTool(tmp_path)], mode="read")
    assert registry.skill_specs() == []
    assert registry.schemas() == []
    assert (
        registry.execute("write_file", {"path": "x", "content": "x"}).error_code
        == "tool_not_permitted"
    )


def test_unknown_custom_skill_defaults_to_run_and_cannot_bypass_mode(tmp_path: Path) -> None:
    registry = ToolRegistry([CustomTool(tmp_path)], mode="edit")
    assert registry.schemas() == []
    assert registry.execute("custom", {}).error_code == "tool_not_permitted"


def test_registry_rejects_duplicate_names_and_invalid_skill_schema(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([CustomTool(tmp_path), CustomTool(tmp_path)])

    class InvalidSchemaTool(CustomTool):
        name = "invalid"

        def skill_spec(self) -> SkillSpec:
            return SkillSpec(self.name, self.description, {"type": "not-a-type"}, "result")

    with pytest.raises(ValueError, match="JSON Schema"):
        ToolRegistry([InvalidSchemaTool(tmp_path)])


def test_registry_bounds_output_for_registered_skill(tmp_path: Path) -> None:
    registry = ToolRegistry([CustomTool(tmp_path)], max_output_chars=7)
    result = registry.execute("custom", {})
    assert result.success
    assert result.content == "x" * 7


def test_registry_snapshots_metadata_and_rejects_external_schema_refs(tmp_path: Path) -> None:
    tool = CustomTool(tmp_path)
    registry = ToolRegistry([tool])
    tool.parameters = dict(tool.parameters)
    tool.parameters["additionalProperties"] = True
    advertised = registry.schemas()[0]["function"]["parameters"]
    assert advertised["additionalProperties"] is False

    class ExternalReferenceTool(CustomTool):
        name = "external-reference"

        def skill_spec(self) -> SkillSpec:
            return SkillSpec(
                self.name,
                self.description,
                {"$ref": "https://example.invalid/schema.json"},
                "result",
            )

    with pytest.raises(ValueError, match="local"):
        ToolRegistry([ExternalReferenceTool(tmp_path)])


def test_custom_tool_rejections_do_not_leak_exception_details(tmp_path: Path) -> None:
    class RejectingTool(CustomTool):
        def execute(self, arguments: dict[str, object]) -> ToolResult:
            raise ValueError("private credential")

    result = ToolRegistry([RejectingTool(tmp_path)]).execute("custom", {})
    assert result.error_code == "tool_rejected"
    assert "credential" not in result.content


def test_fractional_timeout_metadata_is_valid(tmp_path: Path) -> None:
    class FractionalTimeoutTool(CustomTool):
        def skill_spec(self) -> SkillSpec:
            return SkillSpec(
                self.name, self.description, self.parameters, "result", timeout_seconds=0.1
            )

    assert ToolRegistry([FractionalTimeoutTool(tmp_path)]).skill_specs()[0].timeout_seconds == 0.1


def test_invalid_tool_result_is_converted_to_structured_failure(tmp_path: Path) -> None:
    class InvalidResultTool(CustomTool):
        def execute(self, arguments: dict[str, object]) -> ToolResult:
            return "not a ToolResult"  # type: ignore[return-value]

    result = ToolRegistry([InvalidResultTool(tmp_path)]).execute("custom", {})
    assert result.error_code == "tool_execution_failed"


def test_skill_schema_and_arguments_must_be_finite_bounded_json(tmp_path: Path) -> None:
    class NonFiniteSchemaTool(CustomTool):
        name = "nonfinite-schema"

        def skill_spec(self) -> SkillSpec:
            return SkillSpec(self.name, self.description, {"const": float("nan")}, "result")

    with pytest.raises(ValueError, match="finite JSON"):
        ToolRegistry([NonFiniteSchemaTool(tmp_path)])

    class NumericTool(CustomTool):
        parameters: ClassVar[dict[str, object]] = {
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
            "additionalProperties": False,
        }

    registry = ToolRegistry([NumericTool(tmp_path)])
    result = registry.execute("custom", {"value": float("inf")})
    assert result.error_code == "invalid_arguments"
    assert "finite" in result.content


def test_invalid_tool_result_metadata_is_sanitized_without_leaking(tmp_path: Path) -> None:
    class InvalidMetadataTool(CustomTool):
        def execute(self, arguments: dict[str, object]) -> ToolResult:
            return ToolResult(  # type: ignore[arg-type]
                "yes", "private output", "token=private-credential", "retry"
            )

    registry = ToolRegistry([InvalidMetadataTool(tmp_path)])
    result = registry.execute("custom", {})
    assert result == ToolResult(
        False, "Tool execution returned an invalid result.", "tool_execution_failed", True
    )
    assert "credential" not in registry.message_content(ToolResult(False, "x", "secret=credential"))
