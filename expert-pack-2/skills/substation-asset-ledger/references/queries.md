# 设备档案专家 · 典型问数与参数模板

> 本文件是 `substation-asset-ledger` 的细节层。工具名、参数名以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，示例数据来自 `spec/interfaces.json` 的 `mock` 字段，回答时须标注「Mock 数据，仅用于联调」。

## 一、调用组合速查

| 用户意图 | 工具组合 | 说明 |
|---|---|---|
| 单台设备详情 | `get_asset_by_id` | 资产侧主键最稳 |
| 扫码 / 实物ID | `get_device_by_utc_num` → `get_asset_by_id` | 先定位再补铭牌 |
| 同类设备参数对比 | `list_asset_params` | 按 `assetType` 维度 |
| 站级设备清单 | `list_psr_by_filters` | 按站/电压等级/类型/名称 |
| 资源侧详情 | `get_psr_by_id` | 含拓扑/图形关联字段 |
| 主键互认 | `get_asset_by_id` / `get_device_by_utc_num` / `get_psr_by_id` 交叉 | 两侧都带 `assetId` / `psrId`/ `utcNum` 时互填 |

## 二、典型问数（8 条）

### 问数 1：这台主变是什么型号、容量多少、投运多久了？

- **意图**：台账档案 / 单设备详情
- **工具组合**：`get_asset_by_id`
- **参数模板**：

```json
{"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}}
```

- **字段口径**：
  - `model` 为设备型号（如 SSZ11-180000/220），`capacityMVA` 为额定容量（MVA），两者不可互相推算；
  - `commissioningDate` 为投运日期，投运年限 = 当前年份 − 投运年份（不足一年按不满年说明，不四舍五入成整年）；
  - `voltageLevel` 取铭牌电压等级，与站内实际运行电压等级不一致时应并列说明；
  - `assetStatus`（在运/退役/备用）为资产侧状态，口径以本单位设备状态管理规定为准。
- **输出要点**：一句话结论（1号主变、220kV、SSZ11-180000/220、180MVA、2016-05 投运、约 10 年）；字段表；来源 `pgp-102-2411-00102`。

### 问数 2：全站主变的容量参数分别有哪些？哪个厂家？

- **意图**：台账档案 / 批量对比
- **工具组合**：`list_asset_params`
- **参数模板**：

```json
{"tool": "list_asset_params", "arguments": {"assetType": "transformer", "stationId": "STA-220-01", "voltageLevel": "220kV", "pageNo": 1, "pageSize": 20}}
```

- **字段口径**：
  - `assetType` 为接口路径参数，取值为设备类型标识（示例值 `transformer` / `breaker` / `disconnector`），中文类型名与标识的映射以接口说明文档为准；
  - `capacityMVA` 为单台额定容量，站级合计容量 = 各台容量之和，不含备用主变时应注明；
  - `voltageRatio`（电压比）用于区分三绕组/双绕组，不可用 `voltageLevel` 代替。
- **输出要点**：表格逐台列出资产ID、名称、型号、容量、电压比、厂家；给出合计容量与厂家分布；说明分页总数与是否截断。

### 问数 3：扫这个实物 ID 对应哪台设备、台账如何？

- **意图**：台账档案 / 实物ID 定位
- **工具组合**：`get_device_by_utc_num` →（拿 `assetId`）`get_asset_by_id`
- **参数模板**：

```json
[
  {"tool": "get_device_by_utc_num", "arguments": {"utcNum": "UTC-2020-000123"}},
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}}
]
```

- **字段口径**：
  - `utcNum` 为实物ID（二维码/标签编码），与资产ID、资源ID 不是同一编码体系，不能互相替代；
  - 返回体中若同时含 `assetId`、`psrId`，应写入本次会话主键映射表；
  - 实物ID 未查到设备时，先确认是标签未绑定还是台账未同步，再建议用资产ID/资源ID 兜底。
- **输出要点**：设备身份 + 台账摘要；说明实物ID 与资产ID 的对应关系。

### 问数 4：220kV 郑州变有多少台断路器？型号分布如何？

- **意图**：台账档案 / 设备清单与统计
- **工具组合**：`list_psr_by_filters`（必要时 `get_psr_by_id` 补详情）
- **参数模板**：

