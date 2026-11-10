# 诊断专家 · 典型诊断任务模板

> 本文件是 `substation-diagnosis` 的细节层：每个任务给出「用户任务 → 数据 MCP 跨域取数 → bundle 组装 → 分析 MCP 调用 → 输出要点」。
> 工具名/参数名以 `spec/interfaces.json`（26 数据工具）与 `spec/analysis-tools.json`（7 分析工具）为准；bundle 字段以 `spec/analysis-bundle.schema.json` 为准。
> 当前 `PMS_AUTH_MODE=mock`，示例取自各接口 `mock` 字段，输出须标注「Mock 数据，仅用于联调」。

## 通用要点

| 要点 | 说明 |
|---|---|
| 证据域要全 | 台账 + 故障 + 缺陷 + 修试 + 巡视 + 负载；缺域直接降低 `confidence` |
| 时间窗 | 覆盖「事件前 12 个月 + 事件本身」；重复/家族识别另给 `window_days` |
| 记录字段不改写 | `cause`、`desc`、`part`、`abnormalities` 原文带入，否则规则关键词匹配会偏 |
| 证据可溯 | `sourceMeta[]` 必须含 `interfaceCode` + `tool` + `calledAt` + `params` |
| 结果只解读 | `hypotheses` 顺序、`score`、`confidence`、`patterns` 不得改写 |

---

## 任务 1：1 号主变这次跳闸最可能是什么原因？

**取数（跨域证据）**

```json
[
  {"tool": "list_fault_trip_records", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2023-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-07-01", "endDate": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "query_open_capacity", "arguments": {"deviceId": "AST-102-0001", "pageNo": 1, "pageSize": 20}},
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}}
]
```

**bundle 组装**：`device`（台账）+ `faults[]`（`faultTime→time`）+ `defects[]`（`defectLevel→level`、`defectDesc→desc`）+ `tests[]` + `patrolRecords[]` + `load{}`；`timeWindow` 写 2025-10-26～2026-10-26。

**分析调用**

```json
{"tool": "diagnose_equipment", "arguments": {"bundle": {"device": {"psrId": "PSR-220-0001", "assetId": "AST-102-0001", "name": "1号主变", "stationId": "STA-220-01", "voltageLevel": "220kV", "deviceType": "变压器", "model": "SSZ11-180000/220", "manufacturer": "特变电工", "commissioningDate": "2016-05-18", "capacityMVA": 180}, "timeWindow": {"start": "2025-10-26", "end": "2026-10-26"}, "faults": [{"faultId": "FT-2026-0001", "time": "2026-08-03 02:17", "protectionAction": "差动保护动作", "cause": "套管绝缘受潮"}], "defects": [{"defectId": "DF-2026-0001", "level": "严重", "status": "处理中", "discoverTime": "2026-09-12 10:22", "part": "本体/套管", "desc": "本体套管油位偏低，存在渗油痕迹"}], "tests": [{"recordId": "RT-2025-0001", "testType": "预防性试验", "testDate": "2025-04-11", "result": "合格", "dataSummary": "绕组直流电阻不平衡率 0.8%，绝缘电阻 12000MΩ"}], "load": {"ratedCapacityMVA": 180, "currentLoadMVA": 126, "openCapacityMVA": 54, "loadRate": 70.0}}, "max_hypotheses": 5}}
```

**输出要点**：假设排序表（假设 | 匹配度 | 置信度 | 关键证据）→ 证据链三段式 → `missingEvidence` 转核查清单（如缺介损/油色谱）→ 与记录 `cause` 是否一致 → 复核提示。

---

## 任务 2：套管渗油反复出现，是不是重复缺陷？

**取数**

```json
[
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2024-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "view_defect", "arguments": {"defectId": "DF-2026-0001"}},
  {"tool": "get_repair_plan", "arguments": {"deviceId": "PSR-220-0001", "year": 2026, "pageNo": 1, "pageSize": 50}}
]
```

**分析调用（单设备聚类）**

```json
{"tool": "detect_defect_patterns", "arguments": {"defects": [{"defectId": "DF-2026-0001", "level": "严重", "status": "处理中", "discoverTime": "2026-09-12 10:22", "part": "本体/套管", "desc": "本体套管油位偏低，存在渗油痕迹"}, {"defectId": "DF-2025-0031", "level": "一般", "status": "已消除", "discoverTime": "2025-11-03 09:10", "part": "本体/套管", "desc": "套管渗油"}], "device_meta": {"deviceType": "变压器", "model": "SSZ11-180000/220", "manufacturer": "特变电工", "commissioningDate": "2016-05-18"}, "window_days": 365, "family_min_count": 3}}
```

**输出要点**：给「部位 + 次数 + 时间跨度 + 等级分布」；如命中 `duplicateClusters`，再调 `diagnose_equipment` 看机制性假设；结论写成「同一薄弱点未根治，建议核查上次消缺质量与验收」，不写「设备必须更换」。

---

## 任务 3：同型号主变是否有家族性缺陷？

**取数（先取同型号设备，再逐台取缺陷）**

```json
[
  {"tool": "list_asset_params", "arguments": {"assetType": "transformer", "stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2024-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0002", "startTime": "2024-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "get_manufacturer_infos", "arguments": {"manufacturerName": "特变电工", "pageNo": 1, "pageSize": 50}}
]
```

**分析调用**

