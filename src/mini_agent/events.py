from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tools.paths import resolve_workspace_path


@dataclass(frozen=True)
class ToolEvent:
    """Safe-to-persist metadata; never arguments, output, or model reasoning."""

    tool: str
    success: bool
    duration_ms: int
    summary: str
    error_code: str | None = None


class EventLogger:
    def __init__(self, workspace: Path, path: Path | None) -> None:
        self.workspace = workspace
        self.path = path

    def tool_result(self, event: ToolEvent) -> None:
        if self.path is None:
            return
        try:
            # The target can change after startup, so check every append.
            target = resolve_workspace_path(self.workspace, str(self.path), must_exist=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "tool_result",
                **asdict(event),
            }
            with target.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            # Observability must never leave a tool-call batch without its results.
            return
