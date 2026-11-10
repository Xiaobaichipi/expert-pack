# 资源拓扑专家 · 典型问数与参数模板

> 本文件是 `substation-resource-topology` 的细节层。工具名与参数名以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，示例数据来自 `spec/interfaces.json` 的 `mock` 字段，回答时须标注「Mock 数据，仅用于联调」。

## 一、枚举与主键口径

| 维度 | 取值 | 说明 |
|---|---|---|
| 智能装备类型 `deviceType` | 在线监测 / 机器人 / 无人机 | 与一次设备 `deviceType`（变压器/断路器）同名不同义，注意区分 |
| 在线状态 `onlineStatus` | 在线 / 离线 | 查询时点快照，非历史在线率 |
| 仪表检定状态 `calibrationStatus` | 合格 / 不合格 / 超期（示例值 合格） | 以最近一次 `calibrationDate` 检定结论为准 |
| 停电分析方向 `direction` | outage（停电影响）/ restore（复电范围） | 默认 `outage` |
| 拓扑主键 | `psrId`（优先）或 `deviceId`（二选一） | 两者不能同时为空 |

## 二、典型问数（10 条）

### 问数 1：站里有哪些智能装备？在不在线？

- **工具组合**：`find_smart_device`（全量 + 按 `onlineStatus` 过滤）
- **参数模板**：