```json
{"tool": "detect_defect_patterns", "arguments": {"defects": [{"deviceName": "1号主变", "defectId": "DF-2026-0001", "level": "严重", "status": "处理中", "discoverTime": "2026-09-12 10:22", "part": "本体/套管"}, {"deviceName": "2号主变", "defectId": "DF-2026-0007", "level": "一般", "status": "已消除", "discoverTime": "2026-03-08 14:05", "part": "本体/套管"}, {"deviceName": "3号主变", "defectId": "DF-2025-0019", "level": "一般", "status": "已消除", "discoverTime": "2025-12-20 11:30", "part": "本体/套管"}], "device_meta": {"deviceType": "变压器", "model": "SSZ11-180000/220", "manufacturer": "特变电工"}, "window_days": 730, "family_min_count": 3}}
```

**输出要点**：`familyClusters` 的「型号/厂家 + 部位 + 台数 + 设备名」；口径写明「近 730 天、同部位 ≥3 台」；建议「联系厂家、排查同批次投运设备」；明确「不等于全部设备已故障」。

---

## 任务 4：2201 断路器机构箱受潮拒动诊断

**取数**

```json
[
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0101", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_fault_trip_records", "arguments": {"deviceId": "PSR-220-0101", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0101", "startTime": "2023-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-07-01", "endDate": "2026-10-26", "pageNo": 1, "pageSize": 50}}
]
```

**分析调用**：`diagnose_equipment`，bundle 中 `defects[]` 带 `part:"机构箱"`、`desc:"机构箱受潮"`，`faults[].protectionAction` 原文带入（如「拒动」），并附 `tests[]` 的回路电阻/绝缘数据摘要。

**输出要点**：机构箱受潮类假设的匹配度与置信度；核查清单偏向「加热除湿装置、二次回路绝缘、密封与封堵」；如证据仅来自巡视异常、无试验数据，必须写「置信度偏低，待补回路绝缘试验」。

---

## 任务 5：证据不足时能定到什么程度？

**取数（最少域）**

```json
[
  {"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0101"}},
  {"tool": "list_fault_trip_records", "arguments": {"stationId": "STA-220-01", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}}
]
```

**分析调用**：仍调用 `diagnose_equipment`（bundle 仅含 `device` + `faults`），不得因数据少而跳过工具或自己拍原因。

**输出要点**：先写「证据仅 2 类，`dataGaps` 列出缺失域」→ 再给低置信度方向 → 最后给补证据清单：

| 缺什么 | 对应工具 | 接口编码 |
|---|---|---|
| 缺陷记录 | `inquire_defect` | pgp-106-2411-00703 |
| 修试/试验数据 | `find_repair_test` | pgp-106-2411-05003 |
| 巡视异常 | `list_patrol_record` | pgp-106-2411-00403 |
| 负载与容量 | `query_open_capacity` | pgp-108-2411-00201 |

---

## 任务 6：补数据后重新诊断

**流程**：按任务 5 清单取数 → 新版 bundle（旧 `sourceMeta` 保留 + 追加新条目与 `calledAt`）→ **重跑 `diagnose_equipment`** → 对比两版假设排序与置信度变化。

```json
[
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0101", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "find_repair_test", "arguments": {"deviceId": "PSR-220-0101", "startTime": "2023-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_patrol_record", "arguments": {"stationId": "STA-220-01", "startDate": "2026-07-01", "endDate": "2026-10-26", "pageNo": 1, "pageSize": 50}}
]
```

**输出要点**：写「v1（证据 2 类，Top1 置信度 0.35）→ v2（证据 5 类，Top1 置信度 0.72）」，并说明新增哪条证据改变了排序；**禁止手工上调置信度或改写假设顺序**。

---

## 任务 7：故障复盘中的根因与建议章节（交接报告技能）

**前序**：任务 1 的诊断结果 + 任务 2/3 的模式识别结果。

**交接方式**：把 `hypotheses[]`（`name`/`score`/`confidence`）、证据表、`missingEvidence[]`、`suggestions[]` 作为 `payload` 的一部份交 `substation-report` 的 `generate_report`（`report_type: "fault_review"`）；`payload` 具体键名以 `list_report_types` 返回的 `requiredPayloadKeys` 为准。

```json
{"tool": "generate_report", "arguments": {"report_type": "fault_review", "title": "1号主变 2026-08-03 差动保护动作故障复盘", "payload": {"device": {"psrId": "PSR-220-0001", "name": "1号主变", "voltageLevel": "220kV", "deviceType": "变压器"}, "faults": [{"faultId": "FT-2026-0001", "time": "2026-08-03 02:17", "protectionAction": "差动保护动作", "cause": "套管绝缘受潮"}], "diagnosis": {"hypotheses": [{"ruleId": "<引擎返回的 ruleId>", "name": "套管受潮", "score": 0.78, "confidence": 0.68, "evidence": ["差动保护动作", "套管渗油严重缺陷处理中"], "suggestions": ["补做介损与油色谱试验", "核查套管密封与油位"]}], "missingEvidence": ["最近一次介损试验分项数据", "油色谱分析报告"], "dataGaps": []}}}}
```

**输出要点**：本技能只负责诊断部分的准确性（假设、证据、缺口），章节结构与排版由报告技能保证；报告中凡出现诊断结论，必须带置信度与「需复核」提示。

## 通用注意

1. 假设只解读不重排；`score` 称「匹配度」，不换算成概率。
2. 低置信度（<0.55）不得定性；必须同段给补证据方案。
3. 重复/家族簇必须写明 `window_days`、`family_min_count` 口径。
4. `cause` 等记录字段与诊断结果不一致时并列展示，不互相覆盖。
5. Mock 数据标注；责任认定类表述一律禁止，改为「建议复核」。
