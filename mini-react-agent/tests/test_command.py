from pathlib import Path

from mini_agent.tools.command import RunCommandTool
from mini_agent.tools.registry import ToolRegistry


def test_command_is_disabled_by_default(tmp_path: Path) -> None:
    registry = ToolRegistry([RunCommandTool(tmp_path)])
    result = registry.execute("run_command", {"command": ["python", "-m", "pytest"]})
    assert not result.success
    assert "disabled" in result.content


def test_unapproved_command_is_refused(tmp_path: Path) -> None:
    registry = ToolRegistry([RunCommandTool(tmp_path, enabled=True)])
    result = registry.execute("run_command", {"command": ["python", "script.py"]})
    assert not result.success
    assert "allowlist" in result.content

