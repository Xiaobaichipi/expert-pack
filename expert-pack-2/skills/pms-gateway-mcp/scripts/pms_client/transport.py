"""传输层：基于标准库 urllib 的 HTTP 调用、超时、重试、响应归一。

本模块只负责「把一次工具调用变成 HTTP 请求，并把返回变成 {code, message, data}」，
不含任何业务知识；业务参数如何切分由 :mod:`pms_client.client` 依据 spec 决定。

对外主要接口：

- :meth:`Transport.call`            发起请求（自动重试、错误归一）
- :func:`normalize_envelope`        任意返回体 → ``{code, message, data}``
- :func:`extract_list`              兼容 ``data.list`` / ``data.records`` / 直接 list 的取列表
- :func:`extract_total`             取总数
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .auth import AuthProvider, create_auth_provider
from .config import PmsConfig
from .errors import (
    ErrorCode,
    PmsError,
    http_error,
    network_error,
    parse_error,
    remote_error,
    timeout_error,
)

USER_AGENT = "pms-gateway-mcp/1.0 (+stdlib-urllib)"

#: 视为成功的远端业务码（不同中台接口可能返回 0 或 200）
SUCCESS_CODES = frozenset({"0", "200", "0000", "000000", "success", "ok", ""})
#: 分页列表可能的字段名（兼容中台不同接口的返回风格）
LIST_KEYS = ("list", "records", "rows", "items", "dataList", "resultList", "content", "results")
#: 总数可能的字段名
TOTAL_KEYS = ("total", "totalCount", "totalNum", "count", "totalElements", "recordsTotal")


def substitute_path(path: str, path_params: Mapping[str, Any] | None = None) -> str:
    """把 ``/assetCenter/queryServices/{assetType}`` 中的占位符替换为实际值。"""
    result = str(path or "")
    for key, value in (path_params or {}).items():
        token = "{" + str(key) + "}"
        if token in result:
            result = result.replace(token, urllib.parse.quote(str(value), safe=""))
    if "{" in result and "}" in result:
        missing = result[result.index("{") : result.index("}") + 1]
        raise PmsError(
            ErrorCode.INVALID_PARAM,
            f"路径参数 {missing} 未提供，无法拼接接口地址 {path}",
            details={"path": path, "missing": missing},
        )
    return result


def encode_query(query: Mapping[str, Any] | None = None) -> str:
    """把参数编码为 query string；跳过 None，布尔转小写，列表用逗号连接。"""
    if not query:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((str(key), "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            pairs.append((str(key), ",".join(str(item) for item in value)))
        elif isinstance(value, dict):
            pairs.append((str(key), json.dumps(value, ensure_ascii=False)))
        else:
            pairs.append((str(key), str(value)))
    return urllib.parse.urlencode(pairs)


def _is_success_code(code: Any) -> bool:
    if code is None:
        return True
    if isinstance(code, bool):
        return True
    if isinstance(code, int):
        return code in (0, 200)
    return str(code).strip().lower() in SUCCESS_CODES


def normalize_envelope(payload: Any) -> dict[str, Any]:
    """把任意网关返回体归一为 ``{code, message, data}``。

    兼容三种常见风格：
    1. 标准中台风格 ``{"code":0,"message":"ok","data":{...}}``；
    2. 简化风格 ``{"data":{...}}`` / 直接返回业务对象；
    3. 直接返回列表 ``[...]``。
    """
    if isinstance(payload, dict):
        if "code" in payload or "success" in payload:
            raw_code = payload.get("code")
            if raw_code is None:
                raw_code = 0 if payload.get("success") is not False else -1
            message = (
                payload.get("message")
                or payload.get("msg")
                or payload.get("messageText")
                or ("ok" if _is_success_code(raw_code) else "")
            )
            data = payload.get("data")
            if data is None and "success" in payload and "code" not in payload:
                # {"success": true, ...其他业务字段} 视为 data 本身就是业务数据
                data = {k: v for k, v in payload.items() if k != "success"}
            return {"code": _as_code(raw_code), "message": str(message), "data": data}
        if "data" in payload:
            return {"code": 0, "message": "ok", "data": payload["data"]}
        return {"code": 0, "message": "ok", "data": payload}
    if isinstance(payload, list):
        return {"code": 0, "message": "ok", "data": payload}
    if payload is None:
        return {"code": 0, "message": "ok", "data": None}
    return {"code": 0, "message": "ok", "data": payload}


def _as_code(raw: Any) -> Any:
    """业务码尽量转成 int，便于调用方判断；无法转换时保留原值。"""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return raw


def _unwrap_data(value: Any) -> Any:
    """去掉可能存在的一层 ``{"data": ...}`` 包装。"""
    if isinstance(value, dict) and "data" in value and not any(k in value for k in LIST_KEYS + TOTAL_KEYS):
        return value["data"]
    return value


def extract_list(response: Any) -> list[Any]:
    """从响应中提取列表，兼容 ``data.list`` / ``data.records`` / 直接 list。

    支持传入完整响应（含 code/message/data）或仅 data 部分。
    """
    value = response
    if isinstance(value, dict) and ("code" in value or "message" in value) and "data" in value:
        value = value.get("data")
    for _ in range(3):
        if isinstance(value, list):
            return list(value)
        if not isinstance(value, dict):
            return []
        found = False
        for key in LIST_KEYS:
            item = value.get(key)
            if isinstance(item, list):
                return list(item)
            if isinstance(item, dict):
                value = item
                found = True
                break
        if found:
            continue
        if "data" in value:
            value = value.get("data")
            continue
        return []
    return []


def extract_total(response: Any) -> int | None:
    """从响应中提取总条数，取不到返回 None。"""
    value = response
    if isinstance(value, dict) and ("code" in value or "message" in value) and "data" in value:
        value = value.get("data")
    for _ in range(3):
        if not isinstance(value, dict):
            return None
        for key in TOTAL_KEYS:
            raw = value.get(key)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
        if "data" in value and isinstance(value.get("data"), dict):
            value = value.get("data")
            continue
        return None
    return None


def extract_remote_message(body_text: str) -> str:
    """从错误响应体中尽量提取可读消息。"""
    text = (body_text or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return text[:200]
    if isinstance(payload, dict):
        for key in ("message", "msg", "messageText", "error_description", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        code = payload.get("code")
        if code is not None:
            return f"code={code}"
    return text[:200]


class Transport:
    """HTTP 传输实现（urllib，标准库）。"""

    def __init__(self, config: PmsConfig, auth: AuthProvider | None = None) -> None:
        self.config = config
        self.auth = auth or create_auth_provider(config)

    # -- 公共入口 -------------------------------------------------------
    def build_url(self, path: str, query: Mapping[str, Any] | None = None) -> str:
        base = str(self.config.base_url or "").rstrip("/")
        if not base:
            raise PmsError(
                ErrorCode.NOT_CONFIGURED,
                "PMS_GATEWAY_BASE_URL 未配置，无法拼接真实网关地址。联调阶段请使用 PMS_AUTH_MODE=mock",
            )
        if not base.lower().startswith(("http://", "https://")):
            base = "https://" + base
        target = str(path or "")
        if not target.startswith("/"):
            target = "/" + target
        url = base + target
        encoded = encode_query(query)
        if encoded:
            url = f"{url}{'&' if '?' in url else '?'}{encoded}"
        return url

    def call(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        path_params: Mapping[str, Any] | None = None,
        tool: str | None = None,
    ) -> dict[str, Any]:
        """发起一次网关调用，返回归一化响应 ``{code, message, data}``。"""
        method = (method or "GET").upper()
        real_path = substitute_path(path, path_params)
        clean_query = {k: v for k, v in (query or {}).items() if v is not None}
        attempts = max(1, int(self.config.retry) + 1)
        last_error: PmsError | None = None

        for attempt in range(attempts):
            try:
                return self._call_once(method, real_path, clean_query, body, tool)
            except PmsError as exc:
                last_error = exc
                if not exc.retryable or attempt + 1 >= attempts:
                    raise
                time.sleep(min(0.2 * (2**attempt), 1.0))
        raise last_error or PmsError(ErrorCode.INTERNAL, "请求未执行", tool=tool)  # pragma: no cover

    # -- 内部实现 -------------------------------------------------------
    def _call_once(
        self,
        method: str,
        path: str,
        query: dict[str, Any],
        body: Mapping[str, Any] | None,
        tool: str | None,
    ) -> dict[str, Any]:
        url = self.build_url(path, query)
        payload: bytes | None = None
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        headers.update(self.auth.build_headers(method, path, query, payload))

        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        context = None
        if url.lower().startswith("https://") and not self.config.verify_ssl:
            context = ssl._create_unverified_context()  # noqa: SLF001 - 仅在显式关闭校验时使用

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout, context=context) as response:
                raw = response.read()
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            body_text = _read_error_body(exc)
            raise http_error(exc.code, extract_remote_message(body_text), tool=tool, body=body_text) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise timeout_error(self.config.timeout, tool=tool) from None
            raise network_error(reason, tool=tool) from None
        except (socket.timeout, TimeoutError):
            raise timeout_error(self.config.timeout, tool=tool) from None
        except OSError as exc:  # 连接被重置、DNS 等
            raise network_error(exc, tool=tool) from None

        text = raw.decode("utf-8", errors="replace") if raw else ""
        if not text.strip():
            envelope: dict[str, Any] = {"code": status if status >= 400 else 0, "message": "ok", "data": None}
        else:
            try:
                envelope = normalize_envelope(json.loads(text))
            except (ValueError, TypeError):
                raise parse_error(text, tool=tool) from None
        self._raise_on_remote_error(envelope, tool)
        return envelope

    @staticmethod
    def _raise_on_remote_error(envelope: Mapping[str, Any], tool: str | None) -> None:
        if not _is_success_code(envelope.get("code")):
            raise remote_error(dict(envelope), tool=tool)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:  # pragma: no cover - 读错误体失败不影响主流程
        return ""
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")


def filter_none(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """去掉值为 None 的键（构造 query/body 时常用）。"""
    return {key: value for key, value in mapping.items() if value is not None}
