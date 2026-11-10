"""本地可鉴权模拟网关（expert-pack-2 二期）。

把 ``spec/interfaces.json`` 的 26 个 PMS 接口在本地以**真实 HTTP** 跑起来，
并支持 token / appkey / none 三种鉴权，让 ``pms_client`` 走完整的网络+鉴权链路
（而不是 mock 直出），便于端到端验证 CLI / MCP / 上层问数技能。

组件
----
- :mod:`mock_gateway.data`    26 个接口的确定性模拟数据（虚构、主键一致）
- :mod:`mock_gateway.auth`    token / appkey / none 鉴权（appkey 复用 pms_client.signing）
- :mod:`mock_gateway.server`  ThreadingHTTPServer + 26 条路由（按 spec 注册）
- :mod:`pms_client.signing`   appkey 签名规范的唯一实现（客户端与服务端共用）

快速开始::

    from mock_gateway.server import start_server
    server = start_server("127.0.0.1", 0, "token")   # 端口 0 = 自动分配
    try:
        client = PmsClient(PmsConfig(
            base_url=server.base_url, auth_mode="token",
            token=server.auth.token, spec_path="<expert-pack-2>/spec/interfaces.json",
        ))
        print(client.get_asset_by_id("AST-102-0001")["data"]["assetName"])
    finally:
        server.stop()

命令行::

    python pms_cli.py mock-server --host 127.0.0.1 --port 18080 --auth-mode token
"""

from __future__ import annotations

from . import data
from .auth import AUTH_MODES, AuthResult, MockAuth
from .server import DEFAULT_HOST, DEFAULT_PORT, MockGatewayServer, Route, make_routes, start_server

#: 供 `from mock_gateway import signing` 使用（实现位于 pms_client.signing，单一实现）
from pms_client import signing  # noqa: E402  (放在最后，避免干扰包内导入顺序)

__version__ = "1.0.0"

__all__ = [
    # 服务
    "MockGatewayServer",
    "start_server",
    "make_routes",
    "Route",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    # 鉴权
    "MockAuth",
    "AuthResult",
    "AUTH_MODES",
    # 数据 / 签名
    "data",
    "signing",
    "__version__",
]
