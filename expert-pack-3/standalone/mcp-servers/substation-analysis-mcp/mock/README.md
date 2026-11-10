# 离线模拟数据 · substation-analysis-mcp

模拟数据，仅用于内网联调/演示；不得作为业务结论或真实数据使用。

## 文件说明

- `results`：用 `assets/demo_bundle.json` 实算的健康度/诊断/指标/模式/站级画像；
- `cliExamples`：离线可运行的 CLI 命令；
- `demoBundle`：演示数据包（1号主变，含严重缺陷/跳闸/不合格试验）。

## 使用方式（内网无 PMS 中台时）

1. 按 `samples.json` 中 `tool`/`params` 理解该技能的入参；
2. 用 `response` 作为模拟返回走通技能流程（字段与真实接口一致）；
3. 需要真实调用链时，配置同级的 `pms-gateway-mcp` MCP 或本地模拟网关。

> 数据来源 `mock_gateway/data.py`（虚构，确定性）；完整数据/全部接口请运行模拟网关。
