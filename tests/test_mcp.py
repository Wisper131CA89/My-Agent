from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from mini_agent.mcp import MCPClient, MCPServerConfig
from mini_agent.tools.registry import ToolRegistry


def _client(tmp_path: Path, permissions: dict[str, str] | None = None) -> MCPClient:
    return MCPClient(
        MCPServerConfig(
            "demo",
            (sys.executable, "-m", "mini_agent.mcp_demo", "stdio"),
            permissions or {"add": "read"},
        ),
        tmp_path,
    )


def _fixture_server(tmp_path: Path, source: str) -> tuple[str, ...]:
    """Create an actual stdio peer; keeping it out of the product package avoids test hooks."""
    server = tmp_path / "mcp_fixture.py"
    server.write_text(source, encoding="utf-8")
    return (sys.executable, "-u", str(server))


def test_real_stdio_lifecycle_discovery_and_error_result(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        client.start()
        tools = client.discover_tools()
        assert [tool.name for tool in tools] == ["mcp_demo_add"]
        assert tools[0].permission == "read"
        assert tools[0].execute({"a": 2, "b": 3}).content == "5"
        error = tools[0].execute({"a": 2})
        assert not error.success and error.error_code == "mcp_tool_error"
    finally:
        client.close()
        client.close()


def test_only_local_allowlist_is_discovered_or_callable(tmp_path: Path) -> None:
    client = _client(tmp_path, {"write_note": "edit"})
    try:
        client.start()
        assert client.discover_tools() == []
        denied = client.call_tool("add", {"a": 1, "b": 1})
        assert denied.error_code == "tool_not_permitted"
    finally:
        client.close()


def test_start_timeout_kills_non_reading_server(tmp_path: Path) -> None:
    client = MCPClient(
        MCPServerConfig("stuck", (sys.executable, "-c", "import time; time.sleep(60)"), {}, 0.1),
        tmp_path,
    )
    with pytest.raises(RuntimeError, match="timed out"):
        client.start()
    assert client._closed


def test_pagination_notification_and_string_ping_request(tmp_path: Path) -> None:
    command = _fixture_server(
        tmp_path,
        """import json, sys
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":request["id"],"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{}}}})
    elif method == "notifications/initialized":
        send({"jsonrpc":"2.0","method":"notice","params":{}})
        send({"jsonrpc":"2.0","id":"server-ping","method":"ping"})
    elif method == "tools/list":
        cursor = request.get("params", {}).get("cursor")
        if cursor is None:
            send({"jsonrpc":"2.0","id":request["id"],"result":{"tools":[{"name":"one","inputSchema":{"type":"object"}}],"nextCursor":"next"}})
        else:
            send({"jsonrpc":"2.0","id":request["id"],"result":{"tools":[{"name":"two","inputSchema":{"type":"object"}}]}})
""",
    )
    client = MCPClient(MCPServerConfig("paged", command, {"one": "read", "two": "read"}), tmp_path)
    try:
        client.start()
        assert [tool.name for tool in client.discover_tools()] == ["mcp_paged_one", "mcp_paged_two"]
        assert client._notifications.get(timeout=1)["method"] == "notice"
    finally:
        client.close()


def test_wrong_jsonrpc_envelope_fails_initialization(tmp_path: Path) -> None:
    command = _fixture_server(
        tmp_path,
        """import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc":"2.0","id":request["id"],"method":"bad","result":{}}), flush=True)
""",
    )
    client = MCPClient(
        MCPServerConfig("bad", command, {}),
        tmp_path,
    )
    with pytest.raises(RuntimeError, match="protocol error"):
        client.start()
    assert client._closed


def test_eof_fails_pending_request_without_waiting_full_timeout(tmp_path: Path) -> None:
    command = _fixture_server(
        tmp_path,
        """import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get("method") == "initialize":
        print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{}}}}), flush=True)
    elif request.get("method") == "tools/list":
        break
""",
    )
    client = MCPClient(MCPServerConfig("eof", command, {}, 5), tmp_path)
    try:
        client.start()
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="protocol error"):
            client.discover_tools()
        assert time.monotonic() - started < 1
    finally:
        client.close()


def test_read_mode_rejects_advertised_write_tool_without_remote_call(tmp_path: Path) -> None:
    calls = tmp_path / "calls.txt"
    source = """import json, sys
calls = COUNTER
def send(value): print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        send({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}}}})
    elif request.get('method') == 'tools/list':
        send({'jsonrpc':'2.0','id':request['id'],'result':{'tools':[{'name':'write','annotations':{'readOnlyHint':True},'inputSchema':{'type':'object'}}]}})
    elif request.get('method') == 'tools/call':
        open(calls, 'a', encoding='utf-8').write('called\\n')
        send({'jsonrpc':'2.0','id':request['id'],'result':{'content':[{'type':'text','text':'called'}]}})
""".replace("COUNTER", repr(str(calls)))
    client = MCPClient(
        MCPServerConfig("mutator", _fixture_server(tmp_path, source), {"write": "edit"}), tmp_path
    )
    try:
        client.start()
        tools = client.discover_tools()
        read_registry = ToolRegistry(tools, mode="read")
        assert read_registry.schemas() == []
        assert read_registry.execute(tools[0].name, {}).error_code == "tool_not_permitted"
        assert not calls.exists()
        assert ToolRegistry(tools, mode="edit").execute(tools[0].name, {}).success
        assert calls.read_text(encoding="utf-8") == "called\n"
    finally:
        client.close()


def test_tool_response_timeout_closes_and_reaps_server(tmp_path: Path) -> None:
    source = """import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}}}}), flush=True)
    elif request.get('method') == 'tools/list':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'tools':[{'name':'slow','inputSchema':{'type':'object'}}]}}), flush=True)
"""
    client = MCPClient(
        MCPServerConfig("slow", _fixture_server(tmp_path, source), {"slow": "read"}, 0.1), tmp_path
    )
    try:
        client.start()
        tool = client.discover_tools()[0]
        process = client._process
        result = tool.execute({})
        assert result.error_code == "mcp_transport_error"
        assert "timed out" in result.content
        assert client._closed and process is not None and process.poll() is not None
    finally:
        client.close()


def test_large_write_deadline_closes_and_reaps_server(tmp_path: Path) -> None:
    source = """import json, os, sys, time
request = json.loads(sys.stdin.readline())
print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}}}}), flush=True)
sys.stdin.readline()
time.sleep(60)
"""
    client = MCPClient(
        MCPServerConfig("blocked", _fixture_server(tmp_path, source), {"blob": "read"}, 0.1),
        tmp_path,
    )
    try:
        client.start()
        process = client._process
        started = time.monotonic()
        result = client.call_tool("blob", {"payload": "x" * 900_000})
        assert time.monotonic() - started < 2
        assert result.error_code == "mcp_transport_error"
        assert client._closed and process is not None and process.poll() is not None
    finally:
        client.close()


def test_server_environment_excludes_model_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-mcp")
    source = """import json, os, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}}}}), flush=True)
    elif request.get('method') == 'tools/call':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'content':[{'type':'text','text':str(bool(os.getenv('DEEPSEEK_API_KEY')))}]}}), flush=True)
"""
    client = MCPClient(
        MCPServerConfig("env", _fixture_server(tmp_path, source), {"check": "read"}), tmp_path
    )
    try:
        client.start()
        assert client.call_tool("check", {}).content == "False"
    finally:
        client.close()


@pytest.mark.parametrize("timeout", [True, 0, float("inf")])
def test_config_fails_closed_on_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError):
        MCPServerConfig("x", ("python", "-V"), {}, timeout)  # type: ignore[arg-type]
