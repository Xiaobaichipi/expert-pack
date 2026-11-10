#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨域证据链诊断（规则库驱动）。

规则库见 ``config/diagnosis_rules.json``：每条规则由条件组合（关键词 / 阈值 / 运行年限 /
缺陷数 / 故障/保护动作 / 试验结果 / 家族缺陷 / 重复缺陷 / 台账缺失等）触发，命中后输出：

- ``hypotheses``：按 score 降序的根因假设，含证据链、置信度、处置建议与知识检索建议；
- ``patterns``：同部位重复缺陷簇与家族性缺陷簇；
- ``missingEvidence`` / ``dataGaps``：为确认/排除假设还缺哪些证据与数据段。

置信度由「证据条数 + 数据完备度」确定性推导，不读系统时钟。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .config import clamp, format_number, load_diagnosis_rules, parse_date, round_half_up
from .evidence import (
    compute_load_rate,
    compute_open_capacity_ratio,
    data_gap,
    days_since,
    dedupe_evidence,
    dedupe_gaps,
    latest_test_date,
    make_evidence,
    pick,
    record_text,
    require_bundle,
    resolve_as_of,
    scope_records,
    section_presence,
    source_for_section,
)
from .patterns import detect_defect_patterns_from_bundle

__all__ = [
    "diagnose_equipment",
]

_COMPLETENESS_SECTIONS = ("defects", "faults", "tests", "load")

_OPS = {
    ">": lambda left, right: left > right,
    ">=": lambda left, right: left >= right,
    "<": lambda left, right: left < right,
    "<=": lambda left, right: left <= right,
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _record_id(record: dict[str, Any], scope: str) -> Any:
    if scope == "defects":
        return pick(record, "defectId", "defectNo", "id")
    if scope == "faults":
        return pick(record, "faultId", "id")
    if scope == "tests":
        return pick(record, "recordId", "testId", "id")
    if scope == "hazards":
        return pick(record, "hazardId", "id")
    if scope == "patrolRecords":
        return pick(record, "recordId", "id")
    return pick(record, "id")


def _short(text: Any, limit: int = 60) -> str:
    value = str(text or "").strip().replace("\n", " ")
    return value[:limit] + "…" if len(value) > limit else value


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op in _OPS:
        try:
            return bool(_OPS[op](float(actual), float(expected)))
        except (TypeError, ValueError):
            return False
    if op == "==":
        if isinstance(expected, bool) or isinstance(actual, bool):
            return bool(actual) == bool(expected)
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return str(actual) == str(expected)
    if op == "!=":
        return not _compare(actual, "==", expected)
    raise ValueError(f"不支持的条件运算符：{op}")


def _empty_result() -> dict[str, Any]:
    return {"matched": False, "evidence": [], "missing": []}


def _result(matched: bool, evidence: list[dict[str, Any]] | None = None, missing: list[str] | None = None) -> dict[str, Any]:
    return {
        "matched": bool(matched),
        "evidence": evidence or [],
        "missing": list(dict.fromkeys(missing or [])),
    }


# ---------------------------------------------------------------------------
# 单条件求值
# ---------------------------------------------------------------------------
def _eval_keyword(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    scopes = [str(scope) for scope in condition.get("scopes", ["defects", "tests", "faults"])]
    keywords = [str(keyword) for keyword in condition.get("any", []) if str(keyword).strip()]
    if not keywords:
        return _result(False, missing=["规则缺少关键词配置"])
    evidence: list[dict[str, Any]] = []
    for scope in scopes:
        for record in scope_records(bundle, scope):
            text = record_text(record)
            lowered = text.lower()
            matched_keywords = [kw for kw in keywords if kw.lower() in lowered]
            if not matched_keywords:
                continue
            evidence.append(
                make_evidence(
                    str(rule.get("ruleId")),
                    str(rule.get("dimension", "")),
                    f"命中关键词「{'、'.join(matched_keywords)}」：{_short(text, 80)}",
                    source=source_for_section(scope, bundle),
                    data={
                        "scope": scope,
                        "recordId": _record_id(record, scope),
                        "keywords": matched_keywords,
                        "text": _short(text, 160),
                    },
                )
            )
    return _result(bool(evidence), evidence=evidence)


def _eval_threshold(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    field = str(condition.get("field", ""))
    op = str(condition.get("op", ">"))
    expected = condition.get("value")
    scope = "load"
    if field == "load.loadRate":
        actual = compute_load_rate(bundle.get("load"))
        label = "负载率"
        unit = "%"
    elif field == "load.openCapacityRatio":
        actual = compute_open_capacity_ratio(bundle.get("load"))
        label = "可开放容量比"
        unit = "%"
    else:
        return _result(False, missing=[f"未支持的条件字段：{field}"])
    if actual is None:
        return _result(False, missing=[f"缺少{label}数据（{field}）"])
    actual_rounded = round_half_up(actual, 2)
    matched = _compare(actual, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"{label} {format_number(actual_rounded)}{unit} {op} {format_number(expected)}{unit}",
                source=source_for_section(scope, bundle),
                data={field: actual_rounded, "operator": op, "expected": expected},
            )
        )
    return _result(matched, evidence=evidence)


def _eval_age(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any], as_of: date | None
) -> dict[str, Any]:
    device = bundle.get("device") or {}
    commissioning = device.get("commissioningDate")
    if parse_date(commissioning) is None:
        return _result(False, missing=["设备投运日期（device.commissioningDate）"])
    if as_of is None:
        return _result(False, missing=["时间基准（timeWindow.end 或 as-of），运行年限无法计算"])
    age_years = (as_of - parse_date(commissioning)).days / 365.25
    age_rounded = round_half_up(age_years, 2)
    op = str(condition.get("op", ">"))
    expected = condition.get("value")
    matched = _compare(age_years, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"设备运行年限 {format_number(age_rounded)} 年 {op} {format_number(expected)} 年",
                source=source_for_section("device", bundle),
                data={"commissioningDate": commissioning, "ageYears": age_rounded},
            )
        )
    return _result(matched, evidence=evidence)


