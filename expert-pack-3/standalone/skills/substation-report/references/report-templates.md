# 报告专家 · 模板与 payload 组装

> 本文件是 `substation-report` 的细节层：三类报告模板的 payload 组装、章节结构、验收清单。
> 事实源优先级：`spec/analysis-tools.json`（`generate_report` / `list_report_types` 契约）> 分析引擎 `templates/*.md` > 本文件（组装与验收规范）。
> **payload 键名以 `list_report_types.requiredPayloadKeys` 为准**；本文列的是推荐键与素材映射，用于「有素材该放哪、没素材怎么说明」。

## 一、选型决策

| 用户诉求特征 | 选 `report_type` | 前置依赖（必须先跑） |
|---|---|---|
| 单台设备、要健康分/等级/扣分/诊断 | `device_profile` | `assess_device_health`（必）+ `diagnose_equipment`（建议） |
| 整站/多设备、按月/按期、要统计与风险清单 | `station_monthly` | `assess_station_health`（必）+ `compute_device_metrics`（建议） |
| 单次故障/跳闸事件、要经过与根因 | `fault_review` | `diagnose_equipment`（必）+ 故障记录 |
| 只问「有哪些报告模板」 | 不渲染 | 仅 `list_report_types` |

**混合诉求拆分**：既要看单设备又要看整站 → 出两份（月报里引用画像摘要）；既有故障又要站点统计 → 复盘为主、附站级指标一节。

## 二、通用组装流程

1. `list_report_types` → 取目标类型的 `requiredPayloadKeys[]`，作为组装的**唯一清单**。
2. 按清单从分析结果 JSON 中取值；取不到 → 记入 `dataGaps` 并在报告正文写「数据未提供」。
3. 值必须原样搬（分数不改位、等级不改写、扣分值不改符号）。
4. 时间窗、主键、单位、Mock 状态一并带上（渲染器需要写进报告头部/数据质量章节）。
5. 需要条款引用时附 `citations`（见 `knowledge-integration.md`）。
6. 渲染后执行第四节验收清单。

## 三、`device_profile`（设备画像）

### 3.1 推荐 payload

| 键 | 内容 | 来源 | 缺失时 |
|---|---|---|---|
| `device` | 铭牌与位置（`psrId`/`assetId`/名称/站/电压等级/类型/型号/厂家/投运日期/容量） | `get_asset_by_id`（pgp-102-2411-00102） | 必填，缺则先补台账 |
| `health` | `score`/`grade`/`gradeLabel`/`risk`/`dimensions[]`/`completeness`/`confidence` | `assess_device_health` | 必填；无评分不出画像 |
| `deductions` | 扣分证据（`ruleId`/`dimension`/`delta`/`reason`/`source`） | `assess_device_health.deductions` | 「数据未提供」+ 原因 |
| `diagnosis` | `hypotheses[]`（`name`/`score`/`confidence`）、`patterns`、`missingEvidence[]` | `diagnose_equipment` | 「本次未做诊断」 |
| `metrics` | 派生指标 | `compute_device_metrics` | 「指标未计算」 |
| `defects` / `hazards` / `faults` | 记录清单 | `inquire_defect` / `list_hazard` / `list_fault_trip_records` | 写「该时间窗内无记录」并降置信度 |
| `dataGaps` | 缺口清单 | 各工具 `dataGaps` | 合并去重后列出 |
| `suggestions` | 处置建议 | `diagnose_equipment.suggestions` + 健康建议 | 至少一条「补数/复核」建议 |

### 3.2 章节结构（8 节）

1. **报告说明**：报告类型、设备、时间窗、数据截止时间、Mock 标注。
2. **设备概况**：铭牌参数、运行年限、站与电压等级。
3. **健康评分**：分数 + 等级 + 风险 + 一句话结论（引用 `summary`，不改写）。
4. **维度得分**：维度表（维度 | 权重 | 得分 | 说明）。
5. **扣分证据链**：规则ID | 维度 | 扣分 | 依据数据 | 来源接口。
6. **诊断结论**（如有）：假设排序表 + 证据链摘要 + 置信度。
7. **数据质量与置信度**：`completeness`、`confidence` 档位、`dataGaps`、`missingEvidence`。
8. **处置建议与复核**：建议动作 + 复核提示 + 引用列表。

