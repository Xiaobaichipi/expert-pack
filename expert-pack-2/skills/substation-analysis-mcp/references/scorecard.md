# 健康度评分卡口径（scorecard）

实现：`scripts/analysis/health.py`；配置：`config/scorecard.json`；测试：`tests/test_analysis_health.py`。
**所有分数由 Python 计算，LLM 不得口算或改写。**

## 一、总分公式

```
维度得分 = base(100) − min(maxDeduction(100), Σ|该维度扣分|)
总分     = round_half_up(Σ(维度权重 × 维度得分), 1)
```

- 5 个维度固定顺序与权重：缺陷 0.30、故障 0.25、修试 0.20、负载 0.15、台账 0.10（合计 1.0）；
- 每维从 100 分起扣，单维扣分最多 100（最低 0 分）；
- 总分用 `Decimal(...).quantize(Decimal("0.1"), ROUND_HALF_UP)` 保留 1 位小数。

演示数据（`assets/demo_bundle.json`）：

| 维度 | 权重 | 得分 | 扣分 | 加权 |
|---|---|---|---|---|
| 缺陷 | 0.30 | 60 | 40 | 18.0 |
| 故障 | 0.25 | 75 | 25 | 18.75 |
| 修试 | 0.20 | 70 | 30 | 14.0 |
| 负载 | 0.15 | 100 | 0 | 15.0 |
| 台账 | 0.10 | 100 | 0 | 10.0 |
| **合计** | 1.00 | — | — | **75.75 → 75.8（C·注意，风险中）** |

## 二、分维度扣分规则

### 2.1 缺陷（weight 0.30）

对**未闭环**缺陷（`status` 不属于 已消除/已关闭/已验收/closed 等）逐条计算：

| ruleId | 条件 | 扣分 |
|---|---|---|
| `DEF-CRITICALOPEN` | 等级=危急 | -30/项 |
| `DEF-SERIOUSOPEN` | 等级=严重 | -15/项 |
| `DEF-NORMALOPEN` | 等级=一般 | -5/项 |
| `DEF-OVERDUE` | 未闭环且 openDays > 时限：危急 1 天、严重 7 天、一般 30 天 | -10/项（与等级扣分叠加） |

- `openDays` = as-of − `discoverTime`（天）；无 as-of 时不做超期判断；
- 已闭环缺陷不扣分，也不进入证据链；
- 等级别名归一化：`紧急`→危急、`重大`→严重、`轻微/普通`→一般等。

### 2.2 故障（weight 0.25）

| ruleId | 条件（故障时间距 as-of） | 扣分 |
|---|---|---|
| `FAULT-RECENT` | ≤ 365 天 | -25/次 |
| `FAULT-MID` | 366–1095 天（13–36 个月） | -10/次 |
| 更早 | > 1095 天 | 不扣分 |

### 2.3 修试（weight 0.20）

| ruleId | 条件 | 扣分 |
|---|---|---|
| `TEST-NO-RECORD` | `tests` 为**空数组**（显式确认无记录） | -20（每台设备一次） |
| `TEST-STALE` | 最近一条 `testDate` 距 as-of > 1095 天 | -20 |
| `TEST-UNQUALIFIED` | 每条 `result` ∈ {不合格, 异常} | -30/条 |

> 无记录与超期互斥：无记录时只给 `TEST-NO-RECORD`；有记录但最近一条超期给 `TEST-STALE`。
> **缺键不算空数组**：`tests` 字段整体缺失时该维度按 100 分起算，只降完备度/置信度并记 `dataGap`，
> 避免把「没取到数」误判成「没有试验」。缺陷/故障/负载维度同理。

### 2.4 负载（weight 0.15）

| ruleId | 条件 | 扣分 |
|---|---|---|
| `LOAD-OVERLOAD` | 负载率 > 90% | -20 |
| `LOAD-HEAVY` | 负载率 > 80%（且 ≤90%） | -10 |
| `LOAD-LOW-OPEN-CAPACITY` | 可开放容量比 < 5% | -10 |

- 负载率优先取 `load.loadRate`，缺失由 `currentLoadMVA/ratedCapacityMVA×100` 推导；
- 可开放容量比优先由 `openCapacityMVA/ratedCapacityMVA×100` 推导，缺失时用 `100−负载率`；
- 90% 与 80% 不同时触发（>90 时只扣 20）。

