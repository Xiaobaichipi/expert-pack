# 检修试验专家 · 典型问数与参数模板

> 本文件是 `substation-maintenance-test` 的细节层。工具名、参数名与枚举值以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，示例数据来自 `spec/interfaces.json` 的 `mock` 字段，回答时须标注「Mock 数据，仅用于联调」。

## 一、参数与状态口径

| 工具 | 时间参数 | 状态枚举 |
|---|---|---|
| `get_repair_plan` | `year`（整数）/`month`（整数） | `planStatus`：待执行 / 执行中 / 已完成 |
| `find_repair_test` | `startTime` / `endTime`（`yyyy-MM-dd`） | — |
| `list_patrol_plan` | `startDate` / `endDate`（`yyyy-MM-dd`） | `status`：未开始 / 执行中 / 已完成 |
| `list_patrol_record` | `startDate` / `endDate`（`yyyy-MM-dd`） | — |
| `find_repair_program` | — | 按 `programId`/`deviceId`/`stationId` 过滤 |
| `list_test_item` | — | 按 `deviceType`/`testType`/`voltageLevel` 过滤 |

> 注意：巡视类用 `startDate`/`endDate`，修试类用 `startTime`/`endTime`，写错参数名会导致过滤失效。

## 二、典型问数（10 条）

### 问数 1：这台设备本年度有没有检修计划？安排在什么时候？

- **工具组合**：`get_repair_plan`
- **参数模板**：

