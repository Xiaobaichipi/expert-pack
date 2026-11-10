#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""证据链与数据包取数辅助。

本模块把「扣分/假设为什么成立」所需的公共能力集中起来：

- 数据包字段与来源接口编码的映射（``source_for_section``），保证每条证据都能追溯到
  ``sourceMeta`` 中的接口编码；数据包未记录时回退到 spec/interfaces.json 的接口编码；
- 数据段存在性判断与 ``dataGaps`` 构造（缺数据必须显式声明，不得用推测值补齐）；
- 记录全文展开（关键词匹配用）、缺陷状态/等级归一、日期差计算；
- ``evidence`` 统一结构：``{ruleId, dimension, delta, reason, source, data}``。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from .config import (
    BundleError,
    format_number,
    parse_date,
)

__all__ = [
    "CLOSED_DEFECT_STATUSES",
    "TOOL_CODES",
    "SECTION_TOOL",
    "DIMENSION_TOOL",
    "source_for_section",
    "source_for_dimension",
    "require_bundle",
    "section_presence",
    "data_gap",
    "dedupe_gaps",
    "record_text",
    "pick",
    "scope_records",
    "resolve_as_of",
    "is_closed_status",
    "is_open_defect",
    "normalize_defect_level",
    "days_since",
    "defect_open_days",
    "latest_test_date",
    "make_evidence",
    "dedupe_evidence",
    "compute_load_rate",
    "compute_open_capacity_ratio",
]

#: 视为「已闭环」的缺陷状态（其余状态按未闭环处理）
CLOSED_DEFECT_STATUSES = frozenset({"已消除", "已关闭", "已验收", "closed", "Closed", "CLOSED"})

#: 数据来源接口编码（与 spec/interfaces.json 保持一致，仅用于证据链展示）
TOOL_CODES: dict[str, str] = {
    "get_asset_by_id": "pgp-102-2411-00102",
    "list_psr_by_filters": "pgp-101-2411-00102",
    "get_psr_by_id": "pgp-101-2411-00103",
    "inquire_defect": "pgp-106-2411-00703",
    "view_defect": "pgp-106-2411-00704",
    "list_hazard": "pgp-106-2411-01003",
    "list_fault_trip_records": "pgp-106-2411-02603",
    "get_repair_plan": "pgp-106-2411-04206",
    "find_repair_test": "pgp-106-2411-05003",
    "list_patrol_record": "pgp-106-2411-00403",
    "query_open_capacity": "pgp-108-2411-00201",
    "query_station_scale_analysis": "pgp-108-2411-00405",
}

#: 数据包段 -> 取数工具
SECTION_TOOL: dict[str, str] = {
    "device": "get_asset_by_id",
    "defects": "inquire_defect",
    "hazards": "list_hazard",
    "faults": "list_fault_trip_records",
    "tests": "find_repair_test",
    "repairPlans": "get_repair_plan",
    "patrolRecords": "list_patrol_record",
    "load": "query_open_capacity",
    "reliability": "query_station_scale_analysis",
}

#: 评分维度 -> 取数工具（台账维度来自设备台账接口）
DIMENSION_TOOL: dict[str, str] = {
    "defects": "inquire_defect",
    "faults": "list_fault_trip_records",
    "tests": "find_repair_test",
    "load": "query_open_capacity",
    "ledger": "get_asset_by_id",
}


def _source_meta_entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    meta = bundle.get("sourceMeta")
    if not isinstance(meta, list):
        return []
    return [item for item in meta if isinstance(item, dict)]


def source_for_section(section: str, bundle: dict[str, Any] | None = None) -> list[str]:
    """返回数据段对应的接口编码列表；优先使用数据包 ``sourceMeta`` 记录。"""
    tool = SECTION_TOOL.get(section)
    if tool is None:
        return []
    if bundle is not None:
        for entry in _source_meta_entries(bundle):
            if entry.get("tool") == tool and entry.get("interfaceCode"):
                return [str(entry["interfaceCode"])]
    code = TOOL_CODES.get(tool)
    return [code] if code else []


def source_for_dimension(dimension: str, bundle: dict[str, Any] | None = None) -> list[str]:
    tool = DIMENSION_TOOL.get(dimension)
    if tool is None:
        return []
    if bundle is not None:
        for entry in _source_meta_entries(bundle):
            if entry.get("tool") == tool and entry.get("interfaceCode"):
                return [str(entry["interfaceCode"])]
    code = TOOL_CODES.get(tool)
    return [code] if code else []


def require_bundle(bundle: Any) -> dict[str, Any]:
    """校验输入数据包最小契约：必须是对象且 ``device.name`` 非空。"""
    if not isinstance(bundle, dict):
        raise BundleError("bundle 必须是 JSON 对象（字段见 spec/analysis-bundle.schema.json）")
    device = bundle.get("device")
    if not isinstance(device, dict):
        raise BundleError("bundle.device 必填，且必须是对象")
    name = device.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BundleError("bundle.device.name 必填（设备名称）")
    return bundle


def _section_present(value: Any) -> bool:
    """数据段存在 = 键存在且值非 None（空列表代表「已查询、无记录」，仍算存在）。"""
    return value is not None


def section_presence(bundle: dict[str, Any], sections: Iterable[str]) -> tuple[list[str], list[str]]:
    """判断数据包中哪些数据段存在，返回 (present, missing)。"""
    present: list[str] = []
    missing: list[str] = []
    for section in sections:
        if section in bundle and _section_present(bundle.get(section)):
            present.append(section)
        else:
            missing.append(section)
    return present, missing


