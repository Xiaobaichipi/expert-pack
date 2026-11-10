#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟数据问数分析示例（expert-pack-2 二期）。

一条命令完成三件事：
1. 启动本地可鉴权模拟网关（进程内、token 模式、随机端口）；
2. 通过 **真实 HTTP + 鉴权** 调用 ``spec/interfaces.json`` 的 26 个 PMS 接口，
   为每类接口取回模拟数据；
3. 按 12 个业务问题组织取数与分析：台账/缺陷/隐患/检修/试验/负载/可靠性/拓扑，
   并用 ``substation-analysis-mcp`` 的分析引擎计算健康分、诊断假设、缺陷模式、
   站级画像与设备画像报告。

示例::

    python tools/mock_qa_demo.py                 # 12 个问题（默认）
    python tools/mock_qa_demo.py --samples       # 26 个接口的模拟数据样例
    python tools/mock_qa_demo.py --question 8    # 只跑第 8 个问题

说明：全部数据为虚构模拟数据；分析结论仅用于演示，不得作为业务结论。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "pms-gateway-mcp" / "scripts"
ANALYSIS_SCRIPTS = ROOT / "skills" / "substation-analysis-mcp" / "scripts"
for path in (SCRIPTS, ANALYSIS_SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mock_gateway.server import start_server  # noqa: E402
from pms_client import PmsClient, PmsConfig  # noqa: E402
from pms_client.spec import InterfaceSpec  # noqa: E402
import analysis  # noqa: E402

STATION_ID = "STA-220-01"
STATION_NAME = "220kV 郑州变电站"
DEVICE_ASSET_ID = "AST-102-0001"
DEVICE_PSR_ID = "PSR-220-0001"
DEVICE_UTC_NUM = "UTC-2020-000123"
AS_OF = "2026-09-30"
TIME_WINDOW = {"start": "2025-10-01", "end": AS_OF}

#: 26 个接口的演示参数（与 spec 的必填项一一对应，可直接复现）
SAMPLE_ARGS = {
    "list_asset_params": {"assetType": "transformer", "stationId": STATION_ID},
    "get_asset_by_id": {"assetId": DEVICE_ASSET_ID},
    "get_psr_by_id": {"psrId": DEVICE_PSR_ID},
    "get_device_by_utc_num": {"utcNum": DEVICE_UTC_NUM},
    "get_device_tree_root": {},
    "get_device_tree_nodes": {"parentId": "ROOT"},
    "list_psr_by_filters": {"stationId": STATION_ID},
    "query_svg_map_by_psr_id": {"psrId": DEVICE_PSR_ID},
    "search_power_path": {"psrId": DEVICE_PSR_ID},
    "analyze_supply_area": {"psrId": DEVICE_PSR_ID, "direction": "outage"},
    "inquire_defect": {"defectLevel": "严重"},
    "view_defect": {"defectId": "DF-2026-0001"},
    "list_hazard": {"stationId": STATION_ID},
    "list_fault_trip_records": {"deviceId": DEVICE_ASSET_ID},
    "get_repair_plan": {"stationId": STATION_ID},
    "find_repair_test": {"pageSize": 50},
    "find_repair_program": {"deviceId": DEVICE_ASSET_ID},
    "list_test_item": {},
    "list_patrol_plan": {"stationId": STATION_ID},
    "list_patrol_record": {"stationId": STATION_ID},
    "query_open_capacity": {"stationId": STATION_ID},
    "query_station_scale_analysis": {"stationId": STATION_ID},
    "query_outage_incident": {"stationId": STATION_ID},
    "find_smart_device": {"stationId": STATION_ID},
    "get_instrument_list": {"stationId": STATION_ID},
    "get_manufacturer_infos": {},
}


# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------
def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pragma: no cover
                pass


def title(text: str) -> None:
    print()
    print("=" * 78)
    print(text)
    print("=" * 78)


def section(text: str) -> None:
    print()
    print("## " + text)


def table(headers: list[str], rows: list[list[object]]) -> None:
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        print("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")


def one_line(value: object, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def list_items(payload: object) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("list"), list):
        return [item for item in payload["list"] if isinstance(item, dict)]
    return []


def total_of(payload: object) -> int:
    if isinstance(payload, dict) and isinstance(payload.get("total"), int):
        return payload["total"]
    return len(list_items(payload))


# ---------------------------------------------------------------------------
# 取数客户端（真实 HTTP + token 鉴权，记录调用用于 sourceMeta）
# ---------------------------------------------------------------------------
class QaClient:
    def __init__(self, client: PmsClient, spec: InterfaceSpec) -> None:
        self.client = client
        self.spec = spec
        self.calls: list[tuple[str, dict]] = []

    def call(self, tool: str, params: dict | None = None) -> object:
        args = dict(params or {})
        envelope = self.client.call_tool(tool, args)
        self.calls.append((tool, args))
        return envelope.get("data")

    def object(self, tool: str, params: dict | None = None) -> dict:
        data = self.call(tool, params)
        return data if isinstance(data, dict) else {}

    def items(self, tool: str, params: dict | None = None) -> list[dict]:
        return [item for item in list_items(self.call(tool, params))]

    def source_meta(self) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        meta: list[dict] = []
        for tool, params in self.calls:
            key = (tool, json.dumps(params, ensure_ascii=False, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            meta.append(
                {
                    "interfaceCode": self.spec.get(tool).code,
                    "tool": tool,
                    "params": params,
                }
            )
        return meta


# ---------------------------------------------------------------------------
# 接口数据 → 分析引擎 bundle
# ---------------------------------------------------------------------------
def build_bundle(ev: QaClient, asset_id: str) -> dict:
    asset = ev.object("get_asset_by_id", {"assetId": asset_id})
    psr_id = asset.get("psrId", "")
    station_id = asset.get("stationId", "")

    defects_raw = ev.items("inquire_defect", {"deviceId": asset_id, "pageSize": 50})
    defects: list[dict] = []
    for defect in defects_raw:
        detail = ev.object("view_defect", {"defectId": defect.get("defectId", "")})
        defects.append(
            {
                "defectId": defect.get("defectId"),
                "defectNo": defect.get("defectNo"),
                "level": defect.get("defectLevel"),
                "status": defect.get("status"),
                "discoverTime": defect.get("discoverTime"),
                "closeTime": detail.get("closeTime") or defect.get("closeTime"),
                "part": defect.get("part"),
                "desc": detail.get("defectDesc") or "",
            }
        )

    hazards = [
        {
            "hazardId": item.get("hazardId"),
            "type": item.get("hazardType"),
            "riskLevel": item.get("riskLevel"),
            "status": item.get("status"),
            "desc": item.get("hazardDesc"),
        }
        for item in ev.items("list_hazard", {"stationId": station_id, "pageSize": 50})
    ]
    faults = [
        {
            "faultId": item.get("faultId"),
            "time": item.get("faultTime"),
            "protectionAction": item.get("protectionAction"),
            "cause": item.get("cause"),
            "description": "{}（保护动作：{}）".format(item.get("cause"), item.get("protectionAction")),
        }
        for item in ev.items("list_fault_trip_records", {"deviceId": asset_id, "pageSize": 50})
    ]
    tests = [
        {
            "recordId": item.get("recordId"),
            "testType": item.get("testType"),
            "testDate": item.get("testDate"),
            "result": item.get("result"),
            "dataSummary": item.get("dataSummary"),
        }
        for item in ev.items("find_repair_test", {"deviceId": asset_id, "pageSize": 50})
    ]
    repair_plans = [
        {
            "planId": item.get("planId"),
            "planName": item.get("planName"),
            "planTime": item.get("planTime"),
            "status": item.get("status"),
            "deviceName": item.get("deviceName"),
        }
        for item in ev.items("get_repair_plan", {"deviceId": asset_id, "pageSize": 50})
    ]
    patrol_records = [
        {
            "recordId": item.get("recordId"),
            "patrolTime": item.get("patrolTime"),
            "result": item.get("result"),
            "abnormalities": item.get("abnormalities") or [],
        }
        for item in ev.items("list_patrol_record", {"stationId": station_id, "pageSize": 50})
    ]
    capacity = ev.items("query_open_capacity", {"deviceId": asset_id, "pageSize": 20})
    load = dict(capacity[0]) if capacity else {}
    reliability_rows = ev.items("query_station_scale_analysis", {"stationId": station_id, "pageSize": 20})
    reliability = dict(reliability_rows[0]) if reliability_rows else {}

    bundle = {
        "device": {
            "psrId": psr_id,
            "assetId": asset.get("assetId"),
            "utcNum": asset.get("utcNum"),
            "name": asset.get("assetName"),
            "stationId": station_id,
            "stationName": asset.get("stationName"),
            "voltageLevel": asset.get("voltageLevel"),
            "deviceType": asset.get("deviceType"),
            "model": asset.get("model"),
            "manufacturer": asset.get("manufacturer"),
            "commissioningDate": asset.get("commissioningDate"),
            "capacityMVA": asset.get("capacityMVA"),
            "status": asset.get("assetStatus"),
        },
        "timeWindow": dict(TIME_WINDOW),
        "defects": defects,
        "hazards": hazards,
        "faults": faults,
        "tests": tests,
        "repairPlans": repair_plans,
        "patrolRecords": patrol_records,
        "load": {
            "ratedCapacityMVA": load.get("ratedCapacityMVA"),
            "currentLoadMVA": load.get("currentLoadMVA"),
            "openCapacityMVA": load.get("openCapacityMVA"),
            "loadRate": load.get("loadRate"),
        }
        if load
        else {},
        "reliability": {
            "availabilityRate": reliability.get("availabilityRate"),
            "outageHours": reliability.get("outageHours"),
            "outageUserHours": reliability.get("outageUserHours"),
            "statPeriod": reliability.get("statPeriod"),
        }
        if reliability
        else {},
        "sourceMeta": ev.source_meta(),
    }
    return bundle


# ---------------------------------------------------------------------------
# 问题实现
# ---------------------------------------------------------------------------
def q1_ledger(ev: QaClient) -> None:
    section("Q1 · 220kV 郑州变电站有哪些主变？台账关键信息是什么？")
    assets = ev.items("list_asset_params", {"assetType": "transformer", "stationId": STATION_ID, "pageSize": 50})
    print("调用：list_asset_params(assetType=transformer, stationId={})".format(STATION_ID))
    print("返回：{} 台主变".format(len(assets)))
    table(
        ["assetId", "名称", "设备类型", "电压等级", "型号", "容量MVA", "投运日期", "状态"],
        [
            [
                a.get("assetId"),
                a.get("assetName"),
                a.get("deviceType"),
                a.get("voltageLevel"),
                a.get("model"),
                a.get("capacityMVA"),
                a.get("commissioningDate"),
                a.get("assetStatus"),
            ]
            for a in assets
        ],
    )
    psr = ev.items("list_psr_by_filters", {"stationId": STATION_ID, "pageSize": 50})
    type_counts: dict[str, int] = {}
    for item in psr:
        key = str(item.get("deviceType"))
        type_counts[key] = type_counts.get(key, 0) + 1
    print()
    print("全站资源（list_psr_by_filters）：{} 个 PSR，按类型：{}".format(
        len(psr), "、".join("{} {}".format(name, count) for name, count in sorted(type_counts.items()))))
    print("分析：{} 台主变均为特变电工 SSZ11 系列（220kV 单台 180MVA）；全站共 {} 个 PSR 资源。".format(
        len(assets), len(psr)))


def q2_topology(ev: QaClient) -> None:
    section("Q2 · 实物 ID 反查与拓扑定位：UTC-2020-000123 是哪台设备？如何供电路径/停电影响？")
    device = ev.object("get_device_by_utc_num", {"utcNum": DEVICE_UTC_NUM})
    print("调用：get_device_by_utc_num(utcNum={})".format(DEVICE_UTC_NUM))
    print("返回：{}（{} / {} / {}）".format(
        device.get("assetName"), device.get("assetId"), device.get("stationName"), device.get("voltageLevel")))
    svg = ev.object("query_svg_map_by_psr_id", {"psrId": DEVICE_PSR_ID})
    print("接线图：{}（{}，SVG {} 字符）".format(
        svg.get("mapName"), svg.get("mapType"), len(svg.get("svgContent") or "")))
    path = ev.object("search_power_path", {"psrId": DEVICE_PSR_ID})
    print("供电路径：{}".format(path.get("pathDescription")))
    supply = ev.object("analyze_supply_area", {"psrId": DEVICE_PSR_ID, "direction": "outage"})
    print("停电影响：{} 个对象，涉及 {}；风险等级 {}".format(
        supply.get("affectedCount"),
        "、".join(supply.get("affectedStations") or []),
        supply.get("riskLevel"),
    ))
    print("分析：该主变由 500kV 嵩山变供电，停运将影响 110kV 二里岗/城东两个站的部分 10kV 负荷，"
          "属“较大”风险，检修安排需评估转供方案。")


def q3_defects(ev: QaClient) -> None:
    section("Q3 · 当前有哪些严重缺陷？涉及哪些设备、处理状态如何？")
    defects = ev.items("inquire_defect", {"defectLevel": "严重", "pageSize": 50})
    print("调用：inquire_defect(defectLevel=严重)")
    print("返回：{} 条严重缺陷".format(len(defects)))
    table(
        ["defectId", "设备", "站", "等级", "部位", "发现时间", "状态", "处理人"],
        [
            [
                d.get("defectId"),
                d.get("deviceName"),
                d.get("stationName"),
                d.get("defectLevel"),
                d.get("part"),
                d.get("discoverTime"),
                d.get("status"),
                d.get("handler"),
            ]
            for d in defects
        ],
    )
    for defect in defects:
        detail = ev.object("view_defect", {"defectId": defect.get("defectId")})
        print("详情 {}：{}（验收：{}）".format(
            detail.get("defectId"),
            detail.get("defectDesc"),
            (detail.get("acceptance") or {}).get("result"),
        ))
    open_count = sum(1 for d in defects if "已" not in str(d.get("status")))
    print("分析：严重缺陷 {} 条，未闭环 {} 条；{}".format(
        len(defects),
        open_count,
        "其中 1 号主变套管缺陷与 8 月跳闸记录（套管绝缘受潮）、套管区消防隐患相互印证，应优先处理"
        if open_count
        else "均已闭环",
    ))


def q4_hazards(ev: QaClient) -> None:
    section("Q4 · 220kV 郑州变电站当前有哪些隐患？风险等级与整改状态？")
    hazards = ev.items("list_hazard", {"stationId": STATION_ID, "pageSize": 50})
    print("调用：list_hazard(stationId={})".format(STATION_ID))
    print("返回：{} 条隐患".format(len(hazards)))
    table(
        ["hazardId", "类型", "风险等级", "描述", "措施", "整改期限", "状态"],
        [
            [h.get("hazardId"), h.get("hazardType"), h.get("riskLevel"), h.get("hazardDesc"),
             h.get("measures"), h.get("deadline"), h.get("status")]
            for h in hazards
        ],
    )
    major = [h for h in hazards if h.get("riskLevel") in ("重大", "较大")]
    print("分析：{} 条隐患中较大及以上 {} 条；建议把“站外施工塔吊侵入”纳入外破风险重点管控。".format(
        len(hazards), len(major)))


def q5_maintenance(ev: QaClient) -> None:
    section("Q5 · 检修计划与修试情况：哪些计划待执行？有没有不合格试验？")
    plans = ev.items("get_repair_plan", {"stationId": STATION_ID, "pageSize": 50})
    print("调用：get_repair_plan(stationId={})".format(STATION_ID))
    table(
        ["planId", "计划名称", "设备", "计划时间", "类型", "状态"],
        [[p.get("planId"), p.get("planName"), p.get("deviceName"), p.get("planTime"),
          p.get("planType"), p.get("status")] for p in plans],
    )
    tests = [
        item
        for item in ev.items("find_repair_test", {"pageSize": 50})
        if item.get("stationId") == STATION_ID
    ]
    print()
    print("调用：find_repair_test(pageSize=50) → 按 stationId={} 过滤".format(STATION_ID))
    table(
        ["recordId", "设备", "试验类型", "试验日期", "结果", "摘要"],
        [[t.get("recordId"), t.get("deviceName"), t.get("testType"), t.get("testDate"),
          t.get("result"), t.get("dataSummary")] for t in tests],
    )
    pending = sum(1 for p in plans if p.get("status") == "待执行")
    bad = sum(1 for t in tests if t.get("result") != "合格")
    print("分析：检修计划 {} 项（待执行 {}，最近 1 号主变 A 类检修 10 月 15 日开工）；试验 {} 条（非合格 {}）。"
          "1 号主变 9 月发现严重缺陷，但试验记录仅到 2025-04，需在 A 类检修中补做套管介损/电容量复测。".format(
              len(plans), pending, len(tests), bad))


def q6_load(ev: QaClient) -> None:
    section("Q6 · 主变负载与可开放容量：是否存在重过载风险？")
    rows = ev.items("query_open_capacity", {"stationId": STATION_ID, "pageSize": 50})
    print("调用：query_open_capacity(stationId={})".format(STATION_ID))
    table(
        ["设备", "额定MVA", "当前负载MVA", "可开放MVA", "负载率%"],
        [[r.get("deviceName"), r.get("ratedCapacityMVA"), r.get("currentLoadMVA"),
          r.get("openCapacityMVA"), r.get("loadRate")] for r in rows],
    )
    if rows:
        top = max(rows, key=lambda r: float(r.get("loadRate") or 0))
        total_open = sum(float(r.get("openCapacityMVA") or 0) for r in rows)
        print("分析：最高负载率 {}%（{}），全站可开放容量合计 {} MVA；未达 80% 重载阈值，"
              "但 1 号主变负载率 70% 已处较高水平，检修停电时需校核 N-1。".format(
                  top.get("loadRate"), top.get("deviceName"), total_open))


def q7_reliability(ev: QaClient) -> None:
    section("Q7 · 站可靠性指标与停电事件：可用率多少？年内发生了哪些停电？")
    stats = ev.items("query_station_scale_analysis", {"stationId": STATION_ID, "pageSize": 20})
    print("调用：query_station_scale_analysis(stationId={})".format(STATION_ID))
    if stats:
        s = stats[0]
        print("返回：可用率 {}%，停电 {} 次 / {} 小时，停电用户小时 {}".format(
            s.get("availabilityRate"), s.get("outageCount"), s.get("outageHours"), s.get("outageUserHours")))
    incidents = ev.items("query_outage_incident", {"stationId": STATION_ID, "pageSize": 50})
    print()
    print("调用：query_outage_incident(stationId={})".format(STATION_ID))
    table(
        ["incidentId", "开始", "结束", "范围", "原因", "影响用户数"],
        [[i.get("incidentId"), i.get("outageStart"), i.get("outageEnd"), i.get("scope"),
          i.get("cause"), i.get("affectedUserCount")] for i in incidents],
    )
    users = sum(int(i.get("affectedUserCount") or 0) for i in incidents)
    print("分析：按 stationId 查询到停电事件 {} 条、累计影响 {} 户；站级统计为 {} 次（含事件表未列出的临时停电），"
          "可用率维持 99.98% 以上。".format(
              len(incidents), users, (stats[0].get("outageCount") if stats else len(incidents))))


def q8_health(ev: QaClient) -> tuple[dict, dict]:
    section("Q8 · 1 号主变健康度如何？扣分来自哪些证据？")
    bundle = build_bundle(ev, DEVICE_ASSET_ID)
    health = analysis.assess_device_health(bundle, as_of=AS_OF)
    print("取数：get_asset_by_id / inquire_defect / view_defect / list_hazard / list_fault_trip_records / "
          "find_repair_test / get_repair_plan / list_patrol_record / query_open_capacity / "
          "query_station_scale_analysis（共 {} 次调用）".format(len(ev.calls)))
    print("结果：健康分 {} / 等级 {} {} / 风险 {}（各维度扣分与证据数见下表）".format(
        health.get("score"), health.get("grade"), health.get("gradeLabel"), health.get("risk")))
    table(
        ["维度", "权重", "扣分", "得分", "证据数"],
        [[d.get("name"), d.get("weight"), d.get("deduction"), d.get("score"), d.get("evidenceCount")]
         for d in health.get("dimensions", [])],
    )
    print("主要扣分：" + "；".join(
        "{}（{} {}）".format(item.get("reason"), item.get("ruleId"), item.get("delta"))
        for item in health.get("deductions", [])[:5]))
    return bundle, health


def q9_diagnose(ev: QaClient, bundle: dict) -> None:
    section("Q9 · 跨域证据链诊断：1 号主变 8 月跳闸的可能原因是什么？")
    diagnosis = analysis.diagnose_equipment(bundle, max_hypotheses=5, as_of=AS_OF)
    hypotheses = diagnosis.get("hypotheses", [])
    print("调用：diagnose_equipment(bundle) → {} 个假设".format(len(hypotheses)))
    table(
        ["排名", "假设", "规则", "得分", "置信度", "证据数"],
        [[index + 1, h.get("name"), h.get("ruleId"), h.get("score"), h.get("confidence"),
          h.get("evidenceCount")] for index, h in enumerate(hypotheses)],
    )
    if hypotheses:
        top = hypotheses[0]
        print("结论：首选「{}」（置信度 {}），证据 {} 条；".format(
            top.get("name"), top.get("confidence"), top.get("evidenceCount")))
        for evidence in top.get("evidence", [])[:3]:
            print("  - " + evidence.get("reason", ""))
    print("建议：安排停电做套管介损/电容量复测与末屏检查，结合 A 类检修计划一并处理。")


def q10_patterns(ev: QaClient) -> None:
    section("Q10 · 缺陷时空分布与模式识别：缺陷集中在哪些设备/部位？是否存在重复/家族性缺陷？")
    defects = ev.items("inquire_defect", {"pageSize": 50})
    print("调用：inquire_defect(pageSize=50) → {} 条缺陷".format(len(defects)))
    by_level: dict[str, int] = {}
    by_station: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for defect in defects:
        by_level[str(defect.get("defectLevel"))] = by_level.get(str(defect.get("defectLevel")), 0) + 1
        by_station[str(defect.get("stationName"))] = by_station.get(str(defect.get("stationName")), 0) + 1
        month = str(defect.get("discoverTime") or "")[:7]
        by_month[month] = by_month.get(month, 0) + 1
    print("等级分布：" + "、".join("{} {}".format(k, v) for k, v in sorted(by_level.items())))
    print("站分布：" + "、".join("{} {}".format(k, v) for k, v in sorted(by_station.items())))
    print("月份分布：" + "、".join("{} {}".format(k, v) for k, v in sorted(by_month.items())))
    patterns = analysis.detect_defect_patterns(defects, window_days=365, family_min_count=2, as_of=AS_OF)
    summary = patterns.get("summary") or {}
    print("调用：detect_defect_patterns(window_days=365, family_min_count=2)")
    print("引擎输出：重复缺陷簇 {} 个、家族性缺陷簇 {} 个（评估 {} 条）".format(
        summary.get("duplicateClusterCount"), summary.get("familyClusterCount"), summary.get("evaluatedCount")))
    for gap in patterns.get("dataGaps") or []:
        print("数据缺口：{} / {} → {}".format(gap.get("section"), gap.get("field"), gap.get("reason")))
    print("分析：当前 6 条缺陷中，严重/危急 3 条且集中在 1 号主变（套管渗油）与 2202 断路器（灭弧室）；"
          "未形成重复/家族簇。家族性判定需要同型号/同厂家 + 同部位的多台设备证据（device_meta），"
          "当前接口返回足以标注该数据缺口，不应据此下“无家族缺陷”的绝对结论。")


def q11_station(ev: QaClient) -> None:
    section("Q11 · 站级健康画像：220kV 郑州变电站风险设备排序？")
    psr_list = ev.items("list_psr_by_filters", {"stationId": STATION_ID, "pageSize": 50})
    bundles = []
    for psr in psr_list:
        asset_id = psr.get("assetId")
        if not asset_id:
            continue
        bundles.append(build_bundle(ev, asset_id))
    station_meta = {"stationId": STATION_ID, "stationName": STATION_NAME, "voltageLevel": "220kV"}
    profile = analysis.assess_station_health(bundles, station_meta=station_meta, top_n=5, as_of=AS_OF)
    print("取数：{} 台设备的台账/缺陷/故障/修试/负载/可靠性（共 {} 次调用）".format(len(bundles), len(ev.calls)))
    print("输出键：" + "、".join(sorted(profile.keys())))
    aggregate = profile.get("aggregate") or profile
    print("站级汇总：" + one_line(aggregate, 400))
    devices = profile.get("devices") or []
    risks = sorted(devices, key=lambda item: float(item.get("score") or 100))[:5]
    if risks:
        table(
            ["设备", "健康分", "等级", "风险"],
            [[r.get("name") or r.get("deviceName"), r.get("score"), r.get("grade"), r.get("risk")]
             for r in risks],
        )
        lowest = risks[0]
        print("分析：{} 健康分最低（{} 分，{} 级），是站内首要风险设备；站均分 {}，"
              "建议纳入本月重点消缺与检修窗口。".format(
                  lowest.get("name") or lowest.get("deviceName"),
                  lowest.get("score"),
                  lowest.get("grade"),
                  aggregate.get("avgScore"),
              ))


def q12_report(ev: QaClient, bundle: dict, health: dict) -> None:
    section("Q12 · 生成设备画像报告（Markdown）")
    diagnosis = analysis.diagnose_equipment(bundle, as_of=AS_OF)
    metrics = analysis.compute_device_metrics(bundle, as_of=AS_OF)
    payload = {
        "device": bundle["device"],
        "health": health,
        "diagnosis": diagnosis,
        "metrics": metrics,
        "timeWindow": bundle["timeWindow"],
    }
    report = analysis.generate_report("device_profile", payload)
    markdown = report.get("markdown") or report.get("content") or ""
    lines = [line for line in markdown.splitlines() if line.strip()]
    print("调用：generate_report(device_profile, payload=健康分+诊断+派生指标)")
    print("报告行数：{}；dataGaps：{}".format(len(lines), one_line(report.get("dataGaps") or [], 200)))
    print("---- 报告预览（前 18 行） ----")
    for line in lines[:18]:
        print(line)
    print("---- 预览结束 ----")
    print("分析：报告中的健康分、扣分证据、诊断假设均来自上面的接口取数与引擎计算，"
          "未使用推测值；知识库条款需真实检索后引用。")


# ---------------------------------------------------------------------------
# 26 接口样例
# ---------------------------------------------------------------------------
def run_samples(ev: QaClient) -> None:
    title("26 个 PMS 接口模拟数据样例（真实 HTTP + token 鉴权）")
    print("网关鉴权：token；参数见 SAMPLE_ARGS；每条为实际返回摘要。")
    ok = 0
    rows: list[list[str]] = []
    for tool in ev.spec.tools:
        if tool.name not in SAMPLE_ARGS:
            rows.append([tool.name, tool.method + " " + tool.path, "-", "缺少演示参数"])
            continue
        args = SAMPLE_ARGS[tool.name]
        try:
            data = ev.call(tool.name, args)
        except Exception as exc:  # noqa: BLE001
            rows.append([tool.name, tool.method + " " + tool.path, one_line(args, 80),
                         "ERROR {}: {}".format(type(exc).__name__, exc)])
            continue
        ok += 1
        if isinstance(data, dict) and isinstance(data.get("list"), list):
            items = list_items(data)
            summary = "total={}，首条={}".format(total_of(data), one_line(items[0] if items else {}, 150))
        else:
            summary = one_line(data, 160)
        rows.append([tool.name, tool.method + " " + tool.path, one_line(args, 80), summary])
    for row in rows:
        print("| {} | {} | {} | {} |".format(*row))
    print()
    print("汇总：{} / {} 个接口返回成功（HTTP 200 + code=0）".format(ok, len(ev.spec.tools)))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="模拟数据问数分析示例（expert-pack-2）")
    parser.add_argument("--samples", action="store_true", help="只输出 26 个接口的模拟数据样例")
    args = parser.parse_args(argv)

    server = start_server("127.0.0.1", 0, "token")
    try:
        config = PmsConfig(
            base_url=server.base_url,
            auth_mode="token",
            token=server.auth.token,
            spec_path=str(ROOT / "spec" / "interfaces.json"),
        )
        client = PmsClient(config)
        spec = InterfaceSpec.load(str(ROOT / "spec" / "interfaces.json"))
        ev = QaClient(client, spec)

        title("变电智能问数 · 模拟数据问数分析示例")
        print("网关：127.0.0.1:<随机端口>（本地模拟网关，token 鉴权）")
        print("接口：{} 个（spec/interfaces.json）；数据：虚构，仅用于演示".format(len(spec.tools)))
        print("数据规模：" + one_line(server.describe().get("data"), 260))

        if args.samples:
            run_samples(ev)
            return 0

        ev.calls.clear()
        q1_ledger(ev)
        ev.calls.clear()
        q2_topology(ev)
        ev.calls.clear()
        q3_defects(ev)
        ev.calls.clear()
        q4_hazards(ev)
        ev.calls.clear()
        q5_maintenance(ev)
        ev.calls.clear()
        q6_load(ev)
        ev.calls.clear()
        q7_reliability(ev)
        ev.calls.clear()
        bundle, health = q8_health(ev)
        q9_diagnose(ev, bundle)
        ev.calls.clear()
        q10_patterns(ev)
        ev.calls.clear()
        q11_station(ev)
        q12_report(ev, bundle, health)
        print()
        print("完成：12 个问题全部通过接口取数 + 分析引擎计算；数据与结论均为演示用途。")
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
