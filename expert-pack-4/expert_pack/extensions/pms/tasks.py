"""P0 PMS 问数任务集（基于 expert-pack-3 的 mock 数据，可确定性判分）。"""

from __future__ import annotations

from typing import Any

from expert_pack.contracts import Task

PMS_FAMILIES = (
    "ledger_model",
    "defect_level",
    "capacity_load",
    "reliability_availability",
    "topology_source",
    "maintenance_plan",
)

#: 按工具族自适应步数（P2-2）：简单对象查询少给，易发生重试的族多给。
FAMILY_MAX_STEPS = {
    "ledger_model": 4,
    "defect_level": 4,
    "capacity_load": 6,
    "reliability_availability": 6,
    "topology_source": 5,
    "maintenance_plan": 5,
    "capacity_max": 5,
    "defect_presence": 4,
    "reliability_threshold": 4,
    "highest_model": 6,
    "global_rank": 6,
}

#: 意图 → 建议工具（候选人提示，也用于可选的白名单约束）
INTENT_ACTIONS: dict[str, list[str]] = {
    "ledger_model": ["tool:pms/get_asset_by_id"],
    "defect_level": ["tool:pms/view_defect"],
    "capacity_load": ["tool:pms/query_open_capacity"],
    "reliability_availability": ["tool:pms/query_station_scale_analysis"],
    "topology_source": ["tool:pms/search_power_path"],
    "maintenance_plan": ["tool:pms/get_repair_plan"],
    "capacity_max": ["tool:pms/query_open_capacity"],
    "defect_presence": ["tool:pms/inquire_defect"],
    "reliability_threshold": ["tool:pms/query_station_scale_analysis"],
    "highest_model": ["tool:pms/query_open_capacity", "tool:pms/get_asset_by_id"],
    "global_rank": [
        "tool:pms/query_station_scale_analysis",
        "tool:pms/query_open_capacity",
    ],
}

#: 复杂意图的执行计划提示（帮助模型生成正确候选与顺序）
INTENT_PLANS: dict[str, str] = {
    "capacity_max": (
        "1) 调用 query_open_capacity 获取该站全部主变的 loadRate；"
        "2) 比较并选出 loadRate 最大的 deviceName；3) 只回答该名称。"
    ),
    "defect_presence": (
        "1) 调用 inquire_defect 获取该站缺陷；2) 判断是否存在 defectLevel 为 严重 或 危急 的记录；"
        "3) 只回答 是 或 否。"
    ),
    "reliability_threshold": (
        "1) 调用 query_station_scale_analysis 获取 availabilityRate；"
        "2) 与 99.9 比较；3) 只回答 是 或 否。"
    ),
    "highest_model": (
        "1) 调用 query_open_capacity 获取全部主变 loadRate；2) 选出最大者并记下 deviceId；"
        "3) 调用 get_asset_by_id 获取 model；4) 只回答型号。"
    ),
    "global_rank": (
        "1) 先获取所有候选记录（query_station_scale_analysis 或 query_open_capacity）；"
        "2) 在全部记录上比较目标字段；3) 只回答最终胜出者。"
    ),
}


def _task(
    task_id: str,
    family: str,
    goal: str,
    expect: str,
    *,
    station_id: str,
    intent: str,
    asset_id: str = "",
    psr_id: str = "",
    defect_id: str = "",
    max_steps: int = 0,
    plan_hint: str = "",
) -> Task:
    context: dict[str, Any] = {
        "intent": intent,
        "expect": expect,
        "stationId": station_id,
    }
    suggested = INTENT_ACTIONS.get(intent)
    if suggested:
        context["suggestedActions"] = list(suggested)
    if asset_id:
        context["assetId"] = asset_id
    if psr_id:
        context["psrId"] = psr_id
    if defect_id:
        context["defectId"] = defect_id
    plan_hint = plan_hint or INTENT_PLANS.get(intent, "")
    if plan_hint:
        context["planHint"] = plan_hint
    return Task(
        id=task_id,
        goal=goal,
        success_criteria="只回答期望的字段值；不要额外解释。",
        max_steps=max_steps or FAMILY_MAX_STEPS.get(family, 4),
        family=family,
        context=context,
    )


