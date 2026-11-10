"""mock 模式：由 spec 中的 ``mock`` 数据生成样例返回。

用途：在没有拿到中台凭证之前，让 MCP / CLI / 问数流程可以完整跑通。
特性：
- 数据完全来自 ``spec/interfaces.json`` 的 ``mock`` 字段，改 spec 即改 mock；
- 分页接口支持 ``pageNo`` / ``pageSize`` 分页；
- 支持简单的等值/包含过滤（如按 ``stationName``、``psrId``、``deviceType`` 过滤）；
- 返回体统一为 ``{code, message, data, meta}``，并显式标注 ``meta.mode=mock``，
  提醒下游「Mock 数据，仅用于联调」。
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .errors import ErrorCode, PmsError
from .spec import ToolSpec

#: 这些参数只用于分页，不参与过滤
PAGE_KEYS = frozenset({"pageNo", "pageSize", "pageNum", "size", "current", "limit"})
#: 参数名 → 数据里可能对应的字段名（mock 样例字段风格不完全统一）
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": (
        "psrName",
        "assetName",
        "deviceName",
        "stationName",
        "nodeName",
        "manufacturerName",
        "instrumentName",
        "programName",
        "planName",
        "defectNo",
    ),
    "deviceId": ("deviceId", "assetId", "psrId"),
    "assetId": ("assetId", "psrId"),
    "psrId": ("psrId", "assetId"),
    "deviceName": ("deviceName", "assetName", "psrName"),
    "stationName": ("stationName",),
    "manufacturerName": ("manufacturerName",),
    "programId": ("programId",),
    "defectId": ("defectId",),
    "instrumentType": ("instrumentType",),
}


def _match_value(actual: Any, expected: Any) -> bool:
    """等值或包含匹配（大小写不敏感；数字按数值比较；列表逐项匹配）。"""
    if actual is None or expected is None:
        return False
    if isinstance(actual, (list, tuple)):
        return any(_match_value(item, expected) for item in actual)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return str(actual).strip().lower() == str(expected).strip().lower()
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return str(actual) == str(expected)
    actual_text = str(actual).strip().lower()
    expected_text = str(expected).strip().lower()
    return actual_text == expected_text or expected_text in actual_text


def _filter_items(items: list[Any], params: Mapping[str, Any]) -> list[Any]:
    """按参数做简单过滤：只对 mock 数据里真实存在的字段生效。"""
    filtered = list(items)
    for key, expected in params.items():
        if key in PAGE_KEYS or expected is None or expected == "":
            continue
        if not isinstance(expected, (str, int, float, bool)):
            continue
        candidates = (key,) + FIELD_ALIASES.get(key, ())
        applicable = [name for name in candidates if any(isinstance(item, Mapping) and name in item for item in filtered)]
        if not applicable:
            continue
        filtered = [
            item
            for item in filtered
            if isinstance(item, Mapping) and any(_match_value(item.get(name), expected) for name in applicable)
        ]
    return filtered


def _param_default(tool: ToolSpec, name: str) -> Any:
    for param in tool.params:
        if param.name == name:
            return param.default
    return None


def _positive_int(value: Any, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


class MockBackend:
    """基于 spec.mock 的本地数据后端。"""

    def __init__(self, spec) -> None:
        self.spec = spec

    def call(self, tool: ToolSpec, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """返回 mock 数据归一化响应。"""
        args = dict(params or {})
        if tool.mock is None:
            raise PmsError(
                ErrorCode.MOCK_ERROR,
                f"工具 {tool.name} 在 spec/interfaces.json 中没有 mock 数据，mock 模式无法出数；"
                "请补充该工具的 mock 字段，或切换到真实网关模式",
                tool=tool.name,
            )
        if tool.is_paged or isinstance(tool.mock, list):
            data = self._paged_data(tool, args)
        else:
            data = copy.deepcopy(tool.mock)
        return {
            "code": 0,
            "message": "mock 数据（内置样例，仅用于联调，不代表真实业务数据）",
            "data": data,
            "meta": {
                "mode": "mock",
                "tool": tool.name,
                "interfaceCode": tool.code,
                "paged": bool(tool.is_paged),
            },
        }

    # -- 内部 -----------------------------------------------------------
    def _paged_data(self, tool: ToolSpec, params: Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(tool.mock, list):
            total_items: list[Any] = list(tool.mock)
        elif isinstance(tool.mock, Mapping):
            total_items = []
            for key in ("list", "records", "rows", "items"):
                value = tool.mock.get(key)
                if isinstance(value, list):
                    total_items = list(value)
                    break
        else:
            raise PmsError(
                ErrorCode.MOCK_ERROR,
                f"工具 {tool.name} 的 mock 数据结构不符合分页约定（应为含 list 的对象或数组）",
                tool=tool.name,
            )

        filtered = _filter_items(total_items, params)
        page_no = _positive_int(params.get("pageNo"), _positive_int(_param_default(tool, "pageNo"), 1))
        page_size = _positive_int(params.get("pageSize"), _positive_int(_param_default(tool, "pageSize"), 20))
        page_size = min(page_size, 500)
        start = (page_no - 1) * page_size
        page_items = filtered[start : start + page_size]
        return {
            "total": len(filtered),
            "pageNo": page_no,
            "pageSize": page_size,
            "list": copy.deepcopy(page_items),
        }

    def preview(self, tool: ToolSpec, limit: int = 1) -> list[Any]:
        """返回前若干条 mock 数据（供 CLI describe / doctor 展示）。"""
        mock = tool.mock
        if isinstance(mock, list):
            return copy.deepcopy(mock[:limit])
        if isinstance(mock, Mapping):
            for key in ("list", "records", "rows", "items"):
                value = mock.get(key)
                if isinstance(value, list):
                    return copy.deepcopy(value[:limit])
            return [copy.deepcopy(mock)]
        return []
