"""统一错误模型。

PMS 接口网关的所有异常都归一到 :class:`PmsError`，便于 MCP / CLI 统一处理：
- ``code``       机器可读错误码（见 :class:`ErrorCode`）
- ``message``    面向人（和 LLM）的中文可操作提示
- ``http_status`` HTTP 状态码（网络层错误才有）
- ``retryable``  是否可安全重试（供 transport 自动重试）
- ``details``    附加信息（远端业务码、原始返回片段等）
- ``tool``       出错的工具名（可选）
"""

from __future__ import annotations

import json
from typing import Any


class ErrorCode:
    """错误码常量（统一大写下划线风格，便于日志检索与文档引用）。"""

    # --- 调用方 / 入参问题 ---
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_PARAM = "INVALID_PARAM"

    # --- 配置与鉴权 ---
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTH_MODE_INVALID = "AUTH_MODE_INVALID"
    AUTH_MISSING_CREDENTIALS = "AUTH_MISSING_CREDENTIALS"
    AUTH_SIGNATURE_TODO = "AUTH_SIGNATURE_TODO"
    AUTH_FAILED = "AUTH_FAILED"

    # --- 规格文件 ---
    SPEC_NOT_FOUND = "SPEC_NOT_FOUND"
    SPEC_ERROR = "SPEC_ERROR"

    # --- 网络 / 网关 ---
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    REMOTE_ERROR = "REMOTE_ERROR"

    # --- 其他 ---
    MOCK_ERROR = "MOCK_ERROR"
    INTERNAL = "INTERNAL"


