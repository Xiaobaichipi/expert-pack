"""更接近真实分布的模拟数据：不同电压等级/容量/厂家/缺陷状态/负载/可靠性。

默认数据集不受影响；仅在 ``PMS_MOCK_DATASET=realistic`` 时由 ``data.py`` 调用。
"""

from __future__ import annotations

import copy
from typing import Any

#: 6 个站：覆盖 220/110/35kV、不同容量与运行状态
STATION_SPECS: list[dict[str, Any]] = [
    {
        "stationId": "STA-220-07",
        "stationName": "220kV 航空港变电站",
        "voltageLevel": "220kV",
        "stationType": "地区站",
        "availabilityRate": 99.921,
        "outageCount": 4,
    },
    {
        "stationId": "STA-220-08",
        "stationName": "220kV 高新变电站",
        "voltageLevel": "220kV",
        "stationType": "地区站",
        "availabilityRate": 99.987,
        "outageCount": 1,
    },
    {
        "stationId": "STA-110-09",
        "stationName": "110kV 大学城变电站",
        "voltageLevel": "110kV",
        "stationType": "终端站",
        "availabilityRate": 99.70,
        "outageCount": 6,
    },
    {
        "stationId": "STA-110-10",
        "stationName": "110kV 滨河变电站",
        "voltageLevel": "110kV",
        "stationType": "终端站",
        "availabilityRate": 99.95,
        "outageCount": 2,
    },
    {
        "stationId": "STA-35-11",
        "stationName": "35kV 城西变电站",
        "voltageLevel": "35kV",
        "stationType": "终端站",
        "availabilityRate": 99.99,
        "outageCount": 0,
    },
    {
        "stationId": "STA-35-12",
        "stationName": "35kV 物流园变电站",
        "voltageLevel": "35kV",
        "stationType": "终端站",
        "availabilityRate": 99.60,
        "outageCount": 8,
    },
]

#: 主变：型号/容量/负载/厂家/投运日期均有差异
ASSET_SPECS: list[dict[str, Any]] = [
    {
        "assetId": "AST-220-1001",
        "assetName": "1号主变",
        "stationId": "STA-220-07",
        "voltageLevel": "220kV",
        "model": "SSZ11-240000/220",
        "capacityMVA": 240,
        "voltageRatio": "220/110/10.5kV",
        "manufacturer": "特变电工",
        "commissioningDate": "2014-08-12",
        "loadRate": 88.0,
    },
    {
        "assetId": "AST-220-1002",
        "assetName": "2号主变",
        "stationId": "STA-220-07",
        "voltageLevel": "220kV",
        "model": "SSZ11-180000/220",
        "capacityMVA": 180,
        "voltageRatio": "220/110/10.5kV",
        "manufacturer": "保变电气",
        "commissioningDate": "2017-03-20",
        "loadRate": 76.0,
    },
    {
        "assetId": "AST-220-1003",
        "assetName": "1号主变",
        "stationId": "STA-220-08",
        "voltageLevel": "220kV",
        "model": "SSZ11-120000/220",
        "capacityMVA": 120,
        "voltageRatio": "220/110/10.5kV",
        "manufacturer": "特变电工",
        "commissioningDate": "2019-11-05",
        "loadRate": 55.0,
    },
    {
        "assetId": "AST-110-1001",
        "assetName": "1号主变",
        "stationId": "STA-110-09",
        "voltageLevel": "110kV",
        "model": "SSZ11-50000/110",
        "capacityMVA": 50,
        "voltageRatio": "110/35/10kV",
        "manufacturer": "保变电气",
        "commissioningDate": "2012-06-18",
        "loadRate": 92.0,
    },
    {
        "assetId": "AST-110-1002",
        "assetName": "1号主变",
        "stationId": "STA-110-10",
        "voltageLevel": "110kV",
        "model": "SSZ11-50000/110",
        "capacityMVA": 50,
        "voltageRatio": "110/35/10kV",
        "manufacturer": "特变电工",
        "commissioningDate": "2020-09-02",
        "loadRate": 45.0,
    },
    {
        "assetId": "AST-35-1001",
        "assetName": "1号主变",
        "stationId": "STA-35-11",
        "voltageLevel": "35kV",
        "model": "SZ11-20000/35",
        "capacityMVA": 20,
        "voltageRatio": "35/10kV",
        "manufacturer": "西电集团",
        "commissioningDate": "2022-04-15",
        "loadRate": 30.0,
    },
    {
        "assetId": "AST-35-1002",
        "assetName": "1号主变",
        "stationId": "STA-35-12",
        "voltageLevel": "35kV",
        "model": "SZ11-20000/35",
        "capacityMVA": 20,
        "voltageRatio": "35/10kV",
        "manufacturer": "西电集团",
        "commissioningDate": "2023-10-08",
        "loadRate": 12.0,
    },
]