def build_tasks() -> list[Task]:
    """42 道题：21 道基础题 + 21 道同义改写题（6 个意图族 × 多实例）。"""

    base = _base_tasks()
    variants: list[Task] = []
    for task in base:
        context = dict(task.context)
        variants.append(
            Task(
                id=task.id + "-v2",
                goal="麻烦你查一下，" + task.goal,
                success_criteria=task.success_criteria,
                max_steps=task.max_steps,
                family=task.family,
                context=context,
            )
        )
    return base + variants


def _base_tasks() -> list[Task]:
    """21 道基础题：6 个意图族 × 多站/多设备实例。"""

    tasks: list[Task] = []

    # 1) 设备型号：4 台主变（跨 3 个站、2 种型号）
    for index, (asset, psr, station, model) in enumerate(
        [
            ("AST-102-0001", "PSR-220-0001", "STA-220-01", "SSZ11-180000/220"),
            ("AST-102-0002", "PSR-220-0002", "STA-220-01", "SSZ11-180000/220"),
            ("AST-102-0003", "PSR-110-0001", "STA-110-02", "SSZ11-50000/110"),
            ("AST-102-0004", "PSR-110-0002", "STA-110-03", "SSZ11-50000/110"),
        ],
        start=1,
    ):
        tasks.append(
            _task(
                f"ledger-model-{index}",
                "ledger_model",
                f"查询资产 {asset}（资源 {psr}）的型号，只回答型号。",
                model,
                station_id=station,
                intent="ledger_model",
                asset_id=asset,
                psr_id=psr,
            )
        )

    # 2) 缺陷等级：4 条缺陷（含危急/严重/一般）
    for index, (defect, level, station) in enumerate(
        [
            ("DF-2026-0004", "危急", "STA-220-01"),
            ("DF-2026-0001", "严重", "STA-220-01"),
            ("DF-2026-0002", "一般", "STA-220-01"),
            ("DF-2026-0006", "严重", "STA-110-02"),
        ],
        start=1,
    ):
        tasks.append(
            _task(
                f"defect-level-{index}",
                "defect_level",
                f"查询缺陷 {defect}（站点 {station}）的缺陷等级，只回答等级。",
                level,
                station_id=station,
                intent="defect_level",
                defect_id=defect,
            )
        )

    # 3) 负载率：4 台主变
    for index, (asset, station, load) in enumerate(
        [
            ("AST-102-0001", "STA-220-01", "70.0"),
            ("AST-102-0002", "STA-220-01", "54.4"),
            ("AST-102-0003", "STA-110-02", "62.0"),
            ("AST-102-0004", "STA-110-03", "44.0"),
        ],
        start=1,
    ):
        tasks.append(
            _task(
                f"capacity-load-{index}",
                "capacity_load",
                f"查询设备 {asset}（站点 {station}）的负载率，只回答数值。",
                load,
                station_id=station,
                intent="capacity_load",
                asset_id=asset,
            )
        )

    # 4) 站可用率：3 个站
    for index, (station, asset, availability) in enumerate(
        [
            ("STA-220-01", "AST-102-0001", "99.982"),
            ("STA-110-02", "AST-102-0003", "99.965"),
            ("STA-110-03", "AST-102-0004", "99.991"),
        ],
        start=1,
    ):
        tasks.append(
            _task(
                f"reliability-availability-{index}",
                "reliability_availability",
                f"查询变电站 {station}（设备 {asset}）的可用率，只回答数值。",
                availability,
                station_id=station,
                intent="reliability_availability",
                asset_id=asset,
            )
        )

    # 5) 上级电源站：3 个资源
    for index, psr in enumerate(["PSR-220-0001", "PSR-220-0101", "PSR-110-0001"], start=1):
        tasks.append(
            _task(
                f"topology-source-{index}",
                "topology_source",
                f"查询资源 {psr} 的上级电源站名称，只回答站名。",
                "500kV 嵩山变电站",
                station_id="STA-220-01" if index == 1 else "STA-110-02",
                intent="topology_source",
                psr_id=psr,
            )
        )

    # 6) 检修计划时间：3 台设备
    for index, (asset, station, plan_time) in enumerate(
        [
            ("AST-102-0001", "STA-220-01", "2026-10-15 至 2026-10-18"),
            ("AST-103-0101", "STA-220-01", "2026-11-05 至 2026-11-06"),
            ("AST-102-0002", "STA-220-01", "2025-09-10 至 2025-09-12"),
        ],
        start=1,
    ):
        tasks.append(
            _task(
                f"maintenance-plan-{index}",
                "maintenance_plan",
                f"查询设备 {asset}（站点 {station}）的检修计划时间，只回答时间。",
                plan_time,
                station_id=station,
                intent="maintenance_plan",
                asset_id=asset,
            )
        )

    return tasks