class PmsError(Exception):
    """网关统一异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        details: Any = None,
        tool: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = bool(retryable)
        self.details = details
        self.tool = tool

    # -- 序列化 ---------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """转为可 JSON 序列化的字典（MCP tools/call 出错时直接回给宿主）。"""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.http_status is not None:
            payload["httpStatus"] = self.http_status
        if self.retryable:
            payload["retryable"] = True
        if self.tool:
            payload["tool"] = self.tool
        if self.details is not None:
            payload["details"] = self.details
        return payload

    def __str__(self) -> str:  # pragma: no cover - 仅日志展示
        suffix = f" (HTTP {self.http_status})" if self.http_status is not None else ""
        return f"[{self.code}] {self.message}{suffix}"

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PmsError(code={self.code!r}, message={self.message!r}, "
            f"http_status={self.http_status!r}, retryable={self.retryable!r})"
        )


# ---------------------------------------------------------------------------
# 常用构造函数：让各处报错文案保持统一、可操作
# ---------------------------------------------------------------------------
def unknown_tool(name: str, known: list[str]) -> PmsError:
    suggestion = ""
    try:
        import difflib

        matches = difflib.get_close_matches(str(name), known, n=3, cutoff=0.5)
        if matches:
            suggestion = "；你是否想调用：" + "、".join(matches)
    except Exception:  # pragma: no cover - 建议功能失败不影响主流程
        suggestion = ""
    return PmsError(
        ErrorCode.UNKNOWN_TOOL,
        f"未知工具 {name!r}。可用工具共 {len(known)} 个，请先执行 tools/list 或 CLI list-tools 查看{suggestion}",
        details={"tool": name, "knownCount": len(known)},
    )


def invalid_param(message: str, *, tool: str | None = None, details: Any = None) -> PmsError:
    return PmsError(ErrorCode.INVALID_PARAM, message, tool=tool, details=details)


def not_configured(message: str) -> PmsError:
    return PmsError(ErrorCode.NOT_CONFIGURED, message)


def timeout_error(timeout: float, tool: str | None = None) -> PmsError:
    return PmsError(
        ErrorCode.TIMEOUT,
        f"请求网关超时（{timeout:g}s）。可增大 PMS_TIMEOUT、检查网络/网关连通性后重试",
        retryable=True,
        tool=tool,
    )


def network_error(reason: Any, tool: str | None = None) -> PmsError:
    return PmsError(
        ErrorCode.NETWORK,
        f"无法连接网关：{reason}。请检查 PMS_GATEWAY_BASE_URL、DNS、代理与网络连通性",
        retryable=True,
        tool=tool,
        details={"reason": str(reason)},
    )


def http_error(status: int, remote_message: str = "", tool: str | None = None, body: str = "") -> PmsError:
    """按 HTTP 状态码归一错误，并给出可操作建议。"""
    remote_message = (remote_message or "").strip()
    detail = f"：{remote_message}" if remote_message else ""
    snippet = body[:500] if body else ""
    if status in (401, 403):
        return PmsError(
            ErrorCode.AUTH_FAILED,
            f"网关鉴权失败（HTTP {status}）{detail}。请检查 PMS_AUTH_MODE 与对应凭证"
            "（PMS_TOKEN / PMS_APP_KEY / PMS_APP_SECRET）是否有效、是否在有效期内",
            http_status=status,
            tool=tool,
            details={"body": snippet} if snippet else None,
        )
    if status == 404:
        return PmsError(
            ErrorCode.NOT_FOUND,
            f"接口路径不存在（HTTP 404）{detail}。请核对 spec/interfaces.json 中的 path 是否与网关服务目录一致",
            http_status=status,
            tool=tool,
            details={"body": snippet} if snippet else None,
        )
    if status == 429:
        return PmsError(
            ErrorCode.RATE_LIMITED,
            f"触发网关限流（HTTP 429）{detail}。请降低调用频率、增大重试间隔或申请提升 QPS 配额",
            http_status=status,
            retryable=True,
            tool=tool,
            details={"body": snippet} if snippet else None,
        )
    if status in (400, 405, 409, 415, 422):
        return PmsError(
            ErrorCode.BAD_REQUEST,
            f"网关拒绝了请求（HTTP {status}）{detail}。请核对工具参数与参数风格（query / json_body）",
            http_status=status,
            tool=tool,
            details={"body": snippet} if snippet else None,
        )
    if 500 <= status < 600:
        return PmsError(
            ErrorCode.SERVER_ERROR,
            f"网关服务端错误（HTTP {status}）{detail}。可稍后重试；持续失败请联系中台运维",
            http_status=status,
            retryable=True,
            tool=tool,
            details={"body": snippet} if snippet else None,
        )
    return PmsError(
        ErrorCode.HTTP_ERROR,
        f"网关返回异常状态（HTTP {status}）{detail}",
        http_status=status,
        tool=tool,
        details={"body": snippet} if snippet else None,
    )


def parse_error(raw: str, tool: str | None = None) -> PmsError:
    return PmsError(
        ErrorCode.PARSE_ERROR,
        "网关返回内容不是合法 JSON，无法解析。可抓包确认返回体，或联系中台确认接口契约",
        tool=tool,
        details={"raw": raw[:500]},
    )


def remote_error(envelope: dict[str, Any], tool: str | None = None) -> PmsError:
    code = envelope.get("code")
    message = str(envelope.get("message") or "网关返回业务错误")
    return PmsError(
        ErrorCode.REMOTE_ERROR,
        f"网关业务错误（code={code}）：{message}",
        retryable=False,
        tool=tool,
        details={"remoteCode": code, "data": _safe_json(envelope.get("data"))},
    )


def spec_error(message: str, details: Any = None) -> PmsError:
    return PmsError(ErrorCode.SPEC_ERROR, message, details=details)


def internal_error(exc: BaseException, tool: str | None = None) -> PmsError:
    return PmsError(
        ErrorCode.INTERNAL,
        f"内部错误：{type(exc).__name__}: {exc}",
        tool=tool,
    )


def _safe_json(value: Any) -> Any:
    """data 里可能有不可序列化对象，转成 JSON 安全结构。"""
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        return str(value)
