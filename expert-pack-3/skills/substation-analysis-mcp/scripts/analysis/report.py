#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告渲染（设备画像 / 站级月报 / 故障复盘）。

设计要点
--------
- 模板文件位于 ``templates/*.md``，占位符语法为 ``{{点分路径}}``（如 ``{{health.score}}``）；
- 表格/清单类内容由 Python 预渲染为 Markdown 片段（``{{dimensionsTable}}`` 等），
  避免模板里出现循环语法，也保证渲染结果确定；
- payload 缺键时占位符渲染为「数据未提供」并写入 ``dataGaps``，报告生成不失败；
- ``citations`` 渲染为引用列表，无引用时写「知识库未检索到相关条款」；
- 渲染后保证不残留 ``{{`` 占位符。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .config import (
    ConfigError,
    ReportError,
    TEMPLATES_DIR,
    format_number,
)

__all__ = [
    "MISSING_TEXT",
    "REPORT_TYPES",
    "generate_report",
    "list_report_types",
]

MISSING_TEXT = "数据未提供"
NO_CITATION_TEXT = "知识库未检索到相关条款"

REPORT_TYPES: list[dict[str, Any]] = [
    {
        "type": "device_profile",
        "name": "设备画像报告",
        "template": "device_profile.md",
        "defaultTitle": "设备画像报告",
        "requiredPayloadKeys": ["device", "health"],
    },
    {
        "type": "station_monthly",
        "name": "站级月报",
        "template": "station_monthly.md",
        "defaultTitle": "变电站月度分析报告",
        "requiredPayloadKeys": ["station", "aggregate"],
    },
    {
        "type": "fault_review",
        "name": "故障复盘报告",
        "template": "fault_review.md",
        "defaultTitle": "故障复盘报告",
        "requiredPayloadKeys": ["fault"],
    },
]
REPORT_TYPE_MAP = {item["type"]: item for item in REPORT_TYPES}

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*\}\}")

_METRIC_META: dict[str, tuple[str, str]] = {
    "defectRate": ("缺陷率", "条/台"),
    "criticalOpen": ("危急未闭环缺陷", "条"),
    "overdueOpen": ("超期未消缺缺陷", "条"),
    "repairPlanCompletion": ("检修计划完成率", "%"),
    "testCompletion": ("修试完成率", "%"),
    "loadRate": ("负载率", "%"),
    "openCapacityRatio": ("可开放容量比", "%"),
    "availabilityRate": ("可用率", "%"),
    "trend": ("缺陷趋势", ""),
}


# ---------------------------------------------------------------------------
# 模板与取值
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _read_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取报告模板 {path}：{exc}") from None


def _dig(payload: Any, *paths: str) -> Any:
    for path in paths:
        current: Any = payload
        found = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                found = False
                break
        if found and current is not None:
            return current
    return None


def _flatten(payload: dict[str, Any], prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    result = out if out is not None else {}
    for key, value in payload.items():
        name = f"{prefix}{key}"
        result[name] = value
        if isinstance(value, dict):
            _flatten(value, f"{name}.", result)
    return result


def _cell(value: Any) -> str:
    if value is None:
        return MISSING_TEXT
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return MISSING_TEXT
        return "、".join(_cell(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    if not text:
        return MISSING_TEXT
    return text.replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: Any) -> str:
    if rows is None:
        return MISSING_TEXT
    if isinstance(rows, list) and not rows:
        return "无记录"
    if not isinstance(rows, list):
        return MISSING_TEXT
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        if not isinstance(row, (list, tuple)):
            row = [row]
        lines.append("| " + " | ".join(_cell(item) for item in row) + " |")
    return "\n".join(lines)


def _numbered_list(items: Any, empty_text: str = "无") -> str:
    if items is None:
        return MISSING_TEXT
    if not isinstance(items, (list, tuple)):
        items = [items]
    if not items:
        return empty_text
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            text = _cell(item.get("reason") or item.get("name") or item)
        else:
            text = _cell(item)
        lines.append(f"{index}. {text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 派生内容（表格 / 清单）
# ---------------------------------------------------------------------------
def _dimensions_table(payload: dict[str, Any]) -> str:
    dimensions = _dig(payload, "health.dimensions", "dimensions")
    if not isinstance(dimensions, list):
        return MISSING_TEXT
    rows = []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                item.get("name") or item.get("id"),
                format_number(item.get("weight")) if isinstance(item.get("weight"), (int, float)) else item.get("weight"),
                item.get("score"),
                item.get("deduction"),
                item.get("evidenceCount"),
            ]
        )
    return _table(["维度", "权重", "得分", "扣分", "证据数"], rows)


def _deductions_table(payload: dict[str, Any]) -> str:
    deductions = _dig(payload, "health.deductions", "deductions")
    if not isinstance(deductions, list):
        return MISSING_TEXT
    rows = []
    for item in deductions:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                item.get("ruleId"),
                item.get("dimension"),
                item.get("delta"),
                item.get("reason"),
                "、".join(str(code) for code in item.get("source", []) if code),
            ]
        )
    return _table(["规则ID", "维度", "扣分", "原因", "来源接口"], rows)


def _hypotheses_table(payload: dict[str, Any]) -> str:
    hypotheses = _dig(payload, "diagnosis.hypotheses", "hypotheses")
    if not isinstance(hypotheses, list):
        return MISSING_TEXT
    rows = []
    for index, item in enumerate(hypotheses, start=1):
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                index,
                item.get("name"),
                item.get("ruleId"),
                item.get("score"),
                item.get("confidence"),
                item.get("evidenceCount", len(item.get("evidence") or [])),
            ]
        )
    return _table(["序号", "根因假设", "规则ID", "可能性", "置信度", "证据数"], rows)


def _metrics_table(payload: dict[str, Any]) -> str:
    metrics = _dig(payload, "metrics.metrics", "metrics")
    if not isinstance(metrics, dict):
        return MISSING_TEXT
    rows = []
    for key, (label, unit) in _METRIC_META.items():
        value = metrics.get(key)
        rows.append([label, value if value is not None else MISSING_TEXT, unit])
    return _table(["指标", "数值", "单位"], rows)


def _devices_table(payload: dict[str, Any]) -> str:
    devices = _dig(payload, "devices", "station.devices")
    if not isinstance(devices, list):
        return MISSING_TEXT
    rows = [
        [
            item.get("name"),
            item.get("score"),
            item.get("grade"),
            item.get("risk"),
            item.get("confidence"),
        ]
        for item in devices
        if isinstance(item, dict)
    ]
    return _table(["设备", "健康分", "等级", "风险", "置信度"], rows)


def _risk_top_table(payload: dict[str, Any]) -> str:
    risk_top = _dig(payload, "aggregate.riskTop", "riskTop")
    if not isinstance(risk_top, list):
        return MISSING_TEXT
    rows = [
        [item.get("name"), item.get("score"), item.get("grade"), item.get("risk")]
        for item in risk_top
        if isinstance(item, dict)
    ]
    return _table(["设备", "健康分", "等级", "风险"], rows)


def _defects_table(payload: dict[str, Any]) -> str:
    defects = _dig(payload, "defects", "bundle.defects")
    if not isinstance(defects, list):
        return MISSING_TEXT
    rows = []
    for item in defects:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("desc") or item.get("description") or "")
        rows.append(
            [
                item.get("defectId") or item.get("defectNo") or item.get("id"),
                item.get("level") or item.get("defectLevel"),
                item.get("status"),
                item.get("discoverTime") or item.get("foundTime"),
                item.get("part") or item.get("defectPart"),
                desc[:80] + "…" if len(desc) > 80 else desc,
            ]
        )
    return _table(["缺陷ID", "等级", "状态", "发现时间", "部位", "描述"], rows)


def _tests_table(payload: dict[str, Any]) -> str:
    tests = _dig(payload, "tests", "bundle.tests")
    if not isinstance(tests, list):
        return MISSING_TEXT
    rows = []
    for item in tests:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                item.get("recordId") or item.get("testId") or item.get("id"),
                item.get("testType") or item.get("type"),
                item.get("testDate") or item.get("testTime"),
                item.get("result"),
                item.get("dataSummary") or item.get("summary"),
            ]
        )
    return _table(["记录ID", "试验类型", "试验日期", "结果", "数据摘要"], rows)


def _grade_distribution(payload: dict[str, Any]) -> str:
    distribution = _dig(payload, "aggregate.gradeDistribution")
    if not isinstance(distribution, dict):
        return MISSING_TEXT
    parts = []
    for grade in ("A", "B", "C", "D", "E"):
        if grade in distribution:
            parts.append(f"{grade} {distribution[grade]} 台")
    return "、".join(parts) if parts else MISSING_TEXT


def _period(payload: dict[str, Any]) -> Any:
    period = _dig(payload, "period")
    if period:
        return period
    time_window = _dig(payload, "timeWindow")
    if isinstance(time_window, dict) and (time_window.get("start") or time_window.get("end")):
        return f"{time_window.get('start') or '未标注'} 至 {time_window.get('end') or '未标注'}"
    return MISSING_TEXT


def _as_of(payload: dict[str, Any]) -> Any:
    value = _dig(payload, "asOf", "health.asOf", "diagnosis.asOf", "metrics.asOf")
    if value:
        return value
    time_window = _dig(payload, "timeWindow")
    if isinstance(time_window, dict) and time_window.get("end"):
        return time_window.get("end")
    return MISSING_TEXT


def _citations_list(citations: Any) -> str:
    if not isinstance(citations, list) or not citations:
        return NO_CITATION_TEXT
    lines = []
    for index, citation in enumerate(citations, start=1):
        if not isinstance(citation, dict):
            lines.append(f"{index}. {_cell(citation)}")
            continue
        title = _cell(citation.get("title"))
        source = _cell(citation.get("source"))
        snippet = _cell(citation.get("snippet"))
        kb_id = _cell(citation.get("kbId"))
        lines.append(f"{index}. **{title}**（来源：{source}；kbId：{kb_id}）：{snippet}")
    return "\n".join(lines)


def _suggestions_list(payload: dict[str, Any]) -> str:
    suggestions: list[str] = []
    hypotheses = _dig(payload, "diagnosis.hypotheses", "hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            if isinstance(item, dict):
                for suggestion in item.get("suggestions") or []:
                    text = str(suggestion)
                    if text not in suggestions:
                        suggestions.append(text)
    explicit = _dig(payload, "suggestions")
    if isinstance(explicit, list):
        for suggestion in explicit:
            text = str(suggestion)
            if text not in suggestions:
                suggestions.append(text)
    return _numbered_list(suggestions, empty_text="无")


def _missing_evidence_list(payload: dict[str, Any]) -> str:
    missing = _dig(payload, "diagnosis.missingEvidence", "missingEvidence")
    return _numbered_list(missing, empty_text="无")


def _collect_payload_gaps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for path in (
        "dataGaps",
        "health.dataGaps",
        "diagnosis.dataGaps",
        "metrics.dataGaps",
        "patterns.dataGaps",
    ):
        value = _dig(payload, path)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                collected.append(item)
            elif isinstance(item, str) and item.strip():
                collected.append({"section": "report", "field": None, "reason": item.strip()})
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for item in collected:
        key = (item.get("section"), item.get("field"), item.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _data_gaps_list(payload: dict[str, Any]) -> str:
    gaps = _collect_payload_gaps(payload)
    return _numbered_list(gaps, empty_text="无")


def _build_context(
    payload: dict[str, Any],
    citations: list[dict[str, Any]],
    title: str,
) -> dict[str, Any]:
    context = _flatten(payload)
    context.update(
        {
            "title": title,
            "asOf": _as_of(payload),
            "period": _period(payload),
            "dimensionsTable": _dimensions_table(payload),
            "deductionsTable": _deductions_table(payload),
            "hypothesesTable": _hypotheses_table(payload),
            "metricsTable": _metrics_table(payload),
            "devicesTable": _devices_table(payload),
            "riskTopTable": _risk_top_table(payload),
            "defectsTable": _defects_table(payload),
            "testsTable": _tests_table(payload),
            "gradeDistribution": _grade_distribution(payload),
            "missingEvidenceList": _missing_evidence_list(payload),
            "suggestionsList": _suggestions_list(payload),
            "dataGapsList": _data_gaps_list(payload),
            "citationsList": _citations_list(citations),
        }
    )
    return context


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def _lookup(context: dict[str, Any], key: str) -> tuple[Any, bool]:
    if key in context:
        return context[key], True
    current: Any = context
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None, False
    return current, True


def _render_value(value: Any) -> tuple[str, bool]:
    if value is None:
        return MISSING_TEXT, False
    if isinstance(value, bool):
        return ("是" if value else "否"), True
    if isinstance(value, (int, float)):
        return format_number(value), True
    if isinstance(value, str):
        text = value.strip()
        return (text, True) if text else (MISSING_TEXT, False)
    if isinstance(value, (list, tuple)):
        if not value:
            return MISSING_TEXT, False
        return "、".join(_cell(item) for item in value), True
    if isinstance(value, dict):
        if not value:
            return MISSING_TEXT, False
        return json.dumps(value, ensure_ascii=False, sort_keys=True), True
    return _cell(value), True


def render_template(text: str, context: dict[str, Any]) -> tuple[str, list[str]]:
    """渲染模板，返回 (markdown, 缺失占位符键列表)。"""
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value, found = _lookup(context, key)
        if not found:
            missing.append(key)
            return MISSING_TEXT
        rendered, ok = _render_value(value)
        if not ok:
            missing.append(key)
        return rendered

    markdown = PLACEHOLDER_RE.sub(_replace, text)
    if "{{" in markdown or "}}" in markdown:
        leftovers = re.findall(r"\{\{.*?\}\}", markdown, flags=re.DOTALL)
        for item in leftovers:
            missing.append(item.strip("{} ").strip())
        markdown = re.sub(r"\{\{.*?\}\}", MISSING_TEXT, markdown, flags=re.DOTALL)
        markdown = markdown.replace("{{", MISSING_TEXT).replace("}}", MISSING_TEXT)
    return markdown, list(dict.fromkeys(missing))


def _split_sections(markdown: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if current is None:
            return
        current["content"] = "\n".join(buffer).strip()
        sections.append(current)

    for line in markdown.splitlines():
        if line.startswith("## "):
            _flush()
            current = {
                "id": f"section-{len(sections) + 1}",
                "title": line[3:].strip(),
                "content": "",
            }
            buffer = []
        elif line.startswith("# ") and current is None:
            current = {
                "id": "intro",
                "title": line[2:].strip(),
                "content": "",
            }
            buffer = []
        elif current is not None:
            buffer.append(line)
    _flush()
    if not sections:
        sections.append({"id": "report", "title": "报告正文", "content": markdown.strip()})
    return sections


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def list_report_types() -> dict[str, Any]:
    """返回可用报告模板及所需 payload 键。"""
    return {
        "reportTypes": [
            {
                "type": item["type"],
                "name": item["name"],
                "requiredPayloadKeys": list(item["requiredPayloadKeys"]),
            }
            for item in REPORT_TYPES
        ]
    }


def _normalize_citations(citations: Any) -> list[dict[str, Any]]:
    if citations is None:
        return []
    if not isinstance(citations, list):
        raise ReportError("citations 必须是数组：[{title, source, snippet, kbId}]")
    normalized: list[dict[str, Any]] = []
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            raise ReportError(f"citations 第 {index + 1} 项必须是对象")
        normalized.append(
            {
                "title": citation.get("title"),
                "source": citation.get("source"),
                "snippet": citation.get("snippet"),
                "kbId": citation.get("kbId"),
            }
        )
    return normalized


def generate_report(
    report_type: str,
    payload: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """把分析结果按模板渲染为 Markdown 报告。"""
    if report_type not in REPORT_TYPE_MAP:
        raise ReportError(
            f"未知报告类型 {report_type!r}，可选类型："
            + "、".join(item["type"] for item in REPORT_TYPES)
        )
    if not isinstance(payload, dict):
        raise ReportError("payload 必须是 JSON 对象（分析结果负载）")
    meta = REPORT_TYPE_MAP[report_type]
    normalized_citations = _normalize_citations(citations)
    report_title = (title or "").strip() or str(meta["defaultTitle"])

    template = _read_template(str(meta["template"]))
    context = _build_context(payload, normalized_citations, report_title)

    from datetime import datetime as _datetime  # 仅 generatedAt 允许读系统时钟

    generated_at = _datetime.now().astimezone().isoformat(timespec="seconds")
    context["generatedAt"] = generated_at

    markdown, missing_keys = render_template(template, context)
    gaps = _collect_payload_gaps(payload)
    for key in meta["requiredPayloadKeys"]:
        if key not in payload or payload.get(key) in (None, {}, []):
            gaps.append(
                {
                    "section": "payload",
                    "field": key,
                    "reason": f"payload 缺少必需键 {key}，报告对应内容标注「{MISSING_TEXT}」",
                }
            )
    for key in missing_keys:
        gaps.append(
            {
                "section": "template",
                "field": key,
                "reason": f"模板占位 {{{{ {key} }}}} 缺值，已渲染为「{MISSING_TEXT}」",
            }
        )
    unique_gaps: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for gap in gaps:
        key = (gap.get("section"), gap.get("field"), gap.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        unique_gaps.append(gap)

    return {
        "reportType": report_type,
        "title": report_title,
        "markdown": markdown,
        "sections": _split_sections(markdown),
        "generatedAt": generated_at,
        "dataGaps": unique_gaps,
    }
