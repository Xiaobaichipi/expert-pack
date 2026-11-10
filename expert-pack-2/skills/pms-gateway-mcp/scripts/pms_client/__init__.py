"""pms-gateway-mcp 客户端包（纯标准库，Python 3.10+）。

典型用法::

    from pms_client import PmsClient, PmsConfig

    client = PmsClient()                      # 默认 mock 模式，直接可跑
    resp = client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
    print(resp["data"]["assetName"])

    # 或使用同名显式方法
    resp = client.get_asset_by_id("AST-102-0001")

切换到真实网关只需设置环境变量（代码零改动）::

    PMS_GATEWAY_BASE_URL=https://pms-gateway.example.com
    PMS_AUTH_MODE=token
    PMS_TOKEN=<向中台申请的令牌>
"""

from __future__ import annotations

from .auth import (
    AppKeyAuthProvider,
    AuthProvider,
    MockAuthProvider,
    NoneAuthProvider,
    TokenAuthProvider,
    build_appkey_signature,
    create_auth_provider,
)
from .client import PmsClient, coerce_value, validate_arguments
from .config import (
    AUTH_MODES,
    DEFAULT_AUTH_MODE,
    ENV_APP_KEY,
    ENV_APP_SECRET,
    ENV_AUTH_MODE,
    ENV_BASE_URL,
    ENV_RETRY,
    ENV_SPEC_PATH,
    ENV_TIMEOUT,
    ENV_TOKEN,
    ENV_VERIFY_SSL,
    PmsConfig,
    find_spec_path,
)
from .errors import ErrorCode, PmsError
from .mock import MockBackend
from .spec import InterfaceSpec, ParamSpec, ToolSpec, load_spec
from .transport import (
    Transport,
    extract_list,
    extract_total,
    normalize_envelope,
    substitute_path,
)

__version__ = "1.0.0"
__all__ = [
    # 客户端
    "PmsClient",
    "PmsConfig",
    "PmsError",
    "ErrorCode",
    # 规格
    "InterfaceSpec",
    "ToolSpec",
    "ParamSpec",
    "load_spec",
    # 鉴权
    "AuthProvider",
    "MockAuthProvider",
    "NoneAuthProvider",
    "TokenAuthProvider",
    "AppKeyAuthProvider",
    "create_auth_provider",
    "build_appkey_signature",
    # 传输
    "Transport",
    "normalize_envelope",
    "extract_list",
    "extract_total",
    "substitute_path",
    # mock
    "MockBackend",
    # 工具函数
    "validate_arguments",
    "coerce_value",
    "find_spec_path",
    # 常量
    "AUTH_MODES",
    "DEFAULT_AUTH_MODE",
    "ENV_BASE_URL",
    "ENV_AUTH_MODE",
    "ENV_APP_KEY",
    "ENV_APP_SECRET",
    "ENV_TOKEN",
    "ENV_TIMEOUT",
    "ENV_RETRY",
    "ENV_SPEC_PATH",
    "ENV_VERIFY_SSL",
    "__version__",
]
