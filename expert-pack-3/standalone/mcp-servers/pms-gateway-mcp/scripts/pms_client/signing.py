"""appkey 签名规范（二期「模拟规范」）：客户端与本地模拟网关的唯一实现。

本模块是 **appkey 鉴权签名算法的单一实现**：:mod:`pms_client.auth`（客户端）与
:mod:`mock_gateway.auth`（本地模拟网关）都调用这里，保证两端逐字节一致。

签名串（canonical string，UTF-8，共 7 段，用 ``"\\n"`` 连接）::

    app_key
    METHOD             # HTTP 方法大写，如 GET / POST
    path               # 已做路径参数替换后的最终路径，保留 percent-encode，不含 query
    canonical_query    # 见下
    body_sha256        # sha256(raw_body).hexdigest()，空 body 取空字节的摘要
    timestamp          # 毫秒级时间戳字符串，如 "1759000000000"
    nonce              # 一次性随机串（客户端用 uuid4().hex）

``canonical_query`` 的构造规则：

1. 跳过值为 ``None`` 的参数；
2. 列表/元组按英文逗号拼接（``["a", "b"]`` → ``"a,b"``）；布尔转小写 ``true``/``false``；
   对象按键有序、紧凑 JSON 序列化；
3. 其余取值 ``str(value)``；
4. 所有 ``(key, value)`` 二元组按升序排序，再用 ``urllib.parse.urlencode`` 编码
   （空格编码为 ``+``，中文等非 ASCII 字符按 UTF-8 percent-encode）。

最终签名 = ``HMAC-SHA256(app_secret, canonical).hexdigest()``，**小写十六进制**。

边界情况（与服务端校验逐条对齐）：

- 无 query 参数时 ``canonical_query`` 为空串；
- 空 body（GET 等无请求体）时摘要为 ``sha256(b"").hexdigest()``；
- ``path`` 用「已替换路径参数」的最终路径，**不含** ``?query``；客户端签名用的是
  ``transport.substitute_path`` 之后的路径，服务端用请求行里的原始（已编码）路径。

注意：这是为本地联调定义的**模拟规范**，不是真实中台规范。正式《接口说明文档》下发后，
只需替换 :func:`build_appkey_signature`（及 :func:`build_canonical` 中与之相关的段），
客户端与模拟网关会自动同步，无需改其它代码。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# 请求头约定（客户端与模拟网关共用，改名只改这里）
# ---------------------------------------------------------------------------
HEADER_APP_KEY = "X-PMS-App-Key"
HEADER_TIMESTAMP = "X-PMS-Timestamp"
HEADER_NONCE = "X-PMS-Nonce"
HEADER_SIGNATURE = "X-PMS-Signature"

#: 签名算法标识（写入文档/日志，便于排查两端实现是否同版本）
SIGNATURE_ALGORITHM = "HMAC-SHA256"
#: 签名串字段顺序（文档与测试的对照清单）
CANONICAL_FIELDS = (
    "appKey",
    "method",
    "path",
    "canonicalQuery",
    "bodySha256",
    "timestamp",
    "nonce",
)

#: 空请求体的摘要（``sha256(b"").hexdigest()``），避免两端各算一次
EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()


def normalize_query_value(value: Any) -> str | None:
    """把单个 query 值归一为签名用的字符串；``None`` 表示该参数不参与签名。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            text = normalize_query_value(item)
            if text is not None:
                parts.append(text)
        return ",".join(parts)
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def canonical_query(query: Mapping[str, Any] | None = None) -> str:
    """构造签名用的 query 串：跳过 None、列表逗号拼接、布尔小写、按二元组排序后 urlencode。"""
    if not query:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        text = normalize_query_value(value)
        if text is None:
            continue
        pairs.append((str(key), text))
    pairs.sort()
    return urllib.parse.urlencode(pairs)


def body_sha256(body: bytes | None) -> str:
    """请求体的 SHA-256 小写十六进制摘要；空 body 取空字节摘要。"""
    if not body:
        return EMPTY_BODY_SHA256
    if isinstance(body, str):  # 容错：调用方传了文本
        body = body.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def canonical_string(
    app_key: str,
    method: str,
    path: str,
    query: Mapping[str, Any] | None,
    body: bytes | None,
    timestamp: str,
    nonce: str,
) -> str:
    """拼出待签名的 7 段签名串（不含 secret）。"""
    return "\n".join(
        [
            str(app_key),
            str(method or "").upper(),
            str(path or ""),
            canonical_query(query),
            body_sha256(body),
            str(timestamp),
            str(nonce),
        ]
    )


def compute_signature(app_secret: str, canonical: str) -> str:
    """HMAC-SHA256(secret, canonical) → 小写十六进制。"""
    if not app_secret:
        raise ValueError("app_secret 不能为空：appkey 模式下必须提供应用密钥")
    return hmac.new(
        str(app_secret).encode("utf-8"),
        str(canonical).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


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
    """按本模块的模拟规范计算 appkey 签名（小写 hex）。

    参数顺序与 :func:`pms_client.auth.build_appkey_signature` 完全一致，客户端只需设置
    ``PMS_AUTH_MODE=appkey`` + ``PMS_APP_KEY`` / ``PMS_APP_SECRET`` 即可走通；
    真实中台规范下发后替换本函数实现即可。

    示例::

        >>> from pms_client.signing import build_appkey_signature
        >>> build_appkey_signature("mock-app-key", "mock-app-secret", "GET",
        ...                         "/assetCenter/queryServices/getAstById",
        ...                         {"assetId": "AST-102-0001"}, None,
        ...                         "1759000000000", "abc123")
        '...64 位小写 hex...'
    """
    canonical = canonical_string(app_key, method, path, query, body, timestamp, nonce)
    return compute_signature(app_secret, canonical)


def describe_scheme() -> dict[str, Any]:
    """签名规范摘要（供 doctor / 文档 / 测试断言）。"""
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "canonicalSeparator": "\n",
        "canonicalFields": list(CANONICAL_FIELDS),
        "queryRules": "skip None; list→comma; bool→lowercase; sort (key,value); urlencode",
        "bodyDigest": "sha256(rawBody).hexdigest() (empty body = sha256 of b'')",
        "signatureEncoding": "lowercase hex",
        "headers": {
            "appKey": HEADER_APP_KEY,
            "timestamp": HEADER_TIMESTAMP,
            "nonce": HEADER_NONCE,
            "signature": HEADER_SIGNATURE,
        },
        "timestampUnit": "milliseconds",
    }


__all__ = [
    "HEADER_APP_KEY",
    "HEADER_TIMESTAMP",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "SIGNATURE_ALGORITHM",
    "CANONICAL_FIELDS",
    "EMPTY_BODY_SHA256",
    "normalize_query_value",
    "canonical_query",
    "body_sha256",
    "canonical_string",
    "compute_signature",
    "build_appkey_signature",
    "describe_scheme",
]
