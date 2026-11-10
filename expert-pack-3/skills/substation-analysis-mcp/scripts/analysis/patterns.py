#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺陷模式识别：同部位重复缺陷簇 + 家族性缺陷簇。

- 重复缺陷簇：同一设备同一部位在窗口内出现 ≥2 次（部位做去空格归一）；
- 家族性缺陷簇：同型号 + 同厂家 + 同部位，涉及不同设备数 ≥ ``family_min_count``（默认 3）；
- 输出缺陷清单、等级分布、首末发现时间与设备名列表，便于上层编排定位到具体设备；
- 数据不足（部位/型号/厂家/发现时间缺失）时写入 ``dataGaps``，不做推测补齐。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import BundleError, parse_date
from .evidence import data_gap, dedupe_gaps, pick

__all__ = [
    "detect_defect_patterns",
    "detect_defect_patterns_from_bundle",
]

_LEVEL_ORDER = ("危急", "严重", "一般")
_STATUS_ORDER = ("待处理", "处理中", "已消除")
_UNKNOWN_DEVICE = "未标注设备"
_UNKNOWN_PART = "未标注部位"


def _defect_desc(value: Any, limit: int = 80) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:limit] + "…" if len(text) > limit else text


def _resolve_device_name(defect: dict[str, Any], device_meta: dict[str, Any]) -> str:
    name = pick(defect, "deviceName", "device", "psrName")
    if not name:
        name = device_meta.get("name") or device_meta.get("psrName")
    return str(name).strip() if name else _UNKNOWN_DEVICE


def _resolve_model(defect: dict[str, Any], device_meta: dict[str, Any]) -> str:
    value = pick(defect, "model", "deviceModel")
    if not value:
        value = device_meta.get("model")
    return str(value).strip() if value else ""


def _resolve_manufacturer(defect: dict[str, Any], device_meta: dict[str, Any]) -> str:
    value = pick(defect, "manufacturer", "deviceManufacturer", "vendor")
    if not value:
        value = device_meta.get("manufacturer")
    return str(value).strip() if value else ""


def _resolve_part(defect: dict[str, Any]) -> str:
    value = pick(defect, "part", "defectPart")
    return str(value).strip() if value else ""


def _resolve_time(defect: dict[str, Any]) -> Any:
    return pick(defect, "discoverTime", "foundTime", "discoverDate")


