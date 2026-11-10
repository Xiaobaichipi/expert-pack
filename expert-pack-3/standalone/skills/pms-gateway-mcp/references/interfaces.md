# PMS 接口网关 · 26 个工具目录

本文件是 `pms-gateway-mcp` 底座技能的**工具目录参考**，面向「要调哪个工具、传什么参数、拿到什么数据」的场景。
所有工具、接口编码、地址、参数、返回形态的唯一事实源是专家包内的
[`spec/interfaces.json`](../../../spec/interfaces.json)；本文件由该文件整理而成，二者不一致时以 spec 为准。

> ⚠️ **状态说明**：spec 的 `status` 为 `inferred`，接口路径、参数与返回字段均为依据
> 《变电智能问数_26接口功能说明》与平台命名惯例**推断的占位规格**。正式《接口说明文档》下发后，
> 只需修改 `spec/interfaces.json`，本技能代码（client / MCP / CLI）与本目录表同步更新即可，无需改业务逻辑。
>
> 参数列中带 **✓** 表示必填（`required: true`）。

## 一、分组概览（6 组 / 26 工具）

| 分组 | 名称 | 负责角色 | 对应业务技能 | 工具数 |
|---|---|---|---|---|
| `asset-ledger` | 设备台账 | 设备档案专家 | `substation-asset-ledger` | 5 |
| `device-tree` | 设备树导航 | 设备导航专家 | `substation-device-tree` | 2 |
| `om-health` | 运维健康（缺陷/隐患/故障） | 运维健康专家 | `substation-om-health` | 4 |
| `maintenance-test` | 检修试验（计划/方案/修试/巡视/试验项目） | 检修试验专家 | `substation-maintenance-test` | 6 |
| `reliability` | 可靠性分析 | 可靠性分析专家 | `substation-reliability` | 3 |
| `resource-topology` | 作业资源与图形拓扑 | 资源拓扑专家 | `substation-resource-topology` | 6 |

## 二、26 个工具目录表

