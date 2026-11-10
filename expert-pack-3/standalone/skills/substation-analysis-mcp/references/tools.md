# 分析工具契约（7 个工具）

本文件是 `skills/substation-analysis-mcp` 的工具调用手册，权威字段定义以
`expert-pack/spec/analysis-tools.json` 为准（测试 `test_analysis_mcp.py` 会逐字段比对）。
所有工具都是**纯函数**：同输入同输出，不读网络、不读系统时钟（报告 `generatedAt` 除外）。

传输方式：

- **MCP（stdio）**：`python skills/substation-analysis-mcp/scripts/analysis_mcp.py`，换行分隔 JSON-RPC 2.0；
- **CLI**：`python skills/substation-analysis-mcp/scripts/analysis_cli.py <command> --bundle ...`；
- **Python**：`from analysis import assess_device_health, ...`（把 `scripts` 加入 `sys.path`）。

## 通用约定

### 请求 / 响应信封（MCP）

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"assess_device_health","arguments":{"bundle":{...}}}}
```

成功：

```json
{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"score\":75.8,...}"}],"isError":false}}
```

业务数据错误（**不是**协议错误，模型可纠正后重试）：

```json
{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\"error\":{\"code\":\"BUNDLE_INVALID\",\"message\":\"...\"}}"}],"isError":true}}
```

协议错误码：`-32700` 解析失败、`-32600` 非法请求、`-32601` 未知方法、`-32602` 未知工具/参数缺失或类型/枚举不合法、
`-32603` 内部错误；业务错误码：`BUNDLE_INVALID`、`CONFIG_INVALID`、`REPORT_INVALID`。

### 时间基准

`as-of` 依次取：显式 `as_of`（Python API）/ `--as-of`（CLI）→ `bundle.timeWindow.end`。
两者都没有时，时间相关扣分不执行，并在 `dataGaps` 中说明；**绝不使用系统当前时间**。

### 证据链结构

每个扣分/命中证据统一为：

```json
{
  "ruleId": "DEF-OVERDUE",
  "dimension": "defects",
  "delta": -10,
  "reason": "严重缺陷超期未消缺 41 天（限值 7 天）：...（DF-2026-0101）",
  "source": ["pgp-106-2411-00703"],
  "data": {"defectId": "DF-2026-0101", "openDays": 41, "overdueLimitDays": 7}
}
```

`source` 为接口编码：优先取自 `bundle.sourceMeta[].interfaceCode`（按工具名匹配），否则使用内置码表：

| 数据段 | 取数工具 | 默认接口编码 |
|---|---|---|
| device | get_asset_by_id | `pgp-102-2411-00102` |
| defects | inquire_defect | `pgp-106-2411-00703` |
| hazards | list_hazard | `pgp-106-2411-01003` |
| faults | list_fault_trip_records | `pgp-106-2411-02603` |
| tests | find_repair_test | `pgp-106-2411-05003` |
| repairPlans | get_repair_plan | `pgp-106-2411-04206` |
| patrolRecords | list_patrol_record | `pgp-106-2411-00403` |
| load | query_open_capacity | `pgp-108-2411-00201` |
| reliability | query_station_scale_analysis | `pgp-108-2411-00405` |

---

## 1. assess_device_health — 单设备健康度评分

**入参**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| bundle | object | 是 | — | 设备数据包，见 [`bundle-schema.md`](bundle-schema.md) |
| scorecard_profile | string | 否 | `default` | 评分卡档位，目前仅 `default` |

**出参**（`content[0].text` 为 JSON 串）

| 字段 | 说明 |
|---|---|
| score | 总分，1 位小数 |
| grade / gradeLabel / risk | A/B/C/D/E、健康/良好/注意/预警/严重、低/低/中/较高/高 |
| dimensions[] | `{id,name,weight,base,deduction,score,evidenceCount}`，顺序 defects/faults/tests/load/ledger |
| deductions[] | 扣分证据链（见上），按规则执行顺序 |
| completeness | `{present,total,missing,ratio}`，total=4（defects/faults/tests/load） |
| confidence | 置信度 0.30–0.95 |
| summary | 中文结论摘要（含主要扣分） |
| knowledgeQueries | 按命中维度聚合的知识库检索建议 |
| dataGaps | `[{section,field,reason}]` 数据缺口 |
| asOf | 本次分析时间基准 |

**示例**

```json
{"name":"assess_device_health","arguments":{"bundle":{...},"scorecard_profile":"default"}}
```

演示数据返回 `score=75.8, grade=C, gradeLabel=注意, risk=中, confidence=0.9, completeness=4/4`，
扣分：`DEF-SERIOUSOPEN -15`、`DEF-OVERDUE -10`、`DEF-NORMALOPEN -5`、`DEF-OVERDUE -10`、
`FAULT-RECENT -25`、`TEST-UNQUALIFIED -30`。

**CLI**：`analysis_cli.py health --bundle bundle.json [--as-of 2026-09-30]`

---

## 2. assess_station_health — 站级健康画像

**入参**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| bundles | array | 是 | — | 同一站的设备数据包数组，非空 |
| station_meta | object | 否 | `{}` | `stationId/stationName/voltageLevel` |
| scorecard_profile | string | 否 | `default` | 评分卡档位 |
| top_n | integer | 否 | `5` | 风险设备 TopN |

**出参**

| 字段 | 说明 |
|---|---|
| station | `{stationId,stationName,voltageLevel,deviceCount}` |
| devices[] | 每台 `{name,psrId,assetId,score,grade,gradeLabel,risk,confidence,summary}` |
| aggregate | `{avgScore,gradeDistribution{A..E},riskTop[],criticalCount}`；riskTop 按分数升序（同分按名称），criticalCount=D+E 台数 |
| knowledgeQueries | 站级知识库检索建议 |
| asOf | 分析时间基准 |

**CLI**：`station-health --bundle station.json`，其中 `station.json` 可以是
`{"station":{...},"bundles":[...]}`，也可以直接是 bundle 数组。

---

## 3. diagnose_equipment — 跨域证据链诊断

**入参**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| bundle | object | 是 | — | 设备数据包 |
| max_hypotheses | integer | 否 | `5` | 最多返回假设数 |

**出参**

| 字段 | 说明 |
|---|---|
| hypotheses[] | `{ruleId,name,dimension,score,confidence,evidenceCount,evidence[],suggestions[],knowledgeQueries[],missingEvidence[]}`，按 score 降序 |
| patterns | 与 `detect_defect_patterns` 相同的聚类结果 |
| missingEvidence | 命中假设的缺失证据去重清单 |
| dataGaps | 数据缺口（含「证据不足」提示） |
| rulesEvaluated | 已评估规则数 |
| asOf | 分析时间基准 |

- `score` = 规则基础分 + 0.02×(证据数−2)，上限 +0.10，最终不超过 0.99；
- `confidence` = 0.25 + 0.10×min(证据数,4) + 0.30×数据完备度，clamp [0.30, 0.95]；
- 同一记录（同 scope+recordId）只计一次证据，合并关键词。

**CLI**：`diagnose --bundle bundle.json [--max-hypotheses 5]`

---

## 4. detect_defect_patterns — 重复/家族缺陷识别

**入参**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| defects | array | 是 | — | 缺陷记录数组 |
| device_meta | object | 否 | — | `model/manufacturer/commissioningDate/deviceType`（当缺陷记录缺设备字段时回退） |
| window_days | integer | 否 | `365` | 聚类时间窗口 |
| family_min_count | integer | 否 | `3` | 家族性缺陷最小设备数 |

**出参**

| 字段 | 说明 |
|---|---|
| duplicateClusters[] | 同设备同部位 count≥2：`{clusterId:"DUP-n",part,deviceName,count,defectIds,levels,statuses,firstTime,lastTime,defects[]}` |
| familyClusters[] | 同型号+同厂家+同部位的不同设备数≥family_min_count：`{clusterId:"FAM-n",model,manufacturer,part,deviceCount,deviceNames,count,defectIds,levels,firstTime,lastTime}` |
| summary | `{defectCount,evaluatedCount,windowDays,familyMinCount,asOf,duplicateClusterCount,familyClusterCount,dataGaps}` |
| dataGaps | 缺 part/model/manufacturer 等字段时的说明 |

时间窗口：`discoverTime` 不早于 `asOf − window_days`；未显式给 `as_of` 时，以最新一条缺陷发现时间为基准。

**CLI**：`patterns --bundle bundle.json [--window-days 365] [--family-min-count 3]`

---

## 5. compute_device_metrics — 派生指标

**入参**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| bundle | object | 是 | — | 设备数据包 |

**出参**

| 字段 | 说明 |
|---|---|
| metrics | 9 项指标（见下） |
| denominators | 分母与原始计数，便于复核 |
| dataGaps | 无法计算的指标说明（如 `trend`） |
| summary | 中文摘要 |
| asOf | 分析时间基准 |

指标口径（单设备）：

| 指标键 | 定义 | 单位/类型 |
|---|---|---|
| defectRate | 缺陷数 / 设备数 | 条/台 |
| criticalOpen | 危急且未闭环缺陷数 | 条 |
| overdueOpen | 超期未消缺缺陷数（危急>1天/严重>7天/一般>30天） | 条 |
| repairPlanCompletion | 已完成检修计划 / 计划总数×100 | %（无计划为 0.0） |
| testCompletion | 最近试验未超期（默认 1095 天）→100，否则 0；无记录为 0 | % |
| loadRate | `load.loadRate`，缺失时由 当前负载/额定容量×100 推导 | % |
| openCapacityRatio | 可开放容量/额定容量×100，缺失由 `100−loadRate` 推导 | % |
| availabilityRate | `reliability.availabilityRate` | %（缺失为 `null`+dataGap） |
| trend | 多期趋势；单期 bundle 无法计算，固定 `null` + `dataGap` | null |

**CLI**：`metrics --bundle bundle.json`

---

## 6. generate_report — 报告渲染

**入参**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| report_type | string | 是 | — | `device_profile` / `station_monthly` / `fault_review` |
| payload | object | 是 | — | 分析结果负载，键见 [`report-templates.md`](report-templates.md) |
| citations | array | 否 | 省略即无引用 | `[{title,source,snippet,kbId}]` 知识库引用 |
| title | string | 否 | 模板标题 | 自定义报告标题 |

**出参**：`{reportType,title,markdown,sections:[{id,title,content}],generatedAt,dataGaps}`。

- payload 缺键 → 渲染「数据未提供」并写入 `dataGaps`，**不抛错**；
- citations 渲染为引用列表，无引用时写「知识库未检索到相关条款」；
- 渲染后不残留 `{{占位符}}`。

**CLI**：`report --type device_profile --bundle bundle.json [--citations citations.json] [--title ...]`
或 `report --type ... --payload payload.json`。

---

## 7. list_report_types — 报告模板清单

**入参**：无。

**出参**：

```json
{"reportTypes":[
  {"type":"device_profile","name":"设备画像报告","requiredPayloadKeys":["device","health"]},
  {"type":"station_monthly","name":"站级月报","requiredPayloadKeys":["station","aggregate"]},
  {"type":"fault_review","name":"故障复盘报告","requiredPayloadKeys":["fault"]}
]}
```

**CLI**：`list-report-types`
