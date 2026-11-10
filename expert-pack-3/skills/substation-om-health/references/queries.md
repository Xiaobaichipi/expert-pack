# 运维健康专家 · 典型问数与参数模板

> 本文件是 `substation-om-health` 的细节层。工具名、参数名与枚举值以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，示例数据来自 `spec/interfaces.json` 的 `mock` 字段，回答时须标注「Mock 数据，仅用于联调」。

## 一、枚举与状态口径

| 维度 | 取值 | 说明 |
|---|---|---|
| 缺陷等级 `defectLevel` | 危急 / 严重 / 一般 | 业务时限：危急缺陷一般要求 24 小时内消除、严重缺陷按周、一般缺陷按计划安排，**具体时限以本单位缺陷管理规程为准** |
| 缺陷状态 `status` | 待处理 / 处理中 / 已消除 | 「未消除」= 待处理 + 处理中；不得把「待处理」直接表述为「超期」 |
| 隐患类型 `hazardType` | 内部 / 外部 | 外部多为周边环境、施工外破等 |
| 隐患风险 `riskLevel` | 重大 / 较大 / 一般 | 与缺陷等级不是同一套体系 |
| 隐患状态 `status` | 未整改 / 整改中 / 已闭环 | 「未闭环」= 未整改 + 整改中 |

## 二、典型问数（9 条）

### 问数 1：某站当前有哪些严重、危急缺陷？

- **工具组合**：`inquire_defect`（按等级分别查，或一次查全量后在本地分组）
- **参数模板**：

