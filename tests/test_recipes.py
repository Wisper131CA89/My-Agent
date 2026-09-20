from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from mini_agent.models import ToolResult
from mini_agent.recipes import RecipeManager
from mini_agent.tools.base import Tool
from mini_agent.tools.command import RunCommandTool
from mini_agent.tools.filesystem import ReadFileTool
from mini_agent.tools.registry import ToolRegistry


class RecordingTool(Tool):
    description = "A deterministic recipe test tool."
    parameters: ClassVar[dict[str, object]] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "additionalProperties": False,
    }

    def __init__(self, workspace: Path, name: str, *, succeeds: bool = True) -> None:
        self.name = name
        self.succeeds = succeeds
        self.calls: list[dict[str, Any]] = []
        super().__init__(workspace)

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(
            self.succeeds, "private tool output", None if self.succeeds else "command_failed"
        )


def registry(
    tmp_path: Path, *, mode: str = "run", succeeds: bool = True
) -> tuple[ToolRegistry, RecordingTool]:
    command = RecordingTool(tmp_path, "run_command", succeeds=succeeds)
    reader = RecordingTool(tmp_path, "read_file")
    return ToolRegistry([reader, command], mode=mode), command


def recipe() -> list[dict[str, Any]]:
    return [{"tool": "read_file", "arguments": {}}, {"tool": "run_command", "arguments": {}}]


