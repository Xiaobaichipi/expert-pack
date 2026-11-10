# 报告专家 · 典型报告任务模板

> 本文件是 `substation-report` 的细节层：5 个典型报告任务的「前置依赖 → payload 组装 → `generate_report` 调用 → 输出要点」。
> 工具名/参数名以 `spec/analysis-tools.json` 为准；payload 键名以 `list_report_types.requiredPayloadKeys` 为准，示例值为示意值。
> 当前 `PMS_AUTH_MODE=mock`，报告首页须标注「Mock 数据，仅用于联调，不可作为生产结论」。

## 通用前置检查（每个任务都要过）

| 检查 | 要求 |
|---|---|
| 前置分析是否已跑 | `device_profile` → `assess_device_health`；`station_monthly` → `assess_station_health`；`fault_review` → `diagnose_equipment` |
| 主键与时间窗是否一致 | 全篇同一 `psrId`/`stationId`、同一 `timeWindow`、同一数据截止时间 |
| 模板契约是否已取 | 先 `list_report_types`，按 `requiredPayloadKeys` 组包 |
| 知识检索是否需要 | 用户要求引用条款时才做；做了就必须传 `citations` |

---

## 任务 1：给 1 号主变出一份设备画像报告

**前置**：`assess_device_health`（必）+ `diagnose_equipment`（建议）+ 台账/缺陷/修试取数（由领域技能完成）。

**模板契约**

```json
{"tool": "list_report_types", "arguments": {}}
```

**渲染**

```json
{"tool": "generate_report", "arguments": {"report_type": "device_profile", "title": "1号主变设备健康画像（220kV 郑州变电站）", "payload": {"device": {"psrId": "PSR-220-0001", "assetId": "AST-102-0001", "name": "1号主变", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV", "deviceType": "变压器", "model": "SSZ11-180000/220", "manufacturer": "特变电工", "commissioningDate": "2016-05-18", "capacityMVA": 180}, "health": {"score": 62.0, "grade": "D", "gradeLabel": "预警", "risk": "较高", "completeness": {"present": 4, "total": 5}, "confidence": 0.8}, "deductions": [{"ruleId": "<引擎返回>", "dimension": "缺陷", "delta": -30, "reason": "严重缺陷未闭环", "source": ["pgp-106-2411-00703"]}], "diagnosis": {"hypotheses": [{"name": "套管受潮", "score": 0.78, "confidence": 0.68}], "missingEvidence": ["最近一次介损试验分项数据"]}, "dataGaps": ["巡视记录未取到（pgp-106-2411-00403）"], "suggestions": ["按等级时限消缺", "补做套管介损与油色谱"]}, "citations": [{"title": "电力变压器检修导则（示例标题）", "source": "DL/T 573（示例）", "snippet": "示例：套管油位异常时应结合介损与油色谱分析判断受潮程度。", "kbId": "kb-doc-001"}]}}
```

**输出要点**：8 节齐全（报告说明→设备概况→健康评分→维度得分→扣分证据链→诊断结论→数据质量→处置建议）；分数等级与分析结果逐字一致；置信度与缺口单列章节；末尾引用列表与正文【来源：标题】对应。

---

## 任务 2：生成 220kV 郑州变电站 2026 年 9 月设备健康月报

**前置**：`assess_station_health`（必，全站 bundles）+ `compute_device_metrics`（建议，重点设备）+ 巡视/检修/缺陷取数。

**关键组装动作**

1. `station` 取 `assess_station_health.station`；设备总台数用 `list_psr_by_filters.total` 核对。
2. `devices[]` 按分数升序排（风险在前），每台给「名称/分数/等级/主要扣分维度」。
3. `riskList` 用 `aggregate.riskTop` 全量（不截断），并给每台一条建议动作。
4. `metrics` 携 `denominators`（分母必须进入报告）。
5. 跨月对比仅在「同 profile + 同设备范围」时写，否则写「口径不同，不做环比」。

```json
{"tool": "generate_report", "arguments": {"report_type": "station_monthly", "title": "220kV 郑州变电站 2026年9月设备健康月报", "payload": {"station": {"stationId": "STA-220-01", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV"}, "period": {"start": "2026-09-01", "end": "2026-09-30"}, "aggregate": {"avgScore": 78.4, "gradeDistribution": {"A": 2, "B": 3, "C": 2, "D": 1, "E": 0}, "criticalCount": 1}, "devices": [{"name": "1号主变", "score": 62.0, "grade": "D", "mainGap": "严重缺陷未闭环"}, {"name": "2号主变", "score": 84.5, "grade": "B", "mainGap": "试验超期"}], "riskList": [{"name": "1号主变", "score": 62.0, "grade": "D", "risk": "较高", "suggestion": "安排专项检查并消缺"}], "metrics": {"defectRate": 0.18, "overdueOpen": 1, "loadRate": 70.0, "openCapacityRatio": 30.0}, "denominators": {"设备台数": 8, "应完成检修计划数": 3}, "dataQuality": {"completeness": {"present": 4, "total": 5}, "dataGaps": ["9月巡视记录未取到（pgp-106-2411-00403）"]}, "suggestions": ["对 D 级设备安排专项检查", "核查试验超期设备试验计划"]}}}
```

