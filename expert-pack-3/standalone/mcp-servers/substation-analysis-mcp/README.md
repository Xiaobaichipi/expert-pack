# substation-analysis-mcp（独立 MCP 包）

变电分析引擎 MCP：7 个工具（健康度/站级画像/诊断/缺陷模式/派生指标/报告模板/报告渲染），纯 Python、无网络依赖。

## 运行方式

```powershell
$here = (Resolve-Path .).Path

# 1) 一条命令跑通全部分析（自带演示数据包）
python "$here\scripts\analysis_cli.py" demo

# 2) 单设备健康分 / 诊断 / 报告
python "$here\scripts\analysis_cli.py" health   --bundle "$here\assets\demo_bundle.json"
python "$here\scripts\analysis_cli.py" diagnose --bundle "$here\assets\demo_bundle.json"
python "$here\scripts\analysis_cli.py" report   --type device_profile --bundle "$here\assets\demo_bundle.json"

# 3) stdio MCP（宿主挂载）
python "$here\scripts\analysis_mcp.py"
```

## 宿主 MCP 配置（stdio）

```json
{{
  "mcpServers": {{
    "substation-analysis": {{
      "command": "python",
      "args": ["<本目录绝对路径>/scripts/analysis_mcp.py"]
    }}
  }}
}}
```

## 离线数据

- `assets/demo_bundle.json`：演示数据包（1号主变，含严重缺陷/跳闸/不合格试验，预期健康分 75.8 / C）；
- `mock/samples.json`：引擎实算的健康分、诊断、指标、模式、站级画像结果；
- `config/` + `templates/`：评分卡、诊断规则库、报告模板，随包自带。
