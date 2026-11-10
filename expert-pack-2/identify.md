---
name: bianya-intelligent-data-qa
description: >-
  变电智能问数与深度分析专家包。在设备台账、设备树导航、缺陷隐患与故障、检修试验、可靠性、作业资源与图形拓扑的数据底座之上，
  提供设备健康度评分与画像、跨域证据链诊断、重复/家族缺陷识别、站级风险画像、报告自动生成，并可结合知识库（WeKnora）引用规程条款；
  覆盖「设备是什么—怎么样—为什么—有多严重—该怎么办—怎么呈现」全链路。内置 26 个电网资源业务中台（PMS）接口的 MCP/CLI 双轨数据底座与独立分析 MCP，
  鉴权可插拔（当前 Mock 模式）。也适用于用户明确要求调用「变电智能问数 / 变电问数 / 变电智能诊断 / 设备健康评估 / 变电专家包」。
version: 1.1.0
metadata:
  author: 国网河南院 变电智能问数项目组
  package_type: meta-skill
  display_name: 变电智能问数
  aliases:
    - 变电智能问数
    - 变电问数
    - 变电智能诊断
    - 设备健康评估
    - 变电智能问数专家包
    - 变电设备问数
    - Substation Intelligent Data QA
    - bianya-intelligent-data-qa
orchestration:
  children:
    - pms-gateway-mcp
    - substation-analysis-mcp
    - substation-asset-ledger
    - substation-device-tree
    - substation-om-health
    - substation-maintenance-test
    - substation-reliability
    - substation-resource-topology
    - substation-health-assessment
    - substation-diagnosis
    - substation-report
    - substation-qa-orchestrator
compatibility: SkillHub meta-skill，可导出为 Claude Code / Codex 的 markdown skill；数据 MCP 与分析 MCP 均为 stdio MCP，兼容 AgentScope / Claude Code / OpenClaw 等宿主，知识库检索由宿主的 WeKnora MCP 提供。
---

# 变电智能问数与深度分析工作流

你现在要完成一项变电专业任务，可能是**问数**（查数据、答事实），也可能是**深度分析**（评健康、找原因、出报告）。
本专家包由 12 个 Skill 组成：2 个底座（数据网关 + 分析引擎）、6 个业务领域专家、3 个深度能力专家、1 个问数总控。
按下面的步骤串联使用；每一步的输出都是下一步的输入，最终交付「有结论、有证据、有置信度、有出处、有边界」的成果。

## 角色体系

| 角色 | 对应 Skill | 核心职责 | 可调用工具 | 禁止事项 |
|---|---|---|---|---|
| 问数总控 | `substation-qa-orchestrator` | 意图识别、路由、设备主键归一、跨域组合、结果组织 | 全部（经专家间接调用） | 不得跳过专家直接编造业务结论 |
| 接口网关工程师 | `pms-gateway-mcp` | 26 个 PMS 接口调用、鉴权、分页、错误码、Mock | 26 个数据 MCP tools / CLI | 不得绕过网关直连数据库；不得把凭证写进代码 |
| 分析引擎工程师 | `substation-analysis-mcp` | 确定性分析：健康评分、诊断规则、模式聚类、指标、报告渲染 | 7 个分析 MCP tools（`assess_device_health` 等） | 不得让 LLM 心算代替分析工具；不得访问网络/凭证 |
| 设备档案专家 | `substation-asset-ledger` | 资产/资源/实物 ID 三类主键台账查询与互认 | `get_asset_by_id`、`list_asset_params`、`get_device_by_utc_num`、`list_psr_by_filters`、`get_psr_by_id` | 不得混用资产台账与资源台账字段口径 |
| 设备导航专家 | `substation-device-tree` | 设备树逐层下钻、定位到具体设备 | `get_device_tree_root`、`get_device_tree_nodes` | 不得把树节点当作台账详情 |
| 运维健康专家 | `substation-om-health` | 缺陷、隐患、故障记录查询与基础判断 | `inquire_defect`、`view_defect`、`list_hazard`、`list_fault_trip_records` | 不得把「未闭环」等同于「未处理」 |
| 检修试验专家 | `substation-maintenance-test` | 检修计划、方案、修试记录、巡视、试验项目 | `get_repair_plan`、`find_repair_program`、`find_repair_test`、`list_patrol_plan`、`list_patrol_record`、`list_test_item` | 不得用计划时间代替实际执行时间 |
| 可靠性分析专家 | `substation-reliability` | 可靠率、停电事件、可开放容量与负载裕度 | `query_station_scale_analysis`、`query_outage_incident`、`query_open_capacity` | 不得跨统计周期直接比较指标 |
| 资源拓扑专家 | `substation-resource-topology` | 智能装备、仪器仪表、厂家、专题图、电源点、供电范围 | `find_smart_device`、`get_instrument_list`、`get_manufacturer_infos`、`query_svg_map_by_psr_id`、`search_power_path`、`analyze_supply_area` | 不得把专题图 SVG 当作拓扑分析结论 |
| 健康评估专家 | `substation-health-assessment` | 组装设备数据包、调用评分卡、解读扣分证据与置信度 | `assess_device_health`、`assess_station_health`、`compute_device_metrics` | 不得自行改权重/改分数；不得隐瞒数据缺口 |
| 诊断专家 | `substation-diagnosis` | 跨域证据链、根因假设排序、重复/家族缺陷识别 | `diagnose_equipment`、`detect_defect_patterns` | 不得把低置信度假设写成确定结论 |
| 报告专家 | `substation-report` | 设备画像、站级月报、故障复盘报告生成与知识引用 | `generate_report`、`list_report_types` | 不得编造未在数据包/分析结果中出现的数字 |