| # | 工具名 | 接口编码 | 接口名称 | 请求 | 入参 | 返回形态 | 分组 / 技能 |
|---|---|---|---|---|---|---|---|
| 1 | `get_asset_by_id` | `pgp-102-2411-00102` | 根据资产ID查看设备台账详情 | `GET /assetCenter/queryServices/getAstById` | assetId✓ | 单个对象 | 设备台账 / `substation-asset-ledger` |
| 2 | `list_asset_params` | `pgp-102-2411-00101` | 查询设备资产参数列表 | `GET /assetCenter/queryServices/{assetType}` | assetType✓（路径参数）、stationId、voltageLevel、pageNo、pageSize | 分页列表 | 设备台账 / `substation-asset-ledger` |
| 3 | `get_device_by_utc_num` | `pgp-102-2411-00103` | 根据实物ID查看设备台账详情 | `GET /assetCenter/queryServices/getDeviceByUTCNum` | utcNum✓ | 单个对象 | 设备台账 / `substation-asset-ledger` |
| 4 | `list_psr_by_filters` | `pgp-101-2411-00102` | 查询电网设备台账列表 | `POST /PSRCenter/queryServices/listPropertiesByFilters` | stationId、voltageLevel、deviceType、name、pageNo、pageSize | 分页列表 | 设备台账 / `substation-asset-ledger` |
| 5 | `get_psr_by_id` | `pgp-101-2411-00103` | 根据资源ID查看设备台账详情 | `GET /PSRCenter/queryServices/getPsrById` | psrId✓ | 单个对象 | 设备台账 / `substation-asset-ledger` |
| 6 | `get_device_tree_root` | `pgp-101-2411-00501` | 查询设备树根节点 | `GET /PSRCenter/commonTreeService/getDeviceTreeRoot` | orgId | 单个对象 | 设备树导航 / `substation-device-tree` |
| 7 | `get_device_tree_nodes` | `pgp-101-2411-00503` | 查询设备树下级节点 | `GET /PSRCenter/commonTreeService/getDeviceTreeNodes` | parentId✓、nodeType、pageNo、pageSize | 列表 | 设备树导航 / `substation-device-tree` |
| 8 | `inquire_defect` | `pgp-106-2411-00703` | 查询缺陷记录 | `POST /WMCenter/defect/inquireDefect` | stationId、deviceId、defectLevel、status、startTime、endTime、pageNo、pageSize | 分页列表 | 运维健康 / `substation-om-health` |
| 9 | `view_defect` | `pgp-106-2411-00704` | 查看缺陷记录 | `GET /WMCenter/defect/viewDefect` | defectId✓ | 单个对象（含照片/过程/验收） | 运维健康 / `substation-om-health` |
| 10 | `list_hazard` | `pgp-106-2411-01003` | 查询隐患记录 | `POST /WMCenter/hazard/listHazard` | stationId、hazardType、riskLevel、status、pageNo、pageSize | 分页列表 | 运维健康 / `substation-om-health` |
| 11 | `list_fault_trip_records` | `pgp-106-2411-02603` | 查询故障记录 | `POST /WMCenter/operation/faultTriprcdList` | deviceId、stationId、startTime、endTime、pageNo、pageSize | 分页列表 | 运维健康 / `substation-om-health` |
| 12 | `get_repair_plan` | `pgp-106-2411-04206` | 查询检修计划 | `POST /WMCenter/repairManagement/getRepairPlan` | deviceId、stationId、year、month、planStatus、pageNo、pageSize | 分页列表 | 检修试验 / `substation-maintenance-test` |
| 13 | `find_repair_test` | `pgp-106-2411-05003` | 查询修试记录 | `POST /WMCenter/examineRepair/findRepairTest` | deviceId、startTime、endTime、pageNo、pageSize | 分页列表 | 检修试验 / `substation-maintenance-test` |
| 14 | `find_repair_program` | `pgp-106-2411-04803` | 查询检修方案 | `POST /WMCenter/examineRepair/findProgram` | programId、deviceId、stationId、pageNo、pageSize | 分页列表 | 检修试验 / `substation-maintenance-test` |
| 15 | `list_patrol_plan` | `pgp-106-2411-00303` | 查询巡视计划（工单） | `POST /WMCenter/patrol/planList` | stationId、startDate、endDate、status、pageNo、pageSize | 分页列表 | 检修试验 / `substation-maintenance-test` |
| 16 | `list_patrol_record` | `pgp-106-2411-00403` | 查询巡视记录 | `POST /WMCenter/patrol/recordList` | stationId、startDate、endDate、pageNo、pageSize | 分页列表 | 检修试验 / `substation-maintenance-test` |
| 17 | `list_test_item` | `pgp-106-2411-06801` | 查询检测试验项目 | `GET /WMCenter/test/testItemList` | deviceType、testType、voltageLevel、pageNo、pageSize | 分页列表 | 检修试验 / `substation-maintenance-test` |
| 18 | `query_station_scale_analysis` | `pgp-108-2411-00405` | 统计变电站可靠性分析数据 | `POST /analyCenter/reliabilityAnalyData/queryStationScaleAnalysis` | stationId、startDate、endDate、pageNo、pageSize | 分页列表 | 可靠性分析 / `substation-reliability` |
| 19 | `query_outage_incident` | `pgp-108-2411-00502` | 查询可靠性中压停电事件列表 | `POST /analyCenter/reliabilityEvent/queryOutageIncidentInformation` | stationId、voltageLevel、startTime、endTime、pageNo、pageSize | 分页列表 | 可靠性分析 / `substation-reliability` |
| 20 | `query_open_capacity` | `pgp-108-2411-00201` | 查询设备可开放容量 | `POST /analyCenter/queryOpenCapacityData/find` | deviceId、stationId、voltageLevel、pageNo、pageSize | 分页列表 | 可靠性分析 / `substation-reliability` |
| 21 | `find_smart_device` | `pgp-105-2411-00602` | 查询智能装备台账信息 | `POST /WRCenter/SmartDevice/findSmartDevice` | stationId、deviceType、onlineStatus、pageNo、pageSize | 分页列表 | 资源拓扑 / `substation-resource-topology` |
| 22 | `get_instrument_list` | `pgp-105-2411-00403` | 查询仪器仪表台账信息 | `POST /WRCenter/instruments/getInstrumentLIST` | stationId、instrumentType、pageNo、pageSize | 分页列表 | 资源拓扑 / `substation-resource-topology` |
| 23 | `get_manufacturer_infos` | `pgp-102-2411-00701` | 查询生产厂家列表 | `GET /baseCenter/devInfoService/manufacturerInfos` | manufacturerName、pageNo、pageSize | 分页列表 | 资源拓扑 / `substation-resource-topology` |
| 24 | `query_svg_map_by_psr_id` | `pgp-103-2411-00502` | 根据设备ID获取专题图 | `GET /geoCenter/thematicMapQueryServices/querySvgMapByPsrId` | psrId✓ | 单个对象（SVG 内容 + 图元） | 资源拓扑 / `substation-resource-topology` |
| 25 | `search_power_path` | `pgp-104-2411-00101` | 查询电源点和供电路径 | `POST /topoCenter/normalServices/searchPower` | psrId、deviceId（二选一） | 单个对象（电源点 + 路径节点） | 资源拓扑 / `substation-resource-topology` |
| 26 | `analyze_supply_area` | `pgp-104-2411-00301` | 分析供电范围 | `POST /topoCenter/normalServices/supplyArea` | psrId、deviceId（二选一）、direction（outage/restore，默认 outage） | 单个对象（影响范围） | 资源拓扑 / `substation-resource-topology` |

