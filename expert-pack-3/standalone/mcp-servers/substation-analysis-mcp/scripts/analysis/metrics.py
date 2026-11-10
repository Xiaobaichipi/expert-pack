#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""派生指标计算（由设备数据包确定性推导）。

输出 9 个指标：

===================  ==========================================================
指标                  口径
===================  ==========================================================
defectRate           缺陷数 / 设备数（单设备即缺陷条数，条/台）
criticalOpen         危急且未闭环缺陷数（条）
overdueOpen          超期未消缺数（危急>1 天、严重>7 天、一般>30 天，按 as-of 计）
repairPlanCompletion 检修计划完成率（%，已完成计划/计划总数）
testCompletion       修试完成率（%，最近一次试验在有效期内记 100，否则 0）
loadRate             负载率（%），优先 load.loadRate，否则 current/rated 计算
openCapacityRatio    可开放容量比（%），openCapacityMVA/ratedCapacityMVA
availabilityRate     可用率（%），取 reliability.availabilityRate
trend                缺陷趋势（bundle 无多期时间序列时为 null 并写入 dataGaps）
===================  ==========================================================

数据段缺失或字段不足时指标返回 ``null`` 并写入 ``dataGaps``，不得用推测值补齐。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import format_number, load_scorecard, round_half_up
from .evidence import (
    compute_load_rate,
    compute_open_capacity_ratio,
    data_gap,
    dedupe_gaps,
    defect_open_days,
    is_open_defect,
    latest_test_date,
    normalize_defect_level,
    pick,
    require_bundle,
    resolve_as_of,
)

__all__ = [
    "compute_device_metrics",
]

_METRIC_ORDER = (
    "defectRate",
    "criticalOpen",
    "overdueOpen",
    "repairPlanCompletion",
    "testCompletion",
    "loadRate",
    "openCapacityRatio",
    "availabilityRate",
    "trend",
)

_COMPLETED_PLAN_STATUSES = frozenset(
    {"已完成", "完成", "已完工", "已竣工", "已关闭", "closed", "done", "finish", "finished"}
)