```json
{"tool": "get_repair_plan", "arguments": {"deviceId": "PSR-220-0001", "year": 2026, "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：`planTime` 为计划时间（可能是区间文本，如「2026-10-15 至 2026-10-18」）；`outageArrangement` 为停电安排原文；`status` 为计划状态。
- **输出要点**：计划表 + 结论（有无计划、时间、状态）；无记录时写「未查询到 2026 年检修计划」，可建议扩大年度范围重查。

### 问数 2：某站某月检修计划清单

- **工具组合**：`get_repair_plan`（`stationId` + `year` + `month`）
- **参数模板**：

```json
{"tool": "get_repair_plan", "arguments": {"stationId": "STA-220-01", "year": 2026, "month": 10, "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：`total` 为计划条数；按月过滤依据计划月份字段，跨月计划可能只落在起始月，需在口径中说明。
- **输出要点**：按月计划表 + 状态分布（待执行/执行中/已完成）+ 总量。

### 问数 3：这次检修的方案和作业内容是什么？

- **工具组合**：`find_repair_program`
- **参数模板**：

```json
{"tool": "find_repair_program", "arguments": {"programId": "PG-2026-0001", "pageNo": 1, "pageSize": 10}}
```

- **字段口径**：`workContent` 为作业内容、`safetyMeasures` 为安全措施、`personnel` 为人员安排；三者均为原文字段，输出时保留原文不摘要改写。
- **输出要点**：方案卡片（名称 | 作业内容 | 安全措施 | 人员）；提示作业前须履行工作票/操作票流程。

### 问数 4：这台设备的历次修试历史与试验数据？

- **工具组合**：`find_repair_test`
- **参数模板**：

```json
{"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2020-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：`testType` 为试验类型（如预防性试验/例行试验）；`testDate` 为实际试验日期（执行态）；`result` 为结论（合格/不合格）；`dataSummary` 为数据摘要文本（非结构化验测值）。
- **输出要点**：按时间排序的修试表 + 趋势提示（如「绝缘电阻 2023 年 15000MΩ → 2025 年 12000MΩ，需关注下降趋势」），注明摘要文本非原始量测。

### 问数 5：本季度该站的巡视计划/工单有哪些？

- **工具组合**：`list_patrol_plan`
- **参数模板**：

```json
{"tool": "list_patrol_plan", "arguments": {"stationId": "STA-220-01", "startDate": "2026-10-01", "endDate": "2026-12-31", "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：`frequency` 为巡视频次（如每月一次）；`executor` 为执行班组/人；`startDate`/`endDate` 为计划起止（计划态）。
- **输出要点**：计划表 + 状态；说明「计划起止」不是实际执行时间。

### 问数 6：该站最近一次巡视是什么时候、结果如何？

- **工具组合**：`list_patrol_record`
- **参数模板**：

```json
{"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-01-01", "endDate": "2026-10-26", "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：`patrolTime` 为实际巡视时间（可能是区间文本）；`result` 为结果摘要（如「发现异常 2 项」）；`abnormalities` 为异常清单，可与缺陷记录交叉核对。
- **输出要点**：最近巡视时间 + 类型 + 结果 + 异常项；异常项建议转 `substation-om-health` 核对是否已登记缺陷。

### 问数 7：巡视到位率如何计算？（某站某月）

- **工具组合**：`list_patrol_plan` + `list_patrol_record`
- **参数模板**：

```json
[
  {"tool": "list_patrol_plan", "arguments": {"stationId": "STA-220-01", "startDate": "2026-09-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-09-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 100}}
]
```

- **字段口径**：巡视到位率 = 实际完成的巡视次数 ÷ 计划巡视次数 × 100%；计划取 `list_patrol_plan` 中该月应执行的计划条数，实际取 `list_patrol_record` 中该月记录条数；两者按站与月份对齐。
- **输出要点**：计划数、实际数、到位率（1 位小数）；说明按条数近似、未按巡视点位细化，因此「到位率」为工单级口径。

### 问数 8：检修计划完成率 / 检修及时率口径

- **工具组合**：`get_repair_plan`（`planStatus`）+ `find_repair_test`（实际执行）+ `substation-om-health` 的缺陷记录（及时率分母）
- **参数模板**：

```json
[
  {"tool": "get_repair_plan", "arguments": {"stationId": "STA-220-01", "year": 2026, "pageNo": 1, "pageSize": 200}},
  {"tool": "get_repair_plan", "arguments": {"stationId": "STA-220-01", "year": 2026, "planStatus": "已完成", "pageNo": 1, "pageSize": 200}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：
  - 检修计划完成率 = 已完成计划数 ÷ 应完成计划数 × 100%（分母为截至统计日应执行完的计划，不含尚未到期计划）；
  - 检修及时率 = 按时完成（或按时消缺）项数 ÷ 应完成项数 × 100%，及时判据以规程时限为准（如危急缺陷 24 小时，**以本单位规程为准**）；
  - 「已完成」以 `planStatus` 为计划态口径，实际完成须用修试记录交叉验证。
- **输出要点**：分子/分母/比例 + 计划态与执行态的差异说明。

### 问数 9：变压器预防性试验要做哪些项目、依据什么标准？

- **工具组合**：`list_test_item`
- **参数模板**：

```json
{"tool": "list_test_item", "arguments": {"deviceType": "变压器", "testType": "预防性试验", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：`standard` 为标准号（如 DL/T 596-2021），`requirement` 为合格要求原文；两者按接口返回引用，接口未返回时写「未取到标准依据」。
- **输出要点**：项目表（项目 | 适用设备 | 试验类型 | 标准 | 合格要求）；提示具体执行以现行有效版本标准及本单位规程为准。

### 问数 10：设备超期未修试识别

- **工具组合**：`find_repair_test`（最近一次试验）+ `list_test_item`（周期要求）+ `get_asset_by_id`（投运日期）
- **参数模板**：

```json
[
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2018-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_test_item", "arguments": {"deviceType": "变压器", "testType": "预防性试验", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}}
]
```

- **字段口径**：超期 = 当前日期 − 最近一次 `testDate` > 规程要求周期；试验周期字段在 `list_test_item` 中可能未直接给出，需按 `standard`/`requirement` 文本或本单位规程判定，判定依据必须写明。
- **输出要点**：超期清单 + 距上次试验时长 + 判定依据；无法自动判定时标注「需人工确认周期」。

## 三、通用注意

1. **计划态与执行态分离**：`get_repair_plan` 给计划，`find_repair_test` 给实际，结论必须成对引用。
2. **参数名别混**：`startDate`/`endDate`（巡视） vs `startTime`/`endTime`（修试、缺陷、故障）。
3. **时间窗必写**：年度/季度/月份换算成具体日期并在口径中说明。
4. **标准引用可核**：引用 `standard`/`requirement` 原文，标准版本随文标注。
5. **空结果不推论**：无计划/无修试记录时只写「未查询到」，不推断「无需检修」或「设备状态良好」。
6. **Mock 标注**：所有数据标注「Mock 数据，仅用于联调」。
7. **脱敏**：作业人员保留姓氏，联系方式脱敏；方案中的具体作业风险点可保留。