### 3.3 骨架示例（节选，示意结构与写法；数值为示例值）

```markdown
## 1号主变设备健康画像（220kV 郑州变电站）
数据窗口：2025-10-26 至 2026-10-26｜数据截止：2026-10-26｜Mock 数据，仅用于联调

### 一、设备概况
1号主变（PSR-220-0001 / AST-102-0001），变压器，220kV，SSZ11-180000/220，特变电工，2016-05-18 投运，容量 180MVA。

### 二、健康评分
健康度 62.0 分，D 级（预警），风险较高。主要受严重缺陷未闭环与试验超期影响。

### 三、维度得分
| 维度 | 权重 | 得分 | 说明 |
|---|---|---|---|
| 缺陷 | 0.30 | 55.0 | 1 条严重缺陷处理中 |

### 四、扣分证据链
> 规则ID 必须原样引用 `assess_device_health.deductions[].ruleId`，下方为展示格式（不对应真实规则ID）。

| 规则ID | 维度 | 扣分 | 依据数据 | 来源接口 |
|---|---|---|---|---|
| （引擎返回的 ruleId） | 缺陷 | -30 | DF-2026-0001 严重 处理中 | pgp-106-2411-00703 |

### 五、数据质量与置信度
完备度 4/5，置信度 0.80（中）；未取到巡视记录（pgp-106-2411-00403）。

### 六、处置建议
按等级时限消缺；补做套管介损与油色谱；本结论需变电专业复核。

### 引用
- 【来源：电力变压器检修导则（示例标题）】DL/T 573（示例）：套管油位异常时应结合介损与油色谱分析判断受潮程度。
```

## 四、`station_monthly`（站级月报）

### 4.1 推荐 payload

| 键 | 内容 | 来源 | 缺失时 |
|---|---|---|---|
| `station` | 站元数据 | `assess_station_health.station` / `list_psr_by_filters` | 必填 |
| `period` / 时间窗 | 统计月与数据截止 | 取数时确定（如 2026-09） | 必填 |
| `aggregate` | `avgScore`/`gradeDistribution`/`riskTop`/`criticalCount` | `assess_station_health.aggregate` | 必填；无站级评分不出月报 |
| `devices[]` | 每台设备分项（名称/分数/等级/主要缺口） | `assess_station_health.devices` | 「部分设备未评分」+原因 |
| `riskList` | 风险清单（含 MainGap、建议） | `aggregate.riskTop` + 诊断线索 | 「本次无风险设备」需置信度支撑 |
| `metrics` / `denominators` | 关键指标与分母 | `compute_device_metrics` | 「指标未计算」 |
| `dataQuality` | 完备度、置信度、缺口 | 各工具合并 | 必填 |
| `suggestions` | 下月建议 | 分析结果 + 缺口 | 至少一条 |

### 4.2 章节结构（8 节）

1. **报告说明**：站、统计月、数据截止、Mock 标注。
2. **站级概览**：设备总台数（`list_psr_by_filters.total`）、纳入评分台数、未纳入原因。
3. **评分统计**：`avgScore` + 等级分布（A/B/C/D/E 各 n 台）+ 与上月对比（同 profile/同范围才可比）。
4. **设备分项表**：设备 | 分数 | 等级 | 主要扣分维度 | 建议。
5. **风险设备清单**：`riskTop` 全量 + 每台建议动作 + `criticalCount`。
6. **关键指标**：缺陷率、超期未消缺、检修计划完成率、试验完成率、负载率、可开放容量比、可用率（各带分母与口径）。
7. **数据质量**：完备度、置信度、缺口、未评分设备说明。
8. **下月建议**：消缺、试验、专项检查、补数计划。

### 4.3 口径红线

- `avgScore` 是「纳入评分设备」的均值，必须在正文注明台数；**不得把均值当站级等级**。
- 跨月对比必须同 `scorecard_profile`、同设备范围；范围变化单列说明。
- 指标分母（设备台数、应完成计划数）必须展示，不允许只给百分比。

