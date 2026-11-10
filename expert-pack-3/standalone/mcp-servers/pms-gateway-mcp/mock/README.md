# 离线模拟数据 · pms-gateway-mcp

模拟数据，仅用于内网联调/演示；不得作为业务结论或真实数据使用。

## 文件说明

- `calls`：26 个 PMS 接口各 1 条模拟返回（分页列表截断为前 2 条，total 保留）；
- 本地模拟网关：`python scripts/pms_cli.py mock-server --auth-mode token --port 18080`；
- 默认 mock 模式无需网关：`python scripts/pms_cli.py doctor` / `call`。

## 使用方式（内网无 PMS 中台时）

1. 按 `samples.json` 中 `tool`/`params` 理解该技能的入参；
2. 用 `response` 作为模拟返回走通技能流程（字段与真实接口一致）；
3. 需要真实调用链时，配置同级的 `pms-gateway-mcp` MCP 或本地模拟网关。

> 数据来源 `mock_gateway/data.py`（虚构，确定性）；完整数据/全部接口请运行模拟网关。