def _is_completed_plan(status: Any) -> bool:
    if not isinstance(status, str):
        return False
    text = status.strip()
    if text in _COMPLETED_PLAN_STATUSES:
        return True
    return "已完成" in text or "完成" in text or "竣工" in text


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def compute_device_metrics(
    bundle: dict[str, Any], as_of: str | date | None = None
) -> dict[str, Any]:
    """由设备数据包计算派生指标、分母与数据缺口。"""
    require_bundle(bundle)
    card = load_scorecard("default")
    as_of_date = resolve_as_of(bundle, as_of)
    dimensions = [item for item in (card.get("dimensions") or []) if isinstance(item, dict)]
    defects_dim = next((item for item in dimensions if item.get("id") == "defects"), {})
    tests_dim = next((item for item in dimensions if item.get("id") == "tests"), {})
    overdue_cfg = (defects_dim.get("rules") or {}).get("overdue") or {}
    overdue_limits = overdue_cfg.get("overdueDays") or {"危急": 1, "严重": 7, "一般": 30}
    stale_days = int(((tests_dim.get("rules") or {}).get("stale") or {}).get("staleDays", 1095))

    metrics: dict[str, Any] = {key: None for key in _METRIC_ORDER}
    denominators: dict[str, Any] = {
        "deviceCount": 1,
        "defectCount": None,
        "openDefectCount": None,
        "faultCount": None,
        "testCount": None,
        "repairPlanCount": None,
        "ratedCapacityMVA": None,
        "currentLoadMVA": None,
        "openCapacityMVA": None,
    }
    gaps: list[dict[str, Any]] = []

    # ---- 缺陷类指标 ----
    defects_value = bundle.get("defects")
    if "defects" not in bundle or defects_value is None:
        gaps.append(data_gap("defects", None, "bundle 未提供 defects 段，缺陷率/危急未闭环/超期未消缺无法计算"))
    else:
        defects = [item for item in defects_value if isinstance(item, dict)] if isinstance(defects_value, list) else []
        open_defects = [item for item in defects if is_open_defect(item)]
        denominators["defectCount"] = len(defects)
        denominators["openDefectCount"] = len(open_defects)
        metrics["defectRate"] = round_half_up(len(defects) / max(int(denominators["deviceCount"]), 1), 2)
        critical_open = 0
        for defect in open_defects:
            if normalize_defect_level(pick(defect, "level", "defectLevel", "severity")) == "危急":
                critical_open += 1
        metrics["criticalOpen"] = critical_open

        if as_of_date is None:
            gaps.append(data_gap("defects", "overdueOpen", "缺少时间基准，超期未消缺无法计算"))
        else:
            overdue_open = 0
            missing_time = 0
            for defect in open_defects:
                days = defect_open_days(defect, as_of_date)
                if days is None:
                    missing_time += 1
                    continue
                level = normalize_defect_level(pick(defect, "level", "defectLevel", "severity")) or "一般"
                if days > int(overdue_limits.get(level, 0)):
                    overdue_open += 1
            metrics["overdueOpen"] = overdue_open
            if missing_time:
                gaps.append(
                    data_gap(
                        "defects",
                        "discoverTime",
                        f"{missing_time} 条未闭环缺陷缺少发现时间，未计入超期未消缺统计",
                    )
                )

    # ---- 检修计划完成率 ----
    plans_value = bundle.get("repairPlans")
    if "repairPlans" not in bundle or plans_value is None:
        gaps.append(data_gap("repairPlans", None, "bundle 未提供 repairPlans 段，检修计划完成率无法计算"))
    else:
        plans = [item for item in plans_value if isinstance(item, dict)] if isinstance(plans_value, list) else []
        denominators["repairPlanCount"] = len(plans)
        if not plans:
            gaps.append(data_gap("repairPlans", None, "无检修计划记录，检修计划完成率无法计算"))
        else:
            completed = sum(1 for plan in plans if _is_completed_plan(pick(plan, "status", "planStatus")))
            metrics["repairPlanCompletion"] = round_half_up(completed / len(plans) * 100.0, 2)

    # ---- 修试完成率 ----
    tests_value = bundle.get("tests")
    if "tests" not in bundle or tests_value is None:
        gaps.append(data_gap("tests", None, "bundle 未提供 tests 段，修试完成率无法计算"))
    else:
        tests = [item for item in tests_value if isinstance(item, dict)] if isinstance(tests_value, list) else []
        denominators["testCount"] = len(tests)
        if not tests:
            metrics["testCompletion"] = 0.0
            gaps.append(data_gap("tests", None, "无试验/修试记录，修试完成率按 0 计"))
        elif as_of_date is None:
            gaps.append(data_gap("tests", "testDate", "缺少时间基准，修试完成率无法判断"))
        else:
            latest, _record = latest_test_date(tests)
            if latest is None:
                gaps.append(data_gap("tests", "testDate", "试验记录均缺少 testDate，修试完成率无法判断"))
            else:
                metrics["testCompletion"] = (
                    100.0 if (as_of_date - latest).days <= stale_days else 0.0
                )
                if metrics["testCompletion"] == 0.0:
                    gaps.append(
                        data_gap(
                            "tests",
                            "testDate",
                            f"最近一次试验已超过 {stale_days} 天有效期，修试完成率按 0 计",
                        )
                    )

    # ---- 负载类指标 ----
    load = bundle.get("load")
    if not isinstance(load, dict):
        gaps.append(data_gap("load", None, "bundle 未提供 load 段，负载率/可开放容量比无法计算"))
    else:
        denominators["ratedCapacityMVA"] = _numeric(load.get("ratedCapacityMVA"))
        denominators["currentLoadMVA"] = _numeric(load.get("currentLoadMVA"))
        denominators["openCapacityMVA"] = _numeric(load.get("openCapacityMVA"))
        rate = compute_load_rate(load)
        if rate is None:
            gaps.append(
                data_gap("load", "loadRate", "load 段缺少 loadRate 或 ratedCapacityMVA/currentLoadMVA")
            )
        else:
            metrics["loadRate"] = round_half_up(rate, 2)
        ratio = compute_open_capacity_ratio(load)
        if ratio is None:
            gaps.append(
                data_gap(
                    "load",
                    "openCapacityMVA",
                    "load 段缺少 ratedCapacityMVA/openCapacityMVA，可开放容量比无法计算",
                )
            )
        else:
            metrics["openCapacityRatio"] = round_half_up(ratio, 2)

    # ---- 可靠率 ----
    reliability = bundle.get("reliability")
    if not isinstance(reliability, dict):
        gaps.append(data_gap("reliability", None, "bundle 未提供 reliability 段，可用率无法计算"))
    else:
        availability = _numeric(reliability.get("availabilityRate"))
        if availability is None:
            gaps.append(data_gap("reliability", "availabilityRate", "缺少 availabilityRate，可用率无法计算"))
        else:
            metrics["availabilityRate"] = round_half_up(availability, 2)

    # ---- 趋势 ----
    gaps.append(
        data_gap(
            "trend",
            "trend",
            "bundle 未提供多期缺陷/负载时间序列，缺陷趋势无法计算（不使用推测值）",
        )
    )

    gaps = dedupe_gaps(gaps)
    summary = (
        "派生指标："
        f"缺陷率 {format_number(metrics['defectRate']) if metrics['defectRate'] is not None else 'null'}、"
        f"危急未闭环 {metrics['criticalOpen'] if metrics['criticalOpen'] is not None else 'null'} 条、"
        f"超期未消缺 {metrics['overdueOpen'] if metrics['overdueOpen'] is not None else 'null'} 条、"
        f"负载率 {format_number(metrics['loadRate']) if metrics['loadRate'] is not None else 'null'}%"
    )
    return {
        "metrics": metrics,
        "denominators": denominators,
        "dataGaps": gaps,
        "summary": summary,
        "asOf": as_of_date.isoformat() if as_of_date else None,
    }
