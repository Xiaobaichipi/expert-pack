# 问数总控 · 意图路由与跨域组合

> 本文件是 `substation-qa-orchestrator` 的路由细节层。工具名与参数名以 `spec/interfaces.json` 为唯一事实源。
> 当前鉴权模式 `mock`，所有示例数据为联调样例，回答须标注「Mock 数据，仅用于联调」。

## 一、意图识别信号词

| 意图 | 高置信信号词 | 易混淆点 |
|---|---|---|
| ① 台账档案 | 型号、容量、厂家、投运、铭牌、台账、几台、多少台 | 「容量」在可靠性域问的是可开放容量，需看是否有「还能带」「裕度」 |
| ② 导航定位 | 设备树、在哪、下面挂、逐层、间隔、归属 | 「找设备」若已给明确主键则不导航，直接查台账 |
| ③ 运维健康 | 缺陷、危急、严重、隐患、跳闸、故障、保护动作、健康 | 「消缺」既是缺陷也是检修动作，按主语判定 |
| ④ 检修试验 | 检修计划、方案、修试、试验、巡视、标准、周期 | 「什么时候修过」= 修试记录（执行态），不是检修计划 |
| ⑤ 可靠性 | 可靠率、可用率、停电事件、时户数、可开放容量、负载率 | 「停电」也可能是检修计划停电，需并列说明 |
| ⑥ 资源拓扑 | 智能装备、在线监测、机器人、仪器、检定、厂家、接线图、电源、影响范围 | 「厂家」也可由台账字段直接给出，优先台账 |

## 二、六类意图路由表（工具级）

| 意图 | 技能 | 首选工具 | 关键参数 | 备用工具 |
|---|---|---|---|---|
| 台账档案-单设备 | `substation-asset-ledger` | `get_asset_by_id`（pgp-102-2411-00102） | `assetId` | `get_psr_by_id`（pgp-101-2411-00103） |
| 台账档案-设备清单 | `substation-asset-ledger` | `list_psr_by_filters`（pgp-101-2411-00102） | `stationId`、`deviceType`、`voltageLevel`、`name` | `list_asset_params`（pgp-102-2411-00101，按 `assetType`） |
| 台账档案-扫码 | `substation-asset-ledger` | `get_device_by_utc_num`（pgp-102-2411-00103） | `utcNum` | `get_asset_by_id`（pgp-102-2411-00102） |
| 导航定位 | `substation-device-tree` | `get_device_tree_nodes`（pgp-101-2411-00503） | `parentId`、`nodeType` | `get_device_tree_root`（pgp-101-2411-00501，`orgId`） |
| 运维健康-缺陷 | `substation-om-health` | `inquire_defect`（pgp-106-2411-00703） | `stationId`/`deviceId`、`defectLevel`、`status`、`startTime`/`endTime` | `view_defect`（pgp-106-2411-00704，`defectId`） |
| 运维健康-隐患 | `substation-om-health` | `list_hazard`（pgp-106-2411-01003） | `stationId`、`hazardType`、`riskLevel`、`status` | — |
| 运维健康-故障 | `substation-om-health` | `list_fault_trip_records`（pgp-106-2411-02603） | `deviceId`、`stationId`、`startTime`/`endTime` | — |
| 检修-计划 | `substation-maintenance-test` | `get_repair_plan`（pgp-106-2411-04206） | `deviceId`/`stationId`、`year`、`month`、`planStatus` | `find_repair_program`（pgp-106-2411-04803） |
| 检修-执行 | `substation-maintenance-test` | `find_repair_test`（pgp-106-2411-05003） | `deviceId`、`startTime`/`endTime` | `list_test_item`（pgp-106-2411-06801，标准） |
| 检修-巡视 | `substation-maintenance-test` | `list_patrol_plan`（pgp-106-2411-00303）/ `list_patrol_record`（pgp-106-2411-00403） | `stationId`、`startDate`/`endDate`、`status` | — |
| 可靠性-指标 | `substation-reliability` | `query_station_scale_analysis`（pgp-108-2411-00405） | `stationId`、`startDate`/`endDate` | — |
| 可靠性-停电 | `substation-reliability` | `query_outage_incident`（pgp-108-2411-00502） | `stationId`、`voltageLevel`、`startTime`/`endTime` | — |
| 可靠性-容量 | `substation-reliability` | `query_open_capacity`（pgp-108-2411-00201） | `deviceId`、`stationId`、`voltageLevel` | — |
| 拓扑-资源 | `substation-resource-topology` | `find_smart_device`（pgp-105-2411-00602）/ `get_instrument_list`（pgp-105-2411-00403）/ `get_manufacturer_infos`（pgp-102-2411-00701） | `stationId`、`deviceType`、`instrumentType`、`manufacturerName` | 台账侧 `manufacturer` 字段 |
| 拓扑-图形 | `substation-resource-topology` | `query_svg_map_by_psr_id`（pgp-103-2411-00502） | `psrId` | `get_psr_by_id`（pgp-101-2411-00103，取 `graphicId`） |
| 拓扑-供电 | `substation-resource-topology` | `search_power_path`（pgp-104-2411-00101） | `psrId`（或 `deviceId`） | — |
| 拓扑-影响 | `substation-resource-topology` | `analyze_supply_area`（pgp-104-2411-00301） | `psrId`（或 `deviceId`）、`direction` | `search_power_path`（pgp-104-2411-00101） |