## 三、典型问数 → 工具与参数示例

| # | 工具名 | 典型问数 | 示例参数（mock 模式可直接跑通） |
|---|---|---|---|
| 1 | `get_asset_by_id` | 这台主变是什么型号、容量多少、投运多久了？ | `{"assetId": "AST-102-0001"}` |
| 2 | `list_asset_params` | 全站主变的容量参数分别有哪些？ | `{"assetType": "transformer", "voltageLevel": "220kV"}` |
| 3 | `get_device_by_utc_num` | 扫这个实物ID对应的是哪台设备、台账如何？ | `{"utcNum": "UTC-2020-000123"}` |
| 4 | `list_psr_by_filters` | 某220kV站共有多少台断路器、型号分布如何？ | `{"voltageLevel": "220kV", "deviceType": "断路器"}` |
| 5 | `get_psr_by_id` | 这个设备的资源台账和接线关系是什么？ | `{"psrId": "PSR-220-0001"}` |
| 6 | `get_device_tree_root` | 全局设备树从哪里开始展开？ | `{}` |
| 7 | `get_device_tree_nodes` | 进入某站后下面挂哪些一次设备？ | `{"parentId": "ROOT"}` |
| 8 | `inquire_defect` | 某变电站当前有哪些严重、危急缺陷？ | `{"defectLevel": "严重", "status": "处理中"}` |
| 9 | `view_defect` | 这条缺陷的详细情况、处理到哪一步了？ | `{"defectId": "DF-2026-0001"}` |
| 10 | `list_hazard` | 变电站周边有哪些尚未闭环的隐患？ | `{"status": "整改中"}` |
| 11 | `list_fault_trip_records` | 这台主变最近有没有跳闸/故障？原因是什么？ | `{"deviceId": "AST-102-0001"}` |
| 12 | `get_repair_plan` | 这台设备本年度有没有检修计划？安排在什么时候？ | `{"year": 2026, "planStatus": "待执行"}` |
| 13 | `find_repair_test` | 这台设备的历次修试历史与试验数据有哪些？ | `{"deviceId": "AST-102-0001"}` |
| 14 | `find_repair_program` | 这次检修的方案和作业内容是什么？ | `{"programId": "PG-2026-0001"}` |
| 15 | `list_patrol_plan` | 本季度该站的巡视计划/工单有哪些？ | `{"stationId": "STA-220-01"}` |
| 16 | `list_patrol_record` | 该站最近一次巡视是什么时候、结果如何？ | `{"stationId": "STA-220-01"}` |
| 17 | `list_test_item` | 变压器预防性试验要做哪些项目、依据什么标准？ | `{"deviceType": "变压器", "testType": "预防性试验"}` |
| 18 | `query_station_scale_analysis` | 这个站的供电可靠率是多少？可靠性指标如何？ | `{"stationId": "STA-220-01"}` |
| 19 | `query_outage_incident` | 最近有哪些停电事件？影响范围多大？ | `{"voltageLevel": "10kV"}` |
| 20 | `query_open_capacity` | 这台主变还有多少可开放容量？当前负载多大？ | `{"deviceId": "AST-102-0001"}` |
| 21 | `find_smart_device` | 站里有哪些在线监测/智能装备？在不在线？ | `{"deviceType": "在线监测"}` |
| 22 | `get_instrument_list` | 站内有哪些试验仪器仪表？检定情况如何？ | `{"instrumentType": "试验仪器"}` |
| 23 | `get_manufacturer_infos` | 这批断路器是哪个厂家生产的？ | `{"manufacturerName": "平高"}` |
| 24 | `query_svg_map_by_psr_id` | 能调出这台设备的接线图/专题图吗？ | `{"psrId": "PSR-220-0001"}` |
| 25 | `search_power_path` | 这个站的电源从哪里来？供电路径是什么？ | `{"psrId": "PSR-220-0001"}` |
| 26 | `analyze_supply_area` | 这台设备停电会影响哪些用户/设备？ | `{"psrId": "PSR-220-0001", "direction": "outage"}` |

