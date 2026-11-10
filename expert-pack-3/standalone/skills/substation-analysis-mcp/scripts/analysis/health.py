#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""健康度评分卡引擎（单设备 + 站级）。

评分逻辑
--------
- 五个维度：缺陷 0.30、故障 0.25、修试 0.20、负载 0.15、台账 0.10（权重/阈值全部来自
  ``config/scorecard.json``），每维从 100 分起扣，单维扣分上限 100；
- 总分 = Σ(维度权重 × 维度得分)，保留 1 位小数（half-up）；
- 等级 A≥90 / B≥80 / C≥70 / D≥60 / E<60，并给出标签与风险；
- 置信度 = 0.9 − 0.05×缺失数据段数（最多 −0.4）− 0.1×(数据截止晚于 as-of 超 180 天)，
  clamp 到 [0.30, 0.95]；同时输出 completeness（present/total）；
- 每个扣分项输出 ``{ruleId, dimension, delta, reason, source, data}`` 证据链，
  来源接口编码优先取 ``bundle.sourceMeta``。

确定性
------
评分不读取系统时钟：时间基准为 ``as_of`` 参数，缺省取 ``bundle.timeWindow.end``。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import BundleError, clamp, format_number, load_scorecard, parse_date, round_half_up
from .evidence import (
    compute_load_rate,
    compute_open_capacity_ratio,
    data_gap,
    days_since,
    dedupe_gaps,
    defect_open_days,
    is_closed_status,
    is_open_defect,
    latest_test_date,
    make_evidence,
    normalize_defect_level,
    pick,
    require_bundle,
    resolve_as_of,
    section_presence,
    source_for_dimension,
)

__all__ = [
    "DEFAULT_PROFILE",
    "assess_device_health",
    "assess_station_health",
]

DEFAULT_PROFILE = "default"

_REASON_MAX_LEN = 40


# ---------------------------------------------------------------------------
# 单条缺陷/故障/试验记录字段兼容取值
# ---------------------------------------------------------------------------
def _defect_level(defect: dict[str, Any]) -> Any:
    return pick(defect, "level", "defectLevel", "severity")


def _defect_status(defect: dict[str, Any]) -> Any:
    return pick(defect, "status", "defectStatus", "handleStatus")


def _defect_time(defect: dict[str, Any]) -> Any:
    return pick(defect, "discoverTime", "foundTime", "discoverDate")


def _defect_label(defect: dict[str, Any]) -> str:
    desc = pick(defect, "desc", "description", "defectDesc")
    part = pick(defect, "part", "defectPart")
    defect_id = pick(defect, "defectId", "defectNo", "id")
    text = str(desc or part or "")
    if len(text) > _REASON_MAX_LEN:
        text = text[:_REASON_MAX_LEN] + "…"
    if defect_id:
        return f"{text}（{defect_id}）" if text else f"（{defect_id}）"
    return text


def _fault_time(fault: dict[str, Any]) -> Any:
    return pick(fault, "time", "faultTime", "tripTime")


def _fault_label(fault: dict[str, Any]) -> str:
    fault_id = pick(fault, "faultId", "id")
    cause = pick(fault, "cause", "description", "faultCause")
    text = str(cause or "")
    if len(text) > _REASON_MAX_LEN:
        text = text[:_REASON_MAX_LEN] + "…"
    if fault_id:
        return f"{text}（{fault_id}）" if text else f"（{fault_id}）"
    return text


def _test_label(record: dict[str, Any]) -> str:
    record_id = pick(record, "recordId", "testId", "id")
    test_type = pick(record, "testType", "type")
    test_date = pick(record, "testDate", "testTime")
    parts = [str(item) for item in (test_type, test_date) if item]
    text = " ".join(parts)
    if record_id:
        return f"{text}（{record_id}）" if text else f"（{record_id}）"
    return text


