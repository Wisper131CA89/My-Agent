"""Tiny stdio MCP demo: expose one read-only numeric ``add`` tool.

Run with ``python -m mini_agent.mcp_demo stdio``.  It intentionally exposes no
filesystem or command capability, so it is safe as an integration-test server.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict) or "id" not in request:
            continue
        ident, method = request["id"], request.get("method")
        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mini-demo", "version": "0.3"},
                    },
                }
            )
        elif method == "tools/list":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "result": {
                        "tools": [
                            {
                                "name": "add",
                                "description": "Add two numbers.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "a": {"type": "number"},
                                        "b": {"type": "number"},
                                    },
                                    "required": ["a", "b"],
                                    "additionalProperties": False,
                                },
                            }
                        ]
                    },
                }
            )
        elif method == "tools/call":
            params = request.get("params", {})
            args = params.get("arguments", {}) if isinstance(params, dict) else {}
            if (
                params.get("name") != "add"
                or not isinstance(args.get("a"), (int, float))
                or not isinstance(args.get("b"), (int, float))
            ):
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": ident,
                        "result": {
                            "content": [{"type": "text", "text": "invalid add arguments"}],
                            "isError": True,
                        },
                    }
                )
            else:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": ident,
                        "result": {
                            "content": [{"type": "text", "text": str(args["a"] + args["b"])}]
                        },
                    }
                )
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
