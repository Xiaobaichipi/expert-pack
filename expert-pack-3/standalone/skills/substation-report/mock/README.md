# 离线模拟数据 · substation-report

模拟数据，仅用于内网联调/演示；不得作为业务结论或真实数据使用。

## 文件说明

- `calls`：本技能最常用的 PMS 接口模拟返回（分页列表截断为前 2 条，total 保留）；
- 每个调用含 `tool`、`params`、`response`，可直接作为 Agent/脚本的模拟输入。

## 使用方式（内网无 PMS 中台时）

1. 按 `samples.json` 中 `tool`/`params` 理解该技能的入参；
2. 用 `response` 作为模拟返回走通技能流程（字段与真实接口一致）；
3. 需要真实调用链时，配置同级的 `pms-gateway-mcp` MCP 或本地模拟网关。

> 数据来源 `mock_gateway/data.py`（虚构，确定性）；完整数据/全部接口请运行模拟网关。
