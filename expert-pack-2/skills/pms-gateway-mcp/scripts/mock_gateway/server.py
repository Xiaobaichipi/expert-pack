"""本地模拟网关 HTTP 服务：ThreadingHTTPServer + 按 spec 注册 26 条路由。

架构
----
- 路由来自 :func:`pms_client.spec.load_spec`（``spec/interfaces.json`` 的 26 条
  ``method + path``），支持 ``/assetCenter/queryServices/{assetType}`` 这类路径参数；
- 鉴权由 :class:`mock_gateway.auth.MockAuth` 负责（token / appkey / none）；
- 数据由 :mod:`mock_gateway.data` 提供的 26 个处理函数返回（确定性、主键一致）；
- 统一响应 ``{"code":0,"message":"ok","data":...,"meta":{...}}``，列表接口
  ``data={"list":[...],"total":N,"pageNo":p,"pageSize":s}``；
- 未知路由 → HTTP 404 + JSON；方法不匹配 → HTTP 405 + JSON；
  认证失败 → HTTP 401/403 + JSON（客户端归一为 ``AUTH_FAILED``）；
  请求体非法 → HTTP 400 + JSON；处理异常 → HTTP 500 + JSON。

用法
----
进程内（测试推荐）::

    from mock_gateway.server import start_server
    server = start_server("127.0.0.1", 0, "token")
    ...  # server.base_url 形如 http://127.0.0.1:54321
    server.stop()

命令行::

    python pms_cli.py mock-server --host 127.0.0.1 --port 18080 --auth-mode token

环境变量（服务端）::

    PMS_MOCK_TOKEN / PMS_MOCK_APP_KEY / PMS_MOCK_APP_SECRET / PMS_MOCK_TIME_WINDOW
    PMS_MOCK_HOST / PMS_MOCK_PORT

注意：本模块只监听回环地址即用，默认绑定 ``127.0.0.1``，不要暴露到公网；
凭证为公开的模拟默认值，仅用于本地联调。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from pms_client.spec import InterfaceSpec, ToolSpec

from . import data
from .auth import AUTH_MODES, MockAuth

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MockGatewayServer",
    "make_routes",
    "start_server",
]

ENV_MOCK_HOST = "PMS_MOCK_HOST"
ENV_MOCK_PORT = "PMS_MOCK_PORT"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080
#: 路径参数占位符，如 ``{assetType}``
_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_METHOD_NOT_ALLOWED = 405
HTTP_INTERNAL_ERROR = 500


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
class Route:
    """一条路由：spec 的 method + path → 处理函数。"""

    __slots__ = ("tool_name", "method", "path", "pattern", "paged", "interface_code", "param_names")

    def __init__(self, tool: ToolSpec) -> None:
        self.tool_name = tool.name
        self.method = tool.method.upper()
        self.path = tool.path
        self.interface_code = tool.code
        self.paged = tool.name in data.PAGED_TOOLS
        self.param_names = tuple(tool.path_param_names)
        self.pattern = _compile_path(tool.path)

    def describe(self) -> dict[str, Any]:
        return {
            "tool": self.tool_name,
            "method": self.method,
            "path": self.path,
            "paged": self.paged,
            "interfaceCode": self.interface_code,
        }

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return "Route({} {})".format(self.method, self.path)


def _compile_path(template: str) -> "re.Pattern[str]":
    """把 ``/x/{assetType}/y`` 编译为正则，路径参数捕获为命名组。"""
    parts = _PATH_PARAM_RE.split(str(template or ""))
    chunks: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 0:  # 字面量
            chunks.append(re.escape(part))
        else:  # 参数名
            chunks.append("(?P<{}>[^/]+)".format(part))
    return re.compile("^" + "".join(chunks) + "$")


def make_routes(spec: InterfaceSpec) -> list[Route]:
    """按 spec 的 26 个工具生成路由，并校验数据层处理函数齐备。"""
    missing = [tool.name for tool in spec.tools if tool.name not in data.HANDLERS]
    if missing:
        raise RuntimeError(
            "mock_gateway.data 缺少以下工具的处理函数，无法注册路由：{}".format("、".join(missing))
        )
    extra = sorted(set(data.HANDLERS) - set(spec.tool_names))
    if extra:
        raise RuntimeError(
            "mock_gateway.data 存在 spec 未声明的处理函数：{}".format("、".join(extra))
        )
    return [Route(tool) for tool in spec.tools]


# ---------------------------------------------------------------------------
# 服务端
# ---------------------------------------------------------------------------
class MockGatewayServer:
    """本地模拟网关（可进程内启动/停止，便于单元测试）。"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        auth_mode: str = "token",
        *,
        token: str | None = None,
        app_key: str | None = None,
        app_secret: str | None = None,
        time_window_seconds: int | None = None,
        nonce_cache_size: int | None = None,
        spec: InterfaceSpec | None = None,
        spec_path: str | None = None,
        verbose: bool = False,
    ) -> None:
        if str(auth_mode).strip().lower() not in AUTH_MODES:
            raise ValueError(
                "auth_mode 非法：{!r}，可选值：{}".format(auth_mode, "、".join(AUTH_MODES))
            )
        self.host = str(host)
        self.requested_port = int(port)
        self.auth = MockAuth(
            auth_mode,
            token=token,
            app_key=app_key,
            app_secret=app_secret,
            time_window_seconds=time_window_seconds,
            nonce_cache_size=nonce_cache_size,
        )
        self.spec = spec or InterfaceSpec.load(spec_path)
        self.routes: list[Route] = make_routes(self.spec)
        self.verbose = bool(verbose)
        # 路由匹配顺序：字面量优先（路径参数越少越先匹配），避免
        # `/queryServices/{assetType}` 遮蔽 `/queryServices/getDeviceByUTCNum`
        # 这类字面量路径路由（后者会被参数化路由截获）。
        self._by_pattern = sorted(
            self.routes, key=lambda route: (len(route.param_names), route.path)
        )
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._actual_port = 0

    # -- 生命周期 -------------------------------------------------------
    def start(self) -> "MockGatewayServer":
        """绑定并启动后台服务线程，返回自身（支持 port=0 自动分配）。"""
        if self._httpd is not None:
            return self
        httpd = _GatewayHttpServer((self.host, self.requested_port), self)
        self._httpd = httpd
        self._actual_port = int(httpd.server_address[1])
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="pms-mock-gateway",
            daemon=True,
        )
        self._thread.start()
        self._stopped.clear()
        self._log(
            "mock gateway listening on {} (auth-mode={}, routes={})".format(
                self.base_url, self.auth.mode, len(self.routes)
            )
        )
        return self

    def stop(self) -> None:
        """停止服务并释放端口（可重复调用）。"""
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:  # pragma: no cover - 防御
                pass
            try:
                httpd.server_close()
            except Exception:  # pragma: no cover - 防御
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._stopped.set()

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞直到 :meth:`stop` 被调用（CLI 用）；超时返回 False。"""
        return self._stopped.wait(timeout)

    def __enter__(self) -> "MockGatewayServer":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    # -- 只读信息 -------------------------------------------------------
    @property
    def port(self) -> int:
        return self._actual_port or self.requested_port

    @property
    def auth_mode(self) -> str:
        return self.auth.mode

    @property
    def base_url(self) -> str:
        host = self.host
        if host in ("", "0.0.0.0", "::"):
            host = "127.0.0.1"
        return "http://{}:{}".format(host, self.port)

    def enumerate_routes(self) -> list[dict[str, Any]]:
        """路由清单（供 doctor / 文档 / 测试断言 26 条）。"""
        return [route.describe() for route in self.routes]

    def describe(self) -> dict[str, Any]:
        return {
            "baseUrl": self.base_url,
            "host": self.host,
            "port": self.port,
            "auth": self.auth.describe(),
            "routeCount": len(self.routes),
            "data": data.summarize(),
        }

    # -- 请求处理（与 HTTP 解耦，便于进程内测试） -----------------------
    def dispatch(
        self,
        method: str,
        target: str,
        headers: Any = None,
        body: bytes | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """处理一次请求，返回 ``(http_status, json_payload)``。

        :param target: 请求目标（可含 ``?query``），如 ``/assetCenter/...?assetId=X``
        :param headers: 请求头（dict 或 ``HTTPMessage``，大小写不敏感取值）
        :param body: 原始请求体字节（GET 为空）
        """
        method = str(method or "GET").upper()
        split = urllib.parse.urlsplit(str(target or "/"))
        raw_path = split.path or "/"
        decoded_path = urllib.parse.unquote(raw_path)
        query_pairs = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        query: dict[str, Any] = {}
        for key, value in query_pairs:
            query[key] = value

        # 1) 路由匹配：先按路径找（用于区分 404 / 405），再校验方法
        matched: Route | None = None
        path_matched: Route | None = None
        path_params: dict[str, str] = {}
        for route in self._by_pattern:
            result = route.pattern.match(decoded_path)
            if result is None:
                continue
            if path_matched is None:
                path_matched = route
                path_params = {key: urllib.parse.unquote(value) for key, value in result.groupdict().items()}
            if route.method == method:
                matched = route
                break
        if matched is None:
            if path_matched is not None:
                return self._error(
                    HTTP_METHOD_NOT_ALLOWED,
                    "方法不允许：路径 {} 仅支持 {}（收到 {}）".format(
                        decoded_path, path_matched.method, method
                    ),
                    path=decoded_path,
                    allowedMethod=path_matched.method,
                )
            return self._error(
                HTTP_NOT_FOUND,
                "未知路由：{} {}（本模拟网关仅注册 spec/interfaces.json 中的 {} 条路由）".format(
                    method, decoded_path, len(self.routes)
                ),
                path=decoded_path,
            )

        # 2) 鉴权（appkey 签名用请求行里的原始 path，与客户端签名口径一致）
        auth_result = self.auth.check(
            method=method,
            path=raw_path,
            query=query,
            raw_body=body,
            headers=headers,
        )
        if not auth_result.ok:
            return auth_result.status, auth_result.to_body()

        # 3) 请求体解析（POST 等）
        payload: dict[str, Any] = {}
        if body:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                return self._error(
                    HTTP_BAD_REQUEST,
                    "请求体不是合法 JSON：{}".format(exc),
                    tool=matched.tool_name,
                )
            if not isinstance(parsed, Mapping):
                return self._error(
                    HTTP_BAD_REQUEST,
                    "请求体必须是 JSON 对象（key-value），实际收到 {}".format(type(parsed).__name__),
                    tool=matched.tool_name,
                )
            payload = dict(parsed)

        # 4) 合并参数：query < path 参数 < body（同名以更“具体”的来源为准）
        params: dict[str, Any] = dict(query)
        params.update(path_params)
        params.update(payload)

        # 5) 取数并包装响应
        try:
            result = data.handle(matched.tool_name, params)
        except KeyError as exc:
            return self._error(HTTP_INTERNAL_ERROR, "模拟数据层缺少处理函数：{}".format(exc), tool=matched.tool_name)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            return self._error(
                HTTP_INTERNAL_ERROR,
                "模拟数据层处理异常：{}: {}".format(type(exc).__name__, exc),
                tool=matched.tool_name,
            )

        envelope: dict[str, Any] = {
            "code": 0,
            "message": "ok",
            "data": result,
            "meta": {
                "tool": matched.tool_name,
                "interfaceCode": matched.interface_code,
                "method": matched.method,
                "path": matched.path,
                "paged": matched.paged,
                "authMode": self.auth.mode,
                "server": "mock-gateway",
            },
        }
        return HTTP_OK, envelope

    # -- 内部 -----------------------------------------------------------
    @staticmethod
    def _error(status: int, message: str, **extra: Any) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {"code": status, "message": message, "data": None}
        payload.update(extra)
        return status, payload

    def _log(self, message: str) -> None:
        if self.verbose:
            sys.stderr.write("[pms-mock-gateway] {}\n".format(message))
            sys.stderr.flush()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return "MockGatewayServer(base_url={!r}, auth_mode={!r})".format(self.base_url, self.auth.mode)


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------
class _GatewayHttpServer(ThreadingHTTPServer):
    """把 :class:`MockGatewayServer` 挂到 ThreadingHTTPServer 上。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], gateway: MockGatewayServer) -> None:
        self.gateway = gateway
        super().__init__(server_address, _GatewayRequestHandler)


