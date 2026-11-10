# 健康评估专家 · 典型问数与调用模板

> 本文件是 `substation-health-assessment` 的细节层：每个任务给出「用户问法 → 数据 MCP 取数 → bundle 组装 → 分析 MCP 调用 → 输出要点」。
> 工具名/参数名以 `spec/interfaces.json`（26 数据工具）与 `spec/analysis-tools.json`（7 分析工具）为准；bundle 字段以 `spec/analysis-bundle.schema.json` 为准。
> 当前 `PMS_AUTH_MODE=mock`，示例数据取自各接口的 `mock` 字段，输出须标注「Mock 数据，仅用于联调」。

## 通用组装映射（所有问数复用）

| 接口返回字段 | bundle 字段 | 说明 |
|---|---|---|
| `get_asset_by_id.data`（`assetName/assetStatus/psrId`） | `device{name,status,psrId,...}` | 字段名对齐 schema，值不改写 |
| `inquire_defect.list[].defectLevel` | `defects[].level` | 枚举 危急/严重/一般 原样 |
| `inquire_defect.list[].defectDesc` | `defects[].desc` | 无此字段则用 `part` 摘要，不臆造描述 |
| `inquire_defect.list[].discoverTime` | `defects[].discoverTime` | 时间格式保持 `yyyy-MM-dd HH:mm`；不手工改写时区 |
| `list_fault_trip_records.list[].faultTime` | `faults[].time` | 另带 `protectionAction`、`cause` |
| `find_repair_test.list[].testDate/result` | `tests[].testDate/result` | `result` 只允许 合格/不合格/异常 |
| `query_open_capacity.list[0]` | `load{}` | 四个数值字段直搬 |
| 每次调用 | `sourceMeta[]` | 必写 `interfaceCode` + `tool` + `calledAt` + `params` |

---

## 问数 1：给 1 号主变做个健康评估，多少分、什么级？

**取数**

```json
[
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_hazard", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_fault_trip_records", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2023-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "query_open_capacity", "arguments": {"deviceId": "AST-102-0001", "pageNo": 1, "pageSize": 20}}
]
```

**bundle 组装**：`device` 由 `get_asset_by_id` → `defects[]` 由问数 2 的映射 → `faults[]` → `tests[]` → `load{}`；`timeWindow{start:"2025-10-26", end:"2026-10-26"}`；`sourceMeta` 记 6 条接口编码。

**分析调用**

```json
{"tool": "assess_device_health", "arguments": {"bundle": {"device": {"psrId": "PSR-220-0001", "assetId": "AST-102-0001", "name": "1号主变", "stationId": "STA-220-01", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV", "deviceType": "变压器", "model": "SSZ11-180000/220", "manufacturer": "特变电工", "commissioningDate": "2016-05-18", "capacityMVA": 180, "status": "在运"}, "timeWindow": {"start": "2025-10-26", "end": "2026-10-26"}, "defects": [{"defectId": "DF-2026-0001", "defectNo": "QXB-2026-0001", "level": "严重", "status": "处理中", "discoverTime": "2026-09-12 10:22", "part": "本体/套管", "desc": "本体套管油位偏低，存在渗油痕迹"}], "tests": [{"recordId": "RT-2025-0001", "testType": "预防性试验", "testDate": "2025-04-11", "result": "合格", "dataSummary": "绕组直流电阻不平衡率 0.8%，绝缘电阻 12000MΩ"}], "load": {"ratedCapacityMVA": 180, "currentLoadMVA": 126, "openCapacityMVA": 54, "loadRate": 70.0}}, "scorecard_profile": "default"}}
```

**输出要点**：一句话结论（分数 + 等级 + 风险）→ 维度表 → 扣分证据链 → 置信度/缺口 → 建议；等级与分数同时给出，不单报分数。

---

## 问数 2：这台设备为什么是 C 级、扣在哪？

**取数**：复用问数 1 的取数结果；需要过程细节时补 `view_defect` 与 `list_patrol_record`。

