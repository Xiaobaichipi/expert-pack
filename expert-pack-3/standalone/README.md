# standalone · 内网验证包（变电智能问数）

本目录把专家包 **拆成 12 个独立技能 + 2 个独立 MCP**，每个包都自带离线模拟数据，
可整目录拷贝到内网电脑（无需外网、无需真实 PMS 中台/凭证）验证效果。

> 所有模拟数据均为虚构，仅用于联调/演示，不得作为业务结论。

## 一、一分钟自检

```powershell
cd expert-pack-3
python standalone/verify_offline.py
```

期望：逐项 PASS（12 技能包 / 2 MCP / 26 接口样例 / 分析引擎 75.8 / MCP stdio 协议）。

## 二、12 个独立技能包

技能目录可直接复制到宿主技能目录，或上传 `dist-standalone/skills/<slug>.zip`。

| slug | 名称 | 类型 | 模拟样例 |
|---|---|---|---|
| pms-gateway-mcp | PMS 接口网关（变电问数底座） | mcp | `mock/samples.json`（26 条） |
| substation-analysis-mcp | 变电分析引擎（健康度/诊断/报告） | mcp | `mock/samples.json`（5 条） |
| substation-asset-ledger | 设备档案专家 | skill | `mock/samples.json`（4 条） |
| substation-device-tree | 设备导航专家 | skill | `mock/samples.json`（3 条） |
| substation-om-health | 运维健康专家 | skill | `mock/samples.json`（4 条） |
| substation-maintenance-test | 检修试验专家 | skill | `mock/samples.json`（6 条） |
| substation-reliability | 可靠性分析专家 | skill | `mock/samples.json`（4 条） |
| substation-resource-topology | 资源拓扑专家 | skill | `mock/samples.json`（7 条） |
| substation-health-assessment | 健康评估专家 | skill | `mock/samples.json`（5 条） |
| substation-diagnosis | 诊断专家 | skill | `mock/samples.json`（6 条） |
| substation-report | 报告专家 | skill | `mock/samples.json`（7 条） |
| substation-qa-orchestrator | 问数总控 | skill | `mock/samples.json`（7 条） |

每个技能目录结构：`SKILL.md`（含附录 A 离线数据说明）+ `references/` 等原始资源 + `mock/samples.json`。

## 三、2 个独立 MCP

| slug | 名称 | 传输 |
|---|---|---|
| pms-gateway-mcp | PMS 接口网关（变电问数底座） | stdio |
| substation-analysis-mcp | 变电分析引擎（健康度/诊断/报告） | stdio |

- 目录：`standalone/mcp-servers/<slug>/`（含 `README.md`、`run-stdio.ps1`、`requirements.txt`）
- 上传包：`dist-standalone/mcp/<slug>.zip`
- **pms-gateway-mcp**：默认 mock 模式；自带 `references/interfaces.json`，可脱离专家包运行；
  `scripts/pms_cli.py doctor` 应返回 26 个工具；`mock-server` 可本地起 token/appkey 鉴权网关。
- **substation-analysis-mcp**：自带评分卡/规则库/报告模板/演示数据包；
  `scripts/analysis_cli.py demo` 应输出健康分 75.8。
- 仅依赖 Python 3.9+ 标准库，无第三方包、无网络访问。

## 四、宿主 MCP 配置

```powershell
python standalone/mcp-config/make_mcp_config.py
```

生成 `standalone/mcp-config/mcp-config.generated.json`（绝对路径），合并到宿主的 MCP 配置文件即可；
模板见 `mcp-config.example.json`。

## 五、模拟数据说明

- 数据规模：4 站 / 9 设备 / 13 PSR / 47 树节点 / 6 缺陷 / 4 隐患 / 3 故障 / 3 检修计划 / 3 试验 /
  3 巡视 / 4 容量 / 3 可靠性 / 3 停电 / 3 智能装置 / 3 仪表 / 3 厂家；
- 主键一致：`AST-102-0001 ↔ PSR-220-0001 ↔ UTC-2020-000123 ↔ TOPO-220-0001`；
- PMS 侧：`skills/pms-gateway-mcp` 自带 `mock/samples.json`（26 接口）；
- 分析侧：`substation-analysis-mcp` 自带 `assets/demo_bundle.json` + `mock/samples.json`（实算结果）。

## 六、限制

1. 模拟数据不代表真实设备/业务；
2. 技能包上传到平台需平台支持（本目录只提供 zip 与目录）；
3. MCP 宿主需自行配置 stdio（见第四节）；
4. 真实 PMS 接入、真实签名规范仍需企业环境联调。