def _eval_defect_count(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    defects = [item for item in (bundle.get("defects") or []) if isinstance(item, dict)] if isinstance(bundle.get("defects"), list) else []
    level = condition.get("level")
    status_filter = str(condition.get("status", "all"))
    selected = []
    for defect in defects:
        if level and str(pick(defect, "level", "defectLevel")) != str(level):
            continue
        if status_filter == "open" and pick(defect, "status") in ("已消除", "已关闭"):
            continue
        if status_filter == "closed" and pick(defect, "status") not in ("已消除", "已关闭"):
            continue
        selected.append(defect)
    count = len(selected)
    op = str(condition.get("op", ">="))
    expected = condition.get("value", 1)
    matched = _compare(count, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"缺陷记录 {count} 条（{op} {expected}）",
                source=source_for_section("defects", bundle),
                data={
                    "count": count,
                    "level": level,
                    "status": status_filter,
                    "defectIds": [_record_id(item, "defects") for item in selected[:10]],
                },
            )
        )
    return _result(matched, evidence=evidence)


def _eval_fault_count(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any], as_of: date | None
) -> dict[str, Any]:
    faults = [item for item in (bundle.get("faults") or []) if isinstance(item, dict)] if isinstance(bundle.get("faults"), list) else []
    within_days = condition.get("withinDays")
    if within_days is not None and as_of is not None:
        filtered = []
        for fault in faults:
            days = days_since(pick(fault, "time", "faultTime", "tripTime"), as_of)
            if days is not None and days <= int(within_days):
                filtered.append(fault)
        faults = filtered
    count = len(faults)
    op = str(condition.get("op", ">="))
    expected = condition.get("value", 1)
    matched = _compare(count, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"故障跳闸记录 {count} 次（{op} {expected}）",
                source=source_for_section("faults", bundle),
                data={"count": count, "withinDays": within_days},
            )
        )
    return _result(matched, evidence=evidence)


