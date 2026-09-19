from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
    show_plan: bool = True
    mcp_servers: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.workspace, Path):
            raise TypeError("workspace must be a path")
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("model must be a non-empty string")
        if not isinstance(self.base_url, str) or not self.base_url:
            raise ValueError("base_url must be a non-empty string")
        if type(self.allow_run) is not bool:
            raise ValueError("allow_run must be a boolean")
        if type(self.max_steps) is not int:
            raise ValueError("max_steps must be an integer")
        if type(self.max_consecutive_errors) is not int:
            raise ValueError("max_consecutive_errors must be an integer")
        if type(self.max_tool_output_chars) is not int:
            raise ValueError("max_tool_output_chars must be an integer")
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
            log_runs = Path(self.log_runs)
            resolved = resolve_workspace_path(
                workspace, str(log_runs.expanduser()), must_exist=False
            )
            if resolved.suffix.lower() not in {".jsonl", ".log"}:
                raise ValueError("log_runs must use a .jsonl or .log extension")
            object.__setattr__(self, "log_runs", resolved)
        if type(self.show_plan) is not bool:
            raise ValueError("show_plan must be a boolean")


_AGENT_FIELDS = {
    "workspace",
    "model",
    "base_url",
    "max_steps",
    "max_consecutive_errors",
    "max_tool_output_chars",
    "mode",
    "allow_run",
    "log_runs",
    "show_plan",
}


def _configuration_error() -> ValueError:
    """Do not include TOML values: they may accidentally contain credentials."""
    return ValueError("配置文件格式或字段无效。")


def load_config(path: Path, overrides: dict[str, Any] | None = None) -> AgentConfig:
    """Load an explicitly selected TOML configuration; no ambient file is consulted."""
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("无法读取配置文件。") from exc
    if not isinstance(raw, dict) or set(raw) - {"agent", "mcp"}:
        raise _configuration_error()
    agent = raw.get("agent", {})
    if not isinstance(agent, dict) or set(agent) - _AGENT_FIELDS:
        raise _configuration_error()
    values = dict(agent)
    for name in ("max_steps", "max_consecutive_errors", "max_tool_output_chars"):
        if name in values and (type(values[name]) is not int):
            raise _configuration_error()
    if "show_plan" in values and type(values["show_plan"]) is not bool:
        raise _configuration_error()
    if "allow_run" in values and type(values["allow_run"]) is not bool:
        raise _configuration_error()
    for name in ("workspace", "model", "base_url", "mode", "log_runs"):
        if name in values and not isinstance(values[name], str):
            raise _configuration_error()
    base = path.expanduser().resolve().parent
    workspace_value = values.pop("workspace", ".")
    workspace = Path(workspace_value)
    if not workspace.is_absolute():
        workspace = base / workspace
    # Apply CLI values before constructing AgentConfig.  In particular, this
    # lets a valid --workspace replace a stale/missing relative TOML workspace.
    merged = dict(values)
    if overrides:
        merged.update(overrides)
        # CLI permission choices replace both representations of the legacy
        # policy.  A TOML allow_run=true must not defeat --mode read.
        if "mode" in overrides or "allow_run" in overrides:
            merged["allow_run"] = False
    if "workspace" in merged:
        override_workspace = Path(merged.pop("workspace"))
        workspace = (
            override_workspace
            if override_workspace.is_absolute()
            else Path.cwd() / override_workspace
        )
    # MCP objects are imported lazily to keep normal no-MCP startup minimal.
    servers: tuple[Any, ...] = ()
    if "mcp" in raw:
        try:
            servers = _parse_mcp_servers(raw["mcp"])
        except (TypeError, ValueError):
            raise _configuration_error() from None
    try:
        return AgentConfig(workspace=workspace, mcp_servers=servers, **merged)
    except (TypeError, ValueError, PermissionError) as exc:
        raise _configuration_error() from exc


def _parse_mcp_servers(raw: Any) -> tuple[Any, ...]:
    """Validate only the small trusted stdio MCP configuration surface."""
    from .mcp import MCPServerConfig

    if not isinstance(raw, dict) or set(raw) != {"servers"}:
        raise ValueError("invalid mcp")
    raw_servers = raw["servers"]
    if not isinstance(raw_servers, dict):
        raise TypeError("invalid mcp servers")
    servers = []
    for name, server in raw_servers.items():
        if not isinstance(name, str) or not name or not isinstance(server, dict):
            raise ValueError("invalid mcp server")
        if set(server) - {"command", "timeout_seconds", "tool_permissions"}:
            raise ValueError("invalid mcp server")
        command = server.get("command")
        permissions = server.get("tool_permissions", {})
        timeout = server.get("timeout_seconds", 10)
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
            or not isinstance(permissions, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in permissions.items()
            )
            or type(timeout) not in {int, float}
        ):
            raise ValueError("invalid mcp server")
        servers.append(MCPServerConfig(name, tuple(command), dict(permissions), float(timeout)))
    return tuple(servers)