def build_task_metadata() -> list[dict[str, Any]]:
    """给实验报告用的任务描述（不含答案时也方便审计）。"""

    return [
        {
            "id": task.id,
            "family": task.family,
            "goal": task.goal,
            "expect": task.context.get("expect"),
            "intent": task.context.get("intent"),
        }
        for task in build_tasks()
    ]


def build_extended_tasks() -> list[Task]:
    """扩展模拟数据集（6 个克隆站 × 5 台设备）的任务集，共 66 题。

    与 ``data_extended.py`` 的克隆编号一一对应：
    站 ``STA-220-11..16``；设备 ``AST-102-<1000+n*10+k>``；
    缺陷/计划也按同一编号规则。
    """

    tasks: list[Task] = []
    for number in range(1, 7):
        station = "STA-220-{:02d}".format(10 + number)
        station_name = "220kV 仿真变电站{}号".format(number)
        asset = lambda k: "AST-102-{:04d}".format(1000 + number * 10 + k)
        psr = lambda k: "PSR-220-{:04d}".format(1000 + number * 10 + k)
        defect = lambda j: "DF-2026-{:04d}".format(1000 + number * 10 + j)

        # 1) 两个主变型号
        for k, expected in ((1, "SSZ11-180000/220"), (2, "SSZ11-180000/220")):
            tasks.append(
                _task(
                    f"ledger-model-{number * 100 + k}",
                    "ledger_model",
                    f"查询资产 {asset(k)}（资源 {psr(k)}）的型号，只回答型号。",
                    expected,
                    station_id=station,
                    intent="ledger_model",
                    asset_id=asset(k),
                    psr_id=psr(k),
                )
            )

        # 2) 三个缺陷等级（克隆缺陷：1=严重, 2=一般, 4=危急）
        for position, (defect_index, expected) in enumerate(
            ((1, "严重"), (2, "一般"), (4, "危急")), start=1
        ):
            tasks.append(
                _task(
                    f"defect-level-{number * 100 + position}",
                    "defect_level",
                    f"查询缺陷 {defect(defect_index)}（站点 {station}）的缺陷等级，只回答等级。",
                    expected,
                    station_id=station,
                    intent="defect_level",
                    defect_id=defect(defect_index),
                )
            )

        # 3) 两个主变负载率
        for k, expected in ((1, "70.0"), (2, "54.4")):
            tasks.append(
                _task(
                    f"capacity-load-{number * 100 + k}",
                    "capacity_load",
                    f"查询设备 {asset(k)}（站点 {station}）的负载率，只回答数值。",
                    expected,
                    station_id=station,
                    intent="capacity_load",
                    asset_id=asset(k),
                )
            )

        # 4) 站可用率
        tasks.append(
            _task(
                f"reliability-availability-{number * 100 + 1}",
                "reliability_availability",
                f"查询变电站 {station}（设备 {asset(1)}）的可用率，只回答数值。",
                "99.982",
                station_id=station,
                intent="reliability_availability",
                asset_id=asset(1),
            )
        )

        # 5) 上级电源站
        tasks.append(
            _task(
                f"topology-source-{number * 100 + 1}",
                "topology_source",
                f"查询资源 {psr(1)} 的上级电源站名称，只回答站名。",
                "500kV 嵩山变电站",
                station_id=station,
                intent="topology_source",
                psr_id=psr(1),
            )
        )

        # 6) 两个检修计划时间
        for k, expected in (
            (1, "2026-10-15 至 2026-10-18"),
            (3, "2026-11-05 至 2026-11-06"),
        ):
            tasks.append(
                _task(
                    f"maintenance-plan-{number * 100 + k}",
                    "maintenance_plan",
                    f"查询设备 {asset(k)}（站点 {station}）的检修计划时间，只回答时间。",
                    expected,
                    station_id=station,
                    intent="maintenance_plan",
                    asset_id=asset(k),
                )
            )

    return tasks
