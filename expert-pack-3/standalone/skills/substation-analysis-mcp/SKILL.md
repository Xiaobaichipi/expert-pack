---
name: substation-analysis-mcp
slug: substation-analysis-mcp
displayName: 变电分析引擎（健康度/诊断/报告）
description: >-
  变电智能问数分析引擎底座：把「设备数据包（bundle）」做确定性计算，输出设备健康度评分、跨域证据链诊断、
  重复/家族缺陷识别、站级健康画像、派生指标与 Markdown 报告（设备画像 / 站级月报 / 故障复盘）。
  7 个分析工具（assess_device_health、assess_station_health、diagnose_equipment、detect_defect_patterns、
  compute_device_metrics、generate_report、list_report_types）提供 MCP（stdio）/ CLI / Python 三轨调用，
  每个扣分与根因假设都带证据链（规则ID/依据数据/接口编码）、置信度与 dataGaps，并给出 knowledgeQueries
  供知识库（WeKnora）检索规程条款。
  触发词：设备健康度、健康评分、设备画像、健康等级、扣分证据、置信度、数据完备度、根因诊断、证据链、故障复盘、
  重复缺陷、家族性缺陷、缺陷聚类、站级健康画像、风险设备、派生指标、缺陷率、超期未消缺、可开放容量比、可用率、
  设备画像报告、站级月报、故障复盘报告、报告生成、评分卡、诊断规则库。
  也适用于用户明确要求调用「substation-analysis-mcp / 分析引擎 / 分析底座 / 变电分析 MCP」。
version: 1.1.0
metadata:
  author: 国网河南院 变电智能问数项目组
  package_type: skill
  display_name: 变电分析引擎（健康度/诊断/报告）
  category: analysis-engine
  tags:
    - 变电问数
    - 健康度评分
    - 证据链诊断
    - 缺陷聚类
    - 站级画像
    - 报告生成
    - mcp
    - 确定性计算
  compatibility: 纯 Python 3.10+ 标准库；MCP 协议 2024-11-05（stdio、换行分隔 JSON-RPC 2.0）；无网络、无凭证。
---

# 变电分析引擎（substation-analysis-mcp）

**角色**：分析引擎工程师。你负责把上游数据 MCP 取回的数据组装成 **bundle**，交给本引擎做**确定性计算**，
再解读引擎返回的分数、假设、证据链、置信度与数据缺口。

> **铁律**：LLM 不做计算。评分、阈值、统计、聚类、模板渲染必须由本技能的 MCP 工具或 CLI 完成；
> 不得口算分数、不得改权重、不得编造未在返回结果中出现的数字或条款。

## 何时使用本技能

- 需要给单台设备**评健康度**、拿扣分证据与置信度时 → `assess_device_health`
- 需要一个站多台设备的**站级画像、等级分布、风险设备 TopN** 时 → `assess_station_health`
- 需要**根因假设排序、证据链、缺失证据、下一步核查建议**时 → `diagnose_equipment`
- 需要识别**同部位重复缺陷、同型号同厂家家族性缺陷**时 → `detect_defect_patterns`
- 需要**缺陷率、危急未闭环、超期未消缺、计划/修试完成率、负载率、可开放容量比、可用率**时 → `compute_device_metrics`
- 需要输出**设备画像 / 站级月报 / 故障复盘** Markdown 报告，并附知识库引用时 → `generate_report` / `list_report_types`

数据取数请先走 `pms-gateway-mcp`（26 个数据接口）；本技能只读 bundle，**不访问网络、不读凭证、不读系统时钟**
（报告 `generatedAt` 除外；时间基准用 `bundle.timeWindow.end` 或 CLI `--as-of`）。

## 一、能力清单（7 个工具）

| 工具 | 作用 | 关键返回 |
|---|---|---|
| `assess_device_health` | 单设备健康度评分 | score/grade/gradeLabel/risk/dimensions/deductions/completeness/confidence/summary/knowledgeQueries |
| `assess_station_health` | 站级健康画像 | station/devices/aggregate{avgScore,gradeDistribution,riskTop,criticalCount}/knowledgeQueries |
| `diagnose_equipment` | 跨域证据链诊断 | hypotheses（按 score 降序）/patterns/missingEvidence/dataGaps |
| `detect_defect_patterns` | 重复/家族缺陷识别 | duplicateClusters/familyClusters/summary |
| `compute_device_metrics` | 派生指标 | metrics（9 项）/denominators/dataGaps |
| `generate_report` | 报告渲染 | reportType/title/markdown/sections/generatedAt |
| `list_report_types` | 报告模板清单 | reportTypes[{type,name,requiredPayloadKeys}] |

