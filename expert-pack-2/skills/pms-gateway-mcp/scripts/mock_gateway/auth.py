"""本地模拟网关鉴权：token / appkey / none 三种模式。

与客户端（:mod:`pms_client.auth` + :mod:`pms_client.signing`）逐字节对齐：

- **token**：客户端发 ``Authorization: Bearer <PMS_TOKEN>``；服务端期望
  ``PMS_MOCK_TOKEN``（默认 ``mock-token-001``）。缺失/错误 → HTTP 401。
- **appkey**：客户端发 ``X-PMS-App-Key`` / ``X-PMS-Timestamp``（毫秒）/
  ``X-PMS-Nonce`` / ``X-PMS-Signature``；签名算法完全复用
  :func:`pms_client.signing.build_appkey_signature`（同一份 canonical 拼接与 HMAC-SHA256）。
  服务端凭证 ``PMS_MOCK_APP_KEY``（默认 ``mock-app-key``）/
  ``PMS_MOCK_APP_SECRET``（默认 ``mock-app-secret``）。
  时间窗 ±300s（可用 ``PMS_MOCK_TIME_WINDOW`` 覆盖）；nonce 有界缓存防重放
  （重放 → HTTP 403）。缺头/appKey 不符/时间戳越界/签名不符 → HTTP 401。
- **none**：不做任何校验，仅供本地调试（等价于网关侧免鉴权）。

认证失败返回 :class:`AuthResult`，由 :mod:`mock_gateway.server` 转成
``HTTP 4xx`` + ``{"code": 4xx, "message": "..."}``，客户端 ``transport`` 会归一为
``AUTH_FAILED`` 错误码（401/403 均归一）。

安全说明：这是**本地模拟网关**，默认凭证写在文档与默认值里，绝不能用于任何真实环境。
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Any, Iterable, Mapping

from pms_client.signing import (
    HEADER_APP_KEY,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    build_appkey_signature,
)

__all__ = [
    "AUTH_MODES",
    "ENV_MOCK_APP_KEY",
    "ENV_MOCK_APP_SECRET",
    "ENV_MOCK_TIME_WINDOW",
    "ENV_MOCK_TOKEN",
    "DEFAULT_TOKEN",
    "DEFAULT_APP_KEY",
    "DEFAULT_APP_SECRET",
    "DEFAULT_TIME_WINDOW_SECONDS",
    "DEFAULT_NONCE_CACHE_SIZE",
    "AuthResult",
    "MockAuth",
]

# ---------------------------------------------------------------------------
# 环境变量与默认值（模拟凭证，仅本地联调）
# ---------------------------------------------------------------------------
ENV_MOCK_TOKEN = "PMS_MOCK_TOKEN"
ENV_MOCK_APP_KEY = "PMS_MOCK_APP_KEY"
ENV_MOCK_APP_SECRET = "PMS_MOCK_APP_SECRET"
ENV_MOCK_TIME_WINDOW = "PMS_MOCK_TIME_WINDOW"

DEFAULT_TOKEN = "mock-token-001"
DEFAULT_APP_KEY = "mock-app-key"
DEFAULT_APP_SECRET = "mock-app-secret"
#: appkey 时间窗（秒）：|now - timestamp| 超过该值即拒绝
DEFAULT_TIME_WINDOW_SECONDS = 300
#: nonce 防重放缓存上限（有界，避免内存无限增长）
DEFAULT_NONCE_CACHE_SIZE = 4096

#: 支持的鉴权模式
AUTH_MODES = ("token", "appkey", "none")

#: HTTP 状态与业务码（认证失败时两者一致，便于客户端日志检索）
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
CODE_UNAUTHORIZED = 401
CODE_FORBIDDEN = 403


def _env(name: str, default: str) -> str:
    """读环境变量：未设置或空白时用默认值（模拟凭证仅本地使用）。"""
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def default_token() -> str:
    """服务端期望的 token（PMS_MOCK_TOKEN，默认 mock-token-001）。"""
    return _env(ENV_MOCK_TOKEN, DEFAULT_TOKEN)


def default_app_key() -> str:
    """服务端期望的 appKey（PMS_MOCK_APP_KEY，默认 mock-app-key）。"""
    return _env(ENV_MOCK_APP_KEY, DEFAULT_APP_KEY)


def default_app_secret() -> str:
    """服务端期望的 appSecret（PMS_MOCK_APP_SECRET，默认 mock-app-secret）。"""
    return _env(ENV_MOCK_APP_SECRET, DEFAULT_APP_SECRET)


def _header(headers: Any, name: str) -> str:
    """大小写不敏感地取请求头（兼容 dict 与 ``http.client.HTTPMessage``）。"""
    if not headers:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        try:
            value = getter(name)
        except Exception:  # pragma: no cover - 防御
            value = None
        if value:
            return str(value).strip()
    try:
        items: Iterable[tuple[Any, Any]] = headers.items()  # type: ignore[union-attr]
    except AttributeError:
        return ""
    target = str(name).lower()
    for key, value in items:
        if str(key).lower() == target:
            return "" if value is None else str(value).strip()
    return ""


class AuthResult:
    """一次鉴权的结果。

    - ``ok=True`` 时 ``status/code`` 均为 200/0，服务端继续处理请求；
    - ``ok=False`` 时 ``status`` 为 401/403，``code`` 同值，``message`` 为中文可读原因。
    """

    __slots__ = ("ok", "status", "code", "message", "reason")

    def __init__(
        self,
        ok: bool,
        *,
        status: int = 200,
        code: int = 0,
        message: str = "ok",
        reason: str = "",
    ) -> None:
        self.ok = bool(ok)
        self.status = int(status)
        self.code = int(code)
        self.message = str(message)
        self.reason = str(reason)

    def to_body(self) -> dict[str, Any]:
        """认证失败的 JSON 响应体（``{"code": 4xx, "message": "..."}``）。"""
        return {"code": self.code, "message": self.message}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "reason": self.reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return "AuthResult(ok={!r}, status={!r}, reason={!r})".format(self.ok, self.status, self.reason)

    # -- 常用构造 -------------------------------------------------------
    @classmethod
    def success(cls, reason: str = "ok") -> "AuthResult":
        return cls(True, status=200, code=0, message="ok", reason=reason)

    @classmethod
    def unauthorized(cls, message: str, reason: str = "") -> "AuthResult":
        return cls(
            False,
            status=HTTP_UNAUTHORIZED,
            code=CODE_UNAUTHORIZED,
            message=message,
            reason=reason or "unauthorized",
        )

    @classmethod
    def forbidden(cls, message: str, reason: str = "") -> "AuthResult":
        return cls(
            False,
            status=HTTP_FORBIDDEN,
            code=CODE_FORBIDDEN,
            message=message,
            reason=reason or "forbidden",
        )


class MockAuth:
    """模拟网关鉴权器（token / appkey / none）。

    参数默认从环境变量读取（``PMS_MOCK_*``），显式传入优先生效，便于测试固定凭证。
    """

    def __init__(
        self,
        mode: str = "token",
        *,
        token: str | None = None,
        app_key: str | None = None,
        app_secret: str | None = None,
        time_window_seconds: int | None = None,
        nonce_cache_size: int | None = None,
        clock: Any = None,
    ) -> None:
        normalized = str(mode or "token").strip().lower()
        if normalized not in AUTH_MODES:
            raise ValueError(
                "未知鉴权模式 {!r}，可选值：{}".format(mode, "、".join(AUTH_MODES))
            )
        self.mode = normalized
        self.token = default_token() if token is None else str(token)
        self.app_key = default_app_key() if app_key is None else str(app_key)
        self.app_secret = default_app_secret() if app_secret is None else str(app_secret)
        self.time_window_seconds = (
            _env_int(ENV_MOCK_TIME_WINDOW, DEFAULT_TIME_WINDOW_SECONDS)
            if time_window_seconds is None
            else int(time_window_seconds)
        )
        self.nonce_cache_size = (
            DEFAULT_NONCE_CACHE_SIZE if nonce_cache_size is None else int(nonce_cache_size)
        )
        self._clock = clock or (lambda: time.time() * 1000.0)
        self._lock = threading.Lock()
        #: nonce → 首次出现时间（毫秒）；OrderedDict 保证按插入顺序淘汰
        self._nonces: dict[str, float] = {}

    # -- 对外入口 -------------------------------------------------------
    def check(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        raw_body: bytes | None = None,
        headers: Any = None,
    ) -> AuthResult:
        """校验一次请求；返回 :class:`AuthResult`（失败时由服务端转 HTTP 401/403）。"""
        if self.mode == "none":
            return AuthResult.success(reason="auth-disabled")
        if self.mode == "token":
            return self._check_token(headers)
        return self._check_appkey(method, path, query, raw_body, headers)

    # -- token ----------------------------------------------------------
    def _check_token(self, headers: Any) -> AuthResult:
        raw = _header(headers, "Authorization")
        if not raw:
            return AuthResult.unauthorized(
                "缺少 Authorization 请求头：token 模式需携带 Authorization: Bearer <PMS_TOKEN>",
                reason="token-missing",
            )
        scheme, _, credential = raw.partition(" ")
        if scheme.strip().lower() != "bearer" or not credential.strip():
            return AuthResult.unauthorized(
                "Authorization 头格式非法：应形如 Authorization: Bearer <PMS_TOKEN>",
                reason="token-format",
            )
        if not hmac.compare_digest(credential.strip(), str(self.token)):
            return AuthResult.unauthorized(
                "token 无效：Bearer Token 与服务端期望值不一致（模拟网关默认 PMS_MOCK_TOKEN=mock-token-001）",
                reason="token-invalid",
            )
        return AuthResult.success(reason="token-ok")

    # -- appkey ---------------------------------------------------------
    def _check_appkey(
        self,
        method: str,
        path: str,
        query: Mapping[str, Any] | None,
        raw_body: bytes | None,
        headers: Any,
    ) -> AuthResult:
        app_key = _header(headers, HEADER_APP_KEY)
        timestamp = _header(headers, HEADER_TIMESTAMP)
        nonce = _header(headers, HEADER_NONCE)
        signature = _header(headers, HEADER_SIGNATURE)
        missing = [
            name
            for name, value in (
                (HEADER_APP_KEY, app_key),
                (HEADER_TIMESTAMP, timestamp),
                (HEADER_NONCE, nonce),
                (HEADER_SIGNATURE, signature),
            )
            if not value
        ]
        if missing:
            return AuthResult.unauthorized(
                "缺少 appkey 鉴权请求头：{}（appkey 模式需 4 个头齐全）".format("、".join(missing)),
                reason="headers-missing",
            )
        if not hmac.compare_digest(app_key, str(self.app_key)):
            return AuthResult.unauthorized(
                "appKey 无效：与服务端 PMS_MOCK_APP_KEY 不一致（默认 mock-app-key）",
                reason="appkey-invalid",
            )
        try:
            timestamp_ms = int(timestamp)
        except ValueError:
            return AuthResult.unauthorized(
                "时间戳非法：{} 不是毫秒整数".format(timestamp),
                reason="timestamp-invalid",
            )
        now_ms = float(self._clock())
        drift_ms = abs(now_ms - timestamp_ms)
        window_ms = self.time_window_seconds * 1000
        if drift_ms > window_ms:
            return AuthResult.unauthorized(
                "时间戳超出允许窗口（±{}s）：请求 {}ms，服务端 {}ms".format(
                    self.time_window_seconds, timestamp_ms, int(now_ms)
                ),
                reason="timestamp-window",
            )
        expected = build_appkey_signature(
            app_key=app_key,
            app_secret=str(self.app_secret),
            method=method,
            path=path,
            query=query or {},
            body=raw_body,
            timestamp=timestamp,
            nonce=nonce,
        )
        if not hmac.compare_digest(signature.lower(), expected.lower()):
            return AuthResult.unauthorized(
                "签名校验失败：请确认客户端与服务端使用同一 PMS_APP_SECRET 与同一签名规范",
                reason="signature-invalid",
            )
        if self._remember_nonce(nonce, now_ms):
            return AuthResult.forbidden(
                "nonce 已被使用（检测到重放请求）：请为每次请求生成新的 X-PMS-Nonce",
                reason="nonce-replay",
            )
        return AuthResult.success(reason="appkey-ok")

    # -- nonce 防重放（有界缓存） ---------------------------------------
    def _remember_nonce(self, nonce: str, now_ms: float) -> bool:
        """记录 nonce；返回 True 表示重放（该 nonce 在有效窗口内已出现过）。"""
        with self._lock:
            self._prune_nonces(now_ms)
            if nonce in self._nonces:
                return True
            self._nonces[nonce] = now_ms
            while len(self._nonces) > max(1, self.nonce_cache_size):
                self._nonces.pop(next(iter(self._nonces)))
            return False

    def _prune_nonces(self, now_ms: float) -> None:
        """淘汰超出时间窗的 nonce（窗口外的 nonce 不再有重放风险）。"""
        expiry_ms = now_ms - max(self.time_window_seconds, 1) * 1000
        stale = [key for key, seen in self._nonces.items() if seen < expiry_ms]
        for key in stale:
            del self._nonces[key]
        while len(self._nonces) > max(1, self.nonce_cache_size):
            self._nonces.pop(next(iter(self._nonces)))

    # -- 展示 -----------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """脱敏描述（供 doctor / 启动日志 / 测试）。"""
        return {
            "mode": self.mode,
            "tokenMasked": _mask(self.token if self.mode == "token" else ""),
            "appKeyMasked": _mask(self.app_key if self.mode == "appkey" else ""),
            "timeWindowSeconds": self.time_window_seconds,
            "nonceCacheSize": self.nonce_cache_size,
            "nonceCached": len(self._nonces),
        }

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return "MockAuth(mode={!r}, timeWindow={}s)".format(self.mode, self.time_window_seconds)


def _mask(secret: str) -> str:
    """凭证脱敏：保留首尾少量字符。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return "{}****{}".format(secret[:4], secret[-4:])