def data_gap(section: str, field: str | None, reason: str) -> dict[str, Any]:
    """构造统一的 dataGaps 条目。"""
    return {"section": section, "field": field, "reason": reason}


def dedupe_gaps(gaps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 (section, field, reason) 去重并保持首次出现顺序。"""
    seen: set[tuple[Any, Any, Any]] = set()
    result: list[dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        key = (gap.get("section"), gap.get("field"), gap.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        result.append(gap)
    return result


def record_text(record: Any) -> str:
    """把一条记录（含嵌套 list/dict）展开为可供关键词匹配的文本。"""
    parts: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, bool):
            parts.append("是" if value else "否")
        elif isinstance(value, (int, float)):
            parts.append(format_number(value))
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)

    _walk(record)
    return " ".join(part for part in parts if part).strip()


def pick(record: Any, *keys: str, default: Any = None) -> Any:
    """按候选字段名取值（兼容接口原样字段名，如 level/defectLevel）。"""
    if isinstance(record, dict):
        for key in keys:
            value = record.get(key)
            if value is not None and value != "":
                return value
    return default


def scope_records(bundle: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    """按数据段名取出记录列表；对象型数据段（device/load/reliability）包装为单元素列表。"""
    if scope == "device":
        device = bundle.get("device")
        return [device] if isinstance(device, dict) else []
    value = bundle.get(scope)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def resolve_as_of(bundle: dict[str, Any], as_of: str | date | None = None) -> date | None:
    """解析评分/诊断时间基准：显式 ``as_of`` 优先，否则取 ``bundle.timeWindow.end``。"""
    if as_of is not None:
        parsed = parse_date(as_of)
        if parsed is None:
            raise BundleError(f"as-of 时间无法解析：{as_of!r}，应为 yyyy-MM-dd 或 ISO 日期时间")
        return parsed
    time_window = bundle.get("timeWindow")
    if isinstance(time_window, dict):
        return parse_date(time_window.get("end"))
    return None


def is_closed_status(status: Any) -> bool:
    return isinstance(status, str) and status.strip() in CLOSED_DEFECT_STATUSES


def is_open_defect(defect: dict[str, Any]) -> bool:
    """未闭环缺陷：状态非「已消除/已关闭」；状态缺失时按未闭环处理（由调用方记 dataGap）。"""
    return not is_closed_status(defect.get("status"))


def normalize_defect_level(level: Any) -> str | None:
    """归一缺陷等级；无法识别返回 None。"""
    if isinstance(level, str):
        text = level.strip()
        if text in ("危急", "严重", "一般"):
            return text
    return None


def days_since(value: Any, as_of: date | None) -> int | None:
    """返回 ``as_of - value`` 的天数；日期或基准缺失时返回 None。"""
    if as_of is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        return None
    return (as_of - parsed).days


def defect_open_days(defect: dict[str, Any], as_of: date | None) -> int | None:
    """缺陷已持续时间（天），以发现时间为起点；日期缺失返回 None。"""
    return days_since(defect.get("discoverTime") or defect.get("foundTime"), as_of)


def latest_test_date(tests: Iterable[Any]) -> tuple[date | None, dict[str, Any] | None]:
    """返回 (最近一次试验日期, 对应记录)。"""
    latest: date | None = None
    latest_record: dict[str, Any] | None = None
    for record in tests:
        if not isinstance(record, dict):
            continue
        parsed = parse_date(record.get("testDate") or record.get("testTime"))
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
            latest_record = record
    return latest, latest_record


def make_evidence(
    rule_id: str,
    dimension: str,
    reason: str,
    *,
    source: Iterable[str] | None = None,
    data: Any = None,
    delta: int | None = None,
) -> dict[str, Any]:
    """构造统一证据条目。``delta`` 仅评分扣分证据携带。"""
    evidence: dict[str, Any] = {"ruleId": rule_id, "dimension": dimension}
    if delta is not None:
        evidence["delta"] = int(delta)
    evidence["reason"] = reason
    evidence["source"] = [str(item) for item in (source or []) if item]
    evidence["data"] = data if data is not None else {}
    return evidence


def dedupe_evidence(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 (ruleId, reason, data) 去重并保持顺序，避免同一记录被多条条件重复计入。"""
    seen: set[tuple[Any, Any, Any]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (item.get("ruleId"), item.get("reason"), _freeze(item.get("data")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(val)) for key, val in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def compute_load_rate(load: Any) -> float | None:
    """负载率（%）：优先取 ``loadRate``，否则由 currentLoadMVA / ratedCapacityMVA 计算。"""
    if not isinstance(load, dict):
        return None
    rate = load.get("loadRate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        return float(rate)
    rated = load.get("ratedCapacityMVA")
    current = load.get("currentLoadMVA")
    if (
        isinstance(rated, (int, float))
        and not isinstance(rated, bool)
        and isinstance(current, (int, float))
        and not isinstance(current, bool)
        and float(rated) > 0
    ):
        return float(current) / float(rated) * 100.0
    return None


def compute_open_capacity_ratio(load: Any) -> float | None:
    """可开放容量比（%）= openCapacityMVA / ratedCapacityMVA * 100。"""
    if not isinstance(load, dict):
        return None
    rated = load.get("ratedCapacityMVA")
    open_capacity = load.get("openCapacityMVA")
    if (
        isinstance(rated, (int, float))
        and not isinstance(rated, bool)
        and isinstance(open_capacity, (int, float))
        and not isinstance(open_capacity, bool)
        and float(rated) > 0
    ):
        return float(open_capacity) / float(rated) * 100.0
    return None
