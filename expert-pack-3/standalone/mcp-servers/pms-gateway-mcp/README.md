# pms-gateway-mcp（独立 MCP 包）

PMS 接口网关 MCP：26 个工具，默认 mock 模式（无需真实中台/凭证）；也可启动本地可鉴权模拟网关（token/appkey）。

## 运行方式

```powershell
$here = (Resolve-Path .).Path

# 1) 自检（无需网络）
python "$here\scripts\pms_cli.py" doctor

# 2) 单次 mock 调用
python "$here\scripts\pms_cli.py" call get_asset_by_id --params '{{"assetId":"AST-102-0001"}}'

# 3) 本地可鉴权网关（HTTP，token；Ctrl+C 退出）
python "$here\scripts\pms_cli.py" mock-server --auth-mode token --host 127.0.0.1 --port 18080

# 4) stdio MCP（宿主挂载）
python "$here\scripts\mcp_server.py"
```

## 宿主 MCP 配置（stdio）

```json
{{
  "mcpServers": {{
    "pms-gateway": {{
      "command": "python",
      "args": ["<本目录绝对路径>/scripts/mcp_server.py"],
      "env": {{"PMS_AUTH_MODE": "mock"}}
    }}
  }}
}}
```

也可直接运行 `mcp-config/make_mcp_config.py` 生成绝对路径配置。

## 离线数据

- 自带 `references/interfaces.json`（spec 快照，脱离专家包根目录也能解析）；
- `mock/samples.json`：26 个接口的模拟返回（数据虚构）；
- 默认常量：token=`mock-token-001`、app_key=`mock-app-key`、secret=`mock-app-secret`；
- 仅标准库（Python 3.9+），不依赖外网。
