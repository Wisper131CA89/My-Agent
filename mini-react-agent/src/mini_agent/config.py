from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    workspace: Path
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    max_steps: int = 20
    max_consecutive_errors: int = 3
    max_tool_output_chars: int = 20_000
    allow_run: bool = False

    def __post_init__(self) -> None:
        workspace = self.workspace.expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace}")
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        object.__setattr__(self, "workspace", workspace)