def _count_by(values: list[str], order: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value in order:
            counts[value] = counts.get(value, 0) + 1
    for value in values:
        if value not in order:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _slim_defect(defect: dict[str, Any], part: str, device_name: str) -> dict[str, Any]:
    return {
        "defectId": pick(defect, "defectId", "defectNo", "id"),
        "level": pick(defect, "level", "defectLevel"),
        "status": pick(defect, "status", "defectStatus"),
        "discoverTime": _resolve_time(defect),
        "part": part,
        "deviceName": device_name,
        "desc": _defect_desc(pick(defect, "desc", "description", "defectDesc")),
    }


def detect_defect_patterns(
    defects: list[dict[str, Any]],
    device_meta: dict[str, Any] | None = None,
    window_days: int = 365,
    family_min_count: int = 3,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    """对缺陷记录做重复缺陷簇与家族性缺陷簇聚类（确定性、无网络）。"""
    if not isinstance(defects, list):
        raise BundleError("defects 必须是数组（缺陷记录）")
    meta = device_meta if isinstance(device_meta, dict) else {}
    window = int(window_days) if isinstance(window_days, int) and window_days > 0 else 365
    family_min = int(family_min_count) if isinstance(family_min_count, int) and family_min_count > 1 else 3

    as_of_date = parse_date(as_of) if as_of is not None else None
    gaps: list[dict[str, Any]] = []
    if as_of is not None and as_of_date is None:
        gaps.append(data_gap("defects", "asOf", f"as-of 时间无法解析：{as_of!r}，未按窗口过滤"))

    valid: list[tuple[int, dict[str, Any], str, str, str, str]] = []
    missing_time = 0
    missing_part = 0
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            gaps.append(data_gap("defects", "record", f"第 {index + 1} 条缺陷记录不是对象，已跳过"))
            continue
        discover_time = _resolve_time(defect)
        parsed_time = parse_date(discover_time)
        if parsed_time is None:
            missing_time += 1
        part = _resolve_part(defect)
        if not part:
            missing_part += 1
        valid.append(
            (
                index,
                defect,
                _resolve_device_name(defect, meta),
                _resolve_model(defect, meta),
                _resolve_manufacturer(defect, meta),
                part,
            )
        )

    if as_of is None and valid:
        latest = max(
            (
                parsed
                for _, defect, *_ in valid
                if (parsed := parse_date(_resolve_time(defect))) is not None
            ),
            default=None,
        )
        if latest is not None:
            as_of_date = latest

    used: list[tuple[int, dict[str, Any], str, str, str, str]] = []
    for item in valid:
        _, defect, _device, _model, _manufacturer, _part = item
        parsed_time = parse_date(_resolve_time(defect))
        if as_of_date is not None and parsed_time is not None:
            if (as_of_date - parsed_time).days > window:
                continue
        used.append(item)

    if missing_time:
        gaps.append(
            data_gap(
                "defects",
                "discoverTime",
                f"{missing_time} 条缺陷缺少有效发现时间，按「记录仍在窗口内」参与聚类",
            )
        )
    if missing_part:
        gaps.append(
            data_gap("defects", "part", f"{missing_part} 条缺陷缺少部位字段，已归入「{_UNKNOWN_PART}」")
        )
    if not meta.get("model") or not meta.get("manufacturer"):
        gaps.append(
            data_gap(
                "device",
                "model/manufacturer",
                "device_meta 缺少 model/manufacturer，家族性缺陷判定可能不完整",
            )
        )
    if not used:
        gaps.append(data_gap("defects", None, "窗口内没有可用缺陷记录"))

    # ---- 重复缺陷簇：同一设备 + 同一部位 ≥2 次 ----
    duplicate_groups: dict[tuple[str, str], list[tuple[int, dict[str, Any], str, str, str, str]]] = {}
    for item in used:
        _, _defect, device_name, _model, _manufacturer, part = item
        key = (device_name, part or _UNKNOWN_PART)
        duplicate_groups.setdefault(key, []).append(item)

    duplicate_clusters: list[dict[str, Any]] = []
    for (device_name, part), items in duplicate_groups.items():
        if len(items) < 2:
            continue
        times = sorted(
            str(_resolve_time(item[1]))
            for item in items
            if _resolve_time(item[1]) is not None
        )
        levels = _count_by(
            [str(pick(item[1], "level", "defectLevel") or "未标注") for item in items],
            _LEVEL_ORDER,
        )
        statuses = _count_by(
            [str(pick(item[1], "status", "defectStatus") or "未标注") for item in items],
            _STATUS_ORDER,
        )
        duplicate_clusters.append(
            {
                "part": part,
                "deviceName": device_name,
                "count": len(items),
                "defectIds": [pick(item[1], "defectId", "defectNo", "id") for item in items],
                "levels": levels,
                "statuses": statuses,
                "firstTime": times[0] if times else None,
                "lastTime": times[-1] if times else None,
                "defects": [_slim_defect(item[1], part, device_name) for item in items],
            }
        )
    duplicate_clusters.sort(
        key=lambda cluster: (-cluster["count"], cluster["part"], cluster["deviceName"])
    )
    for index, cluster in enumerate(duplicate_clusters, start=1):
        cluster["clusterId"] = f"DUP-{index}"

    # ---- 家族性缺陷簇：同型号 + 同厂家 + 同部位，设备数 ≥ family_min_count ----
    family_groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any], str, str, str, str]]] = {}
    for item in used:
        _, _defect, device_name, model, manufacturer, part = item
        if not model or not manufacturer or not part:
            continue
        family_groups.setdefault((model, manufacturer, part), []).append(item)

    family_clusters: list[dict[str, Any]] = []
    for (model, manufacturer, part), items in family_groups.items():
        device_names = sorted({item[2] for item in items})
        if len(device_names) < family_min:
            continue
        times = sorted(
            str(_resolve_time(item[1]))
            for item in items
            if _resolve_time(item[1]) is not None
        )
        family_clusters.append(
            {
                "model": model,
                "manufacturer": manufacturer,
                "part": part,
                "deviceCount": len(device_names),
                "deviceNames": device_names,
                "count": len(items),
                "defectIds": [pick(item[1], "defectId", "defectNo", "id") for item in items],
                "firstTime": times[0] if times else None,
                "lastTime": times[-1] if times else None,
                "defects": [
                    _slim_defect(item[1], part, item[2])
                    for item in sorted(items, key=lambda entry: entry[2])
                ],
            }
        )
    family_clusters.sort(
        key=lambda cluster: (
            -cluster["deviceCount"],
            cluster["part"],
            cluster["model"],
            cluster["manufacturer"],
        )
    )
    for index, cluster in enumerate(family_clusters, start=1):
        cluster["clusterId"] = f"FAM-{index}"

    gaps = dedupe_gaps(gaps)
    summary = {
        "defectCount": len(defects),
        "evaluatedCount": len(used),
        "windowDays": window,
        "familyMinCount": family_min,
        "asOf": as_of_date.isoformat() if as_of_date else None,
        "duplicateClusterCount": len(duplicate_clusters),
        "familyClusterCount": len(family_clusters),
        "dataGaps": gaps,
    }
    return {
        "duplicateClusters": duplicate_clusters,
        "familyClusters": family_clusters,
        "summary": summary,
        "dataGaps": gaps,
    }


def detect_defect_patterns_from_bundle(
    bundle: dict[str, Any], as_of: str | date | None = None
) -> dict[str, Any]:
    """从设备数据包识别缺陷模式（供 diagnose_equipment 复用）。"""
    if not isinstance(bundle, dict):
        raise BundleError("bundle 必须是 JSON 对象")
    defects = bundle.get("defects")
    device_meta = bundle.get("device") if isinstance(bundle.get("device"), dict) else {}
    if not isinstance(defects, list):
        defects = []
    return detect_defect_patterns(
        defects,
        device_meta=device_meta,
        as_of=as_of,
    )
