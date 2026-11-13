"""扩展模拟数据集：克隆 220kV 郑州变的站/设备/缺陷/容量/可靠性/检修记录。

设计目标是给 P3 提供"更多但确定"的模拟数据，同时**不改动默认数据集**：
只有设置 ``PMS_MOCK_DATASET=extended`` 时才由 ``data.py`` 调用 :func:`extend`。

克隆规则（全部确定性）：
* 新增 6 个 220kV 站：STA-220-11..16；
* 每站克隆原 220kV 郑州变的 5 台设备；
* asset/psr/utc/topo/graphic/defect/plan 主键全部重编号，并保持互认；
* 数值字段（型号/容量/缺陷等级/负载率/可用率/检修时间）与原站一致，便于判分。
"""

from __future__ import annotations

import copy
from typing import Any

BASE_STATION_ID = "STA-220-01"
CLONE_COUNT = 6


def _id(kind: str, number: int) -> str:
    if kind == "STA":
        return "STA-220-{:02d}".format(10 + number)
    if kind == "AST":
        return "AST-102-{:04d}".format(1000 + number)
    if kind == "PSR":
        return "PSR-220-{:04d}".format(1000 + number)
    if kind == "UTC":
        return "UTC-2026-{:04d}".format(1000 + number)
    if kind == "TOPO":
        return "TOPO-220-{:04d}".format(1000 + number)
    if kind == "GEO":
        return "GEO-220-{:04d}".format(1000 + number)
    if kind == "DF":
        return "DF-2026-{:04d}".format(1000 + number)
    if kind == "RP":
        return "RP-2026-{:04d}".format(1000 + number)
    raise ValueError(kind)


def extend(module: Any) -> dict[str, int]:
    """把扩展记录追加到 ``mock_gateway.data`` 模块（原地修改）。"""

    stations: list[dict[str, Any]] = module.STATIONS
    assets: list[dict[str, Any]] = module.ASSETS
    psr_devices: list[dict[str, Any]] = module.PSR_DEVICES
    defects: list[dict[str, Any]] = module.DEFECTS
    capacities: list[dict[str, Any]] = module.OPEN_CAPACITY
    reliability: list[dict[str, Any]] = module.STATION_RELIABILITY
    plans: list[dict[str, Any]] = module.REPAIR_PLANS
    station_by_id = module.STATION_BY_ID
    asset_by_id = module.ASSET_BY_ID
    asset_by_utc = module.ASSET_BY_UTC
    psr_by_id = module.PSR_BY_ID

    base_station = station_by_id[BASE_STATION_ID]
    base_assets = [asset for asset in assets if asset["stationId"] == BASE_STATION_ID]
    base_psrs = {psr["assetId"]: psr for psr in psr_devices if psr.get("assetId")}
    base_defects = [item for item in defects if item["stationId"] == BASE_STATION_ID]
    base_capacities = [item for item in capacities if item["stationId"] == BASE_STATION_ID]
    base_reliability = next(
        (item for item in reliability if item["stationId"] == BASE_STATION_ID), None
    )
    base_plans = [item for item in plans if item["stationId"] == BASE_STATION_ID]

    for number in range(1, CLONE_COUNT + 1):
        station_id = _id("STA", number)
        station_psr_id = _id("PSR", number)
        station_name = "220kV 仿真变电站{}号".format(number)
        station = copy.deepcopy(base_station)
        station.update(
            {
                "stationId": station_id,
                "psrId": station_psr_id,
                "stationName": station_name,
            }
        )
        stations.append(station)
        station_by_id[station_id] = station
        psr_devices.append(
            {
                "psrId": station_psr_id,
                "psrName": station_name,
                "deviceType": "变电站",
                "voltageLevel": station["voltageLevel"],
                "stationId": station_id,
                "stationName": station_name,
                "assetId": None,
                "topoNodeId": _id("TOPO", number),
                "graphicId": _id("GEO", number),
            }
        )
        psr_by_id[station_psr_id] = psr_devices[-1]

        asset_map: dict[str, str] = {}
        for index, base_asset in enumerate(base_assets, start=1):
            asset_id = _id("AST", number * 10 + index)
            psr_id = _id("PSR", number * 10 + index)
            utc = _id("UTC", number * 10 + index)
            topo = _id("TOPO", number * 10 + index)
            graphic = _id("GEO", number * 10 + index)
            asset = copy.deepcopy(base_asset)
            asset.update(
                {
                    "assetId": asset_id,
                    "psrId": psr_id,
                    "utcNum": utc,
                    "topoNodeId": topo,
                    "graphicId": graphic,
                    "stationId": station_id,
                    "stationName": station_name,
                }
            )
            assets.append(asset)
            asset_by_id[asset_id] = asset
            asset_by_utc[utc] = asset
            asset_map[base_asset["assetId"]] = asset_id

            psr = copy.deepcopy(base_psrs[base_asset["assetId"]])
            psr.update(
                {
                    "psrId": psr_id,
                    "stationId": station_id,
                    "stationName": station_name,
                    "assetId": asset_id,
                    "topoNodeId": topo,
                    "graphicId": graphic,
                }
            )
            psr_devices.append(psr)
            psr_by_id[psr_id] = psr

        for index, base_defect in enumerate(base_defects, start=1):
            device_id = asset_map.get(base_defect["deviceId"])
            if not device_id:
                continue
            defect = copy.deepcopy(base_defect)
            defect_id = _id("DF", number * 10 + index)
            defect_no = "QXB-2026-{:04d}".format(1000 + number * 10 + index)
            defect.update(
                {
                    "defectId": defect_id,
                    "defectNo": defect_no,
                    "deviceId": device_id,
                    "psrId": asset_by_id[device_id]["psrId"],
                    "stationId": station_id,
                    "stationName": station_name,
                    "photos": ["https://example.com/defect/{}-1.jpg".format(defect_id)],
                }
            )
            defects.append(defect)

        for index, base_capacity in enumerate(base_capacities, start=1):
            device_id = asset_map.get(base_capacity["deviceId"])
            if not device_id:
                continue
            capacity = copy.deepcopy(base_capacity)
            capacity.update(
                {
                    "deviceId": device_id,
                    "psrId": asset_by_id[device_id]["psrId"],
                    "stationId": station_id,
                    "stationName": station_name,
                }
            )
            capacities.append(capacity)

        if base_reliability is not None:
            item = copy.deepcopy(base_reliability)
            item.update({"stationId": station_id, "stationName": station_name})
            reliability.append(item)

        for index, base_plan in enumerate(base_plans, start=1):
            device_id = asset_map.get(base_plan["deviceId"])
            if not device_id:
                continue
            plan = copy.deepcopy(base_plan)
            plan_id = _id("RP", number * 10 + index)
            plan.update(
                {
                    "planId": plan_id,
                    "deviceId": device_id,
                    "psrId": asset_by_id[device_id]["psrId"],
                    "stationId": station_id,
                    "stationName": station_name,
                }
            )
            plans.append(plan)

    return {
        "stations": CLONE_COUNT,
        "assets": CLONE_COUNT * len(base_assets),
        "defects": CLONE_COUNT * len(base_defects),
        "capacities": CLONE_COUNT * len(base_capacities),
        "plans": CLONE_COUNT * len(base_plans),
    }