def _eval_test_result(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    tests = [item for item in (bundle.get("tests") or []) if isinstance(item, dict)] if isinstance(bundle.get("tests"), list) else []
    values = [str(item) for item in condition.get("values", ["不合格", "异常"])]
    evidence: list[dict[str, Any]] = []
    for record in tests:
        result = pick(record, "result", "testResult", "conclusion")
        if result is not None and str(result) in values:
            evidence.append(
                make_evidence(
                    str(rule.get("ruleId")),
                    str(rule.get("dimension", "")),
                    f"试验结果{result}：{_short(pick(record, 'dataSummary', 'summary') or pick(record, 'testType'), 60)}",
                    source=source_for_section("tests", bundle),
                    data={
                        "recordId": pick(record, "recordId", "testId", "id"),
                        "testType": pick(record, "testType", "type"),
                        "testDate": pick(record, "testDate", "testTime"),
                        "result": result,
                    },
                )
            )
    return _result(bool(evidence), evidence=evidence)


def _eval_test_count(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    tests = bundle.get("tests")
    count = len([item for item in tests if isinstance(item, dict)]) if isinstance(tests, list) else 0
    op = str(condition.get("op", "=="))
    expected = condition.get("value", 0)
    matched = _compare(count, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"试验/修试记录 {count} 条（{op} {expected}）",
                source=source_for_section("tests", bundle),
                data={"testCount": count},
            )
        )
    return _result(matched, evidence=evidence)


def _eval_test_stale(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any], as_of: date | None
) -> dict[str, Any]:
    tests = [item for item in (bundle.get("tests") or []) if isinstance(item, dict)] if isinstance(bundle.get("tests"), list) else []
    if as_of is None:
        return _result(False, missing=["时间基准（timeWindow.end 或 as-of），试验超期无法计算"])
    latest, latest_record = latest_test_date(tests)
    if latest is None:
        return _result(False, missing=["最近一次有效试验日期（tests.testDate）"])
    stale_days = int(condition.get("staleDays", 1095))
    days = (as_of - latest).days
    matched = days > stale_days
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"最近试验距数据截止 {days} 天，超过 {stale_days} 天",
                source=source_for_section("tests", bundle),
                data={
                    "latestTestDate": latest.isoformat(),
                    "daysSinceLatest": days,
                    "staleDays": stale_days,
                    "recordId": pick(latest_record or {}, "recordId", "testId", "id"),
                },
            )
        )
    return _result(matched, evidence=evidence)


def _eval_protection_action(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any], as_of: date | None
) -> dict[str, Any]:
    faults = [item for item in (bundle.get("faults") or []) if isinstance(item, dict)] if isinstance(bundle.get("faults"), list) else []
    within_days = condition.get("withinDays")
    evidence: list[dict[str, Any]] = []
    for fault in faults:
        action = pick(fault, "protectionAction", "protection")
        if not action:
            continue
        if within_days is not None:
            days = days_since(pick(fault, "time", "faultTime", "tripTime"), as_of)
            if days is None or days > int(within_days):
                continue
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"保护动作记录：{_short(action)}",
                source=source_for_section("faults", bundle),
                data={
                    "faultId": pick(fault, "faultId", "id"),
                    "time": pick(fault, "time", "faultTime", "tripTime"),
                    "protectionAction": action,
                },
            )
        )
    return _result(bool(evidence), evidence=evidence)


