from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, ClassVar

from ..models import ToolResult
from .base import Tool
from .paths import resolve_workspace_path


class RunCommandTool(Tool):
    """Run a deliberately small set of trusted, workspace-local dev commands.

    Enabling this tool permits the selected command to execute project code. It is
    an execution convenience, not a sandbox or a way to safely run untrusted code.
    """

    name = "run_command"
    description = (
        "Run one approved workspace development command without a shell: "
        "python -m pytest, python -m compileall, or python -m ruff check. "
        "May be disabled."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {"type": "array", "items": {"type": "string"}, "minItems": 3},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    _PYTEST_FLAGS: ClassVar[frozenset[str]] = frozenset(
        {"-q", "--quiet", "-v", "--verbose", "-x", "--disable-warnings"}
    )
    _PYTEST_TB_VALUES: ClassVar[frozenset[str]] = frozenset(
        {"auto", "long", "short", "line", "native", "no"}
    )
    _COMPILEALL_FLAGS: ClassVar[frozenset[str]] = frozenset({"-q", "-f"})
    _READER_JOIN_SECONDS: ClassVar[float] = 1.0

    def __init__(
        self, workspace: Path, enabled: bool = False, max_output_chars: int = 20_000
    ) -> None:
        super().__init__(workspace)
        self.enabled = enabled
        self.max_output_chars = max(0, max_output_chars)

    @staticmethod
    def _valid_command_shape(command: object) -> bool:
        return isinstance(command, list) and all(
            isinstance(part, str) and part and "\x00" not in part for part in command
        )

    def _workspace_path(self, value: str, *, allow_node_id: bool = False) -> str:
        """Validate a relative path (or pytest ``path::node`` selector)."""
        path_value = value.split("::", 1)[0] if allow_node_id else value
        resolve_workspace_path(self.workspace, path_value, must_exist=True)
        return value

    def _build_command(self, command: list[str]) -> list[str]:
        """Parse the complete accepted grammar and substitute the running Python."""
        if len(command) < 3 or command[:2] != ["python", "-m"]:
            raise PermissionError("command is not in the development-command allowlist")

        module = command[2]
        arguments = command[3:]
        if module == "pytest":
            parsed: list[str] = []
            index = 0
            while index < len(arguments):
                argument = arguments[index]
                if argument in self._PYTEST_FLAGS or (
                    argument.startswith("--tb=")
                    and argument.removeprefix("--tb=") in self._PYTEST_TB_VALUES
                ):
                    parsed.append(argument)
                elif argument == "--tb" and index + 1 < len(arguments):
                    value = arguments[index + 1]
                    if value not in self._PYTEST_TB_VALUES:
                        raise PermissionError("command is not in the development-command allowlist")
                    parsed.extend((argument, value))
                    index += 1
                elif argument == "-c" and index + 1 < len(arguments):
                    if arguments[index + 1] != "pyproject.toml":
                        raise PermissionError("command is not in the development-command allowlist")
                    self._workspace_path("pyproject.toml")
                    parsed.extend((argument, "pyproject.toml"))
                    index += 1
                elif not argument.startswith("-"):
                    parsed.append(self._workspace_path(argument, allow_node_id=True))
                else:
                    raise PermissionError("command is not in the development-command allowlist")
                index += 1
        elif module == "compileall":
            if not arguments:
                raise PermissionError("compileall requires at least one workspace path")
            parsed = []
            target_count = 0
            for argument in arguments:
                if argument in self._COMPILEALL_FLAGS:
                    parsed.append(argument)
                elif not argument.startswith("-"):
                    parsed.append(self._workspace_path(argument))
                    target_count += 1
                else:
                    raise PermissionError("command is not in the development-command allowlist")
            if not target_count:
                raise PermissionError("compileall requires at least one workspace path")
        elif module == "ruff":
            if not arguments or arguments[0] != "check":
                raise PermissionError("command is not in the development-command allowlist")
            if len(arguments) == 1:
                raise PermissionError("ruff check requires at least one workspace path")
            parsed = ["check"]
            for argument in arguments[1:]:
                if argument.startswith("-"):
                    raise PermissionError("command is not in the development-command allowlist")
                parsed.append(self._workspace_path(argument))
        else:
            raise PermissionError("command is not in the development-command allowlist")
        return [sys.executable, "-m", module, *parsed]

    def _safe_environment(self) -> dict[str, str]:
        """Keep OS launch essentials while excluding credentials and Python injection variables."""
        allowed = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "TMPDIR",
            "LANG",
            "LC_ALL",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        # Temporary files created by a trusted test run must also remain in its
        # workspace. This also avoids relying on a caller's private temp folder.
        for key in ("TEMP", "TMP", "TMPDIR"):
            environment[key] = str(self.workspace)
        return environment

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
        """Best-effort termination of the dedicated child process group/tree."""
        if os.name == "nt":
            try:
                taskkill = (
                    Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
                )
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    check=False,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def _run(self, command: list[str], timeout: int) -> tuple[int | None, bytes, bool, bool, bool]:
        """Return status, bounded output, truncation, timeout, and an open-output-pipe flag."""
        popen_options: dict[str, Any] = {
            "cwd": self.workspace,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "env": self._safe_environment(),
            "shell": False,
        }
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
        process: subprocess.Popen[bytes] = subprocess.Popen(command, **popen_options)
        assert process.stdout is not None
        output = bytearray()
        truncated = False

        def drain() -> None:
            nonlocal truncated
            # BufferedReader.read(size) can wait for ``size`` bytes or EOF.
            # A background descendant retaining stdout prevents EOF and would
            # hide a small amount of already-written parent output. ``read1``
            # returns the currently available pipe bytes instead; fakes used by
            # unit tests only need to implement the regular ``read`` fallback.
            read_chunk = getattr(process.stdout, "read1", process.stdout.read)
            while chunk := read_chunk(4096):
                remaining = self.max_output_chars - len(output)
                if remaining > 0:
                    output.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_process_tree(process)
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return_code = None
        except BaseException:
            self._terminate_process_tree(process)
            reader.join(timeout=self._READER_JOIN_SECONDS)
            if not reader.is_alive():
                process.stdout.close()
            raise
        reader.join(timeout=self._READER_JOIN_SECONDS)
        pipe_was_left_open = reader.is_alive()
        if pipe_was_left_open:
            # A descendant can retain the inherited pipe after its parent has
            # exited. Never close a buffered stream while another thread may be
            # blocked inside read(): on some platforms that can block forever.
            # Instead terminate the group, wait again for a bounded period, and
            # leave the daemon reader alone if the OS still has not released it.
            self._terminate_process_tree(process)
            reader.join(timeout=self._READER_JOIN_SECONDS)
        if not reader.is_alive():
            process.stdout.close()
        return return_code, bytes(output), truncated, timed_out, pipe_was_left_open

    def _render_output(self, prefix: str, output: str, truncated: bool) -> str:
        marker = "\n[output truncated]" if truncated else ""
        if self.max_output_chars <= len(prefix) + len(marker):
            return (prefix + marker)[: self.max_output_chars]
        available = self.max_output_chars - len(prefix) - len(marker)
        return prefix + output[:available] + marker

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.enabled:
            raise PermissionError("command execution is disabled; restart with --allow-run")
        command = arguments.get("command")
        if not self._valid_command_shape(command):
            raise ValueError("command must be a non-empty array of non-empty strings")
        timeout_value = arguments.get("timeout_seconds", 30)
        if isinstance(timeout_value, bool):
            raise TypeError("timeout_seconds must be an integer between 1 and 120")
        try:
            timeout = int(timeout_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be an integer between 1 and 120") from exc
        if timeout != timeout_value or not 1 <= timeout <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")

        executable_command = self._build_command(command)
        return_code, raw_output, truncated, timed_out, pipe_left_open = self._run(
            executable_command, timeout
        )
        rendered = raw_output.decode("utf-8", errors="replace")
        if timed_out:
            return ToolResult(
                False,
                self._render_output(f"Command timed out after {timeout}s.\n", rendered, truncated),
                error_code="command_timeout",
            )
        if pipe_left_open:
            return ToolResult(
                False,
                self._render_output(
                    "Command output pipe did not close; result is unsafe.\n", rendered, True
                ),
                error_code="command_pipe_open",
            )
        success = return_code == 0
        return ToolResult(
            success,
            self._render_output(f"exit_code={return_code}\noutput:\n", rendered, truncated),
            error_code=None if success else "command_failed",
        )
