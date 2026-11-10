# 设备导航专家 · 典型问数与参数模板

> 本文件是 `substation-device-tree` 的细节层。工具名与参数名以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，示例数据来自 `spec/interfaces.json` 的 `mock` 字段，回答时须标注「Mock 数据，仅用于联调」。

## 一、节点类型与下钻路径

| nodeType | 含义 | 典型 nodeId（Mock） | 下一级 |
|---|---|---|---|
| `ORG_ROOT` | 组织机构/区域根 | `ROOT` | `STATION` |
| `STATION` | 变电站 | `STA-220-01` | `VOLTAGE_LEVEL` |
| `VOLTAGE_LEVEL` | 电压等级/间隔层 | `VL-220-01` | `DEVICE` |
| `DEVICE` | 一次设备 | `DEV-220-T1` | `COMPONENT` |
| `COMPONENT` | 设备部件 | `CMP-220-T1-BUSH` | — |

> 上表除 `ORG_ROOT`/`STATION` 的 Mock 节点来自 spec 外，`VOLTAGE_LEVEL`/`DEVICE`/`COMPONENT` 的示例 nodeId 为推断占位，仅用于说明下钻关系。

## 二、典型问数（7 条）

### 问数 1：全局设备树从哪里开始展开？

- **工具组合**：`get_device_tree_root` → `get_device_tree_nodes`
- **参数模板**：

```json
[
  {"tool": "get_device_tree_root", "arguments": {}},
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "ROOT", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：`nodeId` 为树内唯一键；`childrenCount` 为直接下级数量（不是整棵子树设备总数）；`nodeType=ORG_ROOT` 表示导航根。
- **输出要点**：根节点信息 + 一级节点清单；说明「整树设备总数需逐层统计，本接口不直接返回」。

### 问数 2：这个地区有哪些变电站？

- **工具组合**：`get_device_tree_nodes`（带 `nodeType=STATION`）
- **参数模板**：

```json
{"tool": "get_device_tree_nodes", "arguments": {"parentId": "ORG-HN-01", "nodeType": "STATION", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：`hasChildren=true` 表示还有下级（电压等级/设备）；站名以 `nodeName` 为准，用户口语简称需在回答中标注映射关系。
- **输出要点**：站清单表（站名 | 节点ID | 是否有下级）+ 计数；超过一页时注明总数。

### 问数 3：进入某站后下面挂哪些一次设备？

- **工具组合**：`get_device_tree_nodes`（`VOLTAGE_LEVEL` → `DEVICE`）
- **参数模板**：

```json
[
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "STA-220-01", "nodeType": "VOLTAGE_LEVEL", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "VL-220-01", "nodeType": "DEVICE", "pageNo": 1, "pageSize": 50}}
]
```

- **字段口径**：设备清单只含节点级信息（名称、类型、是否有部件），型号/容量等铭牌参数须转 `substation-asset-ledger` 查询。
- **输出要点**：按电压等级分组列出设备；设备数很多时按类型聚合计数并提示可下钻。

### 问数 4：这台设备属于哪个站、哪个电压等级？

- **工具组合**：逐层下钻比对，或用 `list_psr_by_filters` 反查归属
- **参数模板**：

```json
[
  {"tool": "get_device_tree_root", "arguments": {}},
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "STA-220-01", "nodeType": "DEVICE", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_psr_by_filters", "arguments": {"name": "1号主变", "pageNo": 1, "pageSize": 20}}
]
```

- **字段口径**：设备树只表达层级归属，不表达运行归属/调度关系；资源侧 `stationName`、`voltageLevel` 字段可交叉验证。
- **输出要点**：输出归属路径（站 → 电压等级 → 设备）+ 交叉验证结论；两侧不一致时并列说明。

### 问数 5：某站 220kV 有多少个间隔/多少台设备？

- **工具组合**：`get_device_tree_nodes`（多次分页）
- **参数模板**：

```json
{"tool": "get_device_tree_nodes", "arguments": {"parentId": "STA-220-01", "nodeType": "DEVICE", "pageNo": 1, "pageSize": 100}}
```

- **字段口径**：设备数量以接口 `total` 为准；「间隔」在树中可能不是独立 `nodeType`，需说明按设备节点计数近似。
- **输出要点**：数量 + 按类型分布；明确「间隔数」与「设备台数」不是同一口径。

### 问数 6：这台主变由哪些部件组成？

- **工具组合**：`get_device_tree_nodes`（`nodeType=COMPONENT`）
- **参数模板**：

```json
{"tool": "get_device_tree_nodes", "arguments": {"parentId": "DEV-220-T1", "nodeType": "COMPONENT", "pageNo": 1, "pageSize": 50}}
```

- **字段口径**：部件节点用于定位缺陷部位（如「本体/套管」）；部件名称与缺陷记录中的 `part` 字段需人工/规则对齐。
- **输出要点**：部件清单表；后续可结合 `substation-om-health` 的缺陷 `part` 字段定位。

### 问数 7：只给了站名，帮我找到站里的 1 号主变并继续查缺陷

- **工具组合**：`get_device_tree_root` → `get_device_tree_nodes`（找站）→ `get_device_tree_nodes`（找设备）→ `list_psr_by_filters` → 转 `substation-om-health`
- **参数模板**：

```json
[
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "ROOT", "nodeType": "STATION", "pageNo": 1, "pageSize": 50}},
  {"tool": "get_device_tree_nodes", "arguments": {"parentId": "STA-220-01", "nodeType": "DEVICE", "pageNo": 1, "pageSize": 100}},
  {"tool": "list_psr_by_filters", "arguments": {"stationId": "STA-220-01", "deviceType": "变压器", "name": "1号主变", "pageNo": 1, "pageSize": 20}}
]
```

- **字段口径**：导航阶段拿到的 `nodeId` 不能直接当 `deviceId`/`psrId`；必须经台账接口换取主键后再查业务数据。
- **输出要点**：定位过程摘要 + 最终设备主键；后续缺陷查询参数由 `substation-om-health` 给出。

## 三、通用注意

1. **层级优先**：先确定站，再确定电压等级，最后确定设备；用户说的「某站」可能同名，需用电压等级或地区消歧。
2. **分页必看 `total`**：数量结论以 `total` 为准，不用当前页条数代替。
3. **下钻有上限**：最多 5 层/20 次调用，超限时返回候选与当前层级，请用户补充条件。
4. **不做台账结论**：树节点字段不能替代 `model`/`capacityMVA`/`commissioningDate` 等台账字段。
5. **Mock 标注**：任何节点清单均标注「Mock 数据，仅用于联调」。
6. **脱敏**：节点若含责任人/联系电话，输出时脱敏。
