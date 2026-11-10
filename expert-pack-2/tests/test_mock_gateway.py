"""模拟网关本地验收测试（二期 task-2）。

覆盖目标（与 ``docs/09-模拟网关与鉴权.md`` 的契约逐条对应）：

- 服务器启停：``start_server`` 导出、``port=0`` 自动分配 / 空闲端口复用 /
  ``setUpClass`` 启动 + ``tearDownClass`` 停止 / 上下文管理器 / 停止后释放端口；
- token 鉴权：26 个工具全量成功、envelope 形状、无/错 token → 401；
- appkey 鉴权：正确签名 200、错 secret / 时间戳越界 / nonce 重放 → 401/403；
- 路由与错误：未知路径 404 JSON、方法不符 405、非法请求体 400；
- 数据语义：分页生效、过滤、未知主键空结果、主键一致性、确定性；
- 断言强度：每个接口至少断言 ``code=0`` 与 ``data is not None``；
  列表接口断言 ``total``/``list`` 与分页字段；对象接口断言非空。

仅用标准库、离线运行；所有服务器都在用例内（或 ``tearDownClass``）停止，
不残留监听端口；不使用临时文件。

路由优先级回归：``/assetCenter/queryServices/{assetType}`` 参数化路由不得遮蔽
``/assetCenter/queryServices/getDeviceByUTCNum`` 字面量路由；由
``test_utc_num_lookup_route_not_shadowed`` 与
``test_all_routes_reachable_via_dispatch`` 两个用例共同守护。
"""

from __future__ import annotations

import json
import socket
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from _support import load_spec, make_config  # noqa: E402
from pms_client import ErrorCode, PmsClient, PmsError  # noqa: E402
from pms_client.signing import (  # noqa: E402
    HEADER_APP_KEY,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    build_appkey_signature,
)
from pms_client.transport import encode_query, substitute_path  # noqa: E402
from mock_gateway import data as mock_data  # noqa: E402
from mock_gateway.server import start_server  # noqa: E402

TOKEN = "mock-token-001"
APP_KEY = "mock-app-key"
APP_SECRET = "mock-app-secret"
SPEC_PATH = _TESTS_DIR.parent / "spec" / "interfaces.json"
STATUS_PORT = 18081

#: 26 个工具的**具体**调用参数（不用 spec.example_args() 里的 ``<占位符>``，
#: 避免对象接口因占位参数返回空对象而弱化断言）。
CALL_ARGS: dict[str, dict] = {
    "get_asset_by_id": {"assetId": "AST-102-0001"},
    "list_asset_params": {"assetType": "transformer"},
    "get_device_by_utc_num": {"utcNum": "UTC-2020-000123"},
    "list_psr_by_filters": {},
    "get_psr_by_id": {"psrId": "PSR-220-0001"},
    "get_device_tree_root": {},
    "get_device_tree_nodes": {"parentId": "ROOT"},
    "inquire_defect": {},
    "view_defect": {"defectId": "DF-2026-0001"},
    "list_hazard": {},
    "list_fault_trip_records": {},
    "get_repair_plan": {},
    "find_repair_test": {},
    "find_repair_program": {},
    "list_patrol_plan": {},
    "list_patrol_record": {},
    "list_test_item": {},
    "query_station_scale_analysis": {},
    "query_outage_incident": {},
    "query_open_capacity": {},
    "find_smart_device": {},
    "get_instrument_list": {},
    "get_manufacturer_infos": {},
    "query_svg_map_by_psr_id": {"psrId": "PSR-220-0001"},
    "search_power_path": {"psrId": "PSR-220-0001"},
    "analyze_supply_area": {"psrId": "PSR-220-0001"},
}

#: 分页接口 data 的结构（docs/09 第 6 节）
PAGED_DATA_KEYS = frozenset({"list", "total", "pageNo", "pageSize"})


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def token_headers(token: str = TOKEN) -> dict:
    return {"Authorization": "Bearer " + token}


def appkey_headers(
    method: str,
    path: str,
    query=None,
    body=None,
    *,
    app_key: str = APP_KEY,
    app_secret: str = APP_SECRET,
    timestamp=None,
    nonce=None,
) -> dict:
    """按 docs/09 §5.2 的 canonical 规范构造 4 个 appkey 请求头。"""
    ts = str(int(time.time() * 1000)) if timestamp is None else str(timestamp)
    nc = uuid.uuid4().hex if nonce is None else str(nonce)
    signature = build_appkey_signature(
        app_key=app_key,
        app_secret=app_secret,
        method=method,
        path=path,
        query=query or {},
        body=body,
        timestamp=ts,
        nonce=nc,
    )
    return {
        HEADER_APP_KEY: app_key,
        HEADER_TIMESTAMP: ts,
        HEADER_NONCE: nc,
        HEADER_SIGNATURE: signature,
    }


