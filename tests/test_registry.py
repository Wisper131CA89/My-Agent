from pathlib import Path

from mini_agent.tools.filesystem import WriteFileTool
from mini_agent.tools.registry import ToolRegistry


def test_registry_rejects_schema_invalid_arguments_before_tool_execution(tmp_path: Path) -> None:
    registry = ToolRegistry([WriteFileTool(tmp_path)])
    result = registry.execute("write_file", {"path": "file.txt", "content": 42})
    assert not result.success
    assert result.error_code == "invalid_arguments"
    assert not (tmp_path / "file.txt").exists()


def test_registry_enforces_allowed_tools(tmp_path: Path) -> None:
    registry = ToolRegistry([WriteFileTool(tmp_path)], allowed_tools=set())
    result = registry.execute("write_file", {"path": "file.txt", "content": "safe"})
    assert result.error_code == "tool_not_permitted"