```json
{"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "deviceType": "断路器", "voltageLevel": "220kV", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：
  - `total` 为满足条件的总条数，数量结论以 `total` 为准，不要用当前页 `list` 长度代替；
  - `deviceType` 取资源侧设备类型（如「变压器」「断路器」「隔离开关」），与资产侧 `deviceType` 命名可能不同；
  - 型号分布需逐台取 `get_psr_by_id`（资源台账）或配合 `list_asset_params` 才能拿到 `model` 字段。
- **输出要点**：总数 + 分布表（按电压等级/型号）；若 `total` > 当前页条数，明确写出「共 N 台，本次展示前 M 台，可翻页」。

### 问数 5：这个设备的资源台账和接线关系是什么？

- **意图**：台账档案 / 资源侧详情
- **工具组合**：`get_psr_by_id`（需要图时转 `substation-resource-topology`）
- **参数模板**：

```json
{"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0001"}}
```

- **字段口径**：
  - `topoNodeId` 为拓扑节点，`graphicId` 为图形对象，两者是后续专题图与供电分析的桥梁，不等于设备自身ID；
  - 返回中的 `assetId` 可回填资产侧主键，用于跨域查询；
  - 资源台账不保证含铭牌参数，缺 `model`/`capacityMVA` 时需再调资产侧接口，不得留空臆测。

### 问数 6：这个资产ID对应的资源ID 是多少？（主键互认）

- **意图**：主键归一
- **工具组合**：`get_asset_by_id` → `get_psr_by_id`
- **参数模板**：

```json
[
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
  {"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0001"}}
]
```

- **字段口径**：资产侧返回 `psrId`，资源侧返回 `assetId`，两侧互为外键；若一侧缺失，说明台账未关联，需业务侧补录，不得用同名设备硬匹配。
- **输出要点**：主键映射表（assetId / psrId / utcNum / 设备名）；下游查询应统一使用 `psrId`。

### 问数 7：按厂家统计全站设备数量 / 这批断路器是哪个厂家生产的？

- **意图**：台账档案 / 厂家维度统计
- **工具组合**：`list_psr_by_filters`（取清单）→ `get_asset_by_id` 或 `list_asset_params`（取 `manufacturer`）；厂家中英文对照可用 `substation-resource-topology` 的 `get_manufacturer_infos`
- **参数模板**：

```json
[
  {"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_asset_params", "arguments": {"assetType": "breaker", "stationId": "STA-220-01", "pageNo": 1, "pageSize": 100}}
]
```

- **字段口径**：`manufacturer` 为铭牌厂家名称，统计前需归一（简称/全称），归一规则需在回答中写明；统计结论应说明样本是否为全量。

### 问数 8：这台设备退役/备用了吗？还能查它的台账吗？

- **意图**：台账档案 / 状态核查
- **工具组合**：`get_asset_by_id`（`assetStatus`）+ `get_psr_by_id`（资源侧状态）
- **参数模板**：

```json
[
  {"tool": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
  {"tool": "get_psr_by_id", "arguments": {"psrId": "PSR-220-0001"}}
]
```

- **字段口径**：`assetStatus` 为资产状态；资源侧可能另有运行/停役标志，两侧不一致时并列展示并说明「以本单位设备状态管理规定为准」。
- **输出要点**：状态结论 + 两侧字段对照；如已退役，提示后续缺陷/检修类问数可能无数据是正常现象。

## 三、通用注意

1. **先定位后取数**：任何下游业务查询前先确认 `psrId`/`assetId` 已确定，避免用设备名模糊匹配结果直接下结论。
2. **分页必看 `total`**：数量类结论以 `total` 为准，列表展示需注明页码与每页条数。
3. **空结果三选一**：换主键（资产/资源/实物）、放宽条件（去掉电压等级或类型过滤）、说明权限未开通，不得沉默返回。
4. **Mock 标注**：`PMS_AUTH_MODE=mock` 时所有数值均为样例，回答首行标注「Mock 数据，仅用于联调」。
5. **脱敏**：厂家联系人、联系电话、详细地址等字段对外输出脱敏，如 `400-000-0001` → `400-***-0001`。
