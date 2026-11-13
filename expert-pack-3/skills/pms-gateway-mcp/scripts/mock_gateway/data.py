"""26 个 PMS 接口的确定性模拟数据集（本地模拟网关专用）。

设计原则
--------
1. **确定性**：全部为模块级常量或由常量派生，不使用随机数、不读取系统时间，
   同一请求任意次数返回完全相同的 JSON（便于回归测试与 diff 对比）。
2. **虚构**：站点、设备、厂家、人员全部为虚构演示数据，不对应任何真实业务数据。
3. **主键一致**：同一 ``assetId`` 在台账、缺陷、故障、检修、可靠性、拓扑接口中
   始终指向同一台设备；``assetId`` ↔ ``psrId`` ↔ ``utcNum`` ↔ ``topoNodeId``
   的映射由 :data:`ASSETS` 单一维护，:data:`PSR_DEVICES` 由其派生。
4. **数据锚点**：字段命名以 ``spec/interfaces.json`` 各工具 ``mock`` 样例为锚，
   在其基础上补齐列表/分页/多对象，保证 ``extract_list`` / ``extract_total`` 兼容。

对外入口
--------
- :func:`handle`            按工具名返回该接口的 ``data`` 部分（服务端用）
- :data:`HANDLERS`          工具名 → 处理函数
- :data:`PAGED_TOOLS`       列表/分页类工具（返回 ``{"list","total","pageNo","pageSize"}``）
- :data:`OBJECT_TOOLS`      单对象类工具（返回对象；未知主键返回 ``{}``）
- :func:`summarize`         数据集规模摘要（供 doctor / 文档 / 测试）

过滤与分页约定
--------------
- 分页参数 ``pageNo``（从 1 开始）/ ``pageSize``；非法值退回默认值（pageSize 上限 500）。
- ``deviceId`` 参数同时接受 ``assetId`` 与 ``psrId``（同一台设备两种主键）。
- 时间范围参数（``startTime``/``endTime``/``startDate``/``endDate``）按
  ``yyyy-MM-dd`` 做闭区间比较；只比较日期部分，带时分秒的字段也能正确过滤。
- 未知主键（如不存在的 ``assetId``/``defectId``/``psrId``）返回空对象 ``{}``，
  **不报错**；列表接口过滤后为空返回 ``list=[]`` 且 ``total=0``。
- 未声明/未识别的过滤条件一律忽略（宽松，与 ``pms_client.mock`` 行为一致）。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "HANDLERS",
    "PAGED_TOOLS",
    "OBJECT_TOOLS",
    "TOOL_NAMES",
    "STATIONS",
    "ASSETS",
    "PSR_DEVICES",
    "handle",
    "paginate",
    "summarize",
]

# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------
DEFAULT_PAGE_SIZE = 20
#: pageSize 上限（防止一次拉爆；与中台常见约定一致）
MAX_PAGE_SIZE = 500
#: 仅用于分页、不参与过滤的参数
PAGE_KEYS = frozenset({"pageNo", "pageSize", "pageNum", "size", "current", "limit"})


def _text(params: Mapping[str, Any], key: str) -> str:
    """取字符串参数（去空白；非字符串按 str 处理；缺失返回空串）。"""
    value = params.get(key)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value).strip()


def _positive_int(value: Any, fallback: int) -> int:
    """宽松转正整数，非法值退回 fallback。"""
    if value is None or isinstance(value, bool):
        return fallback
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _page_size(params: Mapping[str, Any], default: int = DEFAULT_PAGE_SIZE) -> int:
    return min(_positive_int(params.get("pageSize"), default), MAX_PAGE_SIZE)


def paginate(items: Iterable[Mapping[str, Any]], params: Mapping[str, Any], default_size: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    """按 pageNo/pageSize 切页，返回 ``{"list","total","pageNo","pageSize"}``。"""
    materialized = [copy.deepcopy(dict(item)) for item in items]
    page_no = _positive_int(params.get("pageNo"), 1)
    page_size = _page_size(params, default_size)
    start = (page_no - 1) * page_size
    return {
        "list": materialized[start : start + page_size],
        "total": len(materialized),
        "pageNo": page_no,
        "pageSize": page_size,
    }


def _eq(actual: Any, expected: str) -> bool:
    """宽松等值比较（大小写不敏感；列表按任一项命中）。"""
    if not expected:
        return True
    if actual is None:
        return False
    if isinstance(actual, (list, tuple)):
        return any(_eq(item, expected) for item in actual)
    return str(actual).strip().lower() == expected.strip().lower()


def _contains(actual: Any, expected: str) -> bool:
    """子串匹配（大小写不敏感）。"""
    if not expected:
        return True
    if actual is None:
        return False
    return expected.strip().lower() in str(actual).strip().lower()


def _date_part(value: Any) -> str:
    """取日期部分（``yyyy-MM-dd``）；非法/缺失返回空串。"""
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _in_date_range(value: Any, start: str, end: str) -> bool:
    """日期闭区间比较；只比较 ``yyyy-MM-dd`` 前缀。"""
    day = _date_part(value)
    if not day:
        return not (start or end)
    if start and day < start[:10]:
        return False
    if end and day > end[:10]:
        return False
    return True


def _ranges_intersect(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    """两个日期区间是否有交集（用于计划/统计期间过滤）。"""
    if not start_b and not end_b:
        return True
    left = start_a or "0000-00-00"
    right = end_a or "9999-99-99"
    if end_b and left > end_b[:10]:
        return False
    if start_b and right < start_b[:10]:
        return False
    return True


def _device_hit(item: Mapping[str, Any], wanted: str) -> bool:
    """``deviceId`` 同时匹配 assetId / psrId（同一台设备的两种主键）。"""
    if not wanted:
        return True
    for key in ("deviceId", "assetId", "psrId"):
        value = item.get(key)
        if value and str(value) == wanted:
            return True
    return False


# ---------------------------------------------------------------------------
# 站点 / 设备台账（单一事实源：ASSETS 派生 PSR 与设备树）
# ---------------------------------------------------------------------------
STATIONS: list[dict[str, Any]] = [
    {
        "stationId": "STA-500-00",
        "psrId": "PSR-500-0001",
        "stationName": "500kV 嵩山变电站",
        "voltageLevel": "500kV",
        "orgId": "ORG-4101",
        "stationType": "枢纽站",
        "mainTransformerCount": 2,
    },
    {
        "stationId": "STA-220-01",
        "psrId": "PSR-220-0000",
        "stationName": "220kV 郑州变电站",
        "voltageLevel": "220kV",
        "orgId": "ORG-4101",
        "stationType": "地区站",
        "mainTransformerCount": 2,
    },
    {
        "stationId": "STA-110-02",
        "psrId": "PSR-110-0000",
        "stationName": "110kV 二里岗变电站",
        "voltageLevel": "110kV",
        "orgId": "ORG-4102",
        "stationType": "终端站",
        "mainTransformerCount": 1,
    },
    {
        "stationId": "STA-110-03",
        "psrId": "PSR-110-0010",
        "stationName": "110kV 城东变电站",
        "voltageLevel": "110kV",
        "orgId": "ORG-4102",
        "stationType": "终端站",
        "mainTransformerCount": 1,
    },
]

#: 设备台账（9 台虚构设备）；psrId / utcNum / topoNodeId / graphicId 在此单一维护
ASSETS: list[dict[str, Any]] = [
    {
        "assetId": "AST-102-0001",
        "assetName": "1号主变",
        "assetType": "transformer",
        "deviceType": "变压器",
        "voltageLevel": "220kV",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "model": "SSZ11-180000/220",
        "capacityMVA": 180,
        "voltageRatio": "220/110/10.5kV",
        "manufacturer": "特变电工",
        "manufacturerId": "MF-001",
        "commissioningDate": "2016-05-18",
        "assetStatus": "在运",
        "psrId": "PSR-220-0001",
        "utcNum": "UTC-2020-000123",
        "topoNodeId": "TOPO-220-0001",
        "graphicId": "GEO-220-0001",
    },
    {
        "assetId": "AST-102-0002",
        "assetName": "2号主变",
        "assetType": "transformer",
        "deviceType": "变压器",
        "voltageLevel": "220kV",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "model": "SSZ11-180000/220",
        "capacityMVA": 180,
        "voltageRatio": "220/110/10.5kV",
        "manufacturer": "特变电工",
        "manufacturerId": "MF-001",
        "commissioningDate": "2017-03-22",
        "assetStatus": "在运",
        "psrId": "PSR-220-0002",
        "utcNum": "UTC-2020-000124",
        "topoNodeId": "TOPO-220-0002",
        "graphicId": "GEO-220-0002",
    },
    {
        "assetId": "AST-102-0003",
        "assetName": "1号主变",
        "assetType": "transformer",
        "deviceType": "变压器",
        "voltageLevel": "110kV",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "model": "SSZ11-50000/110",
        "capacityMVA": 50,
        "voltageRatio": "110/35/10kV",
        "manufacturer": "特变电工",
        "manufacturerId": "MF-001",
        "commissioningDate": "2018-07-09",
        "assetStatus": "在运",
        "psrId": "PSR-110-0001",
        "utcNum": "UTC-2021-000201",
        "topoNodeId": "TOPO-110-0001",
        "graphicId": "GEO-110-0001",
    },
    {
        "assetId": "AST-102-0004",
        "assetName": "1号主变",
        "assetType": "transformer",
        "deviceType": "变压器",
        "voltageLevel": "110kV",
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "model": "SSZ11-50000/110",
        "capacityMVA": 50,
        "voltageRatio": "110/35/10kV",
        "manufacturer": "特变电工",
        "manufacturerId": "MF-001",
        "commissioningDate": "2019-11-30",
        "assetStatus": "在运",
        "psrId": "PSR-110-0002",
        "utcNum": "UTC-2021-000202",
        "topoNodeId": "TOPO-110-0002",
        "graphicId": "GEO-110-0002",
    },
    {
        "assetId": "AST-103-0101",
        "assetName": "2201断路器",
        "assetType": "breaker",
        "deviceType": "断路器",
        "voltageLevel": "220kV",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "model": "LW10B-252",
        "capacityMVA": None,
        "voltageRatio": None,
        "manufacturer": "平高电气",
        "manufacturerId": "MF-002",
        "commissioningDate": "2016-06-02",
        "assetStatus": "在运",
        "psrId": "PSR-220-0101",
        "utcNum": "UTC-2020-000125",
        "topoNodeId": "TOPO-220-0101",
        "graphicId": "GEO-220-0101",
    },
    {
        "assetId": "AST-103-0102",
        "assetName": "2202断路器",
        "assetType": "breaker",
        "deviceType": "断路器",
        "voltageLevel": "220kV",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "model": "LW10B-252",
        "capacityMVA": None,
        "voltageRatio": None,
        "manufacturer": "平高电气",
        "manufacturerId": "MF-002",
        "commissioningDate": "2016-06-02",
        "assetStatus": "在运",
        "psrId": "PSR-220-0102",
        "utcNum": "UTC-2020-000126",
        "topoNodeId": "TOPO-220-0102",
        "graphicId": "GEO-220-0102",
    },
    {
        "assetId": "AST-103-0103",
        "assetName": "1101断路器",
        "assetType": "breaker",
        "deviceType": "断路器",
        "voltageLevel": "110kV",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "model": "LW36-126",
        "capacityMVA": None,
        "voltageRatio": None,
        "manufacturer": "平高电气",
        "manufacturerId": "MF-002",
        "commissioningDate": "2018-08-15",
        "assetStatus": "在运",
        "psrId": "PSR-110-0101",
        "utcNum": "UTC-2021-000203",
        "topoNodeId": "TOPO-110-0101",
        "graphicId": "GEO-110-0101",
    },
    {
        "assetId": "AST-103-0104",
        "assetName": "1102断路器",
        "assetType": "breaker",
        "deviceType": "断路器",
        "voltageLevel": "110kV",
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "model": "LW36-126",
        "capacityMVA": None,
        "voltageRatio": None,
        "manufacturer": "平高电气",
        "manufacturerId": "MF-002",
        "commissioningDate": "2019-12-06",
        "assetStatus": "在运",
        "psrId": "PSR-110-0102",
        "utcNum": "UTC-2021-000204",
        "topoNodeId": "TOPO-110-0102",
        "graphicId": "GEO-110-0102",
    },
    {
        "assetId": "AST-104-0201",
        "assetName": "2201隔离开关",
        "assetType": "disconnector",
        "deviceType": "隔离开关",
        "voltageLevel": "220kV",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "model": "GW4-252D",
        "capacityMVA": None,
        "voltageRatio": None,
        "manufacturer": "平高电气",
        "manufacturerId": "MF-002",
        "commissioningDate": "2016-06-10",
        "assetStatus": "在运",
        "psrId": "PSR-220-0201",
        "utcNum": "UTC-2020-000127",
        "topoNodeId": "TOPO-220-0201",
        "graphicId": "GEO-220-0201",
    },
]

STATION_BY_ID: dict[str, dict[str, Any]] = {station["stationId"]: station for station in STATIONS}
ASSET_BY_ID: dict[str, dict[str, Any]] = {asset["assetId"]: asset for asset in ASSETS}
ASSET_BY_UTC: dict[str, dict[str, Any]] = {asset["utcNum"]: asset for asset in ASSETS}

#: 资源侧设备台账：站级 PSR（拓扑/供电路径用）+ 由 ASSETS 派生的设备 PSR
PSR_DEVICES: list[dict[str, Any]] = []
for _station in STATIONS:
    PSR_DEVICES.append(
        {
            "psrId": _station["psrId"],
            "psrName": _station["stationName"],
            "deviceType": "变电站",
            "voltageLevel": _station["voltageLevel"],
            "stationId": _station["stationId"],
            "stationName": _station["stationName"],
            "assetId": None,
            "topoNodeId": "TOPO-" + _station["psrId"].split("-", 1)[1],
            "graphicId": "GEO-" + _station["psrId"].split("-", 1)[1],
        }
    )
for _asset in ASSETS:
    PSR_DEVICES.append(
        {
            "psrId": _asset["psrId"],
            "psrName": _asset["assetName"],
            "deviceType": _asset["deviceType"],
            "voltageLevel": _asset["voltageLevel"],
            "stationId": _asset["stationId"],
            "stationName": _asset["stationName"],
            "assetId": _asset["assetId"],
            "topoNodeId": _asset["topoNodeId"],
            "graphicId": _asset["graphicId"],
        }
    )
PSR_BY_ID: dict[str, dict[str, Any]] = {psr["psrId"]: psr for psr in PSR_DEVICES}

# ---------------------------------------------------------------------------
# 设备树（站点 → 电压等级 → 设备 → 部件；由台账派生，主键与台账一致）
# ---------------------------------------------------------------------------
DEVICE_COMPONENTS: dict[str, list[str]] = {
    "变压器": ["本体", "套管", "冷却系统", "有载分接开关"],
    "断路器": ["机构箱", "灭弧室", "支柱绝缘子"],
    "隔离开关": ["触头", "操作机构", "支柱绝缘子"],
}
#: nodeId → 子节点列表；由下面的构建代码填充
TREE_INDEX: dict[str, list[dict[str, Any]]] = {}
TREE_NODES: dict[str, dict[str, Any]] = {}

ROOT_NODE: dict[str, Any] = {
    "nodeId": "ROOT",
    "nodeName": "河南电网设备树",
    "nodeType": "ORG_ROOT",
    "orgId": "ORG-4101",
    "hasChildren": True,
    "parentId": None,
}


def _register_node(node: dict[str, Any], parent_id: str) -> None:
    TREE_NODES[node["nodeId"]] = node
    TREE_INDEX.setdefault(parent_id, []).append(node)


for _station in STATIONS:
    _vl_ids: list[str] = []
    _station_assets = [asset for asset in ASSETS if asset["stationId"] == _station["stationId"]]
    _levels: list[str] = []
    for _asset in _station_assets:
        if _asset["voltageLevel"] not in _levels:
            _levels.append(_asset["voltageLevel"])
    _levels.sort()
    _station_node = {
        "nodeId": _station["stationId"],
        "nodeName": _station["stationName"],
        "nodeType": "STATION",
        "voltageLevel": _station["voltageLevel"],
        "hasChildren": bool(_levels),
        "childrenCount": len(_levels),
        "parentId": "ROOT",
    }
    _register_node(_station_node, "ROOT")
    for _level in _levels:
        _vl_id = _station["stationId"] + "#" + _level
        _vl_ids.append(_vl_id)
        _vl_assets = [asset for asset in _station_assets if asset["voltageLevel"] == _level]
        _register_node(
            {
                "nodeId": _vl_id,
                "nodeName": _station["stationName"] + "-" + _level,
                "nodeType": "VOLTAGE_LEVEL",
                "voltageLevel": _level,
                "hasChildren": bool(_vl_assets),
                "childrenCount": len(_vl_assets),
                "parentId": _station["stationId"],
            },
            _station["stationId"],
        )
        for _asset in _vl_assets:
            _components = DEVICE_COMPONENTS.get(_asset["deviceType"], ["本体"])
            _register_node(
                {
                    "nodeId": "TREE-" + _asset["assetId"],
                    "nodeName": _asset["assetName"],
                    "nodeType": "DEVICE",
                    "deviceType": _asset["deviceType"],
                    "voltageLevel": _asset["voltageLevel"],
                    "assetId": _asset["assetId"],
                    "psrId": _asset["psrId"],
                    "hasChildren": True,
                    "childrenCount": len(_components),
                    "parentId": _vl_id,
                },
                _vl_id,
            )
            for _index, _component in enumerate(_components, start=1):
                _register_node(
                    {
                        "nodeId": "COMP-{}-{}".format(_asset["assetId"], _index),
                        "nodeName": _component,
                        "nodeType": "COMPONENT",
                        "assetId": _asset["assetId"],
                        "hasChildren": False,
                        "childrenCount": 0,
                        "parentId": "TREE-" + _asset["assetId"],
                    },
                    "TREE-" + _asset["assetId"],
                )
    _station_node["voltageLevelNodeIds"] = _vl_ids

ROOT_NODE["childrenCount"] = len(STATIONS)
ROOT_NODE["stationCount"] = len(STATIONS)

# ---------------------------------------------------------------------------
# 运维健康：缺陷 / 隐患 / 故障
# ---------------------------------------------------------------------------
DEFECTS: list[dict[str, Any]] = [
    {
        "defectId": "DF-2026-0001",
        "defectNo": "QXB-2026-0001",
        "deviceId": "AST-102-0001",
        "psrId": "PSR-220-0001",
        "deviceName": "1号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "defectDesc": "本体套管油位偏低，存在渗油痕迹",
        "defectLevel": "严重",
        "discoverTime": "2026-09-12 10:22",
        "part": "本体/套管",
        "status": "处理中",
        "handler": "张工",
        "photos": ["https://example.com/defect/DF-2026-0001-1.jpg"],
        "processRecords": [
            {"time": "2026-09-12 11:05", "action": "缺陷登记", "operator": "张工"},
            {"time": "2026-09-13 09:30", "action": "安排处理", "operator": "王班长"},
        ],
        "acceptance": {"result": "未验收", "time": ""},
    },
    {
        "defectId": "DF-2026-0002",
        "defectNo": "QXB-2026-0002",
        "deviceId": "AST-103-0101",
        "psrId": "PSR-220-0101",
        "deviceName": "2201断路器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "defectDesc": "机构箱内受潮，加热器回路异常",
        "defectLevel": "一般",
        "discoverTime": "2026-09-20 15:40",
        "part": "机构箱",
        "status": "待处理",
        "handler": "李工",
        "photos": ["https://example.com/defect/DF-2026-0002-1.jpg"],
        "processRecords": [{"time": "2026-09-20 16:10", "action": "缺陷登记", "operator": "李工"}],
        "acceptance": {"result": "未验收", "time": ""},
    },
    {
        "defectId": "DF-2026-0003",
        "defectNo": "QXB-2026-0003",
        "deviceId": "AST-102-0002",
        "psrId": "PSR-220-0002",
        "deviceName": "2号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "defectDesc": "冷却器风扇异响，需更换轴承",
        "defectLevel": "一般",
        "discoverTime": "2026-08-18 09:05",
        "part": "冷却系统",
        "status": "已消除",
        "handler": "王工",
        "photos": ["https://example.com/defect/DF-2026-0003-1.jpg"],
        "processRecords": [
            {"time": "2026-08-18 10:00", "action": "缺陷登记", "operator": "王工"},
            {"time": "2026-08-20 17:20", "action": "处理完成（更换风扇轴承）", "operator": "王工"},
        ],
        "acceptance": {"result": "验收合格", "time": "2026-08-21 09:10"},
    },
    {
        "defectId": "DF-2026-0004",
        "defectNo": "QXB-2026-0004",
        "deviceId": "AST-103-0102",
        "psrId": "PSR-220-0102",
        "deviceName": "2202断路器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "defectDesc": "六氟化硫气体压力低，需补气检漏",
        "defectLevel": "危急",
        "discoverTime": "2026-09-28 21:10",
        "part": "灭弧室",
        "status": "处理中",
        "handler": "赵工",
        "photos": ["https://example.com/defect/DF-2026-0004-1.jpg"],
        "processRecords": [
            {"time": "2026-09-28 21:40", "action": "缺陷登记", "operator": "赵工"},
            {"time": "2026-09-29 08:00", "action": "补气并安排检漏", "operator": "王班长"},
        ],
        "acceptance": {"result": "未验收", "time": ""},
    },
    {
        "defectId": "DF-2026-0005",
        "defectNo": "QXB-2026-0005",
        "deviceId": "AST-104-0201",
        "psrId": "PSR-220-0201",
        "deviceName": "2201隔离开关",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "defectDesc": "操动机构卡涩，分合闸不顺畅",
        "defectLevel": "一般",
        "discoverTime": "2026-07-02 14:30",
        "part": "操作机构",
        "status": "已消除",
        "handler": "李工",
        "photos": ["https://example.com/defect/DF-2026-0005-1.jpg"],
        "processRecords": [
            {"time": "2026-07-02 15:00", "action": "缺陷登记", "operator": "李工"},
            {"time": "2026-07-05 11:30", "action": "处理完成（除锈润滑）", "operator": "李工"},
        ],
        "acceptance": {"result": "验收合格", "time": "2026-07-06 10:00"},
    },
    {
        "defectId": "DF-2026-0006",
        "defectNo": "QXB-2026-0006",
        "deviceId": "AST-102-0003",
        "psrId": "PSR-110-0001",
        "deviceName": "1号主变",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "defectDesc": "本体油色谱乙炔含量微增，需跟踪分析",
        "defectLevel": "严重",
        "discoverTime": "2026-09-30 08:15",
        "part": "本体",
        "status": "待处理",
        "handler": "张工",
        "photos": ["https://example.com/defect/DF-2026-0006-1.jpg"],
        "processRecords": [{"time": "2026-09-30 09:00", "action": "缺陷登记", "operator": "张工"}],
        "acceptance": {"result": "未验收", "time": ""},
    },
]

HAZARDS: list[dict[str, Any]] = [
    {
        "hazardId": "HZ-2026-0001",
        "hazardType": "外部",
        "riskLevel": "较大",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "hazardDesc": "站外施工塔吊作业半径侵入站区，存在外破风险",
        "measures": "加装防护围栏并纳入巡视",
        "discoverDate": "2026-08-06",
        "deadline": "2026-12-31",
        "status": "整改中",
    },
    {
        "hazardId": "HZ-2026-0002",
        "hazardType": "内部",
        "riskLevel": "一般",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "hazardDesc": "站内排水沟淤积，雨季存在积水风险",
        "measures": "清理排水沟",
        "discoverDate": "2026-09-02",
        "deadline": "2026-10-31",
        "status": "未整改",
    },
    {
        "hazardId": "HZ-2026-0003",
        "hazardType": "外部",
        "riskLevel": "重大",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "hazardDesc": "进站道路上方树木超高，台风天可能倒伏",
        "measures": "协调园林部门修剪，并纳入特巡",
        "discoverDate": "2026-07-11",
        "deadline": "2026-09-30",
        "status": "已闭环",
    },
    {
        "hazardId": "HZ-2026-0004",
        "hazardType": "内部",
        "riskLevel": "一般",
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "hazardDesc": "电缆沟防火封堵局部老化",
        "measures": "重新封堵并加装防火隔板",
        "discoverDate": "2026-09-15",
        "deadline": "2026-11-15",
        "status": "整改中",
    },
]

FAULT_TRIPS: list[dict[str, Any]] = [
    {
        "faultId": "FT-2026-0001",
        "deviceId": "AST-102-0001",
        "psrId": "PSR-220-0001",
        "deviceName": "1号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "faultTime": "2026-08-03 02:17",
        "protectionAction": "差动保护动作",
        "cause": "套管绝缘受潮",
        "faultLevel": "一般",
        "restoreTime": "2026-08-03 18:40",
    },
    {
        "faultId": "FT-2026-0002",
        "deviceId": "AST-103-0101",
        "psrId": "PSR-220-0101",
        "deviceName": "2201断路器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "faultTime": "2026-06-11 16:05",
        "protectionAction": "本体三相不一致保护动作",
        "cause": "辅助接点接触不良",
        "faultLevel": "一般",
        "restoreTime": "2026-06-11 20:15",
    },
    {
        "faultId": "FT-2026-0003",
        "deviceId": "AST-102-0003",
        "psrId": "PSR-110-0001",
        "deviceName": "1号主变",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "faultTime": "2026-05-20 11:48",
        "protectionAction": "过流保护动作",
        "cause": "低压侧出口短路",
        "faultLevel": "一般",
        "restoreTime": "2026-05-20 15:30",
    },
]

# ---------------------------------------------------------------------------
# 检修试验：计划 / 方案 / 修试 / 巡视 / 试验项目
# ---------------------------------------------------------------------------
REPAIR_PLANS: list[dict[str, Any]] = [
    {
        "planId": "RP-2026-0001",
        "planName": "1号主变A类检修",
        "deviceId": "AST-102-0001",
        "psrId": "PSR-220-0001",
        "deviceName": "1号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "planStartDate": "2026-10-15",
        "planEndDate": "2026-10-18",
        "planTime": "2026-10-15 至 2026-10-18",
        "outageArrangement": "主变停电，110kV 母线单母线运行",
        "planType": "A类检修",
        "status": "待执行",
    },
    {
        "planId": "RP-2026-0002",
        "planName": "2201断路器B类检修",
        "deviceId": "AST-103-0101",
        "psrId": "PSR-220-0101",
        "deviceName": "2201断路器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "planStartDate": "2026-11-05",
        "planEndDate": "2026-11-06",
        "planTime": "2026-11-05 至 2026-11-06",
        "outageArrangement": "2201 断路器及两侧隔离开关停电",
        "planType": "B类检修",
        "status": "待执行",
    },
    {
        "planId": "RP-2025-0003",
        "planName": "2号主变C类检修",
        "deviceId": "AST-102-0002",
        "psrId": "PSR-220-0002",
        "deviceName": "2号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "planStartDate": "2025-09-10",
        "planEndDate": "2025-09-12",
        "planTime": "2025-09-10 至 2025-09-12",
        "outageArrangement": "2号主变停电，负荷转移至1号主变",
        "planType": "C类检修",
        "status": "已完成",
    },
]

REPAIR_TESTS: list[dict[str, Any]] = [
    {
        "recordId": "RT-2025-0001",
        "deviceId": "AST-102-0001",
        "psrId": "PSR-220-0001",
        "deviceName": "1号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "testType": "预防性试验",
        "testDate": "2025-04-11",
        "result": "合格",
        "tester": "赵工",
        "dataSummary": "绕组直流电阻不平衡率 0.8%，绝缘电阻 12000MΩ",
    },
    {
        "recordId": "RT-2026-0002",
        "deviceId": "AST-103-0101",
        "psrId": "PSR-220-0101",
        "deviceName": "2201断路器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "testType": "断路器机械特性试验",
        "testDate": "2026-03-20",
        "result": "合格",
        "tester": "赵工",
        "dataSummary": "分闸时间 32ms，合闸时间 78ms，同期差 2ms",
    },
    {
        "recordId": "RT-2024-0003",
        "deviceId": "AST-102-0002",
        "psrId": "PSR-220-0002",
        "deviceName": "2号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "testType": "预防性试验",
        "testDate": "2024-06-18",
        "result": "合格",
        "tester": "孙工",
        "dataSummary": "绕组直流电阻不平衡率 1.1%，绝缘电阻 10500MΩ",
    },
]

REPAIR_PROGRAMS: list[dict[str, Any]] = [
    {
        "programId": "PG-2026-0001",
        "programName": "1号主变A类检修方案",
        "deviceId": "AST-102-0001",
        "psrId": "PSR-220-0001",
        "deviceName": "1号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "workContent": "本体及套管检修、有载分接开关检查、冷却系统维护",
        "safetyMeasures": "停电、验电、装设接地线、悬挂标示牌",
        "personnel": "工作负责人：王工；成员：4人",
        "createDate": "2026-09-20",
    },
    {
        "programId": "PG-2026-0002",
        "programName": "2201断路器B类检修方案",
        "deviceId": "AST-103-0101",
        "psrId": "PSR-220-0101",
        "deviceName": "2201断路器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "workContent": "灭弧室检查、机构箱检修、SF6 气体处理",
        "safetyMeasures": "停电、验电、装设接地线、SF6 气体检测",
        "personnel": "工作负责人：李工；成员：3人",
        "createDate": "2026-10-08",
    },
]

PATROL_PLANS: list[dict[str, Any]] = [
    {
        "planId": "PP-2026-0001",
        "planName": "220kV 郑州变 2026年四季度例行巡视",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "frequency": "每月一次",
        "executor": "运维一班",
        "startDate": "2026-10-01",
        "endDate": "2026-12-31",
        "status": "执行中",
    },
    {
        "planId": "PP-2026-0002",
        "planName": "110kV 二里岗变 2026年10月特巡",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "frequency": "单次",
        "executor": "运维二班",
        "startDate": "2026-10-08",
        "endDate": "2026-10-09",
        "status": "未开始",
    },
    {
        "planId": "PP-2026-0003",
        "planName": "110kV 城东变 2026年三季度例行巡视",
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "frequency": "每月一次",
        "executor": "运维二班",
        "startDate": "2026-07-01",
        "endDate": "2026-09-30",
        "status": "已完成",
    },
]

PATROL_RECORDS: list[dict[str, Any]] = [
    {
        "recordId": "PR-2026-0001",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "patrolDate": "2026-09-28",
        "patrolTime": "2026-09-28 09:00-11:20",
        "patrolType": "例行巡视",
        "executor": "运维一班",
        "result": "发现异常 2 项",
        "abnormalities": ["1号主变套管渗油", "2201断路器机构箱受潮"],
    },
    {
        "recordId": "PR-2026-0002",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "patrolDate": "2026-09-15",
        "patrolTime": "2026-09-15 20:00-21:10",
        "patrolType": "熄灯巡视",
        "executor": "运维二班",
        "result": "正常",
        "abnormalities": [],
    },
    {
        "recordId": "PR-2026-0003",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "patrolDate": "2026-08-20",
        "patrolTime": "2026-08-20 09:00-10:40",
        "patrolType": "例行巡视",
        "executor": "运维一班",
        "result": "发现异常 1 项",
        "abnormalities": ["2号主变冷却器风扇异响"],
    },
]

TEST_ITEMS: list[dict[str, Any]] = [
    {
        "itemId": "TI-001",
        "itemName": "绕组绝缘电阻测量",
        "deviceType": "变压器",
        "testType": "预防性试验",
        "voltageLevel": "220kV",
        "standard": "DL/T 596-2021",
        "requirement": "绝缘电阻不低于出厂值的 70%",
        "durationMinutes": 60,
    },
    {
        "itemId": "TI-002",
        "itemName": "绕组直流电阻测量",
        "deviceType": "变压器",
        "testType": "预防性试验",
        "voltageLevel": "220kV",
        "standard": "DL/T 596-2021",
        "requirement": "相间不平衡率不大于 2%",
        "durationMinutes": 45,
    },
    {
        "itemId": "TI-003",
        "itemName": "断路器机械特性试验",
        "deviceType": "断路器",
        "testType": "例行试验",
        "voltageLevel": "220kV",
        "standard": "DL/T 596-2021",
        "requirement": "分合闸时间与同期差满足厂家技术条件",
        "durationMinutes": 30,
    },
    {
        "itemId": "TI-004",
        "itemName": "绝缘油色谱分析",
        "deviceType": "变压器",
        "testType": "预防性试验",
        "voltageLevel": "110kV",
        "standard": "DL/T 722-2014",
        "requirement": "乙炔含量为 0，总烃不超注意值",
        "durationMinutes": 40,
    },
]

# ---------------------------------------------------------------------------
# 可靠性：站级指标 / 停电事件 / 可开放容量
# ---------------------------------------------------------------------------
STATION_RELIABILITY: list[dict[str, Any]] = [
    {
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "statStartDate": "2026-01-01",
        "statEndDate": "2026-09-30",
        "statPeriod": "2026-01 至 2026-09",
        "availabilityRate": 99.982,
        "outageHours": 1.42,
        "outageUserHours": 320.5,
        "outageCount": 2,
    },
    {
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "statStartDate": "2026-01-01",
        "statEndDate": "2026-09-30",
        "statPeriod": "2026-01 至 2026-09",
        "availabilityRate": 99.965,
        "outageHours": 2.31,
        "outageUserHours": 168.0,
        "outageCount": 3,
    },
    {
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "statStartDate": "2026-01-01",
        "statEndDate": "2026-09-30",
        "statPeriod": "2026-01 至 2026-09",
        "availabilityRate": 99.991,
        "outageHours": 0.72,
        "outageUserHours": 58.4,
        "outageCount": 1,
    },
]

OUTAGE_INCIDENTS: list[dict[str, Any]] = [
    {
        "incidentId": "OI-2026-0001",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "outageStart": "2026-09-05 08:00",
        "outageEnd": "2026-09-05 12:30",
        "scope": "10kV 城北线 12 个台区",
        "cause": "计划检修",
        "voltageLevel": "10kV",
        "affectedUserCount": 1260,
    },
    {
        "incidentId": "OI-2026-0002",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "outageStart": "2026-07-18 14:20",
        "outageEnd": "2026-07-18 15:05",
        "scope": "10kV 二里岗线 6 个台区",
        "cause": "电缆故障",
        "voltageLevel": "10kV",
        "affectedUserCount": 480,
    },
    {
        "incidentId": "OI-2026-0003",
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "outageStart": "2026-08-22 09:10",
        "outageEnd": "2026-08-22 10:00",
        "scope": "10kV 城东线 4 个台区",
        "cause": "上级电源失电",
        "voltageLevel": "10kV",
        "affectedUserCount": 310,
    },
]

OPEN_CAPACITY: list[dict[str, Any]] = [
    {
        "deviceId": "AST-102-0001",
        "psrId": "PSR-220-0001",
        "deviceName": "1号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "voltageLevel": "220kV",
        "ratedCapacityMVA": 180,
        "currentLoadMVA": 126,
        "openCapacityMVA": 54,
        "loadRate": 70.0,
    },
    {
        "deviceId": "AST-102-0002",
        "psrId": "PSR-220-0002",
        "deviceName": "2号主变",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "voltageLevel": "220kV",
        "ratedCapacityMVA": 180,
        "currentLoadMVA": 98,
        "openCapacityMVA": 82,
        "loadRate": 54.4,
    },
    {
        "deviceId": "AST-102-0003",
        "psrId": "PSR-110-0001",
        "deviceName": "1号主变",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "voltageLevel": "110kV",
        "ratedCapacityMVA": 50,
        "currentLoadMVA": 31,
        "openCapacityMVA": 19,
        "loadRate": 62.0,
    },
    {
        "deviceId": "AST-102-0004",
        "psrId": "PSR-110-0002",
        "deviceName": "1号主变",
        "stationId": "STA-110-03",
        "stationName": "110kV 城东变电站",
        "voltageLevel": "110kV",
        "ratedCapacityMVA": 50,
        "currentLoadMVA": 22,
        "openCapacityMVA": 28,
        "loadRate": 44.0,
    },
]

# ---------------------------------------------------------------------------
# 作业资源：智能装备 / 仪器仪表 / 生产厂家
# ---------------------------------------------------------------------------
SMART_DEVICES: list[dict[str, Any]] = [
    {
        "deviceId": "SD-001",
        "deviceName": "1号主变在线监测装置",
        "deviceType": "在线监测",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "onlineStatus": "在线",
        "model": "OM-2200",
        "lastOnlineTime": "2026-10-20 08:00",
    },
    {
        "deviceId": "SD-002",
        "deviceName": "巡检机器人 A01",
        "deviceType": "机器人",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "onlineStatus": "离线",
        "model": "RB-A01",
        "lastOnlineTime": "2026-10-18 17:30",
    },
    {
        "deviceId": "SD-003",
        "deviceName": "无人机 U01",
        "deviceType": "无人机",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "onlineStatus": "在线",
        "model": "UAV-U01",
        "lastOnlineTime": "2026-10-20 09:15",
    },
]

INSTRUMENTS: list[dict[str, Any]] = [
    {
        "instrumentId": "IN-001",
        "instrumentName": "回路电阻测试仪",
        "instrumentType": "试验仪器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "manufacturer": "保定华创",
        "calibrationDate": "2026-03-15",
        "nextCalibrationDate": "2027-03-14",
        "calibrationStatus": "合格",
    },
    {
        "instrumentId": "IN-002",
        "instrumentName": "局部放电检测仪",
        "instrumentType": "试验仪器",
        "stationId": "STA-220-01",
        "stationName": "220kV 郑州变电站",
        "manufacturer": "上海华乘",
        "calibrationDate": "2026-01-08",
        "nextCalibrationDate": "2027-01-07",
        "calibrationStatus": "合格",
    },
    {
        "instrumentId": "IN-003",
        "instrumentName": "SF6 气体检漏仪",
        "instrumentType": "检测仪器",
        "stationId": "STA-110-02",
        "stationName": "110kV 二里岗变电站",
        "manufacturer": "上海华乘",
        "calibrationDate": "2025-12-20",
        "nextCalibrationDate": "2026-12-19",
        "calibrationStatus": "合格",
    },
]

MANUFACTURERS: list[dict[str, Any]] = [
    {
        "manufacturerId": "MF-001",
        "manufacturerName": "特变电工",
        "deviceTypes": ["变压器"],
        "contact": "400-000-0001",
        "address": "新疆昌吉（虚构地址）",
        "creditLevel": "A",
    },
    {
        "manufacturerId": "MF-002",
        "manufacturerName": "平高电气",
        "deviceTypes": ["断路器", "隔离开关"],
        "contact": "400-000-0002",
        "address": "河南平顶山（虚构地址）",
        "creditLevel": "A",
    },
    {
        "manufacturerId": "MF-003",
        "manufacturerName": "许继电气",
        "deviceTypes": ["在线监测", "机器人"],
        "contact": "400-000-0003",
        "address": "河南许昌（虚构地址）",
        "creditLevel": "B",
    },
]

# ---------------------------------------------------------------------------
# 图形拓扑：专题图 / 电源点供电路径 / 供电范围
# ---------------------------------------------------------------------------
_MAP_VERSION = "2026-09-01"


def _svg_content(psr: Mapping[str, Any]) -> str:
    """生成确定性的示例 SVG（虚构占位，不含真实接线信息）。"""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">'
        '<text x="20" y="30">DEMO SVG</text>'
        '<text x="20" y="60">{}</text>'
        '<text x="20" y="90">{}</text>'
        "</svg>"
    ).format(psr.get("stationName") or "", psr.get("psrName") or "")


def _svg_map(psr_id: str) -> dict[str, Any]:
    psr = PSR_BY_ID.get(psr_id)
    if not psr:
        return {}
    return {
        "psrId": psr["psrId"],
        "psrName": psr["psrName"],
        "graphicId": psr["graphicId"],
        "mapName": "{}一次接线图".format(psr["stationName"]),
        "mapType": "STATION_SINGLE_LINE",
        "svgContent": _svg_content(psr),
        "version": _MAP_VERSION,
    }


#: 供电路径起点（虚构：所有站点由 500kV 嵩山变供电）
SOURCE_PSR_ID = "PSR-500-0001"


def _power_path(psr_id: str) -> dict[str, Any]:
    psr = PSR_BY_ID.get(psr_id)
    if not psr:
        return {}
    nodes: list[dict[str, Any]] = [
        {"psrId": SOURCE_PSR_ID, "name": "500kV 嵩山变电站", "nodeType": "SOURCE"}
    ]
    if psr["stationId"] != "STA-500-00":
        station_psr = STATION_BY_ID[psr["stationId"]]["psrId"]
        if station_psr != psr["psrId"]:
            nodes.append(
                {"psrId": station_psr, "name": psr["stationName"], "nodeType": "STATION"}
            )
    nodes.append({"psrId": psr["psrId"], "name": psr["psrName"], "nodeType": "DEVICE"})
    return {
        "psrId": psr["psrId"],
        "sourcePsrId": SOURCE_PSR_ID,
        "sourceName": "500kV 嵩山变电站",
        "pathDescription": " → ".join(node["name"] for node in nodes),
        "pathNodes": nodes,
    }


#: 站级停电影响范围（虚构）
STATION_SUPPLY_AREA: dict[str, dict[str, Any]] = {
    "PSR-500-0001": {
        "affectedStations": ["220kV 郑州变电站", "110kV 二里岗变电站", "110kV 城东变电站"],
        "affectedUsers": ["地区负荷约 320MW", "重要用户 6 户"],
        "riskLevel": "重大",
    },
    "PSR-220-0000": {
        "affectedStations": ["110kV 二里岗变电站", "110kV 城东变电站"],
        "affectedUsers": ["城北线台区 12 个", "重要用户 2 户"],
        "riskLevel": "较大",
    },
    "PSR-110-0000": {
        "affectedStations": [],
        "affectedUsers": ["台区 8 个", "重要用户 1 户"],
        "riskLevel": "一般",
    },
    "PSR-110-0010": {
        "affectedStations": [],
        "affectedUsers": ["台区 5 个"],
        "riskLevel": "一般",
    },
}


def _supply_area(psr_id: str, direction: str) -> dict[str, Any]:
    psr = PSR_BY_ID.get(psr_id)
    if not psr:
        return {}
    station_psr = STATION_BY_ID[psr["stationId"]]["psrId"]
    template = STATION_SUPPLY_AREA.get(station_psr, {"affectedStations": [], "affectedUsers": [], "riskLevel": "一般"})
    return {
        "psrId": psr["psrId"],
        "psrName": psr["psrName"],
        "direction": direction or "outage",
        "affectedCount": len(template["affectedStations"]) + len(template["affectedUsers"]),
        "affectedStations": list(template["affectedStations"]),
        "affectedUsers": list(template["affectedUsers"]),
        "riskLevel": template["riskLevel"],
    }


# ---------------------------------------------------------------------------
# 各工具处理函数（26 个）
# ---------------------------------------------------------------------------
def _asset_row(params: Mapping[str, Any], asset_type_hint: str = "") -> list[dict[str, Any]]:
    """list_asset_params：按 assetType（英文 key 或中文设备类型）+ 站/电压等级过滤。"""
    wanted = asset_type_hint
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        if wanted and not (
            _eq(asset["assetType"], wanted) or _eq(asset["deviceType"], wanted)
        ):
            continue
        if not _eq(asset["stationId"], _text(params, "stationId")):
            continue
        if not _eq(asset["voltageLevel"], _text(params, "voltageLevel")):
            continue
        rows.append(
            {
                "assetId": asset["assetId"],
                "assetName": asset["assetName"],
                "deviceType": asset["deviceType"],
                "voltageLevel": asset["voltageLevel"],
                "stationId": asset["stationId"],
                "stationName": asset["stationName"],
                "model": asset["model"],
                "capacityMVA": asset["capacityMVA"],
                "voltageRatio": asset["voltageRatio"],
                "manufacturer": asset["manufacturer"],
                "commissioningDate": asset["commissioningDate"],
                "assetStatus": asset["assetStatus"],
            }
        )
    return rows


def handle_get_asset_by_id(params: Mapping[str, Any]) -> Any:
    asset = ASSET_BY_ID.get(_text(params, "assetId"))
    return copy.deepcopy(asset) if asset else {}


def handle_list_asset_params(params: Mapping[str, Any]) -> Any:
    rows = _asset_row(params, _text(params, "assetType"))
    return paginate(rows, params, 20)


def handle_get_device_by_utc_num(params: Mapping[str, Any]) -> Any:
    asset = ASSET_BY_UTC.get(_text(params, "utcNum"))
    if not asset:
        return {}
    return {
        "utcNum": asset["utcNum"],
        "assetId": asset["assetId"],
        "assetName": asset["assetName"],
        "stationId": asset["stationId"],
        "stationName": asset["stationName"],
        "deviceType": asset["deviceType"],
        "voltageLevel": asset["voltageLevel"],
        "assetStatus": asset["assetStatus"],
    }


def handle_list_psr_by_filters(params: Mapping[str, Any]) -> Any:
    name = _text(params, "name")
    rows = [
        dict(psr)
        for psr in PSR_DEVICES
        if psr["deviceType"] != "变电站"
        and _eq(psr["stationId"], _text(params, "stationId"))
        and _eq(psr["voltageLevel"], _text(params, "voltageLevel"))
        and _eq(psr["deviceType"], _text(params, "deviceType"))
        and _contains(psr["psrName"], name)
    ]
    return paginate(rows, params, 20)


def handle_get_psr_by_id(params: Mapping[str, Any]) -> Any:
    psr = PSR_BY_ID.get(_text(params, "psrId"))
    return copy.deepcopy(psr) if psr else {}


def handle_get_device_tree_root(params: Mapping[str, Any]) -> Any:
    return copy.deepcopy(ROOT_NODE)


def handle_get_device_tree_nodes(params: Mapping[str, Any]) -> Any:
    parent_id = _text(params, "parentId")
    node_type = _text(params, "nodeType")
    rows = [
        node
        for node in TREE_INDEX.get(parent_id, [])
        if not node_type or _eq(node["nodeType"], node_type)
    ]
    return paginate(rows, params, 50)


def handle_inquire_defect(params: Mapping[str, Any]) -> Any:
    rows = [
        _defect_brief(item)
        for item in DEFECTS
        if _device_hit(item, _text(params, "deviceId"))
        and _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["defectLevel"], _text(params, "defectLevel"))
        and _eq(item["status"], _text(params, "status"))
        and _in_date_range(item["discoverTime"], _text(params, "startTime"), _text(params, "endTime"))
    ]
    return paginate(rows, params, 20)


def _defect_brief(item: Mapping[str, Any]) -> dict[str, Any]:
    """缺陷列表行的轻量字段（明细看 view_defect）。"""
    return {
        "defectId": item["defectId"],
        "defectNo": item["defectNo"],
        "deviceId": item["deviceId"],
        "psrId": item["psrId"],
        "deviceName": item["deviceName"],
        "stationId": item["stationId"],
        "stationName": item["stationName"],
        "defectLevel": item["defectLevel"],
        "discoverTime": item["discoverTime"],
        "part": item["part"],
        "status": item["status"],
        "handler": item["handler"],
    }


def handle_view_defect(params: Mapping[str, Any]) -> Any:
    wanted = _text(params, "defectId")
    for item in DEFECTS:
        if item["defectId"] == wanted:
            return copy.deepcopy(item)
    return {}


def handle_list_hazard(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in HAZARDS
        if _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["hazardType"], _text(params, "hazardType"))
        and _eq(item["riskLevel"], _text(params, "riskLevel"))
        and _eq(item["status"], _text(params, "status"))
    ]
    return paginate(rows, params, 20)


def handle_list_fault_trip_records(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in FAULT_TRIPS
        if _device_hit(item, _text(params, "deviceId"))
        and _eq(item["stationId"], _text(params, "stationId"))
        and _in_date_range(item["faultTime"], _text(params, "startTime"), _text(params, "endTime"))
    ]
    return paginate(rows, params, 20)


def handle_get_repair_plan(params: Mapping[str, Any]) -> Any:
    wanted_year = _positive_int(params.get("year"), 0)
    wanted_month = _positive_int(params.get("month"), 0)
    rows = []
    for item in REPAIR_PLANS:
        start = item["planStartDate"]
        if wanted_year and int(start[:4]) != wanted_year:
            continue
        if wanted_month and int(start[5:7]) != wanted_month:
            continue
        if not _device_hit(item, _text(params, "deviceId")):
            continue
        if not _eq(item["stationId"], _text(params, "stationId")):
            continue
        if not _eq(item["status"], _text(params, "planStatus")):
            continue
        rows.append(dict(item))
    return paginate(rows, params, 20)


def handle_find_repair_test(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in REPAIR_TESTS
        if _device_hit(item, _text(params, "deviceId"))
        and _in_date_range(item["testDate"], _text(params, "startTime"), _text(params, "endTime"))
    ]
    return paginate(rows, params, 20)


def handle_find_repair_program(params: Mapping[str, Any]) -> Any:
    program_id = _text(params, "programId")
    rows = [
        dict(item)
        for item in REPAIR_PROGRAMS
        if (not program_id or item["programId"] == program_id)
        and _device_hit(item, _text(params, "deviceId"))
        and _eq(item["stationId"], _text(params, "stationId"))
    ]
    return paginate(rows, params, 20)


def handle_list_patrol_plan(params: Mapping[str, Any]) -> Any:
    start = _text(params, "startDate")
    end = _text(params, "endDate")
    rows = [
        dict(item)
        for item in PATROL_PLANS
        if _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["status"], _text(params, "status"))
        and _ranges_intersect(item["startDate"], item["endDate"], start, end)
    ]
    return paginate(rows, params, 20)


def handle_list_patrol_record(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in PATROL_RECORDS
        if _eq(item["stationId"], _text(params, "stationId"))
        and _in_date_range(item["patrolDate"], _text(params, "startDate"), _text(params, "endDate"))
    ]
    return paginate(rows, params, 20)


def handle_list_test_item(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in TEST_ITEMS
        if _eq(item["deviceType"], _text(params, "deviceType"))
        and _eq(item["testType"], _text(params, "testType"))
        and _eq(item["voltageLevel"], _text(params, "voltageLevel"))
    ]
    return paginate(rows, params, 50)


def handle_query_station_scale_analysis(params: Mapping[str, Any]) -> Any:
    start = _text(params, "startDate")
    end = _text(params, "endDate")
    rows = [
        dict(item)
        for item in STATION_RELIABILITY
        if _eq(item["stationId"], _text(params, "stationId"))
        and _ranges_intersect(item["statStartDate"], item["statEndDate"], start, end)
    ]
    return paginate(rows, params, 20)


def handle_query_outage_incident(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in OUTAGE_INCIDENTS
        if _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["voltageLevel"], _text(params, "voltageLevel"))
        and _in_date_range(item["outageStart"], _text(params, "startTime"), _text(params, "endTime"))
    ]
    return paginate(rows, params, 20)


def handle_query_open_capacity(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in OPEN_CAPACITY
        if _device_hit(item, _text(params, "deviceId"))
        and _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["voltageLevel"], _text(params, "voltageLevel"))
    ]
    return paginate(rows, params, 20)


def handle_find_smart_device(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in SMART_DEVICES
        if _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["deviceType"], _text(params, "deviceType"))
        and _eq(item["onlineStatus"], _text(params, "onlineStatus"))
    ]
    return paginate(rows, params, 20)


def handle_get_instrument_list(params: Mapping[str, Any]) -> Any:
    rows = [
        dict(item)
        for item in INSTRUMENTS
        if _eq(item["stationId"], _text(params, "stationId"))
        and _eq(item["instrumentType"], _text(params, "instrumentType"))
    ]
    return paginate(rows, params, 20)


def handle_get_manufacturer_infos(params: Mapping[str, Any]) -> Any:
    name = _text(params, "manufacturerName")
    rows = [dict(item) for item in MANUFACTURERS if _contains(item["manufacturerName"], name)]
    return paginate(rows, params, 50)


def handle_query_svg_map_by_psr_id(params: Mapping[str, Any]) -> Any:
    return _svg_map(_text(params, "psrId"))


def _resolve_psr_id(params: Mapping[str, Any]) -> str:
    """``psrId`` 优先；其次接受 ``deviceId``（assetId 或 psrId）。"""
    psr_id = _text(params, "psrId")
    if psr_id:
        return psr_id
    device_id = _text(params, "deviceId")
    if not device_id:
        return ""
    if device_id in PSR_BY_ID:
        return device_id
    asset = ASSET_BY_ID.get(device_id)
    return asset["psrId"] if asset else ""


def handle_search_power_path(params: Mapping[str, Any]) -> Any:
    return _power_path(_resolve_psr_id(params))


def handle_analyze_supply_area(params: Mapping[str, Any]) -> Any:
    psr_id = _resolve_psr_id(params)
    direction = _text(params, "direction") or "outage"
    return _supply_area(psr_id, direction)


#: 工具名 → 处理函数（键必须与 spec/interfaces.json 的 tools[].name 完全一致）
HANDLERS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    "get_asset_by_id": handle_get_asset_by_id,
    "list_asset_params": handle_list_asset_params,
    "get_device_by_utc_num": handle_get_device_by_utc_num,
    "list_psr_by_filters": handle_list_psr_by_filters,
    "get_psr_by_id": handle_get_psr_by_id,
    "get_device_tree_root": handle_get_device_tree_root,
    "get_device_tree_nodes": handle_get_device_tree_nodes,
    "inquire_defect": handle_inquire_defect,
    "view_defect": handle_view_defect,
    "list_hazard": handle_list_hazard,
    "list_fault_trip_records": handle_list_fault_trip_records,
    "get_repair_plan": handle_get_repair_plan,
    "find_repair_test": handle_find_repair_test,
    "find_repair_program": handle_find_repair_program,
    "list_patrol_plan": handle_list_patrol_plan,
    "list_patrol_record": handle_list_patrol_record,
    "list_test_item": handle_list_test_item,
    "query_station_scale_analysis": handle_query_station_scale_analysis,
    "query_outage_incident": handle_query_outage_incident,
    "query_open_capacity": handle_query_open_capacity,
    "find_smart_device": handle_find_smart_device,
    "get_instrument_list": handle_get_instrument_list,
    "get_manufacturer_infos": handle_get_manufacturer_infos,
    "query_svg_map_by_psr_id": handle_query_svg_map_by_psr_id,
    "search_power_path": handle_search_power_path,
    "analyze_supply_area": handle_analyze_supply_area,
}

#: 列表/分页类工具：data 为 ``{"list","total","pageNo","pageSize"}``
PAGED_TOOLS = frozenset(
    {
        "list_asset_params",
        "list_psr_by_filters",
        "get_device_tree_nodes",
        "inquire_defect",
        "list_hazard",
        "list_fault_trip_records",
        "get_repair_plan",
        "find_repair_test",
        "find_repair_program",
        "list_patrol_plan",
        "list_patrol_record",
        "list_test_item",
        "query_station_scale_analysis",
        "query_outage_incident",
        "query_open_capacity",
        "find_smart_device",
        "get_instrument_list",
        "get_manufacturer_infos",
    }
)

#: 单对象类工具：data 为对象（未知主键返回 ``{}``）
OBJECT_TOOLS = frozenset(HANDLERS) - PAGED_TOOLS

TOOL_NAMES: tuple[str, ...] = tuple(HANDLERS)


def handle(tool_name: str, params: Mapping[str, Any] | None = None) -> Any:
    """按工具名返回该接口的 ``data`` 部分。

    未知工具名抛 ``KeyError``（服务端在注册路由阶段已按 spec 校验，正常不会发生）。
    """
    handler = HANDLERS.get(str(tool_name))
    if handler is None:
        raise KeyError("未知工具：{}".format(tool_name))
    return handler(dict(params or {}))


def summarize() -> dict[str, Any]:
    """数据集规模摘要（供 doctor / 文档 / 测试断言）。"""
    return {
        "toolCount": len(HANDLERS),
        "pagedToolCount": len(PAGED_TOOLS),
        "objectToolCount": len(OBJECT_TOOLS),
        "stations": len(STATIONS),
        "assets": len(ASSETS),
        "psrDevices": len(PSR_DEVICES),
        "treeNodes": len(TREE_NODES),
        "defects": len(DEFECTS),
        "hazards": len(HAZARDS),
        "faultTrips": len(FAULT_TRIPS),
        "repairPlans": len(REPAIR_PLANS),
        "repairTests": len(REPAIR_TESTS),
        "repairPrograms": len(REPAIR_PROGRAMS),
        "patrolPlans": len(PATROL_PLANS),
        "patrolRecords": len(PATROL_RECORDS),
        "testItems": len(TEST_ITEMS),
        "stationReliability": len(STATION_RELIABILITY),
        "outageIncidents": len(OUTAGE_INCIDENTS),
        "openCapacity": len(OPEN_CAPACITY),
        "smartDevices": len(SMART_DEVICES),
        "instruments": len(INSTRUMENTS),
        "manufacturers": len(MANUFACTURERS),
    }

# ---------------------------------------------------------------------------
# 可选扩展数据集（P2/P3 压力测试用；默认数据集不受影响）
# ---------------------------------------------------------------------------
def _load_extended_dataset() -> None:
    import os
    import sys

    dataset = os.environ.get("PMS_MOCK_DATASET", "").strip().lower()
    if dataset == "extended":
        from . import data_extended

        data_extended.extend(sys.modules[__name__])
    elif dataset == "realistic":
        from . import data_realistic

        data_realistic.extend(sys.modules[__name__])


_load_extended_dataset()
