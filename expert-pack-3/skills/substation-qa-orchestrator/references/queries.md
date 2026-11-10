# 问数总控 · 典型问数与串联参数模板

> 本文件是 `substation-qa-orchestrator` 的示例层：给出复合问数的完整串联参数模板与输出骨架。
> 工具名与参数名以 `spec/interfaces.json` 为唯一事实源；当前 `PMS_AUTH_MODE=mock`，示例数据为联调样例。

## 一、单意图直答（不组合）

### 问数 1：这台主变是什么型号、容量多少、投运多久了？

- **路由**：意图① 台账档案 → `substation-asset-ledger`
- **串联参数**：

```json
[
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}}
]
```

- **输出骨架**：结论（1号主变 / 220kV / SSZ11-180000/220 / 180MVA / 2016-05-18 投运）→ 字段表 → 口径（资产侧台账、投运年限按年份差）→ 来源 `get_asset_by_id`（pgp-102-2411-00102）→ 局限（Mock）。

### 问数 2：某站当前有哪些严重、危急缺陷？

- **路由**：意图③ 运维健康 → `substation-om-health`
- **串联参数**：

```json
[
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "defectLevel": "严重", "pageNo": 1, "pageSize": 50}},
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "defectLevel": "危急", "pageNo": 1, "pageSize": 50}}
]
```

- **输出骨架**：结论（1 条严重处理中、0 条危急）→ 等级分组表 → 口径（等级枚举、状态枚举、时间窗）→ 来源 `inquire_defect`（pgp-106-2411-00703）→ 局限。

### 问数 3：能调出这台设备的接线图吗？

- **路由**：意图⑥ 资源拓扑 → `substation-resource-topology`
- **串联参数**：

```json
[
  {"tool": "query_svg_map_by_psr_id", "arguments": {"psrId": "PSR-220-0001"}}
]
```

- **输出骨架**：结论（已取到 220kV 郑州变一次接线图，版本 2026-09-01）→ 图信息表 → 口径（图版本、不含实时状态）→ 来源 `query_svg_map_by_psr_id`（pgp-103-2411-00502）→ 局限（SVG 不作运行状态判断）。

## 二、复合问数（跨域组合）

### 问数 4：给我 1 号主变的健康画像

- **路由**：意图①+③+④+⑤+⑥ → 套路 1「主变健康画像」
- **步骤主键**：`assetId=AST-102-0001`、`psrId=PSR-220-0001`、`stationId=STA-220-01`（来自 `get_psr_by_id` 回填）
- **串联参数**：

```json
[
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
  {"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0001"}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2024-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_fault_trip_records", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2024-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2018-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "get_repair_plan", "arguments": {"deviceId": "PSR-220-0001", "year": 2026, "pageNo": 1, "pageSize": 20}},
  {"tool": "query_open_capacity", "arguments": {"deviceId": "AST-102-0001", "pageNo": 1, "pageSize": 20}},
  {"tool": "search_power_path", "arguments": {"psrId": "PSR-220-0001"}}
]
```

- **输出骨架**：
  1. 结论：健康风险点排序（危急/严重缺陷 → 故障跳闸 → 试验数据趋势 → 负载率）；
  2. 数据表：台账/缺陷/故障/修试/容量五张表；
  3. 口径与时间：时间窗 2024-10-26 至 2026-10-26、可开放容量为时点值、修试数据为摘要文本；
  4. 来源接口：逐项标注 8 个接口编码；
  5. 局限与建议：隐患无设备维度未计入、需专项检查/纳入检修计划、申请量测接口。

### 问数 5：1 号主变停电会影响哪些用户？

- **路由**：意图⑥+⑤ → 套路 2「停电影响分析」
- **串联参数**：

```json
[
  {"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0001"}},
  {"tool": "search_power_path", "arguments": {"psrId": "PSR-220-0001"}},
  {"tool": "analyze_supply_area", "arguments": {"psrId": "PSR-220-0001", "direction": "outage"}},
  {"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2023-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "query_open_capacity", "arguments": {"stationId": "STA-220-01", "voltageLevel": "10kV", "pageNo": 1, "pageSize": 50}}
]
```

- **输出骨架**：影响范围（2 个下级站、城北线 12 个台区、重要用户 2 户）→ 风险等级「较大」→ 历史停电佐证 → 口径（`direction=outage`、静态推演）→ 来源 → 局限（未计转供/保护动作/备自投，需业务复核）。

### 问数 6：这个站今年检修及时率多少？

- **路由**：意图④+③ → 套路 3「检修及时率」
- **串联参数**：

```json
[
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "get_repair_plan", "arguments": {"stationId": "STA-220-01", "year": 2026, "pageNo": 1, "pageSize": 200}},
  {"tool": "get_repair_plan", "arguments": {"stationId": "STA-220-01", "year": 2026, "planStatus": "已完成", "pageNo": 1, "pageSize": 200}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}}
]
```

