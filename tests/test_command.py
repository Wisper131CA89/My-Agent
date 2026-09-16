from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mini_agent.tools.command import RunCommandTool
from mini_agent.tools.registry import ToolRegistry


def test_command_is_disabled_by_default(tmp_path: Path) -> None:
    registry = ToolRegistry([RunCommandTool(tmp_path)])
    result = registry.execute("run_command", {"command": ["python", "-m", "pytest"]})
    assert not result.success
    assert "disabled" in result.content


@pytest.mark.parametrize(
    "command",
    [
        ["python", "script.py"],
        ["git", "status"],
        ["python", "-m", "mypy"],
        ["python", "-m", "ruff", "format", "."],
        ["python", "-m", "ruff", "check", "--fix", "."],
        ["python", "-m", "pytest", "--rootdir=/tmp"],
        ["python", "-m", "compileall"],
        ["python", "-m", "compileall", "-q"],
    ],
)
def test_unapproved_command_is_refused(tmp_path: Path, command: list[str]) -> None:
    result = ToolRegistry([RunCommandTool(tmp_path, enabled=True)]).execute(
        "run_command", {"command": command}
    )
    assert not result.success


def test_command_paths_cannot_escape_workspace(tmp_path: Path) -> None:
    result = ToolRegistry([RunCommandTool(tmp_path, enabled=True)]).execute(
        "run_command", {"command": ["python", "-m", "ruff", "check", "../outside.py"]}
    )
    assert not result.success
    assert "outside the workspace" in result.content


@pytest.mark.parametrize("target", [".git", "file.txt:secret"])
def test_command_paths_use_shared_protected_name_policy(tmp_path: Path, target: str) -> None:
    (tmp_path / "file.txt").write_text("safe")
    result = ToolRegistry([RunCommandTool(tmp_path, enabled=True)]).execute(
        "run_command", {"command": ["python", "-m", "ruff", "check", target]}
    )
    assert not result.success
    assert "protected" in result.content or "unsafe Windows name" in result.content


def test_command_uses_current_python_and_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeStdout:
        def __init__(self) -> None:
            self.read_once = False

        def read(self, size: int) -> bytes:
            if self.read_once:
                return b""
            self.read_once = True
            return b"ok"

        def close(self) -> None:
            pass

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = FakeStdout()
            self.pid = 123

        def wait(self, timeout: int | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-child")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    result = RunCommandTool(tmp_path, enabled=True).execute(
        {"command": ["python", "-m", "compileall", "."]}
    )

    assert result.success
    assert captured["command"] == [sys.executable, "-m", "compileall", "."]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]


def test_actual_pytest_output_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_noisy.py").write_text(
        "def test_noisy():\n    print('x' * 100000)\n    assert False\n"
    )
    maximum = 1_000
    result = RunCommandTool(tmp_path, enabled=True, max_output_chars=maximum).execute(
        {"command": ["python", "-m", "pytest", "-c", "pyproject.toml", "tests"]}
    )
    assert not result.success
    assert len(result.content) <= maximum


def test_actual_pytest_timeout_reports_timeout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(30)\n")
    result = RunCommandTool(tmp_path, enabled=True).execute(
        {
            "command": ["python", "-m", "pytest", "-c", "pyproject.toml", "tests"],
            "timeout_seconds": 1,
        }
    )
    assert not result.success
    assert "timed out after 1s" in result.content


def test_interruption_terminates_started_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeStdout:
        def read(self, size: int) -> bytes:
            return b""

        def close(self) -> None:
            pass

    class InterruptedProcess:
        stdout = FakeStdout()
        pid = 456

        def wait(self, timeout: int | None = None) -> int:
            raise KeyboardInterrupt

    cleaned: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: InterruptedProcess())
    tool = RunCommandTool(tmp_path, enabled=True)
    monkeypatch.setattr(tool, "_terminate_process_tree", lambda process: cleaned.append(process))
    with pytest.raises(KeyboardInterrupt):
        tool._run([sys.executable, "-m", "compileall", "."], 1)
    assert len(cleaned) == 1


def test_open_pipe_is_not_closed_while_reader_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading = threading.Event()
    release = threading.Event()
    closed: list[bool] = []

    class BlockingStdout:
        def read(self, size: int) -> bytes:
            reading.set()
            release.wait(10)
            return b""

        def close(self) -> None:
            closed.append(True)
            raise AssertionError("close must not be called while read is blocked")

    class ExitedProcess:
        stdout = BlockingStdout()
        pid = 789

        def wait(self, timeout: int | None = None) -> int:
            return 0

    tool = RunCommandTool(tmp_path, enabled=True)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: ExitedProcess())
    monkeypatch.setattr(tool, "_terminate_process_tree", lambda process: None)
    status, _, _, timed_out, pipe_was_left_open = tool._run(
        [sys.executable, "-m", "compileall", "."], 1
    )
    release.set()
    assert status == 0
    assert not timed_out
    assert pipe_was_left_open
    assert not closed


def test_actual_background_child_output_pipe_is_bounded_and_failed(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
        "print('parent exited')"
    )
    tool = RunCommandTool(tmp_path, enabled=True)
    started = time.monotonic()
    status, output, _, timed_out, pipe_was_left_open = tool._run([sys.executable, "-c", code], 5)
    assert time.monotonic() - started < 5
    assert status == 0
    assert b"parent exited" in output
    assert not timed_out
    assert pipe_was_left_open


def test_safe_environment_contains_no_common_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    environment = RunCommandTool(tmp_path, enabled=True)._safe_environment()
    assert "OPENAI_API_KEY" not in environment
    assert "DEEPSEEK_API_KEY" not in environment
