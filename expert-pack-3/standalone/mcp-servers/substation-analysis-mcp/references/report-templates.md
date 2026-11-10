# 报告模板与渲染（report-templates）

实现：`scripts/analysis/report.py`；模板：`templates/*.md`；测试：`tests/test_analysis_report.py`。

报告 = **模板占位符** + **Python 预渲染表格/清单** + **知识库引用**。
渲染不做任何计算，只做格式化；payload 缺失时写「数据未提供」并记 `dataGaps`，**绝不因缺数据而失败**。

## 一、模板清单

`list_report_types` / `analysis_cli.py list-report-types` 返回：

| type | name | 必需 payload 键 | 模板文件 |
|---|---|---|---|
| `device_profile` | 设备画像报告 | `device`、`health` | `templates/device_profile.md` |
| `station_monthly` | 站级月报 | `station`、`aggregate` | `templates/station_monthly.md` |
| `fault_review` | 故障复盘报告 | `fault` | `templates/fault_review.md` |

## 二、占位符语法

- `{{key}}`：普通字段，按点分路径取值（如 `{{health.score}}`、`{{device.name}}`）；
- 找不到 → 渲染为 `数据未提供`，并在 `dataGaps` 记 `{section,field,reason}`；
- 表格/清单类占位符（如 `{{dimensionsTable}}`）由 Python 预渲染成 Markdown 表格或编号列表；
- 渲染完成后不允许残留 `{{` / `}}`（测试会检查）。

### 2.1 通用占位符（3 类模板都有）

| 占位符 | 来源 | 说明 |
|---|---|---|
| `{{title}}` | 参数 `title` 或模板默认标题 | 报告标题 |
| `{{generatedAt}}` | 渲染时刻（本文件唯一读系统时钟处） | ISO 8601 带时区 |
| `{{asOf}}` | payload `asOf` 或 health/diagnosis 的 `asOf` | 数据截止时间 |
| `{{dataGapsList}}` | payload `dataGaps` + 缺键缺口 | 编号列表，无缺口为「无」 |
| `{{citationsList}}` | 参数 `citations` | 编号引用列表；无引用为「知识库未检索到相关条款」 |

### 2.2 device_profile（设备画像）

| 占位符 | 说明 |
|---|---|
| `{{device.name/stationName/voltageLevel/deviceType/model/manufacturer/commissioningDate/psrId/assetId}}` | 设备基本情况表 |
| `{{health.score}}`、`{{health.grade}}`、`{{health.gradeLabel}}`、`{{health.risk}}` | 总分/等级/风险 |
| `{{health.confidence}}`、`{{health.completeness.present}}`、`{{health.completeness.total}}` | 置信度与完备度 |
| `{{health.summary}}` | 结论摘要（引擎生成，不要改数字） |
| `{{dimensionsTable}}` | 维度得分表（维度/权重/得分/扣分/证据数） |
| `{{deductionsTable}}` | 扣分证据链表（规则ID/维度/扣分/原因/来源接口） |
| `{{hypothesesTable}}` | 根因假设表（序号/假设/规则ID/可能性/置信度/证据数） |
| `{{missingEvidenceList}}` | 缺失证据编号列表 |
| `{{metricsTable}}` | 派生指标表（指标/数值/单位） |

对应 payload 推荐结构：`{device, health, diagnosis, metrics, defects?, tests?, timeWindow?, asOf?, dataGaps?}`。

### 2.3 station_monthly（站级月报）

| 占位符 | 说明 |
|---|---|
| `{{period}}` | 统计期间（payload `period`，缺省写「数据未提供」） |
| `{{station.stationName/stationId/voltageLevel/deviceCount}}` | 站级概况 |
| `{{aggregate.avgScore}}`、`{{aggregate.criticalCount}}` | 平均健康分、D/E 设备数 |
| `{{gradeDistribution}}` | A–E 等级分布列表 |
| `{{riskTopTable}}` | 风险设备 TopN 表 |
| `{{devicesTable}}` | 全设备评分表 |
| `{{metricsTable}}` | 站级指标表（可为空表） |

对应 payload：`assess_station_health` 的结果（`station`/`devices`/`aggregate`），可加 `period`/`metrics`/`dataGaps`。

### 2.4 fault_review（故障复盘）

| 占位符 | 说明 |
|---|---|
| `{{device.name}}`、`{{device.stationName}}` | 设备/站 |
| `{{fault.time/protectionAction/cause/description}}` | 故障概况 |
| `{{defectsTable}}` | 缺陷清单 |
| `{{testsTable}}` | 试验清单 |
| `{{hypothesesTable}}` | 根因假设排序 |
| `{{missingEvidenceList}}` | 缺失证据 |
| `{{suggestionsList}}` | 处置建议 |

对应 payload：`{device, fault, health?, diagnosis?, defects?, tests?, dataGaps?}`。

## 三、入参

```json
{
  "report_type": "device_profile",
  "payload": {"device": {...}, "health": {...}, "diagnosis": {...}, "metrics": {...}},
  "citations": [
    {"title": "变压器运行规程", "source": "DL/T 572", "snippet": "套管介损超过规定值时应复核。", "kbId": "KB-001"}
  ],
  "title": "1号主变专项画像"
}
```

- `report_type` 必填且必须是三类之一，否则 `REPORT_INVALID`（CLI 退出码 1；MCP 为 `isError=true`）；
- `payload` 必须是对象；`citations` 必须是数组；`title` 非空字符串时覆盖模板标题；
- `citations[].title/source/snippet/kbId` 全部容错，有哪个渲染哪个。

## 四、返参

```json
{
  "reportType": "device_profile",
  "title": "设备画像报告",
  "markdown": "# 设备画像报告\n...",
  "sections": [{"id": "basic", "title": "一、设备基本情况", "content": "..."}],
  "generatedAt": "2026-10-26T17:50:37+08:00",
  "dataGaps": [{"section": "payload", "field": "health", "reason": "缺少 health 数据"}]
}
```

- `sections` 按 `##` 标题切分，便于前端目录/分段展示；
- `dataGaps` 同时包含 payload 缺键与缺值占位符；
- 同一 payload 两次渲染除 `generatedAt`（及 markdown 中时间戳）外完全一致。

## 五、CLI 用法

```bash
# 直接从 bundle 生成（内部自动算健康度/诊断/指标）
python skills/substation-analysis-mcp/scripts/analysis_cli.py report --type device_profile --bundle bundle.json

# 用已有分析结果 payload
python ... report --type station_monthly --payload station_result.json

# 附知识库引用与自定义标题
python ... report --type fault_review --bundle bundle.json --citations citations.json --title "FT-2026-0001 故障复盘"
```

`--payload` 与 `--bundle` 二选一；两者同时给出时以 `--payload` 为准；`-` 表示 stdin。

## 六、报告写作约束

1. **数字只来自引擎**：健康分、指标、假设得分/置信度原样引用，不改写、不四舍五入、不补算；
2. **证据链可追溯**：扣分/假设必须带规则 ID 与来源接口（模板已渲染）；
3. **缺口透明**：`数据未提供`、`dataGaps`、`missingEvidence` 必须保留，不得删减或伪装成结论；
4. **知识引用**：先拿 `knowledgeQueries` 检索 WeKnora，命中后把条款作为 `citations` 传入；
   检索不到就保留「知识库未检索到相关条款」，**不得编造标准号/条款**；
5. **决策提示**：涉及停电、检修、技改、低置信度根因时，加业务复核提示；
6. 模板改动后跑 `python -m unittest discover -s tests`，确认无占位符残留、3 类模板均可渲染。