### 2.5 台账（weight 0.10）

| ruleId | 条件 | 扣分 |
|---|---|---|
| `LEDGER-MISSING-FIELD` | `model`/`manufacturer`/`commissioningDate`/`deviceType` 每缺一项 | -10/项 |
| `LEDGER-MISSING-IDS` | `assetId` 与 `psrId` **同时**缺失 | -20 |

## 三、等级与风险

| 等级 | 分数区间 | gradeLabel | risk |
|---|---|---|---|
| A | ≥90 | 健康 | 低 |
| B | 80–89.9 | 良好 | 低 |
| C | 70–79.9 | 注意 | 中 |
| D | 60–69.9 | 预警 | 较高 |
| E | <60 | 严重 | 高 |

等级按总分向下取区间（`score >= minScore` 依次匹配）。

## 四、置信度与完备度

```
missingPenalty = min(0.05 × 缺失数据段数, 0.4)
stalePenalty   = 0.1   （当 as-of − timeWindow.end > 180 天）
confidence     = clamp(0.9 − missingPenalty − stalePenalty, 0.30, 0.95)
completeness   = {present, total:4, missing:[...], ratio}
```

- 完备度统计 4 个数据段：`defects`、`faults`、`tests`、`load`；
- **段存在即算 present**（空数组也算「已确认无记录」），键缺失或为 `null` 才算缺失；
- 报告与结论必须同时展示 `confidence` 与 `completeness`，低置信度需提示复核。

演示：4/4 完备、无陈旧窗口 → `confidence=0.9`。

## 五、输出契约

```json
{
  "score": 75.8, "grade": "C", "gradeLabel": "注意", "risk": "中",
  "dimensions": [{"id":"defects","name":"缺陷","weight":0.3,"base":100,
                  "deduction":40,"score":60,"evidenceCount":4}, ...],
  "deductions": [{"ruleId":"DEF-OVERDUE","dimension":"defects","delta":-10,
                  "reason":"...","source":["pgp-106-2411-00703"],
                  "data":{"defectId":"DF-2026-0101","openDays":41,"overdueLimitDays":7}}],
  "completeness": {"present":4,"total":4,"missing":[],"ratio":1.0},
  "confidence": 0.9,
  "summary": "1号主变 健康度 75.8 分（C·注意，风险中）；数据完备度 4/4，置信度 0.9；主要扣分：…",
  "knowledgeQueries": ["危急缺陷定级标准与消缺时限要求", ...],
  "dataGaps": [],
  "asOf": "2026-09-30"
}
```

`summary` 会拼接前 3 条主要扣分原因；`knowledgeQueries` 按命中维度聚合去重，供 WeKnora 检索。

## 六、站级画像

`assess_station_health(bundles, station_meta, scorecard_profile, top_n)`：

- 每台设备独立评分，输出精简设备行 `{name,psrId,assetId,score,grade,gradeLabel,risk,confidence,summary}`；
- `aggregate.avgScore` = 各设备分数均值（1 位小数）；
- `gradeDistribution` 固定含 A–E 五键（无设备为 0）；
- `riskTop` 按分数**升序**（同分按名称），取前 `top_n` 台；
- `criticalCount` = 等级 D 或 E 的设备数；
- `asOf` 取首台可解析设备的时间基准；站级知识库查询来自 `stationKnowledgeQueries`。

## 七、如何调整口径

只改 `config/scorecard.json`，不改代码：

- 新增档位：在 `profiles` 下加一个同结构 profile（`load_scorecard(profile)` 校验权重合计 1.0、维度 id 唯一、
  规则非空、等级含 minScore），调用时传 `scorecard_profile`；
- 调权重/阈值：改 `dimensions[].weight`、`rules.*`（如 `overdueDays`、`staleDays`、`threshold`）；
- 调置信度：改 `confidence.*`；
- 调整后必须同步更新本文件与 `tests/test_analysis_health.py` 的期望值。

> 修改评分卡属于**评分口径变更**，需在报告中说明并保留变更记录；不得在对话中临时改权重。
