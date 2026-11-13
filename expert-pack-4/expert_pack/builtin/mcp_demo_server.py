"""A tiny, real MCP stdio server used by the offline demo and the tests.

It is also a reference implementation for users who want to expose their own
tools: read one JSON-RPC message per line, answer it, never print to stdout.

Tools:
  lookup(item)            -> 42 / 17 / 3.14 for alpha / beta / gamma
  calc(expression)        -> safe arithmetic evaluation
"""

from __future__ import annotations

import json
import sys
from typing import Any

from expert_pack.builtin.safe_math import evaluate, format_number

_PROTOCOL_VERSION = "2024-11-05"
_DATA = {"alpha": 42, "beta": 17, "gamma": 3.14}

_TOOLS = [
    {
        "name": "lookup",
        "description": "Look up a named fact. Known items: alpha, beta, gamma.",
        "inputSchema": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "item name"}},
            "required": ["item"],
        },
    },
    {
        "name": "calc",
        "description": "Evaluate a pure arithmetic expression, e.g. '42*3'.",
        "inputSchema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
]


def _call(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    if name == "lookup":
        item = str(arguments.get("item", "")).strip().lower()
        if not item:
            return "lookup needs an 'item' argument", True
        if item in _DATA:
            return str(_DATA[item]), False
        return f"unknown item {item!r}; known items: {', '.join(_DATA)}", True
    if name == "calc":
        expression = str(arguments.get("expression", "")).strip()
        if not expression:
            return "calc needs an expression (missing operand)", True
        try:
            value = evaluate(expression)
        except (SyntaxError, ValueError, TypeError) as exc:
            return f"cannot evaluate {expression!r}: {exc}", True
        return format_number(value), False
    return f"unknown tool {name!r}", True


def handle(message: dict[str, Any]) -> dict[str, Any]:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:  # notification
        return {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "expert-pack-demo", "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        text, is_error = _call(name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "shutdown":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("method") == "exit":
            break
        response = handle(message)
        if response:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