def _eval_family_count(
    condition: dict[str, Any], patterns: dict[str, Any], rule: dict[str, Any], bundle: dict[str, Any]
) -> dict[str, Any]:
    part = condition.get("part")
    clusters = patterns.get("familyClusters") or []
    if part:
        clusters = [cluster for cluster in clusters if cluster.get("part") == part]
    device_count = max((int(cluster.get("deviceCount", 0)) for cluster in clusters), default=0)
    op = str(condition.get("op", ">="))
    expected = condition.get("value", 3)
    matched = _compare(device_count, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        for cluster in clusters[:5]:
            evidence.append(
                make_evidence(
                    str(rule.get("ruleId")),
                    str(rule.get("dimension", "")),
                    f"家族性缺陷簇 {cluster.get('clusterId')}：{cluster.get('part')} 涉及 {cluster.get('deviceCount')} 台同型号设备",
                    source=source_for_section("defects", bundle),
                    data=cluster,
                )
            )
    return _result(matched, evidence=evidence)


def _eval_same_part(
    condition: dict[str, Any], patterns: dict[str, Any], rule: dict[str, Any], bundle: dict[str, Any]
) -> dict[str, Any]:
    part = condition.get("part")
    clusters = patterns.get("duplicateClusters") or []
    if part:
        clusters = [cluster for cluster in clusters if cluster.get("part") == part]
    max_count = max((int(cluster.get("count", 0)) for cluster in clusters), default=0)
    op = str(condition.get("op", ">="))
    expected = condition.get("value", 2)
    matched = _compare(max_count, op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        for cluster in clusters[:5]:
            evidence.append(
                make_evidence(
                    str(rule.get("ruleId")),
                    str(rule.get("dimension", "")),
                    f"重复缺陷簇 {cluster.get('clusterId')}：部位「{cluster.get('part')}」窗口内 {cluster.get('count')} 次",
                    source=source_for_section("defects", bundle),
                    data={
                        "clusterId": cluster.get("clusterId"),
                        "part": cluster.get("part"),
                        "count": cluster.get("count"),
                        "defectIds": cluster.get("defectIds"),
                        "firstTime": cluster.get("firstTime"),
                        "lastTime": cluster.get("lastTime"),
                    },
                )
            )
    return _result(matched, evidence=evidence)


def _eval_missing_fields(
    condition: dict[str, Any], bundle: dict[str, Any], rule: dict[str, Any]
) -> dict[str, Any]:
    device = bundle.get("device") or {}
    fields = [str(field) for field in condition.get("fields", ["model", "manufacturer", "commissioningDate", "deviceType"])]
    missing_fields = [
        field
        for field in fields
        if device.get(field) is None or (isinstance(device.get(field), str) and not str(device.get(field)).strip())
    ]
    op = str(condition.get("op", ">="))
    expected = condition.get("value", 2)
    matched = _compare(len(missing_fields), op, expected)
    evidence: list[dict[str, Any]] = []
    if matched:
        evidence.append(
            make_evidence(
                str(rule.get("ruleId")),
                str(rule.get("dimension", "")),
                f"台账字段缺失：{'、'.join(missing_fields)}",
                source=source_for_section("device", bundle),
                data={"missingFields": missing_fields, "device": device.get("name")},
            )
        )
    return _result(matched, evidence=evidence)


def _eval_composite(
    condition: dict[str, Any],
    bundle: dict[str, Any],
    rule: dict[str, Any],
    as_of: date | None,
    patterns: dict[str, Any],
) -> dict[str, Any]:
    subconditions = condition.get("conditions") or []
    results = [
        _eval_condition(item, bundle, rule, as_of, patterns)
        for item in subconditions
        if isinstance(item, dict)
    ]
    matched_results = [item for item in results if item["matched"]]
    evidence: list[dict[str, Any]] = []
    for item in matched_results:
        evidence.extend(item["evidence"])
    missing: list[str] = []
    if not matched_results:
        for item in results:
            missing.extend(item["missing"])
    return _result(bool(matched_results), evidence=evidence, missing=missing)


def _eval_condition(
    condition: dict[str, Any],
    bundle: dict[str, Any],
    rule: dict[str, Any],
    as_of: date | None,
    patterns: dict[str, Any],
) -> dict[str, Any]:
    cond_type = str(condition.get("type", ""))
    if cond_type == "keyword":
        return _eval_keyword(condition, bundle, rule)
    if cond_type == "threshold":
        return _eval_threshold(condition, bundle, rule)
    if cond_type == "ageYears":
        return _eval_age(condition, bundle, rule, as_of)
    if cond_type == "defectCount":
        return _eval_defect_count(condition, bundle, rule)
    if cond_type == "faultCount":
        return _eval_fault_count(condition, bundle, rule, as_of)
    if cond_type == "testResult":
        return _eval_test_result(condition, bundle, rule)
    if cond_type == "testCount":
        return _eval_test_count(condition, bundle, rule)
    if cond_type == "testStale":
        return _eval_test_stale(condition, bundle, rule, as_of)
    if cond_type == "protectionAction":
        return _eval_protection_action(condition, bundle, rule, as_of)
    if cond_type == "familyCount":
        return _eval_family_count(condition, patterns, rule, bundle)
    if cond_type == "samePartCount":
        return _eval_same_part(condition, patterns, rule, bundle)
    if cond_type == "missingFields":
        return _eval_missing_fields(condition, bundle, rule)
    if cond_type in ("anyOf", "allOf"):
        result = _eval_composite(condition, bundle, rule, as_of, patterns)
        if cond_type == "allOf":
            # allOf：所有子条件都必须命中（composite 默认 anyOf 语义）
            subconditions = [item for item in (condition.get("conditions") or []) if isinstance(item, dict)]
            subresults = [
                _eval_condition(item, bundle, rule, as_of, patterns) for item in subconditions
            ]
            matched = all(item["matched"] for item in subresults) and bool(subresults)
            evidence: list[dict[str, Any]] = []
            missing: list[str] = []
            for item in subresults:
                if item["matched"]:
                    evidence.extend(item["evidence"])
                else:
                    missing.extend(item["missing"])
            return _result(matched, evidence=evidence, missing=missing)
        return result
    return _result(False, missing=[f"未知条件类型：{cond_type}"])


# ---------------------------------------------------------------------------
# 规则求值
# ---------------------------------------------------------------------------
def _dedupe_record_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一条记录被多条条件命中时只保留一条证据（合并关键词，保留首次原因）。"""
    seen: dict[tuple[Any, Any], dict[str, Any]] = {}
    order: list[tuple[Any, Any]] = []
    for item in evidence:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        scope = data.get("scope")
        record_id = data.get("recordId")
        if scope is not None and record_id is not None:
            key: tuple[Any, Any] = (scope, record_id)
        else:
            key = (item.get("ruleId"), item.get("reason"))
        if key in seen:
            merged = seen[key]
            keywords = list(merged.get("data", {}).get("keywords") or [])
            for keyword in data.get("keywords") or []:
                if keyword not in keywords:
                    keywords.append(keyword)
            if keywords:
                merged.setdefault("data", {})["keywords"] = keywords
            continue
        seen[key] = item
        order.append(key)
    return [seen[key] for key in order]


def _evaluate_rule(
    rule: dict[str, Any],
    bundle: dict[str, Any],
    as_of: date | None,
    patterns: dict[str, Any],
) -> dict[str, Any] | None:
    conditions = [item for item in (rule.get("conditions") or []) if isinstance(item, dict)]
    if not conditions:
        return None
    results = [_eval_condition(condition, bundle, rule, as_of, patterns) for condition in conditions]
    mode = str(rule.get("conditionsMode", "all"))
    matched_count = sum(1 for item in results if item["matched"])
    if mode == "all":
        matched = matched_count == len(results)
    elif mode == "any":
        matched = matched_count > 0
    elif mode == "min":
        matched = matched_count >= int(rule.get("minConditions", 1))
    else:
        matched = matched_count == len(results)
    if not matched:
        return None

    evidence = _dedupe_record_evidence(
        dedupe_evidence([item for result in results for item in result["evidence"]])
    )
    missing: list[str] = []
    for result in results:
        if not result["matched"]:
            missing.extend(result["missing"])
    for item in rule.get("missingEvidence", []) or []:
        text = str(item).strip()
        if text and text not in missing:
            missing.append(text)
    return {"rule": rule, "evidence": evidence, "missing": missing}


def _confidence(
    evidence_count: int,
    completeness_ratio: float,
    cfg: dict[str, Any],
) -> float:
    base = float(cfg.get("base", 0.25))
    evidence_weight = float(cfg.get("evidenceWeight", 0.10))
    evidence_max = int(cfg.get("evidenceMaxCount", 4))
    completeness_weight = float(cfg.get("completenessWeight", 0.30))
    value = (
        base
        + evidence_weight * min(evidence_count, evidence_max)
        + completeness_weight * completeness_ratio
    )
    return round_half_up(
        clamp(value, float(cfg.get("min", 0.30)), float(cfg.get("max", 0.95))), 2
    )


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def diagnose_equipment(
    bundle: dict[str, Any],
    max_hypotheses: int = 5,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    """基于跨域证据给出根因假设排序、证据链、缺失证据与下一步核查建议。"""
    require_bundle(bundle)
    library = load_diagnosis_rules()
    if not isinstance(max_hypotheses, int) or isinstance(max_hypotheses, bool) or max_hypotheses < 1:
        max_hypotheses = 5
    cfg = library.get("confidence") or {}
    rules = [rule for rule in library.get("rules", []) if isinstance(rule, dict)]
    as_of_date = resolve_as_of(bundle, as_of)

    patterns = detect_defect_patterns_from_bundle(
        bundle,
        as_of=as_of_date.isoformat() if as_of_date else None,
    )

    present, missing_sections = section_presence(bundle, _COMPLETENESS_SECTIONS)
    total_sections = len(_COMPLETENESS_SECTIONS)
    completeness_ratio = len(present) / total_sections if total_sections else 0.0

    evidence_bonus = float(library.get("evidenceScoreBonus", 0.02))
    evidence_bonus_cap = float(library.get("evidenceScoreBonusCap", 0.10))
    max_score = float(library.get("maxScore", 0.99))

    hypotheses: list[dict[str, Any]] = []
    for rule in rules:
        evaluated = _evaluate_rule(rule, bundle, as_of_date, patterns)
        if evaluated is None:
            continue
        evidence = evaluated["evidence"]
        base_score = float(rule.get("score", 0.5))
        bonus = min(evidence_bonus_cap, max(0, len(evidence) - 2) * evidence_bonus)
        score = round_half_up(min(max_score, base_score + bonus), 2)
        confidence = _confidence(len(evidence), completeness_ratio, cfg)
        hypotheses.append(
            {
                "ruleId": str(rule.get("ruleId")),
                "name": str(rule.get("name")),
                "dimension": str(rule.get("dimension", "")),
                "score": score,
                "confidence": confidence,
                "evidenceCount": len(evidence),
                "evidence": evidence,
                "suggestions": [str(item) for item in rule.get("suggestions", []) if item],
                "knowledgeQueries": [
                    str(item) for item in rule.get("knowledgeQueries", []) if item
                ],
                "missingEvidence": evaluated["missing"],
            }
        )

    hypotheses.sort(key=lambda item: (-float(item["score"]), -float(item["confidence"]), item["ruleId"]))
    hypotheses = hypotheses[:max_hypotheses]

    missing_evidence: list[str] = []
    for hypothesis in hypotheses:
        for item in hypothesis.get("missingEvidence", []):
            if item not in missing_evidence:
                missing_evidence.append(item)
    for section in missing_sections:
        text = f"bundle 未提供 {section} 段，相关证据无法验证"
        if text not in missing_evidence:
            missing_evidence.append(text)

    gaps: list[dict[str, Any]] = []
    for section in missing_sections:
        gaps.append(
            data_gap(
                section,
                None,
                f"bundle 未提供 {section} 段，诊断按现有证据计算，相关假设置信度下降",
            )
        )
    if as_of_date is None:
        gaps.append(
            data_gap(
                "timeWindow",
                "end",
                "缺少时间基准（bundle.timeWindow.end 或 --as-of），时间窗类条件已跳过",
            )
        )
    gaps.extend(patterns.get("dataGaps") or [])
    if not hypotheses:
        gaps.append(
            data_gap(
                "diagnosis",
                None,
                "现有证据未命中任何诊断规则（证据不足），建议补充缺陷/故障/试验数据后再诊断",
            )
        )

    return {
        "hypotheses": hypotheses,
        "patterns": patterns,
        "missingEvidence": missing_evidence,
        "dataGaps": dedupe_gaps(gaps),
        "rulesEvaluated": len(rules),
        "asOf": as_of_date.isoformat() if as_of_date else None,
    }
