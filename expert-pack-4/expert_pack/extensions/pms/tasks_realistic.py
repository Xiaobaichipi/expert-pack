"""更真实分布的 PMS 任务集（6 个异构站，34 题）。"""

from __future__ import annotations

from typing import Any

from expert_pack.contracts import Task
from expert_pack.extensions.pms.tasks import _task


def build_realistic_tasks() -> list[Task]:
    """覆盖 220/110/35kV、不同容量/厂家/缺陷状态/负载/可靠性/检修状态。"""

    tasks: list[Task] = []

    def add(
        task_id: str,
        family: str,
        goal: str,
        expect: str,
        station_id: str,
        intent: str,
        **context: str,
    ) -> None:
        tasks.append(
            _task(
                task_id,
                family,
                goal,
                expect,
                station_id=station_id,
                intent=intent,
                **context,
            )
        )

    # 220kV 航空港变：2 台主变、轻重缺陷、高负载、可用率偏低
    add("ledger-model-701", "ledger_model",
        "查询资产 AST-220-1001（资源 PSR-220-1001）的型号，只回答型号。",
        "SSZ11-240000/220", "STA-220-07", "ledger_model",
        asset_id="AST-220-1001", psr_id="PSR-220-1001")
    add("ledger-model-702", "ledger_model",
        "查询资产 AST-220-1002（资源 PSR-220-1002）的型号，只回答型号。",
        "SSZ11-180000/220", "STA-220-07", "ledger_model",
        asset_id="AST-220-1002", psr_id="PSR-220-1002")
    add("defect-level-701", "defect_level",
        "查询缺陷 DF-2026-2001（站点 STA-220-07）的缺陷等级，只回答等级。",
        "危急", "STA-220-07", "defect_level", defect_id="DF-2026-2001")
    add("defect-level-702", "defect_level",
        "查询缺陷 DF-2026-2002（站点 STA-220-07）的缺陷等级，只回答等级。",
        "严重", "STA-220-07", "defect_level", defect_id="DF-2026-2002")
    add("capacity-load-701", "capacity_load",
        "查询设备 AST-220-1001（站点 STA-220-07）的负载率，只回答数值。",
        "88.0", "STA-220-07", "capacity_load", asset_id="AST-220-1001")
    add("capacity-load-702", "capacity_load",
        "查询设备 AST-220-1002（站点 STA-220-07）的负载率，只回答数值。",
        "76.0", "STA-220-07", "capacity_load", asset_id="AST-220-1002")
    add("reliability-availability-701", "reliability_availability",
        "查询变电站 STA-220-07（设备 AST-220-1001）的可用率，只回答数值。",
        "99.921", "STA-220-07", "reliability_availability", asset_id="AST-220-1001")
    add("topology-source-701", "topology_source",
        "查询资源 PSR-220-1001 的上级电源站名称，只回答站名。",
        "500kV 嵩山变电站", "STA-220-07", "topology_source", psr_id="PSR-220-1001")
    add("maintenance-plan-701", "maintenance_plan",
        "查询设备 AST-220-1001（站点 STA-220-07）的检修计划时间，只回答时间。",
        "2026-11-20 至 2026-11-22", "STA-220-07", "maintenance_plan", asset_id="AST-220-1001")

    # 220kV 高新变：单台 120MVA、低负载、无缺陷
    add("ledger-model-801", "ledger_model",
        "查询资产 AST-220-1003（资源 PSR-220-1003）的型号，只回答型号。",
        "SSZ11-120000/220", "STA-220-08", "ledger_model",
        asset_id="AST-220-1003", psr_id="PSR-220-1003")
    add("capacity-load-801", "capacity_load",
        "查询设备 AST-220-1003（站点 STA-220-08）的负载率，只回答数值。",
        "55.0", "STA-220-08", "capacity_load", asset_id="AST-220-1003")
    add("reliability-availability-801", "reliability_availability",
        "查询变电站 STA-220-08（设备 AST-220-1003）的可用率，只回答数值。",
        "99.987", "STA-220-08", "reliability_availability", asset_id="AST-220-1003")
    add("topology-source-801", "topology_source",
        "查询资源 PSR-220-1003 的上级电源站名称，只回答站名。",
        "500kV 嵩山变电站", "STA-220-08", "topology_source", psr_id="PSR-220-1003")
    add("maintenance-plan-801", "maintenance_plan",
        "查询设备 AST-220-1003（站点 STA-220-08）的检修计划时间，只回答时间。",
        "2026-12-01 至 2026-12-03", "STA-220-08", "maintenance_plan", asset_id="AST-220-1003")

    # 110kV 大学城：严重缺陷、92% 重载、可用率 99.70、逾期计划
    add("ledger-model-901", "ledger_model",
        "查询资产 AST-110-1001（资源 PSR-110-1001）的型号，只回答型号。",
        "SSZ11-50000/110", "STA-110-09", "ledger_model",
        asset_id="AST-110-1001", psr_id="PSR-110-1001")
    add("defect-level-901", "defect_level",
        "查询缺陷 DF-2026-2003（站点 STA-110-09）的缺陷等级，只回答等级。",
        "严重", "STA-110-09", "defect_level", defect_id="DF-2026-2003")
    add("capacity-load-901", "capacity_load",
        "查询设备 AST-110-1001（站点 STA-110-09）的负载率，只回答数值。",
        "92.0", "STA-110-09", "capacity_load", asset_id="AST-110-1001")
    add("reliability-availability-901", "reliability_availability",
        "查询变电站 STA-110-09（设备 AST-110-1001）的可用率，只回答数值。",
        "99.70", "STA-110-09", "reliability_availability", asset_id="AST-110-1001")
    add("topology-source-901", "topology_source",
        "查询资源 PSR-110-1001 的上级电源站名称，只回答站名。",
        "500kV 嵩山变电站", "STA-110-09", "topology_source", psr_id="PSR-110-1001")
    add("maintenance-plan-901", "maintenance_plan",
        "查询设备 AST-110-1001（站点 STA-110-09）的检修计划时间，只回答时间。",
        "2026-09-01 至 2026-09-03", "STA-110-09", "maintenance_plan", asset_id="AST-110-1001")

    # 110kV 滨河：已消除的一般缺陷、45% 负载
    add("ledger-model-1001", "ledger_model",
        "查询资产 AST-110-1002（资源 PSR-110-1002）的型号，只回答型号。",
        "SSZ11-50000/110", "STA-110-10", "ledger_model",
        asset_id="AST-110-1002", psr_id="PSR-110-1002")
    add("defect-level-1001", "defect_level",
        "查询缺陷 DF-2026-2004（站点 STA-110-10）的缺陷等级，只回答等级。",
        "一般", "STA-110-10", "defect_level", defect_id="DF-2026-2004")
    add("capacity-load-1001", "capacity_load",
        "查询设备 AST-110-1002（站点 STA-110-10）的负载率，只回答数值。",
        "45.0", "STA-110-10", "capacity_load", asset_id="AST-110-1002")
    add("reliability-availability-1001", "reliability_availability",
        "查询变电站 STA-110-10（设备 AST-110-1002）的可用率，只回答数值。",
        "99.95", "STA-110-10", "reliability_availability", asset_id="AST-110-1002")
    add("topology-source-1001", "topology_source",
        "查询资源 PSR-110-1002 的上级电源站名称，只回答站名。",
        "500kV 嵩山变电站", "STA-110-10", "topology_source", psr_id="PSR-110-1002")

    # 35kV 城西：新投运、低负载、无缺陷
    add("ledger-model-1101", "ledger_model",
        "查询资产 AST-35-1001（资源 PSR-35-1001）的型号，只回答型号。",
        "SZ11-20000/35", "STA-35-11", "ledger_model",
        asset_id="AST-35-1001", psr_id="PSR-35-1001")
    add("capacity-load-1101", "capacity_load",
        "查询设备 AST-35-1001（站点 STA-35-11）的负载率，只回答数值。",
        "30.0", "STA-35-11", "capacity_load", asset_id="AST-35-1001")
    add("reliability-availability-1101", "reliability_availability",
        "查询变电站 STA-35-11（设备 AST-35-1001）的可用率，只回答数值。",
        "99.99", "STA-35-11", "reliability_availability", asset_id="AST-35-1001")
    add("topology-source-1101", "topology_source",
        "查询资源 PSR-35-1001 的上级电源站名称，只回答站名。",
        "500kV 嵩山变电站", "STA-35-11", "topology_source", psr_id="PSR-35-1001")

    # 35kV 物流园：可用率低、无缺陷
    add("ledger-model-1201", "ledger_model",
        "查询资产 AST-35-1002（资源 PSR-35-1002）的型号，只回答型号。",
        "SZ11-20000/35", "STA-35-12", "ledger_model",
        asset_id="AST-35-1002", psr_id="PSR-35-1002")
    add("capacity-load-1201", "capacity_load",
        "查询设备 AST-35-1002（站点 STA-35-12）的负载率，只回答数值。",
        "12.0", "STA-35-12", "capacity_load", asset_id="AST-35-1002")
    add("reliability-availability-1201", "reliability_availability",
        "查询变电站 STA-35-12（设备 AST-35-1002）的可用率，只回答数值。",
        "99.60", "STA-35-12", "reliability_availability", asset_id="AST-35-1002")
    add("topology-source-1201", "topology_source",
        "查询资源 PSR-35-1002 的上级电源站名称，只回答站名。",
        "500kV 嵩山变电站", "STA-35-12", "topology_source", psr_id="PSR-35-1002")

    return tasks
