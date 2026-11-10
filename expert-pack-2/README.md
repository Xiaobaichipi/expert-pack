# 变电智能问数（bianya-intelligent-data-qa）

面向变电专业的**问数 + 深度分析专家包**：在设备台账、设备树导航、缺陷隐患故障、检修试验、可靠性、作业资源与图形拓扑的数据底座之上，新增**设备健康度评分、跨域证据链诊断、重复/家族缺陷识别、站级健康画像、报告自动生成**，并可结合知识库（WeKnora）引用规程条款，覆盖「设备是什么 — 怎么样 — 为什么 — 有多严重 — 该怎么办 — 怎么呈现」全链路。

- 交付形态：skillhub 专家包（1 个 meta-skill + **12 个子技能**），纯文本 + Python 标准库，单包 ≤ 10MB。
- 当前版本：**`1.1.0`**（`identify.md` frontmatter）。
- 三层 MCP 协同：**数据 MCP**（`pms-gateway-mcp`，26 工具）+ **分析 MCP**（`substation-analysis-mcp`，7 工具）+ **知识库 MCP**（WeKnora，平台已配置）。
- 当前状态：**接口规格为推断值、鉴权待申请、默认 Mock**；评分卡/规则库为初始值、**需业务校准**。详见下文「当前状态」。

## 一、12 个技能

12 技能 = **2 个底座** + **6 个业务** + **3 个深能力** + **1 个总控**。

| # | 技能名（slug） | 类别 | 角色 | 工具数 | 核心能力 |
|---|---|---|---|---|---|
| 1 | `pms-gateway-mcp` | 底座 | 接口网关工程师 | 26 | 26 个 PMS 接口的 MCP / CLI 调用、鉴权、分页、错误归一、Mock |
| 2 | `substation-analysis-mcp` | 底座 | 分析引擎工程师 | 7 | 确定性计算：健康评分、站级画像、诊断规则、缺陷聚类、派生指标、报告渲染 |
| 3 | `substation-asset-ledger` | 业务 | 设备档案专家 | 5 | 资产/资源/实物 ID 三类主键的台账查询与互认 |
| 4 | `substation-device-tree` | 业务 | 设备导航专家 | 2 | 设备树逐层下钻，定位到具体设备 |
| 5 | `substation-om-health` | 业务 | 运维健康专家 | 4 | 缺陷、隐患、故障记录查询与基础判断 |
| 6 | `substation-maintenance-test` | 业务 | 检修试验专家 | 6 | 检修计划/方案、修试记录、巡视计划/记录、试验项目 |
| 7 | `substation-reliability` | 业务 | 可靠性分析专家 | 3 | 可靠率、停电事件、可开放容量与负载裕度 |
| 8 | `substation-resource-topology` | 业务 | 资源拓扑专家 | 6 | 智能装备、仪器仪表、厂家、专题图、电源点、供电范围 |
| 9 | `substation-health-assessment` | 深能力 | 健康评估专家 | 3（分析） | 组装 bundle、调用评分卡、解读扣分证据与置信度、站级画像、派生指标 |
| 10 | `substation-diagnosis` | 深能力 | 诊断专家 | 2（分析） | 跨域证据链、根因假设排序、重复/家族缺陷识别 |
| 11 | `substation-report` | 深能力 | 报告专家 | 2（分析） | 设备画像 / 站级月报 / 故障复盘报告生成与知识引用 |
| 12 | `substation-qa-orchestrator` | 总控 | 问数总控 | 0（经技能间接调用） | 意图路由、设备主键归一、跨域组合、结果组织 |

接口 ↔ 技能 ↔ 角色逐条对应见 [docs/01-接口映射表](docs/01-接口映射表.md)（26 个数据接口 + 7 个分析工具两张表）。

## 二、目录结构