# ---------------------------------------------------------------------------
# 各维度扣分
# ---------------------------------------------------------------------------
def _eval_defects(
    bundle: dict[str, Any], dimension: dict[str, Any], as_of: date | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    defects = bundle.get("defects")
    if not isinstance(defects, list) or not defects:
        return [], []
    rules = dimension["rules"]
    level_rule_key = {"危急": "criticalOpen", "严重": "seriousOpen", "一般": "normalOpen"}
    overdue_rule = rules.get("overdue") or {}
    overdue_days_cfg = overdue_rule.get("overdueDays") or {"危急": 1, "严重": 7, "一般": 30}
    overdue_delta = int(overdue_rule.get("delta", -10))
    deductions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            gaps.append(data_gap("defects", "record", f"第 {index + 1} 条缺陷记录不是对象，已跳过"))
            continue
        status = _defect_status(defect)
        if is_closed_status(status):
            continue
        if status is None:
            gaps.append(
                data_gap("defects", "status", f"第 {index + 1} 条缺陷缺少 status，按未闭环计入")
            )
        level = normalize_defect_level(_defect_level(defect))
        if level is None:
            gaps.append(
                data_gap(
                    "defects",
                    "level",
                    f"第 {index + 1} 条缺陷等级缺失或非标准（{_defect_level(defect)!r}），按「一般」计入",
                )
            )
            level = "一般"
        rule_key = level_rule_key[level]
        delta = int((rules.get(rule_key) or {}).get("delta", 0))
        data = {
            "defectId": pick(defect, "defectId", "defectNo", "id"),
            "level": level,
            "status": status,
            "discoverTime": _defect_time(defect),
            "part": pick(defect, "part", "defectPart"),
        }
        deductions.append(
            make_evidence(
                f"DEF-{rule_key.upper()}",
                "defects",
                f"{level}缺陷未闭环：{_defect_label(defect)}",
                source=source_for_dimension("defects", bundle),
                data=data,
                delta=delta,
            )
        )
        days = defect_open_days(defect, as_of)
        if days is None:
            if as_of is None:
                gaps.append(
                    data_gap("defects", "discoverTime", "缺少时间基准，缺陷超期天数无法计算")
                )
            elif _defect_time(defect) is None:
                gaps.append(
                    data_gap(
                        "defects",
                        "discoverTime",
                        f"第 {index + 1} 条缺陷缺少发现时间，未计入超期统计",
                    )
                )
            continue
        limit = int(overdue_days_cfg.get(level, 0))
        if days > limit:
            deductions.append(
                make_evidence(
                    "DEF-OVERDUE",
                    "defects",
                    f"{level}缺陷超期未消缺 {days} 天（限值 {limit} 天）：{_defect_label(defect)}",
                    source=source_for_dimension("defects", bundle),
                    data={**data, "openDays": days, "overdueLimitDays": limit},
                    delta=overdue_delta,
                )
            )
    return deductions, gaps


def _eval_faults(
    bundle: dict[str, Any], dimension: dict[str, Any], as_of: date | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    faults = bundle.get("faults")
    if not isinstance(faults, list) or not faults:
        return [], []
    rules = dimension["rules"]
    recent = rules.get("recent") or {"delta": -25, "days": 365}
    mid = rules.get("mid") or {"delta": -10, "days": 1095}
    deductions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for index, fault in enumerate(faults):
        if not isinstance(fault, dict):
            gaps.append(data_gap("faults", "record", f"第 {index + 1} 条故障记录不是对象，已跳过"))
            continue
        fault_time = _fault_time(fault)
        if as_of is None:
            gaps.append(data_gap("faults", "time", "缺少时间基准，故障时间窗无法计算"))
            continue
        days = days_since(fault_time, as_of)
        if days is None:
            gaps.append(
                data_gap("faults", "time", f"第 {index + 1} 条故障记录缺少故障时间，未计分")
            )
            continue
        if days < 0:
            days = 0
        data = {
            "faultId": pick(fault, "faultId", "id"),
            "time": fault_time,
            "protectionAction": pick(fault, "protectionAction", "protection"),
        }
        if days <= int(recent.get("days", 365)):
            deductions.append(
                make_evidence(
                    "FAULT-RECENT",
                    "faults",
                    f"近 12 个月故障跳闸：{_fault_label(fault)}",
                    source=source_for_dimension("faults", bundle),
                    data={**data, "daysAgo": days},
                    delta=int(recent.get("delta", -25)),
                )
            )
        elif days <= int(mid.get("days", 1095)):
            deductions.append(
                make_evidence(
                    "FAULT-MID",
                    "faults",
                    f"13-36 个月内故障跳闸：{_fault_label(fault)}",
                    source=source_for_dimension("faults", bundle),
                    data={**data, "daysAgo": days},
                    delta=int(mid.get("delta", -10)),
                )
            )
    return deductions, gaps


def _eval_tests(
    bundle: dict[str, Any], dimension: dict[str, Any], as_of: date | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if "tests" not in bundle:
        return [], []
    tests_raw = bundle.get("tests")
    tests = [item for item in tests_raw if isinstance(item, dict)] if isinstance(tests_raw, list) else []
    rules = dimension["rules"]
    no_record = rules.get("noRecord") or {"delta": -20}
    stale = rules.get("stale") or {"delta": -20, "staleDays": 1095}
    unqualified = rules.get("unqualified") or {"delta": -30, "results": ["不合格", "异常"]}
    deductions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    if not tests:
        deductions.append(
            make_evidence(
                "TEST-NO-RECORD",
                "tests",
                "无试验/修试记录",
                source=source_for_dimension("tests", bundle),
                data={"testCount": 0},
                delta=int(no_record.get("delta", -20)),
            )
        )
        gaps.append(data_gap("tests", None, "未提供有效试验/修试记录，按「无试验记录」扣分"))
        return deductions, gaps

    latest, latest_record = latest_test_date(tests)
    if as_of is None:
        gaps.append(data_gap("tests", "testDate", "缺少时间基准，试验超期无法计算"))
    elif latest is None:
        gaps.append(data_gap("tests", "testDate", "试验记录均缺少 testDate，试验超期无法计算"))
    else:
        stale_days = int(stale.get("staleDays", 1095))
        days = (as_of - latest).days
        if days > stale_days:
            deductions.append(
                make_evidence(
                    "TEST-STALE",
                    "tests",
                    f"最近试验距数据截止 {days} 天，超过 {stale_days} 天有效期：{_test_label(latest_record or {})}",
                    source=source_for_dimension("tests", bundle),
                    data={
                        "latestTestDate": latest.isoformat(),
                        "daysSinceLatest": days,
                        "staleDays": stale_days,
                    },
                    delta=int(stale.get("delta", -20)),
                )
            )

    bad_results = [str(item) for item in unqualified.get("results", ["不合格", "异常"])]
    for index, record in enumerate(tests):
        result = pick(record, "result", "testResult", "conclusion")
        if result is None:
            gaps.append(
                data_gap("tests", "result", f"第 {index + 1} 条试验记录缺少 result，未计入不合格判断")
            )
            continue
        if str(result) in bad_results:
            deductions.append(
                make_evidence(
                    "TEST-UNQUALIFIED",
                    "tests",
                    f"试验结果{result}：{_test_label(record)}",
                    source=source_for_dimension("tests", bundle),
                    data={
                        "recordId": pick(record, "recordId", "testId", "id"),
                        "testType": pick(record, "testType", "type"),
                        "testDate": pick(record, "testDate", "testTime"),
                        "result": result,
                        "dataSummary": pick(record, "dataSummary", "summary"),
                    },
                    delta=int(unqualified.get("delta", -30)),
                )
            )
    return deductions, gaps


def _eval_load(
    bundle: dict[str, Any], dimension: dict[str, Any], as_of: date | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    load = bundle.get("load")
    if load is None:
        return [], []
    rules = dimension["rules"]
    overload = rules.get("overload") or {"delta": -20, "threshold": 90}
    heavy = rules.get("heavy") or {"delta": -10, "threshold": 80}
    low_open = rules.get("lowOpenCapacity") or {"delta": -10, "threshold": 5}
    deductions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    rate = compute_load_rate(load)
    if rate is None:
        gaps.append(
            data_gap(
                "load",
                "loadRate",
                "load 段缺少 loadRate 或 ratedCapacityMVA/currentLoadMVA，负载率无法计算",
            )
        )
    else:
        rate_rounded = round_half_up(rate, 2)
        if rate > float(overload.get("threshold", 90)):
            deductions.append(
                make_evidence(
                    "LOAD-OVERLOAD",
                    "load",
                    f"负载率 {format_number(rate_rounded)}% 超过 {format_number(overload.get('threshold', 90))}%",
                    source=source_for_dimension("load", bundle),
                    data={"loadRate": rate_rounded, "threshold": overload.get("threshold", 90)},
                    delta=int(overload.get("delta", -20)),
                )
            )
        elif rate > float(heavy.get("threshold", 80)):
            deductions.append(
                make_evidence(
                    "LOAD-HEAVY",
                    "load",
                    f"负载率 {format_number(rate_rounded)}% 超过 {format_number(heavy.get('threshold', 80))}%",
                    source=source_for_dimension("load", bundle),
                    data={"loadRate": rate_rounded, "threshold": heavy.get("threshold", 80)},
                    delta=int(heavy.get("delta", -10)),
                )
            )
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
        ratio_rounded = round_half_up(ratio, 2)
        threshold = float(low_open.get("threshold", 5))
        if ratio < threshold:
            deductions.append(
                make_evidence(
                    "LOAD-LOW-OPEN-CAPACITY",
                    "load",
                    f"可开放容量比 {format_number(ratio_rounded)}% 低于 {format_number(threshold)}%",
                    source=source_for_dimension("load", bundle),
                    data={"openCapacityRatio": ratio_rounded, "threshold": threshold},
                    delta=int(low_open.get("delta", -10)),
                )
            )
    return deductions, gaps


def _eval_ledger(
    bundle: dict[str, Any], dimension: dict[str, Any], as_of: date | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    device = bundle.get("device") or {}
    rules = dimension["rules"]
    missing_field = rules.get("missingField") or {"delta": -10}
    missing_ids = rules.get("missingIds") or {"delta": -20}
    fields = list(missing_field.get("fields", ["model", "manufacturer", "commissioningDate", "deviceType"]))
    deductions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for field in fields:
        value = device.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            deductions.append(
                make_evidence(
                    f"LEDGER-MISSING-{field.upper()}",
                    "ledger",
                    f"台账关键字段缺失：{field}",
                    source=source_for_dimension("ledger", bundle),
                    data={"field": field, "device": device.get("name")},
                    delta=int(missing_field.get("delta", -10)),
                )
            )
            gaps.append(data_gap("device", field, f"台账字段 {field} 缺失，已按缺失扣分"))
    id_fields = list(missing_ids.get("fields", ["assetId", "psrId"]))
    missing_id_fields = [
        field
        for field in id_fields
        if device.get(field) is None or (isinstance(device.get(field), str) and not device.get(field).strip())
    ]
    if len(missing_id_fields) == len(id_fields) and id_fields:
        deductions.append(
            make_evidence(
                "LEDGER-MISSING-IDS",
                "ledger",
                "资产ID（assetId）与资源ID（psrId）均缺失",
                source=source_for_dimension("ledger", bundle),
                data={"missingFields": missing_id_fields},
                delta=int(missing_ids.get("delta", -20)),
            )
        )
    return deductions, gaps


_EVALUATORS = {
    "defects": _eval_defects,
    "faults": _eval_faults,
    "tests": _eval_tests,
    "load": _eval_load,
    "ledger": _eval_ledger,
}


# ---------------------------------------------------------------------------
# 等级 / 置信度
# ---------------------------------------------------------------------------
def _grade_for(score: float, card: dict[str, Any]) -> dict[str, Any]:
    for item in card.get("grades", []):
        if score >= float(item.get("minScore", 0)):
            return {
                "grade": str(item.get("grade")),
                "gradeLabel": str(item.get("label", "")),
                "risk": str(item.get("risk", "")),
            }
    fallback = card.get("grades", [{}])[-1]
    return {
        "grade": str(fallback.get("grade", "E")),
        "gradeLabel": str(fallback.get("label", "严重")),
        "risk": str(fallback.get("risk", "高")),
    }


def _confidence(
    card: dict[str, Any],
    present: list[str],
    missing: list[str],
    as_of: date | None,
    end_date: date | None,
) -> float:
    cfg = card.get("confidence") or {}
    base = float(cfg.get("base", 0.9))
    penalty_per_missing = float(cfg.get("missingSectionPenalty", 0.05))
    max_missing_penalty = float(cfg.get("missingSectionMaxPenalty", 0.4))
    missing_penalty = min(len(missing) * penalty_per_missing, max_missing_penalty)
    stale_penalty = 0.0
    if as_of is not None and end_date is not None:
        if (as_of - end_date).days > int(cfg.get("staleWindowDays", 180)):
            stale_penalty = float(cfg.get("staleWindowPenalty", 0.1))
    value = base - missing_penalty - stale_penalty
    return round_half_up(
        clamp(value, float(cfg.get("min", 0.30)), float(cfg.get("max", 0.95))), 2
    )


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def assess_device_health(
    bundle: dict[str, Any],
    scorecard_profile: str = DEFAULT_PROFILE,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    """对单台设备按评分卡计算健康度分数、等级、维度得分与扣分证据。"""
    require_bundle(bundle)
    card = load_scorecard(scorecard_profile)
    as_of_date = resolve_as_of(bundle, as_of)
    time_window = bundle.get("timeWindow") if isinstance(bundle.get("timeWindow"), dict) else {}
    end_date = parse_date(time_window.get("end")) if isinstance(time_window, dict) else None

    dimensions: list[dict[str, Any]] = []
    deductions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for dimension in card.get("dimensions", []):
        dim_id = str(dimension["id"])
        evaluator = _EVALUATORS.get(dim_id)
        if evaluator is None:
            raise BundleError(f"评分卡维度 {dim_id} 没有对应的评分实现")
        dim_deductions, dim_gaps = evaluator(bundle, dimension, as_of_date)
        deductions.extend(dim_deductions)
        gaps.extend(dim_gaps)
        base = int(dimension.get("base", 100))
        max_deduction = int(dimension.get("maxDeduction", 100))
        raw_deduction = sum(abs(int(item.get("delta", 0))) for item in dim_deductions)
        deducted = min(raw_deduction, max_deduction)
        dim_score = max(0, min(100, base - deducted))
        dimensions.append(
            {
                "id": dim_id,
                "name": str(dimension.get("name", dim_id)),
                "weight": float(dimension.get("weight", 0)),
                "base": base,
                "deduction": deducted,
                "score": dim_score,
                "evidenceCount": len(dim_deductions),
            }
        )

    weighted = sum(float(item["weight"]) * float(item["score"]) for item in dimensions)
    score = round_half_up(clamp(weighted, 0.0, 100.0), 1)
    grade = _grade_for(score, card)

    sections = [str(item) for item in (card.get("completeness") or {}).get("sections", [])]
    present, missing = section_presence(bundle, sections)
    total = len(sections)
    confidence = _confidence(card, present, missing, as_of_date, end_date)

    for section in missing:
        gaps.append(
            data_gap(
                section,
                None,
                f"bundle 未提供 {section} 段，该维度按 {format_number(100)} 分起算并降低置信度",
            )
        )
    if as_of_date is None:
        gaps.append(
            data_gap(
                "timeWindow",
                "end",
                "缺少时间基准（bundle.timeWindow.end 或 --as-of），超期/时效类判断已跳过",
            )
        )

    # knowledgeQueries：按有扣分的维度给出检索建议
    knowledge_queries: list[str] = []
    for dimension, dim_result in zip(card.get("dimensions", []), dimensions):
        if dim_result["deduction"] <= 0:
            continue
        for query in dimension.get("knowledgeQueries", []) or []:
            text = str(query).strip()
            if text and text not in knowledge_queries:
                knowledge_queries.append(text)

    top_n = int((card.get("summary") or {}).get("topDeductions", 3))
    reason_items: list[str] = []
    for item in deductions:
        reason = str(item.get("reason", ""))
        if len(reason) > _REASON_MAX_LEN:
            reason = reason[:_REASON_MAX_LEN] + "…"
        reason_items.append(reason)
        if len(reason_items) >= top_n:
            break
    deduction_text = "；".join(reason_items) if reason_items else "无"
    summary = (
        f"{bundle['device']['name']} 健康度 {format_number(score, 1)} 分"
        f"（{grade['grade']}·{grade['gradeLabel']}，风险{grade['risk']}）；"
        f"数据完备度 {len(present)}/{total}，置信度 {format_number(confidence)}；"
        f"主要扣分：{deduction_text}"
    )

    return {
        "score": score,
        "grade": grade["grade"],
        "gradeLabel": grade["gradeLabel"],
        "risk": grade["risk"],
        "dimensions": dimensions,
        "deductions": deductions,
        "completeness": {
            "present": len(present),
            "total": total,
            "missing": missing,
            "ratio": round_half_up(len(present) / total, 2) if total else 0.0,
        },
        "confidence": confidence,
        "summary": summary,
        "knowledgeQueries": knowledge_queries,
        "dataGaps": dedupe_gaps(gaps),
        "asOf": as_of_date.isoformat() if as_of_date else None,
    }


def assess_station_health(
    bundles: list[dict[str, Any]],
    station_meta: dict[str, Any] | None = None,
    scorecard_profile: str = DEFAULT_PROFILE,
    top_n: int = 5,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    """对同一变电站多台设备批量评分，输出站级均值、等级分布与风险 TopN。"""
    if not isinstance(bundles, list) or not bundles:
        raise BundleError("bundles 必须是非空数组（同一变电站的设备数据包）")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        top_n = 5
    meta = station_meta if isinstance(station_meta, dict) else {}

    device_results: list[dict[str, Any]] = []
    as_of_values: list[str | None] = []
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            raise BundleError(f"第 {index + 1} 个设备数据包不是对象")
        health = assess_device_health(bundle, scorecard_profile, as_of=as_of)
        as_of_values.append(health.get("asOf"))
        device = bundle.get("device") or {}
        device_results.append(
            {
                "name": str(device.get("name", f"设备{index + 1}")),
                "psrId": device.get("psrId"),
                "assetId": device.get("assetId"),
                "score": health["score"],
                "grade": health["grade"],
                "gradeLabel": health["gradeLabel"],
                "risk": health["risk"],
                "confidence": health["confidence"],
                "summary": health["summary"],
            }
        )

    first_device = (bundles[0].get("device") or {}) if isinstance(bundles[0], dict) else {}
    station = {
        "stationId": meta.get("stationId") or first_device.get("stationId"),
        "stationName": meta.get("stationName") or first_device.get("stationName"),
        "voltageLevel": meta.get("voltageLevel") or first_device.get("voltageLevel"),
        "deviceCount": len(device_results),
    }

    scores = [float(item["score"]) for item in device_results]
    avg_score = round_half_up(sum(scores) / len(scores), 1)
    grade_distribution = {grade: 0 for grade in ("A", "B", "C", "D", "E")}
    for item in device_results:
        grade = str(item["grade"])
        if grade in grade_distribution:
            grade_distribution[grade] += 1

    ranked = sorted(device_results, key=lambda item: (float(item["score"]), str(item["name"])))
    risk_top = [
        {
            "name": item["name"],
            "score": item["score"],
            "grade": item["grade"],
            "gradeLabel": item["gradeLabel"],
            "risk": item["risk"],
        }
        for item in ranked[:top_n]
    ]

    card = load_scorecard(scorecard_profile)
    station_queries = [str(item) for item in card.get("stationKnowledgeQueries", []) if item]
    for device in device_results:
        if device["grade"] in ("D", "E"):
            query = f"对风险设备「{device['name']}」执行跨域证据链诊断与处置建议"
            if query not in station_queries:
                station_queries.append(query)

    return {
        "station": station,
        "devices": device_results,
        "aggregate": {
            "avgScore": avg_score,
            "gradeDistribution": grade_distribution,
            "riskTop": risk_top,
            "criticalCount": sum(1 for item in device_results if item["grade"] in ("D", "E")),
        },
        "knowledgeQueries": station_queries,
        "asOf": next((value for value in as_of_values if value), None),
    }