#: 缺陷：危急/严重/一般 + 处理中/待处理/已消除
DEFECT_SPECS: list[dict[str, Any]] = [
    {
        "defectId": "DF-2026-2001",
        "deviceId": "AST-220-1001",
        "level": "危急",
        "status": "处理中",
        "part": "套管",
        "desc": "套管末屏放电痕，介损严重超标",
    },
    {
        "defectId": "DF-2026-2002",
        "deviceId": "AST-220-1002",
        "level": "严重",
        "status": "待处理",
        "part": "本体",
        "desc": "本体油色谱乙炔含量异常增长",
    },
    {
        "defectId": "DF-2026-2003",
        "deviceId": "AST-110-1001",
        "level": "严重",
        "status": "处理中",
        "part": "冷却系统",
        "desc": "冷却器风扇故障，油温偏高",
    },
    {
        "defectId": "DF-2026-2004",
        "deviceId": "AST-110-1002",
        "level": "一般",
        "status": "已消除",
        "part": "本体",
        "desc": "轻微渗油，已处理",
        "closeTime": "2026-05-12",
    },
]

#: 检修计划：待执行/执行中/已完成/已逾期
PLAN_SPECS: list[dict[str, Any]] = [
    {
        "planId": "RP-2026-2001",
        "deviceId": "AST-220-1001",
        "planName": "1号主变A类检修",
        "planStartDate": "2026-11-20",
        "planEndDate": "2026-11-22",
        "planTime": "2026-11-20 至 2026-11-22",
        "planType": "A类检修",
        "status": "待执行",
    },
    {
        "planId": "RP-2026-2002",
        "deviceId": "AST-220-1003",
        "planName": "1号主变C类检修",
        "planStartDate": "2026-12-01",
        "planEndDate": "2026-12-03",
        "planTime": "2026-12-01 至 2026-12-03",
        "planType": "C类检修",
        "status": "待执行",
    },
    {
        "planId": "RP-2026-2003",
        "deviceId": "AST-110-1001",
        "planName": "1号主变B类检修",
        "planStartDate": "2026-09-01",
        "planEndDate": "2026-09-03",
        "planTime": "2026-09-01 至 2026-09-03",
        "planType": "B类检修",
        "status": "已逾期",
    },
]