```json
[
  {"tool": "find_smart_device", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "find_smart_device", "arguments": {"stationId": "STA-220-01", "onlineStatus": "离线", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：`total` 为装备总台数；`onlineStatus` 为查询时点状态；「在线率」= 在线台数 ÷ 台数总数（时点值，不代表统计周期可用率）。
- **输出要点**：装备表 + 在线/离线统计 + 离线清单提示核查。

### 问数 2：站内有哪些试验仪器仪表？检定情况如何？

- **工具组合**：`get_instrument_list`
- **参数模板**：

```json
{"tool": "get_instrument_list", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：`instrumentType` 为仪表类型（示例「试验仪器」）；`calibrationDate` 为最近检定日期，`calibrationStatus` 为检定结论；检定有效期周期**以本单位计量管理规定为准**。
- **输出要点**：仪表表（名称 | 类型 | 检定日期 | 状态）+ 到期提醒（按检定周期推算，注明周期来源）。

### 问数 3：这批断路器是哪个厂家生产的？

- **工具组合**：`get_manufacturer_infos`（按名称模糊）+ 台账侧 `get_asset_by_id`/`list_asset_params` 取 `manufacturer`
- **参数模板**：

```json
[
  {"tool": "list_asset_params", "arguments": {"assetType": "breaker", "stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_manufacturer_infos", "arguments": {"manufacturerName": "平高", "pageNo": 1, "pageSize": 20}}
]
```

- **字段口径**：厂家名在台账中为自由文本，需与 `manufacturerName` 归一（全称/简称）；`deviceTypes` 为厂家供货设备类型数组，用于校验匹配合理性。
- **输出要点**：设备-厂家对照表 + 厂家联系人（脱敏）；归一规则说明。

### 问数 4：能调出这台设备的接线图/专题图吗？

- **工具组合**：`query_svg_map_by_psr_id`
- **参数模板**：

```json
{"tool": "query_svg_map_by_psr_id", "arguments": {"psrId": "PSR-220-0001"}}
```

- **字段口径**：`mapType` 为图类型（示例 `STATION_SINGLE_LINE` 站一次接线图）；`version` 为图版本时间；`svgContent` 为 SVG 文本，可原样提供但不得解读图形状态；`graphicId`（来自 `get_psr_by_id`）可用于排查「图未出」的问题。
- **输出要点**：图名 + 图类型 + 版本 + SVG 提供方式（内联/链接）；提示图不含实时运行状态。

### 问数 5：这个站的电源从哪里来？供电路径是什么？

- **工具组合**：`search_power_path`
- **参数模板**：

```json
{"tool": "search_power_path", "arguments": {"psrId": "PSR-220-0001"}}
```

- **字段口径**：`sourcePsrId`/`sourceName` 为上级电源点；`pathNodes` 为路径节点序列（按供电方向排列）；`pathDescription` 为文本链路描述，二者应一致，若不一致以 `pathNodes` 为准并说明。
- **输出要点**：电源点 + 链路（A → B → C）+ 路径节点表；说明为静态拓扑关系，不含运行方式变更。

### 问数 6：这台设备停电会影响哪些用户/设备？

- **工具组合**：`analyze_supply_area`（`direction=outage`）+ 必要时 `search_power_path`
- **参数模板**：

```json
[
  {"tool": "analyze_supply_area", "arguments": {"psrId": "PSR-220-0001", "direction": "outage"}},
  {"tool": "search_power_path", "arguments": {"psrId": "PSR-220-0001"}}
]
```

- **字段口径**：`affectedCount` 为受影响对象数；`affectedStations` 为受影响下级站；`affectedUsers` 为用户/台区文本；`riskLevel` 为风险等级（示例「较大」）**以本单位风险评估规定为准**。
- **输出要点**：影响范围表 + 风险等级 + 「静态推演，未计转供与保护动作，需业务复核」提示。

### 问数 7：如果这台设备复电，哪些范围会恢复？

- **工具组合**：`analyze_supply_area`（`direction=restore`）
- **参数模板**：

```json
{"tool": "analyze_supply_area", "arguments": {"psrId": "PSR-220-0001", "direction": "restore"}}
```

- **字段口径**：`direction` 切换为 `restore` 时返回复电影响范围；与 `outage` 结果通常对称但不保证完全一致，需分别调用并对照。
- **输出要点**：复电范围表 + 与停电范围的对称性说明。

### 问数 8：站内离线智能装备清单与影响评估

- **工具组合**：`find_smart_device`（离线）+ 相关设备台账
- **参数模板**：

```json
[
  {"tool": "find_smart_device", "arguments": {"stationId": "STA-220-01", "onlineStatus": "离线", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "deviceType": "变压器", "pageNo": 1, "pageSize": 20}}
]
```

- **字段口径**：离线装备的监测覆盖对象需人工确认（接口不一定返回被监测设备主键，示例 mock 无该字段）；不得推断「离线 = 未监测」的影响结论。
- **输出要点**：离线清单 + 建议核查项；明确「被监测设备关联字段未在接口返回中提供」。

### 问数 9：检修作业资源保障核查（装备 + 仪器 + 厂家）

- **工具组合**：`find_smart_device` + `get_instrument_list` + `get_manufacturer_infos`
- **参数模板**：

```json
[
  {"tool": "find_smart_device", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_instrument_list", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_manufacturer_infos", "arguments": {"pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：资源清单是「有什么」，不代表「可用」；可用性需结合状态字段判断，缺失字段不得假设。
- **输出要点**：资源清单 + 缺口提示（如仪表检定过期、装备离线）。

### 问数 10：停电影响 + 历史停电交叉验证（跨技能）

- **工具组合**：本技能 `analyze_supply_area` + `substation-reliability` 的 `query_outage_incident` + `query_open_capacity`
- **参数模板**：

```json
[
  {"tool": "analyze_supply_area", "arguments": {"psrId": "PSR-220-0001", "direction": "outage"}},
  {"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2023-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "query_open_capacity", "arguments": {"stationId": "STA-220-01", "voltageLevel": "10kV", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：拓扑推演的「可能影响」≠ 历史事件中的「实际影响」；历史事件用于校验推演合理性（同一设备历史影响范围是否接近）。
- **输出要点**：推演范围 + 历史佐证 + 差异说明 + 业务复核提示。

## 三、通用注意

1. **主键优先 `psrId`**：拓扑与专题图接口按资源ID 建模；用 `deviceId` 时须说明。
2. **图不作结论**：SVG 只描述结构，不表达运行状态（带电/检修/接地）。
3. **推演必标局限**：停电影响、供电路径均为静态拓扑结果，需注明未考虑转供、保护动作、备自投。
4. **时点值说明**：在线状态、负载、检定状态均为查询时点/最近一次结论。
5. **字段缺失不推断**：接口未返回的关联关系（如装备-被监测设备）应写「未取到」，不推断。
6. **Mock 标注**：所有数据标注「Mock 数据，仅用于联调」。
7. **脱敏**：厂家联系人、电话、地址、重要用户身份脱敏。