def http_json(server, method: str, target: str, headers=None, body=None):
    """发一次真实 HTTP 请求，返回 ``(status, payload, response_headers)``。"""
    request_headers = dict(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    request = urllib.request.Request(
        server.base_url + target,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw.decode("utf-8")), dict(exc.headers.items())


def can_connect(port: int) -> bool:
    """端口上是否有进程在监听（用于断言 stop() 后无残留监听）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def port_is_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def tool_request(tool, args: dict):
    """把工具调用参数拼成 ``(target, body)``，供 server.dispatch 使用。"""
    path_params = {key: value for key, value in args.items() if key in tool.path_param_names}
    path = substitute_path(tool.path, path_params)
    rest = {key: value for key, value in args.items() if key not in path_params}
    if tool.method in ("POST", "PUT", "PATCH"):
        body = json.dumps(rest, ensure_ascii=False).encode("utf-8") if rest else b"{}"
        return path, body
    query = encode_query(rest)
    return (path + ("?" + query if query else "")), None


def stable_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# 1. 服务器启停
# ---------------------------------------------------------------------------
class ServerLifecycleTest(unittest.TestCase):
    """start_server 导出、端口分配、停止与端口释放。"""

    def test_start_server_on_port_zero(self) -> None:
        server = start_server("127.0.0.1", 0, "token")
        try:
            self.assertGreater(server.port, 0)
            self.assertEqual(server.requested_port, 0)
            self.assertTrue(server.base_url.startswith("http://127.0.0.1:"))
            self.assertIn(str(server.port), server.base_url)
            self.assertEqual(server.auth_mode, "token")
            self.assertEqual(len(server.routes), 26)
        finally:
            server.stop()

    def test_start_server_on_explicit_free_port(self) -> None:
        first = start_server("127.0.0.1", 0, "token")
        port = first.port
        first.stop()
        self.assertTrue(port_is_free(port), "port={} 停止后应可再次绑定".format(port))
        second = start_server("127.0.0.1", port, "token")
        try:
            self.assertEqual(second.port, port)
            self.assertEqual(second.requested_port, port)
            status, payload = second.dispatch(
                "GET",
                "/assetCenter/queryServices/getAstById?assetId=AST-102-0001",
                token_headers(),
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["code"], 0)
        finally:
            second.stop()

    def test_start_server_on_status_port_when_available(self) -> None:
        if not port_is_free(STATUS_PORT):
            self.skipTest("端口 {} 已被占用，跳过固定端口用例".format(STATUS_PORT))
        server = start_server("127.0.0.1", STATUS_PORT, "token")
        try:
            self.assertEqual(server.port, STATUS_PORT)
            self.assertEqual(server.base_url, "http://127.0.0.1:{}".format(STATUS_PORT))
        finally:
            server.stop()

    def test_stop_releases_port(self) -> None:
        server = start_server("127.0.0.1", 0, "token")
        port = server.port
        self.assertTrue(can_connect(port))
        server.stop()
        self.assertFalse(can_connect(port), "stop() 后端口 {} 不应再监听".format(port))
        self.assertTrue(port_is_free(port), "stop() 后端口 {} 应可重新绑定".format(port))

    def test_stop_is_idempotent(self) -> None:
        server = start_server("127.0.0.1", 0, "token")
        server.stop()
        server.stop()  # 第二次调用不应抛异常
        self.assertFalse(can_connect(server.port))

    def test_context_manager_stops_server(self) -> None:
        with start_server("127.0.0.1", 0, "token") as server:
            status, payload = server.dispatch(
                "GET",
                "/assetCenter/queryServices/getAstById?assetId=AST-102-0001",
                token_headers(),
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["code"], 0)
            port = server.port
        self.assertFalse(can_connect(port), "退出 with 后不应残留监听")
        server.stop()  # 上下文退出后再调用也应安全

    def test_route_table_matches_spec(self) -> None:
        spec = load_spec()
        server = start_server("127.0.0.1", 0, "token")
        try:
            routes = server.enumerate_routes()
            self.assertEqual(len(routes), 26)
            route_pairs = {(route["method"], route["path"]) for route in routes}
            spec_pairs = {(tool.method, tool.path) for tool in spec.tools}
            self.assertEqual(route_pairs, spec_pairs)
            # 路由清单字段形状（doctor/测试依赖）
            for route in routes:
                self.assertEqual(
                    set(route),
                    {"tool", "method", "path", "paged", "interfaceCode"},
                )
            # 18 分页 + 8 对象
            self.assertEqual(sum(1 for route in routes if route["paged"]), 18)
            self.assertEqual(server.describe()["routeCount"], 26)
        finally:
            server.stop()

    def test_data_layer_covers_spec_tools(self) -> None:
        spec = load_spec()
        self.assertEqual(set(mock_data.HANDLERS), set(spec.tool_names))
        self.assertEqual(len(mock_data.HANDLERS), 26)
        self.assertEqual(len(mock_data.PAGED_TOOLS), 18)
        self.assertEqual(mock_data.HANDLERS["get_asset_by_id"], mock_data.handle_get_asset_by_id)
        summary = mock_data.summarize()
        self.assertEqual(summary["toolCount"], 26)
        self.assertEqual(summary["pagedToolCount"], 18)
        self.assertEqual(summary["objectToolCount"], 8)
        self.assertEqual(summary["stations"], 4)
        self.assertEqual(summary["assets"], 9)


# ---------------------------------------------------------------------------
# 2. token 模式：26 工具全量成功 + envelope 形状
# ---------------------------------------------------------------------------
class GatewayTestCase(unittest.TestCase):
    """进程内启动模拟网关（默认 token），tearDownClass 统一停止。"""

    AUTH_MODE = "token"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.spec = load_spec()
        cls.server = start_server("127.0.0.1", 0, cls.AUTH_MODE)
        cls.client = cls.make_gateway_client()

    @classmethod
    def make_gateway_client(cls) -> PmsClient:
        overrides = {"base_url": cls.server.base_url, "auth_mode": cls.AUTH_MODE}
        if cls.AUTH_MODE == "token":
            overrides["token"] = cls.server.auth.token
        elif cls.AUTH_MODE == "appkey":
            overrides["app_key"] = cls.server.auth.app_key
            overrides["app_secret"] = cls.server.auth.app_secret
        return PmsClient(make_config(**overrides), spec=cls.spec)

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "server", None) is not None:
            cls.server.stop()
            cls.server = None
        super().tearDownClass()


class TokenEnvelopeTest(GatewayTestCase):
    """token 鉴权下 26 个工具全部成功，响应 envelope 形状正确。"""

    def test_call_args_cover_all_spec_tools(self) -> None:
        self.assertEqual(set(CALL_ARGS), set(self.spec.tool_names))
        self.assertEqual(len(CALL_ARGS), 26)

    def test_all_26_tools_succeed_with_token(self) -> None:
        for tool in self.spec.tools:
            with self.subTest(tool=tool.name):
                response = self.client.call_tool(tool.name, CALL_ARGS[tool.name])
                # 每个接口至少：code=0、data 非 None
                self.assertEqual(response["code"], 0)
                self.assertIsNotNone(response["data"])
                self.assertIsInstance(response["message"], str)
                self.assertTrue(response["message"])
                self.assertIsInstance(response["data"], dict)
                self.assertTrue(response["data"], "{} 的 data 不应为空".format(tool.name))
                # meta 由客户端补齐
                self.assertIsInstance(response.get("meta"), dict)
                self.assertEqual(response["meta"]["tool"], tool.name)
                self.assertEqual(response["meta"]["interfaceCode"], tool.code)
                self.assertEqual(response["meta"]["authMode"], "token")

    def test_paged_tools_expose_total_and_list(self) -> None:
        paged_tools = [tool for tool in self.spec.tools if tool.is_paged]
        self.assertEqual(len(paged_tools), 18)
        for tool in paged_tools:
            with self.subTest(tool=tool.name):
                response = self.client.call_tool(tool.name, CALL_ARGS[tool.name])
                data = response["data"]
                self.assertEqual(set(data), set(PAGED_DATA_KEYS))
                self.assertIsInstance(data["list"], list)
                self.assertIsInstance(data["total"], int)
                self.assertGreaterEqual(data["total"], 1, "默认调用应命中模拟数据")
                self.assertGreaterEqual(len(data["list"]), 1)
                self.assertEqual(data["pageNo"], 1)
                self.assertGreaterEqual(data["pageSize"], 1)
                self.assertLessEqual(len(data["list"]), data["pageSize"])

    def test_object_tools_return_object_payloads(self) -> None:
        object_tools = [tool for tool in self.spec.tools if not tool.is_paged]
        self.assertEqual(len(object_tools), 8)
        for tool in object_tools:
            with self.subTest(tool=tool.name):
                data = self.client.call_tool(tool.name, CALL_ARGS[tool.name])["data"]
                self.assertIsInstance(data, dict)
                self.assertTrue(data, "{} 应返回非空对象".format(tool.name))

    def test_spot_check_known_values(self) -> None:
        asset = self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})["data"]
        self.assertEqual(asset["assetId"], "AST-102-0001")
        self.assertEqual(asset["assetName"], "1号主变")
        self.assertEqual(asset["stationId"], "STA-220-01")
        self.assertEqual(asset["psrId"], "PSR-220-0001")
        psr = self.client.call_tool("get_psr_by_id", {"psrId": "PSR-220-0001"})["data"]
        self.assertEqual(psr["assetId"], "AST-102-0001")
        self.assertEqual(psr["topoNodeId"], "TOPO-220-0001")
        self.assertEqual(psr["graphicId"], "GEO-220-0001")
        svg = self.client.call_tool("query_svg_map_by_psr_id", {"psrId": "PSR-220-0001"})["data"]
        self.assertIn("DEMO SVG", svg["svgContent"])
        root = self.client.call_tool("get_device_tree_root")["data"]
        self.assertEqual(root["nodeId"], "ROOT")
        self.assertEqual(root["childrenCount"], 4)
        path = self.client.call_tool("search_power_path", {"psrId": "PSR-220-0001"})["data"]
        self.assertEqual(path["sourcePsrId"], "PSR-500-0001")
        self.assertEqual(path["pathNodes"][-1]["psrId"], "PSR-220-0001")

    def test_raw_http_envelope_shape(self) -> None:
        status, payload, headers = http_json(
            self.server,
            "GET",
            "/assetCenter/queryServices/getAstById?assetId=AST-102-0001",
            token_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"code", "message", "data", "meta"})
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["message"], "ok")
        self.assertEqual(payload["data"]["assetId"], "AST-102-0001")
        meta = payload["meta"]
        self.assertEqual(meta["tool"], "get_asset_by_id")
        self.assertEqual(meta["interfaceCode"], "pgp-102-2411-00102")
        self.assertEqual(meta["method"], "GET")
        self.assertEqual(meta["path"], "/assetCenter/queryServices/getAstById")
        self.assertFalse(meta["paged"])
        self.assertEqual(meta["authMode"], "token")
        self.assertEqual(meta["server"], "mock-gateway")
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("X-PMS-Mock"), "1")

    def test_paged_raw_http_meta_flags_paged(self) -> None:
        status, payload, _ = http_json(
            self.server,
            "POST",
            "/WMCenter/defect/inquireDefect",
            token_headers(),
            body={"pageSize": 2},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["meta"]["paged"])
        self.assertEqual(payload["data"]["pageSize"], 2)
        self.assertEqual(len(payload["data"]["list"]), 2)
        self.assertEqual(payload["data"]["total"], 6)


# ---------------------------------------------------------------------------
# 3. token 反例：无 / 错 / 格式非法 → 401
# ---------------------------------------------------------------------------
class TokenNegativeTest(GatewayTestCase):
    TARGET = "/assetCenter/queryServices/getAstById?assetId=AST-102-0001"

    def assert_unauthorized(self, status: int, payload: dict) -> None:
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], 401)
        self.assertIsInstance(payload["message"], str)
        self.assertTrue(payload["message"])

    def test_valid_token_accepted(self) -> None:
        status, payload, _ = http_json(self.server, "GET", self.TARGET, token_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["assetId"], "AST-102-0001")

    def test_missing_authorization_is_401(self) -> None:
        status, payload, _ = http_json(self.server, "GET", self.TARGET)
        self.assert_unauthorized(status, payload)
        self.assertIn("缺少", payload["message"])
        self.assertIsNone(payload.get("data"))

    def test_wrong_token_is_401(self) -> None:
        status, payload, _ = http_json(self.server, "GET", self.TARGET, token_headers("wrong-token"))
        self.assert_unauthorized(status, payload)
        self.assertIn("token 无效", payload["message"])

    def test_malformed_authorization_scheme_is_401(self) -> None:
        status, payload, _ = http_json(
            self.server, "GET", self.TARGET, {"Authorization": "mock-token-001"}
        )
        self.assertEqual(status, 401)
        self.assertIn("格式非法", payload["message"])
        status, payload, _ = http_json(
            self.server, "GET", self.TARGET, {"Authorization": "Bearer "}
        )
        self.assertEqual(status, 401)
        self.assertIn("格式非法", payload["message"])

    def test_client_normalizes_401_to_auth_failed(self) -> None:
        client = PmsClient(
            make_config(base_url=self.server.base_url, auth_mode="token", token="wrong-token"),
            spec=self.spec,
        )
        with self.assertRaises(PmsError) as ctx:
            client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        self.assertEqual(ctx.exception.code, ErrorCode.AUTH_FAILED)
        self.assertEqual(ctx.exception.http_status, 401)


# ---------------------------------------------------------------------------
# 4. appkey 模式：签名 / 时间窗 / 重放矩阵
# ---------------------------------------------------------------------------
class AppKeyAuthTest(GatewayTestCase):
    AUTH_MODE = "appkey"
    PATH = "/assetCenter/queryServices/getAstById"
    QUERY = {"assetId": "AST-102-0001"}
    TARGET = PATH + "?assetId=AST-102-0001"

    def test_appkey_client_succeeds(self) -> None:
        response = self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        self.assertEqual(response["code"], 0)
        self.assertEqual(response["data"]["psrId"], "PSR-220-0001")
        self.assertEqual(response["meta"]["authMode"], "appkey")

    def test_appkey_client_runs_all_26_tools(self) -> None:
        for tool in self.spec.tools:
            with self.subTest(tool=tool.name):
                response = self.client.call_tool(tool.name, CALL_ARGS[tool.name])
                self.assertEqual(response["code"], 0)
                self.assertIsNotNone(response["data"])
                self.assertTrue(response["data"])
                if tool.is_paged:
                    self.assertEqual(set(response["data"]), set(PAGED_DATA_KEYS))
                    self.assertIsInstance(response["data"]["list"], list)
                    self.assertIsInstance(response["data"]["total"], int)

    def test_correct_signature_is_200(self) -> None:
        headers = appkey_headers("GET", self.PATH, self.QUERY)
        self.assertEqual(set(headers), {HEADER_APP_KEY, HEADER_TIMESTAMP, HEADER_NONCE, HEADER_SIGNATURE})
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 200)
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["assetId"], "AST-102-0001")

    def test_post_body_signature_is_200(self) -> None:
        path = "/WMCenter/defect/inquireDefect"
        body = {"stationId": "STA-220-01", "pageSize": 2}
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = appkey_headers("POST", path, None, raw)
        status, payload, _ = http_json(self.server, "POST", path, headers, body=raw)
        self.assertEqual(status, 200)
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["total"], 5)
        self.assertEqual(len(payload["data"]["list"]), 2)

    def test_chinese_path_query_and_body_signatures(self) -> None:
        # 中文路径参数（percent-encode 口径）
        quoted_path = "/assetCenter/queryServices/" + urllib.parse.quote("变压器", safe="")
        headers = appkey_headers("GET", quoted_path, {})
        status, payload, _ = http_json(self.server, "GET", quoted_path, headers)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["total"], 4)
        # 中文 query 值
        query = {"deviceType": "变压器"}
        path = "/WMCenter/test/testItemList"
        headers = appkey_headers("GET", path, query)
        target = path + "?" + encode_query(query)
        status, payload, _ = http_json(self.server, "GET", target, headers)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["data"]["total"], 1)
        for item in payload["data"]["list"]:
            self.assertEqual(item["deviceType"], "变压器")
        # 中文 body 值
        body = {"hazardType": "外部"}
        path = "/WMCenter/hazard/listHazard"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = appkey_headers("POST", path, None, raw)
        status, payload, _ = http_json(self.server, "POST", path, headers, body=raw)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["total"], 2)
        for item in payload["data"]["list"]:
            self.assertEqual(item["hazardType"], "外部")

    def test_wrong_secret_is_401(self) -> None:
        headers = appkey_headers("GET", self.PATH, self.QUERY, app_secret="wrong-secret")
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], 401)
        self.assertIn("签名校验失败", payload["message"])

    def test_expired_timestamp_is_401(self) -> None:
        old_timestamp = str(int(time.time() * 1000) - 301 * 1000)
        headers = appkey_headers("GET", self.PATH, self.QUERY, timestamp=old_timestamp)
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], 401)
        self.assertIn("时间戳超出允许窗口", payload["message"])

    def test_future_timestamp_is_401(self) -> None:
        future_timestamp = str(int(time.time() * 1000) + 301 * 1000)
        headers = appkey_headers("GET", self.PATH, self.QUERY, timestamp=future_timestamp)
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 401)
        self.assertIn("时间戳超出允许窗口", payload["message"])

    def test_replayed_nonce_is_403(self) -> None:
        headers = appkey_headers("GET", self.PATH, self.QUERY)
        first_status, first_payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(first_status, 200)
        self.assertEqual(first_payload["code"], 0)
        second_status, second_payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(second_status, 403, "同一 nonce 二次使用应被判定重放")
        self.assertEqual(second_payload["code"], 403)
        self.assertIn("nonce", second_payload["message"].lower())
        self.assertIn("重放", second_payload["message"])

    def test_missing_appkey_header_is_401(self) -> None:
        headers = appkey_headers("GET", self.PATH, self.QUERY)
        headers.pop(HEADER_SIGNATURE)
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 401)
        self.assertIn("缺少 appkey 鉴权请求头", payload["message"])
        self.assertIn(HEADER_SIGNATURE, payload["message"])

    def test_wrong_app_key_is_401(self) -> None:
        headers = appkey_headers("GET", self.PATH, self.QUERY, app_key="other-app-key")
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 401)
        self.assertIn("appKey 无效", payload["message"])

    def test_malformed_timestamp_is_401(self) -> None:
        headers = appkey_headers("GET", self.PATH, self.QUERY, timestamp="not-a-millisecond")
        status, payload, _ = http_json(self.server, "GET", self.TARGET, headers)
        self.assertEqual(status, 401)
        self.assertIn("时间戳非法", payload["message"])

    def test_client_wrong_secret_maps_to_auth_failed(self) -> None:
        client = PmsClient(
            make_config(
                base_url=self.server.base_url,
                auth_mode="appkey",
                app_key=self.server.auth.app_key,
                app_secret="wrong-secret",
            ),
            spec=self.spec,
        )
        with self.assertRaises(PmsError) as ctx:
            client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        self.assertEqual(ctx.exception.code, ErrorCode.AUTH_FAILED)
        self.assertEqual(ctx.exception.http_status, 401)


# ---------------------------------------------------------------------------
# 5. 路由 / 错误响应
# ---------------------------------------------------------------------------
class RoutingErrorTest(GatewayTestCase):
    def test_unknown_path_returns_404_json(self) -> None:
        status, payload, headers = http_json(self.server, "GET", "/no/such/route", token_headers())
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], 404)
        self.assertIsNone(payload["data"])
        self.assertEqual(payload["path"], "/no/such/route")
        self.assertIn("未知路由", payload["message"])
        self.assertIn("application/json", headers.get("Content-Type", ""))

    def test_health_and_root_are_404(self) -> None:
        for target in ("/health", "/"):
            with self.subTest(target=target):
                status, payload, _ = http_json(self.server, "GET", target, token_headers())
                self.assertEqual(status, 404)
                self.assertEqual(payload["code"], 404)

    def test_method_not_allowed_returns_405_json(self) -> None:
        status, payload, _ = http_json(
            self.server,
            "GET",
            "/PSRCenter/queryServices/listPropertiesByFilters",
            token_headers(),
        )
        self.assertEqual(status, 405)
        self.assertEqual(payload["code"], 405)
        self.assertEqual(payload["allowedMethod"], "POST")
        self.assertIn("方法不允许", payload["message"])

    def test_invalid_json_body_returns_400(self) -> None:
        status, payload, _ = http_json(
            self.server,
            "POST",
            "/WMCenter/defect/inquireDefect",
            token_headers(),
            body=b"{not-json}",
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], 400)
        self.assertIn("JSON", payload["message"])

    def test_non_object_json_body_returns_400(self) -> None:
        status, payload, _ = http_json(
            self.server,
            "POST",
            "/WMCenter/defect/inquireDefect",
            token_headers(),
            body=b"[1, 2, 3]",
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], 400)
        self.assertIn("JSON 对象", payload["message"])

    def test_dispatch_unknown_route_and_method(self) -> None:
        status, payload = self.server.dispatch("GET", "/no/such/route", token_headers())
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], 404)
        status, payload = self.server.dispatch(
            "GET", "/WMCenter/defect/inquireDefect", token_headers()
        )
        self.assertEqual(status, 405)
        self.assertEqual(payload["allowedMethod"], "POST")


# ---------------------------------------------------------------------------
# 6. 分页与过滤
# ---------------------------------------------------------------------------
class PagingAndFilterTest(GatewayTestCase):
    def test_pagination_pages_are_disjoint_and_total_stable(self) -> None:
        pages = []
        for page_no in (1, 2, 3, 4):
            data = self.client.call_tool(
                "list_psr_by_filters", {"pageNo": page_no, "pageSize": 4}
            )["data"]
            self.assertEqual(data["total"], 9)
            self.assertEqual(data["pageNo"], page_no)
            self.assertEqual(data["pageSize"], 4)
            self.assertLessEqual(len(data["list"]), 4)
            pages.append([item["psrId"] for item in data["list"]])
        self.assertEqual([len(page) for page in pages], [4, 4, 1, 0])
        flattened = [psr_id for page in pages for psr_id in page]
        self.assertEqual(len(flattened), 9)
        self.assertEqual(len(set(flattened)), 9, "分页不应重复条目")

    def test_paging_beyond_last_page_is_empty_but_total_kept(self) -> None:
        data = self.client.call_tool(
            "inquire_defect", {"pageNo": 99, "pageSize": 20}
        )["data"]
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["list"], [])
        self.assertEqual(data["pageNo"], 99)

    def test_invalid_paging_falls_back_to_defaults(self) -> None:
        data = self.client.call_tool(
            "list_psr_by_filters", {"pageNo": 0, "pageSize": 0}
        )["data"]
        self.assertEqual(data["pageNo"], 1)
        self.assertEqual(data["pageSize"], 20)
        data = self.client.call_tool("list_psr_by_filters", {"pageSize": -5})["data"]
        self.assertEqual(data["pageSize"], 20)

    def test_page_size_is_capped(self) -> None:
        data = self.client.call_tool("list_psr_by_filters", {"pageSize": 1000})["data"]
        self.assertEqual(data["pageSize"], 500)
        self.assertEqual(data["total"], 9)
        self.assertEqual(len(data["list"]), 9)

    def test_exact_and_fuzzy_filters(self) -> None:
        defects = self.client.call_tool("inquire_defect", {"defectLevel": "严重"})["data"]
        self.assertEqual(defects["total"], 2)
        for item in defects["list"]:
            self.assertEqual(item["defectLevel"], "严重")
        hazards = self.client.call_tool("list_hazard", {"riskLevel": "重大"})["data"]
        self.assertEqual(hazards["total"], 1)
        self.assertEqual(hazards["list"][0]["hazardId"], "HZ-2026-0003")
        psr_rows = self.client.call_tool(
            "list_psr_by_filters", {"stationId": "STA-220-01"}
        )["data"]
        self.assertEqual(psr_rows["total"], 5)
        for item in psr_rows["list"]:
            self.assertEqual(item["stationId"], "STA-220-01")
        manufacturers = self.client.call_tool(
            "get_manufacturer_infos", {"manufacturerName": "电工"}
        )["data"]
        self.assertEqual(manufacturers["total"], 1)
        self.assertEqual(manufacturers["list"][0]["manufacturerName"], "特变电工")
        smart = self.client.call_tool("find_smart_device", {"onlineStatus": "在线"})["data"]
        self.assertEqual(smart["total"], 2)
        for item in smart["list"]:
            self.assertEqual(item["onlineStatus"], "在线")

    def test_chinese_path_param_asset_type(self) -> None:
        data = self.client.call_tool("list_asset_params", {"assetType": "变压器"})["data"]
        self.assertEqual(data["total"], 4)
        for item in data["list"]:
            self.assertEqual(item["deviceType"], "变压器")

    def test_time_range_filters(self) -> None:
        defects = self.client.call_tool(
            "inquire_defect", {"startTime": "2026-09-01", "endTime": "2026-09-30"}
        )["data"]
        self.assertEqual(defects["total"], 4)
        for item in defects["list"]:
            self.assertTrue("2026-09-01" <= item["discoverTime"][:10] <= "2026-09-30")
        plans = self.client.call_tool("get_repair_plan", {"year": 2025})["data"]
        self.assertEqual(plans["total"], 1)
        for item in plans["list"]:
            self.assertTrue(item["planStartDate"].startswith("2025"))

    def test_range_intersection_filter(self) -> None:
        plans = self.client.call_tool(
            "list_patrol_plan", {"startDate": "2026-10-01", "endDate": "2026-10-31"}
        )["data"]
        self.assertEqual(plans["total"], 2)
        for item in plans["list"]:
            self.assertTrue(item["startDate"] <= "2026-10-31")
            self.assertTrue(item["endDate"] >= "2026-10-01")


# ---------------------------------------------------------------------------
# 7. 未知主键 / 主键一致性
# ---------------------------------------------------------------------------
class PrimaryKeyConsistencyTest(GatewayTestCase):
    def test_unknown_primary_keys_return_empty_not_error(self) -> None:
        object_cases = (
            ("get_asset_by_id", {"assetId": "NOPE"}),
            ("get_psr_by_id", {"psrId": "NOPE"}),
            ("get_device_by_utc_num", {"utcNum": "NOPE"}),
            ("view_defect", {"defectId": "NOPE"}),
            ("query_svg_map_by_psr_id", {"psrId": "NOPE"}),
            ("search_power_path", {"psrId": "NOPE"}),
            ("analyze_supply_area", {"psrId": "NOPE"}),
        )
        for tool_name, args in object_cases:
            with self.subTest(tool=tool_name):
                response = self.client.call_tool(tool_name, args)
                self.assertEqual(response["code"], 0)
                self.assertEqual(response["data"], {})

    def test_unknown_primary_keys_return_empty_list(self) -> None:
        list_cases = (
            ("list_psr_by_filters", {"stationId": "NOPE"}),
            ("inquire_defect", {"deviceId": "NOPE"}),
            ("list_fault_trip_records", {"deviceId": "NOPE"}),
            ("get_repair_plan", {"deviceId": "NOPE"}),
            ("find_repair_test", {"deviceId": "NOPE"}),
            ("find_repair_program", {"deviceId": "NOPE"}),
            ("query_open_capacity", {"deviceId": "NOPE"}),
            ("find_smart_device", {"stationId": "NOPE"}),
            ("get_instrument_list", {"stationId": "NOPE"}),
            ("get_manufacturer_infos", {"manufacturerName": "不存在的厂家"}),
        )
        for tool_name, args in list_cases:
            with self.subTest(tool=tool_name):
                response = self.client.call_tool(tool_name, args)
                self.assertEqual(response["code"], 0)
                self.assertEqual(response["data"]["total"], 0)
                self.assertEqual(response["data"]["list"], [])

    def test_group1_transformer_primary_keys_consistent(self) -> None:
        asset = self.client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})["data"]
        self.assertEqual(asset["psrId"], "PSR-220-0001")
        self.assertEqual(asset["utcNum"], "UTC-2020-000123")
        self.assertEqual(asset["stationId"], "STA-220-01")
        psr = self.client.call_tool("get_psr_by_id", {"psrId": asset["psrId"]})["data"]
        self.assertEqual(psr["assetId"], asset["assetId"])
        self.assertEqual(psr["topoNodeId"], asset["topoNodeId"])
        self.assertEqual(psr["graphicId"], asset["graphicId"])
        # 缺陷：按 assetId / psrId 查到的都是同一台设备
        by_asset = self.client.call_tool("inquire_defect", {"deviceId": asset["assetId"]})["data"]
        by_psr = self.client.call_tool("inquire_defect", {"deviceId": asset["psrId"]})["data"]
        self.assertEqual(by_asset["total"], 1)
        self.assertEqual(by_asset["total"], by_psr["total"])
        defect = by_asset["list"][0]
        self.assertEqual(defect["defectId"], "DF-2026-0001")
        self.assertEqual(defect["psrId"], asset["psrId"])
        self.assertEqual(defect["stationId"], asset["stationId"])
        # 检修 / 故障 / 可靠性 / 容量都指向同一台设备
        repairs = self.client.call_tool("get_repair_plan", {"deviceId": asset["psrId"]})["data"]["list"]
        self.assertTrue(repairs)
        for item in repairs:
            self.assertEqual(item["deviceId"], asset["assetId"])
            self.assertEqual(item["psrId"], asset["psrId"])
        faults = self.client.call_tool("list_fault_trip_records", {"deviceId": asset["assetId"]})["data"]["list"]
        self.assertTrue(faults)
        for item in faults:
            self.assertEqual(item["deviceId"], asset["assetId"])
            self.assertEqual(item["psrId"], asset["psrId"])
        capacities = self.client.call_tool("query_open_capacity", {"deviceId": asset["assetId"]})["data"]["list"]
        self.assertTrue(capacities)
        for item in capacities:
            self.assertEqual(item["deviceId"], asset["assetId"])
            self.assertEqual(item["psrId"], asset["psrId"])
        # 拓扑：专题图 / 供电路径 / 供电范围
        svg = self.client.call_tool("query_svg_map_by_psr_id", {"psrId": asset["psrId"]})["data"]
        self.assertEqual(svg["graphicId"], asset["graphicId"])
        path = self.client.call_tool("search_power_path", {"deviceId": asset["assetId"]})["data"]
        self.assertEqual(path["psrId"], asset["psrId"])
        self.assertEqual(path["pathNodes"][-1]["psrId"], asset["psrId"])
        area = self.client.call_tool("analyze_supply_area", {"psrId": asset["psrId"]})["data"]
        self.assertEqual(area["psrId"], asset["psrId"])
        self.assertGreater(area["affectedCount"], 0)

    def test_group2_breaker_primary_keys_consistent(self) -> None:
        asset = self.client.call_tool("get_asset_by_id", {"assetId": "AST-103-0101"})["data"]
        self.assertEqual(asset["psrId"], "PSR-220-0101")
        self.assertEqual(asset["utcNum"], "UTC-2020-000125")
        psr = self.client.call_tool("get_psr_by_id", {"psrId": asset["psrId"]})["data"]
        self.assertEqual(psr["assetId"], asset["assetId"])
        self.assertEqual(psr["topoNodeId"], "TOPO-220-0101")
        defects = self.client.call_tool("inquire_defect", {"deviceId": asset["psrId"]})["data"]["list"]
        self.assertTrue(defects)
        for item in defects:
            self.assertEqual(item["deviceId"], asset["assetId"])
            self.assertEqual(item["psrId"], asset["psrId"])
        path = self.client.call_tool("search_power_path", {"psrId": asset["psrId"]})["data"]
        self.assertEqual(path["psrId"], asset["psrId"])
        self.assertEqual(path["pathNodes"][-1]["psrId"], asset["psrId"])
        self.assertEqual(path["sourcePsrId"], "PSR-500-0001")
        area = self.client.call_tool("analyze_supply_area", {"deviceId": asset["assetId"]})["data"]
        self.assertEqual(area["psrId"], asset["psrId"])

    def test_device_tree_nodes_share_same_keys(self) -> None:
        root = self.client.call_tool("get_device_tree_root")["data"]
        self.assertEqual(root["nodeId"], "ROOT")
        stations = self.client.call_tool("get_device_tree_nodes", {"parentId": "ROOT"})["data"]
        self.assertEqual(stations["total"], 4)
        station_ids = {node["nodeId"] for node in stations["list"]}
        self.assertIn("STA-220-01", station_ids)
        levels = self.client.call_tool(
            "get_device_tree_nodes", {"parentId": "STA-220-01"}
        )["data"]
        self.assertEqual(levels["total"], 1)
        self.assertEqual(levels["list"][0]["nodeType"], "VOLTAGE_LEVEL")
        devices = self.client.call_tool(
            "get_device_tree_nodes", {"parentId": "STA-220-01#220kV"}
        )["data"]
        self.assertEqual(devices["total"], 5)
        tree_asset = next(
            node for node in devices["list"] if node["assetId"] == "AST-102-0001"
        )
        self.assertEqual(tree_asset["psrId"], "PSR-220-0001")
        self.assertEqual(tree_asset["nodeId"], "TREE-AST-102-0001")
        components = self.client.call_tool(
            "get_device_tree_nodes", {"parentId": "TREE-AST-102-0001"}
        )["data"]
        self.assertEqual(components["total"], 4)
        for component in components["list"]:
            self.assertEqual(component["assetId"], "AST-102-0001")
            self.assertEqual(component["nodeType"], "COMPONENT")

    def test_utc_num_lookup_route_not_shadowed(self) -> None:
        """路由优先级回归：``get_device_by_utc_num`` 不得被 ``{assetType}`` 路由遮蔽。

        ``/assetCenter/queryServices/{assetType}``（list_asset_params）与
        ``/assetCenter/queryServices/getDeviceByUTCNum``（get_device_by_utc_num）
        同前缀，若参数化路由先匹配，后者会被截获（``meta.tool`` 变成
        list_asset_params、返回空分页）。服务器现按「字面量优先（路径参数越少越先）」
        排序匹配，本用例锁定该行为。
        """
        direct = mock_data.handle("get_device_by_utc_num", {"utcNum": "UTC-2020-000123"})
        self.assertEqual(direct["assetId"], "AST-102-0001")
        status, payload, _ = http_json(
            self.server,
            "GET",
            "/assetCenter/queryServices/getDeviceByUTCNum?utcNum=UTC-2020-000123",
            token_headers(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["meta"]["tool"], "get_device_by_utc_num")
        self.assertEqual(payload["data"].get("assetId"), "AST-102-0001")
        self.assertEqual(payload["data"].get("utcNum"), "UTC-2020-000123")
        # 未知实物 ID → 空对象（可达后才验证得到）
        unknown_status, unknown_payload, _ = http_json(
            self.server,
            "GET",
            "/assetCenter/queryServices/getDeviceByUTCNum?utcNum=UTC-NOT-EXIST",
            token_headers(),
        )
        self.assertEqual(unknown_status, 200)
        self.assertEqual(unknown_payload["meta"]["tool"], "get_device_by_utc_num")
        self.assertEqual(unknown_payload["data"], {})

    def test_all_routes_reachable_via_dispatch(self) -> None:
        mismatches = []
        statuses = []
        for tool in self.spec.tools:
            target, body = tool_request(tool, CALL_ARGS[tool.name])
            status, payload = self.server.dispatch(tool.method, target, token_headers(), body)
            statuses.append(status)
            if payload.get("meta", {}).get("tool") != tool.name:
                mismatches.append(tool.name)
        self.assertEqual(set(statuses), {200})
        # 26 条路由必须全部命中自己的处理函数（字面量不得被参数化路由遮蔽）
        self.assertEqual(mismatches, [], "以下路由被错误路由处理：{}".format(mismatches))


# ---------------------------------------------------------------------------
# 8. 确定性
# ---------------------------------------------------------------------------
class DeterminismTest(GatewayTestCase):
    def test_dispatch_same_request_twice_is_identical(self) -> None:
        first = self.server.dispatch(
            "POST",
            "/WMCenter/defect/inquireDefect",
            token_headers(),
            b'{"stationId":"STA-220-01","pageSize":3}',
        )
        second = self.server.dispatch(
            "POST",
            "/WMCenter/defect/inquireDefect",
            token_headers(),
            b'{"stationId":"STA-220-01","pageSize":3}',
        )
        self.assertEqual(first[0], 200)
        self.assertEqual(stable_json(first[1]), stable_json(second[1]))

    def test_client_same_request_twice_is_identical(self) -> None:
        args = {"stationId": "STA-220-01", "pageSize": 3}
        first = self.client.call_tool("inquire_defect", args)
        second = self.client.call_tool("inquire_defect", args)
        self.assertEqual(stable_json(first["data"]), stable_json(second["data"]))
        self.assertEqual(first["code"], second["code"])

    def test_response_meta_has_no_volatile_fields(self) -> None:
        status, payload, _ = http_json(
            self.server, "GET", "/assetCenter/queryServices/getAstById?assetId=AST-102-0001", token_headers()
        )
        self.assertEqual(status, 200)
        meta = payload["meta"]
        self.assertEqual(
            set(meta),
            {"tool", "interfaceCode", "method", "path", "paged", "authMode", "server"},
        )
        for key in ("serverTime", "timestamp", "time", "requestId", "nonce"):
            self.assertNotIn(key, meta)

    def test_all_paged_tools_deterministic_across_calls(self) -> None:
        for tool in (tool for tool in self.spec.tools if tool.is_paged):
            with self.subTest(tool=tool.name):
                first = self.client.call_tool(tool.name, CALL_ARGS[tool.name])["data"]
                second = self.client.call_tool(tool.name, CALL_ARGS[tool.name])["data"]
                self.assertEqual(stable_json(first), stable_json(second))
                self.assertEqual(first["total"], second["total"])
                self.assertEqual(len(first["list"]), len(second["list"]))


# ---------------------------------------------------------------------------
# 9. none 模式（网关侧免鉴权）
# ---------------------------------------------------------------------------
class NoneAuthModeTest(unittest.TestCase):
    def test_none_mode_needs_no_authorization(self) -> None:
        server = start_server("127.0.0.1", 0, "none")
        try:
            status, payload, _ = http_json(
                server,
                "GET",
                "/assetCenter/queryServices/getAstById?assetId=AST-102-0001",
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["code"], 0)
            self.assertEqual(payload["data"]["assetId"], "AST-102-0001")
            self.assertEqual(payload["meta"]["authMode"], "none")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