## 三、路由执行五条规则

1. **单一意图优先**：问题只命中一类意图时，直接交对应技能，不叠加跨域分析。
2. **复合意图拆解**：命中 2 类以上意图时，按「主键归一 → 台账/导航 → 业务域 → 跨域组合」顺序串行，逐个主题取数。
3. **消歧优先于取数**：主键不确定、时间窗缺失、口径不明时先走一次澄清（见第六节），或给出默认值并标注。
4. **依赖先于主线**：需要 `psrId` 才能查的业务，必须先完成台账/导航取主键，禁止用设备名模糊结果直接下发。
5. **失败不静默**：任一工具失败，记录失败接口编码与原因，继续其余可取部分，最终在「局限」段说明缺哪块。

## 四、跨域组合套路

### 套路 1：主变健康画像

**用户问法**：「1 号主变健康画像 / 这台主变整体情况怎么样 / 给我一份主变运行健康报告」

| 步骤 | 技能 | 工具与参数 | 产出 |
|---|---|---|---|
| 1 | `substation-asset-ledger` | `get_asset_by_id {"assetId":"AST-102-0001"}` | 铭牌、投运年限、状态 |
| 2 | `substation-om-health` | `inquire_defect {"deviceId":"PSR-220-0001","startTime":"2024-10-26","endTime":"2026-10-26","pageNo":1,"pageSize":100}` | 缺陷等级/部位分布 |
| 3 | `substation-om-health` | `list_fault_trip_records {"deviceId":"PSR-220-0001","startTime":"2024-10-26","endTime":"2026-10-26","pageNo":1,"pageSize":50}` | 跳闸与保护动作 |
| 4 | `substation-om-health` | `list_hazard {"stationId":"STA-220-01","pageNo":1,"pageSize":50}` | 站级隐患（外部隐患常无设备维度） |
| 5 | `substation-maintenance-test` | `find_repair_test {"deviceId":"PSR-220-0001","startTime":"2018-01-01","endTime":"2026-10-26","pageNo":1,"pageSize":100}` | 修试历史与试验数据趋势 |
| 6 | `substation-maintenance-test` | `get_repair_plan {"deviceId":"PSR-220-0001","year":2026,"pageNo":1,"pageSize":20}` | 后续检修安排 |
| 7 | `substation-reliability` | `query_open_capacity {"deviceId":"AST-102-0001","pageNo":1,"pageSize":20}` | 负载率与可开放容量 |
| 8 | `substation-resource-topology` | `query_svg_map_by_psr_id {"psrId":"PSR-220-0001"}`、`search_power_path {"psrId":"PSR-220-0001"}` | 接线图 + 上级电源与链路 |