- **输出骨架**：及时率数值 + 分子分母 → 超期/未完成清单 → 口径（时限依据、分母只计应完成项、计划态 vs 执行态）→ 来源 → 局限（列表接口缺消除时间时以 `view_defect` 补齐或标注缺失）。

### 问数 7：某站运行可靠性概览

- **路由**：意图⑤+③ → 套路 4「站级可靠性概览」
- **串联参数**：

```json
[
  {"tool": "query_station_scale_analysis", "arguments": {"stationId": "STA-220-01", "startDate": "2026-01-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 20}},
  {"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-09-30", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_fault_trip_records", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-09-30", "pageNo": 1, "pageSize": 50}},
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-09-30", "pageNo": 1, "pageSize": 200}},
  {"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 1}}
]
```

- **输出骨架**：指标表（可用率 99.982%、停电 1.42 小时、2 次、时户数 320.5）→ 成因分解（计划/故障）→ 与缺陷故障交叉 → 口径（`statPeriod` 原值、站级可用率口径）→ 来源 → 局限（周期不完整、考核口径不同）。

### 问数 8：这个站设备家底怎么样？（台账 + 资源 + 装备）

- **路由**：意图①+⑥ → 台账 + 资源拓扑
- **串联参数**：

```json
[
  {"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_asset_params", "arguments": {"assetType": "transformer", "stationId": "STA-220-01", "voltageLevel": "220kV", "pageNo": 1, "pageSize": 20}},
  {"tool": "find_smart_device", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_instrument_list", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}}
]
```

- **输出骨架**：设备规模（总台数、类型分布、电压等级分布）→ 主变参数表 → 智能装备与仪表清单 → 口径（设备总数以 `total` 为准）→ 来源 → 局限。

### 问数 9：这台设备的缺陷、检修、停电影响一起看一下（广义画像）

- **路由**：意图③+④+⑥ → 缺陷 + 检修 + 拓扑（简化版画像）
- **串联参数**：

```json
[
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "get_repair_plan", "arguments": {"deviceId": "PSR-220-0001", "year": 2026, "pageNo": 1, "pageSize": 20}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "analyze_supply_area", "arguments": {"psrId": "PSR-220-0001", "direction": "outage"}}
]
```

- **输出骨架**：三段式（健康现状 / 检修安排 / 停电影响）+ 综合判断 → 口径 → 来源 → 局限（停电影响为推演）。

### 问数 10：我问题比较模糊，先帮我理一下能查什么

- **路由**：意图判定失败 → 走澄清话术，不调用工具
- **话术模板**：

> 「我可以按六类帮你查：①设备台账（型号/容量/厂家/投运）②设备定位（站在哪、树节点、站内设备清单）③运维健康（缺陷/隐患/故障跳闸）④检修试验（计划/方案/修试/巡视/试验标准）⑤可靠性（可用率/停电事件/可开放容量/负载率）⑥资源与拓扑（智能装备/仪器/厂家/接线图/电源路径/停电影响）。请给一个设备或一个站，我先给你一版关键指标。」

## 三、输出五段式骨架（可直接套用）

```markdown
> Mock 数据，仅用于联调，不可作为生产结论。

【结论】<一句话结论 + 关键数字>

【数据表】
| 项目 | 取值 | 单位 | 来源接口 |
|---|---|---|---|
| 型号 | SSZ11-180000/220 | — | pgp-102-2411-00102 |
| ... | ... | ... | ... |

【口径与时间】
- 统计周期：2025-10-26 至 2026-10-26（数据截止 2026-10-26）
- 指标口径：站级可用率 `availabilityRate`（非供电可靠率 RS-1）
- 状态口径：缺陷「处理中」按未消除统计
- 单位与精度：容量 MVA；占比保留 1 位小数；时限以本单位规程为准

【来源接口】
- get_asset_by_id（pgp-102-2411-00102）
- inquire_defect（pgp-106-2411-00703）
- …

【局限】
- 隐患数据无设备维度，未计入设备画像
- 可开放容量为模型计算值，接入需专业校核
- 停电影响为静态拓扑推演，需业务复核
- 下一步：如需真实数据，请申请对应接口鉴权
```

## 四、串接检查清单（回答前自检）

1. 主键是否统一？`assetId`/`psrId`/`utcNum`/`deviceId` 是否已写入映射表并一致使用。
2. 时间窗是否写明？请求参数与返回的 `statPeriod` 是否一致。
3. 是否区分了计划态与执行态？
4. 每个数字是否有来源接口编码？
5. 是否标注 Mock？是否有需要业务复核的结论提示？
6. 空结果/失败接口是否在「局限」中说明，而不是静默省略？
7. 敏感字段是否已脱敏？