```
专家包/
├─ 变电智能问数_26接口功能说明.docx      # 原始接口说明（输入资料）
├─ expert-pack/                           # 交付主体
│  ├─ manifest.json                       # 平台 SkillSet 清单（slug/12 技能列表/manifestVersion/type）
│  ├─ identify.md                         # 专家包编排提示词（v1.1.0，12 技能工作流）
│  ├─ README.md                           # 本文件
│  ├─ spec/
│  │  ├─ interfaces.json                  # 26 个 PMS 数据接口契约（工具/参数/Mock）
│  │  ├─ analysis-tools.json              # 7 个分析工具契约（工具/参数/返回/设计规则）
│  │  └─ analysis-bundle.schema.json      # 分析输入数据包（bundle）字段契约
│  ├─ skills/
│  │  ├─ pms-gateway-mcp/                 # 数据底座
│  │  │  ├─ SKILL.md
│  │  │  ├─ references/                   # 接口目录、鉴权说明
│  │  │  └─ scripts/
│  │  │     ├─ mcp_server.py              # stdio MCP Server（26 工具）
│  │  │     ├─ pms_cli.py                 # CLI（list-tools/describe/call/serve/doctor）
│  │  │     └─ pms_client/                # config/auth/errors/transport/spec/client/mock
│  │  ├─ substation-analysis-mcp/         # 分析底座
│  │  │  ├─ SKILL.md
│  │  │  ├─ references/                   # tools / bundle-schema / scorecard / diagnosis-rules / report-templates
│  │  │  ├─ scripts/
│  │  │  │  ├─ analysis_mcp.py            # stdio MCP Server（7 工具）
│  │  │  │  ├─ analysis_cli.py            # CLI（health/station-health/diagnose/patterns/metrics/report/demo）
│  │  │  │  └─ analysis/                  # config/evidence/metrics/health/diagnosis/patterns/report
│  │  │  ├─ config/scorecard.json         # 评分卡（权重/阈值，可校准）
│  │  │  ├─ config/diagnosis_rules.json   # 诊断规则库（可扩展）
│  │  │  ├─ templates/                    # device_profile / station_monthly / fault_review
│  │  │  └─ assets/demo_bundle.json       # 演示数据包（零依赖 demo）
│  │  ├─ substation-asset-ledger/         # 业务技能：SKILL.md + references/queries.md
│  │  ├─ substation-device-tree/
│  │  ├─ substation-om-health/
│  │  ├─ substation-maintenance-test/
│  │  ├─ substation-reliability/
│  │  ├─ substation-resource-topology/
│  │  ├─ substation-health-assessment/    # 深能力技能
│  │  ├─ substation-diagnosis/
│  │  ├─ substation-report/
│  │  └─ substation-qa-orchestrator/      # 总控
│  ├─ docs/
│  │  ├─ 01-接口映射表.md                  # 26 数据接口表 + 7 分析工具表
│  │  ├─ 02-鉴权接入指南.md
│  │  ├─ 03-部署与使用说明.md              # 12 技能发布、三个 MCP 配置、端到端命令
│  │  ├─ 04-开发与扩展指南.md
│  │  ├─ 05-架构设计.md                    # 含 L0 知识层 / L2.5 分析层、D8–D10
│  │  └─ 06-深能力与知识库集成.md           # 能力地图、数据流、腾睿work 注册、合规边界
│  ├─ tools/
│  │  └─ build_pack.py                    # 校验 + 打包（幂等，stdlib，12 技能动态校验）
│  ├─ tests/                              # unittest（数据底座 + 分析引擎）
│  └─ dist/                               # 构建产物（由 build_pack.py 生成，不入库）
└─ work/ research/                        # 过程资料与平台 CLI 参考（非交付物）
```

## 三、快速开始

### 第 0 步：构建与校验

```powershell
python expert-pack/tools/build_pack.py --validate-only   # 只校验（12 技能 + 两份契约）
python expert-pack/tools/build_pack.py                   # 校验 + 打包到 expert-pack/dist
```

任一校验失败会以非 0 退出并打印中文原因（缺哪些技能、缺哪个契约文件会逐条列出）。

### 第 1 步：零依赖验证分析引擎（无需凭证/接口/知识库）

```powershell
python expert-pack/skills/substation-analysis-mcp/scripts/analysis_cli.py demo
```

期望输出：1号主变的健康分与等级、五维得分与扣分证据（含规则 ID、接口来源编码）、诊断假设 TopN、Markdown 报告摘要；连续执行两次结果一致。

### 第 2 步：Mock 模式跑通数据链路

