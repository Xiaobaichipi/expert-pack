# 诊断规则库与证据链（diagnosis-rules）

实现：`scripts/analysis/diagnosis.py`；配置：`config/diagnosis_rules.json`；聚类：`scripts/analysis/patterns.py`；
测试：`tests/test_analysis_diagnosis.py`、`tests/test_analysis_patterns.py`。

诊断是**可解释的规则匹配**，不是黑盒模型：每条假设都能追溯到规则 ID、命中条件、输入记录与接口编码。
LLM 只负责把返回的假设转述成业务语言，不得新增/改写规则或分数。

## 一、规则结构

```json
{
  "ruleId": "DIAG-BUSHING-MOISTURE",
  "name": "套管受潮/绝缘劣化",
  "dimension": "tests",
  "score": 0.78,
  "conditionsMode": "all",
  "conditions": [ ... ],
  "suggestions": ["..."],
  "knowledgeQueries": ["..."],
  "missingEvidence": ["..."]
}
```

- `conditionsMode`：`all`（全部命中，默认）/ `any`（任一命中）/ `min`（命中数 ≥ `minConditions`）；
- `score` 是规则**基础可能性**（0–1）；实际得分见第三节；
- `suggestions` 是下一步核查/处置建议；`knowledgeQueries` 用于知识库检索；`missingEvidence` 是缺失证据清单。

## 二、条件 DSL

| type | 字段 | 语义 |
|---|---|---|
| `keyword` | `scopes[]`, `any[]`（可选 `all[]`） | 在指定数据段的文本中匹配关键词；`any` 任一命中即可，`all` 需全部命中 |
| `threshold` | `field`, `op`, `value` | 数值阈值；支持 `load.loadRate`、`load.openCapacityRatio` |
| `ageYears` | `op`, `value` | 运行年限 = (as-of − 投运日期)/365.25，未给 as-of 时不命中并记缺失 |
| `defectCount` | `op`, `value`, 可选 `level`, `status`(`all/open/closed`) | 缺陷条数统计 |
| `faultCount` | `op`, `value`, `withinDays` | 故障次数（可按距 as-of 天数过滤） |
| `testResult` | `values[]` | 试验结果命中（默认 不合格/异常） |
| `testCount` | `op`, `value` | 试验记录条数 |
| `testStale` | `staleDays` | 最近一条试验距 as-of 超过 `staleDays` |
| `protectionAction` | `withinDays` | 窗口内存在保护动作/跳闸记录 |
| `familyCount` | `op`, `value` | 家族性缺陷簇的设备数（来自聚类） |
| `samePartCount` | `op`, `value` | 同设备同部位缺陷数（来自聚类） |
| `missingFields` | `fields[]`, `op`, `value` | device 关键字段缺失个数 |
| `anyOf` / `allOf` | `conditions[]` | 组合条件：任一命中 / 全部命中 |

`op` 支持 `>` `>=` `<` `<=` `==` `!=`。

## 三、规则清单（12 条）

| ruleId | 名称 | 维度 | 基础分 | 命中条件（摘要） |
|---|---|---|---|---|
| `DIAG-BUSHING-MOISTURE` | 套管受潮/绝缘劣化 | tests | 0.78 | 关键词含 套管/末屏 **且** 含 介损/电容量/绝缘电阻/泄漏电流/受潮/渗油 |
| `DIAG-MECH-BOX-MOISTURE` | 机构箱/二次回路受潮 | defects | 0.68 | 含 机构箱/二次回路/端子箱/控制回路 **且** 含 受潮/凝露/拒动/误动/直流接地/故障 |
| `DIAG-OLTC` | 有载分接开关异常 | defects | 0.60 | 含 分接开关/有载/OLTC/调压开关 **且** 含 异常/卡涩/拒动/滑挡/连动/油质 |
| `DIAG-COOLING-OVERLOAD` | 冷却系统异常/过负荷 | load | 0.65 | 负载率 > 90% **且** 含 冷却器/风扇/油温/温升/冷却系统 |
| `DIAG-FAMILY-DEFECT` | 家族性缺陷 | defects | 0.62 | 家族缺陷簇设备数 ≥ 3 |
| `DIAG-REPEAT-DEFECT` | 重复性缺陷 | defects | 0.55 | 同部位缺陷数 ≥ 2（时间窗内） |
| `DIAG-INSTALL-QUALITY` | 安装质量问题 | defects | 0.50 | 运行年限 < 1 年 **且** 缺陷数 ≥ 1 |
| `DIAG-PROTECTION-MISOP` | 保护动作/误动核查 | faults | 0.45 | 365 天内有保护动作 **且**（试验不合格/异常 或 故障描述含 保护误动/误动作/越级跳闸） |
| `DIAG-JOINT-OVERHEAT` | 接头/引线过热 | defects | 0.60 | 含 接头/线夹/引线/将军帽/桩头 **且** 含 发热/过热/红外/温度/温升 |
| `DIAG-INSULATION-AGING` | 绝缘老化 | tests | 0.58 | 运行年限 > 20 年 **且**（试验不合格/异常 或 含 绝缘老化/介损超标/绝缘电阻下降） |
| `DIAG-LEDGER-INCOMPLETE` | 台账关键信息缺失 | ledger | 0.40 | model/manufacturer/commissioningDate/deviceType 缺失数 ≥ 2 |
| `DIAG-TEST-GAP` | 修试记录缺失或超期 | tests | 0.42 | 试验记录数 = 0 **或** 最近试验超期 > 1095 天 |