> 说明：mock 模式下的过滤是「按 mock 样例字段做等值/包含匹配」，因此部分示例参数（如 `stationId`）
> 在 mock 数据没有对应字段时会自动忽略，不会被误当成「查不到」。切到真实网关后过滤行为以接口实现为准。

## 四、调用与返回约定

### 4.1 请求参数风格（`paramStyle`）

| 风格 | 含义 | 参数去向 | 示例工具 |
|---|---|---|---|
| `query` | 纯 GET 查询 | 全部参数拼 query string | `get_asset_by_id`、`list_test_item` |
| `json_body` | 纯 POST 查询 | 全部参数放 JSON body | `inquire_defect`、`query_open_capacity` |
| `mixed` | 混合 | `in: path` 的参数替换路径占位符，其余按方法进 query/body | `list_asset_params` |

路径参数示例：`list_asset_params` 的 `assetType=transformer` 会把
`/assetCenter/queryServices/{assetType}` 替换为 `/assetCenter/queryServices/transformer`。

### 4.2 返回归一

客户端把所有返回统一成 `{code, message, data}`（真实模式再附加 `meta`）：

```json
{"code": 0, "message": "ok", "data": {"assetId": "AST-102-0001", "assetName": "1号主变"}}
```

- `code=0` 表示成功；非 0 的业务码会抛 `REMOTE_ERROR`（含远端 code 与 message）。
- 列表提取兼容 `data.list` / `data.records` / `data.rows` / 直接 `list`（`extract_list`）。
- 总数提取兼容 `total` / `totalCount` / `count`（`extract_total`）。
- mock 模式的 `meta` 形如 `{"mode": "mock", "tool": "...", "interfaceCode": "...", "paged": true}`，
  回答用户时必须标注「Mock 数据，仅用于联调」。

### 4.3 分页约定

分页工具统一使用 `pageNo`（从 1 开始）+ `pageSize`（默认 20 或 50，见各工具 spec 的 `default`）。
mock 模式返回 `{"total": <过滤后总数>, "pageNo": ..., "pageSize": ..., "list": [...]}`。

### 4.4 设备主键口径（重要）

| 主键 | 含义 | 主要接口 |
|---|---|---|
| `assetId` | 资产/设备台账 ID（如 `AST-102-0001`） | `get_asset_by_id` |
| `psrId` | 电网资源 ID（如 `PSR-220-0001`），资源侧与拓扑/图形视角 | `get_psr_by_id`、`query_svg_map_by_psr_id`、`search_power_path`、`analyze_supply_area` |
| `utcNum` | 实物 ID（二维码/标签编码） | `get_device_by_utc_num` |
| `deviceId` / `stationId` | 业务系统内的设备 ID / 变电站 ID | 缺陷、检修、巡视、可靠性等业务接口（多数标为可选） |

同一台设备在资产侧与资源侧字段口径不同，跨接口关联时优先用 `psrId` 对齐（详见
`substation-asset-ledger` 技能与 `substation-qa-orchestrator` 的主键归一规则）。

## 五、工具可见性自检

```bash
# 26 个工具一次看全（JSON）
python skills/pms-gateway-mcp/scripts/pms_cli.py list-tools

# MCP 宿主视角：tools/list 应返回 26 个工具
# 每个工具都含 name / description / inputSchema（required 与 spec 一致）
```
