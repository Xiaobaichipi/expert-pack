"""复杂 PMS 问数任务：多步、判断、比较、歧义（真实模型专用）。

任务仍带确定性 expect，但正确回答通常需要：
* 先调一个查询工具，再基于返回结果做比较/判断；
* 或需要对比多条记录（例如最高负载、最低可用率）；
* 或需要区分同名设备（站名必须作为上下文）。
"""

from __future__ import annotations

from expert_pack.contracts import Task
from expert_pack.extensions.pms.tasks import _task

#: 站点画像（与 data_realistic.py 对应）
STATIONS = [
    {
        "id": "STA-220-07",
        "name": "220kV 航空港变电站",
        "availability": 99.921,
        "severe": "是",
        "top_load_device": "1号主变",
        "top_load_model": "SSZ11-240000/220",
        "threshold_99_9": "否",
    },
    {
        "id": "STA-220-08",
        "name": "220kV 高新变电站",
        "availability": 99.987,
        "severe": "否",
        "top_load_device": "1号主变",
        "top_load_model": "SSZ11-120000/220",
        "threshold_99_9": "否",
    },
    {
        "id": "STA-110-09",
        "name": "110kV 大学城变电站",
        "availability": 99.70,
        "severe": "是",
        "top_load_device": "1号主变",
        "top_load_model": "SSZ11-50000/110",
        "threshold_99_9": "是",
    },
    {
        "id": "STA-110-10",
        "name": "110kV 滨河变电站",
        "availability": 99.95,
        "severe": "否",
        "top_load_device": "1号主变",
        "top_load_model": "SSZ11-50000/110",
        "threshold_99_9": "否",
    },
    {
        "id": "STA-35-11",
        "name": "35kV 城西变电站",
        "availability": 99.99,
        "severe": "否",
        "top_load_device": "1号主变",
        "top_load_model": "SZ11-20000/35",
        "threshold_99_9": "否",
    },
    {
        "id": "STA-35-12",
        "name": "35kV 物流园变电站",
        "availability": 99.60,
        "severe": "否",
        "top_load_device": "1号主变",
        "top_load_model": "SZ11-20000/35",
        "threshold_99_9": "是",
    },
]


def build_complex_tasks() -> list[Task]:
    """6 站 × 4 类复杂问题 = 24 题，另有 2 道全站比较题。"""

    tasks: list[Task] = []
    for index, station in enumerate(STATIONS, start=1):
        sid = station["id"]
        tasks.append(
            _task(
                f"capacity-max-{index:02d}",
                "capacity_max",
                f"查询 {sid} 负载率最高的主变名称，只回答主变名称。",
                station["top_load_device"],
                station_id=sid,
                intent="capacity_max",
            )
        )
        tasks.append(
            _task(
                f"defect-presence-{index:02d}",
                "defect_presence",
                f"查询 {sid} 是否存在严重及以上缺陷，只回答 是 或 否。",
                station["severe"],
                station_id=sid,
                intent="defect_presence",
            )
        )
        tasks.append(
            _task(
                f"reliability-threshold-{index:02d}",
                "reliability_threshold",
                f"查询 {sid} 的可用率，并判断是否低于 99.9%，只回答 是 或 否。",
                station["threshold_99_9"],
                station_id=sid,
                intent="reliability_threshold",
            )
        )
        tasks.append(
            _task(
                f"highest-model-{index:02d}",
                "highest_model",
                f"查询 {sid} 负载率最高的主变型号，只回答型号。",
                station["top_load_model"],
                station_id=sid,
                intent="highest_model",
            )
        )

    # 全站比较题：需要对比所有站，而不是单站查询
    tasks.append(
        _task(
            "global-lowest-availability-01",
            "global_rank",
            "查询所有变电站中可用率最低的站名，只回答站名。",
            "35kV 物流园变电站",
            station_id="STA-35-12",
            intent="global_rank",
        )
    )
    tasks.append(
        _task(
            "global-high-load-01",
            "global_rank",
            "查询所有设备中负载率最高的主变名称，只回答主变名称。",
            "1号主变",
            station_id="STA-110-09",
            intent="global_rank",
        )
    )
    return tasks