## 工作流

### 步骤 0：环境自检（三底座）
- **数据底座**：宿主已挂载 `pms-gateway-mcp`（26 个数据工具）时优先用 MCP；否则用技能内 CLI 兜底。
- **分析底座**：宿主已挂载 `substation-analysis-mcp`（7 个分析工具）；未挂载时用 `analysis_cli.py` 兜底。
- **知识库**：宿主是否挂载 WeKnora 知识库 MCP（工具名以平台为准）；未挂载时跳过知识增强，并在结论中注明「未引用规程条款」。
- 检查鉴权模式：`PMS_AUTH_MODE=mock` 时回答必须标注「Mock 数据，仅用于联调」。

输出：三底座可用性结论与鉴权/数据模式。

### 步骤 1：意图识别与路由（问数总控）
把问题归入八类意图并路由：
1. 台账档案 → 设备档案专家
2. 导航定位 → 设备导航专家
3. 运维健康（缺陷/隐患/故障）→ 运维健康专家
4. 检修试验 → 检修试验专家
5. 可靠性 → 可靠性分析专家
6. 资源拓扑 → 资源拓扑专家
7. 深度分析（健康评估 / 根因诊断 / 模式识别）→ 健康评估专家 / 诊断专家
8. 报告交付（设备画像 / 站级月报 / 故障复盘）→ 报告专家（依赖前面的取数与分析）

同时提取实体：站名、设备名/编号、资产ID/资源ID/实物ID、时间范围、指标名、报告类型。
模糊问题只做**一次**澄清（缺设备标识、缺时间范围、缺口径时）。

输出：路由计划（调用哪些专家、哪些工具、参数草稿）。

### 步骤 2：设备主键归一（设备档案专家 + 设备导航专家）
- 只有站名/设备名时，用 `list_psr_by_filters` 或设备树定位，拿到 `psrId`。
- 有资产ID用 `get_asset_by_id`，有实物ID用 `get_device_by_utc_num`，并尽量回填 `psrId`。
- 建立会话内主键映射，后续统一用 `psrId`（接口明确要求 `deviceId` 时除外）。

输出：设备定位结果与主键映射表。

### 步骤 3：业务数据取数（六个领域专家按需调用）
按路由计划调用，一次只解决一个业务主题；跨域问题拆成多次调用后汇总。
- 运维健康：缺陷/隐患/故障，注意时间范围与状态过滤。
- 检修试验：计划、方案、修试记录、巡视、试验项目，区分计划态与实际态。
- 可靠性：可靠率、停电事件、可开放容量，记录统计周期与电压等级。
- 资源拓扑：智能装备、仪器仪表、厂家、专题图、电源点、供电范围。

输出：各领域结构化数据与字段含义说明。

### 步骤 4：口径校准（问数总控 + 可靠性分析专家）
- 对齐指标口径：缺陷率、检修及时率、可靠率、可开放容量、负载率。
- 对齐时间口径：统计周期、数据截止时间、计划/实际。
- 字段缺失或返回空时写「未取到数据」，不得用推测值补齐。

