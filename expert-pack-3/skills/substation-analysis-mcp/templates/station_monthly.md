# {{title}}

> 报告类型：站级月报 ｜ 统计周期：{{period}} ｜ 生成时间：{{generatedAt}} ｜ 数据截止：{{asOf}}
>
> 数据说明：本报告由变电分析引擎（substation-analysis-mcp）依据各设备数据包批量评分汇总生成；
> 未取到的数据统一标注「数据未提供」，不做推测补齐。

## 一、站级概况

| 项目 | 内容 |
|---|---|
| 变电站 | {{station.stationName}} |
| 变电站ID | {{station.stationId}} |
| 电压等级 | {{station.voltageLevel}} |
| 纳入统计设备数 | {{station.deviceCount}} |

## 二、站级健康画像

- 平均健康分：**{{aggregate.avgScore}}** 分
- 风险设备数（D/E 级）：{{aggregate.criticalCount}}
- 等级分布：{{gradeDistribution}}

### 2.1 风险设备 TopN

{{riskTopTable}}

### 2.2 设备健康明细

{{devicesTable}}

## 三、站级指标

{{metricsTable}}

## 四、数据缺口

{{dataGapsList}}

## 五、知识库引用

{{citationsList}}

---

*说明：站级均分与等级分布由分析引擎计算，风险设备排序为「健康分升序 + 设备名升序」；
处置决策需结合停电计划与现场核查结果复核。*
