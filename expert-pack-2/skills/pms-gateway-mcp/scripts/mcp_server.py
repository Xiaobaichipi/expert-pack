#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pms-gateway-mcp —— PMS 接口网关 MCP Server（stdio / 换行分隔 JSON-RPC 2.0）。

协议约定
--------
- 传输：stdin/stdout 双向，**一行一条 JSON-RPC 2.0 消息**（UTF-8，\\n 分隔）；
- stdout **只输出协议消息**，任何日志/诊断/异常栈一律写 stderr；
- 支持方法：
    * ``initialize``（protocolVersion=2024-11-05，capabilities.tools={}，serverInfo）
    * ``notifications/initialized``（通知，无响应）
    * ``ping``
    * ``tools/list``（26 个工具，含 inputSchema）
    * ``tools/call``（返回 ``content:[{type:"text",text:<JSON字符串>}]`` 与 ``isError``）
- 错误码：解析失败 -32700；非法请求 -32600；未知方法 -32601；参数错误 -32602；
  服务端内部错误 -32603。单条消息解析失败只回错误，进程不退出。

启动（宿主以 stdio 方式拉起，无需参数）::

    python expert-pack/skills/pms-gateway-mcp/scripts/mcp_server.py

可选参数：``--spec`` / ``--auth-mode`` / ``--base-url`` / ``--timeout`` / ``--retry``，
其余配置全部来自环境变量（见 SKILL.md）。
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable, TextIO

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from pms_client import (  # noqa: E402  (需先插入 sys.path)
    ErrorCode,
    PmsClient,
    PmsConfig,
    PmsError,
    __version__,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pms-gateway-mcp"
SERVER_VERSION = __version__

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: 通知类方法（无响应）
NOTIFICATION_METHODS = (
    "notifications/initialized",
    "notifications/cancelled",
    "notifications/roots/list_changed",
)


def log(message: str) -> None:
    """诊断日志只写 stderr，绝不污染 stdout 协议通道。"""
    stream = _LOG_STREAM if _LOG_STREAM is not None else sys.stderr
    try:
        print(f"[{SERVER_NAME}] {message}", file=stream, flush=True)
    except Exception:  # pragma: no cover - stderr 不可用时静默
        pass


#: 运行期日志流（serve_stdio 可注入，便于测试与宿主重定向）
_LOG_STREAM: TextIO | None = None


class JsonRpcError(Exception):
    """处理消息时主动抛出的 JSON-RPC 错误。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class McpServer:
    """MCP 协议处理器（与传输解耦，便于单元测试直接调用）。"""

    def __init__(
        self,
        client: PmsClient | None = None,
        *,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
    ) -> None:
        self.client = client or PmsClient()
        self.server_name = server_name
        self.server_version = server_version
        self.initialized = False
        log(
            f"init: authMode={self.client.auth_mode} tools={len(self.client.spec.tools)} "
            f"spec={self.client.spec.path}"
        )

    # ------------------------------------------------------------------
    # 消息入口
    # ------------------------------------------------------------------
    def handle_message(self, message: Any) -> dict[str, Any] | None:
        """处理一条已解析的 JSON-RPC 消息，返回响应对象（通知返回 None）。"""
        if isinstance(message, list):
            # 兼容 JSON-RPC 批量请求（MCP 常规不批量，但不应崩溃）
            responses = [resp for resp in (self.handle_message(item) for item in message) if resp is not None]
            return responses or None
        if not isinstance(message, dict):
            return self._error_response(None, INVALID_REQUEST, "请求必须是 JSON 对象")
        if not isinstance(message.get("jsonrpc"), str):
            return self._error_response(
                message.get("id"), INVALID_REQUEST, "缺少 jsonrpc 字段，仅支持 JSON-RPC 2.0"
            )

        method = message.get("method")
        params = message.get("params")
        has_id = "id" in message
        msg_id = message.get("id")

        if not isinstance(method, str) or not method:
            return self._error_response(msg_id, INVALID_REQUEST, "缺少 method 字段")
        if params is not None and not isinstance(params, (dict, list)):
            if has_id:
                return self._error_response(msg_id, INVALID_PARAMS, "params 必须是对象或数组")
            return None

        if method in NOTIFICATION_METHODS or not has_id:
            # 通知：执行副作用但不返回响应（未知通知方法仅记日志）
            try:
                self._dispatch(method, params)
            except JsonRpcError as exc:
                log(f"通知 {method} 处理失败：{exc.message}")
            except Exception as exc:  # pragma: no cover - 防御
                log(f"通知 {method} 异常：{type(exc).__name__}: {exc}")
            return None

        try:
            result = self._dispatch(method, params)
        except JsonRpcError as exc:
            return self._error_response(msg_id, exc.code, exc.message, exc.data)
        except PmsError as exc:
            log(f"工具调用失败：{exc.code} {exc.message}")
            return self._error_response(msg_id, INTERNAL_ERROR, exc.message, exc.to_dict())
        except Exception as exc:  # pragma: no cover - 防御未知异常
            log("内部异常：\n" + traceback.format_exc())
            return self._error_response(msg_id, INTERNAL_ERROR, f"服务端内部错误：{type(exc).__name__}: {exc}")
        return self._result_response(msg_id, result)

    def handle_line(self, line: str) -> str | None:
        """处理一行文本（stdin 的一行），返回一行待输出文本（无响应返回 None）。"""
        if not isinstance(line, str):
            return None
        text = line.strip()
        if not text:
            return None
        try:
            message = json.loads(text)
        except ValueError as exc:
            log(f"JSON 解析失败：{exc}")
            return self._dump(self._error_response(None, PARSE_ERROR, f"JSON 解析失败：{exc}"))
        try:
            response = self.handle_message(message)
        except Exception as exc:  # pragma: no cover - handle_message 内部已兜底
            log("消息处理异常：\n" + traceback.format_exc())
            response = self._error_response(None, INTERNAL_ERROR, f"服务端内部错误：{exc}")
        if response is None:
            return None
        if isinstance(response, list):
            return self._dump(response)
        return self._dump(response)

    # ------------------------------------------------------------------
    # 方法分发
    # ------------------------------------------------------------------
    def _dispatch(self, method: str, params: Any) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method in NOTIFICATION_METHODS:
            if method == "notifications/initialized":
                self.initialized = True
                log("客户端已确认初始化完成（notifications/initialized）")
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.client.tool_schemas()}
        if method == "tools/call":
            return self._tools_call(params)
        if method == "resources/list":
            raise JsonRpcError(INVALID_PARAMS, "本服务未声明 resources 能力，请使用 tools/list")
        if method == "prompts/list":
            raise JsonRpcError(INVALID_PARAMS, "本服务未声明 prompts 能力，请使用 tools/list")
        raise JsonRpcError(METHOD_NOT_FOUND, f"不支持的方法：{method}")

    def _initialize(self, params: Any) -> dict[str, Any]:
        requested = ""
        if isinstance(params, dict):
            requested = str(params.get("protocolVersion") or "")
            client_info = params.get("clientInfo") or {}
            if isinstance(client_info, dict):
                log(
                    f"initialize: client={client_info.get('name')!r} "
                    f"version={client_info.get('version')!r} requestedProtocol={requested!r}"
                )
        else:
            log("initialize: params 非对象，按默认协议版本返回")
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self.server_name, "version": self.server_version},
        }

    def _tools_call(self, params: Any) -> dict[str, Any]:
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "tools/call 的 params 必须是对象")
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise JsonRpcError(INVALID_PARAMS, "tools/call 缺少工具名 name")
        name = name.strip()
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "tools/call 的 arguments 必须是 JSON 对象")

        try:
            envelope = self.client.call_tool(name, arguments)
        except PmsError as exc:
            if exc.code in (ErrorCode.INVALID_PARAM, ErrorCode.UNKNOWN_TOOL):
                # 协议级参数错误：返回 -32602，便于宿主/模型纠正后重试
                raise JsonRpcError(INVALID_PARAMS, exc.message, exc.to_dict()) from None
            log(f"工具 {name} 调用失败：{exc.code} {exc.message}")
            return {
                "content": [{"type": "text", "text": self._dump({"error": exc.to_dict()})}],
                "isError": True,
            }

        is_error = envelope.get("code") not in (0, None)
        return {
            "content": [{"type": "text", "text": self._dump(envelope)}],
            "isError": bool(is_error),
        }

    # ------------------------------------------------------------------
    # 响应构造
    # ------------------------------------------------------------------
    @staticmethod
    def _dump(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _result_response(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _error_response(self, msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": error}


# ---------------------------------------------------------------------------
# stdio 服务循环
# ---------------------------------------------------------------------------
def _reconfigure(stream: TextIO | None, **kwargs: Any) -> None:
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(**kwargs)
        except Exception:  # pragma: no cover - 非文本流/已关闭时忽略
            pass


def serve_stdio(
    server: McpServer | None = None,
    *,
    stdin: Iterable[str] | TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """stdio 主循环：逐行读请求、逐行写响应。"""
    server = server or McpServer()
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    if source is sys.stdin:
        _reconfigure(sys.stdin, encoding="utf-8", errors="replace")
    if sink is sys.stdout:
        _reconfigure(sys.stdout, encoding="utf-8", errors="replace")
    if err is sys.stderr:
        _reconfigure(sys.stderr, encoding="utf-8", errors="replace")

    global _LOG_STREAM
    previous_log_stream = _LOG_STREAM
    _LOG_STREAM = err
    log("stdio 服务已启动，等待 JSON-RPC 消息（Ctrl+C 退出）")
    try:
        for line in source:
            response = server.handle_line(line)
            if response is None:
                continue
            try:
                sink.write(response + "\n")
                sink.flush()
            except (BrokenPipeError, ValueError):  # 宿主提前关闭管道
                log("stdout 已关闭，退出服务")
                return 0
    except KeyboardInterrupt:  # pragma: no cover - 交互场景
        log("收到中断信号，退出服务")
    except (BrokenPipeError, ValueError):
        log("输入流已关闭，退出服务")
    finally:
        _LOG_STREAM = previous_log_stream
    log("stdio 服务已退出")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp_server.py",
        description="PMS 接口网关 MCP Server（stdio JSON-RPC 2.0，26 个变电专业接口工具）",
    )
    parser.add_argument("--spec", default=None, help="interfaces.json 路径（默认自动定位 expert-pack/spec/）")
    parser.add_argument("--auth-mode", default=None, help="鉴权模式：mock/none/appkey/token（默认读 PMS_AUTH_MODE）")
    parser.add_argument("--base-url", default=None, help="网关地址（默认读 PMS_GATEWAY_BASE_URL）")
    parser.add_argument("--timeout", type=float, default=None, help="请求超时秒数（默认读 PMS_TIMEOUT）")
    parser.add_argument("--retry", type=int, default=None, help="重试次数（默认读 PMS_RETRY）")
    parser.add_argument("--server-name", default=SERVER_NAME, help=argparse.SUPPRESS)
    parser.add_argument("--server-version", default=SERVER_VERSION, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = PmsConfig.from_env(
        base_url=args.base_url,
        auth_mode=args.auth_mode,
        timeout=args.timeout,
        retry=args.retry,
        spec_path=args.spec,
    )
    try:
        client = PmsClient(config)
    except PmsError as exc:
        log(f"启动失败：{exc}")
        return 1
    server = McpServer(client, server_name=args.server_name, server_version=args.server_version)
    return serve_stdio(server)


if __name__ == "__main__":
    sys.exit(main())