## 五、`fault_review`（故障复盘）

### 5.1 推荐 payload

| 键 | 内容 | 来源 | 缺失时 |
|---|---|---|---|
| `device` | 故障设备 | `get_asset_by_id` / `get_psr_by_id` | 必填 |
| `faults[]` | `time`/`protectionAction`/`cause`/`description` | `list_fault_trip_records`（pgp-106-2411-02603） | 必填；无故障记录不写复盘 |
| `diagnosis` | `hypotheses[]`（`name`/`score`/`confidence`/`suggestions`）、证据、`missingEvidence[]` | `diagnose_equipment` | 必填（复盘核心） |
| `patterns` | 重复/家族簇 | `detect_defect_patterns` | 「未做模式识别」 |
| `defects` | 相关缺陷清单 | `inquire_defect` | 写「相关缺陷未取到」 |
| `suggestions` | 整改建议 | `diagnose_equipment.suggestions` | 至少一条 |
| `dataGaps` | 缺口 | 各工具 | 必填 |

### 5.2 章节结构（8 节）

1. **报告说明**：事件名称、设备、时间、数据截止、Mock 标注。
2. **事件概况**：时间、设备、保护动作原文、当前状态。
3. **故障经过时间线**：按时间排序（取数时间 → 跳闸 → 处理 → 恢复），只写有记录的节点。
4. **保护动作分析**：`protectionAction` 原文 + 与诊断的一致性说明（无录波时注明缺口）。
5. **根因假设排序**：假设 | 匹配度 | 置信度 | 关键证据；**原样使用引擎顺序**。
6. **证据链**：支持证据 → 规则/接口 → 反证与缺口。
7. **影响与整改建议**：影响范围（可用 `analyze_supply_area` 结果，由领域技能提供）+ 建议动作。
8. **待补证据与复核**：`missingEvidence` 清单 + 复核提示。

> 复盘报告**禁止**写责任认定、禁止把低置信度假设写成「事故原因已查明」。

## 六、验收清单（生成后逐项过）

| # | 检查项 | 通过标准 |
|---|---|---|
| 1 | 无占位符 | `markdown` 中无 `{{` / `}}` / `TODO` / `xxx` |
| 2 | 章节齐全 | 对应类型的章节结构不缺项；缺素材有「数据未提供」说明 |
| 3 | 数字可追溯 | 每个数字能指出 payload 键与接口编码 |
| 4 | 等级/分数一致 | 报告的分数、等级与 `assess_*` 返回完全一致 |
| 5 | 假设顺序一致 | 与 `diagnose_equipment.hypotheses` 顺序一致 |
| 6 | 引用规范 | 正文【来源：标题】+ 文末引用列表；`snippet` 与知识库返回一致 |
| 7 | 检索声明 | 无命中时写「知识库未检索到相关条款」 |
| 8 | 缺口披露 | `dataGaps`/`missingEvidence` 有独立章节 |
| 9 | 口径一致 | 时间窗、主键、单位、口径说明前后一致 |
| 10 | 标注与脱敏 | Mock 标注、复核提示、敏感字段脱敏 |

**不通过的处理**：修改 payload 后重新调 `generate_report`，**禁止直接编辑 `markdown` 文本**（会导致数字与分析结果脱钩，无法追溯）。

## 七、常见错误

| 错误 | 后果 | 纠正 |
|---|---|---|
| 猜 payload 键名 | 渲染出「数据未提供」或结构错位 | 先 `list_report_types` |
| 把站级均值写成「站级健康等级」 | 口径错误、误导决策 | 只报均值 + 等级分布 |
| 把 `payload` 数字改得「更好看」 | 数字不可追溯 | 原样搬，问题回取数/分析层解决 |
| 用手工文本替换占位符 | 报告与 payload 不一致 | 补素材重渲染 |
| 引用片段概括成一句话 | 违反片段保真 | 原文照录或写「未检索到」 |
| 漏写数据质量章节 | 置信度缺失，结论被误用 | 固定章节不可省 |