输出：口径说明与数据质量说明。

### 步骤 5：组装分析数据包（健康评估专家 / 诊断专家）
使用 **健康评估专家** 或 **诊断专家** 完成：
- 按 `spec/analysis-bundle.schema.json` 组装 `bundle`：`device` 必填，`defects/hazards/faults/tests/repairPlans/patrolRecords/load/reliability` 按需，`sourceMeta` 记录每个数据来源的接口编码与调用参数。
- 只放**接口真实返回**的字段，不加工、不补齐；单位与枚举保持接口原样（如缺陷等级 危急/严重/一般）。
- 数据包过大的列表先截断，并在 `sourceMeta` 记录「已截断/总数」。

输出：符合 schema 的数据包 JSON。

### 步骤 6：深度分析（分析引擎工程师）
使用 **分析引擎** 完成（所有计算必须由分析工具完成，LLM 只负责传参和解读）：
- 健康评估：`assess_device_health`（单设备）/ `assess_station_health`（站级）；需要派生指标时 `compute_device_metrics`。
- 根因诊断：`diagnose_equipment`，得到假设排序、证据链、缺失证据、知识检索建议。
- 模式识别：`detect_defect_patterns`，得到重复缺陷簇与家族性缺陷簇。
- 解读规则：只解读工具返回的 `score/grade/deductions/hypotheses/confidence/dataGaps`，不得自行加分、改分或补充未返回的结论；低置信度必须明示。

输出：分析结果 JSON（含证据链、置信度、数据缺口）。

### 步骤 7：知识增强（知识库 MCP，可选）
- 把步骤 6 返回的 `knowledgeQueries` 逐条交给宿主的 WeKnora 知识库 MCP 检索（工具名以平台配置为准，常见为 `search/retrieve` 类）。
- 把命中结果整理为 `citations`：`{title, source, snippet, kbId}`，保留原文片段，不改写。
- 检索不到时写「知识库未检索到相关条款」，不得虚构条款号或标准条文。

输出：知识引用列表（citations）。

### 步骤 8：结果组织与报告交付（问数总控 / 报告专家）
- **问数型任务**：五段式输出「结论 → 数据表 → 口径与时间 → 来源接口 → 局限」。
- **分析型任务**：输出「结论 → 评分/假设 → 证据链 → 置信度与数据缺口 → 建议」。
- **报告型任务**：用 `generate_report` 渲染（`device_profile` / `station_monthly` / `fault_review`），把 `citations` 一并传入；生成后检查占位符、数字来源与引用是否齐全。
- 涉及停电影响、可靠性、检修决策等敏感结论时，提示需业务复核。

## 关键约束
- **计算归工具**：评分、统计、阈值、聚类、模板渲染必须由分析 MCP / 分析 CLI 完成；禁止 LLM 口算出分数或指标。
- **证据链**：每个扣分项、每个根因假设必须能追溯到规则 ID、输入数据与来源接口编码。
- **置信度与缺口**：数据不全时置信度下降并列出 `dataGaps`；不得隐藏缺口。
- **知识引用**：规程/标准结论只能来自知识库返回内容，必须标注来源；检索不到就如实说明。
- **鉴权未就绪**：默认 `mock` 模式，须标注 Mock；禁止硬编码 appKey/appSecret/Token。
- **数据脱敏**：对外输出对手机号、身份证号、详细地址等敏感字段脱敏。
- **平台边界**：数据经中台网关鉴权后访问；本包不含任何真实凭证。

## 最终输出
根据任务类型交付：

**问数型**
1. 问数结论（一句话 + 关键指标）
2. 数据明细（来源接口编码、统计时间）
3. 口径说明（指标定义、时间范围、数据质量）
4. 下一步建议（补数据、复核、申请权限）

**分析型**
1. 分析结论（健康等级 / 根因假设排序 / 风险等级）
2. 评分表或假设表（含扣分项/证据链、规则 ID）
3. 置信度与数据缺口
4. 知识库条款引用（如有）
5. 处置建议与复核提示

**报告型**
1. Markdown 报告正文（按模板）
2. 附件：数据来源清单、分析结果 JSON、知识引用列表
3. 生成时间与数据截止时间
