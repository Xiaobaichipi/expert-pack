"""鉴权：AuthProvider 抽象 + mock / none / appkey / token 四种实现。

设计原则：
- 凭证只来自环境变量（:class:`~pms_client.config.PmsConfig`），**任何情况下都不硬编码**；
- appkey 模式的签名算法实现于 :mod:`pms_client.signing`（客户端与本地模拟网关共用同一实现），
  本模块的 :func:`build_appkey_signature` 仅做委托；正式《接口说明文档》下发后
  只替换 ``signing`` 中的实现，transport / client / CLI / MCP 零改动；
- 缺凭证时给出可操作的中文报错，而不是静默失败或返回空请求头。
"""

from __future__ import annotations

import abc
import time
import uuid
from typing import Any, Mapping

from .config import PmsConfig
from .errors import ErrorCode, PmsError
from .signing import (
    HEADER_APP_KEY,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
)
from .signing import build_appkey_signature as _build_appkey_signature

# 请求头约定（正式联调时以中台《接口说明文档》为准，可在此统一调整；
# appkey 的四个头由 pms_client.signing 统一定义，客户端与模拟网关共用）
HEADER_TOKEN = "Authorization"
HEADER_MOCK = "X-PMS-Mock"


class AuthProvider(abc.ABC):
    """鉴权提供者接口：为每次请求生成鉴权请求头。"""

    mode: str = "none"

    def __init__(self, config: PmsConfig) -> None:
        self.config = config

    @abc.abstractmethod
    def build_headers(
        self,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        body: bytes | None = None,
    ) -> dict[str, str]:
        """返回本次请求需要附加的请求头（不含 Content-Type 等通用头）。"""

    def problems(self) -> list[str]:
        """返回该鉴权模式下的配置问题（供 doctor 展示）。"""
        return []

    def describe(self) -> dict[str, Any]:
        """脱敏描述，用于日志/自检。"""
        return {"mode": self.mode}

    def check(self) -> None:
        problems = self.problems()
        if problems:
            raise PmsError(
                ErrorCode.AUTH_MISSING_CREDENTIALS,
                problems[0],
                details={"problems": problems},
            )


class MockAuthProvider(AuthProvider):
    """mock 模式：不发真实请求，仅用于本地联调与演示。"""

    mode = "mock"

    def build_headers(self, method, path, query=None, body=None) -> dict[str, str]:
        return {HEADER_MOCK: "1"}

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode, "note": "内置样例数据，不访问真实网关"}


class NoneAuthProvider(AuthProvider):
    """none 模式：网关侧免鉴权（如内网直连或已由网关代理统一鉴权）。"""

    mode = "none"

    def build_headers(self, method, path, query=None, body=None) -> dict[str, str]:
        return {}


class TokenAuthProvider(AuthProvider):
    """token 模式：Bearer Token。"""

    mode = "token"

    def build_headers(self, method, path, query=None, body=None) -> dict[str, str]:
        self.check()
        return {HEADER_TOKEN: f"Bearer {self.config.token}"}

    def problems(self) -> list[str]:
        if not self.config.token:
            return [
                "token 模式缺少凭证：环境变量 PMS_TOKEN 为空。请向中台申请访问令牌后配置；"
                "暂未申请到可设置 PMS_AUTH_MODE=mock 使用内置样例数据联调"
            ]
        return []

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hasToken": bool(self.config.token),
            "tokenMasked": _mask(self.config.token),
        }


class AppKeyAuthProvider(AuthProvider):
    """appkey 模式：appKey + 时间戳 + 随机数 + HMAC 签名。

    凭证从 ``PMS_APP_KEY`` / ``PMS_APP_SECRET`` 读取；签名算法见
    :func:`build_appkey_signature`（实现位于 :mod:`pms_client.signing`，
    本地模拟网关 ``mock_gateway`` 使用同一实现，两端逐字节一致）。
    """

    mode = "appkey"

    def build_headers(self, method, path, query=None, body=None) -> dict[str, str]:
        self.check()
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        signature = build_appkey_signature(
            app_key=self.config.app_key,
            app_secret=self.config.app_secret,
            method=method,
            path=path,
            query=query or {},
            body=body,
            timestamp=timestamp,
            nonce=nonce,
        )
        return {
            HEADER_APP_KEY: self.config.app_key,
            HEADER_TIMESTAMP: timestamp,
            HEADER_NONCE: nonce,
            HEADER_SIGNATURE: signature,
        }

    def problems(self) -> list[str]:
        missing = []
        if not self.config.app_key:
            missing.append("PMS_APP_KEY")
        if not self.config.app_secret:
            missing.append("PMS_APP_SECRET")
        if missing:
            return [
                "appkey 模式缺少凭证：" + "、".join(missing) + " 为空。请向中台管理部门提交接入申请获取 appKey/appSecret，"
                "通过环境变量配置（禁止写进代码仓库）；未申请到之前请用 PMS_AUTH_MODE=mock 联调"
            ]
        return []

    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hasAppKey": bool(self.config.app_key),
            "hasAppSecret": bool(self.config.app_secret),
            "appKeyMasked": _mask(self.config.app_key),
        }


def build_appkey_signature(
    app_key: str,
    app_secret: str,
    method: str,
    path: str,
    query: Mapping[str, Any] | None,
    body: bytes | None,
    timestamp: str,
    nonce: str,
) -> str:
    """按二期「模拟规范」计算 appkey 签名（HMAC-SHA256，小写 hex）。

    唯一实现位于 :mod:`pms_client.signing`，本地模拟网关 ``mock_gateway.auth`` 复用同一
    实现，保证客户端与服务端逐字节一致。签名串（7 段，以 ``"\\n"`` 连接）::

        app_key \\n METHOD \\n path \\n canonical_query \\n body_sha256 \\n timestamp \\n nonce

    其中：

    - ``canonical_query``：跳过 None、列表逗号拼接、布尔转小写、按 (key, value) 排序后
      用 ``urllib.parse.urlencode`` 编码；
    - ``body_sha256``：``sha256(raw_body).hexdigest()``，空 body 取空字节的摘要；
    - ``timestamp``：毫秒级时间戳字符串；``nonce``：一次性随机串（服务端在 ±300s 窗口内
      做防重放校验）；
    - 签名 = ``HMAC-SHA256(app_secret, canonical)`` 的**小写十六进制**。

    正式《接口说明文档》下发后，只替换 ``pms_client/signing.py`` 中的实现，
    transport / client / CLI / MCP 均无需改动。
    """
    return _build_appkey_signature(
        app_key,
        app_secret,
        method,
        path,
        query,
        body,
        timestamp,
        nonce,
    )


def create_auth_provider(config: PmsConfig) -> AuthProvider:
    """按 ``config.auth_mode`` 创建鉴权提供者。"""
    mode = (config.auth_mode or "").lower()
    providers = {
        "mock": MockAuthProvider,
        "none": NoneAuthProvider,
        "appkey": AppKeyAuthProvider,
        "token": TokenAuthProvider,
    }
    provider_cls = providers.get(mode)
    if provider_cls is None:
        raise PmsError(
            ErrorCode.AUTH_MODE_INVALID,
            f"未知鉴权模式 {config.auth_mode!r}。可选值：mock、none、appkey、token"
            "（对应环境变量 PMS_AUTH_MODE；默认 mock）",
            details={"authMode": config.auth_mode, "allowed": sorted(providers)},
        )
    return provider_cls(config)


def _mask(secret: str) -> str:
    """凭证脱敏：保留首尾少量字符，绝不回显完整凭证。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"