关键词匹配范围默认覆盖 defects/hazards/faults/tests/patrolRecords 中规则声明的段；匹配文本由记录字段拼接，
证据 `data` 中保留 `scope`、`recordId`、命中 `keywords` 与原文 `text`。

## 四、得分与置信度

```
得分 = min(maxScore, base + min(evidenceScoreBonusCap, max(0, 证据数 − 2) × 0.02))
置信度 = clamp(base + evidenceWeight×min(证据数,4) + completenessWeight×完备度, 0.30, 0.95)
```

配置默认：`evidenceScoreBonus=0.02`、`cap=0.10`、`maxScore=0.99`；
`confidence.base=0.25`、`evidenceWeight=0.10`、`evidenceMaxCount=4`、`completenessWeight=0.30`、
`min=0.30`、`max=0.95`。两者均保留 2 位小数。

- 证据数：**去重后**的证据条数（同 scope+recordId 只算一条，关键词合并）；
- 完备度：与健康度一致的 4 段完备度（present/4）；
- 排序：按 `score` 降序，其次 `confidence` 降序，再次 `ruleId`；截断到 `max_hypotheses`。

演示（1号主变）结果：

| # | 假设 | 得分 | 置信度 | 证据数 |
|---|---|---|---|---|
| 1 | 套管受潮/绝缘劣化 | 0.88 | 0.95 | 8 |
| 2 | 重复性缺陷 | 0.55 | 0.65 | 1 |
| 3 | 保护动作/误动核查 | 0.45 | 0.75 | 2 |

> 0.88 = 0.78 + 0.02×5（证据数 8，封顶 +0.10）；置信度 0.95 = clamp(0.25+0.40+0.30×1)。

## 五、缺陷聚类（patterns）

`detect_defect_patterns(defects, device_meta, window_days=365, family_min_count=3)`：

- **重复缺陷簇**：同设备（`deviceName` 或 device_meta.name）+ 同 `part`，窗口内 count ≥ 2；
  输出 `clusterId=DUP-n`、`count`、`defectIds`、`levels`/`statuses` 分布、`firstTime`/`lastTime`；
- **家族性缺陷簇**：同 `model` + `manufacturer` + `part`，`distinct(deviceName)` ≥ `family_min_count`；
  输出 `clusterId=FAM-n`、`deviceCount`、`deviceNames`、`defectIds` 等；
- 窗口：`discoverTime >= asOf − window_days`；未给 as-of 时取最新缺陷发现时间；
- 缺 `part` 归为「未标注部位」并记 `dataGap`；缺 model/manufacturer 无法做家族聚类并记 `dataGap`；
- 排序确定性：重复簇按 count 降序、part、deviceName；家族簇按 deviceCount 降序、model、manufacturer、part。

## 六、缺失证据与数据缺口

- 每条命中假设附带规则声明的 `missingEvidence`（去重）；
- bundle 缺整段（defects/faults/tests/load）时，`missingEvidence` 加「X 数据未提供」类说明，
  `dataGaps` 记 `{section,field,reason}`；
- 无任何假设命中时，`dataGaps` 追加「证据不足」说明，提示补取数据后重跑；
- 低置信度（<0.6）或依赖缺失数据的结论，报告/回答中必须明示，不得当成确定结论。

## 七、扩展规则

只改 `config/diagnosis_rules.json`：

1. 复制一条结构，改 `ruleId`（唯一）、`name`、`dimension`、`score`；
2. 用第二节 DSL 组合条件；关键词要覆盖同义表述（如「渗漏/渗油/漏油」）；
3. 补 `suggestions`、`knowledgeQueries`、`missingEvidence`（中文、可执行、面向业务）；
4. 规则库无代码上限，但测试要求：≥10 条、字段完整、ruleId 唯一、score∈[0,1]；
5. 新增后跑 `python -m unittest discover -s tests`，并同步更新本文件。

> 不要在对话里临时发明规则；规则必须落盘并可复现。