完整参数、返回示例与错误码见 [`references/tools.md`](references/tools.md)；输入契约见
[`references/bundle-schema.md`](references/bundle-schema.md)（与专家包 `spec/analysis-bundle.schema.json` 一致）。

## 二、三种用法

### 2.1 MCP 宿主挂载（推荐）

宿主以 stdio 方式拉起脚本即可，**无需 PYTHONPATH**（脚本自行处理导入路径）：

```bash
python skills/substation-analysis-mcp/scripts/analysis_mcp.py
```

- 协议：JSON-RPC 2.0，**一行一条消息**，UTF-8；`stdout` 只输出协议消息，日志全部走 `stderr`；
- 方法：`initialize`（protocolVersion=2024-11-05）、`notifications/initialized`、`ping`、`tools/list`、`tools/call`；
- `tools/call` 返回 `content:[{type:"text", text:<JSON字符串>}]` 与 `isError`；
- 错误码：`-32700` 解析失败、`-32600` 非法请求、`-32601` 未知方法、`-32602` 参数错误、`-32603` 内部错误；
- **业务数据错误**（如 bundle 不合法）不抛协议错误，而是在 `tools/call` 结果里返回 `isError=true` 与
  `{"error":{"code":"BUNDLE_INVALID","message":"..."}}`，便于模型纠正输入后重试。

### 2.2 CLI（无 MCP 宿主时兜底 / 联调 / 演示）

```bash
# 一条命令跑通 健康+诊断+模式+指标+报告，并打印摘要（演示首选）
python skills/substation-analysis-mcp/scripts/analysis_cli.py demo

python skills/substation-analysis-mcp/scripts/analysis_cli.py health      --bundle bundle.json
python skills/substation-analysis-mcp/scripts/analysis_cli.py diagnose    --bundle bundle.json --max-hypotheses 5
python skills/substation-analysis-mcp/scripts/analysis_cli.py patterns    --bundle bundle.json --window-days 365
python skills/substation-analysis-mcp/scripts/analysis_cli.py metrics     --bundle bundle.json
python skills/substation-analysis-mcp/scripts/analysis_cli.py station-health --bundle station_bundles.json
python skills/substation-analysis-mcp/scripts/analysis_cli.py report      --type device_profile --bundle bundle.json
python skills/substation-analysis-mcp/scripts/analysis_cli.py report      --type device_profile --payload payload.json
python skills/substation-analysis-mcp/scripts/analysis_cli.py list-report-types
```

- `--bundle -` 从 stdin 读；`--as-of yyyy-MM-dd` 覆盖时间基准；`--compact` 输出单行 JSON；
- 输出 UTF-8 JSON（`ensure_ascii=False`）；退出码：`0` 成功、`1` 运行/数据错误、`2` 用法错误。

### 2.3 Python 直接调用（脚本/单测）

```python
import json, sys
sys.path.insert(0, "skills/substation-analysis-mcp/scripts")
from analysis import assess_device_health, diagnose_equipment

bundle = json.load(open("skills/substation-analysis-mcp/assets/demo_bundle.json", encoding="utf-8"))
health = assess_device_health(bundle)          # 或 assess_device_health(bundle, as_of="2026-09-30")
diagnosis = diagnose_equipment(bundle)
```

## 三、评分卡（摘要）

| 维度 | 权重 | 主要扣分规则 |
|---|---|---|
| 缺陷 | 0.30 | 危急未闭环 -30/项、严重 -15/项、一般 -5/项；超期未消缺 -10/项（危急>1天/严重>7天/一般>30天）；已消除不计 |
| 故障 | 0.25 | 近 12 个月 -25/次；13-36 个月 -10/次 |
| 修试 | 0.20 | 无试验记录 -20；最近试验超期（默认 1095 天）-20；结果不合格/异常 -30/条 |
| 负载 | 0.15 | 负载率>90 -20、>80 -10；可开放容量比<5% -10 |
| 台账 | 0.10 | 关键字段缺失（model/manufacturer/commissioningDate/deviceType）-10/项；assetId 与 psrId 均缺失 -20 |

- 每维从 100 分起扣，单维上限 100；总分 = Σ(维度权重×维度得分)，保留 1 位小数；
- 等级：A≥90（健康/低）、B≥80（良好/低）、C≥70（注意/中）、D≥60（预警/较高）、E<60（严重/高）；
- 置信度：base 0.9 − 0.05×缺失数据段数（最多 −0.4）− 0.1×数据截止晚于 as-of 超 180 天，clamp 到 [0.30, 0.95]，
  同时输出 completeness（present/total）；
- 每个扣分项输出 `{ruleId, dimension, delta, reason, source:[接口编码], data}`。

权重与阈值全部在 [`config/scorecard.json`](config/scorecard.json)，**改评分口径只改配置，不改代码**。
详见 [`references/scorecard.md`](references/scorecard.md)。

