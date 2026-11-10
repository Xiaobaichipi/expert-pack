# 输入数据包契约（DeviceBundle）

分析引擎的输入是**一个设备数据包（bundle）**：由 Agent 通过数据 MCP（`pms-gateway-mcp` 的 26 个接口）
取数后组装成 JSON。权威 JSON Schema 见 `expert-pack/spec/analysis-bundle.schema.json`。

**设计原则**

1. 只允许 `device` 必填；其余字段可缺省。**缺省不等于 0**：引擎会计入完备度并降低置信度，绝不用推测值补齐。
2. 所有记录保留原始字段（不要改写状态/等级/时间），引擎按既定口径自己归一化。
3. 接口返回的原样记录可直接放入数组；多余字段不会影响计算。
4. `sourceMeta` 用于证据链接口编码：有则优先，无则用内置码表。

## 一、字段总览

```json
{
  "device": {
    "psrId": "PSR-220-0001",
    "assetId": "AST-102-0001",
    "utcNum": "实物ID",
    "name": "1号主变",
    "stationId": "STA-220-01",
    "stationName": "220kV 郑州变电站",
    "voltageLevel": "220kV",
    "deviceType": "变压器",
    "model": "SSZ11-180000/220",
    "manufacturer": "特变电工",
    "commissioningDate": "2016-05-18",
    "capacityMVA": 180,
    "status": "运行"
  },
  "timeWindow": {"start": "2025-10-01", "end": "2026-09-30"},
  "defects": [...],
  "hazards": [...],
  "faults": [...],
  "tests": [...],
  "repairPlans": [...],
  "patrolRecords": [...],
  "load": {...},
  "reliability": {...},
  "sourceMeta": [...]
}
```

### 1.1 device（必填）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| name | string | 是 | 设备名称 |
| psrId | string | 否 | 电网资源 ID |
| assetId | string | 否 | 资产 ID |
| utcNum | string | 否 | 实物 ID |
| stationId | string | 否 | 站 ID |
| stationName | string | 否 | 站名称 |
| voltageLevel | string | 否 | 电压等级，如 `220kV` |
| deviceType | string | 否 | 设备类型，如 `变压器`/`断路器` |
| model | string | 否 | 型号 |
| manufacturer | string | 否 | 生产厂家 |
| commissioningDate | string | 否 | 投运日期 `yyyy-MM-dd` |
| capacityMVA | number | 否 | 容量（MVA，主变） |
| status | string | 否 | 运行状态 |

> 台账维度只看 `model/manufacturer/commissioningDate/deviceType`（各 -10）与
> `assetId`+`psrId` 是否同时缺失（-20）。

### 1.2 timeWindow

`{start,end}`，表示本次取数覆盖范围。`end` 是默认分析时间基准（as-of），用于超期、故障窗口、试验超期等判断。

### 1.3 defects（缺陷，来自 inquire_defect）

| 字段 | 类型 | 说明 |
|---|---|---|
| defectId / defectNo | string | 缺陷编号（证据链使用） |
| level | string | `危急` / `严重` / `一般`（也兼容 `紧急` 等别名的归一化） |
| status | string | `待处理` / `处理中` / `已消除`；也兼容 `已关闭`/`已验收`/`closed` 等，视为闭环 |
| discoverTime | string | 发现时间 |
| closeTime | string | 消除时间 |
| part | string | 缺陷部位（套管/机构箱/本体…），模式聚类使用 |
| desc | string | 缺陷描述，诊断关键词使用 |

### 1.4 hazards（隐患，来自 list_hazard）

`hazardId, type, riskLevel, status, desc`。参与诊断关键词匹配，不直接扣健康分。

### 1.5 faults（故障/跳闸，来自 list_fault_trip_records）

`faultId, time, protectionAction, cause, description`。
故障窗口：距 as-of ≤365 天 -25/次，366–1095 天 -10/次，更早不扣分。

### 1.6 tests（修试/试验，来自 find_repair_test）

`recordId, testType, testDate, result, dataSummary, items[]`。

- `result` ∈ `合格` / `不合格` / `异常`；不合格或异常每条 -30；
- 最近一条 `testDate` 距 as-of 超过 1095 天 -20；
- `dataSummary` 与 `items[].name/value/conclusion` 参与诊断关键词匹配（介损、电容量、绝缘电阻等）。

### 1.7 repairPlans（检修计划，来自 get_repair_plan）

