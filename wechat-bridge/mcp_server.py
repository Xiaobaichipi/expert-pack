#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小微信推送 MCP 服务器（零依赖，stdio 传输）。

给 DeepSeek Harness / Claude Code / Cursor 之类支持 MCP 的客户端提供三个工具：

  wechat_push       Server酱 Turbo —— 把消息推到个人微信（服务号）
  wecom_app_send    企业微信自建应用 —— 应用消息（成员在“微信插件”里可收到）
  wecom_robot_push  企业微信群机器人 webhook（群消息，微信插件可收到）

协议：MCP 的 JSON-RPC 2.0 over stdio，一行一条 JSON。
不依赖 mcp SDK / pydantic，只用标准库，方便在内网离线环境跑。

凭据来源（优先级：工具参数 > 环境变量）：
  SCT_SENDKEY        Server酱 SendKey（SCT 开头）
  WECOM_CORP_ID      企业 ID
  WECOM_AGENT_ID     自建应用 AgentId
  WECOM_SECRET       自建应用 Secret
  WECOM_ROBOT_URL    群机器人 webhook 地址（含 key 参数）

用法：
  python mcp_server.py            # stdio 模式，由 MCP 客户端拉起
  python mcp_server.py --selftest # 只做协议自检，不联网
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

TIMEOUT = 15
SERVER_NAME = "wechat-push"
SERVER_VERSION = "1.0.0"

TOOLS = [
    {
        "name": "wechat_push",
        "description": (
            "通过 Server酱 Turbo 把一条消息推送到个人微信（微信服务号通道）。"
            "适合发通知、告警、定时简报；单向推送，不能读微信消息。"
            "免费额度约每天 5 条。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "标题，建议 <= 32 字"},
                "desp": {
                    "type": "string",
                    "description": "正文，支持 Markdown",
                },
                "sendkey": {
                    "type": "string",
                    "description": "可选，覆盖环境变量 SCT_SENDKEY",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "wecom_app_send",
        "description": (
            "用企业微信自建应用发送应用消息给指定成员（userid，@all 表示全员）。"
            "成员关注“微信插件”后可在个人微信里收到。支持 text / markdown。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "成员 userid，多个用 | 分隔，@all 表示全员",
                },
                "content": {"type": "string", "description": "消息正文"},
                "msgtype": {
                    "type": "string",
                    "enum": ["text", "markdown"],
                    "description": "消息类型，默认 text",
                },
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "wecom_robot_push",
        "description": (
            "向企业微信群机器人 webhook 推送文本或 markdown（群消息推送，"
            "微信插件里也能收到）。只需要一个 webhook 地址，不需要 corpsecret。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "消息正文"},
                "msgtype": {
                    "type": "string",
                    "enum": ["text", "markdown"],
                    "description": "消息类型，默认 text",
                },
                "webhook": {
                    "type": "string",
                    "description": "可选，覆盖环境变量 WECOM_ROBOT_URL",
                },
            },
            "required": ["content"],
        },
    },
]


class ToolError(Exception):
    pass


def _post(url: str, payload: dict | None = None, form: dict | None = None) -> dict:
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ToolError(f"缺少 {name}：请写在工具参数或环境变量里")
    return value


def wechat_push(args: dict) -> dict:
    sendkey = _require(args.get("sendkey") or os.environ.get("SCT_SENDKEY"), "SCT_SENDKEY")
    url = f"https://sctapi.ftqq.com/{urllib.parse.quote(sendkey)}.send"
    result = _post(url, form={"title": args["title"], "desp": args.get("desp", "")})
    if result.get("code") not in (0, None) and result.get("data") is None:
        raise ToolError(f"Server酱返回失败：{result}")
    return {
        "ok": True,
        "channel": "serverchan",
        "pushid": (result.get("data") or {}).get("pushid"),
        "message": "已提交到 Server酱，微信端通常 1-2 秒内收到",
    }


def _wecom_token(corpid: str, secret: str) -> str:
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?" + urllib.parse.urlencode(
        {"corpid": corpid, "corpsecret": secret}
    )
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8", "replace"))
    if body.get("errcode") != 0:
        raise ToolError(f"获取 access_token 失败：{body.get('errcode')} {body.get('errmsg')}")
    return body["access_token"]


