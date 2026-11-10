# 可靠性分析专家 · 典型问数与参数模板

> 本文件是 `substation-reliability` 的细节层。工具名与参数名以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，示例数据来自 `spec/interfaces.json` 的 `mock` 字段，回答时须标注「Mock 数据，仅用于联调」。

## 一、指标字段口径

| 字段 | 所属工具 | 含义 | 单位/精度 | 注意 |
|---|---|---|---|---|
| `availabilityRate` | `query_station_scale_analysis` | 站级可用率 | %，保留 3 位小数 | 与供电可靠率 RS-1/RS-3 口径不同，引用须注明来源字段 |
| `outageHours` | `query_station_scale_analysis` | 累计停电小时数 | 小时 | 统计周期内合计 |
| `outageUserHours` | `query_station_scale_analysis` | 停电时户数 | 时·户 | 反映影响广度，与停电时长不是同一指标 |
| `outageCount` | `query_station_scale_analysis` | 停电次数 | 次 | 与事件列表条数可能不一致，以指标接口为准并说明 |
| `statPeriod` | `query_station_scale_analysis` | 统计周期 | 文本 | 以返回值为准，不要用请求参数替代 |
| `outageStart`/`outageEnd` | `query_outage_incident` | 停电起止时间 | `yyyy-MM-dd HH:mm` | 时长 = 结束 − 开始 |
| `scope` / `cause` | `query_outage_incident` | 影响范围 / 停电原因 | 文本 | 原因分为计划检修、故障等 |
| `ratedCapacityMVA` | `query_open_capacity` | 额定容量 | MVA | 与台账 `capacityMVA` 应一致，不一致时并列说明 |
| `currentLoadMVA` | `query_open_capacity` | 当前负载 | MVA | 数据时点值，非全年峰值 |
| `openCapacityMVA` | `query_open_capacity` | 可开放容量 | MVA | 理论值 = 额定容量 − 已占用/受限容量，具体规则由分析模型决定 |
| `loadRate` | `query_open_capacity` | 负载率 | %，1 位小数 | = 当前负载 ÷ 额定容量 × 100% |

## 二、典型问数（8 条）

### 问数 1：这个站的供电可靠率是多少？可靠性指标如何？

- **工具组合**：`query_station_scale_analysis`
- **参数模板**：