**输出要点**：`avgScore` 注明「纳入评分 N 台」；等级分布报台数；风险清单不截断；指标带分母；未评分设备单列原因；下月建议可执行。

---

## 任务 3：这次跳闸写一份故障复盘报告

**前置**：`diagnose_equipment`（必）+ `list_fault_trip_records`（故障经过/保护动作）+ 缺陷/修试取数；需要影响范围时由资源拓扑技能提供 `analyze_supply_area` 结果。

```json
{"tool": "generate_report", "arguments": {"report_type": "fault_review", "title": "1号主变 2026-08-03 差动保护动作故障复盘", "payload": {"device": {"psrId": "PSR-220-0001", "name": "1号主变", "voltageLevel": "220kV", "deviceType": "变压器"}, "faults": [{"faultId": "FT-2026-0001", "time": "2026-08-03 02:17", "protectionAction": "差动保护动作", "cause": "套管绝缘受潮"}], "diagnosis": {"hypotheses": [{"name": "套管受潮", "score": 0.78, "confidence": 0.68, "suggestions": ["补做介损与油色谱试验", "核查套管密封与油位"]}, {"name": "冷却系统/过负荷", "score": 0.31, "confidence": 0.45, "suggestions": ["核查冷却器运行方式与温度曲线"]}], "missingEvidence": ["最近一次介损试验分项数据", "油色谱分析报告"], "dataGaps": []}, "suggestions": ["按规程安排停电试验确认", "同型号设备开展套管专项排查"]}, "citations": [{"title": "变压器运行规程（示例标题）", "source": "GB/T 17468（示例）", "snippet": "示例：变压器跳闸后应结合保护动作、油色谱与电气试验综合判定原因。", "kbId": "kb-doc-002"}]}}
```

**输出要点**：时间线只写有记录的节点；保护动作原文照录；假设顺序与 `diagnose_equipment` 一致；低置信度假设标注「方向」；`missingEvidence` 单列「待补证据」章节；**禁止责任认定**。

---

## 任务 4：给报告补上规程条款出处（知识引用环节）

**流程**：取分析结果的 `knowledgeQueries` → 逐条交 WeKnora MCP 检索（工具名以平台配置为准）→ 整理 `citations` → 重新渲染报告。

**检索参数示例（参数名以平台为准，非工具调用语法）**

```json
{"query": "危急缺陷 消缺时限 规程要求", "top_k": 5}
```

**citations 传入**

```json
{"tool": "generate_report", "arguments": {"report_type": "device_profile", "payload": {"device": {"psrId": "PSR-220-0001", "name": "1号主变"}, "health": {"score": 62.0, "grade": "D"}}, "citations": [{"title": "变电设备缺陷管理规定（示例标题）", "source": "示例单位规程 第4.2节", "snippet": "示例：危急缺陷应在 24 小时内组织处理并履行验收手续。", "kbId": "kb-doc-002"}]}}
```

**输出要点**：正文引用写【来源：标题】；文末列引用列表；`snippet` 原文未改写；检索不到写「知识库未检索到相关条款」；引用不改变任何分数与等级。**注意**：重新渲染时 `payload` 必须仍是原分析结果（可省略未变部分，但不可改数）。

---

## 任务 5：检查这份报告有没有占位符、编造数字或假引用

**做法**：不重新取数，直接对 `generate_report` 返回的 `markdown` 与传入的 `payload`/`citations` 做交叉核对。

| 检查 | 方法 | 判定 |
|---|---|---|
| 占位符 | 搜索 `{{`、`}}`、`TODO`、`xxx`、`待填` | 有即不合格 → 修 payload 重渲染 |
| 空章节 | 逐节看是否有正文或「数据未提供」说明 | 空节 → 补说明或补素材 |
| 数字可追溯 | 每个数字回查 payload 键或接口编码 | 无源数字 → 删除并补说明 |
| 分数/等级一致 | 与 `assess_device_health`/`assess_station_health` 返回值比对 | 不一致 → 以工具返回为准重渲染 |
| 假设顺序 | 与 `diagnose_equipment.hypotheses` 顺序比对 | 不一致 → 重渲染 |
| 引用真实性 | `citations[].snippet` 与知识库返回原文比对 | 改写/编造 → 改用原文或声明未检索到 |
| 引用格式 | 正文【来源：标题】与文末列表互查 | 缺失 → 补格式 |
| 口径与标注 | 时间窗、主键、单位、Mock 标注、复核提示 | 缺失 → 补齐后重渲染 |
| 脱敏 | 姓名、电话、身份证、详细地址 | 未脱敏 → 脱敏后重渲染 |

**输出要点**：给一张自检结果表（检查项 | 结果 | 处理），并声明「本次报告数字均来自 payload，引用均来自知识库返回」；若不合格项无法修 payload，明确告知用户缺什么素材。

## 通用注意

1. **先契约后组装**：先 `list_report_types` 拿 `requiredPayloadKeys`，不猜键名。
2. **只渲染不创作**：报告文字可由 `generate_report` 生成，业务数字只能来自 payload。
3. **不手改 markdown**：任何问题通过「补素材 → 重新 generate_report」解决。
4. **引用三不**：不改写片段、不编条款号、不能用条款推翻分析结论。
5. **交付三件套**：`markdown` 正文 + 自检记录 + 数据来源清单（接口编码与时间）。