def wecom_app_send(args: dict) -> dict:
    corpid = _require(os.environ.get("WECOM_CORP_ID"), "WECOM_CORP_ID")
    secret = _require(os.environ.get("WECOM_SECRET"), "WECOM_SECRET")
    agentid = _require(os.environ.get("WECOM_AGENT_ID"), "WECOM_AGENT_ID")
    msgtype = args.get("msgtype") or "text"
    token = _wecom_token(corpid, secret)
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={urllib.parse.quote(token)}"
    if msgtype == "markdown":
        payload = {"touser": args["to"], "msgtype": "markdown", "agentid": agentid, "markdown": {"content": args["content"]}}
    else:
        payload = {"touser": args["to"], "msgtype": "text", "agentid": agentid, "text": {"content": args["content"]}}
    result = _post(url, payload=payload)
    if result.get("errcode") != 0:
        raise ToolError(f"应用消息发送失败：{result.get('errcode')} {result.get('errmsg')}")
    return {
        "ok": True,
        "channel": "wecom-app",
        "invaliduser": result.get("invaliduser", ""),
        "message": "已发送；成员在微信插件中可收到（需已关注插件并允许接收）",
    }


def wecom_robot_push(args: dict) -> dict:
    webhook = _require(args.get("webhook") or os.environ.get("WECOM_ROBOT_URL"), "WECOM_ROBOT_URL")
    msgtype = args.get("msgtype") or "text"
    if msgtype == "markdown":
        payload = {"msgtype": "markdown", "markdown": {"content": args["content"]}}
    else:
        payload = {"msgtype": "text", "text": {"content": args["content"]}}
    result = _post(webhook, payload=payload)
    if result.get("errcode") != 0:
        raise ToolError(f"群机器人推送失败：{result.get('errcode')} {result.get('errmsg')}")
    return {"ok": True, "channel": "wecom-robot", "message": "已推送到群机器人"}


HANDLERS = {
    "wechat_push": wechat_push,
    "wecom_app_send": wecom_app_send,
    "wecom_robot_push": wecom_robot_push,
}


def handle_call(name: str, args: dict) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ToolError(f"未知工具：{name}")
    return handler(args or {})


def build_response(req_id, result=None, error=None) -> dict:
    resp: dict = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def dispatch(msg: dict) -> dict | None:
    """处理一条 JSON-RPC 消息；通知类返回 None（不回包）。"""
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return build_response(
            req_id,
            {
                "protocolVersion": params.get("protocolVersion") or "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return build_response(req_id, {})
    if method == "tools/list":
        return build_response(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = handle_call(name, args)
        except ToolError as exc:
            return build_response(
                req_id,
                {"content": [{"type": "text", "text": f"失败：{exc}"}], "isError": True},
            )
        except Exception as exc:  # noqa: BLE001 - 网络/IO 错误统一回传给模型
            return build_response(
                req_id,
                {"content": [{"type": "text", "text": f"失败：{type(exc).__name__}: {exc}"}], "isError": True},
            )
        return build_response(
            req_id,
            {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]},
        )
    return build_response(req_id, error={"code": -32601, "message": f"Method not found: {method}"})


def serve() -> None:
    # Windows 控制台/管道默认可能是 GBK，JSON 里全是中文，必须切成 UTF-8。
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(build_response(None, error={"code": -32700, "message": "Parse error"})) + "\n")
            sys.stdout.flush()
            continue
        resp = dispatch(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def selftest() -> int:
    cases = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "wechat_push", "arguments": {"title": "t"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    for case in cases:
        resp = dispatch(case)
        if resp is None:
            print("notification -> no response (ok)")
            continue
        print(json.dumps(resp, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    serve()