```json
{"tool": "query_station_scale_analysis", "arguments": {"stationId": "STA-220-01", "startDate": "2026-01-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：返回 `availabilityRate=99.982` 读作「站级可用率 99.982%」，不要直接称「供电可靠率」；`outageCount` 与 `query_outage_incident` 条数不一致时，以指标接口为统计口径并说明差异原因（事件过滤条件不同）。
- **输出要点**：指标表 + 一句话结论；写明统计周期原值（如「2026-01 至 2026-09」）。

### 问数 2：最近有哪些停电事件？影响范围多大？

- **工具组合**：`query_outage_incident`
- **参数模板**：

```json
{"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：`voltageLevel` 过滤为电压等级（该接口定位为「中压停电事件」，220kV 站可能返回空结果，需说明口径边界）；`scope` 为影响范围文本（台区数、用户类别）；停电时长逐条计算。
- **输出要点**：事件表（起止 | 时长 | 范围 | 原因 | 电压等级）+ 合计时长 + 按原因分组。

### 问数 3：这台主变还有多少可开放容量？当前负载多大？

- **工具组合**：`query_open_capacity`
- **参数模板**：

```json
{"tool": "query_open_capacity", "arguments": {"deviceId": "AST-102-0001", "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：`deviceId` 建议传资产ID（示例 mock 的 `deviceId` 为 `AST-102-0001`），与资源ID 混用可能查不到；可开放容量与负载率需自洽校验：`currentLoadMVA / ratedCapacityMVA ≈ loadRate`，不自洽时提示数据异常。
- **输出要点**：容量表 + 结论（可开放容量 54MVA、负载率 70%）；说明为数据时点值。

### 问数 4：站内哪些主变负载率偏高？

- **工具组合**：`query_open_capacity`（`stationId` + `voltageLevel`）
- **参数模板**：

```json
{"tool": "query_open_capacity", "arguments": {"stationId": "STA-220-01", "voltageLevel": "220kV", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：负载率阈值（如 80% 重载、100% 过载）**以本单位运行规程为准**，不得自行认定为「重载设备」；按 `loadRate` 降序排列。
- **输出要点**：降序表 + 阈值说明 + 裕度最小设备提示。

### 问数 5：近一年停电次数与累计时长统计

- **工具组合**：`query_station_scale_analysis` + `query_outage_incident`
- **参数模板**：

```json
[
  {"tool": "query_station_scale_analysis", "arguments": {"stationId": "STA-220-01", "startDate": "2025-10-26", "endDate": "2026-10-26", "pageNo": 1, "pageSize": 20}},
  {"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}}
]
```

- **字段口径**：指标侧 `outageCount`/`outageHours` 与事件侧逐条累加值应做一致性核对；差异超过 10% 时在局限中说明并建议以可靠性指标接口为准。
- **输出要点**：两口径对照表 + 差异说明。

### 问数 6：停电主要是计划检修还是故障？原因分布如何？

- **工具组合**：`query_outage_incident`（按 `cause` 分组）
- **参数模板**：

```json
{"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}}
```

- **字段口径**：`cause` 为文本原因（计划检修/故障/外力等），统计前需归类；计划停电与故障停电对可靠性指标的影响不同，需分开统计。
- **输出要点**：原因分布表（原因 | 次数 | 时长 | 占比）；占比分母为该周期事件总条数。

### 问数 7：两个站/两个周期可靠性对比

- **工具组合**：`query_station_scale_analysis`（按站或按周期多次调用）
- **参数模板**：

```json
[
  {"tool": "query_station_scale_analysis", "arguments": {"stationId": "STA-220-01", "startDate": "2025-01-01", "endDate": "2025-12-31", "pageNo": 1, "pageSize": 20}},
  {"tool": "query_station_scale_analysis", "arguments": {"stationId": "STA-220-01", "startDate": "2026-01-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 20}}
]
```

- **字段口径**：周期不等长（12 个月 vs 9 个月）时，必须年化或按期折算后再比较，或明确标注「周期不等长，仅供趋势参考」；不同站的电压等级/规模差异需说明，不得直接下「谁更可靠」的绝对结论。
- **输出要点**：对比表 + 折算口径 + 结论限定语。

### 问数 8：这台设备停电会影响哪些用户/设备？（跨技能）

- **工具组合**：本技能 `query_open_capacity`（受影响设备容量）+ `substation-resource-topology` 的 `analyze_supply_area`（影响范围）+ `query_outage_incident`（历史同类事件影响）
- **参数模板**：

```json
[
  {"tool": "analyze_supply_area", "arguments": {"psrId": "PSR-220-0001", "direction": "outage"}},
  {"tool": "query_open_capacity", "arguments": {"stationId": "STA-220-01", "voltageLevel": "10kV", "pageNo": 1, "pageSize": 50}},
  {"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2023-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}}
]
```

- **字段口径**：拓扑侧给「可能受影响范围」，可靠性侧给「历史实际影响」，两者不能等同；影响用户数/台区数以拓扑返回为准并标注为推演结果。
- **输出要点**：影响范围表 + 历史同类事件佐证 + 「停电影响需业务复核」提示。

## 三、通用注意

1. **周期先对齐**：请求周期、返回 `statPeriod`、数据截止时间三者都要写进口径。
2. **口径不混用**：`availabilityRate`（站级可用率）≠ 供电可靠率 RS-1/RS-3；引用务必附字段名。
3. **单位不省略**：%、小时、时·户、MVA 必须带单位。
4. **精度不虚高**：接口返回 99.982 就写 99.982%，不要写成 100%；容量保留接口精度。
5. **空结果不推论**：`total=0` 写「该周期内未查询到停电事件」，不写「零停电」。
6. **Mock 标注**：所有数据标注「Mock 数据，仅用于联调，不可用于考核/对外报送」。
7. **脱敏**：影响用户、台区名称、重要用户身份按需脱敏。