```powershell
# 默认即 mock；如之前设置过真实模式，先改回
$env:PMS_AUTH_MODE = "mock"

python expert-pack/skills/pms-gateway-mcp/scripts/pms_cli.py doctor
python expert-pack/skills/pms-gateway-mcp/scripts/pms_cli.py list-tools
python expert-pack/skills/pms-gateway-mcp/scripts/pms_cli.py call get_asset_by_id --params '{"assetId":"AST-102-0001"}'
```

`doctor` 应显示 `ok: true`、`authMode: "mock"`、26 个工具、spec 可定位；调用返回内置样例（如 `1号主变`）。Mock 数据仅用于联调演示。

> 二期（`expert-pack-2`）新增本地可鉴权模拟网关：真实 HTTP + token/appkey 鉴权，无需真实凭证即可验证完整链路：

```powershell
# 终端 A：启动网关（token 模式，默认 127.0.0.1:18080）
python expert-pack-2/skills/pms-gateway-mcp/scripts/pms_cli.py mock-server --auth-mode token

# 终端 B：客户端指向本地网关
$env:PMS_GATEWAY_BASE_URL = "http://127.0.0.1:18080"
$env:PMS_AUTH_MODE = "token"
$env:PMS_TOKEN = "mock-token-001"
python expert-pack-2/skills/pms-gateway-mcp/scripts/pms_cli.py doctor
```

详见 [docs/09-模拟网关与鉴权](docs/09-模拟网关与鉴权.md)。

> 想看「模拟数据 + 业务问题 + 分析结论」的完整示例（12 个问题、26 个接口样例）：

```powershell
python expert-pack-2/tools/mock_qa_demo.py            # 12 个问题：取数 → 健康分/诊断/模式/站级画像/报告
python expert-pack-2/tools/mock_qa_demo.py --samples  # 26 个接口的模拟数据样例
```

数据规模、逐接口样例、问题清单与分析结果见 [docs/10-模拟数据与问数分析示例](docs/10-模拟数据与问数分析示例.md)。

### 第 3 步：组装 bundle → 健康分 → 诊断 → 报告

```powershell
$cli = "python expert-pack/skills/substation-analysis-mcp/scripts/analysis_cli.py"

# 把第 2 步的取数结果按 spec/analysis-bundle.schema.json 组装为 bundle.json（device 必填）
& $cli health   --bundle .\bundle.json
& $cli diagnose --bundle .\bundle.json
& $cli report   --type device_profile --bundle .\bundle.json
```

完整示例（bundle 示意、故障复盘、知识引用）见 [docs/06-深能力与知识库集成](docs/06-深能力与知识库集成.md) 第四节。

### 第 4 步：挂到 MCP 宿主（含内网腾睿work / AgentScope）

数据底座与分析底座都是 stdio MCP，配置结构一致（完整示例见 [docs/03-部署与使用说明](docs/03-部署与使用说明.md) 第五节）：

