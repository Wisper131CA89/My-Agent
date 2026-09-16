from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .tools.paths import resolve_workspace_path

AgentMode = Literal["read", "edit", "run"]


@dataclass(frozen=True)
class AgentConfig:
    """Validated, deliberately small set of runtime limits for the agent."""

    workspace: Path
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    max_steps: int = 20
    max_consecutive_errors: int = 3
    max_tool_output_chars: int = 20_000
    mode: AgentMode = "edit"
    allow_run: bool = False  # Compatibility alias; normalized to mode="run".
    log_runs: Path | None = None

    def __post_init__(self) -> None:
        workspace = self.workspace.expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace}")
        if self.mode not in {"read", "edit", "run"}:
            raise ValueError("mode must be one of: read, edit, run")
        if self.allow_run and self.mode != "edit":
            raise ValueError("--allow-run cannot be combined with an explicit non-edit mode")
        if not 1 <= self.max_steps <= 100:
            raise ValueError("max_steps must be between 1 and 100")
        if not 1 <= self.max_consecutive_errors <= 20:
            raise ValueError("max_consecutive_errors must be between 1 and 20")
        if not 1_000 <= self.max_tool_output_chars <= 100_000:
            raise ValueError("max_tool_output_chars must be between 1000 and 100000")
        object.__setattr__(self, "workspace", workspace)
        if self.allow_run:
            object.__setattr__(self, "mode", "run")
        object.__setattr__(self, "allow_run", self.mode == "run")
        if self.log_runs is not None:
            resolved = resolve_workspace_path(
                workspace, str(self.log_runs.expanduser()), must_exist=False
            )
            if resolved.suffix.lower() not in {".jsonl", ".log"}:
                raise ValueError("log_runs must use a .jsonl or .log extension")
            object.__setattr__(self, "log_runs", resolved)
