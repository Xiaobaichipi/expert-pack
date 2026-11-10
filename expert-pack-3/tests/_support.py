"""测试公共支撑（不以 test_ 开头，unittest discover 不会当作用例收集）。

职责：把 ``skills/pms-gateway-mcp/scripts`` 插入 ``sys.path``（使 ``import pms_client`` /
``import mcp_server`` / ``import pms_cli`` 可用），并给出定位 spec 与构造客户端的工具函数。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

TESTS_DIR = Path(__file__).resolve().parent
PACK_DIR = TESTS_DIR.parent
SKILL_DIR = PACK_DIR / "skills" / "pms-gateway-mcp"
SCRIPTS_DIR = SKILL_DIR / "scripts"
SPEC_PATH = PACK_DIR / "spec" / "interfaces.json"

for _path in (str(SCRIPTS_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from pms_client import InterfaceSpec, MockBackend, PmsClient, PmsConfig, PmsError  # noqa: E402
from pms_client import errors as pms_errors  # noqa: E402
from pms_client import auth as pms_auth  # noqa: E402
from pms_client import transport as pms_transport  # noqa: E402

EXPECTED_TOOL_COUNT = 26
EXPECTED_GROUP_COUNTS = {
    "asset-ledger": 5,
    "device-tree": 2,
    "om-health": 4,
    "maintenance-test": 6,
    "reliability": 3,
    "resource-topology": 6,
}


def load_spec() -> InterfaceSpec:
    """加载专家包真实 spec（测试同时验证 spec 本身可用）。"""
    return InterfaceSpec.load(SPEC_PATH)


def make_config(**overrides: Any) -> PmsConfig:
    """构造 mock 模式配置（不读外部环境变量，保证测试确定）。"""
    defaults: dict[str, Any] = {
        "base_url": "",
        "auth_mode": "mock",
        "app_key": "",
        "app_secret": "",
        "token": "",
        "timeout": 5.0,
        "retry": 0,
        "spec_path": str(SPEC_PATH),
        "verify_ssl": True,
    }
    defaults.update(overrides)
    return PmsConfig(**defaults)


def make_client(**overrides: Any) -> PmsClient:
    return PmsClient(make_config(**overrides))


_shared_client: PmsClient | None = None


def shared_client() -> PmsClient:
    """进程内复用的 mock 客户端（供 MCP 协议测试构造 server）。"""
    global _shared_client
    if _shared_client is None:
        _shared_client = make_client()
    return _shared_client


class Capture:
    """同时捕获 stdout/stderr 的上下文管理器（用于 CLI / serve_stdio 测试）。"""

    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def __enter__(self) -> "Capture":
        self._out = redirect_stdout(self.stdout)
        self._err = redirect_stderr(self.stderr)
        self._out.__enter__()
        self._err.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._err.__exit__(exc_type, exc, tb)
        self._out.__exit__(exc_type, exc, tb)


class BaseTestCase(unittest.TestCase):
    """预置 spec / mock 客户端，并静默 MCP 初始化日志。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = load_spec()
        cls.client = PmsClient(make_config(), spec=cls.spec)

    def setUp(self) -> None:
        self._stderr_buffer = io.StringIO()
        self._stderr_ctx = redirect_stderr(self._stderr_buffer)
        self._stderr_ctx.__enter__()

    def tearDown(self) -> None:
        self._stderr_ctx.__exit__(None, None, None)