```json
[
  {"tool": "view_defect", "arguments": {"defectId": "DF-2026-0001"}},
  {"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-07-01", "endDate": "2026-10-26", "pageNo": 1, "pageSize": 50}}
]
```

**分析调用**：重新组装 bundle（补 `defects[].closeTime/desc`、`patrolRecords[]`）后**重跑** `assess_device_health`，profile 保持不变。

**输出要点**：按 `deductions[]` 逐条讲「哪条规则、扣多少、依据哪条记录、来源哪个接口」；维度层给「缺陷维度得分最低（xx/100）」；不新增引擎未返回的扣分原因；若主要扣分来自数据缺失（台账维度），要点明「补台账字段即可回升，非设备本体问题」。

---

## 问数 3：本站哪几台设备最不健康？给 Top5

**取数**

```json
[
  {"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "list_fault_trip_records", "arguments": {"stationId": "STA-220-01", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "query_station_scale_analysis", "arguments": {"stationId": "STA-220-01", "startDate": "2026-01-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 20}}
]
```

**bundle 组装**：按设备拆包——用 `list_psr_by_filters.list[]` 的 `psrId` 建骨架，把站级 `inquire_defect` 结果按 `deviceName` 归并到各 bundle 的 `defects[]`，故障同理；站级可靠性 `reliability{}` 只放站级汇总包（不作为单设备证据）。

**分析调用**

```json
{"tool": "assess_station_health", "arguments": {"bundles": [{"device": {"psrId": "PSR-220-0001", "name": "1号主变", "stationId": "STA-220-01", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV", "deviceType": "变压器"}}, {"device": {"psrId": "PSR-220-0101", "name": "2201断路器", "stationId": "STA-220-01", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV", "deviceType": "断路器"}}], "station_meta": {"stationId": "STA-220-01", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV"}, "scorecard_profile": "default", "top_n": 5}}
```

**输出要点**：等级分布（A/B/C/D/E 各 n 台）→ `aggregate.avgScore` → `riskTop` 清单（设备名、分数、等级、主因）→ 说明纳入台数与 `total` 的关系（未评分设备要列出原因）。

---

## 问数 4：同型号主变健康度横向对比（家族设备）

**取数**

```json
[
  {"tool": "list_asset_params", "arguments": {"assetType": "transformer", "stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0002", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "get_manufacturer_infos", "arguments": {"manufacturerName": "特变电工", "pageNo": 1, "pageSize": 50}}
]
```

**bundle 组装**：`list_asset_params.list[]` 提供 `model/manufacturer/capacityMVA`（同型号筛选条件 = `model` + `manufacturer`）；每台设备各建一个 bundle，**`defects` 必须单设备查询**，不得用站级结果平摊。

**分析调用**：逐台 `assess_device_health`，或直接 `assess_station_health`（`bundles` 只放同型号设备，`station_meta` 可省，`top_n` 取全部台数）。

**输出要点**：横向对比表（设备 | 分数 | 等级 | 主因维度）；指出「同型号共同扣分维度」作为家族性风险线索，并可提示「是否需 `substation-diagnosis` 做家族缺陷识别」——但**本技能不下家族缺陷结论**。

---

## 问数 5：这台主变的缺陷率、超期未消缺、负载率、可开放容量比分别是多少？

**取数**

```json
[
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "get_repair_plan", "arguments": {"deviceId": "PSR-220-0001", "year": 2026, "pageNo": 1, "pageSize": 50}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2023-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "query_open_capacity", "arguments": {"deviceId": "AST-102-0001", "pageNo": 1, "pageSize": 20}}
]
```

**分析调用**

