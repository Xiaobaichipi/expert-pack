#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 mcp_server.py 做端到端协议自检：真的用管道拉起子进程，逐条收发 JSON-RPC。

只验证协议与错误路径，不发真实网络请求（凭据留空，缺凭据应回 isError）。

用法：python test_protocol.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "mcp_server.py")


def send(proc: subprocess.Popen, payload: dict) -> dict | None:
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    if "id" not in payload:
        return None
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("服务器没有响应就退出了")
    return json.loads(line)


def main() -> int:
    env = dict(os.environ)
    for key in ("SCT_SENDKEY", "WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET", "WECOM_ROBOT_URL"):
        env.pop(key, None)

    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  <- {detail}"))
        if not cond:
            failures.append(name)

    try:
        init = send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                                      "clientInfo": {"name": "selftest", "version": "0"}}})
        check("initialize 返回 serverInfo", init["result"]["serverInfo"]["name"] == "wechat-push", str(init))
        check("initialize 声明 tools 能力", "tools" in init["result"]["capabilities"], str(init))

        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        listed = send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in listed["result"]["tools"]]
        check("tools/list 返回 3 个工具",
              names == ["wechat_push", "wecom_app_send", "wecom_robot_push"], str(names))
        check("每个工具都有 inputSchema",
              all("inputSchema" in t for t in listed["result"]["tools"]), str(listed)[:200])

        # 缺凭据：必须回 isError 而不是崩掉
        for tool, args in (
            ("wechat_push", {"title": "t"}),
            ("wecom_app_send", {"to": "@all", "content": "hi"}),
            ("wecom_robot_push", {"content": "hi"}),
        ):
            resp = send(proc, {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                               "params": {"name": tool, "arguments": args}})
            result = resp["result"]
            check(f"{tool} 缺凭据回 isError",
                  result.get("isError") is True and "失败" in result["content"][0]["text"],
                  str(resp)[:200])

        ping = send(proc, {"jsonrpc": "2.0", "id": 11, "method": "ping"})
        check("ping 有 result", ping.get("result") == {}, str(ping))

        unknown = send(proc, {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
                              "params": {"name": "nope", "arguments": {}}})
        check("未知工具回 isError", unknown["result"].get("isError") is True, str(unknown)[:200])
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        proc.wait(timeout=10)

    if proc.returncode != 0:
        check("进程正常退出", False, f"returncode={proc.returncode} stderr={proc.stderr.read()[:500]}")
    else:
        print("PASS  进程正常退出")

    print()
    if failures:
        print(f"失败 {len(failures)} 项：{failures}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