## 四、诊断规则库（摘要）

12 条规则（可配置、可扩展），全部基于关键词/阈值/年限/统计/聚类的**组合条件**：

套管受潮、机构箱受潮、有载分接开关异常、冷却系统/过负荷、家族性缺陷、重复缺陷、
安装质量问题、保护动作/误动核查、接头过热、绝缘老化、台账关键信息缺失、修试记录缺失或超期。

- 输出 `hypotheses`：按 score 降序，含 `ruleId/name/score/confidence/evidence/suggestions/knowledgeQueries/missingEvidence`；
- 置信度 = base 0.25 + 0.10×min(证据数,4) + 0.30×数据完备度，clamp [0.30, 0.95]；
- 附带 `patterns`（重复/家族缺陷簇）、`missingEvidence`、`dataGaps`。

条件 DSL 与规则清单见 [`references/diagnosis-rules.md`](references/diagnosis-rules.md)，
配置在 [`config/diagnosis_rules.json`](config/diagnosis_rules.json)。

## 五、报告模板

| 类型 | 名称 | 必需 payload 键 | 模板 |
|---|---|---|---|
| `device_profile` | 设备画像报告 | `device`、`health` | [`templates/device_profile.md`](templates/device_profile.md) |
| `station_monthly` | 站级月报 | `station`、`aggregate` | [`templates/station_monthly.md`](templates/station_monthly.md) |
| `fault_review` | 故障复盘报告 | `fault` | [`templates/fault_review.md`](templates/fault_review.md) |

- 占位符语法 `{{点分路径}}`（如 `{{health.score}}`），表格/清单由 Python 预渲染；
- payload 缺键时渲染为「数据未提供」并写入 `dataGaps`，**报告生成不失败**；
- `citations` 渲染为引用列表，无引用时写「知识库未检索到相关条款」；
- 渲染后不残留 `{{占位符}}`；
- 报告专家应把 `knowledgeQueries` 交给 WeKnora 知识库检索，命中结果整理为 `citations` 再传入。

详见 [`references/report-templates.md`](references/report-templates.md)。

## 六、目录结构

```
skills/substation-analysis-mcp/
├── SKILL.md
├── config/
│   ├── scorecard.json          # 评分卡（维度权重/阈值/等级/置信度）
│   └── diagnosis_rules.json    # 诊断规则库（条件 DSL）
├── templates/                  # 3 类报告 Markdown 模板
├── assets/demo_bundle.json     # 演示数据包（1号主变：套管渗油+跳闸+不合格试验+负载 70%）
├── scripts/
│   ├── analysis/               # 核心包：config/evidence/health/diagnosis/patterns/metrics/report
│   ├── analysis_mcp.py         # MCP Server（stdio JSON-RPC 2.0，7 工具）
│   └── analysis_cli.py         # CLI（health|diagnose|patterns|metrics|report|demo...）
└── references/                 # 契约与口径文档（tools/bundle-schema/scorecard/diagnosis-rules/report-templates）
```

## 七、输出与解读约定

1. **结论先行**：先给分数/等级/风险或假设排序，再给证据链。
2. **证据链**：每个扣分/假设必须能追溯到 ruleId、输入记录与接口编码；接口编码优先取 bundle.sourceMeta。
3. **置信度与缺口**：低置信度必须明示；`dataGaps`/`missingEvidence` 必须原样转述，不得隐藏或补齐。
4. **知识引用**：`knowledgeQueries` 只是检索建议；规程条款必须来自知识库返回的 `citations`，检索不到就如实说明。
5. **确定性**：同一 bundle 同一输入必得同一输出（报告 `generatedAt` 除外）；不要用系统时钟替代 `as-of`。
6. **敏感结论**：停电影响、检修/技改决策、低置信度根因需提示业务复核。

## 八、自测

```bash
# 在 expert-pack 目录下
python -m unittest discover -s tests -v
python skills/substation-analysis-mcp/scripts/analysis_cli.py demo
```

测试覆盖：评分规则/等级/置信度、诊断规则触发、模式聚类、指标、3 类报告渲染、MCP 协议与
`tools/list` 与 `spec/analysis-tools.json` 逐字段一致、CLI 退出码与确定性。

---

## 附录 A · 离线模拟数据（内网验证）

本目录是可独立安装/上传的拆分技能包。没有 PMS 中台时，`mock/samples.json` 提供本技能相关接口的
确定性模拟返回（字段与真实接口一致，数据虚构、仅用于演示），说明见 `mock/README.md`。

需要真实调用链时，配置 `pms-gateway-mcp`（本地模拟网关/stdio MCP 见
`standalone/mcp-servers/pms-gateway-mcp/README.md`）。模拟数据不得作为业务结论。
