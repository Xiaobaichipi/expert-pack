#!/usr/bin/env python3
"""生成带绝对路径的 MCP 配置（内网 Windows/Linux 通用）。

用法：python standalone/mcp-config/make_mcp_config.py
输出：同目录 mcp-config.generated.json
"""
from __future__ import annotations

import json
from pathlib import Path

STANDALONE = Path(__file__).resolve().parents[1]
MCP = STANDALONE / "mcp-servers"


def main() -> int:
    config = {
        "mcpServers": {
            "pms-gateway": {
                "command": "python",
                "args": [(MCP / "pms-gateway-mcp" / "scripts" / "mcp_server.py").as_posix()],
                "env": {"PMS_AUTH_MODE": "mock"},
            },
            "substation-analysis": {
                "command": "python",
                "args": [(MCP / "substation-analysis-mcp" / "scripts" / "analysis_mcp.py").as_posix()],
            },
        }
    }
    out = Path(__file__).resolve().parent / "mcp-config.generated.json"
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已生成：" + str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