class _GatewayRequestHandler(BaseHTTPRequestHandler):
    """单次 HTTP 请求 → :meth:`MockGatewayServer.dispatch` → JSON 响应。"""

    server_version = "PmsMockGateway/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # 所有受支持的方法都走同一入口（路由层再判断方法是否允许）
    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch()

    def _dispatch(self) -> None:
        gateway: MockGatewayServer = getattr(self.server, "gateway")
        body = self._read_body()
        try:
            status, payload = gateway.dispatch(self.command, self.path, self.headers, body)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            status, payload = MockGatewayServer._error(
                HTTP_INTERNAL_ERROR, "模拟网关内部错误：{}: {}".format(type(exc).__name__, exc)
            )
        self._send_json(status, payload)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return b""
        try:
            return self.rfile.read(length)
        except Exception:  # pragma: no cover - 客户端提前断开
            return b""

    def _send_json(self, status: int, payload: Mapping[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-PMS-Mock", "1")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):  # pragma: no cover - 客户端提前断开
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 覆盖父类签名
        gateway = getattr(self.server, "gateway", None)
        if gateway is not None and gateway.verbose:
            sys.stderr.write(
                "[pms-mock-gateway] {} - {}\n".format(self.address_string(), format % args)
            )
            sys.stderr.flush()


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    auth_mode: str = "token",
    **kwargs: Any,
) -> MockGatewayServer:
    """创建并启动模拟网关，返回对象含 ``base_url`` / ``stop()``（测试直接用）。

    ``port=0`` 时由系统分配空闲端口，避免测试端口冲突。
    """
    server = MockGatewayServer(host, port, auth_mode, **kwargs)
    return server.start()


def _env_default(name: str, default: str) -> str:
    value = os.environ.get(name)
    return str(value).strip() if value and str(value).strip() else default


def resolve_host_port(host: str | None = None, port: int | None = None) -> tuple[str, int]:
    """CLI 参数缺省时回落到环境变量 ``PMS_MOCK_HOST`` / ``PMS_MOCK_PORT``。"""
    resolved_host = host or _env_default(ENV_MOCK_HOST, DEFAULT_HOST)
    if port is not None:
        return resolved_host, int(port)
    raw = _env_default(ENV_MOCK_PORT, str(DEFAULT_PORT))
    try:
        return resolved_host, int(raw)
    except ValueError:
        return resolved_host, DEFAULT_PORT