**结论组织**：健康结论（风险点排序：危急缺陷 > 重复故障 > 严重缺陷 > 试验数据劣化 > 负载率偏高）→ 各表 → 口径 → 来源 → 局限与建议（专项检查、纳入检修计划、申请量测接口）。

**易错点**：隐患无设备维度时不得算入设备画像；可开放容量用资产ID（示例 mock 的 `deviceId`），不要拿 `psrId` 直接查。

### 套路 2：停电影响分析

**用户问法**：「1 号主变停电会影响谁 / 这台设备检修停电范围多大 / 停电风险如何」

| 步骤 | 技能 | 工具与参数 | 产出 |
|---|---|---|---|
| 1 | `substation-asset-ledger` | `get_psr_by_id {"psrId":"PSR-220-0001"}` | 主键与拓扑/图形关联 |
| 2 | `substation-resource-topology` | `search_power_path {"psrId":"PSR-220-0001"}` | 上级电源与供电链路 |
| 3 | `substation-resource-topology` | `analyze_supply_area {"psrId":"PSR-220-0001","direction":"outage"}` | 受影响站/用户/风险等级 |
| 4 | `substation-reliability` | `query_open_capacity {"stationId":"STA-220-01","voltageLevel":"10kV","pageNo":1,"pageSize":50}` | 受影响容量 |
| 5 | `substation-reliability` | `query_outage_incident {"stationId":"STA-220-01","startTime":"2023-01-01","endTime":"2026-10-26","pageNo":1,"pageSize":100}` | 历史同类停电佐证 |
| 6 | `substation-maintenance-test` | `get_repair_plan {"stationId":"STA-220-01","year":2026,"pageNo":1,"pageSize":50}` | 是否已有计划停电安排 |

**结论组织**：影响范围（站/台区/用户）→ 风险等级 → 历史佐证 → 差异说明 → **必须写「静态拓扑推演，未计转供/保护动作/备自投，需业务复核」**。

### 套路 3：检修及时率

**用户问法**：「今年检修及时率多少 / 缺陷有没有按时消除 / 检修计划完成得怎么样」

| 步骤 | 技能 | 工具与参数 | 产出 |
|---|---|---|---|
| 1 | `substation-om-health` | `inquire_defect {"stationId":"STA-220-01","startTime":"2026-01-01","endTime":"2026-10-26","pageNo":1,"pageSize":200}` | 应消缺项与等级时限 |
| 2 | `substation-maintenance-test` | `get_repair_plan {"stationId":"STA-220-01","year":2026,"pageNo":1,"pageSize":200}` | 计划态与完成态 |
| 3 | `substation-maintenance-test` | `find_repair_test {"deviceId":"PSR-220-0001","startTime":"2026-01-01","endTime":"2026-10-26","pageNo":1,"pageSize":100}` | 实际执行证据 |
| 4 | 口径校准 | 分子/分母、时限判据 | 及时率与超期清单 |

**口径要点**：
- 检修及时率 = 按时完成项数 ÷ 应完成项数 ×100%；「按时」判据按时限：危急缺陷 24 小时内消除（**以本单位缺陷管理规程为准**），严重/一般按期限制。
- 计划完成率分母**只计截至统计日应执行完的计划**，未到期计划不计入分母，否则指标失真。
- `planStatus=已完成` 是计划态，须与 `find_repair_test` 实际记录交叉验证后才可称「已执行」。

### 套路 4：站级可靠性概览

**用户问法**：「某站可靠性怎么样 / 这个站运行水平如何 / 站级运行概览」