`planId, planName, planTime, status, deviceName`。
计划完成率：`status` 为 已完成/完成/已完工/已竣工/已关闭/done/finished 等，或含「完成/竣工」视为完成；
无计划时完成率为 `0.0`。

### 1.8 patrolRecords（巡视记录，来自 list_patrol_record）

`recordId, patrolTime, result, abnormalities[]`。`abnormalities` 为字符串数组，参与诊断关键词匹配。

### 1.9 load（负载，来自 query_open_capacity）

| 字段 | 类型 | 说明 |
|---|---|---|
| ratedCapacityMVA | number | 额定容量 |
| currentLoadMVA | number | 当前负载 |
| openCapacityMVA | number | 可开放容量 |
| loadRate | number | 负载率百分比，`70` 表示 70% |

缺失 `loadRate` 时由 `currentLoadMVA/ratedCapacityMVA×100` 推导；
缺失 `openCapacityMVA` 时由 `ratedCapacityMVA−currentLoadMVA` 推导。

### 1.10 reliability（可靠性，来自 query_station_scale_analysis）

`availabilityRate, outageHours, outageUserHours, statPeriod`。`availabilityRate` 直接进入指标；
缺失时指标为 `null` 并给出 `dataGap`。

### 1.11 sourceMeta（数据来源元信息，建议填写）

```json
[
  {"interfaceCode":"pgp-102-2411-00102","tool":"get_asset_by_id","calledAt":"2026-09-30T10:00:00+08:00","params":{"psrId":"PSR-220-0001"}},
  {"interfaceCode":"pgp-106-2411-00703","tool":"inquire_defect","calledAt":"2026-09-30T10:01:00+08:00","params":{"psrId":"PSR-220-0001"}}
]
```

证据链 `source` 优先取 `sourceMeta` 中同 `tool` 的 `interfaceCode`；未命中则回退内置码表。
`calledAt` 仅作展示，不参与评分。

## 二、组装示例（最小可用）

```json
{
  "device": {"name": "1号主变", "psrId": "PSR-220-0001", "assetId": "AST-102-0001",
             "model": "SSZ11-180000/220", "manufacturer": "特变电工",
             "commissioningDate": "2016-05-18", "deviceType": "变压器"},
  "timeWindow": {"start": "2025-10-01", "end": "2026-09-30"},
  "defects": [
    {"defectId": "DF-2026-0101", "level": "严重", "status": "处理中",
     "discoverTime": "2026-08-20", "part": "套管", "desc": "套管法兰渗油"}
  ],
  "faults": [],
  "tests": [
    {"recordId": "RT-2026-0101", "testDate": "2026-06-12", "result": "不合格",
     "dataSummary": "套管介损超标"}
  ],
  "load": {"ratedCapacityMVA": 180, "currentLoadMVA": 126, "openCapacityMVA": 54, "loadRate": 70},
  "reliability": {"availabilityRate": 99.982}
}
```

## 三、站级输入

`assess_station_health` / `station-health` 需要同一站的多个 bundle：

```json
{
  "station": {"stationId": "STA-220-01", "stationName": "220kV 郑州变电站", "voltageLevel": "220kV"},
  "bundles": [ {...}, {...} ]
}
```

CLI 也接受直接传入 bundle 数组（此时站名等从首台设备推导）。

## 四、数据缺口的处理方式

| 缺失内容 | 引擎行为 |
|---|---|
| `device` 或 `device.name` | 抛 `BUNDLE_INVALID`（业务错误），提示补齐 |
| `defects` / `faults` / `tests` / `load` 整段缺失 | 该维度按 100 分起算（**不推测扣分**），完备度 -1 段、置信度 -0.05，并写入 `dataGaps` |
| 显式给出空数组（如 `"tests": []`） | 视为「确认无记录」，按「无试验记录」规则 -20；与缺键不同 |
| `timeWindow.end` 且无 `--as-of` | 超期/故障窗口/试验超期等时间规则不执行，写入 `dataGaps` |
| `load` 子字段 | 能按容量推导就推导，否则对应指标 `null` + `dataGap` |
| `reliability` | 可用率 `null` + `dataGap` |
| 缺 `sourceMeta` | 证据链使用内置接口编码，不降低置信度 |

> 组装层不要为了「好看」补 0 或补空对象：空数组代表「确认无记录」，缺键代表「没取到」，
> 两者对完备度和置信度的影响不同。