def test_verified_recipe_survives_restart_and_source_change_requires_reverify(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.py").write_text("first", encoding="utf-8")
    first_registry, command = registry(tmp_path)
    manager = RecipeManager(tmp_path, first_registry)
    assert manager.create("check_source", recipe())["verified"] is False
    assert manager.verify("check_source").success
    assert len(command.calls) == 1

    restarted_registry, restarted_command = registry(tmp_path)
    restarted = RecipeManager(tmp_path, restarted_registry)
    assert restarted.run("check_source").success
    (tmp_path / "source.py").write_text("changed", encoding="utf-8")
    stale = restarted.run("check_source")
    assert stale.error_code == "stale_recipe"
    assert len(restarted_command.calls) == 1
    assert restarted.list()[0]["verified"] is False


def test_unverified_and_failed_recipe_never_promote(tmp_path: Path) -> None:
    good_registry, good_command = registry(tmp_path)
    manager = RecipeManager(tmp_path, good_registry)
    manager.create("checks", recipe())
    assert manager.run("checks").error_code == "not_verified"
    assert not good_command.calls

    bad_registry, _ = registry(tmp_path, succeeds=False)
    bad = RecipeManager(tmp_path, bad_registry)
    result = bad.verify("checks")
    assert result.error_code == "command_failed"
    assert bad.list()[0]["verified"] is False


def test_preflight_rejects_invalid_or_read_only_without_any_execution(tmp_path: Path) -> None:
    run_registry, command = registry(tmp_path)
    manager = RecipeManager(tmp_path, run_registry)
    manager.create("invalid", [{"tool": "run_command", "arguments": {"unknown": "x"}}])
    assert manager.verify("invalid").error_code == "invalid_arguments"
    assert not command.calls

    read_registry, read_command = registry(tmp_path, mode="read")
    readonly = RecipeManager(tmp_path, read_registry, writable=False)
    # It reloads the existing state but does not run its persisted command.
    assert readonly.run("invalid").error_code == "tool_not_permitted"
    assert not read_command.calls


def test_recipe_validation_and_no_overwrite(tmp_path: Path) -> None:
    manager = RecipeManager(tmp_path, registry(tmp_path)[0])
    with pytest.raises(ValueError):
        manager.create("Bad-name", recipe())
    with pytest.raises(ValueError):
        manager.create("writing", [{"tool": "write_file", "arguments": {}}])
    manager.create("once", recipe())
    with pytest.raises(ValueError, match="overwriting"):
        manager.create("once", recipe())


def test_real_command_recipe_reloads_and_runs_in_a_clean_workspace(tmp_path: Path) -> None:
    (tmp_path / "test_probe.py").write_text(
        "def test_probe():\n    assert True\n", encoding="utf-8"
    )
    steps = [
        {"tool": "read_file", "arguments": {"path": "test_probe.py"}},
        {
            "tool": "run_command",
            "arguments": {"command": ["python", "-m", "pytest", "-q", "test_probe.py"]},
        },
    ]
    first = ToolRegistry(
        [ReadFileTool(tmp_path), RunCommandTool(tmp_path, enabled=True)], mode="run"
    )
    manager = RecipeManager(tmp_path, first)
    manager.create("probe", steps)
    assert manager.verify("probe").success

    second = ToolRegistry(
        [ReadFileTool(tmp_path), RunCommandTool(tmp_path, enabled=True)], mode="run"
    )
    assert RecipeManager(tmp_path, second).run("probe").success


@pytest.mark.parametrize("interrupt", [False, True])
def test_failed_reverification_revokes_persisted_success(tmp_path: Path, interrupt: bool) -> None:
    good_registry, _ = registry(tmp_path)
    manager = RecipeManager(tmp_path, good_registry)
    manager.create("checks", recipe())
    assert manager.verify("checks").success

    if interrupt:

        class InterruptingTool(RecordingTool):
            def execute(self, arguments: dict[str, Any]) -> ToolResult:
                self.calls.append(arguments)
                raise KeyboardInterrupt

        command = InterruptingTool(tmp_path, "run_command")
        manager.registry = ToolRegistry([RecordingTool(tmp_path, "read_file"), command], mode="run")
        with pytest.raises(KeyboardInterrupt):
            manager.verify("checks")
    else:
        manager.registry, _ = registry(tmp_path, succeeds=False)
        assert not manager.verify("checks").success

    restarted = RecipeManager(tmp_path, registry(tmp_path)[0])
    assert restarted.list()[0]["verified"] is False
    assert restarted.run("checks").error_code == "not_verified"


def test_changed_steps_on_disk_cannot_reuse_old_fingerprint(tmp_path: Path) -> None:
    manager = RecipeManager(tmp_path, registry(tmp_path)[0])
    manager.create("checks", recipe())
    assert manager.verify("checks").success
    state_path = tmp_path / ".mini-agent" / "recipes.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["recipes"][0]["steps"] = [{"tool": "run_command", "arguments": {}}]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    restarted = RecipeManager(tmp_path, registry(tmp_path)[0])
    assert restarted.run("checks").error_code == "stale_recipe"
    assert restarted.list()[0]["verified"] is False


def test_read_only_verification_never_executes_with_run_registry(tmp_path: Path) -> None:
    writer = RecipeManager(tmp_path, registry(tmp_path)[0])
    writer.create("checks", recipe())
    run_registry, command = registry(tmp_path)
    readonly = RecipeManager(tmp_path, run_registry, writable=False)
    assert readonly.verify("checks").error_code == "tool_not_permitted"
    assert not command.calls


@pytest.mark.parametrize(
    "payload",
    [
        b'{"version":true,"recipes":[]}',
        b"not json",
        b"x" * 1_000_001,
    ],
    ids=["boolean-version", "invalid-json", "oversize"],
)
def test_corrupt_or_oversize_state_is_refused(tmp_path: Path, payload: bytes) -> None:
    state_dir = tmp_path / ".mini-agent"
    state_dir.mkdir()
    (state_dir / "recipes.json").write_bytes(payload)
    with pytest.raises(ValueError):
        RecipeManager(tmp_path, registry(tmp_path)[0])


def test_create_rolls_back_if_atomic_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = RecipeManager(tmp_path, registry(tmp_path)[0])

    def fail_save() -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(manager, "_save", fail_save)
    with pytest.raises(OSError):
        manager.create("checks", recipe())
    assert manager.list() == []