| 步骤 | 技能 | 工具与参数 | 产出 |
|---|---|---|---|
| 1 | `substation-reliability` | `query_station_scale_analysis {"stationId":"STA-220-01","startDate":"2026-01-01","endDate":"2026-09-30","pageNo":1,"pageSize":20}` | 可用率、停电小时、时户数、次数 |
| 2 | `substation-reliability` | `query_outage_incident {"stationId":"STA-220-01","startTime":"2026-01-01","endTime":"2026-09-30","pageNo":1,"pageSize":100}` | 事件明细与成因 |
| 3 | `substation-om-health` | `list_fault_trip_records {"stationId":"STA-220-01","startTime":"2026-01-01","endTime":"2026-09-30","pageNo":1,"pageSize":50}` | 故障跳闸佐证 |
| 4 | `substation-asset-ledger` | `list_psr_by_filters {"stationId":"STA-220-01","pageNo":1,"pageSize":1}` | 设备规模（缺陷率分母） |
| 5 | `substation-om-health` | `inquire_defect {"stationId":"STA-220-01","startTime":"2026-01-01","endTime":"2026-09-30","pageNo":1,"pageSize":200}` | 缺陷情况 |

**结论组织**：指标表（含 `statPeriod` 原值）→ 成因分解（计划/故障）→ 与缺陷故障交叉 → 口径与局限（周期不完整、口径与考核口径不同）。

### 组合套路选择表

| 用户关键词 | 推荐套路 | 最少必要工具数 |
|---|---|---|
| 健康画像、整体情况、综合评价 | 套路 1 | 6–8 |
| 停电影响、影响范围、检修停电 | 套路 2 | 4–6 |
| 检修及时率、计划完成率、按时 | 套路 3 | 3–4 |
| 可靠性、运行水平、停电次数 | 套路 4 | 4–5 |
| 单一事实型（型号/几台/有没有计划） | 不组合，单技能直答 | 1–2 |

## 五、主键归一与串接规则（补充）

1. **映射表先行**：进入业务域前把 `assetId`/`psrId`/`utcNum` 与设备名写入映射表，全链路复用。
2. **`deviceId` 语义**：缺陷、故障、检修、巡视类接口的 `deviceId` 可传资产ID 或资源ID；同一回答内统一一种，跨接口变更须说明。
3. **`psrId` 优先域**：`query_svg_map_by_psr_id`、`search_power_path`、`analyze_supply_area` 以 `psrId` 为准；`query_open_capacity` 的示例 `deviceId` 为资产ID。
4. **主键拿不到时**：走设备树逐层下钻 + `list_psr_by_filters` 检索；仍拿不到时返回候选请求用户确认，不进入业务域。
5. **两套台账冲突**：资产侧与资源侧对同一设备的名称/电压等级/状态不一致时并列展示，标注来源接口，禁止择一隐瞒。

## 六、澄清话术（一次澄清原则）

| 缺失项 | 话术 |
|---|---|
| 设备标识 | 「请给设备名称+变电站，或资产ID/资源ID/实物ID；不确定的话我先按『220kV 郑州变 1号主变』示例演示。」 |
| 时间范围 | 「默认按最近 12 个月（2025-10-26 至 2026-10-26）统计，可以吗？也可指定年度/月份。」 |
| 指标口径 | 「『可靠率』按站级可用率（availabilityRate）还是供电可靠率（RS-1）？默认站级可用率。」 |
| 范围指代 | 「『全站设备』是否含 10kV 侧？默认按 220kV 主变与断路器统计。」 |
| 复合诉求 | 「涉及台账、缺陷、检修、可靠性四块，我先给结论与关键指标，再逐块展开。」 |
| 数据权限 | 「该接口需中台鉴权，当前为 Mock 模式；如需真实数据，请先申请对应接口权限。」 |

**写法要求**：一次最多问 2 个问题；能查到的不问；给出默认值；澄清后立即执行，不再二次追问。

## 七、冲突与异常处理

| 情况 | 处理 |
|---|---|
| 指标接口与事件明细不一致 | 以指标接口为统计口径，事件明细作佐证，差异 >10% 写入局限 |
| 计划态已完成但无修试记录 | 表述「计划标记已完成，但未查询到对应修试记录，需业务核实」 |
| 台账状态与运行状态不一致 | 两侧并列，标注「以本单位设备状态管理规定为准」 |
| 部分接口失败 | 继续可取部分，输出「已取到/未取到」清单，失败接口编码写入局限 |
| 一切为空 | 提示换主键（资产/资源/实物）、放宽时间窗、确认权限，不下「无风险」结论 |