```json
{
  "mcpServers": {
    "pms-gateway-mcp": {
      "command": "python",
      "args": ["F:/work/2026年/10月/专家包/expert-pack/skills/pms-gateway-mcp/scripts/mcp_server.py"],
      "env": {"PMS_AUTH_MODE": "mock"}
    },
    "substation-analysis-mcp": {
      "command": "python",
      "args": ["F:/work/2026年/10月/专家包/expert-pack/skills/substation-analysis-mcp/scripts/analysis_mcp.py"],
      "env": {"PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

- 数据底座发布 zip 已内置 spec 快照（`references/interfaces.json`），单独安装后**无需配置 `PMS_SPEC_PATH`**。
- 分析底座发布 zip 已内置评分卡、规则库、3 个报告模板与 demo 数据包，**无需任何环境变量**（纯本地计算，不访问网络/凭证）。
- 知识库 MCP（WeKnora）由平台侧配置，本包只消费其检索能力；**工具名以平台实际配置为准**，不写死。

### 第 5 步：填写凭证，切换真实接口

1. 按 [docs/02-鉴权接入指南](docs/02-鉴权接入指南.md) 完成服务目录检索 → 申请 → 测试环境联调；
2. 配置 `PMS_GATEWAY_BASE_URL`、`PMS_AUTH_MODE` 与凭证（`PMS_TOKEN` 或 `PMS_APP_KEY`/`PMS_APP_SECRET`）；
3. appkey 模式：签名已按「模拟规范」实现（`pms_client/signing.py`，HMAC-SHA256 + ±300s 时间窗）；拿到官方《接口说明文档》后只需替换该实现；
4. 跑 `doctor` → 单接口 → 26 接口抽样 → 02 第六节验收清单；
5. 分析侧分数与建议需业务校准：调 `config/scorecard.json` 与 `config/diagnosis_rules.json`，不改代码（见 [docs/04](docs/04-开发与扩展指南.md) 第八节）。

## 四、构建产物

`python expert-pack/tools/build_pack.py` 生成 `expert-pack/dist/`：

| 产物 | 内容 | 用途 |
|---|---|---|
| `skills/<slug>.zip` × 12 | zip 根即技能根（`SKILL.md` 在根）；`pms-gateway-mcp` 额外内置 spec 快照 `references/interfaces.json`；`substation-analysis-mcp` 内置 `config/scorecard.json`、`config/diagnosis_rules.json`、`templates/*.md`（3 个）、`assets/demo_bundle.json` | 单个技能发布/离线安装；两个底座均装完即用 |
| `bianya-intelligent-data-qa-bundle.zip` | 构建生成的 `manifest.json` + `identify.md`（`skills[]`/`files[]` 由构建脚本从各 `SKILL.md` 与 identify.md 字节生成；**不含**子技能 zip） | 平台专家包清单包，与 skillhub.cn 实际下载物一致；归档/交付 |
| `checksums.txt` | `sha256  相对路径` | 交付校验，支持逐版本比对 |

构建特征：幂等、确定性（zip 时间戳固定，重复构建 checksums 不变）、每个 zip 均校验 `< 10MB`、排除 `__pycache__`/`*.pyc`/`.DS_Store`/`Thumbs.db`/`dist`。校验范围：PMS 契约（26 工具）、分析契约（7 工具、name 唯一、参数 required 合法）、bundle schema 结构、平台清单字段与技能数（**从 manifest 动态读取**）、顺序契约（前两项为两个底座、末项为总控）、技能 frontmatter（`slug`/`displayName`/`version`，与 `skillhub publish` 校验一致）、分析资产完备性（分析底座必含、其余技能不得含）、清单包结构（仅 `manifest.json` + `identify.md`，`files[]` 的 sha256/size 与 identify.md 字节一致）。

## 五、当前状态

| 项目 | 状态 | 说明 |
|---|---|---|
| 接口规格 | **推断值**（`spec.status = inferred`） | 地址/参数/返回字段为依据原始说明文档与命名惯例推断的占位规格；正式文档下发后只改 `spec/interfaces.json`，见 [docs/04](docs/04-开发与扩展指南.md) |
| 鉴权 | **凭证待申请 / 签名已就绪（模拟规范）** | 尚未取得中台凭证；appKey 签名已实现于 `pms_client/signing.py`；默认 Mock 可用，本地可鉴权网关见 [docs/09](docs/09-模拟网关与鉴权.md) |
| 深能力（P0） | **已实现** | 健康评分、站级画像、跨域证据链诊断、重复/家族缺陷识别、派生指标、三类报告（`device_profile`/`station_monthly`/`fault_review`） |
| 预测/趋势 | **延后** | 历史数据仅约 2 年，样本不足以支撑可靠趋势；`trend` 返回 `null` 并写入 `dataGaps`，不用推测值填充 |
| 评分卡/规则库 | **待业务校准** | 维度权重（缺陷 0.30/故障 0.25/修试 0.20/负载 0.15/台账 0.10）、扣分阈值、诊断规则为初始值，需用真实样本回溯校准并留档 |
| 知识库 | **已就绪（平台侧）** | WeKnora 已建好并通过 MCP 调通；本包只消费检索能力，工具名以腾睿work 实际配置为准（见 [docs/06](docs/06-深能力与知识库集成.md) 3.5 节） |
| 测试 | unittest（stdlib） | 在 `expert-pack` 目录执行 `python -m unittest discover -s tests -v` |
| 平台发布 | 待执行 | 12 个子技能按顺序 `skillhub publish`，再创建专家包，见 [docs/03](docs/03-部署与使用说明.md) 第二节 |
| 版本 | 1.1.0 | 版本策略见 [docs/04](docs/04-开发与扩展指南.md) 第八节 |

## 六、文档索引

| 文档 | 内容 |
|---|---|
| [docs/01-接口映射表.md](docs/01-接口映射表.md) | 26 个数据接口 × 工具名 × 编码 × 中心/能力域 × 技能/角色 × 典型问数；7 个分析工具 × 技能 × 角色 × 用途 |
| [docs/02-鉴权接入指南.md](docs/02-鉴权接入指南.md) | 申请流程、环境变量、四种鉴权模式、AppKey 签名规范（模拟实现 + 真实规范替换步骤）、联调验收、QPS/脱敏 |
| [docs/03-部署与使用说明.md](docs/03-部署与使用说明.md) | 12 技能发布顺序、专家包创建/上传/安装、三个 MCP 配置（含腾睿work）、CLI、Mock 验证、端到端 demo、常见问题 |
| [docs/04-开发与扩展指南.md](docs/04-开发与扩展指南.md) | 三份契约事实源、接口修订、新增工具/技能、分析工具扩展流程、bundle schema 演进规则、构建/测试/版本管理 |
| [docs/05-架构设计.md](docs/05-架构设计.md) | 分层架构（L0 知识层 / L2.5 分析层）、关键决策 D1–D10、效率收益、演进触发条件、反模式 |
| [docs/06-深能力与知识库集成.md](docs/06-深能力与知识库集成.md) | 能力地图、数据流、三个 MCP 注册、知识库工具名映射占位、端到端示例、引用合规边界、已知限制 |
| [docs/09-模拟网关与鉴权.md](docs/09-模拟网关与鉴权.md) | 二期模拟网关：架构、三种启动方式（CLI/进程内/MCP）、环境变量、签名规范（可复算样例）、26 接口模拟数据说明、自测结果、限制 |
| [docs/10-模拟数据与问数分析示例.md](docs/10-模拟数据与问数分析示例.md) | 模拟数据规模、26 接口样例、12 个业务问题（问句→接口→数据→分析）、bundle 字段映射、复现命令、限制 |
| `skills/*/SKILL.md` | 各技能角色定位、工具清单、调用流程与输出格式 |
| `skills/*/references/` | 典型问数模板、字段口径、评分卡/诊断规则/报告模板说明、知识库集成说明 |

## 七、免责与数据安全

- **数据来源**：本包不含任何真实业务数据与真实凭证。Mock 模式返回的站名、设备名、编号、缺陷与试验数据均为**虚构样例**，仅用于功能联调与演示。
- **接口边界**：所列 26 个接口为电网资源业务中台服务目录标准接口，实际调用需按平台规范**申请鉴权后经中台网关接入**；接口地址在本包中为相对路径占位。
- **分析结论边界**：健康分、诊断假设、处置建议来自**可校准的评分卡与规则库**，属辅助判断，不替代专业结论；低置信度结果不得作为唯一依据，须提示业务复核。
- **知识引用边界**：规程/标准条款只能来自知识库真实返回内容，必须标注来源；检索不到即如实说明，**禁止编造条款号、标准编号或条文**；知识库内容不参与任何数值计算。
- **无鉴权不可用真实数据**：在未取得凭证与数据授权前，不得将 Mock 结果作为业务结论使用；真实环境调用须遵守中台频控（QPS）与数据安全要求。
- **脱敏与最小权限**：对外输出对手机号、身份证号、详细地址、用户姓名等敏感字段脱敏；按岗位最小权限申请数据范围；不落盘、不外传敏感明细。
- **结论复核**：涉及停电影响、可靠性指标、检修决策、责任认定等敏感结果时，回答会标注数据来源与局限，**需业务人员复核**后方可用于生产决策。
- **责任限制**：本包为辅助问数与分析工具，不替代调度、运检等专业系统与人工判断；因接口规格推断值、Mock 数据、初始评分卡未校准或使用不当造成的后果，由使用者自行评估承担。
