# {{title}}

> 报告类型：故障复盘 ｜ 生成时间：{{generatedAt}} ｜ 数据截止：{{asOf}}
>
> 数据说明：本报告由变电分析引擎（substation-analysis-mcp）依据故障、缺陷、试验与诊断结果生成；
> 未取到的数据统一标注「数据未提供」，不得以推测代替现场证据。

## 一、故障概况

| 项目 | 内容 |
|---|---|
| 设备名称 | {{device.name}} |
| 所属变电站 | {{device.stationName}} |
| 故障时间 | {{fault.time}} |
| 保护动作 | {{fault.protectionAction}} |
| 故障原因（记录值） | {{fault.cause}} |
| 故障描述 | {{fault.description}} |

## 二、关联缺陷记录

{{defectsTable}}

## 三、关联修试记录

{{testsTable}}

## 四、根因假设排序（证据链）

{{hypothesesTable}}

### 4.1 缺失证据（需补充核查）

{{missingEvidenceList}}

## 五、处置建议

{{suggestionsList}}

## 六、数据缺口

{{dataGapsList}}

## 七、知识库引用

{{citationsList}}

---

*说明：根因假设按可能性降序排列，置信度受证据条数与数据完备度影响；
低置信度假设不得作为定性结论，需结合保护录波、现场检查与厂家分析复核。*
