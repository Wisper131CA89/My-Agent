from __future__ import annotations

import subprocess
from typing import Any

from ..models import ToolResult
from .base import Tool


class RunCommandTool(Tool):
    name = "run_command"
    description = "Run an approved development command without a shell. May be disabled."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, workspace, enabled: bool = False, max_output_chars: int = 20_000) -> None:
        super().__init__(workspace)
        self.enabled = enabled
        self.max_output_chars = max_output_chars

    @staticmethod
    def _approved(command: list[str]) -> bool:
        normalized = [part.lower() for part in command]
        if normalized[:3] in (["python", "-m", "pytest"], ["python", "-m", "compileall"]):
            return True
        if normalized[:3] in (["python", "-m", "ruff"], ["python", "-m", "mypy"]):
            return True
        if normalized[:2] in (["git", "status"], ["git", "diff"]):
            return True
        return False

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.enabled:
            raise PermissionError("command execution is disabled; restart with --allow-run")
        command = arguments["command"]
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ValueError("command must be a non-empty array of strings")
        if not self._approved(command):
            raise PermissionError("command is not in the development-command allowlist")
        timeout = int(arguments.get("timeout_seconds", 30))
        if not 1 <= timeout <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            partial = f"{exc.stdout or ''}{exc.stderr or ''}"[: self.max_output_chars]
            return ToolResult(False, f"Command timed out after {timeout}s.\n{partial}")
        output = (
            f"exit_code={completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )[: self.max_output_chars]
        return ToolResult(completed.returncode == 0, output)