```json
[
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "defectLevel": "严重", "pageNo": 1, "pageSize": 50}},
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "defectLevel": "危急", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：`total` 为满足条件总条数；`discoverTime` 为发现时间（`yyyy-MM-dd HH:mm`）；`status` 过滤可叠加为 `处理中`/`待处理` 得到「未消除」。
- **输出要点**：按等级分组表格 + 总数；标注「截止数据时间仍有 N 条未消除」。

### 问数 2：这条缺陷处理到哪一步了？

- **工具组合**：`view_defect`
- **参数模板**：

```json
{"tool": "view_defect", "arguments": {"defectId": "DF-2026-0001"}}
```

- **字段口径**：`processRecords` 为处理过程流水（登记→安排→处理→验收），最后一条即当前进展；`acceptance.result` 为验收结论（如「未验收」）；`photos` 为现场照片链接，对外输出只给链接不臆测内容。
- **输出要点**：时间轴式进展 + 验收状态；如未验收，提示「待消缺验收后闭环」。

### 问数 3：这台设备历史上有过哪些缺陷？（设备维度）

- **工具组合**：`inquire_defect`（`deviceId`）
- **参数模板**：

```json
{"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2024-10-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}}
```

- **字段口径**：`deviceId` 接受资产ID 或资源ID（以接口说明文档为准，建议统一传 `psrId`）；同一设备不同编码体系会产生不同结果，切换主键需说明。
- **输出要点**：缺陷时间序列表 + 部位分布；如出现同一部位重复缺陷，单列为「重复缺陷提示」。

### 问数 4：站内还有哪些隐患没闭环？

- **工具组合**：`list_hazard`（`status`=整改中/未整改，或一次查全量）
- **参数模板**：

```json
[
  {"tool": "list_hazard", "arguments": {"stationId": "STA-220-01", "status": "整改中", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_hazard", "arguments": {"stationId": "STA-220-01", "status": "未整改", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：`measures` 为管控/整改措施，不是整改结果；`riskLevel` 独立于缺陷等级；外部隐患通常无设备ID，不能按设备维度关联。
- **输出要点**：按风险等级分组表 + 未闭环总数；重大隐患单独置顶提示。

### 问数 5：这台主变最近有没有跳闸/故障？原因是什么？

- **工具组合**：`list_fault_trip_records`
- **参数模板**：

```json
{"tool": "list_fault_trip_records", "arguments": {"deviceId": "PSR-220-0001", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：`protectionAction` 为保护动作（如「差动保护动作」），`cause` 为原因分析结论（人工/系统判定，需专业复核）；`faultTime` 为故障发生时间，不是恢复时间。
- **输出要点**：故障清单 + 原因归纳；注明「原因字段为记录值，最终定性以事故分析报告为准」。

### 问数 6：近一年某站缺陷多少条？危急/严重占比多少？

- **工具组合**：`inquire_defect`（按等级分别取 `total`，或全量后本地统计）
- **参数模板**：

```json
[
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "defectLevel": "危急", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 20}}
]
```

- **字段口径**：占比分母为同期缺陷总条数（按 `startTime`/`endTime` 过滤发现时间），分子为对应等级条数；四舍五入保留 1 位小数；样本不完整（分页未取全）时须标注「基于前 N 条样本」。
- **输出要点**：总条数、等级分布、占比、未消除条数。

### 问数 7：缺陷平均处理时长是多少？有没有超期未消除的？

- **工具组合**：`inquire_defect`（全量取记录）→ 必要时逐条 `view_defect` 取消除时间
- **参数模板**：

```json
[
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "status": "已消除", "startTime": "2026-01-01", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 200}},
  {"tool": "view_defect", "arguments": {"defectId": "DF-2026-0001"}}
]
```

- **字段口径**：处理时长 = 消除时间 − 发现时间（小时）；列表接口若不返回消除时间，需 `view_defect` 的 `processRecords` 中「验收/消除」节点补齐；未消除缺陷单独计「已挂起时长」并对照等级时限（危急 24 小时，**以本单位规程为准**）。
- **输出要点**：平均/中位处理时长、超期清单（按等级时限判定）、样本量与缺失说明。

### 问数 8：站级健康画像（缺陷 + 隐患 + 故障）

- **工具组合**：`inquire_defect` + `list_hazard` + `list_fault_trip_records`
- **参数模板**：

```json
[
  {"tool": "inquire_defect", "arguments": {"stationId": "STA-220-01", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_hazard", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 50}},
  {"tool": "list_fault_trip_records", "arguments": {"stationId": "STA-220-01", "startTime": "2025-10-26", "endTime": "2026-10-26", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：三类记录时间字段不同（`discoverTime` / 无 / `faultTime`），汇总时必须分别说明统计口径；不能把隐患数与缺陷数相加成「问题总数」。
- **输出要点**：三张表 + 健康结论（风险点排序：危急缺陷 > 重大隐患 > 重复故障）。

### 问数 9：某台设备的缺陷部位集中在哪些部件？

- **工具组合**：`inquire_defect`（取 `part` 字段）→ 需要部件定位时配合 `substation-device-tree` 的 `COMPONENT` 节点
- **参数模板**：

```json
[
  {"tool": "inquire_defect", "arguments": {"deviceId": "PSR-220-0001", "pageNo": 1, "pageSize": 100}},
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "DEV-220-T1", "nodeType": "COMPONENT", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：`part` 为部位文本（如「本体/套管」「机构箱」），是自由填写字段，统计前需做关键词归类；归类规则须写明。
- **输出要点**：部位分布表 + 结论（如「套管渗油类缺陷 2 次，建议纳入专项检查」）。

## 三、通用注意

1. **主键统一**：跨技能查询前确认 `psrId`/`assetId` 一致，混用会导致漏查。
2. **时间窗必写**：任何统计都要写明起止日期与数据截止时间。
3. **分页必看 `total`**：数量结论以 `total` 为准；占比计算需先确认样本是否全量。
4. **等级不混用**：缺陷三档（危急/严重/一般）与隐患三档（重大/较大/一般）不得混称。
5. **记录 ≠ 结论**：故障原因、缺陷等级、隐患风险均为记录值，涉及责任认定与考核的结论必须提示业务复核。
6. **Mock 标注**：所有数据标注「Mock 数据，仅用于联调」。
7. **脱敏**：处理人保留姓氏，电话、身份证、住址等脱敏。
