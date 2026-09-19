"""A deliberately small, local-stdio MCP client.

This is not an MCP gateway: a server is only launched from an explicit trusted
configuration and only explicitly allowlisted tools are exposed to the agent.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from .models import ToolResult
from .tools.base import Tool

_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")
_MAX_LINE_BYTES = 1_000_000
_MAX_PENDING = 32
_MAX_NOTIFICATIONS = 1
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_]")


@dataclass(frozen=True)
class MCPServerConfig:
    """Trusted launch details and the *local* permission mapping for one server."""

    name: str
    command: tuple[str, ...]
    tool_permissions: dict[str, str]
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 32:
            raise ValueError("MCP server name must be a non-empty short string")
        if (
            not isinstance(self.command, tuple)
            or not self.command
            or not all(isinstance(part, str) and part for part in self.command)
        ):
            raise ValueError("MCP command must be a non-empty tuple of strings")
        if not isinstance(self.tool_permissions, dict) or not all(
            isinstance(tool, str) and tool and permission in {"read", "edit", "run"}
            for tool, permission in self.tool_permissions.items()
        ):
            raise ValueError("MCP tool permissions must explicitly be read, edit, or run")
        timeout = self.timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 3600
        ):
            raise ValueError("MCP timeout_seconds must be a finite number between 0 and 3600")


class MCPClient:
    """Synchronous JSON-RPC client for one bounded local stdio MCP process."""

    def __init__(
        self, config: MCPServerConfig, workspace: Path, max_output_chars: int = 20_000
    ) -> None:
        if (
            isinstance(max_output_chars, bool)
            or not isinstance(max_output_chars, int)
            or max_output_chars < 1
        ):
            raise ValueError("max_output_chars must be a positive integer")
        self.config = config
        # Copy the trusted policy once.  A frozen dataclass does not freeze its nested
        # dict, and mutating it later must not grant a running server new capability.
        self._permissions = dict(config.tool_permissions)
        self.workspace = workspace.resolve(strict=True)
        self.max_output_chars = max_output_chars
        self._process: subprocess.Popen[bytes] | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._reader: threading.Thread | None = None
        self._closed = True
        self._disconnect_reason: str | None = None
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue(_MAX_NOTIFICATIONS)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if not self._closed:
            return
        command = list(self.config.command)
        if command[0] == "python":
            command[0] = sys.executable
        # Do not pass model credentials or import-path overrides to untrusted server code.
        allowed_environment = {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "LANG",
            "LC_ALL",
            "TMP",
            "TEMP",
        }
        env = {
            key: value for key, value in os.environ.items() if key.upper() in allowed_environment
        }
        try:
            spawn_options: dict[str, Any] = {}
            if os.name == "nt":
                spawn_options["creationflags"] = (
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                spawn_options["start_new_session"] = True
            self._process = subprocess.Popen(
                command,
                cwd=self.workspace,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                **spawn_options,
            )
            self._closed = False
            self._disconnect_reason = None
            self._reader = threading.Thread(
                target=self._read_loop, daemon=True, name=f"mcp-{self.config.name}"
            )
            self._reader.start()
            response = self._request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOLS[0],
                    "capabilities": {},
                    "clientInfo": {"name": "mini-react-agent", "version": "0.3"},
                },
            )
            version, capabilities = response.get("protocolVersion"), response.get("capabilities")
            if (
                version not in _PROTOCOLS
                or not isinstance(capabilities, dict)
                or not isinstance(capabilities.get("tools"), dict)
            ):
                raise RuntimeError("MCP server selected an unsupported protocol version")
            self._notify("notifications/initialized", {})
        except BaseException:
            self.close()
            raise

    def discover_tools(self) -> list[Tool]:
        self._ensure_started()
        listed: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(32):
            result = self._request("tools/list", {} if cursor is None else {"cursor": cursor})
            tools = result.get("tools")
            if not isinstance(tools, list):
                raise RuntimeError("MCP tools/list returned an invalid result")  # noqa: TRY004 - peer protocol violation
            listed.extend(item for item in tools if isinstance(item, dict))
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise RuntimeError("MCP tools/list returned an invalid cursor")
            cursor = next_cursor
        else:
            raise RuntimeError("MCP tools/list pagination limit reached")
        exposed: list[Tool] = []
        exposed_names: set[str] = set()
        for item in listed:
            remote_name = item.get("name")
            # Permissions are a local policy; server annotations are never authority.
            permission = (
                self._permissions.get(remote_name) if isinstance(remote_name, str) else None
            )
            if permission is None:
                continue
            params = item.get("inputSchema")
            if not isinstance(params, dict) or params.get("type") not in {None, "object"}:
                continue
            proxy = _MCPTool(
                self, remote_name, item.get("description"), params or {"type": "object"}, permission
            )
            # Truncation/sanitisation must never turn two remote capabilities into a
            # silently overwritten local capability.
            if proxy.name in exposed_names:
                raise RuntimeError("MCP tool name collision after local sanitisation")
            exposed.append(proxy)
            exposed_names.add(proxy.name)
        return exposed

    def close(self) -> None:
        process, self._process = self._process, None
        self._closed = True
        if process is None:
            return
        self._fail_pending("MCP server disconnected")
        self._terminate_process_tree(process)
        # Do not close stdin here.  Text/buffered stream close can attempt a final flush
        # and hang if the trusted-but-buggy server stopped reading.  Terminating the
        # process first wakes any daemon writer blocked in flush.
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1)
        # Do not close a BufferedReader while its daemon reader could be stuck
        # behind a descendant which inherited stdout.
        if reader is None or not reader.is_alive():
            try:
                if process.stdout:
                    process.stdout.close()
            except OSError:
                pass

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "nt":
                taskkill = (
                    Path(os.environ.get("SYSTEMROOT", r"C:\\Windows")) / "System32" / "taskkill.exe"
                )
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    check=False,
                    timeout=2,
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
                process.wait(timeout=1)  # reap the direct child after group kill fails
            except OSError:
                pass
            except subprocess.TimeoutExpired:
                pass

    def _ensure_started(self) -> None:
        if self._closed or self._process is None:
            raise RuntimeError("MCP client is not running")

    def _send(self, payload: dict[str, Any]) -> float:
        self._ensure_started()
        process = self._process
        assert process is not None
        data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        if len(data) > _MAX_LINE_BYTES:
            raise RuntimeError("MCP request exceeds size limit")
        done = threading.Event()
        failed: list[BaseException] = []

        def write() -> None:
            try:
                with self._write_lock:
                    # A timed-out daemon writer must never wake up and write into a
                    # newly started connection on this reusable client object.
                    if self._closed or self._process is not process or process.stdin is None:
                        raise BrokenPipeError
                    process.stdin.write(data)
                    process.stdin.flush()
            except BaseException as exc:  # noqa: BLE001 - preserve cleanup on Ctrl-C pipe races.
                failed.append(exc)
            finally:
                done.set()

        started = time.monotonic()
        threading.Thread(target=write, daemon=True, name=f"mcp-write-{self.config.name}").start()
        if not done.wait(float(self.config.timeout_seconds)):
            self._disconnect_reason = "MCP write timed out"
            self.close()
            raise RuntimeError("MCP request timed out")
        if failed:
            self._disconnect_reason = "MCP server disconnected"
            self.close()
            raise RuntimeError("MCP server disconnected") from None
        return time.monotonic() - started

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_started()
        with self._pending_lock:
            if len(self._pending) >= _MAX_PENDING:
                raise RuntimeError("too many pending MCP requests")
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(1)
            self._pending[request_id] = response_queue
        try:
            elapsed = self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            try:
                response = response_queue.get(
                    timeout=max(0.001, float(self.config.timeout_seconds) - elapsed)
                )
            except queue.Empty:
                # Killing preserves request/response framing: no late reply can be reused.
                self.close()
                raise RuntimeError("MCP request timed out") from None
            if "error" in response:
                raise RuntimeError("MCP server returned a protocol error")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("MCP server returned an invalid result")  # noqa: TRY004 - peer protocol violation
            return result
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while not self._closed:
                line = process.stdout.readline(_MAX_LINE_BYTES + 1)
                if not line:
                    self._disconnect_reason = "MCP server disconnected"
                    return
                if len(line) > _MAX_LINE_BYTES or not line.endswith(b"\n"):
                    self._disconnect_reason = "MCP protocol line limit exceeded"
                    self.close()
                    return
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._disconnect_reason = "MCP protocol error"
                    self.close()
                    return
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    self._protocol_failure()
                    return
                has_id = "id" in message
                identifier = message.get("id")
                has_result = "result" in message
                has_error = "error" in message
                method = message.get("method")
                # JSON-RPC responses and requests/notifications are disjoint envelopes.
                # In particular, a normal request has neither result nor error.
                if has_result or has_error:
                    if not has_id or has_result == has_error or "method" in message:
                        self._protocol_failure()
                        return
                    if not isinstance(identifier, int) or isinstance(identifier, bool):
                        self._protocol_failure()
                        return
                    with self._pending_lock:
                        target = self._pending.get(identifier)
                    if target is not None:
                        try:
                            target.put_nowait(message)
                        except queue.Full:
                            pass
                elif isinstance(method, str) and method:
                    if has_id:
                        if not isinstance(identifier, (int, str)) or isinstance(identifier, bool):
                            self._protocol_failure()
                            return
                        self._handle_server_request(identifier, method)
                    else:
                        # Server notifications are deliberately bounded and have no
                        # authority over local permissions.
                        try:
                            self._notifications.put_nowait(message)
                        except queue.Full:
                            pass
                else:
                    self._protocol_failure()
                    return
        finally:
            if not self._closed:
                self._disconnect_reason = self._disconnect_reason or "MCP server disconnected"
                self._fail_pending(self._disconnect_reason)
                self.close()

    def _handle_server_request(self, identifier: int | str, method: str) -> None:
        try:
            if method == "ping":
                self._send({"jsonrpc": "2.0", "id": identifier, "result": {}})
            else:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "error": {"code": -32601, "message": "Method not supported"},
                    }
                )
        except RuntimeError:
            pass

    def _protocol_failure(self) -> None:
        self._disconnect_reason = "MCP protocol error"
        self._fail_pending(self._disconnect_reason, protocol_error=True)
        self.close()

    def _fail_pending(self, reason: str, *, protocol_error: bool = False) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
        for target in pending:
            try:
                target.put_nowait(
                    {"jsonrpc": "2.0", "error": {"code": -32600, "message": reason}}
                    if protocol_error
                    else {"jsonrpc": "2.0", "error": {"code": -32000, "message": reason}}
                )
            except queue.Full:
                pass

    def call_tool(self, remote_name: str, arguments: dict[str, Any]) -> ToolResult:
        if (
            not isinstance(remote_name, str)
            or not isinstance(arguments, dict)
            or self._permissions.get(remote_name) not in {"read", "edit", "run"}
        ):
            return ToolResult(False, "This MCP tool is not permitted.", "tool_not_permitted", False)
        try:
            result = self._request("tools/call", {"name": remote_name, "arguments": arguments})
        except (KeyboardInterrupt, SystemExit):
            # Cancellation never leaves a potentially active server/session available
            # for a later agent turn.
            self.close()
            raise
        except RuntimeError as exc:
            return ToolResult(
                False, str(exc)[: self.max_output_chars], "mcp_transport_error", False
            )
        content = result.get("content")
        if not isinstance(content, list) or not isinstance(result.get("isError", False), bool):
            return ToolResult(
                False, "MCP tool returned an invalid result.", "mcp_protocol_error", False
            )
        parts: list[str] = []
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                parts.append(item["text"])
        if not parts and isinstance(result.get("structuredContent"), dict):
            # Preserve useful structured-only results while still returning the agent's text result type.
            parts.append(
                json.dumps(result["structuredContent"], ensure_ascii=False, separators=(",", ":"))
            )
        text = "\n".join(parts)[: self.max_output_chars]
        if result.get("isError") is True:
            return ToolResult(False, text or "MCP tool reported an error.", "mcp_tool_error", False)
        if not text:
            return ToolResult(
                False, "MCP tool returned unsupported content.", "mcp_protocol_error", False
            )
        return ToolResult(True, text)


class _MCPTool(Tool):
    def __init__(
        self,
        client: MCPClient,
        remote_name: str,
        description: Any,
        parameters: dict[str, Any],
        permission: str,
    ) -> None:
        # Workspace was validated by the client and Tool is used only for its public schema.
        super().__init__(client.workspace)
        server = _SAFE_NAME.sub("_", client.config.name)
        remote = _SAFE_NAME.sub("_", remote_name)
        self.name = f"mcp_{server}_{remote}"[:64]
        self.description = (
            description if isinstance(description, str) else f"MCP tool {remote_name}"
        )
        self.parameters = parameters
        self.permission = permission
        self._client = client
        self._remote_name = remote_name

    def skill_spec(self) -> Any:
        from .skills import SkillSpec

        return SkillSpec(
            self.name,
            self.description,
            self.parameters,
            "str",
            self.permission,
            self._client.config.timeout_seconds,
            "0.3",
            [],
            "mcp",
        )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return self._client.call_tool(self._remote_name, arguments)
