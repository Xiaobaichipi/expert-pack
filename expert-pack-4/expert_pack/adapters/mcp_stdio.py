"""A minimal MCP stdio client, plus the ToolProvider adapter.

Transport: one JSON-RPC 2.0 message per line on stdin/stdout (the MCP stdio
convention). Implemented with the standard library so no MCP SDK is required;
the protocol surface is deliberately small:

    initialize -> notifications/initialized -> tools/list -> tools/call

Anything else (resources, prompts, sampling, HTTP transport) is out of scope
and is listed as a vacancy in the docs rather than half-implemented.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from typing import Any, Mapping, Sequence

from expert_pack.contracts import ToolResult, ToolSpec
from expert_pack.errors import McpError

_CLIENT_INFO = {"name": "expert-pack", "version": "0.1.0"}
_PROTOCOL_VERSION = "2024-11-05"


class McpStdioClient:
    def __init__(
        self,
        command: str | Sequence[str],
        args: Sequence[str] = (),
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        if isinstance(command, str):
            self._argv = [command, *args]
        else:
            self._argv = list(command)
        self.cwd = cwd
        self.env = dict(env or {})
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue[dict] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=200)
        self._next_id = 0
        self._lock = threading.Lock()
        self._started = False
        self._starting = False
        self.protocol_version = _PROTOCOL_VERSION
        self.server_info: dict[str, Any] = {}

    # -- lifecycle --------------------------------------------------------- #

    def _spawn(self) -> None:
        env = {**os.environ, **self.env}
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self.cwd,
                env=env,
                **kwargs,
            )
        except OSError as exc:
            raise McpError(
                f"cannot start MCP server {self._argv!r}: {exc}. "
                "Check the command in assembly.json (use a full path or an executable on PATH)."
            ) from exc
        threading.Thread(target=self._read_stdout, daemon=True, name="mcp-stdout").start()
        threading.Thread(target=self._read_stderr, daemon=True, name="mcp-stderr").start()

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except ValueError:
                self._stderr.append(f"non-JSON stdout: {text[:160]}")
                continue
            if isinstance(message, dict):
                self._queue.put(message)

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr.append(line.rstrip()[:300])

    def _ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            if self._starting:
                return
            self._starting = True
        try:
            self._spawn()
            request_id = self._new_id()
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": _CLIENT_INFO,
                    },
                }
            )
            result = self._wait(request_id, timeout=self.timeout, method="initialize")
            if isinstance(result, dict):
                self.protocol_version = str(result.get("protocolVersion") or _PROTOCOL_VERSION)
                self.server_info = dict(result.get("serverInfo") or {})
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            self._started = True
        finally:
            with self._lock:
                self._starting = False

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if self._started and proc.poll() is None:
            shutdown_id = self._new_id()
            try:
                self._send(
                    {"jsonrpc": "2.0", "id": shutdown_id, "method": "shutdown", "params": {}}
                )
                self._wait(shutdown_id, timeout=2.0, method="shutdown")
            except McpError:
                pass
            try:
                self._send({"jsonrpc": "2.0", "method": "exit", "params": {}})
            except McpError:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None
        self._started = False

    def __enter__(self) -> "McpStdioClient":
        self._ensure_started()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport --------------------------------------------------------- #

    def _new_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    def _send(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpError("MCP server is not running")
        if proc.poll() is not None:
            raise McpError(
                f"MCP server exited with code {proc.returncode}; stderr tail: {self._stderr_tail()}"
            )
        try:
            proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpError(f"cannot write to MCP server: {exc}; stderr tail: {self._stderr_tail()}") from exc

    def _stderr_tail(self, limit: int = 6) -> str:
        lines = list(self._stderr)[-limit:]
        return " | ".join(lines) if lines else "(empty)"

    def _wait(self, request_id: int, *, timeout: float, method: str) -> Any:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError(
                    f"timed out after {timeout:.0f}s waiting for {method}; "
                    f"stderr tail: {self._stderr_tail()}"
                )
            try:
                message = self._queue.get(timeout=remaining)
            except queue.Empty:
                continue
            if message.get("id") != request_id:
                continue  # notification or an out-of-order response
            if "error" in message:
                error = message.get("error") or {}
                raise McpError(
                    f"MCP error for {method}: {error.get('message', error)}"
                    f" (code {error.get('code', '?')})"
                )
            return message.get("result")

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float | None = None) -> Any:
        self._ensure_started()
        request_id = self._new_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params or {}),
            }
        )
        return self._wait(request_id, timeout=timeout or self.timeout, method=method)

    # -- MCP methods ------------------------------------------------------- #

    def list_tools(self, *, timeout: float | None = None) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params, timeout=timeout)
            if not isinstance(result, dict):
                raise McpError(f"tools/list returned {type(result).__name__}, expected object")
            batch = result.get("tools") or []
            if not isinstance(batch, list):
                raise McpError("tools/list returned a non-list 'tools'")
            tools.extend(item for item in batch if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: Mapping[str, Any], *, timeout: float | None = None) -> tuple[str, dict[str, Any], bool]:
        result = self.request(
            "tools/call", {"name": name, "arguments": dict(arguments)}, timeout=timeout
        )
        if not isinstance(result, dict):
            raise McpError(f"tools/call returned {type(result).__name__}, expected object")
        texts: list[str] = []
        for item in result.get("content") or []:
            if not isinstance(item, dict):
                texts.append(str(item))
                continue
            kind = item.get("type")
            if kind == "text":
                texts.append(str(item.get("text", "")))
            elif kind == "resource":
                texts.append(json.dumps(item.get("resource") or item, ensure_ascii=False)[:2000])
            elif kind == "image":
                texts.append("[image content omitted]")
            else:
                texts.append(json.dumps(item, ensure_ascii=False)[:2000])
        structured = result.get("structuredContent")
        data = structured if isinstance(structured, dict) else {}
        return "\n".join(texts), data, bool(result.get("isError"))


class McpToolProvider:
    """Bind one MCP server to the ``tools`` slot."""

    def __init__(
        self,
        name: str,
        command: str | Sequence[str],
        args: Sequence[str] = (),
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.name = name
        self._client = McpStdioClient(command, args, cwd=cwd, env=env, timeout=timeout)
        self._tools: list[ToolSpec] | None = None

    def list_tools(self) -> list[ToolSpec]:
        if self._tools is not None:
            return list(self._tools)
        raw = self._client.list_tools()
        specs: list[ToolSpec] = []
        seen: set[str] = set()
        for item in raw:
            tool_name = str(item.get("name") or "").strip()
            if not tool_name:
                continue
            if tool_name in seen:
                raise McpError(f"MCP server {self.name!r} exposes duplicate tool {tool_name!r}")
            seen.add(tool_name)
            schema = item.get("inputSchema") or {}
            specs.append(
                ToolSpec(
                    provider=self.name,
                    name=tool_name,
                    description=str(item.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else {},
                )
            )
        self._tools = specs
        return list(specs)

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            text, data, is_error = self._client.call_tool(name, arguments)
        except McpError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise McpError(f"MCP call {self.name}/{name} failed: {exc}") from exc
        if is_error:
            return ToolResult(ok=False, content=text, data=data, error=text or "MCP tool reported an error")
        return ToolResult(ok=True, content=text, data=data)

    def close(self) -> None:
        self._client.close()