def _device(asset_id: str, specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return specs[asset_id]


def extend(module: Any) -> dict[str, int]:
    """把 realistic 数据集追加到 mock_gateway.data 模块。"""

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

    asset_specs = {item["assetId"]: item for item in ASSET_SPECS}
    for spec in STATION_SPECS:
        station_id = spec["stationId"]
        station_psr = "PSR-{}-{}".format(
            station_id.split("-")[1], station_id.split("-")[2].zfill(4)
        )
        station = {
            "stationId": station_id,
            "psrId": station_psr,
            "stationName": spec["stationName"],
            "voltageLevel": spec["voltageLevel"],
            "orgId": "ORG-4101" if spec["voltageLevel"] == "220kV" else "ORG-4102",
            "stationType": spec["stationType"],
            "mainTransformerCount": sum(1 for a in ASSET_SPECS if a["stationId"] == station_id),
        }
        stations.append(station)
        station_by_id[station_id] = station
        psr_devices.append(
            {
                "psrId": station_psr,
                "psrName": spec["stationName"],
                "deviceType": "变电站",
                "voltageLevel": spec["voltageLevel"],
                "stationId": station_id,
                "stationName": spec["stationName"],
                "assetId": None,
                "topoNodeId": "TOPO-" + station_psr.split("-", 1)[1],
                "graphicId": "GEO-" + station_psr.split("-", 1)[1],
            }
        )
        psr_by_id[station_psr] = psr_devices[-1]

        reliability.append(
            {
                "stationId": station_id,
                "stationName": spec["stationName"],
                "statStartDate": "2026-01-01",
                "statEndDate": "2026-09-30",
                "statPeriod": "2026-01 至 2026-09",
                "availabilityRate": spec["availabilityRate"],
                "outageHours": round((100 - spec["availabilityRate"]) * 720 / 100, 2),
                "outageUserHours": round((100 - spec["availabilityRate"]) * 100, 1),
                "outageCount": spec["outageCount"],
            }
        )

        for asset in [item for item in ASSET_SPECS if item["stationId"] == station_id]:
            psr_id = "PSR-{}-{}".format(
                asset["assetId"].split("-")[1], asset["assetId"].split("-")[2]
            )
            utc = "UTC-2026-{}".format(asset["assetId"].split("-")[2])
            topo = "TOPO-{}-{}".format(asset["assetId"].split("-")[1], asset["assetId"].split("-")[2])
            graphic = "GEO-{}-{}".format(asset["assetId"].split("-")[1], asset["assetId"].split("-")[2])
            asset_record = {
                "assetId": asset["assetId"],
                "assetName": asset["assetName"],
                "assetType": "transformer",
                "deviceType": "变压器",
                "voltageLevel": asset["voltageLevel"],
                "stationId": station_id,
                "stationName": spec["stationName"],
                "model": asset["model"],
                "capacityMVA": asset["capacityMVA"],
                "voltageRatio": asset["voltageRatio"],
                "manufacturer": asset["manufacturer"],
                "manufacturerId": "MF-REAL",
                "commissioningDate": asset["commissioningDate"],
                "assetStatus": "在运",
                "psrId": psr_id,
                "utcNum": utc,
                "topoNodeId": topo,
                "graphicId": graphic,
            }
            assets.append(asset_record)
            asset_by_id[asset["assetId"]] = asset_record
            asset_by_utc[utc] = asset_record
            psr_devices.append(
                {
                    "psrId": psr_id,
                    "psrName": asset["assetName"],
                    "deviceType": "变压器",
                    "voltageLevel": asset["voltageLevel"],
                    "stationId": station_id,
                    "stationName": spec["stationName"],
                    "assetId": asset["assetId"],
                    "topoNodeId": topo,
                    "graphicId": graphic,
                }
            )
            psr_by_id[psr_id] = psr_devices[-1]

            rated = float(asset["capacityMVA"])
            load = float(asset["loadRate"])
            capacities.append(
                {
                    "deviceId": asset["assetId"],
                    "psrId": psr_id,
                    "deviceName": asset["assetName"],
                    "stationId": station_id,
                    "stationName": spec["stationName"],
                    "voltageLevel": asset["voltageLevel"],
                    "ratedCapacityMVA": asset["capacityMVA"],
                    "currentLoadMVA": round(rated * load / 100, 1),
                    "openCapacityMVA": round(rated - rated * load / 100, 1),
                    "loadRate": load,
                }
            )

    for spec in DEFECT_SPECS:
        asset = asset_specs[spec["deviceId"]]
        station = station_by_id[asset["stationId"]]
        defect = {
            "defectId": spec["defectId"],
            "defectNo": "QXB-2026-{}".format(spec["defectId"].split("-")[-1]),
            "deviceId": spec["deviceId"],
            "psrId": asset_by_id[spec["deviceId"]]["psrId"],
            "deviceName": asset["assetName"],
            "stationId": asset["stationId"],
            "stationName": station["stationName"],
            "defectDesc": spec["desc"],
            "defectLevel": spec["level"],
            "discoverTime": "2026-09-10 10:00",
            "part": spec["part"],
            "status": spec["status"],
            "handler": "李工",
            "photos": ["https://example.com/defect/{}-1.jpg".format(spec["defectId"])],
            "processRecords": [
                {"time": "2026-09-10 11:00", "action": "缺陷登记", "operator": "李工"}
            ],
            "acceptance": {
                "result": "已验收" if spec["status"] == "已消除" else "未验收",
                "time": spec.get("closeTime", ""),
            },
        }
        if spec.get("closeTime"):
            defect["closeTime"] = spec["closeTime"]
        defects.append(defect)

    for spec in PLAN_SPECS:
        asset = asset_specs[spec["deviceId"]]
        station = station_by_id[asset["stationId"]]
        plans.append(
            {
                "planId": spec["planId"],
                "planName": spec["planName"],
                "deviceId": spec["deviceId"],
                "psrId": asset_by_id[spec["deviceId"]]["psrId"],
                "deviceName": asset["assetName"],
                "stationId": asset["stationId"],
                "stationName": station["stationName"],
                "planStartDate": spec["planStartDate"],
                "planEndDate": spec["planEndDate"],
                "planTime": spec["planTime"],
                "outageArrangement": "设备停电，做好负荷转供",
                "planType": spec["planType"],
                "status": spec["status"],
            }
        )

    return {
        "stations": len(STATION_SPECS),
        "assets": len(ASSET_SPECS),
        "defects": len(DEFECT_SPECS),
        "plans": len(PLAN_SPECS),
    }
