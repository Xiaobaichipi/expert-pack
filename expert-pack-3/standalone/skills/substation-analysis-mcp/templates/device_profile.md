# {{title}}

> 报告类型：设备画像 ｜ 生成时间：{{generatedAt}} ｜ 数据截止：{{asOf}}
>
> 数据说明：本报告由变电分析引擎（substation-analysis-mcp）依据输入数据包确定性计算生成；
> 未取到的数据统一标注「数据未提供」，不做推测补齐；所有分数、指标、证据链均来自分析工具输出。

## 一、设备基本情况

| 项目 | 内容 |
|---|---|
| 设备名称 | {{device.name}} |
| 所属变电站 | {{device.stationName}} |
| 电压等级 | {{device.voltageLevel}} |
| 设备类型 | {{device.deviceType}} |
| 型号 | {{device.model}} |
| 生产厂家 | {{device.manufacturer}} |
| 投运日期 | {{device.commissioningDate}} |
| 资源ID | {{device.psrId}} |
| 资产ID | {{device.assetId}} |

## 二、健康度评估

- 健康度得分：**{{health.score}}** 分
- 健康等级：{{health.grade}}（{{health.gradeLabel}}）
- 风险等级：{{health.risk}}
- 置信度：{{health.confidence}}（数据完备度 {{health.completeness.present}}/{{health.completeness.total}}）
- 结论摘要：{{health.summary}}

### 2.1 维度得分

{{dimensionsTable}}

### 2.2 扣分证据链

{{deductionsTable}}

## 三、跨域根因诊断

{{hypothesesTable}}

### 3.1 缺失证据（需补充核查）

{{missingEvidenceList}}

## 四、派生指标

{{metricsTable}}

## 五、数据缺口

{{dataGapsList}}

## 六、知识库引用

{{citationsList}}

---

*说明：本报告中的健康度分数、等级、扣分、指标均由分析引擎计算，报告仅做格式化呈现；
涉及停电、检修与技改决策的结论需专业复核。*