```json
{"tool": "compute_device_metrics", "arguments": {"bundle": {"device": {"psrId": "PSR-220-0001", "name": "1号主变", "capacityMVA": 180}, "timeWindow": {"start": "2025-10-26", "end": "2026-10-26"}, "defects": [{"level": "危急", "status": "处理中", "discoverTime": "2026-09-01 08:00", "part": "本体"}], "faults": [], "tests": [{"recordId": "RT-2025-0001", "testDate": "2025-04-11", "result": "合格"}], "repairPlans": [{"planId": "RP-2026-0001", "status": "待执行"}], "load": {"ratedCapacityMVA": 180, "currentLoadMVA": 126, "openCapacityMVA": 54, "loadRate": 70.0}}}}
```

**输出要点**：指标表（指标 | 值 | 分母 | 口径）；`denominators` 必须展示（缺陷率分母、计划应完成数等）；`dataGaps` 非空时对相应指标写「数据不足，未计算」，**不得用 0 或均值代替**；`trend` 为 null 时说明「样本周期不足，趋势延后」。

---

## 问数 6：给这个站做一次月度设备体检（月报前置）

**取数**：问数 3 的全站取数 + 巡视/检修域。

```json
[
  {"tool": "list_patrol_plan", "arguments": {"stationId": "STA-220-01", "startDate": "2026-09-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-09-01", "endDate": "2026-09-30", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_repair_plan", "arguments": {"stationId": "STA-220-01", "year": 2026, "month": 9, "pageNo": 1, "pageSize": 50}},
  {"tool": "query_outage_incident", "arguments": {"stationId": "STA-220-01", "startTime": "2026-09-01", "endTime": "2026-09-30", "pageNo": 1, "pageSize": 50}}
]
```

**分析调用**：`assess_station_health`（全站 bundles）→ 需要指标时对重点设备追加 `compute_device_metrics`。

**输出要点**：这是 `substation-report` 的 `station_monthly` 前置步骤，交付结构为「站级评分摘要 + 设备分项表 + 风险清单 + 指标表 + 数据质量」；报告生成交报告技能，本步骤不渲染模板。

---

## 问数 7：数据不全时如何评估（只有台账 + 缺陷）

**取数**

```json
[
  {"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0001"}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}}
]
```

**分析调用**：仍调用 `assess_device_health`（引擎会自行计算完备度与置信度），**不得因为数据少就跳过工具**。

**输出要点**：先声明「本次仅取到台账与缺陷两类数据，完备度 2/5」，再给「按现有数据评分 xx 分（置信度 0.xx，偏低）」；明确写出「不作为考核/停电决策依据」；输出补数清单：

| 缺什么 | 对应工具 | 接口编码 |
|---|---|---|
| 故障跳闸记录 | `list_fault_trip_records` | pgp-106-2411-02603 |
| 修试记录 | `find_repair_test` | pgp-106-2411-05003 |
| 负载与可开放容量 | `query_open_capacity` | pgp-108-2411-00201 |

---

## 问数 8：补齐数据后重新出一版评估

**流程**：按问数 7 的补数清单取数 → 组装新版 bundle（保留旧 `sourceMeta` 并追加新条目与 `calledAt`）→ **重跑 `assess_device_health`** → 对比两版差异。

```json
[
  {"tool": "list_fault_trip_records", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2023-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "query_open_capacity", "arguments": {"deviceId": "AST-102-0001", "pageNo": 1, "pageSize": 20}}
]
```

**输出要点**：写成「v1（完备度 2/5，置信度 0.60）→ v2（完备度 5/5，置信度 0.90）；分数由 A 变为 B，差异来自新增故障记录 1 次」；**禁止手工改分**，两版结果都必须是工具输出。

## 通用注意

1. 取数先定主键：统一用 `psrId`，`query_open_capacity`/`get_asset_by_id` 需 `assetId` 时显式说明换键。
2. 时间窗必须写进 bundle `timeWindow`，回答中同步标注。
3. 分页看 `total`：样本未取全时在 `sourceMeta` 标注「已截断/总数」。
4. 分析结果只解读不改写；`summary` 可引用，`grade/score` 不可换算。
5. Mock 数据必须标注；涉及考核、停电、检修的结论必须提示业务复核。
